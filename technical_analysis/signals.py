"""
signals.py — Multi-Indicator Consensus Engine.

Murphy Ch 19: "Pulling It All Together"
Combines ALL indicators, patterns, and analysis into a single
weighted scoring system that produces a final BUY / SELL / HOLD
recommendation with a confidence percentage.

Scoring philosophy (from Murphy):
  "No single indicator is infallible.  The key is to combine
   several tools and look for CONFIRMATION."

Weight categories:
  - Trend Analysis   : 25%
  - Momentum/Osc     : 20%
  - Volume           : 15%
  - Patterns          : 15%
  - Support/Resistance: 10%
  - Risk              : 15%
"""

from __future__ import annotations

import math
from technical_analysis.config import (
    RSI_OVERBOUGHT, RSI_OVERSOLD,
    STOCH_OVERBOUGHT, STOCH_OVERSOLD,
    WILLR_OVERBOUGHT, WILLR_OVERSOLD,
    CCI_OVERBOUGHT, CCI_OVERSOLD,
    ADX_STRONG, ADX_WEAK,
    WEIGHT_TREND, WEIGHT_MOMENTUM, WEIGHT_VOLUME,
    WEIGHT_PATTERN, WEIGHT_SUPPORT_RES, WEIGHT_RISK,
)


# ═══════════════════════════════════════════════════════════════
#  SCORING HELPERS
# ═══════════════════════════════════════════════════════════════

def _clamp(val: float, lo: float = -100.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, val))


def _safe(val):
    if val is None or (isinstance(val, float) and (math.isnan(val) or math.isinf(val))):
        return None
    return val


# ═══════════════════════════════════════════════════════════════
#  TREND SCORE  (25 points max)
# ═══════════════════════════════════════════════════════════════

def _score_trend(snap: dict, trend: dict) -> dict:
    """Score trend indicators: MA alignment, ADX, Supertrend, Aroon."""
    score = 0.0
    details = []
    max_pts = WEIGHT_TREND

    # 1. Price vs MAs (up to 10 pts)
    ma_pts = 0
    if snap.get("above_sma_200") is True:
        ma_pts += 3; details.append("✅ Above 200-SMA (major uptrend intact)")
    elif snap.get("sma_200") is not None:
        ma_pts -= 3; details.append("❌ Below 200-SMA (major uptrend broken)")

    if snap.get("above_sma_50") is True:
        ma_pts += 2; details.append("✅ Above 50-SMA (medium-term bullish)")
    elif snap.get("sma_50") is not None:
        ma_pts -= 2; details.append("❌ Below 50-SMA (medium-term bearish)")

    if snap.get("above_sma_20") is True:
        ma_pts += 1.5; details.append("✅ Above 20-SMA (short-term bullish)")
    elif snap.get("sma_20") is not None:
        ma_pts -= 1.5; details.append("❌ Below 20-SMA (short-term bearish)")
    score += _clamp(ma_pts, -8, 8)

    # 2. EMA alignment
    alignment = trend.get("ema_alignment", "")
    if "PERFECT BULLISH" in alignment:
        score += 5; details.append("✅ Perfect EMA ribbon alignment (bullish)")
    elif "PERFECT BEARISH" in alignment:
        score -= 5; details.append("❌ Perfect EMA ribbon alignment (bearish)")

    # 3. ADX strength
    adx = _safe(snap.get("adx"))
    if adx is not None:
        plus_di = _safe(snap.get("plus_di"))
        minus_di = _safe(snap.get("minus_di"))
        if adx >= ADX_STRONG:
            direction = 1 if (plus_di and minus_di and plus_di > minus_di) else -1
            score += 4 * direction
            details.append(f"{'✅' if direction > 0 else '❌'} ADX={adx:.0f} (strong trend, {'+DI' if direction > 0 else '-DI'} leading)")
        elif adx < ADX_WEAK:
            details.append(f"⚠️ ADX={adx:.0f} (no clear trend — oscillator signals preferred)")

    # 4. Supertrend
    if snap.get("supertrend_bullish") is True:
        score += 3; details.append("✅ Supertrend is BULLISH (green)")
    elif snap.get("supertrend_bullish") is False:
        score -= 3; details.append("❌ Supertrend is BEARISH (red)")

    # 5. Aroon (trend indicator, not volume)
    aroon_osc = _safe(snap.get("aroon_osc"))
    if aroon_osc is not None:
        if aroon_osc > 50:
            score += 2; details.append(f"✅ Aroon oscillator={aroon_osc:.0f} (strong uptrend)")
        elif aroon_osc < -50:
            score -= 2; details.append(f"❌ Aroon oscillator={aroon_osc:.0f} (strong downtrend)")

    # Normalize to max weight
    normalized = _clamp(score / 22.0 * max_pts, -max_pts, max_pts)
    return {"score": round(normalized, 1), "max": max_pts, "details": details}


