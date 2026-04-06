"""
Quantitative Trading Strategy Engine — Bollinger Band Based
═══════════════════════════════════════════════════════════════

A complete, self-contained quantitative analysis system built on Bollinger
Band mathematics.  It computes regime detection, mean-reversion signals,
momentum signals, volatility-adjusted position sizing, risk management
levels, and a composite quant score — all with plain-English explanations
so a layman can understand every piece.

References synthesised here:
  • John Bollinger — "Bollinger on Bollinger Bands" (2001)
  • Perry Kaufman — "Trading Systems and Methods" (5th ed.)
  • Ernie Chan — "Quantitative Trading" (2009)
  • Van Tharp — "Trade Your Way to Financial Freedom" (position sizing)
  • Keltner / ATR-based volatility filters (Squeeze detection)
  • Z-Score mean-reversion from statistical arbitrage literature

This module does NOT touch any existing scanner/signals/strategies code.
It reads a DataFrame with pre-computed indicators and produces a standalone
QuantResult dict.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

import numpy as np
import pandas as pd


# ═══════════════════════════════════════════════════════════════
# SECTION 1 — ADDITIONAL INDICATOR COMPUTATIONS
# (computed fresh from OHLCV; does NOT modify the original df)
# ═══════════════════════════════════════════════════════════════

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range — measures volatility in price terms."""
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder's smoothing)."""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _keltner_channels(high, low, close, ema_period=20, atr_period=10, atr_mult=1.5):
    """Keltner Channels for squeeze detection."""
    mid = _ema(close, ema_period)
    atr_val = _atr(high, low, close, atr_period)
    upper = mid + atr_mult * atr_val
    lower = mid - atr_mult * atr_val
    return mid, upper, lower


def _zscore(series: pd.Series, lookback: int = 20) -> pd.Series:
    """Rolling Z-Score = (value − mean) / std."""
    m = series.rolling(lookback).mean()
    s = series.rolling(lookback).std()
    return (series - m) / s.replace(0, np.nan)


def _vwap(high, low, close, volume) -> pd.Series:
    """Cumulative session VWAP (resets conceptually each day, but for
    daily data we compute a rolling 20-day VWAP)."""
    typical = (high + low + close) / 3
    cum_tp_vol = (typical * volume).rolling(20).sum()
    cum_vol = volume.rolling(20).sum()
    return cum_tp_vol / cum_vol.replace(0, np.nan)


def _adx(high, low, close, period=14) -> pd.Series:
    """Average Directional Index — trend strength (0–100)."""
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    atr_val = _atr(high, low, close, period)
    plus_di = 100 * _ema(plus_dm, period) / atr_val.replace(0, np.nan)
    minus_di = 100 * _ema(minus_dm, period) / atr_val.replace(0, np.nan)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return _ema(dx, period)


# ═══════════════════════════════════════════════════════════════
# SECTION 2 — MARKET REGIME DETECTION
# ═══════════════════════════════════════════════════════════════

@dataclass
class RegimeResult:
    regime: str               # TRENDING_UP, TRENDING_DOWN, MEAN_REVERTING, VOLATILE_CHOPPY
    confidence: float         # 0–100
    adx_value: float
    bb_squeeze: bool
    keltner_squeeze: bool
    trend_slope: float        # slope of 20-SMA (normalised)
    volatility_regime: str    # LOW, NORMAL, HIGH, EXTREME
    bbw_percentile: float     # where current BBW sits vs last 6 months
    explanation: str


