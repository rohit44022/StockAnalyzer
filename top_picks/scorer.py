"""
top_picks/scorer.py — 5-Component Composite Scoring
════════════════════════════════════════════════════

Components (weights in config.WEIGHTS):
  1. BB Strategy   (30%) — BB method confidence
  2. TA Score      (20%) — Murphy's 6-category TA
  3. Triple Score  (15%) — BB+TA+PA cross-validation
  4. Brooks PA     (20%) — Brooks PA engine v3
  5. Fundamental   (15%) — Company quality (valuation+profitability+growth+stability)
"""

from __future__ import annotations
import math
from typing import Optional

from top_picks.config import (
    WEIGHTS, TRIPLE_MAX_SCORE, TRIPLE_MIN_SCORE, PA_MAX_SCORE,
)


# ═══════════════════════════════════════════════════════════════
# MAIN SCORING FUNCTION
# ═══════════════════════════════════════════════════════════════

def compute_composite_score(
    bb_confidence: float,
    bb_signal_type: str,
    ta_signal: dict,
    hybrid_result: dict,
    method: str,
    signal_filter: str = "BUY",
    brooks_result: Optional[dict] = None,
    fundamental_score: Optional[float] = None,
    # legacy kwargs kept so callers don't break during transition
    **_kwargs,
) -> dict:
    """
    Combine 5 analysis layers into a single Composite Score (0-100).

    Returns dict with composite_score, grade, components breakdown,
    reasons list, and warnings list.
    """
    is_sell = signal_filter == "SELL"
    reasons = []
    warnings = []

    # ── 1: BB Strategy ──
    bb_raw = _score_bb_strategy(bb_confidence, bb_signal_type, method)
    if bb_raw >= 80:
        reasons.append(f"Strong {method} pattern match ({bb_confidence:.0f}% confidence)")
    elif bb_raw >= 50:
        reasons.append(f"Moderate {method} pattern ({bb_confidence:.0f}% confidence)")

    # ── 2: TA Score ──
    ta_raw_signal = ta_signal.get("score", 0) or 0
    ta_norm = _score_ta(ta_signal, is_sell)
    if not is_sell and ta_raw_signal < -30:
        warnings.append(f"Technical BEARISH ({ta_raw_signal:+.0f}) conflicts with BUY")
    elif not is_sell and ta_raw_signal > 30:
        reasons.append(f"Technical BULLISH ({ta_raw_signal:+.0f}) confirms BUY")

    # ── 3: Triple Score ──
    triple_combined = _extract_triple_combined_score(hybrid_result)
    triple_norm = _score_triple(hybrid_result, is_sell)
    if not is_sell and triple_combined < -25:
        warnings.append(f"Triple BEARISH ({triple_combined:+.0f}) conflicts with BUY")
    elif not is_sell and triple_combined > 50:
        reasons.append(f"Triple BULLISH ({triple_combined:+.0f}) confirms BUY")

    # ── 4: Brooks PA ──
    brooks_norm = _score_brooks_pa(brooks_result, is_sell)
    if brooks_result:
        bpa_type = brooks_result.get("signal_type", "HOLD")
        bpa_conf = brooks_result.get("confidence", 0)
        if not is_sell and bpa_type == "BUY" and bpa_conf >= 50:
            reasons.append(f"Brooks PA: {bpa_type} ({bpa_conf}% confidence)")
        elif not is_sell and bpa_type == "SELL":
            warnings.append(f"Brooks PA: SELL conflicts with BUY")

    # ── 5: Fundamental ──
    fund_norm = _score_fundamental(fundamental_score)
    if fundamental_score is not None:
        if fundamental_score >= 70:
            reasons.append(f"Strong fundamentals ({fundamental_score:.0f}/100)")
        elif fundamental_score < 35:
            warnings.append(f"Weak fundamentals ({fundamental_score:.0f}/100)")

    # ── Weighted composite ──
    w_bb = WEIGHTS["bb_strategy"]
    w_ta = WEIGHTS["ta_score"]
    w_tr = WEIGHTS["triple_score"]
    w_bp = WEIGHTS["brooks_pa"]
    w_fn = WEIGHTS["fundamental"]

    composite = max(0.0, min(100.0,
        bb_raw * w_bb +
        ta_norm * w_ta +
        triple_norm * w_tr +
        brooks_norm * w_bp +
        fund_norm * w_fn
    ))

    # ── Components breakdown ──
    components = {
        "bb_strategy": {
            "score": round(bb_raw, 1),
            "weight": w_bb,
            "weighted": round(bb_raw * w_bb, 1),
            "hint": f"{method} pattern confidence: {bb_confidence:.0f}%",
            "detail": f"BB confidence {bb_confidence:.0f}%, signal: {bb_signal_type}",
        },
        "ta_score": {
            "score": round(ta_norm, 1),
            "weight": w_ta,
            "weighted": round(ta_norm * w_ta, 1),
            "hint": f"TA {ta_raw_signal:+.0f}/100",
            "detail": "Murphy's 6-category technical analysis",
        },
        "triple_score": {
            "score": round(triple_norm, 1),
            "weight": w_tr,
            "weighted": round(triple_norm * w_tr, 1),
            "hint": f"Triple {triple_combined:+.0f}/425",
            "detail": "Cross-validation of BB, TA, and PA engines",
        },
        "brooks_pa": {
            "score": round(brooks_norm, 1),
            "weight": w_bp,
            "weighted": round(brooks_norm * w_bp, 1),
            "hint": _brooks_hint(brooks_result),
            "detail": "Al Brooks Price Action v3 — bar-by-bar analysis",
        },
        "fundamental": {
            "score": round(fund_norm, 1),
            "weight": w_fn,
            "weighted": round(fund_norm * w_fn, 1),
            "hint": f"Fundamental {fundamental_score:.0f}/100" if fundamental_score is not None else "No data",
            "detail": "Valuation + Profitability + Growth + Stability",
        },
    }

    return {
        "composite_score": round(composite, 1),
        "grade": _grade(composite),
        "components": components,
        "reasons": reasons,
        "warnings": warnings,
    }


