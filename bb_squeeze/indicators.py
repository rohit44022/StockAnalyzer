"""
indicators.py — All technical indicator calculations.
Based on: Bollinger on Bollinger Bands, John Bollinger CFA CMT
Method I: Volatility Breakout — Chapters 15, 16 & 18
"""

import numpy as np
import pandas as pd
from bb_squeeze.config import (
    BB_PERIOD, BB_STD_DEV,
    BBW_LOOKBACK, BBW_TRIGGER,
    PERCENT_B_UPPER, PERCENT_B_MID, PERCENT_B_LOWER,
    SAR_INIT_AF, SAR_STEP_AF, SAR_MAX_AF,
    VOLUME_SMA_PERIOD,
    CMF_PERIOD,
    MFI_PERIOD,
    II_NORM_PERIOD, AD_NORM_PERIOD,
    VWMACD_FAST, VWMACD_SLOW, VWMACD_SIGNAL,
    EXPANSION_LOOKBACK,
    NORM_RSI_PERIOD, NORM_RSI_BB_LEN, NORM_RSI_BB_STD,
    NORM_MFI_BB_LEN, NORM_MFI_BB_STD,
    KC_EMA_PERIOD, KC_ATR_PERIOD, KC_ATR_MULT,
    KC_SQUEEZE_LOOKBACK, KC_SQUEEZE_MIN_BARS,
    WIDTH_LENGTH_ANCHORS, WIDTH_LENGTH_MIN, WIDTH_LENGTH_MAX,
    BB_USE_TYPICAL_PRICE,
    VPT_SIGNAL_PERIOD,
    BBOX_MIN_SWINGS, BBOX_LOOKBACK,
    M4_WALK_LEG_MIN_BARS, M4_WALK_EXPECTED_LEGS,
)


# ═══════════════════════════════════════════════════════════════
# GROUP A — BOLLINGER BANDS
# ═══════════════════════════════════════════════════════════════

def width_length_std_dev(period: int) -> float:
    """Rule 11, p.184: piecewise-linear through book anchors (10→1.9, 20→2.0, 50→2.1)."""
    anchors = WIDTH_LENGTH_ANCHORS
    if len(anchors) < 2:
        return BB_STD_DEV
    raw = anchors[0][1]  # safe default
    if period <= anchors[0][0]:
        denom = anchors[1][0] - anchors[0][0]
        slope = (anchors[1][1] - anchors[0][1]) / denom if denom else 0
        raw = anchors[0][1] + slope * (period - anchors[0][0])
    elif period >= anchors[-1][0]:
        denom = anchors[-1][0] - anchors[-2][0]
        slope = (anchors[-1][1] - anchors[-2][1]) / denom if denom else 0
        raw = anchors[-1][1] + slope * (period - anchors[-1][0])
    else:
        for i in range(len(anchors) - 1):
            if anchors[i][0] <= period <= anchors[i + 1][0]:
                denom = anchors[i + 1][0] - anchors[i][0]
                t = (period - anchors[i][0]) / denom if denom else 0
                raw = anchors[i][1] + t * (anchors[i + 1][1] - anchors[i][1])
                break
    return max(WIDTH_LENGTH_MIN, min(WIDTH_LENGTH_MAX, raw))


def bollinger_bands(close: pd.Series, period: int = BB_PERIOD,
                    std_dev: float = BB_STD_DEV,
                    high: pd.Series = None, low: pd.Series = None,
                    use_typical_price: bool = BB_USE_TYPICAL_PRICE,
                    auto_std: bool = False):
    """
    Bollinger Bands (SMA-based). Population std dev (ddof=0).
    use_typical_price=True → (H+L+C)/3 instead of close (Ch.7).
    auto_std=True → Rule 11 width-length auto-adjustment.
    """
    if use_typical_price and high is not None and low is not None:
        source = (high + low + close) / 3.0
    else:
        source = close
    if auto_std:
        std_dev = width_length_std_dev(period)
    mid   = source.rolling(window=period).mean()
    sigma = source.rolling(window=period).std(ddof=0)
    upper = mid + std_dev * sigma
    lower = mid - std_dev * sigma
    return mid, upper, lower


