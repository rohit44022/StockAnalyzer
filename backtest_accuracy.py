#!/usr/bin/env python3
"""
backtest_accuracy.py — Comprehensive Historical Backtest & Accuracy Report
═══════════════════════════════════════════════════════════════════════════

Tests EVERY module of the stock analysis system against historical data:

  1. BB Method I   (Squeeze signals)   → Accuracy of BUY/SELL signals
  2. BB Method II  (Trend Following)   → Accuracy of BUY/SELL signals
  3. BB Method III (Reversals)         → Accuracy of W-Bottom/M-Top predictions
  4. BB Method IV  (Walking the Bands) → Accuracy of walk continuation
  5. Hybrid Engine                     → Accuracy of combined verdict
  6. Technical Analysis                → Accuracy of Murphy's framework
  7. Top 5 Picks Scorer               → Do high-score picks outperform?

Methodology:
  - For each stock with ≥300 bars, split data: train on first N-20 bars,
    measure ACTUAL returns over the withheld 5/10/20 bars.
  - Run the system on the train portion, record its signal.
  - Compare signal direction vs actual forward return direction.
  - A BUY is "correct" if forward return > 0.
  - A SELL is "correct" if forward return < 0.
"""

import sys, os, glob, json, time, warnings, math, traceback
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings("ignore")

# ── Project imports ──────────────────────────────────────────
from bb_squeeze.indicators import compute_all_indicators
from bb_squeeze.signals import analyze_signals
from bb_squeeze.strategies import run_all_strategies, strategy_result_to_dict
from hybrid_engine import run_hybrid_analysis

# ═══════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════
CSV_DIR = "stock_csv"
MIN_BARS = 300          # Need ≥300 bars for meaningful indicator calc + holdout
HOLDOUT_DAYS = 20       # Withhold last 20 trading days for forward returns
FORWARD_WINDOWS = [5, 10, 20]   # Measure returns at 5, 10, 20 days
MAX_STOCKS = 500        # Sample size (use 0 for ALL — very slow)
WORKERS = 8             # Parallel workers
SEED = 42               # Reproducible sampling

# ═══════════════════════════════════════════════════════════════
#  MULTIPLE TEST DATES  - test at 3 different cut points for robustness
# ═══════════════════════════════════════════════════════════════
# We test at T-20, T-60, T-100 (days from end)
# This gives 3 independent tests per stock
TEST_OFFSETS = [20, 60, 100]


# ═══════════════════════════════════════════════════════════════
#  RESULT ACCUMULATORS
# ═══════════════════════════════════════════════════════════════
@dataclass
class SignalOutcome:
    ticker: str
    method: str           # M1 / M2 / M3 / M4 / HYBRID / TA
    signal_type: str      # BUY / SELL / HOLD / etc.
    confidence: float
    cut_offset: int       # which offset was used
    price_at_signal: float
    fwd_return_5d: float  # % return 5 days later
    fwd_return_10d: float
    fwd_return_20d: float
    correct_5d: bool = False
    correct_10d: bool = False
    correct_20d: bool = False


def _nan_safe(val, default=0.0):
    try:
        v = float(val)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except (ValueError, TypeError):
        return default


