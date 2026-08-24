"""
backtest_pipeline.py — Walk-Forward Backtest of Full Top Picks Pipeline
=======================================================================

Simulates the complete Top Picks pipeline on Nifty 50 stocks over all
available historical data. Runs every Friday, picks the Top 5 BUY stocks,
and measures their forward returns (5-day, 10-day, 20-day).

Compares:
  A) Pipeline WITH strict weekly filter  (BULLISH weekly only)
  B) Pipeline WITHOUT weekly filter       (strict checklist alone)

This tells us whether the weekly BB confirmation actually improves returns.

Usage:
    python3 backtest_pipeline.py
    python3 backtest_pipeline.py --method M1          # Default
    python3 backtest_pipeline.py --method M2
    python3 backtest_pipeline.py --method M1 --workers 4
"""

from __future__ import annotations
import argparse
import os
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from bb_squeeze.data_loader import load_stock_data
from bb_squeeze.indicators import compute_all_indicators
from bb_squeeze.signals import analyze_signals
from bb_squeeze.strategies import run_all_strategies, strategy_result_to_dict
from bb_squeeze.weekly_confirmation import compute_weekly_view
from bb_squeeze.config import CSV_DIR
from hybrid_pa_engine import run_triple_analysis
from top_picks.config import (
    MIN_BB_CONFIDENCE, MIN_COMPOSITE_SCORE, TOP_N,
)
from top_picks.scorer import compute_composite_score
from top_picks.engine import pick_passes_strict_checklist, pick_passes_weekly_filter

# ─────────────────────────────────────────────────────────────
#  NIFTY 50 TICKERS (48 available in CSV)
# ─────────────────────────────────────────────────────────────
NIFTY_50 = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BPCL",
    "BHARTIARTL", "BRITANNIA", "CIPLA", "COALINDIA", "DRREDDY",
    "EICHERMOT", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE",
    "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK", "ITC",
    "INDUSINDBK", "INFY", "JSWSTEEL", "KOTAKBANK", "LT",
    "M&M", "MARUTI", "NTPC", "NESTLEIND",
    "ONGC", "POWERGRID", "RELIANCE", "SBILIFE", "SBIN",
    "SUNPHARMA", "TCS", "TATACONSUM", "TATASTEEL",
    "TECHM", "TITAN", "ULTRACEMCO", "WIPRO", "SHRIRAMFIN",
]

WARMUP_BARS = 150   # need enough for weekly BB (20-week) + indicators
CAPITAL = 500_000


def _safe(val, default=0):
    if val is None:
        return default
    try:
        v = float(val)
        return v if np.isfinite(v) else default
    except (TypeError, ValueError):
        return default


# ─────────────────────────────────────────────────────────────
#  Load all Nifty 50 data upfront
# ─────────────────────────────────────────────────────────────
def load_all_data() -> dict[str, pd.DataFrame]:
    data = {}
    for ticker in NIFTY_50:
        csv_path = os.path.join(CSV_DIR, f"{ticker}.NS.csv")
        if not os.path.exists(csv_path):
            continue
        df = pd.read_csv(csv_path, parse_dates=["Date"])
        df = df.sort_values("Date").reset_index(drop=True)
        if len(df) >= WARMUP_BARS:
            data[f"{ticker}.NS"] = df
    return data