def _detect_regime(df: pd.DataFrame) -> RegimeResult:
    """Classify the current market regime using multiple indicators."""
    close = df["Close"]
    high = df["High"]
    low = df["Low"]

    # ADX for trend strength
    adx = _adx(high, low, close, 14)
    adx_now = float(adx.iloc[-1]) if not np.isnan(adx.iloc[-1]) else 0

    # Bollinger Band Width percentile (6-month)
    bbw = df["BBW"]
    bbw_now = float(bbw.iloc[-1]) if not np.isnan(bbw.iloc[-1]) else 0
    bbw_6m = bbw.tail(126)
    bbw_pctile = float((bbw_6m < bbw_now).sum() / max(len(bbw_6m), 1) * 100)

    # BB Squeeze (BBW at 6-month low zone)
    bb_squeeze = bbw_pctile < 15

    # Keltner Squeeze
    _, k_upper, k_lower = _keltner_channels(high, low, close)
    bb_upper = df["BB_Upper"]
    bb_lower = df["BB_Lower"]
    kelt_squeeze = bool(
        bb_upper.iloc[-1] < k_upper.iloc[-1] and bb_lower.iloc[-1] > k_lower.iloc[-1]
    ) if not (np.isnan(k_upper.iloc[-1]) or np.isnan(bb_upper.iloc[-1])) else False

    # Trend slope (normalised % per day)
    sma20 = df["BB_Mid"]
    if len(sma20) >= 10:
        slope_raw = (float(sma20.iloc[-1]) - float(sma20.iloc[-10])) / max(float(sma20.iloc[-10]), 1)
        trend_slope = round(slope_raw * 100, 3)  # % over 10 days
    else:
        trend_slope = 0.0

    # Volatility classification
    if bbw_pctile >= 90:
        vol_regime = "EXTREME"
    elif bbw_pctile >= 70:
        vol_regime = "HIGH"
    elif bbw_pctile >= 30:
        vol_regime = "NORMAL"
    else:
        vol_regime = "LOW"

    # Regime classification
    if adx_now >= 25 and trend_slope > 0.3:
        regime = "TRENDING_UP"
        conf = min(100, adx_now * 2 + abs(trend_slope) * 10)
        explain = (
            f"The stock is in a confirmed UPTREND. ADX at {adx_now:.1f} (above 25 = strong trend) "
            f"and the 20-day moving average is sloping upward at {trend_slope:+.2f}%/10d. "
            f"In this regime, MOMENTUM strategies work best — ride the trend, don't fight it. "
            f"Mean-reversion (buying dips to lower band) is RISKY here as 'cheap' can get cheaper.\n"
            f"Why this matters: In an uptrend, the upper Bollinger Band acts as a magnet, not a ceiling. "
            f"Price touching the upper band is a sign of STRENGTH, not a sell signal. "
            f"Look for pullbacks to the 20-SMA (middle band) as potential entry points."
        )
    elif adx_now >= 25 and trend_slope < -0.3:
        regime = "TRENDING_DOWN"
        conf = min(100, adx_now * 2 + abs(trend_slope) * 10)
        explain = (
            f"The stock is in a confirmed DOWNTREND. ADX at {adx_now:.1f} (strong trend) "
            f"with 20-SMA sloping down at {trend_slope:+.2f}%/10d. "
            f"Avoid buying 'cheap' — in downtrends, stocks that touch the lower band often continue falling. "
            f"Wait for trend reversal signals or use momentum to short/exit.\n"
            f"Key insight: The most common mistake retail investors make is buying 'the dip' in a downtrend. "
            f"In Bollinger's words, the lower band is NOT a buy signal in a trending-down market — "
            f"it confirms weakness. Wait for ADX to drop below 20 (trend weakening) before considering entry."
        )
    elif adx_now < 20 and vol_regime in ("LOW", "NORMAL"):
        regime = "MEAN_REVERTING"
        conf = min(100, (25 - adx_now) * 4 + (50 - bbw_pctile) * 0.5)
        explain = (
            f"The stock is RANGE-BOUND (sideways). ADX at {adx_now:.1f} (below 20 = no trend). "
            f"This is the ideal regime for MEAN-REVERSION — buy near the lower band, sell near the upper band. "
            f"Bollinger Bands work like rubber bands here: price stretches to one side and snaps back. "
            f"Volatility is {vol_regime.lower()}, making band touches more reliable.\n"
            f"How to trade it: When price touches the lower Bollinger Band AND RSI is below 30 AND "
            f"Z-Score is below −1.5, that's a high-probability buy setup. Set your target at the middle band (20-SMA) "
            f"or the upper band, and place a stop-loss 2× ATR below your entry."
        )
    else:
        regime = "VOLATILE_CHOPPY"
        conf = max(20, 60 - abs(adx_now - 20) * 2)
        explain = (
            f"The stock is in a CHOPPY/VOLATILE state. ADX at {adx_now:.1f} with "
            f"volatility at the {bbw_pctile:.0f}th percentile. "
            f"Neither trending nor mean-reverting cleanly. This is the toughest regime to trade. "
            f"Position sizes should be SMALLER, stops WIDER. Wait for a clear regime to develop.\n"
            f"Important: Most trading losses come from forcing trades in choppy markets. "
            f"Professional traders know that the best trade is sometimes NO trade. Cash is a position. "
            f"Wait for ADX to either rise above 25 (trend forming) or for the Bollinger Bands to squeeze "
            f"(volatility contracting), which often precedes a clear, tradeable move."
        )

    if bb_squeeze or kelt_squeeze:
        explain += (
            f"\n\n🔥 SQUEEZE DETECTED! Bollinger Bands are inside Keltner Channels — "
            f"volatility is coiled like a spring. A big move is likely coming. "
            f"Direction is uncertain until the breakout happens."
        )

    return RegimeResult(
        regime=regime,
        confidence=round(min(100, max(0, conf)), 1),
        adx_value=round(adx_now, 1),
        bb_squeeze=bb_squeeze,
        keltner_squeeze=kelt_squeeze,
        trend_slope=trend_slope,
        volatility_regime=vol_regime,
        bbw_percentile=round(bbw_pctile, 1),
        explanation=explain,
    )


# ═══════════════════════════════════════════════════════════════
# SECTION 3 — MEAN-REVERSION SIGNAL  (Z-Score based)
# ═══════════════════════════════════════════════════════════════

@dataclass
class MeanReversionSignal:
    signal: str          # STRONG_BUY, BUY, NEUTRAL, SELL, STRONG_SELL
    zscore: float        # current z-score of close vs 20-day
    pctb: float          # current %b
    rsi: float           # 14-day RSI
    lower_band_dist: float   # % distance from lower band
    upper_band_dist: float   # % distance from upper band
    mean_dist: float         # % distance from 20-SMA
    explanation: str


