"""
target_price.py — Multi-Method Target Price Calculator.

Combines 7 different target price methods used by professional analysts:
  1. Fibonacci Extension Targets
  2. Support/Resistance-Based Targets
  3. ATR-Based Targets (Volatility Projection)
  4. Moving Average Envelope Targets
  5. Bollinger Band Projection Targets
  6. Pattern-Based Targets (from chart patterns)
  7. Pivot Point Targets

Each method produces a target with a confidence level.
The final composite target is a weighted average of all methods.
"""

from __future__ import annotations
import math
import numpy as np
import pandas as pd


def _safe(v):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return None
    return round(float(v), 2)


# ═══════════════════════════════════════════════════════════════
#  1. FIBONACCI EXTENSION TARGETS
# ═══════════════════════════════════════════════════════════════

def _fibonacci_targets(snap: dict, fib_data: dict) -> list:
    """
    Fibonacci extension levels project where price may go BEYOND
    the previous swing high/low.

    Extensions: 1.0 (full retracement), 1.272, 1.618 (golden), 2.0, 2.618
    """
    targets = []
    price = snap.get("price")
    if not price:
        return targets

    swing_high = fib_data.get("swing_high")
    swing_low = fib_data.get("swing_low")
    is_uptrend = fib_data.get("is_uptrend")

    if not swing_high or not swing_low or swing_high == swing_low:
        return targets

    swing_range = swing_high - swing_low

    if is_uptrend:
        # Uptrend: targets are above the swing high
        extensions = [
            (1.0, "Swing High Retest", 80),
            (1.272, "127.2% Extension", 65),
            (1.618, "161.8% Golden Extension", 55),
            (2.0, "200% Extension", 40),
            (2.618, "261.8% Extension", 25),
        ]
        for ratio, label, conf in extensions:
            level = swing_low + swing_range * ratio
            if level > price:
                upside = (level - price) / price * 100
                targets.append({
                    "method": "Fibonacci Extension",
                    "label": label,
                    "target": _safe(level),
                    "upside_pct": round(upside, 1),
                    "confidence": conf,
                    "direction": "UP",
                    "explanation": (
                        f"Fibonacci {label} projects price to ₹{level:.2f} "
                        f"({upside:.1f}% upside). This level is calculated by "
                        f"extending the swing range (₹{swing_low:.2f} → ₹{swing_high:.2f}) "
                        f"by {ratio:.3f}x. The 161.8% (golden ratio) is the most "
                        f"watched extension level by professional traders."
                    ),
                })
    else:
        # Downtrend: targets are below the swing low
        extensions = [
            (1.0, "Swing Low Retest", 80),
            (1.272, "127.2% Extension", 65),
            (1.618, "161.8% Golden Extension", 55),
        ]
        for ratio, label, conf in extensions:
            level = swing_high - swing_range * ratio
            if level < price and level > 0:
                downside = (price - level) / price * 100
                targets.append({
                    "method": "Fibonacci Extension",
                    "label": label,
                    "target": _safe(level),
                    "downside_pct": round(downside, 1),
                    "confidence": conf,
                    "direction": "DOWN",
                    "explanation": (
                        f"Fibonacci {label} projects price to ₹{level:.2f} "
                        f"({downside:.1f}% downside). Calculated by extending "
                        f"the swing range downward by {ratio:.3f}x."
                    ),
                })

    return targets


# ═══════════════════════════════════════════════════════════════
#  2. SUPPORT/RESISTANCE-BASED TARGETS
# ═══════════════════════════════════════════════════════════════

