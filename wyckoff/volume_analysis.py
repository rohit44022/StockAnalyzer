"""
wyckoff/volume_analysis.py — Weis Wave & Effort-vs-Result Analysis
===================================================================

TRUTHFULNESS AUDIT
──────────────────
Source Book: David H. Weis, "Trades About to Happen" (Wiley, 2013)

Weis teaches reading price-volume relationships visually, bar by bar.
The concepts here (waves, effort vs result, shortening, absorption)
are ALL from the book. The ALGORITHMIC IMPLEMENTATION — grouping bars
into waves, summing volume, computing ratios — is our quantification
of Weis's visual bar-reading method.

Core Weis Concept (PARAPHRASE, not direct quote):
  "The market tells its own story through the relationship between
   price spread and volume. When effort (volume) doesn't match
   result (price movement), the market is being deceptive."

  [PARAPHRASE] Weis teaches this principle throughout Ch. 4 (bar reading)
  and Ch. 8-10 (chart studies and wave analysis).

This module implements:
  1. Weis Wave computation — [WEIS concept, our algorithm]
  2. Effort vs Result analysis — [WEIS Ch. 2-3]
  3. Volume character detection — [WEIS Ch. 3-5]
  4. Shortening of thrust — [WEIS Ch. 4]
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from typing import List, Tuple
from dataclasses import dataclass, field

from wyckoff.config import (
    VOLUME_SPIKE_MULTIPLIER,
    VOLUME_CLIMAX_MULTIPLIER,
    VOLUME_DRYUP_FRACTION,
    VOLUME_AVG_PERIOD,
    WAVE_MIN_BARS,
    WAVE_LOOKBACK,
    SHORTENING_THRESHOLD,
    NARROW_SPREAD_PERCENTILE,
    WIDE_SPREAD_PERCENTILE,
    SPREAD_LOOKBACK,
)


# ═══════════════════════════════════════════════════════════════
#  DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════

@dataclass
class WeisWave:
    """A single Weis wave — a directional move with cumulative volume."""
    direction: str          # "UP" or "DOWN"
    start_idx: int          # Index where this wave started
    end_idx: int            # Index where this wave ended
    bars: int               # Number of bars in the wave
    price_move: float       # Absolute price change (high-low of entire wave)
    cum_volume: float       # Total volume during this wave
    start_price: float      # Price at wave start
    end_price: float        # Price at wave end


@dataclass
class EffortResult:
    """Effort vs Result analysis for a single bar or period."""
    bar_idx: int
    spread: float           # High - Low (price range)
    volume: float           # Volume on this bar
    close_position: float   # Where close sits in the bar: 0=low, 1=high
    effort_result: str      # "NORMAL" | "ABSORPTION" | "NO_DEMAND" | "NO_SUPPLY" | "CLIMAX_UP" | "CLIMAX_DOWN"
    description: str        # Human-readable explanation


@dataclass
class VolumeCharacter:
    """Overall volume character assessment."""
    status: str             # "CLIMAX" | "SPIKE" | "ABOVE_AVG" | "NORMAL" | "DRYUP"
    ratio: float            # Current volume / average volume
    trend: str              # "INCREASING" | "DECREASING" | "FLAT"
    description: str


# ═══════════════════════════════════════════════════════════════
#  WEIS WAVE COMPUTATION
# ═══════════════════════════════════════════════════════════════

def compute_weis_waves(df: pd.DataFrame, lookback: int = 0) -> List[WeisWave]:
    """
    Compute Weis Waves from OHLCV data.

    [WEIS] A Weis wave groups consecutive bars moving in the same direction
    and sums their volume. By comparing cumulative volume on UP waves vs
    DOWN waves, we see where the real effort is.

    Method:
      - An UP bar: Close > Close[prior] (or Close > Open if first bar)
      - A DOWN bar: Close < Close[prior]
      - Group consecutive same-direction bars into waves
      - Sum volume for each wave
      - Track price extent (highest high - lowest low) for each wave

    Returns:
        List of WeisWave objects, most recent last.
    """
    if df is None or len(df) < 5:
        return []

    closes = df["Close"].values
    highs = df["High"].values
    lows = df["Low"].values
    volumes = df["Volume"].values
    n = len(df)

    # Determine direction for each bar
    directions = []
    for i in range(n):
        if i == 0:
            directions.append("UP" if closes[i] >= df["Open"].values[i] else "DOWN")
        else:
            if closes[i] > closes[i - 1]:
                directions.append("UP")
            elif closes[i] < closes[i - 1]:
                directions.append("DOWN")
            else:
                # Unchanged — inherit prior direction
                directions.append(directions[-1] if directions else "UP")

    # Build waves by grouping consecutive same-direction bars
    waves: List[WeisWave] = []
    wave_start = 0
    current_dir = directions[0]

    for i in range(1, n):
        if directions[i] != current_dir or i == n - 1:
            end = i if directions[i] != current_dir else i + 1
            actual_end = min(end, n)
            seg_highs = highs[wave_start:actual_end]
            seg_lows = lows[wave_start:actual_end]
            seg_volumes = volumes[wave_start:actual_end]
            bars_count = actual_end - wave_start

            if bars_count >= WAVE_MIN_BARS:
                waves.append(WeisWave(
                    direction=current_dir,
                    start_idx=wave_start,
                    end_idx=actual_end - 1,
                    bars=bars_count,
                    price_move=float(np.max(seg_highs) - np.min(seg_lows)),
                    cum_volume=float(np.sum(seg_volumes)),
                    start_price=float(closes[wave_start]),
                    end_price=float(closes[actual_end - 1]),
                ))

            if directions[i] != current_dir:
                wave_start = i
                current_dir = directions[i]

    # Return only recent waves if lookback specified
    if lookback > 0 and len(waves) > lookback:
        waves = waves[-lookback:]

    return waves


def detect_shortening_of_thrust(waves: List[WeisWave]) -> dict:
    """
    [WEIS] Shortening of Thrust — key wave exhaustion signal.

    Source: Weis — Ch. 9-10, "Weis Wave" methodology.
      Weis explicitly discusses this concept: when each successive
      push in the same direction covers less ground, the move is
      losing momentum. He emphasizes this is especially significant
      when volume INCREASES but price progress DECREASES (effort
      without result = absorption by the opposing side).

    [PARAPHRASE] "When each successive push covers less ground, the
     move is running out of steam." Weis shows this visually on
     wave charts. He does not give a numeric ratio threshold.

    NOTE: Calling this "Wyckoff's most reliable exhaustion signal"
    was our characterization. Weis treats it as one of several
    important wave signals. [CORRECTED]

    Our algorithmic rules:
      1. Last 3+ waves in same direction — [WEIS]
      2. Each successive wave covers less distance — [WEIS]
      3. Especially powerful if volume increases — [WEIS]
      4. Threshold: <65% ratio = shortening — [CALIBRATION]

    Returns:
        dict with shortening detection results
    """
    if len(waves) < 4:
        return {"detected": False, "direction": None, "description": "Insufficient waves"}

    # Separate up and down waves
    up_waves = [w for w in waves if w.direction == "UP"]
    down_waves = [w for w in waves if w.direction == "DOWN"]

    result = {"detected": False, "direction": None, "waves_analyzed": 0,
              "description": "", "severity": "NONE"}

    # Check up-wave shortening (bearish signal)
    if len(up_waves) >= 3:
        recent_up = up_waves[-3:]
        moves = [w.price_move for w in recent_up]
        if moves[0] > moves[1] > moves[2]:
            # Each push up covers less ground
            ratio = moves[2] / moves[0] if moves[0] > 0 else 1
            if ratio < SHORTENING_THRESHOLD:
                vols = [w.cum_volume for w in recent_up]
                vol_increasing = vols[2] > vols[0]
                severity = "STRONG" if vol_increasing else "MODERATE"
                result = {
                    "detected": True,
                    "direction": "UP_EXHAUSTION",
                    "waves_analyzed": 3,
                    "severity": severity,
                    "thrust_ratio": round(ratio, 3),
                    "volume_increasing": vol_increasing,
                    "description": (
                        f"Shortening of upward thrust detected. "
                        f"Last 3 up-waves covered decreasing distance "
                        f"(ratio: {ratio:.1%} of first wave). "
                        + ("Volume is INCREASING despite less progress — "
                           "smart money is absorbing buying. Bearish." if vol_increasing
                           else "Buyers are losing momentum. Watch for reversal.")
                    ),
                }
                return result

    # Check down-wave shortening (bullish signal)
    if len(down_waves) >= 3:
        recent_dn = down_waves[-3:]
        moves = [w.price_move for w in recent_dn]
        if moves[0] > moves[1] > moves[2]:
            ratio = moves[2] / moves[0] if moves[0] > 0 else 1
            if ratio < SHORTENING_THRESHOLD:
                vols = [w.cum_volume for w in recent_dn]
                vol_increasing = vols[2] > vols[0]
                severity = "STRONG" if vol_increasing else "MODERATE"
                result = {
                    "detected": True,
                    "direction": "DOWN_EXHAUSTION",
                    "waves_analyzed": 3,
                    "severity": severity,
                    "thrust_ratio": round(ratio, 3),
                    "volume_increasing": vol_increasing,
                    "description": (
                        f"Shortening of downward thrust detected. "
                        f"Last 3 down-waves covered decreasing distance "
                        f"(ratio: {ratio:.1%} of first wave). "
                        + ("Volume is INCREASING despite less decline — "
                           "smart money is absorbing selling. Bullish." if vol_increasing
                           else "Sellers are losing power. Watch for bottom.")
                    ),
                }

    return result


def compare_wave_volumes(waves: List[WeisWave]) -> dict:
    """
    [WEIS] Compare cumulative volume on up-waves vs down-waves.

    Source: Weis — Ch. 9-10, wave volume comparison.
      Weis teaches comparing cumulative volume on up-waves versus
      down-waves to determine whether demand or supply dominates.
      This is a CORE Weis concept throughout the book.

    [PARAPHRASE] "If up-waves carry more volume than down-waves,
     demand exceeds supply. If down-waves carry more volume, supply
     exceeds demand."

    NOTE: The specific ratio thresholds (1.5×, 1.15×, etc.) for
    categorization into DEMAND_DOMINANT vs SLIGHT_DEMAND, etc.,
    are [CALIBRATION]. Weis makes this comparison visually.

    Returns:
        dict with volume balance assessment
    """
    if len(waves) < 4:
        return {"balance": "INSUFFICIENT", "ratio": 1.0, "description": "Need more waves"}

    recent = waves[-WAVE_LOOKBACK:] if len(waves) > WAVE_LOOKBACK else waves
    up_vol = sum(w.cum_volume for w in recent if w.direction == "UP") or 1
    dn_vol = sum(w.cum_volume for w in recent if w.direction == "DOWN") or 1

    ratio = up_vol / dn_vol

    if ratio > 1.5:
        balance = "DEMAND_DOMINANT"
        desc = (f"Up-wave volume is {ratio:.1f}× down-wave volume. "
                "Buyers are clearly more aggressive — demand exceeds supply. Bullish.")
    elif ratio > 1.15:
        balance = "SLIGHT_DEMAND"
        desc = (f"Up-wave volume slightly exceeds down-wave ({ratio:.1f}×). "
                "Buyers have a slight edge. Mildly bullish.")
    elif ratio < 0.67:
        balance = "SUPPLY_DOMINANT"
        desc = (f"Down-wave volume is {1/ratio:.1f}× up-wave volume. "
                "Sellers are clearly more aggressive — supply exceeds demand. Bearish.")
    elif ratio < 0.87:
        balance = "SLIGHT_SUPPLY"
        desc = (f"Down-wave volume slightly exceeds up-wave ({1/ratio:.1f}×). "
                "Sellers have a slight edge. Mildly bearish.")
    else:
        balance = "BALANCED"
        desc = "Up and down-wave volumes are roughly equal. No clear dominance."

    # [WEIS Ch. 9-10] Wave duration comparison — time is the third element
    up_duration = sum(w.bars for w in recent if w.direction == "UP") or 1
    dn_duration = sum(w.bars for w in recent if w.direction == "DOWN") or 1
    duration_ratio = up_duration / dn_duration
    if duration_ratio > 1.3:
        duration_note = "Up-waves last longer than down-waves — buyers are patient and persistent."
    elif duration_ratio < 0.77:
        duration_note = "Down-waves last longer than up-waves — sellers are patient and persistent."
    else:
        duration_note = "Wave durations are roughly balanced."

    return {
        "balance": balance,
        "ratio": round(ratio, 2),
        "up_volume": int(up_vol),
        "down_volume": int(dn_vol),
        "up_duration": up_duration,
        "down_duration": dn_duration,
        "duration_ratio": round(duration_ratio, 2),
        "duration_note": duration_note,
        "description": desc,
    }


# ═══════════════════════════════════════════════════════════════
#  EFFORT VS RESULT (Volume-Spread Analysis)
# ═══════════════════════════════════════════════════════════════

def analyze_effort_vs_result(df: pd.DataFrame, lookback: int = 5) -> List[EffortResult]:
    """
    [WEIS] Effort vs Result — central Wyckoff volume-spread analysis.

    Source: Weis — Ch. 4 (bar-by-bar reading), "Effort vs Result."
      This is the HEART of Weis's teaching. Volume is effort, price
      spread is result. Weis reads each bar asking: "Does the effort
      match the result?"

    [PARAPHRASE] "Volume is effort. Price spread is result. When they
     don't match, somebody is lying." This captures Weis's core idea;
     the exact words and "lying" metaphor are ours.

    Classification (concepts from Weis, categories named by us):
      NORMAL:      Volume and spread proportional — genuine move [WEIS]
      ABSORPTION:  High volume + narrow spread — smart money absorbing [WEIS Ch. 4]
      NO_DEMAND:   Low volume + narrow spread on up bar [WEIS Ch. 4]
      NO_SUPPLY:   Low volume + narrow spread on down bar [WEIS Ch. 4]
      CLIMAX_UP:   Extreme vol + wide spread up + close near low [WEIS Ch. 4, 8]
      CLIMAX_DOWN: Extreme vol + wide spread down + close near high [WEIS Ch. 4, 8]

    NOTE: All threshold values (percentiles, multipliers) are [CALIBRATION].
    Weis makes these judgments visually, not with computed percentiles.

    Returns:
        List of EffortResult for the last `lookback` bars
    """
    if df is None or len(df) < SPREAD_LOOKBACK:
        return []

    spreads = (df["High"] - df["Low"]).values
    volumes = df["Volume"].values
    closes = df["Close"].values
    opens = df["Open"].values
    highs = df["High"].values
    lows = df["Low"].values

    # Compute reference thresholds
    recent_spreads = spreads[-SPREAD_LOOKBACK:]
    narrow_threshold = np.percentile(recent_spreads, NARROW_SPREAD_PERCENTILE)
    wide_threshold = np.percentile(recent_spreads, WIDE_SPREAD_PERCENTILE)

    vol_avg = np.mean(volumes[-VOLUME_AVG_PERIOD:]) if len(volumes) >= VOLUME_AVG_PERIOD else np.mean(volumes)

    results = []
    n = len(df)
    start_idx = max(0, n - lookback)

    for i in range(start_idx, n):
        spread = spreads[i]
        vol = volumes[i]
        close_pos = (closes[i] - lows[i]) / spread if spread > 0 else 0.5
        is_up_bar = closes[i] > opens[i]
        vol_ratio = vol / vol_avg if vol_avg > 0 else 1.0

        # Classify effort vs result
        if vol_ratio >= VOLUME_CLIMAX_MULTIPLIER and spread >= wide_threshold:
            if is_up_bar and close_pos < 0.4:
                er = "CLIMAX_UP"
                desc = (f"BUYING CLIMAX: Extreme volume ({vol_ratio:.1f}× avg) with wide spread "
                        f"but close near the low ({close_pos:.0%}). Smart money is selling into "
                        f"the buying frenzy. This often marks a significant top.")
            elif not is_up_bar and close_pos > 0.6:
                er = "CLIMAX_DOWN"
                desc = (f"SELLING CLIMAX: Extreme volume ({vol_ratio:.1f}× avg) with wide spread "
                        f"but close near the high ({close_pos:.0%}). Smart money is buying into "
                        f"the panic. This often marks a significant bottom.")
            else:
                er = "NORMAL"
                desc = f"High volume ({vol_ratio:.1f}× avg) with wide spread — genuine strong move."
        elif vol_ratio >= VOLUME_SPIKE_MULTIPLIER and spread <= narrow_threshold:
            er = "ABSORPTION"
            desc = (f"ABSORPTION: High volume ({vol_ratio:.1f}× avg) but narrow spread. "
                    f"Somebody is absorbing all the {'selling' if is_up_bar else 'buying'} pressure. "
                    f"Smart money is quietly accumulating/distributing.")
        elif vol_ratio < VOLUME_DRYUP_FRACTION and spread <= narrow_threshold:
            if is_up_bar:
                er = "NO_DEMAND"
                desc = ("NO DEMAND: Low volume with narrow up bar. Nobody wants to buy here. "
                        "Any rally attempt is weak and likely to fail.")
            else:
                er = "NO_SUPPLY"
                desc = ("NO SUPPLY: Low volume with narrow down bar. Nobody wants to sell here. "
                        "Selling pressure has dried up — potential support.")
        else:
            er = "NORMAL"
            desc = f"Normal volume-spread relationship ({vol_ratio:.1f}× avg, spread normal)."

        results.append(EffortResult(
            bar_idx=i,
            spread=float(spread),
            volume=float(vol),
            close_position=float(close_pos),
            effort_result=er,
            description=desc,
        ))

    return results


# ═══════════════════════════════════════════════════════════════
#  VOLUME CHARACTER ASSESSMENT
# ═══════════════════════════════════════════════════════════════

def assess_volume_character(df: pd.DataFrame) -> VolumeCharacter:
    """
    [WEIS] Assess overall volume character of recent trading.

    Source: Weis — Ch. 4, general volume assessment.
      Weis constantly assesses whether volume is "above normal,"
      "climactic," "dried up," etc. This function quantifies that
      qualitative assessment.

    [INFERRED] The specific categories (CLIMAX/SPIKE/ABOVE_AVG/
    NORMAL/DRYUP) and the volume trend computation (first-half vs
    second-half of last 10 bars) are our algorithmic formalization
    of Weis's visual volume reading. The underlying concepts are
    from Weis; the categorization system is ours.

    Looks at:
      1. Current volume vs average (spike/climax/normal/dry-up)
      2. Volume trend over last 10 bars (increasing/decreasing/flat)
    """
    if df is None or len(df) < 10:
        return VolumeCharacter("UNKNOWN", 0, "UNKNOWN", "Insufficient data")

    volumes = df["Volume"].values
    vol_avg = np.mean(volumes[-VOLUME_AVG_PERIOD:]) if len(volumes) >= VOLUME_AVG_PERIOD else np.mean(volumes)
    current_vol = volumes[-1]
    ratio = current_vol / vol_avg if vol_avg > 0 else 1.0

    # Status
    if ratio >= VOLUME_CLIMAX_MULTIPLIER:
        status = "CLIMAX"
    elif ratio >= VOLUME_SPIKE_MULTIPLIER:
        status = "SPIKE"
    elif ratio >= 1.0:
        status = "ABOVE_AVG"
    elif ratio >= VOLUME_DRYUP_FRACTION:
        status = "NORMAL"
    else:
        status = "DRYUP"

    # Volume trend (last 10 bars)
    recent_10 = volumes[-10:]
    first_half = np.mean(recent_10[:5])
    second_half = np.mean(recent_10[5:])
    if second_half > first_half * 1.2:
        trend = "INCREASING"
    elif second_half < first_half * 0.8:
        trend = "DECREASING"
    else:
        trend = "FLAT"

    desc = {
        "CLIMAX": f"CLIMAX volume ({ratio:.1f}× average) — potential selling/buying climax forming.",
        "SPIKE": f"SPIKE volume ({ratio:.1f}× average) — significant institutional activity.",
        "ABOVE_AVG": f"Above average volume ({ratio:.1f}× avg) — healthy participation.",
        "NORMAL": f"Normal volume ({ratio:.1f}× avg) — no unusual activity.",
        "DRYUP": f"DRIED UP volume ({ratio:.1f}× avg) — very low interest at this price. A breakout move is building.",
    }.get(status, "Unknown volume status")

    return VolumeCharacter(status=status, ratio=round(ratio, 2), trend=trend, description=desc)
