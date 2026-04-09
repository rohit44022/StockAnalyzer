"""
market_profile/engine.py — Complete Dalton Market Profile Engine
=================================================================

Source: "Mind Over Markets" by Dalton, Jones & Dalton (2012 Updated Edition)

Implements from daily OHLCV data (per Dalton Section XV):
  - Value Area / POC approximation (D8, D9)
  - Day type classification (D12-D17)
  - Open type vs previous day (D18-D21, D22-D27)
  - Initiative vs Responsive framework (D67-D68)
  - Directional Performance = 30 relationships (D40)
  - Trend vs Bracket detection (D41-D42)
  - One-timeframing (D28)
  - Poor highs/lows (D61)
  - Profile shape: P/b formations (D33, D34)
  - 3-to-I high-probability setup (D48)
  - Neutral-Extreme detection (D50)
  - Balance-area breakout (D52)
  - Gap classification (D53)
  - Rotation Factor (D32)
  - Overnight inventory proxy (D58)
  - POC migration (D9)
  - VA placement sequence (D39)

WHAT IS DALTON: Every concept, framework, and qualitative rule.
WHAT IS CALIBRATION: All numeric thresholds translating Dalton's
qualitative descriptions into code (e.g., "narrow IB" → range < 0.6×ATR).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import numpy as np
import pandas as pd


# ═══════════════════════════════════════════════════════════════
#  DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════

@dataclass
class DayProfile:
    """Single day's Market Profile approximation from OHLCV."""
    date: Any
    open: float
    high: float
    low: float
    close: float
    volume: float
    va_high: float      # Value Area High (70% range proxy)
    va_low: float       # Value Area Low
    poc: float          # Point of Control (fairest price proxy)
    range_size: float   # High - Low
    body_size: float    # |Open - Close|
    body_ratio: float   # body / range (0-1)
    close_position: float  # (Close-Low) / (High-Low), 0=low 1=high
    upper_tail: float   # H - max(O,C) as fraction of range
    lower_tail: float   # min(O,C) - L as fraction of range


@dataclass
class MarketProfileResult:
    """Complete Dalton Market Profile analysis output."""

    # [D8, D9] Current day's Value Area
    va_high: float = 0.0
    va_low: float = 0.0
    poc: float = 0.0

    # [D12-D17] Day Type Classification
    day_type: str = "UNKNOWN"           # NONTREND | NEUTRAL | NEUTRAL_EXTREME |
                                        # NORMAL | NORMAL_VARIATION | TREND | DOUBLE_DIST
    day_type_conviction: str = "LOW"    # LOW | MODERATE | HIGH | VERY_HIGH

    # [D18-D21] Open Type
    open_type: str = "UNKNOWN"          # OPEN_DRIVE | OPEN_TEST_DRIVE |
                                        # OPEN_REJECTION_REVERSE | OPEN_AUCTION

    # [D22-D27] Open vs Previous Day's VA/Range
    open_vs_prev_va: str = "UNKNOWN"    # WITHIN_VA | WITHIN_RANGE | OUTSIDE_RANGE
    open_location: str = "UNKNOWN"      # ABOVE | BELOW | WITHIN

    # [D40] Directional Performance (30 relationships)
    attempted_direction: str = "NEUTRAL"  # UP | DOWN | NEUTRAL
    directional_performance: str = "NEUTRAL"  # VERY_STRONG | STRONG | MODERATE | WEAK | VERY_WEAK | NEUTRAL

    # [D39] VA Relationship to Previous
    va_relationship: str = "UNKNOWN"    # HIGHER | LOWER | OVERLAPPING | INSIDE | OUTSIDE

    # [D41-D42] Market Structure
    market_structure: str = "UNKNOWN"   # TRENDING_UP | TRENDING_DOWN | BRACKETING | TRANSITIONING
    bracket_days: int = 0

    # [D28] One-Timeframing
    one_timeframing: str = "NONE"       # UP | DOWN | NONE
    one_tf_days: int = 0

    # [D61] Poor Highs/Lows
    is_poor_high: bool = False
    is_poor_low: bool = False
    consecutive_poor_highs: int = 0
    consecutive_poor_lows: int = 0

    # [D33, D34] Profile Shape
    profile_shape: str = "NORMAL"       # P_SHAPE | B_SHAPE | ELONGATED | NORMAL

    # [D48] 3-to-I Day (94%/97% probability)
    is_3_to_i: bool = False
    three_to_i_direction: str = "NONE"  # BULLISH | BEARISH

    # [D50] Neutral-Extreme (92% probability)
    is_neutral_extreme: bool = False
    neutral_extreme_direction: str = "NONE"

    # [D52] Balance-Area Breakout
    is_balance_breakout: bool = False
    balance_breakout_direction: str = "NONE"

    # [D67] Initiative vs Responsive
    activity_type: str = "UNKNOWN"      # INITIATIVE_BUYING | INITIATIVE_SELLING |
                                        # RESPONSIVE_BUYING | RESPONSIVE_SELLING | MIXED

    # [D53] Gap Analysis
    gap_type: str = "NONE"              # BREAKAWAY | ACCELERATION | EXHAUSTION | NONE
    gap_direction: str = "NONE"         # UP | DOWN | NONE
    gap_size_pct: float = 0.0

    # [D58] Overnight Inventory Proxy
    overnight_inventory: str = "NEUTRAL"  # LONG | SHORT | NEUTRAL

    # [D32] Rotation Factor
    rotation_factor: int = 0

    # [D9] POC Migration
    poc_migration: str = "STATIONARY"   # MIGRATING_UP | MIGRATING_DOWN | STATIONARY

    # [D39] VA Sequence (last 5 days)
    va_sequence: List[str] = field(default_factory=list)

    # Score adjustments for blending into triple engine
    cv_bonus: float = 0.0               # Cross-validation adjustment

    # Human-readable observations
    observations: List[str] = field(default_factory=list)
    dalton_signals: List[Dict[str, Any]] = field(default_factory=list)

    # Summary
    summary: str = ""


# ═══════════════════════════════════════════════════════════════
#  VALUE AREA COMPUTATION
# ═══════════════════════════════════════════════════════════════

