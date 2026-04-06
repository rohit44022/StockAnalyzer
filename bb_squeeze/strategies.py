"""
strategies.py — Three additional Bollinger Band strategies from the book.

"Bollinger on Bollinger Bands" by John Bollinger (2001):
  Method II  — Trend Following   (%b + MFI confirmation)
  Method III — Reversals          (W-Bottoms & M-Tops with %b divergence)
  Method IV  — Walking the Bands  (Strong trend continuation)

Architecture:
  Each strategy is a self-contained analyser that receives a DataFrame
  (already enriched with indicators from indicators.py) and returns a
  typed StrategyResult dataclass.  The strategies module NEVER modifies
  the DataFrame or the existing squeeze (Method I) pipeline.

  All three analysers are composed by `run_all_strategies()` which
  returns a list of results that the web/API layer serialises.
"""

from __future__ import annotations

import math
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from bb_squeeze.strategy_config import (
    # Method II
    M2_PCT_B_BUY_THRESHOLD, M2_PCT_B_SELL_THRESHOLD,
    M2_MFI_CONFIRM_BUY, M2_MFI_CONFIRM_SELL,
    M2_MFI_DIVERGE_LOOKBACK, M2_VOL_CONFIRM,
    # Method III
    M3_W_LOOKBACK, M3_W_MIN_SEPARATION, M3_W_MAX_SEPARATION,
    M3_W_FIRST_LOW_PCT_B, M3_W_SECOND_LOW_PCT_B, M3_W_PRICE_TOLERANCE,
    M3_M_FIRST_HIGH_PCT_B, M3_M_SECOND_HIGH_PCT_B, M3_M_PRICE_TOLERANCE,
    M3_MFI_DIVERGE_THRESHOLD,
    # Method IV
    M4_WALK_MIN_TOUCHES, M4_WALK_LOOKBACK, M4_WALK_TOUCH_TOLERANCE,
    M4_WALK_PCT_B_UPPER, M4_WALK_PCT_B_LOWER, M4_WALK_BB_MID_PULLBACK,
    # Display
    STRATEGY_NAMES, STRATEGY_DESCRIPTIONS,
)


def _nan_safe(val, default=0.0):
    """Convert a value to float, replacing NaN/Inf with default."""
    try:
        v = float(val)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except (ValueError, TypeError):
        return default


# ═══════════════════════════════════════════════════════════════
#  DATA CLASSES
# ═══════════════════════════════════════════════════════════════

@dataclass
class StrategySignal:
    """A single signal event from any strategy."""
    signal_type: str         # "BUY" | "SELL" | "HOLD" | "WATCH" | "NONE"
    strength: str            # "STRONG" | "MODERATE" | "WEAK"
    confidence: int          # 0-100
    reason: str              # Human-readable one-liner
    details: str             # Multi-line detailed explanation


@dataclass
class PatternMatch:
    """A detected chart pattern (W-Bottom, M-Top, Walk, etc.)."""
    name: str                # "W-BOTTOM" | "M-TOP" | "WALK-UPPER" | "WALK-LOWER"
    start_idx: int           # Index of pattern start
    end_idx: int             # Index of pattern end
    start_date: str          # Date string
    end_date: str            # Date string
    description: str         # Narrative


@dataclass
class StrategyResult:
    """Complete result from one strategy analysis."""
    code: str                # "M2" | "M3" | "M4"
    name: str                # Full name
    description: str         # Strategy explanation
    signal: StrategySignal   # Current signal
    patterns: List[PatternMatch] = field(default_factory=list)
    indicators: dict = field(default_factory=dict)  # Strategy-specific metrics
    book_reference: str = ""  # Page/chapter reference from the book


# ═══════════════════════════════════════════════════════════════
#  METHOD II — TREND FOLLOWING (%b + MFI)
#  Book: Chapters 15-16
#  Core idea: %b tells WHERE price is in the band structure.
#  MFI CONFIRMS whether money is flowing in the same direction.
#  When %b > 0.8 and MFI > 80 → strong uptrend.
#  When %b < 0.2 and MFI < 20 → strong downtrend.
#  Divergence between the two warns of reversals.
# ═══════════════════════════════════════════════════════════════

