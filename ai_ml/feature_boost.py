"""
ai_ml/feature_boost.py — Expanded Feature Engineering

Adds 10 indicators (already computed by bb_squeeze but never fed to ML)
as new features for the XGBoost classifier. Two entry points:

  compute_boost_features_train(ind, i)  → dict   (training, NumPy arrays)
  extract_boost_features_pick(pick)     → dict   (inference, live pick dict)

Formulas mirror bb_squeeze/indicators.py exactly — reimplemented in NumPy
for the training pipeline which operates on raw arrays, not DataFrames.
"""
from __future__ import annotations

import numpy as np


# ─────────────────────────────────────────────────────────────────
#  NumPy helpers — used only during training data generation
# ─────────────────────────────────────────────────────────────────

def _rolling_sum(arr: np.ndarray, window: int) -> np.ndarray:
    out = np.full(len(arr), np.nan)
    cs = np.nancumsum(arr)
    out[window - 1:] = cs[window - 1:] - np.concatenate([[0], cs[:-window]])
    return out


def _ema(arr: np.ndarray, span: int) -> np.ndarray:
    alpha = 2.0 / (span + 1)
    out = np.empty_like(arr)
    out[0] = arr[0] if not np.isnan(arr[0]) else 0.0
    for i in range(1, len(arr)):
        v = arr[i] if not np.isnan(arr[i]) else out[i - 1]
        out[i] = alpha * v + (1 - alpha) * out[i - 1]
    return out