def _compute_day_profile(row, prev_row=None) -> DayProfile:
    """
    [D8, D9] Approximate Value Area and POC from single OHLCV bar.

    Dalton: "Value Area = price region where 70% of TPOs occurred."
    Without intraday TPO data, we proxy by ensuring the VA always
    covers ~70% of the day's range, centered on the body midpoint.
    [CALIBRATION] VA width = max(body + 0.30*range, 0.70*range)
    ensures Dalton's ~70% threshold is met even for doji candles.
    """
    o, h, l, c, v = row["Open"], row["High"], row["Low"], row["Close"], row.get("Volume", 0)

    # Sanitize: clamp close within [low, high] to handle bad data
    c = max(l, min(h, c))
    o = max(l, min(h, o))

    rng = h - l if h > l else 0.001
    body_top = max(o, c)
    body_bot = min(o, c)
    body = body_top - body_bot

    # VA = centered on body, guaranteed ≥70% of range [D8]
    body_mid = (body_top + body_bot) / 2.0
    va_half = max(body / 2.0 + 0.15 * rng, 0.35 * rng)  # at least 70% of range
    va_high = min(h, body_mid + va_half)
    va_low = max(l, body_mid - va_half)

    # If body is near one extreme, the VA gets capped — redistribute
    min_va_width = 0.70 * rng
    if (va_high - va_low) < min_va_width:
        deficit = min_va_width - (va_high - va_low)
        room_below = va_low - l
        room_above = h - va_high
        if room_below >= deficit:
            va_low -= deficit
        elif room_above >= deficit:
            va_high += deficit
        else:
            va_low = max(l, va_low - deficit / 2)
            va_high = min(h, va_high + deficit / 2)

    # POC = weighted typical price (Dalton: "fairest price")
    poc = (h + l + c + c) / 4.0

    close_pos = (c - l) / rng if rng > 0.001 else 0.5
    upper_tail = (h - body_top) / rng if rng > 0.001 else 0.0
    lower_tail = (body_bot - l) / rng if rng > 0.001 else 0.0
    body_ratio = body / rng if rng > 0.001 else 0.0

    return DayProfile(
        date=row.get("Date", row.name if hasattr(row, "name") else None),
        open=o, high=h, low=l, close=c, volume=v,
        va_high=va_high, va_low=va_low, poc=poc,
        range_size=rng, body_size=body, body_ratio=body_ratio,
        close_position=close_pos,
        upper_tail=upper_tail, lower_tail=lower_tail,
    )


def _compute_profiles(df: pd.DataFrame, lookback: int = 20) -> List[DayProfile]:
    """Compute DayProfile for the last `lookback` bars."""
    n = min(lookback, len(df))
    profiles = []
    for i in range(-n, 0):
        row = df.iloc[i]
        profiles.append(_compute_day_profile(row))
    return profiles


# ═══════════════════════════════════════════════════════════════
#  DAY TYPE CLASSIFICATION (D12-D17)
# ═══════════════════════════════════════════════════════════════

def _classify_day_type(
    profile: DayProfile,
    atr: float,
    avg_vol: float,
) -> tuple:
    """
    [D12-D17] Classify today's day type from OHLCV.

    Dalton defines 6 day types by OTF participation and IB width.
    Without intraday data, we approximate using range/ATR ratio,
    body/range ratio, close position, and volume.

    Returns: (day_type, conviction_level)
    """
    range_ratio = profile.range_size / atr if atr > 0 else 1.0
    vol_ratio = profile.volume / avg_vol if avg_vol > 0 else 1.0

    # [D12] Nontrend: tiny range, low volume — no OTF activity
    if range_ratio < 0.5 and vol_ratio < 0.7:
        return "NONTREND", "LOW"

    # [D16] Trend: huge range, open near one extreme, close near other
    # body > 70% of range, close at extreme
    if (range_ratio > 1.5 and profile.body_ratio > 0.65
            and (profile.close_position > 0.80 or profile.close_position < 0.20)):
        return "TREND", "VERY_HIGH"

    # [D17] Double-Distribution: large range but distinct separation
    # Proxy: very large range + moderate body ratio (2 clusters, not 1 continuous move)
    if range_ratio > 1.5 and 0.35 <= profile.body_ratio <= 0.65:
        return "DOUBLE_DIST", "HIGH"

    # [D13] Neutral: range extension both sides, close determines subtype
    # Moderate range, close near center = Neutral
    if 0.7 <= range_ratio <= 1.3 and 0.25 <= profile.close_position <= 0.75:
        if profile.body_ratio < 0.40:
            return "NEUTRAL", "LOW"
        return "NEUTRAL", "MODERATE"

    # [D13] Neutral-Extreme: Neutral pattern but close at extreme
    if 0.7 <= range_ratio <= 1.3 and (profile.close_position > 0.80 or profile.close_position < 0.20):
        return "NEUTRAL_EXTREME", "HIGH"

    # [D15] Normal Variation: moderate-to-large range, partial OTF extension
    if range_ratio > 1.0 and profile.body_ratio > 0.50:
        return "NORMAL_VARIATION", "MODERATE"

    # [D14] Normal: typical range, two-sided trade
    return "NORMAL", "MODERATE"


# ═══════════════════════════════════════════════════════════════
#  OPEN TYPE CLASSIFICATION (D18-D21)
# ═══════════════════════════════════════════════════════════════

def _classify_open_type(
    profile: DayProfile,
    prev_profile: DayProfile,
    atr: float,
) -> str:
    """
    [D18-D21] Classify today's opening type.

    Dalton ranks open types by conviction:
    1. Open-Drive (highest) — opens at extreme, never returns
    2. Open-Test-Drive — tests one direction, then drives the other
    3. Open-Rejection-Reverse — less conviction reversal
    4. Open-Auction — no initial conviction, rotational

    From daily OHLCV:
    - Open-Drive: open = day's high or low (within 5% of range)
    - Open-Test-Drive: open near prev reference, close at opposite end
    - Open-Auction: open within previous VA, moderate range
    """
    rng = profile.range_size
    if rng < 0.001:
        return "OPEN_AUCTION"

    open_from_low = (profile.open - profile.low) / rng
    open_from_high = (profile.high - profile.open) / rng

    # [D18] Open-Drive: open IS the extreme (within 5% of range)
    # [CALIBRATION] 0.05 threshold
    if open_from_low < 0.05 and profile.close_position > 0.70:
        return "OPEN_DRIVE"  # Bullish drive — opened at low, closed near high
    if open_from_high < 0.05 and profile.close_position < 0.30:
        return "OPEN_DRIVE"  # Bearish drive — opened at high, closed near low

    # Gap context: how far did we open from previous close?
    gap_pct = abs(profile.open - prev_profile.close) / atr if atr > 0 else 0

    # [D19] Open-Test-Drive: opened near a reference, reversed strongly
    # Open near prev high/low, close at opposite end of today's range
    near_prev_high = abs(profile.open - prev_profile.high) < 0.3 * atr
    near_prev_low = abs(profile.open - prev_profile.low) < 0.3 * atr

    if near_prev_high and profile.close_position < 0.30:
        return "OPEN_TEST_DRIVE"  # Tested above prev high, drove down
    if near_prev_low and profile.close_position > 0.70:
        return "OPEN_TEST_DRIVE"  # Tested below prev low, drove up

    # [D20] Open-Rejection-Reverse: open outside prev range, rejected back
    if profile.open > prev_profile.high and profile.close < prev_profile.va_high:
        return "OPEN_REJECTION_REVERSE"
    if profile.open < prev_profile.low and profile.close > prev_profile.va_low:
        return "OPEN_REJECTION_REVERSE"

    # [D21] Open-Auction: default — rotational, no immediate conviction
    return "OPEN_AUCTION"