def _sr_targets(snap: dict, sr_data: dict) -> list:
    """
    Use nearest support and resistance levels as natural price targets.
    Stronger levels (more touches) get higher confidence.
    """
    targets = []
    price = snap.get("price")
    if not price:
        return targets

    # Upside targets from resistance levels
    for r in sr_data.get("resistance", []):
        level = r["level"]
        touches = r.get("touches", 1)
        strength = r.get("strength", 1)
        upside = (level - price) / price * 100
        if upside > 0.5:  # At least 0.5% away
            conf = min(40 + touches * 10 + strength * 5, 90)
            targets.append({
                "method": "Resistance Level",
                "label": f"R @ ₹{level} ({touches} touches)",
                "target": _safe(level),
                "upside_pct": round(upside, 1),
                "confidence": conf,
                "direction": "UP",
                "explanation": (
                    f"Resistance at ₹{level:.2f} has been tested {touches} time(s). "
                    f"This is {upside:.1f}% above current price. Stocks often rally "
                    f"to resistance levels before facing selling pressure. "
                    f"A breakout above this level could trigger further upside."
                ),
            })

    # Downside targets from support levels
    for s in sr_data.get("support", []):
        level = s["level"]
        touches = s.get("touches", 1)
        strength = s.get("strength", 1)
        downside = (price - level) / price * 100
        if downside > 0.5:
            conf = min(40 + touches * 10 + strength * 5, 90)
            targets.append({
                "method": "Support Level",
                "label": f"S @ ₹{level} ({touches} touches)",
                "target": _safe(level),
                "downside_pct": round(downside, 1),
                "confidence": conf,
                "direction": "DOWN",
                "explanation": (
                    f"Support at ₹{level:.2f} has been tested {touches} time(s). "
                    f"This is {downside:.1f}% below current price. Stocks often "
                    f"find buying interest at support levels. A breakdown below "
                    f"this level could trigger further downside."
                ),
            })

    return targets


# ═══════════════════════════════════════════════════════════════
#  3. ATR-BASED TARGETS (Volatility Projection)
# ═══════════════════════════════════════════════════════════════

def _atr_targets(snap: dict, trend: dict) -> list:
    """
    ATR (Average True Range) measures daily volatility.
    Project targets using multiples of ATR for different timeframes.

    1× ATR = typical 1-day move
    5× ATR ≈ 1-week potential move
    10× ATR ≈ 2-week potential move
    20× ATR ≈ 1-month potential move
    """
    targets = []
    price = snap.get("price")
    atr = snap.get("atr")
    if not price or not atr:
        return targets

    primary = trend.get("primary", "SIDEWAYS")

    horizons = [
        (3, "Short-term (3-day)", 75),
        (5, "1-Week", 65),
        (10, "2-Week", 50),
        (20, "1-Month", 35),
    ]

    for mult, label, conf in horizons:
        if primary in ("UPTREND",):
            level = price + atr * mult
            pct = atr * mult / price * 100
            targets.append({
                "method": "ATR Projection",
                "label": f"{label} Upside",
                "target": _safe(level),
                "upside_pct": round(pct, 1),
                "confidence": conf,
                "direction": "UP",
                "explanation": (
                    f"Based on ATR of ₹{atr:.2f} ({atr/price*100:.1f}% of price), "
                    f"the stock can potentially move ₹{atr*mult:.2f} ({pct:.1f}%) "
                    f"over {label.lower()}. In an uptrend, this projects to ₹{level:.2f}. "
                    f"ATR-based targets account for the stock's actual volatility — "
                    f"high-volatility stocks naturally have wider target ranges."
                ),
            })
        elif primary in ("DOWNTREND",):
            level = price - atr * mult
            if level > 0:
                pct = atr * mult / price * 100
                targets.append({
                    "method": "ATR Projection",
                    "label": f"{label} Downside",
                    "target": _safe(level),
                    "downside_pct": round(pct, 1),
                    "confidence": conf,
                    "direction": "DOWN",
                    "explanation": (
                        f"Based on ATR of ₹{atr:.2f}, the stock can potentially "
                        f"decline ₹{atr*mult:.2f} ({pct:.1f}%) over {label.lower()}. "
                        f"In a downtrend, this projects to ₹{level:.2f}."
                    ),
                })
        else:
            # Sideways: give both
            up_level = price + atr * mult
            dn_level = max(price - atr * mult, price * 0.50)  # Floor at 50% of price
            pct = atr * mult / price * 100
            targets.append({
                "method": "ATR Projection",
                "label": f"{label} Range",
                "target": _safe(up_level),
                "target_low": _safe(dn_level),
                "range_pct": round(pct * 2, 1),
                "confidence": conf,
                "direction": "RANGE",
                "explanation": (
                    f"In a sideways market, expect price to oscillate between "
                    f"₹{dn_level:.2f} and ₹{up_level:.2f} over {label.lower()} "
                    f"(total range: {pct*2:.1f}% based on {mult}× ATR of ₹{atr:.2f})."
                ),
            })

    return targets


