"""
Vince Risk Management Routes — Flask Blueprint
================================================
Web routes for:
  /risk-management        — main dashboard page
  /api/vince/analyze      — full risk analysis for a ticker
  /api/vince/portfolio    — portfolio-level optimal allocation
  /api/vince/position-size — position sizing calculator
  /api/vince/frontier     — efficient frontier for portfolio tickers
"""

from __future__ import annotations
import sys, os, json, math
from typing import List

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from flask import Blueprint, jsonify, request, render_template
import numpy as np
import json

from bb_squeeze.data_loader import (
    normalise_ticker, load_stock_data, get_all_tickers_from_csv,
)
from bb_squeeze.portfolio_db import get_open_positions

vince_bp = Blueprint("vince", __name__)


# ─── Helpers ────────────────────────────────────────────────────

class _NumpyEncoder(json.JSONEncoder):
    """Handle numpy types that Flask's default encoder can't serialize."""
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


def _jsonify(data, status=200):
    """JSON response that handles numpy types."""
    from flask import Response
    return Response(
        json.dumps(data, cls=_NumpyEncoder),
        status=status,
        mimetype="application/json",
    )

def _trades_from_csv(ticker: str, period: int = 252) -> dict:
    """
    Extract daily P&L "trades" from CSV price data.

    Per the book (Application to Stock Trading, near end):
    Treat each day's price change as a trade. For stocks (no leverage),
    set risk-free rate to 0 and treat 100-share blocks as 1 contract.
    """
    df = load_stock_data(ticker)
    if df is None or df.empty:
        return {"error": f"No data for {ticker}"}

    # Use the last `period` rows
    df = df.tail(period + 1).copy()
    if len(df) < 20:
        return {"error": f"Insufficient data for {ticker}"}

    closes = df["Close"].values.astype(float)

    # Daily price changes (per share)
    daily_changes = list(np.diff(closes))
    # Also keep percentage changes for some analyses
    pct_changes = list(np.diff(closes) / closes[:-1])

    return {
        "ticker": ticker,
        "trades": daily_changes,
        "pct_changes": pct_changes,
        "closes": list(closes),
        "last_price": float(closes[-1]),
        "num_days": len(daily_changes),
    }


# ═══════════════════════════════════════════════════════════════════
#  PAGE ROUTE
# ═══════════════════════════════════════════════════════════════════

@vince_bp.route("/risk-management")
def risk_management_page():
    """Serve the Risk Management dashboard template."""
    tickers = get_all_tickers_from_csv()
    return render_template("risk_management.html", tickers=json.dumps(tickers))


# ═══════════════════════════════════════════════════════════════════
#  API: FULL TICKER ANALYSIS
# ═══════════════════════════════════════════════════════════════════

