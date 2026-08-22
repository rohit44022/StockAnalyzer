"""
Builds the 4 layman-friendly "regime" cards shown on /analyze and
on the portfolio position-analysis panel.

Cards produced:
  1. Trend Strength (ADX 14)
  2. Volatility Squeeze (Bollinger inside Keltner)
  3. Daily Volatility (ATR 14) + suggested stops
  4. Smart Money Flow (OBV)

All values are plucked from an already-computed run_triple_analysis()
result — this module does NO indicator math, so it can never drift
from the engine's own numbers.

Output contract (JSON-safe, stable):
    {
      "trend": {...}, "squeeze": {...},
      "volatility": {...}, "money_flow": {...}
    }

Each card dict has: {title, verdict, verdict_color, big_number, subline,
plain_english, action, rows[]}. Frontend just renders — no logic there.
"""
from __future__ import annotations

from typing import Any, Optional


# ─────────────────────────────────────────────────────────────────────
#  Small helpers — never crash on missing fields
# ─────────────────────────────────────────────────────────────────────

def _num(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        v = float(x)
        # NaN check
        if v != v:
            return None
        return v
    except (TypeError, ValueError):
        return None


def _fmt_inr(v: Optional[float], decimals: int = 2) -> str:
    if v is None:
        return "—"
    return f"₹{v:,.{decimals}f}"


def _fmt_pct(v: Optional[float], decimals: int = 2) -> str:
    if v is None:
        return "—"
    return f"{v:.{decimals}f}%"


def _fmt_num(v: Optional[float], decimals: int = 2) -> str:
    if v is None:
        return "—"
    return f"{v:.{decimals}f}"


# ─────────────────────────────────────────────────────────────────────
#  Card 1 — Trend Strength (ADX)
# ─────────────────────────────────────────────────────────────────────

def _trend_card(snap: dict) -> dict:
    adx = _num(snap.get("adx"))
    pdi = _num(snap.get("plus_di"))
    ndi = _num(snap.get("minus_di"))

    if adx is None:
        return {
            "title": "Trend Strength (ADX 14)",
            "verdict": "N/A", "verdict_color": "gray",
            "big_number": "—", "subline": "Not enough data",
            "plain_english": "ADX needs at least 14 trading bars to compute.",
            "action": "Check back once more data is available.",
            "rows": [],
        }

    if adx < 20:
        verdict, color = "RANGING", "yellow"
        action = ("Trend meter is quiet — the stock is drifting sideways. "
                  "This is the ideal environment for mean-reversion: buy near "
                  "the lower Bollinger Band, sell near the upper band. Do NOT "
                  "chase breakouts here — they usually fail.")
    elif adx < 25:
        verdict, color = "BUILDING", "blue"
        action = ("A trend is forming but not confirmed. Wait for ADX to "
                  "cross above 25 before committing to a directional trade.")
    elif adx < 40:
        verdict, color = "TRENDING", "green"
        direction = "UP" if pdi is not None and ndi is not None and pdi > ndi else \
                    "DOWN" if pdi is not None and ndi is not None else "?"
        action = (f"A confirmed {direction} trend is running. When Bollinger "
                  f"says 'price is near the band', RIDE it — don't fade it. "
                  f"Trailing stops beat fixed targets in this regime.")
    else:
        verdict, color = "EXHAUSTED", "orange"
        action = ("Trend is unusually strong (ADX > 40) and may be stretched. "
                  "Fine to hold existing positions with a tightening stop, "
                  "but new entries this late carry higher reversal risk.")

    direction_text = "—"
    if pdi is not None and ndi is not None:
        if pdi > ndi:
            direction_text = f"UP (+DI {pdi:.1f} beats -DI {ndi:.1f})"
        elif ndi > pdi:
            direction_text = f"DOWN (-DI {ndi:.1f} beats +DI {pdi:.1f})"
        else:
            direction_text = "Balanced (+DI = -DI)"

    return {
        "title": "Trend Strength (ADX 14)",
        "icon": "bi-graph-up-arrow",
        "verdict": verdict,
        "verdict_color": color,
        "big_number": f"{adx:.1f}",
        "big_unit": "",
        "subline": f"Direction: {direction_text}",
        "plain_english": (
            "ADX is a 'trend meter' from 0-100. It tells you HOW STRONG a "
            "trend is (not which way). Read it with +DI vs -DI to get "
            "direction — whichever is higher is winning.\n\n"
            "  • 0-20   → Sideways / no trend    (mean-reversion works)\n"
            "  • 20-25  → Trend forming\n"
            "  • 25-40  → Confirmed strong trend (ride it, don't fade)\n"
            "  • 40+    → Very strong, may be stretched"
        ),
        "action": action,
        "rows": [
            {"label": "ADX (strength)", "value": f"{adx:.2f}"},
            {"label": "+DI (up pressure)", "value": _fmt_num(pdi)},
            {"label": "-DI (down pressure)", "value": _fmt_num(ndi)},
        ],
    }


# ─────────────────────────────────────────────────────────────────────
#  Card 2 — Volatility Squeeze (BB inside Keltner)
# ─────────────────────────────────────────────────────────────────────

def _squeeze_card(snap: dict) -> dict:
    bb_upper = _num(snap.get("bb_upper"))
    bb_lower = _num(snap.get("bb_lower"))
    kelt_upper = _num(snap.get("keltner_upper"))
    kelt_lower = _num(snap.get("keltner_lower"))
    bbw = _num(snap.get("bbw"))
    price = _num(snap.get("price"))

    if None in (bb_upper, bb_lower, kelt_upper, kelt_lower):
        return {
            "title": "Volatility Squeeze",
            "verdict": "N/A", "verdict_color": "gray",
            "big_number": "—", "subline": "Not enough data",
            "plain_english": "Need both Bollinger and Keltner bands to detect a squeeze.",
            "action": "Check back once more data is available.",
            "rows": [],
        }

    # Squeeze ON = Bollinger fits inside Keltner (BB tighter than expected)
    bb_inside_kelt = (bb_upper <= kelt_upper) and (bb_lower >= kelt_lower)

    if bb_inside_kelt:
        verdict, color = "SQUEEZE ON", "yellow"
        action = ("Volatility is coiled. A move is likely soon — but the "
                  "squeeze does NOT tell you the direction. Wait for the "
                  "FIRST close OUTSIDE the Bollinger Band. That close's "
                  "direction = the trade direction. Squeezes can head-fake, "
                  "so don't guess before the release.")
    else:
        # Where is price relative to BB?
        if price is not None and price > bb_upper:
            verdict, color = "RELEASED UP", "green"
            action = ("Bollinger Bands have opened up and price closed above "
                      "the upper band — the squeeze has resolved BULLISH. "
                      "Trend-follow with a trailing stop; avoid fading.")
        elif price is not None and price < bb_lower:
            verdict, color = "RELEASED DOWN", "red"
            action = ("Bollinger Bands have opened up and price closed below "
                      "the lower band — the squeeze has resolved BEARISH. "
                      "Avoid buying dips until a base forms.")
        else:
            verdict, color = "NORMAL", "gray"
            action = ("Bands are wider than usual — no squeeze in play. "
                      "Trade the current trend or wait for a fresh squeeze "
                      "setup to develop.")

    return {
        "title": "Volatility Squeeze",
        "icon": "bi-fire",
        "verdict": verdict,
        "verdict_color": color,
        "big_number": _fmt_num(bbw, 4) if bbw is not None else "—",
        "big_unit": "BBW",
        "subline": (f"BB {_fmt_inr(bb_lower)}–{_fmt_inr(bb_upper)}  ·  "
                    f"Keltner {_fmt_inr(kelt_lower)}–{_fmt_inr(kelt_upper)}"),
        "plain_english": (
            "Two 'rubber bands' wrap the price:\n"
            "  • Bollinger Bands  = how much the stock has been wiggling\n"
            "  • Keltner Channels = how much it USUALLY wiggles\n\n"
            "When Bollinger fits INSIDE Keltner, the stock is wiggling less "
            "than normal — like a spring coiling up. Coiled springs release. "
            "The longer the squeeze, the bigger the release usually is.\n\n"
            "Direction is unknown until the first close outside the bands."
        ),
        "action": action,
        "rows": [
            {"label": "BB Upper", "value": _fmt_inr(bb_upper)},
            {"label": "BB Lower", "value": _fmt_inr(bb_lower)},
            {"label": "Keltner Upper", "value": _fmt_inr(kelt_upper)},
            {"label": "Keltner Lower", "value": _fmt_inr(kelt_lower)},
        ],
    }


# ─────────────────────────────────────────────────────────────────────
#  Card 3 — Daily Volatility (ATR) + stops
# ─────────────────────────────────────────────────────────────────────

def _volatility_card(snap: dict,
                     trailing_stops: Optional[dict] = None,
                     buy_price: Optional[float] = None) -> dict:
    atr = _num(snap.get("atr"))
    atr_pct = _num(snap.get("atr_pct"))
    price = _num(snap.get("price"))

    if atr is None or price is None:
        return {
            "title": "Daily Volatility (ATR 14)",
            "verdict": "N/A", "verdict_color": "gray",
            "big_number": "—", "subline": "Not enough data",
            "plain_english": "ATR needs at least 14 trading bars.",
            "action": "Check back once more data is available.",
            "rows": [],
        }

    if atr_pct is None or atr_pct < 1.5:
        verdict, color = "LOW", "green"
        action_intro = "Calm stock — tighter stops are OK."
    elif atr_pct < 3.0:
        verdict, color = "MODERATE", "blue"
        action_intro = "Normal volatility — SuperTrend or Chandelier is the sweet spot."
    elif atr_pct < 5.0:
        verdict, color = "HIGH", "orange"
        action_intro = "Choppy — prefer wider 3×ATR stops to avoid whipsaws."
    else:
        verdict, color = "EXTREME", "red"
        action_intro = "Event-level volatility — consider skipping the trade or halving size."

    rows = [
        {"label": "ATR (14-day)", "value": _fmt_inr(atr)},
        {"label": "As % of price", "value": _fmt_pct(atr_pct)},
        {"label": "Current price", "value": _fmt_inr(price)},
    ]

    # If we have a portfolio-side trailing-stops payload, surface all 4
    # candidates so the user can pick. Also express as distance vs BUY price
    # if we know it.
    ts_lines = []
    if isinstance(trailing_stops, dict) and trailing_stops.get("available"):
        stops = [
            ("Tight (2×ATR)",     trailing_stops.get("atr_trail_tight"),   "Active traders"),
            ("SuperTrend (2×ATR10)", trailing_stops.get("supertrend_stop"), "Indian market favourite"),
            ("Wide (3×ATR)",      trailing_stops.get("atr_trail_wide"),    "Swing traders"),
            ("Chandelier (22d)",  trailing_stops.get("chandelier_exit"),   "LeBeau classic"),
        ]
        for lbl, val, note in stops:
            v = _num(val)
            if v is None:
                continue
            extra = ""
            if buy_price and buy_price > 0:
                pnl_pct = (v - buy_price) / buy_price * 100
                extra = f"  ({'+' if pnl_pct >= 0 else ''}{pnl_pct:.1f}% vs buy)"
            ts_lines.append({"label": lbl, "value": f"{_fmt_inr(v)}{extra}", "note": note})
        recommended = _num(trailing_stops.get("recommended_stop"))
        if recommended is not None:
            action_intro += f" Recommended: {_fmt_inr(recommended)}."

    return {
        "title": "Daily Volatility (ATR 14)",
        "icon": "bi-rulers",
        "verdict": verdict,
        "verdict_color": color,
        "big_number": _fmt_inr(atr),
        "big_unit": f"({_fmt_pct(atr_pct)} of price)" if atr_pct is not None else "",
        "subline": f"This stock typically moves {_fmt_inr(atr)} per day.",
        "plain_english": (
            "ATR = 'Average True Range' — the size of a normal daily candle "
            "over the last 14 days. Think of it as the stock's breathing room.\n\n"
            "A stop tighter than 1× ATR will get hit by normal daily noise — "
            "you'll be stopped out for no real reason. Position size and stop "
            "distance both scale with ATR to keep risk consistent.\n\n"
            "Rule: risk per trade = qty × (price − stop). Never let one "
            "trade risk more than 1–2% of total capital."
        ),
        "action": action_intro,
        "rows": rows + ts_lines,
    }


# ─────────────────────────────────────────────────────────────────────
#  Card 4 — Smart Money Flow (OBV)
# ─────────────────────────────────────────────────────────────────────

def _money_flow_card(snap: dict, vol_analysis: Optional[dict]) -> dict:
    obv = _num(snap.get("obv"))
    obv_sma = _num(snap.get("obv_sma"))
    obv_trend_raw = (vol_analysis or {}).get("obv_trend") or ""
    obv_trend = str(obv_trend_raw).upper()

    if obv is None:
        return {
            "title": "Smart Money Flow (OBV)",
            "verdict": "N/A", "verdict_color": "gray",
            "big_number": "—", "subline": "Not enough data",
            "plain_english": "OBV needs a full volume history to compute.",
            "action": "Check back once more data is available.",
            "rows": [],
        }

    if "BULLISH" in obv_trend or (obv_sma is not None and obv > obv_sma):
        verdict, color = "ACCUMULATING", "green"
        action = ("Green light for continuation trades. OBV is rising with "
                  "price — real volume is backing the move, not just a few "
                  "loud traders. If OBV starts flattening while price keeps "
                  "climbing, that's your early warning to tighten stops.")
    elif "BEARISH" in obv_trend or (obv_sma is not None and obv < obv_sma):
        verdict, color = "DISTRIBUTING", "red"
        action = ("Red flag for long positions. OBV is falling — supply is "
                  "outpacing demand. Rallies from here will tend to fail. "
                  "Existing longs: tighten stops or take partial profit. "
                  "New longs: wait for OBV to turn back up.")
    else:
        verdict, color = "NEUTRAL", "gray"
        action = ("Volume flow shows no clear direction. Wait for OBV to "
                  "cross its 20-day average decisively before leaning on "
                  "any breakout signal.")

    rows = [
        {"label": "OBV trend", "value": obv_trend_raw or "—"},
        {"label": "OBV (running total)", "value": f"{obv:,.0f}"},
        {"label": "OBV 20-day avg", "value": f"{obv_sma:,.0f}" if obv_sma is not None else "—"},
    ]

    return {
        "title": "Smart Money Flow (OBV)",
        "icon": "bi-cash-stack",
        "verdict": verdict,
        "verdict_color": color,
        "big_number": verdict.title(),
        "big_unit": "",
        "subline": obv_trend_raw or "",
        "plain_english": (
            "OBV = 'On-Balance Volume' — a running tally:\n"
            "  • Price closes UP today → add today's volume to OBV\n"
            "  • Price closes DOWN today → subtract today's volume\n\n"
            "If OBV keeps climbing, UP days had bigger volume than DOWN days. "
            "Translation: institutions ('smart money') are quietly buying = "
            "accumulation.\n\n"
            "Watch for DIVERGENCE:\n"
            "  • Price new high + OBV flat/down → rally weakening, warning\n"
            "  • Price new low + OBV flat/up   → sellers exhausted, bounce coming"
        ),
        "action": action,
        "rows": rows,
    }


# ─────────────────────────────────────────────────────────────────────
#  Public entry point
# ─────────────────────────────────────────────────────────────────────

def build_regime_cards(triple: Optional[dict],
                       trailing_stops: Optional[dict] = None,
                       buy_price: Optional[float] = None) -> Optional[dict]:
    """Return the 4-card payload, or None if the triple result is missing."""
    if not isinstance(triple, dict):
        return None
    snap = triple.get("snapshot") or {}
    vol_analysis = triple.get("volume") or {}
    return {
        "trend":      _trend_card(snap),
        "squeeze":    _squeeze_card(snap),
        "volatility": _volatility_card(snap, trailing_stops=trailing_stops, buy_price=buy_price),
        "money_flow": _money_flow_card(snap, vol_analysis),
    }
