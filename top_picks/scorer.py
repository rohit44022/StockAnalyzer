"""
top_picks/scorer.py — Composite Scoring Logic for Top 5 Picks Engine
═════════════════════════════════════════════════════════════════════

WHAT THIS FILE DOES (plain English):
─────────────────────────────────────
This file takes ALL the analysis data for a single stock — the BB strategy
result, the Technical Analysis result, the Hybrid Engine result, plus data
quality info — and boils it ALL down to ONE number: the Composite Score (0-100).

Think of it as a judge at a competition. The judge watches every performance
(BB, TA, Hybrid, Risk, Agreement, Data Quality), scores each one separately,
then calculates a weighted average to determine the final ranking.

SCORING BREAKDOWN:
─────────────────
  Component 1 — BB Strategy Score (0-100):
    Directly from the Bollinger Band method's confidence.
    If BB says "BUY with 85% confidence", this component = 85.

  Component 2 — TA Score (0-100):
    Murphy's Technical Analysis returns -100 to +100.
    We normalize: (ta_raw + 100) / 2 = 0 to 100.
    So TA score of +60 → (60+100)/2 = 80 out of 100.

  Component 3 — Hybrid Score (0-100):
    The Hybrid Engine returns -245 to +245.
    We normalize: (hybrid_raw + 245) / 490 × 100 = 0 to 100.
    So hybrid score of +120 → (120+245)/490 × 100 = 74.5 out of 100.

  Component 4 — Risk/Reward Score (0-100):
    Based on the target price vs stop-loss ratio.
    R:R of 3.0 → 90 (excellent). R:R of 1.0 → 35 (barely break-even).

  Component 5 — Signal Agreement (0-100):
    How many analysis engines agree on the direction (BUY/SELL)?
    All 3 agree → 100. Two agree → 65. Conflicting → 20.

  Component 6 — Data Quality (0-100):
    Based on how fresh the stock data is.
    Today's data → 100. Week-old data → 60. Very old → 10.
"""

from __future__ import annotations
import math
from typing import Optional

from top_picks.config import (
    WEIGHTS, RR_SCORE_MAP, FRESHNESS_SCORE_MAP, HYBRID_MAX_SCORE, HYBRID_MIN_SCORE, PA_MAX_SCORE,
)


# ═══════════════════════════════════════════════════════════════
# MAIN SCORING FUNCTION
# ═══════════════════════════════════════════════════════════════

