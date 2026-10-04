"""
web/bb_methods_routes.py — Bollinger Band Methods dashboard.

Routes:
  GET  /bb-methods              — Dashboard page
  GET  /api/bb-methods/accuracy — Real-trade accuracy from portfolio_db
  GET  /api/bb-methods/backtest — Historical backtest accuracy (cached in-memory)
"""
from __future__ import annotations

import os, sys, time, threading
from datetime import date
from flask import Blueprint, render_template, jsonify, request

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from bb_squeeze.portfolio_db import _conn
from bb_squeeze.strategy_config import STRATEGY_NAMES, STRATEGY_DESCRIPTIONS

bb_methods_bp = Blueprint("bb_methods", __name__)

# ── Page ────────────────────────────────────────────────────────

@bb_methods_bp.route("/bb-methods")
def bb_methods_page():
    return render_template("bb_methods.html")


# ── Real-trade accuracy from portfolio ──────────────────────────

@bb_methods_bp.route("/api/bb-methods/accuracy")
def api_bb_methods_accuracy():
    """Per-method accuracy computed from closed portfolio positions."""
    c = _conn()
    rows = c.execute("""
        SELECT strategy_code, buy_price, sell_price, quantity,
               buy_date, sell_date, status
          FROM portfolio_positions
         WHERE strategy_code IN ('M1','M2','M3','M4')
         ORDER BY strategy_code, sell_date DESC
    """).fetchall()
    c.close()

    methods = {}
    for code in ("M1", "M2", "M3", "M4"):
        methods[code] = {
            "name": STRATEGY_NAMES.get(code, code),
            "description": STRATEGY_DESCRIPTIONS.get(code, ""),
            "open": 0, "closed": 0, "wins": 0, "losses": 0,
            "total_pnl_pct": 0.0, "best_pct": None, "worst_pct": None,
            "avg_hold_days": 0, "win_rate": 0.0,
            "trades": [],
        }

    for r in rows:
        code = r["strategy_code"]
        if code not in methods:
            continue
        m = methods[code]

        if r["status"] == "OPEN":
            m["open"] += 1
            continue

        buy_p = float(r["buy_price"]) if r["buy_price"] else 0
        sell_p = float(r["sell_price"]) if r["sell_price"] else 0
        if buy_p <= 0:
            continue

        pnl_pct = round((sell_p - buy_p) / buy_p * 100, 2)
        m["closed"] += 1
        if pnl_pct > 0:
            m["wins"] += 1
        else:
            m["losses"] += 1
        m["total_pnl_pct"] += pnl_pct

        if m["best_pct"] is None or pnl_pct > m["best_pct"]:
            m["best_pct"] = pnl_pct
        if m["worst_pct"] is None or pnl_pct < m["worst_pct"]:
            m["worst_pct"] = pnl_pct

        hold = 0
        if r["buy_date"] and r["sell_date"]:
            try:
                from datetime import datetime
                bd = datetime.strptime(r["buy_date"][:10], "%Y-%m-%d")
                sd = datetime.strptime(r["sell_date"][:10], "%Y-%m-%d")
                hold = (sd - bd).days
            except Exception:
                pass
        m["avg_hold_days"] += hold

        m["trades"].append({
            "buy_price": buy_p, "sell_price": sell_p,
            "pnl_pct": pnl_pct, "hold_days": hold,
            "buy_date": r["buy_date"], "sell_date": r["sell_date"],
        })

    for m in methods.values():
        if m["closed"] > 0:
            m["win_rate"] = round(m["wins"] / m["closed"] * 100, 1)
            m["avg_pnl_pct"] = round(m["total_pnl_pct"] / m["closed"], 2)
            m["avg_hold_days"] = round(m["avg_hold_days"] / m["closed"], 1)
        else:
            m["avg_pnl_pct"] = 0.0
        m["trades"] = m["trades"][:20]

    return jsonify(methods)


# ── Historical backtest accuracy (cached) ───────────────────────

_backtest_cache: dict = {}
_backtest_lock = threading.Lock()
_CACHE_TTL = 3600 * 4  # 4 hours

@bb_methods_bp.route("/api/bb-methods/backtest")
def api_bb_methods_backtest():
    """Run backtester for all 4 methods. Cached 4h. Pass ?refresh=1 to force."""
    force = request.args.get("refresh") == "1"

    now = time.time()
    if not force and _backtest_cache.get("ts") and (now - _backtest_cache["ts"]) < _CACHE_TTL:
        return jsonify(_backtest_cache["data"])

    from bb_squeeze.backtester import backtest_method
    from bb_squeeze.data_loader import get_all_tickers_from_csv
    from bb_squeeze.config import CSV_DIR

    tickers = get_all_tickers_from_csv(CSV_DIR)
    end = date.today().strftime("%Y-%m-%d")
    start = "2025-01-01"

    results = {}
    for method in ("M1", "M2", "M3", "M4"):
        try:
            stats = backtest_method(
                method=method, tickers=tickers,
                start_date=start, end_date=end, csv_dir=CSV_DIR,
            )
            results[method] = {
                "total_trades": stats["total_trades"],
                "wins": stats["wins"],
                "losses": stats["losses"],
                "win_rate": round(stats["win_rate"] * 100, 1),
                "profit_factor": stats["profit_factor"],
                "expectancy_r": stats["expectancy_r"],
                "avg_winner_r": stats["avg_winner_r"],
                "avg_loser_r": stats["avg_loser_r"],
                "max_consecutive_wins": stats["max_consecutive_wins"],
                "max_consecutive_losses": stats["max_consecutive_losses"],
                "explanation": stats["explanation"],
            }
        except Exception as e:
            results[method] = {"error": str(e)}

    with _backtest_lock:
        _backtest_cache["data"] = results
        _backtest_cache["ts"] = now

    return jsonify(results)
