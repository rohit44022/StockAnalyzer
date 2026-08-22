"""
fii_dii_tracker.py — FII/DII Institutional Flow Tracker
=========================================================

WHY THIS MATTERS (for the layman):
    The Indian stock market has two types of big players whose money movements
    can make or break your trade:

    1. FIIs (Foreign Institutional Investors): Think Goldman Sachs, Morgan Stanley,
       SoftBank, and every other foreign fund. They bring MASSIVE money from abroad —
       often ₹2,000–10,000 Crore in a single day. When they buy, markets surge.
       When they panic and sell (e.g., when the US Fed raises interest rates or
       there's global risk-off), markets can fall 5-15% in weeks.

    2. DIIs (Domestic Institutional Investors): Indian mutual funds, LIC, EPFO,
       and domestic insurance companies. They act as the "counterweight" — when
       FIIs panic-sell, DIIs often step in and absorb selling (SIP money flows in
       every month regardless of market conditions). But if BOTH are selling? Run.

    Together, FIIs + DIIs move 60–70% of total market volume on the NSE.
    A retail investor who ignores their flow is like driving without checking
    the weather — you might be fine, but you're flying blind.

HOW TO READ THE SIGNAL:
    BULLISH:  FIIs buying + DIIs buying → institutional confidence is HIGH.
              Example: Jan-Mar 2021, FIIs poured ₹65,000 Cr → Nifty rose 20%.

    MIXED:    FIIs selling but DIIs absorbing → market may hold up; caution advised.
              Example: Oct 2021, FIIs sold ₹25,000 Cr but DIIs bought ₹22,000 Cr →
              Nifty fell only 2% vs what would've been 8-10%.

    BEARISH:  FIIs heavy selling (>₹3,000 Cr/day for 3+ days) → high crash risk.
              Example: Mar 2020, FIIs sold ₹60,000 Cr in a month → Nifty fell 38%.
              Example: Oct-Nov 2024, FIIs sold ₹1.14 Lakh Cr → Nifty fell 10%.

DATA SOURCE: NSE India official API (https://www.nseindia.com/api/fiidiiActivity)
"""

from __future__ import annotations

import time
import requests
from typing import Any

# ── Module-level cache (4-hour TTL) ──────────────────────────────────────────
_CACHE: dict[str, Any] = {}
_CACHE_TTL: float = 4 * 3600  # ponytail: single dict cache, per-endpoint if more APIs added

_FII_DII_URL = "https://www.nseindia.com/api/fiidiiActivity"


def _nse_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://www.nseindia.com/",
    })
    try:
        s.get("https://www.nseindia.com/", timeout=10)
    except Exception:
        pass
    return s


def _trend(net_values: list[float]) -> str:
    """BUYING if 3+ of last 5 net values are positive, SELLING if 3+ negative."""
    last5 = net_values[-5:] if len(net_values) >= 5 else net_values
    positives = sum(1 for v in last5 if v > 0)
    negatives = sum(1 for v in last5 if v < 0)
    if positives >= 3:
        return "BUYING"
    if negatives >= 3:
        return "SELLING"
    return "NEUTRAL"


def _consecutive(net_values: list[float], direction: str) -> int:
    """Count consecutive recent days matching direction ('buy' or 'sell')."""
    count = 0
    for v in reversed(net_values):
        if direction == "buy" and v > 0:
            count += 1
        elif direction == "sell" and v < 0:
            count += 1
        else:
            break
    return count


