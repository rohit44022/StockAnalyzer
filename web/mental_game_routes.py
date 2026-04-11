"""
Mental Game Routes — Flask Blueprint
=====================================
Based on "The Mental Game of Trading" by Jared Tendler.

Routes:
  /mental-game                    — main dashboard page
  /api/mental-game/session        — daily session CRUD
  /api/mental-game/trade-psych    — per-trade psychology CRUD
  /api/mental-game/weekly         — weekly reports
  /api/mental-game/perf-map       — performance map
  /api/mental-game/learning-curve — inchworm tracker
  /api/mental-game/emergency      — emergency protocol log
  /api/mental-game/score-band     — score definitions
  /api/mental-game/patterns       — pattern detection
  /api/mental-game/analytics      — weekly summary auto-compute
  /api/mental-game/reference      — static reference data
"""

from __future__ import annotations
import sys, os
from datetime import datetime, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from flask import Blueprint, jsonify, request, render_template

from mental_game.db import (
    init_mental_game_db,
    save_daily_session, get_daily_session, get_all_sessions,
    save_trade_psychology, update_trade_psychology,
    get_trade_psychology, get_trade_psych_by_position,
    get_all_trade_psychology, get_trade_psych_for_week,
    save_weekly_report, get_all_weekly_reports,
    save_perf_map_entry, update_perf_map_entry,
    delete_perf_map_entry, get_all_perf_map,
    save_learning_curve, get_all_learning_curve,
    save_emergency_log, get_all_emergency_logs,
)
from mental_game.engine import (
    SCORE_BANDS, get_score_band, get_position_size_pct, get_min_confluence,
    get_max_trades, PATTERN_DEFINITIONS, detect_patterns,
    EMERGENCY_PROTOCOLS, IN_TRADE_RULES, PRE_SESSION_CHECKLIST,
    PRE_TRADE_GATE, COMPETENCE_LEVELS, generate_weekly_summary,
    DAILY_WORKFLOW, am_i_trading_system_or_emotions,
)
from bb_squeeze.portfolio_db import get_all_positions
from bb_squeeze.trade_db import get_all_trades

mental_game_bp = Blueprint("mental_game", __name__)


# ═══════════════════════════════════════════════════════════════
#  PAGE
# ═══════════════════════════════════════════════════════════════

@mental_game_bp.route("/mental-game")
def mental_game_page():
    return render_template("mental_game.html")


# ═══════════════════════════════════════════════════════════════
#  DAILY SESSION
# ═══════════════════════════════════════════════════════════════

@mental_game_bp.route("/api/mental-game/session", methods=["GET"])
def api_mg_sessions():
    date_param = request.args.get("date")
    if date_param:
        s = get_daily_session(date_param)
        return jsonify(s if s else {})
    return jsonify(get_all_sessions(int(request.args.get("limit", 30))))


@mental_game_bp.route("/api/mental-game/session", methods=["POST"])
def api_mg_save_session():
    data = request.get_json(force=True)
    if not data.get("session_date"):
        return jsonify({"error": "session_date required"}), 400
    sid = save_daily_session(data)
    # Return computed integration rules
    score = int(data.get("mental_score", 7))
    return jsonify({
        "status": "ok", "id": sid,
        "score_band": get_score_band(score),
        "position_size_pct": get_position_size_pct(score),
        "min_confluence": get_min_confluence(score),
        "max_trades": get_max_trades(score),
    })


# ═══════════════════════════════════════════════════════════════
#  TRADE PSYCHOLOGY
# ═══════════════════════════════════════════════════════════════

@mental_game_bp.route("/api/mental-game/trade-psych", methods=["GET"])
def api_mg_trade_psych_list():
    pid = request.args.get("position_id")
    if pid:
        rec = get_trade_psych_by_position(int(pid))
        return jsonify(rec if rec else {})
    return jsonify(get_all_trade_psychology(int(request.args.get("limit", 100))))


@mental_game_bp.route("/api/mental-game/trade-psych", methods=["POST"])
def api_mg_save_trade_psych():
    data = request.get_json(force=True)
    if not data.get("trade_date") or not data.get("ticker"):
        return jsonify({"error": "trade_date and ticker required"}), 400
    tid = save_trade_psychology(data)
    return jsonify({"status": "ok", "id": tid})


@mental_game_bp.route("/api/mental-game/trade-psych/<int:tid>", methods=["PUT"])
def api_mg_update_trade_psych(tid):
    data = request.get_json(force=True)
    ok = update_trade_psychology(tid, data)
    return jsonify({"status": "ok" if ok else "not_found"})


# ═══════════════════════════════════════════════════════════════
#  WEEKLY REPORT
# ═══════════════════════════════════════════════════════════════