# ─────────────────────────────────────────────────────────────
#  Simulate signals for one stock on a given date slice
# ─────────────────────────────────────────────────────────────
def _get_signal_for_slice(ticker: str, df_slice: pd.DataFrame, method: str):
    """Run BB signals on a data slice. Returns (signal_type, confidence) or None."""
    try:
        df_ind = compute_all_indicators(df_slice.copy())
        sig = analyze_signals(ticker, df_ind)

        if sig.phase in ("INSUFFICIENT_DATA", "ERROR"):
            return None

        if method == "M1":
            if sig.buy_signal:
                return ("BUY", sig.confidence)
            elif sig.sell_signal:
                return ("SELL", sig.confidence)
            return None
        else:
            strats = run_all_strategies(df_ind)
            for sr in strats:
                if sr.code == method:
                    sig_type = sr.signal.signal_type if sr.signal else "NONE"
                    conf = sr.signal.confidence if sr.signal else 0
                    if sig_type in ("BUY", "SELL"):
                        return (sig_type, conf)
            return None
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
#  Deep analyze one stock for a date slice (simplified for speed)
# ─────────────────────────────────────────────────────────────
def _deep_analyze_for_backtest(
    ticker: str,
    df_slice: pd.DataFrame,
    bb_confidence: float,
    bb_signal_type: str,
    method: str,
    signal_filter: str,
) -> Optional[dict]:
    """Simplified deep analysis for backtest — skips fundamentals."""
    try:
        triple = run_triple_analysis(df_slice, ticker=ticker, capital=CAPITAL)
        if "error" in triple:
            return None

        pa_flat = None
        try:
            pa_raw = triple.get("pa_data", {})
            if pa_raw and pa_raw.get("signal_type"):
                pa_flat = {
                    "success": True,
                    "pa_score": pa_raw.get("pa_score", 0),
                    "confidence": pa_raw.get("confidence", 0),
                    "pa_verdict": pa_raw.get("signal_type", "HOLD"),
                    "signal_type": pa_raw.get("signal_type", ""),
                    "signal_strength": pa_raw.get("strength", ""),
                }
        except Exception:
            pass

        ta_signal = triple.get("ta_signal", {})
        data_freshness = triple.get("data_freshness", {})
        bb_data = triple.get("bb_data", {})
        target_prices = triple.get("target_prices", {})

        bb_ind = bb_data.get("indicators", {})
        _vol = _safe(bb_ind.get("volume"), 0)
        _vol_sma = _safe(bb_ind.get("vol_sma50"), 0)
        volume_ratio = (_vol / _vol_sma) if _vol_sma > 0 else None

        scoring = compute_composite_score(
            bb_confidence=bb_confidence,
            bb_signal_type=bb_signal_type,
            ta_signal=ta_signal,
            hybrid_result=triple,
            data_freshness=data_freshness,
            method=method,
            signal_filter=signal_filter,
            pa_result=pa_flat,
            volume_ratio=volume_ratio,
        )

        # Weekly confirmation
        df_weekly = df_slice.copy()
        if not isinstance(df_weekly.index, pd.DatetimeIndex):
            df_weekly.index = pd.to_datetime(df_weekly["Date"])
        wc = compute_weekly_view(df_weekly)

        current_price = _safe(
            bb_data.get("indicators", {}).get("price") or
            triple.get("snapshot", {}).get("close"),
            float(df_slice["Close"].iloc[-1])
        )
        stop_loss = _safe(bb_data.get("stop_loss"), 0)

        return {
            "ticker": ticker,
            "ticker_display": ticker.replace(".NS", ""),
            "current_price": current_price,
            "composite_score": scoring["composite_score"],
            "grade": scoring["grade"],
            "components": scoring["components"],
            "reasons": scoring["reasons"],
            "warnings": scoring["warnings"],
            "bb_signal_type": bb_signal_type,
            "bb_confidence": bb_confidence,
            "bb_conditions": bb_data.get("conditions", {}),
            "bb_short_conditions": bb_data.get("short_conditions", {}),
            "bb_strategies": triple.get("bb_strategies", []),
            "stop_loss": stop_loss,
            "rr_ratio": _safe(target_prices.get("risk_reward_ratio")) if target_prices else None,
            "weekly_confirmation": wc,
        }
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
#  Run pipeline for one date
# ─────────────────────────────────────────────────────────────
def run_pipeline_for_date(
    all_data: dict[str, pd.DataFrame],
    eval_date: pd.Timestamp,
    method: str,
    signal_filter: str = "BUY",
    max_workers: int = 4,
) -> dict:
    """
    Simulate the full Top Picks pipeline for a single evaluation date.

    Returns dict with:
      picks_with_weekly: top 5 after weekly filter
      picks_without_weekly: top 5 without weekly filter (for comparison)
      all_strict: all picks that passed strict checklist
    """

    # Step 1: Slice data up to eval_date, get signals
    candidates = []
    for ticker, df_full in all_data.items():
        mask = df_full["Date"] <= eval_date
        df_slice = df_full[mask].copy()
        if len(df_slice) < WARMUP_BARS:
            continue

        result = _get_signal_for_slice(ticker, df_slice, method)
        if result is None:
            continue

        sig_type, confidence = result
        if sig_type != signal_filter:
            continue
        if confidence < MIN_BB_CONFIDENCE:
            continue

        candidates.append({
            "ticker": ticker,
            "confidence": confidence,
            "signal_type": sig_type,
            "df_slice": df_slice,
        })

    if not candidates:
        return {"picks_with_weekly": [], "picks_without_weekly": [], "all_strict": []}

    # Step 2: Deep analysis (parallel)
    scored = []

    def _analyze(c):
        return _deep_analyze_for_backtest(
            c["ticker"], c["df_slice"], c["confidence"],
            c["signal_type"], method, signal_filter,
        )

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_analyze, c): c for c in candidates}
        for f in as_completed(futures):
            try:
                r = f.result()
                if r and r["composite_score"] >= MIN_COMPOSITE_SCORE:
                    scored.append(r)
            except Exception:
                pass

    scored.sort(key=lambda x: x["composite_score"], reverse=True)

    # Step 3: Strict checklist
    strict_picks = [
        p for p in scored
        if pick_passes_strict_checklist(p, method, signal_filter)
    ]

    # Step 4a: WITHOUT weekly filter — top 5
    picks_without_weekly = strict_picks[:TOP_N]

    # Step 4b: WITH weekly filter — top 5
    weekly_filtered = [
        p for p in strict_picks
        if pick_passes_weekly_filter(p, signal_filter)
    ]
    picks_with_weekly = weekly_filtered[:TOP_N]

    return {
        "picks_with_weekly": picks_with_weekly,
        "picks_without_weekly": picks_without_weekly,
        "all_strict": strict_picks,
    }