# ═══════════════════════════════════════════════════════════════
# COMPONENT SCORERS (each returns 0-100)
# ═══════════════════════════════════════════════════════════════

def _score_bb_strategy(confidence: float, signal_type: str, method: str) -> float:
    score = float(confidence)
    if signal_type in ("BUY", "SELL"):
        score = min(100, score + 5)
    elif signal_type in ("HOLD", "WAIT"):
        score = score * 0.6
    else:
        score = score * 0.3
    return max(0.0, min(100.0, score))


def _score_ta(ta_signal: dict, is_sell: bool = False) -> float:
    raw = ta_signal.get("score", 0)
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        raw = 0
    if is_sell:
        return max(0.0, min(100.0, (100 - raw) / 2.0))
    return max(0.0, min(100.0, (raw + 100) / 2.0))


def _score_triple(hybrid_result: dict, is_sell: bool = False) -> float:
    combined = _extract_triple_combined_score(hybrid_result)
    total_range = TRIPLE_MAX_SCORE - TRIPLE_MIN_SCORE
    if is_sell:
        normalized = (TRIPLE_MAX_SCORE - combined) / total_range * 100.0
    else:
        normalized = (combined - TRIPLE_MIN_SCORE) / total_range * 100.0
    return max(0.0, min(100.0, normalized))


def _score_brooks_pa(brooks_result: Optional[dict], is_sell: bool = False) -> float:
    """Score Brooks PA engine output (0-100)."""
    if not brooks_result or not brooks_result.get("success", False):
        return 40.0  # neutral default when no data

    pa_score = brooks_result.get("pa_score", 0) or 0  # -100 to +100
    confidence = brooks_result.get("confidence", 0) or 0  # 0-100
    quality = brooks_result.get("quality_score", 0) or 0  # 0-100
    signal = brooks_result.get("signal_type", "HOLD")

    # Normalise pa_score to 0-100 (direction-aware)
    if is_sell:
        score_norm = (PA_MAX_SCORE - pa_score) / (2 * PA_MAX_SCORE) * 100.0
    else:
        score_norm = (pa_score + PA_MAX_SCORE) / (2 * PA_MAX_SCORE) * 100.0

    # Blend: 50% score_norm + 30% confidence + 20% quality
    blended = 0.50 * score_norm + 0.30 * confidence + 0.20 * quality

    # Bonus if signal aligns with filter direction
    if (not is_sell and signal == "BUY") or (is_sell and signal == "SELL"):
        blended = min(100, blended + 5)

    return max(0.0, min(100.0, blended))


def _score_fundamental(fundamental_score: Optional[float]) -> float:
    """Score company fundamentals (0-100). Already 0-100 from fundamentals.py."""
    if fundamental_score is None:
        return 40.0  # neutral default when no data
    if isinstance(fundamental_score, float) and math.isnan(fundamental_score):
        return 40.0
    return max(0.0, min(100.0, float(fundamental_score)))


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def _extract_triple_combined_score(hybrid_result: dict) -> float:
    tv = hybrid_result.get("triple_verdict", {})
    if isinstance(tv, dict):
        score = tv.get("score", 0)
        if score is not None and not (isinstance(score, float) and math.isnan(score)):
            return float(score)
    bb = hybrid_result.get("bb_score", {})
    ta = hybrid_result.get("ta_score", {})
    pa = hybrid_result.get("pa_score", {})
    cv = hybrid_result.get("cross_validation", {})
    return (
        float((bb.get("total", 0) if isinstance(bb, dict) else 0))
        + float((ta.get("total", 0) if isinstance(ta, dict) else 0))
        + float((pa.get("total", 0) if isinstance(pa, dict) else 0))
        + float((cv.get("agreement_score", 0) if isinstance(cv, dict) else 0))
    )


def _brooks_hint(brooks_result: Optional[dict]) -> str:
    if not brooks_result:
        return "No Brooks data"
    sig = brooks_result.get("signal_type", "HOLD")
    conf = brooks_result.get("confidence", 0)
    setup = brooks_result.get("setup_type", "")
    parts = [f"{sig} ({conf}%)"]
    if setup and setup != "NONE":
        parts.append(setup)
    return " — ".join(parts)


def _grade(score: float) -> str:
    if score >= 90: return "A+"
    if score >= 80: return "A"
    if score >= 70: return "B+"
    if score >= 60: return "B"
    if score >= 50: return "C"
    if score >= 40: return "D"
    return "F"
