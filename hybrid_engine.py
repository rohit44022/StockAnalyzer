"""
hybrid_engine.py — Hybrid Bollinger Band + Technical Analysis Conviction Engine.

Combines John Bollinger's 4 BB Methods with John Murphy's Technical Analysis
framework to create a HIGH-CONVICTION trading signal system.

Philosophy:
  - Bollinger Bands tell you WHAT is happening (squeeze, breakout, trend, reversal)
  - Technical Analysis tells you WHY (momentum, volume, patterns, risk)
  - Together they confirm or invalidate each other → STRONGER conviction

Architecture:
  1. Run all 4 BB Methods (I: Squeeze, II: Trend, III: Reversal, IV: Walk)
  2. Run full Technical Analysis (Murphy's 6 categories)
  3. Cross-validate signals: BB signal + TA confirmation = HIGH conviction
  4. Produce unified verdict with detailed explanations

Scoring System (200 points max):
  - Bollinger Band Score:    100 points (4 methods)
  - Technical Analysis Score: 100 points (6 categories)
  - CONVICTION = agreement between the two systems
"""

from __future__ import annotations
import math
import numpy as np
import pandas as pd
from typing import Optional

from bb_squeeze.indicators import compute_all_indicators as compute_bb_indicators
from bb_squeeze.signals import analyze_signals as generate_bb_signal
from bb_squeeze.strategies import run_all_strategies, strategy_result_to_dict

from technical_analysis.indicators import (
    compute_all_ta_indicators,
    get_indicator_snapshot,
    detect_ma_crossovers,
    detect_all_divergences,
    compute_pivot_points,
    compute_fibonacci,
)
from technical_analysis.candlesticks import scan_candlestick_patterns
from technical_analysis.patterns import (
    detect_support_resistance,
    identify_trend,
    detect_all_chart_patterns,
    analyze_volume,
    analyze_ichimoku,
)
from technical_analysis.signals import generate_signal as generate_ta_signal
from technical_analysis.risk_manager import generate_risk_report
from technical_analysis.target_price import calculate_target_prices
from bb_squeeze.data_loader import get_data_freshness


def _safe(v):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return None
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        v = float(v)
        if math.isnan(v) or math.isinf(v):
            return None
    return v


def _safe_json(obj):
    if isinstance(obj, dict):
        return {k: _safe_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_safe_json(v) for v in obj]
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    if isinstance(obj, np.ndarray):
        return _safe_json(obj.tolist())
    return obj


# ═══════════════════════════════════════════════════════════════
#  BOLLINGER BAND SCORING (100 points)
# ═══════════════════════════════════════════════════════════════

def _score_bb_method_1(bb_signal) -> dict:
    """
    Method I — Volatility Squeeze Breakout (40 points max).
    The CORE strategy: squeeze builds energy → breakout releases it.
    """
    score = 0.0
    details = []

    if bb_signal.buy_signal:
        score += 30
        details.append(f"✅ BUY SIGNAL ACTIVE — All conditions met (Confidence: {bb_signal.confidence}%)")
    elif bb_signal.head_fake:
        score -= 20
        details.append("❌ HEAD FAKE detected — breakout is likely false")
    elif bb_signal.cond1_squeeze_on:
        details.append("⏳ Squeeze is ON — waiting for breakout")
        if bb_signal.direction_lean == "BULLISH":
            score += 10
            details.append("✅ Direction lean: BULLISH (CMF/MFI/Volume favour upside)")
        elif bb_signal.direction_lean == "BEARISH":
            score -= 10
            details.append("❌ Direction lean: BEARISH (CMF/MFI/Volume favour downside)")
    elif bb_signal.sell_signal:
        score -= 25
        details.append("🔴 SELL/EXIT signal — SAR flip or band tag")

    # Individual conditions
    if bb_signal.cond2_price_above:
        score += 5
        details.append("✅ Price above upper BB (breakout confirmed)")
    if bb_signal.cond3_volume_ok:
        score += 3
        details.append("✅ Volume above 50-SMA (real participation)")
    if bb_signal.cond4_cmf_positive:
        score += 2
        details.append("✅ CMF positive (money flowing in)")
    if bb_signal.cond5_mfi_above_50:
        score += 2
        details.append("✅ MFI > 50 (buying pressure)")

    # Exit signals reduce score
    if bb_signal.exit_sar_flip:
        score -= 10
        details.append("⚠️ SAR has flipped bearish (exit signal)")
    if bb_signal.exit_double_neg:
        score -= 5
        details.append("⚠️ Double negative: CMF < 0 AND MFI < 50")

    score = max(-40, min(40, score))
    return {
        "score": round(score, 1),
        "max": 40,
        "method": "Method I — Volatility Squeeze",
        "details": details,
        "phase": bb_signal.phase,
        "squeeze_days": bb_signal.squeeze_days,
        "explanation": (
            "Method I detects when Bollinger Bandwidth narrows to a 6-month low (the 'squeeze'), "
            "indicating low volatility that ALWAYS precedes a big move. Like compressing a spring — "
            "the tighter the squeeze, the more explosive the breakout. We then check 5 conditions: "
            "(1) BandWidth at minimum, (2) Price breaks above upper band, (3) Volume confirms, "
            "(4) CMF shows money flowing in, (5) MFI shows buying pressure. All 5 = high-confidence buy."
        ),
    }


