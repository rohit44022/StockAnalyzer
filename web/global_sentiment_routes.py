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
from datetime import date
import numpy as np
from flask import Blueprint, jsonify, request, render_template, Response

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


@global_sentiment_bp.route("/api/global-sentiment/export/pdf")
def api_global_sentiment_export_pdf():
    """Download the current global-sentiment readout as a colour-coded PDF.

    Re-uses the same engine output the dashboard renders. Optional
    `?refresh=1` bypasses the 15-minute cache before rendering.
    """
    from web.pdf_global_sentiment import build_global_sentiment_pdf

    refresh = request.args.get("refresh", "0").lower() in ("1", "true", "yes")
    result = _safe_json(get_global_sentiment(force_refresh=refresh))

    try:
        pdf_bytes = build_global_sentiment_pdf(result)
    except Exception as ex:
        return jsonify({"error": f"PDF build failed: {ex}"}), 500

    filename = f"Hiranya_Global_Sentiment_{date.today().isoformat()}.pdf"
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
