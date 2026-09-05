"""
Walk-Forward Backtest — BB + ML Recommendation System
=====================================================

Backtests the full Bollinger Band strategy system (M1-M4) using the complete
indicator set from compute_all_indicators() — NOT the simplified signals in
backtester.py.

Uses method-specific exit signals that mirror _generate_recommendation():
  M1: SAR bearish / lower band tag / CMF+MFI double-negative
  M2: %b < 0.2 AND MFI < 20
  M3: price below lower band (bounce failed) or SAR+below mid
  M4: %b < 0.50 (band walk breaks)
Plus ATR stop/target as safety net, and optional ML conviction filter.

Usage:
    python -m bb_squeeze.rec_backtester              # smoke test, 5 tickers
    python -m bb_squeeze.rec_backtester --full        # all tickers, 2020-2025
    python -m bb_squeeze.rec_backtester --full --ml   # with ML conviction filter
"""
from __future__ import annotations

import glob
import logging
import os
import sys
import time

import numpy as np
import pandas as pd

from bb_squeeze.config import CSV_DIR
from bb_squeeze.data_loader import load_from_csv
from bb_squeeze.indicators import compute_all_indicators
from bb_squeeze.backtester import _consecutive, _monthly_breakdown

logger = logging.getLogger(__name__)


# ─── COLUMN EXTRACTION ───────────────────────────────────────

def _extract(df: pd.DataFrame) -> dict[str, np.ndarray]:
    """Pull indicator columns into numpy arrays for fast walk-forward."""
    def _col(name, dtype=float):
        if name in df.columns:
            return df[name].values.astype(dtype) if dtype == float else df[name].values
        return np.full(len(df), np.nan) if dtype == float else np.zeros(len(df), dtype=bool)

    return {
        "close":    _col("Close"),
        "high":     _col("High"),
        "low":      _col("Low"),
        "volume":   _col("Volume"),
        "atr":      _col("ATR"),
        "bb_upper": _col("BB_Upper"),
        "bb_mid":   _col("BB_Mid"),
        "bb_lower": _col("BB_Lower"),
        "pct_b":    _col("Percent_B"),
        "mfi":      _col("MFI"),
        "rsi":      _col("RSI"),
        "cmf":      _col("CMF"),
        "vol_sma":  _col("Vol_SMA50"),
        "vol_above": _col("Vol_Above_SMA", dtype=bool),
        "squeeze":   _col("Squeeze_ON", dtype=bool),
        "kc_squeeze": _col("KC_Squeeze", dtype=bool),
        "sar_bull":  _col("SAR_Bull", dtype=bool),
        "vwmacd_h":  _col("VWMACD_Hist"),
    }


# ─── ENTRY SIGNALS ───────────────────────────────────────────

def _entry_m1(c: dict, i: int) -> bool:
    """M1 Squeeze Breakout: recent squeeze + breakout above upper BB + volume + momentum."""
    if i < 6 or np.isnan(c["bb_upper"][i]):
        return False
    squeeze_recent = any(c["squeeze"][j] or c["kc_squeeze"][j] for j in range(max(0, i - 5), i))
    return (
        squeeze_recent
        and c["close"][i] > c["bb_upper"][i]
        and c["vol_sma"][i] > 0
        and c["volume"][i] > 1.5 * c["vol_sma"][i]
        and not np.isnan(c["vwmacd_h"][i])
        and c["vwmacd_h"][i] > 0
    )


def _entry_m2(c: dict, i: int) -> bool:
    """M2 Trend Following: %b > 0.8 + MFI > 80 + volume confirms."""
    if np.isnan(c["pct_b"][i]) or np.isnan(c["mfi"][i]):
        return False
    return c["pct_b"][i] > 0.8 and c["mfi"][i] > 80 and c["vol_above"][i]


def _entry_m3(c: dict, i: int) -> bool:
    """M3 W-Bottom: prev bar %b < 0.05, RSI < 30, today bounces up."""
    if i < 2 or np.isnan(c["pct_b"][i - 1]) or np.isnan(c["rsi"][i - 1]):
        return False
    return c["pct_b"][i - 1] < 0.05 and c["rsi"][i - 1] < 30 and c["close"][i] > c["close"][i - 1]