# ═══════════════════════════════════════════════════════════════
#  CORE ANALYSIS FOR ONE STOCK AT ONE CUT POINT
# ═══════════════════════════════════════════════════════════════
def analyze_stock_at_cutoff(csv_path: str, offset: int) -> List[SignalOutcome]:
    """
    Load stock CSV, cut off last `offset` days, run ALL engines on the
    train portion, then measure actual forward returns.
    """
    results = []
    ticker = os.path.basename(csv_path).replace(".NS.csv", "").replace(".csv", "")

    try:
        df_full = pd.read_csv(csv_path)
        if len(df_full) < MIN_BARS + offset:
            return results

        # Split: train portion (up to cutoff) and future portion
        cut_idx = len(df_full) - offset
        df_train = df_full.iloc[:cut_idx].copy().reset_index(drop=True)
        df_future = df_full.iloc[cut_idx:].copy().reset_index(drop=True)

        if len(df_train) < MIN_BARS or len(df_future) < 5:
            return results

        price_at_signal = _nan_safe(df_train["Close"].iloc[-1])
        if price_at_signal <= 0:
            return results

        # Calculate forward returns
        fwd_returns = {}
        for w in FORWARD_WINDOWS:
            if w <= len(df_future):
                future_price = _nan_safe(df_future["Close"].iloc[w - 1])
                if future_price > 0:
                    fwd_returns[w] = ((future_price - price_at_signal) / price_at_signal) * 100
                else:
                    fwd_returns[w] = 0.0
            else:
                fwd_returns[w] = None

        if fwd_returns.get(5) is None:
            return results

        # ────────────────────────────────────────────
        # 1) BB Method I — Squeeze Signals
        # ────────────────────────────────────────────
        try:
            df_bb = compute_all_indicators(df_train.copy())
            sig = analyze_signals(ticker, df_bb)
            if sig.buy_signal or sig.sell_signal:
                sig_type = "BUY" if sig.buy_signal else "SELL"
                outcome = SignalOutcome(
                    ticker=ticker, method="M1", signal_type=sig_type,
                    confidence=_nan_safe(sig.confidence),
                    cut_offset=offset,
                    price_at_signal=price_at_signal,
                    fwd_return_5d=_nan_safe(fwd_returns.get(5, 0)),
                    fwd_return_10d=_nan_safe(fwd_returns.get(10, 0)),
                    fwd_return_20d=_nan_safe(fwd_returns.get(20, 0)),
                )
                outcome.correct_5d = (sig_type == "BUY" and outcome.fwd_return_5d > 0) or \
                                     (sig_type == "SELL" and outcome.fwd_return_5d < 0)
                outcome.correct_10d = (sig_type == "BUY" and outcome.fwd_return_10d > 0) or \
                                      (sig_type == "SELL" and outcome.fwd_return_10d < 0)
                outcome.correct_20d = (sig_type == "BUY" and outcome.fwd_return_20d > 0) or \
                                      (sig_type == "SELL" and outcome.fwd_return_20d < 0)
                results.append(outcome)
        except Exception:
            pass

        # ────────────────────────────────────────────
        # 2) BB Methods II, III, IV
        # ────────────────────────────────────────────
        try:
            df_strat = compute_all_indicators(df_train.copy())
            strat_results = run_all_strategies(df_strat)
            for sr in strat_results:
                st = sr.signal.signal_type
                if st in ("BUY", "SELL"):
                    outcome = SignalOutcome(
                        ticker=ticker, method=sr.code, signal_type=st,
                        confidence=_nan_safe(sr.signal.confidence),
                        cut_offset=offset,
                        price_at_signal=price_at_signal,
                        fwd_return_5d=_nan_safe(fwd_returns.get(5, 0)),
                        fwd_return_10d=_nan_safe(fwd_returns.get(10, 0)),
                        fwd_return_20d=_nan_safe(fwd_returns.get(20, 0)),
                    )
                    outcome.correct_5d = (st == "BUY" and outcome.fwd_return_5d > 0) or \
                                         (st == "SELL" and outcome.fwd_return_5d < 0)
                    outcome.correct_10d = (st == "BUY" and outcome.fwd_return_10d > 0) or \
                                          (st == "SELL" and outcome.fwd_return_10d < 0)
                    outcome.correct_20d = (st == "BUY" and outcome.fwd_return_20d > 0) or \
                                          (st == "SELL" and outcome.fwd_return_20d < 0)
                    results.append(outcome)
        except Exception:
            pass

        # ────────────────────────────────────────────
        # 3) Hybrid Engine + TA
        # ────────────────────────────────────────────
        try:
            hybrid = run_hybrid_analysis(df_train.copy(), ticker=ticker)
            if "error" not in hybrid:
                # Hybrid verdict
                hv = hybrid.get("hybrid_verdict", {})
                verdict = hv.get("verdict", "HOLD")
                h_conf = _nan_safe(hv.get("confidence", 0))
                h_score = _nan_safe(hv.get("score", 0))

                if verdict in ("BUY", "STRONG BUY", "SUPER STRONG BUY"):
                    h_signal = "BUY"
                elif verdict in ("SELL", "STRONG SELL", "SUPER STRONG SELL"):
                    h_signal = "SELL"
                else:
                    h_signal = "HOLD"

                if h_signal in ("BUY", "SELL"):
                    outcome = SignalOutcome(
                        ticker=ticker, method="HYBRID", signal_type=h_signal,
                        confidence=h_conf, cut_offset=offset,
                        price_at_signal=price_at_signal,
                        fwd_return_5d=_nan_safe(fwd_returns.get(5, 0)),
                        fwd_return_10d=_nan_safe(fwd_returns.get(10, 0)),
                        fwd_return_20d=_nan_safe(fwd_returns.get(20, 0)),
                    )
                    outcome.correct_5d = (h_signal == "BUY" and outcome.fwd_return_5d > 0) or \
                                         (h_signal == "SELL" and outcome.fwd_return_5d < 0)
                    outcome.correct_10d = (h_signal == "BUY" and outcome.fwd_return_10d > 0) or \
                                          (h_signal == "SELL" and outcome.fwd_return_10d < 0)
                    outcome.correct_20d = (h_signal == "BUY" and outcome.fwd_return_20d > 0) or \
                                          (h_signal == "SELL" and outcome.fwd_return_20d < 0)
                    results.append(outcome)

                # TA standalone
                ta = hybrid.get("ta_signal", {})
                ta_verdict = ta.get("verdict", "HOLD")
                ta_score = _nan_safe(ta.get("score", 0))
                ta_conf = _nan_safe(ta.get("confidence", 0))

                if ta_verdict in ("BUY", "STRONG BUY"):
                    ta_sig = "BUY"
                elif ta_verdict in ("SELL", "STRONG SELL"):
                    ta_sig = "SELL"
                else:
                    ta_sig = "HOLD"

                if ta_sig in ("BUY", "SELL"):
                    outcome = SignalOutcome(
                        ticker=ticker, method="TA", signal_type=ta_sig,
                        confidence=ta_conf, cut_offset=offset,
                        price_at_signal=price_at_signal,
                        fwd_return_5d=_nan_safe(fwd_returns.get(5, 0)),
                        fwd_return_10d=_nan_safe(fwd_returns.get(10, 0)),
                        fwd_return_20d=_nan_safe(fwd_returns.get(20, 0)),
                    )
                    outcome.correct_5d = (ta_sig == "BUY" and outcome.fwd_return_5d > 0) or \
                                         (ta_sig == "SELL" and outcome.fwd_return_5d < 0)
                    outcome.correct_10d = (ta_sig == "BUY" and outcome.fwd_return_10d > 0) or \
                                          (ta_sig == "SELL" and outcome.fwd_return_10d < 0)
                    outcome.correct_20d = (ta_sig == "BUY" and outcome.fwd_return_20d > 0) or \
                                          (ta_sig == "SELL" and outcome.fwd_return_20d < 0)
                    results.append(outcome)
        except Exception:
            pass

    except Exception:
        pass

    return results