def bandwidth(mid: pd.Series, upper: pd.Series, lower: pd.Series) -> pd.Series:
    """
    BandWidth (BBW) = (Upper - Lower) / Middle
    This is the ONLY indicator that actually measures the squeeze.
    When it reaches a 6-month lowest point → Squeeze is SET.
    """
    return (upper - lower) / mid


def percent_b(close: pd.Series, upper: pd.Series, lower: pd.Series) -> pd.Series:
    """
    %b = (Close - Lower) / (Upper - Lower)
    1.0 = top of band, 0.0 = bottom, 0.5 = middle
    """
    band_range = upper - lower
    # Avoid division by zero in extremely flat periods
    band_range = band_range.replace(0, np.nan)
    return ((close - lower) / band_range).fillna(0.5)


def is_squeeze(bbw: pd.Series, lookback: int = BBW_LOOKBACK) -> pd.Series:
    """
    Squeeze is ON when BBW is at or near its 6-month lowest value.
    Book-faithful: dynamic rolling minimum only (absolute trigger removed).
    """
    rolling_min = bbw.rolling(window=lookback, min_periods=60).min()
    return bbw <= (rolling_min * 1.05)


# ═══════════════════════════════════════════════════════════════
# GROUP A — PARABOLIC SAR
# ═══════════════════════════════════════════════════════════════

def parabolic_sar(high: pd.Series, low: pd.Series,
                  init_af: float = SAR_INIT_AF,
                  step_af: float = SAR_STEP_AF,
                  max_af:  float = SAR_MAX_AF) -> pd.Series:
    """
    Parabolic SAR — automatic trailing stop loss.
    Dots BELOW candles = uptrend (hold).
    Dots ABOVE candles = downtrend (exit/do not buy).
    """
    n    = len(high)
    sar  = np.full(n, np.nan)
    bull = np.full(n, True, dtype=bool)   # True = uptrend
    af   = np.full(n, init_af)
    ep   = np.full(n, np.nan)             # Extreme point

    # Initialise
    bull[0] = True
    sar[0]  = float(low.iloc[0])
    ep[0]   = float(high.iloc[0])
    af[0]   = init_af

    high_arr = high.to_numpy(dtype=float)
    low_arr  = low.to_numpy(dtype=float)

    for i in range(1, n):
        prev_sar  = sar[i - 1]
        prev_bull = bull[i - 1]
        prev_ep   = ep[i - 1]
        prev_af   = af[i - 1]

        # Calculate new SAR
        new_sar = prev_sar + prev_af * (prev_ep - prev_sar)

        if prev_bull:
            # Uptrend: SAR must not be above the two prior lows
            new_sar = min(new_sar, low_arr[i - 1])
            if i >= 2:
                new_sar = min(new_sar, low_arr[i - 2])

            if low_arr[i] < new_sar:
                # Trend reversal → downtrend
                bull[i] = False
                sar[i]  = prev_ep
                ep[i]   = low_arr[i]
                af[i]   = init_af
            else:
                bull[i] = True
                sar[i]  = new_sar
                if high_arr[i] > prev_ep:
                    ep[i] = high_arr[i]
                    af[i] = min(prev_af + step_af, max_af)
                else:
                    ep[i] = prev_ep
                    af[i] = prev_af
        else:
            # Downtrend: SAR must not be below the two prior highs
            new_sar = max(new_sar, high_arr[i - 1])
            if i >= 2:
                new_sar = max(new_sar, high_arr[i - 2])

            if high_arr[i] > new_sar:
                # Trend reversal → uptrend
                bull[i] = True
                sar[i]  = prev_ep
                ep[i]   = high_arr[i]
                af[i]   = init_af
            else:
                bull[i] = False
                sar[i]  = new_sar
                if low_arr[i] < prev_ep:
                    ep[i] = low_arr[i]
                    af[i] = min(prev_af + step_af, max_af)
                else:
                    ep[i] = prev_ep
                    af[i] = prev_af

    result = pd.Series(sar, index=high.index, name="SAR")
    bull_s = pd.Series(bull, index=high.index, name="SAR_Bull")
    return result, bull_s


# ═══════════════════════════════════════════════════════════════
# GROUP A — VOLUME SMA
# ═══════════════════════════════════════════════════════════════

def volume_sma(volume: pd.Series, period: int = VOLUME_SMA_PERIOD) -> pd.Series:
    """50-period SMA of volume — the yellow reference line."""
    return volume.rolling(window=period).mean()


