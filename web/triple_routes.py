"""
triple_routes.py — Flask Blueprint for BB + TA + PA Triple Conviction Engine.

Routes: /triple, /api/triple/analyze
Blueprint name: 'triple'
"""

import sys, os, json, math, time, logging
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flask import Blueprint, render_template, jsonify, request

from bb_squeeze.data_loader import normalise_ticker, load_stock_data, get_all_tickers_from_csv
from bb_squeeze.config import CSV_DIR
from hybrid_pa_engine import run_triple_analysis

logger = logging.getLogger("triple_routes")

triple_bp = Blueprint("triple", __name__, template_folder="templates")


def _safe_json(obj):
    """Make every value JSON-safe (no NaN/Inf, convert numpy types)."""
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


@triple_bp.route("/triple")
def triple_dashboard():
    """Serve the Triple Conviction Engine dashboard."""
    tickers = sorted(get_all_tickers_from_csv(CSV_DIR))
    return render_template("triple_dashboard.html", tickers=tickers)


@triple_bp.route("/api/triple/analyze")
def triple_analyze():
    """Perform full BB + TA + PA triple analysis for a given ticker."""
    raw = request.args.get("ticker", "").strip()
    if not raw:
        return jsonify({"error": "ticker parameter required"}), 400

    ticker = normalise_ticker(raw)
    df = load_stock_data(ticker, CSV_DIR)
    if df is None or df.empty:
        return jsonify({"error": f"No data found for {ticker}"}), 404

    capital = float(request.args.get("capital", 500000))
    try:
        result = run_triple_analysis(df, ticker=ticker, capital=capital)
    except Exception as e:
        return jsonify({"error": f"Analysis failed for {ticker}: {str(e)}"}), 500

    if "error" in result:
        return jsonify(result), 400

    result["ticker"] = ticker

    # ── AI/ML enrichment (additive, never modifies triple data) ──
    try:
        _enrich_triple_with_aiml(result, ticker, capital)
    except Exception as e:
        logger.warning("AI/ML enrichment failed: %s", e)

    safe = _safe_json(result)
    return jsonify(safe)


# ── AI/ML Integration ──────────────────────────────────────────


def _best_bb_method(result):
    """Return method name (M1/M2/M3/M4) with highest absolute score."""
    methods = result.get("bb_score", {}).get("methods", [])
    if not methods:
        return "M1"
    best_idx = max(range(len(methods)),
                   key=lambda i: abs(methods[i].get("score", 0)))
    return f"M{min(best_idx + 1, 4)}"