def _method_ii_trend_following(df: pd.DataFrame) -> StrategyResult:
    """
    Method II — Trend Following.

    Logic straight from the book:
    1. Calculate %b and MFI (already in df from indicators.py)
    2. BUY when %b > 0.8 AND MFI confirms (> 60)
    3. SELL when %b < 0.2 AND MFI confirms (< 40)
    4. WATCH for divergence: %b rising but MFI falling = weakening trend
    """

    if len(df) < 30:
        return StrategyResult(
            code="M2", name=STRATEGY_NAMES["M2"],
            description=STRATEGY_DESCRIPTIONS["M2"],
            signal=StrategySignal("NONE", "WEAK", 0,
                                  "Insufficient data", "Need at least 30 days of data."),
            book_reference="Chapters 15-16",
        )

    tail = df.iloc[-M2_MFI_DIVERGE_LOOKBACK:]
    row = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else row

    pct_b   = _nan_safe(row["Percent_B"], 0.5)
    mfi     = _nan_safe(row["MFI"], 50.0)
    cmf     = _nan_safe(row["CMF"], 0.0)
    close   = float(row["Close"])
    bb_mid  = float(row["BB_Mid"])

    prev_pct_b = _nan_safe(prev["Percent_B"], 0.5)
    prev_mfi   = _nan_safe(prev["MFI"], 50.0)

    vol     = float(row["Volume"])
    vol_sma = float(row["Vol_SMA50"])

    # ── Divergence detection ──
    pct_b_trend = "rising" if pct_b > prev_pct_b else "falling"
    mfi_trend   = "rising" if mfi > prev_mfi else "falling"
    bullish_divergence = (pct_b_trend == "falling" and mfi_trend == "rising")
    bearish_divergence = (pct_b_trend == "rising"  and mfi_trend == "falling")

    # ── Signal generation ──
    signal_type  = "NONE"
    strength     = "WEAK"
    confidence   = 0
    reason       = ""
    details_lines = []

    # Strong Buy: %b in upper zone + MFI confirms + volume
    if pct_b > M2_PCT_B_BUY_THRESHOLD and mfi > M2_MFI_CONFIRM_BUY:
        vol_ok = (vol > vol_sma) if M2_VOL_CONFIRM else True
        if vol_ok and not bearish_divergence:
            signal_type = "BUY"
            strength = "STRONG" if mfi > 80 else "MODERATE"
            # Confidence based on how far BEYOND thresholds we are (excess strength)
            pct_b_excess = (pct_b - M2_PCT_B_BUY_THRESHOLD) / (1.0 - M2_PCT_B_BUY_THRESHOLD)  # 0-1
            mfi_excess = (mfi - M2_MFI_CONFIRM_BUY) / (100 - M2_MFI_CONFIRM_BUY)  # 0-1
            vol_ratio = min(vol / vol_sma, 3.0) / 3.0 if vol_sma > 0 else 0.5  # 0-1
            confidence = min(int(30 + pct_b_excess * 25 + mfi_excess * 25 + vol_ratio * 20), 100)
            reason = f"Strong uptrend — %b at {pct_b:.2f}, MFI at {mfi:.0f}"
            details_lines.append(
                f"Price is in the upper {(1 - pct_b) * 100:.0f}% of the Bollinger Band range. "
                f"Money Flow Index at {mfi:.0f} confirms buying pressure."
            )
            if cmf > 0.1:
                details_lines.append(
                    f"CMF at {cmf:+.3f} shows strong institutional accumulation."
                )
        elif bearish_divergence:
            signal_type = "WATCH"
            strength = "WEAK"
            confidence = 30
            reason = "Bearish divergence — %b rising but MFI falling"
            details_lines.append(
                "⚠️ Price is near the upper band but money flow is weakening. "
                "This divergence often precedes a pullback. Book says: "
                "'When %b and MFI disagree, believe MFI.'"
            )

    # Strong Sell: %b in lower zone + MFI confirms
    elif pct_b < M2_PCT_B_SELL_THRESHOLD and mfi < M2_MFI_CONFIRM_SELL:
        signal_type = "SELL"
        strength = "STRONG" if mfi < 20 else "MODERATE"
        # Confidence based on how far BEYOND thresholds we are (excess strength)
        pct_b_excess = (M2_PCT_B_SELL_THRESHOLD - pct_b) / M2_PCT_B_SELL_THRESHOLD  # 0-1
        mfi_excess = (M2_MFI_CONFIRM_SELL - mfi) / M2_MFI_CONFIRM_SELL  # 0-1
        confidence = min(int(30 + pct_b_excess * 35 + mfi_excess * 35), 100)
        reason = f"Strong downtrend — %b at {pct_b:.2f}, MFI at {mfi:.0f}"
        details_lines.append(
            f"Price is in the lower {pct_b * 100:.0f}% of the Bollinger Band range. "
            f"Money Flow Index at {mfi:.0f} confirms selling pressure."
        )

    # Bullish divergence at bottom — potential reversal
    elif pct_b < 0.3 and bullish_divergence:
        signal_type = "WATCH"
        strength = "MODERATE"
        confidence = 45
        reason = "Bullish divergence — %b falling but MFI rising"
        details_lines.append(
            "Price is near the lower band but money flow is improving. "
            "This is a classic bullish divergence that often precedes a rally. "
            "Watch for %b to cross above 0.5 to confirm."
        )

    # Moderate trend zone
    elif pct_b > 0.5 and mfi > 50:
        signal_type = "HOLD"
        strength = "MODERATE"
        confidence = int(pct_b * 40 + mfi * 0.3)
        reason = f"Trend intact — %b at {pct_b:.2f}, MFI at {mfi:.0f}"
        details_lines.append(
            "Price is above the middle band and money flow is positive. "
            "The trend remains intact. No action needed."
        )

    else:
        signal_type = "NONE"
        strength = "WEAK"
        confidence = 20
        reason = "No clear trend signal"
        details_lines.append(
            f"Current %b: {pct_b:.2f}, MFI: {mfi:.0f}. "
            "Neither in a strong uptrend nor downtrend zone."
        )

    # ── Checklists ──
    buy_checklist = [
        {
            "ok": pct_b > M2_PCT_B_BUY_THRESHOLD,
            "name": "%b Above 0.80 — Upper Zone",
            "detail": f"%b: {pct_b:.3f} (need > {M2_PCT_B_BUY_THRESHOLD})",
            "explain": "Price must be in the upper 20% of the Bollinger Band range, confirming a strong upward trend.",
        },
        {
            "ok": mfi > M2_MFI_CONFIRM_BUY,
            "name": "MFI Confirms Buying Pressure",
            "detail": f"MFI: {mfi:.1f} (need > {M2_MFI_CONFIRM_BUY})",
            "explain": "Money Flow Index must be above 60, confirming institutional buying. Above 80 is very strong.",
        },
        {
            "ok": vol > vol_sma,
            "name": "Volume Above 50-day SMA",
            "detail": f"Volume: {int(vol):,} · SMA-50: {int(vol_sma):,}",
            "explain": "Volume must exceed its 50-day average, proving the move has broad market participation.",
        },
        {
            "ok": not bearish_divergence,
            "name": "No Bearish Divergence",
            "detail": f"%b {pct_b_trend}, MFI {mfi_trend}" + (" — ⚠️ DIVERGING" if bearish_divergence else " — Aligned ✓"),
            "explain": "%b and MFI must move in the same direction. If %b rises but MFI falls, big money is quietly exiting.",
        },
        {
            "ok": cmf > 0,
            "name": "CMF Positive — Money Flowing In",
            "detail": f"CMF: {cmf:+.4f} (need > 0.00)",
            "explain": "Chaikin Money Flow must be positive, showing institutional accumulation. Above +0.10 is strong.",
        },
    ]

    sell_checklist = [
        {
            "ok": pct_b < M2_PCT_B_SELL_THRESHOLD,
            "name": "%b Below 0.20 — Lower Zone",
            "detail": f"%b: {pct_b:.3f} (need < {M2_PCT_B_SELL_THRESHOLD})",
            "explain": "Price must be in the lower 20% of the Bollinger Band range, confirming a strong downtrend.",
        },
        {
            "ok": mfi < M2_MFI_CONFIRM_SELL,
            "name": "MFI Confirms Selling Pressure",
            "detail": f"MFI: {mfi:.1f} (need < {M2_MFI_CONFIRM_SELL})",
            "explain": "Money Flow Index must be below 40, confirming institutions are selling. Below 20 is very strong.",
        },
        {
            "ok": close < bb_mid,
            "name": "Price Below Middle Band",
            "detail": f"Close: ₹{close:.2f} · Mid: ₹{bb_mid:.2f}",
            "explain": "Price should trade below the 20-day SMA (middle band), confirming bearish positioning.",
        },
        {
            "ok": not bullish_divergence,
            "name": "No Bullish Divergence",
            "detail": f"%b {pct_b_trend}, MFI {mfi_trend}" + (" — ⚠️ DIVERGING" if bullish_divergence else " — Aligned ✓"),
            "explain": "If %b is falling but MFI is rising, smart money may be secretly accumulating — potential reversal warning.",
        },
        {
            "ok": cmf < 0,
            "name": "CMF Negative — Money Flowing Out",
            "detail": f"CMF: {cmf:+.4f} (need < 0.00)",
            "explain": "Chaikin Money Flow must be negative, showing institutional distribution (selling).",
        },
    ]

    # ── Indicators for display ──
    indicators = {
        "pct_b": round(pct_b, 4),
        "mfi": round(mfi, 2),
        "cmf": round(cmf, 4),
        "pct_b_trend": pct_b_trend,
        "mfi_trend": mfi_trend,
        "bullish_divergence": bullish_divergence,
        "bearish_divergence": bearish_divergence,
        "price_vs_mid": "ABOVE" if close > bb_mid else "BELOW",
        "volume_confirmed": vol > vol_sma,
        "buy_checklist": buy_checklist,
        "sell_checklist": sell_checklist,
    }

    return StrategyResult(
        code="M2",
        name=STRATEGY_NAMES["M2"],
        description=STRATEGY_DESCRIPTIONS["M2"],
        signal=StrategySignal(
            signal_type=signal_type,
            strength=strength,
            confidence=confidence,
            reason=reason,
            details="\n".join(details_lines),
        ),
        indicators=indicators,
        book_reference="Chapters 15-16: 'Use %b to clarify and MFI to confirm.'",
    )