def volume_is_above_sma(volume: pd.Series, vol_sma: pd.Series) -> pd.Series:
    """Returns True when volume > 50-period SMA (above yellow line)."""
    return volume > vol_sma


# ═══════════════════════════════════════════════════════════════
# GROUP C — CMF (CHAIKIN MONEY FLOW)
# ═══════════════════════════════════════════════════════════════

def chaikin_money_flow(high: pd.Series, low: pd.Series,
                       close: pd.Series, volume: pd.Series,
                       period: int = CMF_PERIOD) -> pd.Series:
    """
    CMF = Sum(MFV, period) / Sum(Volume, period)
    MFV (Money Flow Volume) = ((Close - Low) - (High - Close)) / (High - Low) × Volume
    Reveals what BIG players are doing while price is sleeping during the squeeze.
    """
    hl_range = (high - low).replace(0, np.nan)
    mfm      = ((close - low) - (high - close)) / hl_range   # Money Flow Multiplier
    mfv      = (mfm * volume).fillna(0)                        # Money Flow Volume; no-trade bars (H==L) contribute 0
    cmf      = mfv.rolling(window=period).sum() / volume.rolling(window=period).sum()
    return cmf.fillna(0.0).rename("CMF")


# ═══════════════════════════════════════════════════════════════
# GROUP C — MFI (MONEY FLOW INDEX)
# ═══════════════════════════════════════════════════════════════

def money_flow_index(high: pd.Series, low: pd.Series,
                     close: pd.Series, volume: pd.Series,
                     period: int = MFI_PERIOD) -> pd.Series:
    """
    MFI — Money Flow Index (period=10 as per the book — half of BB period).
    Combines price direction AND volume → the breakout fuel gauge.
    MFI > 80 on breakout = very strong signal.
    MFI < 50 on upside breakout = weak / likely fake.
    """
    typical_price = (high + low + close) / 3.0
    raw_mf        = typical_price * volume

    pos_mf = raw_mf.where(typical_price > typical_price.shift(1), 0.0)
    neg_mf = raw_mf.where(typical_price < typical_price.shift(1), 0.0)

    pos_sum = pos_mf.rolling(window=period).sum()
    neg_sum = neg_mf.rolling(window=period).sum()

    # Avoid division by zero
    neg_sum_safe = neg_sum.replace(0, np.nan)
    mfr  = pos_sum / neg_sum_safe
    mfi  = 100 - (100 / (1 + mfr))
    return mfi.fillna(50.0).rename("MFI")


# ═══════════════════════════════════════════════════════════════
# GROUP D — INTRADAY INTENSITY (II) — Book Ch.18 Table 18.3
# II = (2*Close − High − Low) / (High − Low) × Volume
# II% = normalised oscillator (Table 18.4)
# ═══════════════════════════════════════════════════════════════

def intraday_intensity(high: pd.Series, low: pd.Series,
                       close: pd.Series, volume: pd.Series) -> pd.Series:
    """
    Intraday Intensity (open form) — Book Ch.18 Table 18.3.
    Measures intraperiod money flow based on where the close falls
    within the high-low range, weighted by volume.
    """
    hl_range = (high - low).replace(0, np.nan)
    ii = ((2.0 * close - high - low) / hl_range) * volume
    return ii.fillna(0.0).rename("II")


def intraday_intensity_pct(ii: pd.Series, volume: pd.Series,
                           period: int = II_NORM_PERIOD) -> pd.Series:
    """
    II% — Normalised Intraday Intensity oscillator (Table 18.4).
    II% = sum(II, period) / sum(Volume, period)
    Positive = accumulation. Negative = distribution.
    Used in Method III buy rule: %b < 0.05 AND II% > 0.
    """
    vol_sum = volume.rolling(window=period).sum().replace(0, np.nan)
    ii_pct = ii.rolling(window=period).sum() / vol_sum
    return ii_pct.fillna(0.0).rename("II_Pct")


# ═══════════════════════════════════════════════════════════════
# GROUP D — ACCUMULATION DISTRIBUTION (AD) — Book Ch.18 Table 18.3
# AD = (Close − Open) / (High − Low) × Volume
# AD% = normalised oscillator (Table 18.4)
# ═══════════════════════════════════════════════════════════════

