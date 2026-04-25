"""
signals.py — Signal engine implementing ALL 5 buy conditions, 3 exit signals,
and head-fake detection as described in the Bollinger Band Squeeze Strategy Guide.
"""

import pandas as pd
import numpy as np
import math
from dataclasses import dataclass, field
from typing import Optional
from bb_squeeze.config import (
    CMF_UPPER_LINE, CMF_LOWER_LINE,
    MFI_OVERBOUGHT, MFI_OVERSOLD, MFI_MID,
    PERCENT_B_MID,
    SCORE_BBW_SQUEEZE, SCORE_PRICE_BREAKOUT,
    SCORE_VOLUME_CONFIRM, SCORE_CMF_POSITIVE,
    SCORE_MFI_ABOVE_50, SCORE_CMF_ABOVE_10, SCORE_MFI_ABOVE_80,
)


def _nan_safe(val, default=0.0):
    """Convert to float, replacing NaN/Inf with default."""
    try:
        v = float(val)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except (ValueError, TypeError):
        return default


@dataclass
class SignalResult:
    """Complete signal analysis result for a single stock."""
    ticker: str

    # ── Phase Identification ──
    phase: str = "UNKNOWN"          # "COMPRESSION" | "DIRECTION" | "EXPLOSION" | "POST-BREAKOUT"

    # ── 5 Buy Conditions ──
    cond1_squeeze_on:   bool = False  # BBW at trigger line
    cond2_price_above:  bool = False  # Close above upper BB
    cond3_volume_ok:    bool = False  # Volume green & above 50 SMA
    cond4_cmf_positive: bool = False  # CMF > 0
    cond5_mfi_above_50: bool = False  # MFI > 50 and rising

    # ── Signal Types ──
    buy_signal:    bool = False
    hold_signal:   bool = False
    sell_signal:   bool = False
    wait_signal:   bool = False
    head_fake:     bool = False

    # ── Exit Triggers ──
    exit_sar_flip:       bool = False  # SAR flip (primary exit)
    exit_lower_band_tag: bool = False  # Price touches lower BB (max-profit exit)
    exit_double_neg:     bool = False  # CMF < 0 AND MFI < 50 (early warning)

    # ── Confidence Score (0–100) ──
    confidence: int = 0

    # ── Latest Indicator Values ──
    current_price:  float = 0.0
    bb_upper:       float = 0.0
    bb_mid:         float = 0.0
    bb_lower:       float = 0.0
    bbw:            float = 0.0
    bbw_6m_min:     float = 0.0
    percent_b:      float = 0.0
    sar:            float = 0.0
    sar_bull:       bool  = False
    volume:         float = 0.0
    vol_sma50:      float = 0.0
    cmf:            float = 0.0
    mfi:            float = 0.0

    # ── Book Ch.18 — New Volume Indicators ──
    ii_pct:         float = 0.0   # Intraday Intensity %  (II%)
    ad_pct:         float = 0.0   # Accumulation Distribution %  (AD%)
    vwmacd_hist:    float = 0.0   # VWMACD histogram

    # ── Book Ch.15 — Expansion ──
    expansion_up:   bool  = False  # Lower band falling in uptrend
    expansion_down: bool  = False  # Upper band rising in downtrend
    expansion_end:  bool  = False  # Expansion reversing → end-of-trend

    # ── Book Ch.21 — Normalised Indicators ──
    rsi_norm:       float = 0.5   # %b of RSI (adaptive OB/OS)
    mfi_norm:       float = 0.5   # %b of MFI (adaptive OB/OS)

    # ── Method I Short-Side (Book Ch.16) ──
    short_signal:   bool  = False  # Bearish squeeze breakout
    cond_short_squeeze: bool = False
    cond_short_price:   bool = False
    cond_short_volume:  bool = False
    cond_short_ii_neg:  bool = False
    cond_short_mfi_low: bool = False

    # ── Direction Lean ──
    direction_lean: str = "NEUTRAL"    # "BULLISH" | "BEARISH" | "NEUTRAL"

    # ── Human-readable summary ──
    summary:        str = ""
    action_message: str = ""
    stop_loss:      float = 0.0
    squeeze_days:   int  = 0           # How many consecutive days in squeeze