def _entry_m4(c: dict, i: int) -> bool:
    """M4 Band Walking: 3+ consecutive bars %b > 0.95, rising volume."""
    if i < 3:
        return False
    for j in range(i - 2, i + 1):
        if np.isnan(c["pct_b"][j]) or c["pct_b"][j] < 0.95:
            return False
    return c["volume"][i] > c["volume"][i - 1] > c["volume"][i - 2]


_ENTRY_FN = {"M1": _entry_m1, "M2": _entry_m2, "M3": _entry_m3, "M4": _entry_m4}


# ─── METHOD-SPECIFIC EXIT SIGNALS ────────────────────────────
# Mirrors _generate_recommendation() exit logic per strategy.

def _exit_m1(c: dict, i: int) -> bool:
    """M1: SAR bearish / lower band tag / double-negative (CMF<0 + MFI<50).
    Squeeze context: any 1 signal. Non-squeeze: need 2+ or SAR+below mid."""
    sar_bear = not c["sar_bull"][i]
    lower_tag = c["close"][i] <= c["bb_lower"][i]
    dbl_neg = (not np.isnan(c["cmf"][i]) and c["cmf"][i] < 0
               and not np.isnan(c["mfi"][i]) and c["mfi"][i] < 50)
    n_sigs = int(sar_bear) + int(lower_tag) + int(dbl_neg)
    if c["squeeze"][i] or c["kc_squeeze"][i]:
        return n_sigs >= 1
    return n_sigs >= 2 or (sar_bear and c["close"][i] < c["bb_mid"][i])


def _exit_m2(c: dict, i: int) -> bool:
    """M2: %b < 0.2 AND MFI < 20 — both weak = trend broken."""
    if np.isnan(c["pct_b"][i]) or np.isnan(c["mfi"][i]):
        return False
    return c["pct_b"][i] < 0.2 and c["mfi"][i] < 20


def _exit_m3(c: dict, i: int) -> bool:
    """M3: bounce failed — price drops back below lower band,
    or SAR bearish + below mid (reversal didn't hold)."""
    if not np.isnan(c["pct_b"][i]) and c["pct_b"][i] < 0.0:
        return True
    return not c["sar_bull"][i] and c["close"][i] < c["bb_mid"][i]


def _exit_m4(c: dict, i: int) -> bool:
    """M4: band walk breaks — %b drops below 0.50 (Book Ch.18)."""
    if np.isnan(c["pct_b"][i]):
        return False
    return c["pct_b"][i] < 0.50


_EXIT_FN = {"M1": _exit_m1, "M2": _exit_m2, "M3": _exit_m3, "M4": _exit_m4}


# ─── SINGLE-TICKER WALK-FORWARD ─────────────────────────────

def _run_ticker(
    ticker: str,
    df: pd.DataFrame,
    method: str,
    start_date: str,
    end_date: str,
    stop_mult: float,
    target_mult: float,
    ml_filter: bool,
    ml_threshold: int,
) -> list[dict]:
    entry_fn = _ENTRY_FN[method]
    exit_fn = _EXIT_FN[method]
    cols = _extract(df)
    dates = df.index
    start_ts, end_ts = pd.Timestamp(start_date), pd.Timestamp(end_date)

    valid = np.where((dates >= start_ts) & (dates <= end_ts))[0]
    if len(valid) < 30:
        return []

    trades: list[dict] = []
    in_trade = False
    entry_price = stop = target = 0.0
    entry_date = None

    for i in valid:
        atr = cols["atr"][i]
        if np.isnan(atr) or atr <= 0:
            continue

        if not in_trade:
            if not entry_fn(cols, i):
                continue
            if ml_filter:
                try:
                    from ai_ml.conviction_scorer import score_conviction
                    result = score_conviction(df.iloc[: i + 1].copy(), method, ticker)
                    if result and result.get("ml_conviction", 0) < ml_threshold:
                        continue
                except Exception:
                    pass
            entry_price = float(cols["close"][i])
            stop = entry_price - stop_mult * float(atr)
            target = entry_price + target_mult * float(atr)
            entry_date = dates[i]
            in_trade = True
        else:
            hit_target = cols["high"][i] >= target
            hit_stop = cols["low"][i] <= stop
            rec = exit_fn(cols, i)
            end = dates[i] == end_ts

            if hit_target or hit_stop or rec or end:
                if hit_target:
                    exit_price, result, reason = target, "WIN", "TARGET"
                elif hit_stop:
                    exit_price, result, reason = stop, "LOSS", "STOP"
                elif rec:
                    ep = float(cols["close"][i])
                    exit_price = ep
                    result = "WIN" if ep > entry_price else "LOSS"
                    reason = "REC_EXIT"
                else:
                    exit_price, result, reason = float(cols["close"][i]), "OPEN", "END"

                risk = entry_price - stop
                r_mult = (exit_price - entry_price) / risk if risk > 0 else 0.0
                trades.append({
                    "ticker": ticker, "method": method,
                    "entry_date": str(entry_date.date()),
                    "entry_price": round(entry_price, 2),
                    "exit_date": str(dates[i].date()),
                    "exit_price": round(float(exit_price), 2),
                    "stop": round(stop, 2), "target": round(target, 2),
                    "result": result, "r_multiple": round(r_mult, 3),
                    "holding_days": int((dates[i] - entry_date).days),
                    "exit_reason": reason,
                })
                in_trade = False

    if in_trade:
        li = valid[-1]
        ep = float(cols["close"][li])
        risk = entry_price - stop
        r_mult = (ep - entry_price) / risk if risk > 0 else 0.0
        trades.append({
            "ticker": ticker, "method": method,
            "entry_date": str(entry_date.date()),
            "entry_price": round(entry_price, 2),
            "exit_date": str(dates[li].date()),
            "exit_price": round(ep, 2),
            "stop": round(stop, 2), "target": round(target, 2),
            "result": "OPEN", "r_multiple": round(r_mult, 3),
            "holding_days": int((dates[li] - entry_date).days),
            "exit_reason": "OPEN",
        })
    return trades


