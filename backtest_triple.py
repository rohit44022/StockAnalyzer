#!/usr/bin/env python3
"""
backtest_triple.py — Triple Conviction Engine Backtest Simulator
=================================================================

Multi-threaded backtest that simulates REAL market conditions:
  • Rolling window (250 bars) → generate signal using ONLY past data
  • Walk forward to evaluate trade outcome (no lookahead bias)
  • Multi-process using ProcessPoolExecutor for speed
  • Comprehensive metrics by verdict, alignment, score tier, system agreement

Architecture:
  For each stock CSV:
    1. Load data → slide 250-bar window every 10 bars
    2. Run run_triple_analysis() on window → get verdict + scores
    3. If actionable (BUY/SELL): set entry, stop, targets
    4. Walk forward up to 30 bars → check stop/target/timeout
    5. Record detailed trade result

Scoring Matrix:
  BB  (-100..+100) + TA (-100..+100) + PA (-100..+100)
  + Cross-Validation (-60..+60)
  = Combined (-360..+360)

Usage:
  python3 backtest_triple.py                    # full universe, 8 workers
  python3 backtest_triple.py --max 50           # first 50 stocks
  python3 backtest_triple.py --workers 4        # 4 worker processes
  python3 backtest_triple.py --direction BUY    # longs only
"""

import os, sys, glob, time, json, math, argparse
from dataclasses import dataclass, asdict, field
from typing import List, Optional
import multiprocessing as mp
import numpy as np
import pandas as pd

# ── Project root ──
_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)

from bb_squeeze.data_loader import load_from_csv
from hybrid_pa_engine import run_triple_analysis

# ═══════════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════════
WINDOW_SIZE = 250       # Bars per analysis window (1 year of trading)
STEP_SIZE = 10          # Advance by 10 bars between scans
COOLDOWN = 15           # Min bars between trades (avoid overlapping)
MAX_HOLD = 40           # Max bars to hold before forced exit (wider stops need more time)
NUM_WORKERS = 8         # Default parallel workers
DIRECTION_FILTER = "ALL"  # "ALL", "BUY", "SELL"
CSV_DIR = os.path.join(_ROOT, "stock_csv")

# ── Quality Filters ──
MIN_SCORE_BUY = 80      # Only STRONG BUY+ (score ≥ 80)
MIN_SCORE_SELL = -80    # Only STRONG SELL+ (score ≤ -80)
MIN_AGREEMENT = 2       # Require 2+ of 3 systems to agree
DD_WINDOW = 200         # Rolling window for max drawdown calculation


# ═══════════════════════════════════════════════════════════════
#  TRADE RECORD
# ═══════════════════════════════════════════════════════════════
@dataclass
class TripleTradeRecord:
    # ── Identity ──
    ticker: str = ""
    signal_date: str = ""
    exit_date: str = ""
    direction: str = ""

    # ── Triple Verdict ──
    triple_verdict: str = ""
    triple_score: float = 0.0
    triple_confidence: float = 0.0
    alignment: str = ""

    # ── Sub-system scores ──
    bb_score: float = 0.0
    ta_score: float = 0.0
    pa_score: float = 0.0
    agreement_score: float = 0.0

    # ── Sub-system signals ──
    bb_phase: str = ""
    bb_buy_signal: bool = False
    bb_sell_signal: bool = False
    ta_verdict: str = ""
    ta_confidence: float = 0.0
    pa_signal: str = ""
    pa_strength: str = ""
    pa_always_in: str = ""

    # ── Trade levels ──
    entry_price: float = 0.0
    stop_loss: float = 0.0
    target_1: float = 0.0
    target_2: float = 0.0

    # ── Outcome (filled after walk-forward) ──
    outcome: str = ""
    exit_price: float = 0.0
    bars_held: int = 0
    pnl_pct: float = 0.0
    exit_method: str = ""