@mental_game_bp.route("/api/mental-game/weekly", methods=["GET"])
def api_mg_weekly_list():
    return jsonify(get_all_weekly_reports())


@mental_game_bp.route("/api/mental-game/weekly", methods=["POST"])
def api_mg_save_weekly():
    data = request.get_json(force=True)
    if not data.get("week_start") or not data.get("week_end"):
        return jsonify({"error": "week_start and week_end required"}), 400
    wid = save_weekly_report(data)
    return jsonify({"status": "ok", "id": wid})


# ═══════════════════════════════════════════════════════════════
#  ANALYTICS — auto-computed weekly summary
# ═══════════════════════════════════════════════════════════════

@mental_game_bp.route("/api/mental-game/analytics", methods=["GET"])
def api_mg_analytics():
    """Auto-compute weekly summary from trade psychology records."""
    days = int(request.args.get("days", 7))
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    trades = get_trade_psych_for_week(start, end)
    summary = generate_weekly_summary(trades)
    summary["period"] = {"start": start, "end": end, "days": days}
    return jsonify(summary)


# ═══════════════════════════════════════════════════════════════
#  PERFORMANCE MAP
# ═══════════════════════════════════════════════════════════════

@mental_game_bp.route("/api/mental-game/perf-map", methods=["GET"])
def api_mg_perf_map():
    return jsonify(get_all_perf_map())


@mental_game_bp.route("/api/mental-game/perf-map", methods=["POST"])
def api_mg_save_perf_map():
    data = request.get_json(force=True)
    for f in ("mistake", "emotion_behind", "root_cause", "correction", "early_warning"):
        if not data.get(f):
            return jsonify({"error": f"Missing: {f}"}), 400
    mid = save_perf_map_entry(data)
    return jsonify({"status": "ok", "id": mid})


@mental_game_bp.route("/api/mental-game/perf-map/<int:mid>", methods=["PUT"])
def api_mg_update_perf_map(mid):
    data = request.get_json(force=True)
    ok = update_perf_map_entry(mid, data)
    return jsonify({"status": "ok" if ok else "not_found"})


@mental_game_bp.route("/api/mental-game/perf-map/<int:mid>", methods=["DELETE"])
def api_mg_delete_perf_map(mid):
    ok = delete_perf_map_entry(mid)
    return jsonify({"status": "ok" if ok else "not_found"})


# ═══════════════════════════════════════════════════════════════
#  LEARNING CURVE / INCHWORM
# ═══════════════════════════════════════════════════════════════

@mental_game_bp.route("/api/mental-game/learning-curve", methods=["GET"])
def api_mg_learning_curve():
    return jsonify(get_all_learning_curve())


@mental_game_bp.route("/api/mental-game/learning-curve", methods=["POST"])
def api_mg_save_learning_curve():
    data = request.get_json(force=True)
    if not data.get("month"):
        return jsonify({"error": "month required (e.g. 2026-04)"}), 400
    lid = save_learning_curve(data)
    return jsonify({"status": "ok", "id": lid})


# ═══════════════════════════════════════════════════════════════
#  EMERGENCY LOG
# ═══════════════════════════════════════════════════════════════

@mental_game_bp.route("/api/mental-game/emergency", methods=["GET"])
def api_mg_emergency_list():
    return jsonify(get_all_emergency_logs())


@mental_game_bp.route("/api/mental-game/emergency", methods=["POST"])
def api_mg_save_emergency():
    data = request.get_json(force=True)
    if not data.get("log_date") or not data.get("protocol_type"):
        return jsonify({"error": "log_date and protocol_type required"}), 400
    eid = save_emergency_log(data)
    return jsonify({"status": "ok", "id": eid})


# ═══════════════════════════════════════════════════════════════
#  PATTERN DETECTION
# ═══════════════════════════════════════════════════════════════

@mental_game_bp.route("/api/mental-game/patterns", methods=["GET"])
def api_mg_patterns():
    """Detect patterns from recent trade psychology records."""
    days = int(request.args.get("days", 7))
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    trades = get_trade_psych_for_week(start, end)
    alerts = detect_patterns(trades)
    return jsonify({"alerts": alerts, "trade_count": len(trades)})


# ═══════════════════════════════════════════════════════════════
#  SCORE BAND LOOKUP
# ═══════════════════════════════════════════════════════════════

@mental_game_bp.route("/api/mental-game/score-band", methods=["GET"])
def api_mg_score_band():
    score = int(request.args.get("score", 7))
    band = get_score_band(score)
    return jsonify({
        "score": score,
        "band": band,
        "position_size_pct": get_position_size_pct(score),
        "min_confluence": get_min_confluence(score),
        "max_trades": get_max_trades(score),
    })


