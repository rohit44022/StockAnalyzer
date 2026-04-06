"""
Price Action System — Historical Backtest Simulation
=====================================================
Walks through historical data for each stock, generating PA signals
using a rolling window, then checks if targets or stops were hit in
subsequent bars. Reports win/loss/accuracy metrics.

Methodology
-----------
For each stock:
  1. Slide a window of WINDOW_SIZE bars across the history.
  2. At each step, run the full PA engine on the window.
  3. If a BUY or SELL signal is generated (confidence >= MIN_CONF):
     - Record entry price, stop loss, target_1, target_2.
     - Walk forward up to MAX_HOLD bars to see outcome.
     - WIN:  if target_1 is reached before stop loss.
     - LOSS: if stop loss is hit before target.
     - TIMEOUT: if neither hit within MAX_HOLD bars (partial credit).
  4. Skip ahead by COOLDOWN bars after a signal to avoid overlap.
"""

from __future__ import annotations

import json
import os
import sys
import time
import glob
from dataclasses import dataclass, field, asdict
from typing import List, Dict

import pandas as pd
import numpy as np

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from price_action.engine import run_price_action_analysis
from price_action import config as C

# ─────────────────────────────────────────────────────────────────
#  BACKTEST CONFIGURATION
# ─────────────────────────────────────────────────────────────────
WINDOW_SIZE = 250        # Bars fed to PA engine per signal
STEP_SIZE = 5            # Slide window by N bars between signal checks
COOLDOWN = 10            # Skip N bars after a signal to avoid overlaps
MAX_HOLD = 20            # Max bars to hold a trade before timeout
MIN_CONF = 30            # Minimum confidence to count as a signal
MIN_BARS_NEEDED = WINDOW_SIZE + MAX_HOLD + 10  # Need enough data


# ─────────────────────────────────────────────────────────────────
#  TRADE RESULT
# ─────────────────────────────────────────────────────────────────
@dataclass
class TradeResult:
    ticker: str = ""
    signal_date: str = ""
    direction: str = ""         # BUY or SELL
    setup_type: str = ""
    strength: str = ""
    confidence: int = 0
    pa_score: float = 0.0
    entry_price: float = 0.0
    stop_loss: float = 0.0
    target_1: float = 0.0
    target_2: float = 0.0
    risk_reward: float = 0.0
    outcome: str = ""           # WIN_T1, WIN_T2, LOSS, TIMEOUT_WIN, TIMEOUT_LOSS
    exit_price: float = 0.0
    exit_date: str = ""
    bars_held: int = 0
    pnl_pct: float = 0.0       # percentage gain/loss
    always_in: str = ""
    trend_phase: str = ""