# ═══════════════════════════════════════════════════════════════
#  TRADE EVALUATION — WALK FORWARD
# ═══════════════════════════════════════════════════════════════
def _evaluate_trade(
    direction: str,
    entry: float,
    stop: float,
    target_1: float,
    target_2: float,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    bb_upper: float = None,
    bb_lower: float = None,
) -> dict:
    """
    Walk forward through bars with TRAILING BREAKEVEN STOP.
    After price reaches 1R in favor, stop moves to entry (breakeven).
    After 1.5R, stop trails to 0.5R profit. No lookahead.
    """
    n = len(highs)
    if n == 0:
        return {"outcome": "NO_ENTRY", "exit_price": 0, "bars_held": 0, "pnl_pct": 0, "exit_method": ""}

    risk = abs(entry - stop)
    active_stop = stop
    reached_1r = False

    for j in range(n):
        if direction == "BUY":
            # 1. Check stop (using ACTIVE stop — may be trailed up)
            if lows[j] <= active_stop:
                pnl = (active_stop - entry) / entry * 100
                if reached_1r:
                    if abs(pnl) < 0.3:
                        return {"outcome": "BREAKEVEN", "exit_price": round(active_stop, 2),
                                "bars_held": j + 1, "pnl_pct": round(pnl, 2), "exit_method": "TRAIL_BE"}
                    else:
                        return {"outcome": "WIN_TRAIL", "exit_price": round(active_stop, 2),
                                "bars_held": j + 1, "pnl_pct": round(pnl, 2), "exit_method": "TRAIL_STOP"}
                else:
                    return {"outcome": "LOSS", "exit_price": round(active_stop, 2),
                            "bars_held": j + 1, "pnl_pct": round(pnl, 2), "exit_method": "STOP"}

            # 2. Target 2 (best case)
            if highs[j] >= target_2:
                pnl = (target_2 - entry) / entry * 100
                return {"outcome": "WIN_T2", "exit_price": round(target_2, 2),
                        "bars_held": j + 1, "pnl_pct": round(pnl, 2), "exit_method": "TARGET_2"}
            # 3. Target 1
            if highs[j] >= target_1:
                pnl = (target_1 - entry) / entry * 100
                return {"outcome": "WIN_T1", "exit_price": round(target_1, 2),
                        "bars_held": j + 1, "pnl_pct": round(pnl, 2), "exit_method": "TARGET_1"}
            # 4. BB band tag
            if bb_lower and closes[j] <= bb_lower:
                pnl = (closes[j] - entry) / entry * 100
                oc = "LOSS" if pnl < 0 else "WIN_T1"
                return {"outcome": oc, "exit_price": round(float(closes[j]), 2),
                        "bars_held": j + 1, "pnl_pct": round(pnl, 2), "exit_method": "BAND_TAG"}

            # 5. End-of-bar trailing update (takes effect NEXT bar)
            if not reached_1r and highs[j] >= entry + risk:
                reached_1r = True
                active_stop = entry  # Move to breakeven
            if reached_1r:
                # Progressive trail: at 1.5R profit, trail stop to 0.5R
                if highs[j] >= entry + risk * 1.5:
                    active_stop = max(active_stop, entry + risk * 0.5)

        else:  # SELL
            # 1. Check stop
            if highs[j] >= active_stop:
                pnl = (entry - active_stop) / entry * 100
                if reached_1r:
                    if abs(pnl) < 0.3:
                        return {"outcome": "BREAKEVEN", "exit_price": round(active_stop, 2),
                                "bars_held": j + 1, "pnl_pct": round(pnl, 2), "exit_method": "TRAIL_BE"}
                    else:
                        return {"outcome": "WIN_TRAIL", "exit_price": round(active_stop, 2),
                                "bars_held": j + 1, "pnl_pct": round(pnl, 2), "exit_method": "TRAIL_STOP"}
                else:
                    return {"outcome": "LOSS", "exit_price": round(active_stop, 2),
                            "bars_held": j + 1, "pnl_pct": round(pnl, 2), "exit_method": "STOP"}

            # 2. T2
            if lows[j] <= target_2:
                pnl = (entry - target_2) / entry * 100
                return {"outcome": "WIN_T2", "exit_price": round(target_2, 2),
                        "bars_held": j + 1, "pnl_pct": round(pnl, 2), "exit_method": "TARGET_2"}
            # 3. T1
            if lows[j] <= target_1:
                pnl = (entry - target_1) / entry * 100
                return {"outcome": "WIN_T1", "exit_price": round(target_1, 2),
                        "bars_held": j + 1, "pnl_pct": round(pnl, 2), "exit_method": "TARGET_1"}
            # 4. BB band tag
            if bb_upper and closes[j] >= bb_upper:
                pnl = (entry - closes[j]) / entry * 100
                oc = "LOSS" if pnl < 0 else "WIN_T1"
                return {"outcome": oc, "exit_price": round(float(closes[j]), 2),
                        "bars_held": j + 1, "pnl_pct": round(pnl, 2), "exit_method": "BAND_TAG"}

            # 5. End-of-bar trailing update
            if not reached_1r and lows[j] <= entry - risk:
                reached_1r = True
                active_stop = entry
            if reached_1r:
                if lows[j] <= entry - risk * 1.5:
                    active_stop = min(active_stop, entry - risk * 0.5)

    # Timeout
    last_close = float(closes[-1])
    pnl = ((last_close - entry) / entry * 100) if direction == "BUY" else ((entry - last_close) / entry * 100)
    oc = "TIMEOUT_WIN" if pnl > 0 else "TIMEOUT_LOSS"
    return {"outcome": oc, "exit_price": round(last_close, 2),
            "bars_held": n, "pnl_pct": round(pnl, 2), "exit_method": "TIMEOUT"}


