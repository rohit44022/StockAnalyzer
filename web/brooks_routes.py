"""
Brooks System — Flask Routes
==============================
Separate blueprint for the Al Brooks top-5 BUY / SELL scanner.
"""

from __future__ import annotations

import sys, os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pandas as pd
from flask import Blueprint, render_template, jsonify, request
from bb_squeeze.config import CSV_DIR
from bb_squeeze.data_loader import load_stock_data

brooks_bp = Blueprint("brooks", __name__)


@brooks_bp.route("/brooks")
def brooks_page():
    return render_template("brooks.html")


@brooks_bp.route("/api/brooks/scan")
def api_brooks_scan():
    """Run full scan and return top-5 BUY + top-5 SELL picks with reasoning."""
    from brooks.analyzer import scan_and_rank

    limit = min(int(request.args.get("limit", "5")), 20)
    workers = min(int(request.args.get("workers", "16")), 20)

    result = scan_and_rank(CSV_DIR, max_workers=workers, limit=limit)
    return jsonify(result)


@brooks_bp.route("/api/brooks/chart/<ticker>")
def api_brooks_chart(ticker: str):
    """Last 120 daily candles + EMA20 for the lightweight-charts overlay."""
    ticker = ticker.strip().upper().replace(" ", "")
    df = load_stock_data(ticker, csv_dir=CSV_DIR, use_live_fallback=False)
    if df is None or len(df) < 30:
        return jsonify({"error": f"No data for {ticker}"}), 404

    df = df.tail(120).copy()
    df["ema20"] = df["Close"].ewm(span=20, adjust=False).mean()

    dates = [d.strftime("%Y-%m-%d") for d in df.index]

    def _s(v):
        return round(float(v), 2) if pd.notna(v) else None

    # ── Compute chart overlays from price structure ──
    import numpy as np
    from brooks.engine import _find_swings, SWING_LB

    o = df["Open"].values.astype(float)
    h = df["High"].values.astype(float)
    l = df["Low"].values.astype(float)
    c = df["Close"].values.astype(float)
    n = len(c)
    sh_idx, sl_idx = _find_swings(h, l, lb=SWING_LB)

    # Swing high / low markers
    swing_highs = [{"time": dates[i], "price": _s(h[i])} for i in sh_idx if 0 <= i < n]
    swing_lows = [{"time": dates[i], "price": _s(l[i])} for i in sl_idx if 0 <= i < n]

    # Trend lines (connect last two swing points, project to current bar)
    def _make_trendline(indices, prices):
        if len(indices) < 2:
            return None
        i1, i2 = int(indices[-2]), int(indices[-1])
        if i2 <= i1 or i1 < 0 or i2 >= n:
            return None
        p1, p2 = float(prices[i1]), float(prices[i2])
        slope = (p2 - p1) / (i2 - i1)
        p_end = p2 + slope * (n - 1 - i2)
        return {
            "start": {"time": dates[i1], "price": _s(p1)},
            "end":   {"time": dates[n - 1], "price": _s(p_end)},
        }

    bull_tl = _make_trendline(sl_idx, l)
    bear_tl = _make_trendline(sh_idx, h)

    # Channel line (parallel to bull TL through highest SH, or bear TL through lowest SL)
    channel_line = None
    if bull_tl and len(sl_idx) >= 2 and len(sh_idx) >= 1:
        i1, i2 = int(sl_idx[-2]), int(sl_idx[-1])
        slope = (l[i2] - l[i1]) / (i2 - i1)
        relevant = sh_idx[(sh_idx >= i1) & (sh_idx < n)]
        if len(relevant):
            anchor = int(relevant[np.argmax(h[relevant])])
            ch_at_anchor = l[i1] + slope * (anchor - i1)
            ch_height = h[anchor] - ch_at_anchor
            p_start = l[i1] + ch_height
            p_end = l[i1] + slope * (n - 1 - i1) + ch_height
            channel_line = {
                "start": {"time": dates[i1], "price": _s(p_start)},
                "end":   {"time": dates[n - 1], "price": _s(p_end)},
            }

    # S/R zones (clustered swing points with 2+ touches)
    sr_levels = []
    all_levels = sorted([float(h[i]) for i in sh_idx if i < n] +
                        [float(l[i]) for i in sl_idx if i < n])
    if all_levels:
        cluster = [all_levels[0]]
        for lev in all_levels[1:]:
            if abs(lev - cluster[-1]) / max(cluster[-1], 1e-10) < 0.015:
                cluster.append(lev)
            else:
                if len(cluster) >= 2:
                    sr_levels.append({"price": _s(np.mean(cluster)), "touches": len(cluster)})
                cluster = [lev]
        if len(cluster) >= 2:
            sr_levels.append({"price": _s(np.mean(cluster)), "touches": len(cluster)})

    # ── Pattern geometry detection ──
    patterns = []

    # Double top (M-top): last 2 swing highs within 2%, max 60 bars apart
    if len(sh_idx) >= 2:
        i1, i2 = int(sh_idx[-2]), int(sh_idx[-1])
        if 0 <= i1 < n and 0 <= i2 < n and (i2 - i1) <= 60:
            h1, h2 = float(h[i1]), float(h[i2])
            if h1 > 0 and abs(h1 - h2) / h1 < 0.02:
                patterns.append({
                    "type": "double_top",
                    "points": [
                        {"time": dates[i1], "price": _s(h1)},
                        {"time": dates[i2], "price": _s(h2)},
                    ],
                })

    # Double bottom (W-bottom): last 2 swing lows within 2%
    if len(sl_idx) >= 2:
        i1, i2 = int(sl_idx[-2]), int(sl_idx[-1])
        if 0 <= i1 < n and 0 <= i2 < n and (i2 - i1) <= 60:
            l1, l2 = float(l[i1]), float(l[i2])
            if l1 > 0 and abs(l1 - l2) / l1 < 0.02:
                patterns.append({
                    "type": "double_bottom",
                    "points": [
                        {"time": dates[i1], "price": _s(l1)},
                        {"time": dates[i2], "price": _s(l2)},
                    ],
                })

    # Wedge / Triangle: converging swing high + low structure
    if len(sh_idx) >= 3 and len(sl_idx) >= 3:
        sh3 = [int(x) for x in sh_idx[-3:] if 0 <= x < n]
        sl3 = [int(x) for x in sl_idx[-3:] if 0 <= x < n]
        if len(sh3) >= 2 and len(sl3) >= 2:
            spread_start = float(h[sh3[0]]) - float(l[sl3[0]])
            spread_end = float(h[sh3[-1]]) - float(l[sl3[-1]])
            if spread_start > 0 and spread_end > 0 and spread_end < spread_start * 0.75:
                h_slope = float(h[sh3[-1]]) - float(h[sh3[0]])
                l_slope = float(l[sl3[-1]]) - float(l[sl3[0]])
                if h_slope < 0 and l_slope > 0:
                    ptype = "symmetric_triangle"
                elif h_slope < 0:
                    ptype = "descending_triangle"
                elif l_slope > 0:
                    ptype = "ascending_triangle"
                else:
                    ptype = "wedge"
                patterns.append({
                    "type": ptype,
                    "upper": [{"time": dates[i], "price": _s(h[i])} for i in sh3],
                    "lower": [{"time": dates[i], "price": _s(l[i])} for i in sl3],
                })

    # Micro channel: last 15 bars, very tight high/low corridor
    if n >= 15:
        seg = 15
        seg_h = h[-seg:]
        seg_l = l[-seg:]
        h_range = float(seg_h.max() - seg_h.min())
        l_range = float(seg_l.max() - seg_l.min())
        mid = float((seg_h.mean() + seg_l.mean()) / 2)
        if mid > 0 and (h_range + l_range) / 2 / mid < 0.04:
            patterns.append({
                "type": "micro_channel",
                "upper": [
                    {"time": dates[n - seg], "price": _s(seg_h.max())},
                    {"time": dates[n - 1], "price": _s(seg_h.max())},
                ],
                "lower": [
                    {"time": dates[n - seg], "price": _s(seg_l.min())},
                    {"time": dates[n - 1], "price": _s(seg_l.min())},
                ],
            })

    return jsonify({
        "ticker": ticker,
        "dates": dates,
        "open":   [_s(v) for v in df["Open"]],
        "high":   [_s(v) for v in df["High"]],
        "low":    [_s(v) for v in df["Low"]],
        "close":  [_s(v) for v in df["Close"]],
        "volume": [int(v) for v in df["Volume"]],
        "ema20":  [_s(v) for v in df["ema20"]],
        "overlays": {
            "swing_highs": swing_highs,
            "swing_lows": swing_lows,
            "bull_trendline": bull_tl,
            "bear_trendline": bear_tl,
            "channel_line": channel_line,
            "sr_zones": sr_levels,
        },
        "patterns": patterns,
    })
