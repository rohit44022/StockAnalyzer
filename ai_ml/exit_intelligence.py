"""
ai_ml/exit_intelligence.py — Exit Timing Advisor

Assesses post-entry momentum health for each pick and recommends
whether to hold, tighten stops, or consider exiting.

Rule-based v1 using indicators already on each pick's bb_data.
Adds exit_intelligence dict per pick WITHOUT modifying existing fields.
"""
from __future__ import annotations

import logging

from ai_ml.config import EXIT_URGENCY_THRESHOLDS

logger = logging.getLogger("ai_ml.exit_intelligence")

_HOLD_ESTIMATES = {
    "M1": "15-20", "M2": "20-25", "M3": "10-15", "M4": "20-25",
}


def _score_exit_urgency(indicators: dict, price: float | None = None) -> tuple[int, dict]:
    """
    Score exit urgency 0-100 from current indicators.
    Higher = more urgent to exit.
    Returns (score, signal_details).
    """
    score = 0
    sigs = {}

    rsi = indicators.get("rsi") or indicators.get("rsi14")
    bbw = indicators.get("bbw") or indicators.get("bandwidth")
    volume = indicators.get("volume", 0)
    vol_avg = (indicators.get("vol_avg") or indicators.get("vol_ma")
               or indicators.get("avg_volume", 0))
    sma20 = indicators.get("sma20") or indicators.get("sma_20")
    sar_bull = indicators.get("sar_bull")

    # 1. RSI overbought
    sigs["rsi_overbought"] = rsi is not None and rsi > 75
    if sigs["rsi_overbought"]:
        score += 25

    # 2. RSI declining (use slope if available, else check value)
    rsi_slope = indicators.get("rsi_slope")
    sigs["rsi_declining"] = rsi_slope is not None and rsi_slope < -1.0
    if sigs["rsi_declining"]:
        score += 15

    # 3. BBW contracting (squeeze energy dying after expansion)
    bbw_slope = indicators.get("bbw_slope") or indicators.get("sma20_slope")
    sigs["bbw_contracting"] = False
    if bbw is not None and bbw < 0.06:
        sigs["bbw_contracting"] = True
        score += 10
    # If we have explicit BBW expansion ending signal
    expansion_end = indicators.get("expansion_end")
    if expansion_end:
        sigs["bbw_contracting"] = True
        score += 10

    # 4. Volume fading
    sigs["volume_fading"] = False
    if vol_avg and vol_avg > 0 and volume > 0:
        vol_ratio = volume / vol_avg
        sigs["volume_ratio"] = round(vol_ratio, 2)
        if vol_ratio < 0.8:
            sigs["volume_fading"] = True
            score += 15

    # 5. SAR flipped bearish
    sigs["sar_bearish"] = sar_bull is not None and not sar_bull
    if sigs["sar_bearish"]:
        score += 25

    # 6. Price below SMA20
    sigs["below_sma20"] = False
    if price and sma20 and price < sma20:
        sigs["below_sma20"] = True
        score += 20

    return min(score, 100), sigs


def _assess_momentum(indicators: dict) -> str:
    """Assess overall momentum health from indicator readings."""
    rsi = indicators.get("rsi") or indicators.get("rsi14")
    rsi_slope = indicators.get("rsi_slope")
    volume = indicators.get("volume", 0)
    vol_avg = (indicators.get("vol_avg") or indicators.get("vol_ma")
               or indicators.get("avg_volume", 0))

    health_points = 0

    # RSI level
    if rsi is not None:
        if 45 <= rsi <= 70:
            health_points += 2
        elif 35 <= rsi <= 80:
            health_points += 1

    # RSI trend
    if rsi_slope is not None:
        if rsi_slope > 0.5:
            health_points += 2
        elif rsi_slope > -0.5:
            health_points += 1

    # Volume
    if vol_avg and vol_avg > 0 and volume > 0:
        ratio = volume / vol_avg
        if ratio > 1.5:
            health_points += 2
        elif ratio > 1.0:
            health_points += 1

    if health_points >= 5:
        return "STRONG"
    elif health_points >= 3:
        return "HEALTHY"
    elif health_points >= 1:
        return "FADING"
    return "WEAK"


def _urgency_label(score: int) -> str:
    if score <= EXIT_URGENCY_THRESHOLDS["HOLD"]:
        return "HOLD"
    if score <= EXIT_URGENCY_THRESHOLDS["MONITOR"]:
        return "MONITOR"
    if score <= EXIT_URGENCY_THRESHOLDS["TIGHTEN_STOP"]:
        return "TIGHTEN_STOP"
    return "CONSIDER_EXIT"


