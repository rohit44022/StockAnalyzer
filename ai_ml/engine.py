"""
ai_ml/engine.py — Master AI/ML Orchestrator

Single entry point: enrich_top_picks(result_dict)

Takes the result dict from find_top_picks() and enriches it with:
  1. ML Signal Confidence (per pick)
  2. Correlation Risk Analysis (portfolio level)
  3. Position Sizing via Kelly/Vince (per pick)
  4. Method Routing Advice (portfolio level)
  5. Adaptive Threshold Context (per pick)

CONTRACT:
  - Existing fields are NEVER modified or removed
  - If any sub-module fails, remaining modules still run
  - If the entire AI/ML layer fails, result is returned unchanged
  - This function is safe to call on ANY result dict
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger("ai_ml.engine")


def enrich_top_picks(result: dict, capital: float = 500_000) -> dict:
    """
    Enrich a find_top_picks() result with AI/ML intelligence.

    Parameters
    ----------
    result : dict from find_top_picks() with 'picks' list
    capital : trading capital in ₹ for position sizing

    Returns
    -------
    Same dict with new 'ai_ml' key added at top level,
    and new fields added to each pick dict.
    """
    picks = result.get("picks", [])
    if not picks:
        result["ai_ml"] = {"available": False, "reason": "No picks to enrich"}
        return result

    t0 = time.time()
    ai_data = {"available": True, "modules": {}}

    # ── 1. ML Signal Filter ──────────────────────────────────────
    try:
        from ai_ml.signal_filter import score_picks
        score_picks(picks)
        ai_data["modules"]["signal_filter"] = {
            "status": "ok",
            "picks_scored": sum(1 for p in picks if p.get("ml_confidence") is not None),
        }
    except Exception as e:
        logger.warning("ML Signal Filter failed: %s", e)
        ai_data["modules"]["signal_filter"] = {"status": "error", "error": str(e)}

    # ── 2. Adaptive Thresholds ───────────────────────────────────
    try:
        from ai_ml.adaptive_thresholds import enrich_picks_with_adaptive
        enrich_picks_with_adaptive(picks)
        ai_data["modules"]["adaptive_thresholds"] = {"status": "ok"}
    except Exception as e:
        logger.warning("Adaptive Thresholds failed: %s", e)
        ai_data["modules"]["adaptive_thresholds"] = {"status": "error", "error": str(e)}

    # ── 3. Position Sizing ───────────────────────────────────────
    try:
        from ai_ml.position_sizer import compute_position_sizes
        compute_position_sizes(picks, capital=capital)
        ai_data["modules"]["position_sizer"] = {"status": "ok"}
    except Exception as e:
        logger.warning("Position Sizer failed: %s", e)
        ai_data["modules"]["position_sizer"] = {"status": "error", "error": str(e)}

    # ── 4. Correlation Guard (portfolio-level) ───────────────────
    try:
        from ai_ml.correlation_guard import enrich_picks_with_correlation
        corr = enrich_picks_with_correlation(picks)
        ai_data["correlation"] = corr
        ai_data["modules"]["correlation_guard"] = {"status": "ok"}
    except Exception as e:
        logger.warning("Correlation Guard failed: %s", e)
        ai_data["modules"]["correlation_guard"] = {"status": "error", "error": str(e)}

    # ── 5. Method Router (portfolio-level) ────────────────────────
    try:
        from ai_ml.method_router import get_method_recommendation
        # Use the first pick's indicators as a regime proxy
        first = picks[0] if picks else {}
        bb_ind = first.get("bb_data", {}).get("indicators", {})
        rsi_val = bb_ind.get("rsi") or bb_ind.get("rsi14")
        bbw_pct = None  # computed by adaptive thresholds
        adaptive = first.get("adaptive_context", {})
        if isinstance(adaptive, dict) and adaptive.get("bbw_percentile"):
            bbw_pct = adaptive["bbw_percentile"] / 100.0

        routing = get_method_recommendation(
            current_rsi=rsi_val,
            current_bbw_pct=bbw_pct,
        )
        ai_data["method_routing"] = routing
        ai_data["modules"]["method_router"] = {"status": "ok"}
    except Exception as e:
        logger.warning("Method Router failed: %s", e)
        ai_data["modules"]["method_router"] = {"status": "error", "error": str(e)}

    # ── 6. Market Regime Filter (portfolio-level) ────────────────
    try:
        from ai_ml.regime_filter import get_market_regime, enrich_picks_with_regime
        regime = get_market_regime()
        enrich_picks_with_regime(picks, regime)
        ai_data["market_regime"] = regime
        ai_data["modules"]["regime_filter"] = {"status": "ok"}
    except Exception as e:
        logger.warning("Regime Filter failed: %s", e)
        ai_data["modules"]["regime_filter"] = {"status": "error", "error": str(e)}

    # ── 7. Exit Intelligence ────────────────────────────────────
    try:
        from ai_ml.exit_intelligence import enrich_picks_with_exit
        enrich_picks_with_exit(picks)
        ai_data["modules"]["exit_intelligence"] = {"status": "ok"}
    except Exception as e:
        logger.warning("Exit Intelligence failed: %s", e)
        ai_data["modules"]["exit_intelligence"] = {"status": "error", "error": str(e)}

    # ── 8. Regime Clusters (unsupervised) ─────────────────────────
    try:
        from ai_ml.regime_cluster import enrich_picks_with_clusters
        enrich_picks_with_clusters(picks)
        ai_data["modules"]["regime_cluster"] = {"status": "ok"}
    except Exception as e:
        logger.warning("Regime Cluster failed: %s", e)
        ai_data["modules"]["regime_cluster"] = {"status": "error", "error": str(e)}

    # ── 9. Sequence Scorer (LSTM) ───────────────────────────────
    try:
        from ai_ml.sequence_scorer import score_picks_sequence
        score_picks_sequence(picks)
        ai_data["modules"]["sequence_scorer"] = {"status": "ok"}
    except Exception as e:
        logger.warning("Sequence Scorer failed: %s", e)
        ai_data["modules"]["sequence_scorer"] = {"status": "error", "error": str(e)}

    elapsed = time.time() - t0
    ai_data["elapsed_ms"] = round(elapsed * 1000)

    result["ai_ml"] = ai_data

    # ── Feedback: log picks for outcome tracking ────────────────
    try:
        from ai_ml.feedback_loop import log_picks
        log_picks(picks, method=result.get("method", ""))
    except Exception:
        pass

    return result


def is_available() -> bool:
    """Check if the AI/ML layer has trained models available."""
    import os
    from ai_ml.config import SIGNAL_FILTER_MODEL
    return os.path.exists(SIGNAL_FILTER_MODEL.replace(".xgb.json", ".joblib"))