# ═══════════════════════════════════════════════════════════════
#  METHOD III — REVERSALS (W-BOTTOMS / M-TOPS)
#  Book: Chapter 17
#  Core idea from the book:
#    W-Bottom: First low at or below lower band (%b ≤ 0),
#              second low ABOVE lower band (%b > 0).
#              MFI should be higher on the second low (divergence).
#    M-Top:    First high at or above upper band (%b ≥ 1),
#              second high BELOW upper band (%b < 1).
#              MFI should be lower on the second high (divergence).
# ═══════════════════════════════════════════════════════════════

def _find_local_lows(prices: np.ndarray, order: int = 3) -> List[int]:
    """Find local minima indices using simple comparison."""
    lows = []
    for i in range(order, len(prices) - order):
        if all(prices[i] <= prices[i - j] for j in range(1, order + 1)) and \
           all(prices[i] <= prices[i + j] for j in range(1, order + 1)):
            lows.append(i)
    return lows


def _find_local_highs(prices: np.ndarray, order: int = 3) -> List[int]:
    """Find local maxima indices using simple comparison."""
    highs = []
    for i in range(order, len(prices) - order):
        if all(prices[i] >= prices[i - j] for j in range(1, order + 1)) and \
           all(prices[i] >= prices[i + j] for j in range(1, order + 1)):
            highs.append(i)
    return highs


def _detect_w_bottoms(df: pd.DataFrame, lookback: int = M3_W_LOOKBACK) -> List[PatternMatch]:
    """
    Detect W-Bottom patterns in the last `lookback` bars.

    From the book (Chapter 17):
    "A W bottom involves a first low that is below the lower band or at it,
     a reaction rally to the middle band, a NEW test of the lows which holds
     ABOVE the lower band, and a move up confirmed by an indicator."
    """
    patterns = []
    window = df.iloc[-lookback:].copy()
    if len(window) < 10:
        return patterns

    prices = window["Low"].values.astype(float)
    pct_b  = window["Percent_B"].values.astype(float)
    mfi_vals = window["MFI"].values.astype(float)
    dates  = window.index

    local_lows = _find_local_lows(prices, order=2)

    # Check pairs of lows for W-Bottom
    for i in range(len(local_lows)):
        for j in range(i + 1, len(local_lows)):
            idx1, idx2 = local_lows[i], local_lows[j]
            separation = idx2 - idx1

            if separation < M3_W_MIN_SEPARATION or separation > M3_W_MAX_SEPARATION:
                continue

            price1, price2 = prices[idx1], prices[idx2]
            pb1, pb2 = pct_b[idx1], pct_b[idx2]
            mfi1, mfi2 = mfi_vals[idx1], mfi_vals[idx2]

            # Book criteria:
            # 1. First low at or below the lower band (%b ≤ 0, using tolerance)
            first_at_lower = pb1 <= M3_W_FIRST_LOW_PCT_B + 0.05

            # 2. Second low ABOVE the lower band (%b > 0.2)
            second_above_lower = pb2 > M3_W_SECOND_LOW_PCT_B

            # 3. Second price roughly equal or higher than first (tolerance)
            price_holds = price2 >= price1 * (1 - M3_W_PRICE_TOLERANCE)

            # 4. MFI divergence: MFI higher on second low (positive divergence)
            mfi_diverges = mfi2 > mfi1 + M3_MFI_DIVERGE_THRESHOLD

            if first_at_lower and second_above_lower and price_holds:
                strength = "strong" if mfi_diverges else "moderate"
                desc = (
                    f"W-Bottom ({strength}): First low on {dates[idx1].strftime('%d-%b')} "
                    f"at ₹{price1:.2f} (%b={pb1:.2f}, tagged lower band). "
                    f"Second low on {dates[idx2].strftime('%d-%b')} "
                    f"at ₹{price2:.2f} (%b={pb2:.2f}, held ABOVE lower band). "
                )
                if mfi_diverges:
                    desc += (
                        f"MFI diverged positively: {mfi1:.0f} → {mfi2:.0f}. "
                        "This is the classic textbook W-Bottom from Bollinger's book."
                    )
                else:
                    desc += (
                        f"MFI: {mfi1:.0f} → {mfi2:.0f} (no clear divergence). "
                        "Pattern is present but unconfirmed by indicator divergence."
                    )

                patterns.append(PatternMatch(
                    name="W-BOTTOM",
                    start_idx=idx1, end_idx=idx2,
                    start_date=dates[idx1].strftime("%Y-%m-%d"),
                    end_date=dates[idx2].strftime("%Y-%m-%d"),
                    description=desc,
                ))

    return patterns