# ═══════════════════════════════════════════════════════════════
#  PARALLEL RUNNER
# ═══════════════════════════════════════════════════════════════
def run_backtest():
    """Main backtest orchestrator."""
    print("=" * 72)
    print("  COMPREHENSIVE HISTORICAL BACKTEST — ACCURACY REPORT")
    print("=" * 72)

    # Gather CSVs
    csv_files = sorted(glob.glob(os.path.join(CSV_DIR, "*.csv")))
    print(f"\nTotal CSV files found: {len(csv_files)}")

    # Filter by minimum bars
    eligible = []
    for f in csv_files:
        try:
            n = sum(1 for _ in open(f)) - 1  # fast line count
            if n >= MIN_BARS + max(TEST_OFFSETS):
                eligible.append(f)
        except Exception:
            pass
    print(f"Stocks with ≥{MIN_BARS + max(TEST_OFFSETS)} bars: {len(eligible)}")

    # Sample if needed
    if MAX_STOCKS > 0 and len(eligible) > MAX_STOCKS:
        rng = np.random.default_rng(SEED)
        eligible = list(rng.choice(eligible, size=MAX_STOCKS, replace=False))
        print(f"Sampled {MAX_STOCKS} stocks for testing (seed={SEED})")
    else:
        print(f"Using all {len(eligible)} eligible stocks")

    total_tasks = len(eligible) * len(TEST_OFFSETS)
    print(f"Total test cases: {len(eligible)} stocks × {len(TEST_OFFSETS)} offsets = {total_tasks}")
    print(f"Forward return windows: {FORWARD_WINDOWS} trading days")
    print()

    all_outcomes: List[SignalOutcome] = []
    done = 0
    errors = 0
    t0 = time.time()

    # Build task list
    tasks = []
    for csv_path in eligible:
        for offset in TEST_OFFSETS:
            tasks.append((csv_path, offset))

    # Process in parallel
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(analyze_stock_at_cutoff, cp, off): (cp, off)
                   for cp, off in tasks}

        for future in as_completed(futures):
            done += 1
            try:
                outcomes = future.result()
                all_outcomes.extend(outcomes)
            except Exception:
                errors += 1

            if done % 200 == 0 or done == total_tasks:
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed > 0 else 0
                print(f"  [{done}/{total_tasks}] {len(all_outcomes)} signals collected | "
                      f"{rate:.1f} tests/sec | {errors} errors")

    elapsed = time.time() - t0
    print(f"\n✓ Backtest complete in {elapsed:.1f}s — {len(all_outcomes)} total signal outcomes")
    return all_outcomes


