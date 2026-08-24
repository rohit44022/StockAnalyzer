"""
ai_ml/adaptive_thresholds.py — Stock-Specific Adaptive Thresholds

Instead of fixed BBW < 0.10 for all stocks, this computes where the
current indicator value sits relative to that stock's OWN history.

"This stock's BBW is tighter than 92% of its own last 250 days"
is far more meaningful than a fixed 0.10 cutoff for all stocks.

Adds percentile context to picks WITHOUT modifying existing fields.
"""
from __future__ import annotations

import os
import logging

import numpy as np
import pandas as pd

from ai_ml.config import CSV_DIR

logger = logging.getLogger("ai_ml.adaptive_thresholds")


def _sma(arr: np.ndarray, period: int) -> np.ndarray:
    out = np.full(len(arr), np.nan)
    for i in range(period - 1, len(arr)):
        out[i] = arr[i - period + 1 : i + 1].mean()
    return out


def _rolling_std(arr: np.ndarray, period: int) -> np.ndarray:
    out = np.full(len(arr), np.nan)
    for i in range(period - 1, len(arr)):
        out[i] = arr[i - period + 1 : i + 1].std(ddof=0)
    return out


def _rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    delta = np.diff(close, prepend=np.nan)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = _sma(gain, period)
    avg_loss = _sma(loss, period)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.where(avg_loss == 0, np.inf, avg_gain / avg_loss)
    return 100.0 - (100.0 / (1.0 + rs))


def _atr(high, low, close, period=14):
    prev_close = np.concatenate([[np.nan], close[:-1]])
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    return _sma(tr, period)


def compute_adaptive_context(ticker: str, lookback: int = 250) -> dict | None:
    """
    Compute where current indicator values sit relative to the stock's
    own history (last `lookback` trading days).

    Returns dict with percentile values, or None if data insufficient.
    """
    csv_path = os.path.join(CSV_DIR, f"{ticker}.csv")
    if not os.path.exists(csv_path):
        return None

    try:
        df = pd.read_csv(csv_path, parse_dates=["Date"], index_col="Date")
    except Exception:
        return None

    if len(df) < lookback or "Close" not in df.columns:
        return None

    df = df.tail(lookback + 20)
    close = df["Close"].to_numpy(dtype=float)
    high = df["High"].to_numpy(dtype=float)
    low = df["Low"].to_numpy(dtype=float)
    volume = df["Volume"].to_numpy(dtype=float)

    sma20 = _sma(close, 20)
    std20 = _rolling_std(close, 20)
    upper = sma20 + 2.0 * std20
    lower = sma20 - 2.0 * std20
    bbw = np.where(sma20 > 0, (upper - lower) / sma20, np.nan)
    rsi14 = _rsi(close)
    atr14 = _atr(high, low, close)
    vol_ma = _sma(volume, 20)
    vol_ratio = np.where(vol_ma > 0, volume / vol_ma, np.nan)

    def _pct(arr, idx=-1):
        """What percentile is the current value within the array?"""
        val = arr[idx]
        if np.isnan(val):
            return None
        valid = arr[~np.isnan(arr)]
        if len(valid) < 20:
            return None
        return round(float(np.searchsorted(np.sort(valid), val) / len(valid) * 100), 1)

    current_bbw = bbw[-1] if not np.isnan(bbw[-1]) else None
    current_rsi = rsi14[-1] if not np.isnan(rsi14[-1]) else None
    current_atr = atr14[-1] if not np.isnan(atr14[-1]) else None
    current_vr = vol_ratio[-1] if not np.isnan(vol_ratio[-1]) else None

    return {
        "bbw_current": round(current_bbw, 4) if current_bbw else None,
        "bbw_percentile": _pct(bbw),
        "rsi_current": round(current_rsi, 1) if current_rsi else None,
        "rsi_percentile": _pct(rsi14),
        "atr_current": round(current_atr, 2) if current_atr else None,
        "atr_percentile": _pct(atr14),
        "vol_ratio_current": round(current_vr, 2) if current_vr else None,
        "vol_ratio_percentile": _pct(vol_ratio),
        "lookback_days": lookback,
        "data_points": int(len(close)),
    }


def enrich_picks_with_adaptive(picks: list[dict]) -> list[dict]:
    """
    Add adaptive threshold context to each pick.
    Added field: adaptive_context (dict with percentile data).
    """
    for pick in picks:
        ticker = pick.get("ticker", "")
        ctx = compute_adaptive_context(ticker)
        pick["adaptive_context"] = ctx or {"available": False}

    return picks