def accumulation_distribution(high: pd.Series, low: pd.Series,
                              close: pd.Series, open_price: pd.Series,
                              volume: pd.Series) -> pd.Series:
    """
    Accumulation Distribution (open form) — Book Ch.18 Table 18.3.
    Uses the open-to-close relationship (requires Open data).
    Positive when close > open (buying). Negative when close < open.
    """
    hl_range = (high - low).replace(0, np.nan)
    ad = ((close - open_price) / hl_range) * volume
    return ad.fillna(0.0).rename("AD")


def accumulation_distribution_pct(ad: pd.Series, volume: pd.Series,
                                  period: int = AD_NORM_PERIOD) -> pd.Series:
    """
    AD% — Normalised Accumulation Distribution oscillator (Table 18.4).
    AD% = sum(AD, period) / sum(Volume, period)
    Used in Method III sell rule: %b > 0.95 AND AD% < 0.
    """
    vol_sum = volume.rolling(window=period).sum().replace(0, np.nan)
    ad_pct = ad.rolling(window=period).sum() / vol_sum
    return ad_pct.fillna(0.0).rename("AD_Pct")


# ═══════════════════════════════════════════════════════════════
# GROUP D — VOLUME-WEIGHTED MACD (VWMACD) — Book Ch.18 Table 18.3
# VWMACD = 12-period VW avg of last − 26-period VW avg of last
# Signal = 9-period EMA of VWMACD
# ═══════════════════════════════════════════════════════════════

def _volume_weighted_avg(close: pd.Series, volume: pd.Series,
                         period: int) -> pd.Series:
    """n-day volume-weighted average = sum(close × volume, n) / sum(volume, n)."""
    cv = (close * volume).rolling(window=period).sum()
    v  = volume.rolling(window=period).sum().replace(0, np.nan)
    return cv / v


def volume_weighted_macd(close: pd.Series, volume: pd.Series,
                         fast: int = VWMACD_FAST,
                         slow: int = VWMACD_SLOW,
                         signal_period: int = VWMACD_SIGNAL):
    """
    VWMACD — Book Ch.18 Table 18.3.
    Closed-form volume indicator that acts like MACD but weights by volume.
    Returns: vwmacd line, signal line, histogram.
    """
    vw_fast = _volume_weighted_avg(close, volume, fast)
    vw_slow = _volume_weighted_avg(close, volume, slow)
    vwmacd  = vw_fast - vw_slow
    signal  = vwmacd.ewm(span=signal_period, adjust=False).mean()
    hist    = vwmacd - signal
    return (vwmacd.rename("VWMACD"),
            signal.rename("VWMACD_Signal"),
            hist.rename("VWMACD_Hist"))


# ═══════════════════════════════════════════════════════════════
# GROUP E — EXPANSION DETECTION — Book Ch.15 p.123
# "When a powerful trend is born, volatility expands so much that
#  the lower band turns down in an uptrend or the upper band turns
#  up in a downtrend."  When the Expansion REVERSES → trend likely
#  at an end.
# ═══════════════════════════════════════════════════════════════

def detect_expansion(upper: pd.Series, lower: pd.Series,
                     close: pd.Series, mid: pd.Series,
                     lookback: int = EXPANSION_LOOKBACK):
    """
    Detect Bollinger Band Expansion and its reversal.

    Returns:
      expansion_up   — True when lower band is falling while close > mid (uptrend Expansion)
      expansion_down — True when upper band is rising while close < mid (downtrend Expansion)
      expansion_end  — True when a prior Expansion reverses (end-of-trend warning)
    """
    lower_falling = lower.diff(lookback) < 0   # lower band turned down
    upper_rising  = upper.diff(lookback) > 0   # upper band turned up
    above_mid     = close > mid
    below_mid     = close < mid

    expansion_up   = lower_falling & above_mid
    expansion_down = upper_rising  & below_mid

    # Expansion reversal: was expanding, now contracting
    prev_exp_up   = expansion_up.shift(1).fillna(False).astype(bool)
    prev_exp_down = expansion_down.shift(1).fillna(False).astype(bool)
    lower_recovering = lower.diff(lookback) >= 0
    upper_recovering = upper.diff(lookback) <= 0

    end_up   = prev_exp_up   & lower_recovering   # uptrend Expansion ending
    end_down = prev_exp_down & upper_recovering   # downtrend Expansion ending
    expansion_end = end_up | end_down

    return (expansion_up.rename("Expansion_Up"),
            expansion_down.rename("Expansion_Down"),
            expansion_end.rename("Expansion_End"))