# ═══════════════════════════════════════════════════════════════
#  COMPUTE ACCURACY METRICS
# ═══════════════════════════════════════════════════════════════
def compute_accuracy(outcomes: List[SignalOutcome]) -> Dict:
    """Compute accuracy metrics grouped by method and signal type."""

    if not outcomes:
        return {"error": "No outcomes to analyze"}

    report = {}

    # Group by method
    methods = sorted(set(o.method for o in outcomes))

    for method in methods:
        method_outcomes = [o for o in outcomes if o.method == method]
        buy_outcomes = [o for o in method_outcomes if o.signal_type == "BUY"]
        sell_outcomes = [o for o in method_outcomes if o.signal_type == "SELL"]

        def calc_stats(subset, label):
            if not subset:
                return {"count": 0, "label": label}

            n = len(subset)
            acc_5 = sum(1 for o in subset if o.correct_5d) / n * 100
            acc_10 = sum(1 for o in subset if o.correct_10d) / n * 100
            acc_20 = sum(1 for o in subset if o.correct_20d) / n * 100

            avg_ret_5 = np.mean([o.fwd_return_5d for o in subset])
            avg_ret_10 = np.mean([o.fwd_return_10d for o in subset])
            avg_ret_20 = np.mean([o.fwd_return_20d for o in subset])

            # High-confidence subset (confidence ≥ 60)
            hc = [o for o in subset if o.confidence >= 60]
            hc_acc_10 = (sum(1 for o in hc if o.correct_10d) / len(hc) * 100) if hc else 0

            # Average confidence
            avg_conf = np.mean([o.confidence for o in subset])

            # Unique tickers
            tickers = len(set(o.ticker for o in subset))

            return {
                "label": label,
                "count": n,
                "unique_tickers": tickers,
                "avg_confidence": round(avg_conf, 1),
                "accuracy_5d": round(acc_5, 1),
                "accuracy_10d": round(acc_10, 1),
                "accuracy_20d": round(acc_20, 1),
                "avg_return_5d": round(avg_ret_5, 2),
                "avg_return_10d": round(avg_ret_10, 2),
                "avg_return_20d": round(avg_ret_20, 2),
                "high_conf_count": len(hc),
                "high_conf_accuracy_10d": round(hc_acc_10, 1),
            }

        report[method] = {
            "all": calc_stats(method_outcomes, f"{method} ALL"),
            "buy": calc_stats(buy_outcomes, f"{method} BUY"),
            "sell": calc_stats(sell_outcomes, f"{method} SELL"),
        }

    return report


