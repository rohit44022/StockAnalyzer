"""
bb_squeeze/vix_regime.py — India VIX Regime Detector

Classifies the current market volatility regime using India VIX (^INDIAVIX).
Used as a gate in the Top Picks pipeline: DEFENSIVE suppresses non-trend
methods, CAUTION raises the minimum composite score threshold.
"""
from __future__ import annotations

import functools
from datetime import date

import yfinance as yf

from top_picks.config import (
    VIX_CAUTION_THRESHOLD,
    VIX_DEFENSIVE_THRESHOLD,
    VIX_CAUTION_MIN_SCORE,
    VIX_DEFENSIVE_METHODS,
)


@functools.lru_cache(maxsize=8)
def _fetch_vix(as_of: date) -> float | None:
    try:
        df = yf.download("^INDIAVIX", period="5d", interval="1d",
                         progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None
        close = df["Close"].dropna()
        if close.empty:
            return None
        return float(close.iloc[-1])
    except Exception:
        return None


def get_vix_regime(skip: bool = False) -> dict:
    """
    Returns:
        available          bool
        regime             "NORMAL" | "CAUTION" | "DEFENSIVE" | "UNKNOWN"
        vix_value          float | None
        min_score_override float | None  (None = use config default)
        active_methods     list[str] | None  (None = all methods allowed)
    """
    if skip:
        return {"available": False, "regime": "UNKNOWN", "vix_value": None,
                "min_score_override": None, "active_methods": None}

    vix = _fetch_vix(date.today())
    if vix is None:
        return {"available": False, "regime": "UNKNOWN", "vix_value": None,
                "min_score_override": None, "active_methods": None}

    if vix > VIX_DEFENSIVE_THRESHOLD:
        regime = "DEFENSIVE"
    elif vix > VIX_CAUTION_THRESHOLD:
        regime = "CAUTION"
    else:
        regime = "NORMAL"

    return {
        "available": True,
        "regime": regime,
        "vix_value": round(vix, 2),
        "min_score_override": VIX_CAUTION_MIN_SCORE if regime == "CAUTION" else None,
        "active_methods": VIX_DEFENSIVE_METHODS if regime == "DEFENSIVE" else None,
    }


if __name__ == "__main__":
    print(get_vix_regime())