# ═══════════════════════════════════════════════════════════════
#  MOMENTUM SCORE  (20 points max)
# ═══════════════════════════════════════════════════════════════

def _score_momentum(snap: dict, trend: dict = None) -> dict:
    """Score oscillators: RSI, MACD, Stochastic, Williams %R, CCI, ROC.

    Murphy Ch 10: "Oscillators are subordinate to basic trend analysis."
    In strong uptrends, overbought readings are expected and NOT bearish.
    In strong downtrends, oversold readings are expected and NOT bullish.
    "Trade in the direction of the overriding market trend."
    """
    score = 0.0
    details = []
    max_pts = WEIGHT_MOMENTUM

    # Murphy Ch 10: Determine if oscillator extremes should be penalized
    # "In strong uptrends, overbought can stay overbought — don't sell prematurely"
    primary_trend = (trend or {}).get("primary", "SIDEWAYS")
    trend_strength = (trend or {}).get("strength", "")
    strong_uptrend = (primary_trend == "UPTREND" and "STRONG" in str(trend_strength).upper())
    strong_downtrend = (primary_trend == "DOWNTREND" and "STRONG" in str(trend_strength).upper())

    # RSI
    rsi = _safe(snap.get("rsi"))
    if rsi is not None:
        if rsi < RSI_OVERSOLD:
            if strong_downtrend:
                score += 0.5  # Murphy: oversold is expected in strong downtrend — weak signal
                details.append(f"⚠️ RSI={rsi:.0f} OVERSOLD but in strong downtrend — bounce unreliable")
            else:
                score += 3; details.append(f"✅ RSI={rsi:.0f} OVERSOLD — bounce likely")
        elif rsi > RSI_OVERBOUGHT:
            if strong_uptrend:
                score += 0.5  # Murphy: overbought is NORMAL in strong uptrend — don't penalize
                details.append(f"✅ RSI={rsi:.0f} overbought but in strong uptrend — momentum confirms trend")
            else:
                score -= 3; details.append(f"❌ RSI={rsi:.0f} OVERBOUGHT — correction likely")
        elif 50 < rsi < RSI_OVERBOUGHT:
            score += 1; details.append(f"✅ RSI={rsi:.0f} bullish zone (50–70)")
        elif RSI_OVERSOLD < rsi < 50:
            score -= 1; details.append(f"❌ RSI={rsi:.0f} bearish zone (30–50)")

    # MACD
    macd_hist = _safe(snap.get("macd_hist"))
    macd_hist_prev = _safe(snap.get("macd_hist_prev"))
    if macd_hist is not None:
        if macd_hist > 0:
            score += 2; details.append("✅ MACD histogram positive (bullish momentum)")
        else:
            score -= 2; details.append("❌ MACD histogram negative (bearish momentum)")

        if macd_hist_prev is not None:
            if macd_hist > 0 and macd_hist > macd_hist_prev:
                score += 1; details.append("✅ MACD histogram growing (momentum accelerating)")
            elif macd_hist < 0 and macd_hist < macd_hist_prev:
                score -= 1; details.append("❌ MACD histogram declining (selling accelerating)")

    # Stochastic
    stoch_k = _safe(snap.get("stoch_k"))
    stoch_d = _safe(snap.get("stoch_d"))
    if stoch_k is not None:
        if stoch_k < STOCH_OVERSOLD:
            if strong_downtrend:
                score += 0.5
                details.append(f"⚠️ Stochastic %K={stoch_k:.0f} OVERSOLD — weak in strong downtrend")
            else:
                score += 2; details.append(f"✅ Stochastic %K={stoch_k:.0f} OVERSOLD")
        elif stoch_k > STOCH_OVERBOUGHT:
            if strong_uptrend:
                score += 0.5
                details.append(f"✅ Stochastic %K={stoch_k:.0f} overbought — normal in strong uptrend")
            else:
                score -= 2; details.append(f"❌ Stochastic %K={stoch_k:.0f} OVERBOUGHT")

        if stoch_k is not None and stoch_d is not None:
            if stoch_k > stoch_d:
                score += 1; details.append("✅ Stochastic %K > %D (bullish crossover)")
            else:
                score -= 1; details.append("❌ Stochastic %K < %D (bearish crossover)")

    # Williams %R
    willr = _safe(snap.get("williams_r"))
    if willr is not None:
        if willr < WILLR_OVERSOLD:
            score += 1; details.append(f"✅ Williams %R={willr:.0f} OVERSOLD")
        elif willr > WILLR_OVERBOUGHT:
            score -= 1; details.append(f"❌ Williams %R={willr:.0f} OVERBOUGHT")

    # CCI
    cci = _safe(snap.get("cci"))
    if cci is not None:
        if cci > CCI_OVERBOUGHT:
            if strong_uptrend:
                details.append(f"✅ CCI={cci:.0f} ABOVE +100 — strong momentum in uptrend")
            else:
                score -= 1; details.append(f"❌ CCI={cci:.0f} ABOVE +100 (extended)")
        elif cci < CCI_OVERSOLD:
            if strong_downtrend:
                details.append(f"⚠️ CCI={cci:.0f} BELOW -100 — weak in strong downtrend")
            else:
                score += 1; details.append(f"✅ CCI={cci:.0f} BELOW -100 (oversold)")

    # ROC
    roc = _safe(snap.get("roc"))
    if roc is not None:
        if roc > 0:
            score += 0.5; details.append(f"✅ ROC={roc:.1f}% positive momentum")
        else:
            score -= 0.5; details.append(f"❌ ROC={roc:.1f}% negative momentum")

    normalized = _clamp(score / 11.5 * max_pts, -max_pts, max_pts)
    return {"score": round(normalized, 1), "max": max_pts, "details": details}