# ═══════════════════════════════════════════════════════════════
#  TOP 5 PICKS SIMULATION
# ═══════════════════════════════════════════════════════════════
def simulate_top5_picks(outcomes: List[SignalOutcome]) -> Dict:
    """
    Simulate the Top 5 Picks engine logic:
    - For each method & direction, rank outcomes by confidence
    - Take top 5 → measure if they outperform the average signal
    """
    from collections import defaultdict

    report = {}
    methods = ["M1", "M2", "M3", "M4", "HYBRID"]

    for method in methods:
        for direction in ["BUY", "SELL"]:
            subset = [o for o in outcomes if o.method == method and o.signal_type == direction]
            if len(subset) < 10:
                continue

            # Sort by confidence, take top 5
            subset_sorted = sorted(subset, key=lambda o: o.confidence, reverse=True)
            top5 = subset_sorted[:5]
            rest = subset_sorted[5:]

            top5_acc_10 = sum(1 for o in top5 if o.correct_10d) / len(top5) * 100
            top5_ret_10 = np.mean([o.fwd_return_10d for o in top5])
            rest_acc_10 = (sum(1 for o in rest if o.correct_10d) / len(rest) * 100) if rest else 0
            rest_ret_10 = np.mean([o.fwd_return_10d for o in rest]) if rest else 0

            # Does top 5 beat the rest?
            key = f"{method}_{direction}"
            report[key] = {
                "top5_accuracy_10d": round(top5_acc_10, 1),
                "top5_avg_return_10d": round(top5_ret_10, 2),
                "top5_avg_confidence": round(np.mean([o.confidence for o in top5]), 1),
                "top5_tickers": [o.ticker for o in top5],
                "rest_accuracy_10d": round(rest_acc_10, 1),
                "rest_avg_return_10d": round(rest_ret_10, 2),
                "rest_count": len(rest),
                "top5_beats_rest": top5_acc_10 > rest_acc_10,
                "alpha_vs_rest": round(top5_ret_10 - rest_ret_10, 2),
            }

    return report


