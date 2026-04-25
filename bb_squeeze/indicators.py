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
)


# ═══════════════════════════════════════════════════════════════
# GROUP A — BOLLINGER BANDS
# ═══════════════════════════════════════════════════════════════

def bollinger_bands(close: pd.Series, period: int = BB_PERIOD, std_dev: float = BB_STD_DEV):
    """
    Calculate Bollinger Bands (SMA-based, as per the book).
    Uses POPULATION standard deviation (ddof=0) — the industry standard
    used by TradingView, Zerodha Kite, Screener.in, and most charting
    platforms. This ensures our breakout/squeeze signals match what
    traders see on their charts.

    Returns: middle, upper, lower bands as pd.Series
    """
    mid   = close.rolling(window=period).mean()
    sigma = close.rolling(window=period).std(ddof=0)   # population std — matches TradingView
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


def is_squeeze(bbw: pd.Series, lookback: int = BBW_LOOKBACK, trigger: float = BBW_TRIGGER) -> pd.Series:
    """
    Squeeze is ON when BBW is at or near its 6-month lowest value.
    Uses dynamic rolling minimum AND the absolute 0.08 trigger line.
    """
    rolling_min  = bbw.rolling(window=lookback, min_periods=60).min()
    # Squeeze condition: current BBW ≤ rolling 6-month min * 1.05 (5% tolerance)
    # OR current BBW ≤ absolute trigger value
    dynamic_squeeze  = bbw <= (rolling_min * 1.05)
    absolute_squeeze = bbw <= trigger
    return dynamic_squeeze | absolute_squeeze


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
    mfv      = mfm * volume                                    # Money Flow Volume
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
      D — II, II%, AD, AD%, VWMACD  (Book Ch.18 — NEW)
      E — Expansion, RSI, Normalised RSI/MFI  (Book Ch.15, Ch.21 — NEW)
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

    return df
