"""
indicators.py — Complete Technical Indicator Engine.

Computes EVERY indicator from Murphy's "Technical Analysis of the Financial
Markets" plus popular Indian-market indicators.  Uses standard pandas/numpy
— no external TA libraries required.

Every formula is annotated with its Murphy chapter reference.
"""

from __future__ import annotations

import math
import numpy as np
import pandas as pd

from technical_analysis.config import (
    SMA_PERIODS, EMA_PERIODS, RSI_PERIOD, MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    STOCH_K_PERIOD, STOCH_D_PERIOD, STOCH_SLOW,
    WILLR_PERIOD, CCI_PERIOD, ADX_PERIOD, ATR_PERIOD,
    ICHI_TENKAN, ICHI_KIJUN, ICHI_SENKOU_B, ICHI_DISPLACEMENT,
    KELTNER_PERIOD, KELTNER_ATR_MULT,
    SUPERTREND_PERIOD, SUPERTREND_MULT,
    AROON_PERIOD, OBV_SMA_PERIOD, VROC_PERIOD, VWAP_PERIOD,
)


# ═══════════════════════════════════════════════════════════════
#  HELPER
# ═══════════════════════════════════════════════════════════════

def _safe_val(v, decimals=4):
    """Return a JSON-safe float, handling NaN/Inf."""
    if v is None:
        return None
    if isinstance(v, (float, np.floating)):
        if math.isnan(v) or math.isinf(v):
            return None
        return round(float(v), decimals)
    return v


# ═══════════════════════════════════════════════════════════════
#  MOVING AVERAGES  (Murphy Ch 9)
# ═══════════════════════════════════════════════════════════════

def compute_sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=period, min_periods=period).mean()


def compute_ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def compute_all_moving_averages(df: pd.DataFrame) -> pd.DataFrame:
    """Add SMA and EMA columns for all standard periods."""
    for p in SMA_PERIODS:
        df[f"SMA_{p}"] = compute_sma(df["Close"], p)
    for p in EMA_PERIODS:
        df[f"EMA_{p}"] = compute_ema(df["Close"], p)
    return df


# ═══════════════════════════════════════════════════════════════
#  RSI — RELATIVE STRENGTH INDEX  (Murphy Ch 10, Wilder)
#  RSI = 100 - 100 / (1 + RS)
#  RS  = Average Gain / Average Loss over N periods
# ═══════════════════════════════════════════════════════════════