def _phase_detection(row: pd.Series, prev_rows: pd.DataFrame) -> str:
    """Identify which phase (1/2/3) the stock is currently in."""
    squeeze_on = bool(row.get("Squeeze_ON", False))
    bbw        = float(row.get("BBW", 1.0))
    bbw_prev   = float(prev_rows["BBW"].iloc[-5:].mean()) if len(prev_rows) >= 5 else bbw
    close      = float(row.get("Close", 0))
    bb_upper   = float(row.get("BB_Upper", 0))
    bb_lower   = float(row.get("BB_Lower", 0))

    if not squeeze_on:
        if close > bb_upper:
            return "EXPLOSION"
        elif close < bb_lower:
            return "EXPLOSION"    # Downside explosion
        return "NORMAL"

    # Squeeze is ON
    cmf = float(row.get("CMF", 0))
    mfi = float(row.get("MFI", 50))
    pct_b = float(row.get("Percent_B", 0.5))

    # If we see direction clues — Phase 2
    if abs(cmf) > 0.05 or abs(mfi - 50) > 10 or abs(pct_b - 0.5) > 0.15:
        return "DIRECTION"

    return "COMPRESSION"


def _count_squeeze_days(df: pd.DataFrame) -> int:
    """Count consecutive days the stock has been in squeeze."""
    squeeze_series = df["Squeeze_ON"].astype(bool)
    # Walk backwards from last row
    count = 0
    for val in reversed(squeeze_series.values):
        if val:
            count += 1
        else:
            break
    return count


def _direction_lean(row: pd.Series) -> str:
    """Determine bullish/bearish lean during squeeze (Phase 2 analysis)."""
    cmf    = float(row.get("CMF", 0))
    mfi    = float(row.get("MFI", 50))
    pct_b  = float(row.get("Percent_B", 0.5))
    volume = float(row.get("Volume", 0))
    vol_sma = float(row.get("Vol_SMA50", 1))

    bull_score = 0
    bear_score = 0

    # CMF direction (most important)
    if cmf > CMF_UPPER_LINE:
        bull_score += 3
    elif cmf > 0:
        bull_score += 1
    elif cmf < CMF_LOWER_LINE:
        bear_score += 3
    elif cmf < 0:
        bear_score += 1

    # MFI
    if mfi > 60:
        bull_score += 2
    elif mfi > 50:
        bull_score += 1
    elif mfi < 40:
        bear_score += 2
    elif mfi < 50:
        bear_score += 1

    # %b position
    if pct_b > PERCENT_B_MID:
        bull_score += 1
    else:
        bear_score += 1

    # II% — Book Ch.18: primary directional clue for squeeze breakouts
    ii_pct = float(row.get("II_Pct", 0))
    if ii_pct > 0:
        bull_score += 2
    elif ii_pct < 0:
        bear_score += 2

    # VWMACD histogram — Book Ch.18: closed-form directional clue
    vwmacd_hist = float(row.get("VWMACD_Hist", 0))
    if vwmacd_hist > 0:
        bull_score += 1
    elif vwmacd_hist < 0:
        bear_score += 1

    if bull_score > bear_score + 1:
        return "BULLISH"
    elif bear_score > bull_score + 1:
        return "BEARISH"
    return "NEUTRAL"


