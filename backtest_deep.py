#!/usr/bin/env python3
"""
backtest_deep.py — Deep Multi-Regime Historical Backtest
════════════════════════════════════════════════════════════

Fixes limitations of the initial backtest:
  1. Tests across MANY time offsets (20 to 500 days back) to cover
     bull + bear + sideways markets
  2. Measures RELATIVE accuracy: do BUY-flagged stocks outperform
     SELL-flagged stocks? (market-neutral metric)
  3. Computes "Value-Added" vs naive buy-and-hold
  4. Tests if confidence correlates with outcomes
  5. Simulates a paper portfolio following Top 5 Picks
"""

import sys, os, glob, json, time, warnings, math, traceback
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict

warnings.filterwarnings("ignore")

from bb_squeeze.indicators import compute_all_indicators
from bb_squeeze.signals import analyze_signals
from bb_squeeze.strategies import run_all_strategies, strategy_result_to_dict
from hybrid_engine import run_hybrid_analysis

# ═══════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════
CSV_DIR = "stock_csv"
MIN_BARS = 250
FORWARD_WINDOW = 10         # primary measurement window (trading days)
MAX_STOCKS = 400            # sample size
WORKERS = 8
SEED = 42

# Test at MANY cut points — spans ~2 years of different market regimes
TEST_OFFSETS = [20, 40, 60, 80, 100, 130, 160, 200, 250, 300, 350, 400, 450, 500]


def _nan_safe(val, default=0.0):
    try:
        v = float(val)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except (ValueError, TypeError):
        return default


@dataclass
class TestResult:
    ticker: str
    method: str
    signal_type: str   # BUY / SELL
    confidence: float
    offset: int
    price_at_signal: float
    fwd_return: float  # % return at FORWARD_WINDOW days
    correct: bool      # signal direction matched actual return direction


def analyze_stock_one_offset(csv_path: str, offset: int) -> List[TestResult]:
    """Analyze one stock at one cutoff point."""
    results = []
    ticker = os.path.basename(csv_path).replace(".NS.csv", "").replace(".csv", "")

    try:
        df_full = pd.read_csv(csv_path)
        if len(df_full) < MIN_BARS + offset:
            return results

        cut_idx = len(df_full) - offset
        df_train = df_full.iloc[:cut_idx].copy().reset_index(drop=True)
        df_future = df_full.iloc[cut_idx:].copy().reset_index(drop=True)

        if len(df_train) < MIN_BARS or len(df_future) < FORWARD_WINDOW:
            return results

        price_now = _nan_safe(df_train["Close"].iloc[-1])
        price_fwd = _nan_safe(df_future["Close"].iloc[FORWARD_WINDOW - 1])
        if price_now <= 0 or price_fwd <= 0:
            return results
        fwd_ret = ((price_fwd - price_now) / price_now) * 100

        # ── Run ALL engines ──────────────────────────
        signals_found = []   # (method, signal_type, confidence)

        # M1 Squeeze
        try:
            df_bb = compute_all_indicators(df_train.copy())
            sig = analyze_signals(ticker, df_bb)
            if sig.buy_signal:
                signals_found.append(("M1", "BUY", _nan_safe(sig.confidence)))
            elif sig.sell_signal:
                signals_found.append(("M1", "SELL", _nan_safe(sig.confidence)))
        except Exception:
            pass

        # M2-M4
        try:
            df_strat = compute_all_indicators(df_train.copy())
            for sr in run_all_strategies(df_strat):
                st = sr.signal.signal_type
                if st in ("BUY", "SELL"):
                    signals_found.append((sr.code, st, _nan_safe(sr.signal.confidence)))
        except Exception:
            pass

        # Hybrid + TA
        try:
            hybrid = run_hybrid_analysis(df_train.copy(), ticker=ticker)
            if "error" not in hybrid:
                hv = hybrid.get("hybrid_verdict", {})
                verdict = hv.get("verdict", "HOLD")
                h_conf = _nan_safe(hv.get("confidence", 0))

                if verdict in ("BUY", "STRONG BUY", "SUPER STRONG BUY"):
                    signals_found.append(("HYBRID", "BUY", h_conf))
                elif verdict in ("SELL", "STRONG SELL", "SUPER STRONG SELL"):
                    signals_found.append(("HYBRID", "SELL", h_conf))

                ta = hybrid.get("ta_signal", {})
                ta_v = ta.get("verdict", "HOLD")
                ta_conf = _nan_safe(ta.get("confidence", 0))
                if ta_v in ("BUY", "STRONG BUY"):
                    signals_found.append(("TA", "BUY", ta_conf))
                elif ta_v in ("SELL", "STRONG SELL"):
                    signals_found.append(("TA", "SELL", ta_conf))
        except Exception:
            pass

        # Convert to TestResult
        for method, sig_type, conf in signals_found:
            correct = (sig_type == "BUY" and fwd_ret > 0) or \
                      (sig_type == "SELL" and fwd_ret < 0)
            results.append(TestResult(
                ticker=ticker, method=method, signal_type=sig_type,
                confidence=conf, offset=offset,
                price_at_signal=price_now, fwd_return=fwd_ret, correct=correct
            ))

    except Exception:
        pass

    return results


