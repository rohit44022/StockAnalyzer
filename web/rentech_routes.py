"""
rentech_routes.py — Flask Blueprint for the RenTech Quant Engine.

All routes are mounted under  /rentech/…
Blueprint name: 'rentech'
"""

import sys, os, json, math, queue, threading
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flask import Blueprint, render_template, jsonify, request, Response

from bb_squeeze.data_loader import normalise_ticker, load_stock_data, get_all_tickers_from_csv
from rentech.engine import run_rentech_analysis, scan_top_bullish


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


# ═══════════════════════════════════════════════════════════════
#  TOP BULLISH SCAN
# ═══════════════════════════════════════════════════════════════

def _scan_args():
    """Parse shared query params for both scan routes."""
    n = max(1, min(int(request.args.get("n", 5)), 20))
    capital = float(request.args.get("capital", 1_000_000))
    limit = request.args.get("limit")
    tickers = None
    if limit:  # dev/testing escape hatch — scan only the first N tickers
        tickers = sorted(get_all_tickers_from_csv())[:int(limit)]
    return n, capital, tickers


@rentech_bp.route("/api/rentech/scan/bullish")
def rentech_scan_bullish():
    """
    Blocking scan — returns top N most bullish by RenTech composite score.

    A full scan of ~2900 tickers takes several minutes, so browsers should use
    the /stream variant below. This route stays for scripts and small scans.

    Query params:
      ?n=5             — how many top picks (default 5, max 20)
      &capital=1000000 — portfolio capital in ₹
      &limit=50        — only scan the first 50 tickers (testing)
    """
    n, capital, tickers = _scan_args()
    result = scan_top_bullish(n=n, capital=capital, tickers=tickers)
    return jsonify(_safe_json(result))


@rentech_bp.route("/api/rentech/scan/bullish/stream")
def rentech_scan_bullish_stream():
    """
    Server-Sent Events version of the bullish scan.

    A full scan takes minutes, so this pushes {type:"progress"} events as each
    ticker completes and a final {type:"result"} event with the picks. Same
    query params as the blocking route.
    """
    n, capital, tickers = _scan_args()
    q = queue.Queue()

    def _run():
        try:
            q.put({"type": "phase", "message": "Scanning all stocks with RenTech…"})
            result = scan_top_bullish(
                n=n, capital=capital, tickers=tickers,
                progress_callback=lambda done, total, ticker: q.put({
                    "type": "progress",
                    "done": done,
                    "total": total,
                    "ticker": ticker,
                    "pct": round(done / total * 100) if total else 0,
                }),
            )
            q.put({"type": "result", "data": _safe_json(result)})
        except Exception as e:
            q.put({"type": "error", "message": str(e)})

    threading.Thread(target=_run, daemon=True).start()

    def _generate():
        while True:
            try:
                msg = q.get(timeout=300)
            except queue.Empty:
                yield 'data: {"type":"error","message":"Scan timed out"}\n\n'
                return
            yield f"data: {json.dumps(msg)}\n\n"
            if msg.get("type") in ("result", "error"):
                return

    return Response(
        _generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