# ═══════════════════════════════════════════════════════════════
#  4. MOVING AVERAGE TARGETS
# ═══════════════════════════════════════════════════════════════

def _ma_targets(snap: dict) -> list:
    """
    Moving averages act as magnets — prices tend to revert to key MAs.
    When price is far from an MA, it often moves back toward it.
    """
    targets = []
    price = snap.get("price")
    if not price:
        return targets

    ma_levels = [
        ("SMA 20 (Short-term)", snap.get("sma_20"), 70),
        ("SMA 50 (Medium-term)", snap.get("sma_50"), 65),
        ("SMA 200 (Long-term)", snap.get("sma_200"), 55),
        ("EMA 21 (Swing)", snap.get("ema_21"), 68),
    ]

    for label, ma, conf in ma_levels:
        if not ma:
            continue
        dist_pct = (ma - price) / price * 100
        if abs(dist_pct) < 0.5:
            continue  # Too close, not useful

        direction = "UP" if ma > price else "DOWN"
        targets.append({
            "method": "Moving Average Magnet",
            "label": label,
            "target": _safe(ma),
            "distance_pct": round(abs(dist_pct), 1),
            "confidence": conf,
            "direction": direction,
            "explanation": (
                f"{label} is at ₹{ma:.2f} ({abs(dist_pct):.1f}% {'above' if ma > price else 'below'} "
                f"current price). Moving averages act as 'magnets' — when price drifts "
                f"too far away, it tends to snap back. The {'200-day SMA is the most important' if '200' in label else '50-day SMA'} "
                f"for institutional investors who use it as a key benchmark."
            ),
        })

    return targets


# ═══════════════════════════════════════════════════════════════
#  5. BOLLINGER BAND PROJECTION TARGETS
# ═══════════════════════════════════════════════════════════════

def _bb_targets(snap: dict) -> list:
    """
    Bollinger Bands contain ~88% of price action.
    Upper band = potential upside target, lower band = downside risk.
    """
    targets = []
    price = snap.get("price")
    bb_upper = snap.get("bb_upper")
    bb_lower = snap.get("bb_lower")
    bb_mid = snap.get("bb_mid")
    pct_b = snap.get("percent_b")

    if not price or not bb_upper or not bb_lower:
        return targets

    # Upper band target
    if bb_upper > price:
        dist = (bb_upper - price) / price * 100
        conf = 70 if pct_b and pct_b > 0.5 else 50
        targets.append({
            "method": "Bollinger Band",
            "label": "Upper Band Target",
            "target": _safe(bb_upper),
            "upside_pct": round(dist, 1),
            "confidence": conf,
            "direction": "UP",
            "explanation": (
                f"Upper Bollinger Band at ₹{bb_upper:.2f} ({dist:.1f}% above). "
                f"In an uptrend, price often walks along or touches the upper band. "
                f"Current %b = {pct_b:.2f} — {'approaching upper band' if pct_b and pct_b > 0.7 else 'room to move up'}. "
                f"The band contains ~88% of price action (2 standard deviations)."
            ),
        })

    # Lower band / risk level
    if bb_lower < price:
        dist = (price - bb_lower) / price * 100
        targets.append({
            "method": "Bollinger Band",
            "label": "Lower Band Risk",
            "target": _safe(bb_lower),
            "downside_pct": round(dist, 1),
            "confidence": 60,
            "direction": "DOWN",
            "explanation": (
                f"Lower Bollinger Band at ₹{bb_lower:.2f} ({dist:.1f}% below). "
                f"Price rarely stays below the lower band for long — this acts as "
                f"a natural floor in normal conditions. A close below it signals "
                f"extreme weakness."
            ),
        })

    # Mean reversion to mid band
    if bb_mid and abs(price - bb_mid) / price * 100 > 1:
        dist = (bb_mid - price) / price * 100
        direction = "UP" if bb_mid > price else "DOWN"
        targets.append({
            "method": "Bollinger Band",
            "label": "Mean Reversion (Mid Band)",
            "target": _safe(bb_mid),
            "distance_pct": round(abs(dist), 1),
            "confidence": 65,
            "direction": direction,
            "explanation": (
                f"The middle Bollinger Band (20-SMA) at ₹{bb_mid:.2f} is the mean. "
                f"When price extends too far {'below' if direction=='UP' else 'above'} it, "
                f"a snap-back to the mean is common. This is the basis of 'mean reversion' trading."
            ),
        })

    return targets