@vince_bp.route("/api/vince/analyze")
def api_vince_analyze():
    """
    Full Vince risk analysis for a single ticker.

    Query params:
      ticker  — stock symbol (e.g., RELIANCE)
      period  — lookback days (default 252)
      equity  — account equity (default 100000)
    """
    raw = request.args.get("ticker", "").strip()
    if not raw:
        return _jsonify({"error": "Ticker required"}, 400)

    ticker = normalise_ticker(raw)
    period = int(request.args.get("period", 252))
    equity = float(request.args.get("equity", 100000))

    data = _trades_from_csv(ticker, period)
    if "error" in data:
        return _jsonify(data, 404)

    trades = data["trades"]
    closes = data["closes"]
    price = data["last_price"]

    # Import vince modules
    from vince.optimal_f import (
        find_optimal_f_empirical, compute_by_products,
        fractional_f_analysis, f_curve_data,
        kelly_f, estimated_geometric_mean,
        fundamental_equation_of_trading,
    )
    from vince.statistics import (
        runs_test, serial_correlation, ks_test_normal,
        compute_moments, arc_sine_analysis, turning_points_test,
    )
    from vince.risk_metrics import (
        drawdown_analysis, position_sizing, historical_volatility,
        time_to_goal,
    )

    result = {"ticker": ticker, "period": period, "num_trades": len(trades)}

    # ── Optimal f ────────────────
    opt = find_optimal_f_empirical(trades)
    result["optimal_f"] = opt

    # ── By-products ──────────────
    if opt["optimal_f"] > 0:
        bp = compute_by_products(trades, opt["optimal_f"])
        result["by_products"] = bp

        # ── f-curve chart data ───
        fc = f_curve_data(trades, points=50)
        result["f_curve"] = fc

        # ── Fractional f ────────
        frac = fractional_f_analysis(
            bp["ahpr"], bp["sd_hpr"], opt["optimal_f"], opt["biggest_loss"]
        )
        result["fractional_f"] = frac

        # ── Fundamental equation ─
        egm = estimated_geometric_mean(bp["ahpr"], bp["sd_hpr"])
        fet = fundamental_equation_of_trading(bp["ahpr"], bp["sd_hpr"], len(trades))
        result["fundamental_equation"] = {
            "estimated_geometric_mean": round(egm, 6),
            "fundamental_twr": round(fet, 4),
            "actual_twr": bp["twr"],
        }

        # ── Position sizing at 50% f ──
        ps = position_sizing(equity, opt["optimal_f"], opt["biggest_loss"], price, 0.5)
        result["position_sizing"] = ps

        # ── Time to double ──
        if bp.get("geometric_mean", 0) > 1:
            result["time_to_double"] = time_to_goal(bp["geometric_mean"], 2.0)

    # ── Statistical tests ────────
    result["runs_test"] = runs_test(trades)
    result["serial_correlation"] = serial_correlation(trades)
    result["ks_test"] = ks_test_normal(trades)
    result["moments"] = compute_moments(trades)
    result["turning_points"] = turning_points_test(trades)
    result["arc_sine"] = arc_sine_analysis(len(trades))

    # ── Kelly ────────────────────
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t < 0]
    if wins and losses:
        wp = len(wins) / len(trades)
        wlr = (sum(wins) / len(wins)) / abs(sum(losses) / len(losses))
        result["kelly"] = kelly_f(wp, wlr)

    # ── Drawdown ─────────────────
    # Build equity curve from trades
    eq = [equity]
    for t in trades:
        eq.append(eq[-1] + t)
    result["drawdown"] = drawdown_analysis(eq)

    # ── Volatility ───────────────
    if len(closes) > 21:
        result["volatility"] = historical_volatility(list(closes))

    return _jsonify(result)


# ═══════════════════════════════════════════════════════════════════
#  API: POSITION SIZING CALCULATOR
# ═══════════════════════════════════════════════════════════════════

@vince_bp.route("/api/vince/position-size")
def api_vince_position_size():
    """
    Position sizing calculator.

    Query params:
      ticker       — stock symbol
      equity       — account equity
      fraction     — fraction of optimal f to use (default .5)
      period       — lookback days (default 252)
    """
    raw = request.args.get("ticker", "").strip()
    if not raw:
        return _jsonify({"error": "Ticker required"}, 400)

    ticker = normalise_ticker(raw)
    equity = float(request.args.get("equity", 100000))
    fraction = float(request.args.get("fraction", 0.5))
    period = int(request.args.get("period", 252))

    # Clamp fraction
    fraction = max(0.01, min(fraction, 1.0))

    data = _trades_from_csv(ticker, period)
    if "error" in data:
        return _jsonify(data, 404)

    from vince.optimal_f import find_optimal_f_empirical
    from vince.risk_metrics import position_sizing

    opt = find_optimal_f_empirical(data["trades"])
    if opt["optimal_f"] <= 0:
        return _jsonify({"error": "Could not compute optimal f"}, 400)

    ps = position_sizing(equity, opt["optimal_f"], opt["biggest_loss"],
                         data["last_price"], fraction)
    ps["optimal_f_raw"] = opt["optimal_f"]
    ps["ticker"] = ticker
    return _jsonify(ps)


# ═══════════════════════════════════════════════════════════════════
#  API: PORTFOLIO EFFICIENT FRONTIER
# ═══════════════════════════════════════════════════════════════════

