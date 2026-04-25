"""
Price Action Engine — Main Orchestrator
=========================================
The central engine that:
1. Runs all PA analysis components (bars, patterns, trend, channels, breakouts)
2. Generates PA signals
3. Integrates with existing BB Squeeze, Technical Analysis, and Hybrid data
4. Produces a unified Price Action verdict with cross-system validation

This is the single entry point for all Price Action analysis.
"""

from __future__ import annotations

import sys
import os
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any

import pandas as pd

# Ensure project root is on path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from price_action.bar_types import classify_bars, bar_summary, BarAnalysis
from price_action.patterns import detect_all_patterns, PatternSummary
from price_action.trend_analyzer import analyze_trend, TrendState
from price_action.channels import analyze_channels, ChannelAnalysis
from price_action.breakouts import analyze_breakouts, BreakoutAnalysis
from price_action.signals import generate_pa_signals, PASignalResult
from price_action import config as C


# ─────────────────────────────────────────────────────────────────
#  RESULT DATA CLASS
# ─────────────────────────────────────────────────────────────────

@dataclass
class PriceActionResult:
    """Complete Price Action analysis result for a single stock."""

    ticker: str
    success: bool = True
    error: str = ""

    # ── PA Signal ──
    signal_type: str = "HOLD"       # "BUY" | "SELL" | "HOLD"
    setup_type: str = "NONE"        # BREAKOUT | PULLBACK | REVERSAL | etc.
    strength: str = "NONE"          # "STRONG" | "MODERATE" | "WEAK"
    confidence: int = 0             # 0-100
    pa_score: float = 0.0           # -100 to +100
    pa_verdict: str = "HOLD"        # "STRONG BUY" ... "STRONG SELL"

    # ── Price Levels ──
    entry_price: float = 0.0
    stop_loss: float = 0.0
    target_1: float = 0.0
    target_2: float = 0.0
    risk_reward: float = 0.0
    current_price: float = 0.0

    # ── Trend State ──
    always_in: str = "FLAT"
    always_in_score: float = 0.0
    trend_direction: str = "SIDEWAYS"
    trend_strength: float = 0.0
    trend_phase: str = "UNKNOWN"
    buying_pressure: float = 0.0
    selling_pressure: float = 0.0
    ema_gap_bar_count: int = 0              # Brooks: 20+ = very strong trend
    gap_bar_setup: bool = False             # Brooks: first EMA touch after 20+ gap bars
    in_spike: bool = False                  # Brooks: explosive start of trend
    spike_direction: str = "NONE"           # "BULL" | "BEAR" | "NONE"
    spike_bars: int = 0
    spike_strength: float = 0.0
    recent_climax: bool = False             # Climax bar in last 5 bars
    consecutive_bull_trend: int = 0         # Consecutive bull trend bars
    consecutive_bear_trend: int = 0
    price_vs_ema: str = "AT"                # "ABOVE" | "BELOW" | "AT"
    ema20: float = 0.0                      # Current EMA20 value

    # ── Bar Analysis ──
    last_bar_type: str = "UNKNOWN"
    last_bar_signal: bool = False
    last_bar_description: str = ""

    # ── Pattern Info ──
    active_patterns: List[str] = field(default_factory=list)
    breakout_mode: bool = False
    last_hl_bull: str = ""
    last_hl_bear: str = ""

    # ── Channel Info ──
    price_position: str = "MIDDLE"
    channel_description: str = ""

    # ── Breakout Info ──
    in_breakout: bool = False
    breakout_direction: str = "NONE"

    # ── Scoring Components ──
    score_details: Dict[str, float] = field(default_factory=dict)

    # ── Reasons & Context ──
    reasons: List[str] = field(default_factory=list)
    al_brooks_context: str = ""
    description: str = ""

    # ── Cross-System Integration ──
    bb_agreement: str = "UNKNOWN"    # "AGREE" | "CONFLICT" | "NEUTRAL"
    ta_agreement: str = "UNKNOWN"
    hybrid_agreement: str = "UNKNOWN"
    cross_system_bonus: float = 0.0
    combined_verdict: str = ""       # Final verdict after cross-system validation
    combined_confidence: float = 0.0

    # ── Two-Leg ──
    two_leg_complete: bool = False
    measured_move_target: float = 0.0

    # ── Summaries for display ──
    bar_summary_data: dict = field(default_factory=dict)
    trend_summary: str = ""
    pattern_summary: str = ""
    breakout_summary: str = ""


# ─────────────────────────────────────────────────────────────────
#  CROSS-SYSTEM INTEGRATION
# ─────────────────────────────────────────────────────────────────