def compute_extra_arrays(close: np.ndarray, high: np.ndarray,
                         low: np.ndarray, volume: np.ndarray,
                         open_price: np.ndarray,
                         sma20: np.ndarray, upper: np.ndarray,
                         lower: np.ndarray, bbw: np.ndarray,
                         rsi14: np.ndarray) -> dict:
    """
    Compute the 10 extra indicator arrays from raw OHLCV + existing arrays.
    Called once per stock during training data generation.
    Returns dict of NumPy arrays keyed by feature name.
    """
    n = len(close)

    # ── Percent B ──
    band_range = upper - lower
    band_range_safe = np.where(band_range > 0, band_range, np.nan)
    percent_b = (close - lower) / band_range_safe

    # ── CMF (Chaikin Money Flow, 20-period) ──
    hl_range = high - low
    hl_safe = np.where(hl_range > 0, hl_range, np.nan)
    mfm = ((close - low) - (high - close)) / hl_safe
    mfv = np.nan_to_num(mfm, nan=0.0) * volume
    mfv_sum = _rolling_sum(mfv, 20)
    vol_sum_20 = _rolling_sum(volume, 20)
    vol_sum_20_safe = np.where(vol_sum_20 > 0, vol_sum_20, np.nan)
    cmf = mfv_sum / vol_sum_20_safe

    # ── MFI (Money Flow Index, 10-period) ──
    typical_price = (high + low + close) / 3.0
    raw_mf = typical_price * volume
    tp_diff = np.diff(typical_price, prepend=typical_price[0])
    pos_mf = np.where(tp_diff > 0, raw_mf, 0.0)
    neg_mf = np.where(tp_diff < 0, raw_mf, 0.0)
    pos_sum = _rolling_sum(pos_mf, 10)
    neg_sum = _rolling_sum(neg_mf, 10)
    neg_sum_safe = np.where(neg_sum > 0, neg_sum, np.nan)
    mfr = pos_sum / neg_sum_safe
    mfi = 100.0 - (100.0 / (1.0 + mfr))
    mfi = np.nan_to_num(mfi, nan=50.0)

    # ── II% (Intraday Intensity %, 21-period) ──
    ii_raw = np.nan_to_num((2.0 * close - high - low) / hl_safe, nan=0.0) * volume
    ii_sum = _rolling_sum(ii_raw, 21)
    vol_sum_21 = _rolling_sum(volume, 21)
    vol_sum_21_safe = np.where(vol_sum_21 > 0, vol_sum_21, np.nan)
    ii_pct = ii_sum / vol_sum_21_safe
    ii_pct = np.nan_to_num(ii_pct, nan=0.0)

    # ── AD% (Accumulation Distribution %, 21-period) ──
    ad_raw = np.nan_to_num((close - open_price) / hl_safe, nan=0.0) * volume
    ad_sum = _rolling_sum(ad_raw, 21)
    ad_pct = ad_sum / vol_sum_21_safe
    ad_pct = np.nan_to_num(ad_pct, nan=0.0)

    # ── VWMACD Histogram ──
    cv_12 = _rolling_sum(close * volume, 12)
    v_12 = _rolling_sum(volume, 12)
    v_12_safe = np.where(v_12 > 0, v_12, np.nan)
    vw_fast = cv_12 / v_12_safe

    cv_26 = _rolling_sum(close * volume, 26)
    v_26 = _rolling_sum(volume, 26)
    v_26_safe = np.where(v_26 > 0, v_26, np.nan)
    vw_slow = cv_26 / v_26_safe

    vwmacd_line = vw_fast - vw_slow
    vwmacd_line_clean = np.nan_to_num(vwmacd_line, nan=0.0)
    vwmacd_signal = _ema(vwmacd_line_clean, 9)
    vwmacd_hist = vwmacd_line_clean - vwmacd_signal

    # ── Expansion Up / Down ──
    mid = sma20
    lookback = 5
    expansion_up = np.zeros(n, dtype=float)
    expansion_down = np.zeros(n, dtype=float)
    for i in range(lookback, n):
        lower_falling = lower[i] < lower[i - lookback]
        upper_rising = upper[i] > upper[i - lookback]
        above_mid = close[i] > mid[i] if not np.isnan(mid[i]) else False
        below_mid = close[i] < mid[i] if not np.isnan(mid[i]) else False
        if lower_falling and above_mid:
            expansion_up[i] = 1.0
        if upper_rising and below_mid:
            expansion_down[i] = 1.0

    # ── BBW Rate of Change (5-day) ──
    bbw_roc_5d = np.full(n, np.nan)
    for i in range(5, n):
        if bbw[i - 5] > 0 and not np.isnan(bbw[i]) and not np.isnan(bbw[i - 5]):
            bbw_roc_5d[i] = (bbw[i] - bbw[i - 5]) / bbw[i - 5] * 100

    # ── RSI-BB Divergence ──
    rsi_bb_div = np.full(n, np.nan)
    for i in range(5, n):
        rsi_slope = rsi14[i] - rsi14[i - 5] if not np.isnan(rsi14[i]) and not np.isnan(rsi14[i - 5]) else 0
        price_vs_ma = (close[i] - sma20[i]) / sma20[i] * 100 if sma20[i] > 0 and not np.isnan(sma20[i]) else 0
        # Divergence: RSI falling while price above MA (bearish) or RSI rising while price below MA (bullish)
        rsi_bb_div[i] = rsi_slope * -1.0 * np.sign(price_vs_ma) if price_vs_ma != 0 else 0

    return {
        "percent_b": percent_b,
        "cmf": cmf,
        "mfi": mfi,
        "ii_pct": ii_pct,
        "ad_pct": ad_pct,
        "vwmacd_hist": vwmacd_hist,
        "expansion_up": expansion_up,
        "expansion_down": expansion_down,
        "bbw_roc_5d": bbw_roc_5d,
        "rsi_bb_divergence": rsi_bb_div,
    }


# ─────────────────────────────────────────────────────────────────
#  PUBLIC API — Training
# ─────────────────────────────────────────────────────────────────