# ═══════════════════════════════════════════════════════════════
#  6. PATTERN-BASED TARGETS
# ═══════════════════════════════════════════════════════════════

def _pattern_targets(snap: dict, chart_patterns: list) -> list:
    """
    Classical chart patterns have measured-move targets.
    E.g., Head & Shoulders target = neckline ± pattern height.
    """
    targets = []
    price = snap.get("price")
    if not price:
        return targets

    for p in chart_patterns:
        target = p.get("target")
        neckline = p.get("neckline")
        name = p.get("name", "")
        ptype = p.get("type", "")

        if target:
            if ptype == "BULLISH":
                dist = (target - price) / price * 100
                if dist > 0:
                    targets.append({
                        "method": "Chart Pattern",
                        "label": f"{name} Target",
                        "target": _safe(target),
                        "upside_pct": round(dist, 1),
                        "confidence": min(p.get("strength", 1) * 25, 75),
                        "direction": "UP",
                        "explanation": (
                            f"The {name} pattern projects a target of ₹{target:.2f} "
                            f"({dist:.1f}% upside). Pattern targets are calculated by "
                            f"measuring the pattern's height and projecting it from the "
                            f"breakout point. {'Neckline at ₹' + str(neckline) + '.' if neckline else ''}"
                        ),
                    })
            elif ptype == "BEARISH":
                dist = (price - target) / price * 100
                if dist > 0:
                    targets.append({
                        "method": "Chart Pattern",
                        "label": f"{name} Target",
                        "target": _safe(target),
                        "downside_pct": round(dist, 1),
                        "confidence": min(p.get("strength", 1) * 25, 75),
                        "direction": "DOWN",
                        "explanation": (
                            f"The {name} pattern projects a downside target of ₹{target:.2f} "
                            f"({dist:.1f}% downside). {'Neckline at ₹' + str(neckline) + '.' if neckline else ''}"
                        ),
                    })

    return targets


# ═══════════════════════════════════════════════════════════════
#  7. PIVOT POINT TARGETS
# ═══════════════════════════════════════════════════════════════