def _mean_reversion_signal(df: pd.DataFrame) -> MeanReversionSignal:
    """Mean-reversion signal using Z-Score + %b + RSI confluence."""
    close = df["Close"]

    z = _zscore(close, 20)
    z_now = float(z.iloc[-1]) if not np.isnan(z.iloc[-1]) else 0

    pctb = float(df["Percent_B"].iloc[-1]) if not np.isnan(df["Percent_B"].iloc[-1]) else 0.5
    rsi = _rsi(close, 14)
    rsi_now = float(rsi.iloc[-1]) if not np.isnan(rsi.iloc[-1]) else 50

    bb_upper = float(df["BB_Upper"].iloc[-1])
    bb_lower = float(df["BB_Lower"].iloc[-1])
    bb_mid = float(df["BB_Mid"].iloc[-1])
    price = float(close.iloc[-1])

    lower_dist = round((price - bb_lower) / max(price, 1) * 100, 2)
    upper_dist = round((bb_upper - price) / max(price, 1) * 100, 2)
    mean_dist = round((price - bb_mid) / max(price, 1) * 100, 2)

    # Scoring: lower z-score + lower %b + lower RSI = stronger buy
    buy_score = 0
    if z_now <= -2.0:
        buy_score += 3
    elif z_now <= -1.5:
        buy_score += 2
    elif z_now <= -1.0:
        buy_score += 1

    if pctb <= 0.05:
        buy_score += 3
    elif pctb <= 0.15:
        buy_score += 2
    elif pctb <= 0.25:
        buy_score += 1

    if rsi_now <= 25:
        buy_score += 3
    elif rsi_now <= 35:
        buy_score += 2
    elif rsi_now <= 45:
        buy_score += 1

    sell_score = 0
    if z_now >= 2.0:
        sell_score += 3
    elif z_now >= 1.5:
        sell_score += 2
    elif z_now >= 1.0:
        sell_score += 1

    if pctb >= 0.95:
        sell_score += 3
    elif pctb >= 0.85:
        sell_score += 2
    elif pctb >= 0.75:
        sell_score += 1

    if rsi_now >= 75:
        sell_score += 3
    elif rsi_now >= 65:
        sell_score += 2
    elif rsi_now >= 55:
        sell_score += 1

    if buy_score >= 7:
        signal = "STRONG_BUY"
    elif buy_score >= 4:
        signal = "BUY"
    elif sell_score >= 7:
        signal = "STRONG_SELL"
    elif sell_score >= 4:
        signal = "SELL"
    else:
        signal = "NEUTRAL"

    # Build explanation
    parts = []
    parts.append(
        f"Z-Score: {z_now:+.2f} — "
        f"{'Price is significantly BELOW average (oversold zone)' if z_now < -1.5 else 'Price is BELOW average (mildly oversold)' if z_now < -0.5 else 'Price is near its average (fair value zone)' if abs(z_now) < 0.5 else 'Price is ABOVE average (mildly overbought)' if z_now < 1.5 else 'Price is significantly ABOVE average (overbought zone)'}. "
        f"Z-Score measures how many standard deviations price is from its 20-day mean. "
        f"Below -2 = statistically extreme (happens ~2.5% of the time)."
    )
    parts.append(
        f"%b: {pctb:.3f} — "
        f"{'Price is BELOW the lower Bollinger Band (very rare, extreme oversold)' if pctb < 0 else 'Price is AT the lower band (oversold)' if pctb < 0.1 else 'Price is in the lower zone' if pctb < 0.3 else 'Price is in the middle zone (balanced)' if pctb < 0.7 else 'Price is in the upper zone' if pctb < 0.9 else 'Price is AT the upper band (overbought)' if pctb < 1.0 else 'Price is ABOVE the upper band (extreme overbought)'}. "
        f"%b tells you where price sits within the bands: 0 = lower band, 0.5 = middle, 1 = upper band."
    )
    parts.append(
        f"RSI(14): {rsi_now:.1f} — "
        f"{'Deeply oversold (strong bounce potential)' if rsi_now < 25 else 'Oversold territory' if rsi_now < 35 else 'Slightly weak' if rsi_now < 45 else 'Neutral momentum' if rsi_now < 55 else 'Slightly strong' if rsi_now < 65 else 'Overbought territory' if rsi_now < 75 else 'Deeply overbought (pullback likely)'}. "
        f"RSI measures momentum on a 0-100 scale. Below 30 = oversold, above 70 = overbought."
    )
    parts.append(
        f"Distance from bands: {lower_dist:+.2f}% from lower, {upper_dist:+.2f}% from upper, "
        f"{mean_dist:+.2f}% from 20-SMA."
    )

    if signal in ("STRONG_BUY", "BUY"):
        parts.append(
            f"VERDICT: All three indicators (Z-Score, %b, RSI) agree that price is stretched "
            f"to the DOWNSIDE. In a mean-reverting regime, this is a potential buying opportunity — "
            f"price is likely to snap back toward the middle band. "
            f"{'⚡ STRONG confluence — all 3 indicators at extreme levels!' if signal == 'STRONG_BUY' else 'Moderate confluence across indicators.'}"
        )
    elif signal in ("STRONG_SELL", "SELL"):
        parts.append(
            f"VERDICT: Indicators suggest price is stretched to the UPSIDE. "
            f"Mean-reversion says price is likely to pull back toward the middle band. "
            f"{'⚡ STRONG overbought confluence — consider taking profits!' if signal == 'STRONG_SELL' else 'Moderate overbought signal.'}"
        )
    else:
        parts.append(
            "VERDICT: Price is in a neutral zone — no strong mean-reversion signal. "
            "Wait for price to reach the upper or lower band extremes for clearer signals."
        )

    return MeanReversionSignal(
        signal=signal,
        zscore=round(z_now, 3),
        pctb=round(pctb, 4),
        rsi=round(rsi_now, 1),
        lower_band_dist=lower_dist,
        upper_band_dist=upper_dist,
        mean_dist=mean_dist,
        explanation="\n".join(parts),
    )


# ═══════════════════════════════════════════════════════════════
# SECTION 4 — MOMENTUM / BREAKOUT SIGNAL
# ═══════════════════════════════════════════════════════════════