def _score_bb_method_2(strategy_result: dict) -> dict:
    """
    Method II — Trend Following (%b + MFI) (25 points max).
    Uses %b to locate price within the bands and MFI to confirm money flow.
    """
    score = 0.0
    details = []
    sig = strategy_result.get("signal", {})
    indicators = strategy_result.get("indicators", {})

    sig_type = sig.get("type", "NONE")
    confidence = sig.get("confidence", 0)

    if sig_type == "BUY":
        score += 20 * (confidence / 100)
        details.append(f"✅ Method II BUY — {sig.get('reason', '')}")
    elif sig_type == "SELL":
        score -= 20 * (confidence / 100)
        details.append(f"❌ Method II SELL — {sig.get('reason', '')}")
    elif sig_type == "WATCH":
        details.append(f"⏳ Method II WATCH — {sig.get('reason', '')}")
    elif sig_type == "HOLD":
        score += 5
        details.append(f"✅ Method II HOLD — trend intact")

    # Divergence detection
    if indicators.get("bearish_divergence"):
        score -= 5
        details.append("⚠️ Bearish divergence: %b rising but MFI falling")
    if indicators.get("bullish_divergence"):
        score += 5
        details.append("✅ Bullish divergence: %b falling but MFI rising")

    score = max(-25, min(25, score))
    return {
        "score": round(score, 1),
        "max": 25,
        "method": "Method II — Trend Following",
        "details": details,
        "explanation": (
            "%b tells you WHERE price sits within the bands (0=bottom, 1=top). "
            "MFI (Money Flow Index) tells you if MONEY is flowing in or out. "
            "When both agree — %b in the upper zone AND MFI high — you have a confirmed uptrend. "
            "When they DIVERGE (price rising but money flow falling), the trend is weakening. "
            "As Bollinger says: 'When %b and MFI disagree, believe MFI.'"
        ),
    }


def _score_bb_method_3(strategy_result: dict) -> dict:
    """
    Method III — Reversals (W-Bottoms & M-Tops) (20 points max).
    Detects classic reversal patterns within the band structure.
    """
    score = 0.0
    details = []
    sig = strategy_result.get("signal", {})
    patterns = strategy_result.get("patterns", [])

    sig_type = sig.get("type", "NONE")
    confidence = sig.get("confidence", 0)

    if sig_type == "BUY":
        score += 15 * (confidence / 100)
        details.append(f"✅ Method III BUY — Reversal pattern detected")
    elif sig_type == "SELL":
        score -= 15 * (confidence / 100)
        details.append(f"❌ Method III SELL — Reversal pattern detected")

    for p in patterns:
        name = p.get("name", "")
        details.append(f"📊 Pattern: {name} ({p.get('start_date', '?')} → {p.get('end_date', '?')})")

    score = max(-20, min(20, score))
    return {
        "score": round(score, 1),
        "max": 20,
        "method": "Method III — Reversals",
        "details": details if details else ["No W-Bottom or M-Top patterns detected"],
        "explanation": (
            "W-Bottoms (double bottoms formed at the lower Bollinger Band) are bullish reversal patterns. "
            "The key is that the SECOND low should have a HIGHER %b than the first — showing that "
            "even though price retested the low, the band structure improved. "
            "M-Tops are the bearish mirror image — the second high has a LOWER %b, "
            "showing weakening momentum despite similar price levels."
        ),
    }