# ═══════════════════════════════════════════════════════════════
#  VOLUME SCORE  (15 points max)
# ═══════════════════════════════════════════════════════════════

def _score_volume(snap: dict, vol_analysis: dict, trend: dict = None) -> dict:
    """Score volume indicators: OBV, A/D, Volume ratio.

    Murphy Ch 7: "Volume should increase or expand in the direction of
    the existing price trend."  High volume on rallies in uptrend = bullish.
    High volume on declines in downtrend = bearish.
    High volume AGAINST the trend = warning sign.
    """
    score = 0.0
    details = []
    max_pts = WEIGHT_VOLUME

    # Murphy Ch 7: Determine established trend for volume confirmation
    primary_trend = (trend or {}).get("primary", "SIDEWAYS")

    # OBV trend
    obv_trend = vol_analysis.get("obv_trend", "")
    if "BULLISH" in obv_trend:
        score += 3; details.append("✅ OBV rising (accumulation — smart money buying)")
    elif "BEARISH" in obv_trend:
        score -= 3; details.append("❌ OBV falling (distribution — smart money selling)")

    # Volume level — Murphy: volume must confirm the TREND direction
    vol_ratio = vol_analysis.get("volume_ratio", 1.0)
    vol_status = vol_analysis.get("volume_status", "NORMAL")
    if vol_status in ("HIGH", "VERY HIGH"):
        roc = _safe(snap.get("roc"))
        if roc is not None and roc > 0:
            if primary_trend == "UPTREND":
                score += 2; details.append(f"✅ Volume {vol_ratio:.1f}x avg on UP move in uptrend — trend confirmed (Murphy Ch 7)")
            else:
                score += 1.5; details.append(f"✅ Volume {vol_ratio:.1f}x avg — confirms upward move")
        elif roc is not None and roc < 0:
            if primary_trend == "DOWNTREND":
                score -= 2; details.append(f"❌ Volume {vol_ratio:.1f}x avg on DOWN move in downtrend — trend confirmed (Murphy Ch 7)")
            elif primary_trend == "UPTREND":
                score -= 2.5; details.append(f"⚠️ Volume {vol_ratio:.1f}x avg on DOWN move in uptrend — WARNING: distribution (Murphy Ch 7)")
            else:
                score -= 1.5; details.append(f"❌ Volume {vol_ratio:.1f}x avg — confirms downward move")
    elif vol_status == "LOW":
        if primary_trend == "UPTREND":
            roc = _safe(snap.get("roc"))
            if roc is not None and roc > 0:
                score -= 0.5; details.append(f"⚠️ Volume {vol_ratio:.1f}x avg LOW on rally — weakening upside pressure (Murphy Ch 7)")
            else:
                details.append(f"Volume {vol_ratio:.1f}x avg — light on pullback (normal in uptrend)")
        else:
            details.append(f"⚠️ Volume {vol_ratio:.1f}x avg — low participation (weak conviction)")

    # VWAP
    vwap = _safe(snap.get("vwap"))
    price = _safe(snap.get("price"))
    if vwap and price:
        if price > vwap:
            score += 1; details.append("✅ Price above VWAP (institutional buying)")
        else:
            score -= 1; details.append("❌ Price below VWAP (institutional selling)")

    normalized = _clamp(score / 6.0 * max_pts, -max_pts, max_pts)
    return {"score": round(normalized, 1), "max": max_pts, "details": details}