# ═══════════════════════════════════════════════════════════════
#  STATIC REFERENCE DATA
# ═══════════════════════════════════════════════════════════════

@mental_game_bp.route("/api/mental-game/reference", methods=["GET"])
def api_mg_reference():
    """Return all static definitions for frontend use."""
    return jsonify({
        "score_bands": {str(k): v for k, v in SCORE_BANDS.items()},
        "patterns": PATTERN_DEFINITIONS,
        "emergency_protocols": EMERGENCY_PROTOCOLS,
        "in_trade_rules": IN_TRADE_RULES,
        "pre_session_checklist": PRE_SESSION_CHECKLIST,
        "pre_trade_gate": PRE_TRADE_GATE,
        "competence_levels": COMPETENCE_LEVELS,
        "daily_workflow": DAILY_WORKFLOW,
    })


# ═══════════════════════════════════════════════════════════════
#  MASTER QUESTION API
# ═══════════════════════════════════════════════════════════════

@mental_game_bp.route("/api/mental-game/system-check", methods=["POST"])
def api_mg_system_check():
    """Am I trading my system right now — or my emotions?"""
    data = request.get_json(force=True)
    result = am_i_trading_system_or_emotions(
        mental_score=int(data.get("mental_score", 5)),
        gate_passed=data.get("gate_passed", False),
        system_signal=data.get("system_signal", False),
    )
    return jsonify(result)


# ═══════════════════════════════════════════════════════════════
#  PORTFOLIO SYNC — link existing trades to psychology
# ═══════════════════════════════════════════════════════════════

@mental_game_bp.route("/api/mental-game/unlinked-trades", methods=["GET"])
def api_mg_unlinked_trades():
    """Return portfolio positions & P&L trades that have no psychology entry."""
    all_psych = get_all_trade_psychology(limit=9999)
    linked_pids = {p["position_id"] for p in all_psych if p.get("position_id")}
    # ticker+date combos already logged (for trades without position_id)
    linked_keys = {
        (p["ticker"].upper().strip(), p["trade_date"])
        for p in all_psych if p.get("ticker") and p.get("trade_date")
    }

    unlinked = []

    # Portfolio positions
    for pos in get_all_positions():
        if pos["id"] in linked_pids:
            continue
        key = (pos["ticker"].upper().strip().replace(".NS", ""), pos["buy_date"])
        key2 = (pos["ticker"].upper().strip(), pos["buy_date"])
        if key in linked_keys or key2 in linked_keys:
            continue
        unlinked.append({
            "source": "portfolio",
            "position_id": pos["id"],
            "ticker": pos["ticker"],
            "date": pos["buy_date"],
            "status": pos["status"],
            "buy_price": pos["buy_price"],
            "sell_price": pos.get("sell_price"),
            "sell_date": pos.get("sell_date"),
            "strategy": pos.get("strategy_code", ""),
            "notes": pos.get("notes", ""),
        })

    # P&L trades
    for tr in get_all_trades():
        tk = tr["stock"].upper().strip()
        key = (tk, tr["buy_date"])
        key2 = (tk.replace(".NS", ""), tr["buy_date"])
        if key in linked_keys or key2 in linked_keys:
            continue
        unlinked.append({
            "source": "trades",
            "trade_id": tr["id"],
            "ticker": tr["stock"],
            "date": tr["buy_date"],
            "status": "CLOSED",
            "buy_price": tr["buy_price"],
            "sell_price": tr["sell_price"],
            "sell_date": tr["sell_date"],
            "strategy": "",
            "notes": tr.get("notes", ""),
        })

    return jsonify({"unlinked": unlinked, "total": len(unlinked)})


@mental_game_bp.route("/api/mental-game/bulk-sync", methods=["POST"])
def api_mg_bulk_sync():
    """Create psychology entries for a list of existing trades."""
    data = request.get_json(force=True)
    items = data.get("items", [])
    if not items:
        return jsonify({"error": "No items provided"}), 400

    created = 0
    for item in items:
        ticker = item.get("ticker", "").upper().strip()
        trade_date = item.get("date", "")
        if not ticker or not trade_date:
            continue
        save_trade_psychology({
            "position_id": item.get("position_id"),
            "trade_date": trade_date,
            "ticker": ticker,
            "pre_emotion": item.get("pre_emotion", "NEUTRAL"),
            "pre_mental_score": int(item.get("pre_mental_score", 7)),
            "system_followed": item.get("system_followed", "YES"),
            "rule_broken": item.get("rule_broken", ""),
            "root_cause": item.get("root_cause", ""),
            "in_trade_emotion": item.get("in_trade_emotion", ""),
            "post_reflection": item.get("post_reflection", ""),
            "pattern_tag": item.get("pattern_tag", ""),
        })
        created += 1

    return jsonify({"status": "ok", "created": created})