# ═══════════════════════════════════════════════════════════════
#  PRETTY PRINT REPORT
# ═══════════════════════════════════════════════════════════════
def print_report(report: Dict, top5_report: Dict, outcomes: List[SignalOutcome]):
    """Print a beautiful accuracy report."""

    METHOD_NAMES = {
        "M1": "Method I  — Squeeze Breakout",
        "M2": "Method II — Trend Following",
        "M3": "Method III — Reversals",
        "M4": "Method IV — Band Walking",
        "HYBRID": "Hybrid Engine (BB + TA)",
        "TA": "Technical Analysis (Murphy)",
    }

    print("\n" + "=" * 72)
    print("  SYSTEM ACCURACY REPORT")
    print("=" * 72)

    # ── OVERALL SUMMARY ──
    total = len(outcomes)
    total_correct_10 = sum(1 for o in outcomes if o.correct_10d)
    print(f"\n{'OVERALL':>12}: {total} signals tested | "
          f"10-day accuracy = {total_correct_10/total*100:.1f}%\n")

    # ── PER-METHOD TABLE ──
    print("─" * 72)
    print(f"{'Method':<35} {'#Sig':>5} {'Dir':>5} {'Acc@5d':>7} {'Acc@10d':>8} "
          f"{'Acc@20d':>8} {'AvgRet10d':>10} {'HiConf%':>8}")
    print("─" * 72)

    for method in ["M1", "M2", "M3", "M4", "HYBRID", "TA"]:
        if method not in report:
            continue
        mr = report[method]
        name = METHOD_NAMES.get(method, method)

        for direction in ["buy", "sell"]:
            stats = mr[direction]
            if stats["count"] == 0:
                continue
            dir_arrow = "▲ BUY" if direction == "buy" else "▼ SELL"
            hc_str = f"{stats['high_conf_accuracy_10d']:.0f}%" if stats["high_conf_count"] > 0 else "N/A"
            print(f"  {name:<33} {stats['count']:>5} {dir_arrow:>5} "
                  f"{stats['accuracy_5d']:>6.1f}% {stats['accuracy_10d']:>7.1f}% "
                  f"{stats['accuracy_20d']:>7.1f}% {stats['avg_return_10d']:>+9.2f}% "
                  f"{hc_str:>8}")

    print("─" * 72)

    # ── CONFIDENCE BREAKDOWN ──
    print("\n\n═══ CONFIDENCE vs ACCURACY (Does higher confidence predict better?) ═══\n")
    buckets = [(0, 30, "Low (0-30)"), (30, 60, "Medium (30-60)"),
               (60, 80, "High (60-80)"), (80, 101, "Very High (80-100)")]

    print(f"{'Conf. Bucket':<20} {'#Signals':>8} {'Acc@10d':>8} {'AvgRet10d':>10}")
    print("─" * 50)

    for lo, hi, label in buckets:
        bucket = [o for o in outcomes if lo <= o.confidence < hi]
        if not bucket:
            continue
        acc = sum(1 for o in bucket if o.correct_10d) / len(bucket) * 100
        ret = np.mean([o.fwd_return_10d for o in bucket])
        print(f"  {label:<18} {len(bucket):>8} {acc:>7.1f}% {ret:>+9.2f}%")

    # ── TOP 5 PICKS SIMULATION ──
    if top5_report:
        print("\n\n═══ TOP 5 PICKS SIMULATION (Do highest-confidence picks beat the rest?) ═══\n")
        print(f"{'Strategy':<16} {'Top5 Acc':>9} {'Top5 Ret':>9} {'Rest Acc':>9} "
              f"{'Rest Ret':>9} {'Alpha':>7} {'Beats?':>7}")
        print("─" * 70)
        for key in sorted(top5_report.keys()):
            t5 = top5_report[key]
            beats = "✓ YES" if t5["top5_beats_rest"] else "✗ NO"
            print(f"  {key:<14} {t5['top5_accuracy_10d']:>8.1f}% {t5['top5_avg_return_10d']:>+8.2f}% "
                  f"{t5['rest_accuracy_10d']:>8.1f}% {t5['rest_avg_return_10d']:>+8.2f}% "
                  f"{t5['alpha_vs_rest']:>+6.2f}% {beats:>7}")

    # ── METHOD-SPECIFIC INSIGHTS ──
    print("\n\n═══ KEY FINDINGS ═══\n")

    # Best method by accuracy
    best_method = None
    best_acc = 0
    for method in report:
        for direction in ["buy", "sell"]:
            stats = report[method][direction]
            if stats["count"] >= 20 and stats["accuracy_10d"] > best_acc:
                best_acc = stats["accuracy_10d"]
                best_method = f"{method} {direction.upper()}"

    if best_method:
        print(f"  ★ Best Method: {best_method} at {best_acc:.1f}% accuracy (10-day)")

    # Best by returns
    best_ret_method = None
    best_ret = -999
    for method in report:
        for direction in ["buy", "sell"]:
            stats = report[method][direction]
            if stats["count"] >= 20:
                adj_ret = stats["avg_return_10d"] if direction == "buy" else -stats["avg_return_10d"]
                if adj_ret > best_ret:
                    best_ret = adj_ret
                    best_ret_method = f"{method} {direction.upper()}"

    if best_ret_method:
        print(f"  ★ Best Returns: {best_ret_method} at {best_ret:+.2f}% avg 10-day return")

    # Signal frequency
    for method in ["M1", "M2", "M3", "M4"]:
        if method in report:
            total_all = report[method]["all"]["count"]
            if total_all > 0:
                buy_pct = report[method]["buy"]["count"] / total_all * 100 if report[method]["buy"]["count"] > 0 else 0
                print(f"  • {METHOD_NAMES[method]}: {total_all} signals "
                      f"({buy_pct:.0f}% BUY / {100-buy_pct:.0f}% SELL)")