# ═══════════════════════════════════════════════════════════════
#  PATTERN SCORE  (15 points max)
# ═══════════════════════════════════════════════════════════════

def _score_patterns(chart_patterns: list, candle_patterns: list, divergences: list) -> dict:
    """Score detected chart patterns, candlestick patterns, and divergences."""
    score = 0.0
    details = []
    max_pts = WEIGHT_PATTERN

    # Chart patterns (stronger weight)
    for p in chart_patterns:
        s = p.get("strength", 1)
        if p["type"] == "BULLISH":
            score += s * 1.5
            details.append(f"✅ {p['name']} detected (strength {s}/3)")
        elif p["type"] == "BEARISH":
            score -= s * 1.5
            details.append(f"❌ {p['name']} detected (strength {s}/3)")

    # Candlestick patterns
    for p in candle_patterns:
        s = p.get("strength", 1)
        if p["type"] == "BULLISH":
            score += s * 0.8
            details.append(f"✅ 🕯️ {p['name']} on {p.get('date', '?')}")
        elif p["type"] == "BEARISH":
            score -= s * 0.8
            details.append(f"❌ 🕯️ {p['name']} on {p.get('date', '?')}")

    # Divergences (from indicators.py)
    for d in divergences:
        if "BULLISH" in d["type"]:
            score += 2
            details.append(f"✅ Bullish divergence on {d['indicator']}")
        else:
            score -= 2
            details.append(f"❌ Bearish divergence on {d['indicator']}")

    if not details:
        details.append("No significant patterns detected in recent data")

    normalized = _clamp(score / 8.0 * max_pts, -max_pts, max_pts)
    return {"score": round(normalized, 1), "max": max_pts, "details": details}


# ═══════════════════════════════════════════════════════════════
#  SUPPORT/RESISTANCE SCORE  (10 points max)
# ═══════════════════════════════════════════════════════════════

def _score_support_resistance(snap: dict, sr_data: dict, fib_data: dict) -> dict:
    """Score position relative to support/resistance and Fibonacci levels."""
    score = 0.0
    details = []
    max_pts = WEIGHT_SUPPORT_RES
    price = _safe(snap.get("price"))

    if not price:
        return {"score": 0, "max": max_pts, "details": ["Price data unavailable"]}

    # Nearest support/resistance
    supports = sr_data.get("support", [])
    resistances = sr_data.get("resistance", [])

    if supports:
        nearest_s = supports[0]["level"]
        dist_s = (price - nearest_s) / price * 100
        if dist_s < 2:
            score += 2; details.append(f"✅ Near support at ₹{nearest_s} ({dist_s:.1f}% away) — bounce zone")
        elif dist_s < 5:
            score += 1; details.append(f"Support at ₹{nearest_s} ({dist_s:.1f}% below)")
    else:
        details.append("No clear support levels identified")

    if resistances:
        nearest_r = resistances[0]["level"]
        dist_r = (nearest_r - price) / price * 100
        if dist_r < 2:
            score -= 2; details.append(f"❌ Near resistance at ₹{nearest_r} ({dist_r:.1f}% away) — may face selling")
        elif dist_r < 5:
            score -= 1; details.append(f"Resistance at ₹{nearest_r} ({dist_r:.1f}% above)")

    # Fibonacci position
    if fib_data.get("is_uptrend") is not None:
        fib_382 = fib_data.get("fib_0.382")
        fib_618 = fib_data.get("fib_0.618")
        fib_50 = fib_data.get("fib_0.5")

        if fib_data["is_uptrend"] and fib_382 and fib_618:
            if fib_618 <= price <= fib_382:
                score += 1.5
                details.append(f"✅ Price in Fibonacci BUY zone (38.2%–61.8% retracement)")
        elif not fib_data["is_uptrend"] and fib_382 and fib_618:
            if fib_382 <= price <= fib_618:
                score -= 1.5
                details.append(f"❌ Price in Fibonacci SELL zone (38.2%–61.8% retracement)")

    # Bollinger Band position
    pct_b = _safe(snap.get("percent_b"))
    if pct_b is not None:
        if pct_b < 0:
            score += 1; details.append(f"✅ Below lower Bollinger Band (oversold)")
        elif pct_b > 1:
            score -= 1; details.append(f"❌ Above upper Bollinger Band (overbought)")

    normalized = _clamp(score / 5.0 * max_pts, -max_pts, max_pts)
    return {"score": round(normalized, 1), "max": max_pts, "details": details}