def _detect_m_tops(df: pd.DataFrame, lookback: int = M3_W_LOOKBACK) -> List[PatternMatch]:
    """
    Detect M-Top patterns in the last `lookback` bars.

    From the book (Chapter 17):
    "An M top has a first high at or above the upper band,
     a pullback toward the middle band, a new push to a higher
     or equal price level but BELOW the upper band, and then
     a decline confirmed by an indicator."
    """
    patterns = []
    window = df.iloc[-lookback:].copy()
    if len(window) < 10:
        return patterns

    prices = window["High"].values.astype(float)
    pct_b  = window["Percent_B"].values.astype(float)
    mfi_vals = window["MFI"].values.astype(float)
    dates  = window.index

    local_highs = _find_local_highs(prices, order=2)

    for i in range(len(local_highs)):
        for j in range(i + 1, len(local_highs)):
            idx1, idx2 = local_highs[i], local_highs[j]
            separation = idx2 - idx1

            if separation < M3_W_MIN_SEPARATION or separation > M3_W_MAX_SEPARATION:
                continue

            price1, price2 = prices[idx1], prices[idx2]
            pb1, pb2 = pct_b[idx1], pct_b[idx2]
            mfi1, mfi2 = mfi_vals[idx1], mfi_vals[idx2]

            # Book criteria:
            # 1. First high at or above upper band (%b ≥ 1, using tolerance)
            first_at_upper = pb1 >= M3_M_FIRST_HIGH_PCT_B - 0.05

            # 2. Second high BELOW the upper band (%b < 0.8)
            second_below_upper = pb2 < M3_M_SECOND_HIGH_PCT_B

            # 3. Second price roughly equal or higher than first
            price_matches = price2 >= price1 * (1 - M3_M_PRICE_TOLERANCE)

            # 4. MFI divergence: MFI LOWER on second high (negative divergence)
            mfi_diverges = mfi2 < mfi1 - M3_MFI_DIVERGE_THRESHOLD

            if first_at_upper and second_below_upper and price_matches:
                strength = "strong" if mfi_diverges else "moderate"
                desc = (
                    f"M-Top ({strength}): First high on {dates[idx1].strftime('%d-%b')} "
                    f"at ₹{price1:.2f} (%b={pb1:.2f}, tagged upper band). "
                    f"Second high on {dates[idx2].strftime('%d-%b')} "
                    f"at ₹{price2:.2f} (%b={pb2:.2f}, FAILED to reach upper band). "
                )
                if mfi_diverges:
                    desc += (
                        f"MFI diverged negatively: {mfi1:.0f} → {mfi2:.0f}. "
                        "Classic M-Top — expect a decline."
                    )
                else:
                    desc += (
                        f"MFI: {mfi1:.0f} → {mfi2:.0f} (no clear divergence). "
                        "The pattern structure is present but unconfirmed."
                    )

                patterns.append(PatternMatch(
                    name="M-TOP",
                    start_idx=idx1, end_idx=idx2,
                    start_date=dates[idx1].strftime("%Y-%m-%d"),
                    end_date=dates[idx2].strftime("%Y-%m-%d"),
                    description=desc,
                ))

    return patterns