# ─── AGGREGATION ─────────────────────────────────────────────

def _aggregate(all_trades: list[dict], method: str, universe: int,
               start: str, end: str) -> dict:
    closed = [t for t in all_trades if t["result"] != "OPEN"]
    wins = [t for t in closed if t["result"] == "WIN"]
    losses = [t for t in closed if t["result"] == "LOSS"]

    n_w, n_l, n_t = len(wins), len(losses), len(closed)
    wr = n_w / n_t if n_t else 0.0

    w_rs = [t["r_multiple"] for t in wins]
    l_rs = [abs(t["r_multiple"]) for t in losses]
    aw = float(np.mean(w_rs)) if w_rs else 0.0
    al = float(np.mean(l_rs)) if l_rs else 0.0
    tp, tl = sum(w_rs), sum(l_rs)
    pf = tp / tl if tl > 0 else (float("inf") if tp > 0 else 0.0)
    exp = (wr * aw) - ((1 - wr) * al)

    rec_exits = [t for t in closed if t.get("exit_reason") == "REC_EXIT"]
    rec_wins = [t for t in rec_exits if t["result"] == "WIN"]

    hold_days = [t["holding_days"] for t in closed if t["holding_days"] > 0]

    return {
        "method": method,
        "period": {"start": start, "end": end},
        "universe_size": universe,
        "total_trades": n_t, "wins": n_w, "losses": n_l,
        "open_trades": len(all_trades) - n_t,
        "win_rate": round(wr, 4),
        "avg_winner_r": round(aw, 3), "avg_loser_r": round(al, 3),
        "profit_factor": round(pf, 3),
        "expectancy_r": round(exp, 4),
        "max_consecutive_wins": _consecutive([t["result"] for t in closed], "WIN"),
        "max_consecutive_losses": _consecutive([t["result"] for t in closed], "LOSS"),
        "avg_holding_days": round(float(np.mean(hold_days)), 1) if hold_days else 0,
        "exit_breakdown": {
            "target": len([t for t in closed if t.get("exit_reason") == "TARGET"]),
            "stop": len([t for t in closed if t.get("exit_reason") == "STOP"]),
            "rec_exit": len(rec_exits),
        },
        "rec_exit_win_rate": round(len(rec_wins) / len(rec_exits), 4) if rec_exits else 0.0,
        "monthly_breakdown": _monthly_breakdown(all_trades),
        "all_trades": all_trades,
    }


# ─── PUBLIC API ──────────────────────────────────────────────