def get_fii_dii_activity(days: int = 10) -> dict:
    """Fetch FII/DII activity from NSE and return institutional flow signals."""
    cache_key = f"fii_dii_{days}"
    cached = _CACHE.get(cache_key)
    if cached and (time.time() - cached["_ts"]) < _CACHE_TTL:
        return {k: v for k, v in cached.items() if k != "_ts"}

    try:
        session = _nse_session()
        resp = session.get(_FII_DII_URL, timeout=15)
        resp.raise_for_status()
        raw: list[dict] = resp.json()
    except Exception as exc:
        return {
            "available": False,
            "explanation": (
                f"Could not fetch FII/DII data from NSE ({exc}). "
                "NSE sometimes blocks automated requests — try again later or "
                "check https://www.nseindia.com/market-data/fii-dii-activity manually."
            ),
        }

    # NSE returns newest-first; each entry has fields like:
    # buyValue, sellValue for FII and DII (in Crores, as strings)
    entries = raw[:days] if len(raw) >= days else raw

    daily_data: list[dict] = []
    fii_nets: list[float] = []
    dii_nets: list[float] = []

    for row in reversed(entries):  # oldest → newest
        try:
            fii_buy  = float(str(row.get("fiiBuyValue",  row.get("fii_buy",  0))).replace(",", ""))
            fii_sell = float(str(row.get("fiiSellValue", row.get("fii_sell", 0))).replace(",", ""))
            dii_buy  = float(str(row.get("diiBuyValue",  row.get("dii_buy",  0))).replace(",", ""))
            dii_sell = float(str(row.get("diiSellValue", row.get("dii_sell", 0))).replace(",", ""))
            date_str = str(row.get("date", row.get("Date", "")))
        except (TypeError, ValueError):
            continue

        fii_net = round(fii_buy - fii_sell, 2)
        dii_net = round(dii_buy - dii_sell, 2)
        fii_nets.append(fii_net)
        dii_nets.append(dii_net)
        daily_data.append({"date": date_str, "fii_net": fii_net, "dii_net": dii_net})

    if not daily_data:
        return {
            "available": False,
            "explanation": "NSE returned data but it could not be parsed. Field names may have changed.",
        }

    fii_net_today  = fii_nets[-1]
    dii_net_today  = dii_nets[-1]
    fii_5d         = round(sum(fii_nets[-5:]), 2)
    dii_5d         = round(sum(dii_nets[-5:]), 2)
    fii_trend      = _trend(fii_nets)
    dii_trend      = _trend(dii_nets)
    consec_sell    = _consecutive(fii_nets, "sell")
    consec_buy     = _consecutive(fii_nets, "buy")

    # flow_signal: BEARISH only on heavy sustained FII selling
    heavy_sell_days = sum(1 for v in fii_nets[-5:] if v < -3000)
    if fii_trend == "BUYING" and dii_trend == "BUYING":
        flow_signal = "BULLISH"
    elif heavy_sell_days >= 3:
        flow_signal = "BEARISH"
    else:
        flow_signal = "MIXED"

    # Build explanation
    fii_dir  = "bought" if fii_net_today >= 0 else "sold"
    dii_dir  = "bought" if dii_net_today >= 0 else "sold"
    abs_fii  = abs(fii_net_today)
    abs_dii  = abs(dii_net_today)

    if flow_signal == "BULLISH":
        signal_text = (
            f"BULLISH — FIIs {fii_dir} ₹{abs_fii:,.0f} Cr and DIIs {dii_dir} ₹{abs_dii:,.0f} Cr today. "
            f"Both institutional groups are aligned. This is the scenario that powered the Jan-Mar 2021 rally "
            f"where Nifty rose 20% as FIIs poured ₹65,000 Cr. Strong conviction setup."
        )
    elif flow_signal == "BEARISH":
        signal_text = (
            f"BEARISH — FIIs have been heavy sellers (>₹3,000 Cr/day) for {heavy_sell_days} of the last 5 days. "
            f"Today FIIs {fii_dir} ₹{abs_fii:,.0f} Cr. This pattern preceded the Oct-Nov 2024 crash "
            f"(FIIs sold ₹1.14 Lakh Cr, Nifty fell 10%) and Mar 2020 (₹60,000 Cr FII exit, Nifty -38%). "
            f"Defensive positioning advised."
        )
    else:
        signal_text = (
            f"MIXED — FIIs {fii_dir} ₹{abs_fii:,.0f} Cr, DIIs {dii_dir} ₹{abs_dii:,.0f} Cr today. "
            f"Institutional flows are not aligned. Market likely to stay choppy. "
            f"5-day cumulative: FII ₹{fii_5d:+,.0f} Cr, DII ₹{dii_5d:+,.0f} Cr."
        )

    result = {
        "available": True,
        "fii_net_today": fii_net_today,
        "dii_net_today": dii_net_today,
        "fii_5d_cumulative": fii_5d,
        "dii_5d_cumulative": dii_5d,
        "fii_trend": fii_trend,
        "dii_trend": dii_trend,
        "flow_signal": flow_signal,
        "consecutive_days_fii_sell": consec_sell,
        "consecutive_days_fii_buy": consec_buy,
        "daily_data": daily_data,
        "explanation": signal_text,
    }
    _CACHE[cache_key] = {**result, "_ts": time.time()}
    return result


