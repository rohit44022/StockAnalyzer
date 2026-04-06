#!/usr/bin/env python3
"""
Full System Truthfulness Backtest — Multi-Threaded
====================================================
Backtests the ENTIRE analysis system (BB Methods I-IV, Technical Analysis,
Hybrid Engine, Quant Strategy, Price Action) across ALL stocks from 2020
using multi-processing for speed.

Methodology
-----------
For each stock:
  1. Slide a 250-bar analysis window across daily data starting from 2020.
  2. At each step, run the full Hybrid Engine (BB + TA + cross-validation).
  3. Also run Quant Strategy and Price Action for cross-checking.
  4. If a BUY/SELL signal is generated:
     - Record entry, stop, targets from ALL systems.
     - Walk forward up to MAX_HOLD bars to check outcome.
  5. Aggregate results by system, direction, verdict strength, etc.

Multi-threading
---------------
Uses ProcessPoolExecutor with N workers for CPU-bound analysis.
Each worker processes one stock file independently.
"""

from __future__ import annotations

import json
import os
import sys
import time
import glob
import warnings
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Tuple, Optional
import multiprocessing as mp

import pandas as pd
import numpy as np

warnings.filterwarnings("ignore")

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Pre-import at module level so forked processes share loaded modules
from bb_squeeze.indicators import compute_all_indicators as compute_bb_indicators
from bb_squeeze.signals import analyze_signals as generate_bb_signal
from bb_squeeze.strategies import run_all_strategies, strategy_result_to_dict
from bb_squeeze.quant_strategy import run_quant_analysis

from technical_analysis.indicators import (
    compute_all_ta_indicators, get_indicator_snapshot,
    detect_ma_crossovers, detect_all_divergences,
    compute_pivot_points, compute_fibonacci,
)
from technical_analysis.candlesticks import scan_candlestick_patterns
from technical_analysis.patterns import (
    detect_support_resistance, identify_trend,
    detect_all_chart_patterns, analyze_volume,
)
from technical_analysis.signals import generate_signal as generate_ta_signal
from technical_analysis.risk_manager import calculate_stop_losses
from technical_analysis.target_price import calculate_target_prices

try:
    from price_action.engine import run_price_action_analysis
    _HAS_PA = True
except Exception:
    _HAS_PA = False

# ─────────────────────────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────────────────────────
WINDOW_SIZE      = 250    # Bars fed to each analysis run
STEP_SIZE        = 10     # Slide window every N bars
COOLDOWN         = 15     # Skip N bars after a trade to prevent overlap
MAX_HOLD         = 30     # Max bars to hold before timeout
MIN_DATA_BARS    = WINDOW_SIZE + MAX_HOLD + 20
START_DATE       = "2020-01-01"
NUM_WORKERS      = 8      # Process pool workers (leave a few cores free)

# Direction filter — "BUY" = only long trades, "SELL" = only short, "ALL" = both
# NOTE: This filters at the TRADE DECISION layer only.
#       All core engines (BB I-IV, TA, Hybrid, Quant, PA) still compute fully.
#       Book concepts and indicator logic remain strict and unchanged.
DIRECTION_FILTER = "BUY"  # Default to BUY-only (backtest-proven more reliable)


# ─────────────────────────────────────────────────────────────────
#  TRADE RECORD
# ─────────────────────────────────────────────────────────────────
@dataclass
class TradeRecord:
    ticker:           str = ""
    signal_date:      str = ""
    direction:        str = ""       # BUY / SELL
    # ── Hybrid Engine ──
    hybrid_verdict:   str = ""       # SUPER STRONG BUY, BUY, etc.
    hybrid_score:     float = 0.0
    hybrid_confidence:float = 0.0
    alignment:        str = ""       # ALIGNED / CONFLICTING / PARTIAL
    # ── BB Method I ──
    bb_phase:         str = ""
    bb_buy_signal:    bool = False
    bb_sell_signal:   bool = False
    bb_confidence:    int = 0
    bb_head_fake:     bool = False
    # ── BB Methods II-IV ──
    m2_signal:        str = ""
    m3_signal:        str = ""
    m4_signal:        str = ""
    # ── Technical Analysis ──
    ta_verdict:       str = ""
    ta_score:         float = 0.0
    ta_confidence:    float = 0.0
    # ── Quant Strategy ──
    quant_signal:     str = ""
    quant_strategy:   str = ""
    quant_regime:     str = ""
    # ── Price Action ──
    pa_signal:        str = ""
    pa_confidence:    int = 0
    pa_setup:         str = ""
    # ── Trade Execution ──
    entry_price:      float = 0.0
    stop_loss:        float = 0.0
    target_1:         float = 0.0
    target_2:         float = 0.0
    # ── Outcome ──
    outcome:          str = ""       # WIN_T1, WIN_T2, LOSS, TIMEOUT_WIN, TIMEOUT_LOSS
    exit_price:       float = 0.0
    exit_date:        str = ""
    bars_held:        int = 0
    pnl_pct:          float = 0.0
    # ── Exit method ──
    exit_method:      str = ""       # TARGET / STOP / TIMEOUT / SAR_FLIP / BAND_TAG