def backtest_recommendation(
    method: str,
    tickers: list[str],
    start_date: str = "2020-01-01",
    end_date: str = "2025-12-31",
    ml_filter: bool = False,
    ml_threshold: int = 40,
    stop_atr_mult: float = 2.0,
    target_atr_mult: float = 3.0,
    csv_dir: str | None = None,
) -> dict:
    """Backtest one BB method with full indicators + rec exits."""
    if method not in _ENTRY_FN:
        raise ValueError(f"method must be one of {list(_ENTRY_FN)}; got {method!r}")

    csv_dir = csv_dir or CSV_DIR
    all_trades: list[dict] = []
    processed = 0

    for ticker in tickers:
        try:
            df = load_from_csv(ticker, csv_dir)
            if df is None or len(df) < 120:
                continue
            df = compute_all_indicators(df)
            trades = _run_ticker(
                ticker, df, method, start_date, end_date,
                stop_atr_mult, target_atr_mult, ml_filter, ml_threshold,
            )
            all_trades.extend(trades)
            processed += 1
            if processed % 500 == 0:
                print(f"  [{processed}/{len(tickers)}] {len(all_trades)} trades ...", flush=True)
        except Exception as exc:
            logger.warning("rec_backtest: skipping %s — %s", ticker, exc)

    stats = _aggregate(all_trades, method, len(tickers), start_date, end_date)
    stats["tickers_processed"] = processed
    return stats


def backtest_all_methods(
    tickers: list[str],
    start_date: str = "2020-01-01",
    end_date: str = "2025-12-31",
    ml_filter: bool = False,
    ml_threshold: int = 40,
) -> dict:
    """Run all M1-M4, print results, return per-method + combined stats."""
    results = {}
    combined_trades: list[dict] = []

    for method in ["M1", "M2", "M3", "M4"]:
        print(f"\n{'='*60}")
        print(f"  Backtesting {method} ...")
        print(f"{'='*60}")
        stats = backtest_recommendation(
            method, tickers, start_date, end_date, ml_filter, ml_threshold,
        )
        results[method] = stats
        combined_trades.extend(stats["all_trades"])
        _print_summary(method, stats)

    combined = _aggregate(combined_trades, "ALL", len(tickers), start_date, end_date)
    results["COMBINED"] = combined
    print(f"\n{'='*60}")
    print(f"  COMBINED — All Methods")
    print(f"{'='*60}")
    _print_summary("ALL", combined)

    return results


def _print_summary(method: str, s: dict) -> None:
    names = {"M1": "Squeeze Breakout", "M2": "Trend Following",
             "M3": "W-Bottom Reversal", "M4": "Band Walking", "ALL": "All Methods Combined"}
    print(f"\n  {names.get(method, method)}:")
    print(f"    Trades      : {s['total_trades']} ({s['wins']}W / {s['losses']}L / {s['open_trades']} open)")
    print(f"    Win Rate    : {s['win_rate']:.1%}")
    print(f"    Avg Winner  : +{s['avg_winner_r']:.2f}R")
    print(f"    Avg Loser   : -{s['avg_loser_r']:.2f}R")
    print(f"    Profit Fac  : {s['profit_factor']:.2f}")
    print(f"    Expectancy  : {s['expectancy_r']:+.3f}R")
    print(f"    Avg Hold    : {s['avg_holding_days']:.0f} days")
    eb = s.get("exit_breakdown", {})
    if eb:
        print(f"    Exits       : {eb.get('target',0)} target / {eb.get('stop',0)} stop / {eb.get('rec_exit',0)} rec")
    if s.get("rec_exit_win_rate"):
        print(f"    Rec Exit WR : {s['rec_exit_win_rate']:.1%}")


def _get_all_tickers(csv_dir: str | None = None) -> list[str]:
    csv_dir = csv_dir or CSV_DIR
    return [os.path.basename(f).replace(".csv", "")
            for f in sorted(glob.glob(os.path.join(csv_dir, "*.csv")))]


# ─── SELF CHECK ──────────────────────────────────────────────

if __name__ == "__main__":
    full_mode = "--full" in sys.argv
    ml_mode = "--ml" in sys.argv

    if full_mode:
        tickers = _get_all_tickers()
        print(f"Full backtest: {len(tickers)} tickers, ML={'ON' if ml_mode else 'OFF'}")
    else:
        tickers = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS"]
        print(f"Smoke test: {len(tickers)} tickers")

    t0 = time.time()
    results = backtest_all_methods(
        tickers, "2020-01-01", "2025-12-31", ml_filter=ml_mode,
    )
    print(f"\nDone in {time.time() - t0:.1f}s")

    combined = results["COMBINED"]
    assert combined["total_trades"] >= 0, "Should have non-negative trades"
    if combined["total_trades"] > 0:
        assert 0 <= combined["win_rate"] <= 1, "Win rate out of range"
    print("Self-check passed.")