def run_deep_backtest():
    """Main backtest runner."""
    print("=" * 74)
    print("  DEEP MULTI-REGIME BACKTEST — SYSTEM ACCURACY REPORT")
    print("=" * 74)

    csv_files = sorted(glob.glob(os.path.join(CSV_DIR, "*.csv")))
    print(f"\nTotal CSVs: {len(csv_files)}")

    # Eligible: need enough bars for longest offset + indicators
    max_off = max(TEST_OFFSETS)
    eligible = []
    for f in csv_files:
        try:
            n = sum(1 for _ in open(f)) - 1
            if n >= MIN_BARS + max_off:
                eligible.append(f)
        except Exception:
            pass
    print(f"Stocks with ≥{MIN_BARS + max_off} bars: {len(eligible)}")

    if MAX_STOCKS > 0 and len(eligible) > MAX_STOCKS:
        rng = np.random.default_rng(SEED)
        eligible = list(rng.choice(eligible, size=MAX_STOCKS, replace=False))
        print(f"Sampled {MAX_STOCKS} stocks (seed={SEED})")

    total_tasks = len(eligible) * len(TEST_OFFSETS)
    print(f"Test matrix: {len(eligible)} stocks × {len(TEST_OFFSETS)} offsets = {total_tasks}")
    print(f"Offsets: {TEST_OFFSETS}")
    print(f"Forward return window: {FORWARD_WINDOW} trading days\n")

    all_results: List[TestResult] = []
    done = 0
    t0 = time.time()

    tasks = [(f, off) for f in eligible for off in TEST_OFFSETS]

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(analyze_stock_one_offset, f, off): (f, off)
                   for f, off in tasks}
        for fut in as_completed(futures):
            done += 1
            try:
                all_results.extend(fut.result())
            except Exception:
                pass
            if done % 500 == 0 or done == total_tasks:
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed > 0 else 0
                print(f"  [{done}/{total_tasks}] {len(all_results)} signals | "
                      f"{rate:.1f} tasks/sec")

    elapsed = time.time() - t0
    print(f"\n✓ Complete in {elapsed:.1f}s — {len(all_results)} signal outcomes\n")
    return all_results


