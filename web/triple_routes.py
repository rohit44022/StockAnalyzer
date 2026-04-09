"""
triple_routes.py — Flask Blueprint for BB + TA + PA Triple Conviction Engine.

Routes: /triple, /api/triple/analyze
Blueprint name: 'triple'
"""

import sys, os, json, math
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flask import Blueprint, render_template, jsonify, request

from bb_squeeze.data_loader import normalise_ticker, load_stock_data, get_all_tickers_from_csv
from bb_squeeze.config import CSV_DIR
from hybrid_pa_engine import run_triple_analysis


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
    safe = _safe_json(result)
    return jsonify(safe)