def compute_boost_features_train(ind: dict, i: int) -> dict:
    """
    Extract the 10 boosted features at bar index i from pre-computed arrays.
    Called by trainer._extract_features() after computing extra arrays.
    """
    if i < 60:
        return {}

    def _safe(arr, idx):
        if idx < 0 or idx >= len(arr):
            return np.nan
        v = arr[idx]
        return float(v) if not np.isnan(v) else np.nan

    return {
        "percent_b":        _safe(ind["percent_b"], i),
        "cmf":              _safe(ind["cmf"], i),
        "mfi":              _safe(ind["mfi"], i),
        "ii_pct":           _safe(ind["ii_pct"], i),
        "ad_pct":           _safe(ind["ad_pct"], i),
        "vwmacd_hist":      _safe(ind["vwmacd_hist"], i),
        "expansion_up":     _safe(ind["expansion_up"], i),
        "expansion_down":   _safe(ind["expansion_down"], i),
        "bbw_roc_5d":       _safe(ind["bbw_roc_5d"], i),
        "rsi_bb_divergence": _safe(ind["rsi_bb_divergence"], i),
    }


# ─────────────────────────────────────────────────────────────────
#  PUBLIC API — Inference (live pick dict)
# ─────────────────────────────────────────────────────────────────

def extract_boost_features_pick(pick: dict) -> dict:
    """
    Extract the 10 boosted features from a live Top Picks dict.
    At inference time these indicators already exist in pick["bb_data"]["indicators"]
    because bb_squeeze/indicators.py compute_all_indicators() ran during analysis.
    """
    bb = pick.get("bb_data", {})
    indicators = bb.get("indicators", {})

    price = pick.get("price", 0) or pick.get("current_price", 0)
    sma20 = indicators.get("sma20") or indicators.get("sma_20") or indicators.get("BB_Mid", 0)
    upper = indicators.get("upper_band") or indicators.get("upper") or indicators.get("BB_Upper", 0)
    lower = indicators.get("lower_band") or indicators.get("lower") or indicators.get("BB_Lower", 0)
    bbw = indicators.get("bbw") or indicators.get("bandwidth", 0)

    # Direct from computed indicators
    percent_b = indicators.get("Percent_B") or indicators.get("percent_b")
    if percent_b is None and upper and lower and upper != lower:
        percent_b = (price - lower) / (upper - lower)

    cmf = indicators.get("CMF") or indicators.get("cmf")
    mfi_val = indicators.get("MFI") or indicators.get("mfi")
    vwmacd_hist = indicators.get("VWMACD_Hist") or indicators.get("vwmacd_hist")
    ii_pct = indicators.get("II_Pct") or indicators.get("ii_pct")
    ad_pct = indicators.get("AD_Pct") or indicators.get("ad_pct")

    exp_up = indicators.get("Expansion_Up") or indicators.get("expansion_up")
    exp_down = indicators.get("Expansion_Down") or indicators.get("expansion_down")
    expansion_up = 1.0 if exp_up else 0.0
    expansion_down = 1.0 if exp_down else 0.0

    # Engineered: BBW rate of change (need prior BBW — use slope proxy)
    bbw_roc = indicators.get("bbw_roc_5d")
    if bbw_roc is None:
        sma20_slope = indicators.get("sma20_slope")
        bbw_roc = None  # will be NaN in model — XGBoost handles natively

    # Engineered: RSI-BB divergence
    rsi_slope = indicators.get("rsi_slope") or indicators.get("rsi14_slope_5d", 0)
    price_vs_ma = (price - sma20) / sma20 * 100 if sma20 and sma20 > 0 else 0
    rsi_bb_div = rsi_slope * -1.0 * (1 if price_vs_ma > 0 else -1 if price_vs_ma < 0 else 0) if rsi_slope else None

    return {
        "percent_b":        percent_b,
        "cmf":              cmf,
        "mfi":              mfi_val,
        "ii_pct":           ii_pct,
        "ad_pct":           ad_pct,
        "vwmacd_hist":      vwmacd_hist,
        "expansion_up":     expansion_up,
        "expansion_down":   expansion_down,
        "bbw_roc_5d":       bbw_roc,
        "rsi_bb_divergence": rsi_bb_div,
    }
