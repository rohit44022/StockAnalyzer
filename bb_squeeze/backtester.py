"""
Walk-Forward Backtesting Engine — bb_squeeze
============================================

What is backtesting?
--------------------
Think of backtesting as a "dress rehearsal" for a trading strategy. Instead of
risking real money to see if a strategy works, we run it against *past* historical
price data and count how many times it would have made money versus lost money.

It is like asking: "If I had used this exact rule every day for the last 2 years,
what would have happened?" The answer gives us statistics — win rate, average profit,
average loss — that help us judge whether a strategy is worth trying on live markets.

Key concepts used in this engine
---------------------------------
**R-multiple (R)**
  Every trade risks a fixed amount — the distance between the entry price and the
  stop-loss. We call that one "R" (one unit of risk). If you risked ₹100 and made
  ₹300, that is a 3R winner. If you lost ₹150, that is -1.5R. Using R makes
  comparing trades fair regardless of stock price.

**Profit Factor**
  Total money won ÷ total money lost (both in absolute terms). A profit factor of
  1.5 means: "For every ₹1 we lost, we earned ₹1.50." Anything above 1.0 is
  profitable; most professional traders aim for 1.5–2.5.

**Expectancy**
  Average expected return per trade in R-units.
  Formula: (win_rate × avg_winner_R) − ((1 − win_rate) × avg_loser_R)
  Positive expectancy = strategy makes money over many trades on average.

**ATR (Average True Range)**
  A measure of how much a stock typically moves each day. Using ATR for stops and
  targets means wider stops on volatile stocks and tighter stops on calm ones —
  adapting to the stock's own rhythm rather than using a fixed ₹ amount.

Limitations (important — please read)
--------------------------------------
- Past performance does NOT guarantee future results. Markets evolve.
- Survivorship bias: we only test on stocks that are in the CSV folder. Stocks that
  went bankrupt or got delisted are not included, so results may look better than
  reality.
- Slippage and brokerage are NOT modelled. Real trades cost money to execute.
- Execution assumed at close price; actual fills may differ.

Methods tested
--------------
M1  Squeeze Breakout   — low volatility (BBW < 0.10) then explosive price + volume break
M2  Trend Following    — price above SMA, momentum positive, RSI > 50
M3  Mean Reversion     — oversold bounce: price below lower BB, RSI < 35, bounce candle
M4  Band Walking       — price riding upper BB for 3+ consecutive days with rising volume
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime

import numpy as np
import pandas as pd

from bb_squeeze.config import CSV_DIR
from bb_squeeze.data_loader import load_from_csv

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
#  INDICATOR HELPERS  (standalone so we don't hit compute_all_indicators)
# ─────────────────────────────────────────────────────────────────

def _sma(arr: np.ndarray, period: int) -> np.ndarray:
    out = np.full(len(arr), np.nan)
    for i in range(period - 1, len(arr)):
        out[i] = arr[i - period + 1 : i + 1].mean()
    return out


def _rolling_std(arr: np.ndarray, period: int) -> np.ndarray:
    out = np.full(len(arr), np.nan)
    for i in range(period - 1, len(arr)):
        out[i] = arr[i - period + 1 : i + 1].std(ddof=0)
    return out


def _rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    delta = np.diff(close, prepend=np.nan)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = _sma(gain, period)
    avg_loss = _sma(loss, period)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.where(avg_loss == 0, np.inf, avg_gain / avg_loss)
    return 100.0 - (100.0 / (1.0 + rs))


def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    prev_close = np.concatenate([[np.nan], close[:-1]])
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    return _sma(tr, period)


def _compute_indicators(df: pd.DataFrame) -> dict[str, np.ndarray]:
    """
    Compute all indicators needed by the four methods. Returns dict of numpy arrays
    aligned to df's index.
    """
    close  = df["Close"].to_numpy(dtype=float)
    high   = df["High"].to_numpy(dtype=float)
    low    = df["Low"].to_numpy(dtype=float)
    volume = df["Volume"].to_numpy(dtype=float)

    sma20  = _sma(close, 20)
    std20  = _rolling_std(close, 20)
    upper  = sma20 + 2.0 * std20
    lower  = sma20 - 2.0 * std20
    bbw    = np.where(sma20 > 0, (upper - lower) / sma20, np.nan)
    rsi14  = _rsi(close, 14)
    atr14  = _atr(high, low, close, 14)
    vol_ma = _sma(volume, 20)

    return {
        "close": close, "high": high, "low": low, "volume": volume,
        "sma20": sma20, "upper": upper, "lower": lower, "bbw": bbw,
        "rsi14": rsi14, "atr14": atr14, "vol_ma": vol_ma,
    }


# ─────────────────────────────────────────────────────────────────
#  ENTRY SIGNAL CHECKERS
# ─────────────────────────────────────────────────────────────────

def _signal_m1(ind: dict, i: int) -> bool:
    """M1 Squeeze Breakout: BBW < 0.10, close > upper BB, volume surge."""
    if i < 5:
        return False
    return (
        not np.isnan(ind["bbw"][i])
        and ind["bbw"][i] < 0.10
        and ind["close"][i] > ind["upper"][i]
        and ind["volume"][i] > 1.5 * ind["vol_ma"][i]
    )


def _signal_m2(ind: dict, i: int) -> bool:
    """M2 Trend Following: above SMA, momentum up, RSI > 50, SMA rising."""
    if i < 6:
        return False
    return (
        not np.isnan(ind["sma20"][i])
        and ind["close"][i] > ind["sma20"][i]
        and ind["close"][i] > ind["close"][i - 1]
        and not np.isnan(ind["rsi14"][i])
        and ind["rsi14"][i] > 50
        and ind["sma20"][i] > ind["sma20"][i - 5]
    )


def _signal_m3(ind: dict, i: int) -> bool:
    """M3 Mean Reversion: close below lower BB, RSI < 35, bounce candle."""
    if i < 2:
        return False
    return (
        not np.isnan(ind["lower"][i - 1])
        and ind["close"][i - 1] < ind["lower"][i - 1]   # previous day touched lower
        and not np.isnan(ind["rsi14"][i - 1])
        and ind["rsi14"][i - 1] < 35
        and ind["close"][i] > ind["close"][i - 1]        # today bounced up
    )


def _signal_m4(ind: dict, i: int) -> bool:
    """M4 Band Walking: 3+ consecutive closes above upper BB, volume rising."""
    if i < 3:
        return False
    consec = all(ind["close"][j] > ind["upper"][j] for j in range(i - 2, i + 1))
    vol_rising = ind["volume"][i] > ind["volume"][i - 1] > ind["volume"][i - 2]
    return consec and vol_rising and not np.isnan(ind["upper"][i])


_SIGNAL_FN = {"M1": _signal_m1, "M2": _signal_m2, "M3": _signal_m3, "M4": _signal_m4}


# ─────────────────────────────────────────────────────────────────
#  SINGLE-TICKER WALK-FORWARD
# ─────────────────────────────────────────────────────────────────

def _run_ticker(
    ticker: str,
    df: pd.DataFrame,
    method: str,
    start_date: str,
    end_date: str,
    stop_mult: float,
    target_mult: float,
) -> list[dict]:
    """
    Walk-forward simulation for one ticker. Returns list of trade dicts.
    """
    signal_fn = _SIGNAL_FN[method]
    ind = _compute_indicators(df)
    dates = df.index  # DatetimeIndex

    start_ts = pd.Timestamp(start_date)
    end_ts   = pd.Timestamp(end_date)

    # Map date → integer index for fast lookup
    mask = (dates >= start_ts) & (dates <= end_ts)
    valid_positions = np.where(mask)[0]
    if len(valid_positions) < 30:
        return []

    trades: list[dict] = []
    in_trade = False
    entry_price = stop = target = 0.0
    entry_date = entry_idx = None

    for i in valid_positions:
        atr_val = ind["atr14"][i]
        if np.isnan(atr_val) or atr_val <= 0:
            continue

        if not in_trade:
            # Check entry signal — needs full indicator history so use absolute i
            if signal_fn(ind, i):
                entry_price = ind["close"][i]
                stop        = entry_price - stop_mult * atr_val
                target      = entry_price + target_mult * atr_val
                entry_date  = dates[i]
                entry_idx   = i
                in_trade    = True
        else:
            # Check exit: high hits target → WIN; low hits stop → LOSS
            # Check target first (optimistic but standard for EOD backtesting)
            hit_target = ind["high"][i] >= target
            hit_stop   = ind["low"][i]  <= stop

            if hit_target or hit_stop or dates[i] == end_ts:
                exit_price  = target if hit_target else (stop if hit_stop else ind["close"][i])
                result      = "WIN" if hit_target else ("LOSS" if hit_stop else "OPEN")
                risk        = entry_price - stop
                r_mult      = (exit_price - entry_price) / risk if risk > 0 else 0.0
                holding     = int((dates[i] - entry_date).days)

                trades.append({
                    "ticker":        ticker,
                    "method":        method,
                    "entry_date":    str(entry_date.date()),
                    "entry_price":   round(float(entry_price), 2),
                    "exit_date":     str(dates[i].date()),
                    "exit_price":    round(float(exit_price), 2),
                    "stop":          round(float(stop), 2),
                    "target":        round(float(target), 2),
                    "result":        result,
                    "r_multiple":    round(r_mult, 3),
                    "holding_days":  holding,
                })
                in_trade = False

    # If still in trade at end of data, mark as OPEN
    if in_trade:
        last_i = valid_positions[-1]
        exit_price = ind["close"][last_i]
        risk = entry_price - stop
        r_mult = (exit_price - entry_price) / risk if risk > 0 else 0.0
        trades.append({
            "ticker":       ticker,
            "method":       method,
            "entry_date":   str(entry_date.date()),
            "entry_price":  round(float(entry_price), 2),
            "exit_date":    str(dates[last_i].date()),
            "exit_price":   round(float(exit_price), 2),
            "stop":         round(float(stop), 2),
            "target":       round(float(target), 2),
            "result":       "OPEN",
            "r_multiple":   round(r_mult, 3),
            "holding_days": int((dates[last_i] - entry_date).days),
        })

    return trades


# ─────────────────────────────────────────────────────────────────
#  AGGREGATION HELPERS
# ─────────────────────────────────────────────────────────────────

def _consecutive(results: list[str], target: str) -> int:
    """Max consecutive streak of `target` in results list."""
    best = cur = 0
    for r in results:
        if r == target:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def _monthly_breakdown(trades: list[dict]) -> list[dict]:
    by_month: dict[str, dict] = defaultdict(lambda: {"trades": 0, "wins": 0})
    for t in trades:
        if t["result"] == "OPEN":
            continue
        month = t["entry_date"][:7]   # "YYYY-MM"
        by_month[month]["trades"] += 1
        if t["result"] == "WIN":
            by_month[month]["wins"] += 1
    out = []
    for month in sorted(by_month):
        d = by_month[month]
        total = d["trades"]
        wins  = d["wins"]
        out.append({
            "month":    month,
            "trades":   total,
            "wins":     wins,
            "win_rate": round(wins / total, 3) if total else 0.0,
        })
    return out


def _build_explanation(method: str, stats: dict) -> str:
    method_names = {
        "M1": "Squeeze Breakout",
        "M2": "Trend Following",
        "M3": "Mean Reversion",
        "M4": "Band Walking",
    }
    name = method_names.get(method, method)
    wn   = stats["wins"]
    ls   = stats["losses"]
    tot  = stats["total_trades"]
    wr   = stats["win_rate"]
    pf   = stats["profit_factor"]
    exp  = stats["expectancy_r"]
    aw   = stats["avg_winner_r"]
    al   = stats["avg_loser_r"]

    verdict = (
        "PROFITABLE — positive expectancy and profit factor above 1.0."
        if exp > 0 and pf > 1.0
        else "NOT PROFITABLE in this period — negative expectancy."
    )

    return (
        f"=== Backtest Report: {name} ({method}) ===\n\n"
        f"WHAT WAS TESTED\n"
        f"  Strategy: {name} on Indian NSE stocks\n"
        f"  Period  : {stats['period']['start']} to {stats['period']['end']}\n"
        f"  Universe: {stats['universe_size']} tickers\n\n"
        f"WHAT IS BACKTESTING?\n"
        f"  We replayed this strategy on past price data, like a cricket team reviewing "
        f"match footage to see which plays worked. We applied the exact entry and exit "
        f"rules to every stock in the universe, day by day, and counted results.\n\n"
        f"RESULTS SUMMARY\n"
        f"  Total trades : {tot}  ({wn} wins / {ls} losses / {stats['open_trades']} still open)\n"
        f"  Win rate     : {wr:.1%}  (out of every 10 trades, ~{wr*10:.1f} were winners)\n"
        f"  Avg winner   : +{aw:.2f}R  (each winning trade made {aw:.2f}x the amount risked)\n"
        f"  Avg loser    : -{al:.2f}R  (each losing trade lost {al:.2f}x the amount risked)\n"
        f"  Profit factor: {pf:.2f}  (for every ₹1 lost, ₹{pf:.2f} was earned)\n"
        f"  Expectancy   : {exp:+.3f}R per trade\n"
        f"    → This means on AVERAGE, each trade earns {exp:+.3f} units of risk.\n"
        f"      Over many trades, that compounds significantly.\n\n"
        f"VERDICT: {verdict}\n\n"
        f"WHAT IS R-MULTIPLE?\n"
        f"  When you enter a trade, the distance between your entry price and stop-loss "
        f"is '1R' — one unit of risk. If you buy at ₹100 with a stop at ₹95, your 1R = ₹5. "
        f"If you later sell at ₹115, you made 3R (₹15 profit / ₹5 risk). "
        f"R-multiple lets us compare all trades on equal footing regardless of stock price.\n\n"
        f"WHAT IS PROFIT FACTOR?\n"
        f"  Profit factor = total profits ÷ total losses (absolute values). "
        f"A value of {pf:.2f} means for every ₹1 lost across all losing trades, "
        f"₹{pf:.2f} was made across all winning trades. "
        f"Anything above 1.0 is profitable; professional systems typically target 1.5–2.5.\n\n"
        f"WHAT IS EXPECTANCY?\n"
        f"  Expectancy = (win_rate × avg_winner_R) − ((1−win_rate) × avg_loser_R)\n"
        f"  = ({wr:.3f} × {aw:.3f}) − ({1-wr:.3f} × {al:.3f}) = {exp:+.3f}R\n"
        f"  Think of it as: 'If I take 100 such trades, I expect {exp*100:+.1f}R total profit.'\n\n"
        f"IMPORTANT LIMITATIONS\n"
        f"  1. Past performance does NOT guarantee future results. Indian markets evolve — "
        f"what worked in a bull market may not work in a sideways or bear phase.\n"
        f"  2. Survivorship bias: only stocks with available CSV data are tested. Stocks "
        f"that were suspended, delisted, or went bankrupt are missing — making results "
        f"look slightly better than reality.\n"
        f"  3. Slippage & brokerage NOT included. Real NSE trades attract brokerage, "
        f"STT, SEBI charges, and execution slippage. These can reduce actual returns "
        f"by 0.2–0.5% per trade.\n"
        f"  4. Entry assumed at closing price on signal day. In practice, you would "
        f"execute the next morning's open, which may differ.\n"
        f"  5. Only one trade per ticker at a time (no pyramiding).\n"
    )


# ─────────────────────────────────────────────────────────────────
#  MAIN PUBLIC FUNCTION
# ─────────────────────────────────────────────────────────────────

def backtest_method(
    method: str,
    tickers: list[str],
    start_date: str,
    end_date: str,
    csv_dir: str | None = None,
    stop_atr_mult: float = 2.0,
    target_atr_mult: float = 3.0,
) -> dict:
    """
    Walk-forward backtest for one of four Bollinger Band methods over a list of
    NSE tickers.

    Parameters
    ----------
    method         : "M1" | "M2" | "M3" | "M4"
    tickers        : list of ticker strings, e.g. ["RELIANCE.NS", "TCS.NS"]
    start_date     : "YYYY-MM-DD"
    end_date       : "YYYY-MM-DD"
    csv_dir        : override default CSV_DIR
    stop_atr_mult  : ATR multiplier for stop-loss (default 2.0)
    target_atr_mult: ATR multiplier for profit target (default 3.0)

    Returns
    -------
    dict with full statistics, trade log, monthly breakdown, and plain-English explanation.
    """
    if method not in _SIGNAL_FN:
        raise ValueError(f"method must be one of {list(_SIGNAL_FN)}; got {method!r}")

    csv_dir = csv_dir or CSV_DIR
    all_trades: list[dict] = []

    for ticker in tickers:
        try:
            df = load_from_csv(ticker, csv_dir)
            if df is None or df.empty:
                continue
            trades = _run_ticker(
                ticker, df, method,
                start_date, end_date,
                stop_atr_mult, target_atr_mult,
            )
            all_trades.extend(trades)
        except Exception as exc:
            logger.warning("backtest_method: skipping %s — %s", ticker, exc)

    # ── Aggregate ──────────────────────────────────────────────
    closed = [t for t in all_trades if t["result"] != "OPEN"]
    wins   = [t for t in closed if t["result"] == "WIN"]
    losses = [t for t in closed if t["result"] == "LOSS"]
    open_  = [t for t in all_trades if t["result"] == "OPEN"]

    n_wins = len(wins)
    n_loss = len(losses)
    n_tot  = len(closed)
    win_rate = n_wins / n_tot if n_tot else 0.0

    win_rs  = [t["r_multiple"] for t in wins]
    loss_rs = [abs(t["r_multiple"]) for t in losses]

    avg_winner_r = float(np.mean(win_rs))  if win_rs  else 0.0
    avg_loser_r  = float(np.mean(loss_rs)) if loss_rs else 0.0

    total_profit = sum(win_rs)
    total_loss   = sum(loss_rs)
    profit_factor = total_profit / total_loss if total_loss > 0 else (float("inf") if total_profit > 0 else 0.0)

    expectancy_r = (win_rate * avg_winner_r) - ((1 - win_rate) * avg_loser_r)

    result_seq = [t["result"] for t in closed]
    max_consec_wins  = _consecutive(result_seq, "WIN")
    max_consec_loss  = _consecutive(result_seq, "LOSS")

    best_trade  = max(all_trades, key=lambda t: t["r_multiple"], default=None)
    worst_trade = min(all_trades, key=lambda t: t["r_multiple"], default=None)

    stats = {
        "method":                 method,
        "period":                 {"start": start_date, "end": end_date},
        "universe_size":          len(tickers),
        "total_trades":           n_tot,
        "wins":                   n_wins,
        "losses":                 n_loss,
        "open_trades":            len(open_),
        "win_rate":               round(win_rate, 4),
        "avg_winner_r":           round(avg_winner_r, 3),
        "avg_loser_r":            round(avg_loser_r, 3),
        "profit_factor":          round(profit_factor, 3),
        "expectancy_r":           round(expectancy_r, 4),
        "max_consecutive_wins":   max_consec_wins,
        "max_consecutive_losses": max_consec_loss,
        "best_trade":             best_trade,
        "worst_trade":            worst_trade,
        "monthly_breakdown":      _monthly_breakdown(all_trades),
        "all_trades":             all_trades,
        "explanation":            "",   # filled below to pass stats dict
    }
    stats["explanation"] = _build_explanation(method, stats)
    return stats


# ─────────────────────────────────────────────────────────────────
#  SELF-CHECK
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Minimal smoke-test: indicator math on synthetic data.
    np.random.seed(42)
    n = 60
    price = 100 + np.cumsum(np.random.randn(n) * 0.5)
    sma = _sma(price, 20)
    rsi = _rsi(price, 14)
    atr = _atr(price * 1.01, price * 0.99, price, 14)
    assert not np.isnan(sma[-1]),  "SMA should have a value at last bar"
    assert 0 < rsi[-1] < 100,      "RSI should be between 0 and 100"
    assert atr[-1] > 0,            "ATR should be positive"
    print("Self-check passed — indicator math is working correctly.")