# ═══════════════════════════════════════════════════════════════
#  OPEN vs PREVIOUS DAY (D22-D27)
# ═══════════════════════════════════════════════════════════════

def _classify_open_vs_prev(profile: DayProfile, prev: DayProfile) -> tuple:
    """
    [D22-D27] Where did today open relative to yesterday's VA and range?

    Returns: (open_vs_prev_va, open_location)
    """
    o = profile.open

    if prev.va_low <= o <= prev.va_high:
        return "WITHIN_VA", "WITHIN"
    elif prev.low <= o <= prev.high:
        loc = "ABOVE" if o > prev.va_high else "BELOW"
        return "WITHIN_RANGE", loc
    else:
        loc = "ABOVE" if o > prev.high else "BELOW"
        return "OUTSIDE_RANGE", loc


# ═══════════════════════════════════════════════════════════════
#  INITIATIVE vs RESPONSIVE (D67-D68)
# ═══════════════════════════════════════════════════════════════

def _classify_activity(profile: DayProfile, prev: DayProfile) -> str:
    """
    [D67] Four types of market activity relative to previous VA.

    Dalton D67:
      1. Initiative Buying  = buying within or ABOVE prev VA (strongest bullish)
      2. Initiative Selling  = selling within or BELOW prev VA (strongest bearish)
      3. Responsive Buying  = buying BELOW prev VA (reactive to low prices)
      4. Responsive Selling  = selling ABOVE prev VA (reactive to high prices)

    Initiative = conviction (came hunting for business)
    Responsive = reactive (lured by favorable prices)
    """
    is_up = profile.close > profile.open
    is_down = profile.close < profile.open

    if is_up:
        # [D67] Buying within or above prev VA = Initiative
        if profile.close >= prev.va_low:
            return "INITIATIVE_BUYING"
        else:
            return "RESPONSIVE_BUYING"   # Buying below prev VA
    elif is_down:
        # [D67] Selling within or below prev VA = Initiative
        if profile.close <= prev.va_high:
            return "INITIATIVE_SELLING"
        else:
            return "RESPONSIVE_SELLING"  # Selling above prev VA
    return "MIXED"


# ═══════════════════════════════════════════════════════════════
#  DIRECTIONAL PERFORMANCE — 30 RELATIONSHIPS (D40)
# ═══════════════════════════════════════════════════════════════

def _assess_directional_performance(
    profiles: List[DayProfile],
    avg_vol: float,
) -> tuple:
    """
    [D40] Dalton's 30 Directional Performance Relationships.

    Combines: attempted_direction × volume_change × VA_placement
    to produce performance ratings from VERY_STRONG to VERY_WEAK.

    Uses last 2 bars for comparison.
    """
    if len(profiles) < 2:
        return "NEUTRAL", "NEUTRAL"

    today = profiles[-1]
    prev = profiles[-2]

    # Attempted direction from rotation
    if today.high > prev.high and today.low >= prev.low:
        attempted = "UP"
    elif today.low < prev.low and today.high <= prev.high:
        attempted = "DOWN"
    elif today.high > prev.high and today.low < prev.low:
        attempted = "UP" if today.close_position > 0.5 else "DOWN"
    else:
        attempted = "NEUTRAL"

    # Volume change
    vol_change = "UNCHANGED"
    if avg_vol > 0:
        today_ratio = today.volume / avg_vol
        prev_ratio = prev.volume / avg_vol
        if today.volume > prev.volume * 1.1:
            vol_change = "HIGHER"
        elif today.volume < prev.volume * 0.9:
            vol_change = "LOWER"

    # VA placement
    if today.va_high > prev.va_high and today.va_low >= prev.va_low:
        va_place = "HIGHER"
    elif today.va_low < prev.va_low and today.va_high <= prev.va_high:
        va_place = "LOWER"
    elif today.va_high > prev.va_high and today.va_low < prev.va_low:
        va_place = "OUTSIDE"
    elif today.va_high < prev.va_high and today.va_low > prev.va_low:
        va_place = "INSIDE"
    else:
        va_place = "OVERLAPPING"

    # [D40] Map to performance rating
    if attempted == "UP":
        if vol_change == "HIGHER" and va_place == "HIGHER":
            return "UP", "VERY_STRONG"
        if vol_change == "HIGHER" and va_place in ("OVERLAPPING", "OUTSIDE"):
            return "UP", "STRONG"
        if vol_change == "LOWER" and va_place == "HIGHER":
            return "UP", "MODERATE"
        if vol_change == "LOWER" and va_place in ("LOWER", "INSIDE"):
            return "UP", "VERY_WEAK"
        if vol_change == "LOWER" and va_place == "OVERLAPPING":
            return "UP", "WEAK"
        return "UP", "MODERATE"

    if attempted == "DOWN":
        if vol_change == "HIGHER" and va_place == "LOWER":
            return "DOWN", "VERY_STRONG"
        if vol_change == "HIGHER" and va_place in ("OVERLAPPING", "OUTSIDE"):
            return "DOWN", "STRONG"
        if vol_change == "LOWER" and va_place == "LOWER":
            return "DOWN", "MODERATE"
        if vol_change == "LOWER" and va_place in ("HIGHER", "INSIDE"):
            return "DOWN", "VERY_WEAK"
        if vol_change == "LOWER" and va_place == "OVERLAPPING":
            return "DOWN", "WEAK"
        return "DOWN", "MODERATE"

    return "NEUTRAL", "NEUTRAL"


# ═══════════════════════════════════════════════════════════════
#  VA RELATIONSHIP & SEQUENCE (D39)
# ═══════════════════════════════════════════════════════════════

def _compute_va_relationship(today: DayProfile, prev: DayProfile) -> str:
    """[D39] VA placement relative to previous day."""
    if today.va_low > prev.va_high:
        return "HIGHER"
    if today.va_high < prev.va_low:
        return "LOWER"
    if today.va_high > prev.va_high and today.va_low < prev.va_low:
        return "OUTSIDE"
    if today.va_high < prev.va_high and today.va_low > prev.va_low:
        return "INSIDE"
    return "OVERLAPPING"


def _compute_va_sequence(profiles: List[DayProfile]) -> List[str]:
    """[D39] VA placement for each day vs previous (last 5)."""
    seq = []
    for i in range(1, len(profiles)):
        seq.append(_compute_va_relationship(profiles[i], profiles[i - 1]))
    return seq[-5:]


# ═══════════════════════════════════════════════════════════════
#  TREND vs BRACKET (D41-D42)
# ═══════════════════════════════════════════════════════════════

