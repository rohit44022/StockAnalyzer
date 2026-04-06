"""
Price Action Web Routes — Flask Blueprint
===========================================
API endpoints for the Price Action analysis system.
"""

from __future__ import annotations

import sys
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from flask import Blueprint, jsonify, request, render_template

from bb_squeeze.data_loader import (
    normalise_ticker, load_stock_data, get_all_tickers_from_csv,
)
from bb_squeeze.indicators import compute_all_indicators
from bb_squeeze.signals import analyze_signals
from bb_squeeze.config import CSV_DIR
from price_action.engine import run_price_action_analysis, pa_result_to_dict
from price_action import config as C

pa_bp = Blueprint("price_action", __name__)


@pa_bp.route("/pa")
def pa_dashboard():
    """Price Action dashboard page."""
    tickers = get_all_tickers_from_csv(CSV_DIR)
    return render_template("pa_dashboard.html", tickers=sorted(tickers))


# ─────────────────────────────────────────────────────────────────
#  SINGLE STOCK ANALYSIS
# ─────────────────────────────────────────────────────────────────

@pa_bp.route("/api/pa/<ticker>")
def api_pa_analysis(ticker: str):
    """Full Price Action analysis for a single stock."""
    ticker = normalise_ticker(ticker)

    df = load_stock_data(ticker, csv_dir=CSV_DIR, use_live_fallback=False)
    if df is None or len(df) < C.MIN_BARS_REQUIRED:
        return jsonify({"error": f"Insufficient data for {ticker}"}), 404

    # Also get BB data for cross-validation
    bb_data = None
    try:
        df_ind = compute_all_indicators(df)
        bb_sig = analyze_signals(ticker, df_ind)
        bb_data = {
            "buy_signal": bb_sig.buy_signal,
            "sell_signal": bb_sig.sell_signal,
            "direction_lean": bb_sig.direction_lean,
            "confidence": bb_sig.confidence,
            "phase": bb_sig.phase,
        }
    except Exception:
        pass

    # Get TA data
    ta_data = None
    try:
        from hybrid_engine import run_hybrid_analysis
        hyb = run_hybrid_analysis(df_ind if df_ind is not None else df, ticker=ticker)
        ta_data = hyb.get("ta_signal")
    except Exception:
        pass

    # Get Hybrid data
    hybrid_data = None
    try:
        if hyb:
            hybrid_data = hyb
    except Exception:
        pass

    result = run_price_action_analysis(
        df=df, ticker=ticker,
        bb_data=bb_data, ta_data=ta_data, hybrid_data=hybrid_data,
    )

    return jsonify(pa_result_to_dict(result))


# ─────────────────────────────────────────────────────────────────
#  FULL UNIVERSE SCAN
# ─────────────────────────────────────────────────────────────────

@pa_bp.route("/api/pa/scan")
def api_pa_scan():
    """
    Scan all stocks for Price Action signals.

    Query params:
    - direction: "buy" | "sell" | "all" (default: "all")
    - min_confidence: int (default: 30)
    - limit: int (default: 100)
    """
    direction_filter = request.args.get("direction", "all").lower()
    min_confidence = int(request.args.get("min_confidence", "30"))
    limit = int(request.args.get("limit", "100"))

    tickers = get_all_tickers_from_csv(CSV_DIR)
    results = []
    errors = 0

    for ticker in tickers:
        try:
            df = load_stock_data(ticker, csv_dir=CSV_DIR, use_live_fallback=False)
            if df is None or len(df) < C.MIN_BARS_REQUIRED:
                continue

            # Quick BB cross-validation
            bb_data = None
            try:
                df_ind = compute_all_indicators(df)
                bb_sig = analyze_signals(ticker, df_ind)
                bb_data = {
                    "buy_signal": bb_sig.buy_signal,
                    "sell_signal": bb_sig.sell_signal,
                    "direction_lean": bb_sig.direction_lean,
                    "confidence": bb_sig.confidence,
                }
            except Exception:
                pass

            r = run_price_action_analysis(df=df, ticker=ticker, bb_data=bb_data)

            if not r.success:
                continue
            if r.confidence < min_confidence:
                continue
            if direction_filter == "buy" and r.signal_type != "BUY":
                continue
            if direction_filter == "sell" and r.signal_type != "SELL":
                continue
            if direction_filter == "all" and r.signal_type == "HOLD":
                continue

            results.append(pa_result_to_dict(r))

        except Exception:
            errors += 1
            continue

    # Sort by confidence
    results.sort(key=lambda x: x["signal"]["confidence"], reverse=True)

    return jsonify({
        "count": len(results),
        "scanned": len(tickers),
        "errors": errors,
        "results": results[:limit],
    })


# ─────────────────────────────────────────────────────────────────
#  SCAN SUMMARY (lightweight)
# ─────────────────────────────────────────────────────────────────

@pa_bp.route("/api/pa/scan/summary")
def api_pa_scan_summary():
    """
    Quick scan summary — counts by category without full details.
    Faster than full scan for dashboard overview.
    """
    tickers = get_all_tickers_from_csv(CSV_DIR)
    counts = {
        "total_scanned": 0,
        "buy_signals": 0,
        "sell_signals": 0,
        "strong_buy": 0,
        "strong_sell": 0,
        "breakout_mode": 0,
        "spike_active": 0,
        "hold": 0,
        "errors": 0,
    }

    top_buy = []
    top_sell = []

    for ticker in tickers:
        try:
            df = load_stock_data(ticker, csv_dir=CSV_DIR, use_live_fallback=False)
            if df is None or len(df) < C.MIN_BARS_REQUIRED:
                continue

            r = run_price_action_analysis(df=df, ticker=ticker)
            if not r.success:
                counts["errors"] += 1
                continue

            counts["total_scanned"] += 1

            if r.signal_type == "BUY":
                counts["buy_signals"] += 1
                if r.strength == "STRONG":
                    counts["strong_buy"] += 1
                top_buy.append({"ticker": ticker, "confidence": r.confidence,
                                "setup": r.setup_type, "phase": r.trend_phase})
            elif r.signal_type == "SELL":
                counts["sell_signals"] += 1
                if r.strength == "STRONG":
                    counts["strong_sell"] += 1
                top_sell.append({"ticker": ticker, "confidence": r.confidence,
                                 "setup": r.setup_type, "phase": r.trend_phase})
            else:
                counts["hold"] += 1

            if r.breakout_mode:
                counts["breakout_mode"] += 1
            if r.trend_phase == "SPIKE":
                counts["spike_active"] += 1

        except Exception:
            counts["errors"] += 1

    # Sort and limit top picks
    top_buy.sort(key=lambda x: x["confidence"], reverse=True)
    top_sell.sort(key=lambda x: x["confidence"], reverse=True)

    return jsonify({
        "counts": counts,
        "top_buy": top_buy[:10],
        "top_sell": top_sell[:10],
    })
