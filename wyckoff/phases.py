"""
wyckoff/phases.py — Wyckoff Market Phase & Event Detection
============================================================

TRUTHFULNESS AUDIT
──────────────────
Source Book: David H. Weis, "Trades About to Happen" (Wiley, 2013)

Weis teaches Richard Wyckoff's method of reading price and volume.
The core cycle (Accumulation → Markup → Distribution → Markdown)
is a FOUNDATIONAL Wyckoff concept that Weis covers throughout
the book (Chapters 1-11). The events detected here (SC, BC, Spring,
Upthrust, SOS, SOW, Test) are ALL explicitly discussed by Weis.

IMPORTANT:
- Weis reads bars VISUALLY and in CONTEXT. He does not give
  algorithmic detection rules with numeric thresholds.
- All numeric parameters (spread percentiles, volume multiples,
  close-position thresholds) are [CALIBRATION] — our quantification
  of Weis's qualitative concepts. See config.py for details.
- Quotes attributed to "Weis" below are PARAPHRASES of his teaching
  concepts, not direct verbatim quotations. Marked [PARAPHRASE].
- Sub-phases (EARLY/MIDDLE/CONFIRMED/LATE) are [INFERRED] from
  Weis's descriptions of how phases progress, but he does not
  name them this way.

Wyckoff's Market Cycle (as taught by Weis):
  ┌─────────────┐     ┌──────────┐     ┌──────────────┐     ┌──────────┐
  │ ACCUMULATION │ ──→ │  MARKUP  │ ──→ │ DISTRIBUTION │ ──→ │ MARKDOWN │
  │ (Smart buy)  │     │ (Trend ↑)│     │ (Smart sell) │     │ (Trend ↓)│
  └─────────────┘     └──────────┘     └──────────────┘     └──────────┘
         ↑                                                        │
         └────────────────────────────────────────────────────────┘

Each phase has specific volume-price signatures that tell you
WHERE you are in the cycle.
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from wyckoff.config import (
    RANGE_LOOKBACK, RANGE_THRESHOLD_PCT, PHASE_MIN_BARS,
    SPRING_MAX_PENETRATION_PCT, SPRING_MIN_REVERSAL_PCT,
    SPRING_VOLUME_MAX_RATIO,
    UPTHRUST_MAX_PENETRATION_PCT, UPTHRUST_MIN_REVERSAL_PCT,
    SC_MIN_SPREAD_PERCENTILE, SC_MIN_VOLUME_MULTIPLIER, SC_CLOSE_POSITION_THRESHOLD,
    BC_MIN_SPREAD_PERCENTILE, BC_MIN_VOLUME_MULTIPLIER, BC_CLOSE_POSITION_THRESHOLD,
    SOS_MIN_SPREAD_PERCENTILE, SOS_MIN_VOLUME_RATIO,
    SOW_MIN_SPREAD_PERCENTILE, SOW_MIN_VOLUME_RATIO,
    TEST_VOLUME_RATIO_MAX, TEST_PRICE_PROXIMITY_PCT,
    VOLUME_AVG_PERIOD,
)


# ═══════════════════════════════════════════════════════════════
#  DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════

@dataclass
class WyckoffEvent:
    """A detected Wyckoff event (Spring, Upthrust, Climax, etc.)."""
    event_type: str         # SC, BC, SPRING, UPTHRUST, SOS, SOW, TEST, AR, ST, LPS, LPSY
    bar_index: int          # Where in the DataFrame this occurred
    confidence: float       # 0-100 confidence in the detection
    price: float            # Price at event
    volume_ratio: float     # Volume / average volume
    description: str        # Plain-language explanation
    bullish: bool           # True if bullish event, False if bearish


@dataclass
class WyckoffPhase:
    """Detected Wyckoff market phase."""
    phase: str              # ACCUMULATION | MARKUP | DISTRIBUTION | MARKDOWN | RANGING | UNKNOWN
    sub_phase: str          # Early / Middle / Late / Confirmed
    confidence: float       # 0-100
    events: List[WyckoffEvent] = field(default_factory=list)
    support: float = 0.0    # Trading range support level
    resistance: float = 0.0 # Trading range resistance level
    description: str = ""   # Plain-language explanation


# ═══════════════════════════════════════════════════════════════
#  HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def _vol_avg(volumes: np.ndarray, period: int = VOLUME_AVG_PERIOD) -> float:
    """Compute average volume over the given period."""
    if len(volumes) < period:
        return float(np.mean(volumes)) if len(volumes) > 0 else 1.0
    return float(np.mean(volumes[-period:]))


def _spread_percentile(spreads: np.ndarray, current_spread: float, lookback: int = 50) -> float:
    """What percentile is the current spread in recent history? (0-100)"""
    recent = spreads[-lookback:] if len(spreads) >= lookback else spreads
    if len(recent) == 0:
        return 50.0
    return float(np.searchsorted(np.sort(recent), current_spread) / len(recent) * 100)


def _close_position(high: float, low: float, close: float) -> float:
    """Where does close sit within the bar? 0=low, 1=high."""
    rng = high - low
    if rng <= 0:
        return 0.5
    return (close - low) / rng


def _is_in_range(df: pd.DataFrame, lookback: int = RANGE_LOOKBACK,
                 threshold: float = RANGE_THRESHOLD_PCT) -> Tuple[bool, float, float]:
    """
    [WEIS] Detect if price is in a trading range.

    A trading range exists when:
      - Price has been oscillating within a relatively narrow band
      - The band width is < threshold% of the midpoint
      - This is the breeding ground for Wyckoff Accumulation/Distribution
    """
    if len(df) < lookback:
        return False, 0, 0

    recent = df.tail(lookback)
    high = float(recent["High"].max())
    low = float(recent["Low"].min())
    mid = (high + low) / 2

    if mid <= 0:
        return False, 0, 0

    range_pct = (high - low) / mid
    return range_pct <= threshold, low, high


# ═══════════════════════════════════════════════════════════════
#  WYCKOFF EVENT DETECTION
# ═══════════════════════════════════════════════════════════════

def detect_selling_climax(df: pd.DataFrame) -> Optional[WyckoffEvent]:
    """
    [WEIS] Selling Climax (SC) — potential end of markdown.

    Source: Weis — Ch. 4 (bar reading), Ch. 8 (chart studies).
      Weis teaches that a SC shows panicked selling being absorbed by
      informed buyers. He describes it as a wide-spread down bar with
      heavy volume where the close recovers toward the high of the bar.

    [PARAPHRASE] "The SC is characterized by widening spread, increasing
     volume, and a close recovering toward the top of the bar."

    Our algorithmic rules (all thresholds are [CALIBRATION]):
      1. Wide spread bar (top 20% of recent spreads) — [CALIBRATION]
      2. Very high volume (≥2× average) — [CALIBRATION]
      3. Close in upper 40% of bar (buying coming in) — [CALIBRATION]
      4. Prior bars showed declining prices (context of downtrend) — [WEIS]
    """
    if len(df) < 20:
        return None

    closes = df["Close"].values
    highs = df["High"].values
    lows = df["Low"].values
    opens = df["Open"].values
    volumes = df["Volume"].values
    spreads = highs - lows
    vol_avg = _vol_avg(volumes)

    # Check last 3 bars for SC pattern
    for offset in range(3):
        i = len(df) - 1 - offset
        if i < 10:
            break

        spread = spreads[i]
        sp_pct = _spread_percentile(spreads, spread)
        vol_ratio = volumes[i] / vol_avg if vol_avg > 0 else 0
        close_pos = _close_position(highs[i], lows[i], closes[i])

        # Context: must be after some decline
        if i >= 5:
            recent_trend = closes[i] - closes[i - 5]
            in_decline = recent_trend < 0
        else:
            in_decline = True

        if (sp_pct >= SC_MIN_SPREAD_PERCENTILE and
                vol_ratio >= SC_MIN_VOLUME_MULTIPLIER and
                close_pos >= (1 - SC_CLOSE_POSITION_THRESHOLD) and
                in_decline):
            conf = min(100, (sp_pct / 100 * 40) + (vol_ratio / 4 * 30) + (close_pos * 30))
            return WyckoffEvent(
                event_type="SC",
                bar_index=i,
                confidence=round(conf),
                price=float(closes[i]),
                volume_ratio=round(vol_ratio, 2),
                bullish=True,
                description=(
                    f"SELLING CLIMAX detected: Wide spread ({sp_pct:.0f}th percentile), "
                    f"extreme volume ({vol_ratio:.1f}× avg), close near high ({close_pos:.0%}). "
                    f"Panicked sellers are being absorbed by smart money. "
                    f"This often marks the END of a decline."
                ),
            )

    return None


def detect_buying_climax(df: pd.DataFrame) -> Optional[WyckoffEvent]:
    """
    [WEIS] Buying Climax (BC) — potential end of markup.

    Source: Weis — Ch. 4 (bar reading), Ch. 8 (chart studies).
      Mirror of Selling Climax. Wide spread up bar with extreme volume
      but close near the low — euphoric buyers are being sold to by
      smart money.

    Our algorithmic rules (all thresholds are [CALIBRATION]):
      1. Wide spread bar (top 20% of recent spreads)
      2. Very high volume (≥2× average)
      3. Close in lower 40% of bar (selling into strength)
      4. Prior bars showed advancing prices (context of uptrend)
    """
    if len(df) < 20:
        return None

    closes = df["Close"].values
    highs = df["High"].values
    lows = df["Low"].values
    volumes = df["Volume"].values
    spreads = highs - lows
    vol_avg = _vol_avg(volumes)

    for offset in range(3):
        i = len(df) - 1 - offset
        if i < 10:
            break

        spread = spreads[i]
        sp_pct = _spread_percentile(spreads, spread)
        vol_ratio = volumes[i] / vol_avg if vol_avg > 0 else 0
        close_pos = _close_position(highs[i], lows[i], closes[i])

        if i >= 5:
            recent_trend = closes[i] - closes[i - 5]
            in_advance = recent_trend > 0
        else:
            in_advance = True

        if (sp_pct >= BC_MIN_SPREAD_PERCENTILE and
                vol_ratio >= BC_MIN_VOLUME_MULTIPLIER and
                close_pos <= BC_CLOSE_POSITION_THRESHOLD and
                in_advance):
            conf = min(100, (sp_pct / 100 * 40) + (vol_ratio / 4 * 30) + ((1 - close_pos) * 30))
            return WyckoffEvent(
                event_type="BC",
                bar_index=i,
                confidence=round(conf),
                price=float(closes[i]),
                volume_ratio=round(vol_ratio, 2),
                bullish=False,
                description=(
                    f"BUYING CLIMAX detected: Wide spread ({sp_pct:.0f}th percentile), "
                    f"extreme volume ({vol_ratio:.1f}× avg), close near low ({close_pos:.0%}). "
                    f"Euphoric buyers are being sold to by smart money. "
                    f"This often marks the END of an advance."
                ),
            )

    return None


def detect_spring(df: pd.DataFrame, support: float, dominant_trend: str = "FLAT") -> Optional[WyckoffEvent]:
    """
    [WEIS] Spring — high-probability Wyckoff buy signal.

    Source: Weis — Ch. 5, "The Spring" / "Shakeout."
      Weis teaches that a spring is a break below the low of a
      trading range that quickly reverses. Volume should be low,
      proving there is no real supply.

    [WEIS Ch. 5] "Springs in an UPTREND have the highest success rate."
      Weis emphasizes trend context: springs within a larger uptrend
      (pullback to support) are far more reliable than springs at the
      bottom of a downtrend where supply may still overwhelm.

    Our algorithmic rules:
      1. Price breaks BELOW support level — [WEIS]
      2. Penetration is small (< 3% of support) — [CALIBRATION]
      3. Price reverses and closes back near/above support — [WEIS]
      4. Volume on the break is LOW (< 1.2× average) — [WEIS concept, CALIBRATION threshold]
      5. Trend context adjusts confidence — [WEIS Ch. 5]

    [INFERRED — CONFLUENCE with Brooks]
    Al Brooks calls this a "failed breakout below range" — the strongest
    reversal pattern.
    """
    if len(df) < 10 or support <= 0:
        return None

    volumes = df["Volume"].values
    vol_avg = _vol_avg(volumes)

    # Check last 5 bars
    for offset in range(5):
        i = len(df) - 1 - offset
        if i < 2:
            break

        low = float(df["Low"].values[i])
        close = float(df["Close"].values[i])
        high = float(df["High"].values[i])
        vol_ratio = volumes[i] / vol_avg if vol_avg > 0 else 1.0

        penetration = (support - low) / support if support > 0 else 0

        # Did price break below support?
        if low < support and penetration <= SPRING_MAX_PENETRATION_PCT:
            # Did it reverse? (close back near or above support)
            reversal = (close - low) / support if support > 0 else 0
            if reversal >= SPRING_MIN_REVERSAL_PCT and close >= support * 0.99:
                # Low volume? (the key Weis requirement)
                low_vol = vol_ratio <= SPRING_VOLUME_MAX_RATIO
                conf = 40  # Base confidence for price pattern
                if low_vol:
                    conf += 35  # Low volume = no real supply = strong spring
                else:
                    conf += 10  # High volume spring is weaker (could be genuine break)
                if close > support:
                    conf += 15  # Closed back above support = strongest spring
                else:
                    conf += 5

                # [WEIS Ch. 5] Trend context: springs in uptrends succeed more
                trend_note = ""
                if dominant_trend == "UP":
                    conf += 10  # Spring within uptrend = highest probability
                    trend_note = " Trend context: UPTREND — springs here have the highest success rate."
                elif dominant_trend == "DOWN":
                    conf -= 10  # Spring at bottom of downtrend = riskier
                    trend_note = " Trend context: DOWNTREND — spring is riskier, supply may still overwhelm."

                conf = max(10, min(100, conf))
                return WyckoffEvent(
                    event_type="SPRING",
                    bar_index=i,
                    confidence=round(conf),
                    price=float(close),
                    volume_ratio=round(vol_ratio, 2),
                    bullish=True,
                    description=(
                        f"SPRING detected: Price broke below support (₹{support:.2f}) by "
                        f"{penetration:.1%} then reversed. "
                        + (f"Volume was LOW ({vol_ratio:.1f}× avg) — no real sellers, "
                           f"just a shakeout of weak hands. High-probability buy setup."
                           if low_vol
                           else f"Volume was elevated ({vol_ratio:.1f}× avg) — the spring "
                                f"is less reliable. Watch for a successful test on lower volume.")
                        + trend_note
                    ),
                )

    return None


def detect_upthrust(df: pd.DataFrame, resistance: float, dominant_trend: str = "FLAT") -> Optional[WyckoffEvent]:
    """
    [WEIS] Upthrust — high-probability Wyckoff sell signal.

    Source: Weis — Ch. 6, "The Upthrust."
      Mirror of Spring. Price breaks above resistance on low volume
      then reverses — traps breakout buyers.

    [WEIS Ch. 6] "Upthrusts in a DOWNTREND have the highest success rate."
      Weis emphasizes trend context: upthrusts within a larger downtrend
      (rally to resistance) are far more reliable than upthrusts at the
      top of an uptrend where demand may still overwhelm.

    [INFERRED — CONFLUENCE with Brooks]
    Al Brooks calls this a "failed breakout above range."
    """
    if len(df) < 10 or resistance <= 0:
        return None

    volumes = df["Volume"].values
    vol_avg = _vol_avg(volumes)

    for offset in range(5):
        i = len(df) - 1 - offset
        if i < 2:
            break

        high = float(df["High"].values[i])
        close = float(df["Close"].values[i])
        low = float(df["Low"].values[i])
        vol_ratio = volumes[i] / vol_avg if vol_avg > 0 else 1.0

        penetration = (high - resistance) / resistance if resistance > 0 else 0

        if high > resistance and penetration <= UPTHRUST_MAX_PENETRATION_PCT:
            reversal = (high - close) / resistance if resistance > 0 else 0
            if reversal >= UPTHRUST_MIN_REVERSAL_PCT and close <= resistance * 1.01:
                low_vol = vol_ratio <= SPRING_VOLUME_MAX_RATIO
                conf = 40
                if low_vol:
                    conf += 35
                else:
                    conf += 10
                if close < resistance:
                    conf += 15
                else:
                    conf += 5

                # [WEIS Ch. 6] Trend context: upthrusts in downtrends succeed more
                trend_note = ""
                if dominant_trend == "DOWN":
                    conf += 10  # Upthrust within downtrend = highest probability
                    trend_note = " Trend context: DOWNTREND — upthrusts here have the highest success rate."
                elif dominant_trend == "UP":
                    conf -= 10  # Upthrust at top of uptrend = riskier
                    trend_note = " Trend context: UPTREND — upthrust is riskier, demand may still overwhelm."

                conf = max(10, min(100, conf))
                return WyckoffEvent(
                    event_type="UPTHRUST",
                    bar_index=i,
                    confidence=round(conf),
                    price=float(close),
                    volume_ratio=round(vol_ratio, 2),
                    bullish=False,
                    description=(
                        f"UPTHRUST detected: Price poked above resistance (₹{resistance:.2f}) "
                        f"by {penetration:.1%} then reversed back. "
                        + (f"Volume was LOW ({vol_ratio:.1f}× avg) — no real buyers, "
                           f"just a trap for breakout chasers. High-probability sell setup."
                           if low_vol
                           else f"Volume was elevated ({vol_ratio:.1f}× avg) — the upthrust "
                                f"is less reliable. Watch for confirmation.")
                        + trend_note
                    ),
                )

    return None


def detect_test(df: pd.DataFrame, reference_price: float,
                reference_volume: float, test_type: str = "SUPPORT") -> Optional[WyckoffEvent]:
    """
    [WEIS] Test of Supply/Demand — confirmation event.

    Source: Weis — Ch. 5, "Secondary Test" (tested after spring).
      Weis teaches that after a spring or selling climax, price must
      come back and test that area. If the test shows LESS volume than
      the original event, it confirms supply/demand has been removed.

    [PARAPHRASE] "After a spring or SC, price returns to test that area.
     If the test shows less volume, supply has been absorbed."

    Our algorithmic rules:
      1. Price returns to within 2% of reference level — [CALIBRATION]
      2. Volume < 75% of reference event volume — [CALIBRATION]
    """
    if len(df) < 5 or reference_price <= 0:
        return None

    volumes = df["Volume"].values
    closes = df["Close"].values
    lows = df["Low"].values
    highs = df["High"].values

    for offset in range(5):
        i = len(df) - 1 - offset
        if i < 0:
            break

        if test_type == "SUPPORT":
            test_price = float(lows[i])
            proximity = abs(test_price - reference_price) / reference_price
        else:
            test_price = float(highs[i])
            proximity = abs(test_price - reference_price) / reference_price

        if proximity <= TEST_PRICE_PROXIMITY_PCT:
            vol_ratio = volumes[i] / reference_volume if reference_volume > 0 else 1.0
            if vol_ratio <= TEST_VOLUME_RATIO_MAX:
                is_bullish = test_type == "SUPPORT"
                conf = min(100, max(30, int((1 - vol_ratio) * 80 + 20)))
                return WyckoffEvent(
                    event_type="TEST",
                    bar_index=i,
                    confidence=conf,
                    price=float(closes[i]),
                    volume_ratio=round(vol_ratio, 2),
                    bullish=is_bullish,
                    description=(
                        f"SUCCESSFUL TEST: Price returned to the "
                        f"{'support' if is_bullish else 'resistance'} area "
                        f"(₹{reference_price:.2f}) with only {vol_ratio:.0%} of "
                        f"the original volume. This confirms {'no supply remains — '
                        'smart money has absorbed it all' if is_bullish else 'no demand remains — '
                        'smart money has distributed'}. "
                        f"{'Bullish confirmation.' if is_bullish else 'Bearish confirmation.'}"
                    ),
                )

    return None


def assess_follow_through(df: pd.DataFrame, event: WyckoffEvent, bars_after: int = 3) -> dict:
    """
    [WEIS Ch. 5-6] Follow-through assessment — "the deciding factor."

    Source: Weis — Ch. 5, 6. After a spring, upthrust, or breakout,
      the NEXT few bars reveal whether the move is genuine. Weis calls
      follow-through "the deciding factor" for whether to act on a setup.

    Checks the bars AFTER the detected event for:
      - Price continuation in the expected direction
      - Volume support (expanding volume = genuine follow-through)
      - Lack of follow-through = the setup failed

    Returns:
        dict with follow_through, quality, description
    """
    n = len(df)
    event_idx = event.bar_index
    end_idx = min(event_idx + bars_after + 1, n)

    if end_idx <= event_idx + 1:
        return {"follow_through": "PENDING", "quality": "UNKNOWN",
                "description": "Not enough bars after event to assess follow-through."}

    closes = df["Close"].values
    volumes = df["Volume"].values
    vol_avg = _vol_avg(volumes)
    event_close = closes[event_idx]

    after_closes = closes[event_idx + 1:end_idx]
    after_vols = volumes[event_idx + 1:end_idx]

    if event.bullish:
        # Expect price to move UP after bullish event (spring, SC, test)
        price_moved_right = after_closes[-1] > event_close
        strong_bars = sum(1 for c_i in range(len(after_closes))
                         if after_closes[c_i] > event_close)
        vol_expanding = float(np.mean(after_vols)) > vol_avg
    else:
        # Expect price to move DOWN after bearish event (upthrust, BC)
        price_moved_right = after_closes[-1] < event_close
        strong_bars = sum(1 for c_i in range(len(after_closes))
                         if after_closes[c_i] < event_close)
        vol_expanding = float(np.mean(after_vols)) > vol_avg

    bars_checked = len(after_closes)

    if price_moved_right and vol_expanding and strong_bars >= bars_checked * 0.6:
        quality = "STRONG"
        desc = (f"STRONG follow-through after {event.event_type}: {strong_bars}/{bars_checked} bars "
                f"moved in expected direction with expanding volume. Setup confirmed.")
    elif price_moved_right and strong_bars >= bars_checked * 0.5:
        quality = "MODERATE"
        desc = (f"Moderate follow-through after {event.event_type}: price moved correctly "
                f"but volume was not convincing. Proceed with caution.")
    else:
        quality = "WEAK"
        direction = "up" if event.bullish else "down"
        desc = (f"WEAK/NO follow-through after {event.event_type}: price did not convincingly "
                f"move {direction}. The setup may be failing — Weis calls this 'the deciding factor.'")

    return {
        "follow_through": "YES" if quality in ("STRONG", "MODERATE") else "NO",
        "quality": quality,
        "bars_checked": bars_checked,
        "strong_bars": strong_bars,
        "volume_expanding": vol_expanding,
        "description": desc,
    }


def detect_absorption(df: pd.DataFrame, support: float, resistance: float) -> Optional[WyckoffEvent]:
    """
    [WEIS Ch. 7] Absorption — one of the three core Wyckoff patterns.

    Source: Weis — Ch. 7, absorption within a trading range.
      Weis describes absorption as supply being absorbed by demand
      (or vice versa) WITHIN the range, without a spring or upthrust.

    Six clues for absorption (from the book):
      AB1: Rising supports within the range (lows getting higher)
      AB2: Heavy volume at the top of the range without breaking out
      AB3: Lack of downside follow-through after sharp drops
      AB4: Pressing against resistance repeatedly
      AB5: Bag-holding: heavy selling into support that fails to break it
      AB6: Minor upthrusts near resistance that fail quickly

    We check for the most algorithmically detectable clues: rising supports
    and pressing against resistance with heavy volume absorbed.

    Returns:
        WyckoffEvent if absorption detected, None otherwise.
    """
    if len(df) < 20 or support <= 0 or resistance <= 0:
        return None

    closes = df["Close"].values
    lows = df["Low"].values
    highs = df["High"].values
    volumes = df["Volume"].values
    vol_avg = _vol_avg(volumes)
    n = len(df)

    lookback = min(20, n)
    recent_lows = lows[-lookback:]
    recent_highs = highs[-lookback:]
    recent_vols = volumes[-lookback:]

    # Clue 1: Rising supports — split range into segments, check if lows are rising
    seg_size = lookback // 3
    if seg_size < 2:
        return None
    seg1_low = float(np.min(recent_lows[:seg_size]))
    seg2_low = float(np.min(recent_lows[seg_size:seg_size * 2]))
    seg3_low = float(np.min(recent_lows[seg_size * 2:]))
    rising_supports = seg3_low > seg1_low and seg2_low >= seg1_low

    # Clue 2: Heavy volume near resistance (pressing against top)
    range_height = resistance - support
    if range_height <= 0:
        return None
    near_resistance_mask = recent_highs > (resistance - range_height * 0.15)
    vol_near_resistance = float(np.mean(recent_vols[near_resistance_mask])) if np.any(near_resistance_mask) else 0
    heavy_vol_at_top = vol_near_resistance > vol_avg * 1.3

    # Clue 3: Bag-holding — heavy volume near support that doesn't break
    near_support_mask = recent_lows < (support + range_height * 0.15)
    vol_near_support = float(np.mean(recent_vols[near_support_mask])) if np.any(near_support_mask) else 0
    bag_holding = vol_near_support > vol_avg * 1.5 and float(np.min(recent_lows)) >= support * 0.98

    clue_count = sum([rising_supports, heavy_vol_at_top, bag_holding])

    if clue_count >= 2:
        # Determine if bullish or bearish absorption
        # Rising supports + heavy vol at top = demand absorbing supply = BULLISH
        # Falling highs + heavy vol at bottom = supply absorbing demand = BEARISH
        seg1_high = float(np.max(recent_highs[:seg_size]))
        seg3_high = float(np.max(recent_highs[seg_size * 2:]))
        falling_highs = seg3_high < seg1_high

        if rising_supports and not falling_highs:
            bullish = True
            conf = 50 + clue_count * 15
            desc = (f"BULLISH ABSORPTION: Demand is absorbing supply within the range. "
                    f"Clues: {'Rising supports detected. ' if rising_supports else ''}"
                    f"{'Heavy volume near resistance being absorbed. ' if heavy_vol_at_top else ''}"
                    f"{'Bag-holding at support — heavy selling absorbed. ' if bag_holding else ''}"
                    f"Smart money is quietly accumulating. Expect eventual upside breakout.")
        elif falling_highs:
            bullish = False
            conf = 50 + clue_count * 15
            desc = (f"BEARISH ABSORPTION: Supply is absorbing demand within the range. "
                    f"Highs are falling while {'support holds' if not rising_supports else 'supports rise'}. "
                    f"Smart money may be distributing. Watch for downside break.")
        else:
            bullish = True  # Default: rising supports = bullish
            conf = 45 + clue_count * 10
            desc = (f"ABSORPTION detected with {clue_count} clues. "
                    f"{'Rising supports. ' if rising_supports else ''}"
                    f"{'Heavy volume at top. ' if heavy_vol_at_top else ''}"
                    f"{'Bag-holding at support. ' if bag_holding else ''}")

        conf = min(100, conf)
        return WyckoffEvent(
            event_type="ABSORPTION",
            bar_index=n - 1,
            confidence=round(conf),
            price=float(closes[-1]),
            volume_ratio=round(volumes[-1] / vol_avg if vol_avg > 0 else 1.0, 2),
            bullish=bullish,
            description=desc,
        )

    return None


def detect_change_in_behavior(df: pd.DataFrame) -> Optional[WyckoffEvent]:
    """
    [WEIS Ch. 4] Change in Behavior — the "first" or "largest" opposite-direction event.

    Source: Weis — Ch. 4 (bar reading).
      Weis teaches that a "change in behavior" is the first significant
      bar in the OPPOSITE direction of the prevailing trend. It signals
      that the opposing side is waking up.

    Examples:
      - In an uptrend: the LARGEST down-bar in X periods = sellers emerging
      - In a downtrend: the LARGEST up-bar in X periods = buyers emerging

    Returns:
        WyckoffEvent if a change-in-behavior bar is detected, None otherwise.
    """
    if len(df) < 20:
        return None

    closes = df["Close"].values
    opens = df["Open"].values
    highs = df["High"].values
    lows = df["Low"].values
    volumes = df["Volume"].values
    spreads = highs - lows
    vol_avg = _vol_avg(volumes)
    n = len(df)

    # Determine recent trend from last 20 bars
    sma_short = float(np.mean(closes[-10:]))
    sma_long = float(np.mean(closes[-20:]))
    trend = "UP" if sma_short > sma_long * 1.01 else ("DOWN" if sma_short < sma_long * 0.99 else "FLAT")

    if trend == "FLAT":
        return None

    # Look at last bar
    i = n - 1
    current_spread = spreads[i]
    current_vol = volumes[i]
    is_up_bar = closes[i] > opens[i]

    # Find the largest spread in the OPPOSITE direction in last 20 bars
    lookback = min(20, n - 1)
    if trend == "UP" and not is_up_bar:
        # Down bar in uptrend — check if it's the largest down bar recently
        opposite_spreads = [spreads[j] for j in range(n - lookback, n - 1)
                           if closes[j] < opens[j]]
        if opposite_spreads and current_spread >= max(opposite_spreads):
            conf = min(90, 50 + int((current_vol / vol_avg) * 15))
            return WyckoffEvent(
                event_type="CHANGE_IN_BEHAVIOR",
                bar_index=i,
                confidence=conf,
                price=float(closes[i]),
                volume_ratio=round(current_vol / vol_avg if vol_avg > 0 else 1.0, 2),
                bullish=False,
                description=(
                    f"CHANGE IN BEHAVIOR (bearish): Largest down-bar in {lookback} periods "
                    f"appeared during an uptrend. Spread: {current_spread:.2f}, "
                    f"Volume: {current_vol/vol_avg:.1f}× avg. "
                    f"Sellers are waking up — the first shot across the bow."
                ),
            )
    elif trend == "DOWN" and is_up_bar:
        # Up bar in downtrend — check if it's the largest up bar recently
        opposite_spreads = [spreads[j] for j in range(n - lookback, n - 1)
                           if closes[j] > opens[j]]
        if opposite_spreads and current_spread >= max(opposite_spreads):
            conf = min(90, 50 + int((current_vol / vol_avg) * 15))
            return WyckoffEvent(
                event_type="CHANGE_IN_BEHAVIOR",
                bar_index=i,
                confidence=conf,
                price=float(closes[i]),
                volume_ratio=round(current_vol / vol_avg if vol_avg > 0 else 1.0, 2),
                bullish=True,
                description=(
                    f"CHANGE IN BEHAVIOR (bullish): Largest up-bar in {lookback} periods "
                    f"appeared during a downtrend. Spread: {current_spread:.2f}, "
                    f"Volume: {current_vol/vol_avg:.1f}× avg. "
                    f"Buyers are waking up — potential turning point."
                ),
            )

    return None


def detect_sign_of_strength(df: pd.DataFrame) -> Optional[WyckoffEvent]:
    """
    [POST-WYCKOFF] Sign of Strength (SOS) — confirms accumulation is complete.

    Source: Post-Wyckoff course terminology.
      Weis describes the bar behavior (wide spread up bar, heavy volume,
      strong close) but does not use the label "SOS." The detection logic
      captures the behavior Weis teaches; the naming is from later courses.

    [PARAPHRASE] "An SOS is a wide-spread up bar on increasing volume
     that signals markup is about to begin."

    Our algorithmic rules:
      1. Up bar (close > open) — [WEIS]
      2. Wide spread (≥60th percentile) — [CALIBRATION]
      3. Above-average volume (≥1.3×) — [CALIBRATION]
      4. Close in upper 30% of bar (≥0.7 position) — [CALIBRATION]

    [INFERRED — CONFLUENCE with Bollinger]
    Note about BB squeeze confluence is our integration insight,
    not from Weis's book.
    """
    if len(df) < 10:
        return None

    i = len(df) - 1
    closes = df["Close"].values
    highs = df["High"].values
    lows = df["Low"].values
    opens = df["Open"].values
    volumes = df["Volume"].values
    spreads = highs - lows

    spread = spreads[i]
    sp_pct = _spread_percentile(spreads, spread)
    vol_avg = _vol_avg(volumes)
    vol_ratio = volumes[i] / vol_avg if vol_avg > 0 else 0
    close_pos = _close_position(highs[i], lows[i], closes[i])
    is_up = closes[i] > opens[i]

    if (is_up and sp_pct >= SOS_MIN_SPREAD_PERCENTILE and
            vol_ratio >= SOS_MIN_VOLUME_RATIO and close_pos >= 0.7):
        conf = min(100, int(sp_pct * 0.3 + vol_ratio / 3 * 30 + close_pos * 30))
        return WyckoffEvent(
            event_type="SOS",
            bar_index=i,
            confidence=conf,
            price=float(closes[i]),
            volume_ratio=round(vol_ratio, 2),
            bullish=True,
            description=(
                f"SIGN OF STRENGTH: Wide spread up bar ({sp_pct:.0f}th pct), "
                f"above-average volume ({vol_ratio:.1f}×), closing near the high "
                f"({close_pos:.0%}). This shows strong demand and often signals "
                f"the beginning of a Markup phase."
            ),
        )

    return None


def detect_sign_of_weakness(df: pd.DataFrame) -> Optional[WyckoffEvent]:
    """
    [POST-WYCKOFF] Sign of Weakness (SOW) — confirms distribution is complete.

    Source: Post-Wyckoff course terminology.
      Mirror of SOS. Wide spread down bar on increasing volume
      signals that the markdown phase is about to begin.
      Weis describes this bar behavior; the "SOW" label is from later courses.

    Our algorithmic rules (all thresholds are [CALIBRATION]):
      1. Down bar (close < open) — [WEIS]
      2. Wide spread (≥60th percentile) — [CALIBRATION]
      3. Above-average volume (≥1.3×) — [CALIBRATION]
      4. Close in lower 30% of bar (≤0.3 position) — [CALIBRATION]
    """
    if len(df) < 10:
        return None

    i = len(df) - 1
    closes = df["Close"].values
    highs = df["High"].values
    lows = df["Low"].values
    opens = df["Open"].values
    volumes = df["Volume"].values
    spreads = highs - lows

    spread = spreads[i]
    sp_pct = _spread_percentile(spreads, spread)
    vol_avg = _vol_avg(volumes)
    vol_ratio = volumes[i] / vol_avg if vol_avg > 0 else 0
    close_pos = _close_position(highs[i], lows[i], closes[i])
    is_down = closes[i] < opens[i]

    if (is_down and sp_pct >= SOW_MIN_SPREAD_PERCENTILE and
            vol_ratio >= SOW_MIN_VOLUME_RATIO and close_pos <= 0.3):
        conf = min(100, int(sp_pct * 0.3 + vol_ratio / 3 * 30 + (1 - close_pos) * 30))
        return WyckoffEvent(
            event_type="SOW",
            bar_index=i,
            confidence=conf,
            price=float(closes[i]),
            volume_ratio=round(vol_ratio, 2),
            bullish=False,
            description=(
                f"SIGN OF WEAKNESS: Wide spread down bar ({sp_pct:.0f}th pct), "
                f"above-average volume ({vol_ratio:.1f}×), closing near the low "
                f"({close_pos:.0%}). This shows strong supply and often signals "
                f"the beginning of a Markdown phase."
            ),
        )

    return None


# ═══════════════════════════════════════════════════════════════
#  WYCKOFF PHASE IDENTIFICATION
# ═══════════════════════════════════════════════════════════════

def identify_wyckoff_phase(df: pd.DataFrame) -> WyckoffPhase:
    """
    [WEIS] Identify the current Wyckoff market phase.

    Source: Weis — throughout "Trades About to Happen" (Chapters 1-11).
      Weis teaches four phases of the market cycle. The principles
      below are all from the book; the algorithmic IMPLEMENTATION
      (thresholds, swing-window size, prior-trend detection) is
      [INFERRED] — our quantification of Weis's visual bar reading.

    [INFERRED] Sub-phases (EARLY/MIDDLE/CONFIRMED/LATE):
      Weis describes how phases PROGRESS (e.g., accumulation starts
      with a SC, then springs test support, then SOS breaks out).
      Our sub-phase labels formalize this progression but the specific
      names are our invention, not Weis's terminology.

    Phase Identification Principles from Weis:

    1. ACCUMULATION:
       - Price in a trading range AFTER a decline — [WEIS]
       - Volume decreases on down-waves, increases on up-waves — [WEIS]
       - Springs and successful tests confirm accumulation — [WEIS]
       - SOS bar breaks above range → Markup begins — [WEIS]

    2. MARKUP:
       - Price making higher highs and higher lows — [WEIS]
       - Volume expands on rallies, contracts on pullbacks — [WEIS]
       - LPS concept (pullback on low volume) — [WEIS]

    3. DISTRIBUTION:
       - Price in a trading range AFTER an advance — [WEIS]
       - Volume increases on down-waves, decreases on up-waves — [WEIS]
       - Upthrusts and failed tests confirm distribution — [WEIS]
       - SOW bar breaks below range → Markdown begins — [WEIS]

    4. MARKDOWN:
       - Price making lower highs and lower lows — [WEIS]
       - Volume expands on declines, contracts on rallies — [WEIS]
       - LPSY concept (rally to resistance on low volume) — [WEIS]
    """
    if df is None or len(df) < PHASE_MIN_BARS:
        return WyckoffPhase("UNKNOWN", "UNKNOWN", 0,
                            description="Insufficient data for phase identification")

    closes = df["Close"].values
    highs = df["High"].values
    lows = df["Low"].values
    volumes = df["Volume"].values
    n = len(df)

    # ── Step 1: Determine if price is in a trading range ──
    in_range, range_low, range_high = _is_in_range(df)

    # ── Step 2: Determine prior trend (what came before current state) ──
    # Look at the trend 30-60 bars ago compared to the range
    if n >= 60:
        old_avg = np.mean(closes[-60:-30])
        range_avg = np.mean(closes[-30:])
        prior_trend = "DOWN" if old_avg > range_avg * 1.05 else (
            "UP" if old_avg < range_avg * 0.95 else "FLAT"
        )
    else:
        prior_trend = "FLAT"

    # ── Step 3: Compare volume on up-moves vs down-moves (last 20 bars) ──
    recent = min(20, n)
    up_vol, dn_vol = 0.0, 0.0
    up_count, dn_count = 0, 0
    for i in range(n - recent, n):
        if closes[i] > closes[i - 1] if i > 0 else closes[i] > df["Open"].values[i]:
            up_vol += volumes[i]
            up_count += 1
        else:
            dn_vol += volumes[i]
            dn_count += 1

    avg_up_vol = up_vol / max(1, up_count)
    avg_dn_vol = dn_vol / max(1, dn_count)
    vol_ratio = avg_up_vol / avg_dn_vol if avg_dn_vol > 0 else 1.0

    # ── Step 4: Check for higher highs/lows or lower highs/lows ──
    # Use 10-bar rolling highs and lows
    swing_window = 10
    if n >= swing_window * 3:
        recent_highs = [np.max(highs[i:i + swing_window])
                        for i in range(n - swing_window * 3, n - swing_window, swing_window)]
        recent_lows = [np.min(lows[i:i + swing_window])
                       for i in range(n - swing_window * 3, n - swing_window, swing_window)]
        hh = all(recent_highs[i] >= recent_highs[i - 1] for i in range(1, len(recent_highs)))
        hl = all(recent_lows[i] >= recent_lows[i - 1] for i in range(1, len(recent_lows)))
        lh = all(recent_highs[i] <= recent_highs[i - 1] for i in range(1, len(recent_highs)))
        ll = all(recent_lows[i] <= recent_lows[i - 1] for i in range(1, len(recent_lows)))
    else:
        hh = hl = lh = ll = False

    # ── Step 5: Detect events ──
    events: List[WyckoffEvent] = []

    sc = detect_selling_climax(df)
    if sc:
        events.append(sc)
    bc = detect_buying_climax(df)
    if bc:
        events.append(bc)

    if in_range:
        spring = detect_spring(df, range_low, dominant_trend=prior_trend)
        if spring:
            events.append(spring)
        upthrust = detect_upthrust(df, range_high, dominant_trend=prior_trend)
        if upthrust:
            events.append(upthrust)
        # [WEIS Ch. 7] Absorption detection within the trading range
        absorption = detect_absorption(df, range_low, range_high)
        if absorption:
            events.append(absorption)

    sos = detect_sign_of_strength(df)
    if sos:
        events.append(sos)
    sow = detect_sign_of_weakness(df)
    if sow:
        events.append(sow)

    # [WEIS Ch. 4] Change in behavior — first/largest opposite-direction bar
    cib = detect_change_in_behavior(df)
    if cib:
        events.append(cib)

    # ── Step 6: Classify Phase ──
    phase = "UNKNOWN"
    sub_phase = "UNKNOWN"
    confidence = 30  # Base

    # Check for trending phases first (clearer signals)
    if hh and hl and not in_range:
        phase = "MARKUP"
        has_sos = any(e.event_type == "SOS" for e in events)
        has_bc = any(e.event_type == "BC" for e in events)

        if vol_ratio > 1.2 and has_sos:
            sub_phase = "LATE"
            confidence = 85
            desc = ("LATE MARKUP PHASE: The uptrend is mature — price has been making "
                    "higher highs and higher lows for a while, with strong volume on rallies. "
                    "A Sign of Strength (SOS) bar confirms genuine demand is driving prices up. "
                    "However, watch for signs the trend is getting tired: if a Buying Climax (BC) "
                    "appears, or up-pushes start getting shorter (shortening of thrust), "
                    "the stock may be approaching distribution territory. "
                    "Action: Hold existing longs but tighten stops. Don't chase new buys here — "
                    "you're closer to the END of the move than the beginning.")
        elif vol_ratio > 1.2:
            sub_phase = "CONFIRMED"
            confidence = 75
            desc = ("CONFIRMED MARKUP PHASE: Price is making higher highs and higher lows with "
                    "stronger volume on up-moves — this is the classic uptrend. Think of it like "
                    "a river flowing uphill: each wave carries more water (volume) going up "
                    "than coming down. This is the PROFIT phase — the move up from accumulation "
                    "is underway and confirmed by volume. "
                    "Action: Hold longs with confidence. On pullbacks (small dips), watch for "
                    "LOW volume — that's called an LPS (Last Point of Support) and it's a great "
                    "spot to add more. If a pullback happens on HIGH volume, that's a warning sign.")
        elif has_sos:
            sub_phase = "MIDDLE"
            confidence = 65
            desc = ("MIDDLE MARKUP: The uptrend is developing. Higher highs and higher lows "
                    "are present, and a Sign of Strength (SOS) bar shows buyers flexing their "
                    "muscles — but volume hasn't fully shifted to confirm rallies yet. "
                    "Think of it like a plane that's taken off but hasn't reached cruising altitude. "
                    "Action: Hold existing longs. Look for volume to pick up on the NEXT rally "
                    "to confirm the move. If volume stays weak on up-moves, the markup may stall.")
        else:
            sub_phase = "EARLY"
            confidence = 50
            desc = ("EARLY MARKUP: Higher highs and lows are starting to form but volume "
                    "hasn't confirmed the move yet and no key Wyckoff events have fired. "
                    "Think of it like a car that just started moving — it could be the real deal, "
                    "or it could stall. The price structure looks promising but there's no "
                    "strong volume conviction behind it yet. "
                    "Action: Watch closely. If the next rally comes on increasing volume, "
                    "the markup is likely real. If volume stays flat, be cautious — this could "
                    "be a false start.")

    elif lh and ll and not in_range:
        phase = "MARKDOWN"
        has_sow = any(e.event_type == "SOW" for e in events)
        has_sc = any(e.event_type == "SC" for e in events)

        if vol_ratio < 0.8 and has_sow:
            sub_phase = "LATE"
            confidence = 85
            desc = ("LATE MARKDOWN PHASE: The downtrend is mature — price has been making "
                    "lower highs and lower lows with heavy volume on drops. A Sign of Weakness (SOW) "
                    "confirms that supply is overwhelming demand. However, watch for exhaustion: "
                    "if a Selling Climax (SC) appears, or down-pushes get smaller, the decline "
                    "may be nearing its end and accumulation could begin. "
                    "Action: Stay away from buying. If you're short, start tightening stops — "
                    "the bottom may be forming soon.")
        elif vol_ratio < 0.8:
            sub_phase = "CONFIRMED"
            confidence = 75
            desc = ("CONFIRMED MARKDOWN PHASE: Price is making lower highs and lower lows with "
                    "heavier volume on declines than on rallies. This is the DECLINE phase — "
                    "like a ball rolling downhill, gravity (selling pressure) is doing the work. "
                    "Any bounce that happens on LOW volume is called LPSY (Last Point of Supply) — "
                    "it's a spot where smart money sells the last of their holdings. "
                    "Action: Avoid buying. Rally attempts on low volume are selling opportunities, "
                    "not buying opportunities.")
        elif has_sow:
            sub_phase = "MIDDLE"
            confidence = 65
            desc = ("MIDDLE MARKDOWN: The downtrend is developing. Lower highs and lower lows "
                    "are forming, and a Sign of Weakness (SOW) shows sellers are in control — "
                    "but volume hasn't fully shifted to confirm all declines yet. "
                    "Action: Avoid buying. Wait for clear exhaustion signals before looking for "
                    "a bottom.")
        else:
            sub_phase = "EARLY"
            confidence = 50
            desc = ("EARLY MARKDOWN: Lower highs and lows are forming but volume hasn't "
                    "confirmed the move yet. The downtrend could be real, or it could be a "
                    "temporary pullback within a larger uptrend. "
                    "Action: Be cautious with longs. If the next decline comes on increasing "
                    "volume, the markdown is real. If volume stays light, this might just be "
                    "a normal pullback.")

    elif in_range and prior_trend == "DOWN":
        phase = "ACCUMULATION"
        confidence = 50
        has_spring = any(e.event_type == "SPRING" for e in events)
        has_sc = any(e.event_type == "SC" for e in events)
        has_sos = any(e.event_type == "SOS" for e in events)

        if has_spring and has_sos:
            sub_phase = "LATE"
            confidence = 85
            desc = ("LATE ACCUMULATION: After a decline, price is in a trading range. "
                    "A Spring (shakeout) has occurred AND Sign of Strength detected. "
                    "Smart money has finished accumulating. Markup is imminent. "
                    "This is a HIGH-PROBABILITY buy zone.")
        elif has_spring or has_sc:
            sub_phase = "MIDDLE"
            confidence = 70
            desc = ("MIDDLE ACCUMULATION: Trading range after decline with "
                    + ("Spring detected — smart money is shaking out weak holders. "
                       if has_spring else "Selling Climax detected — panic selling absorbed. ")
                    + "Wait for a test on low volume to confirm before buying.")
        else:
            sub_phase = "EARLY"
            confidence = 45
            desc = ("EARLY ACCUMULATION: Price has established a trading range after a "
                    "decline. Volume patterns suggest possible accumulation but no "
                    "confirming events yet. Watch for a Spring or Selling Climax.")

    elif in_range and prior_trend == "UP":
        phase = "DISTRIBUTION"
        confidence = 50
        has_ut = any(e.event_type == "UPTHRUST" for e in events)
        has_bc = any(e.event_type == "BC" for e in events)
        has_sow = any(e.event_type == "SOW" for e in events)

        if has_ut and has_sow:
            sub_phase = "LATE"
            confidence = 85
            desc = ("LATE DISTRIBUTION: After an advance, price is in a trading range. "
                    "An Upthrust (failed breakout) AND Sign of Weakness detected. "
                    "Smart money has finished distributing. Markdown is imminent. "
                    "This is a HIGH-PROBABILITY sell zone.")
        elif has_ut or has_bc:
            sub_phase = "MIDDLE"
            confidence = 70
            desc = ("MIDDLE DISTRIBUTION: Trading range after advance with "
                    + ("Upthrust detected — breakout buyers are being trapped. "
                       if has_ut else "Buying Climax detected — euphoric buying absorbed. ")
                    + "Watch for confirmation before selling.")
        else:
            sub_phase = "EARLY"
            confidence = 45
            desc = ("EARLY DISTRIBUTION: Price has established a trading range after an "
                    "advance. Possible distribution but no confirming events yet. "
                    "Watch for an Upthrust or Buying Climax.")

    elif in_range:
        phase = "RANGING"
        sub_phase = "CONSOLIDATION"
        confidence = 40
        desc = ("RANGING: Price is in a trading range without clear prior trend context. "
                "Watch for Wyckoff events (Springs, Upthrusts) to reveal which side will win.")
    else:
        # Not in range, not trending clearly
        current_5 = np.mean(closes[-5:])
        current_20 = np.mean(closes[-20:]) if n >= 20 else current_5
        if current_5 > current_20 * 1.02:
            phase = "MARKUP"
            sub_phase = "EARLY"
            confidence = 40
        elif current_5 < current_20 * 0.98:
            phase = "MARKDOWN"
            sub_phase = "EARLY"
            confidence = 40
        else:
            phase = "UNKNOWN"
            sub_phase = "TRANSITIONING"
            confidence = 20
        desc = (f"{phase} ({sub_phase}): Price structure is not fully clear. "
                "The market may be transitioning between phases.")

    return WyckoffPhase(
        phase=phase,
        sub_phase=sub_phase,
        confidence=round(confidence),
        events=events,
        support=round(range_low, 2) if in_range else 0,
        resistance=round(range_high, 2) if in_range else 0,
        description=desc,
    )