def _integrate_with_existing_systems(
    result: PriceActionResult,
    bb_data: Optional[dict] = None,
    ta_data: Optional[dict] = None,
    hybrid_data: Optional[dict] = None,
) -> None:
    """
    Cross-validate PA signal with existing BB, TA, and Hybrid systems.

    Adjusts confidence based on agreement/conflict:
    - All agree: +15 confidence
    - Partial agree: +5
    - Conflict: -10

    Also builds combined_verdict.
    """
    pa_dir = result.signal_type  # "BUY" | "SELL" | "HOLD"
    agreements = 0
    conflicts = 0
    total_checked = 0

    # ── BB Squeeze System ──
    if bb_data:
        total_checked += 1
        bb_dir = _extract_bb_direction(bb_data)
        if pa_dir == "HOLD" or bb_dir == "HOLD":
            result.bb_agreement = "NEUTRAL"
        elif pa_dir == bb_dir:
            result.bb_agreement = "AGREE"
            agreements += 1
        else:
            result.bb_agreement = "CONFLICT"
            conflicts += 1

    # ── Technical Analysis ──
    if ta_data:
        total_checked += 1
        ta_dir = _extract_ta_direction(ta_data)
        if pa_dir == "HOLD" or ta_dir == "HOLD":
            result.ta_agreement = "NEUTRAL"
        elif pa_dir == ta_dir:
            result.ta_agreement = "AGREE"
            agreements += 1
        else:
            result.ta_agreement = "CONFLICT"
            conflicts += 1

    # ── Hybrid System ──
    if hybrid_data:
        total_checked += 1
        hybrid_dir = _extract_hybrid_direction(hybrid_data)
        if pa_dir == "HOLD" or hybrid_dir == "HOLD":
            result.hybrid_agreement = "NEUTRAL"
        elif pa_dir == hybrid_dir:
            result.hybrid_agreement = "AGREE"
            agreements += 1
        else:
            result.hybrid_agreement = "CONFLICT"
            conflicts += 1

    # Apply bonus/penalty
    if total_checked > 0:
        if agreements == total_checked:
            result.cross_system_bonus = C.CROSS_AGREE_BONUS
        elif agreements > conflicts:
            result.cross_system_bonus = C.CROSS_PARTIAL_BONUS
        elif conflicts > agreements:
            result.cross_system_bonus = C.CROSS_CONFLICT_PENALTY
        else:
            result.cross_system_bonus = 0

        # Adjust confidence
        adjusted_conf = result.confidence + result.cross_system_bonus
        result.combined_confidence = max(0, min(100, adjusted_conf))
    else:
        result.combined_confidence = float(result.confidence)

    # Build combined verdict
    _build_combined_verdict(result, agreements, conflicts, total_checked)


def _extract_bb_direction(bb_data: dict) -> str:
    """Extract direction from BB Squeeze data."""
    if isinstance(bb_data, dict):
        if bb_data.get("buy_signal"):
            return "BUY"
        if bb_data.get("sell_signal"):
            return "SELL"
        direction = bb_data.get("direction_lean", "NEUTRAL")
        if direction == "BULLISH":
            return "BUY"
        if direction == "BEARISH":
            return "SELL"
    return "HOLD"


def _extract_ta_direction(ta_data: dict) -> str:
    """Extract direction from TA signal."""
    if isinstance(ta_data, dict):
        verdict = ta_data.get("verdict", "HOLD")
        if "BUY" in verdict.upper():
            return "BUY"
        if "SELL" in verdict.upper():
            return "SELL"
    return "HOLD"


def _extract_hybrid_direction(hybrid_data: dict) -> str:
    """Extract direction from Triple/Hybrid analysis."""
    if isinstance(hybrid_data, dict):
        hv = hybrid_data.get("triple_verdict") or hybrid_data.get("hybrid_verdict", {})
        if isinstance(hv, dict):
            verdict = hv.get("verdict", "HOLD")
            if "BUY" in verdict.upper():
                return "BUY"
            if "SELL" in verdict.upper():
                return "SELL"
    return "HOLD"


