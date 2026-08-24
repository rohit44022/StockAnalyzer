"""
web/holdings_routes.py — Zerodha-style Holdings page.

Routes:
  GET  /holdings           — holdings page
  GET  /api/holdings/live  — live P&L data (merges positions + live prices)
"""
from __future__ import annotations
import sys, os
from flask import Blueprint, jsonify, render_template, g

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from bb_squeeze.portfolio_db import get_open_positions

holdings_bp = Blueprint("holdings", __name__)


def _uid():
    if hasattr(g, "user") and g.user:
        return g.user.get("user_id")
    return None


def _is_admin():
    u = getattr(g, "user", None)
    return bool(u and u.get("is_admin"))


@holdings_bp.route("/holdings")
def holdings_page():
    return render_template("holdings.html")


@holdings_bp.route("/api/holdings/live")
def api_holdings_live():
    from web.app import get_live_prices

    uid, admin = _uid(), _is_admin()
    positions = get_open_positions(user_id=uid, is_admin=admin)
    live = get_live_prices(uid, admin)

    price_map = {}
    for t in live.get("tickers", []):
        raw = t.get("raw_symbol", t["symbol"])
        price_map[raw.replace(".NS", "").upper()] = t

    holdings = []
    totals = {"invested": 0, "current": 0, "pnl": 0, "day_pnl": 0}

    for p in positions:
        ticker = (p.get("ticker") or "").strip().upper().replace(".NS", "")
        qty = p.get("quantity") or 0
        avg = p.get("buy_price") or 0
        invested = round(avg * qty, 2)

        tk = price_map.get(ticker, {})
        ltp = tk.get("price", avg)
        current = round(ltp * qty, 2)
        pnl = round(current - invested, 2)
        pnl_pct = round((pnl / invested) * 100, 2) if invested else 0
        day_chg = round(tk.get("change", 0) * qty, 2)
        day_chg_pct = tk.get("change_pct", 0)

        holdings.append({
            "id": p.get("id"), "ticker": ticker, "qty": qty, "avg_price": avg,
            "ltp": ltp, "invested": invested, "current": current,
            "pnl": pnl, "pnl_pct": pnl_pct,
            "day_change": day_chg, "day_change_pct": day_chg_pct,
            "buy_date": p.get("buy_date", ""),
            "strategy": p.get("strategy_code", ""),
            "platform": p.get("platform", "zerodha"),
            "owner": p.get("owner", "Self"),
        })

        totals["invested"] += invested
        totals["current"] += current
        totals["pnl"] += pnl
        totals["day_pnl"] += day_chg

    totals = {k: round(v, 2) for k, v in totals.items()}
    totals["pnl_pct"] = round(
        (totals["pnl"] / totals["invested"]) * 100, 2
    ) if totals["invested"] else 0

    return jsonify({
        "holdings": holdings, "totals": totals,
        "market_open": live.get("market_open", False),
        "as_of": live.get("as_of"),
    })