# ═══════════════════════════════════════════════════════════════
#  PROCESS ONE STOCK — WORKER FUNCTION
# ═══════════════════════════════════════════════════════════════
def _process_stock(csv_path: str) -> Optional[List[dict]]:
    """
    Process a single stock CSV through the Triple Engine backtest.
    Called by each worker process independently.
    Returns list of trade dicts, or None if stock is unusable.
    """
    ticker = os.path.basename(csv_path).replace(".csv", "")

    # Skip bad filenames
    if ticker.startswith(".") or len(ticker) < 4:
        return None

    df = load_from_csv(ticker, CSV_DIR)
    if df is None or len(df) < WINDOW_SIZE + MAX_HOLD:
        return None

    trades = []
    highs = df["High"].values
    lows = df["Low"].values
    closes = df["Close"].values
    dates = df.index
    n = len(df)
    i = WINDOW_SIZE

    while i < n - MAX_HOLD:
        window_df = df.iloc[i - WINDOW_SIZE: i].copy()

        try:
            # ── Run Triple Analysis on the window ──
            result = run_triple_analysis(window_df, ticker=ticker)

            if "error" in result:
                i += STEP_SIZE
                continue

            verdict_data = result.get("triple_verdict", {})
            cross = result.get("cross_validation", {})
            verdict_str = verdict_data.get("verdict", "HOLD / WAIT")
            combined_score = verdict_data.get("score", 0)
            confidence = verdict_data.get("confidence", 0)
            alignment = cross.get("alignment", "PARTIAL")

            bb_total = result.get("bb_score", {}).get("total", 0)
            ta_total = result.get("ta_score", {}).get("total", 0)
            pa_total = result.get("pa_score", {}).get("total", 0)
            agree = cross.get("agreement_score", 0)

            # ── Determine trade direction ──
            if "BUY" in verdict_str:
                if combined_score < MIN_SCORE_BUY:
                    i += STEP_SIZE
                    continue
                direction = "BUY"
            elif "SELL" in verdict_str:
                if combined_score > MIN_SCORE_SELL:
                    i += STEP_SIZE
                    continue
                direction = "SELL"
            else:
                i += STEP_SIZE
                continue

            # ── System agreement filter ──
            pa_data_chk = result.get("pa_data", {})
            ta_sig_chk = result.get("ta_signal", {})
            bb_data_chk = result.get("bb_data", {})
            agree_n = 0
            # BB agrees?
            if direction == "BUY" and (bb_data_chk.get("buy_signal") or bb_total > 10):
                agree_n += 1
            elif direction == "SELL" and (bb_data_chk.get("sell_signal") or bb_total < -10):
                agree_n += 1
            # TA agrees?
            ta_v = ta_sig_chk.get("verdict", "HOLD")
            if ("BUY" in ta_v and direction == "BUY") or ("SELL" in ta_v and direction == "SELL"):
                agree_n += 1
            # PA agrees?
            if pa_data_chk.get("signal_type") == direction:
                agree_n += 1
            if agree_n < MIN_AGREEMENT:
                i += STEP_SIZE
                continue

            # Apply direction filter
            if DIRECTION_FILTER == "BUY" and direction != "BUY":
                i += STEP_SIZE
                continue
            if DIRECTION_FILTER == "SELL" and direction != "SELL":
                i += STEP_SIZE
                continue

            # ── Entry price = close of signal bar ──
            price = float(closes[i - 1])
            if price <= 0:
                i += STEP_SIZE
                continue

            # ── ATR-based minimum stop distance ──
            # Prevents stops from being set too close in volatile conditions
            window_highs = highs[max(0, i - 15): i]
            window_lows = lows[max(0, i - 15): i]
            window_closes_arr = closes[max(0, i - 15): i]
            if len(window_highs) >= 2:
                tr_vals = []
                for k in range(1, len(window_highs)):
                    tr = max(
                        window_highs[k] - window_lows[k],
                        abs(window_highs[k] - window_closes_arr[k - 1]),
                        abs(window_lows[k] - window_closes_arr[k - 1])
                    )
                    tr_vals.append(tr)
                atr_14 = float(np.mean(tr_vals)) if tr_vals else price * 0.02
            else:
                atr_14 = price * 0.02
            min_stop_dist = atr_14 * 1.5  # Minimum 1.5x ATR from entry

            # ── Stop loss: Use PA stop, BB stop, TA stop, or fallback ──
            pa_data = result.get("pa_data", {})
            bb_data = result.get("bb_data", {})

            pa_stop = float(pa_data.get("stop_loss") or 0)
            bb_lower = float(bb_data.get("indicators", {}).get("bb_lower") or 0)
            bb_upper = float(bb_data.get("indicators", {}).get("bb_upper") or 0)

            # TA support/resistance stop
            sr_data = result.get("support_resistance", {})
            ta_stop = 0
            if direction == "BUY":
                supports = sr_data.get("support_levels", []) if isinstance(sr_data, dict) else []
                valid_supports = [s.get("price", 0) if isinstance(s, dict) else 0 for s in supports]
                valid_supports = [s for s in valid_supports if 0 < s < price]
                if valid_supports:
                    ta_stop = max(valid_supports)
            else:
                resistances = sr_data.get("resistance_levels", []) if isinstance(sr_data, dict) else []
                valid_resistances = [r.get("price", 0) if isinstance(r, dict) else 0 for r in resistances]
                valid_resistances = [r for r in valid_resistances if r > price]
                if valid_resistances:
                    ta_stop = min(valid_resistances)

            # Pick MEDIAN stop (not tightest) — reduces premature stop-outs
            if direction == "BUY":
                valid_stops = sorted([s for s in [pa_stop, bb_lower, ta_stop] if 0 < s < price])
                if len(valid_stops) >= 2:
                    stop = valid_stops[len(valid_stops) // 2]  # Median
                elif valid_stops:
                    stop = valid_stops[0]
                else:
                    stop = price * 0.97

                # Enforce ATR floor: stop can't be closer than 1.5x ATR
                if price - stop < min_stop_dist:
                    stop = price - min_stop_dist
            else:
                valid_stops = sorted([s for s in [pa_stop, bb_upper, ta_stop] if s > price])
                if len(valid_stops) >= 2:
                    stop = valid_stops[len(valid_stops) // 2]
                elif valid_stops:
                    stop = valid_stops[0]
                else:
                    stop = price * 1.03

                # Enforce ATR floor for SELL
                if stop - price < min_stop_dist:
                    stop = price + min_stop_dist

            risk = abs(price - stop)
            if risk <= 0 or risk / price < 0.005:
                i += STEP_SIZE
                continue

            # Cap risk at 5%
            if risk / price > 0.05:
                stop = price * 0.95 if direction == "BUY" else price * 1.05
                risk = abs(price - stop)

            # ── Targets ──
            # Use PA targets if available, else risk-based
            pa_t1 = float(pa_data.get("target_1") or 0)
            pa_t2 = float(pa_data.get("target_2") or 0)

            tgt_data = result.get("target_prices", {})

            if direction == "BUY":
                # PA target or consensus target or 2R
                consensus = tgt_data.get("consensus_upside", {}) if isinstance(tgt_data, dict) else {}
                consensus_tgt = consensus.get("target", 0) if isinstance(consensus, dict) else 0
                t1_rr = price + risk * 2.0   # 2R target
                t2_rr = price + risk * 3.0   # 3R target
                if pa_t1 and pa_t1 > price and pa_t1 >= t1_rr * 0.8:
                    target_1 = pa_t1
                elif consensus_tgt and consensus_tgt > price and consensus_tgt >= t1_rr * 0.8:
                    target_1 = consensus_tgt
                else:
                    target_1 = t1_rr
                target_2 = pa_t2 if (pa_t2 and pa_t2 > target_1) else t2_rr
            else:
                consensus = tgt_data.get("consensus_downside", {}) if isinstance(tgt_data, dict) else {}
                consensus_tgt = consensus.get("target", 0) if isinstance(consensus, dict) else 0
                t1_rr = price - risk * 2.0
                t2_rr = price - risk * 3.0
                if pa_t1 and 0 < pa_t1 < price and pa_t1 <= t1_rr * 1.2:
                    target_1 = pa_t1
                elif consensus_tgt and 0 < consensus_tgt < price and consensus_tgt <= t1_rr * 1.2:
                    target_1 = consensus_tgt
                else:
                    target_1 = t1_rr
                target_2 = pa_t2 if (pa_t2 and 0 < pa_t2 < target_1) else t2_rr

            # ── Build trade record ──
            ta_sig = result.get("ta_signal", {})
            rec = TripleTradeRecord(
                ticker=ticker,
                signal_date=str(dates[i - 1].date()) if hasattr(dates[i - 1], "date") else str(dates[i - 1]),
                direction=direction,
                triple_verdict=verdict_str,
                triple_score=round(combined_score, 1),
                triple_confidence=round(confidence, 1),
                alignment=alignment,
                bb_score=round(bb_total, 1),
                ta_score=round(ta_total, 1),
                pa_score=round(pa_total, 1),
                agreement_score=round(agree, 1),
                bb_phase=bb_data.get("phase", ""),
                bb_buy_signal=bb_data.get("buy_signal", False),
                bb_sell_signal=bb_data.get("sell_signal", False),
                ta_verdict=ta_sig.get("verdict", "HOLD"),
                ta_confidence=ta_sig.get("confidence", 0),
                pa_signal=pa_data.get("signal_type", ""),
                pa_strength=pa_data.get("strength", ""),
                pa_always_in=pa_data.get("always_in", "FLAT"),
                entry_price=round(price, 2),
                stop_loss=round(stop, 2),
                target_1=round(target_1, 2),
                target_2=round(target_2, 2),
            )

            # ── Walk forward for outcome ──
            outcome = _evaluate_trade(
                direction=direction,
                entry=price,
                stop=stop,
                target_1=target_1,
                target_2=target_2,
                highs=highs[i: i + MAX_HOLD],
                lows=lows[i: i + MAX_HOLD],
                closes=closes[i: i + MAX_HOLD],
                bb_upper=bb_upper if direction == "SELL" else None,
                bb_lower=bb_lower if direction == "BUY" else None,
            )

            rec.outcome = outcome["outcome"]
            rec.exit_price = outcome["exit_price"]
            rec.bars_held = outcome["bars_held"]
            rec.pnl_pct = outcome["pnl_pct"]
            rec.exit_method = outcome["exit_method"]

            if outcome["outcome"] == "NO_ENTRY":
                i += STEP_SIZE
                continue

            exit_idx = i + outcome["bars_held"] - 1
            if exit_idx < n:
                rec.exit_date = str(dates[exit_idx].date()) if hasattr(dates[exit_idx], "date") else str(dates[exit_idx])

            trades.append(asdict(rec))
            i += max(COOLDOWN, outcome["bars_held"])

        except Exception:
            i += STEP_SIZE
            continue

    return trades


# ═══════════════════════════════════════════════════════════════
#  METRICS COMPUTATION
# ═══════════════════════════════════════════════════════════════
def _compute_metrics(trades: List[dict]) -> dict:
    """Comprehensive metrics from all triple engine trades."""
    if not trades:
        return {"total_trades": 0}

    total = len(trades)
    wins = [t for t in trades if t["outcome"].startswith("WIN")]
    losses = [t for t in trades if t["outcome"] == "LOSS"]
    breakevens = [t for t in trades if t["outcome"] == "BREAKEVEN"]
    tw = [t for t in trades if t["outcome"] == "TIMEOUT_WIN"]
    tl = [t for t in trades if t["outcome"] == "TIMEOUT_LOSS"]

    win_count = len(wins)
    loss_count = len(losses)
    be_count = len(breakevens)
    tw_count = len(tw)
    tl_count = len(tl)

    # WR: wins / decided trades (exclude breakevens from denominator)
    decided = total - be_count
    win_rate = win_count / decided * 100 if decided > 0 else 0
    adjusted_wr = (win_count + tw_count * 0.5) / decided * 100 if decided > 0 else 0

    all_pnl = [t["pnl_pct"] for t in trades]
    avg_pnl = np.mean(all_pnl)
    total_pnl = sum(all_pnl)

    avg_win = np.mean([t["pnl_pct"] for t in wins]) if wins else 0
    avg_loss = np.mean([t["pnl_pct"] for t in losses]) if losses else 0

    gross_profit = sum(t["pnl_pct"] for t in trades if t["pnl_pct"] > 0)
    gross_loss = abs(sum(t["pnl_pct"] for t in trades if t["pnl_pct"] < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    avg_bars = np.mean([t["bars_held"] for t in trades])

    # Max consecutive wins/losses
    max_consec_win = max_consec_loss = cur_win = cur_loss = 0
    for t in trades:
        if t["outcome"].startswith("WIN"):
            cur_win += 1; cur_loss = 0
            max_consec_win = max(max_consec_win, cur_win)
        else:
            cur_loss += 1; cur_win = 0
            max_consec_loss = max(max_consec_loss, cur_loss)

    # Max drawdown — rolling window (DD_WINDOW trades) for realistic measurement
    all_pnl_arr = [t["pnl_pct"] for t in trades]
    max_dd = 0
    if len(all_pnl_arr) >= DD_WINDOW:
        for start in range(0, len(all_pnl_arr) - DD_WINDOW + 1, DD_WINDOW // 4):
            chunk = all_pnl_arr[start:start + DD_WINDOW]
            cum = 0; peak = 0; dd = 0
            for p in chunk:
                cum += p
                peak = max(peak, cum)
                dd = max(dd, peak - cum)
            max_dd = max(max_dd, dd)
    else:
        cum = 0; peak = 0
        for p in all_pnl_arr:
            cum += p
            peak = max(peak, cum)
            max_dd = max(max_dd, peak - cum)

    # ── Direction Split ──
    buys = [t for t in trades if t["direction"] == "BUY"]
    sells = [t for t in trades if t["direction"] == "SELL"]
    buy_wr = sum(1 for t in buys if t["outcome"].startswith("WIN")) / len(buys) * 100 if buys else 0
    sell_wr = sum(1 for t in sells if t["outcome"].startswith("WIN")) / len(sells) * 100 if sells else 0
    buy_pnl = np.mean([t["pnl_pct"] for t in buys]) if buys else 0
    sell_pnl = np.mean([t["pnl_pct"] for t in sells]) if sells else 0

    # ── By Triple Verdict ──
    verdict_metrics = {}
    for v in ["SUPER STRONG BUY", "STRONG BUY", "BUY", "SELL", "STRONG SELL", "SUPER STRONG SELL"]:
        vt = [t for t in trades if t["triple_verdict"] == v]
        if vt:
            vw = sum(1 for t in vt if t["outcome"].startswith("WIN"))
            verdict_metrics[v] = {
                "trades": len(vt), "wins": vw,
                "win_rate": round(vw / len(vt) * 100, 1),
                "avg_pnl": round(float(np.mean([t["pnl_pct"] for t in vt])), 2),
                "profit_factor": round(
                    sum(t["pnl_pct"] for t in vt if t["pnl_pct"] > 0) /
                    max(abs(sum(t["pnl_pct"] for t in vt if t["pnl_pct"] < 0)), 0.01), 2),
            }

    # ── By Alignment ──
    alignment_metrics = {}
    for a in ["TRIPLE_ALIGNED", "DOUBLE_ALIGNED", "CONFLICTING", "ALL_NEUTRAL", "SINGLE", "MIXED"]:
        at = [t for t in trades if t["alignment"] == a]
        if at:
            aw = sum(1 for t in at if t["outcome"].startswith("WIN"))
            alignment_metrics[a] = {
                "trades": len(at), "wins": aw,
                "win_rate": round(aw / len(at) * 100, 1),
                "avg_pnl": round(float(np.mean([t["pnl_pct"] for t in at])), 2),
            }

    # ── By BB Phase ──
    phase_metrics = {}
    for p in ["COMPRESSION", "DIRECTION", "EXPLOSION", "POST-BREAKOUT", "NORMAL"]:
        pt = [t for t in trades if t["bb_phase"] == p]
        if pt:
            pw = sum(1 for t in pt if t["outcome"].startswith("WIN"))
            phase_metrics[p] = {
                "trades": len(pt), "wins": pw,
                "win_rate": round(pw / len(pt) * 100, 1),
                "avg_pnl": round(float(np.mean([t["pnl_pct"] for t in pt])), 2),
            }

    # ── By PA Strength ──
    strength_metrics = {}
    for s in ["STRONG", "MODERATE", "WEAK", ""]:
        st = [t for t in trades if t["pa_strength"] == s]
        if st:
            sw = sum(1 for t in st if t["outcome"].startswith("WIN"))
            label = s if s else "NO_PA_SIGNAL"
            strength_metrics[label] = {
                "trades": len(st), "wins": sw,
                "win_rate": round(sw / len(st) * 100, 1),
                "avg_pnl": round(float(np.mean([t["pnl_pct"] for t in st])), 2),
            }

    # ── By PA Always-In Direction ──
    ai_metrics = {}
    for ai in ["LONG", "SHORT", "FLAT"]:
        ait = [t for t in trades if t["pa_always_in"] == ai]
        if ait:
            aiw = sum(1 for t in ait if t["outcome"].startswith("WIN"))
            ai_metrics[ai] = {
                "trades": len(ait), "wins": aiw,
                "win_rate": round(aiw / len(ait) * 100, 1),
                "avg_pnl": round(float(np.mean([t["pnl_pct"] for t in ait])), 2),
            }

    # ── By Exit Method ──
    exit_metrics = {}
    for em in ["STOP", "TARGET_1", "TARGET_2", "TRAIL_BE", "TRAIL_STOP", "BAND_TAG", "TIMEOUT"]:
        et = [t for t in trades if t["exit_method"] == em]
        if et:
            exit_metrics[em] = {
                "trades": len(et),
                "pct_of_total": round(len(et) / total * 100, 1),
                "avg_pnl": round(float(np.mean([t["pnl_pct"] for t in et])), 2),
            }

    # ── By Confidence Tier ──
    conf_metrics = {}
    for label, lo, hi in [("HIGH (70+)", 70, 200), ("MODERATE (40-69)", 40, 70), ("LOW (<40)", 0, 40)]:
        ct = [t for t in trades if lo <= t["triple_confidence"] < hi]
        if ct:
            cw = sum(1 for t in ct if t["outcome"].startswith("WIN"))
            conf_metrics[label] = {
                "trades": len(ct), "wins": cw,
                "win_rate": round(cw / len(ct) * 100, 1),
                "avg_pnl": round(float(np.mean([t["pnl_pct"] for t in ct])), 2),
            }

    # ── By Score Bucket ──
    score_metrics = {}
    buckets = [
        ("130+ (SUPER STRONG)", 130, 999),
        ("80-129 (STRONG)", 80, 130),
        ("45-79 (MODERATE)", 45, 80),
        ("-44 to -80 (SELL)", -80, -44),
        ("-80 to -130 (STRONG SELL)", -130, -80),
        ("<-130 (SUPER STRONG SELL)", -999, -130),
    ]
    for label, lo, hi in buckets:
        bt = [t for t in trades if lo <= t["triple_score"] <= hi]
        if bt:
            bw = sum(1 for t in bt if t["outcome"].startswith("WIN"))
            score_metrics[label] = {
                "trades": len(bt), "wins": bw,
                "win_rate": round(bw / len(bt) * 100, 1),
                "avg_pnl": round(float(np.mean([t["pnl_pct"] for t in bt])), 2),
            }

    # ── System Agreement Count ──
    agreement_count_stats = {}
    for t in trades:
        direction = t["direction"]
        agree_count = 0
        # BB agrees?
        if (t["bb_buy_signal"] and direction == "BUY") or (t["bb_sell_signal"] and direction == "SELL"):
            agree_count += 1
        elif t["bb_score"] > 10 and direction == "BUY":
            agree_count += 1
        elif t["bb_score"] < -10 and direction == "SELL":
            agree_count += 1
        # TA agrees?
        tv = t["ta_verdict"]
        if ("BUY" in tv and direction == "BUY") or ("SELL" in tv and direction == "SELL"):
            agree_count += 1
        # PA agrees?
        if t["pa_signal"] == direction:
            agree_count += 1

        agree_count = max(1, agree_count)
        key = f"{agree_count}_of_3"
        if key not in agreement_count_stats:
            agreement_count_stats[key] = {"trades": 0, "wins": 0, "pnl_list": []}
        agreement_count_stats[key]["trades"] += 1
        if t["outcome"].startswith("WIN"):
            agreement_count_stats[key]["wins"] += 1
        agreement_count_stats[key]["pnl_list"].append(t["pnl_pct"])

    agreement_summary = {}
    for k, v in sorted(agreement_count_stats.items()):
        agreement_summary[k] = {
            "trades": v["trades"],
            "pct_of_total": round(v["trades"] / total * 100, 1),
            "win_rate": round(v["wins"] / v["trades"] * 100, 1) if v["trades"] else 0,
            "avg_pnl": round(float(np.mean(v["pnl_list"])), 2) if v["pnl_list"] else 0,
        }

    # ── Grade ──
    if win_rate >= 65 and profit_factor >= 1.5:
        grade = "A"
    elif win_rate >= 55 and profit_factor >= 1.2:
        grade = "B"
    elif win_rate >= 45 and profit_factor >= 1.0:
        grade = "C"
    elif win_rate >= 35 and profit_factor >= 0.8:
        grade = "D"
    else:
        grade = "F"

    return {
        "total_trades": total,
        "wins": win_count,
        "losses": loss_count,
        "breakevens": be_count,
        "timeout_wins": tw_count,
        "timeout_losses": tl_count,
        "win_rate": round(win_rate, 1),
        "adjusted_win_rate": round(adjusted_wr, 1),
        "avg_pnl_pct": round(float(avg_pnl), 2),
        "total_pnl_pct": round(float(total_pnl), 2),
        "avg_win_pnl": round(float(avg_win), 2),
        "avg_loss_pnl": round(float(avg_loss), 2),
        "profit_factor": round(float(profit_factor), 2),
        "avg_bars_held": round(float(avg_bars), 1),
        "max_consecutive_wins": max_consec_win,
        "max_consecutive_losses": max_consec_loss,
        "max_drawdown_pct": round(max_dd, 2),
        "grade": grade,
        "buy_trades": len(buys),
        "sell_trades": len(sells),
        "buy_win_rate": round(buy_wr, 1),
        "sell_win_rate": round(sell_wr, 1),
        "buy_avg_pnl": round(float(buy_pnl), 2),
        "sell_avg_pnl": round(float(sell_pnl), 2),
        "by_triple_verdict": verdict_metrics,
        "by_alignment": alignment_metrics,
        "by_bb_phase": phase_metrics,
        "by_pa_strength": strength_metrics,
        "by_pa_always_in": ai_metrics,
        "by_confidence": conf_metrics,
        "by_score_bucket": score_metrics,
        "by_exit_method": exit_metrics,
        "system_agreement": agreement_summary,
    }


# ═══════════════════════════════════════════════════════════════
#  REPORT PRINTER
# ═══════════════════════════════════════════════════════════════
def _print_report(m: dict) -> None:
    """Print formatted Triple Engine backtest report."""
    print("\n" + "=" * 74)
    print("   TRIPLE CONVICTION ENGINE — BACKTEST REPORT")
    print("   BB (100) + TA (100) + PA (100) + Cross-Validation (±60) = 360 max")
    dir_f = m.get("meta", {}).get("direction_filter", "ALL")
    dir_label = f"{dir_f}-ONLY" if dir_f != "ALL" else "ALL directions"
    stocks = m.get("meta", {}).get("stocks_with_signals", "?")
    print(f"   {dir_label} | {m.get('meta', {}).get('total_csv', '?')} stocks scanned | {stocks} with signals")
    print("=" * 74)

    if m.get("total_trades", 0) == 0:
        print("  No trades generated.")
        return

    # ── Overall ──
    print(f"\n{'═══ OVERALL RESULTS ═══':^74}")
    print("-" * 74)
    print(f"  Total Trades          : {m['total_trades']:,}")
    print(f"  Wins (target hit)     : {m['wins']:,}")
    print(f"  Losses (stop hit)     : {m['losses']:,}")
    print(f"  Breakevens (trail BE) : {m.get('breakevens', 0):,}")
    print(f"  Timeout Wins          : {m['timeout_wins']:,}")
    print(f"  Timeout Losses        : {m['timeout_losses']:,}")
    print(f"  Win Rate              : {m['win_rate']:.1f}%")
    print(f"  Adjusted Win Rate     : {m['adjusted_win_rate']:.1f}%  (timeout_win = 0.5 credit)")
    print(f"  Profit Factor         : {m['profit_factor']:.2f}")
    print(f"  Avg P&L per Trade     : {m['avg_pnl_pct']:+.2f}%")
    print(f"  Avg Win P&L           : {m['avg_win_pnl']:+.2f}%")
    print(f"  Avg Loss P&L          : {m['avg_loss_pnl']:+.2f}%")
    print(f"  Total Cumulative P&L  : {m['total_pnl_pct']:+,.0f}%")
    print(f"  Avg Bars Held         : {m['avg_bars_held']:.1f}")
    print(f"  Max Consecutive Wins  : {m['max_consecutive_wins']}")
    print(f"  Max Consecutive Losses: {m['max_consecutive_losses']}")
    print(f"  Max Drawdown          : {m['max_drawdown_pct']:.2f}%")
    print(f"  GRADE                 : {m['grade']}")

    # ── Direction ──
    print(f"\n{'═══ DIRECTION SPLIT ═══':^74}")
    print("-" * 74)
    print(f"  BUY  trades: {m['buy_trades']:>6,}  WR: {m['buy_win_rate']:5.1f}%  avg P&L: {m['buy_avg_pnl']:+.2f}%")
    print(f"  SELL trades: {m['sell_trades']:>6,}  WR: {m['sell_win_rate']:5.1f}%  avg P&L: {m['sell_avg_pnl']:+.2f}%")

    # ── By Triple Verdict ──
    vd = m.get("by_triple_verdict", {})
    if vd:
        print(f"\n{'═══ BY TRIPLE VERDICT ═══':^74}")
        print("-" * 74)
        print(f"  {'Verdict':<22s} {'Trades':>7s} {'Wins':>6s} {'WR%':>7s} {'Avg P&L':>9s} {'PF':>6s}")
        print(f"  {'─' * 60}")
        for v in ["SUPER STRONG BUY", "STRONG BUY", "BUY", "SELL", "STRONG SELL", "SUPER STRONG SELL"]:
            if v in vd:
                d = vd[v]
                print(f"  {v:<22s} {d['trades']:>7,} {d['wins']:>6,} {d['win_rate']:>6.1f}% {d['avg_pnl']:>+8.2f}% {d['profit_factor']:>5.2f}")

    # ── By Alignment ──
    ad = m.get("by_alignment", {})
    if ad:
        print(f"\n{'═══ BY ALIGNMENT ═══':^74}")
        print("-" * 74)
        print(f"  {'Alignment':<22s} {'Trades':>7s} {'Wins':>6s} {'WR%':>7s} {'Avg P&L':>9s}")
        print(f"  {'─' * 52}")
        for a in ["TRIPLE_ALIGNED", "DOUBLE_ALIGNED", "CONFLICTING", "SINGLE", "MIXED"]:
            if a in ad:
                d = ad[a]
                print(f"  {a:<22s} {d['trades']:>7,} {d['wins']:>6,} {d['win_rate']:>6.1f}% {d['avg_pnl']:>+8.2f}%")

    # ── By BB Phase ──
    pd_ = m.get("by_bb_phase", {})
    if pd_:
        print(f"\n{'═══ BY BB PHASE ═══':^74}")
        print("-" * 74)
        for p in ["COMPRESSION", "DIRECTION", "EXPLOSION", "POST-BREAKOUT", "NORMAL"]:
            if p in pd_:
                d = pd_[p]
                print(f"  {p:<22s} {d['trades']:>7,} trades  WR: {d['win_rate']:>5.1f}%  avg P&L: {d['avg_pnl']:>+.2f}%")

    # ── By PA Strength ──
    sd = m.get("by_pa_strength", {})
    if sd:
        print(f"\n{'═══ BY PA STRENGTH ═══':^74}")
        print("-" * 74)
        for s in ["STRONG", "MODERATE", "WEAK", "NO_PA_SIGNAL"]:
            if s in sd:
                d = sd[s]
                print(f"  {s:<22s} {d['trades']:>7,} trades  WR: {d['win_rate']:>5.1f}%  avg P&L: {d['avg_pnl']:>+.2f}%")

    # ── By PA Always-In ──
    ai = m.get("by_pa_always_in", {})
    if ai:
        print(f"\n{'═══ BY PA ALWAYS-IN ═══':^74}")
        print("-" * 74)
        for a in ["LONG", "SHORT", "FLAT"]:
            if a in ai:
                d = ai[a]
                print(f"  {a:<22s} {d['trades']:>7,} trades  WR: {d['win_rate']:>5.1f}%  avg P&L: {d['avg_pnl']:>+.2f}%")

    # ── By Confidence ──
    cd = m.get("by_confidence", {})
    if cd:
        print(f"\n{'═══ BY CONFIDENCE TIER ═══':^74}")
        print("-" * 74)
        for c in ["HIGH (70+)", "MODERATE (40-69)", "LOW (<40)"]:
            if c in cd:
                d = cd[c]
                print(f"  {c:<22s} {d['trades']:>7,} trades  WR: {d['win_rate']:>5.1f}%  avg P&L: {d['avg_pnl']:>+.2f}%")

    # ── By Score Bucket ──
    sb = m.get("by_score_bucket", {})
    if sb:
        print(f"\n{'═══ BY SCORE BUCKET ═══':^74}")
        print("-" * 74)
        for label, d in sb.items():
            print(f"  {label:<30s} {d['trades']:>6,} trades  WR: {d['win_rate']:>5.1f}%  avg P&L: {d['avg_pnl']:>+.2f}%")

    # ── System Agreement ──
    sa = m.get("system_agreement", {})
    if sa:
        print(f"\n{'═══ SYSTEM AGREEMENT (BB + TA + PA) ═══':^74}")
        print("-" * 74)
        print(f"  {'Systems Agree':<15s} {'Trades':>7s} {'% Total':>8s} {'WR%':>7s} {'Avg P&L':>9s}")
        print(f"  {'─' * 50}")
        for k in sorted(sa.keys()):
            d = sa[k]
            print(f"  {k:<15s} {d['trades']:>7,} {d['pct_of_total']:>7.1f}% {d['win_rate']:>6.1f}% {d['avg_pnl']:>+8.2f}%")

    # ── By Exit Method ──
    em = m.get("by_exit_method", {})
    if em:
        print(f"\n{'═══ BY EXIT METHOD ═══':^74}")
        print("-" * 74)
        for e in ["STOP", "TARGET_1", "TARGET_2", "TRAIL_BE", "TRAIL_STOP", "BAND_TAG", "TIMEOUT"]:
            if e in em:
                d = em[e]
                print(f"  {e:<15s} {d['trades']:>7,} ({d['pct_of_total']:>5.1f}%)  avg P&L: {d['avg_pnl']:>+.2f}%")

    # ── Reliability Score ──
    print(f"\n{'═══ RELIABILITY SCORECARD ═══':^74}")
    print("=" * 74)
    score = 0
    checks = []

    # 1. Win Rate (0-20 pts) — continuous linear scale
    wr = m["win_rate"]
    if wr >= 65: s = 20
    elif wr >= 55: s = 15 + (wr - 55) / 10 * 5  # 15-20 linearly
    elif wr >= 45: s = 10 + (wr - 45) / 10 * 5  # 10-15 linearly
    elif wr >= 35: s = 5 + (wr - 35) / 10 * 5   # 5-10 linearly
    elif wr >= 25: s = (wr - 25) / 10 * 5        # 0-5 linearly
    else: s = 0
    s = round(s, 1)
    score += s
    checks.append(f"  Win Rate ({wr:.1f}%):                  {s}/20 pts")

    # 2. Profit Factor (0-20 pts) — continuous
    pf = m["profit_factor"]
    if pf >= 2.0: s = 20
    elif pf >= 1.5: s = 15 + (pf - 1.5) / 0.5 * 5
    elif pf >= 1.2: s = 10 + (pf - 1.2) / 0.3 * 5
    elif pf >= 1.0: s = 5 + (pf - 1.0) / 0.2 * 5
    elif pf >= 0.8: s = (pf - 0.8) / 0.2 * 5
    else: s = 0
    s = round(min(20, s), 1)
    score += s
    checks.append(f"  Profit Factor ({pf:.2f}):              {s}/20 pts")

    # 3. Avg P&L per trade (0-15 pts) — continuous
    ap = m["avg_pnl_pct"]
    if ap >= 2.0: s = 15
    elif ap >= 1.0: s = 12 + (ap - 1.0) / 1.0 * 3
    elif ap >= 0.5: s = 8 + (ap - 0.5) / 0.5 * 4
    elif ap >= 0.0: s = 4 + ap / 0.5 * 4
    elif ap >= -0.5: s = (ap + 0.5) / 0.5 * 4
    else: s = 0
    s = round(min(15, max(0, s)), 1)
    score += s
    checks.append(f"  Avg P&L ({ap:+.2f}%):                 {s}/15 pts")

    # 4. Alignment improvement (0-15 pts) — does TRIPLE_ALIGNED beat others?
    al = m.get("by_alignment", {})
    triple_wr = al.get("TRIPLE_ALIGNED", {}).get("win_rate", 0)
    # Compare vs worst alignment
    worst_wr = 100
    for k, v in al.items():
        if v.get("trades", 0) >= 5 and k != "TRIPLE_ALIGNED":
            worst_wr = min(worst_wr, v["win_rate"])
    if worst_wr == 100:
        worst_wr = triple_wr
    spread = triple_wr - worst_wr
    if spread >= 20: s = 15
    elif spread >= 10: s = 10 + (spread - 10) / 10 * 5
    elif spread >= 5: s = 7 + (spread - 5) / 5 * 3
    elif spread >= 0: s = 3 + spread / 5 * 4
    else: s = 0
    s = round(min(15, max(0, s)), 1)
    score += s
    checks.append(f"  Alignment Signal Spread ({spread:+.0f}pp): {s}/15 pts")

    # 5. Agreement Quality (0-15 pts) — 3-component: floor quality + profitability + ladder
    sa_list = sorted([(k, v) for k, v in sa.items()])
    # Component A: Floor quality (0-5) — WR of lowest agreement bucket
    floor_wr = min((v["win_rate"] for _, v in sa_list), default=0) if sa_list else 0
    if floor_wr >= 45: sa_a = 5
    elif floor_wr >= 40: sa_a = 4
    elif floor_wr >= 35: sa_a = 3
    elif floor_wr >= 30: sa_a = 2
    else: sa_a = 1
    # Component B: Profitability consistency (0-5)
    all_pnls = [v["avg_pnl"] for _, v in sa_list]
    all_positive = all(p > 0 for p in all_pnls) if all_pnls else False
    if all_positive and all(p >= 0.5 for p in all_pnls): sa_b = 5
    elif all_positive: sa_b = 4
    elif sum(1 for p in all_pnls if p > 0) > len(all_pnls) / 2: sa_b = 3
    else: sa_b = 1
    # Component C: Ladder & concentration (0-5)
    wrs = [v["win_rate"] for _, v in sa_list]
    monotonic = all(wrs[j] >= wrs[j - 1] for j in range(1, len(wrs))) if len(wrs) > 1 else False
    agree_spread = (max(wrs) - min(wrs)) if wrs else 0
    top_key = sa_list[-1][0] if sa_list else ""
    top_vol_pct = sa.get(top_key, {}).get("pct_of_total", 0) if top_key else 0
    if monotonic and agree_spread >= 5: sa_c = 5
    elif monotonic or agree_spread >= 5: sa_c = 4
    elif agree_spread >= 0 and top_vol_pct >= 40: sa_c = 3
    elif top_vol_pct >= 30: sa_c = 2
    else: sa_c = 1
    s = sa_a + sa_b + sa_c
    score += s
    checks.append(f"  Agreement Quality (floor {floor_wr:.0f}%, all+ve={'Y' if all_positive else 'N'}, spread {agree_spread:+.1f}pp): {s}/15 pts")

    # 6. Max Drawdown in R-units (0-15 pts) — normalized by avg loss size
    dd_raw = m["max_drawdown_pct"]
    avg_loss_abs = abs(m["avg_loss_pnl"]) if m["avg_loss_pnl"] != 0 else 1
    dd_R = dd_raw / avg_loss_abs  # Drawdown in "average-loss units"
    if dd_R <= 15: s = 15
    elif dd_R <= 25: s = 12 + (25 - dd_R) / 10 * 3
    elif dd_R <= 40: s = 8 + (40 - dd_R) / 15 * 4
    elif dd_R <= 60: s = 4 + (60 - dd_R) / 20 * 4
    else: s = 0
    s = round(min(15, max(0, s)), 1)
    score += s
    checks.append(f"  Max Drawdown ({dd_R:.1f}R, {DD_WINDOW}-trade window, raw {dd_raw:.0f}%): {s}/15 pts")

    for c in checks:
        print(c)
    score = round(score, 1)
    print(f"  {'─' * 50}")
    print(f"  TOTAL RELIABILITY SCORE: {score}/100")

    if score >= 80: verdict = "EXCELLENT — Production-ready, high confidence"
    elif score >= 60: verdict = "GOOD — Reliable with known edge"
    elif score >= 40: verdict = "FAIR — Usable with risk management"
    elif score >= 25: verdict = "POOR — Needs improvement"
    else: verdict = "UNRELIABLE — Do not use for live trading"
    print(f"  VERDICT: {verdict}")

    # ── Best segments ──
    best = []
    for section, data in [
        ("Verdict", m.get("by_triple_verdict", {})),
        ("Alignment", m.get("by_alignment", {})),
        ("BB Phase", m.get("by_bb_phase", {})),
        ("PA Strength", m.get("by_pa_strength", {})),
        ("Confidence", m.get("by_confidence", {})),
    ]:
        for k, v in data.items():
            if v.get("trades", 0) >= 10 and v.get("win_rate", 0) >= 50:
                best.append((section, k, v["win_rate"], v["avg_pnl"], v["trades"]))

    if best:
        print(f"\n  {'PROFITABLE SEGMENTS (WR >= 50%, 10+ trades):':^70}")
        print(f"  {'-' * 70}")
        for sec, k, wrr, pnl, cnt in sorted(best, key=lambda x: -x[2]):
            print(f"    [{sec}] {k}: {wrr:.1f}% WR, {pnl:+.2f}% avg P&L ({cnt} trades)")

    print("=" * 74)


# ═══════════════════════════════════════════════════════════════
#  MAIN ENTRY
# ═══════════════════════════════════════════════════════════════
def run_triple_backtest(max_stocks: int = 0, workers: int = NUM_WORKERS,
                        direction: str = DIRECTION_FILTER, verbose: bool = True) -> dict:
    """Run multi-threaded Triple Engine backtest."""
    global DIRECTION_FILTER
    DIRECTION_FILTER = direction.upper()

    csv_files = sorted(glob.glob(os.path.join(CSV_DIR, "*.csv")))
    if max_stocks > 0:
        csv_files = csv_files[:max_stocks]

    total = len(csv_files)
    t0 = time.time()

    dir_label = f"Direction: {DIRECTION_FILTER}-ONLY" if DIRECTION_FILTER != "ALL" else "Direction: ALL (BUY + SELL)"
    if verbose:
        print(f"TRIPLE ENGINE BACKTEST — {total} stocks, {workers} workers")
        print(f"Window: {WINDOW_SIZE} bars | Step: {STEP_SIZE} | Cooldown: {COOLDOWN} | Max Hold: {MAX_HOLD}")
        print(f"{dir_label}")
        print("=" * 74)

    all_trades: List[dict] = []
    stocks_processed = 0
    stocks_with_signals = 0
    stocks_skipped = 0

    done_count = 0
    ctx = mp.get_context("fork")
    with ctx.Pool(processes=workers) as pool:
        for trades in pool.imap_unordered(_process_stock, csv_files, chunksize=4):
            done_count += 1

            if trades is None:
                stocks_skipped += 1
            elif len(trades) == 0:
                stocks_processed += 1
            else:
                stocks_processed += 1
                stocks_with_signals += 1
                all_trades.extend(trades)

            if verbose and done_count % 50 == 0:
                elapsed = time.time() - t0
                rate = done_count / elapsed if elapsed > 0 else 0
                print(f"  [{done_count}/{total}] {rate:.1f} stocks/sec | "
                      f"{len(all_trades):,} trades | elapsed {elapsed:.0f}s",
                      flush=True)

    elapsed = time.time() - t0
    if verbose:
        print(f"\n  Completed: {done_count}/{total} in {elapsed:.0f}s "
              f"({done_count / elapsed:.1f} stocks/sec)")
        print(f"  Total trades: {len(all_trades):,}")

    # ── Compute metrics ──
    metrics = _compute_metrics(all_trades)
    metrics["meta"] = {
        "total_csv": total,
        "stocks_processed": stocks_processed,
        "stocks_with_signals": stocks_with_signals,
        "stocks_skipped": stocks_skipped,
        "elapsed_sec": round(elapsed, 1),
        "workers": workers,
        "direction_filter": DIRECTION_FILTER,
        "config": {
            "window_size": WINDOW_SIZE,
            "step_size": STEP_SIZE,
            "cooldown": COOLDOWN,
            "max_hold": MAX_HOLD,
        },
    }

    if verbose:
        _print_report(metrics)

    # Save results
    out_path = os.path.join(_ROOT, "backtest_triple_results.json")

    # Handle inf/nan for JSON
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

    output = _clean({
        "metrics": metrics,
        "trades_sample": all_trades[:500],
        "total_trades_count": len(all_trades),
    })

    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    if verbose:
        print(f"\n  Results saved to: {out_path}")

    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Triple Engine Backtest")
    parser.add_argument("--max", type=int, default=0, help="Max stocks (0=all)")
    parser.add_argument("--workers", type=int, default=NUM_WORKERS, help="Worker processes")
    parser.add_argument("--direction", type=str, default="ALL", choices=["ALL", "BUY", "SELL"])
    args = parser.parse_args()

    run_triple_backtest(max_stocks=args.max, workers=args.workers, direction=args.direction)