def _head_fake_check(row: pd.Series) -> bool:
    """
    Golden Head Fake Filter Rules (from the strategy guide):
    Returns True if this breakout looks like a HEAD FAKE.
    """
    close    = float(row.get("Close", 0))
    high_val = float(row.get("High", 0))
    bb_upper = float(row.get("BB_Upper", 0))
    volume   = float(row.get("Volume", 0))
    vol_sma  = float(row.get("Vol_SMA50", 1))
    cmf      = float(row.get("CMF", 0))
    mfi      = float(row.get("MFI", 50))
    bbw      = float(row.get("BBW", 0))
    bbw_6m   = float(row.get("BBW_6M_Min", bbw))

    head_fake_signals = 0

    # 1. Volume below yellow line (most powerful filter — eliminates 80% of fakes)
    if volume < vol_sma:
        head_fake_signals += 1

    # 2. CMF negative on upside breakout
    if close > bb_upper and cmf < 0:
        head_fake_signals += 1

    # 3. MFI below 50 on upside breakout
    if close > bb_upper and mfi < 50:
        head_fake_signals += 1

    # 4. BBW not expanding after supposed breakout (bands not widening)
    if bbw < bbw_6m * 1.02 and close > bb_upper:
        head_fake_signals += 1

    # 5. Long upper wick rejection (wick > 60% of candle range)
    open_val = float(row.get("Open", close))
    candle_range = high_val - float(row.get("Low", close))
    if candle_range > 0:
        body_top  = max(open_val, close)
        upper_wick = high_val - body_top
        if upper_wick / candle_range > 0.6:
            head_fake_signals += 1

    return head_fake_signals >= 2   # 2+ signals = likely head fake


