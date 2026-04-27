"""
global_sentiment_routes.py — Flask blueprint exposing the macro sentiment engine.
══════════════════════════════════════════════════════════════════════════════════

Routes:
    GET /api/global-sentiment              — JSON readout (15-min cache)
    GET /api/global-sentiment?refresh=1    — bypass cache

Isolation:
  This blueprint is purely read-only and never touches existing routes,
  databases, or analysis pipelines. If the engine fails, the response carries
  ok=False and the frontend hides the section.
"""

import sys, os, math, json
import numpy as np
from flask import Blueprint, jsonify, request, render_template

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from global_sentiment.engine import get_global_sentiment, get_health_summary


global_sentiment_bp = Blueprint("global_sentiment", __name__, template_folder="templates")


@global_sentiment_bp.route("/global-sentiment")
def page_global_sentiment():
    """Render the dedicated Global Market Sentiment dashboard page."""
    return render_template("global_sentiment.html")


@global_sentiment_bp.route("/api/global-sentiment/health")
def api_global_sentiment_health():
    """Lightweight health check — does not trigger a fetch."""
    return jsonify(_safe_json(get_health_summary()))


def _safe_json(obj):
    """Strip NaN/Inf, convert numpy types — matching the project's JSON conventions."""
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


@global_sentiment_bp.route("/api/global-sentiment")
def api_global_sentiment():
    refresh = request.args.get("refresh", "0").lower() in ("1", "true", "yes")
    result = get_global_sentiment(force_refresh=refresh)
    return jsonify(_safe_json(result))
