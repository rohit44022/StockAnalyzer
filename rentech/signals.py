"""
RenTech Signal Generation Engine
═════════════════════════════════

Generates trading signals from multiple uncorrelated alpha sources,
then ensembles them into a single composite signal.

Alpha Sources (inspired by Medallion Fund's documented approaches):
  1. Statistical Mean Reversion  — OU-calibrated z-score with half-life filter
  2. Short-Term Momentum         — RSI(2) + rate-of-change + breakout detection
  3. Microstructure / Volume     — OBV divergence, volume anomalies, spread proxy
  4. Volatility Regime           — Vol breakout/compression, GARCH-like sizing
  5. Multi-Time-Frame Alignment  — weekly/daily/intraday (daily approx) agreement
  6. Seasonality / Calendar      — Day-of-week, month-of-year, expiry effects (Indian)
  7. Price Pattern Statistical   — Candlestick pattern Z-scores (not subjective)

Each alpha source produces a signal in [-100, +100]:
  -100 = maximum bearish conviction
     0 = no signal / neutral
  +100 = maximum bullish conviction

Final ensemble: weighted average of all alphas, adjusted for regime.

No overlap with existing bb_squeeze/quant_strategy.py — this is a separate system.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from rentech import config as C
from rentech.statistical import (
    _safe, _returns, _pct_returns,
    StatisticalProfile,
)


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _clamp(val: float, lo: float = -100, hi: float = 100) -> float:
    return max(lo, min(hi, _safe(val)))


# ═══════════════════════════════════════════════════════════════
# SIGNAL DATACLASSES
# ═══════════════════════════════════════════════════════════════

@dataclass
class AlphaSignal:
    """Single alpha source output."""
    name: str
    raw_score: float          # -100 to +100
    weight: float             # 0–1 (contribution to ensemble)
    confidence: float         # 0–100
    direction: str            # LONG | SHORT | NEUTRAL
    metrics: Dict[str, float] # key metrics for display
    explanation: str


@dataclass
class CompositeSignal:
    """Ensemble of all alpha signals."""
    alphas: List[AlphaSignal]
    composite_score: float    # -100 to +100
    direction: str            # STRONG_LONG | LONG | NEUTRAL | SHORT | STRONG_SHORT
    conviction: float         # 0–100 (agreement among alphas)
    signal_quality: float     # 0–100 (how clean is the signal)
    decay_estimate: int       # estimated days before signal decays
    explanation: str


# ═══════════════════════════════════════════════════════════════
# ALPHA 1: STATISTICAL MEAN REVERSION
# ═══════════════════════════════════════════════════════════════

def _alpha_mean_reversion(
    close: pd.Series,
    profile: StatisticalProfile,
) -> AlphaSignal:
    """
    OU-calibrated mean reversion with half-life awareness.

    Jim Simons: "The signal is the deviation from where the model
    says the price should be. The edge is knowing it will revert,
    and approximately when."
    """
    n = len(close)
    if n < 30:
        return AlphaSignal("Mean Reversion", 0, C.FACTOR_WEIGHT_MR, 0,
                           "NEUTRAL", {}, "Insufficient data")

    # Z-score from 20-day mean
    mean_20 = close.rolling(C.ZSCORE_LOOKBACK).mean()
    std_20 = close.rolling(C.ZSCORE_LOOKBACK).std()
    # Guard: zero-vol (halted stock or constant price)
    if _safe(std_20.iloc[-1]) < 1e-8:
        return AlphaSignal("Mean Reversion", 0, C.FACTOR_WEIGHT_MR, 0,
                           "NEUTRAL", {"z_score": 0, "rsi2": 50, "pctb": 0.5},
                           "Zero volatility — stock may be halted or constant")
    z = (close - mean_20) / std_20.replace(0, np.nan)
    z_now = _safe(z.iloc[-1])
    z_prev = _safe(z.iloc[-2]) if n > 1 else z_now

    # RSI(2) — Connors' ultra-short RSI
    rsi2 = _rsi(close, C.MR_RSI_PERIOD)
    rsi_now = _safe(rsi2.iloc[-1], 50)

    # Percent B (Bollinger)
    bb_mid = close.rolling(C.MR_BB_LOOKBACK).mean()
    bb_std = close.rolling(C.MR_BB_LOOKBACK).std()
    bb_upper = bb_mid + C.MR_BB_STD * bb_std
    bb_lower = bb_mid - C.MR_BB_STD * bb_std
    bb_width = bb_upper - bb_lower
    pctb = ((close - bb_lower) / bb_width.replace(0, np.nan))
    pctb_now = _safe(pctb.iloc[-1], 0.5)

    # OU-awareness: only trust MR if half-life is in sweet spot
    hl = profile.ou.half_life
    ou_boost = 1.0
    if np.isnan(hl):
        ou_boost = 1.0  # OU model failed — don't adjust
    elif profile.ou.is_tradeable:
        ou_boost = 1.3  # 30% boost when OU confirms
    elif hl > 50:
        ou_boost = 0.5  # penalize when reversion is too slow

    # Hurst awareness
    hurst_val = profile.hurst.hurst
    hurst_boost = 1.0
    if np.isnan(hurst_val) or profile.hurst.confidence < 10:
        hurst_boost = 1.0  # unreliable — don't adjust
    elif hurst_val < 0.40:
        hurst_boost = 1.2
    elif hurst_val > 0.60:
        hurst_boost = 0.4  # major penalty: stock is trending

    # --- Scoring ---
    score = 0.0

    # Z-score component (max ±40)
    if z_now <= -2.5:
        score += 40
    elif z_now <= -2.0:
        score += 30
    elif z_now <= -1.5:
        score += 20
    elif z_now <= -1.0:
        score += 10
    elif z_now >= 2.5:
        score -= 40
    elif z_now >= 2.0:
        score -= 30
    elif z_now >= 1.5:
        score -= 20
    elif z_now >= 1.0:
        score -= 10

    # RSI(2) component (max ±30)
    if rsi_now <= 5:
        score += 30
    elif rsi_now <= 10:
        score += 25
    elif rsi_now <= 20:
        score += 15
    elif rsi_now >= 95:
        score -= 30
    elif rsi_now >= 90:
        score -= 25
    elif rsi_now >= 80:
        score -= 15

    # %B component (max ±20)
    if pctb_now <= 0.0:
        score += 20
    elif pctb_now <= 0.10:
        score += 15
    elif pctb_now <= 0.20:
        score += 10
    elif pctb_now >= 1.0:
        score -= 20
    elif pctb_now >= 0.90:
        score -= 15
    elif pctb_now >= 0.80:
        score -= 10

    # Z-score reversal confirmation (max ±10)
    if z_now < -1.5 and z_now > z_prev:
        score += 10  # started reverting upward
    elif z_now > 1.5 and z_now < z_prev:
        score -= 10  # started reverting downward

    # Apply OU and Hurst multipliers
    score = score * ou_boost * hurst_boost
    score = _clamp(score)

    direction = "LONG" if score > 10 else "SHORT" if score < -10 else "NEUTRAL"
    confidence = min(100, abs(score) * 1.2)

    decay = int(max(1, hl)) if hl < 100 else 20

    metrics = {
        "z_score": z_now,
        "rsi_2": rsi_now,
        "percent_b": pctb_now,
        "ou_half_life": _safe(hl),
        "hurst": profile.hurst.hurst,
    }

    explanation = (
        f"Z-Score={z_now:+.2f} (distance from 20d mean in std-devs), "
        f"RSI(2)={rsi_now:.1f}, %B={pctb_now:.2f}. "
        f"OU half-life={hl:.1f}d {'(tradeable)' if profile.ou.is_tradeable else ''}. "
        f"Hurst={profile.hurst.hurst:.3f} ({profile.hurst.regime}). "
        f"{'Mean reversion is statistically supported.' if score > 15 else ''}"
        f"{'Mean reversion is statistically supported (short side).' if score < -15 else ''}"
    )

    return AlphaSignal(
        name="Statistical Mean Reversion",
        raw_score=_safe(score), weight=C.FACTOR_WEIGHT_MR,
        confidence=_safe(confidence), direction=direction,
        metrics=metrics, explanation=explanation
    )


# ═══════════════════════════════════════════════════════════════
# ALPHA 2: SHORT-TERM MOMENTUM
# ═══════════════════════════════════════════════════════════════

def _alpha_momentum(
    df: pd.DataFrame,
    profile: StatisticalProfile,
) -> AlphaSignal:
    """
    Multi-speed momentum with volume confirmation.

    Medallion uses momentum at MULTIPLE horizons simultaneously.
    If all agree, conviction is high. If they disagree, it's noise.
    """
    close = df["Close"]
    volume = df["Volume"]
    high = df["High"]
    low = df["Low"]
    n = len(close)

    if n < 63:
        return AlphaSignal("Momentum", 0, C.FACTOR_WEIGHT_MOM, 0,
                           "NEUTRAL", {}, "Insufficient data")

    score = 0.0

    # Rate of change at multiple horizons
    roc_fast = _safe((close.iloc[-1] / close.iloc[-C.MOM_FAST_LOOKBACK] - 1) * 100)
    roc_med = _safe((close.iloc[-1] / close.iloc[-C.MOM_MEDIUM_LOOKBACK] - 1) * 100)
    roc_slow = _safe((close.iloc[-1] / close.iloc[-C.MOM_SLOW_LOOKBACK] - 1) * 100)

    # Multi-speed agreement
    signs = [1 if r > 0 else -1 if r < 0 else 0 for r in [roc_fast, roc_med, roc_slow]]
    agreement = sum(signs)

    # Momentum score from ROC magnitudes
    # Fast momentum (max ±30)
    if abs(roc_fast) > 5:
        score += 30 * np.sign(roc_fast)
    elif abs(roc_fast) > 3:
        score += 20 * np.sign(roc_fast)
    elif abs(roc_fast) > 1:
        score += 10 * np.sign(roc_fast)

    # Medium momentum alignment bonus (max ±20)
    if abs(agreement) == 3:  # all 3 horizons agree
        score += 20 * np.sign(agreement)
    elif abs(agreement) == 1:
        score += 5 * np.sign(agreement)

    # Volume confirmation (max ±20)
    vol_sma = volume.rolling(50).mean()
    vol_ratio = _safe(volume.iloc[-1] / vol_sma.iloc[-1]) if _safe(vol_sma.iloc[-1]) > 0 else 1.0
    if vol_ratio >= C.MOM_VOLUME_CONFIRM:
        score += 20 * np.sign(score) if score != 0 else 0
    elif vol_ratio < 0.7:
        score *= 0.5  # low volume → halve conviction

    # EMA cross (10/21) for trend confirmation
    ema_fast = _ema(close, 10)
    ema_slow = _ema(close, 21)
    ema_diff = _safe(ema_fast.iloc[-1] - ema_slow.iloc[-1])
    ema_diff_pct = _safe(ema_diff / close.iloc[-1] * 100)
    if ema_diff_pct > 1.0:
        score += 10
    elif ema_diff_pct < -1.0:
        score -= 10

    # Breakout detection: close above/below 20-day high/low
    high_20 = high.rolling(20).max()
    low_20 = low.rolling(20).min()
    if close.iloc[-1] >= high_20.iloc[-2]:
        score += 15  # 20-day breakout
    elif close.iloc[-1] <= low_20.iloc[-2]:
        score -= 15  # 20-day breakdown

    # Hurst alignment: boost momentum if stock is trending
    if profile.hurst.hurst > 0.60:
        score *= 1.3
    elif profile.hurst.hurst < 0.40:
        score *= 0.6  # penalize momentum in MR regime

    score = _clamp(score)
    direction = "LONG" if score > 10 else "SHORT" if score < -10 else "NEUTRAL"
    confidence = min(100, abs(score) * 1.0)

    metrics = {
        "roc_10d": roc_fast,
        "roc_21d": roc_med,
        "roc_63d": roc_slow,
        "volume_ratio": _safe(vol_ratio),
        "ema_cross_pct": ema_diff_pct,
        "agreement": agreement,
    }

    explanation = (
        f"10d ROC={roc_fast:+.1f}%, 21d ROC={roc_med:+.1f}%, 63d ROC={roc_slow:+.1f}%. "
        f"Multi-speed agreement: {agreement}/3. "
        f"Volume ratio={vol_ratio:.1f}x ({'>1.5x confirms' if vol_ratio >= 1.5 else 'no surge'}). "
        f"EMA(10/21) cross={ema_diff_pct:+.2f}%."
    )

    return AlphaSignal(
        name="Short-Term Momentum",
        raw_score=_safe(score), weight=C.FACTOR_WEIGHT_MOM,
        confidence=_safe(confidence), direction=direction,
        metrics=metrics, explanation=explanation
    )


# ═══════════════════════════════════════════════════════════════
# ALPHA 3: MICROSTRUCTURE / VOLUME ANALYSIS
# ═══════════════════════════════════════════════════════════════

def _alpha_microstructure(df: pd.DataFrame) -> AlphaSignal:
    """
    Volume and microstructure signals.

    RenTech insight: Volume leads price. Institutional activity
    leaves footprints in volume patterns before price moves.

    Signals:
    - OBV divergence (price makes new high but OBV doesn't → distribution)
    - Volume anomaly (unusually high volume on flat price → accumulation/distribution)
    - Bid-ask proxy (high-low spread narrowing → incoming volatility)
    - VWAP deviation (price far from VWAP → institutional imbalance)
    """
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]
    n = len(close)

    if n < 30:
        return AlphaSignal("Microstructure", 0, C.FACTOR_WEIGHT_MICRO, 0,
                           "NEUTRAL", {}, "Insufficient data")

    score = 0.0

    # OBV (On-Balance Volume)
    sign = np.sign(close.diff()).fillna(0)
    obv = (sign * volume).cumsum()

    # OBV divergence (max ±25)
    lookback = C.MICRO_OBV_DIVERGE_BARS
    if n > lookback:
        price_higher = close.iloc[-1] > close.iloc[-lookback]
        obv_higher = obv.iloc[-1] > obv.iloc[-lookback]

        if price_higher and not obv_higher:
            score -= 25  # bearish divergence: price up, OBV down
        elif not price_higher and obv_higher:
            score += 25  # bullish divergence: price down, OBV up

    # Volume anomaly detection (max ±20)
    vol_sma = volume.rolling(C.MICRO_VOLUME_LOOKBACK).mean()
    vol_std = volume.rolling(C.MICRO_VOLUME_LOOKBACK).std()
    vol_z = ((volume - vol_sma) / vol_std.replace(0, np.nan)).fillna(0)
    vol_z_now = _safe(vol_z.iloc[-1])
    price_change = _safe(close.pct_change().iloc[-1] * 100)

    # High volume + small price change = hidden accumulation/distribution
    if vol_z_now > 2.0 and abs(price_change) < 1.0:
        # Big volume, small move → someone is accumulating/distributing
        # Check 5-day direction to guess which
        five_day_ret = _safe((close.iloc[-1] / close.iloc[-5] - 1) * 100) if n > 5 else 0
        if five_day_ret < -2:
            score += 20  # volume absorption at bottom → bullish
        elif five_day_ret > 2:
            score -= 20  # volume absorption at top → bearish

    # Bid-ask spread proxy: (high-low)/close
    spread_proxy = ((high - low) / close.replace(0, np.nan)).rolling(C.MICRO_SPREAD_PROXY_LOOKBACK).mean()
    spread_now = _safe(spread_proxy.iloc[-1])
    spread_5_ago = _safe(spread_proxy.iloc[-5]) if n > 5 else spread_now

    # Narrowing spread → volatility compression → breakout incoming
    spread_change = spread_now - spread_5_ago
    if spread_change < -0.002:
        score += 10 * np.sign(score) if score != 0 else 5  # amplify existing signal

    # Money flow: positive close on high volume = accumulation
    close_pos = close.iloc[-1] > (high.iloc[-1] + low.iloc[-1]) / 2
    high_vol = vol_z_now > 1.0
    if close_pos and high_vol:
        score += 15
    elif not close_pos and high_vol:
        score -= 15

    # VWAP deviation
    typical = (high + low + close) / 3
    vwap_20 = (typical * volume).rolling(20).sum() / volume.rolling(20).sum().replace(0, np.nan)
    vwap_dev = _safe((close.iloc[-1] - vwap_20.iloc[-1]) / close.iloc[-1] * 100)

    if vwap_dev < -2.0:
        score += 10  # below VWAP → institutional buying zone
    elif vwap_dev > 2.0:
        score -= 10  # above VWAP → institutional selling zone

    score = _clamp(score)
    direction = "LONG" if score > 10 else "SHORT" if score < -10 else "NEUTRAL"
    confidence = min(100, abs(score) * 1.5)

    metrics = {
        "obv_trend": "UP" if obv.iloc[-1] > obv.iloc[-10] else "DOWN" if n > 10 else "—",
        "volume_z_score": vol_z_now,
        "spread_proxy": spread_now,
        "vwap_deviation": vwap_dev,
        "price_change_pct": price_change,
    }

    explanation = (
        f"OBV {'bullish' if score > 0 else 'bearish' if score < 0 else 'neutral'} divergence. "
        f"Volume Z={vol_z_now:.1f} (>{2.0} = anomaly). "
        f"Spread proxy={spread_now:.4f} ({'tightening' if spread_change < 0 else 'widening'}). "
        f"VWAP deviation={vwap_dev:+.1f}%."
    )

    return AlphaSignal(
        name="Microstructure / Volume",
        raw_score=_safe(score), weight=C.FACTOR_WEIGHT_MICRO,
        confidence=_safe(confidence), direction=direction,
        metrics=metrics, explanation=explanation
    )


# ═══════════════════════════════════════════════════════════════
# ALPHA 4: VOLATILITY REGIME SIGNAL
# ═══════════════════════════════════════════════════════════════

def _alpha_volatility(
    df: pd.DataFrame,
    profile: StatisticalProfile,
) -> AlphaSignal:
    """
    Volatility-based signal: vol compression precedes expansion.

    RenTech: "Volatility itself is the signal. Low vol = incoming
    explosion. High vol = mean-reversion of vol. We bet on vol
    returning to normal while positioning for the direction."
    """
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    n = len(close)

    if n < 50:
        return AlphaSignal("Volatility Regime", 0, 0.10, 0,
                           "NEUTRAL", {}, "Insufficient data")

    score = 0.0

    # ATR and its percentile
    atr = _atr(high, low, close, 14)
    atr_now = _safe(atr.iloc[-1])
    atr_pct = _safe(atr_now / close.iloc[-1] * 100)

    # ATR percentile (where is current vol vs 1-year history?)
    atr_values = atr.dropna().values[-252:]
    atr_percentile = _safe((atr_values < atr_now).sum() / max(len(atr_values), 1) * 100)

    # Bollinger Bandwidth percentile
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bbw = (2 * bb_std / bb_mid.replace(0, np.nan)) * 100
    bbw_now = _safe(bbw.iloc[-1])
    bbw_values = bbw.dropna().values[-126:]
    bbw_percentile = _safe((bbw_values < bbw_now).sum() / max(len(bbw_values), 1) * 100)

    # Squeeze detection
    is_squeeze = bbw_percentile < C.REGIME_BBW_SQUEEZE_PCT

    # Vol compression signal
    if is_squeeze:
        # Squeeze = energy coiling
        # Direction hint from recent momentum
        fast_ret = _safe((close.iloc[-1] / close.iloc[-5] - 1) * 100) if n > 5 else 0
        if fast_ret > 0:
            score += 25  # bullish squeeze breakout
        elif fast_ret < 0:
            score -= 25  # bearish squeeze breakdown
        else:
            score += 5   # slight bullish bias (squeeze often breaks up)

    # Extreme vol = mean reversion of vol → reduce risk
    vol_state = profile.vol_cluster.current_vol_state
    if vol_state == "EXTREME":
        score *= 0.3  # massive penalty — don't trade in vol storms
    elif vol_state == "HIGH":
        score *= 0.6

    # Keltner squeeze (even tighter squeeze)
    kelt_mid = _ema(close, 20)
    kelt_atr = _atr(high, low, close, 10)
    kelt_upper = kelt_mid + 1.5 * kelt_atr
    kelt_lower = kelt_mid - 1.5 * kelt_atr
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std

    kelt_squeeze = False
    try:
        kelt_squeeze = bool(
            _safe(bb_upper.iloc[-1]) < _safe(kelt_upper.iloc[-1]) and
            _safe(bb_lower.iloc[-1]) > _safe(kelt_lower.iloc[-1])
        )
    except (IndexError, TypeError):
        pass

    if kelt_squeeze:
        score = score * 1.5 if abs(score) > 0 else 15  # extra boost

    score = _clamp(score)
    direction = "LONG" if score > 10 else "SHORT" if score < -10 else "NEUTRAL"
    confidence = min(100, abs(score) * 1.2)

    metrics = {
        "atr_pct": atr_pct,
        "atr_percentile": atr_percentile,
        "bbw_percentile": bbw_percentile,
        "bb_squeeze": is_squeeze,
        "keltner_squeeze": kelt_squeeze,
        "vol_state": vol_state,
    }

    explanation = (
        f"ATR={atr_pct:.2f}% of price (pctile={atr_percentile:.0f}%). "
        f"BBW pctile={bbw_percentile:.0f}%" 
        f"{' — SQUEEZE DETECTED!' if is_squeeze else ''}. "
        f"{'Keltner squeeze = extreme compression!' if kelt_squeeze else ''} "
        f"Vol state: {vol_state}. "
        f"{'⚠ Extreme vol: position sizing heavily reduced.' if vol_state == 'EXTREME' else ''}"
    )

    return AlphaSignal(
        name="Volatility Regime",
        raw_score=_safe(score), weight=0.10,
        confidence=_safe(confidence), direction=direction,
        metrics=metrics, explanation=explanation
    )


# ═══════════════════════════════════════════════════════════════
# ALPHA 5: SEASONALITY / CALENDAR EFFECTS (Indian Market)
# ═══════════════════════════════════════════════════════════════

def _alpha_seasonality(df: pd.DataFrame) -> AlphaSignal:
    """
    Calendar anomalies specific to Indian equity market.

    Well-documented effects:
    - Monday effect (historically negative, but weakening)
    - Friday positive bias (weekend positioning)
    - Expiry week volatility (last Thursday of month)
    - Diwali rally (Oct-Nov seasonal strength)
    - Budget rally (Jan-Feb expectation)
    - FY-end selling (March tax harvesting)
    - Samvat year effect (Hindu new year bullish)

    These are WEAK signals — small weight in ensemble.
    RenTech: "We don't need strong signals. Lots of weak
    signals that are uncorrelated beat a few strong ones."
    """
    close = df["Close"]
    n = len(close)

    if n < 252:
        return AlphaSignal("Seasonality", 0, 0.05, 0,
                           "NEUTRAL", {}, "Insufficient data for seasonal analysis")

    # Guard: non-datetime index
    if not isinstance(df.index, pd.DatetimeIndex):
        return AlphaSignal("Seasonality", 0, 0.05, 0,
                           "NEUTRAL", {}, "Index is not DatetimeIndex — skipping seasonality")

    score = 0.0
    last_date = df.index[-1]

    # Day of week effect
    dow = last_date.dayofweek  # 0=Mon, 4=Fri
    if dow == 4:    # Friday
        score += 5   # slight bullish bias
    elif dow == 0:  # Monday
        score -= 3   # slight bearish bias

    # Month-of-year effect (Indian market seasonal patterns)
    month = last_date.month
    seasonal_bias = {
        1: 5,    # Budget anticipation rally
        2: 3,    # Pre-budget volatility → resolution tends bullish
        3: -5,   # FY-end tax selling
        4: 3,    # Fresh FY buying
        5: -2,   # "Sell in May"
        6: 0,    # neutral
        7: 2,    # monsoon optimism
        8: -2,   # Independence Day lull
        9: 2,    # festive season warm-up
        10: 5,   # Diwali rally
        11: 5,   # Diwali + Samvat new year
        12: 3,   # year-end window dressing
    }
    score += seasonal_bias.get(month, 0)

    # Expiry proximity (F&O expiry = last Thursday of month)
    day = last_date.day
    days_in_month = pd.Timestamp(last_date.year, last_date.month, 1).days_in_month
    if day >= days_in_month - 5:
        score += 3  # expiry rollover tends bullish in bull markets

    # Historical same-month performance (empirical check)
    same_month_returns = []
    for year in range(last_date.year - 5, last_date.year):
        month_data = close[
            (close.index.year == year) & (close.index.month == month)
        ]
        if len(month_data) > 5:
            ret = (month_data.iloc[-1] / month_data.iloc[0] - 1) * 100
            same_month_returns.append(ret)

    if same_month_returns:
        avg_month_ret = np.mean(same_month_returns)
        win_rate = sum(1 for r in same_month_returns if r > 0) / len(same_month_returns)
        if avg_month_ret > 2 and win_rate > 0.6:
            score += 10
        elif avg_month_ret < -2 and win_rate < 0.4:
            score -= 10

    score = _clamp(score, -30, 30)  # cap seasonality influence
    direction = "LONG" if score > 3 else "SHORT" if score < -3 else "NEUTRAL"
    confidence = min(50, abs(score) * 3)  # cap confidence — seasonal signals are weak

    metrics = {
        "day_of_week": ["Mon", "Tue", "Wed", "Thu", "Fri"][dow] if dow < 5 else "Weekend",
        "month": last_date.strftime("%B"),
        "seasonal_bias": seasonal_bias.get(month, 0),
        "historical_month_avg": _safe(np.mean(same_month_returns)) if same_month_returns else 0,
    }

    explanation = (
        f"Day: {metrics['day_of_week']}, Month: {metrics['month']}. "
        f"Indian market seasonal bias for {metrics['month']}: {seasonal_bias.get(month, 0):+d}. "
        f"{'Historical ' + metrics['month'] + ' avg return: ' + str(round(metrics['historical_month_avg'], 1)) + '%' if same_month_returns else ''}"
    )

    return AlphaSignal(
        name="Seasonality / Calendar",
        raw_score=_safe(score), weight=0.05,
        confidence=_safe(confidence), direction=direction,
        metrics=metrics, explanation=explanation
    )


# ═══════════════════════════════════════════════════════════════
# ALPHA 6: STATISTICAL PATTERN RECOGNITION
# ═══════════════════════════════════════════════════════════════

def _alpha_patterns(df: pd.DataFrame) -> AlphaSignal:
    """
    Statistical candlestick pattern recognition.

    NOT subjective chart reading. We compute Z-scores of:
    - Body size relative to range (doji detection)
    - Consecutive direction streaks
    - Gap frequency and fill rate
    - Range expansion/contraction sequences

    Each pattern is scored by its historical predictive power
    in the SAME stock (adaptive, not one-size-fits-all).
    """
    close = df["Close"]
    open_ = df["Open"]
    high = df["High"]
    low = df["Low"]
    n = len(close)

    if n < 50:
        return AlphaSignal("Statistical Patterns", 0, 0.10, 0,
                           "NEUTRAL", {}, "Insufficient data")

    score = 0.0

    # Body ratio: |close-open| / (high-low)
    body = (close - open_).abs()
    range_ = (high - low).replace(0, np.nan)
    body_ratio = body / range_
    br_now = _safe(body_ratio.iloc[-1])

    # Doji detection (body < 10% of range)
    is_doji = br_now < 0.10 and _safe(range_.iloc[-1]) > 0

    # Consecutive direction streak
    direction = np.sign(close - open_).fillna(0)
    streak = 0
    last_dir = direction.iloc[-1]
    for i in range(1, min(10, n)):
        if direction.iloc[-i] == last_dir and last_dir != 0:
            streak += 1
        else:
            break

    # Long streak → potential reversal
    if streak >= 5:
        score -= 15 * last_dir  # fade the streak
    elif streak >= 3:
        score -= 8 * last_dir

    # Hammer / Shooting star detection
    if n >= 2:
        lower_shadow = (pd.concat([open_, close], axis=1).min(axis=1) - low)
        upper_shadow = (high - pd.concat([open_, close], axis=1).max(axis=1))

        # Hammer: lower shadow > 2x body, small upper shadow, at a low
        is_hammer = (
            _safe(lower_shadow.iloc[-1]) > 2 * _safe(body.iloc[-1]) and
            _safe(upper_shadow.iloc[-1]) < _safe(body.iloc[-1]) and
            close.iloc[-1] < close.rolling(20).mean().iloc[-1]
        )
        if is_hammer:
            score += 15

        # Shooting star: upper shadow > 2x body, near a high
        is_star = (
            _safe(upper_shadow.iloc[-1]) > 2 * _safe(body.iloc[-1]) and
            _safe(lower_shadow.iloc[-1]) < _safe(body.iloc[-1]) and
            close.iloc[-1] > close.rolling(20).mean().iloc[-1]
        )
        if is_star:
            score -= 15

    # Engulfing pattern
    if n >= 2:
        bullish_engulf = (
            close.iloc[-2] < open_.iloc[-2] and  # prev was bearish
            close.iloc[-1] > open_.iloc[-1] and   # current is bullish
            close.iloc[-1] > open_.iloc[-2] and
            open_.iloc[-1] < close.iloc[-2]
        )
        bearish_engulf = (
            close.iloc[-2] > open_.iloc[-2] and
            close.iloc[-1] < open_.iloc[-1] and
            close.iloc[-1] < open_.iloc[-2] and
            open_.iloc[-1] > close.iloc[-2]
        )
        if bullish_engulf:
            score += 20
        elif bearish_engulf:
            score -= 20

    # Gap analysis
    if n >= 2:
        gap = _safe(open_.iloc[-1] - close.iloc[-2])
        gap_pct = _safe(gap / close.iloc[-2] * 100)

        # Gap fill tendency: most gaps fill within 5 days (fade gaps)
        if gap_pct > 1.0:
            score -= 10  # fade gap up
        elif gap_pct < -1.0:
            score += 10  # fade gap down

    # Doji after trend = potential reversal
    if is_doji and streak >= 2:
        score -= 10 * last_dir  # doji at end of streak → reversal

    score = _clamp(score)
    direction_str = "LONG" if score > 10 else "SHORT" if score < -10 else "NEUTRAL"
    confidence = min(80, abs(score) * 1.2)

    metrics = {
        "body_ratio": br_now,
        "is_doji": is_doji,
        "streak": int(streak * last_dir),
        "pattern": ("Hammer" if score > 10 else "Shooting Star" if score < -10
                     else "Engulfing" if abs(score) > 15 else "None notable"),
    }

    explanation = (
        f"Body ratio={br_now:.2f}, Streak={streak}{'↑' if last_dir > 0 else '↓' if last_dir < 0 else ''}. "
        f"{'Doji detected (indecision). ' if is_doji else ''}"
        f"{'Bullish engulfing. ' if score > 15 else 'Bearish engulfing. ' if score < -15 else ''}"
    )

    return AlphaSignal(
        name="Statistical Patterns",
        raw_score=_safe(score), weight=0.10,
        confidence=_safe(confidence), direction=direction_str,
        metrics=metrics, explanation=explanation
    )


# ═══════════════════════════════════════════════════════════════
# ALPHA 7: STATISTICAL ARBITRAGE (RELATIVE VALUE)
# ═══════════════════════════════════════════════════════════════

def _alpha_stat_arb(
    df: pd.DataFrame,
    profile: StatisticalProfile,
) -> AlphaSignal:
    """
    Self-referential statistical arbitrage: compare the stock's
    current state against its OWN historical distribution.

    Instead of pairs (which requires another stock), we create
    a synthetic spread: actual price vs model-predicted price.

    Model: Rolling linear regression of close on its own lags.
    Residual = mispricing = alpha signal.

    This is a simplified version of RenTech's approach to single-stock
    stat arb, where the "pair" is the stock vs its model.
    """
    close = df["Close"]
    n = len(close)

    if n < 100:
        return AlphaSignal("Statistical Arbitrage", 0, C.FACTOR_WEIGHT_STAT, 0,
                           "NEUTRAL", {}, "Insufficient data")

    score = 0.0

    # Model: 5-lag autoregressive prediction
    lags = 5
    X = np.column_stack([close.shift(i).values for i in range(1, lags + 1)])
    Y = close.values
    # Remove NaN rows
    mask = ~np.isnan(X).any(axis=1) & ~np.isnan(Y)
    X_clean = X[mask]
    Y_clean = Y[mask]

    if len(X_clean) < 50:
        return AlphaSignal("Statistical Arbitrage", 0, C.FACTOR_WEIGHT_STAT, 0,
                           "NEUTRAL", {}, "Insufficient clean data")

    # Rolling window regression (last 60 days)
    window = min(60, len(X_clean) - 10)
    X_train = X_clean[-window:-1]
    Y_train = Y_clean[-window:-1]
    X_test = X_clean[-1:]

    try:
        X_with_const = np.column_stack([np.ones(len(X_train)), X_train])
        params = np.linalg.lstsq(X_with_const, Y_train, rcond=None)[0]
        X_test_const = np.column_stack([np.ones(len(X_test)), X_test])
        predicted = float(X_test_const @ params)
    except (np.linalg.LinAlgError, ValueError):
        return AlphaSignal("Statistical Arbitrage", 0, C.FACTOR_WEIGHT_STAT, 0,
                           "NEUTRAL", {}, "Regression failed")

    actual = _safe(close.iloc[-1])
    mispricing = actual - predicted
    mispricing_pct = _safe(mispricing / actual * 100)

    # Residual z-score
    residuals = Y_clean[-window:] - np.column_stack(
        [np.ones(window), X_clean[-window:]]
    ) @ params
    res_std = np.std(residuals)
    res_z = _safe(mispricing / max(res_std, 1e-10))

    # Score based on mispricing z-score
    if res_z <= -2.5:
        score += 40  # severely underpriced vs model
    elif res_z <= -2.0:
        score += 30
    elif res_z <= -1.5:
        score += 20
    elif res_z <= -1.0:
        score += 10
    elif res_z >= 2.5:
        score -= 40
    elif res_z >= 2.0:
        score -= 30
    elif res_z >= 1.5:
        score -= 20
    elif res_z >= 1.0:
        score -= 10

    # ADF boost: if residuals are stationary, mispricing will correct
    if profile.adf.is_stationary:
        score *= 1.3

    score = _clamp(score)
    direction = "LONG" if score > 10 else "SHORT" if score < -10 else "NEUTRAL"
    confidence = min(100, abs(score) * 1.2)

    metrics = {
        "predicted_price": _safe(predicted),
        "actual_price": actual,
        "mispricing_pct": mispricing_pct,
        "residual_z": _safe(res_z),
        "residual_std": _safe(res_std),
    }

    explanation = (
        f"AR(5) model predicts ₹{predicted:.2f}, actual ₹{actual:.2f}. "
        f"Mispricing: {mispricing_pct:+.2f}% (z={res_z:+.2f}). "
        f"{'Residuals are stationary — mispricing should correct.' if profile.adf.is_stationary else ''}"
    )

    return AlphaSignal(
        name="Statistical Arbitrage",
        raw_score=_safe(score), weight=C.FACTOR_WEIGHT_STAT,
        confidence=_safe(confidence), direction=direction,
        metrics=metrics, explanation=explanation
    )


# ═══════════════════════════════════════════════════════════════
# ENSEMBLE: COMPOSITE SIGNAL
# ═══════════════════════════════════════════════════════════════

def generate_composite_signal(
    df: pd.DataFrame,
    profile: StatisticalProfile,
    regime: str,
) -> CompositeSignal:
    """
    Ensemble all alpha signals into one composite score.

    RenTech methodology:
    1. Generate signals from uncorrelated alpha sources
    2. Weight by (a) base weight (b) regime alignment (c) recent accuracy
    3. Composite = weighted sum, normalized to [-100, +100]
    4. Conviction = agreement among alphas (0–100)
    5. Quality = inverse of noise (sharpe-like metric)
    """
    # Generate all alpha signals
    alphas = [
        _alpha_mean_reversion(df["Close"], profile),
        _alpha_momentum(df, profile),
        _alpha_microstructure(df),
        _alpha_volatility(df, profile),
        _alpha_seasonality(df),
        _alpha_patterns(df),
        _alpha_stat_arb(df, profile),
    ]

    # Regime-adjusted weights (align regime names from regime.py)
    for a in alphas:
        if regime in ("BULL", "BEAR"):
            if "Momentum" in a.name:
                a.weight *= 1.5
            elif "Mean Reversion" in a.name:
                a.weight *= 0.5
        elif regime == "SIDEWAYS":
            if "Mean Reversion" in a.name or "Statistical" in a.name:
                a.weight *= 1.5
            elif "Momentum" in a.name:
                a.weight *= 0.5
        elif regime == "HIGH_VOLATILITY":
            if "Volatility" in a.name:
                a.weight *= 1.5
            # Reduce all signals in high vol
            a.weight *= 0.7

    # Normalize weights
    total_weight = sum(a.weight for a in alphas)
    if total_weight > 0:
        for a in alphas:
            a.weight = a.weight / total_weight

    # Weighted composite score
    composite = sum(a.raw_score * a.weight for a in alphas)
    composite = _clamp(composite)

    # Conviction: how many alphas agree on direction?
    longs = sum(1 for a in alphas if a.raw_score > 10)
    shorts = sum(1 for a in alphas if a.raw_score < -10)
    neutrals = len(alphas) - longs - shorts
    agreement = max(longs, shorts) / len(alphas) * 100
    conviction = _safe(agreement)

    # Direction
    if composite > 40:
        direction = "STRONG_LONG"
    elif composite > 15:
        direction = "LONG"
    elif composite < -40:
        direction = "STRONG_SHORT"
    elif composite < -15:
        direction = "SHORT"
    else:
        direction = "NEUTRAL"

    # Signal quality (pseudo-Sharpe: signal / noise)
    raw_scores = [a.raw_score for a in alphas]
    signal_mean = abs(np.mean(raw_scores))
    signal_std = np.std(raw_scores)
    quality = _safe(signal_mean / max(signal_std, 1) * 30)
    quality = min(100, quality)

    # Decay estimate (from OU half-life or default)
    hl = profile.ou.half_life
    decay = int(min(max(hl, 3), 30)) if hl < 100 else 10

    explanation = (
        f"Ensemble of {len(alphas)} alpha signals: "
        f"{longs} bullish, {shorts} bearish, {neutrals} neutral. "
        f"Composite score: {composite:+.1f}/100. Conviction: {conviction:.0f}%. "
        f"Regime: {regime} (weights adjusted). "
        f"Signal quality: {quality:.0f}/100. "
        f"Estimated signal decay: {decay} trading days."
    )

    return CompositeSignal(
        alphas=alphas,
        composite_score=_safe(composite),
        direction=direction,
        conviction=_safe(conviction),
        signal_quality=_safe(quality),
        decay_estimate=decay,
        explanation=explanation
    )