def compute_composite_score(
    bb_confidence: float,
    bb_signal_type: str,
    ta_signal: dict,
    hybrid_result: dict,
    data_freshness: dict,
    method: str,
    signal_filter: str = "BUY",
    pa_result: Optional[dict] = None,
) -> dict:
    """
    Combine all analysis layers into a single Composite Score (0-100).

    ┌─────────────────────────────────────────────────────────────┐
    │  INPUTS:                                                     │
    │                                                              │
    │  bb_confidence  — The BB strategy's confidence (0-100).      │
    │                   Example: 75 means "75% match to pattern"   │
    │                                                              │
    │  bb_signal_type — "BUY", "SELL", "HOLD", "WAIT", etc.       │
    │                                                              │
    │  ta_signal      — The full TA result dict with:              │
    │                   "score" (-100 to +100), "verdict",         │
    │                   "categories" (trend, momentum, etc.)       │
    │                                                              │
    │  hybrid_result  — The full hybrid engine output dict.        │
    │                   Contains "hybrid_verdict", "bb_score",     │
    │                   "ta_score", "cross_validation", "risk",    │
    │                   "target_prices"                            │
    │                                                              │
    │  data_freshness — Dict with "trading_days_stale" etc.        │
    │                                                              │
    │  method         — Which BB method: "M1", "M2", "M3", "M4"   │
    │                                                              │
    │  signal_filter  — "BUY" or "SELL". Controls how scores are   │
    │                   interpreted:                               │
    │                   BUY  → bullish TA/hybrid = good            │
    │                   SELL → bearish TA/hybrid = good            │
    │                                                              │
    │  OUTPUT:                                                     │
    │  A dict with:                                                │
    │    composite_score  — The final 0-100 score                  │
    │    grade            — "A+", "A", "B+", "B", "C", "D", "F"  │
    │    components       — Individual scores for each layer       │
    │    reasons          — Human-readable explanations            │
    │    warnings         — Any red flags to be aware of           │
    └─────────────────────────────────────────────────────────────┘
    """

    reasons = []       # Why this stock scored well (or poorly)
    warnings = []      # Red flags the trader should know about
    is_sell = signal_filter == "SELL"

    # ── Component 1: BB Strategy Score ──────────────────────────
    bb_score = _score_bb_strategy(bb_confidence, bb_signal_type, method)
    if bb_score >= 80:
        reasons.append(f"Strong {method} pattern match ({bb_confidence}% confidence)")
    elif bb_score >= 50:
        reasons.append(f"Moderate {method} pattern match ({bb_confidence}% confidence)")

    # ── Component 2: TA Score ───────────────────────────────────
    # For BUY picks: bullish TA (high score) = good.
    # For SELL picks: bearish TA (low/negative score) = good.
    # We flip the scale for SELL so that TA score -60 → 80/100.
    ta_score_component = _score_technical_analysis(ta_signal, is_sell)
    ta_verdict = ta_signal.get("verdict", "HOLD")
    ta_raw = ta_signal.get("score", 0)
    if is_sell:
        if ta_raw < -30:
            reasons.append(f"Technical Analysis confirms BEARISH ({ta_verdict}, score {ta_raw:+.0f})")
        elif ta_raw > 30:
            warnings.append(f"Technical Analysis is BULLISH ({ta_verdict}, score {ta_raw:+.0f}) — conflicts with SELL")
    else:
        if ta_raw > 30:
            reasons.append(f"Technical Analysis is BULLISH ({ta_verdict}, score {ta_raw:+.0f})")
        elif ta_raw < -30:
            warnings.append(f"Technical Analysis is BEARISH ({ta_verdict}, score {ta_raw:+.0f})")

    # ── Component 3: Hybrid Score ───────────────────────────────
    # Same direction-aware logic: for SELL, negative hybrid = good.
    hybrid_score_component = _score_hybrid(hybrid_result, is_sell)
    hybrid_verdict_text = _extract_hybrid_verdict(hybrid_result)
    hybrid_combined = _extract_hybrid_combined_score(hybrid_result)
    if is_sell:
        if hybrid_combined < -25:
            reasons.append(f"Hybrid Engine confirms BEARISH ({hybrid_verdict_text})")
        elif hybrid_combined > 50:
            warnings.append(f"Hybrid Engine is BULLISH ({hybrid_verdict_text}) — conflicts with SELL")
    else:
        if hybrid_combined > 50:
            reasons.append(f"Hybrid Engine strongly BULLISH ({hybrid_verdict_text})")
        elif hybrid_combined < -25:
            warnings.append(f"Hybrid Engine is BEARISH ({hybrid_verdict_text})")

    # ── Component 4: Risk/Reward Score ──────────────────────────
    rr_score, rr_ratio = _score_risk_reward(hybrid_result)
    if rr_ratio and rr_ratio >= 2.5:
        reasons.append(f"Excellent risk/reward ratio of 1:{rr_ratio:.1f}")
    elif rr_ratio and rr_ratio < 1.0:
        warnings.append(f"Poor risk/reward ratio of 1:{rr_ratio:.1f} — potential loss exceeds gain")

    # ── Component 5: Signal Agreement ───────────────────────────
    agreement_score = _score_signal_agreement(
        bb_signal_type, ta_verdict, hybrid_verdict_text
    )
    if agreement_score >= 80:
        reasons.append("All analysis engines agree on direction — high conviction")
    elif agreement_score <= 30:
        warnings.append("Analysis engines DISAGREE on direction — mixed signals")

    # ── Component 6½: Price Action (Al Brooks) ──────────────────
    pa_score_component = _score_price_action(pa_result, is_sell)
    pa_verdict_text = ""
    pa_setup_text = ""
    pa_conf_val = 0
    if pa_result and pa_result.get("success"):
        pa_verdict_text = pa_result.get("pa_verdict", "HOLD")
        pa_setup_text = pa_result.get("setup_type", "")
        pa_conf_val = pa_result.get("confidence", 0)
        pa_raw = pa_result.get("pa_score", 0)
        if is_sell:
            if pa_raw < -20:
                reasons.append(f"Price Action confirms BEARISH ({pa_verdict_text}, setup: {pa_setup_text})")
            elif pa_raw > 20:
                warnings.append(f"Price Action is BULLISH ({pa_verdict_text}) — conflicts with SELL")
        else:
            if pa_raw > 20:
                reasons.append(f"Price Action confirms BULLISH ({pa_verdict_text}, setup: {pa_setup_text})")
            elif pa_raw < -20:
                warnings.append(f"Price Action is BEARISH ({pa_verdict_text}) — conflicts with BUY")

    # ── Component 7: Data Quality ───────────────────────────────
    dq_score = _score_data_quality(data_freshness)
    trading_days_stale = data_freshness.get("trading_days_stale", 999)
    if trading_days_stale > 5:
        warnings.append(f"Data is {trading_days_stale} trading days old — signals may be UNRELIABLE")
    elif trading_days_stale > 2:
        warnings.append(f"Data is {trading_days_stale} trading days old — consider refreshing")

    # ── Combine Weighted Components ─────────────────────────────
    composite = (
        bb_score            * WEIGHTS["bb_strategy"]
        + ta_score_component * WEIGHTS["ta_score"]
        + hybrid_score_component * WEIGHTS["hybrid_score"]
        + pa_score_component * WEIGHTS["pa_score"]
        + rr_score           * WEIGHTS["risk_reward"]
        + agreement_score    * WEIGHTS["signal_agreement"]
        + dq_score           * WEIGHTS["data_quality"]
    )

    # Clamp to 0-100
    composite = max(0.0, min(100.0, composite))

    # ── Assign Grade ────────────────────────────────────────────
    grade = _assign_grade(composite)

    return {
        "composite_score": round(composite, 1),
        "grade": grade,
        "components": {
            "bb_strategy": {
                "score": round(bb_score, 1),
                "weight": WEIGHTS["bb_strategy"],
                "weighted": round(bb_score * WEIGHTS["bb_strategy"], 1),
                "detail": f"{method} confidence {bb_confidence}%, signal: {bb_signal_type}",
                "hint": "How strongly this stock matches the Bollinger Band pattern you scanned for",
            },
            "ta_score": {
                "score": round(ta_score_component, 1),
                "weight": WEIGHTS["ta_score"],
                "weighted": round(ta_score_component * WEIGHTS["ta_score"], 1),
                "detail": f"TA verdict: {ta_verdict}, raw score: {ta_raw:+.0f}/100",
                "hint": "Murphy's 6-category technical analysis (trend, momentum, volume, patterns, S/R, risk)",
            },
            "hybrid_score": {
                "score": round(hybrid_score_component, 1),
                "weight": WEIGHTS["hybrid_score"],
                "weighted": round(hybrid_score_component * WEIGHTS["hybrid_score"], 1),
                "detail": f"Hybrid verdict: {hybrid_verdict_text}, combined {hybrid_combined:+.0f}/245",
                "hint": "Cross-validation — do BB and TA agree? Higher when both point the same direction",
            },
            "risk_reward": {
                "score": round(rr_score, 1),
                "weight": WEIGHTS["risk_reward"],
                "weighted": round(rr_score * WEIGHTS["risk_reward"], 1),
                "detail": f"R:R ratio: 1:{rr_ratio:.1f}" if rr_ratio else "R:R not available",
                "hint": "For every ₹1 risked, how much could you gain? Above 1:2 is professional standard",
            },
            "pa_score": {
                "score": round(pa_score_component, 1),
                "weight": WEIGHTS["pa_score"],
                "weighted": round(pa_score_component * WEIGHTS["pa_score"], 1),
                "detail": f"PA verdict: {pa_verdict_text or 'N/A'}, setup: {pa_setup_text or 'N/A'}, conf: {pa_conf_val}%",
                "hint": "Al Brooks bar-by-bar analysis — trend direction, signal bars, patterns, breakouts",
            },
            "signal_agreement": {
                "score": round(agreement_score, 1),
                "weight": WEIGHTS["signal_agreement"],
                "weighted": round(agreement_score * WEIGHTS["signal_agreement"], 1),
                "detail": _describe_agreement(bb_signal_type, ta_verdict, hybrid_verdict_text),
                "hint": "Do all 3 engines (BB, TA, Hybrid) agree? 100 = perfect agreement",
            },
            "data_quality": {
                "score": round(dq_score, 1),
                "weight": WEIGHTS["data_quality"],
                "weighted": round(dq_score * WEIGHTS["data_quality"], 1),
                "detail": f"Data {trading_days_stale} trading day(s) old",
                "hint": "How fresh is the stock data? Stale data = less reliable signals",
            },
        },
        "reasons": reasons,
        "warnings": warnings,
    }


