"""
ta_routes.py — Flask Blueprint for the Technical Analysis Module.

All routes are mounted under  /ta/…
Blueprint name: 'ta'
"""

import sys, os, json, math
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flask import Blueprint, render_template, jsonify, request

from bb_squeeze.data_loader import normalise_ticker, load_stock_data, get_all_tickers_from_csv, get_data_freshness
from bb_squeeze.config import CSV_DIR

from technical_analysis.indicators import (
    compute_all_ta_indicators,
    get_indicator_snapshot,
    detect_ma_crossovers,
    detect_all_divergences,
    compute_pivot_points,
    compute_fibonacci,
)
from technical_analysis.candlesticks import scan_candlestick_patterns
from technical_analysis.patterns import (
    detect_support_resistance,
    identify_trend,
    detect_all_chart_patterns,
    analyze_volume,
    analyze_ichimoku,
)
from technical_analysis.signals import generate_signal
from technical_analysis.risk_manager import generate_risk_report
from technical_analysis.education import get_all_education
from technical_analysis.target_price import calculate_target_prices

ta_bp = Blueprint("ta", __name__, template_folder="templates")


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

@ta_bp.route("/ta")
def ta_dashboard():
    """Serve the main Technical Analysis dashboard."""
    return render_template("ta_dashboard.html")


# ═══════════════════════════════════════════════════════════════
#  FULL ANALYSIS API
# ═══════════════════════════════════════════════════════════════

@ta_bp.route("/api/ta/analyze")
def ta_analyze():
    """
    Full technical analysis for a ticker.

    Query params:  ?ticker=RELIANCE  (or RELIANCE.NS)
                   &capital=500000   (optional, default 500000)

    Returns JSON with:
      - snapshot   : latest values of all indicators
      - trend      : trend classification (Dow Theory)
      - crossovers : MA crossover events
      - divergences: RSI/MACD/OBV divergences
      - candle_patterns: detected candlestick patterns
      - chart_patterns : detected chart patterns (H&S, triangles…)
      - volume     : volume analysis
      - ichimoku   : full Ichimoku interpretation
      - support_resistance: S/R levels
      - fibonacci  : Fibonacci retracement levels
      - pivot_points: classic pivot points
      - signal     : FINAL multi-indicator consensus verdict
      - risk       : risk management report
    """
    raw = request.args.get("ticker", "").strip()
    if not raw:
        return jsonify({"error": "Provide ?ticker=SYMBOL"}), 400

    ticker = normalise_ticker(raw)
    df = load_stock_data(ticker, CSV_DIR)
    if df is None or df.empty:
        return jsonify({"error": f"No data for {ticker}"}), 404

    capital = float(request.args.get("capital", 500000))

    # ── Compute all indicators ──────────────────────────────
    df = compute_all_ta_indicators(df)

    # ── Extract analyses ────────────────────────────────────
    snapshot = get_indicator_snapshot(df)
    trend = identify_trend(df)
    crossovers = detect_ma_crossovers(df)
    divergences = detect_all_divergences(df)
    candle_patterns = scan_candlestick_patterns(df, lookback=5)
    chart_patterns = detect_all_chart_patterns(df)
    vol_analysis = analyze_volume(df)
    ichimoku = analyze_ichimoku(df)
    sr_data = detect_support_resistance(df)
    fib_data = compute_fibonacci(df)
    pivot = compute_pivot_points(df)

    # ── Generate signal ─────────────────────────────────────
    signal = generate_signal(
        snap=snapshot,
        trend=trend,
        vol_analysis=vol_analysis,
        chart_patterns=chart_patterns,
        candle_patterns=candle_patterns,
        divergences=divergences,
        sr_data=sr_data,
        fib_data=fib_data,
    )

    # ── Risk report ─────────────────────────────────────────
    risk = generate_risk_report(snapshot, sr_data, capital)

    # ── Target prices ───────────────────────────────────────
    target_prices = calculate_target_prices(
        snap=snapshot, trend=trend, sr_data=sr_data,
        fib_data=fib_data, pivot=pivot, chart_patterns=chart_patterns,
    )

    # ── Stock meta ──────────────────────────────────────────
    freshness = get_data_freshness(df)
    meta = {
        "ticker": ticker,
        "display_name": ticker.replace(".NS", ""),
        "data_points": len(df),
        "date_range": f"{str(df.index[0])[:10]} → {str(df.index[-1])[:10]}",
        "last_date": str(df.index[-1])[:10],
    }

    response = _safe_json({
        "meta": meta,
        "data_freshness": freshness,
        "snapshot": snapshot,
        "trend": trend,
        "crossovers": crossovers,
        "divergences": divergences,
        "candle_patterns": candle_patterns,
        "chart_patterns": chart_patterns,
        "volume": vol_analysis,
        "ichimoku": ichimoku,
        "support_resistance": sr_data,
        "fibonacci": fib_data,
        "pivot_points": pivot,
        "signal": signal,
        "risk": risk,
        "target_prices": target_prices,
    })

    return jsonify(response)


# ═══════════════════════════════════════════════════════════════
#  EDUCATION API
# ═══════════════════════════════════════════════════════════════

@ta_bp.route("/api/ta/education")
def ta_education():
    """Return all educational content (definitions, explanations)."""
    return jsonify(get_all_education())


# ═══════════════════════════════════════════════════════════════
#  CHART DATA API  (for TradingView / Chart.js)
# ═══════════════════════════════════════════════════════════════

@ta_bp.route("/api/ta/chart")
def ta_chart_data():
    """
    Return OHLCV + indicator data for charting.
    Query:  ?ticker=RELIANCE&days=180
    """
    raw = request.args.get("ticker", "").strip()
    if not raw:
        return jsonify({"error": "Provide ?ticker=SYMBOL"}), 400

    ticker = normalise_ticker(raw)
    days = int(request.args.get("days", 180))
    df = load_stock_data(ticker, CSV_DIR)
    if df is None or df.empty:
        return jsonify({"error": f"No data for {ticker}"}), 404

    df = compute_all_ta_indicators(df)
    df = df.tail(days)

    def _col(name):
        if name in df.columns:
            vals = df[name].tolist()
            return [None if (v is None or (isinstance(v, float) and math.isnan(v))) else round(v, 4) for v in vals]
        return []

    dates = [str(d)[:10] for d in df.index]

    chart = {
        "dates": dates,
        "open": _col("Open"),
        "high": _col("High"),
        "low": _col("Low"),
        "close": _col("Close"),
        "volume": [int(v) if not math.isnan(v) else 0 for v in df["Volume"].tolist()],
        "sma_20": _col("SMA_20"),
        "sma_50": _col("SMA_50"),
        "sma_200": _col("SMA_200"),
        "ema_21": _col("EMA_21"),
        "bb_upper": _col("BB_Upper"),
        "bb_mid": _col("BB_Mid"),
        "bb_lower": _col("BB_Lower"),
        "rsi": _col("RSI"),
        "macd": _col("MACD"),
        "macd_signal": _col("MACD_Signal"),
        "macd_hist": _col("MACD_Hist"),
        "supertrend": _col("SUPERTREND"),
    }

    return jsonify(chart)