# ═══════════════════════════════════════════════════════════════
# GROUP E — RSI (for normalisation) — Wilder's formula
# ═══════════════════════════════════════════════════════════════

def rsi(close: pd.Series, period: int = NORM_RSI_PERIOD) -> pd.Series:
    """RSI — Relative Strength Index (Wilder's smoothing)."""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100.0 - (100.0 / (1.0 + rs))).fillna(50.0).rename("RSI")


# ═══════════════════════════════════════════════════════════════
# GROUP E — INDICATOR NORMALISATION — Book Ch.21 Table 21.1
# Apply Bollinger Bands to indicators for adaptive OB/OS levels.
# %b(indicator) = (indicator − ind_lower) / (ind_upper − ind_lower)
# ═══════════════════════════════════════════════════════════════

def normalize_indicator(indicator: pd.Series, bb_len: int,
                        bb_std: float) -> pd.Series:
    """
    Normalise any indicator using Bollinger Bands (Book Ch.21 Table 21.2).
    Returns %b of the indicator: 1.0 = at upper band (overbought),
    0.0 = at lower band (oversold), adapts to current regime.
    """
    mid   = indicator.rolling(window=bb_len).mean()
    sigma = indicator.rolling(window=bb_len).std(ddof=0)
    upper = mid + bb_std * sigma
    lower = mid - bb_std * sigma
    band_range = (upper - lower).replace(0, np.nan)
    return ((indicator - lower) / band_range).fillna(0.5)


# ═══════════════════════════════════════════════════════════════
# VOLUME-PRICE TREND (Book Ch.18 — 7th of 8 indicators)
# ═══════════════════════════════════════════════════════════════

def volume_price_trend(close: pd.Series, volume: pd.Series,
                       signal_period: int = VPT_SIGNAL_PERIOD):
    """VPT = cumsum(volume × pct_change). Signal = EMA(VPT)."""
    pct = close.pct_change().fillna(0)
    vpt = (volume * pct).cumsum()
    signal = vpt.ewm(span=signal_period, adjust=False).mean()
    return vpt, signal


# ═══════════════════════════════════════════════════════════════
# FIVE-POINT MERRILL PATTERNS (Book Ch.11, pp.84-95)
# 16 W types (M1-M16) + 16 M types (W1-W16)
# Each pattern: 5 consecutive swing points classified by shape.
# ═══════════════════════════════════════════════════════════════

MERRILL_W_PATTERNS = {
    "W1":  (1, -1, 1, -1, 1),   "W2":  (1, -1, 1, 1, -1),
    "W3":  (1, -1, -1, 1, 1),   "W4":  (1, -1, -1, 1, -1),
    "W5":  (1, -1, -1, -1, 1),  "W6":  (1, 1, -1, -1, 1),
    "W7":  (1, 1, -1, 1, -1),   "W8":  (1, 1, -1, -1, -1),
    "W9":  (1, 1, 1, -1, -1),   "W10": (1, 1, -1, 1, 1),
    "W11": (-1, 1, -1, 1, 1),   "W12": (-1, 1, -1, -1, 1),
    "W13": (-1, 1, 1, -1, 1),   "W14": (-1, -1, 1, -1, 1),
    "W15": (-1, -1, 1, 1, -1),  "W16": (-1, -1, -1, 1, 1),
}

MERRILL_M_PATTERNS = {
    "M1":  (-1, 1, -1, 1, -1),  "M2":  (-1, 1, -1, -1, 1),
    "M3":  (-1, 1, 1, -1, -1),  "M4":  (-1, 1, 1, -1, 1),
    "M5":  (-1, 1, 1, 1, -1),   "M6":  (-1, -1, 1, 1, -1),
    "M7":  (-1, -1, 1, -1, 1),  "M8":  (-1, -1, 1, 1, 1),
    "M9":  (-1, -1, -1, 1, 1),  "M10": (-1, -1, 1, -1, -1),
    "M11": (1, -1, 1, -1, -1),  "M12": (1, -1, 1, 1, -1),
    "M13": (1, -1, -1, 1, -1),  "M14": (1, 1, -1, 1, -1),
    "M15": (1, 1, -1, -1, 1),   "M16": (1, 1, 1, -1, -1),
}