# ═══════════════════════════════════════════════════════════════
#  RISK ASSESSMENT SCORE  (15 points max)
# ═══════════════════════════════════════════════════════════════

def _score_risk(snap: dict, trend: dict) -> dict:
    """Score risk factors: ATR, proximity to 52w levels, volatility."""
    score = 0.0
    details = []
    max_pts = WEIGHT_RISK
    price = _safe(snap.get("price"))

    if not price:
        return {"score": 0, "max": max_pts, "details": ["Price data unavailable"]}

    # ATR volatility
    atr_pct = _safe(snap.get("atr_pct"))
    if atr_pct:
        if atr_pct > 4:
            score -= 2; details.append(f"⚠️ ATR={atr_pct:.1f}% — HIGH volatility (risky)")
        elif atr_pct > 2.5:
            score -= 0.5; details.append(f"ATR={atr_pct:.1f}% — moderate volatility")
        else:
            score += 1; details.append(f"✅ ATR={atr_pct:.1f}% — low volatility (safer)")

    # 52-week position
    pct_52w = _safe(snap.get("pct_from_52w_high"))
    if pct_52w is not None:
        if pct_52w > -5:
            score -= 1; details.append(f"⚠️ Near 52-week high ({pct_52w:+.1f}%) — limited upside risk")
        elif pct_52w < -40:
            score += 1; details.append(f"✅ {pct_52w:.0f}% from 52w high — deep value territory")
        elif pct_52w < -20:
            score += 0.5; details.append(f"Price {pct_52w:.0f}% from 52w high")

    # Bandwidth squeeze (Bollinger)
    bbw = _safe(snap.get("bbw"))
    if bbw is not None:
        if bbw < 0.05:
            details.append("⚠️ Bollinger squeeze ACTIVE — explosive move imminent")
        elif bbw > 0.15:
            details.append("Bollinger bandwidth wide — trend established")

    # Trend consistency
    primary = trend.get("primary", "SIDEWAYS")
    if primary == "UPTREND":
        score += 2; details.append("✅ Primary trend is UP (favourable for longs)")
    elif primary == "DOWNTREND":
        score -= 2; details.append("❌ Primary trend is DOWN (risky for longs)")
    else:
        details.append("⚠️ Sideways market — higher risk of whipsaws")

    normalized = _clamp(score / 5.0 * max_pts, -max_pts, max_pts)
    return {"score": round(normalized, 1), "max": max_pts, "details": details}


# ═══════════════════════════════════════════════════════════════
#  MASTER SIGNAL — FINAL VERDICT
# ═══════════════════════════════════════════════════════════════