def _score_bb_method_4(strategy_result: dict) -> dict:
    """
    Method IV — Walking the Bands (15 points max).
    Identifies strong trends where price hugs one band.
    """
    score = 0.0
    details = []
    sig = strategy_result.get("signal", {})
    patterns = strategy_result.get("patterns", [])

    sig_type = sig.get("type", "NONE")
    confidence = sig.get("confidence", 0)

    if sig_type == "BUY":
        score += 12 * (confidence / 100)
        details.append(f"✅ Method IV — Walking upper bands (strong uptrend)")
    elif sig_type == "SELL":
        score -= 12 * (confidence / 100)
        details.append(f"❌ Method IV — Walking lower bands (strong downtrend)")

    for p in patterns:
        details.append(f"📊 Band walk: {p.get('name', '')} ({p.get('description', '')})")

    score = max(-15, min(15, score))
    return {
        "score": round(score, 1),
        "max": 15,
        "method": "Method IV — Walking the Bands",
        "details": details if details else ["No band-walking pattern detected"],
        "explanation": (
            "In a VERY strong trend, price doesn't just touch the upper (or lower) band — "
            "it WALKS along it, with repeated closes at or above the band. "
            "This is NOT overbought — it's a sign of extreme strength. "
            "The key confirmation: pullbacks should touch the MIDDLE band (20-SMA), "
            "not the opposite band. If pullbacks reach the middle band and bounce, "
            "the trend is healthy and likely to continue."
        ),
    }


# ═══════════════════════════════════════════════════════════════
#  CROSS-VALIDATION ENGINE
# ═══════════════════════════════════════════════════════════════

def _cross_validate(bb_total: float, ta_total: float, bb_methods: list, ta_signal: dict) -> dict:
    """
    The magical part — cross-validate BB and TA signals.
    
    Both systems must AGREE for high conviction.
    Disagreement = uncertainty = lower conviction.
    """
    bb_direction = "BULLISH" if bb_total > 10 else "BEARISH" if bb_total < -10 else "NEUTRAL"
    ta_verdict = ta_signal.get("verdict", "HOLD")
    ta_direction = "BULLISH" if ta_verdict in ("STRONG BUY", "BUY") else "BEARISH" if ta_verdict in ("STRONG SELL", "SELL") else "NEUTRAL"

    agreement_score = 0
    observations = []

    # Perfect agreement
    if bb_direction == ta_direction and bb_direction != "NEUTRAL":
        agreement_score += 30
        observations.append(
            f"✅ STRONG AGREEMENT: Both Bollinger Bands ({bb_direction}) and Technical Analysis ({ta_verdict}) "
            f"point in the SAME direction. This is the highest conviction signal — when two independent "
            f"systems built on different philosophies agree, the probability of a successful trade "
            f"increases significantly."
        )
    # Both neutral
    elif bb_direction == "NEUTRAL" and ta_direction == "NEUTRAL":
        observations.append(
            "⏳ BOTH SYSTEMS NEUTRAL: Neither Bollinger Bands nor Technical Analysis show a clear "
            "directional bias. This is a 'wait and watch' situation. The market is building energy "
            "for the next major move — patience is the best strategy here."
        )
    # Disagreement
    elif bb_direction != ta_direction and bb_direction != "NEUTRAL" and ta_direction != "NEUTRAL":
        agreement_score -= 20
        observations.append(
            f"⚠️ CONFLICTING SIGNALS: Bollinger Bands say {bb_direction} but Technical Analysis says "
            f"{ta_verdict}. When two reliable systems disagree, it's a WARNING to stay cautious. "
            f"Possible reasons: (1) The stock is in a transition phase, (2) One system is picking up "
            f"a signal earlier than the other, (3) The move may be temporary. "
            f"RECOMMENDATION: Wait for both systems to align before committing capital."
        )
    # Partial agreement
    else:
        if bb_direction != "NEUTRAL":
            agreement_score += 5
            observations.append(
                f"Bollinger Bands show {bb_direction} bias, but Technical Analysis is neutral. "
                f"The BB system may be picking up an early signal — watch for TA confirmation."
            )
        else:
            observations.append(
                f"Technical Analysis shows {ta_verdict}, but Bollinger Bands are neutral. "
                f"TA sees the bigger picture — watch for BB squeeze/breakout to confirm."
            )

    # Check specific cross-validations
    bb_squeeze_active = any(m.get("phase") == "COMPRESSION" or m.get("phase") == "DIRECTION" for m in bb_methods)
    ta_trend = ta_signal.get("categories", {}).get("trend", {})
    ta_momentum = ta_signal.get("categories", {}).get("momentum", {})
    ta_volume = ta_signal.get("categories", {}).get("volume", {})

    # Squeeze + positive TA trend = building energy in the right direction
    if bb_squeeze_active:
        if ta_trend.get("score", 0) > 5:
            agreement_score += 10
            observations.append(
                "✅ POWERFUL SETUP: Bollinger squeeze is active (energy building) AND the TA trend is bullish. "
                "When a squeeze resolves in the direction of the underlying trend, the move is typically "
                "larger and more sustained. This is a textbook high-confidence setup."
            )
        elif ta_trend.get("score", 0) < -5:
            agreement_score -= 10
            observations.append(
                "⚠️ CAUTION: Bollinger squeeze is active but the TA trend is bearish. "
                "The squeeze could resolve to the downside. Do NOT assume squeezes always break upward."
            )

    # Volume confirmation across both systems
    if ta_volume.get("score", 0) > 5 and bb_total > 10:
        agreement_score += 5
        observations.append(
            "✅ VOLUME CONFIRMS: Both strong volume activity AND positive BB signals. "
            "Volume is the lie detector — when it confirms price, the signal is real."
        )

    return {
        "agreement_score": agreement_score,
        "bb_direction": bb_direction,
        "ta_direction": ta_direction,
        "alignment": "ALIGNED" if bb_direction == ta_direction and bb_direction != "NEUTRAL" else "CONFLICTING" if (bb_direction != ta_direction and bb_direction != "NEUTRAL" and ta_direction != "NEUTRAL") else "PARTIAL",
        "observations": observations,
    }