def _detect_market_structure(profiles: List[DayProfile]) -> tuple:
    """
    [D41] Trend vs Bracket detection from VA sequence.

    Dalton: "Markets trend only 20-30% of the time."
    Trending = VAs separating in one direction.
    Bracketing = VAs overlapping, price oscillating between references.
    """
    if len(profiles) < 5:
        return "UNKNOWN", 0

    # Check last 5 days of VA relationships
    seq = _compute_va_sequence(profiles)

    overlap_count = sum(1 for s in seq if s in ("OVERLAPPING", "INSIDE"))
    higher_count = sum(1 for s in seq if s == "HIGHER")
    lower_count = sum(1 for s in seq if s == "LOWER")

    # [D41] Bracketing: VAs overlapping for 3+ consecutive days
    # [CALIBRATION] 3 out of last 5 days overlapping
    if overlap_count >= 3:
        return "BRACKETING", overlap_count

    # [D41] Trending: 3+ consecutive VAs moving in same direction
    if higher_count >= 3:
        return "TRENDING_UP", 0
    if lower_count >= 3:
        return "TRENDING_DOWN", 0

    # Transitioning: mixed signals
    return "TRANSITIONING", 0


# ═══════════════════════════════════════════════════════════════
#  ONE-TIMEFRAMING (D28)
# ═══════════════════════════════════════════════════════════════

def _detect_one_timeframing(profiles: List[DayProfile]) -> tuple:
    """
    [D28] One-timeframing detection from daily bars.

    Dalton: "One-timeframing UP: each successive period's LOW does
    not exceed the prior period's low."
    "It is generally financially dangerous to trade counter to
    one-timeframing."

    Returns: (direction, consecutive_days)
    """
    if len(profiles) < 3:
        return "NONE", 0

    # Check one-TF UP: each day's low >= previous day's low
    up_count = 0
    for i in range(len(profiles) - 1, 0, -1):
        if profiles[i].low >= profiles[i - 1].low - 0.001:
            up_count += 1
        else:
            break

    # Check one-TF DOWN: each day's high <= previous day's high
    down_count = 0
    for i in range(len(profiles) - 1, 0, -1):
        if profiles[i].high <= profiles[i - 1].high + 0.001:
            down_count += 1
        else:
            break

    if up_count >= 2:
        return "UP", up_count
    if down_count >= 2:
        return "DOWN", down_count
    return "NONE", 0


# ═══════════════════════════════════════════════════════════════
#  POOR HIGHS / POOR LOWS (D61)
# ═══════════════════════════════════════════════════════════════

def _detect_poor_extremes(profiles: List[DayProfile]) -> tuple:
    """
    [D61] "A lack of buying tail = poor low. A lack of selling tail =
    poor high. Auction not complete; will be revisited."

    "Multiple successive poor lows = EXPONENTIAL RISK for longs."

    [CALIBRATION] Tail < 10% of range = "poor" (no aggressive OTF rejection)
    """
    if not profiles:
        return False, False, 0, 0

    today = profiles[-1]
    is_poor_high = today.upper_tail < 0.10
    is_poor_low = today.lower_tail < 0.10

    # Count consecutive poor lows/highs
    consec_poor_lows = 0
    for p in reversed(profiles):
        if p.lower_tail < 0.10:
            consec_poor_lows += 1
        else:
            break

    consec_poor_highs = 0
    for p in reversed(profiles):
        if p.upper_tail < 0.10:
            consec_poor_highs += 1
        else:
            break

    return is_poor_high, is_poor_low, consec_poor_highs, consec_poor_lows


# ═══════════════════════════════════════════════════════════════
#  PROFILE SHAPE: P/b FORMATIONS (D33, D34)
# ═══════════════════════════════════════════════════════════════

def _detect_profile_shape(profiles: List[DayProfile]) -> str:
    """
    [D33] P-shape = short-covering rally (activity in upper part).
    [D34] b-shape = long-liquidation break (activity in lower part).

    From daily data:
    - P-shape: After decline, today closes near high, prior 2 bars declining
    - b-shape: After advance, today closes near low, prior 2 bars advancing
    - Elongated: Very large body ratio with close at extreme
    """
    if len(profiles) < 3:
        return "NORMAL"

    today = profiles[-1]
    prev1 = profiles[-2]
    prev2 = profiles[-3]

    # [D34] b-shape: preceding advance + today's close near low
    if prev2.close < prev1.close and prev1.close > today.close:
        if today.close_position < 0.30 and today.body_ratio > 0.40:
            return "B_SHAPE"

    # [D33] P-shape: preceding decline + today's close near high
    if prev2.close > prev1.close and prev1.close < today.close:
        if today.close_position > 0.70 and today.body_ratio > 0.40:
            return "P_SHAPE"

    # [D62] Elongated: extremely strong body, close at extreme
    if today.body_ratio > 0.80 and (today.close_position > 0.85 or today.close_position < 0.15):
        return "ELONGATED"

    return "NORMAL"


# ═══════════════════════════════════════════════════════════════
#  3-TO-I DETECTION (D48) — 94%/97% PROBABILITY
# ═══════════════════════════════════════════════════════════════

def _detect_3_to_i(profile: DayProfile, avg_vol: float, atr: float) -> tuple:
    """
    [D48] 3-to-I Day: Initiative tail + Initiative TPO count +
    Initiative range extension ALL point same direction.

    "94% of the time next day opens within or better than VA"
    "97% of the time next day closes within or better than VA"

    Approximation from daily OHLCV:
    - Strong tail in one direction (lower_tail > 0.15 for bullish)
    - Body > 60% of range (initiative dominance)
    - Volume > average (participation)
    - Close at extreme (> 0.75 for bullish, < 0.25 for bearish)
    - Range > 0.8 * ATR (meaningful range extension)

    [CALIBRATION] All thresholds are our translation of Dalton's qualitative criteria.
    """
    vol_ok = profile.volume > avg_vol * 0.9 if avg_vol > 0 else True
    range_ok = profile.range_size > atr * 0.8 if atr > 0 else True

    # Bullish 3-to-I
    if (profile.lower_tail > 0.12 and profile.body_ratio > 0.55
            and profile.close_position > 0.72 and vol_ok and range_ok):
        return True, "BULLISH"

    # Bearish 3-to-I
    if (profile.upper_tail > 0.12 and profile.body_ratio > 0.55
            and profile.close_position < 0.28 and vol_ok and range_ok):
        return True, "BEARISH"

    return False, "NONE"


# ═══════════════════════════════════════════════════════════════
#  NEUTRAL-EXTREME DETECTION (D50) — 92% PROBABILITY
# ═══════════════════════════════════════════════════════════════

def _detect_neutral_extreme(
    profile: DayProfile,
    day_type: str,
) -> tuple:
    """
    [D50] Neutral day closing on one extreme:
    "92% of the time next session trades within or better during
    first 90 minutes."

    Conditions: Day classified as NEUTRAL + close at extreme.
    """
    if day_type not in ("NEUTRAL", "NEUTRAL_EXTREME"):
        return False, "NONE"

    if profile.close_position > 0.80:
        return True, "BULLISH"
    if profile.close_position < 0.20:
        return True, "BEARISH"

    return False, "NONE"