# ─────────────────────────────────────────────────────────────────
#  SINGLE STOCK BACKTEST
# ─────────────────────────────────────────────────────────────────
def backtest_stock(df: pd.DataFrame, ticker: str) -> List[TradeResult]:
    """Run PA backtest on a single stock's historical data."""
    trades: List[TradeResult] = []
    n = len(df)

    if n < MIN_BARS_NEEDED:
        return trades

    highs = df["High"].values
    lows = df["Low"].values
    closes = df["Close"].values
    dates = df.index

    i = WINDOW_SIZE
    while i < n - MAX_HOLD:
        # Extract window
        window_df = df.iloc[i - WINDOW_SIZE:i]

        try:
            result = run_price_action_analysis(window_df, ticker)
        except Exception:
            i += STEP_SIZE
            continue

        if not result.success:
            i += STEP_SIZE
            continue

        # Only process actionable signals
        if result.signal_type not in ("BUY", "SELL") or result.confidence < MIN_CONF:
            i += STEP_SIZE
            continue

        # Validate price levels
        if result.entry_price <= 0 or result.stop_loss <= 0 or result.target_1 <= 0:
            i += STEP_SIZE
            continue

        # Avoid invalid risk (stop == entry)
        risk = abs(result.entry_price - result.stop_loss)
        if risk <= 0 or risk / result.entry_price < 0.001:
            i += STEP_SIZE
            continue

        # ── Walk forward to determine outcome ──
        trade = TradeResult(
            ticker=ticker,
            signal_date=str(dates[i - 1].date()) if hasattr(dates[i - 1], "date") else str(dates[i - 1]),
            direction=result.signal_type,
            setup_type=result.setup_type,
            strength=result.strength,
            confidence=result.confidence,
            pa_score=result.pa_score,
            entry_price=result.entry_price,
            stop_loss=result.stop_loss,
            target_1=result.target_1,
            target_2=result.target_2,
            risk_reward=result.risk_reward,
            always_in=result.always_in,
            trend_phase=result.trend_phase,
        )

        outcome = _evaluate_trade(
            direction=result.signal_type,
            entry=result.entry_price,
            stop=result.stop_loss,
            target_1=result.target_1,
            target_2=result.target_2,
            highs=highs[i:i + MAX_HOLD],
            lows=lows[i:i + MAX_HOLD],
            closes=closes[i:i + MAX_HOLD],
        )

        trade.outcome = outcome["outcome"]
        trade.exit_price = outcome["exit_price"]
        trade.bars_held = outcome["bars_held"]
        trade.pnl_pct = outcome["pnl_pct"]

        # Skip trades where entry was never triggered
        if trade.outcome == "NO_ENTRY":
            i += STEP_SIZE
            continue

        exit_idx = i + outcome["bars_held"] - 1
        if exit_idx < n:
            trade.exit_date = str(dates[exit_idx].date()) if hasattr(dates[exit_idx], "date") else str(dates[exit_idx])

        trades.append(trade)

        # Skip forward to avoid overlapping trades
        i += max(COOLDOWN, outcome["bars_held"])
        continue

    return trades


def _evaluate_trade(
    direction: str,
    entry: float,
    stop: float,
    target_1: float,
    target_2: float,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
) -> dict:
    """Walk forward through bars to determine trade outcome."""
    n = len(highs)
    entered = False

    for j in range(n):
        # First check if entry price is triggered
        if not entered:
            if direction == "BUY" and highs[j] >= entry:
                entered = True
            elif direction == "SELL" and lows[j] <= entry:
                entered = True
            else:
                continue  # Entry not yet triggered

        if direction == "BUY":
            # Check stop hit (low touches stop)
            if lows[j] <= stop:
                pnl = (stop - entry) / entry * 100
                return {"outcome": "LOSS", "exit_price": stop, "bars_held": j + 1, "pnl_pct": round(pnl, 2)}
            # Check target_1 hit (high reaches target)
            if highs[j] >= target_1:
                if highs[j] >= target_2:
                    pnl = (target_2 - entry) / entry * 100
                    return {"outcome": "WIN_T2", "exit_price": target_2, "bars_held": j + 1, "pnl_pct": round(pnl, 2)}
                pnl = (target_1 - entry) / entry * 100
                return {"outcome": "WIN_T1", "exit_price": target_1, "bars_held": j + 1, "pnl_pct": round(pnl, 2)}
        else:  # SELL
            if highs[j] >= stop:
                pnl = (entry - stop) / entry * 100
                return {"outcome": "LOSS", "exit_price": stop, "bars_held": j + 1, "pnl_pct": round(pnl, 2)}
            if lows[j] <= target_1:
                if lows[j] <= target_2:
                    pnl = (entry - target_2) / entry * 100
                    return {"outcome": "WIN_T2", "exit_price": target_2, "bars_held": j + 1, "pnl_pct": round(pnl, 2)}
                pnl = (entry - target_1) / entry * 100
                return {"outcome": "WIN_T1", "exit_price": target_1, "bars_held": j + 1, "pnl_pct": round(pnl, 2)}

    if not entered:
        return {"outcome": "NO_ENTRY", "exit_price": 0, "bars_held": 0, "pnl_pct": 0}

    # Timeout — use last close
    last_close = closes[-1] if n > 0 else entry
    if direction == "BUY":
        pnl = (last_close - entry) / entry * 100
    else:
        pnl = (entry - last_close) / entry * 100

    outcome = "TIMEOUT_WIN" if pnl > 0 else "TIMEOUT_LOSS"
    return {"outcome": outcome, "exit_price": float(last_close), "bars_held": n, "pnl_pct": round(pnl, 2)}


