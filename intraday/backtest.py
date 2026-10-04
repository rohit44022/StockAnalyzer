"""
Intraday backtest: simulates the auto-trader on historical daily OHLCV.

For each trading day from 2020-01 to present:
  1. Run Brooks engine on trailing 60+ daily bars
  2. If signal, simulate intraday trade using today's OHLC
  3. Compute Dhan charges on every trade
  4. Track cumulative equity, drawdown, win rate

Usage:
  .venv/bin/python -m intraday.backtest
  .venv/bin/python -m intraday.backtest --start 2022-01-01 --capital 200000
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from brooks.engine import run_brooks_analysis, MIN_BARS
from bb_squeeze.trade_calculator import calculate_trade
from intraday.scanner import INTRADAY_ATR_STOP_MULT, MIN_STOP_PCT, MAX_STOP_PCT, MIN_RR
from intraday.trader import MIN_CONFIDENCE, ALLOWED_SETUPS, PARTIAL_EXIT_PCT
from intraday.datastore import load_5min

STOCK_DIR = os.path.join(_ROOT, "stock_csv")

_NIFTY50_FALLBACK = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS",
    "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "LT.NS", "KOTAKBANK.NS",
    "HINDUNILVR.NS", "BAJFINANCE.NS", "AXISBANK.NS", "MARUTI.NS",
    "SUNPHARMA.NS", "TITAN.NS", "WIPRO.NS", "ULTRACEMCO.NS",
    "TATAMOTORS.NS", "ADANIENT.NS",
]

from intraday.trader import MAX_POSITIONS  # keep in sync with live trader
MAX_DAILY_LOSS_PCT = 2.0       # circuit breaker (like live trader)
LOOKBACK = 80                  # bars fed to engine (>= MIN_BARS=60)

# --- Slippage model (NSE large-cap realistic) ---
# Market order entry at Open: adverse 3 bps (you never get exact Open)
ENTRY_SLIPPAGE_BPS = 3.0
# SL-M stop exit: adverse 5 bps beyond stop (volatile moments slip more)
STOP_SLIPPAGE_BPS = 5.0
# Hard exit market order at Close: adverse 3 bps
HARD_EXIT_SLIPPAGE_BPS = 3.0
# Target: limit order fills at target price, no slippage
TARGET_SLIPPAGE_BPS = 0.0

# --- Partial exit + trailing stop ---
TRAIL_STOP_MULT = 0.5     # unused when PARTIAL_EXIT_PCT=0


@dataclass
class SimTrade:
    date: str
    ticker: str
    direction: str
    setup_type: str
    confidence: int
    entry_price: float
    stop_loss: float
    target: float
    exit_price: float
    exit_reason: str
    quantity: int
    gross_pnl: float
    charges: float          # total charges (float) or full breakdown (dict)
    net_pnl: float
    stop_pct: float = 0.0
    risk_reward: float = 0.0
    always_in: str = ""
    trend_phase: str = ""
    partial_exit_price: float = 0.0
    trail_exit_price: float = 0.0
    trail_exit_reason: str = ""
    trail_best_price: float = 0.0


def _load_daily(ticker: str) -> pd.DataFrame:
    path = os.path.join(STOCK_DIR, f"{ticker}.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path, parse_dates=["Date"])
    df.set_index("Date", inplace=True)
    df.sort_index(inplace=True)
    for c in ["Open", "High", "Low", "Close", "Volume"]:
        if c not in df.columns:
            return pd.DataFrame()
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    return df


def _calc_intraday_stop(signal: str, entry: float, df_trailing: pd.DataFrame) -> float:
    """ATR-based stop using recent daily bars, scaled for intraday."""
    h = df_trailing["High"].values[-14:]
    l = df_trailing["Low"].values[-14:]
    c = df_trailing["Close"].values[-14:]
    n = len(c)
    if n < 2:
        return entry * (0.985 if signal == "BUY" else 1.015)
    tr = np.zeros(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    # Daily ATR → approximate 5-min ATR (daily ~ 8-10x 5-min)
    daily_atr = float(np.mean(tr))
    intraday_atr = daily_atr / 9.0
    stop_dist = intraday_atr * INTRADAY_ATR_STOP_MULT
    min_dist = entry * MIN_STOP_PCT / 100
    max_dist = entry * MAX_STOP_PCT / 100
    stop_dist = max(stop_dist, min_dist)
    stop_dist = min(stop_dist, max_dist)

    if signal == "BUY":
        return round(entry - stop_dist, 2)
    return round(entry + stop_dist, 2)


def _apply_slippage(price: float, direction_adverse: str, bps: float) -> float:
    """Slip price adversely. direction_adverse='up' means buyer pays more."""
    slip = price * bps / 10000
    if direction_adverse == "up":
        return round(price + slip, 2)
    return round(price - slip, 2)


def _slipped_entry(entry: float, direction: str) -> float:
    """Market order at Open slips adversely."""
    if direction == "LONG":
        return _apply_slippage(entry, "up", ENTRY_SLIPPAGE_BPS)
    return _apply_slippage(entry, "down", ENTRY_SLIPPAGE_BPS)


def _slipped_stop(stop: float, direction: str) -> float:
    if direction == "LONG":
        return _apply_slippage(stop, "down", STOP_SLIPPAGE_BPS)
    return _apply_slippage(stop, "up", STOP_SLIPPAGE_BPS)


def _slipped_hard_exit(close: float, direction: str) -> float:
    if direction == "LONG":
        return _apply_slippage(close, "down", HARD_EXIT_SLIPPAGE_BPS)
    return _apply_slippage(close, "up", HARD_EXIT_SLIPPAGE_BPS)


def _ohlc_path_order(o, h, l, c) -> str:
    """Determine likely intraday price path from daily OHLC.

    Standard quant heuristic (Amibroker, TradeStation):
      Bullish candle (C >= O) → price went O→L→H→C (dipped then rallied)
      Bearish candle (C < O)  → price went O→H→L→C (rallied then dropped)

    Returns 'low_first' or 'high_first'.
    """
    if c >= o:
        return "low_first"
    return "high_first"


def _trail_info(target, trail_exit, trail_reason, trail_best):
    return {
        "partial_exit_price": target,
        "trail_exit_price": trail_exit,
        "trail_exit_reason": trail_reason,
        "trail_best": trail_best,
    }


def _simulate_day_trade(
    row_today: pd.Series, entry: float, stop: float, target: float,
    direction: str,
) -> tuple:
    """Simulate intraday trade using today's OHLC with OHLC path ordering + slippage.

    Returns (exit_price, exit_reason, trail_info_or_None).
    When target is hit, trail_info carries partial exit + conservative trail
    (trail portion exits at close since daily OHLC can't reveal post-target path).
    """
    o, h, l, c = row_today["Open"], row_today["High"], row_today["Low"], row_today["Close"]
    path = _ohlc_path_order(o, h, l, c)
    trail_dist = abs(entry - stop) * TRAIL_STOP_MULT

    if direction == "LONG":
        stop_hit = l <= stop
        target_hit = h >= target

        if stop_hit and target_hit:
            if path == "low_first":
                return _slipped_stop(stop, direction), "STOP_HIT", None
            else:
                ts = max(entry, h - trail_dist)
                te = _slipped_stop(ts, direction) if c <= ts else _slipped_hard_exit(c, direction)
                tr = "TRAIL_STOP" if c <= ts else "HARD_EXIT"
                return target, "TARGET_HIT", _trail_info(target, te, tr, float(h))
        if stop_hit:
            return _slipped_stop(stop, direction), "STOP_HIT", None
        if target_hit:
            ts = max(entry, h - trail_dist)
            te = _slipped_stop(ts, direction) if c <= ts else _slipped_hard_exit(c, direction)
            tr = "TRAIL_STOP" if c <= ts else "HARD_EXIT"
            return target, "TARGET_HIT", _trail_info(target, te, tr, float(h))
        return _slipped_hard_exit(c, direction), "HARD_EXIT", None
    else:  # SHORT
        stop_hit = h >= stop
        target_hit = l <= target

        if stop_hit and target_hit:
            if path == "high_first":
                return _slipped_stop(stop, direction), "STOP_HIT", None
            else:
                ts = min(entry, l + trail_dist)
                te = _slipped_stop(ts, direction) if c >= ts else _slipped_hard_exit(c, direction)
                tr = "TRAIL_STOP" if c >= ts else "HARD_EXIT"
                return target, "TARGET_HIT", _trail_info(target, te, tr, float(l))
        if stop_hit:
            return _slipped_stop(stop, direction), "STOP_HIT", None
        if target_hit:
            ts = min(entry, l + trail_dist)
            te = _slipped_stop(ts, direction) if c >= ts else _slipped_hard_exit(c, direction)
            tr = "TRAIL_STOP" if c >= ts else "HARD_EXIT"
            return target, "TARGET_HIT", _trail_info(target, te, tr, float(l))
        return _slipped_hard_exit(c, direction), "HARD_EXIT", None


STALE_BARS = 18  # 1.5 hours with no new favorable extreme → exit if in profit

def _simulate_5min_trade(
    bars_5min: pd.DataFrame, entry: float, stop: float, target: float,
    direction: str,
) -> tuple:
    """Walk real 5-min bars with stale-trade exit.

    If trade makes no new favorable extreme for STALE_BARS (1.5hr)
    and is currently in profit, exit — the trend lost momentum.
    Returns (exit_price, exit_reason, trail_info_or_None).
    """
    from datetime import time as t_time
    hard_exit_time = t_time(15, 15)  # IST or UTC depending on data source

    best_fav = 0.0
    last_new_extreme_bar = 0

    for i, (ts, bar) in enumerate(bars_5min.iterrows()):
        bar_time = ts.time() if hasattr(ts, 'time') else None
        h, l, c = float(bar["High"]), float(bar["Low"]), float(bar["Close"])

        # Track favorable movement
        fav = (h - entry) if direction == "LONG" else (entry - l)
        if fav > best_fav:
            best_fav = fav
            last_new_extreme_bar = i

        if bar_time and bar_time >= hard_exit_time:
            return _slipped_hard_exit(c, direction), "HARD_EXIT", None

        if direction == "LONG":
            if l <= stop:
                return _slipped_stop(stop, direction), "STOP_HIT", None
            if h >= target:
                return target, "TARGET_HIT", None
        else:
            if h >= stop:
                return _slipped_stop(stop, direction), "STOP_HIT", None
            if l <= target:
                return target, "TARGET_HIT", None

        # Stale trade: no new extreme for 1.5hr and currently in profit
        current_pnl = (c - entry) if direction == "LONG" else (entry - c)
        if (i - last_new_extreme_bar) >= STALE_BARS and i >= STALE_BARS and current_pnl > 0:
            return c, "STALE_EXIT", None

    last_close = float(bars_5min["Close"].iloc[-1])
    return _slipped_hard_exit(last_close, direction), "HARD_EXIT", None


def run_backtest(
    watchlist: List[str] = None,
    start_date: str = "2020-01-01",
    end_date: str = None,
    capital: float = 100_000,
) -> Dict:
    if watchlist is None:
        from intraday.trader import _fetch_nifty500
        watchlist = _fetch_nifty500()
        if not watchlist:
            watchlist = _NIFTY50_FALLBACK
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date) if end_date else pd.Timestamp.now()

    # Load all data upfront
    all_data = {}
    for ticker in watchlist:
        df = _load_daily(ticker)
        if len(df) > LOOKBACK:
            all_data[ticker] = df
    print(f"Loaded {len(all_data)} stocks with sufficient history")

    # Get union of all trading dates
    # Preload 5-min data once per ticker (avoid re-reading CSV per trade)
    fivemin_cache: Dict[str, pd.DataFrame] = {}
    for ticker in all_data:
        df_5m = load_5min(ticker)
        if not df_5m.empty:
            fivemin_cache[ticker] = df_5m

    if fivemin_cache:
        min5_dates = set()
        for df_5m in fivemin_cache.values():
            min5_dates.update(str(d) for d in set(df_5m.index.date))
        print(f"  5-min data loaded for {len(fivemin_cache)} tickers, {len(min5_dates)} unique dates")

    all_dates = sorted(set().union(*(df.loc[start:end].index for df in all_data.values())))
    print(f"Simulating {len(all_dates)} trading days: {all_dates[0].date()} → {all_dates[-1].date()}")

    trades: List[SimTrade] = []
    equity = capital
    peak_equity = capital
    max_drawdown = 0.0
    equity_curve = []
    circuit_breaker_days = 0
    sim_5min_count = 0
    sim_daily_count = 0

    for day_idx, date in enumerate(all_dates):
        day_trades = []
        day_str = date.strftime("%Y-%m-%d")
        day_pnl = 0.0
        day_date = date.date() if hasattr(date, 'date') else pd.Timestamp(date).date()

        # --- Phase 1: Generate ALL signals for the day (like live scanner) ---
        candidates = []
        for ticker, df in all_data.items():
            if date not in df.index:
                continue
            loc = df.index.get_loc(date)
            if isinstance(loc, slice):
                loc = loc.start
            if loc < LOOKBACK:
                continue

            # Signal from data up to YESTERDAY only — no look-ahead bias
            trailing = df.iloc[loc - LOOKBACK: loc].copy()
            today = df.iloc[loc]

            result = run_brooks_analysis(df=trailing, ticker=ticker)
            if not result.success or result.signal_type == "HOLD":
                continue
            if result.entry_price <= 0:
                continue

            direction = "SHORT" if result.signal_type == "SELL" else "LONG"
            raw_open = float(today["Open"])
            entry = _slipped_entry(raw_open, direction)

            stop = _calc_intraday_stop(result.signal_type, entry, trailing)
            stop_dist = abs(entry - stop)
            if stop_dist <= 0:
                continue

            stop_pct = round(stop_dist / entry * 100, 2)

            if direction == "LONG":
                target = round(entry + stop_dist * MIN_RR, 2)
            else:
                target = round(entry - stop_dist * MIN_RR, 2)

            per_slot = capital / MAX_POSITIONS
            qty = int(per_slot // entry)
            if qty <= 0:
                continue

            candidates.append({
                "ticker": ticker, "df_today": today, "result": result,
                "direction": direction, "entry": entry, "stop": stop,
                "target": target, "stop_pct": stop_pct, "qty": qty,
            })

        # --- Phase 2: Filter by MIN_CONFIDENCE + sort by confidence desc (like live trader) ---
        candidates = [c for c in candidates
                      if c["result"].confidence >= MIN_CONFIDENCE
                      and (("LONG_FIRST" if c["result"].signal_type == "BUY" else "SHORT_FIRST"),
                           c["result"].setup_type) in ALLOWED_SETUPS]
        candidates.sort(key=lambda c: -c["result"].confidence)

        # --- Phase 3: Take top MAX_POSITIONS, simulate each ---
        for cand in candidates[:MAX_POSITIONS]:
            ticker = cand["ticker"]
            today = cand["df_today"]
            result = cand["result"]
            direction = cand["direction"]
            entry = cand["entry"]
            stop = cand["stop"]
            target = cand["target"]
            stop_pct = cand["stop_pct"]
            qty = cand["qty"]
            rr = round(MIN_RR, 2)

            # Simulate — prefer 5-min bar-by-bar when data exists
            bars_5m = pd.DataFrame()
            if ticker in fivemin_cache:
                bars_5m = fivemin_cache[ticker][fivemin_cache[ticker].index.date == day_date]
            if not bars_5m.empty and len(bars_5m) >= 10:
                exit_price, exit_reason, trail_info = _simulate_5min_trade(
                    bars_5m, entry, stop, target, direction
                )
                sim_5min_count += 1
            else:
                exit_price, exit_reason, trail_info = _simulate_day_trade(
                    today, entry, stop, target, direction
                )
                sim_daily_count += 1

            partial_exit_price = trail_exit_price = trail_best_price = 0.0
            trail_exit_reason = ""
            partial_qty = trail_qty = 0
            sign = 1 if direction == "LONG" else -1
            stock_name = ticker.replace(".NS", "")
            use_trail = PARTIAL_EXIT_PCT > 0 and trail_info and qty >= 2 and abs(entry - stop) > entry * 0.001

            if use_trail:
                partial_qty = max(1, int(qty * PARTIAL_EXIT_PCT))
                trail_qty = qty - partial_qty
                partial_exit_price = trail_info["partial_exit_price"]
                trail_exit_price = trail_info["trail_exit_price"]
                trail_exit_reason = trail_info["trail_exit_reason"]
                trail_best_price = round(trail_info["trail_best"], 2)
                gross = sign * ((partial_exit_price - entry) * partial_qty +
                                (trail_exit_price - entry) * trail_qty)
                exit_price = round((partial_exit_price * partial_qty +
                                    trail_exit_price * trail_qty) / qty, 2)
                exit_reason = "PARTIAL_TRAIL"
            else:
                gross = sign * (exit_price - entry) * qty

            # Charges — full breakdown (like live trader)
            charges_total = 0.0
            charges_dict = {}
            try:
                if use_trail:
                    for ep, eq in [(partial_exit_price, partial_qty),
                                   (trail_exit_price, trail_qty)]:
                        bp = ep if direction == "SHORT" else entry
                        sp = entry if direction == "SHORT" else ep
                        p = calculate_trade(
                            stock=stock_name, platform="dhan",
                            trade_type="intraday", exchange="NSE",
                            quantity=eq, buy_price=bp, sell_price=sp,
                            buy_date=day_str, sell_date=day_str)
                        charges_total += p.charges.total
                        d = p.charges.to_dict()
                        charges_dict = {k: round(charges_dict.get(k, 0) + d.get(k, 0), 2)
                                        for k in set(charges_dict) | set(d)}
                else:
                    buy_p = exit_price if direction == "SHORT" else entry
                    sell_p = entry if direction == "SHORT" else exit_price
                    pnl_obj = calculate_trade(
                        stock=stock_name, platform="dhan",
                        trade_type="intraday", exchange="NSE",
                        quantity=qty, buy_price=buy_p, sell_price=sell_p,
                        buy_date=day_str, sell_date=day_str)
                    charges_total = pnl_obj.charges.total
                    charges_dict = pnl_obj.charges.to_dict()
            except Exception:
                pass

            net = round(gross - charges_total, 2)
            day_pnl += net
            equity += net

            trade = SimTrade(
                date=day_str, ticker=ticker, direction=direction,
                setup_type=result.setup_type, confidence=result.confidence,
                entry_price=entry, stop_loss=stop, target=target,
                exit_price=exit_price, exit_reason=exit_reason,
                quantity=qty, gross_pnl=round(gross, 2),
                charges=charges_dict if charges_dict else round(charges_total, 2),
                net_pnl=net, stop_pct=stop_pct, risk_reward=rr,
                always_in=getattr(result, "always_in", ""),
                trend_phase=getattr(result, "trend_phase", ""),
                partial_exit_price=partial_exit_price,
                trail_exit_price=trail_exit_price,
                trail_exit_reason=trail_exit_reason,
                trail_best_price=trail_best_price,
            )
            trades.append(trade)
            day_trades.append(trade)

            # Circuit breaker check (like live: -2% of starting capital)
            loss_limit = capital * MAX_DAILY_LOSS_PCT / 100
            if day_pnl < -loss_limit:
                circuit_breaker_days += 1
                break

        if equity > peak_equity:
            peak_equity = equity
        dd = (peak_equity - equity) / peak_equity * 100
        if dd > max_drawdown:
            max_drawdown = dd

        equity_curve.append({"date": day_str, "equity": round(equity, 2)})

        if (day_idx + 1) % 250 == 0:
            print(f"  ...{day_idx+1}/{len(all_dates)} days, {len(trades)} trades, equity ₹{equity:,.0f}")

    summary = _compute_summary(trades, capital, equity, peak_equity, max_drawdown)
    summary["circuit_breaker_days"] = circuit_breaker_days
    summary["sim_5min_trades"] = sim_5min_count
    summary["sim_daily_trades"] = sim_daily_count
    return {
        "trades": trades,
        "equity_curve": equity_curve,
        "summary": summary,
    }


def _compute_summary(trades, start_cap, end_cap, peak, max_dd):
    if not trades:
        return {"total_trades": 0}

    wins = [t for t in trades if t.net_pnl > 0]
    losses = [t for t in trades if t.net_pnl <= 0]
    longs = [t for t in trades if t.direction == "LONG"]
    shorts = [t for t in trades if t.direction == "SHORT"]

    def _charge_total(c):
        if isinstance(c, dict):
            return c.get("total", sum(v for v in c.values() if isinstance(v, (int, float))))
        return float(c) if c else 0.0

    gross_sum = sum(t.gross_pnl for t in trades)
    charges_sum = sum(_charge_total(t.charges) for t in trades)
    net_sum = sum(t.net_pnl for t in trades)

    targets = [t for t in trades if t.exit_reason == "TARGET_HIT"]
    stops = [t for t in trades if t.exit_reason == "STOP_HIT"]
    hard_exits = [t for t in trades if t.exit_reason == "HARD_EXIT"]
    trail_exits = [t for t in trades if t.exit_reason == "PARTIAL_TRAIL"]

    avg_win = np.mean([t.net_pnl for t in wins]) if wins else 0
    avg_loss = np.mean([t.net_pnl for t in losses]) if losses else 0
    profit_factor = abs(sum(t.net_pnl for t in wins) / sum(t.net_pnl for t in losses)) if losses and sum(t.net_pnl for t in losses) != 0 else 0

    # Per-year breakdown
    yearly = {}
    for t in trades:
        yr = t.date[:4]
        if yr not in yearly:
            yearly[yr] = {"trades": 0, "net": 0, "wins": 0, "charges": 0}
        yearly[yr]["trades"] += 1
        yearly[yr]["net"] += t.net_pnl
        yearly[yr]["charges"] += _charge_total(t.charges)
        if t.net_pnl > 0:
            yearly[yr]["wins"] += 1

    # Top winners / losers
    sorted_by_pnl = sorted(trades, key=lambda t: t.net_pnl, reverse=True)
    top5 = sorted_by_pnl[:5]
    bottom5 = sorted_by_pnl[-5:]

    return {
        "start_capital": start_cap,
        "end_capital": round(end_cap, 2),
        "total_return_pct": round((end_cap - start_cap) / start_cap * 100, 2),
        "total_trades": len(trades),
        "longs": len(longs),
        "shorts": len(shorts),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 1),
        "gross_pnl": round(gross_sum, 2),
        "total_charges": round(charges_sum, 2),
        "net_pnl": round(net_sum, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "peak_equity": round(peak, 2),
        "target_exits": len(targets),
        "stop_exits": len(stops),
        "hard_exits": len(hard_exits),
        "trail_exits": len(trail_exits),
        "yearly": yearly,
        "top5_winners": [(t.date, t.ticker, t.direction, t.net_pnl) for t in top5],
        "top5_losers": [(t.date, t.ticker, t.direction, t.net_pnl) for t in bottom5],
        "slippage_bps": {
            "entry": ENTRY_SLIPPAGE_BPS,
            "stop": STOP_SLIPPAGE_BPS,
            "hard_exit": HARD_EXIT_SLIPPAGE_BPS,
            "target": TARGET_SLIPPAGE_BPS,
        },
    }


def print_report(result: Dict):
    s = result["summary"]
    if s["total_trades"] == 0:
        print("No trades generated.")
        return

    print("\n" + "=" * 70)
    print("  INTRADAY BACKTEST RESULTS")
    print("=" * 70)

    print(f"\n  Period:          {result['equity_curve'][0]['date']} → {result['equity_curve'][-1]['date']}")
    print(f"  Starting Capital: ₹{s['start_capital']:>12,.2f}")
    print(f"  Ending Capital:   ₹{s['end_capital']:>12,.2f}")
    print(f"  Total Return:     {s['total_return_pct']:>+11.2f}%")
    print(f"  Max Drawdown:     {s['max_drawdown_pct']:>11.2f}%")
    print(f"  Peak Equity:      ₹{s['peak_equity']:>12,.2f}")

    print(f"\n  {'─' * 40}")
    print(f"  TRADES")
    print(f"  Total:    {s['total_trades']:>6}  ({s['longs']} long, {s['shorts']} short)")
    print(f"  Winners:  {s['wins']:>6}  ({s['win_rate_pct']:.1f}%)")
    print(f"  Losers:   {s['losses']:>6}")
    print(f"  Avg Win:  ₹{s['avg_win']:>10,.2f}")
    print(f"  Avg Loss: ₹{s['avg_loss']:>10,.2f}")
    print(f"  Profit F: {s['profit_factor']:>10.2f}")

    print(f"\n  {'─' * 40}")
    print(f"  EXIT REASONS")
    print(f"  Target Hit:   {s['target_exits']:>5}")
    print(f"  Partial+Trail:{s.get('trail_exits', 0):>5}")
    print(f"  Stop Hit:     {s['stop_exits']:>5}")
    print(f"  Hard Exit:    {s['hard_exits']:>5}")

    print(f"\n  {'─' * 40}")
    print(f"  P&L BREAKDOWN")
    print(f"  Gross P&L:    ₹{s['gross_pnl']:>12,.2f}")
    print(f"  Dhan Charges: ₹{s['total_charges']:>12,.2f}")
    print(f"  Net P&L:      ₹{s['net_pnl']:>12,.2f}")

    print(f"\n  {'─' * 40}")
    print(f"  YEARLY BREAKDOWN")
    print(f"  {'Year':<6} {'Trades':>7} {'Win%':>6} {'Net P&L':>12} {'Charges':>10}")
    for yr in sorted(s["yearly"]):
        y = s["yearly"][yr]
        wr = round(y["wins"] / y["trades"] * 100, 1) if y["trades"] else 0
        print(f"  {yr:<6} {y['trades']:>7} {wr:>5.1f}% ₹{y['net']:>11,.2f} ₹{y['charges']:>9,.2f}")

    print(f"\n  {'─' * 40}")
    print(f"  TOP 5 WINNERS")
    for d, t, dr, pnl in s["top5_winners"]:
        print(f"    {d}  {t.replace('.NS',''):>12}  {dr:>5}  ₹{pnl:>+10,.2f}")

    print(f"\n  TOP 5 LOSERS")
    for d, t, dr, pnl in s["top5_losers"]:
        print(f"    {d}  {t.replace('.NS',''):>12}  {dr:>5}  ₹{pnl:>+10,.2f}")

    print(f"\n  {'─' * 40}")
    print(f"  SIMULATION METHOD")
    print(f"  5-min bar-by-bar:  {s.get('sim_5min_trades', 0):>6} trades")
    print(f"  Daily OHLC path:   {s.get('sim_daily_trades', 0):>6} trades")
    sl = s.get('slippage_bps', {})
    print(f"  Slippage: entry={sl.get('entry',0)}bps  stop={sl.get('stop',0)}bps  hard_exit={sl.get('hard_exit',0)}bps")
    print(f"  Circuit breaker days: {s.get('circuit_breaker_days', 0)}")

    print("\n" + "=" * 70)


RESULTS_FILE = os.path.join(os.path.dirname(__file__), ".backtest_results.json")


def save_results(result: Dict):
    """Save backtest results to JSON for web UI."""
    import json
    out = {
        "summary": result["summary"],
        "equity_curve": result["equity_curve"],
        "trades": [
            {
                "date": t.date, "ticker": t.ticker, "direction": t.direction,
                "setup_type": t.setup_type, "confidence": t.confidence,
                "entry_price": t.entry_price, "stop_loss": t.stop_loss,
                "target": t.target, "exit_price": t.exit_price,
                "exit_reason": t.exit_reason, "quantity": t.quantity,
                "gross_pnl": t.gross_pnl, "charges": t.charges,
                "net_pnl": t.net_pnl,
                "stop_pct": t.stop_pct, "risk_reward": t.risk_reward,
                "always_in": t.always_in, "trend_phase": t.trend_phase,
                "partial_exit_price": t.partial_exit_price,
                "trail_exit_price": t.trail_exit_price,
                "trail_exit_reason": t.trail_exit_reason,
                "trail_best_price": t.trail_best_price,
            }
            for t in result["trades"]
        ],
    }
    with open(RESULTS_FILE, "w") as f:
        json.dump(out, f)
    print(f"\nResults saved to {RESULTS_FILE}")


def get_backtest_results() -> Dict:
    """Load saved backtest results (for web UI)."""
    import json
    if not os.path.exists(RESULTS_FILE):
        return {}
    with open(RESULTS_FILE) as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="Intraday system backtest")
    parser.add_argument("--start", default="2020-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="End date (YYYY-MM-DD)")
    parser.add_argument("--capital", type=float, default=100_000, help="Starting capital")
    parser.add_argument("--watchlist", nargs="*", help="Tickers to test")
    args = parser.parse_args()

    wl = [t if t.endswith(".NS") else t + ".NS" for t in args.watchlist] if args.watchlist else None  # None → Nifty 500

    result = run_backtest(
        watchlist=wl, start_date=args.start,
        end_date=args.end, capital=args.capital,
    )
    print_report(result)
    save_results(result)


if __name__ == "__main__":
    main()