@dataclass
class MomentumSignal:
    signal: str           # STRONG_BUY, BUY, NEUTRAL, SELL, STRONG_SELL
    bb_breakout: str      # UPPER_BREAKOUT, LOWER_BREAKDOWN, NONE
    volume_surge: bool    # volume > 1.5x SMA
    price_vs_vwap: str    # ABOVE, BELOW, AT
    trend_strength: float # ADX
    sar_direction: str    # BULLISH, BEARISH
    consecutive_closes: int  # consecutive closes above/below mid
    explanation: str


def _momentum_signal(df: pd.DataFrame) -> MomentumSignal:
    """Momentum/breakout signal using BB breakouts + volume + VWAP."""
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]
    price = float(close.iloc[-1])

    bb_upper = float(df["BB_Upper"].iloc[-1])
    bb_lower = float(df["BB_Lower"].iloc[-1])
    bb_mid = float(df["BB_Mid"].iloc[-1])

    # Breakout detection
    if price > bb_upper:
        bb_breakout = "UPPER_BREAKOUT"
    elif price < bb_lower:
        bb_breakout = "LOWER_BREAKDOWN"
    else:
        bb_breakout = "NONE"

    # Volume surge
    vol_sma = float(df["Vol_SMA50"].iloc[-1]) if not np.isnan(df["Vol_SMA50"].iloc[-1]) else 0
    vol_now = float(volume.iloc[-1])
    volume_surge = vol_now > vol_sma * 1.5 if vol_sma > 0 else False
    vol_ratio = round(vol_now / max(vol_sma, 1), 2)

    # VWAP
    vwap = _vwap(high, low, close, volume)
    vwap_now = float(vwap.iloc[-1]) if not np.isnan(vwap.iloc[-1]) else price
    if price > vwap_now * 1.002:
        price_vs_vwap = "ABOVE"
    elif price < vwap_now * 0.998:
        price_vs_vwap = "BELOW"
    else:
        price_vs_vwap = "AT"

    # ADX
    adx = _adx(high, low, close, 14)
    adx_now = float(adx.iloc[-1]) if not np.isnan(adx.iloc[-1]) else 0

    # SAR
    sar_bull = bool(df["SAR_Bull"].iloc[-1])
    sar_dir = "BULLISH" if sar_bull else "BEARISH"

    # Consecutive closes above/below mid (compare each day vs its own BB_Mid)
    bb_mid_series = df["BB_Mid"]
    consec = 0
    for i in range(len(close) - 1, max(len(close) - 21, -1), -1):
        day_mid = float(bb_mid_series.iloc[i]) if not np.isnan(bb_mid_series.iloc[i]) else bb_mid
        if float(close.iloc[i]) > day_mid:
            consec += 1
        else:
            break
    if consec == 0:
        for i in range(len(close) - 1, max(len(close) - 21, -1), -1):
            day_mid = float(bb_mid_series.iloc[i]) if not np.isnan(bb_mid_series.iloc[i]) else bb_mid
            if float(close.iloc[i]) < day_mid:
                consec -= 1
            else:
                break

    # Momentum scoring
    mom_score = 0  # positive = bullish, negative = bearish
    if bb_breakout == "UPPER_BREAKOUT":
        mom_score += 3
    elif bb_breakout == "LOWER_BREAKDOWN":
        mom_score -= 3

    if volume_surge and bb_breakout == "UPPER_BREAKOUT":
        mom_score += 2
    elif volume_surge and bb_breakout == "LOWER_BREAKDOWN":
        mom_score -= 2

    if price_vs_vwap == "ABOVE":
        mom_score += 1
    elif price_vs_vwap == "BELOW":
        mom_score -= 1

    if sar_bull:
        mom_score += 1
    else:
        mom_score -= 1

    if adx_now >= 25:
        if consec > 0:
            mom_score += 2
        elif consec < 0:
            mom_score -= 2

    if mom_score >= 6:
        signal = "STRONG_BUY"
    elif mom_score >= 3:
        signal = "BUY"
    elif mom_score <= -6:
        signal = "STRONG_SELL"
    elif mom_score <= -3:
        signal = "SELL"
    else:
        signal = "NEUTRAL"

    # Explanation
    parts = []
    if bb_breakout == "UPPER_BREAKOUT":
        parts.append(
            f"🚀 UPPER BAND BREAKOUT — Price (₹{price:.2f}) has broken ABOVE the upper Bollinger Band (₹{bb_upper:.2f}). "
            f"In a trending market, this signals strong upward momentum. "
            f"The upper band acts as a 'ceiling' — breaking through it means buyers are very aggressive."
        )
    elif bb_breakout == "LOWER_BREAKDOWN":
        parts.append(
            f"📉 LOWER BAND BREAKDOWN — Price (₹{price:.2f}) has fallen BELOW the lower Bollinger Band (₹{bb_lower:.2f}). "
            f"This signals heavy selling pressure. "
            f"In a trending-down market, this confirms weakness. In a range-bound market, it may be a buying opportunity."
        )
    else:
        parts.append(
            f"Price (₹{price:.2f}) is within the bands (Lower: ₹{bb_lower:.2f}, Upper: ₹{bb_upper:.2f}). "
            f"No breakout detected."
        )

    parts.append(
        f"Volume: {vol_ratio:.1f}x average — "
        f"{'🔊 VOLUME SURGE! Significantly higher than normal. Breakouts with high volume are more reliable.' if volume_surge else 'Normal volume levels. Breakouts without volume can be false signals.'}"
    )

    parts.append(
        f"VWAP: Price is {price_vs_vwap} the 20-day VWAP (₹{vwap_now:.2f}). "
        f"{'Institutional buyers are likely active (bullish).' if price_vs_vwap == 'ABOVE' else 'Institutional selling pressure (bearish).' if price_vs_vwap == 'BELOW' else 'Neutral — price at fair value.'} "
        f"VWAP = Volume Weighted Average Price — tells you the 'true' average price accounting for volume."
    )

    parts.append(
        f"Parabolic SAR: {sar_dir} — {'Dots are below price (uptrend confirmed)' if sar_bull else 'Dots are above price (downtrend confirmed)'}. "
        f"SAR is a trend-following indicator that places dots above/below price to show direction."
    )

    parts.append(
        f"ADX: {adx_now:.1f} — {'Strong trend in play (ADX > 25)' if adx_now >= 25 else 'Weak/no trend (ADX < 25 — momentum signals less reliable)'}. "
        f"{'Price has closed above the middle band for ' + str(consec) + ' consecutive days.' if consec > 0 else 'Price has closed below the middle band for ' + str(abs(consec)) + ' consecutive days.' if consec < 0 else ''}"
    )

    return MomentumSignal(
        signal=signal,
        bb_breakout=bb_breakout,
        volume_surge=volume_surge,
        price_vs_vwap=price_vs_vwap,
        trend_strength=round(adx_now, 1),
        sar_direction=sar_dir,
        consecutive_closes=consec,
        explanation="\n".join(parts),
    )