def _build_explanation(label: str, momentum: str, signals: dict) -> str:
    parts = []

    if label == "HOLD":
        _sig_names = {"rsi_overbought": "RSI is overbought", "rsi_declining": "RSI is declining",
                      "bbw_contracting": "BB width contracting", "volume_fading": "volume is fading",
                      "sar_bearish": "SAR turned bearish", "below_sma20": "price below SMA20"}
        active = [_sig_names[k] for k in _sig_names if signals.get(k)]
        if active:
            parts.append(f"Minor flag: {', '.join(active)} — but not enough to trigger an exit. Hold the position and trail your stop-loss as planned.")
        else:
            parts.append("No exit signals firing. Let the trade run and trail your stop-loss as planned.")
    elif label == "MONITOR":
        parts.append("Some early warning signs are appearing.")
        if signals.get("rsi_declining"):
            parts.append("RSI momentum is declining — the upward push is slowing.")
        if signals.get("volume_fading"):
            parts.append(f"Volume has dropped to {signals.get('volume_ratio', '?')}x average — fewer buyers participating.")
        parts.append("Consider tightening your stop-loss to protect profits.")
    elif label == "TIGHTEN_STOP":
        parts.append("Multiple warning signs are firing — structural damage detected.")
        if signals.get("rsi_overbought"):
            parts.append("RSI is above 75 (overbought) — the stock may be due for a pullback.")
        if signals.get("bbw_contracting"):
            parts.append("Bollinger Band width is contracting — the breakout energy is dying down.")
        if signals.get("below_sma20"):
            parts.append("Price has fallen below the 20-day moving average — the short-term trend is weakening.")
        parts.append("Move your stop-loss to breakeven or take partial profits.")
    else:
        parts.append("Multiple exit signals are firing simultaneously — the setup is breaking down.")
        if signals.get("sar_bearish"):
            parts.append("Parabolic SAR has flipped bearish — this is a classic exit signal.")
        if signals.get("rsi_overbought"):
            parts.append("RSI is overbought — a pullback is likely.")
        if signals.get("below_sma20"):
            parts.append("Price is below the 20-day MA — structure is broken.")
        parts.append("Consider taking profits on most or all of the position.")

    health_note = {
        "STRONG": "Overall momentum is STRONG — buyers are in control.",
        "HEALTHY": "Momentum is HEALTHY — the move still has energy.",
        "FADING": "Momentum is FADING — fewer buyers, less conviction.",
        "WEAK": "Momentum is WEAK — the move appears exhausted.",
    }
    parts.append(health_note.get(momentum, ""))

    return " ".join(parts)


def enrich_picks_with_exit(picks: list[dict]) -> None:
    """Add exit_intelligence dict to each pick."""
    for pick in picks:
        bb = pick.get("bb_data", {})
        indicators = bb.get("indicators", {})
        price = pick.get("price") or pick.get("current_price")
        method = pick.get("method", "M1")

        if not indicators:
            pick["exit_intelligence"] = {"available": False, "reason": "No indicator data"}
            continue

        urgency, signals = _score_exit_urgency(indicators, price)
        label = _urgency_label(urgency)
        momentum = _assess_momentum(indicators)
        explanation = _build_explanation(label, momentum, signals)

        pick["exit_intelligence"] = {
            "available": True,
            "urgency": urgency,
            "urgency_label": label,
            "momentum_health": momentum,
            "hold_estimate_days": _HOLD_ESTIMATES.get(method, "15-20"),
            "signals": signals,
            "recommended_action": label,
            "explanation": explanation,
        }


if __name__ == "__main__":
    fake = [{
        "ticker": "TEST.NS", "price": 500, "method": "M2",
        "bb_data": {"indicators": {
            "rsi": 62, "bbw": 0.09, "volume": 1_200_000,
            "vol_avg": 800_000, "sma20": 490, "sar_bull": True,
        }},
    }]
    enrich_picks_with_exit(fake)
    ei = fake[0]["exit_intelligence"]
    print(f"Urgency: {ei['urgency']} ({ei['urgency_label']})")
    print(f"Momentum: {ei['momentum_health']}")
    print(f"Action: {ei['recommended_action']}")
    print(f"Explanation: {ei['explanation'][:100]}...")
    assert ei["available"]
    assert ei["urgency_label"] in ("HOLD", "MONITOR", "TIGHTEN_STOP", "CONSIDER_EXIT")
    assert ei["momentum_health"] in ("STRONG", "HEALTHY", "FADING", "WEAK")
    print("OK")