def _enrich_triple_with_aiml(result, ticker, capital):
    """Run AI/ML modules on the triple analysis result. Additive only."""
    t0 = time.time()
    ai_data = {"available": True, "modules": {}}

    bb_data = result.get("bb_data", {})
    orig_indicators = bb_data.get("indicators", {})
    price = orig_indicators.get("price", 0)

    # Build aliased copy — never mutate the original triple result
    indicators = dict(orig_indicators)
    snapshot = result.get("snapshot", {})
    if "rsi14" not in indicators and "rsi" not in indicators:
        if snapshot.get("rsi") is not None:
            indicators["rsi14"] = snapshot["rsi"]
        elif indicators.get("rsi_norm") is not None:
            indicators["rsi14"] = indicators["rsi_norm"] * 100
    if "sma20" not in indicators:
        indicators["sma20"] = indicators.get("bb_mid")
    if "upper_band" not in indicators:
        indicators["upper_band"] = indicators.get("bb_upper")
    if "lower_band" not in indicators:
        indicators["lower_band"] = indicators.get("bb_lower")
    if "vol_avg" not in indicators:
        indicators["vol_avg"] = indicators.get("vol_sma50")
    if "atr14" not in indicators and "atr" not in indicators:
        if snapshot.get("atr") is not None:
            indicators["atr14"] = snapshot["atr"]

    pick = {
        "ticker": ticker,
        "price": price,
        "current_price": price,
        "method": _best_bb_method(result),
        "stop_loss": result.get("triple_targets", {}).get("stop_loss", {}).get("price"),
        "bb_data": {"indicators": indicators, **{k: v for k, v in bb_data.items() if k != "indicators"}},
    }
    picks = [pick]

    # 1. ML Signal Filter (XGBoost + SHAP)
    try:
        from ai_ml.signal_filter import score_picks
        score_picks(picks)
        ai_data["modules"]["signal_filter"] = {"status": "ok"}
    except Exception as e:
        logger.warning("ML Signal Filter: %s", e)
        ai_data["modules"]["signal_filter"] = {"status": "error", "error": str(e)}

    # 2. Adaptive Thresholds
    try:
        from ai_ml.adaptive_thresholds import enrich_picks_with_adaptive
        enrich_picks_with_adaptive(picks)
        ai_data["modules"]["adaptive_thresholds"] = {"status": "ok"}
    except Exception as e:
        logger.warning("Adaptive Thresholds: %s", e)
        ai_data["modules"]["adaptive_thresholds"] = {"status": "error", "error": str(e)}

    # 3. Market Regime
    try:
        from ai_ml.regime_filter import get_market_regime, enrich_picks_with_regime
        regime = get_market_regime()
        enrich_picks_with_regime(picks, regime)
        ai_data["market_regime"] = regime
        ai_data["modules"]["regime_filter"] = {"status": "ok"}
    except Exception as e:
        logger.warning("Regime Filter: %s", e)
        ai_data["modules"]["regime_filter"] = {"status": "error", "error": str(e)}

    # 4. Exit Intelligence
    try:
        from ai_ml.exit_intelligence import enrich_picks_with_exit
        enrich_picks_with_exit(picks)
        ai_data["modules"]["exit_intelligence"] = {"status": "ok"}
    except Exception as e:
        logger.warning("Exit Intelligence: %s", e)
        ai_data["modules"]["exit_intelligence"] = {"status": "error", "error": str(e)}

    # 5. Regime Cluster (UMAP + KMeans)
    try:
        from ai_ml.regime_cluster import enrich_picks_with_clusters
        enrich_picks_with_clusters(picks)
        ai_data["modules"]["regime_cluster"] = {"status": "ok"}
    except Exception as e:
        logger.warning("Regime Cluster: %s", e)
        ai_data["modules"]["regime_cluster"] = {"status": "error", "error": str(e)}

    # 6. Sequence Scorer (LSTM)
    try:
        from ai_ml.sequence_scorer import score_picks_sequence
        score_picks_sequence(picks)
        ai_data["modules"]["sequence_scorer"] = {"status": "ok"}
    except Exception as e:
        logger.warning("Sequence Scorer: %s", e)
        ai_data["modules"]["sequence_scorer"] = {"status": "error", "error": str(e)}

    # 7. Method Router
    try:
        from ai_ml.method_router import get_method_recommendation
        rsi_val = indicators.get("rsi") or indicators.get("rsi14") or indicators.get("rsi_norm")
        bbw_pct = None
        adaptive = pick.get("adaptive_context", {})
        if isinstance(adaptive, dict) and adaptive.get("bbw_percentile"):
            bbw_pct = adaptive["bbw_percentile"] / 100.0
        ai_data["method_routing"] = get_method_recommendation(
            current_rsi=rsi_val, current_bbw_pct=bbw_pct,
        )
        ai_data["modules"]["method_router"] = {"status": "ok"}
    except Exception as e:
        logger.warning("Method Router: %s", e)
        ai_data["modules"]["method_router"] = {"status": "error", "error": str(e)}

    # 8. Position Sizer (Kelly / Vince)
    try:
        from ai_ml.position_sizer import compute_position_sizes
        compute_position_sizes(picks, capital=capital)
        ai_data["modules"]["position_sizer"] = {"status": "ok"}
    except Exception as e:
        logger.warning("Position Sizer: %s", e)
        ai_data["modules"]["position_sizer"] = {"status": "error", "error": str(e)}

    # 9. Keltner Squeeze Intelligence (T7)
    try:
        from ai_ml.keltner_squeeze import enrich_picks_with_keltner
        enrich_picks_with_keltner(picks)
        ai_data["modules"]["keltner_squeeze"] = {"status": "ok"}
    except Exception as e:
        logger.warning("Keltner Squeeze: %s", e)
        ai_data["modules"]["keltner_squeeze"] = {"status": "error", "error": str(e)}

    ai_data["elapsed_ms"] = round((time.time() - t0) * 1000)

    # Flatten pick-level fields into ai_data for easy template access
    ai_data["pick"] = {
        "ml_confidence": pick.get("ml_confidence"),
        "ml_verdict": pick.get("ml_verdict"),
        "ml_explanation": pick.get("ml_explanation"),
        "ml_downside_risk": pick.get("ml_downside_risk"),
        "ml_percentile": pick.get("ml_percentile"),
        "adaptive_context": pick.get("adaptive_context"),
        "market_regime": pick.get("market_regime"),
        "exit_intelligence": pick.get("exit_intelligence"),
        "regime_cluster_id": pick.get("regime_cluster_id"),
        "regime_cluster_label": pick.get("regime_cluster_label"),
        "regime_cluster_confidence": pick.get("regime_cluster_confidence"),
        "seq_confidence": pick.get("seq_confidence"),
        "seq_verdict": pick.get("seq_verdict"),
        "seq_agreement": pick.get("seq_agreement"),
        "size_kelly_fraction": pick.get("size_kelly_fraction"),
        "size_recommended_pct": pick.get("size_recommended_pct"),
        "size_recommended_amount": pick.get("size_recommended_amount"),
        "size_shares": pick.get("size_shares"),
        "size_risk_per_trade": pick.get("size_risk_per_trade"),
        "size_method_stats": pick.get("size_method_stats"),
        "kc_squeeze_data": pick.get("kc_squeeze_data"),
    }

    result["ai_ml"] = ai_data