# ═══════════════════════════════════════════════════════════════
# SECTION 5 — VOLATILITY ANALYSIS & POSITION SIZING
# ═══════════════════════════════════════════════════════════════

@dataclass
class VolatilityAnalysis:
    atr_value: float         # ATR in price terms
    atr_percent: float       # ATR as % of price
    daily_volatility: float  # std dev of daily returns
    annual_volatility: float # annualised
    suggested_stop_loss: float    # price level
    suggested_target: float       # price level
    risk_reward_ratio: float
    position_size_pct: float  # % of capital per Van Tharp's model
    position_size_shares: int # number of shares (for ₹1L capital)
    volatility_rank: str      # LOW, MEDIUM, HIGH, EXTREME
    explanation: str


def _volatility_analysis(df: pd.DataFrame) -> VolatilityAnalysis:
    """ATR-based volatility, position sizing, and risk management."""
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    price = float(close.iloc[-1])

    # ATR
    atr = _atr(high, low, close, 14)
    atr_now = float(atr.iloc[-1]) if not np.isnan(atr.iloc[-1]) else 0
    atr_pct = round(atr_now / max(price, 1) * 100, 2)

    # Daily & annual volatility
    returns = close.pct_change().dropna()
    daily_vol = float(returns.tail(60).std()) if len(returns) >= 60 else float(returns.std())
    annual_vol = round(daily_vol * math.sqrt(252) * 100, 1)
    daily_vol_pct = round(daily_vol * 100, 2)

    # Stop loss: 2 × ATR below current price (standard approach)
    stop_loss = round(price - 2 * atr_now, 2)

    # Target: 3 × ATR above current price (1.5:1 R:R)
    target = round(price + 3 * atr_now, 2)

    risk_per_share = price - stop_loss
    reward_per_share = target - price
    rr_ratio = round(reward_per_share / max(risk_per_share, 0.01), 2)

    # Van Tharp position sizing: Risk 1% of capital per trade
    capital = 100000  # ₹1 Lakh reference
    risk_amount = capital * 0.01  # 1% = ₹1000
    shares = int(risk_amount / max(risk_per_share, 0.01))
    position_pct = round(shares * price / capital * 100, 1)

    # Volatility rank
    if atr_pct <= 1.0:
        vol_rank = "LOW"
    elif atr_pct <= 2.0:
        vol_rank = "MEDIUM"
    elif atr_pct <= 3.5:
        vol_rank = "HIGH"
    else:
        vol_rank = "EXTREME"

    parts = []
    parts.append(
        f"ATR(14): ₹{atr_now:.2f} ({atr_pct:.2f}% of price) — "
        f"The stock moves an average of ₹{atr_now:.2f} per day. "
        f"ATR = Average True Range — measures daily volatility in rupee terms. "
        f"Higher ATR = stock moves more each day = more risk AND more opportunity."
    )
    parts.append(
        f"Annual Volatility: {annual_vol:.1f}% — "
        f"{'Low volatility — stable, predictable stock. Good for conservative strategies.' if annual_vol < 25 else 'Moderate volatility — balanced risk/reward.' if annual_vol < 40 else 'High volatility — big swings, requires wider stops.' if annual_vol < 60 else 'Extreme volatility — very risky, only for experienced traders.'}"
    )
    parts.append(
        f"Suggested Stop Loss: ₹{stop_loss:.2f} (2 × ATR below price) — "
        f"If you buy at ₹{price:.2f}, set stop loss at ₹{stop_loss:.2f} to limit your loss. "
        f"Using 2×ATR gives the stock enough room to breathe without getting stopped out by normal noise."
    )
    parts.append(
        f"Suggested Target: ₹{target:.2f} (3 × ATR above price) — "
        f"Risk:Reward = 1:{rr_ratio:.1f}. "
        f"For every ₹1 you risk, you aim to make ₹{rr_ratio:.1f}. "
        f"Professional traders look for at least 1:1.5 risk-reward ratio."
    )
    parts.append(
        f"Position Sizing (Van Tharp 1% Rule): "
        f"For ₹1,00,000 capital, buy {shares} shares (₹{shares * price:,.0f} = {position_pct:.1f}% of capital). "
        f"The 1% rule means: if your stop loss hits, you lose at most 1% of your total capital. "
        f"This protects you from large drawdowns even if multiple trades go wrong."
    )

    return VolatilityAnalysis(
        atr_value=round(atr_now, 2),
        atr_percent=atr_pct,
        daily_volatility=daily_vol_pct,
        annual_volatility=annual_vol,
        suggested_stop_loss=stop_loss,
        suggested_target=target,
        risk_reward_ratio=rr_ratio,
        position_size_pct=position_pct,
        position_size_shares=shares,
        volatility_rank=vol_rank,
        explanation="\n".join(parts),
    )