def _extract_swings(values: np.ndarray, order: int = 2):
    """Extract swing highs and lows as (index, value, type) tuples."""
    swings = []
    for i in range(order, len(values) - order):
        window = values[i - order:i + order + 1]
        if values[i] == window.max() and np.sum(window == window.max()) == 1:
            swings.append((i, values[i], 1))   # swing high
        elif values[i] == window.min() and np.sum(window == window.min()) == 1:
            swings.append((i, values[i], -1))  # swing low
    return swings


def detect_merrill_five_point(pct_b: np.ndarray, lookback: int = 40) -> list:
    """
    Classify last 5 swing points into one of Merrill's 32 patterns.
    Returns list of (pattern_name, pattern_type, swing_indices).
    """
    if len(pct_b) < lookback:
        return []
    window = pct_b[-lookback:]
    swings = _extract_swings(window)
    if len(swings) < 5:
        return []

    results = []
    for start in range(len(swings) - 4):
        five = swings[start:start + 5]
        signature = tuple(s[2] for s in five)
        indices = [s[0] for s in five]

        for name, pat in MERRILL_W_PATTERNS.items():
            if signature == pat:
                results.append((name, "W", indices))
                break
        else:
            for name, pat in MERRILL_M_PATTERNS.items():
                if signature == pat:
                    results.append((name, "M", indices))
                    break
    return results


# ═══════════════════════════════════════════════════════════════
# HEAD-AND-SHOULDERS DECOMPOSITION (Book Ch.13, pp.105-110)
# Decompose into M-building-blocks: LS-H-RS with %b declining.
# ═══════════════════════════════════════════════════════════════

def detect_head_shoulders(pct_b: np.ndarray, prices: np.ndarray,
                          lookback: int = 50) -> list:
    """
    Detect head-and-shoulders as three highs where the middle is highest
    and %b declines from left shoulder to right shoulder.
    Returns list of dicts with pattern info.
    """
    if len(pct_b) < lookback or len(prices) < lookback:
        return []
    w_pctb = pct_b[-lookback:]
    w_price = prices[-lookback:]
    swings = _extract_swings(w_price, order=3)
    highs = [(i, v) for i, v, t in swings if t == 1]
    if len(highs) < 3:
        return []

    results = []
    for a in range(len(highs) - 2):
        ls_i, ls_v = highs[a]
        for b in range(a + 1, len(highs) - 1):
            h_i, h_v = highs[b]
            for c in range(b + 1, len(highs)):
                rs_i, rs_v = highs[c]
                if h_v <= ls_v or h_v <= rs_v:
                    continue
                if abs(ls_v - rs_v) / max(h_v, 1e-9) > 0.05:
                    continue
                ls_pctb = w_pctb[ls_i] if ls_i < len(w_pctb) else 0.5
                rs_pctb = w_pctb[rs_i] if rs_i < len(w_pctb) else 0.5
                if rs_pctb < ls_pctb:
                    results.append({
                        "type": "HEAD_AND_SHOULDERS",
                        "ls_idx": ls_i, "head_idx": h_i, "rs_idx": rs_i,
                        "ls_pctb": float(ls_pctb), "rs_pctb": float(rs_pctb),
                        "pctb_decline": float(ls_pctb - rs_pctb),
                    })
    return results[-1:] if results else []


# ═══════════════════════════════════════════════════════════════
# BOLLINGER BOXES (Book Ch.11)
# A consolidation range defined by BB extremes during a squeeze.
# ═══════════════════════════════════════════════════════════════