# ═══════════════════════════════════════════════════════════════
#  BALANCE-AREA BREAKOUT (D52)
# ═══════════════════════════════════════════════════════════════

def _detect_balance_breakout(
    profiles: List[DayProfile],
    market_structure: str,
    atr: float,
) -> tuple:
    """
    [D52] "A trade you almost have to do" — balance-area breakout.

    Dalton (Ch.4): "Risk is minimal and profit potential is very high."

    Detection: Market was bracketing (overlapping VAs) then today's
    price breaks beyond the bracket range.
    """
    if market_structure != "BRACKETING" or len(profiles) < 5:
        return False, "NONE"

    # Define bracket bounds from overlapping period
    bracket_high = max(p.high for p in profiles[-5:-1])
    bracket_low = min(p.low for p in profiles[-5:-1])
    today = profiles[-1]

    # [CALIBRATION] Break beyond bracket by at least 0.3 * ATR
    threshold = 0.3 * atr if atr > 0 else 0

    if today.close > bracket_high + threshold and today.close_position > 0.60:
        return True, "BULLISH"
    if today.close < bracket_low - threshold and today.close_position < 0.40:
        return True, "BEARISH"

    return False, "NONE"


# ═══════════════════════════════════════════════════════════════
#  GAP CLASSIFICATION (D53)
# ═══════════════════════════════════════════════════════════════

def _classify_gap(
    profiles: List[DayProfile],
    market_structure: str,
    atr: float,
) -> tuple:
    """
    [D53] Three gap types:
    1. Breakaway: Start of new trend (at bracket extremes)
    2. Acceleration: Mid-trend confirmation
    3. Exhaustion: End of trend (often filled quickly)

    "Gap = form of excess = strongest form of excess."
    """
    if len(profiles) < 2:
        return "NONE", "NONE", 0.0

    today = profiles[-1]
    prev = profiles[-2]
    gap = today.open - prev.close
    gap_pct = abs(gap) / prev.close * 100 if prev.close > 0 else 0

    # No meaningful gap [CALIBRATION] threshold = 0.2% of price
    if gap_pct < 0.2:
        return "NONE", "NONE", 0.0

    direction = "UP" if gap > 0 else "DOWN"

    # [D53] Breakaway: gap from a bracket
    if market_structure == "BRACKETING":
        return "BREAKAWAY", direction, gap_pct

    # [D53] Exhaustion: gap in trend direction but with reversal close
    # Gap up but close below open = potential exhaustion
    if direction == "UP" and today.close < today.open:
        return "EXHAUSTION", direction, gap_pct
    if direction == "DOWN" and today.close > today.open:
        return "EXHAUSTION", direction, gap_pct

    # [D53] Acceleration: gap in trend direction with continuation
    if market_structure in ("TRENDING_UP", "TRENDING_DOWN"):
        return "ACCELERATION", direction, gap_pct

    return "BREAKAWAY", direction, gap_pct


# ═══════════════════════════════════════════════════════════════
#  OVERNIGHT INVENTORY PROXY (D58)
# ═══════════════════════════════════════════════════════════════

def _estimate_overnight_inventory(profile: DayProfile, prev: DayProfile) -> str:
    """
    [D58] Dalton: "If majority of overnight trade is above settle =
    overnight inventory LONG."

    Proxy: Compare today's open to previous close.
    Open > prev close = overnight longs. Open < prev close = overnight shorts.
    [CALIBRATION] Threshold: 0.15% gap is meaningful.
    """
    if prev.close <= 0:
        return "NEUTRAL"

    gap_pct = (profile.open - prev.close) / prev.close * 100

    if gap_pct > 0.15:
        return "LONG"
    if gap_pct < -0.15:
        return "SHORT"
    return "NEUTRAL"


# ═══════════════════════════════════════════════════════════════
#  ROTATION FACTOR (D32)
# ═══════════════════════════════════════════════════════════════

def _compute_rotation_factor(profiles: List[DayProfile], window: int = 5) -> int:
    """
    [D32] "For each period — if high > prior high, +1; if lower, -1.
    If low > prior low, +1; if lower, -1. Cumulative sum = Rotation Factor."

    Uses daily bars instead of 30-min periods.
    Positive = upward attempted direction. Negative = downward.
    """
    n = min(window, len(profiles) - 1)
    rf = 0
    for i in range(-n, 0):
        curr = profiles[i]
        prev = profiles[i - 1]
        if curr.high > prev.high:
            rf += 1
        elif curr.high < prev.high:
            rf -= 1
        if curr.low > prev.low:
            rf += 1
        elif curr.low < prev.low:
            rf -= 1
    return rf


# ═══════════════════════════════════════════════════════════════
#  POC MIGRATION (D9)
# ═══════════════════════════════════════════════════════════════

def _detect_poc_migration(profiles: List[DayProfile]) -> str:
    """
    [D9] "POC migrating higher = OTF buying in control.
    POC migrating lower = OTF selling in control.
    POC stationary = balance / no conviction."

    Check last 3 days of POC movement.
    """
    if len(profiles) < 3:
        return "STATIONARY"

    pocs = [p.poc for p in profiles[-3:]]
    up = all(pocs[i] > pocs[i - 1] for i in range(1, len(pocs)))
    down = all(pocs[i] < pocs[i - 1] for i in range(1, len(pocs)))

    if up:
        return "MIGRATING_UP"
    if down:
        return "MIGRATING_DOWN"
    return "STATIONARY"


# ═══════════════════════════════════════════════════════════════
#  CROSS-VALIDATION BONUS COMPUTATION
# ═══════════════════════════════════════════════════════════════