# ═══════════════════════════════════════════════════════════════
# SECTION 6 — BB WALK DETECTION & TREND QUALITY
# ═══════════════════════════════════════════════════════════════

@dataclass
class BBWalkAnalysis:
    walking_upper: bool
    walking_lower: bool
    walk_duration: int       # days
    band_touch_count: int    # touches in last 20 days
    trend_quality: str       # STRONG, MODERATE, WEAK, NONE
    price_vs_bands: str      # UPPER_HALF, LOWER_HALF, MIDDLE
    explanation: str


def _bb_walk_analysis(df: pd.DataFrame) -> BBWalkAnalysis:
    """Detect 'Walking the Bands' — strong trend where price hugs one band."""
    close = df["Close"]
    bb_upper = df["BB_Upper"]
    bb_lower = df["BB_Lower"]
    bb_mid = df["BB_Mid"]
    pctb = df["Percent_B"]

    last20 = pctb.tail(20)

    # Count touches (within 5% of band edges)
    upper_touches = int((last20 >= 0.95).sum())
    lower_touches = int((last20 <= 0.05).sum())
    band_touches = max(upper_touches, lower_touches)

    # Walking detection: sustained %b > 0.8 or < 0.2
    walk_upper_days = 0
    for v in reversed(pctb.values):
        if not np.isnan(v) and v >= 0.75:
            walk_upper_days += 1
        else:
            break

    walk_lower_days = 0
    for v in reversed(pctb.values):
        if not np.isnan(v) and v <= 0.25:
            walk_lower_days += 1
        else:
            break

    walking_upper = walk_upper_days >= 3
    walking_lower = walk_lower_days >= 3
    walk_duration = max(walk_upper_days, walk_lower_days)

    # Trend quality
    if walk_duration >= 8 and band_touches >= 3:
        trend_quality = "STRONG"
    elif walk_duration >= 5 or band_touches >= 2:
        trend_quality = "MODERATE"
    elif walk_duration >= 3:
        trend_quality = "WEAK"
    else:
        trend_quality = "NONE"

    # Position within bands
    pctb_now = float(pctb.iloc[-1]) if not np.isnan(pctb.iloc[-1]) else 0.5
    if pctb_now >= 0.65:
        position = "UPPER_HALF"
    elif pctb_now <= 0.35:
        position = "LOWER_HALF"
    else:
        position = "MIDDLE"

    parts = []
    if walking_upper:
        parts.append(
            f"📈 WALKING THE UPPER BAND for {walk_upper_days} days! "
            f"Price has been hugging the upper Bollinger Band — this is a sign of STRONG upward momentum. "
            f"In Bollinger's words: 'Tags of the upper band are NOT sell signals. In a strong uptrend, "
            f"price can walk along the upper band for weeks.' "
            f"Don't sell just because price touches the upper band — it often continues higher."
        )
    elif walking_lower:
        parts.append(
            f"📉 WALKING THE LOWER BAND for {walk_lower_days} days! "
            f"Price is stuck near the lower band — persistent selling pressure. "
            f"This is a WARNING: don't try to 'catch a falling knife'. "
            f"In a downtrend, price can walk along the lower band for extended periods."
        )
    else:
        parts.append(
            f"No band walk detected. Price is in the {position.replace('_', ' ').lower()} of the bands. "
            f"This is a normal state — not trending strongly in either direction."
        )

    parts.append(
        f"Band touches (last 20 days): {upper_touches} upper, {lower_touches} lower. "
        f"{'Frequent upper touches = persistent buying pressure.' if upper_touches >= 3 else 'Frequent lower touches = persistent selling pressure.' if lower_touches >= 3 else 'Few band touches = ranging/consolidating.'}"
    )

    parts.append(
        f"Trend Quality: {trend_quality} — "
        f"{'Powerful, sustained trend. Ride it with trailing stops.' if trend_quality == 'STRONG' else 'Decent trend developing, but not fully established.' if trend_quality == 'MODERATE' else 'Weak trend attempt — may fizzle out.' if trend_quality == 'WEAK' else 'No clear trend. Sideways price action.'}"
    )

    return BBWalkAnalysis(
        walking_upper=walking_upper,
        walking_lower=walking_lower,
        walk_duration=walk_duration,
        band_touch_count=band_touches,
        trend_quality=trend_quality,
        price_vs_bands=position,
        explanation="\n".join(parts),
    )


# ═══════════════════════════════════════════════════════════════
# SECTION 7 — COMPOSITE QUANT SCORE & FINAL VERDICT
# ═══════════════════════════════════════════════════════════════

@dataclass
class QuantVerdict:
    score: int                   # 0–100
    signal: str                  # STRONG_BUY, BUY, NEUTRAL, SELL, STRONG_SELL
    recommended_strategy: str    # MEAN_REVERSION, MOMENTUM, WAIT, AVOID
    confidence: int              # 0–100
    key_factors: List[str]
    risk_level: str              # LOW, MEDIUM, HIGH, EXTREME
    explanation: str