def analyze_results(results: List[TestResult]):
    """Comprehensive multi-dimensional analysis."""

    if not results:
        print("No results to analyze.")
        return

    MN = {
        "M1": "Method I  (Squeeze)",
        "M2": "Method II (Trend)",
        "M3": "Method III (Reversal)",
        "M4": "Method IV (Walk)",
        "HYBRID": "Hybrid Engine",
        "TA": "Technical Analysis",
    }

    # ═══════════════════════════════════════════════════
    #  1) PER-METHOD ACCURACY TABLE
    # ═══════════════════════════════════════════════════
    print("=" * 74)
    print("  1. PER-METHOD DIRECTIONAL ACCURACY")
    print("=" * 74)
    print(f"\n{'Method':<26} {'Dir':>5} {'Signals':>8} {'Correct':>8} "
          f"{'Accuracy':>8} {'AvgRet':>8} {'AvgConf':>8}")
    print("─" * 74)

    method_summary = {}
    for method in ["M1", "M2", "M3", "M4", "HYBRID", "TA"]:
        for direction in ["BUY", "SELL"]:
            subset = [r for r in results if r.method == method and r.signal_type == direction]
            if not subset:
                continue
            n = len(subset)
            correct = sum(1 for r in subset if r.correct)
            acc = correct / n * 100
            avg_ret = np.mean([r.fwd_return for r in subset])
            avg_conf = np.mean([r.confidence for r in subset])

            arrow = "▲" if direction == "BUY" else "▼"
            name = MN.get(method, method)
            print(f"  {name:<24} {arrow} {direction:<4} {n:>7} {correct:>8} "
                  f"{acc:>7.1f}% {avg_ret:>+7.2f}% {avg_conf:>7.1f}")

            key = f"{method}_{direction}"
            method_summary[key] = {"n": n, "correct": correct, "acc": acc,
                                   "avg_ret": avg_ret, "avg_conf": avg_conf}
    print("─" * 74)

    # ═══════════════════════════════════════════════════
    #  2) MARKET-REGIME ANALYSIS
    # ═══════════════════════════════════════════════════
    print(f"\n\n{'=' * 74}")
    print("  2. ACCURACY BY MARKET REGIME (offset → different time periods)")
    print("=" * 74)

    # Group by offset — each offset is a different market regime
    print(f"\n{'Offset':>7} {'Mkt Avg Ret':>12} {'Regime':>10} "
          f"{'#BUY':>6} {'BUY Acc':>8} {'#SELL':>6} {'SELL Acc':>8}")
    print("─" * 74)

    offsets = sorted(set(r.offset for r in results))
    bull_results = []
    bear_results = []
    for off in offsets:
        off_results = [r for r in results if r.offset == off]
        off_rets = [r.fwd_return for r in off_results]
        mkt_avg = np.mean(off_rets) if off_rets else 0

        buys = [r for r in off_results if r.signal_type == "BUY"]
        sells = [r for r in off_results if r.signal_type == "SELL"]
        buy_acc = (sum(1 for r in buys if r.correct) / len(buys) * 100) if buys else 0
        sell_acc = (sum(1 for r in sells if r.correct) / len(sells) * 100) if sells else 0

        regime = "BULL" if mkt_avg > 1.5 else ("BEAR" if mkt_avg < -1.5 else "SIDEWAYS")
        if regime == "BULL":
            bull_results.extend(off_results)
        elif regime == "BEAR":
            bear_results.extend(off_results)

        print(f"  T-{off:>4} {mkt_avg:>+11.2f}% {regime:>10} "
              f"{len(buys):>6} {buy_acc:>7.1f}% {len(sells):>6} {sell_acc:>7.1f}%")

    print("─" * 74)

    # ═══════════════════════════════════════════════════
    #  3) BULL vs BEAR REGIME ACCURACY
    # ═══════════════════════════════════════════════════
    print(f"\n\n{'=' * 74}")
    print("  3. BULL vs BEAR REGIME ACCURACY")
    print("=" * 74)

    for regime_name, regime_data in [("BULL Market Periods", bull_results),
                                      ("BEAR Market Periods", bear_results)]:
        if not regime_data:
            continue
        print(f"\n  ── {regime_name} ({len(regime_data)} signals) ──")
        buys = [r for r in regime_data if r.signal_type == "BUY"]
        sells = [r for r in regime_data if r.signal_type == "SELL"]
        if buys:
            buy_acc = sum(1 for r in buys if r.correct) / len(buys) * 100
            buy_ret = np.mean([r.fwd_return for r in buys])
            print(f"    BUY signals:  {len(buys):>5} | Accuracy: {buy_acc:>5.1f}% | Avg Return: {buy_ret:>+6.2f}%")
        if sells:
            sell_acc = sum(1 for r in sells if r.correct) / len(sells) * 100
            sell_ret = np.mean([r.fwd_return for r in sells])
            print(f"    SELL signals: {len(sells):>5} | Accuracy: {sell_acc:>5.1f}% | Avg Return: {sell_ret:>+6.2f}%")

    # ═══════════════════════════════════════════════════
    #  4) BUY vs SELL RELATIVE PERFORMANCE
    # ═══════════════════════════════════════════════════
    print(f"\n\n{'=' * 74}")
    print("  4. SIGNAL SEPARATION POWER (Do BUY stocks outperform SELL stocks?)")
    print("=" * 74)
    print(f"\n  This is the MOST IMPORTANT test: regardless of market direction,")
    print(f"  do stocks flagged BUY have HIGHER returns than stocks flagged SELL?\n")

    for method in ["M1", "M2", "M3", "M4", "HYBRID", "TA"]:
        buys = [r for r in results if r.method == method and r.signal_type == "BUY"]
        sells = [r for r in results if r.method == method and r.signal_type == "SELL"]
        if len(buys) < 5 or len(sells) < 5:
            continue
        buy_ret = np.mean([r.fwd_return for r in buys])
        sell_ret = np.mean([r.fwd_return for r in sells])
        spread = buy_ret - sell_ret
        correct_separation = spread > 0
        symbol = "✓" if correct_separation else "✗"
        name = MN.get(method, method)
        print(f"  {name:<24} BUY avg: {buy_ret:>+6.2f}%  SELL avg: {sell_ret:>+6.2f}%  "
              f"Spread: {spread:>+6.2f}% {symbol}")

    # ═══════════════════════════════════════════════════
    #  5) CONFIDENCE vs ACCURACY
    # ═══════════════════════════════════════════════════
    print(f"\n\n{'=' * 74}")
    print("  5. CONFIDENCE CALIBRATION (Does higher confidence = better results?)")
    print("=" * 74)

    buckets = [(0, 20), (20, 40), (40, 60), (60, 80), (80, 101)]
    print(f"\n{'Conf Range':<15} {'#Signals':>8} {'Accuracy':>8} {'Avg Return':>10}")
    print("─" * 45)
    for lo, hi in buckets:
        bucket = [r for r in results if lo <= r.confidence < hi]
        if not bucket:
            continue
        acc = sum(1 for r in bucket if r.correct) / len(bucket) * 100
        ret = np.mean([r.fwd_return for r in bucket])
        print(f"  {lo}-{hi-1:>3}         {len(bucket):>8} {acc:>7.1f}% {ret:>+9.2f}%")

    # ═══════════════════════════════════════════════════
    #  6) TOP 5 PICKS SIMULATION (per method, per direction, per regime)
    # ═══════════════════════════════════════════════════
    print(f"\n\n{'=' * 74}")
    print("  6. TOP 5 PICKS PORTFOLIO SIMULATION")
    print("=" * 74)
    print(f"\n  For each offset, take top-5 by confidence → measure if they beat the rest.\n")

    top5_wins = 0
    top5_total = 0
    top5_all_alpha = []

    for method in ["M1", "M2", "M3", "M4", "HYBRID", "TA"]:
        for direction in ["BUY", "SELL"]:
            method_dir = [r for r in results if r.method == method and r.signal_type == direction]
            if len(method_dir) < 15:
                continue

            # Group by offset, take top5 per offset
            by_offset = defaultdict(list)
            for r in method_dir:
                by_offset[r.offset].append(r)

            t5_correct = 0
            t5_total_local = 0
            t5_rets = []
            rest_rets = []

            for off, off_signals in by_offset.items():
                if len(off_signals) < 8:
                    continue
                sorted_sigs = sorted(off_signals, key=lambda r: r.confidence, reverse=True)
                t5 = sorted_sigs[:5]
                rest = sorted_sigs[5:]

                for r in t5:
                    t5_rets.append(r.fwd_return)
                    t5_total_local += 1
                    if r.correct:
                        t5_correct += 1
                for r in rest:
                    rest_rets.append(r.fwd_return)

            if t5_total_local < 5:
                continue

            t5_acc = t5_correct / t5_total_local * 100
            t5_ret = np.mean(t5_rets)
            rest_ret = np.mean(rest_rets) if rest_rets else 0
            alpha = t5_ret - rest_ret

            if direction == "SELL":
                t5_ret_adj = -t5_ret   # for SELL, negative return = profit
                rest_ret_adj = -rest_ret
                alpha_adj = t5_ret_adj - rest_ret_adj
            else:
                alpha_adj = alpha

            beats = alpha_adj > 0
            if beats:
                top5_wins += 1
            top5_total += 1
            top5_all_alpha.append(alpha_adj)

            arrow = "▲" if direction == "BUY" else "▼"
            sym = "✓" if beats else "✗"
            name = MN.get(method, method)[:20]
            print(f"  {name:<20} {arrow}{direction:<4} | Top5 Acc: {t5_acc:>5.1f}% "
                  f"| Top5 Ret: {t5_ret:>+6.2f}% | Rest Ret: {rest_ret:>+6.2f}% "
                  f"| Alpha: {alpha_adj:>+5.2f}% {sym}")

    if top5_total > 0:
        print(f"\n  Top-5 Picks selection wins: {top5_wins}/{top5_total} "
              f"({top5_wins/top5_total*100:.0f}%)")
        print(f"  Average alpha of Top-5 picks: {np.mean(top5_all_alpha):>+.2f}%")

    # ═══════════════════════════════════════════════════
    #  7) OVERALL SYSTEM SCORECARD
    # ═══════════════════════════════════════════════════
    print(f"\n\n{'=' * 74}")
    print("  7. OVERALL SYSTEM SCORECARD")
    print("=" * 74)

    total = len(results)
    total_correct = sum(1 for r in results if r.correct)
    overall_acc = total_correct / total * 100

    # Weighted accuracy (weight by method importance)
    all_accs = []
    for method in ["M1", "M2", "M3", "M4", "HYBRID", "TA"]:
        m_results = [r for r in results if r.method == method]
        if m_results:
            m_acc = sum(1 for r in m_results if r.correct) / len(m_results) * 100
            all_accs.append(m_acc)

    avg_method_acc = np.mean(all_accs) if all_accs else 0

    # Separation power: average spread across methods
    spreads = []
    for method in ["M1", "M2", "M3", "M4", "HYBRID", "TA"]:
        buys = [r for r in results if r.method == method and r.signal_type == "BUY"]
        sells = [r for r in results if r.method == method and r.signal_type == "SELL"]
        if len(buys) >= 5 and len(sells) >= 5:
            spread = np.mean([r.fwd_return for r in buys]) - np.mean([r.fwd_return for r in sells])
            spreads.append(spread)
    avg_spread = np.mean(spreads) if spreads else 0

    print(f"""
  ┌────────────────────────────────────────────────────┐
  │  Total Signals Tested:        {total:>7,}              │
  │  Overall Directional Accuracy: {overall_acc:>5.1f}%             │
  │  Average Method Accuracy:      {avg_method_acc:>5.1f}%             │
  │  BUY-SELL Separation Spread:  {avg_spread:>+6.2f}%             │
  │  Top-5 Selection Win Rate:     {top5_wins}/{top5_total} ({top5_wins/top5_total*100:.0f}%)              │
  └────────────────────────────────────────────────────┘""")

    # Grade
    # Directional accuracy: 50% = random, 55% = edge, 60%+ = strong
    # Separation power: > 0 means system differentiates correctly
    score = 0

    # Weight 1: Directional accuracy (max 40 pts)
    if overall_acc >= 65:
        score += 40
    elif overall_acc >= 60:
        score += 35
    elif overall_acc >= 55:
        score += 28
    elif overall_acc >= 52:
        score += 20
    elif overall_acc >= 50:
        score += 12
    else:
        score += 5

    # Weight 2: Separation power (max 30 pts)
    if avg_spread > 3:
        score += 30
    elif avg_spread > 1.5:
        score += 25
    elif avg_spread > 0.5:
        score += 18
    elif avg_spread > 0:
        score += 12
    else:
        score += 0

    # Weight 3: Top-5 picks (max 20 pts)
    if top5_total > 0:
        t5_rate = top5_wins / top5_total
        score += int(t5_rate * 20)

    # Weight 4: Confidence calibration (max 10 pts)
    hc = [r for r in results if r.confidence >= 60]
    lc = [r for r in results if r.confidence < 30]
    if hc and lc:
        hc_acc = sum(1 for r in hc if r.correct) / len(hc) * 100
        lc_acc = sum(1 for r in lc if r.correct) / len(lc) * 100
        if hc_acc > lc_acc + 5:
            score += 10
        elif hc_acc > lc_acc:
            score += 5

    if score >= 85:
        grade = "A+ (Exceptional)"
    elif score >= 75:
        grade = "A (Excellent)"
    elif score >= 65:
        grade = "B+ (Very Good)"
    elif score >= 55:
        grade = "B (Good — Meaningful Edge)"
    elif score >= 45:
        grade = "B- (Decent — Moderate Edge)"
    elif score >= 35:
        grade = "C+ (Fair — Slight Edge)"
    elif score >= 25:
        grade = "C (Marginal)"
    else:
        grade = "D (Needs Improvement)"

    print(f"""
  ┌────────────────────────────────────────────────────┐
  │                                                    │
  │   SYSTEM GRADE:  {grade:<34}│
  │   Score: {score}/100                                    │
  │                                                    │
  │   Scoring Breakdown:                               │
  │     Directional Accuracy: ....... /40              │
  │     Separation Power: ........... /30              │
  │     Top-5 Selection: ............ /20              │
  │     Confidence Calibration: ..... /10              │
  │                                                    │
  └────────────────────────────────────────────────────┘

  CONTEXT:
    • Random guessing = 50% accuracy, 0% spread
    • Professional quant systems target 55-65% directional accuracy
    • A positive BUY-SELL spread means the system correctly
      differentiates winners from losers
    • The Indian market (NSE) had mixed conditions in the test period
""")

    # Save results
    save_data = {
        "summary": {
            "total_signals": total,
            "overall_accuracy": round(overall_acc, 2),
            "avg_method_accuracy": round(avg_method_acc, 2),
            "buy_sell_spread": round(avg_spread, 3),
            "grade": grade,
            "score": score,
        },
        "per_method": {k: v for k, v in method_summary.items()},
        "raw_count": total,
    }
    with open("backtest_deep_results.json", "w") as f:
        json.dump(save_data, f, indent=2)
    print(f"  Results saved to backtest_deep_results.json")


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    results = run_deep_backtest()
    if results:
        analyze_results(results)
    else:
        print("No results generated.")