def analyze_signals(ticker: str, df: pd.DataFrame) -> SignalResult:
    """
    Core signal engine.
    Evaluates ALL 5 buy conditions, 3 exit signals, and head-fake detection.
    Returns a complete SignalResult object.
    """
    result = SignalResult(ticker=ticker)

    if df is None or len(df) < 50:
        result.phase   = "INSUFFICIENT_DATA"
        result.summary = "Not enough data for analysis."
        return result

    # Latest row and recent history
    row      = df.iloc[-1]
    prev_df  = df.iloc[:-1]

    # ── Extract latest values ──
    result.current_price = float(row.get("Close", 0))
    result.bb_upper      = float(row.get("BB_Upper", 0))
    result.bb_mid        = float(row.get("BB_Mid", 0))
    result.bb_lower      = float(row.get("BB_Lower", 0))
    result.bbw           = _nan_safe(row.get("BBW", 0), 0)
    result.bbw_6m_min    = _nan_safe(row.get("BBW_6M_Min", result.bbw), result.bbw)
    result.percent_b     = _nan_safe(row.get("Percent_B", 0.5), 0.5)
    result.sar           = float(row.get("SAR", 0))
    result.sar_bull      = bool(row.get("SAR_Bull", False))
    result.volume        = _nan_safe(row.get("Volume", 0), 0)
    result.vol_sma50     = _nan_safe(row.get("Vol_SMA50", 0), 0)
    result.cmf           = _nan_safe(row.get("CMF", 0), 0)
    result.mfi           = _nan_safe(row.get("MFI", 50), 50)

    # ── New Book Indicators (Ch.18, Ch.15, Ch.21) ──
    result.ii_pct        = _nan_safe(row.get("II_Pct", 0), 0)
    result.ad_pct        = _nan_safe(row.get("AD_Pct", 0), 0)
    result.vwmacd_hist   = _nan_safe(row.get("VWMACD_Hist", 0), 0)
    result.expansion_up  = bool(row.get("Expansion_Up", False))
    result.expansion_down = bool(row.get("Expansion_Down", False))
    result.expansion_end = bool(row.get("Expansion_End", False))
    result.rsi_norm      = _nan_safe(row.get("RSI_Norm", 0.5), 0.5)
    result.mfi_norm      = _nan_safe(row.get("MFI_Norm", 0.5), 0.5)

    # ── Phase Detection ──
    result.phase         = _phase_detection(row, prev_df)
    result.direction_lean = _direction_lean(row)
    result.squeeze_days  = _count_squeeze_days(df)

    # ──────────────────────────────────────────────────────────
    # 5 BUY CONDITIONS (ALL FIVE must be GREEN)
    # ──────────────────────────────────────────────────────────

    # Condition 1 — BBW at squeeze trigger
    result.cond1_squeeze_on = bool(row.get("Squeeze_ON", False))

    # Condition 2 — Price candle CLOSES above upper Bollinger Band
    result.cond2_price_above = result.current_price > result.bb_upper

    # Condition 3 — Volume is GREEN (up day) AND above 50 SMA
    prev_close = float(prev_df["Close"].iloc[-1]) if len(prev_df) >= 1 else result.current_price
    is_green_candle      = result.current_price >= prev_close
    vol_above_sma        = result.volume > result.vol_sma50
    result.cond3_volume_ok = is_green_candle and vol_above_sma

    # Condition 4 — CMF above zero (ideally > +0.10)
    result.cond4_cmf_positive = result.cmf > 0

    # Condition 5 — MFI above 50 and rising
    prev_mfi = float(prev_df["MFI"].iloc[-1]) if len(prev_df) >= 1 else result.mfi
    mfi_rising = result.mfi > prev_mfi
    result.cond5_mfi_above_50 = (result.mfi > MFI_MID) and mfi_rising

    # ──────────────────────────────────────────────────────────
    # CONFIDENCE SCORE CALCULATION
    # ──────────────────────────────────────────────────────────
    score = 0
    if result.cond1_squeeze_on:   score += SCORE_BBW_SQUEEZE
    if result.cond2_price_above:  score += SCORE_PRICE_BREAKOUT
    if result.cond3_volume_ok:    score += SCORE_VOLUME_CONFIRM
    if result.cond4_cmf_positive: score += SCORE_CMF_POSITIVE
    if result.cond5_mfi_above_50: score += SCORE_MFI_ABOVE_50
    # Bonus
    if result.cmf > CMF_UPPER_LINE:  score += SCORE_CMF_ABOVE_10
    if result.mfi > MFI_OVERBOUGHT:  score += SCORE_MFI_ABOVE_80
    result.confidence = min(score, 100)

    # ──────────────────────────────────────────────────────────
    # HEAD FAKE DETECTION
    # ──────────────────────────────────────────────────────────
    if result.cond2_price_above:
        result.head_fake = _head_fake_check(row)

    # ──────────────────────────────────────────────────────────
    # BUY SIGNAL — ALL 5 CONDITIONS + NO HEAD FAKE
    # ──────────────────────────────────────────────────────────
    all_five_green = (
        result.cond1_squeeze_on and
        result.cond2_price_above and
        result.cond3_volume_ok and
        result.cond4_cmf_positive and
        result.cond5_mfi_above_50
    )
    result.buy_signal = all_five_green and not result.head_fake

    # ──────────────────────────────────────────────────────────
    # METHOD I SHORT-SIDE — Bearish Squeeze Breakout (Book Ch.16)
    # "A short sale signal is triggered by falling below the lower
    #  band after a Squeeze."
    # ──────────────────────────────────────────────────────────
    result.cond_short_squeeze = result.cond1_squeeze_on
    result.cond_short_price   = result.current_price < result.bb_lower

    prev_close_short = float(prev_df["Close"].iloc[-1]) if len(prev_df) >= 1 else result.current_price
    is_red_candle     = result.current_price < prev_close_short
    result.cond_short_volume = is_red_candle and vol_above_sma

    result.cond_short_ii_neg  = result.ii_pct < 0    # II% negative = distribution (Book Ch.18)
    result.cond_short_mfi_low = result.mfi < MFI_MID # MFI below 50 = weak buying

    short_conditions_met = (
        result.cond_short_squeeze and
        result.cond_short_price and
        result.cond_short_volume and
        result.cond_short_ii_neg and
        result.cond_short_mfi_low
    )
    result.short_signal = short_conditions_met

    # ──────────────────────────────────────────────────────────
    # STOP LOSS — Parabolic SAR
    # ──────────────────────────────────────────────────────────
    result.stop_loss = result.sar

    # ──────────────────────────────────────────────────────────
    # HOLD SIGNAL — Already in a trade, trend still intact
    # Signs trend is intact (from trade management section)
    # ──────────────────────────────────────────────────────────
    sar_below        = result.sar_bull                      # SAR dots below candles
    price_above_mid  = result.current_price > result.bb_mid # Price above 20 SMA
    cmf_positive     = result.cmf > 0
    mfi_above_40     = result.mfi > 40
    bbw_expanding    = result.bbw > float(prev_df["BBW"].iloc[-1]) if len(prev_df) >= 1 else True

    result.hold_signal = (
        sar_below and
        price_above_mid and
        cmf_positive and
        mfi_above_40
    )

    # ──────────────────────────────────────────────────────────
    # 3 EXIT SIGNALS — ONE IS ENOUGH
    # ──────────────────────────────────────────────────────────

    # Exit Signal 1 — SAR Flip (Primary Exit)
    # Price closed BELOW the Parabolic SAR dot
    result.exit_sar_flip = (not result.sar_bull) and (result.current_price < result.sar)

    # Exit Signal 2 — Tag of Opposite (Lower) Band
    # Price touches or crosses lower BB
    result.exit_lower_band_tag = result.current_price <= result.bb_lower

    # Exit Signal 3 — Double Negative (Early Warning)
    # CMF drops below zero AND MFI drops below 50 simultaneously
    cmf_below_zero = result.cmf < 0
    mfi_below_50   = result.mfi < 50
    result.exit_double_neg = cmf_below_zero and mfi_below_50

    # Exit Signal 4 — Expansion End (Book Ch.15 p.123)
    # When a prior Expansion reverses, the trend is at an end.
    exit_expansion_end = result.expansion_end

    # Sell signal logic:
    # In squeeze-related phases, a single exit trigger is enough (we're in a trade).
    # In NORMAL phase (no squeeze context), require stronger evidence:
    #   - at least 2 exit conditions firing, OR
    #   - SAR flip + price below mid band (confirmed downtrend)
    # This prevents the system from flooding SELL signals on every normal stock.
    exit_count = sum([result.exit_sar_flip, result.exit_lower_band_tag, result.exit_double_neg, exit_expansion_end])
    is_squeeze_context = result.phase in ("COMPRESSION", "DIRECTION", "EXPLOSION", "POST-BREAKOUT")

    if is_squeeze_context:
        # In squeeze context: any single exit triggers SELL
        result.sell_signal = exit_count >= 1
    else:
        # NORMAL phase: need stronger evidence to declare SELL
        strong_sell = exit_count >= 2
        confirmed_downtrend = (result.exit_sar_flip and
                               result.current_price < result.bb_mid and
                               result.percent_b < 0.3)
        result.sell_signal = strong_sell or confirmed_downtrend

    # Sell takes priority over hold — you can't hold if exit conditions met
    if result.sell_signal:
        result.hold_signal = False

    # Wait signal — squeeze is on but no breakout yet
    result.wait_signal = (
        result.cond1_squeeze_on and
        not result.buy_signal and
        not result.sell_signal and
        not result.hold_signal
    )

    # Fallback: if no signal is set, default to WAIT
    # This covers the case where there's no squeeze, no hold conditions,
    # and no sell conditions — stock is in a normal state, no action needed.
    if not any([result.buy_signal, result.hold_signal,
                result.sell_signal, result.wait_signal]):
        result.wait_signal = True

    # ──────────────────────────────────────────────────────────
    # BUILD HUMAN-READABLE MESSAGES
    # ──────────────────────────────────────────────────────────
    result.summary = _build_summary(result)
    result.action_message = _build_action(result)

    return result