def _compute_verdict(
    regime: RegimeResult,
    mean_rev: MeanReversionSignal,
    momentum: MomentumSignal,
    volatility: VolatilityAnalysis,
    bb_walk: BBWalkAnalysis,
) -> QuantVerdict:
    """Combine all sub-signals into a single composite verdict."""
    score = 50  # start neutral
    factors = []
    confidence_parts = []

    # ── Regime alignment ──
    if regime.regime == "TRENDING_UP":
        if momentum.signal in ("STRONG_BUY", "BUY"):
            score += 20
            factors.append("Uptrend + bullish momentum = strong alignment")
            confidence_parts.append(25)
        elif momentum.signal in ("STRONG_SELL", "SELL"):
            score -= 5
            factors.append("Uptrend but momentum fading — caution")
            confidence_parts.append(10)
        else:
            score += 8
            factors.append("Uptrend in place, momentum neutral")
            confidence_parts.append(15)

    elif regime.regime == "TRENDING_DOWN":
        if momentum.signal in ("STRONG_SELL", "SELL"):
            score -= 20
            factors.append("Downtrend + bearish momentum = avoid buying")
            confidence_parts.append(25)
        elif momentum.signal in ("STRONG_BUY", "BUY"):
            score -= 5
            factors.append("Downtrend with some bullish signals — could be false")
            confidence_parts.append(10)
        else:
            score -= 10
            factors.append("Downtrend, no strong counter-signals")
            confidence_parts.append(15)

    elif regime.regime == "MEAN_REVERTING":
        if mean_rev.signal in ("STRONG_BUY", "BUY"):
            score += 18
            factors.append("Range-bound + oversold = ideal mean-reversion buy")
            confidence_parts.append(25)
        elif mean_rev.signal in ("STRONG_SELL", "SELL"):
            score -= 15
            factors.append("Range-bound + overbought = sell/take-profits signal")
            confidence_parts.append(20)
        else:
            score += 0
            factors.append("Range-bound but no extremes — wait")
            confidence_parts.append(10)

    else:  # VOLATILE_CHOPPY
        score -= 5
        factors.append("Choppy market — high uncertainty, reduce exposure")
        confidence_parts.append(5)

    # ── Mean-Reversion sub-score ──
    if mean_rev.signal == "STRONG_BUY":
        score += 10
        factors.append(f"Z-Score {mean_rev.zscore:+.2f}, %b {mean_rev.pctb:.3f}, RSI {mean_rev.rsi:.0f} — triple oversold")
    elif mean_rev.signal == "BUY":
        score += 5
        factors.append(f"Mild oversold: Z={mean_rev.zscore:+.2f}, %b={mean_rev.pctb:.3f}")
    elif mean_rev.signal == "STRONG_SELL":
        score -= 10
        factors.append(f"Triple overbought: Z={mean_rev.zscore:+.2f}, %b={mean_rev.pctb:.3f}, RSI {mean_rev.rsi:.0f}")
    elif mean_rev.signal == "SELL":
        score -= 5
        factors.append(f"Mild overbought: Z={mean_rev.zscore:+.2f}, %b={mean_rev.pctb:.3f}")

    # ── Momentum sub-score ──
    if momentum.bb_breakout == "UPPER_BREAKOUT" and momentum.volume_surge:
        score += 8
        factors.append("Upper band breakout with volume surge — confirmed breakout")
        confidence_parts.append(20)
    elif momentum.bb_breakout == "LOWER_BREAKDOWN" and momentum.volume_surge:
        score -= 8
        factors.append("Lower band breakdown with volume — confirmed breakdown")
        confidence_parts.append(20)

    if momentum.sar_direction == "BULLISH":
        score += 3
    else:
        score -= 3

    # ── BB Walk ──
    if bb_walk.walking_upper and bb_walk.trend_quality in ("STRONG", "MODERATE"):
        score += 7
        factors.append(f"Walking upper band for {bb_walk.walk_duration} days — sustained bullish pressure")
    elif bb_walk.walking_lower and bb_walk.trend_quality in ("STRONG", "MODERATE"):
        score -= 7
        factors.append(f"Walking lower band for {bb_walk.walk_duration} days — sustained bearish pressure")

    # ── Squeeze bonus ──
    if regime.keltner_squeeze:
        factors.append("🔥 Keltner Squeeze active — expect explosive move soon")
        confidence_parts.append(10)
    elif regime.bb_squeeze:
        factors.append("Bollinger Squeeze narrowing — volatility expansion coming")
        confidence_parts.append(5)

    # ── Volatility penalty ──
    if volatility.volatility_rank == "EXTREME":
        score = int(score * 0.85)
        factors.append("⚠️ Extreme volatility — score dampened, risk is elevated")
    elif volatility.volatility_rank == "HIGH":
        score = int(score * 0.92)
        factors.append("High volatility — slight penalty applied")

    # Clamp score
    score = max(0, min(100, score))

    # Determine signal
    if score >= 75:
        signal = "STRONG_BUY"
    elif score >= 60:
        signal = "BUY"
    elif score <= 25:
        signal = "STRONG_SELL"
    elif score <= 40:
        signal = "SELL"
    else:
        signal = "NEUTRAL"

    # Recommended strategy
    if regime.regime == "MEAN_REVERTING" and mean_rev.signal in ("STRONG_BUY", "BUY"):
        rec_strat = "MEAN_REVERSION"
    elif regime.regime in ("TRENDING_UP", "TRENDING_DOWN") and momentum.signal != "NEUTRAL":
        rec_strat = "MOMENTUM"
    elif regime.regime == "VOLATILE_CHOPPY":
        rec_strat = "AVOID"
    else:
        rec_strat = "WAIT"

    # Confidence
    confidence = max(20, min(100, sum(confidence_parts) + int(regime.confidence * 0.4)))

    # Risk level
    if volatility.volatility_rank in ("LOW",) and regime.regime == "MEAN_REVERTING":
        risk_level = "LOW"
    elif volatility.volatility_rank == "MEDIUM":
        risk_level = "MEDIUM"
    elif volatility.volatility_rank == "HIGH":
        risk_level = "HIGH"
    else:
        risk_level = "EXTREME"

    # Final explanation
    strat_names = {
        "MEAN_REVERSION": "MEAN-REVERSION (buy low, sell high within the range)",
        "MOMENTUM": "MOMENTUM (follow the trend direction)",
        "WAIT": "WAIT — no clear setup, patience required",
        "AVOID": "AVOID — choppy conditions, sit on the sidelines",
    }
    explanation = (
        f"Composite Quant Score: {score}/100. "
        f"Recommended approach: {strat_names.get(rec_strat, rec_strat)}. "
        f"The score synthesises regime detection, mean-reversion indicators, "
        f"momentum signals, band-walk analysis, and volatility adjustment. "
        f"A score above 60 leans bullish, below 40 leans bearish, "
        f"and 40–60 suggests waiting for clearer signals.\n"
        f"How the score is built: Starting from 50 (neutral), points are added or subtracted based on "
        f"regime-momentum alignment (±20), mean-reversion extremes (±10), breakout confirmations (±8), "
        f"band-walk persistence (±7), SAR direction (±3), and volatility penalties (up to −15%). "
        f"This ensures no single indicator dominates — only when multiple factors agree does the score "
        f"reach extreme levels."
    )

    return QuantVerdict(
        score=score,
        signal=signal,
        recommended_strategy=rec_strat,
        confidence=confidence,
        key_factors=factors,
        risk_level=risk_level,
        explanation=explanation,
    )


