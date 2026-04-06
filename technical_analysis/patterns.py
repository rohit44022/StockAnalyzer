"""
patterns.py — Chart Pattern & Trend Analysis.

Murphy Ch 4: Support/Resistance, Trendlines, Fibonacci
Murphy Ch 5: Head & Shoulders, Double/Triple Tops/Bottoms
Murphy Ch 6: Triangles, Flags, Pennants, Wedges, Rectangles
Murphy Ch 2: Dow Theory trend classification
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from technical_analysis.config import (
    SUPPORT_RESISTANCE_WINDOW as SR_WINDOW,
    SUPPORT_RESISTANCE_CLUSTER as SR_CLUSTER_PCT,
    PATTERN_MIN_BARS, PATTERN_MAX_BARS,
)


# ═══════════════════════════════════════════════════════════════
#  SUPPORT / RESISTANCE DETECTION  (Murphy Ch 4)
# ═══════════════════════════════════════════════════════════════

def _find_swing_points(series: pd.Series, window: int = SR_WINDOW) -> tuple[list, list]:
    """Identify local swing highs and swing lows."""
    highs, lows = [], []
    vals = series.values
    for i in range(window, len(vals) - window):
        # swing high: center is maximum of both sides
        if vals[i] == max(vals[i - window: i + window + 1]):
            highs.append((i, vals[i]))
        # swing low: center is minimum of both sides
        if vals[i] == min(vals[i - window: i + window + 1]):
            lows.append((i, vals[i]))
    return highs, lows


def _cluster_levels(price_levels: list[float], pct: float = SR_CLUSTER_PCT) -> list[float]:
    """Cluster nearby price levels into zones."""
    if not price_levels:
        return []
    levels = sorted(price_levels)
    clusters = [[levels[0]]]
    for p in levels[1:]:
        if abs(p - np.mean(clusters[-1])) / np.mean(clusters[-1]) <= pct:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    # Return average of each cluster, weighted by touch count
    return [{"level": round(np.mean(c), 2), "touches": len(c), "strength": min(len(c), 5)}
            for c in clusters]


def detect_support_resistance(df: pd.DataFrame, lookback: int = 120) -> dict:
    """
    Detect support and resistance levels from swing highs/lows.
    Returns dict with 'support' and 'resistance' lists.
    """
    window = df.tail(lookback)
    swing_highs, swing_lows = _find_swing_points(window["Close"])

    current_price = float(window["Close"].iloc[-1])

    # Separate levels above and below current price
    resistance_prices = [p for _, p in swing_highs if p > current_price * 0.99]
    support_prices = [p for _, p in swing_lows if p < current_price * 1.01]

    resistance = _cluster_levels(resistance_prices)
    support = _cluster_levels(support_prices)

    # Sort: closest first
    resistance.sort(key=lambda x: x["level"])
    support.sort(key=lambda x: x["level"], reverse=True)

    return {
        "resistance": resistance[:5],  # Top 5 levels
        "support": support[:5],
        "current_price": round(current_price, 2),
    }


# ═══════════════════════════════════════════════════════════════
#  TREND IDENTIFICATION  (Murphy Ch 2, Ch 4 — Dow Theory)
# ═══════════════════════════════════════════════════════════════

def identify_trend(df: pd.DataFrame) -> dict:
    """
    Classify the current trend using multiple methods:
    1. Moving Average alignment (price vs SMA 20/50/200)
    2. Higher Highs / Higher Lows vs Lower Highs / Lower Lows
    3. ADX strength
    4. Dow Theory classification (primary/secondary/minor)
    """
    if len(df) < 200:
        return {"primary": "INSUFFICIENT DATA", "strength": "N/A", "phase": "N/A"}

    close = df["Close"]
    last = float(close.iloc[-1])

    # MA alignment
    sma_20 = float(df["SMA_20"].iloc[-1]) if "SMA_20" in df.columns else None
    sma_50 = float(df["SMA_50"].iloc[-1]) if "SMA_50" in df.columns else None
    sma_200 = float(df["SMA_200"].iloc[-1]) if "SMA_200" in df.columns else None

    ma_bullish_count = sum(1 for ma in [sma_20, sma_50, sma_200] if ma and last > ma)
    ma_bearish_count = sum(1 for ma in [sma_20, sma_50, sma_200] if ma and last < ma)

    # Higher Highs / Higher Lows detection (over last 60 bars)
    window = df.tail(60)
    swing_h, swing_l = _find_swing_points(window["Close"], window=3)

    hh_hl = False  # Higher Highs + Higher Lows
    lh_ll = False  # Lower Highs + Lower Lows

    if len(swing_h) >= 2 and len(swing_l) >= 2:
        hh_hl = (swing_h[-1][1] > swing_h[-2][1]) and (swing_l[-1][1] > swing_l[-2][1])
        lh_ll = (swing_h[-1][1] < swing_h[-2][1]) and (swing_l[-1][1] < swing_l[-2][1])

    # ADX
    adx_val = float(df["ADX"].iloc[-1]) if "ADX" in df.columns else None
    plus_di = float(df["PLUS_DI"].iloc[-1]) if "PLUS_DI" in df.columns else None
    minus_di = float(df["MINUS_DI"].iloc[-1]) if "MINUS_DI" in df.columns else None

    # Determine primary trend
    if ma_bullish_count >= 2 and (hh_hl or (plus_di and plus_di > (minus_di or 0))):
        primary = "UPTREND"
    elif ma_bearish_count >= 2 and (lh_ll or (minus_di and minus_di > (plus_di or 0))):
        primary = "DOWNTREND"
    else:
        primary = "SIDEWAYS"

    # Trend strength
    if adx_val:
        if adx_val >= 40:
            strength = "VERY STRONG"
        elif adx_val >= 25:
            strength = "STRONG"
        elif adx_val >= 20:
            strength = "MODERATE"
        else:
            strength = "WEAK"
    else:
        strength = "MODERATE" if primary != "SIDEWAYS" else "WEAK"

    # Dow Theory phase
    pct_from_200_low = 0
    low_200 = float(df.tail(200)["Low"].min())
    high_200 = float(df.tail(200)["High"].max())
    total_range = high_200 - low_200

    if total_range > 0:
        position = (last - low_200) / total_range

        if primary == "UPTREND":
            if position > 0.75:
                phase = "DISTRIBUTION (late stage — smart money may be selling)"
            elif position > 0.4:
                phase = "PUBLIC PARTICIPATION (trend followers joining)"
            else:
                phase = "ACCUMULATION (early stage — smart money buying)"
        elif primary == "DOWNTREND":
            if position < 0.25:
                phase = "PANIC SELLING (capitulation — late stage)"
            elif position < 0.6:
                phase = "PUBLIC PARTICIPATION (trend followers selling)"
            else:
                phase = "DISTRIBUTION (early stage — smart money selling)"
        else:
            phase = "CONSOLIDATION (range-bound, waiting for breakout)"
    else:
        phase = "FLAT"

    # EMA ribbon alignment
    ema_alignment = "N/A"
    if all(f"EMA_{p}" in df.columns for p in [9, 21, 50, 200]):
        e9 = float(df["EMA_9"].iloc[-1])
        e21 = float(df["EMA_21"].iloc[-1])
        e50 = float(df["EMA_50"].iloc[-1])
        e200 = float(df["EMA_200"].iloc[-1])
        if e9 > e21 > e50 > e200:
            ema_alignment = "PERFECT BULLISH (all EMAs stacked up)"
        elif e9 < e21 < e50 < e200:
            ema_alignment = "PERFECT BEARISH (all EMAs stacked down)"
        else:
            ema_alignment = "MIXED (trend transition in progress)"

    return {
        "primary": primary,
        "strength": strength,
        "phase": phase,
        "adx": round(adx_val, 1) if adx_val else None,
        "ma_bullish": ma_bullish_count,
        "ma_bearish": ma_bearish_count,
        "higher_highs_lows": hh_hl,
        "lower_highs_lows": lh_ll,
        "ema_alignment": ema_alignment,
        "explanation": (
            f"The stock is currently in a {primary} with {strength} momentum. "
            f"Phase: {phase}. "
            f"Price is above {ma_bullish_count}/3 key moving averages. "
            f"{'Higher highs and higher lows confirm uptrend.' if hh_hl else ''}"
            f"{'Lower highs and lower lows confirm downtrend.' if lh_ll else ''}"
        ),
    }


# ═══════════════════════════════════════════════════════════════
#  CHART PATTERN DETECTION  (Murphy Ch 5-6)
# ═══════════════════════════════════════════════════════════════

def _detect_double_top_bottom(df: pd.DataFrame, lookback: int = 60) -> list[dict]:
    """Detect Double Top (M) and Double Bottom (W) patterns."""
    patterns = []
    window = df.tail(lookback)
    swing_h, swing_l = _find_swing_points(window["Close"], window=5)

    current_price = float(window["Close"].iloc[-1])

    # Double Top: two highs at roughly same level with a trough between
    if len(swing_h) >= 2:
        h1_idx, h1 = swing_h[-2]
        h2_idx, h2 = swing_h[-1]

        if abs(h1 - h2) / h1 < 0.03 and h2_idx > h1_idx + 5:
            # Find trough between the two peaks
            between = window["Close"].iloc[h1_idx:h2_idx]
            if len(between) > 0:
                trough = float(between.min())
                neckline = trough

                if current_price < neckline:
                    patterns.append({
                        "name": "Double Top (M Pattern)",
                        "type": "BEARISH",
                        "strength": 3,
                        "neckline": round(neckline, 2),
                        "target": round(neckline - (h1 - neckline), 2),
                        "meaning": (
                            f"Price tested resistance near ₹{h1:.0f} twice and failed. "
                            f"Neckline at ₹{neckline:.0f} is broken → bearish. "
                            f"Target: ₹{neckline - (h1 - neckline):.0f}"
                        ),
                    })

    # Double Bottom: two lows at roughly same level with a peak between
    if len(swing_l) >= 2:
        l1_idx, l1 = swing_l[-2]
        l2_idx, l2 = swing_l[-1]

        if abs(l1 - l2) / l1 < 0.03 and l2_idx > l1_idx + 5:
            between = window["Close"].iloc[l1_idx:l2_idx]
            if len(between) > 0:
                peak = float(between.max())
                neckline = peak

                if current_price > neckline:
                    patterns.append({
                        "name": "Double Bottom (W Pattern)",
                        "type": "BULLISH",
                        "strength": 3,
                        "neckline": round(neckline, 2),
                        "target": round(neckline + (neckline - l1), 2),
                        "meaning": (
                            f"Price tested support near ₹{l1:.0f} twice and held. "
                            f"Neckline at ₹{neckline:.0f} is broken → bullish. "
                            f"Target: ₹{neckline + (neckline - l1):.0f}"
                        ),
                    })

    return patterns


def _detect_head_and_shoulders(df: pd.DataFrame, lookback: int = 80) -> list[dict]:
    """Detect Head & Shoulders (bearish) and Inverse H&S (bullish)."""
    patterns = []
    window = df.tail(lookback)
    swing_h, swing_l = _find_swing_points(window["Close"], window=5)
    current_price = float(window["Close"].iloc[-1])

    # H&S Top: three peaks where middle > sides
    if len(swing_h) >= 3:
        ls_idx, ls = swing_h[-3]  # Left shoulder
        h_idx, head = swing_h[-2]  # Head
        rs_idx, rs = swing_h[-1]  # Right shoulder

        if (head > ls and head > rs
                and abs(ls - rs) / ls < 0.05  # Shoulders roughly equal
                and h_idx > ls_idx and rs_idx > h_idx):
            # Neckline from troughs between shoulders and head
            troughs = [p for idx, p in swing_l if ls_idx < idx < rs_idx]
            if troughs:
                neckline = np.mean(troughs)
                if current_price < neckline:
                    patterns.append({
                        "name": "Head & Shoulders (Top)",
                        "type": "BEARISH",
                        "strength": 3,
                        "neckline": round(neckline, 2),
                        "target": round(neckline - (head - neckline), 2),
                        "meaning": (
                            f"Classic Head & Shoulders reversal pattern detected. "
                            f"Head at ₹{head:.0f}, neckline at ₹{neckline:.0f}. "
                            f"Neckline broken → bearish target ₹{neckline - (head - neckline):.0f}."
                        ),
                    })

    # Inverse H&S: three troughs where middle < sides
    if len(swing_l) >= 3:
        ls_idx, ls = swing_l[-3]
        h_idx, head = swing_l[-2]
        rs_idx, rs = swing_l[-1]

        if (head < ls and head < rs
                and abs(ls - rs) / ls < 0.05
                and h_idx > ls_idx and rs_idx > h_idx):
            peaks = [p for idx, p in swing_h if ls_idx < idx < rs_idx]
            if peaks:
                neckline = np.mean(peaks)
                if current_price > neckline:
                    patterns.append({
                        "name": "Inverse Head & Shoulders (Bottom)",
                        "type": "BULLISH",
                        "strength": 3,
                        "neckline": round(neckline, 2),
                        "target": round(neckline + (neckline - head), 2),
                        "meaning": (
                            f"Inverse Head & Shoulders (bullish reversal). "
                            f"Head at ₹{head:.0f}, neckline at ₹{neckline:.0f}. "
                            f"Neckline broken → bullish target ₹{neckline + (neckline - head):.0f}."
                        ),
                    })

    return patterns


def _detect_triangle(df: pd.DataFrame, lookback: int = 60) -> list[dict]:
    """Detect Ascending, Descending, and Symmetrical Triangles."""
    patterns = []
    window = df.tail(lookback)
    swing_h, swing_l = _find_swing_points(window["Close"], window=3)

    if len(swing_h) < 3 or len(swing_l) < 3:
        return patterns

    # Check if highs are declining, flat, or rising
    highs = [p for _, p in swing_h[-4:]]
    lows = [p for _, p in swing_l[-4:]]

    if len(highs) >= 3 and len(lows) >= 3:
        high_slope = (highs[-1] - highs[0]) / len(highs)
        low_slope = (lows[-1] - lows[0]) / len(lows)

        avg_h = np.mean(highs)
        avg_l = np.mean(lows)
        range_pct = abs(high_slope) / avg_h if avg_h else 0
        low_range_pct = abs(low_slope) / avg_l if avg_l else 0

        # Ascending Triangle: flat top + rising bottom
        if range_pct < 0.01 and low_slope > 0:
            patterns.append({
                "name": "Ascending Triangle",
                "type": "BULLISH",
                "strength": 2,
                "resistance": round(np.mean(highs), 2),
                "meaning": (
                    "Ascending Triangle: Flat resistance line with rising support. "
                    "Buyers are getting more aggressive each pullback. "
                    "Usually breaks upward — bullish bias."
                ),
            })

        # Descending Triangle: flat bottom + falling top
        elif low_range_pct < 0.01 and high_slope < 0:
            patterns.append({
                "name": "Descending Triangle",
                "type": "BEARISH",
                "strength": 2,
                "support": round(np.mean(lows), 2),
                "meaning": (
                    "Descending Triangle: Flat support line with falling resistance. "
                    "Sellers are getting more aggressive each bounce. "
                    "Usually breaks downward — bearish bias."
                ),
            })

        # Symmetrical Triangle: converging from both sides
        elif high_slope < 0 and low_slope > 0:
            patterns.append({
                "name": "Symmetrical Triangle",
                "type": "NEUTRAL",
                "strength": 2,
                "meaning": (
                    "Symmetrical Triangle: Both highs and lows converging. "
                    "Market is coiling — expect a powerful breakout soon. "
                    "Direction depends on existing trend (usually continuation)."
                ),
            })

    return patterns


def _detect_channel(df: pd.DataFrame, lookback: int = 40) -> list[dict]:
    """Detect price channels (ascending/descending)."""
    patterns = []
    window = df.tail(lookback)
    swing_h, swing_l = _find_swing_points(window["Close"], window=3)

    if len(swing_h) >= 2 and len(swing_l) >= 2:
        highs = [p for _, p in swing_h]
        lows = [p for _, p in swing_l]

        h_slope = (highs[-1] - highs[0]) / max(len(highs) - 1, 1)
        l_slope = (lows[-1] - lows[0]) / max(len(lows) - 1, 1)

        # Both sloping in same direction with similar magnitude
        if h_slope > 0 and l_slope > 0 and abs(h_slope - l_slope) / max(abs(h_slope), 0.01) < 0.5:
            patterns.append({
                "name": "Ascending Channel",
                "type": "BULLISH",
                "strength": 2,
                "meaning": (
                    "Price is moving up within parallel rising trendlines. "
                    "Buy near the lower channel line, sell near the upper line."
                ),
            })
        elif h_slope < 0 and l_slope < 0 and abs(h_slope - l_slope) / max(abs(h_slope), 0.01) < 0.5:
            patterns.append({
                "name": "Descending Channel",
                "type": "BEARISH",
                "strength": 2,
                "meaning": (
                    "Price is moving down within parallel falling trendlines. "
                    "Sell near the upper channel line, look for support at the lower line."
                ),
            })

    return patterns


def detect_all_chart_patterns(df: pd.DataFrame) -> list[dict]:
    """Run all chart pattern detectors and return combined results."""
    patterns = []
    patterns.extend(_detect_double_top_bottom(df))
    patterns.extend(_detect_head_and_shoulders(df))
    patterns.extend(_detect_triangle(df))
    patterns.extend(_detect_channel(df))
    return patterns


# ═══════════════════════════════════════════════════════════════
#  VOLUME ANALYSIS  (Murphy Ch 7)
# ═══════════════════════════════════════════════════════════════

def analyze_volume(df: pd.DataFrame) -> dict:
    """Comprehensive volume analysis per Murphy Ch 7."""
    if len(df) < 50:
        return {"status": "INSUFFICIENT DATA"}

    vol = df["Volume"]
    close = df["Close"]

    # Volume SMA
    vol_sma_20 = float(vol.rolling(20).mean().iloc[-1])
    current_vol = float(vol.iloc[-1])
    vol_ratio = current_vol / vol_sma_20 if vol_sma_20 > 0 else 1.0

    # OBV trend
    obv_trend = "NEUTRAL"
    if "OBV" in df.columns and "OBV_SMA" in df.columns:
        obv_val = float(df["OBV"].iloc[-1])
        obv_sma = float(df["OBV_SMA"].iloc[-1])
        if obv_val > obv_sma:
            obv_trend = "BULLISH (accumulation)"
        else:
            obv_trend = "BEARISH (distribution)"

    # Price-Volume relationship (last 5 days)
    recent = df.tail(5)
    pv_signals = []
    for i in range(1, len(recent)):
        p_up = float(recent["Close"].iloc[i]) > float(recent["Close"].iloc[i - 1])
        v_up = float(recent["Volume"].iloc[i]) > float(recent["Volume"].iloc[i - 1])

        if p_up and v_up:
            pv_signals.append("BULLISH")
        elif not p_up and v_up:
            pv_signals.append("BEARISH")
        elif p_up and not v_up:
            pv_signals.append("WEAK_BULLISH")
        else:
            pv_signals.append("WEAK_BEARISH")

    bullish_count = pv_signals.count("BULLISH") + pv_signals.count("WEAK_BULLISH")
    bearish_count = pv_signals.count("BEARISH") + pv_signals.count("WEAK_BEARISH")

    if bullish_count > bearish_count:
        pv_overall = "BULLISH — price rising with volume support"
    elif bearish_count > bullish_count:
        pv_overall = "BEARISH — price falling with volume support"
    else:
        pv_overall = "NEUTRAL — mixed price-volume signals"

    return {
        "current_volume": int(current_vol),
        "avg_volume_20": int(vol_sma_20),
        "volume_ratio": round(vol_ratio, 2),
        "volume_status": (
            "VERY HIGH" if vol_ratio > 2.0 else
            "HIGH" if vol_ratio > 1.5 else
            "NORMAL" if vol_ratio > 0.7 else
            "LOW"
        ),
        "obv_trend": obv_trend,
        "price_volume_relationship": pv_overall,
        "explanation": (
            f"Today's volume is {vol_ratio:.1f}x the 20-day average. "
            f"{'This high volume confirms the current move.' if vol_ratio > 1.5 else 'Volume is typical — no unusual activity.'} "
            f"OBV is {obv_trend}. "
            f"Price-volume analysis: {pv_overall}."
        ),
    }


# ═══════════════════════════════════════════════════════════════
#  ICHIMOKU ANALYSIS  (Comprehensive cloud interpretation)
# ═══════════════════════════════════════════════════════════════

def analyze_ichimoku(df: pd.DataFrame) -> dict:
    """Full Ichimoku analysis with layman-friendly interpretation."""
    required = ["ICHI_Tenkan", "ICHI_Kijun", "ICHI_SpanA", "ICHI_SpanB"]
    if not all(col in df.columns for col in required):
        return {"status": "NOT COMPUTED"}

    last = df.iloc[-1]
    price = float(last["Close"])
    tenkan = float(last["ICHI_Tenkan"])
    kijun = float(last["ICHI_Kijun"])
    span_a = float(last["ICHI_SpanA"]) if not pd.isna(last["ICHI_SpanA"]) else None
    span_b = float(last["ICHI_SpanB"]) if not pd.isna(last["ICHI_SpanB"]) else None

    signals = []
    score = 0

    # 1. Price vs Cloud
    if span_a is not None and span_b is not None:
        cloud_top = max(span_a, span_b)
        cloud_bottom = min(span_a, span_b)

        if price > cloud_top:
            signals.append("Price ABOVE cloud — BULLISH")
            score += 2
        elif price < cloud_bottom:
            signals.append("Price BELOW cloud — BEARISH")
            score -= 2
        else:
            signals.append("Price INSIDE cloud — NEUTRAL (transition zone)")

        # Cloud color
        if span_a > span_b:
            signals.append("Cloud is GREEN (Senkou A > B) — bullish bias ahead")
            score += 1
        else:
            signals.append("Cloud is RED (Senkou B > A) — bearish bias ahead")
            score -= 1

    # 2. Tenkan/Kijun cross
    if tenkan > kijun:
        signals.append("Tenkan above Kijun — short-term momentum is BULLISH")
        score += 1
    else:
        signals.append("Tenkan below Kijun — short-term momentum is BEARISH")
        score -= 1

    # 3. Chikou Span (if computable)
    if "ICHI_Chikou" in df.columns and len(df) > 26:
        chikou_idx = -27  # Chikou is current close plotted 26 periods back
        if abs(chikou_idx) < len(df):
            price_26_ago = float(df["Close"].iloc[chikou_idx])
            if price > price_26_ago:
                signals.append("Chikou Span above past price — confirms BULLISH")
                score += 1
            else:
                signals.append("Chikou Span below past price — confirms BEARISH")
                score -= 1

    if score >= 3:
        verdict = "STRONG BUY — all Ichimoku signals aligned bullish"
    elif score >= 1:
        verdict = "LEAN BULLISH — most Ichimoku signals positive"
    elif score <= -3:
        verdict = "STRONG SELL — all Ichimoku signals aligned bearish"
    elif score <= -1:
        verdict = "LEAN BEARISH — most Ichimoku signals negative"
    else:
        verdict = "NEUTRAL — mixed Ichimoku signals"

    return {
        "score": score,
        "verdict": verdict,
        "signals": signals,
        "tenkan": round(tenkan, 2),
        "kijun": round(kijun, 2),
        "span_a": round(span_a, 2) if span_a else None,
        "span_b": round(span_b, 2) if span_b else None,
    }