# ─────────────────────────────────────────────────────────────
#  Measure forward returns for a pick
# ─────────────────────────────────────────────────────────────
def get_forward_returns(
    all_data: dict[str, pd.DataFrame],
    ticker: str,
    entry_date: pd.Timestamp,
    entry_price: float,
    horizons: list[int] = [5, 10, 20],
) -> dict:
    """Get forward returns at multiple horizons from entry_date."""
    df = all_data.get(ticker)
    if df is None:
        return {}

    future = df[df["Date"] > entry_date].head(max(horizons))
    if len(future) == 0:
        return {}

    returns = {}
    for h in horizons:
        if len(future) >= h:
            future_price = float(future.iloc[h - 1]["Close"])
            returns[f"ret_{h}d"] = (future_price - entry_price) / entry_price * 100
        else:
            returns[f"ret_{h}d"] = None
    return returns


# ─────────────────────────────────────────────────────────────
#  Main backtest loop
# ─────────────────────────────────────────────────────────────
def run_backtest(method: str = "M1", max_workers: int = 4):
    print("=" * 70)
    print(f"  FULL PIPELINE WALK-FORWARD BACKTEST — {method}")
    print(f"  Universe: Nifty 50 ({len(NIFTY_50)} tickers)")
    print("=" * 70)
    print()

    # Load all data
    print("Loading all Nifty 50 CSV data...")
    t0 = time.time()
    all_data = load_all_data()
    print(f"  Loaded {len(all_data)} stocks in {time.time()-t0:.1f}s")

    # Determine evaluation dates (every Friday in the data range)
    sample_ticker = list(all_data.keys())[0]
    all_dates = all_data[sample_ticker]["Date"]
    # Start after warmup, end 20 days before data end (need forward returns)
    start_idx = WARMUP_BARS
    end_idx = len(all_dates) - 25

    eval_dates = []
    for i in range(start_idx, end_idx):
        d = all_dates.iloc[i]
        if d.weekday() == 4:  # Friday
            eval_dates.append(d)

    # Subsample to bi-weekly if too many dates (speed vs resolution)
    if len(eval_dates) > 60:
        eval_dates = eval_dates[::2]

    print(f"  Evaluation dates: {len(eval_dates)} "
          f"({eval_dates[0].strftime('%Y-%m-%d')} to {eval_dates[-1].strftime('%Y-%m-%d')})")
    print(f"  Workers: {max_workers}")
    print()

    # Results storage
    all_trades_with = []      # trades with weekly filter
    all_trades_without = []   # trades without weekly filter
    weekly_stats = {"total_picks_with": 0, "total_picks_without": 0,
                    "weeks_with_picks": 0, "weeks_without_picks": 0}

    for idx, eval_date in enumerate(eval_dates):
        date_str = eval_date.strftime("%Y-%m-%d")
        elapsed_pct = (idx + 1) / len(eval_dates) * 100
        print(f"\r  [{idx+1}/{len(eval_dates)}] {date_str} "
              f"({elapsed_pct:.0f}%)  ", end="", flush=True)

        result = run_pipeline_for_date(
            all_data, eval_date, method, "BUY", max_workers
        )

        # Track picks WITH weekly filter
        for pick in result["picks_with_weekly"]:
            fwd = get_forward_returns(
                all_data, pick["ticker"], eval_date, pick["current_price"]
            )
            all_trades_with.append({
                "date": date_str,
                "ticker": pick["ticker_display"],
                "price": pick["current_price"],
                "score": pick["composite_score"],
                "grade": pick["grade"],
                "weekly_trend": pick.get("weekly_confirmation", {}).get("weekly_trend", "N/A"),
                **fwd,
            })

        # Track picks WITHOUT weekly filter
        for pick in result["picks_without_weekly"]:
            fwd = get_forward_returns(
                all_data, pick["ticker"], eval_date, pick["current_price"]
            )
            all_trades_without.append({
                "date": date_str,
                "ticker": pick["ticker_display"],
                "price": pick["current_price"],
                "score": pick["composite_score"],
                "grade": pick["grade"],
                "weekly_trend": pick.get("weekly_confirmation", {}).get("weekly_trend", "N/A"),
                **fwd,
            })

        if result["picks_with_weekly"]:
            weekly_stats["weeks_with_picks"] += 1
        if result["picks_without_weekly"]:
            weekly_stats["weeks_without_picks"] += 1
        weekly_stats["total_picks_with"] += len(result["picks_with_weekly"])
        weekly_stats["total_picks_without"] += len(result["picks_without_weekly"])

    print("\n")

    # ── Build results ──
    df_with = pd.DataFrame(all_trades_with) if all_trades_with else pd.DataFrame()
    df_without = pd.DataFrame(all_trades_without) if all_trades_without else pd.DataFrame()

    _print_results(df_with, df_without, weekly_stats, method)

    # Save to CSV
    out_dir = os.path.join(_ROOT, "logs")
    os.makedirs(out_dir, exist_ok=True)

    if not df_with.empty:
        path_w = os.path.join(out_dir, f"backtest_{method}_with_weekly.csv")
        df_with.to_csv(path_w, index=False)
        print(f"\n  Saved: {path_w}")
    if not df_without.empty:
        path_wo = os.path.join(out_dir, f"backtest_{method}_without_weekly.csv")
        df_without.to_csv(path_wo, index=False)
        print(f"  Saved: {path_wo}")

    return df_with, df_without