def _pivot_targets(snap: dict, pivot: dict) -> list:
    """Pivot points are widely used by day and swing traders."""
    targets = []
    price = snap.get("price")
    if not price:
        return targets

    # Upside pivots
    for key in ["R1", "R2", "R3"]:
        level = pivot.get(key)
        if level and level > price:
            dist = (level - price) / price * 100
            conf = {"R1": 70, "R2": 55, "R3": 35}.get(key, 50)
            targets.append({
                "method": "Pivot Point",
                "label": key,
                "target": _safe(level),
                "upside_pct": round(dist, 1),
                "confidence": conf,
                "direction": "UP",
                "explanation": (
                    f"Pivot {key} at ₹{level:.2f} ({dist:.1f}% above). "
                    f"Pivot points are calculated from yesterday's High, Low, Close. "
                    f"R1 is the first resistance (most likely to reach), R2 is moderate, "
                    f"R3 is the extreme target for a very strong day."
                ),
            })

    # Downside pivots
    for key in ["S1", "S2", "S3"]:
        level = pivot.get(key)
        if level and level < price:
            dist = (price - level) / price * 100
            conf = {"S1": 70, "S2": 55, "S3": 35}.get(key, 50)
            targets.append({
                "method": "Pivot Point",
                "label": key,
                "target": _safe(level),
                "downside_pct": round(dist, 1),
                "confidence": conf,
                "direction": "DOWN",
                "explanation": (
                    f"Pivot {key} at ₹{level:.2f} ({dist:.1f}% below). "
                    f"Support pivots act as natural price floors. S1 is the first "
                    f"support (most likely), S2 is moderate, S3 is the extreme "
                    f"support for a very weak day."
                ),
            })

    return targets


# ═══════════════════════════════════════════════════════════════
#  COMPOSITE TARGET PRICE ENGINE
# ═══════════════════════════════════════════════════════════════

def calculate_target_prices(
    snap: dict,
    trend: dict,
    sr_data: dict,
    fib_data: dict,
    pivot: dict,
    chart_patterns: list,
) -> dict:
    """
    Master target price calculator — combines all 7 methods.

    Returns a comprehensive target price report including:
      - Individual method targets
      - Consensus upside/downside targets
      - Weighted composite target
      - Risk:Reward assessment
    """
    price = snap.get("price")
    if not price:
        return {"error": "No price data available"}

    # Collect all targets from all methods
    all_targets = []
    all_targets.extend(_fibonacci_targets(snap, fib_data))
    all_targets.extend(_sr_targets(snap, sr_data))
    all_targets.extend(_atr_targets(snap, trend))
    all_targets.extend(_ma_targets(snap))
    all_targets.extend(_bb_targets(snap))
    all_targets.extend(_pattern_targets(snap, chart_patterns))
    all_targets.extend(_pivot_targets(snap, pivot))

    # Separate upside and downside
    upside_targets = [t for t in all_targets if t["direction"] == "UP"]
    downside_targets = [t for t in all_targets if t["direction"] == "DOWN"]
    range_targets = [t for t in all_targets if t["direction"] == "RANGE"]

    # Calculate weighted consensus targets
    consensus_up = _weighted_consensus(upside_targets, price, "UP")
    consensus_down = _weighted_consensus(downside_targets, price, "DOWN")

    # Overall assessment
    primary_trend = trend.get("primary", "SIDEWAYS")

    if primary_trend == "UPTREND" and consensus_up:
        bias = "BULLISH"
        primary_target = consensus_up
        bias_explanation = (
            f"The stock is in an UPTREND. Based on {len(upside_targets)} upside projections "
            f"from {len(set(t['method'] for t in upside_targets))} different methods, "
            f"the consensus upside target is ₹{consensus_up['target']:.2f} "
            f"({consensus_up['pct']:.1f}% above current price ₹{price:.2f}). "
            f"This target is a confidence-weighted average — methods with higher "
            f"confidence (like nearby S/R levels) contribute more than distant projections."
        )
    elif primary_trend == "DOWNTREND" and consensus_down:
        bias = "BEARISH"
        primary_target = consensus_down
        bias_explanation = (
            f"The stock is in a DOWNTREND. Based on {len(downside_targets)} downside projections, "
            f"the consensus downside target is ₹{consensus_down['target']:.2f} "
            f"({consensus_down['pct']:.1f}% below current price ₹{price:.2f}). "
            f"Consider this as a potential where price could go if the downtrend continues."
        )
    else:
        bias = "NEUTRAL"
        primary_target = consensus_up if consensus_up else consensus_down
        bias_explanation = (
            f"The stock is in a SIDEWAYS/NEUTRAL phase. "
            f"{'Upside target: ₹' + str(consensus_up['target']) + ' (' + str(consensus_up['pct']) + '%)' if consensus_up else 'No clear upside target'}. "
            f"{'Downside risk: ₹' + str(consensus_down['target']) + ' (' + str(consensus_down['pct']) + '%)' if consensus_down else 'No clear downside risk'}. "
            f"In a range-bound market, trade between support and resistance."
        )

    # Risk:Reward ratio
    rr_ratio = None
    if consensus_up and consensus_down:
        upside_dist = consensus_up["target"] - price
        downside_dist = price - consensus_down["target"]
        if downside_dist > 0:
            rr_ratio = round(upside_dist / downside_dist, 2)

    return {
        "current_price": _safe(price),
        "bias": bias,
        "bias_explanation": bias_explanation,
        "consensus_upside": consensus_up,
        "consensus_downside": consensus_down,
        "risk_reward_ratio": rr_ratio,
        "risk_reward_explanation": _rr_explanation(rr_ratio),
        "upside_targets": sorted(upside_targets, key=lambda t: t.get("target", 0)),
        "downside_targets": sorted(downside_targets, key=lambda t: t.get("target", 0), reverse=True),
        "range_targets": range_targets,
        "total_methods_used": len(set(t["method"] for t in all_targets)),
        "total_targets_computed": len(all_targets),
        "methodology_explanation": (
            "Target prices are computed using 7 independent methods: "
            "Fibonacci Extensions (based on swing highs/lows), "
            "Support/Resistance Levels (from price history), "
            "ATR Volatility Projections (based on average daily range), "
            "Moving Average Magnets (prices tend to revert to key MAs), "
            "Bollinger Band Projections (2-std-dev envelope), "
            "Chart Pattern Measured Moves (classical pattern targets), "
            "and Pivot Point Levels (daily floor trader pivots). "
            "The consensus target is a confidence-weighted average of all methods."
        ),
    }