# ─────────────────────────────────────────────────────────────────
#  FULL UNIVERSE BACKTEST
# ─────────────────────────────────────────────────────────────────
def run_full_backtest(max_stocks: int = 0, verbose: bool = True) -> dict:
    """Run backtest across all stocks in stock_csv/."""
    csv_dir = os.path.join(_ROOT, "stock_csv")
    csv_files = sorted(glob.glob(os.path.join(csv_dir, "*.csv")))

    if max_stocks > 0:
        csv_files = csv_files[:max_stocks]

    all_trades: List[TradeResult] = []
    stocks_processed = 0
    stocks_with_signals = 0
    stocks_skipped = 0
    errors = 0

    total = len(csv_files)
    t0 = time.time()

    if verbose:
        print(f"PA BACKTEST — Processing {total} stocks")
        print("=" * 60)

    for idx, csv_path in enumerate(csv_files):
        ticker = os.path.basename(csv_path).replace(".csv", "")

        try:
            df = pd.read_csv(csv_path, parse_dates=["Date"], index_col="Date")
        except Exception:
            errors += 1
            continue

        if len(df) < MIN_BARS_NEEDED:
            stocks_skipped += 1
            continue

        try:
            trades = backtest_stock(df, ticker)
            stocks_processed += 1
            if trades:
                stocks_with_signals += 1
                all_trades.extend(trades)
        except Exception as e:
            errors += 1
            if verbose and errors <= 5:
                print(f"  ERROR {ticker}: {e}")

        if verbose and (idx + 1) % 100 == 0:
            elapsed = time.time() - t0
            rate = (idx + 1) / elapsed
            print(f"  [{idx + 1}/{total}] {rate:.0f} stocks/sec, "
                  f"{len(all_trades)} trades so far")

    elapsed = time.time() - t0

    # ── Compute metrics ──
    metrics = _compute_metrics(all_trades)
    metrics["meta"] = {
        "total_csv": total,
        "stocks_processed": stocks_processed,
        "stocks_with_signals": stocks_with_signals,
        "stocks_skipped": stocks_skipped,
        "errors": errors,
        "elapsed_sec": round(elapsed, 1),
        "config": {
            "window_size": WINDOW_SIZE,
            "step_size": STEP_SIZE,
            "cooldown": COOLDOWN,
            "max_hold": MAX_HOLD,
            "min_confidence": MIN_CONF,
        },
    }

    if verbose:
        _print_report(metrics)

    # Save results
    output = {
        "metrics": metrics,
        "trades": [asdict(t) for t in all_trades],
    }
    out_path = os.path.join(_ROOT, "backtest_pa_results.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    if verbose:
        print(f"\nResults saved to {out_path}")

    return metrics


def _compute_metrics(trades: List[TradeResult]) -> dict:
    """Compute comprehensive backtest metrics."""
    if not trades:
        return {"total_trades": 0}

    total = len(trades)
    wins = [t for t in trades if t.outcome.startswith("WIN")]
    losses = [t for t in trades if t.outcome == "LOSS"]
    timeout_wins = [t for t in trades if t.outcome == "TIMEOUT_WIN"]
    timeout_losses = [t for t in trades if t.outcome == "TIMEOUT_LOSS"]

    win_count = len(wins)
    loss_count = len(losses)
    tw_count = len(timeout_wins)
    tl_count = len(timeout_losses)

    win_rate = win_count / total * 100 if total else 0
    # Count timeout wins as half-wins for adjusted rate
    adjusted_win_rate = (win_count + tw_count * 0.5) / total * 100 if total else 0

    # P&L
    all_pnl = [t.pnl_pct for t in trades]
    avg_pnl = np.mean(all_pnl) if all_pnl else 0
    total_pnl = sum(all_pnl)

    avg_win_pnl = np.mean([t.pnl_pct for t in wins]) if wins else 0
    avg_loss_pnl = np.mean([t.pnl_pct for t in losses]) if losses else 0

    # Profit factor
    gross_profit = sum(t.pnl_pct for t in trades if t.pnl_pct > 0)
    gross_loss = abs(sum(t.pnl_pct for t in trades if t.pnl_pct < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Average bars held
    avg_bars = np.mean([t.bars_held for t in trades])

    # By direction
    buys = [t for t in trades if t.direction == "BUY"]
    sells = [t for t in trades if t.direction == "SELL"]
    buy_wr = sum(1 for t in buys if t.outcome.startswith("WIN")) / len(buys) * 100 if buys else 0
    sell_wr = sum(1 for t in sells if t.outcome.startswith("WIN")) / len(sells) * 100 if sells else 0

    # By setup type
    setup_metrics = {}
    for stype in ["BREAKOUT", "PULLBACK", "REVERSAL", "TREND_CONT", "FAILED_BREAKOUT", "SECOND_ENTRY"]:
        st_trades = [t for t in trades if t.setup_type == stype]
        if st_trades:
            st_wins = sum(1 for t in st_trades if t.outcome.startswith("WIN"))
            setup_metrics[stype] = {
                "trades": len(st_trades),
                "wins": st_wins,
                "win_rate": round(st_wins / len(st_trades) * 100, 1),
                "avg_pnl": round(np.mean([t.pnl_pct for t in st_trades]), 2),
            }

    # By strength
    strength_metrics = {}
    for s in ["STRONG", "MODERATE", "WEAK"]:
        s_trades = [t for t in trades if t.strength == s]
        if s_trades:
            s_wins = sum(1 for t in s_trades if t.outcome.startswith("WIN"))
            strength_metrics[s] = {
                "trades": len(s_trades),
                "wins": s_wins,
                "win_rate": round(s_wins / len(s_trades) * 100, 1),
                "avg_pnl": round(np.mean([t.pnl_pct for t in s_trades]), 2),
            }

    # By confidence tier
    conf_metrics = {}
    for label, lo, hi in [("HIGH (75+)", 75, 101), ("MODERATE (50-74)", 50, 75), ("WEAK (30-49)", 30, 50)]:
        c_trades = [t for t in trades if lo <= t.confidence < hi]
        if c_trades:
            c_wins = sum(1 for t in c_trades if t.outcome.startswith("WIN"))
            conf_metrics[label] = {
                "trades": len(c_trades),
                "wins": c_wins,
                "win_rate": round(c_wins / len(c_trades) * 100, 1),
                "avg_pnl": round(np.mean([t.pnl_pct for t in c_trades]), 2),
            }

    # By trend phase
    phase_metrics = {}
    for phase in ["SPIKE", "TIGHT_CHANNEL", "CHANNEL", "BROAD_CHANNEL", "TRADING_RANGE"]:
        p_trades = [t for t in trades if t.trend_phase == phase]
        if p_trades:
            p_wins = sum(1 for t in p_trades if t.outcome.startswith("WIN"))
            phase_metrics[phase] = {
                "trades": len(p_trades),
                "wins": p_wins,
                "win_rate": round(p_wins / len(p_trades) * 100, 1),
                "avg_pnl": round(np.mean([t.pnl_pct for t in p_trades]), 2),
            }

    # Grade the system
    if win_rate >= 65 and profit_factor >= 1.5:
        grade = "A"
    elif win_rate >= 55 and profit_factor >= 1.2:
        grade = "B"
    elif win_rate >= 45 and profit_factor >= 1.0:
        grade = "C"
    elif win_rate >= 35:
        grade = "D"
    else:
        grade = "F"

    return {
        "total_trades": total,
        "wins": win_count,
        "losses": loss_count,
        "timeout_wins": tw_count,
        "timeout_losses": tl_count,
        "win_rate": round(win_rate, 1),
        "adjusted_win_rate": round(adjusted_win_rate, 1),
        "avg_pnl_pct": round(avg_pnl, 2),
        "total_pnl_pct": round(total_pnl, 2),
        "avg_win_pnl": round(avg_win_pnl, 2),
        "avg_loss_pnl": round(avg_loss_pnl, 2),
        "profit_factor": round(profit_factor, 2),
        "avg_bars_held": round(avg_bars, 1),
        "buy_trades": len(buys),
        "sell_trades": len(sells),
        "buy_win_rate": round(buy_wr, 1),
        "sell_win_rate": round(sell_wr, 1),
        "by_setup": setup_metrics,
        "by_strength": strength_metrics,
        "by_confidence": conf_metrics,
        "by_phase": phase_metrics,
        "grade": grade,
    }


def _print_report(m: dict) -> None:
    """Print formatted backtest report."""
    print("\n" + "=" * 60)
    print("   AL BROOKS PRICE ACTION — BACKTEST REPORT")
    print("=" * 60)

    if m.get("total_trades", 0) == 0:
        print("No trades generated.")
        return

    print(f"\n{'OVERALL RESULTS':^60}")
    print("-" * 60)
    print(f"  Total Trades     : {m['total_trades']}")
    print(f"  Wins (target hit): {m['wins']}")
    print(f"  Losses (stop hit): {m['losses']}")
    print(f"  Timeout Win      : {m['timeout_wins']}")
    print(f"  Timeout Loss     : {m['timeout_losses']}")
    print(f"  Win Rate         : {m['win_rate']:.1f}%")
    print(f"  Adjusted Win Rate: {m['adjusted_win_rate']:.1f}% (timeout wins = half credit)")
    print(f"  Profit Factor    : {m['profit_factor']:.2f}")
    print(f"  Avg P&L per Trade: {m['avg_pnl_pct']:+.2f}%")
    print(f"  Avg Win P&L      : {m['avg_win_pnl']:+.2f}%")
    print(f"  Avg Loss P&L     : {m['avg_loss_pnl']:+.2f}%")
    print(f"  Avg Bars Held    : {m['avg_bars_held']:.1f}")
    print(f"  GRADE            : {m['grade']}")

    print(f"\n{'DIRECTION SPLIT':^60}")
    print("-" * 60)
    print(f"  BUY  trades: {m['buy_trades']}  win rate: {m['buy_win_rate']:.1f}%")
    print(f"  SELL trades: {m['sell_trades']}  win rate: {m['sell_win_rate']:.1f}%")

    if m.get("by_setup"):
        print(f"\n{'BY SETUP TYPE':^60}")
        print("-" * 60)
        for stype, data in sorted(m["by_setup"].items(), key=lambda x: -x[1]["win_rate"]):
            print(f"  {stype:20s}  trades: {data['trades']:5d}  "
                  f"WR: {data['win_rate']:5.1f}%  avg P&L: {data['avg_pnl']:+.2f}%")

    if m.get("by_strength"):
        print(f"\n{'BY SIGNAL STRENGTH':^60}")
        print("-" * 60)
        for s, data in m["by_strength"].items():
            print(f"  {s:10s}  trades: {data['trades']:5d}  "
                  f"WR: {data['win_rate']:5.1f}%  avg P&L: {data['avg_pnl']:+.2f}%")

    if m.get("by_confidence"):
        print(f"\n{'BY CONFIDENCE TIER':^60}")
        print("-" * 60)
        for label, data in m["by_confidence"].items():
            print(f"  {label:18s}  trades: {data['trades']:5d}  "
                  f"WR: {data['win_rate']:5.1f}%  avg P&L: {data['avg_pnl']:+.2f}%")

    if m.get("by_phase"):
        print(f"\n{'BY TREND PHASE':^60}")
        print("-" * 60)
        for phase, data in sorted(m["by_phase"].items(), key=lambda x: -x[1]["win_rate"]):
            print(f"  {phase:18s}  trades: {data['trades']:5d}  "
                  f"WR: {data['win_rate']:5.1f}%  avg P&L: {data['avg_pnl']:+.2f}%")

    meta = m.get("meta", {})
    if meta:
        print(f"\n{'PROCESSING':^60}")
        print("-" * 60)
        print(f"  Stocks processed : {meta.get('stocks_processed', 0)}")
        print(f"  With signals     : {meta.get('stocks_with_signals', 0)}")
        print(f"  Skipped (data)   : {meta.get('stocks_skipped', 0)}")
        print(f"  Errors           : {meta.get('errors', 0)}")
        print(f"  Elapsed          : {meta.get('elapsed_sec', 0):.1f}s")

    print("=" * 60)


# ─────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="PA Backtest")
    parser.add_argument("--max", type=int, default=0, help="Max stocks (0=all)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    run_full_backtest(max_stocks=args.max, verbose=not args.quiet)