# ═══════════════════════════════════════════════════════════════
# COMPONENT SCORERS (each returns 0-100)
# ═══════════════════════════════════════════════════════════════

def _score_bb_strategy(confidence: float, signal_type: str, method: str) -> float:
    """
    Score the BB strategy's strength (0-100).

    LOGIC:
    - Start with the raw confidence (0-100) from the BB method.
    - Apply a small bonus if the signal is a clear BUY (not just HOLD/WAIT).
    - Apply a penalty if the signal is neutral or conflicting.

    EXAMPLE:
      confidence=75, signal_type="BUY"  → 75 + 5 = 80
      confidence=75, signal_type="HOLD" → 75 × 0.6 = 45  (holding ≠ strong pick)
    """
    score = float(confidence)

    if signal_type == "BUY":
        # Clear BUY signal — small bonus for conviction (reduced from +10 to +5
        # so stocks with 90-100% confidence remain distinguishable)
        score = min(100, score + 5)
    elif signal_type == "SELL":
        # We invert for SELL scans (high confidence SELL = good SELL pick)
        score = min(100, score + 5)
    elif signal_type in ("HOLD", "WAIT"):
        # HOLD/WAIT means the pattern exists but isn't compelling
        score = score * 0.6
    else:
        # NONE or unknown — heavy penalty
        score = score * 0.3

    return max(0.0, min(100.0, score))


