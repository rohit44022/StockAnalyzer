"""
Intraday Trading — Flask Routes
================================
Blueprint for Brooks-based intraday scanner.
"""

from __future__ import annotations

import sys, os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import json
import re
import threading
import time as _time

from flask import Blueprint, render_template, jsonify, request, Response
from bb_squeeze.config import CSV_DIR

intraday_bp = Blueprint("intraday", __name__)

_ENV_PATH = os.path.join(_ROOT, ".env")
_TOKEN_VALIDITY_HOURS = 24

# Background backtest runner state
_bt_lock = threading.Lock()
_bt_status = {"running": False, "progress": "", "error": ""}


@intraday_bp.route("/intraday")
def intraday_page():
    return render_template("intraday.html")


# ── Dhan Token Management ──────────────────────────────────

def _read_env_var(key):
    """Read a single var from .env without loading into os.environ."""
    if not os.path.exists(_ENV_PATH):
        return None
    with open(_ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    return None


def _write_env_var(key, value):
    """Update or insert a single var in .env, preserving everything else."""
    lines = []
    found = False
    if os.path.exists(_ENV_PATH):
        with open(_ENV_PATH) as f:
            lines = f.readlines()
    new_lines = []
    for line in lines:
        if line.strip().startswith(f"{key}="):
            new_lines.append(f"{key}={value}\n")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={value}\n")
    with open(_ENV_PATH, "w") as f:
        f.writelines(new_lines)


def _token_saved_at():
    """Return timestamp when .env was last modified (proxy for token save time)."""
    if not os.path.exists(_ENV_PATH):
        return None
    return os.path.getmtime(_ENV_PATH)


@intraday_bp.route("/api/intraday/token", methods=["GET"])
def api_get_token():
    from datetime import datetime, timedelta
    client_id = _read_env_var("DHAN_CLIENT_ID") or ""
    token = _read_env_var("DHAN_ACCESS_TOKEN") or ""
    saved_at = _token_saved_at()

    if not token:
        return jsonify({"status": "missing", "client_id": client_id,
                        "token_masked": "", "hours_left": 0, "saved_at": ""})

    masked = token[:12] + "…" + token[-8:] if len(token) > 24 else token[:6] + "…"
    hours_left = 0
    status = "expired"
    saved_at_str = ""
    if saved_at:
        saved_dt = datetime.fromtimestamp(saved_at)
        saved_at_str = saved_dt.strftime("%Y-%m-%d %H:%M")
        expires_dt = saved_dt + timedelta(hours=_TOKEN_VALIDITY_HOURS)
        remaining = (expires_dt - datetime.now()).total_seconds()
        if remaining > 0:
            hours_left = round(remaining / 3600, 1)
            status = "valid"

    return jsonify({"status": status, "client_id": client_id,
                    "token_masked": masked, "hours_left": hours_left,
                    "saved_at": saved_at_str})


@intraday_bp.route("/api/intraday/token", methods=["POST"])
def api_save_token():
    data = request.get_json(force=True)
    token = (data.get("token") or "").strip()
    client_id = (data.get("client_id") or "").strip()

    if not token:
        return jsonify({"ok": False, "error": "Token is required"}), 400
    if not re.match(r'^[A-Za-z0-9._\-]+$', token):
        return jsonify({"ok": False, "error": "Token contains invalid characters"}), 400

    if client_id:
        _write_env_var("DHAN_CLIENT_ID", client_id)
    _write_env_var("DHAN_ACCESS_TOKEN", token)

    # Reload into current process so the daemon picks it up
    from dotenv import load_dotenv
    load_dotenv(_ENV_PATH, override=True)

    return jsonify({"ok": True, "message": "Token saved — valid for 24 hours"})


@intraday_bp.route("/api/intraday/scan")
def api_intraday_scan():
    """Run intraday scan on watchlist or auto-detected bearish stocks."""
    from intraday.scanner import scan_intraday

    watchlist_raw = request.args.get("watchlist", "")
    top_n = min(int(request.args.get("limit", "10")), 20)

    watchlist = None
    if watchlist_raw:
        watchlist = [t.strip().upper() for t in watchlist_raw.split(",") if t.strip()]
        watchlist = [t if t.endswith(".NS") else t + ".NS" for t in watchlist]

    result = scan_intraday(watchlist=watchlist, csv_dir=CSV_DIR, top_n=top_n)
    return jsonify(result)


@intraday_bp.route("/api/intraday/trader/status")
def api_trader_status():
    from datetime import datetime
    from intraday.trader import get_trader_state, get_available_funds, is_daemon_running
    state = get_trader_state()
    # Reset stale state from previous day
    today = datetime.now().strftime("%Y-%m-%d")
    if state.get("date") and state["date"] != today:
        state["leverage"] = 1.0
        state["daily_pnl"] = 0
        state["circuit_breaker"] = False
        state["kill_switch"] = False
        state["positions"] = []
        state["closed_today"] = []
    state["live_funds"] = get_available_funds()
    state["daemon_running"] = is_daemon_running()
    return jsonify(state)


@intraday_bp.route("/api/intraday/index-ltp")
def api_index_ltp():
    """Nifty 500 index LTP via Dhan marketfeed."""
    try:
        from intraday.data import _load_dhan_context
        from dhanhq._market_feed import MarketFeed as MF
        ctx, ok = _load_dhan_context()
        if not ok:
            return jsonify({"error": "Dhan not configured"}), 503
        mf = MF(ctx)
        resp = mf.ticker_data(securities={"IDX_I": [19]})
        if resp.get("status") == "success":
            d = resp["data"].get("IDX_I:19", resp["data"].get("19", {}))
            return jsonify({"ltp": d.get("last_price", 0), "ok": True})
        return jsonify({"error": "no data", "ok": False}), 502
    except Exception as e:
        return jsonify({"error": str(e), "ok": False}), 500


@intraday_bp.route("/api/intraday/trader/leverage", methods=["GET", "POST"])
def api_trader_leverage():
    from intraday.trader import get_trader_state, set_leverage
    if request.method == "GET":
        state = get_trader_state()
        return jsonify({"leverage": state.get("leverage", 1.0)})
    data = request.get_json(force=True)
    mult = float(data.get("leverage", 1.0))
    state = set_leverage(mult)
    return jsonify({"ok": True, "leverage": state.get("leverage", 1.0)})


@intraday_bp.route("/api/intraday/trader/daemon/start", methods=["POST"])
def api_daemon_start():
    """Start trader daemon, killing any existing one first."""
    import signal, subprocess
    from intraday.trader import is_daemon_running, PID_FILE

    if is_daemon_running():
        old_pid = int(open(PID_FILE).read().strip())
        try:
            os.kill(old_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            os.remove(PID_FILE)
        except OSError:
            pass
        import time as _t
        _t.sleep(1)

    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "live").lower()

    # Write mode + PID hint to state file immediately so UI reads correct state
    from intraday.trader import get_trader_state, STATE_FILE
    import json as _json
    state = get_trader_state()
    state["mode"] = mode.upper()
    with open(STATE_FILE, "w") as f:
        _json.dump(state, f, indent=2)

    python = os.path.join(_ROOT, ".venv", "bin", "python")
    cmd = [python, "-m", "intraday.trader"]
    if mode == "live":
        cmd.append("--live")

    log_path = os.path.join(_ROOT, "intraday", "trader.log")
    proc = subprocess.Popen(
        cmd, cwd=_ROOT,
        stdout=open(log_path, "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    # Write PID file immediately so is_daemon_running() returns True
    from intraday.trader import PID_FILE
    with open(PID_FILE, "w") as f:
        f.write(str(proc.pid))

    return jsonify({"status": "started", "pid": proc.pid, "mode": mode.upper()})


@intraday_bp.route("/api/intraday/trader/daemon/stop", methods=["POST"])
def api_daemon_stop():
    """Stop trader daemon by sending SIGTERM."""
    import signal
    from intraday.trader import is_daemon_running, PID_FILE

    if not is_daemon_running():
        return jsonify({"status": "not_running"})

    pid = int(open(PID_FILE).read().strip())
    os.kill(pid, signal.SIGTERM)
    import time as _t
    _t.sleep(0.5)  # let SIGTERM handler save state
    try:
        os.remove(PID_FILE)
    except OSError:
        pass
    # Ensure enabled=false sticks — daemon's SIGTERM handler may have overwritten it
    from intraday.trader import get_trader_state, STATE_FILE
    import json as _json
    state = get_trader_state()
    state["enabled"] = False
    with open(STATE_FILE, "w") as f:
        _json.dump(state, f, indent=2)
    return jsonify({"status": "stopped", "pid": pid})


@intraday_bp.route("/api/intraday/trader/toggle", methods=["POST"])
def api_trader_toggle():
    from intraday.trader import set_trader_toggle
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled", False))
    state = set_trader_toggle(enabled)
    return jsonify(state)


@intraday_bp.route("/api/intraday/trader/exit-all", methods=["POST"])
def api_trader_exit_all():
    from intraday.trader import get_trader_state, set_trader_toggle, exit_all_positions
    set_trader_toggle(False)
    closed = exit_all_positions()
    state = get_trader_state()
    return jsonify({"message": f"Exited {closed} positions", **state})


@intraday_bp.route("/api/intraday/trader/scan-feed")
def api_scan_feed():
    from intraday.trader import get_trader_state
    state = get_trader_state()
    return jsonify({
        "feed": state.get("scan_feed", []),
        "stats": state.get("scan_stats", {}),
    })


@intraday_bp.route("/api/intraday/connection-status")
def api_connection_status():
    """Check Dhan API connectivity, IP, and token status."""
    import requests as _req
    from dotenv import load_dotenv
    load_dotenv(_ENV_PATH, override=True)

    result = {"machine_ip": None, "dhan_funds": None, "dhan_orders": None,
              "token_status": None, "client_id": None}

    # 1. Our public IP
    try:
        result["machine_ip"] = _req.get("https://api.ipify.org", timeout=5).text.strip()
    except Exception:
        result["machine_ip"] = "unknown"

    # 2. Token info
    client_id = os.environ.get("DHAN_CLIENT_ID", "")
    token = os.environ.get("DHAN_ACCESS_TOKEN", "")
    result["client_id"] = client_id
    result["token_present"] = bool(token)
    result["token_masked"] = (token[:12] + "…" + token[-8:]) if len(token) > 24 else "too short"

    if not token or not client_id:
        result["token_status"] = "missing"
        return jsonify(result)

    # 3. Test Funds API (data read)
    try:
        from dhanhq import DhanContext, Funds
        ctx = DhanContext(client_id, token)
        resp = Funds(ctx).get_fund_limits()
        if resp.get("status") == "success":
            bal = resp.get("data", {}).get("availabelBalance", 0)
            result["dhan_funds"] = {"status": "connected", "balance": bal}
        else:
            result["dhan_funds"] = {"status": "failed", "error": str(resp.get("remarks", resp))}
    except Exception as e:
        result["dhan_funds"] = {"status": "error", "error": str(e)}

    # 4. Test Orders API (trading read)
    try:
        from dhanhq import DhanHTTP
        http = DhanHTTP(client_id, token)
        resp = http.get("/orders")
        if resp.get("status") == "success":
            result["dhan_orders"] = {"status": "connected", "today_orders": len(resp.get("data", []))}
        else:
            err = resp.get("remarks", {})
            if isinstance(err, dict):
                result["dhan_orders"] = {"status": "failed", "error_code": err.get("error_code", ""),
                                         "error": err.get("error_message", str(err))}
            else:
                result["dhan_orders"] = {"status": "failed", "error": str(err)}
    except Exception as e:
        result["dhan_orders"] = {"status": "error", "error": str(e)}

    # Overall
    funds_ok = result["dhan_funds"] and result["dhan_funds"]["status"] == "connected"
    orders_ok = result["dhan_orders"] and result["dhan_orders"]["status"] == "connected"
    result["token_status"] = "valid" if (funds_ok and orders_ok) else "partial" if funds_ok else "invalid"

    return jsonify(result)


@intraday_bp.route("/api/intraday/trader/live-log")
def api_live_log():
    """Tail the raw trader.log file."""
    n = min(int(request.args.get("n", "50")), 200)
    log_path = os.path.join(_ROOT, "intraday", "trader.log")
    if not os.path.exists(log_path):
        return jsonify({"lines": []})
    with open(log_path) as f:
        lines = f.readlines()
    return jsonify({"lines": [l.rstrip() for l in lines[-n:]]})


@intraday_bp.route("/api/intraday/trader/log")
def api_trader_log():
    from intraday.trader import get_trade_log
    n = min(int(request.args.get("n", "20")), 100)
    return jsonify(get_trade_log(n))


@intraday_bp.route("/api/intraday/trades")
def api_intraday_trades():
    """All auto-traded intraday positions (closed) with charges."""
    from intraday.trader import get_trade_log
    n = min(int(request.args.get("n", "200")), 500)
    raw = get_trade_log(n)
    trades = [t for t in raw if t.get("action") == "CLOSE"]
    return jsonify(trades)


@intraday_bp.route("/intraday/backtest")
def intraday_backtest_page():
    return render_template("intraday_backtest.html")


@intraday_bp.route("/api/intraday/backtest")
def api_intraday_backtest():
    from intraday.backtest import get_backtest_results
    data = get_backtest_results()
    if not data:
        return jsonify({"error": "No backtest results. Run: .venv/bin/python -m intraday.backtest"}), 404
    return jsonify(data)


@intraday_bp.route("/api/intraday/backtest/run", methods=["POST"])
def api_backtest_run():
    """Kick off backtest in background thread."""
    with _bt_lock:
        if _bt_status["running"]:
            return jsonify({"status": "already_running", "progress": _bt_status["progress"]}), 409

    data = request.get_json(silent=True) or {}
    capital = float(data.get("capital", 100000))
    start = data.get("start", "2020-01-01")
    end = data.get("end", None)
    download_5min = bool(data.get("download_5min", False))

    def _run():
        with _bt_lock:
            _bt_status["running"] = True
            _bt_status["progress"] = "Starting…"
            _bt_status["error"] = ""
        try:
            if download_5min:
                with _bt_lock:
                    _bt_status["progress"] = "Downloading 5-min data…"
                from intraday.datastore import download_all
                download_all()

            with _bt_lock:
                _bt_status["progress"] = "Running backtest…"
            from intraday.backtest import run_backtest, print_report, save_results
            result = run_backtest(start_date=start, end_date=end, capital=capital)
            print_report(result)
            save_results(result)
            with _bt_lock:
                _bt_status["progress"] = "Done"
        except Exception as e:
            with _bt_lock:
                _bt_status["error"] = str(e)
                _bt_status["progress"] = "Failed"
        finally:
            with _bt_lock:
                _bt_status["running"] = False

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"status": "started"})


@intraday_bp.route("/api/intraday/backtest/status")
def api_backtest_status():
    with _bt_lock:
        return jsonify(dict(_bt_status))


@intraday_bp.route("/api/intraday/backtest/chart")
def api_backtest_chart():
    """Return OHLCV candles + pattern annotations around a trade date."""
    ticker = request.args.get("ticker", "")
    date = request.args.get("date", "")
    if not ticker or not date:
        return jsonify({"error": "ticker and date required"}), 400

    import pandas as pd
    import numpy as np
    from intraday.backtest import _load_daily

    df = _load_daily(ticker)
    if df.empty:
        return jsonify({"error": f"No data for {ticker}"}), 404

    trade_date = pd.Timestamp(date)
    if trade_date not in df.index:
        loc = df.index.searchsorted(trade_date)
        if loc >= len(df.index):
            loc = len(df.index) - 1
    else:
        loc = df.index.get_loc(trade_date)
        if isinstance(loc, slice):
            loc = loc.start

    # 25 bars before trade + trade day + 5 after = ~31 candles
    start = max(0, loc - 25)
    end = min(len(df), loc + 6)
    window = df.iloc[start:end]

    # Pattern detection on each bar
    o = window["Open"].values.astype(float)
    h = window["High"].values.astype(float)
    l = window["Low"].values.astype(float)
    c = window["Close"].values.astype(float)
    v = window["Volume"].values.astype(float)
    n = len(window)

    avg_range = float(np.mean(h - l)) if n > 1 else 1.0
    avg_body = float(np.mean(np.abs(c - o))) if n > 1 else 1.0

    candles = []
    for i in range(n):
        bar_range = h[i] - l[i]
        body = abs(c[i] - o[i])
        patterns = []

        if i > 0:
            if h[i] < h[i-1] and l[i] > l[i-1]:
                patterns.append("IB")
            if h[i] > h[i-1] and l[i] < l[i-1]:
                patterns.append("OB")

        if bar_range > 0:
            body_pct = body / bar_range
            if body_pct < 0.2:
                patterns.append("DOJI")
            elif body_pct > 0.6 and bar_range > avg_range * 1.3:
                if c[i] > o[i]:
                    patterns.append("TREND_UP")
                else:
                    patterns.append("TREND_DOWN")

        # Two-bar reversal
        if i > 0:
            if c[i-1] < o[i-1] and c[i] > o[i] and c[i] > h[i-1]:
                patterns.append("BULL_REV")
            if c[i-1] > o[i-1] and c[i] < o[i] and c[i] < l[i-1]:
                patterns.append("BEAR_REV")

        # Signal bar (trade date)
        bar_date = window.index[i].strftime("%Y-%m-%d")
        if bar_date == date:
            patterns.append("SIGNAL")

        candles.append({
            "time": bar_date,
            "open": round(float(o[i]), 2),
            "high": round(float(h[i]), 2),
            "low": round(float(l[i]), 2),
            "close": round(float(c[i]), 2),
            "volume": int(v[i]),
            "patterns": patterns,
        })

    return jsonify({"ticker": ticker, "date": date, "candles": candles})


@intraday_bp.route("/api/intraday/chart/<ticker>")
def api_intraday_chart(ticker):
    """Return 5-min OHLCV as lightweight-charts array."""
    from intraday.data import fetch_intraday

    if not ticker.endswith(".NS"):
        ticker += ".NS"

    days = min(int(request.args.get("days", "5")), 30)
    df = fetch_intraday(ticker, interval="5m", days=days)

    if df is None:
        return jsonify([])

    candles = []
    for ts, row in df.iterrows():
        candles.append({
            "time": int(ts.timestamp()),
            "open": round(row["Open"], 2),
            "high": round(row["High"], 2),
            "low": round(row["Low"], 2),
            "close": round(row["Close"], 2),
            "volume": int(row["Volume"]),
        })
    return jsonify(candles)


@intraday_bp.route("/api/intraday/trader/ws-status")
def api_ws_status():
    """WebSocket connection status + kill switch + registered IP."""
    from intraday.trader import get_ws_status
    return jsonify(get_ws_status())


@intraday_bp.route("/api/intraday/trader/kill-switch", methods=["POST"])
def api_kill_switch():
    """Manual emergency kill switch — squares off all + blocks new orders."""
    from intraday.trader import activate_kill_switch, get_status
    state = get_status()
    if state.get("positions"):
        from intraday.trader import AutoTrader
        # Exit all open positions first
        # (handled by the daemon if running, but direct call as safety net)
    ok = activate_kill_switch()
    return jsonify({"activated": ok})


@intraday_bp.route("/api/intraday/trader/trade-book")
def api_trade_book():
    """Today's broker-confirmed trades from Dhan Statement API."""
    from intraday.trader import get_trade_book
    return jsonify({"trades": get_trade_book()})


@intraday_bp.route("/api/intraday/broker/orders")
def api_broker_orders():
    """Live order book from Dhan."""
    from intraday.trader import _load_dhan_context
    ctx, ok = _load_dhan_context()
    if not ok:
        return jsonify({"orders": [], "error": "No credentials"})
    try:
        resp = ctx.dhan_http.get('/orders')
        if resp.get("status") == "success":
            return jsonify({"orders": resp.get("data", [])})
        return jsonify({"orders": [], "error": str(resp.get("remarks", ""))})
    except Exception as e:
        return jsonify({"orders": [], "error": str(e)})


@intraday_bp.route("/api/intraday/broker/positions")
def api_broker_positions():
    """Live positions from Dhan, enriched with LTP for open positions."""
    from intraday.trader import _load_dhan_context
    ctx, ok = _load_dhan_context()
    if not ok:
        return jsonify({"positions": [], "error": "No credentials"})
    try:
        from dhanhq import Portfolio
        resp = Portfolio(ctx).get_positions()
        if resp.get("status") != "success":
            return jsonify({"positions": [], "error": str(resp.get("remarks", ""))})
        positions = resp.get("data", [])
        # Fetch LTP for open intraday positions
        open_sids = {}
        for p in positions:
            if p.get("productType") == "INTRADAY" and abs(p.get("netQty", 0)) > 0:
                seg = p.get("exchangeSegment", "NSE_EQ")
                sid = p.get("securityId")
                if sid:
                    open_sids.setdefault(seg, []).append(int(sid))
        if open_sids:
            try:
                ltp_resp = ctx.dhan_http.post("/marketfeed/ltp", open_sids)
                ltp_data = ltp_resp.get("data", {}) if isinstance(ltp_resp, dict) else {}
                for p in positions:
                    sid = str(p.get("securityId", ""))
                    seg = p.get("exchangeSegment", "")
                    ltp_val = ltp_data.get(seg, {}).get(sid, {})
                    if isinstance(ltp_val, dict):
                        p["lastPrice"] = ltp_val.get("last_price", 0)
                    elif isinstance(ltp_val, (int, float)):
                        p["lastPrice"] = ltp_val
            except Exception:
                pass
        return jsonify({"positions": positions})
    except Exception as e:
        return jsonify({"positions": [], "error": str(e)})


@intraday_bp.route("/api/intraday/broker/funds")
def api_broker_funds():
    """Detailed fund limits from Dhan."""
    from intraday.trader import _load_dhan_context
    ctx, ok = _load_dhan_context()
    if not ok:
        return jsonify({"error": "No credentials"})
    try:
        from dhanhq import Funds
        resp = Funds(ctx).get_fund_limits()
        if resp.get("status") == "success":
            return jsonify(resp.get("data", {}))
        return jsonify({"error": str(resp.get("remarks", ""))})
    except Exception as e:
        return jsonify({"error": str(e)})


@intraday_bp.route("/api/intraday/trader/trade-history")
def api_trade_history():
    """Broker trade history for a date range."""
    from intraday.trader import get_trade_history
    from_date = request.args.get("from", "")
    to_date = request.args.get("to", "")
    if not from_date or not to_date:
        return jsonify({"error": "from and to params required"}), 400
    page = int(request.args.get("page", "0"))
    return jsonify({"trades": get_trade_history(from_date, to_date, page)})


# ── SSE Real-Time Stream ─────────────────────────────────────

_broker_snap_cache = {"data": None, "ts": 0, "fetching": False}
_broker_snap_lock = threading.Lock()
_BROKER_SNAP_TTL = 1


def _fetch_positions(ctx):
    try:
        from dhanhq import Portfolio
        resp = Portfolio(ctx).get_positions()
        if resp.get("status") != "success":
            return []
        positions = resp.get("data", [])
        open_sids = {}
        for p in positions:
            if p.get("productType") == "INTRADAY" and abs(p.get("netQty", 0)) > 0:
                seg = p.get("exchangeSegment", "NSE_EQ")
                sid = p.get("securityId")
                if sid:
                    open_sids.setdefault(seg, []).append(int(sid))
        if open_sids:
            try:
                ltp_resp = ctx.dhan_http.post("/marketfeed/ltp", open_sids)
                ltp_data = ltp_resp.get("data", {}) if isinstance(ltp_resp, dict) else {}
                for p in positions:
                    sid = str(p.get("securityId", ""))
                    seg = p.get("exchangeSegment", "")
                    ltp_val = ltp_data.get(seg, {}).get(sid, {})
                    if isinstance(ltp_val, dict):
                        p["lastPrice"] = ltp_val.get("last_price", 0)
                    elif isinstance(ltp_val, (int, float)):
                        p["lastPrice"] = ltp_val
            except Exception:
                pass
        return positions
    except Exception:
        return []


def _fetch_funds(ctx):
    try:
        from dhanhq import Funds
        resp = Funds(ctx).get_fund_limits()
        return resp.get("data", {}) if resp.get("status") == "success" else {}
    except Exception:
        return {}


def _fetch_orders(ctx):
    try:
        resp = ctx.dhan_http.get('/orders')
        return resp.get("data", []) if resp.get("status") == "success" else []
    except Exception:
        return []


def _get_broker_snapshot():
    """Fetch positions+funds+orders from Dhan in parallel, cached across SSE clients."""
    with _broker_snap_lock:
        if _broker_snap_cache["data"] and _time.time() - _broker_snap_cache["ts"] < _BROKER_SNAP_TTL:
            return _broker_snap_cache["data"]
        if _broker_snap_cache["fetching"]:
            return _broker_snap_cache["data"] or {"positions": [], "funds": {}, "orders": []}
        _broker_snap_cache["fetching"] = True

    try:
        from intraday.data import _load_dhan_context
        from concurrent.futures import ThreadPoolExecutor
        ctx, ok = _load_dhan_context()
        if not ok:
            return {"positions": [], "funds": {}, "orders": []}

        with ThreadPoolExecutor(max_workers=3) as ex:
            fp = ex.submit(_fetch_positions, ctx)
            ff = ex.submit(_fetch_funds, ctx)
            fo = ex.submit(_fetch_orders, ctx)

        result = {"positions": fp.result(), "funds": ff.result(), "orders": fo.result()}

        with _broker_snap_lock:
            _broker_snap_cache["data"] = result
            _broker_snap_cache["ts"] = _time.time()

        return result
    finally:
        with _broker_snap_lock:
            _broker_snap_cache["fetching"] = False


@intraday_bp.route("/api/intraday/stream")
def api_intraday_stream():
    """SSE endpoint — pushes trader state (1s) + broker data (2s) to browser."""
    from flask import g
    if not getattr(g, "user", None):
        return jsonify({"code": 401, "error": "Authentication required"}), 401
    from intraday.trader import get_trader_state, STATE_FILE
    from intraday.event_bus import read_new

    def _json(obj):
        return json.dumps(obj, default=str, separators=(",", ":"))

    def generate():
        last_seq = 0
        last_state_mtime = 0
        last_broker_ts = 0
        BROKER_INTERVAL = 2
        LOG_INTERVAL = 2
        last_log_ts = 0
        ev_byte_offset = 0

        # Initial full state
        try:
            state = get_trader_state()
            yield f"event: state\ndata: {_json(state)}\n\n"
        except Exception:
            pass

        while True:
            try:
                # Discrete events from daemon
                events, ev_byte_offset = read_new(after_seq=last_seq, byte_offset=ev_byte_offset)
                for ev in events:
                    yield f"event: {ev['type']}\ndata: {_json(ev)}\n\n"
                    last_seq = ev.get("seq", last_seq)

                # State file changes (daemon writes every 1s)
                try:
                    mtime = os.path.getmtime(STATE_FILE)
                except OSError:
                    mtime = 0
                if mtime > last_state_mtime:
                    try:
                        state = get_trader_state()
                        yield f"event: state\ndata: {_json(state)}\n\n"
                    except Exception:
                        pass
                    last_state_mtime = mtime

                # Broker REST data (every 5s)
                if _time.time() - last_broker_ts > BROKER_INTERVAL:
                    try:
                        broker = _get_broker_snapshot()
                        yield f"event: broker\ndata: {_json(broker)}\n\n"
                    except Exception:
                        pass
                    last_broker_ts = _time.time()

                # Log tail (every 5s)
                if _time.time() - last_log_ts > LOG_INTERVAL:
                    try:
                        log_path = os.path.join(_ROOT, "intraday", "trader.log")
                        if os.path.exists(log_path):
                            with open(log_path, "rb") as f:
                                try:
                                    f.seek(-16384, 2)
                                except OSError:
                                    f.seek(0)
                                tail = f.read().decode("utf-8", errors="replace").splitlines()
                            yield f"event: log\ndata: {_json({'lines': tail[-100:]})}\n\n"
                    except Exception:
                        pass
                    last_log_ts = _time.time()

                _time.sleep(0.5)

            except GeneratorExit:
                return

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