def generate_signal(
    snap: dict,
    trend: dict,
    vol_analysis: dict,
    chart_patterns: list,
    candle_patterns: list,
    divergences: list,
    sr_data: dict,
    fib_data: dict,
) -> dict:
    """
    Generate the FINAL multi-indicator consensus signal.

    Returns:
        {
            "verdict": "STRONG BUY" | "BUY" | "HOLD" | "SELL" | "STRONG SELL",
            "score": float (-100 to +100),
            "confidence": float (0–100%),
            "categories": { trend, momentum, volume, pattern, sr, risk },
            "summary": str,
            "action_items": list[str],
        }
    """
    # Score each category
    trend_score = _score_trend(snap, trend)
    momentum_score = _score_momentum(snap, trend)
    volume_score = _score_volume(snap, vol_analysis, trend)
    pattern_score = _score_patterns(chart_patterns, candle_patterns, divergences)
    sr_score = _score_support_resistance(snap, sr_data, fib_data)
    risk_score = _score_risk(snap, trend)

    # Total score: -100 to +100
    total = (
        trend_score["score"]
        + momentum_score["score"]
        + volume_score["score"]
        + pattern_score["score"]
        + sr_score["score"]
        + risk_score["score"]
    )
    max_total = WEIGHT_TREND + WEIGHT_MOMENTUM + WEIGHT_VOLUME + WEIGHT_PATTERN + WEIGHT_SUPPORT_RES + WEIGHT_RISK

    # Confidence = how far from 0 (stronger signal = more confidence)
    confidence = min(abs(total) / max_total * 100, 100)

    # Verdict — tightened thresholds to reduce false signals
    # (score range: -100 to +100; old BUY=20, new BUY=30)
    if total >= 45:
        verdict = "STRONG BUY"
    elif total >= 30:
        verdict = "BUY"
    elif total <= -45:
        verdict = "STRONG SELL"
    elif total <= -30:
        verdict = "SELL"
    else:
        verdict = "HOLD"

    # Generate action items
    actions = _generate_actions(verdict, snap, trend, sr_data, fib_data)

    # Summary
    price = snap.get("price", 0)
    summary = (
        f"Technical analysis scores {total:+.0f}/100 → {verdict} "
        f"(Confidence: {confidence:.0f}%). "
        f"Trend: {trend.get('primary', 'N/A')} ({trend.get('strength', 'N/A')}). "
        f"Key levels: Nearest support ₹{sr_data.get('support', [{}])[0].get('level', 'N/A') if sr_data.get('support') else 'N/A'}, "
        f"Resistance ₹{sr_data.get('resistance', [{}])[0].get('level', 'N/A') if sr_data.get('resistance') else 'N/A'}."
    )

    return {
        "verdict": verdict,
        "score": round(total, 1),
        "max_score": max_total,
        "confidence": round(confidence, 1),
        "categories": {
            "trend": trend_score,
            "momentum": momentum_score,
            "volume": volume_score,
            "pattern": pattern_score,
            "support_resistance": sr_score,
            "risk": risk_score,
        },
        "summary": summary,
        "action_items": actions,
    }


def _generate_actions(verdict: str, snap: dict, trend: dict, sr_data: dict, fib_data: dict) -> list[str]:
    """Generate specific, actionable trading suggestions."""
    actions = []
    price = snap.get("price", 0)
    atr = snap.get("atr")

    if verdict in ("STRONG BUY", "BUY"):
        actions.append(f"🟢 Consider BUYING at current price ₹{price}")

        if atr:
            stop = round(price - 2 * atr, 2)
            actions.append(f"🛡️ Set STOP LOSS at ₹{stop} (2× ATR below entry)")

        # Target from resistance
        if sr_data.get("resistance"):
            target = sr_data["resistance"][0]["level"]
            actions.append(f"🎯 First TARGET: ₹{target} (nearest resistance)")
            if price and atr and target > price:
                rr = round((target - price) / (2 * atr), 1) if atr > 0 else 0
                actions.append(f"📊 Risk:Reward ratio = 1:{rr}")

        # Fibonacci target
        if fib_data.get("is_uptrend") and fib_data.get("fib_0.0"):
            actions.append(f"📐 Fibonacci extension target: ₹{fib_data.get('swing_high', 'N/A')}")

        actions.append("⏰ TIMING: Enter on a pullback to the 20-day SMA or near support for better risk:reward")

    elif verdict in ("STRONG SELL", "SELL"):
        actions.append(f"🔴 Consider SELLING / AVOIDING at ₹{price}")

        if sr_data.get("support"):
            near_support = sr_data["support"][0]["level"]
            actions.append(f"⬇️ Potential downside target: ₹{near_support}")

        actions.append("🛡️ If already holding, tighten your stop loss")
        actions.append("⏰ Wait for trend reversal confirmation before buying")

    else:  # HOLD
        actions.append(f"🟡 HOLD / WAIT at ₹{price} — no clear edge right now")
        actions.append("⏰ Wait for a decisive breakout or breakdown before acting")

        if trend.get("primary") == "SIDEWAYS":
            if sr_data.get("support"):
                actions.append(f"🟢 Buy near support ₹{sr_data['support'][0]['level']}")
            if sr_data.get("resistance"):
                actions.append(f"🔴 Sell near resistance ₹{sr_data['resistance'][0]['level']}")

    return actions