def _weighted_consensus(targets: list, price: float, direction: str) -> dict | None:
    """Calculate confidence-weighted consensus target."""
    if not targets:
        return None

    total_weight = sum(t["confidence"] for t in targets)
    if total_weight == 0:
        return None

    weighted_target = sum(t["target"] * t["confidence"] for t in targets) / total_weight
    avg_confidence = total_weight / len(targets)

    pct = abs(weighted_target - price) / price * 100

    return {
        "target": _safe(weighted_target),
        "pct": round(pct, 1),
        "confidence": round(avg_confidence, 0),
        "num_methods": len(set(t["method"] for t in targets)),
        "num_targets": len(targets),
    }


def _rr_explanation(rr: float | None) -> str:
    if rr is None:
        return "Cannot calculate Risk:Reward — insufficient upside or downside targets."
    if rr >= 3:
        return (
            f"Risk:Reward = 1:{rr:.1f} — EXCELLENT. For every ₹1 you risk, "
            f"the potential reward is ₹{rr:.1f}. Professional traders look for "
            f"minimum 1:2, and this exceeds that threshold significantly. "
            f"This is a favourable setup for position entry."
        )
    elif rr >= 2:
        return (
            f"Risk:Reward = 1:{rr:.1f} — GOOD. Meets the professional minimum "
            f"of 1:2. For every ₹1 risked, potential reward is ₹{rr:.1f}. "
            f"This trade makes mathematical sense over many repetitions."
        )
    elif rr >= 1:
        return (
            f"Risk:Reward = 1:{rr:.1f} — MARGINAL. The potential reward is only "
            f"slightly more than the risk. Only take this trade if you have very "
            f"high conviction from other indicators."
        )
    else:
        return (
            f"Risk:Reward = 1:{rr:.1f} — POOR. The potential downside exceeds "
            f"the potential upside. Professional traders avoid trades where the "
            f"risk exceeds the reward. Wait for a better entry point."
        )