# ═══════════════════════════════════════════════════════════════
#  GRADE THE OVERALL SYSTEM
# ═══════════════════════════════════════════════════════════════
def grade_system(report: Dict) -> str:
    """Give the overall system a letter grade based on aggregate accuracy."""
    accs = []
    for method in report:
        for direction in ["buy", "sell"]:
            stats = report[method][direction]
            if stats["count"] >= 10:
                accs.append(stats["accuracy_10d"])

    if not accs:
        return "INSUFFICIENT DATA"

    avg_acc = np.mean(accs)
    if avg_acc >= 65:
        return f"A (Excellent: {avg_acc:.1f}%)"
    elif avg_acc >= 58:
        return f"B+ (Very Good: {avg_acc:.1f}%)"
    elif avg_acc >= 53:
        return f"B (Good: {avg_acc:.1f}%)"
    elif avg_acc >= 50:
        return f"C+ (Above Random: {avg_acc:.1f}%)"
    elif avg_acc >= 45:
        return f"C (Near Random: {avg_acc:.1f}%)"
    else:
        return f"D (Below Random: {avg_acc:.1f}%)"


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    outcomes = run_backtest()

    if not outcomes:
        print("\n✗ No signal outcomes generated. Check data availability.")
        sys.exit(1)

    # Compute accuracy
    report = compute_accuracy(outcomes)
    top5_report = simulate_top5_picks(outcomes)

    # Print beautiful report
    print_report(report, top5_report, outcomes)

    # Overall system grade
    grade = grade_system(report)
    print(f"\n{'=' * 72}")
    print(f"  OVERALL SYSTEM GRADE: {grade}")
    print(f"{'=' * 72}")
    print(f"\n  (Random guessing = 50%. Anything > 55% is meaningful edge.)")
    print(f"  (Professional quant systems target 55-65% directional accuracy.)\n")

    # Save raw results
    raw_data = []
    for o in outcomes:
        raw_data.append({
            "ticker": o.ticker, "method": o.method, "signal": o.signal_type,
            "confidence": o.confidence, "offset": o.cut_offset,
            "price": o.price_at_signal,
            "fwd_5d": o.fwd_return_5d, "fwd_10d": o.fwd_return_10d, "fwd_20d": o.fwd_return_20d,
            "correct_5d": o.correct_5d, "correct_10d": o.correct_10d, "correct_20d": o.correct_20d,
        })

    outfile = "backtest_results.json"
    with open(outfile, "w") as f:
        json.dump({
            "summary": {
                "total_signals": len(outcomes),
                "grade": grade,
                "methods_tested": list(report.keys()),
            },
            "accuracy_report": {m: {k: v for k, v in mr.items()} for m, mr in report.items()},
            "top5_simulation": top5_report,
            "raw_outcomes": raw_data,
        }, f, indent=2)
    print(f"  Raw results saved to {outfile}")