def detect_bollinger_boxes(df: pd.DataFrame, lookback: int = BBOX_LOOKBACK,
                           min_swings: int = BBOX_MIN_SWINGS) -> list:
    """
    Detect price consolidation boxes bounded by BB upper/lower during squeeze.
    Returns list of dicts with box bounds and breakout status.
    """
    if len(df) < lookback:
        return []
    window = df.iloc[-lookback:]
    squeeze_mask = window.get("Squeeze_ON", pd.Series([False] * len(window)))
    if not squeeze_mask.any():
        return []

    squeeze_runs = []
    start = None
    for i, sq in enumerate(squeeze_mask.values):
        if sq and start is None:
            start = i
        elif not sq and start is not None:
            if i - start >= min_swings:
                squeeze_runs.append((start, i))
            start = None
    if start is not None and len(window) - start >= min_swings:
        squeeze_runs.append((start, len(window)))

    results = []
    for s, e in squeeze_runs:
        seg = window.iloc[s:e]
        box_top = float(seg["BB_Upper"].max())
        box_bot = float(seg["BB_Lower"].min())
        last_close = float(window.iloc[-1]["Close"])
        breakout = "UPPER" if last_close > box_top else (
            "LOWER" if last_close < box_bot else "INSIDE")
        results.append({
            "type": "BOLLINGER_BOX",
            "start": s, "end": e, "bars": e - s,
            "top": box_top, "bottom": box_bot,
            "breakout": breakout,
        })
    return results


# ═══════════════════════════════════════════════════════════════
# 3-LEG WALK DETECTION (Elliott convention, Book Ch.14)
# ═══════════════════════════════════════════════════════════════

def detect_walk_legs(pct_b: np.ndarray, direction: str = "upper",
                     min_leg_bars: int = M4_WALK_LEG_MIN_BARS) -> int:
    """
    Count legs in a walk along the band. A leg = consecutive bars where
    %b stays in the extreme zone, separated by brief pullbacks.
    """
    if direction == "upper":
        in_zone = pct_b > 0.75
    else:
        in_zone = pct_b < 0.25

    legs = 0
    in_leg = False
    leg_bars = 0
    for val in in_zone:
        if val:
            if not in_leg:
                in_leg = True
                leg_bars = 1
            else:
                leg_bars += 1
        else:
            if in_leg and leg_bars >= min_leg_bars:
                legs += 1
            in_leg = False
            leg_bars = 0
    if in_leg and leg_bars >= min_leg_bars:
        legs += 1
    return legs


# ═══════════════════════════════════════════════════════════════
# COMPOSITE INDICATOR CALCULATION
# ═══════════════════════════════════════════════════════════════