def _method_iii_reversals(df: pd.DataFrame) -> StrategyResult:
    """
    Method III — Reversals (W-Bottoms & M-Tops).

    The book says: "The most important pattern recognition technique
    applied to Bollinger Bands is the identification of M-type tops
    and W-type bottoms."
    """
    if len(df) < M3_W_LOOKBACK:
        return StrategyResult(
            code="M3", name=STRATEGY_NAMES["M3"],
            description=STRATEGY_DESCRIPTIONS["M3"],
            signal=StrategySignal("NONE", "WEAK", 0,
                                  "Insufficient data",
                                  f"Need at least {M3_W_LOOKBACK} days of data."),
            book_reference="Chapter 17",
        )

    w_patterns = _detect_w_bottoms(df)
    m_patterns = _detect_m_tops(df)
    all_patterns = w_patterns + m_patterns

    row  = df.iloc[-1]
    pct_b = _nan_safe(row["Percent_B"], 0.5)
    mfi   = _nan_safe(row["MFI"], 50.0)
    close = float(row["Close"])

    # ── Determine current signal based on recent patterns ──
    signal_type = "NONE"
    strength    = "WEAK"
    confidence  = 0
    reason      = ""
    details_lines = []

    # Check for recent (last 5 bars) pattern completion
    recent_w = [p for p in w_patterns if p.end_idx >= len(df.iloc[-M3_W_LOOKBACK:]) - 5]
    recent_m = [p for p in m_patterns if p.end_idx >= len(df.iloc[-M3_W_LOOKBACK:]) - 5]

    if recent_w:
        last_w = recent_w[-1]
        if pct_b > 0.3:  # Price starting to recover
            signal_type = "BUY"
            strength = "STRONG" if "strong" in last_w.description else "MODERATE"
            confidence = 75 if strength == "STRONG" else 55
            reason = "W-Bottom reversal detected — buy signal"
            details_lines.append(last_w.description)
            details_lines.append(
                "The book says: 'The first low can be below the band, "
                "but the second low MUST hold above it.' This is your signal "
                "that selling pressure is exhausted."
            )
        else:
            signal_type = "WATCH"
            strength = "MODERATE"
            confidence = 40
            reason = "W-Bottom forming — watch for confirmation"
            details_lines.append(last_w.description)
            details_lines.append(
                "Pattern is forming but price hasn't moved above %b = 0.5 yet. "
                "Wait for a close above the middle Bollinger Band to confirm."
            )

    elif recent_m:
        last_m = recent_m[-1]
        if pct_b < 0.7:  # Price starting to decline
            signal_type = "SELL"
            strength = "STRONG" if "strong" in last_m.description else "MODERATE"
            confidence = 75 if strength == "STRONG" else 55
            reason = "M-Top reversal detected — sell signal"
            details_lines.append(last_m.description)
            details_lines.append(
                "The book says: 'The first high can exceed the band, "
                "but the second high MUST fail to reach it.' This shows "
                "buying momentum is fading."
            )
        else:
            signal_type = "WATCH"
            strength = "MODERATE"
            confidence = 40
            reason = "M-Top forming — watch for confirmation"
            details_lines.append(last_m.description)

    else:
        # No recent pattern — describe current position
        if pct_b < 0.1:
            details_lines.append(
                f"Price near lower band (%b = {pct_b:.2f}). "
                "If price bounces from here and makes another low that "
                "holds ABOVE the lower band, that would form a W-Bottom."
            )
        elif pct_b > 0.9:
            details_lines.append(
                f"Price near upper band (%b = {pct_b:.2f}). "
                "If price pulls back and then rallies again without "
                "reaching the upper band, that would form an M-Top."
            )
        else:
            details_lines.append(
                f"No W-Bottom or M-Top pattern detected in the last "
                f"{M3_W_LOOKBACK} trading days. %b = {pct_b:.2f}."
            )
        reason = "No reversal pattern currently active"

    # ── Extract pattern data for checklists ──
    # W-Bottom: get data from last detected W pattern
    _w_found = len(w_patterns) > 0
    _w_recent = len(recent_w) > 0
    # Extract %b values from the last W-Bottom if found
    _w_pb1 = _w_pb2 = _w_mfi1 = _w_mfi2 = None
    if w_patterns:
        _lw = w_patterns[-1]
        _ww = df.iloc[-M3_W_LOOKBACK:]
        if _lw.start_idx < len(_ww) and _lw.end_idx < len(_ww):
            _w_pb1 = float(_ww.iloc[_lw.start_idx]["Percent_B"])
            _w_pb2 = float(_ww.iloc[_lw.end_idx]["Percent_B"])
            _w_mfi1 = float(_ww.iloc[_lw.start_idx]["MFI"])
            _w_mfi2 = float(_ww.iloc[_lw.end_idx]["MFI"])

    # M-Top: get data from last detected M pattern
    _m_found = len(m_patterns) > 0
    _m_recent = len(recent_m) > 0
    _m_pb1 = _m_pb2 = _m_mfi1 = _m_mfi2 = None
    if m_patterns:
        _lm = m_patterns[-1]
        _mw = df.iloc[-M3_W_LOOKBACK:]
        if _lm.start_idx < len(_mw) and _lm.end_idx < len(_mw):
            _m_pb1 = float(_mw.iloc[_lm.start_idx]["Percent_B"])
            _m_pb2 = float(_mw.iloc[_lm.end_idx]["Percent_B"])
            _m_mfi1 = float(_mw.iloc[_lm.start_idx]["MFI"])
            _m_mfi2 = float(_mw.iloc[_lm.end_idx]["MFI"])

    # ── Checklists ──
    buy_checklist = [
        {
            "ok": _w_found,
            "name": "W-Bottom Pattern Detected",
            "detail": f"{len(w_patterns)} W-Bottom(s) found in last {M3_W_LOOKBACK} days" if _w_found else f"No W-Bottom in last {M3_W_LOOKBACK} days",
            "explain": "A W-Bottom (double bottom) pattern must be present. Two lows separated by a rally form the classic 'W' shape.",
        },
        {
            "ok": _w_pb1 is not None and _w_pb1 <= M3_W_FIRST_LOW_PCT_B + 0.05,
            "name": "1st Low at/Below Lower Band",
            "detail": f"1st low %b: {_w_pb1:.3f} (need ≤ {M3_W_FIRST_LOW_PCT_B + 0.05:.2f})" if _w_pb1 is not None else "No pattern — N/A",
            "explain": "The first low must tag or pierce the lower Bollinger Band (%b near zero). This shows an initial oversold extreme.",
        },
        {
            "ok": _w_pb2 is not None and _w_pb2 > M3_W_SECOND_LOW_PCT_B,
            "name": "2nd Low ABOVE Lower Band",
            "detail": f"2nd low %b: {_w_pb2:.3f} (need > {M3_W_SECOND_LOW_PCT_B})" if _w_pb2 is not None else "No pattern — N/A",
            "explain": "The second low MUST hold above the lower band. This is the key — selling pressure is exhausted, buyers stepping in.",
        },
        {
            "ok": _w_mfi1 is not None and _w_mfi2 is not None and _w_mfi2 > _w_mfi1 + M3_MFI_DIVERGE_THRESHOLD,
            "name": "MFI Positive Divergence",
            "detail": f"MFI: {_w_mfi1:.0f} → {_w_mfi2:.0f} (need ↑ by >{M3_MFI_DIVERGE_THRESHOLD})" if _w_mfi1 is not None else "No pattern — N/A",
            "explain": "MFI must be HIGHER on the second low than the first. This divergence proves money is flowing in despite the retest.",
        },
        {
            "ok": _w_recent and pct_b > 0.3,
            "name": "%b Recovering — Price Moving Up",
            "detail": f"%b: {pct_b:.3f} (need > 0.30, recent pattern)",
            "explain": "After the W-Bottom completes, %b must rise above 0.30, confirming the reversal and the start of a new uptrend.",
        },
    ]

    sell_checklist = [
        {
            "ok": _m_found,
            "name": "M-Top Pattern Detected",
            "detail": f"{len(m_patterns)} M-Top(s) found in last {M3_W_LOOKBACK} days" if _m_found else f"No M-Top in last {M3_W_LOOKBACK} days",
            "explain": "An M-Top (double top) pattern must be present. Two highs separated by a pullback form the classic 'M' shape.",
        },
        {
            "ok": _m_pb1 is not None and _m_pb1 >= M3_M_FIRST_HIGH_PCT_B - 0.05,
            "name": "1st High at/Above Upper Band",
            "detail": f"1st high %b: {_m_pb1:.3f} (need ≥ {M3_M_FIRST_HIGH_PCT_B - 0.05:.2f})" if _m_pb1 is not None else "No pattern — N/A",
            "explain": "The first high must tag or pierce the upper Bollinger Band (%b near 1.0). This shows an initial overbought extreme.",
        },
        {
            "ok": _m_pb2 is not None and _m_pb2 < M3_M_SECOND_HIGH_PCT_B,
            "name": "2nd High BELOW Upper Band",
            "detail": f"2nd high %b: {_m_pb2:.3f} (need < {M3_M_SECOND_HIGH_PCT_B})" if _m_pb2 is not None else "No pattern — N/A",
            "explain": "The second high MUST fail to reach the upper band. This is the key — buying momentum is fading, sellers gaining control.",
        },
        {
            "ok": _m_mfi1 is not None and _m_mfi2 is not None and _m_mfi2 < _m_mfi1 - M3_MFI_DIVERGE_THRESHOLD,
            "name": "MFI Negative Divergence",
            "detail": f"MFI: {_m_mfi1:.0f} → {_m_mfi2:.0f} (need ↓ by >{M3_MFI_DIVERGE_THRESHOLD})" if _m_mfi1 is not None else "No pattern — N/A",
            "explain": "MFI must be LOWER on the second high than the first. This divergence proves money is flowing out despite the retest.",
        },
        {
            "ok": _m_recent and pct_b < 0.7,
            "name": "%b Declining — Price Weakening",
            "detail": f"%b: {pct_b:.3f} (need < 0.70, recent pattern)",
            "explain": "After the M-Top completes, %b must fall below 0.70, confirming the reversal and the start of a new downtrend.",
        },
    ]

    indicators = {
        "pct_b": round(pct_b, 4),
        "mfi": round(mfi, 2),
        "w_bottoms_found": len(w_patterns),
        "m_tops_found": len(m_patterns),
        "recent_w_bottoms": len(recent_w),
        "recent_m_tops": len(recent_m),
        "buy_checklist": buy_checklist,
        "sell_checklist": sell_checklist,
    }

    return StrategyResult(
        code="M3",
        name=STRATEGY_NAMES["M3"],
        description=STRATEGY_DESCRIPTIONS["M3"],
        signal=StrategySignal(
            signal_type=signal_type,
            strength=strength,
            confidence=confidence,
            reason=reason,
            details="\n".join(details_lines),
        ),
        patterns=all_patterns,
        indicators=indicators,
        book_reference="Chapter 17: 'W-Bottoms and M-Tops — the most important patterns.'",
    )


