"""
calibration.py — Historical-replay-based threshold calibration.
═══════════════════════════════════════════════════════════════

The composite-score buckets and verdict bucket boundaries (e.g. -50/-30/-10/+10/+30/+50)
were originally tuned by eye. This module replays the composite score over the past
~3 years of daily data and derives data-driven percentile breakpoints.

Cached on disk for 24 hours so the work is amortized.

Public API:
    get_calibration() -> dict
        Returns calibrated buckets + score distribution stats.
        Falls back to hardcoded defaults if replay fails.
"""

from __future__ import annotations
import os, time, pickle
from typing import Optional

import numpy as np
import pandas as pd

from global_sentiment.data_loader import logger, _safe_float
from global_sentiment.instruments import BY_KEY, ALL_INSTRUMENTS


_CACHE_TTL = 24 * 3600  # 24h
_CACHE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "logs",
    "global_sentiment_calibration.pkl",
)

# Hardcoded defaults — used when replay isn't possible (insufficient data, etc.)
DEFAULT_BUCKETS = {
    "strong_risk_off": -50.0,
    "risk_off":        -20.0,
    "neutral_low":     -20.0,
    "neutral_high":     20.0,
    "risk_on":          20.0,
    "strong_risk_on":   50.0,
}


# ─────────────────────────── replay ───────────────────────────

def _per_day_summarize(closes: pd.Series, idx: int) -> dict:
    """For a given index in the closes series, compute the lookback metrics."""
    if idx < 21:
        return {}
    last = _safe_float(closes.iloc[idx])
    if last is None:
        return {}
    out = {"last": last}
    # 1d/5d/20d/60d % changes
    for n, key in [(1, "change_1d_pct"), (5, "change_5d_pct"),
                   (20, "change_20d_pct"), (60, "change_60d_pct")]:
        if idx - n < 0:
            continue
        ref = _safe_float(closes.iloc[idx - n])
        if not ref:
            continue
        out[key] = (last - ref) / ref * 100
    return out


def _replay_day(market_data: dict, day_idx: int) -> Optional[float]:
    """
    Compute the composite score AS IF today were day_idx (counted from the end).
    Returns the score or None if insufficient data.

    day_idx=0 → today, day_idx=1 → yesterday, etc.
    """
    weights = {
        "sp500": 1.5, "nasdaq": 1.0, "nifty": 1.5, "dow": 0.5,
        "ftse": 0.3, "dax": 0.3, "nikkei": 0.4, "hangseng": 0.4,
        "vix": 1.2, "indiavix": 1.5,
        "us10y": 0.8, "us30y": 0.3,
        "dxy": 1.0, "usdinr": 0.7, "jpyinr": 0.5,
        "gold": 1.0, "copper": 0.8, "brent": 0.8,
        "btc": 0.7, "eth": 0.3,
    }
    tf_w = {"change_1d_pct": 0.20, "change_5d_pct": 0.50, "change_20d_pct": 0.30}

    score = 0.0
    total_w = 0.0
    for k, w in weights.items():
        inst = BY_KEY.get(k)
        if not inst or k not in market_data:
            continue
        closes = market_data[k]["Close"].dropna()
        if len(closes) <= day_idx + 21:
            continue
        idx = len(closes) - 1 - day_idx
        if idx < 21:
            continue
        s = _per_day_summarize(closes, idx)
        if not s:
            continue

        tf_score = 0.0
        tf_used = 0.0
        for f, tw in tf_w.items():
            v = s.get(f)
            if v is None:
                continue
            tf_score += max(-12.0, min(12.0, v)) * tw
            tf_used += tw
        if tf_used == 0:
            continue
        tf_score /= tf_used

        # Polarity (context-aware, mirrors compute_composite_score)
        polarity = inst.polarity
        last = s.get("last")
        if polarity == 0:
            if k == "dxy":
                polarity = -1
            elif k in ("brent", "wti"):
                polarity = -1 if last and last > 85 else (+1 if last and 50 <= last <= 75 else 0)
            elif k in ("us10y", "us30y"):
                polarity = -1 if last and last > 4.5 else (+1 if last and 0 < last < 3.5 else 0)
            else:
                polarity = 0

        score += tf_score * polarity * w
        total_w += w

    if total_w == 0:
        return None
    return max(-100.0, min(100.0, score / total_w * 14.0))


