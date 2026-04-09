"""
Trend Analysis Engine — Al Brooks Methodology
===============================================
Implements the core trend analysis concepts from
"Trading Price Action: TRENDS":

- **Always-In Direction**: If forced to be in the market, which side?
- **Buying / Selling Pressure**: Cumulative bar analysis
- **Spike Detection**: Consecutive strong trend bars = spike
- **Trend Phases**: SPIKE → CHANNEL → BROAD_CHANNEL → TRADING_RANGE
- **Two-Leg Analysis**: Most moves have two legs
- **Trend Strength Score**: Composite strength assessment
- **Trend State Machine**: Tracks transitions between phases
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

from price_action.bar_types import BarAnalysis
from price_action import config as C


# ─────────────────────────────────────────────────────────────────
#  DATA CLASSES
# ─────────────────────────────────────────────────────────────────

@dataclass
class TrendState:
    """Complete Al Brooks trend state at a point in time."""

    # ── Direction ──
    always_in: str = "FLAT"                 # "LONG" | "SHORT" | "FLAT"
    always_in_score: float = 0.0            # -100 to +100 (+ve = bull)
    always_in_confidence: float = 0.0       # 0-100

    # ── Trend Strength ──
    trend_direction: str = "SIDEWAYS"       # "BULL" | "BEAR" | "SIDEWAYS"
    trend_strength: float = 0.0             # 0-100
    trend_phase: str = "UNKNOWN"            # SPIKE | CHANNEL | TIGHT_CHANNEL |
                                            # BROAD_CHANNEL | TRADING_RANGE | UNKNOWN

    # ── Pressure ──
    buying_pressure: float = 0.0            # 0-100
    selling_pressure: float = 0.0           # 0-100
    pressure_balance: str = "NEUTRAL"       # "BUYERS" | "SELLERS" | "NEUTRAL"

    # ── Spike Analysis ──
    in_spike: bool = False
    spike_direction: str = "NONE"           # "BULL" | "BEAR" | "NONE"
    spike_bars: int = 0
    spike_strength: float = 0.0             # 0-100

    # ── Channel Analysis ──
    in_channel: bool = False
    channel_direction: str = "NONE"
    channel_bars: int = 0
    channel_slope: float = 0.0              # Price change per bar

    # ── Two-Leg Analysis ──
    current_leg: int = 0                    # 0, 1, or 2
    leg1_size: float = 0.0                  # Price range of first leg
    leg2_size: float = 0.0                  # Price range of second leg
    two_leg_complete: bool = False
    measured_move_target: float = 0.0       # Projected target from leg equality

    # ── Consecutive Bars ──
    consecutive_bull_trend: int = 0
    consecutive_bear_trend: int = 0
    consecutive_bull_close: int = 0         # Bars closing above prior high
    consecutive_bear_close: int = 0

    # ── Context ──
    bars_since_last_reversal: int = 0
    ema20: float = 0.0
    price_vs_ema: str = "AT"               # "ABOVE" | "BELOW" | "AT"
    recent_climax: bool = False             # Climax bar in last 5 bars
    ema_gap_bar_count: int = 0              # Consecutive bars not touching EMA20
                                            # Brooks: 20+ = very strong trend (sign of strength)

    # ── Summary ──
    description: str = ""


@dataclass
class TrendLeg:
    """A directional leg (move) in the trend."""
    direction: str              # "BULL" | "BEAR"
    start_idx: int
    end_idx: int
    start_price: float
    end_price: float
    size: float                 # abs(end_price - start_price)
    bars: int
    start_date: str = ""
    end_date: str = ""


# ─────────────────────────────────────────────────────────────────
#  ALWAYS-IN DIRECTION
# ─────────────────────────────────────────────────────────────────

def compute_always_in(
    bars: List[BarAnalysis],
    df: pd.DataFrame,
) -> tuple:
    """
    Determine the Always-In direction per Al Brooks.

    "If you HAD to be in the market right now, would you be long or short?"

    Factors considered (all weighted):
    1. Recent trend bars ratio (bull vs bear)
    2. Price vs EMA(20)
    3. Recent signal bars direction
    4. Consecutive trend bars
    5. Higher highs/lower lows pattern
    6. Last significant breakout direction

    Returns (always_in_direction, score, confidence)
    """
    if len(bars) < C.AI_LOOKBACK:
        return "FLAT", 0.0, 0.0

    recent = bars[-C.AI_LOOKBACK:]
    score = 0.0

    # Factor 1: Trend bar ratio (weight: 30 points)
    bull_trend = sum(1 for b in recent if b.is_trend_bar and b.is_bull)
    bear_trend = sum(1 for b in recent if b.is_trend_bar and b.is_bear)
    total_trend = bull_trend + bear_trend
    if total_trend > 0:
        ratio = (bull_trend - bear_trend) / total_trend  # -1 to +1
        score += ratio * 30

    # Factor 2: Price vs EMA(20) (weight: 20 points)
    if len(df) >= C.AI_EMA_PERIOD:
        ema = df["Close"].ewm(span=C.AI_EMA_PERIOD, adjust=False).mean()
        last_close = df["Close"].iloc[-1]
        last_ema = ema.iloc[-1]
        if last_ema > 0:
            pct_diff = (last_close - last_ema) / last_ema
            ema_score = max(min(pct_diff * 500, 20), -20)  # Cap at ±20
            score += ema_score

    # Factor 3: Consecutive trend bars at end (weight: 20 points)
    consec_bull = 0
    consec_bear = 0
    for b in reversed(recent):
        if b.is_trend_bar and b.is_bull:
            if consec_bear > 0:  # Direction changed — stop
                break
            consec_bull += 1
        elif b.is_trend_bar and b.is_bear:
            if consec_bull > 0:  # Direction changed — stop
                break
            consec_bear += 1
        else:
            break
    if consec_bull >= 3:
        score += min(consec_bull * 5, 20)
    elif consec_bear >= 3:
        score -= min(consec_bear * 5, 20)

    # Factor 4: Higher highs / lower lows (weight: 15 points)
    if len(recent) >= 6:
        recent_highs = [b.high for b in recent[-6:]]
        recent_lows = [b.low for b in recent[-6:]]
        hh = sum(1 for i in range(1, len(recent_highs)) if recent_highs[i] > recent_highs[i - 1])
        ll = sum(1 for i in range(1, len(recent_lows)) if recent_lows[i] < recent_lows[i - 1])
        hl = sum(1 for i in range(1, len(recent_lows)) if recent_lows[i] > recent_lows[i - 1])
        lh = sum(1 for i in range(1, len(recent_highs)) if recent_highs[i] < recent_highs[i - 1])

        if hh > lh:
            score += min((hh - lh) * 3, 15)
        if ll > hl:
            score -= min((ll - hl) * 3, 15)

    # Factor 5: Last signal bar direction (weight: 15 points)
    last_signals = [b for b in recent if b.is_signal_bar]
    if last_signals:
        last_sig = last_signals[-1]
        if last_sig.signal_direction == "BULL_REVERSAL":
            score += 10 if last_sig.signal_quality in ("STRONG", "MODERATE") else 5
        elif last_sig.signal_direction == "BEAR_REVERSAL":
            score -= 10 if last_sig.signal_quality in ("STRONG", "MODERATE") else 5

    # Normalize to -100..+100
    score = max(min(score, 100), -100)

    # Determine direction
    if score >= C.AI_STRONG_THRESHOLD:
        direction = "LONG"
        confidence = min(abs(score), 100)
    elif score <= -C.AI_STRONG_THRESHOLD:
        direction = "SHORT"
        confidence = min(abs(score), 100)
    elif score > 20:
        direction = "LONG"
        confidence = abs(score) * 0.7
    elif score < -20:
        direction = "SHORT"
        confidence = abs(score) * 0.7
    else:
        direction = "FLAT"
        confidence = 30  # Low confidence when flat

    return direction, score, confidence


# ─────────────────────────────────────────────────────────────────
#  BUYING / SELLING PRESSURE
# ─────────────────────────────────────────────────────────────────

def compute_pressure(bars: List[BarAnalysis]) -> tuple:
    """
    Compute buying and selling pressure from bar analysis.

    Al Brooks: "Pressure is cumulative. Count the bull trend bars vs bear
    trend bars, bars closing near their highs vs lows, and follow-through."

    Returns (buying_pressure, selling_pressure, balance)
    """
    if len(bars) < C.PRESSURE_LOOKBACK:
        return 50.0, 50.0, "NEUTRAL"

    recent = bars[-C.PRESSURE_LOOKBACK:]
    n = len(recent)

    # Component 1: Bull vs Bear trend bars
    bull_trend = sum(1 for b in recent if b.is_trend_bar and b.is_bull)
    bear_trend = sum(1 for b in recent if b.is_trend_bar and b.is_bear)

    # Component 2: Close position (bars closing near high vs low)
    close_upper = sum(1 for b in recent if b.close_zone == "UPPER_THIRD")
    close_lower = sum(1 for b in recent if b.close_zone == "LOWER_THIRD")

    # Component 3: Strong trend bars (extra weight)
    strong_bull = sum(1 for b in recent if b.is_strong_trend_bar and b.is_bull)
    strong_bear = sum(1 for b in recent if b.is_strong_trend_bar and b.is_bear)

    # Component 4: Follow-through (bar closes above/below prior bar close)
    follow_bull = 0
    follow_bear = 0
    for i in range(1, n):
        if recent[i].close > recent[i - 1].close:
            follow_bull += 1
        elif recent[i].close < recent[i - 1].close:
            follow_bear += 1

    # Composite buying pressure (0-100)
    buy_points = (
        (bull_trend / n * 30) +
        (close_upper / n * 25) +
        (strong_bull / n * 25) +
        (follow_bull / n * 20)
    )
    buying_pressure = min(buy_points * 100 / 100, 100)

    # Composite selling pressure (0-100)
    sell_points = (
        (bear_trend / n * 30) +
        (close_lower / n * 25) +
        (strong_bear / n * 25) +
        (follow_bear / n * 20)
    )
    selling_pressure = min(sell_points * 100 / 100, 100)

    # Normalize so they sum reasonably
    total = buying_pressure + selling_pressure
    if total > 0:
        buying_pressure = buying_pressure / total * 100
        selling_pressure = selling_pressure / total * 100

    if buying_pressure >= C.PRESSURE_STRONG * 100:
        balance = "BUYERS"
    elif selling_pressure >= C.PRESSURE_STRONG * 100:
        balance = "SELLERS"
    else:
        balance = "NEUTRAL"

    return round(buying_pressure, 1), round(selling_pressure, 1), balance


# ─────────────────────────────────────────────────────────────────
#  SPIKE DETECTION
# ─────────────────────────────────────────────────────────────────

def detect_spike(bars: List[BarAnalysis]) -> dict:
    """
    Detect if the market is in or just completed a spike.

    Al Brooks: "A spike is one or several consecutive trend bars that are
    large and have little overlap. It represents urgency."

    Returns dict with spike info.
    """
    result = {
        "in_spike": False,
        "direction": "NONE",
        "bars": 0,
        "strength": 0.0,
        "start_idx": -1,
        "end_idx": -1,
    }

    if len(bars) < 3:
        return result

    # Scan from the end looking for consecutive strong trend bars
    last = bars[-1]
    consec_bull = 0
    consec_bear = 0

    # Check last N bars for spike characteristics
    for i in range(len(bars) - 1, max(len(bars) - C.SPIKE_MAX_BARS - 2, -1), -1):
        b = bars[i]
        if b.body_pct >= C.SPIKE_BODY_THRESHOLD and b.is_bull:
            if consec_bear > 0:  # Direction changed — stop counting
                break
            consec_bull += 1
        elif b.body_pct >= C.SPIKE_BODY_THRESHOLD and b.is_bear:
            if consec_bull > 0:  # Direction changed — stop counting
                break
            consec_bear += 1
        else:
            break

    if consec_bull >= C.SPIKE_MIN_BARS:
        result["in_spike"] = True
        result["direction"] = "BULL"
        result["bars"] = consec_bull
        result["start_idx"] = len(bars) - consec_bull
        result["end_idx"] = len(bars) - 1
        # Strength: more bars + bigger bodies = stronger
        avg_body = np.mean([bars[j].body_pct for j in range(len(bars) - consec_bull, len(bars))])
        result["strength"] = min(consec_bull * 20 + avg_body * 40, 100)

    elif consec_bear >= C.SPIKE_MIN_BARS:
        result["in_spike"] = True
        result["direction"] = "BEAR"
        result["bars"] = consec_bear
        result["start_idx"] = len(bars) - consec_bear
        result["end_idx"] = len(bars) - 1
        avg_body = np.mean([bars[j].body_pct for j in range(len(bars) - consec_bear, len(bars))])
        result["strength"] = min(consec_bear * 20 + avg_body * 40, 100)

    return result


# ─────────────────────────────────────────────────────────────────
#  TREND PHASE DETECTION (Spike → Channel → Broad Channel → TR)
# ─────────────────────────────────────────────────────────────────

def detect_trend_phase(
    bars: List[BarAnalysis],
    spike_info: dict,
) -> str:
    """
    Determine current trend phase.

    Al Brooks phases:
    1. SPIKE: Consecutive strong trend bars (urgency)
    2. TIGHT_CHANNEL: Very orderly, small pullbacks, micro channel
    3. CHANNEL: Normal trending channel with pullbacks
    4. BROAD_CHANNEL: Wider swings, more overlap
    5. TRADING_RANGE: No clear direction, lots of overlap

    The market cycles: SPIKE → CHANNEL → BROAD_CHANNEL → TRADING_RANGE
    and then back to SPIKE when a breakout occurs.
    """
    if len(bars) < 10:
        return "UNKNOWN"

    recent = bars[-20:] if len(bars) >= 20 else bars

    # If currently in a spike
    if spike_info.get("in_spike") and spike_info.get("bars", 0) >= 2:
        return "SPIKE"

    # Measure overlap and bar characteristics
    n = len(recent)

    # Overlap ratio: how many bars have >50% overlap with prior bar?
    overlap_count = 0
    for i in range(1, n):
        overlap_high = min(recent[i].high, recent[i - 1].high)
        overlap_low = max(recent[i].low, recent[i - 1].low)
        if overlap_high > overlap_low:
            overlap_size = overlap_high - overlap_low
            bar_range = recent[i].range_size
            if bar_range > 0 and overlap_size / bar_range > 0.50:
                overlap_count += 1

    overlap_pct = overlap_count / (n - 1) if n > 1 else 0

    # Trend bar ratio
    trend_bars = sum(1 for b in recent if b.is_trend_bar)
    trend_ratio = trend_bars / n

    # Doji ratio
    doji_count = sum(1 for b in recent if b.is_doji)
    doji_ratio = doji_count / n

    # Determine phase
    if trend_ratio >= 0.60 and overlap_pct < 0.30:
        return "TIGHT_CHANNEL"
    elif trend_ratio >= 0.40 and overlap_pct < 0.50:
        return "CHANNEL"
    elif overlap_pct < 0.70 and doji_ratio < 0.40:
        return "BROAD_CHANNEL"
    else:
        return "TRADING_RANGE"


# ─────────────────────────────────────────────────────────────────
#  TWO-LEG ANALYSIS
# ─────────────────────────────────────────────────────────────────

def analyze_two_legs(bars: List[BarAnalysis]) -> dict:
    """
    Analyze the current move in terms of Al Brooks' two-leg concept.

    "Almost every move, whether a trend or a pullback, has two legs.
    After the first leg, expect a second leg approximately equal in size."

    Returns dict with leg analysis and measured move target.
    """
    result = {
        "current_leg": 0,
        "leg1_size": 0.0,
        "leg2_size": 0.0,
        "two_leg_complete": False,
        "measured_move_target": 0.0,
        "legs": [],
    }

    if len(bars) < 10:
        return result

    # Find legs by detecting swing points
    legs = _find_trend_legs(bars)
    result["legs"] = legs

    if not legs:
        return result

    if len(legs) >= 2:
        result["current_leg"] = 2
        result["leg1_size"] = legs[-2].size
        result["leg2_size"] = legs[-1].size
        result["two_leg_complete"] = True

        # Measured move: project from end of leg 1 pullback
        if legs[-1].direction == "BULL":
            result["measured_move_target"] = legs[-1].start_price + legs[-2].size
        else:
            result["measured_move_target"] = legs[-1].start_price - legs[-2].size

    elif len(legs) == 1:
        result["current_leg"] = 1
        result["leg1_size"] = legs[0].size

        # Project measured move target for second leg
        if legs[0].direction == "BULL":
            result["measured_move_target"] = bars[-1].close + legs[0].size
        else:
            result["measured_move_target"] = bars[-1].close - legs[0].size

    return result


def _find_trend_legs(bars: List[BarAnalysis]) -> List[TrendLeg]:
    """Find directional legs in recent price action."""
    if len(bars) < 5:
        return []

    legs: List[TrendLeg] = []
    # Use a simplified approach: find significant swing points and
    # measure moves between them
    from price_action.patterns import _find_swing_points

    swing_highs = _find_swing_points(bars, "HIGH", lookback=2)
    swing_lows = _find_swing_points(bars, "LOW", lookback=2)

    # Merge and sort all swings
    all_swings = [(idx, price, "HIGH") for idx, price in swing_highs] + \
                 [(idx, price, "LOW") for idx, price in swing_lows]
    all_swings.sort(key=lambda x: x[0])

    # Build legs from alternating swings
    for i in range(1, len(all_swings)):
        prev_idx, prev_price, prev_type = all_swings[i - 1]
        curr_idx, curr_price, curr_type = all_swings[i]

        if prev_type == "LOW" and curr_type == "HIGH":
            leg = TrendLeg(
                direction="BULL",
                start_idx=prev_idx,
                end_idx=curr_idx,
                start_price=prev_price,
                end_price=curr_price,
                size=abs(curr_price - prev_price),
                bars=curr_idx - prev_idx,
                start_date=bars[prev_idx].date if prev_idx < len(bars) else "",
                end_date=bars[curr_idx].date if curr_idx < len(bars) else "",
            )
            legs.append(leg)

        elif prev_type == "HIGH" and curr_type == "LOW":
            leg = TrendLeg(
                direction="BEAR",
                start_idx=prev_idx,
                end_idx=curr_idx,
                start_price=prev_price,
                end_price=curr_price,
                size=abs(curr_price - prev_price),
                bars=curr_idx - prev_idx,
                start_date=bars[prev_idx].date if prev_idx < len(bars) else "",
                end_date=bars[curr_idx].date if curr_idx < len(bars) else "",
            )
            legs.append(leg)

    return legs


# ─────────────────────────────────────────────────────────────────
#  CONSECUTIVE BAR ANALYSIS
# ─────────────────────────────────────────────────────────────────

def _count_consecutive(bars: List[BarAnalysis]) -> dict:
    """Count consecutive trend bars at the end of the series."""
    if not bars:
        return {"bull_trend": 0, "bear_trend": 0, "bull_close": 0, "bear_close": 0}

    bull_trend = 0
    bear_trend = 0
    bull_close = 0
    bear_close = 0

    # Count consecutive bull/bear trend bars from the end
    for b in reversed(bars):
        if b.is_trend_bar and b.is_bull:
            bull_trend += 1
        else:
            break

    if bull_trend == 0:
        for b in reversed(bars):
            if b.is_trend_bar and b.is_bear:
                bear_trend += 1
            else:
                break

    # Count consecutive closes above/below prior close
    for i in range(len(bars) - 1, 0, -1):
        if bars[i].close > bars[i - 1].close:
            bull_close += 1
        else:
            break

    if bull_close == 0:
        for i in range(len(bars) - 1, 0, -1):
            if bars[i].close < bars[i - 1].close:
                bear_close += 1
            else:
                break

    return {
        "bull_trend": bull_trend,
        "bear_trend": bear_trend,
        "bull_close": bull_close,
        "bear_close": bear_close,
    }


# ─────────────────────────────────────────────────────────────────
#  MAIN ENTRY POINT: FULL TREND ANALYSIS
# ─────────────────────────────────────────────────────────────────

def analyze_trend(
    bars: List[BarAnalysis],
    df: pd.DataFrame,
) -> TrendState:
    """
    Perform complete Al Brooks trend analysis.

    Parameters
    ----------
    bars : list[BarAnalysis]
        Classified bars from bar_types.classify_bars().
    df : pd.DataFrame
        Original OHLCV DataFrame with DatetimeIndex.

    Returns
    -------
    TrendState
        Complete trend state including always-in direction, pressure,
        spike/channel detection, two-leg analysis, and strength.
    """
    state = TrendState()

    if len(bars) < C.MIN_BARS_REQUIRED:
        state.description = "Insufficient data for trend analysis"
        return state

    # 1. Always-in direction
    ai_dir, ai_score, ai_conf = compute_always_in(bars, df)
    state.always_in = ai_dir
    state.always_in_score = round(ai_score, 1)
    state.always_in_confidence = round(ai_conf, 1)

    # Set trend direction from always-in
    if ai_dir == "LONG":
        state.trend_direction = "BULL"
    elif ai_dir == "SHORT":
        state.trend_direction = "BEAR"
    else:
        state.trend_direction = "SIDEWAYS"

    # 2. Buying / Selling pressure
    bp, sp, balance = compute_pressure(bars)
    state.buying_pressure = bp
    state.selling_pressure = sp
    state.pressure_balance = balance

    # 3. Spike detection
    spike_info = detect_spike(bars)
    state.in_spike = spike_info["in_spike"]
    state.spike_direction = spike_info["direction"]
    state.spike_bars = spike_info["bars"]
    state.spike_strength = spike_info["strength"]

    # 4. Trend phase
    state.trend_phase = detect_trend_phase(bars, spike_info)

    # 5. Two-leg analysis
    two_leg = analyze_two_legs(bars)
    state.current_leg = two_leg["current_leg"]
    state.leg1_size = two_leg["leg1_size"]
    state.leg2_size = two_leg["leg2_size"]
    state.two_leg_complete = two_leg["two_leg_complete"]
    state.measured_move_target = round(two_leg["measured_move_target"], 2)

    # 6. Consecutive analysis
    consec = _count_consecutive(bars)
    state.consecutive_bull_trend = consec["bull_trend"]
    state.consecutive_bear_trend = consec["bear_trend"]
    state.consecutive_bull_close = consec["bull_close"]
    state.consecutive_bear_close = consec["bear_close"]

    # 7. EMA reference
    if len(df) >= C.EMA_PERIOD:
        ema = df["Close"].ewm(span=C.EMA_PERIOD, adjust=False).mean()
        state.ema20 = round(ema.iloc[-1], 2)
        last_close = df["Close"].iloc[-1]
        if last_close > state.ema20 * 1.005:
            state.price_vs_ema = "ABOVE"
        elif last_close < state.ema20 * 0.995:
            state.price_vs_ema = "BELOW"
        else:
            state.price_vs_ema = "AT"

        # Brooks: "20 moving average gap bars" — count consecutive bars
        # where neither the low (in bull) nor high (in bear) touches EMA20.
        # 20+ gap bars = very strong trend, sign of strength.
        ema_values = ema.values
        gap_count = 0
        for j in range(len(df) - 1, max(0, len(df) - 60), -1):
            bar_low = df["Low"].iloc[j]
            bar_high = df["High"].iloc[j]
            ema_val = ema_values[j]
            # Bar doesn't touch EMA if EMA is not between low and high
            if bar_low > ema_val or bar_high < ema_val:
                gap_count += 1
            else:
                break  # First bar touching EMA ends the count
        state.ema_gap_bar_count = gap_count

    # 8. Recent climax
    recent_5 = bars[-5:]
    state.recent_climax = any(b.is_climax_bar for b in recent_5)

    # 9. Compute overall trend strength (0-100)
    state.trend_strength = _compute_trend_strength(state)

    # 10. Build description
    state.description = _build_trend_description(state)

    return state


def _compute_trend_strength(state: TrendState) -> float:
    """Compute overall trend strength (0-100) from all components."""
    strength = 0.0

    # Always-in strength (30 points)
    strength += abs(state.always_in_score) * 0.3

    # Pressure alignment (25 points)
    if state.trend_direction == "BULL" and state.pressure_balance == "BUYERS":
        strength += 25
    elif state.trend_direction == "BEAR" and state.pressure_balance == "SELLERS":
        strength += 25
    elif state.pressure_balance == "NEUTRAL":
        strength += 10

    # Trend phase (20 points)
    phase_scores = {
        "SPIKE": 20, "TIGHT_CHANNEL": 18, "CHANNEL": 15,
        "BROAD_CHANNEL": 8, "TRADING_RANGE": 3, "UNKNOWN": 5,
    }
    strength += phase_scores.get(state.trend_phase, 5)

    # Consecutive trend bars (15 points)
    max_consec = max(state.consecutive_bull_trend, state.consecutive_bear_trend)
    strength += min(max_consec * 5, 15)

    # Spike bonus (10 points)
    if state.in_spike:
        strength += 10

    # Brooks: 20 gap bar setup — very strong trend sign of strength
    if state.ema_gap_bar_count >= 20:
        strength += 10  # Major sign of strength per Brooks
    elif state.ema_gap_bar_count >= 10:
        strength += 5   # Moderate sign of strength

    return min(round(strength, 1), 100)


def _build_trend_description(state: TrendState) -> str:
    """Build human-readable trend description."""
    parts: List[str] = []

    # Direction
    if state.always_in == "LONG":
        parts.append(f"Always-in LONG (score {state.always_in_score:+.0f}, "
                     f"confidence {state.always_in_confidence:.0f}%)")
    elif state.always_in == "SHORT":
        parts.append(f"Always-in SHORT (score {state.always_in_score:+.0f}, "
                     f"confidence {state.always_in_confidence:.0f}%)")
    else:
        parts.append("No clear always-in direction (FLAT)")

    # Phase
    parts.append(f"Phase: {state.trend_phase}")

    # Pressure
    parts.append(f"Pressure: {state.pressure_balance} "
                 f"(buy {state.buying_pressure:.0f}% / sell {state.selling_pressure:.0f}%)")

    # Spike
    if state.in_spike:
        parts.append(f"IN SPIKE — {state.spike_bars} {state.spike_direction} bars, "
                     f"strength {state.spike_strength:.0f}")

    # Two-leg
    if state.two_leg_complete:
        parts.append(f"Two-leg move COMPLETE. Target: {state.measured_move_target:.2f}")
    elif state.current_leg == 1:
        parts.append(f"First leg in progress. Measured move target: {state.measured_move_target:.2f}")

    # Climax warning
    if state.recent_climax:
        parts.append("⚠ CLIMAX BAR detected — possible exhaustion")

    # Consecutive
    if state.consecutive_bull_trend >= C.CONSECUTIVE_TREND_STRONG:
        parts.append(f"{state.consecutive_bull_trend} consecutive bull trend bars — STRONG")
    elif state.consecutive_bear_trend >= C.CONSECUTIVE_TREND_STRONG:
        parts.append(f"{state.consecutive_bear_trend} consecutive bear trend bars — STRONG")

    # Brooks: 20 gap bar sign of strength
    if state.ema_gap_bar_count >= 20:
        parts.append(f"⚡ {state.ema_gap_bar_count} EMA gap bars — VERY STRONG trend (Brooks sign of strength)")
    elif state.ema_gap_bar_count >= 10:
        parts.append(f"{state.ema_gap_bar_count} EMA gap bars — strong trend momentum")

    return " | ".join(parts)
