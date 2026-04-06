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
# COMPOSITE INDICATOR CALCULATION
# ═══════════════════════════════════════════════════════════════

def compute_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Master function: calculates ALL 7 indicators for a stock DataFrame.
    Input df must have: Open, High, Low, Close, Volume columns.
    Returns enriched DataFrame with all indicator columns added.
    """
    close  = df["Close"].astype(float)
    high   = df["High"].astype(float)
    low    = df["Low"].astype(float)
    volume = df["Volume"].astype(float)

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

    return df
