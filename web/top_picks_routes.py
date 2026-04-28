"""
web/top_picks_routes.py — Flask Blueprint for the Top 5 Picks System
════════════════════════════════════════════════════════════════════

ROUTES:
  /api/top-picks/<method>   — Run the Top 5 Picks engine for a given BB method
  /api/top-picks/stream/<method>  — SSE stream for live progress updates

HOW IT WORKS (for non-technical readers):
─────────────────────────────────────────
  1. The frontend sends a request: "Give me top 5 BUY picks for Method II"
  2. This route calls the scan API internally to get all matching stocks
  3. Passes the scan results to the Top Picks engine (top_picks/engine.py)
  4. The engine runs deep analysis on each qualifying stock
  5. Returns the top 5 ranked by composite score

ISOLATION:
  This blueprint is completely self-contained. It doesn't modify
  any existing route or template. It only READS from existing APIs.
"""

import sys
import os
import json
import math
import time
import threading
import queue
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flask import Blueprint, jsonify, request, Response

from bb_squeeze.data_loader import (
    normalise_ticker, load_stock_data, get_all_tickers_from_csv, get_data_freshness,
)
from bb_squeeze.indicators import compute_all_indicators
from bb_squeeze.signals import analyze_signals
from bb_squeeze.strategies import run_all_strategies, strategy_result_to_dict
from bb_squeeze.config import CSV_DIR
from top_picks.engine import find_top_picks
from top_picks.config import DEFAULT_CAPITAL


top_picks_bp = Blueprint("top_picks", __name__)