def _compute_cv_bonus(result: MarketProfileResult) -> float:
    """
    Compute the cross-validation bonus/penalty from Market Profile analysis.

    This is blended into the existing triple engine's cross-validation
    section alongside the Wyckoff bonus. It does NOT create a separate
    scoring dimension — it enhances the existing conviction assessment.

    Dalton signals are weighted by their book-stated probability:
      [D48] 3-to-I: ±12 pts (94%/97% probability — highest)
      [D52] Balance Breakout: ±10 pts ("trade you almost have to do")
      [D50] Neutral-Extreme: ±8 pts (92% probability)
      [D28] One-Timeframing: ±6 pts ("financially dangerous" to counter)
      [D40] Directional Performance: ±5 pts (30 relationships)
      [D61] Poor Highs/Lows: ±4 pts (incomplete auction)
      [D33/34] P/b Shape: ±3 pts (short covering / long liquidation warning)
      [D53] Gap Type: ±3 pts (excess classification)
      [D18] Open-Drive: ±2 pts (highest conviction open)

    Maximum bonus: clamped to ±35 to avoid overwhelming the triple system.
    [CALIBRATION] All point values are our design — Dalton gives
    qualitative rules, not numeric scores.
    """
    bonus = 0.0

    # [D48] 3-to-I Day — 94%/97% probability
    if result.is_3_to_i:
        bonus += 12 if result.three_to_i_direction == "BULLISH" else -12

    # [D52] Balance-Area Breakout — "trade you almost have to do"
    if result.is_balance_breakout:
        bonus += 10 if result.balance_breakout_direction == "BULLISH" else -10

    # [D50] Neutral-Extreme — 92% probability
    if result.is_neutral_extreme:
        bonus += 8 if result.neutral_extreme_direction == "BULLISH" else -8

    # [D28] One-Timeframing — "financially dangerous to counter"
    if result.one_timeframing == "UP":
        bonus += 6
    elif result.one_timeframing == "DOWN":
        bonus -= 6

    # [D40] Directional Performance
    perf_map = {"VERY_STRONG": 5, "STRONG": 3, "MODERATE": 1, "WEAK": -3, "VERY_WEAK": -5}
    perf_val = perf_map.get(result.directional_performance, 0)
    if result.attempted_direction == "DOWN":
        perf_val = -perf_val  # Invert for bearish attempts
    bonus += perf_val

    # [D61] Poor Highs/Lows — incomplete auction signals
    if result.consecutive_poor_lows >= 2:
        bonus -= 4  # "Multiple poor lows = exponential risk for longs"
    elif result.is_poor_low:
        bonus -= 2

    if result.consecutive_poor_highs >= 2:
        bonus += 4  # Multiple poor highs = exponential risk for shorts
    elif result.is_poor_high:
        bonus += 2

    # [D33/34] Profile Shape Warning
    if result.profile_shape == "P_SHAPE":
        bonus -= 3  # Short-covering rally — "NOT new buying, offers selling opportunity"
    elif result.profile_shape == "B_SHAPE":
        bonus += 3  # Long-liquidation break — "offers buying opportunity"

    # [D53] Gap Classification
    if result.gap_type == "BREAKAWAY":
        bonus += 3 if result.gap_direction == "UP" else -3
    elif result.gap_type == "EXHAUSTION":
        # Exhaustion gap = reversal signal, goes AGAINST gap direction
        bonus += -3 if result.gap_direction == "UP" else 3
    elif result.gap_type == "ACCELERATION":
        bonus += 2 if result.gap_direction == "UP" else -2

    # [D18] Open-Drive — highest conviction opening type
    if result.open_type == "OPEN_DRIVE":
        # Open-Drive always gets a bonus — Dalton ranks it as highest conviction
        if result.attempted_direction == "UP":
            bonus += 2
        elif result.attempted_direction == "DOWN":
            bonus -= 2

    # [D12] Nontrend day = STAND ASIDE penalty
    if result.day_type == "NONTREND":
        # Pull score toward zero — no facilitation = no opportunity
        bonus -= 3 if bonus > 0 else 3 if bonus < 0 else 0

    # Clamp
    return max(-35, min(35, bonus))


# ═══════════════════════════════════════════════════════════════
#  OBSERVATION BUILDER
# ═══════════════════════════════════════════════════════════════

def _build_observations(result: MarketProfileResult) -> List[str]:
    """Build human-readable observations from Dalton analysis."""
    obs = []

    # Day type
    day_type_labels = {
        "NONTREND": "Nontrend day — no facilitation. Dalton: STAND ASIDE.",
        "NEUTRAL": "Neutral day — both buyers and sellers present.",
        "NEUTRAL_EXTREME": "Neutral-Extreme — close at extreme signals next-session conviction.",
        "NORMAL": "Normal day — two-sided trade within typical range.",
        "NORMAL_VARIATION": "Normal Variation — OTF extending range on one side.",
        "TREND": "TREND DAY — highest conviction. One-timeframe activity all day.",
        "DOUBLE_DIST": "Double-Distribution Trend — two clusters of value, very high conviction.",
    }
    if result.day_type in day_type_labels:
        obs.append(f"📊 [DALTON] {day_type_labels[result.day_type]}")

    # High-probability setups
    if result.is_3_to_i:
        d = result.three_to_i_direction
        obs.append(
            f"🎯 [DALTON D48] 3-to-I {d} — Initiative tail + body + range extension "
            f"all aligned {d}. Dalton: \"94% next day trades better than VA, "
            f"97% closes within or better.\" HIGHEST PROBABILITY mechanical trade."
        )

    if result.is_balance_breakout:
        d = result.balance_breakout_direction
        obs.append(
            f"🔥 [DALTON D52] Balance-Area Breakout {d} — "
            f"Dalton: \"A trade you almost have to do. Risk is minimal and "
            f"profit potential is very high.\""
        )

    if result.is_neutral_extreme:
        d = result.neutral_extreme_direction
        obs.append(
            f"📊 [DALTON D50] Neutral-Extreme {d} — "
            f"Dalton: \"92% of the time next session trades within or better "
            f"during first 90 minutes.\" High-probability setup."
        )

    # One-timeframing
    if result.one_timeframing != "NONE":
        obs.append(
            f"📊 [DALTON D28] One-timeframing {result.one_timeframing} "
            f"({result.one_tf_days} days). Dalton: \"It is generally financially "
            f"dangerous to trade counter to one-timeframing.\""
        )

    # Directional performance
    if result.directional_performance in ("VERY_STRONG", "VERY_WEAK"):
        obs.append(
            f"📊 [DALTON D40] Directional performance: Attempting {result.attempted_direction}, "
            f"performance is {result.directional_performance} "
            f"(volume × VA placement assessment from 30 relationships)."
        )

    # Poor highs/lows
    if result.consecutive_poor_lows >= 2:
        obs.append(
            f"⚠️ [DALTON D61] {result.consecutive_poor_lows} consecutive POOR LOWS — "
            f"Dalton: \"Multiple successive poor lows = EXPONENTIAL RISK for longs.\" "
            f"Auction incomplete, will likely be revisited."
        )
    elif result.is_poor_low:
        obs.append(
            "⚠️ [DALTON D61] Poor Low detected — no buying tail. "
            "Auction incomplete, may be revisited."
        )

    if result.consecutive_poor_highs >= 2:
        obs.append(
            f"📊 [DALTON D61] {result.consecutive_poor_highs} consecutive POOR HIGHS — "
            f"multiple incomplete auctions above. Exponential risk for shorts."
        )
    elif result.is_poor_high:
        obs.append(
            "📊 [DALTON D61] Poor High — no selling tail. "
            "Auction incomplete above, may be revisited."
        )

    # Profile shape
    if result.profile_shape == "P_SHAPE":
        obs.append(
            "📊 [DALTON D33] P-shaped profile — short-covering rally. "
            "Dalton: \"This is OLD business covering, NOT new buying. "
            "Market resumes prior course once covering diminishes.\""
        )
    elif result.profile_shape == "B_SHAPE":
        obs.append(
            "📊 [DALTON D34] b-shaped profile — long-liquidation break. "
            "Dalton: \"Market corrects upward after liquidation exhausts itself. "
            "Offers buying opportunity.\""
        )

    # Open type
    open_labels = {
        "OPEN_DRIVE": "Open-Drive — highest conviction. Dalton: \"Enter EARLY.\"",
        "OPEN_TEST_DRIVE": "Open-Test-Drive — tested reference and reversed.",
        "OPEN_REJECTION_REVERSE": "Open-Rejection-Reverse — opened out of balance, rejected back.",
        "OPEN_AUCTION": "Open-Auction — no initial conviction.",
    }
    if result.open_type in open_labels:
        obs.append(f"📊 [DALTON D18-21] {open_labels[result.open_type]}")

    # Activity type
    if result.activity_type == "INITIATIVE_BUYING":
        obs.append(
            "📊 [DALTON D67] Initiative Buying — buyers came hunting above "
            "previous value. Strongest bullish conviction."
        )
    elif result.activity_type == "INITIATIVE_SELLING":
        obs.append(
            "📊 [DALTON D67] Initiative Selling — sellers came hunting below "
            "previous value. Strongest bearish conviction."
        )

    # Market structure
    if result.market_structure == "BRACKETING":
        obs.append(
            f"📊 [DALTON D41] Market is BRACKETING (overlapping VAs for "
            f"{result.bracket_days} days). Dalton: \"Markets spend 70-80% of "
            f"time in trading range.\" Trade responsively or wait for breakout."
        )
    elif result.market_structure == "TRENDING_UP":
        obs.append("📊 [DALTON D41] Market TRENDING UP — VAs separating higher.")
    elif result.market_structure == "TRENDING_DOWN":
        obs.append("📊 [DALTON D41] Market TRENDING DOWN — VAs separating lower.")

    # POC Migration
    if result.poc_migration == "MIGRATING_UP":
        obs.append(
            "📊 [DALTON D9] POC migrating higher — other-timeframe buying in control."
        )
    elif result.poc_migration == "MIGRATING_DOWN":
        obs.append(
            "📊 [DALTON D9] POC migrating lower — other-timeframe selling in control."
        )

    # Gap classification
    if result.gap_type != "NONE":
        gap_labels = {
            "BREAKAWAY": "Breakaway gap — start of new trend. Trade WITH the gap.",
            "ACCELERATION": "Acceleration gap — mid-trend confirmation.",
            "EXHAUSTION": "Exhaustion gap — potential end of trend, may fill quickly.",
        }
        obs.append(
            f"📊 [DALTON D53] {result.gap_direction} {gap_labels.get(result.gap_type, '')} "
            f"({result.gap_size_pct:.2f}%)"
        )

    # Overnight inventory
    if result.overnight_inventory != "NEUTRAL":
        obs.append(
            f"📊 [DALTON D58] Overnight inventory {result.overnight_inventory}. "
            f"Dalton: \"If inventory gets too long/short, expect inventory "
            f"adjustment shortly after open.\""
        )

    return obs