def compute_delivery_trend(delivery_data: list[dict]) -> dict:
    """
    Analyse delivery % trend to distinguish accumulation from distribution.

    delivery_data: list of dicts with keys date, delivery_pct, close_price
                   (oldest → newest order).

    Delivery % = actual shares taken delivery (held overnight) vs total traded.
    High delivery % means people are HOLDING, not just day-trading.
    Rising delivery + rising price = smart money accumulating.
    Rising delivery + falling price = smart money distributing (selling into buyers).
    """
    if len(delivery_data) < 5:
        return {
            "trend": "NEUTRAL",
            "signal": "NEUTRAL",
            "5d_avg": None,
            "10d_avg": None,
            "explanation": "Not enough delivery data (need at least 5 days).",
        }

    pcts    = [d["delivery_pct"] for d in delivery_data]
    prices  = [d["close_price"]  for d in delivery_data]

    avg5    = round(sum(pcts[-5:]) / 5, 2)
    avg10   = round(sum(pcts[-10:]) / min(len(pcts), 10), 2) if len(pcts) >= 10 else avg5

    # Slope check: compare last 3 days avg vs prior 3 days avg
    recent_del  = sum(pcts[-3:]) / 3
    prior_del   = sum(pcts[-6:-3]) / 3 if len(pcts) >= 6 else recent_del
    recent_px   = sum(prices[-3:]) / 3
    prior_px    = sum(prices[-6:-3]) / 3 if len(pcts) >= 6 else recent_px

    del_rising  = recent_del > prior_del * 1.02   # >2% uptick
    px_rising   = recent_px  > prior_px  * 1.005  # >0.5% uptick

    if del_rising and px_rising:
        trend, signal = "ACCUMULATION", "BULLISH"
        expl = (
            f"Delivery % rising ({prior_del:.1f}% → {recent_del:.1f}%) alongside price — "
            f"investors are HOLDING shares, not selling. This is called accumulation: "
            f"smart money is quietly building positions. 5-day avg delivery: {avg5}%."
        )
    elif del_rising and not px_rising:
        trend, signal = "DISTRIBUTION", "BEARISH"
        expl = (
            f"Delivery % rising ({prior_del:.1f}% → {recent_del:.1f}%) but price is flat/falling — "
            f"shares are changing hands but prices aren't rising, classic distribution. "
            f"Someone is offloading stock into buying demand. Caution. 5-day avg delivery: {avg5}%."
        )
    else:
        trend, signal = "NEUTRAL", "NEUTRAL"
        expl = (
            f"Delivery % flat/declining ({recent_del:.1f}% recent avg). "
            f"Mostly intraday / speculative activity. No strong directional conviction. "
            f"5-day avg delivery: {avg5}%, 10-day avg: {avg10}%."
        )

    return {
        "trend": trend,
        "signal": signal,
        "5d_avg": avg5,
        "10d_avg": avg10,
        "explanation": expl,
    }


if __name__ == "__main__":
    result = get_fii_dii_activity(days=5)
    print("available:", result.get("available"))
    if result.get("available"):
        print("flow_signal:", result["flow_signal"])
        print("fii_net_today:", result["fii_net_today"])
        print("explanation:", result["explanation"])
    else:
        print("explanation:", result.get("explanation"))

    # delivery trend self-check
    sample = [
        {"date": "2024-01-01", "delivery_pct": 40.0, "close_price": 100.0},
        {"date": "2024-01-02", "delivery_pct": 42.0, "close_price": 101.0},
        {"date": "2024-01-03", "delivery_pct": 44.0, "close_price": 102.5},
        {"date": "2024-01-04", "delivery_pct": 46.0, "close_price": 103.0},
        {"date": "2024-01-05", "delivery_pct": 50.0, "close_price": 105.0},
        {"date": "2024-01-06", "delivery_pct": 53.0, "close_price": 106.5},
    ]
    dt = compute_delivery_trend(sample)
    assert dt["trend"] == "ACCUMULATION", f"Expected ACCUMULATION, got {dt['trend']}"
    print("delivery_trend self-check passed:", dt["signal"])