def _safe_json(obj):
    """Make every value JSON-safe (no NaN/Inf, convert numpy types)."""
    if isinstance(obj, dict):
        return {k: _safe_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
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
# INTERNAL SCAN HELPERS
# ═══════════════════════════════════════════════════════════════
# These recreate the scan logic from app.py but return raw data
# instead of HTTP responses. This avoids calling our own server.

def _signal_dict(sig):
    """Convert a SignalResult to a dictionary (mirrors app.py's _signal_dict)."""
    def _s(v, d=2):
        if v is None:
            return None
        if isinstance(v, float):
            if math.isnan(v) or math.isinf(v):
                return None
            return round(v, d)
        return v

    return {
        "ticker": sig.ticker,
        "phase": sig.phase,
        "current_price": _s(sig.current_price),
        "bbw": _s(sig.bbw, 6),
        "percent_b": _s(sig.percent_b, 4),
        "cmf": _s(sig.cmf, 4),
        "mfi": _s(sig.mfi),
        "volume": _s(sig.volume, 0),
        "vol_sma50": _s(sig.vol_sma50, 0),
        "cond1": sig.cond1_squeeze_on,
        "cond2": sig.cond2_price_above,
        "cond3": sig.cond3_volume_ok,
        "cond4": sig.cond4_cmf_positive,
        "cond5": sig.cond5_mfi_above_50,
        "buy_signal": sig.buy_signal,
        "sell_signal": sig.sell_signal,
        "hold_signal": sig.hold_signal,
        "wait_signal": sig.wait_signal,
        "head_fake": sig.head_fake,
        "exit_sar_flip": sig.exit_sar_flip,
        "exit_lower_band": sig.exit_lower_band_tag,
        "exit_double_neg": sig.exit_double_neg,
        "confidence": sig.confidence,
        "direction_lean": sig.direction_lean,
        "squeeze_days": sig.squeeze_days,
        "stop_loss": _s(sig.stop_loss),
        "summary": sig.summary,
        "action_message": sig.action_message,
        # ── New Book Indicators (Ch.15, 18, 21) ──
        "ii_pct": _s(sig.ii_pct, 4),
        "ad_pct": _s(sig.ad_pct, 4),
        "vwmacd_hist": _s(sig.vwmacd_hist, 4),
        "expansion_up": sig.expansion_up,
        "expansion_down": sig.expansion_down,
        "expansion_end": sig.expansion_end,
        "rsi_norm": _s(sig.rsi_norm, 3),
        "mfi_norm": _s(sig.mfi_norm, 3),
        # ── Method I Short-Side (Ch.16) ──
        "short_signal": sig.short_signal,
        "cond_short_squeeze": sig.cond_short_squeeze,
        "cond_short_price": sig.cond_short_price,
        "cond_short_volume": sig.cond_short_volume,
        "cond_short_ii_neg": sig.cond_short_ii_neg,
        "cond_short_mfi_low": sig.cond_short_mfi_low,
    }


def _run_internal_scan(method: str):
    """
    Run the stock scan internally (no HTTP call).

    Returns the same data format as /api/scan or /api/scan/strategies.
    This is faster and avoids self-referencing HTTP loops.
    """
    tickers = get_all_tickers_from_csv(CSV_DIR)

    if method == "M1":
        # Same logic as /api/scan in app.py
        results = []
        for t in tickers:
            try:
                df = load_stock_data(t, csv_dir=CSV_DIR, use_live_fallback=False)
                if df is None or len(df) < 50:
                    continue
                df = compute_all_indicators(df)
                sig = analyze_signals(t, df)
                if sig.phase in ("INSUFFICIENT_DATA", "ERROR"):
                    continue
                results.append(_signal_dict(sig))
            except Exception:
                continue
        return results
    else:
        # Same logic as /api/scan/strategies in app.py
        results = []
        for t in tickers:
            try:
                df = load_stock_data(t, csv_dir=CSV_DIR, use_live_fallback=False)
                if df is None or len(df) < 50:
                    continue
                df = compute_all_indicators(df)
                sig = analyze_signals(t, df)
                if sig.phase in ("INSUFFICIENT_DATA", "ERROR"):
                    continue
                m1 = _signal_dict(sig)
                strats = run_all_strategies(df)
                strat_dicts = [strategy_result_to_dict(sr) for sr in strats]
                results.append({
                    "ticker": t,
                    "price": m1["current_price"],
                    "m1": m1,
                    "strategies": strat_dicts,
                })
            except Exception:
                continue
        return results


# ═══════════════════════════════════════════════════════════════
# ROUTE: /api/top-picks/stream/<method>
# ═══════════════════════════════════════════════════════════════
# Uses Server-Sent Events (SSE) for live progress updates.
# The frontend connects to this, receives progress updates
# as stocks are analyzed, and finally gets the results.

# Global state for tracking progress per request
_progress_state = {}
_progress_lock = threading.Lock()


@top_picks_bp.route("/api/top-picks/stream/<method>")
def top_picks_stream(method):
    """
    Server-Sent Events stream for Top Picks analysis.

    HOW SSE WORKS (for non-technical readers):
    ──────────────────────────────────────────
      Normal HTTP: You ask → server thinks → you wait → server responds.
      SSE: You connect once → server sends updates as they happen → final result.

      It's like texting someone "how's the analysis going?" and they reply
      every few seconds: "Done 5/80...", "Done 10/80...", "Done 80/80! Here are results."

    QUERY PARAMS:
      method (path)  — M1, M2, M3, M4
      filter (query)  — BUY (default), SELL
      capital (query) — Trading capital (optional, default ₹5,00,000)
    """
    method = method.upper()
    if method not in ("M1", "M2", "M3", "M4"):
        return jsonify({"error": f"Invalid method '{method}'. Use M1, M2, M3, or M4."}), 400

    signal_filter = request.args.get("filter", "BUY").upper()
    if signal_filter not in ("BUY", "SELL"):
        signal_filter = "BUY"

    capital = float(request.args.get("capital", DEFAULT_CAPITAL))

    # Generate a unique request ID for progress tracking
    req_id = f"{method}_{signal_filter}_{time.time()}"
    progress_queue = queue.Queue()

    def _progress_callback(done, total, ticker):
        progress_queue.put({
            "type": "progress",
            "done": done,
            "total": total,
            "ticker": ticker,
            "pct": round(done / total * 100) if total > 0 else 0,
        })

    def _run_analysis():
        """Background thread that runs scan + analysis."""
        try:
            # Phase 1: Scanning
            progress_queue.put({
                "type": "phase",
                "phase": "scanning",
                "message": f"Scanning all stocks with {method}..."
            })

            scan_data = _run_internal_scan(method)

            progress_queue.put({
                "type": "phase",
                "phase": "analyzing",
                "message": f"Found {len(scan_data)} stocks. Running deep analysis...",
                "total_scanned": len(scan_data),
            })

            # Phase 2: Deep analysis + scoring
            result = find_top_picks(
                scan_results=scan_data,
                method=method,
                signal_filter=signal_filter,
                capital=capital,
                progress_callback=_progress_callback,
            )

            # Phase 3: Done
            progress_queue.put({
                "type": "result",
                "data": _safe_json(result),
            })
        except Exception as e:
            progress_queue.put({
                "type": "error",
                "message": str(e),
            })

    # Start analysis in background thread
    thread = threading.Thread(target=_run_analysis, daemon=True)
    thread.start()

    def _generate():
        """SSE event generator."""
        while True:
            try:
                msg = progress_queue.get(timeout=120)  # 2-minute timeout
            except queue.Empty:
                yield "data: {\"type\":\"error\",\"message\":\"Analysis timed out after 2 minutes\"}\n\n"
                break

            yield f"data: {json.dumps(msg)}\n\n"

            if msg.get("type") in ("result", "error"):
                break

    return Response(
        _generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ═══════════════════════════════════════════════════════════════
# ROUTE: /api/top-picks/<method> (non-streaming, simpler)
# ═══════════════════════════════════════════════════════════════

@top_picks_bp.route("/api/top-picks/<method>")
def top_picks_api(method):
    """
    Non-streaming Top Picks endpoint — returns all results at once.
    Use this for programmatic access or testing.
    The streaming endpoint is preferred for the UI (better UX).
    """
    method = method.upper()
    if method not in ("M1", "M2", "M3", "M4"):
        return jsonify({"error": f"Invalid method '{method}'. Use M1, M2, M3, or M4."}), 400

    signal_filter = request.args.get("filter", "BUY").upper()
    if signal_filter not in ("BUY", "SELL"):
        signal_filter = "BUY"
    capital = float(request.args.get("capital", DEFAULT_CAPITAL))

    scan_data = _run_internal_scan(method)

    result = find_top_picks(
        scan_results=scan_data,
        method=method,
        signal_filter=signal_filter,
        capital=capital,
    )

    return jsonify(_safe_json(result))


# ═══════════════════════════════════════════════════════════════
# ROUTE: /api/top-picks/<method>/export/xlsx — Excel download
# ═══════════════════════════════════════════════════════════════

@top_picks_bp.route("/api/top-picks/<method>/export/xlsx")
def top_picks_export_xlsx(method):
    """
    Download the Top 5 picks for a given method+filter as a colour-coded
    Excel workbook.

    Same scan + analysis pipeline as the streaming/non-streaming endpoints —
    just rendered to .xlsx instead of JSON. Idempotent.

    Query params:
      filter:  BUY (default) | SELL
      capital: optional float, defaults to DEFAULT_CAPITAL
    """
    from datetime import date as _date
    from web.excel_top_picks import build_top_picks_xlsx

    method = method.upper()
    if method not in ("M1", "M2", "M3", "M4"):
        return jsonify({"error": f"Invalid method '{method}'. Use M1, M2, M3, or M4."}), 400

    signal_filter = (request.args.get("filter", "BUY") or "BUY").upper()
    if signal_filter not in ("BUY", "SELL"):
        signal_filter = "BUY"
    try:
        capital = float(request.args.get("capital", DEFAULT_CAPITAL))
    except (TypeError, ValueError):
        capital = DEFAULT_CAPITAL

    scan_data = _run_internal_scan(method)
    result = find_top_picks(
        scan_results=scan_data,
        method=method,
        signal_filter=signal_filter,
        capital=capital,
    )
    safe = _safe_json(result)

    try:
        xlsx_bytes = build_top_picks_xlsx(safe, method=method, signal_filter=signal_filter)
    except Exception as ex:
        return jsonify({"error": f"Excel build failed: {ex}"}), 500

    filename = f"Hiranya_Top5_{signal_filter}_{method}_{_date.today().isoformat()}.xlsx"
    return Response(
        xlsx_bytes,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