def _build_combined_verdict(
    result: PriceActionResult,
    agreements: int,
    conflicts: int,
    total: int,
) -> None:
    """Build final combined verdict text."""
    if result.signal_type == "HOLD":
        result.combined_verdict = (
            f"HOLD — PA sees no clear setup. "
            f"Cross-system: {agreements}/{total} agree."
        )
        return

    dir_text = result.signal_type
    strength = result.strength

    if agreements == total and total > 0:
        result.combined_verdict = (
            f"CONFIRMED {dir_text} ({strength}) — "
            f"All {total} systems AGREE. "
            f"Setup: {result.setup_type.replace('_', ' ')}. "
            f"Combined confidence: {result.combined_confidence:.0f}%"
        )
    elif agreements > conflicts:
        result.combined_verdict = (
            f"{dir_text} ({strength}) — "
            f"{agreements}/{total} systems agree. "
            f"Setup: {result.setup_type.replace('_', ' ')}. "
            f"Combined confidence: {result.combined_confidence:.0f}%"
        )
    elif conflicts > 0:
        result.combined_verdict = (
            f"CAUTION {dir_text} ({strength}) — "
            f"{conflicts}/{total} systems CONFLICT. "
            f"PA says {dir_text} but other systems disagree. "
            f"Reduced confidence: {result.combined_confidence:.0f}%"
        )
    else:
        result.combined_verdict = (
            f"{dir_text} ({strength}) — "
            f"PA standalone signal. "
            f"Confidence: {result.combined_confidence:.0f}%"
        )


# ─────────────────────────────────────────────────────────────────
#  MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────

def run_price_action_analysis(
    df: pd.DataFrame,
    ticker: str = "UNKNOWN",
    bb_data: Optional[dict] = None,
    ta_data: Optional[dict] = None,
    hybrid_data: Optional[dict] = None,
) -> PriceActionResult:
    """
    Run complete Al Brooks Price Action analysis on a stock.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV DataFrame with DatetimeIndex.
    ticker : str
        Stock ticker symbol.
    bb_data : dict, optional
        BB Squeeze signal data (from _signal_dict or SignalResult).
    ta_data : dict, optional
        TA signal data (from generate_signal()).
    hybrid_data : dict, optional
        Triple/Hybrid analysis data (from run_triple_analysis()).

    Returns
    -------
    PriceActionResult
        Complete PA analysis with signal, scoring, and cross-system validation.
    """
    result = PriceActionResult(ticker=ticker)

    # ── Validate input ──
    if df is None or len(df) < C.MIN_BARS_REQUIRED:
        result.success = False
        result.error = f"Insufficient data ({len(df) if df is not None else 0} bars, need {C.MIN_BARS_REQUIRED})"
        return result

    required_cols = {"Open", "High", "Low", "Close"}
    if not required_cols.issubset(df.columns):
        result.success = False
        result.error = f"Missing columns: {required_cols - set(df.columns)}"
        return result

    try:
        # Limit to last 250 bars for performance (PA only needs recent context)
        if len(df) > 250:
            df = df.iloc[-250:]

        result.current_price = float(df["Close"].iloc[-1])

        # ── Step 1: Bar Classification ──
        bars = classify_bars(df)
        if not bars:
            result.success = False
            result.error = "Bar classification returned empty"
            return result

        # ── Step 2: Pattern Detection ──
        patterns = detect_all_patterns(bars)

        # ── Step 3: Trend Analysis ──
        trend = analyze_trend(bars, df)

        # ── Step 4: Channel Analysis ──
        channels = analyze_channels(bars)

        # ── Step 5: Breakout Analysis ──
        breakout_analysis = analyze_breakouts(bars)

        # ── Step 6: Signal Generation ──
        signal_result = generate_pa_signals(
            bars, trend, patterns, channels, breakout_analysis,
        )

        # ── Populate Result ──
        sig = signal_result.primary_signal

        result.signal_type = sig.signal_type
        result.setup_type = sig.setup_type
        result.strength = sig.strength
        result.confidence = sig.confidence
        result.pa_score = signal_result.pa_score
        result.pa_verdict = signal_result.pa_verdict

        result.entry_price = sig.entry_price
        result.stop_loss = sig.stop_loss
        result.target_1 = sig.target_1
        result.target_2 = sig.target_2
        result.risk_reward = sig.risk_reward

        result.always_in = trend.always_in
        result.always_in_score = trend.always_in_score
        result.trend_direction = trend.trend_direction
        result.trend_strength = trend.trend_strength
        result.trend_phase = trend.trend_phase
        result.buying_pressure = trend.buying_pressure
        result.selling_pressure = trend.selling_pressure
        result.ema_gap_bar_count = trend.ema_gap_bar_count
        result.gap_bar_setup = trend.gap_bar_setup
        result.in_spike = trend.in_spike
        result.spike_direction = trend.spike_direction
        result.spike_bars = trend.spike_bars
        result.spike_strength = trend.spike_strength
        result.recent_climax = trend.recent_climax
        result.consecutive_bull_trend = trend.consecutive_bull_trend
        result.consecutive_bear_trend = trend.consecutive_bear_trend
        result.price_vs_ema = trend.price_vs_ema
        result.ema20 = trend.ema20

        # Last bar info
        last_bar = bars[-1]
        result.last_bar_type = last_bar.bar_type
        result.last_bar_signal = last_bar.is_signal_bar
        result.last_bar_description = last_bar.description

        # Patterns
        result.active_patterns = [p.name for p in patterns.active_patterns]
        result.breakout_mode = patterns.breakout_mode
        result.last_hl_bull = patterns.last_hl_bull
        result.last_hl_bear = patterns.last_hl_bear

        # Channel
        result.price_position = channels.price_position
        result.channel_description = channels.description

        # Breakout
        result.in_breakout = breakout_analysis.in_breakout
        result.breakout_direction = breakout_analysis.breakout_direction

        # Scoring
        result.score_details = sig.scores

        # Reasons & context
        result.reasons = sig.reasons
        result.al_brooks_context = sig.al_brooks_context
        result.description = sig.description

        # Two-leg
        result.two_leg_complete = trend.two_leg_complete
        result.measured_move_target = trend.measured_move_target

        # Summaries
        result.bar_summary_data = signal_result.bar_summary
        result.trend_summary = signal_result.trend_summary
        result.pattern_summary = signal_result.pattern_summary
        result.breakout_summary = signal_result.breakout_summary

        # ── Step 7: Cross-System Integration ──
        _integrate_with_existing_systems(result, bb_data, ta_data, hybrid_data)

    except Exception as exc:
        result.success = False
        result.error = f"Analysis error: {str(exc)}"

    return result