# ═══════════════════════════════════════════════════════════════
#  METHOD IV — WALKING THE BANDS
#  Book: Chapter 18
#  Core idea: In a strong trend, price repeatedly "walks" along
#  the upper or lower band. Each successive touch is a CONFIRMATION,
#  not a reversal signal.
#  "Tags of the band are just that — tags, not signals."
# ═══════════════════════════════════════════════════════════════

def _detect_band_walk(
    df: pd.DataFrame,
    band: str,
    lookback: int = M4_WALK_LOOKBACK,
) -> Optional[PatternMatch]:
    """
    Detect if price is 'walking' along a Bollinger Band.

    A walk is defined as:
    - `M4_WALK_MIN_TOUCHES` or more closes within tolerance of the band
      in the last `lookback` bars.
    - %b consistently in the extreme zone.
    """
    window = df.iloc[-lookback:]
    if len(window) < M4_WALK_MIN_TOUCHES:
        return None

    closes  = window["Close"].values.astype(float)
    pct_b   = window["Percent_B"].values.astype(float)
    dates   = window.index

    if band == "upper":
        band_vals = window["BB_Upper"].values.astype(float)
        touch_mask = np.abs(closes - band_vals) / band_vals <= M4_WALK_TOUCH_TOLERANCE
        zone_mask  = pct_b >= M4_WALK_PCT_B_UPPER
    else:
        band_vals = window["BB_Lower"].values.astype(float)
        touch_mask = np.abs(closes - band_vals) / band_vals <= M4_WALK_TOUCH_TOLERANCE
        zone_mask  = pct_b <= M4_WALK_PCT_B_LOWER

    # Also count closes ABOVE upper band or BELOW lower band
    if band == "upper":
        beyond_mask = closes > band_vals
    else:
        beyond_mask = closes < band_vals

    combined = touch_mask | zone_mask | beyond_mask
    touch_count = int(combined.sum())

    if touch_count >= M4_WALK_MIN_TOUCHES:
        direction = "upper" if band == "upper" else "lower"
        first_touch = np.argmax(combined)
        last_touch  = len(combined) - 1 - np.argmax(combined[::-1])

        desc = (
            f"Price is walking the {direction} Bollinger Band: "
            f"{touch_count} touches/closes in the {direction} zone "
            f"over the last {lookback} bars. "
        )
        if band == "upper":
            desc += (
                "The book says: 'Tags of the upper band during an uptrend are NOT "
                "sell signals — they CONFIRM the strength of the trend.' "
                "Continue holding until price fails to tag and pulls to the middle band."
            )
        else:
            desc += (
                "The book says: 'Tags of the lower band during a downtrend are NOT "
                "buy signals — they CONFIRM the trend is still bearish.' "
                "Stay out until price fails to tag and recovers to the middle band."
            )

        return PatternMatch(
            name=f"WALK-{direction.upper()}",
            start_idx=first_touch,
            end_idx=last_touch,
            start_date=dates[first_touch].strftime("%Y-%m-%d"),
            end_date=dates[last_touch].strftime("%Y-%m-%d"),
            description=desc,
        )

    return None