# ═══════════════════════════════════════════════════════════════
#  HYBRID CONCLUSION GENERATOR
# ═══════════════════════════════════════════════════════════════

def _generate_hybrid_verdict(combined_score: float, cross: dict) -> dict:
    """Generate the final hybrid verdict with plain-English explanation."""

    # Tightened thresholds to reduce false BUY/SELL (max combined_score = 245)
    if combined_score >= 90:
        verdict = "SUPER STRONG BUY"
        color = "bull"
        emoji = "🟢🟢🟢"
    elif combined_score >= 55:
        verdict = "STRONG BUY"
        color = "bull"
        emoji = "🟢🟢"
    elif combined_score >= 35:
        verdict = "BUY"
        color = "bull"
        emoji = "🟢"
    elif combined_score <= -90:
        verdict = "SUPER STRONG SELL"
        color = "bear"
        emoji = "🔴🔴🔴"
    elif combined_score <= -55:
        verdict = "STRONG SELL"
        color = "bear"
        emoji = "🔴🔴"
    elif combined_score <= -35:
        verdict = "SELL"
        color = "bear"
        emoji = "🔴"
    else:
        verdict = "HOLD / WAIT"
        color = "neutral"
        emoji = "🟡"

    confidence = min(abs(combined_score) / 245 * 100, 100)

    # Generate plain-English summary
    alignment = cross.get("alignment", "PARTIAL")

    if alignment == "ALIGNED":
        conviction_text = (
            f"BOTH Bollinger Band analysis and Technical Analysis point in the same direction. "
            f"This dual confirmation gives us {confidence:.0f}% confidence in the {verdict} signal. "
            f"When two independent analysis systems agree, the probability of a successful outcome "
            f"is significantly higher than relying on either system alone."
        )
    elif alignment == "CONFLICTING":
        conviction_text = (
            f"The Bollinger Band system and Technical Analysis system are giving CONFLICTING signals. "
            f"This reduces our confidence to {confidence:.0f}%. In such situations, the wise approach "
            f"is to WAIT for clarity. Markets often go through transition periods where signals are mixed."
        )
    else:
        conviction_text = (
            f"One system shows a directional signal while the other is neutral. "
            f"This gives us moderate confidence of {confidence:.0f}% in the {verdict} signal. "
            f"Watch for the neutral system to start confirming the signal for a stronger setup."
        )

    return {
        "verdict": verdict,
        "emoji": emoji,
        "color": color,
        "score": round(combined_score, 1),
        "max_score": 245,
        "confidence": round(confidence, 1),
        "conviction_text": conviction_text,
        "alignment": alignment,
    }


