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

import threading

from flask import Blueprint, render_template, jsonify, request
from bb_squeeze.config import CSV_DIR

intraday_bp = Blueprint("intraday", __name__)

# Background backtest runner state
_bt_lock = threading.Lock()
_bt_status = {"running": False, "progress": "", "error": ""}


@intraday_bp.route("/intraday")
def intraday_page():
    return render_template("intraday.html")


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
    from intraday.trader import get_trader_state, get_available_funds, is_daemon_running
    state = get_trader_state()
    state["live_funds"] = get_available_funds()
    state["daemon_running"] = is_daemon_running()
    return jsonify(state)


@intraday_bp.route("/api/intraday/trader/daemon/start", methods=["POST"])
def api_daemon_start():
    """Start trader daemon as background process."""
    import subprocess
    from intraday.trader import is_daemon_running, PID_FILE

    if is_daemon_running():
        pid = int(open(PID_FILE).read().strip())
        return jsonify({"status": "already_running", "pid": pid}), 409

    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "paper").lower()

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

    return jsonify({"status": "started", "pid": proc.pid, "mode": mode.upper()})


@intraday_bp.route("/api/intraday/trader/toggle", methods=["POST"])
def api_trader_toggle():
    from intraday.trader import set_trader_toggle
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled", False))
    state = set_trader_toggle(enabled)
    return jsonify(state)


@intraday_bp.route("/api/intraday/trader/exit-all", methods=["POST"])
def api_trader_exit_all():
    from intraday.trader import get_trader_state, set_trader_toggle
    set_trader_toggle(False)
    state = get_trader_state()
    return jsonify({"message": "Toggle OFF — trader will exit all on next cycle", **state})


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
    """Return 5-min OHLCV data for charting."""
    from intraday.data import fetch_intraday

    if not ticker.endswith(".NS"):
        ticker += ".NS"

    days = min(int(request.args.get("days", "5")), 30)
    df = fetch_intraday(ticker, interval="5m", days=days)

    if df is None:
        return jsonify({"error": f"No intraday data for {ticker}"}), 404

    return jsonify({
        "ticker": ticker,
        "interval": "5m",
        "candles": len(df),
        "timestamp": df.index.strftime("%Y-%m-%d %H:%M").tolist(),
        "open": df["Open"].round(2).tolist(),
        "high": df["High"].round(2).tolist(),
        "low": df["Low"].round(2).tolist(),
        "close": df["Close"].round(2).tolist(),
        "volume": df["Volume"].tolist(),
    })