def _build_summary(r: SignalResult) -> str:
    """Build a concise one-line summary of the stock's current state."""
    phase_desc = {
        "COMPRESSION": "🔵 In Squeeze (Spring Coiling — Low Volatility)",
        "DIRECTION":   "🟡 In Squeeze with Direction Clues Forming",
        "EXPLOSION":   "🔴 Squeeze Released — Band Expansion Happening",
        "NORMAL":      "⚪ No Active Squeeze",
        "POST-BREAKOUT": "🟢 Post-Breakout Trend in Progress",
        "INSUFFICIENT_DATA": "❓ Insufficient Data",
    }
    return phase_desc.get(r.phase, f"Phase: {r.phase}")


def _build_action(r: SignalResult) -> str:
    """Build the plain-English action message the user needs to act on."""
    if r.phase == "INSUFFICIENT_DATA":
        return "Not enough historical data to analyze this stock."

    if r.buy_signal:
        mfi_strength = ""
        if r.mfi > MFI_OVERBOUGHT:
            mfi_strength = " Enter FULL position — MFI shows maximum fuel."
        elif r.mfi > MFI_MID:
            mfi_strength = " MFI moderate — consider half position."
        return (
            f"✅ BUY SIGNAL — Enter at tomorrow's market open (or today's close).{mfi_strength}\n"
            f"   Stop Loss: ₹{r.stop_loss:.2f} (Parabolic SAR). Exit if price closes below this."
        )

    if r.short_signal:
        return (
            f"🔻 SHORT SIGNAL (Method I Bearish Breakout) — Price broke below lower band from Squeeze.\n"
            f"   II% = {r.ii_pct:+.4f} (distribution), MFI = {r.mfi:.0f} (weak buying).\n"
            f"   Stop Loss: ₹{r.stop_loss:.2f} (Parabolic SAR). Cover if price closes above this."
        )

    if r.head_fake and r.cond2_price_above:
        return (
            "⚠️  HEAD FAKE DETECTED — Do NOT enter. One or more confirming indicators are contradicting "
            "the breakout. Wait 2-3 days. The REAL move will come in the opposite direction "
            "with all 5 conditions confirmed."
        )

    if r.sell_signal:
        reasons = []
        if r.exit_sar_flip:
            reasons.append("SAR Flip (price closed below SAR dot)")
        if r.exit_lower_band_tag:
            reasons.append("Price tagged/crossed lower Bollinger Band")
        if r.exit_double_neg:
            reasons.append("CMF below 0 AND MFI below 50 (double negative = fuel exhausted)")
        if r.expansion_end:
            reasons.append("Band Expansion reversing (Ch.15 — trend at an end)")
        return (
            f"🔴 SELL / EXIT SIGNAL — Exit at tomorrow's market open.\n"
            f"   Reason(s): {' | '.join(reasons)}"
        )

    if r.hold_signal:
        return (
            f"🟢 HOLD — Trend is intact. SAR dots below candles. Stay in the trade.\n"
            f"   Trailing Stop Loss (SAR): ₹{r.stop_loss:.2f}. Exit if price closes below this."
        )

    if r.wait_signal:
        lean = r.direction_lean
        direction_msg = {
            "BULLISH": "Direction clues lean BULLISH — prepare for upside breakout.",
            "BEARISH": "Direction clues lean BEARISH — possible downside breakout ahead.",
            "NEUTRAL": "No clear direction yet. Continue watching.",
        }.get(lean, "")
        missing = []
        if not r.cond2_price_above:  missing.append("price hasn't broken above upper band")
        if not r.cond3_volume_ok:    missing.append("volume not confirmed")
        if not r.cond4_cmf_positive: missing.append("CMF not positive")
        if not r.cond5_mfi_above_50: missing.append("MFI below 50")
        return (
            f"⏳ WAIT — Squeeze is SET. {direction_msg}\n"
            f"   Not ready yet: {', '.join(missing) if missing else 'continue monitoring'}.\n"
            f"   Squeeze has been building for {r.squeeze_days} day(s). Stay alert."
        )

    # No squeeze, no signal
    phase_msg = {
        "NORMAL": "No squeeze detected. BBW is not at 6-month low. No trade setup present.",
        "EXPLOSION": "Bands are expanding. If you're already in — check exit conditions.",
    }
    return phase_msg.get(r.phase, "Monitor this stock for a squeeze setup to develop.")