# ═══════════════════════════════════════════════════════════════
#  MASTER HYBRID ANALYSIS
# ═══════════════════════════════════════════════════════════════

def run_hybrid_analysis(df: pd.DataFrame, ticker: str = "UNKNOWN", capital: float = 500000) -> dict:
    """
    Run the complete hybrid BB + TA analysis.

    Args:
        df: DataFrame with OHLCV data
        capital: Trading capital for position sizing

    Returns:
        Complete hybrid analysis result with all data for the dashboard.
    """
    if df is None or df.empty or len(df) < 50:
        return {"error": "Insufficient data (need at least 50 data points)"}

    # ══════════════════════════════════════════════════════════
    #  DATA FRESHNESS CHECK (critical for live trading)
    # ══════════════════════════════════════════════════════════
    freshness = get_data_freshness(df)

    # ══════════════════════════════════════════════════════════
    #  STEP 1: RUN BOLLINGER BAND ANALYSIS
    # ══════════════════════════════════════════════════════════
    df_bb = compute_bb_indicators(df.copy())
    bb_signal = generate_bb_signal(ticker, df_bb)
    bb_strategies = run_all_strategies(df_bb)
    bb_strategies_dict = [strategy_result_to_dict(s) for s in bb_strategies]

    # ══════════════════════════════════════════════════════════
    #  STEP 2: RUN TECHNICAL ANALYSIS
    # ══════════════════════════════════════════════════════════
    df_ta = compute_all_ta_indicators(df.copy())
    snapshot = get_indicator_snapshot(df_ta)
    trend = identify_trend(df_ta)
    crossovers = detect_ma_crossovers(df_ta)
    divergences = detect_all_divergences(df_ta)
    candle_patterns = scan_candlestick_patterns(df_ta, lookback=5)
    chart_patterns = detect_all_chart_patterns(df_ta)
    vol_analysis = analyze_volume(df_ta)
    ichimoku = analyze_ichimoku(df_ta)
    sr_data = detect_support_resistance(df_ta)
    fib_data = compute_fibonacci(df_ta)
    pivot = compute_pivot_points(df_ta)

    ta_signal = generate_ta_signal(
        snap=snapshot, trend=trend, vol_analysis=vol_analysis,
        chart_patterns=chart_patterns, candle_patterns=candle_patterns,
        divergences=divergences, sr_data=sr_data, fib_data=fib_data,
    )

    risk = generate_risk_report(snapshot, sr_data, capital)
    target_prices = calculate_target_prices(
        snap=snapshot, trend=trend, sr_data=sr_data,
        fib_data=fib_data, pivot=pivot, chart_patterns=chart_patterns,
    )

    # ══════════════════════════════════════════════════════════
    #  STEP 3: SCORE BOLLINGER BAND METHODS (100 pts max)
    # ══════════════════════════════════════════════════════════
    m1_score = _score_bb_method_1(bb_signal)
    _strat = {s.get("code"): s for s in bb_strategies_dict}
    m2_score = _score_bb_method_2(_strat.get("M2", {}))
    m3_score = _score_bb_method_3(_strat.get("M3", {}))
    m4_score = _score_bb_method_4(_strat.get("M4", {}))

    bb_total = m1_score["score"] + m2_score["score"] + m3_score["score"] + m4_score["score"]
    bb_methods = [m1_score, m2_score, m3_score, m4_score]

    # ══════════════════════════════════════════════════════════
    #  STEP 4: TA SCORE (already computed as signal score, scale to 100)
    # ══════════════════════════════════════════════════════════
    ta_total = ta_signal.get("score", 0)  # Already -100 to +100

    # ══════════════════════════════════════════════════════════
    #  STEP 5: CROSS-VALIDATE
    # ══════════════════════════════════════════════════════════
    cross = _cross_validate(bb_total, ta_total, bb_methods, ta_signal)

    # ══════════════════════════════════════════════════════════
    #  STEP 6: COMBINED SCORE (BB + TA + cross-validation bonus)
    # ══════════════════════════════════════════════════════════
    combined_score = bb_total + ta_total + cross["agreement_score"]
    max_possible = 245  # bb(100) + ta(100) + cross(45)

    # ══════════════════════════════════════════════════════════
    #  STEP 7: GENERATE HYBRID VERDICT
    # ══════════════════════════════════════════════════════════
    hybrid_verdict = _generate_hybrid_verdict(combined_score, cross)

    # ══════════════════════════════════════════════════════════
    #  STEP 8: BUILD COMPLETE BB SIGNAL DATA
    # ══════════════════════════════════════════════════════════
    bb_data = {
        "phase": bb_signal.phase,
        "squeeze_on": bb_signal.cond1_squeeze_on,
        "squeeze_days": bb_signal.squeeze_days,
        "buy_signal": bb_signal.buy_signal,
        "sell_signal": bb_signal.sell_signal,
        "hold_signal": bb_signal.hold_signal,
        "head_fake": bb_signal.head_fake,
        "confidence": bb_signal.confidence,
        "direction_lean": bb_signal.direction_lean,
        "summary": bb_signal.summary,
        "action_message": bb_signal.action_message,
        "indicators": {
            "price": _safe(bb_signal.current_price),
            "bb_upper": _safe(bb_signal.bb_upper),
            "bb_mid": _safe(bb_signal.bb_mid),
            "bb_lower": _safe(bb_signal.bb_lower),
            "bbw": _safe(bb_signal.bbw),
            "percent_b": _safe(bb_signal.percent_b),
            "sar": _safe(bb_signal.sar),
            "sar_bull": bb_signal.sar_bull,
            "cmf": _safe(bb_signal.cmf),
            "mfi": _safe(bb_signal.mfi),
            "volume": _safe(bb_signal.volume),
            "vol_sma50": _safe(bb_signal.vol_sma50),
            "ii_pct": _safe(bb_signal.ii_pct),
            "ad_pct": _safe(bb_signal.ad_pct),
            "vwmacd_hist": _safe(bb_signal.vwmacd_hist),
            "rsi_norm": _safe(bb_signal.rsi_norm),
            "mfi_norm": _safe(bb_signal.mfi_norm),
            "expansion_up": bb_signal.expansion_up,
            "expansion_down": bb_signal.expansion_down,
            "expansion_end": bb_signal.expansion_end,
        },
        "conditions": {
            "squeeze": bb_signal.cond1_squeeze_on,
            "price_breakout": bb_signal.cond2_price_above,
            "volume_confirm": bb_signal.cond3_volume_ok,
            "cmf_positive": bb_signal.cond4_cmf_positive,
            "mfi_above_50": bb_signal.cond5_mfi_above_50,
        },
        "exit_signals": {
            "sar_flip": bb_signal.exit_sar_flip,
            "lower_band_tag": bb_signal.exit_lower_band_tag,
            "double_negative": bb_signal.exit_double_neg,
            "expansion_end": bb_signal.expansion_end,
        },
        "short_signal": bb_signal.short_signal,
        "short_conditions": {
            "squeeze": bb_signal.cond_short_squeeze,
            "price_below": bb_signal.cond_short_price,
            "volume_confirm": bb_signal.cond_short_volume,
            "ii_negative": bb_signal.cond_short_ii_neg,
            "mfi_low": bb_signal.cond_short_mfi_low,
        },
        "stop_loss": _safe(bb_signal.stop_loss),
    }

    # Build the final response
    result = _safe_json({
        "hybrid_verdict": hybrid_verdict,
        "data_freshness": freshness,
        "cross_validation": cross,
        "bb_score": {
            "total": round(bb_total, 1),
            "max": 100,
            "methods": bb_methods,
        },
        "ta_score": {
            "total": round(ta_total, 1),
            "max": 100,
            "categories": ta_signal.get("categories", {}),
        },
        "bb_data": bb_data,
        "bb_strategies": bb_strategies_dict,
        "ta_signal": ta_signal,
        "snapshot": snapshot,
        "trend": trend,
        "crossovers": crossovers,
        "divergences": divergences,
        "candle_patterns": candle_patterns,
        "chart_patterns": chart_patterns,
        "volume": vol_analysis,
        "ichimoku": ichimoku,
        "support_resistance": sr_data,
        "fibonacci": fib_data,
        "pivot_points": pivot,
        "risk": risk,
        "target_prices": target_prices,
    })

    return result