def compute_rsi(df: pd.DataFrame, period: int = RSI_PERIOD) -> pd.DataFrame:
    delta = df["Close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    # Wilder's smoothing (equivalent to EMA with alpha = 1/period)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["RSI"] = 100.0 - (100.0 / (1.0 + rs))
    # When avg_loss=0 (stock went up every day), RSI should be 100 (max strength)
    df["RSI"] = df["RSI"].fillna(100.0)
    return df


# ═══════════════════════════════════════════════════════════════
#  MACD  (Murphy Ch 10, Gerald Appel)
#  MACD Line   = EMA(12) - EMA(26)
#  Signal Line = EMA(9) of MACD Line
#  Histogram   = MACD - Signal
# ═══════════════════════════════════════════════════════════════

def compute_macd(df: pd.DataFrame) -> pd.DataFrame:
    ema_fast = compute_ema(df["Close"], MACD_FAST)
    ema_slow = compute_ema(df["Close"], MACD_SLOW)
    df["MACD"]        = ema_fast - ema_slow
    df["MACD_Signal"] = compute_ema(df["MACD"], MACD_SIGNAL)
    df["MACD_Hist"]   = df["MACD"] - df["MACD_Signal"]
    return df


# ═══════════════════════════════════════════════════════════════
#  STOCHASTIC OSCILLATOR  (Murphy Ch 10, George Lane)
#  %K = (Close - Lowest Low) / (Highest High - Lowest Low) × 100
#  %D = SMA of %K over D periods
#  Slow %K = %D;  Slow %D = SMA of Slow %K
# ═══════════════════════════════════════════════════════════════

def compute_stochastic(df: pd.DataFrame) -> pd.DataFrame:
    low_min = df["Low"].rolling(window=STOCH_K_PERIOD).min()
    high_max = df["High"].rolling(window=STOCH_K_PERIOD).max()
    denom = (high_max - low_min).replace(0, np.nan)

    fast_k = ((df["Close"] - low_min) / denom) * 100.0
    fast_d = fast_k.rolling(window=STOCH_D_PERIOD).mean()

    # Slow stochastic
    df["STOCH_K"] = fast_d.fillna(50.0)                       # Slow %K = Fast %D
    df["STOCH_D"] = df["STOCH_K"].rolling(window=STOCH_SLOW).mean().fillna(50.0)  # Slow %D
    return df


# ═══════════════════════════════════════════════════════════════
#  WILLIAMS %R  (Murphy Ch 10, Larry Williams)
#  %R = (Highest High - Close) / (Highest High - Lowest Low) × (-100)
# ═══════════════════════════════════════════════════════════════

def compute_williams_r(df: pd.DataFrame) -> pd.DataFrame:
    high_max = df["High"].rolling(window=WILLR_PERIOD).max()
    low_min = df["Low"].rolling(window=WILLR_PERIOD).min()
    denom = (high_max - low_min).replace(0, np.nan)
    df["WILLR"] = (((high_max - df["Close"]) / denom) * -100.0).fillna(-50.0)
    return df


# ═══════════════════════════════════════════════════════════════
#  CCI — COMMODITY CHANNEL INDEX  (Murphy Ch 10, Donald Lambert)
#  TP = (H + L + C) / 3
#  CCI = (TP - SMA(TP, N)) / (0.015 × Mean Deviation)
# ═══════════════════════════════════════════════════════════════

def compute_cci(df: pd.DataFrame) -> pd.DataFrame:
    tp = (df["High"] + df["Low"] + df["Close"]) / 3.0
    sma_tp = tp.rolling(window=CCI_PERIOD).mean()
    mad = tp.rolling(window=CCI_PERIOD).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    df["CCI"] = (tp - sma_tp) / (0.015 * mad.replace(0, np.nan))
    return df


# ═══════════════════════════════════════════════════════════════
#  ROC — RATE OF CHANGE  (Murphy Ch 10)
#  ROC = ((Close - Close_N) / Close_N) × 100
# ═══════════════════════════════════════════════════════════════

def compute_roc(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    prev = df["Close"].shift(period)
    df["ROC"] = ((df["Close"] - prev) / prev.replace(0, np.nan)) * 100.0
    return df


# ═══════════════════════════════════════════════════════════════
#  ADX / DMI  (Murphy Ch 10, Wilder)
#  +DM = max(High - PrevHigh, 0) if > max(PrevLow - Low, 0)
#  -DM = max(PrevLow - Low, 0) if > max(High - PrevHigh, 0)
#  TR  = max(H-L, |H-Cp|, |L-Cp|)
#  +DI = 100 × Smooth(+DM) / Smooth(TR)
#  -DI = 100 × Smooth(-DM) / Smooth(TR)
#  DX  = |+DI - -DI| / (+DI + -DI) × 100
#  ADX = Smooth(DX)
# ═══════════════════════════════════════════════════════════════

def compute_adx(df: pd.DataFrame, period: int = ADX_PERIOD) -> pd.DataFrame:
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    plus_dm = high.diff()
    minus_dm = -low.diff()

    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    plus_di = 100.0 * plus_dm.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean() / atr.replace(0, np.nan)
    minus_di = 100.0 * minus_dm.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean() / atr.replace(0, np.nan)

    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100.0
    adx = dx.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    df["PLUS_DI"] = plus_di
    df["MINUS_DI"] = minus_di
    df["ADX"] = adx
    return df


# ═══════════════════════════════════════════════════════════════
#  ATR — AVERAGE TRUE RANGE  (Wilder)
#  TR = max(H-L, |H-Cp|, |L-Cp|)
#  ATR = Wilder-smoothed TR
# ═══════════════════════════════════════════════════════════════

def compute_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.DataFrame:
    high = df["High"]
    low = df["Low"]
    prev_close = df["Close"].shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    df["ATR"] = tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    return df


# ═══════════════════════════════════════════════════════════════
#  OBV — ON BALANCE VOLUME  (Murphy Ch 7, Joe Granville)
#  If close > prev close: OBV += volume
#  If close < prev close: OBV -= volume
# ═══════════════════════════════════════════════════════════════

def compute_obv(df: pd.DataFrame) -> pd.DataFrame:
    direction = np.sign(df["Close"].diff())
    df["OBV"] = (direction * df["Volume"]).fillna(0).cumsum()
    df["OBV_SMA"] = df["OBV"].rolling(window=OBV_SMA_PERIOD).mean()
    return df


# ═══════════════════════════════════════════════════════════════
#  A/D LINE — ACCUMULATION/DISTRIBUTION  (Murphy Ch 7, Chaikin)
#  CLV = ((C - L) - (H - C)) / (H - L)
#  A/D = cumsum(CLV × Volume)
# ═══════════════════════════════════════════════════════════════

def compute_ad_line(df: pd.DataFrame) -> pd.DataFrame:
    hl = (df["High"] - df["Low"]).replace(0, np.nan)
    clv = ((df["Close"] - df["Low"]) - (df["High"] - df["Close"])) / hl
    df["AD_Line"] = (clv * df["Volume"]).fillna(0).cumsum()
    return df


# ═══════════════════════════════════════════════════════════════
#  VOLUME ROC  (Murphy Ch 7)
# ═══════════════════════════════════════════════════════════════

def compute_volume_roc(df: pd.DataFrame) -> pd.DataFrame:
    prev_vol = df["Volume"].shift(VROC_PERIOD)
    df["VROC"] = ((df["Volume"] - prev_vol) / prev_vol.replace(0, np.nan)) * 100.0
    return df


# ═══════════════════════════════════════════════════════════════
#  VWAP — VOLUME WEIGHTED AVERAGE PRICE
#  Rolling VWAP = cumsum(TP × Vol) / cumsum(Vol) over N periods
# ═══════════════════════════════════════════════════════════════

def compute_vwap(df: pd.DataFrame) -> pd.DataFrame:
    tp = (df["High"] + df["Low"] + df["Close"]) / 3.0
    tp_vol = tp * df["Volume"]
    df["VWAP"] = (
        tp_vol.rolling(window=VWAP_PERIOD).sum()
        / df["Volume"].rolling(window=VWAP_PERIOD).sum().replace(0, np.nan)
    )
    return df


# ═══════════════════════════════════════════════════════════════
#  ICHIMOKU CLOUD  (Hosoda)
# ═══════════════════════════════════════════════════════════════

def compute_ichimoku(df: pd.DataFrame) -> pd.DataFrame:
    # Tenkan-sen (Conversion) = (HH9 + LL9) / 2
    hh9 = df["High"].rolling(window=ICHI_TENKAN).max()
    ll9 = df["Low"].rolling(window=ICHI_TENKAN).min()
    df["ICHI_Tenkan"] = (hh9 + ll9) / 2.0

    # Kijun-sen (Base) = (HH26 + LL26) / 2
    hh26 = df["High"].rolling(window=ICHI_KIJUN).max()
    ll26 = df["Low"].rolling(window=ICHI_KIJUN).min()
    df["ICHI_Kijun"] = (hh26 + ll26) / 2.0

    # Senkou Span A = (Tenkan + Kijun) / 2, shifted forward 26 periods
    df["ICHI_SpanA"] = ((df["ICHI_Tenkan"] + df["ICHI_Kijun"]) / 2.0).shift(ICHI_DISPLACEMENT)

    # Senkou Span B = (HH52 + LL52) / 2, shifted forward 26 periods
    hh52 = df["High"].rolling(window=ICHI_SENKOU_B).max()
    ll52 = df["Low"].rolling(window=ICHI_SENKOU_B).min()
    df["ICHI_SpanB"] = ((hh52 + ll52) / 2.0).shift(ICHI_DISPLACEMENT)

    # Chikou Span = Close shifted BACK 26 periods
    df["ICHI_Chikou"] = df["Close"].shift(-ICHI_DISPLACEMENT)

    return df


# ═══════════════════════════════════════════════════════════════
#  KELTNER CHANNELS  (Raschke variant: EMA ± ATR×mult)
# ═══════════════════════════════════════════════════════════════

def compute_keltner(df: pd.DataFrame) -> pd.DataFrame:
    if "ATR" not in df.columns:
        df = compute_atr(df)
    mid = compute_ema(df["Close"], KELTNER_PERIOD)
    df["KELTNER_Mid"]   = mid
    df["KELTNER_Upper"] = mid + KELTNER_ATR_MULT * df["ATR"]
    df["KELTNER_Lower"] = mid - KELTNER_ATR_MULT * df["ATR"]
    return df


# ═══════════════════════════════════════════════════════════════
#  SUPERTREND
#  Basic Band = HL/2 ± mult × ATR
#  Flips between upper/lower based on close crossing the band.
# ═══════════════════════════════════════════════════════════════

def compute_supertrend(df: pd.DataFrame) -> pd.DataFrame:
    # Always compute Supertrend's own ATR (period may differ from main ATR)
    high = df["High"]
    low = df["Low"]
    prev_close = df["Close"].shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    st_tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr_val = st_tr.ewm(alpha=1.0 / SUPERTREND_PERIOD, min_periods=SUPERTREND_PERIOD, adjust=False).mean()

    hl2 = (df["High"] + df["Low"]) / 2.0

    upper_basic = hl2 + SUPERTREND_MULT * atr_val
    lower_basic = hl2 - SUPERTREND_MULT * atr_val

    n = len(df)
    supertrend = np.zeros(n)
    direction = np.ones(n)  # 1 = up (bullish), -1 = down (bearish)
    final_upper = upper_basic.values.copy()
    final_lower = lower_basic.values.copy()
    close = df["Close"].values

    for i in range(1, n):
        # Carry forward tighter band
        if final_lower[i] < final_lower[i - 1] and close[i - 1] > final_lower[i - 1]:
            final_lower[i] = final_lower[i - 1]
        if final_upper[i] > final_upper[i - 1] and close[i - 1] < final_upper[i - 1]:
            final_upper[i] = final_upper[i - 1]

        if direction[i - 1] == 1:  # was bullish
            if close[i] < final_lower[i]:
                direction[i] = -1
                supertrend[i] = final_upper[i]
            else:
                direction[i] = 1
                supertrend[i] = final_lower[i]
        else:  # was bearish
            if close[i] > final_upper[i]:
                direction[i] = 1
                supertrend[i] = final_lower[i]
            else:
                direction[i] = -1
                supertrend[i] = final_upper[i]

    df["SUPERTREND"] = supertrend
    df["SUPERTREND_DIR"] = direction  # 1=bullish, -1=bearish
    return df


# ═══════════════════════════════════════════════════════════════
#  AROON  (Tushar Chande)
#  Aroon Up   = ((period - days since highest high) / period) × 100
#  Aroon Down = ((period - days since lowest low) / period) × 100
# ═══════════════════════════════════════════════════════════════

def compute_aroon(df: pd.DataFrame, period: int = AROON_PERIOD) -> pd.DataFrame:
    df["AROON_Up"] = df["High"].rolling(window=period + 1).apply(
        lambda x: (period - (period - x.values.argmax())) / period * 100.0, raw=False
    )
    df["AROON_Down"] = df["Low"].rolling(window=period + 1).apply(
        lambda x: (period - (period - x.values.argmin())) / period * 100.0, raw=False
    )
    df["AROON_Osc"] = df["AROON_Up"] - df["AROON_Down"]
    return df


# ═══════════════════════════════════════════════════════════════
#  BOLLINGER BANDS  (from existing system, recomputed for independence)
# ═══════════════════════════════════════════════════════════════

def compute_bollinger(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
    if "BB_Mid" not in df.columns:
        df["BB_Mid"] = df["Close"].rolling(window=period).mean()
        rolling_std = df["Close"].rolling(window=period).std(ddof=0)
        df["BB_Upper"] = df["BB_Mid"] + std_dev * rolling_std
        df["BB_Lower"] = df["BB_Mid"] - std_dev * rolling_std
        df["BBW"] = ((df["BB_Upper"] - df["BB_Lower"]) / df["BB_Mid"].replace(0, np.nan))
        df["Percent_B"] = (df["Close"] - df["BB_Lower"]) / (df["BB_Upper"] - df["BB_Lower"]).replace(0, np.nan)
    return df


# ═══════════════════════════════════════════════════════════════
#  PIVOT POINTS  (Classic Floor Method)
# ═══════════════════════════════════════════════════════════════

def compute_pivot_points(df: pd.DataFrame) -> dict:
    """Compute pivot points from the previous completed session's bar."""
    if len(df) < 2:
        return {}
    prev = df.iloc[-2]
    h, l, c = float(prev["High"]), float(prev["Low"]), float(prev["Close"])

    pp = (h + l + c) / 3.0
    r1 = 2 * pp - l
    s1 = 2 * pp - h
    r2 = pp + (h - l)
    s2 = pp - (h - l)
    r3 = h + 2 * (pp - l)
    s3 = l - 2 * (h - pp)

    return {
        "PP": round(pp, 2), "R1": round(r1, 2), "R2": round(r2, 2), "R3": round(r3, 2),
        "S1": round(s1, 2), "S2": round(s2, 2), "S3": round(s3, 2),
    }


# ═══════════════════════════════════════════════════════════════
#  FIBONACCI RETRACEMENTS  (Murphy Ch 4)
# ═══════════════════════════════════════════════════════════════

def compute_fibonacci(df: pd.DataFrame, lookback: int = 120) -> dict:
    """
    Compute Fibonacci retracement levels from the swing high/low
    in the lookback window.
    """
    window = df.tail(lookback)
    swing_high = float(window["High"].max())
    swing_low = float(window["Low"].min())
    diff = swing_high - swing_low

    high_idx = window["High"].idxmax()
    low_idx = window["Low"].idxmin()
    is_uptrend = low_idx < high_idx  # low came before high

    levels = {}
    fib_ratios = [0.0, 0.236, 0.382, 0.500, 0.618, 0.786, 1.0]

    if is_uptrend:
        # Retracement from high → down
        for r in fib_ratios:
            levels[f"fib_{r}"] = round(swing_high - diff * r, 2)
    else:
        # Retracement from low → up
        for r in fib_ratios:
            levels[f"fib_{r}"] = round(swing_low + diff * r, 2)

    levels["swing_high"] = round(swing_high, 2)
    levels["swing_low"] = round(swing_low, 2)
    levels["is_uptrend"] = is_uptrend

    return levels


# ═══════════════════════════════════════════════════════════════
#  MOVING AVERAGE CROSSOVER DETECTION
# ═══════════════════════════════════════════════════════════════

def detect_ma_crossovers(df: pd.DataFrame) -> list[dict]:
    """Detect Golden Cross / Death Cross and other MA crossovers."""
    crossovers = []

    pairs = [
        ("SMA_50", "SMA_200", "Golden Cross / Death Cross"),
        ("EMA_12", "EMA_26", "MACD Proxy Crossover"),
        ("SMA_20", "SMA_50", "Short-Term Crossover"),
    ]

    for fast_col, slow_col, label in pairs:
        if fast_col not in df.columns or slow_col not in df.columns:
            continue
        fast = df[fast_col]
        slow = df[slow_col]
        above_now = float(fast.iloc[-1]) > float(slow.iloc[-1])
        above_prev = float(fast.iloc[-2]) > float(slow.iloc[-2]) if len(df) > 1 else above_now

        if above_now and not above_prev:
            crossovers.append({"type": "BULLISH", "label": label, "detail": f"{fast_col} crossed above {slow_col}"})
        elif not above_now and above_prev:
            crossovers.append({"type": "BEARISH", "label": label, "detail": f"{fast_col} crossed below {slow_col}"})
        else:
            state = "ABOVE" if above_now else "BELOW"
            crossovers.append({"type": state, "label": label, "detail": f"{fast_col} is {state.lower()} {slow_col}"})

    return crossovers


# ═══════════════════════════════════════════════════════════════
#  DIVERGENCE DETECTION  (Murphy Ch 10)
# ═══════════════════════════════════════════════════════════════

def _detect_divergence(price: pd.Series, indicator: pd.Series, lookback: int = 30) -> str | None:
    """
    Check for bullish or bearish divergence between price and an indicator.
    Returns 'BULLISH_DIV', 'BEARISH_DIV', or None.
    """
    if len(price) < lookback + 5:
        return None

    window_p = price.tail(lookback)
    window_i = indicator.tail(lookback)

    # Find two most recent swing lows/highs in the window
    half = lookback // 2

    # Bearish divergence: price higher high + indicator lower high
    p_first_half_max = window_p.iloc[:half].max()
    p_second_half_max = window_p.iloc[half:].max()
    i_first_half_max = window_i.iloc[:half].max()
    i_second_half_max = window_i.iloc[half:].max()

    if p_second_half_max > p_first_half_max and i_second_half_max < i_first_half_max:
        return "BEARISH_DIV"

    # Bullish divergence: price lower low + indicator higher low
    p_first_half_min = window_p.iloc[:half].min()
    p_second_half_min = window_p.iloc[half:].min()
    i_first_half_min = window_i.iloc[:half].min()
    i_second_half_min = window_i.iloc[half:].min()

    if p_second_half_min < p_first_half_min and i_second_half_min > i_first_half_min:
        return "BULLISH_DIV"

    return None


def detect_all_divergences(df: pd.DataFrame) -> list[dict]:
    """Check for divergences across all major oscillators."""
    divs = []
    checks = [
        ("RSI", "RSI"),
        ("MACD_Hist", "MACD Histogram"),
        ("STOCH_K", "Stochastic"),
        ("OBV", "On Balance Volume"),
    ]
    for col, name in checks:
        if col not in df.columns:
            continue
        result = _detect_divergence(df["Close"], df[col])
        if result:
            divs.append({
                "indicator": name,
                "type": result,
                "meaning": (
                    f"Price and {name} are moving in opposite directions — "
                    f"{'sellers may be losing steam (potential rally)' if 'BULLISH' in result else 'buyers may be losing steam (potential decline)'}"
                ),
            })
    return divs


# ═══════════════════════════════════════════════════════════════
#  MASTER COMPUTATION — COMPUTE ALL INDICATORS
# ═══════════════════════════════════════════════════════════════

def compute_all_ta_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute ALL technical indicators from Murphy's book.
    Input: DataFrame with Open, High, Low, Close, Volume.
    Output: Same DataFrame with ~40+ indicator columns added.
    """
    df = df.copy()

    # Moving Averages (Ch 9)
    df = compute_all_moving_averages(df)

    # Bollinger Bands (Ch 9)
    df = compute_bollinger(df)

    # RSI (Ch 10)
    df = compute_rsi(df)

    # MACD (Ch 10)
    df = compute_macd(df)

    # Stochastic (Ch 10)
    df = compute_stochastic(df)

    # Williams %R (Ch 10)
    df = compute_williams_r(df)

    # CCI (Ch 10)
    df = compute_cci(df)

    # ROC
    df = compute_roc(df)

    # ADX/DMI (Ch 10)
    df = compute_adx(df)

    # ATR (Wilder)
    df = compute_atr(df)

    # OBV (Ch 7)
    df = compute_obv(df)

    # A/D Line (Ch 7)
    df = compute_ad_line(df)

    # Volume ROC (Ch 7)
    df = compute_volume_roc(df)

    # VWAP
    df = compute_vwap(df)

    # Ichimoku Cloud
    df = compute_ichimoku(df)

    # Keltner Channels
    df = compute_keltner(df)

    # Supertrend
    df = compute_supertrend(df)

    # Aroon
    df = compute_aroon(df)

    return df


# ═══════════════════════════════════════════════════════════════
#  SNAPSHOT — EXTRACT LATEST VALUES FOR UI
# ═══════════════════════════════════════════════════════════════

def get_indicator_snapshot(df: pd.DataFrame) -> dict:
    """
    Extract the latest values of ALL indicators into a flat dict
    for JSON serialization and UI display.
    """
    if df.empty:
        return {}

    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else last

    def sv(col, decimals=2):
        """Safe value from last row."""
        if col in df.columns:
            return _safe_val(float(last[col]), decimals)
        return None

    def pv(col, decimals=2):
        """Previous value."""
        if col in df.columns:
            return _safe_val(float(prev[col]), decimals)
        return None

    snapshot = {
        # Price
        "price": sv("Close"),
        "open": sv("Open"),
        "high": sv("High"),
        "low": sv("Low"),
        "volume": int(last["Volume"]) if "Volume" in df.columns else 0,

        # Moving Averages
        "sma_10": sv("SMA_10"), "sma_20": sv("SMA_20"), "sma_50": sv("SMA_50"),
        "sma_100": sv("SMA_100"), "sma_200": sv("SMA_200"),
        "ema_9": sv("EMA_9"), "ema_12": sv("EMA_12"), "ema_21": sv("EMA_21"),
        "ema_26": sv("EMA_26"), "ema_50": sv("EMA_50"), "ema_200": sv("EMA_200"),

        # Price vs MAs
        "above_sma_20": sv("Close") is not None and sv("SMA_20") is not None and sv("Close") > sv("SMA_20"),
        "above_sma_50": sv("Close") is not None and sv("SMA_50") is not None and sv("Close") > sv("SMA_50"),
        "above_sma_200": sv("Close") is not None and sv("SMA_200") is not None and sv("Close") > sv("SMA_200"),
        "above_ema_21": sv("Close") is not None and sv("EMA_21") is not None and sv("Close") > sv("EMA_21"),

        # Bollinger Bands
        "bb_upper": sv("BB_Upper"), "bb_mid": sv("BB_Mid"), "bb_lower": sv("BB_Lower"),
        "bbw": sv("BBW", 4), "percent_b": sv("Percent_B", 4),

        # RSI
        "rsi": sv("RSI"), "rsi_prev": pv("RSI"),

        # MACD
        "macd": sv("MACD", 4), "macd_signal": sv("MACD_Signal", 4), "macd_hist": sv("MACD_Hist", 4),
        "macd_hist_prev": pv("MACD_Hist", 4),

        # Stochastic
        "stoch_k": sv("STOCH_K"), "stoch_d": sv("STOCH_D"),

        # Williams %R
        "williams_r": sv("WILLR"),

        # CCI
        "cci": sv("CCI"),

        # ROC
        "roc": sv("ROC"),

        # ADX/DMI
        "adx": sv("ADX"), "plus_di": sv("PLUS_DI"), "minus_di": sv("MINUS_DI"),

        # ATR
        "atr": sv("ATR"),
        "atr_pct": sv("ATR") / sv("Close") * 100 if sv("Close") and sv("ATR") else None,

        # OBV
        "obv": sv("OBV", 0), "obv_sma": sv("OBV_SMA", 0),

        # A/D Line
        "ad_line": sv("AD_Line", 0),

        # Volume
        "vroc": sv("VROC"),
        "vwap": sv("VWAP"),

        # Ichimoku
        "ichi_tenkan": sv("ICHI_Tenkan"), "ichi_kijun": sv("ICHI_Kijun"),
        "ichi_span_a": sv("ICHI_SpanA"), "ichi_span_b": sv("ICHI_SpanB"),

        # Keltner
        "keltner_upper": sv("KELTNER_Upper"), "keltner_mid": sv("KELTNER_Mid"),
        "keltner_lower": sv("KELTNER_Lower"),

        # Supertrend
        "supertrend": sv("SUPERTREND"),
        "supertrend_bullish": bool(last.get("SUPERTREND_DIR", 0) == 1) if "SUPERTREND_DIR" in df.columns else None,

        # Aroon
        "aroon_up": sv("AROON_Up"), "aroon_down": sv("AROON_Down"),
        "aroon_osc": sv("AROON_Osc"),
    }

    # 52-week data
    tail_252 = df.tail(252)
    snapshot["high_52w"] = _safe_val(float(tail_252["High"].max()), 2)
    snapshot["low_52w"] = _safe_val(float(tail_252["Low"].min()), 2)
    if snapshot["price"] and snapshot["high_52w"]:
        snapshot["pct_from_52w_high"] = _safe_val(
            (snapshot["price"] - snapshot["high_52w"]) / snapshot["high_52w"] * 100, 2
        )

    return snapshot