def _score_technical_analysis(ta_signal: dict, is_sell: bool = False) -> float:
    """
    Normalize TA score from (-100 to +100) → (0 to 100).

    LOGIC (plain English):
      FOR BUY PICKS:
        -100 → 0   (terrible)  |  0 → 50  (neutral)  |  +100 → 100 (great)
        Formula: (raw + 100) / 2

      FOR SELL PICKS (flipped — bearish = good):
        -100 → 100 (great — very bearish, confirms SELL)
        0 → 50     (neutral)
        +100 → 0   (terrible — bullish contradicts SELL)
        Formula: (100 - raw) / 2
    """
    raw = ta_signal.get("score", 0)
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        raw = 0
    if is_sell:
        normalized = (100 - raw) / 2.0
    else:
        normalized = (raw + 100) / 2.0
    return max(0.0, min(100.0, normalized))


def _score_hybrid(hybrid_result: dict, is_sell: bool = False) -> float:
    """
    Normalize Hybrid Engine score from (-230 to +245) → (0 to 100).

    Uses asymmetric range: max = +245, min = -230.
    FOR BUY:  normalized = (combined - min) / (max - min) × 100
    FOR SELL: normalized = (max - combined) / (max - min) × 100  (flipped)

    EXAMPLES (BUY):
      Combined score +120  →  (120 + 230) / (245 + 230) × 100 = 73.7
      Combined score -50   →  (-50 + 230) / 475 × 100 = 37.9
      Combined score +200  →  (200 + 230) / 475 × 100 = 90.5
    """
    combined = _extract_hybrid_combined_score(hybrid_result)
    max_s = HYBRID_MAX_SCORE   # +245
    min_s = HYBRID_MIN_SCORE   # -230
    total_range = max_s - min_s  # 475
    if is_sell:
        normalized = (max_s - combined) / total_range * 100.0
    else:
        normalized = (combined - min_s) / total_range * 100.0
    return max(0.0, min(100.0, normalized))