def _build_dalton_signals(result: MarketProfileResult) -> List[Dict[str, Any]]:
    """Build structured signal list for dashboard consumption."""
    signals = []

    if result.is_3_to_i:
        signals.append({
            "type": "3_TO_I",
            "direction": result.three_to_i_direction,
            "probability": "94%/97%",
            "rule": "D48",
            "description": "3-to-I alignment — highest probability Dalton setup",
        })

    if result.is_balance_breakout:
        signals.append({
            "type": "BALANCE_BREAKOUT",
            "direction": result.balance_breakout_direction,
            "probability": "HIGH",
            "rule": "D52",
            "description": "Balance-area breakout — 'trade you almost have to do'",
        })

    if result.is_neutral_extreme:
        signals.append({
            "type": "NEUTRAL_EXTREME",
            "direction": result.neutral_extreme_direction,
            "probability": "92%",
            "rule": "D50",
            "description": "Neutral-Extreme day — 92% next session favorable",
        })

    if result.one_timeframing != "NONE":
        signals.append({
            "type": "ONE_TIMEFRAMING",
            "direction": result.one_timeframing,
            "days": result.one_tf_days,
            "rule": "D28",
            "description": f"One-timeframing {result.one_timeframing} for {result.one_tf_days} days",
        })

    if result.consecutive_poor_lows >= 2:
        signals.append({
            "type": "POOR_LOWS_EXPONENTIAL",
            "count": result.consecutive_poor_lows,
            "rule": "D61",
            "description": f"{result.consecutive_poor_lows} consecutive poor lows — exponential risk for longs",
        })

    if result.consecutive_poor_highs >= 2:
        signals.append({
            "type": "POOR_HIGHS_EXPONENTIAL",
            "count": result.consecutive_poor_highs,
            "rule": "D61",
            "description": f"{result.consecutive_poor_highs} consecutive poor highs — exponential risk for shorts",
        })

    return signals


# ═══════════════════════════════════════════════════════════════
#  SUMMARY BUILDER
# ═══════════════════════════════════════════════════════════════

def _build_summary(result: MarketProfileResult) -> str:
    """Build a one-paragraph Dalton-perspective summary."""
    parts = []

    # Market structure context
    struct_map = {
        "TRENDING_UP": "The market is in an uptrend with value areas migrating higher",
        "TRENDING_DOWN": "The market is in a downtrend with value areas migrating lower",
        "BRACKETING": f"The market is bracketing (overlapping VAs for {result.bracket_days} days)",
        "TRANSITIONING": "The market is transitioning between bracket and trend",
    }
    parts.append(struct_map.get(result.market_structure,
                                "Market structure is developing"))

    # Day type
    parts.append(f"Today classified as {result.day_type} day "
                 f"({result.day_type_conviction} conviction)")

    # Activity
    act_map = {
        "INITIATIVE_BUYING": "with initiative buying (strongest bullish conviction)",
        "INITIATIVE_SELLING": "with initiative selling (strongest bearish conviction)",
        "RESPONSIVE_BUYING": "with responsive buying (reactive to lower prices)",
        "RESPONSIVE_SELLING": "with responsive selling (reactive to higher prices)",
    }
    if result.activity_type in act_map:
        parts.append(act_map[result.activity_type])

    # Directional performance
    if result.directional_performance not in ("NEUTRAL", "MODERATE"):
        parts.append(
            f"Directional performance: {result.directional_performance} "
            f"(attempting {result.attempted_direction})"
        )

    # High-probability signal
    if result.is_3_to_i:
        parts.append(
            f"ALERT: 3-to-I {result.three_to_i_direction} detected (94%/97% probability)"
        )
    if result.is_balance_breakout:
        parts.append(
            f"ALERT: Balance-area breakout {result.balance_breakout_direction}"
        )

    return ". ".join(parts) + "."


# ═══════════════════════════════════════════════════════════════
#  MASTER ENTRY POINT
# ═══════════════════════════════════════════════════════════════