def _method_iv_walking_the_bands(df: pd.DataFrame) -> StrategyResult:
    """
    Method IV — Walking the Bands.

    The book's key insight: "Most traders treat a tag of the upper band
    as a sell signal and a tag of the lower band as a buy signal.
    THEY ARE WRONG. Tags during a strong trend confirm that trend."
    """
    if len(df) < M4_WALK_LOOKBACK:
        return StrategyResult(
            code="M4", name=STRATEGY_NAMES["M4"],
            description=STRATEGY_DESCRIPTIONS["M4"],
            signal=StrategySignal("NONE", "WEAK", 0,
                                  "Insufficient data",
                                  f"Need at least {M4_WALK_LOOKBACK} days."),
            book_reference="Chapter 18",
        )

    row   = df.iloc[-1]
    pct_b = _nan_safe(row["Percent_B"], 0.5)
    mfi   = _nan_safe(row["MFI"], 50.0)
    cmf   = _nan_safe(row["CMF"], 0.0)
    close = float(row["Close"])
    bb_upper = float(row["BB_Upper"])
    bb_lower = float(row["BB_Lower"])
    bb_mid   = float(row["BB_Mid"])
    sar_bull = bool(row["SAR_Bull"])

    upper_walk = _detect_band_walk(df, "upper")
    lower_walk = _detect_band_walk(df, "lower")

    patterns = []
    if upper_walk:
        patterns.append(upper_walk)
    if lower_walk:
        patterns.append(lower_walk)

    signal_type  = "NONE"
    strength     = "WEAK"
    confidence   = 0
    reason       = ""
    details_lines = []

    if upper_walk:
        # Walking upper band — strong uptrend
        if pct_b > 0.8 and sar_bull:
            signal_type = "HOLD"
            strength = "STRONG" if mfi > 60 else "MODERATE"
            confidence = min(int(70 + mfi * 0.3), 100)
            reason = "Walking the upper band — strong uptrend, HOLD"
            details_lines.append(upper_walk.description)
            details_lines.append(
                f"Current %b: {pct_b:.2f}. SAR dots are below candles (bullish). "
                "DO NOT sell just because price is touching the upper band. "
                "Exit only when price closes below the middle band."
            )
        elif pct_b < 0.5:
            # Walk is breaking — price pulled back to middle band
            signal_type = "SELL"
            strength = "MODERATE"
            confidence = 60
            reason = "Upper band walk breaking — price fell to middle band"
            details_lines.append(
                f"Price was walking the upper band but has now pulled back to %b = {pct_b:.2f}. "
                "The book says: 'When the walk ends and price closes below the middle band, "
                "the trend has changed. Take profits.'"
            )
        else:
            signal_type = "WATCH"
            strength = "MODERATE"
            confidence = 50
            reason = "Upper band walk with weakening momentum"
            details_lines.append(upper_walk.description)
            details_lines.append(
                f"Price is still above the middle band (%b = {pct_b:.2f}) but "
                "not firmly at the upper band anymore. Watch closely."
            )

    elif lower_walk:
        # Walking lower band — strong downtrend
        if pct_b < 0.2 and not sar_bull:
            signal_type = "SELL"
            strength = "STRONG" if mfi < 40 else "MODERATE"
            confidence = min(int(70 + (100 - mfi) * 0.3), 100)
            reason = "Walking the lower band — strong downtrend, SELL/AVOID"
            details_lines.append(lower_walk.description)
            details_lines.append(
                f"Current %b: {pct_b:.2f}. SAR dots are above candles (bearish). "
                "DO NOT buy just because price is touching the lower band. "
                "Wait until price recovers above the middle band."
            )
        elif pct_b > 0.5:
            # Walk is breaking — price recovered to middle band
            signal_type = "BUY"
            strength = "MODERATE"
            confidence = 60
            reason = "Lower band walk breaking — price recovered to middle band"
            details_lines.append(
                f"Price was walking the lower band but has now recovered to %b = {pct_b:.2f}. "
                "The book says: 'When the walk ends and price closes above the middle band, "
                "the downtrend has changed. Consider buying.'"
            )
        else:
            signal_type = "WATCH"
            strength = "MODERATE"
            confidence = 45
            reason = "Lower band walk with improving momentum"
            details_lines.append(lower_walk.description)

    else:
        # No walk detected
        reason = "No band walk detected"
        if pct_b > 0.7:
            details_lines.append(
                f"Price is near the upper band (%b = {pct_b:.2f}) but not consistently "
                f"walking it (fewer than {M4_WALK_MIN_TOUCHES} touches in {M4_WALK_LOOKBACK} bars). "
                "May develop into a walk if trend strengthens."
            )
        elif pct_b < 0.3:
            details_lines.append(
                f"Price is near the lower band (%b = {pct_b:.2f}) but not consistently "
                f"walking it. A lower band walk (bearish) would need {M4_WALK_MIN_TOUCHES}+ "
                f"touches in {M4_WALK_LOOKBACK} bars."
            )
        else:
            details_lines.append(
                f"Price is in the middle of the bands (%b = {pct_b:.2f}). "
                "No walking pattern detected. This is a neutral zone."
            )

    # ── Checklists ──
    _upper_active = upper_walk is not None
    _lower_active = lower_walk is not None

    buy_checklist = [
        {
            "ok": _lower_active,
            "name": "Lower Band Walk Detected",
            "detail": f"Lower walk: {'ACTIVE' if _lower_active else 'Not detected'} (need ≥{M4_WALK_MIN_TOUCHES} touches in {M4_WALK_LOOKBACK} bars)",
            "explain": "Price must have been 'walking' the lower band (3+ touches in 10 bars). This confirms a prior downtrend existed.",
        },
        {
            "ok": _lower_active and pct_b > 0.5,
            "name": "Walk Breaking — %b Recovering Above 0.50",
            "detail": f"%b: {pct_b:.3f} (need > 0.50)",
            "explain": "Price must recover above the middle of the bands. When the lower walk breaks and %b crosses 0.50, the downtrend is ending.",
        },
        {
            "ok": close > bb_mid,
            "name": "Price Above Middle Bollinger Band",
            "detail": f"Close: ₹{close:.2f} · Mid: ₹{bb_mid:.2f}",
            "explain": "Price must close above the 20-day SMA (middle band). This confirms the trend reversal from bearish to bullish.",
        },
        {
            "ok": sar_bull,
            "name": "SAR Bullish — Dots Below Candles",
            "detail": f"SAR: {'↑ Bullish (dots below)' if sar_bull else '↓ Bearish (dots above)'}",
            "explain": "Parabolic SAR must flip bullish (dots below candles). This is trend confirmation from a separate indicator.",
        },
        {
            "ok": mfi > 50,
            "name": "MFI Above 50 — Buying Pressure",
            "detail": f"MFI: {mfi:.1f} (need > 50)",
            "explain": "Money Flow Index must be above 50, showing buying pressure is returning. This confirms the trend change.",
        },
    ]

    sell_checklist = [
        {
            "ok": _upper_active,
            "name": "Upper Band Walk Detected",
            "detail": f"Upper walk: {'ACTIVE' if _upper_active else 'Not detected'} (need ≥{M4_WALK_MIN_TOUCHES} touches in {M4_WALK_LOOKBACK} bars)",
            "explain": "Price must have been 'walking' the upper band. Tags during an uptrend are NOT sell signals — they CONFIRM the trend.",
        },
        {
            "ok": _upper_active and pct_b < 0.5,
            "name": "Walk Breaking — %b Falling Below 0.50",
            "detail": f"%b: {pct_b:.3f} (need < 0.50)",
            "explain": "Price must fall below the middle of the bands. When the upper walk breaks and %b drops below 0.50, the uptrend is over.",
        },
        {
            "ok": close < bb_mid,
            "name": "Price Below Middle Bollinger Band",
            "detail": f"Close: ₹{close:.2f} · Mid: ₹{bb_mid:.2f}",
            "explain": "Price must close below the 20-day SMA (middle band). The book says: 'Take profits when the walk ends.'",
        },
        {
            "ok": not sar_bull,
            "name": "SAR Bearish — Dots Above Candles",
            "detail": f"SAR: {'↑ Bullish (dots below)' if sar_bull else '↓ Bearish (dots above)'}",
            "explain": "Parabolic SAR must flip bearish (dots above candles). This confirms the trend has changed from bullish to bearish.",
        },
        {
            "ok": mfi < 50,
            "name": "MFI Below 50 — Selling Pressure",
            "detail": f"MFI: {mfi:.1f} (need < 50)",
            "explain": "Money Flow Index must be below 50, showing selling pressure is building. Institutions are reducing positions.",
        },
    ]

    indicators = {
        "pct_b": round(pct_b, 4),
        "mfi": round(mfi, 2),
        "cmf": round(cmf, 4),
        "sar_bull": sar_bull,
        "upper_walk_active": upper_walk is not None,
        "lower_walk_active": lower_walk is not None,
        "price_vs_upper": round(close / bb_upper, 4) if bb_upper else None,
        "price_vs_lower": round(close / bb_lower, 4) if bb_lower else None,
        "price_vs_mid": round(close / bb_mid, 4) if bb_mid else None,
        "buy_checklist": buy_checklist,
        "sell_checklist": sell_checklist,
    }

    return StrategyResult(
        code="M4",
        name=STRATEGY_NAMES["M4"],
        description=STRATEGY_DESCRIPTIONS["M4"],
        signal=StrategySignal(
            signal_type=signal_type,
            strength=strength,
            confidence=confidence,
            reason=reason,
            details="\n".join(details_lines),
        ),
        patterns=patterns,
        indicators=indicators,
        book_reference="Chapter 18: 'Tags of the band are tags, not signals.'",
    )