def _score_risk_reward(hybrid_result: dict) -> tuple[float, Optional[float]]:
    """
    Score the risk/reward ratio (0-100).

    WHAT IS RISK:REWARD? (for non-traders):
      If you buy a stock at ₹100, your stop-loss is at ₹90 (risk = ₹10),
      and your target is ₹130 (reward = ₹30).
      R:R ratio = 30/10 = 3.0 (you could gain 3× what you risk).
      Professional traders require at LEAST 1:2 (gain 2× risk).

    SCORING TABLE:
      R:R >= 4.0  → 100   "Excellent — 4× upside vs downside"
      R:R >= 3.0  →  90   "Very good"
      R:R >= 2.0  →  70   "Professional standard"
      R:R >= 1.0  →  35   "Break-even territory"
      R:R <  1.0  →  15   "Danger — more to lose than gain"
    """
    # Extract risk:reward from target_prices section
    tp = hybrid_result.get("target_prices", {})
    rr = tp.get("risk_reward_ratio")

    if rr is None:
        # Try fallback from risk section
        risk = hybrid_result.get("risk", {})
        rr_data = risk.get("risk_reward") if isinstance(risk, dict) else None
        if isinstance(rr_data, dict):
            rr = rr_data.get("ratio")

    if rr is None or (isinstance(rr, float) and (math.isnan(rr) or math.isinf(rr))):
        return 40.0, None  # Default middle score when R:R not available

    rr = float(rr)
    rr = max(0.0, rr)

    # Find the matching threshold
    for threshold, score in RR_SCORE_MAP:
        if rr >= threshold:
            return float(score), rr

    return 15.0, rr


def _score_signal_agreement(
    bb_signal: str, ta_verdict: str, hybrid_verdict: str
) -> float:
    """
    Score how well all three engines agree (0-100).

    LOGIC (plain English):
      We check what direction each engine is pointing:
        - BB signal: BUY → BULLISH, SELL → BEARISH, else NEUTRAL
        - TA verdict: STRONG BUY/BUY → BULLISH, STRONG SELL/SELL → BEARISH
        - Hybrid: SUPER STRONG BUY/STRONG BUY/BUY → BULLISH, etc.

      Then count agreements:
        All 3 same direction  → 100 (high conviction — everyone agrees)
        2 out of 3 agree      →  65 (good — majority agrees)
        All different          →  40 (neutral — no consensus)
        Direct conflict        →  20 (danger — engines contradict)
        (e.g. BB says BUY but TA says SELL)

    WHY THIS MATTERS:
      A stock where ALL signals agree (BB pattern + TA momentum + Hybrid cross-check)
      is much safer than one where the signals conflict.
    """
    bb_dir = _to_direction(bb_signal)
    ta_dir = _to_direction(ta_verdict)
    hybrid_dir = _to_direction(hybrid_verdict)

    directions = [bb_dir, ta_dir, hybrid_dir]
    bullish_count = directions.count("BULLISH")
    bearish_count = directions.count("BEARISH")
    neutral_count = directions.count("NEUTRAL")

    # Perfect alignment (all 3 agree on direction)
    if bullish_count == 3 or bearish_count == 3:
        return 100.0

    # Strong alignment (2 agree, 1 neutral)
    if (bullish_count == 2 and neutral_count == 1) or \
       (bearish_count == 2 and neutral_count == 1):
        return 75.0

    # Majority (2 agree but 1 disagrees)
    if bullish_count == 2 or bearish_count == 2:
        return 65.0

    # All neutral
    if neutral_count == 3:
        return 50.0

    # Direct conflict (some bullish, some bearish)
    if bullish_count >= 1 and bearish_count >= 1:
        return 20.0

    # Everything else (mixed neutral + one direction)
    return 40.0


def _score_data_quality(freshness: dict) -> float:
    """
    Score data freshness (0-100).

    WHY THIS MATTERS:
      Technical signals are based on RECENT price action. If the data is
      5 days old, the patterns may have already resolved. Stale signals
      are like yesterday's weather forecast — not useful for today.

    SCORING:
      0-1 trading days old  → 100 (fresh — signals are reliable)
      2 days old            →  85
      3-5 days old          →  60 (consider refreshing)
      6-10 days old         →  30 (signals UNRELIABLE)
      10+ days old          →  10 (essentially useless)
    """
    stale_days = freshness.get("trading_days_stale", 999)
    if stale_days is None:
        stale_days = 999

    for threshold, score in FRESHNESS_SCORE_MAP:
        if stale_days <= threshold:
            return float(score)

    return 10.0