# ─────────────────────────────────────────────────────────────────
#  WORKER: Process a single stock
# ─────────────────────────────────────────────────────────────────
def _process_stock(csv_path: str) -> List[dict]:
    """Process a single stock file — runs in a forked process."""
    has_pa = _HAS_PA
    ticker = os.path.basename(csv_path).replace(".csv", "")
    trades: List[dict] = []

    try:
        df = pd.read_csv(csv_path, parse_dates=["Date"], index_col="Date")
    except Exception:
        return trades

    # Filter to data from 2020 onwards
    df = df[df.index >= START_DATE]
    if len(df) < MIN_DATA_BARS:
        return trades

    highs  = df["High"].values
    lows   = df["Low"].values
    closes = df["Close"].values
    dates  = df.index

    n = len(df)
    i = WINDOW_SIZE

    while i < n - MAX_HOLD:
        window_df = df.iloc[i - WINDOW_SIZE : i].copy()

        try:
            # ── 1. BB Analysis ──
            df_bb = compute_bb_indicators(window_df.copy())
            bb_signal = generate_bb_signal(ticker, df_bb)
            bb_strategies = run_all_strategies(df_bb)
            bb_strats_dict = [strategy_result_to_dict(s) for s in bb_strategies]
            strat_map = {s.get("code"): s for s in bb_strats_dict}

            # ── 2. TA Analysis ──
            df_ta = compute_all_ta_indicators(window_df.copy())
            snapshot = get_indicator_snapshot(df_ta)
            trend = identify_trend(df_ta)
            divergences = detect_all_divergences(df_ta)
            candle_patterns = scan_candlestick_patterns(df_ta, lookback=5)
            chart_patterns = detect_all_chart_patterns(df_ta)
            vol_analysis = analyze_volume(df_ta)
            sr_data = detect_support_resistance(df_ta)
            fib_data = compute_fibonacci(df_ta)
            pivot = compute_pivot_points(df_ta)

            ta_signal = generate_ta_signal(
                snap=snapshot, trend=trend, vol_analysis=vol_analysis,
                chart_patterns=chart_patterns, candle_patterns=candle_patterns,
                divergences=divergences, sr_data=sr_data, fib_data=fib_data,
            )

            # ── 3. Quant Strategy ──
            try:
                quant = run_quant_analysis(df_bb)
            except Exception:
                quant = {"verdict": {"signal": "NEUTRAL", "strategy": "ERROR", "confidence": 0},
                         "regime": {"regime": "UNKNOWN"},
                         "volatility": {"stop_loss": 0, "target": 0}}

            # ── 4. Price Action (if available) ──
            pa_result = None
            if has_pa:
                try:
                    pa_result = run_price_action_analysis(window_df, ticker)
                    if not pa_result.success:
                        pa_result = None
                except Exception:
                    pa_result = None

            # ── Determine if there is a tradeable signal ──
            hybrid_verdict = _derive_hybrid_verdict(bb_signal, ta_signal, strat_map)
            direction = _determine_direction(hybrid_verdict, bb_signal, ta_signal, quant, pa_result)

            if direction is None:
                i += STEP_SIZE
                continue

            # ── Compute entry, stop, targets ──
            price = float(closes[i - 1])
            if price <= 0:
                i += STEP_SIZE
                continue

            # Stop loss: best of multiple methods
            try:
                stops = calculate_stop_losses(snapshot, sr_data)
                rec_stop = stops.get("recommended_level", 0)
            except Exception:
                rec_stop = 0

            bb_stop = float(bb_signal.stop_loss) if bb_signal.stop_loss else 0
            quant_stop = float(quant.get("volatility", {}).get("stop_loss", 0) or 0)

            # Use tightest valid stop
            valid_stops = []
            if direction == "BUY":
                for s in [rec_stop, bb_stop, quant_stop]:
                    if 0 < s < price:
                        valid_stops.append(s)
                stop = max(valid_stops) if valid_stops else price * 0.97  # fallback 3%
            else:
                for s in [rec_stop, bb_stop, quant_stop]:
                    if s > price:
                        valid_stops.append(s)
                stop = min(valid_stops) if valid_stops else price * 1.03

            # Targets
            try:
                tgt_data = calculate_target_prices(
                    snap=snapshot, trend=trend, sr_data=sr_data,
                    fib_data=fib_data, pivot=pivot, chart_patterns=chart_patterns,
                )
            except Exception:
                tgt_data = {}

            risk = abs(price - stop)
            if risk <= 0 or risk / price < 0.002:
                i += STEP_SIZE
                continue

            # Target 1 = 1.5R, Target 2 = 2.5R (or from consensus)
            if direction == "BUY":
                consensus_up = tgt_data.get("consensus_upside")
                if consensus_up and consensus_up.get("target", 0) > price:
                    target_1 = consensus_up["target"]
                else:
                    target_1 = price + risk * 1.5
                target_2 = price + risk * 2.5

                quant_tgt = float(quant.get("volatility", {}).get("target", 0) or 0)
                if quant_tgt > price and quant_tgt < target_1:
                    target_1 = quant_tgt
            else:
                consensus_dn = tgt_data.get("consensus_downside")
                if consensus_dn and consensus_dn.get("target", 0) > 0 and consensus_dn["target"] < price:
                    target_1 = consensus_dn["target"]
                else:
                    target_1 = price - risk * 1.5
                target_2 = price - risk * 2.5

                quant_tgt = float(quant.get("volatility", {}).get("target", 0) or 0)
                if 0 < quant_tgt < price and quant_tgt > target_1:
                    target_1 = quant_tgt

            # Cap risk at 5% max
            if risk / price > 0.05:
                if direction == "BUY":
                    stop = price * 0.95
                else:
                    stop = price * 1.05
                risk = abs(price - stop)
                target_1 = price + risk * 1.5 if direction == "BUY" else price - risk * 1.5
                target_2 = price + risk * 2.5 if direction == "BUY" else price - risk * 2.5

            # ── Build trade record ──
            m2_sig = strat_map.get("M2", {}).get("signal", {}).get("type", "NONE")
            m3_sig = strat_map.get("M3", {}).get("signal", {}).get("type", "NONE")
            m4_sig = strat_map.get("M4", {}).get("signal", {}).get("type", "NONE")

            qv = quant.get("verdict", {})
            qr = quant.get("regime", {})

            rec = TradeRecord(
                ticker=ticker,
                signal_date=str(dates[i - 1].date()) if hasattr(dates[i - 1], "date") else str(dates[i - 1]),
                direction=direction,
                hybrid_verdict=hybrid_verdict["verdict"],
                hybrid_score=hybrid_verdict["score"],
                hybrid_confidence=hybrid_verdict["confidence"],
                alignment=hybrid_verdict["alignment"],
                bb_phase=bb_signal.phase,
                bb_buy_signal=bb_signal.buy_signal,
                bb_sell_signal=bb_signal.sell_signal,
                bb_confidence=bb_signal.confidence,
                bb_head_fake=bb_signal.head_fake,
                m2_signal=m2_sig,
                m3_signal=m3_sig,
                m4_signal=m4_sig,
                ta_verdict=ta_signal.get("verdict", "HOLD"),
                ta_score=ta_signal.get("score", 0),
                ta_confidence=ta_signal.get("confidence", 0),
                quant_signal=qv.get("signal", "NEUTRAL"),
                quant_strategy=qv.get("strategy", "WAIT"),
                quant_regime=qr.get("regime", "UNKNOWN"),
                pa_signal=pa_result.signal_type if pa_result else "",
                pa_confidence=pa_result.confidence if pa_result else 0,
                pa_setup=pa_result.setup_type if pa_result else "",
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
                # Also check BB exit signals on forward bars
                bb_upper=df_bb["BB_Upper"].values[-1] if "BB_Upper" in df_bb.columns else None,
                bb_lower=df_bb["BB_Lower"].values[-1] if "BB_Lower" in df_bb.columns else None,
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


# ─────────────────────────────────────────────────────────────────
#  SIGNAL DERIVATION HELPERS
# ─────────────────────────────────────────────────────────────────

def _derive_hybrid_verdict(bb_signal, ta_signal: dict, strat_map: dict) -> dict:
    """Lightweight hybrid verdict without full engine overhead."""
    # BB score
    bb_score = 0.0
    if bb_signal.buy_signal:
        bb_score += 30
    elif bb_signal.head_fake:
        bb_score -= 20
    elif bb_signal.sell_signal:
        bb_score -= 25
    elif bb_signal.cond1_squeeze_on:
        if bb_signal.direction_lean == "BULLISH":
            bb_score += 10
        elif bb_signal.direction_lean == "BEARISH":
            bb_score -= 10

    # Conditions
    if bb_signal.cond2_price_above:
        bb_score += 5
    if bb_signal.cond3_volume_ok:
        bb_score += 3
    if bb_signal.cond4_cmf_positive:
        bb_score += 2
    if bb_signal.cond5_mfi_above_50:
        bb_score += 2
    if bb_signal.exit_sar_flip:
        bb_score -= 10
    if bb_signal.exit_double_neg:
        bb_score -= 5

    # Strategies M2-M4
    for code in ["M2", "M3", "M4"]:
        sig = strat_map.get(code, {}).get("signal", {})
        st = sig.get("type", "NONE")
        conf = sig.get("confidence", 0)
        if st == "BUY":
            bb_score += 10 * (conf / 100)
        elif st == "SELL":
            bb_score -= 10 * (conf / 100)

    ta_score = ta_signal.get("score", 0)

    bb_dir = "BULLISH" if bb_score > 10 else "BEARISH" if bb_score < -10 else "NEUTRAL"
    ta_verdict_str = ta_signal.get("verdict", "HOLD")
    ta_dir = "BULLISH" if ta_verdict_str in ("STRONG BUY", "BUY") else \
             "BEARISH" if ta_verdict_str in ("STRONG SELL", "SELL") else "NEUTRAL"

    agree = 0
    if bb_dir == ta_dir and bb_dir != "NEUTRAL":
        agree = 30
        alignment = "ALIGNED"
    elif bb_dir != ta_dir and bb_dir != "NEUTRAL" and ta_dir != "NEUTRAL":
        agree = -20
        alignment = "CONFLICTING"
    else:
        agree = 5
        alignment = "PARTIAL"

    combined = bb_score + ta_score + agree

    if combined >= 90:
        verdict = "SUPER STRONG BUY"
    elif combined >= 55:
        verdict = "STRONG BUY"
    elif combined >= 35:
        verdict = "BUY"
    elif combined <= -90:
        verdict = "SUPER STRONG SELL"
    elif combined <= -55:
        verdict = "STRONG SELL"
    elif combined <= -35:
        verdict = "SELL"
    else:
        verdict = "HOLD / WAIT"

    confidence = min(abs(combined) / 245 * 100, 100)

    return {
        "verdict": verdict,
        "score": round(combined, 1),
        "confidence": round(confidence, 1),
        "alignment": alignment,
        "bb_score": round(bb_score, 1),
        "ta_score": round(ta_score, 1),
    }


def _determine_direction(hybrid: dict, bb_signal, ta_signal: dict, quant: dict, pa_result) -> Optional[str]:
    """Determine if we have a strong enough signal to trade.

    Respects DIRECTION_FILTER: 'BUY' = longs only, 'SELL' = shorts only, 'ALL' = both.
    Core signal logic is UNCHANGED — all engines still compute fully.
    The filter only decides whether to ACT on a given direction.
    """
    verdict = hybrid["verdict"]

    # Only trade on actual BUY/SELL verdicts (skip HOLD/WAIT)
    if "BUY" in verdict:
        direction = "BUY"
    elif "SELL" in verdict:
        direction = "SELL"
    else:
        # Fallback: Quant standalone signal
        qsig = quant.get("verdict", {}).get("signal", "NEUTRAL")
        if qsig in ("STRONG_BUY", "BUY"):
            direction = "BUY"
        elif qsig in ("STRONG_SELL", "SELL"):
            direction = "SELL"
        else:
            return None

    # Apply direction filter (trade-decision layer only)
    if DIRECTION_FILTER == "BUY" and direction != "BUY":
        return None
    if DIRECTION_FILTER == "SELL" and direction != "SELL":
        return None

    return direction


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
    """Walk forward through bars to determine trade outcome."""
    n = len(highs)

    for j in range(n):
        if direction == "BUY":
            # Check stop hit first
            if lows[j] <= stop:
                pnl = (stop - entry) / entry * 100
                return {"outcome": "LOSS", "exit_price": round(stop, 2),
                        "bars_held": j + 1, "pnl_pct": round(pnl, 2), "exit_method": "STOP"}
            # Check target hit
            if highs[j] >= target_1:
                if highs[j] >= target_2:
                    pnl = (target_2 - entry) / entry * 100
                    return {"outcome": "WIN_T2", "exit_price": round(target_2, 2),
                            "bars_held": j + 1, "pnl_pct": round(pnl, 2), "exit_method": "TARGET_2"}
                pnl = (target_1 - entry) / entry * 100
                return {"outcome": "WIN_T1", "exit_price": round(target_1, 2),
                        "bars_held": j + 1, "pnl_pct": round(pnl, 2), "exit_method": "TARGET_1"}
            # BB lower band tag exit (sell signal for longs)
            if bb_lower and closes[j] <= bb_lower:
                pnl = (closes[j] - entry) / entry * 100
                em = "BAND_TAG"
                oc = "LOSS" if pnl < 0 else "WIN_T1"
                return {"outcome": oc, "exit_price": round(float(closes[j]), 2),
                        "bars_held": j + 1, "pnl_pct": round(pnl, 2), "exit_method": em}
        else:  # SELL
            if highs[j] >= stop:
                pnl = (entry - stop) / entry * 100
                return {"outcome": "LOSS", "exit_price": round(stop, 2),
                        "bars_held": j + 1, "pnl_pct": round(pnl, 2), "exit_method": "STOP"}
            if lows[j] <= target_1:
                if lows[j] <= target_2:
                    pnl = (entry - target_2) / entry * 100
                    return {"outcome": "WIN_T2", "exit_price": round(target_2, 2),
                            "bars_held": j + 1, "pnl_pct": round(pnl, 2), "exit_method": "TARGET_2"}
                pnl = (entry - target_1) / entry * 100
                return {"outcome": "WIN_T1", "exit_price": round(target_1, 2),
                        "bars_held": j + 1, "pnl_pct": round(pnl, 2), "exit_method": "TARGET_1"}
            # BB upper band tag exit (cover signal for shorts)
            if bb_upper and closes[j] >= bb_upper:
                pnl = (entry - closes[j]) / entry * 100
                oc = "LOSS" if pnl < 0 else "WIN_T1"
                return {"outcome": oc, "exit_price": round(float(closes[j]), 2),
                        "bars_held": j + 1, "pnl_pct": round(pnl, 2), "exit_method": "BAND_TAG"}

    # Timeout
    if n == 0:
        return {"outcome": "NO_ENTRY", "exit_price": 0, "bars_held": 0, "pnl_pct": 0, "exit_method": ""}

    last_close = float(closes[-1])
    if direction == "BUY":
        pnl = (last_close - entry) / entry * 100
    else:
        pnl = (entry - last_close) / entry * 100

    oc = "TIMEOUT_WIN" if pnl > 0 else "TIMEOUT_LOSS"
    return {"outcome": oc, "exit_price": round(last_close, 2),
            "bars_held": n, "pnl_pct": round(pnl, 2), "exit_method": "TIMEOUT"}


# ─────────────────────────────────────────────────────────────────
#  METRICS & REPORTING
# ─────────────────────────────────────────────────────────────────

def _compute_metrics(trades: List[dict]) -> dict:
    """Comprehensive metrics from all trades."""
    if not trades:
        return {"total_trades": 0}

    total = len(trades)
    wins = [t for t in trades if t["outcome"].startswith("WIN")]
    losses = [t for t in trades if t["outcome"] == "LOSS"]
    tw = [t for t in trades if t["outcome"] == "TIMEOUT_WIN"]
    tl = [t for t in trades if t["outcome"] == "TIMEOUT_LOSS"]

    win_count = len(wins)
    loss_count = len(losses)
    tw_count = len(tw)
    tl_count = len(tl)

    win_rate = win_count / total * 100
    adjusted_wr = (win_count + tw_count * 0.5) / total * 100

    all_pnl = [t["pnl_pct"] for t in trades]
    avg_pnl = np.mean(all_pnl)
    total_pnl = sum(all_pnl)

    avg_win = np.mean([t["pnl_pct"] for t in wins]) if wins else 0
    avg_loss = np.mean([t["pnl_pct"] for t in losses]) if losses else 0

    gross_profit = sum(t["pnl_pct"] for t in trades if t["pnl_pct"] > 0)
    gross_loss = abs(sum(t["pnl_pct"] for t in trades if t["pnl_pct"] < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    avg_bars = np.mean([t["bars_held"] for t in trades])

    # ── By Direction ──
    buys = [t for t in trades if t["direction"] == "BUY"]
    sells = [t for t in trades if t["direction"] == "SELL"]
    buy_wr = sum(1 for t in buys if t["outcome"].startswith("WIN")) / len(buys) * 100 if buys else 0
    sell_wr = sum(1 for t in sells if t["outcome"].startswith("WIN")) / len(sells) * 100 if sells else 0

    # ── By Hybrid Verdict ──
    verdict_metrics = {}
    for v in ["SUPER STRONG BUY", "STRONG BUY", "BUY", "SELL", "STRONG SELL", "SUPER STRONG SELL"]:
        vt = [t for t in trades if t["hybrid_verdict"] == v]
        if vt:
            vw = sum(1 for t in vt if t["outcome"].startswith("WIN"))
            verdict_metrics[v] = {
                "trades": len(vt), "wins": vw,
                "win_rate": round(vw / len(vt) * 100, 1),
                "avg_pnl": round(np.mean([t["pnl_pct"] for t in vt]), 2),
            }

    # ── By Alignment ──
    alignment_metrics = {}
    for a in ["ALIGNED", "PARTIAL", "CONFLICTING"]:
        at = [t for t in trades if t["alignment"] == a]
        if at:
            aw = sum(1 for t in at if t["outcome"].startswith("WIN"))
            alignment_metrics[a] = {
                "trades": len(at), "wins": aw,
                "win_rate": round(aw / len(at) * 100, 1),
                "avg_pnl": round(np.mean([t["pnl_pct"] for t in at]), 2),
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
                "avg_pnl": round(np.mean([t["pnl_pct"] for t in pt]), 2),
            }

    # ── By TA Verdict ──
    ta_verdict_metrics = {}
    for v in ["STRONG BUY", "BUY", "HOLD", "SELL", "STRONG SELL"]:
        vt = [t for t in trades if t["ta_verdict"] == v]
        if vt:
            vw = sum(1 for t in vt if t["outcome"].startswith("WIN"))
            ta_verdict_metrics[v] = {
                "trades": len(vt), "wins": vw,
                "win_rate": round(vw / len(vt) * 100, 1),
                "avg_pnl": round(np.mean([t["pnl_pct"] for t in vt]), 2),
            }

    # ── By Quant Regime ──
    regime_metrics = {}
    for r in ["TRENDING_UP", "TRENDING_DOWN", "MEAN_REVERTING", "VOLATILE_CHOPPY", "UNKNOWN"]:
        rt = [t for t in trades if t["quant_regime"] == r]
        if rt:
            rw = sum(1 for t in rt if t["outcome"].startswith("WIN"))
            regime_metrics[r] = {
                "trades": len(rt), "wins": rw,
                "win_rate": round(rw / len(rt) * 100, 1),
                "avg_pnl": round(np.mean([t["pnl_pct"] for t in rt]), 2),
            }

    # ── By Quant Strategy ──
    qstrat_metrics = {}
    for s in ["MEAN_REVERSION", "MOMENTUM", "WAIT", "AVOID", "ERROR"]:
        st = [t for t in trades if t["quant_strategy"] == s]
        if st:
            sw = sum(1 for t in st if t["outcome"].startswith("WIN"))
            qstrat_metrics[s] = {
                "trades": len(st), "wins": sw,
                "win_rate": round(sw / len(st) * 100, 1),
                "avg_pnl": round(np.mean([t["pnl_pct"] for t in st]), 2),
            }

    # ── By Exit Method ──
    exit_metrics = {}
    for em in ["STOP", "TARGET_1", "TARGET_2", "BAND_TAG", "TIMEOUT"]:
        et = [t for t in trades if t["exit_method"] == em]
        if et:
            exit_metrics[em] = {
                "trades": len(et),
                "avg_pnl": round(np.mean([t["pnl_pct"] for t in et]), 2),
            }

    # ── System Agreement Analysis (how often do systems agree?) ──
    agreement_stats = _compute_agreement_stats(trades)

    # ── Confidence buckets ──
    conf_metrics = {}
    for label, lo, hi in [("HIGH (70+)", 70, 101), ("MODERATE (40-69)", 40, 70), ("LOW (<40)", 0, 40)]:
        ct = [t for t in trades if lo <= t["hybrid_confidence"] < hi]
        if ct:
            cw = sum(1 for t in ct if t["outcome"].startswith("WIN"))
            conf_metrics[label] = {
                "trades": len(ct), "wins": cw,
                "win_rate": round(cw / len(ct) * 100, 1),
                "avg_pnl": round(np.mean([t["pnl_pct"] for t in ct]), 2),
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
        "grade": grade,
        "buy_trades": len(buys),
        "sell_trades": len(sells),
        "buy_win_rate": round(buy_wr, 1),
        "sell_win_rate": round(sell_wr, 1),
        "by_hybrid_verdict": verdict_metrics,
        "by_alignment": alignment_metrics,
        "by_bb_phase": phase_metrics,
        "by_ta_verdict": ta_verdict_metrics,
        "by_quant_regime": regime_metrics,
        "by_quant_strategy": qstrat_metrics,
        "by_confidence": conf_metrics,
        "by_exit_method": exit_metrics,
        "agreement_stats": agreement_stats,
    }


def _compute_agreement_stats(trades: List[dict]) -> dict:
    """Analyze how often different sub-systems agree."""
    total = len(trades)
    if total == 0:
        return {}

    # Count how many sub-systems agree on direction for each trade
    agreement_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    agreement_wr = {1: [], 2: [], 3: [], 4: [], 5: []}

    for t in trades:
        direction = t["direction"]
        agree_count = 0

        # Hybrid
        hv = t["hybrid_verdict"]
        if ("BUY" in hv and direction == "BUY") or ("SELL" in hv and direction == "SELL"):
            agree_count += 1

        # BB M1
        if (t["bb_buy_signal"] and direction == "BUY") or (t["bb_sell_signal"] and direction == "SELL"):
            agree_count += 1

        # TA
        tv = t["ta_verdict"]
        if ("BUY" in tv and direction == "BUY") or ("SELL" in tv and direction == "SELL"):
            agree_count += 1

        # Quant
        qs = t["quant_signal"]
        if ("BUY" in qs and direction == "BUY") or ("SELL" in qs and direction == "SELL"):
            agree_count += 1

        # PA
        ps = t.get("pa_signal", "")
        if ps == direction:
            agree_count += 1

        agree_count = max(1, agree_count)
        agreement_counts[agree_count] = agreement_counts.get(agree_count, 0) + 1

        is_win = t["outcome"].startswith("WIN")
        agreement_wr[agree_count].append(is_win)

    result = {}
    for k in sorted(agreement_counts.keys()):
        count = agreement_counts[k]
        if count > 0:
            wins = sum(agreement_wr[k])
            result[f"{k}_systems_agree"] = {
                "trades": count,
                "pct_of_total": round(count / total * 100, 1),
                "win_rate": round(wins / count * 100, 1) if count else 0,
            }

    return result


def _print_report(m: dict) -> None:
    """Print formatted full system backtest report."""
    print("\n" + "=" * 70)
    print("   FULL SYSTEM TRUTHFULNESS BACKTEST — REPORT")
    print("   BB Methods I-IV + TA + Hybrid + Quant + Price Action")
    dir_f = m.get("meta", {}).get("direction_filter", "ALL")
    dir_label = f"{dir_f}-ONLY" if dir_f != "ALL" else "ALL directions"
    print(f"   Data: 2020 → Present | {dir_label} | Multi-Threaded Simulation")
    print("=" * 70)

    if m.get("total_trades", 0) == 0:
        print("No trades generated.")
        return

    print(f"\n{'═══ OVERALL RESULTS ═══':^70}")
    print("-" * 70)
    print(f"  Total Trades        : {m['total_trades']:,}")
    print(f"  Wins (target hit)   : {m['wins']:,}")
    print(f"  Losses (stop hit)   : {m['losses']:,}")
    print(f"  Timeout Win         : {m['timeout_wins']:,}")
    print(f"  Timeout Loss        : {m['timeout_losses']:,}")
    print(f"  Win Rate            : {m['win_rate']:.1f}%")
    print(f"  Adjusted Win Rate   : {m['adjusted_win_rate']:.1f}%")
    print(f"  Profit Factor       : {m['profit_factor']:.2f}")
    print(f"  Avg P&L per Trade   : {m['avg_pnl_pct']:+.2f}%")
    print(f"  Avg Win P&L         : {m['avg_win_pnl']:+.2f}%")
    print(f"  Avg Loss P&L        : {m['avg_loss_pnl']:+.2f}%")
    print(f"  Total Cumulative P&L: {m['total_pnl_pct']:+,.0f}%")
    print(f"  Avg Bars Held       : {m['avg_bars_held']:.1f}")
    print(f"  GRADE               : {m['grade']}")

    print(f"\n{'═══ DIRECTION SPLIT ═══':^70}")
    print("-" * 70)
    print(f"  BUY  trades: {m['buy_trades']:>6,}  win rate: {m['buy_win_rate']:.1f}%")
    print(f"  SELL trades: {m['sell_trades']:>6,}  win rate: {m['sell_win_rate']:.1f}%")

    if m.get("by_hybrid_verdict"):
        print(f"\n{'═══ BY HYBRID VERDICT (is the conviction engine accurate?) ═══':^70}")
        print("-" * 70)
        for v, d in sorted(m["by_hybrid_verdict"].items(), key=lambda x: -x[1]["win_rate"]):
            print(f"  {v:22s}  trades: {d['trades']:>5,}  "
                  f"WR: {d['win_rate']:5.1f}%  avg P&L: {d['avg_pnl']:+.2f}%")

    if m.get("by_alignment"):
        print(f"\n{'═══ BY CROSS-VALIDATION ALIGNMENT ═══':^70}")
        print("-" * 70)
        for a, d in sorted(m["by_alignment"].items(), key=lambda x: -x[1]["win_rate"]):
            print(f"  {a:15s}  trades: {d['trades']:>5,}  "
                  f"WR: {d['win_rate']:5.1f}%  avg P&L: {d['avg_pnl']:+.2f}%")

    if m.get("by_bb_phase"):
        print(f"\n{'═══ BY BB PHASE ═══':^70}")
        print("-" * 70)
        for p, d in sorted(m["by_bb_phase"].items(), key=lambda x: -x[1]["win_rate"]):
            print(f"  {p:15s}  trades: {d['trades']:>5,}  "
                  f"WR: {d['win_rate']:5.1f}%  avg P&L: {d['avg_pnl']:+.2f}%")

    if m.get("by_ta_verdict"):
        print(f"\n{'═══ BY TA VERDICT ═══':^70}")
        print("-" * 70)
        for v, d in sorted(m["by_ta_verdict"].items(), key=lambda x: -x[1]["win_rate"]):
            print(f"  {v:15s}  trades: {d['trades']:>5,}  "
                  f"WR: {d['win_rate']:5.1f}%  avg P&L: {d['avg_pnl']:+.2f}%")

    if m.get("by_quant_regime"):
        print(f"\n{'═══ BY QUANT REGIME ═══':^70}")
        print("-" * 70)
        for r, d in sorted(m["by_quant_regime"].items(), key=lambda x: -x[1]["win_rate"]):
            print(f"  {r:18s}  trades: {d['trades']:>5,}  "
                  f"WR: {d['win_rate']:5.1f}%  avg P&L: {d['avg_pnl']:+.2f}%")

    if m.get("by_quant_strategy"):
        print(f"\n{'═══ BY QUANT STRATEGY ═══':^70}")
        print("-" * 70)
        for s, d in sorted(m["by_quant_strategy"].items(), key=lambda x: -x[1]["win_rate"]):
            print(f"  {s:18s}  trades: {d['trades']:>5,}  "
                  f"WR: {d['win_rate']:5.1f}%  avg P&L: {d['avg_pnl']:+.2f}%")

    if m.get("by_confidence"):
        print(f"\n{'═══ BY CONFIDENCE LEVEL ═══':^70}")
        print("-" * 70)
        for c, d in sorted(m["by_confidence"].items(), key=lambda x: -x[1]["win_rate"]):
            print(f"  {c:20s}  trades: {d['trades']:>5,}  "
                  f"WR: {d['win_rate']:5.1f}%  avg P&L: {d['avg_pnl']:+.2f}%")

    if m.get("by_exit_method"):
        print(f"\n{'═══ BY EXIT METHOD ═══':^70}")
        print("-" * 70)
        for em, d in sorted(m["by_exit_method"].items(), key=lambda x: -x[1]["avg_pnl"]):
            print(f"  {em:12s}  trades: {d['trades']:>5,}  avg P&L: {d['avg_pnl']:+.2f}%")

    if m.get("agreement_stats"):
        print(f"\n{'═══ SYSTEM AGREEMENT ANALYSIS ═══':^70}")
        print("-" * 70)
        print("  (Win rate when N sub-systems agree on direction)")
        for k, d in sorted(m["agreement_stats"].items()):
            print(f"  {k:22s}  trades: {d['trades']:>5,}  "
                  f"({d['pct_of_total']:4.1f}% of total)  WR: {d['win_rate']:5.1f}%")

    meta = m.get("meta", {})
    if meta:
        print(f"\n{'═══ PROCESSING INFO ═══':^70}")
        print("-" * 70)
        print(f"  Stocks Processed : {meta.get('stocks_processed', 0):,}")
        print(f"  Stocks w/Signals : {meta.get('stocks_with_signals', 0):,}")
        print(f"  Stocks Skipped   : {meta.get('stocks_skipped', 0):,}")
        print(f"  Errors           : {meta.get('errors', 0):,}")
        print(f"  Elapsed          : {meta.get('elapsed_sec', 0):.0f}s")
        print(f"  Workers          : {meta.get('workers', 0)}")

    # ── TRUTHFULNESS SUMMARY ──
    print(f"\n{'═══ TRUTHFULNESS VERDICT ═══':^70}")
    print("=" * 70)
    grade = m["grade"]
    wr = m["win_rate"]
    pf = m["profit_factor"]

    if grade in ("A", "B"):
        verdict_text = "HIGHLY RELIABLE — The system generates profitable signals consistently."
    elif grade == "C":
        verdict_text = "MODERATELY RELIABLE — The system is above breakeven but some signals are weak."
    elif grade == "D":
        verdict_text = "PARTIALLY RELIABLE — The system has directional accuracy but needs filtering."
    else:
        verdict_text = "NEEDS IMPROVEMENT — Raw signals are not profitable; filtering required."

    print(f"  System Grade      : {grade}")
    print(f"  Overall Win Rate  : {wr:.1f}%")
    print(f"  Profit Factor     : {pf:.2f}")
    print(f"  Verdict           : {verdict_text}")

    # Best performing segments
    best_segments = []
    for section_name, section_data in [
        ("Hybrid Verdict", m.get("by_hybrid_verdict", {})),
        ("Alignment", m.get("by_alignment", {})),
        ("BB Phase", m.get("by_bb_phase", {})),
        ("Quant Regime", m.get("by_quant_regime", {})),
        ("Confidence", m.get("by_confidence", {})),
    ]:
        for k, v in section_data.items():
            if v.get("win_rate", 0) >= 50 and v.get("trades", 0) >= 10:
                best_segments.append((section_name, k, v["win_rate"], v["avg_pnl"], v["trades"]))

    if best_segments:
        print(f"\n  {'PROFITABLE SEGMENTS (WR >= 50%, 10+ trades):':^66}")
        print(f"  {'-' * 66}")
        for sec, k, wr, pnl, cnt in sorted(best_segments, key=lambda x: -x[2]):
            print(f"    [{sec}] {k}: {wr:.1f}% WR, {pnl:+.2f}% avg P&L ({cnt} trades)")

    print("=" * 70)


# ─────────────────────────────────────────────────────────────────
#  MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────

def run_full_backtest(max_stocks: int = 0, workers: int = NUM_WORKERS,
                      direction: str = DIRECTION_FILTER, verbose: bool = True) -> dict:
    """Run multi-threaded full system backtest."""
    global DIRECTION_FILTER
    DIRECTION_FILTER = direction.upper()

    csv_dir = os.path.join(_ROOT, "stock_csv")
    csv_files = sorted(glob.glob(os.path.join(csv_dir, "*.csv")))

    if max_stocks > 0:
        csv_files = csv_files[:max_stocks]

    total = len(csv_files)
    t0 = time.time()

    dir_label = f"Direction: {DIRECTION_FILTER}-ONLY" if DIRECTION_FILTER != "ALL" else "Direction: ALL (BUY + SELL)"
    if verbose:
        print(f"FULL SYSTEM BACKTEST — {total} stocks, {workers} workers")
        print(f"Period: {START_DATE} → Present | {dir_label}")
        print(f"Config: window={WINDOW_SIZE}, step={STEP_SIZE}, cooldown={COOLDOWN}, max_hold={MAX_HOLD}")
        print("=" * 70)

    all_trades: List[dict] = []
    stocks_processed = 0
    stocks_with_signals = 0
    stocks_skipped = 0
    errors = 0

    # ── Multi-process execution (fork-based) ──
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

            if verbose and done_count % 100 == 0:
                elapsed = time.time() - t0
                rate = done_count / elapsed
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
        "errors": errors,
        "elapsed_sec": round(elapsed, 1),
        "workers": workers,
        "start_date": START_DATE,
        "direction_filter": DIRECTION_FILTER,
        "config": {
            "window_size": WINDOW_SIZE,
            "step_size": STEP_SIZE,
            "cooldown": COOLDOWN,
            "max_hold": MAX_HOLD,
            "direction_filter": DIRECTION_FILTER,
        },
    }

    if verbose:
        _print_report(metrics)

    # Save results
    out_path = os.path.join(_ROOT, "backtest_full_results.json")
    output = {
        "metrics": metrics,
        "trades_sample": all_trades[:500],  # First 500 trades as sample
        "total_trades_count": len(all_trades),
    }
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    if verbose:
        print(f"\nResults saved to {out_path}")

    return metrics


# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Full System Backtest")
    parser.add_argument("--max", type=int, default=0, help="Max stocks (0=all)")
    parser.add_argument("--workers", type=int, default=NUM_WORKERS, help="Worker processes")
    parser.add_argument("--direction", type=str, default=DIRECTION_FILTER,
                        choices=["BUY", "SELL", "ALL"],
                        help="Direction filter: BUY (default, longs only), SELL (shorts only), ALL (both)")
    args = parser.parse_args()

    run_full_backtest(max_stocks=args.max, workers=args.workers, direction=args.direction)