def _print_results(df_with, df_without, stats, method):
    print("=" * 70)
    print(f"  BACKTEST RESULTS — {method} BUY")
    print("=" * 70)

    for label, df in [("WITH weekly filter (BULLISH only)", df_with),
                      ("WITHOUT weekly filter (checklist only)", df_without)]:
        print(f"\n  ── {label} ──")
        if df.empty:
            print("    No trades generated.")
            continue

        n = len(df)
        print(f"    Total trades: {n}")

        for horizon in ["ret_5d", "ret_10d", "ret_20d"]:
            col = df[horizon].dropna()
            if col.empty:
                continue
            wins = (col > 0).sum()
            total = len(col)
            win_rate = wins / total * 100
            avg = col.mean()
            med = col.median()
            best = col.max()
            worst = col.min()
            h_name = horizon.replace("ret_", "").replace("d", "-day")
            print(f"\n    {h_name} Forward Returns:")
            print(f"      Win Rate:   {win_rate:.1f}% ({wins}/{total})")
            print(f"      Avg Return: {avg:+.2f}%")
            print(f"      Median:     {med:+.2f}%")
            print(f"      Best:       {best:+.2f}%")
            print(f"      Worst:      {worst:+.2f}%")

        # Grade distribution
        if "grade" in df.columns:
            print(f"\n    Grade distribution:")
            for g in ["A+", "A", "B+", "B", "C", "D", "F"]:
                ct = (df["grade"] == g).sum()
                if ct > 0:
                    print(f"      {g}: {ct} ({ct/n*100:.0f}%)")

        # Weekly trend distribution
        if "weekly_trend" in df.columns:
            print(f"\n    Weekly trend distribution:")
            for t in df["weekly_trend"].value_counts().items():
                print(f"      {t[0]}: {t[1]}")

    # ── Head-to-head comparison ──
    print(f"\n  ── HEAD-TO-HEAD COMPARISON ──")
    print(f"    Weeks with picks (with weekly):    {stats['weeks_with_picks']}")
    print(f"    Weeks with picks (without weekly): {stats['weeks_without_picks']}")
    print(f"    Total picks (with weekly):    {stats['total_picks_with']}")
    print(f"    Total picks (without weekly): {stats['total_picks_without']}")

    if not df_with.empty and not df_without.empty:
        for horizon in ["ret_5d", "ret_10d", "ret_20d"]:
            w = df_with[horizon].dropna()
            wo = df_without[horizon].dropna()
            if w.empty or wo.empty:
                continue
            h_name = horizon.replace("ret_", "").replace("d", "-day")
            diff_avg = w.mean() - wo.mean()
            diff_wr = (w > 0).mean() * 100 - (wo > 0).mean() * 100
            print(f"\n    {h_name}:")
            print(f"      Avg return improvement: {diff_avg:+.2f}%")
            print(f"      Win rate improvement:   {diff_wr:+.1f}%")
            verdict = "WEEKLY FILTER HELPS" if diff_avg > 0 and diff_wr > 0 else (
                "MIXED RESULTS" if diff_avg > 0 or diff_wr > 0 else "NO IMPROVEMENT"
            )
            print(f"      Verdict: {verdict}")

    print()
    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Walk-Forward Pipeline Backtest")
    parser.add_argument("--method", default="M1", choices=["M1", "M2", "M3", "M4"])
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--enhanced", action="store_true",
                        help="Already active — reweighted scoring + volume quality "
                             "are applied via config. This flag is a no-op marker.")
    args = parser.parse_args()

    run_backtest(method=args.method, max_workers=args.workers)