# ─────────────────────────────────────────────────────────────────
#  SERIALIZATION
# ─────────────────────────────────────────────────────────────────

def pa_result_to_dict(result: PriceActionResult) -> dict:
    """Convert PriceActionResult to a JSON-safe dictionary."""
    return {
        "ticker": result.ticker,
        "success": result.success,
        "error": result.error,

        "signal": {
            "type": result.signal_type,
            "setup": result.setup_type,
            "strength": result.strength,
            "confidence": result.confidence,
            "pa_score": result.pa_score,
            "pa_verdict": result.pa_verdict,
        },

        "price_levels": {
            "current": result.current_price,
            "entry": result.entry_price,
            "stop_loss": result.stop_loss,
            "target_1": result.target_1,
            "target_2": result.target_2,
            "risk_reward": result.risk_reward,
        },

        "trend": {
            "always_in": result.always_in,
            "always_in_score": result.always_in_score,
            "direction": result.trend_direction,
            "strength": result.trend_strength,
            "phase": result.trend_phase,
            "buying_pressure": result.buying_pressure,
            "selling_pressure": result.selling_pressure,
            "ema_gap_bar_count": result.ema_gap_bar_count,
            "gap_bar_setup": result.gap_bar_setup,
            "in_spike": result.in_spike,
            "spike_direction": result.spike_direction,
            "spike_bars": result.spike_bars,
            "spike_strength": result.spike_strength,
            "recent_climax": result.recent_climax,
            "consecutive_bull_trend": result.consecutive_bull_trend,
            "consecutive_bear_trend": result.consecutive_bear_trend,
            "price_vs_ema": result.price_vs_ema,
            "ema20": result.ema20,
        },

        "last_bar": {
            "type": result.last_bar_type,
            "is_signal": result.last_bar_signal,
            "description": result.last_bar_description,
        },

        "patterns": {
            "active": result.active_patterns,
            "breakout_mode": result.breakout_mode,
            "last_h": result.last_hl_bull,
            "last_l": result.last_hl_bear,
        },

        "channel": {
            "price_position": result.price_position,
            "description": result.channel_description,
        },

        "breakout": {
            "in_breakout": result.in_breakout,
            "direction": result.breakout_direction,
        },

        "two_leg": {
            "complete": result.two_leg_complete,
            "measured_target": result.measured_move_target,
        },

        "scoring": result.score_details,

        "cross_system": {
            "bb_agreement": result.bb_agreement,
            "ta_agreement": result.ta_agreement,
            "hybrid_agreement": result.hybrid_agreement,
            "cross_bonus": result.cross_system_bonus,
            "combined_confidence": result.combined_confidence,
            "combined_verdict": result.combined_verdict,
        },

        "reasons": result.reasons,
        "al_brooks_context": result.al_brooks_context,
        "description": result.description,

        "summaries": {
            "bar": result.bar_summary_data,
            "trend": result.trend_summary,
            "pattern": result.pattern_summary,
            "breakout": result.breakout_summary,
        },
    }