# ═══════════════════════════════════════════════════════════════
#  PUBLIC API — Run All Strategies
# ═══════════════════════════════════════════════════════════════

def run_all_strategies(df: pd.DataFrame) -> List[StrategyResult]:
    """
    Run all three additional strategies on the enriched DataFrame.
    Returns a list of StrategyResult objects.

    The existing squeeze (Method I) is NOT included here — it runs
    through the existing signals.py pipeline as before.  This function
    only adds Methods II, III, and IV.
    """
    results: List[StrategyResult] = []

    # Method II — Trend Following
    results.append(_method_ii_trend_following(df))

    # Method III — Reversals
    results.append(_method_iii_reversals(df))

    # Method IV — Walking the Bands
    results.append(_method_iv_walking_the_bands(df))

    return results


def _sanitize(obj):
    """Recursively replace NaN/Inf floats with None for valid JSON."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    return obj


def strategy_result_to_dict(sr: StrategyResult) -> dict:
    """Convert a StrategyResult to a JSON-serialisable dictionary."""
    return _sanitize({
        "code":           sr.code,
        "name":           sr.name,
        "description":    sr.description,
        "book_reference": sr.book_reference,
        "signal": {
            "type":       sr.signal.signal_type,
            "strength":   sr.signal.strength,
            "confidence": sr.signal.confidence,
            "reason":     sr.signal.reason,
            "details":    sr.signal.details,
        },
        "patterns": [
            {
                "name":        p.name,
                "start_date":  p.start_date,
                "end_date":    p.end_date,
                "description": p.description,
            }
            for p in sr.patterns
        ],
        "indicators": sr.indicators,
    })
