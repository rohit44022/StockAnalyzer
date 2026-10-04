"""
Brooks Engine — Walk-Forward Backtest
======================================
Runs the Brooks engine day-by-day on historical data, tracks signal outcomes,
and writes empirical win rates per setup type to brooks/empirical_setup_prob.json.

Usage:
    .venv/bin/python backtest_brooks.py [--start 2023-01-01] [--end 2025-12-31] [--cost 0.50]

Output:
    brooks/empirical_setup_prob.json  — load automatically by engine.py
    backtest_brooks_results.json      — full trade log + stats
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))

from brooks.engine import run_brooks_analysis, BrooksResult, NSE_COST_PCT, SHORTLIST_SETUPS


MAX_HOLD_DAYS = {"BREAKOUT": 30, "PULLBACK": 20, "SECOND_ENTRY": 20,
                 "BREAKOUT_PULLBACK": 25, "REVERSAL": 15,
                 "FAILED_BREAKOUT": 15, "TRAPPED_TRADERS": 15,
                 "CHANNEL_REVERSAL": 15}


def _walk_trade(df_future: pd.DataFrame, sig: str, entry: float,
                stop: float, target: float, max_days: int,
                cost_pct: float) -> dict:
    """Walk forward from signal day to determine outcome.

    Returns dict with keys: outcome, exit_price, bars_held, pnl_pct
    """
    cost = entry * cost_pct / 100
    is_buy = sig == "BUY"

    for i in range(len(df_future)):
        hi = float(df_future.iloc[i].get("High", df_future.iloc[i].get("high", 0)))
        lo = float(df_future.iloc[i].get("Low", df_future.iloc[i].get("low", 0)))

        if is_buy:
            # Check entry fill on first bar
            if i == 0:
                if hi < entry:
                    return {"outcome": "NO_FILL", "exit_price": 0,
                            "bars_held": 0, "pnl_pct": 0}
            # Stop hit?
            if lo <= stop:
                pnl = stop - entry - cost
                return {"outcome": "STOP", "exit_price": stop,
                        "bars_held": i + 1,
                        "pnl_pct": round(pnl / entry * 100, 4)}
            # Target hit?
            if hi >= target:
                pnl = target - entry - cost
                return {"outcome": "TARGET", "exit_price": target,
                        "bars_held": i + 1,
                        "pnl_pct": round(pnl / entry * 100, 4)}
        else:
            if i == 0:
                if lo > entry:
                    return {"outcome": "NO_FILL", "exit_price": 0,
                            "bars_held": 0, "pnl_pct": 0}
            if hi >= stop:
                pnl = entry - stop - cost
                return {"outcome": "STOP", "exit_price": stop,
                        "bars_held": i + 1,
                        "pnl_pct": round(pnl / entry * 100, 4)}
            if lo <= target:
                pnl = entry - target - cost
                return {"outcome": "TARGET", "exit_price": target,
                        "bars_held": i + 1,
                        "pnl_pct": round(pnl / entry * 100, 4)}

        if i + 1 >= max_days:
            cl = float(df_future.iloc[i].get("Close", df_future.iloc[i].get("close", entry)))
            if is_buy:
                pnl = cl - entry - cost
            else:
                pnl = entry - cl - cost
            return {"outcome": "TIMEOUT", "exit_price": cl,
                    "bars_held": i + 1,
                    "pnl_pct": round(pnl / entry * 100, 4)}

    cl = float(df_future.iloc[-1].get("Close", df_future.iloc[-1].get("close", entry)))
    if is_buy:
        pnl = cl - entry - cost
    else:
        pnl = entry - cl - cost
    return {"outcome": "TIMEOUT", "exit_price": cl,
            "bars_held": len(df_future),
            "pnl_pct": round(pnl / entry * 100, 4)}


def _backtest_ticker(ticker: str, csv_dir: str, start: str, end: str,
                     cost_pct: float) -> list:
    """Run walk-forward backtest for a single ticker."""
    try:
        from bb_squeeze.data_loader import load_stock_data
        df = load_stock_data(ticker, csv_dir=csv_dir, use_live_fallback=False)
        if df is None or len(df) < 120:
            return []
    except Exception:
        return []

    if not isinstance(df.index, pd.DatetimeIndex):
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"])
            df = df.set_index("Date")
        else:
            return []

    df = df.sort_index()
    start_dt = pd.Timestamp(start)
    end_dt = pd.Timestamp(end)

    signal_dates = df.index[(df.index >= start_dt) & (df.index <= end_dt)]
    trades = []

    for sig_date in signal_dates[::5]:  # sample every 5 days to keep runtime sane
        hist_end = df.index.get_loc(sig_date)
        if hist_end < 60:
            continue

        df_hist = df.iloc[:hist_end + 1]
        try:
            r = run_brooks_analysis(df_hist, ticker)
        except Exception:
            continue

        if not r.success or r.signal_type == "HOLD":
            continue
        if r.entry_price <= 0 or r.stop_loss <= 0 or r.target_1 <= 0:
            continue
        if r.warnings:
            continue
        if r.setup_type not in SHORTLIST_SETUPS:
            continue
        if r.equation_verdict != "EDGE":
            continue

        max_d = MAX_HOLD_DAYS.get(r.setup_type, 20)
        future_start = hist_end + 1
        future_end = min(future_start + max_d, len(df))
        if future_start >= len(df):
            continue

        df_future = df.iloc[future_start:future_end]
        result = _walk_trade(df_future, r.signal_type, r.entry_price,
                             r.stop_loss, r.target_1, max_d, cost_pct)

        if result["outcome"] == "NO_FILL":
            continue

        trades.append({
            "ticker": ticker,
            "date": str(sig_date.date()),
            "signal": r.signal_type,
            "setup": r.setup_type,
            "confidence": r.confidence,
            "entry": round(r.entry_price, 2),
            "stop": round(r.stop_loss, 2),
            "target": round(r.target_1, 2),
            "risk_reward": round(r.risk_reward, 2),
            "phase": r.trend_phase,
            "always_in": r.always_in,
            **result,
        })

    return trades


NIFTY50 = [
    "RELIANCE.NS", "HDFCBANK.NS", "TCS.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "KOTAKBANK.NS",
    "LT.NS", "AXISBANK.NS", "BAJFINANCE.NS", "MARUTI.NS", "HCLTECH.NS",
    "WIPRO.NS", "ADANIENT.NS", "SUNPHARMA.NS", "NTPC.NS", "TITAN.NS",
    "ONGC.NS", "NESTLEIND.NS", "POWERGRID.NS", "ULTRACEMCO.NS",
    "BAJAJFINSV.NS", "TECHM.NS", "HINDALCO.NS", "TATASTEEL.NS",
    "INDUSINDBK.NS", "COALINDIA.NS", "APOLLOHOSP.NS", "DRREDDY.NS",
    "BAJAJ-AUTO.NS", "EICHERMOT.NS", "CIPLA.NS", "GRASIM.NS",
    "DIVISLAB.NS", "TATACONSUM.NS", "HEROMOTOCO.NS", "SBILIFE.NS",
    "JSWSTEEL.NS", "BRITANNIA.NS", "ADANIPORTS.NS", "BPCL.NS",
    "HDFCLIFE.NS", "ASIANPAINT.NS", "SHRIRAMFIN.NS", "M&M.NS",
]


def run_backtest(csv_dir: str, start: str = "2023-01-01",
                 end: str = "2025-12-31", cost_pct: float = None,
                 max_workers: int = 8, tickers: list = None) -> dict:
    if cost_pct is None:
        cost_pct = NSE_COST_PCT

    if tickers is None:
        from bb_squeeze.data_loader import get_all_tickers_from_csv
        tickers = get_all_tickers_from_csv(csv_dir)

    all_trades = []
    done = 0

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_backtest_ticker, t, csv_dir, start, end, cost_pct): t
                   for t in tickers}
        for fut in as_completed(futures, timeout=3600):
            done += 1
            if done % 50 == 0:
                print(f"  {done}/{len(tickers)} tickers...", flush=True)
            try:
                trades = fut.result(timeout=60)
                all_trades.extend(trades)
            except Exception:
                pass

    # ── Compute stats per setup ──
    setup_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "total_pnl": 0.0,
                                       "trades": 0, "pnl_list": []})
    for t in all_trades:
        s = setup_stats[t["setup"]]
        s["trades"] += 1
        s["pnl_list"].append(t["pnl_pct"])
        s["total_pnl"] += t["pnl_pct"]
        if t["pnl_pct"] > 0:
            s["wins"] += 1
        else:
            s["losses"] += 1

    # ── Build empirical probabilities ──
    empirical_prob = {}
    summary = {}
    for setup, st in setup_stats.items():
        n = st["trades"]
        if n < 10:
            continue
        win_rate = st["wins"] / n
        avg_pnl = st["total_pnl"] / n
        pnl_arr = np.array(st["pnl_list"])
        summary[setup] = {
            "trades": n,
            "win_rate": round(win_rate, 4),
            "avg_pnl_pct": round(avg_pnl, 4),
            "median_pnl_pct": round(float(np.median(pnl_arr)), 4),
            "max_win_pct": round(float(pnl_arr.max()), 4),
            "max_loss_pct": round(float(pnl_arr.min()), 4),
            "sharpe": round(float(pnl_arr.mean() / max(pnl_arr.std(), 0.01)), 4),
        }
        empirical_prob[setup] = round(win_rate, 4)

    total_trades = len(all_trades)
    total_wins = sum(1 for t in all_trades if t["pnl_pct"] > 0)
    total_pnl = sum(t["pnl_pct"] for t in all_trades)

    results = {
        "config": {"start": start, "end": end, "cost_pct": cost_pct,
                    "tickers": len(tickers)},
        "overall": {
            "total_trades": total_trades,
            "win_rate": round(total_wins / max(total_trades, 1), 4),
            "avg_pnl_pct": round(total_pnl / max(total_trades, 1), 4),
            "total_pnl_pct": round(total_pnl, 4),
        },
        "per_setup": summary,
        "empirical_prob": empirical_prob,
        "trades": all_trades,
    }

    # ── Write outputs ──
    out_path = _ROOT / "backtest_brooks_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nFull results: {out_path}")

    if empirical_prob and total_trades >= 50:
        prob_path = _ROOT / "brooks" / "empirical_setup_prob.json"
        with open(prob_path, "w") as f:
            json.dump(empirical_prob, f, indent=2)
        print(f"Empirical probabilities: {prob_path}")
        print("  → engine.py will load these automatically on next run")
    elif total_trades < 50:
        print(f"Too few trades ({total_trades}) — empirical probs NOT updated")

    # ── Print summary ──
    print(f"\n{'='*60}")
    print(f"Brooks Backtest: {start} → {end}  (cost: {cost_pct}%)")
    print(f"{'='*60}")
    print(f"Total trades: {total_trades}  |  Win rate: {results['overall']['win_rate']*100:.1f}%  |  Avg PnL: {results['overall']['avg_pnl_pct']:.2f}%")
    print(f"\nPer setup:")
    print(f"  {'Setup':<22} {'Trades':>6} {'Win%':>6} {'AvgPnL':>8} {'Sharpe':>7}")
    print(f"  {'-'*51}")
    for setup in sorted(summary, key=lambda s: summary[s]["trades"], reverse=True):
        s = summary[setup]
        print(f"  {setup:<22} {s['trades']:>6} {s['win_rate']*100:>5.1f}% {s['avg_pnl_pct']:>+7.2f}% {s['sharpe']:>7.2f}")
    print()

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Brooks engine walk-forward backtest")
    parser.add_argument("--start", default="2023-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--cost", type=float, default=None,
                        help=f"Round-trip cost %% (default: {NSE_COST_PCT})")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--nifty50", action="store_true",
                        help="Run on Nifty 50 stocks only")
    parser.add_argument("--tickers", nargs="*", help="Specific tickers to test")
    args = parser.parse_args()

    from bb_squeeze.config import CSV_DIR

    ticker_list = None
    if args.nifty50:
        ticker_list = NIFTY50
        print(f"Backtesting Brooks engine on Nifty 50 ({len(ticker_list)} stocks)")
    elif args.tickers:
        ticker_list = args.tickers
        print(f"Backtesting Brooks engine on {len(ticker_list)} tickers")
    else:
        print(f"Backtesting Brooks engine on full universe ({CSV_DIR})")

    print(f"  Period: {args.start} → {args.end}")
    print(f"  Cost: {args.cost or NSE_COST_PCT}%")
    run_backtest(CSV_DIR, args.start, args.end, args.cost, args.workers, ticker_list)