def _score_price_action(pa_result: Optional[dict], is_sell: bool = False) -> float:
    """
    Score the Price Action (Al Brooks) analysis (0-100).

    PA score ranges from -100 (strongly bearish) to +100 (strongly bullish).
    Confidence ranges from 0 to 100.

    FOR BUY: high PA score + high confidence = good
    FOR SELL: low (negative) PA score + high confidence = good (flipped)
    """
    if not pa_result or not pa_result.get("success"):
        return 40.0  # Neutral default when PA data unavailable

    pa_raw = pa_result.get("pa_score", 0)  # -100 to +100
    confidence = pa_result.get("confidence", 0)  # 0 to 100

    # Normalize PA score to 0-100
    if is_sell:
        # For SELL: negative PA score is good
        normalized = (PA_MAX_SCORE - pa_raw) / (2 * PA_MAX_SCORE) * 100.0
    else:
        # For BUY: positive PA score is good
        normalized = (pa_raw + PA_MAX_SCORE) / (2 * PA_MAX_SCORE) * 100.0

    # Blend with confidence (70% normalized score, 30% confidence)
    blended = normalized * 0.7 + confidence * 0.3

    return max(0.0, min(100.0, blended))


# ═══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def _to_direction(signal: str) -> str:
    """
    Convert any signal/verdict string into a simple direction.

    MAPPING:
      BUY/STRONG BUY/SUPER STRONG BUY → "BULLISH"
      SELL/STRONG SELL/SUPER STRONG SELL → "BEARISH"
      Everything else (HOLD, WAIT, NEUTRAL, etc.) → "NEUTRAL"
    """
    if not signal:
        return "NEUTRAL"
    s = signal.upper().strip()
    if "BUY" in s:
        return "BULLISH"
    if "SELL" in s:
        return "BEARISH"
    return "NEUTRAL"


def _extract_hybrid_verdict(hybrid_result: dict) -> str:
    """Extract the human-readable verdict string from the hybrid result."""
    hv = hybrid_result.get("hybrid_verdict", {})
    if isinstance(hv, dict):
        return hv.get("verdict", "UNKNOWN")
    return str(hv) if hv else "UNKNOWN"


def _extract_hybrid_combined_score(hybrid_result: dict) -> float:
    """
    Extract the combined numerical score from the hybrid result.
    This is BB_total + TA_total + agreement_bonus (range: -245 to +245).
    """
    hv = hybrid_result.get("hybrid_verdict", {})
    if isinstance(hv, dict):
        score = hv.get("score", 0)
        if score is not None and not (isinstance(score, float) and math.isnan(score)):
            return float(score)

    # Fallback: reconstruct from bb_score + ta_score + cross_validation
    bb = hybrid_result.get("bb_score", {})
    ta = hybrid_result.get("ta_score", {})
    cv = hybrid_result.get("cross_validation", {})
    bb_total = bb.get("total", 0) if isinstance(bb, dict) else 0
    ta_total = ta.get("total", 0) if isinstance(ta, dict) else 0
    cv_score = cv.get("agreement_score", 0) if isinstance(cv, dict) else 0
    return float(bb_total) + float(ta_total) + float(cv_score)


def _describe_agreement(bb_signal: str, ta_verdict: str, hybrid_verdict: str) -> str:
    """Build a human-readable description of signal agreement."""
    bb_dir = _to_direction(bb_signal)
    ta_dir = _to_direction(ta_verdict)
    hy_dir = _to_direction(hybrid_verdict)

    parts = [
        f"BB → {bb_dir}",
        f"TA → {ta_dir}",
        f"Hybrid → {hy_dir}",
    ]
    return " | ".join(parts)


def _assign_grade(score: float) -> str:
    """
    Assign a letter grade based on composite score.

    GRADING SCALE (think school grades):
      90-100  → A+  (exceptional pick — extremely rare)
      80-89   → A   (excellent pick — high confidence)
      70-79   → B+  (good pick — solid case)
      60-69   → B   (decent pick — worth considering)
      50-59   → C   (mediocre — mixed signals)
      40-49   → D   (weak — proceed with extreme caution)
      0-39    → F   (failing — do not recommend)
    """
    if score >= 90:
        return "A+"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B+"
    if score >= 60:
        return "B"
    if score >= 50:
        return "C"
    if score >= 40:
        return "D"
    return "F"