# ═══════════════════════════════════════════════════════════════
# SECTION 8 — MASTER FUNCTION
# ═══════════════════════════════════════════════════════════════

def run_quant_analysis(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Run the full quantitative trading strategy analysis on an
    indicator-enriched DataFrame.  Returns a JSON-serialisable dict.

    Expects df to already have: BB_Upper, BB_Lower, BB_Mid, BBW,
    Percent_B, SAR, SAR_Bull, Vol_SMA50, CMF, MFI, Squeeze_ON.
    """
    regime = _detect_regime(df)
    mean_rev = _mean_reversion_signal(df)
    momentum = _momentum_signal(df)
    volatility = _volatility_analysis(df)
    bb_walk = _bb_walk_analysis(df)
    verdict = _compute_verdict(regime, mean_rev, momentum, volatility, bb_walk)

    return {
        "regime": {
            "regime": regime.regime,
            "confidence": regime.confidence,
            "adx": regime.adx_value,
            "bb_squeeze": regime.bb_squeeze,
            "keltner_squeeze": regime.keltner_squeeze,
            "trend_slope": regime.trend_slope,
            "volatility_regime": regime.volatility_regime,
            "bbw_percentile": regime.bbw_percentile,
            "explanation": regime.explanation,
        },
        "mean_reversion": {
            "signal": mean_rev.signal,
            "zscore": mean_rev.zscore,
            "pctb": mean_rev.pctb,
            "rsi": mean_rev.rsi,
            "lower_band_dist": mean_rev.lower_band_dist,
            "upper_band_dist": mean_rev.upper_band_dist,
            "mean_dist": mean_rev.mean_dist,
            "explanation": mean_rev.explanation,
        },
        "momentum": {
            "signal": momentum.signal,
            "bb_breakout": momentum.bb_breakout,
            "volume_surge": momentum.volume_surge,
            "price_vs_vwap": momentum.price_vs_vwap,
            "trend_strength": momentum.trend_strength,
            "sar_direction": momentum.sar_direction,
            "consecutive_closes": momentum.consecutive_closes,
            "explanation": momentum.explanation,
        },
        "volatility": {
            "atr_value": volatility.atr_value,
            "atr_percent": volatility.atr_percent,
            "daily_volatility": volatility.daily_volatility,
            "annual_volatility": volatility.annual_volatility,
            "stop_loss": volatility.suggested_stop_loss,
            "target": volatility.suggested_target,
            "risk_reward": volatility.risk_reward_ratio,
            "position_size_pct": volatility.position_size_pct,
            "position_size_shares": volatility.position_size_shares,
            "volatility_rank": volatility.volatility_rank,
            "explanation": volatility.explanation,
        },
        "bb_walk": {
            "walking_upper": bb_walk.walking_upper,
            "walking_lower": bb_walk.walking_lower,
            "walk_duration": bb_walk.walk_duration,
            "band_touches": bb_walk.band_touch_count,
            "trend_quality": bb_walk.trend_quality,
            "price_vs_bands": bb_walk.price_vs_bands,
            "explanation": bb_walk.explanation,
        },
        "verdict": {
            "score": verdict.score,
            "signal": verdict.signal,
            "strategy": verdict.recommended_strategy,
            "confidence": verdict.confidence,
            "factors": verdict.key_factors,
            "risk_level": verdict.risk_level,
            "explanation": verdict.explanation,
        },
    }