def compute_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Master function: calculates ALL indicators for a stock DataFrame.
    Input df must have: Open, High, Low, Close, Volume columns.
    Returns enriched DataFrame with all indicator columns added.

    Indicator groups (all per "Bollinger on Bollinger Bands"):
      A — Bollinger Bands, %b, BandWidth, Squeeze, Parabolic SAR
      B — Volume SMA
      C — CMF, MFI  (existing)
      D — II, II%, AD, AD%, VWMACD, VPT  (Book Ch.18)
      E — Expansion, RSI, Normalised RSI/MFI  (Book Ch.15, Ch.21)
    """
    close  = df["Close"].astype(float)
    high   = df["High"].astype(float)
    low    = df["Low"].astype(float)
    volume = df["Volume"].astype(float)
    open_price = df["Open"].astype(float) if "Open" in df.columns else close

    # ── Bollinger Bands ──
    mid, upper, lower = bollinger_bands(close)
    df["BB_Mid"]   = mid
    df["BB_Upper"] = upper
    df["BB_Lower"] = lower

    # ── Bandwidth & %b ──
    bbw = bandwidth(mid, upper, lower)
    df["BBW"]         = bbw
    df["Percent_B"]   = percent_b(close, upper, lower)
    df["Squeeze_ON"]  = is_squeeze(bbw)

    # Rolling 6-month min BBW for context display
    df["BBW_6M_Min"]  = bbw.rolling(window=BBW_LOOKBACK, min_periods=60).min()

    # ── Parabolic SAR ──
    sar, sar_bull = parabolic_sar(high, low)
    df["SAR"]      = sar
    df["SAR_Bull"] = sar_bull   # True = dots below candles = uptrend

    # ── Volume SMA ──
    vol_sma = volume_sma(volume)
    df["Vol_SMA50"]       = vol_sma
    df["Vol_Above_SMA"]   = volume > vol_sma

    # ── CMF ──
    df["CMF"] = chaikin_money_flow(high, low, close, volume)

    # ── MFI ──
    df["MFI"] = money_flow_index(high, low, close, volume)

    # ── Intraday Intensity (Book Ch.18 Table 18.3) ──
    ii_raw = intraday_intensity(high, low, close, volume)
    df["II"]     = ii_raw
    df["II_Pct"] = intraday_intensity_pct(ii_raw, volume)

    # ── Accumulation Distribution (Book Ch.18 Table 18.3) ──
    ad_raw = accumulation_distribution(high, low, close, open_price, volume)
    df["AD"]     = ad_raw
    df["AD_Pct"] = accumulation_distribution_pct(ad_raw, volume)

    # ── Volume-Weighted MACD (Book Ch.18 Table 18.3) ──
    vwmacd_line, vwmacd_sig, vwmacd_hist = volume_weighted_macd(close, volume)
    df["VWMACD"]        = vwmacd_line
    df["VWMACD_Signal"] = vwmacd_sig
    df["VWMACD_Hist"]   = vwmacd_hist

    # ── Volume-Price Trend (Book Ch.18 — 7th of 8 indicators) ──
    vpt_line, vpt_sig = volume_price_trend(close, volume)
    df["VPT"] = vpt_line
    df["VPT_Signal"] = vpt_sig

    # ── Expansion Detection (Book Ch.15 p.123) ──
    exp_up, exp_down, exp_end = detect_expansion(upper, lower, close, mid)
    df["Expansion_Up"]   = exp_up
    df["Expansion_Down"] = exp_down
    df["Expansion_End"]  = exp_end

    # ── RSI (for normalisation — Book Ch.21) ──
    rsi_series = rsi(close)
    df["RSI"] = rsi_series

    # ── Normalised Indicators (Book Ch.21 Table 21.1) ──
    df["RSI_Norm"] = normalize_indicator(rsi_series, NORM_RSI_BB_LEN, NORM_RSI_BB_STD)
    df["MFI_Norm"] = normalize_indicator(df["MFI"], NORM_MFI_BB_LEN, NORM_MFI_BB_STD)

    # ── Keltner Channels & T7 Squeeze (additive — never modifies above) ──
    try:
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(KC_ATR_PERIOD).mean()
        df["ATR"] = atr

        kc_mid = close.ewm(span=KC_EMA_PERIOD, adjust=False).mean()
        kc_upper = kc_mid + KC_ATR_MULT * atr
        kc_lower = kc_mid - KC_ATR_MULT * atr
        df["KC_Mid"]   = kc_mid
        df["KC_Upper"] = kc_upper
        df["KC_Lower"] = kc_lower

        kc_sq = (upper < kc_upper) & (lower > kc_lower)
        df["KC_Squeeze"] = kc_sq.fillna(False)

        # Consecutive duration of KC squeeze
        groups = (kc_sq != kc_sq.shift()).cumsum()
        dur = kc_sq.groupby(groups).cumsum().astype(int)
        df["KC_Squeeze_Duration"] = dur

        # Had squeeze: ≥ KC_SQUEEZE_MIN_BARS consecutive True in last KC_SQUEEZE_LOOKBACK bars
        def _had_squeeze(s):
            if len(s) < KC_SQUEEZE_MIN_BARS:
                return False
            return int(s.max()) >= KC_SQUEEZE_MIN_BARS
        df["KC_Had_Squeeze"] = dur.rolling(
            window=KC_SQUEEZE_LOOKBACK, min_periods=1
        ).apply(_had_squeeze, raw=False).fillna(0).astype(bool)

        # Squeeze intensity: how much narrower BB is compared to KC
        kc_width = kc_upper - kc_lower
        bb_width = upper - lower
        intensity = (1 - bb_width / kc_width.replace(0, np.nan)).clip(0, 1)
        df["KC_Squeeze_Intensity"] = intensity.where(kc_sq, 0).fillna(0)
    except Exception:
        df["ATR"] = np.nan
        df["KC_Mid"] = np.nan
        df["KC_Upper"] = np.nan
        df["KC_Lower"] = np.nan
        df["KC_Squeeze"] = False
        df["KC_Squeeze_Duration"] = 0
        df["KC_Had_Squeeze"] = False
        df["KC_Squeeze_Intensity"] = 0.0

    # ── Filter columns (backtest-validated signal quality filters) ──
    df["BBW_Avg20"] = bbw.rolling(20).mean()
    df["BBW_Contracting"] = bbw < df["BBW_Avg20"]
    df["MA_Slope_5"] = mid > mid.shift(5)
    df["Vol_Ratio"] = (volume / vol_sma).where(vol_sma > 0, 0)

    return df