def run_market_profile_analysis(df: pd.DataFrame) -> MarketProfileResult:
    """
    Run complete Dalton Market Profile analysis on daily OHLCV data.

    This function computes all implementable Dalton concepts and returns
    a MarketProfileResult that is blended into the Triple Conviction Engine.

    Requires at least 20 bars of data for meaningful analysis.
    """
    result = MarketProfileResult()

    if df is None or df.empty or len(df) < 20:
        result.summary = "Insufficient data for Market Profile analysis."
        return result

    # ── Data sanitization: drop corrupt rows ──
    # Bad rows have H == L (zero range) or Close outside [Low, High]
    df = df.copy()
    valid = (df["High"] > df["Low"]) & (df["Close"] >= df["Low"]) & (df["Close"] <= df["High"])
    if not valid.iloc[-1]:
        # Last row is corrupt — drop it to prevent garbage analysis
        df = df[valid]
    if len(df) < 20:
        result.summary = "Insufficient valid data for Market Profile analysis."
        return result

    # ── Compute helper statistics ──
    df_recent = df.tail(60) if len(df) >= 60 else df
    atr_series = (df_recent["High"] - df_recent["Low"]).rolling(20).mean()
    atr = float(atr_series.iloc[-1]) if len(atr_series) > 0 and not np.isnan(atr_series.iloc[-1]) else 1.0

    vol_series = df_recent["Volume"].rolling(20).mean()
    avg_vol = float(vol_series.iloc[-1]) if len(vol_series) > 0 and not np.isnan(vol_series.iloc[-1]) else 1.0

    # ── Compute day profiles for last 10 days ──
    profiles = _compute_profiles(df, lookback=10)
    if len(profiles) < 2:
        result.summary = "Not enough profile data."
        return result

    today = profiles[-1]
    prev = profiles[-2]

    # ── [D8, D9] Value Area / POC ──
    result.va_high = today.va_high
    result.va_low = today.va_low
    result.poc = today.poc

    # ── [D12-D17] Day Type ──
    result.day_type, result.day_type_conviction = _classify_day_type(today, atr, avg_vol)

    # ── [D18-D21] Open Type ──
    result.open_type = _classify_open_type(today, prev, atr)

    # ── [D22-D27] Open vs Previous VA ──
    result.open_vs_prev_va, result.open_location = _classify_open_vs_prev(today, prev)

    # ── [D67] Initiative vs Responsive ──
    result.activity_type = _classify_activity(today, prev)

    # ── [D40] Directional Performance ──
    result.attempted_direction, result.directional_performance = \
        _assess_directional_performance(profiles, avg_vol)

    # ── [D39] VA Relationship ──
    result.va_relationship = _compute_va_relationship(today, prev)
    result.va_sequence = _compute_va_sequence(profiles)

    # ── [D41-D42] Market Structure ──
    result.market_structure, result.bracket_days = _detect_market_structure(profiles)

    # ── [D28] One-Timeframing ──
    result.one_timeframing, result.one_tf_days = _detect_one_timeframing(profiles)

    # ── [D61] Poor Highs/Lows ──
    result.is_poor_high, result.is_poor_low, \
        result.consecutive_poor_highs, result.consecutive_poor_lows = \
        _detect_poor_extremes(profiles)

    # ── [D33, D34] Profile Shape ──
    result.profile_shape = _detect_profile_shape(profiles)

    # ── [D48] 3-to-I ──
    result.is_3_to_i, result.three_to_i_direction = _detect_3_to_i(today, avg_vol, atr)

    # ── [D50] Neutral-Extreme ──
    result.is_neutral_extreme, result.neutral_extreme_direction = \
        _detect_neutral_extreme(today, result.day_type)

    # ── [D52] Balance-Area Breakout ──
    result.is_balance_breakout, result.balance_breakout_direction = \
        _detect_balance_breakout(profiles, result.market_structure, atr)

    # ── [D53] Gap Classification ──
    result.gap_type, result.gap_direction, result.gap_size_pct = \
        _classify_gap(profiles, result.market_structure, atr)

    # ── [D58] Overnight Inventory ──
    result.overnight_inventory = _estimate_overnight_inventory(today, prev)

    # ── [D32] Rotation Factor ──
    result.rotation_factor = _compute_rotation_factor(profiles)

    # ── [D9] POC Migration ──
    result.poc_migration = _detect_poc_migration(profiles)

    # ── Cross-Validation Bonus ──
    result.cv_bonus = _compute_cv_bonus(result)

    # ── Observations & Signals ──
    result.observations = _build_observations(result)
    result.dalton_signals = _build_dalton_signals(result)
    result.summary = _build_summary(result)

    return result


# ═══════════════════════════════════════════════════════════════
#  SERIALIZATION
# ═══════════════════════════════════════════════════════════════

def market_profile_to_dict(mp: MarketProfileResult) -> dict:
    """Convert MarketProfileResult to JSON-safe dict for API/dashboard."""
    return {
        "value_area": {
            "va_high": round(mp.va_high, 2),
            "va_low": round(mp.va_low, 2),
            "poc": round(mp.poc, 2),
        },
        "day_type": {
            "type": mp.day_type,
            "conviction": mp.day_type_conviction,
        },
        "open_type": mp.open_type,
        "open_vs_prev": {
            "position": mp.open_vs_prev_va,
            "location": mp.open_location,
        },
        "activity": mp.activity_type,
        "directional_performance": {
            "direction": mp.attempted_direction,
            "rating": mp.directional_performance,
        },
        "market_structure": {
            "type": mp.market_structure,
            "bracket_days": mp.bracket_days,
        },
        "one_timeframing": {
            "direction": mp.one_timeframing,
            "days": mp.one_tf_days,
        },
        "poor_extremes": {
            "poor_high": bool(mp.is_poor_high),
            "poor_low": bool(mp.is_poor_low),
            "consecutive_poor_highs": int(mp.consecutive_poor_highs),
            "consecutive_poor_lows": int(mp.consecutive_poor_lows),
        },
        "profile_shape": mp.profile_shape,
        "high_probability": {
            "three_to_i": {
                "active": bool(mp.is_3_to_i),
                "direction": mp.three_to_i_direction,
            },
            "neutral_extreme": {
                "active": bool(mp.is_neutral_extreme),
                "direction": mp.neutral_extreme_direction,
            },
            "balance_breakout": {
                "active": bool(mp.is_balance_breakout),
                "direction": mp.balance_breakout_direction,
            },
        },
        "gap": {
            "type": mp.gap_type,
            "direction": mp.gap_direction,
            "size_pct": round(mp.gap_size_pct, 3),
        },
        "overnight_inventory": mp.overnight_inventory,
        "rotation_factor": int(mp.rotation_factor),
        "poc_migration": mp.poc_migration,
        "va_sequence": mp.va_sequence,
        "scoring": {
            "cv_bonus": round(mp.cv_bonus, 1),
        },
        "dalton_signals": mp.dalton_signals,
        "observations": mp.observations,
        "summary": mp.summary,
    }