@vince_bp.route("/api/vince/frontier")
def api_vince_frontier():
    """
    Efficient frontier for a set of tickers (from open positions or manual).

    Query params:
      tickers — comma-separated list (or uses open portfolio positions)
      period  — lookback days (default 252)
    """
    raw = request.args.get("tickers", "").strip()
    period = int(request.args.get("period", 252))

    if raw:
        ticker_list = [normalise_ticker(t.strip()) for t in raw.split(",") if t.strip()]
    else:
        positions = get_open_positions()
        ticker_list = list(set(normalise_ticker(p["ticker"]) for p in positions))

    if len(ticker_list) < 2:
        return _jsonify({"error": "Need at least 2 tickers for frontier analysis"}, 400)

    from vince.portfolio_math import (
        compute_correlation_matrix, compute_covariance_matrix,
        compute_efficient_frontier, geometric_frontier_analysis,
    )

    returns_map = {}
    stats = {}
    for t in ticker_list:
        data = _trades_from_csv(t, period)
        if "error" in data:
            continue
        returns_map[t] = data["pct_changes"]
        arr = np.array(data["pct_changes"])
        ahpr = float(np.mean(arr)) + 1
        sd = float(np.std(arr, ddof=0))
        stats[t] = {"ahpr": round(ahpr, 6), "sd": round(sd, 6)}

    valid_tickers = sorted(returns_map.keys())
    if len(valid_tickers) < 2:
        return _jsonify({"error": "Less than 2 valid tickers with data"}, 400)

    corr = compute_correlation_matrix(returns_map)
    cov = compute_covariance_matrix(returns_map)

    expected_returns = [stats[t]["ahpr"] - 1 for t in valid_tickers]
    frontier = compute_efficient_frontier(
        valid_tickers, expected_returns, cov["matrix"]
    )

    return _jsonify({
        "tickers": valid_tickers,
        "stats": stats,
        "correlation": corr,
        "frontier": frontier,
    })


# ═══════════════════════════════════════════════════════════════════
#  API: PORTFOLIO RISK SUMMARY (open positions)
# ═══════════════════════════════════════════════════════════════════

@vince_bp.route("/api/vince/portfolio-risk")
def api_vince_portfolio_risk():
    """
    Risk assessment for all open portfolio positions.
    """
    positions = get_open_positions()
    if not positions:
        return _jsonify({"error": "No open positions"}, 400)

    from vince.optimal_f import find_optimal_f_empirical, compute_by_products
    from vince.risk_metrics import position_sizing, historical_volatility

    equity = float(request.args.get("equity", 100000))
    period = int(request.args.get("period", 252))

    results = []
    for pos in positions:
        ticker = normalise_ticker(pos["ticker"])
        data = _trades_from_csv(ticker, period)
        if "error" in data:
            results.append({"ticker": ticker, "error": data["error"]})
            continue

        opt = find_optimal_f_empirical(data["trades"])
        item = {
            "ticker": ticker,
            "buy_price": pos.get("buy_price"),
            "quantity": pos.get("quantity"),
            "current_price": data["last_price"],
            "optimal_f": opt["optimal_f"],
            "biggest_loss": opt["biggest_loss"],
        }

        if opt["optimal_f"] > 0:
            bp = compute_by_products(data["trades"], opt["optimal_f"])
            ps = position_sizing(
                equity, opt["optimal_f"], opt["biggest_loss"],
                data["last_price"], 0.5,
            )
            item["geometric_mean"] = bp.get("geometric_mean")
            item["twr"] = bp.get("twr")
            item["recommended_shares"] = ps.get("shares_to_buy")
            item["risk_per_trade"] = ps.get("risk_per_trade")

            current_qty = pos.get("quantity", 0)
            rec_qty = ps.get("shares_to_buy", 0)
            if current_qty > 0 and rec_qty > 0:
                item["sizing_status"] = (
                    "OVERSIZED" if current_qty > rec_qty * 1.3
                    else "UNDERSIZED" if current_qty < rec_qty * 0.7
                    else "OPTIMAL"
                )

        if len(data.get("closes", [])) > 21:
            vol = historical_volatility(data["closes"])
            item["volatility_pct"] = vol.get("current_volatility_pct")

        results.append(item)

    return _jsonify({"equity": equity, "positions": results})