# ─────────────────────────── public API ───────────────────────────

def _load_cached() -> Optional[dict]:
    if not os.path.exists(_CACHE_FILE):
        return None
    try:
        with open(_CACHE_FILE, "rb") as f:
            payload = pickle.load(f)
        if time.time() - payload.get("ts", 0) > _CACHE_TTL:
            return None
        return payload.get("data")
    except Exception as e:
        logger.warning(f"calibration cache load failed: {e}")
        return None


def _save_cached(data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
        with open(_CACHE_FILE, "wb") as f:
            pickle.dump({"ts": time.time(), "data": data}, f)
    except Exception as e:
        logger.warning(f"calibration cache save failed: {e}")


def get_calibration(market_data: dict, force_refresh: bool = False) -> dict:
    """
    Returns:
      {
        "ok":        bool,
        "source":    'replay' | 'cached' | 'default',
        "n_days":    int,
        "score_distribution": {p5, p25, p50, p75, p95, mean, std},
        "buckets":   {strong_risk_off, risk_off, neutral_low, neutral_high, risk_on, strong_risk_on},
        "computed_at": ISO timestamp,
      }
    """
    if not force_refresh:
        cached = _load_cached()
        if cached:
            cached["source"] = "cached"
            return cached

    if not market_data:
        return {"ok": False, "source": "default", "buckets": DEFAULT_BUCKETS,
                "score_distribution": None, "n_days": 0,
                "note": "no market data available; using default buckets"}

    # Replay last 3 years (~750 trading days) — limit to avoid explosion
    LOOKBACK = 750
    scores = []
    failures = 0
    for d in range(LOOKBACK):
        try:
            s = _replay_day(market_data, d)
            if s is not None:
                scores.append(s)
        except Exception as e:
            failures += 1
            if failures > 50:
                break

    if len(scores) < 100:
        # Insufficient data — fall back to defaults
        result = {
            "ok": False,
            "source": "default",
            "n_days": len(scores),
            "buckets": DEFAULT_BUCKETS,
            "score_distribution": None,
            "note": f"only {len(scores)} valid days replayed; using default buckets",
        }
        return result

    arr = np.array(scores)
    p5  = float(np.percentile(arr, 5))
    p25 = float(np.percentile(arr, 25))
    p50 = float(np.percentile(arr, 50))
    p75 = float(np.percentile(arr, 75))
    p95 = float(np.percentile(arr, 95))
    mean = float(arr.mean())
    std  = float(arr.std())

    # Calibrated buckets:
    #   strong risk-off : score <= p5     (rarest 5%)
    #   risk-off        : p5 < score <= p25
    #   neutral         : p25 < score < p75
    #   risk-on         : p75 <= score < p95
    #   strong risk-on  : score >= p95
    buckets = {
        "strong_risk_off": round(p5, 1),
        "risk_off":        round(p25, 1),
        "neutral_low":     round(p25, 1),
        "neutral_high":    round(p75, 1),
        "risk_on":         round(p75, 1),
        "strong_risk_on":  round(p95, 1),
    }

    result = {
        "ok": True,
        "source": "replay",
        "n_days": len(scores),
        "score_distribution": {
            "p5":   round(p5, 1),
            "p25":  round(p25, 1),
            "p50":  round(p50, 1),
            "p75":  round(p75, 1),
            "p95":  round(p95, 1),
            "mean": round(mean, 1),
            "std":  round(std, 1),
            "min":  round(float(arr.min()), 1),
            "max":  round(float(arr.max()), 1),
        },
        "buckets": buckets,
        "computed_at": int(time.time()),
    }
    _save_cached(result)
    return result


def label_score(score: float, buckets: dict) -> tuple:
    """
    Apply calibrated buckets to a score → (label, color).
    """
    if score >= buckets.get("strong_risk_on", 50):
        return ("STRONG RISK-ON", "#3fb950")
    if score >= buckets.get("risk_on", 20):
        return ("RISK-ON", "#56d364")
    if score >= buckets.get("neutral_low", -20):
        return ("NEUTRAL", "#8b949e")
    if score >= buckets.get("strong_risk_off", -50):
        return ("RISK-OFF", "#ff7b72")
    return ("STRONG RISK-OFF", "#f85149")
