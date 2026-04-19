"""
rentech_routes.py — Flask Blueprint for the RenTech Quant Engine.

All routes are mounted under  /rentech/…
Blueprint name: 'rentech'
"""

import sys, os, json, math
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flask import Blueprint, render_template, jsonify, request

from bb_squeeze.data_loader import normalise_ticker, load_stock_data, get_all_tickers_from_csv
from rentech.engine import run_rentech_analysis


rentech_bp = Blueprint("rentech", __name__, template_folder="templates")


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


# ═══════════════════════════════════════════════════════════════
#  DASHBOARD PAGE
# ═══════════════════════════════════════════════════════════════

@rentech_bp.route("/rentech")
def rentech_dashboard():
    """Serve the RenTech Quant Engine dashboard."""
    from flask import make_response
    resp = make_response(render_template("rentech_dashboard.html"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp
    resp = make_response(render_template("rentech_dashboard.html"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp
    resp = make_response(render_template("rentech_dashboard.html"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


# ═══════════════════════════════════════════════════════════════
#  ANALYSIS API
# ═══════════════════════════════════════════════════════════════

@rentech_bp.route("/api/rentech/analyze")
def rentech_analyze():
    """
    Run RenTech quant analysis on a ticker.

    Query params:
        ?ticker=RELIANCE  (or RELIANCE.NS)
        &capital=1000000  (optional, default ₹10L)

    Returns JSON with:
        - verdict          : action, grade, score, regime, edge
        - statistical_profile : Hurst, OU, VR, ADF, autocorr, entropy, vol
        - regime           : current, transition, micro, optimal strategies
        - signals          : composite + 7 alpha signals
        - risk             : position sizing, levels, costs, drawdown
    """
    raw = request.args.get("ticker", "").strip()
    if not raw:
        return jsonify({"success": False, "error": "No ticker provided"}), 400

    ticker = normalise_ticker(raw)
    capital = float(request.args.get("capital", 1_000_000))

    df = load_stock_data(ticker)
    if df is None or df.empty:
        return jsonify({
            "success": False,
            "error": f"No data found for {ticker}"
        }), 404

    result = run_rentech_analysis(df, ticker, capital)
    return jsonify(_safe_json(result))


# ═══════════════════════════════════════════════════════════════
#  TICKERS API (autocomplete)
# ═══════════════════════════════════════════════════════════════

@rentech_bp.route("/api/rentech/tickers")
def rentech_tickers():
    """Return list of available tickers."""
    tickers = get_all_tickers_from_csv()
    return jsonify(sorted(tickers))
