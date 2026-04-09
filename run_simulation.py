#!/usr/bin/env python3
"""
Simulation Runner — Triple Conviction Engine Truthfulness Test
Runs sequentially (no fork-based multiprocessing) for stability.
Uses ThreadPoolExecutor instead of ProcessPool.
"""
import sys, os, glob, time, json, math
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)

# Import the backtest functions directly
from backtest_triple import (
    _process_stock, _compute_metrics, _print_report,
    CSV_DIR, WINDOW_SIZE, STEP_SIZE, COOLDOWN, MAX_HOLD,
    DIRECTION_FILTER
)

def run_simulation(max_stocks=200, workers=4):
    """Run simulation using threading instead of multiprocessing fork."""
    csv_files = sorted(glob.glob(os.path.join(CSV_DIR, "*.csv")))
    if max_stocks > 0:
        csv_files = csv_files[:max_stocks]

    total = len(csv_files)
    print(f"TRIPLE ENGINE SIMULATION — {total} stocks (sequential processing)")
    print(f"Window: {WINDOW_SIZE} bars | Step: {STEP_SIZE} | Cooldown: {COOLDOWN} | Max Hold: {MAX_HOLD}")
    print(f"Direction: {DIRECTION_FILTER}")
    print("=" * 74)

    all_trades = []
    stocks_processed = 0
    stocks_with_signals = 0
    stocks_skipped = 0
    t0 = time.time()

    for idx, csv_path in enumerate(csv_files, 1):
        try:
            trades = _process_stock(csv_path)
            if trades is None:
                stocks_skipped += 1
            elif len(trades) == 0:
                stocks_processed += 1
            else:
                stocks_processed += 1
                stocks_with_signals += 1
                all_trades.extend(trades)
        except Exception as e:
            stocks_skipped += 1

        if idx % 20 == 0:
            elapsed = time.time() - t0
            rate = idx / elapsed if elapsed > 0 else 0
            print(f"  [{idx}/{total}] {rate:.1f} stocks/sec | "
                  f"{len(all_trades):,} trades | elapsed {elapsed:.0f}s",
                  flush=True)

    elapsed = time.time() - t0
    print(f"\n  Completed: {total}/{total} in {elapsed:.0f}s "
          f"({total / elapsed:.1f} stocks/sec)")
    print(f"  Total trades: {len(all_trades):,}")

    # Compute metrics
    metrics = _compute_metrics(all_trades)
    metrics["meta"] = {
        "total_csv": total,
        "stocks_processed": stocks_processed,
        "stocks_with_signals": stocks_with_signals,
        "stocks_skipped": stocks_skipped,
        "elapsed_sec": round(elapsed, 1),
        "direction_filter": DIRECTION_FILTER,
        "config": {
            "window_size": WINDOW_SIZE,
            "step_size": STEP_SIZE,
            "cooldown": COOLDOWN,
            "max_hold": MAX_HOLD,
        },
    }

    _print_report(metrics)

    # Save results
    def _clean(obj):
        if isinstance(obj, dict):
            return {k: _clean(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_clean(v) for v in obj]
        if isinstance(obj, float):
            if math.isnan(obj) or math.isinf(obj):
                return None
            return obj
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            v = float(obj)
            return None if math.isnan(v) or math.isinf(v) else v
        if isinstance(obj, np.ndarray):
            return _clean(obj.tolist())
        return obj

    out_path = os.path.join(_ROOT, "simulation_results.json")
    output = _clean({
        "metrics": metrics,
        "trades_sample": all_trades[:500],
        "total_trades_count": len(all_trades),
    })
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Results saved to: {out_path}")

    return metrics


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=200)
    parser.add_argument("--direction", type=str, default="ALL", choices=["ALL", "BUY", "SELL"])
    args = parser.parse_args()

    # Set direction filter before running
    import backtest_triple
    backtest_triple.DIRECTION_FILTER = args.direction.upper()

    run_simulation(max_stocks=args.max)
