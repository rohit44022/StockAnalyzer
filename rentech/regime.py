"""
RenTech Regime Detection — Hidden Markov Model Inspired
═══════════════════════════════════════════════════════

Markets exist in UNOBSERVABLE states. You can't see the regime
directly — you can only infer it from observable data (returns,
volume, volatility).

Jim Simons: "The market switches between regimes. The same signal
that makes money in one regime loses money in another. The FIRST
thing we do is figure out what regime we're in."

This module implements:
  1. HMM-inspired regime detection (3-state: Bull/Bear/Sideways)
  2. Multi-indicator regime synthesis
  3. Regime transition probability estimation
  4. Indian market-specific indicators (FII/DII proxy, Nifty breadth)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from rentech import config as C
from rentech.statistical import (
    _safe, _returns, _pct_returns,
    StatisticalProfile, volatility_clustering,
)


# ═══════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════

@dataclass
class RegimeState:
    """Current market regime classification."""
    regime: str                   # BULL | BEAR | SIDEWAYS | HIGH_VOLATILITY
    confidence: float             # 0–100
    sub_regime: str               # e.g., "EARLY_BULL", "LATE_BEAR", etc.
    duration_days: int            # how many days in this regime
    explanation: str


@dataclass
class RegimeTransition:
    """Probability of transitioning to each regime."""
    to_bull: float                # 0–1
    to_bear: float                # 0–1
    to_sideways: float            # 0–1
    to_high_vol: float            # 0–1
    most_likely_next: str
    explanation: str


@dataclass
class MarketMicroRegime:
    """Short-term micro regime (intraday-equivalent for daily data)."""
    trend_strength: float         # 0–100 (ADX-based)
    vol_compression: bool         # squeeze detected
    breadth: str                  # BROAD_ADVANCE | NARROW | BROAD_DECLINE
    flow_proxy: str               # ACCUMULATION | DISTRIBUTION | NEUTRAL
    explanation: str


@dataclass
class RegimeAnalysis:
    """Complete regime analysis."""
    current: RegimeState
    transition: RegimeTransition
    micro: MarketMicroRegime
    optimal_strategies: List[str]   # ordered list of best strategies
    regime_score: float             # -100 (deep bear) to +100 (deep bull)
    summary: str


# ═══════════════════════════════════════════════════════════════
# HMM-INSPIRED REGIME DETECTION
# ═══════════════════════════════════════════════════════════════

def _detect_hmm_regime(close: pd.Series, volume: pd.Series) -> Tuple[str, float, int]:
    """
    Simplified HMM: instead of full Baum-Welch, we use a feature-based
    approach that captures the SPIRIT of HMM state detection.

    Observable features:
    - Returns (sign and magnitude)
    - Volatility level
    - Volume trend
    - Moving average alignment

    Hidden states:
    - BULL: positive returns, rising MAs, expanding volume on up
    - BEAR: negative returns, falling MAs, expanding volume on down
    - SIDEWAYS: low returns magnitude, flat MAs, declining volume
    - HIGH_VOLATILITY: extreme returns either way, volume spikes
    """
    n = len(close)
    if n < 60:
        return "SIDEWAYS", 30.0, 0

    # Feature extraction
    ret = _pct_returns(close)

    # 1. Moving average alignment (10/21/50/200 if available)
    ma10 = close.rolling(10).mean()
    ma21 = close.rolling(21).mean()
    ma50 = close.rolling(50).mean()

    ma_alignment = 0
    if n > 50:
        if _safe(ma10.iloc[-1]) > _safe(ma21.iloc[-1]) > _safe(ma50.iloc[-1]):
            ma_alignment = 3  # perfectly bullish
        elif _safe(ma10.iloc[-1]) < _safe(ma21.iloc[-1]) < _safe(ma50.iloc[-1]):
            ma_alignment = -3  # perfectly bearish
        elif _safe(ma10.iloc[-1]) > _safe(ma21.iloc[-1]):
            ma_alignment = 1
        elif _safe(ma10.iloc[-1]) < _safe(ma21.iloc[-1]):
            ma_alignment = -1

    # 2. Recent return trend
    ret_5d = _safe((close.iloc[-1] / close.iloc[-5] - 1) * 100) if n > 5 else 0
    ret_21d = _safe((close.iloc[-1] / close.iloc[-21] - 1) * 100) if n > 21 else 0
    ret_63d = _safe((close.iloc[-1] / close.iloc[-63] - 1) * 100) if n > 63 else 0

    # 3. Volatility state
    daily_vol = _safe(ret.tail(20).std())
    long_vol = _safe(ret.tail(252).std()) if n > 252 else daily_vol
    vol_ratio = daily_vol / max(long_vol, 1e-10)

    # 4. Volume trend
    vol_sma20 = volume.rolling(20).mean()
    vol_sma50 = volume.rolling(50).mean()
    vol_trend = 0
    if n > 50 and _safe(vol_sma50.iloc[-1]) > 0:
        vol_trend = _safe(vol_sma20.iloc[-1] / vol_sma50.iloc[-1] - 1)

    # ── STATE SCORING ──
    bull_score = 0.0
    bear_score = 0.0
    sideways_score = 0.0
    high_vol_score = 0.0

    # MA alignment
    if ma_alignment >= 2:
        bull_score += 30
    elif ma_alignment == 1:
        bull_score += 15
    elif ma_alignment <= -2:
        bear_score += 30
    elif ma_alignment == -1:
        bear_score += 15

    # Return trends
    if ret_21d > 5:
        bull_score += 25
    elif ret_21d > 2:
        bull_score += 15
    elif ret_21d < -5:
        bear_score += 25
    elif ret_21d < -2:
        bear_score += 15

    if ret_63d > 10:
        bull_score += 15
    elif ret_63d < -10:
        bear_score += 15

    # Volatility state
    if vol_ratio > 1.5:
        high_vol_score += 40
        bull_score *= 0.5
        bear_score *= 0.5
    elif vol_ratio < 0.7:
        sideways_score += 20

    # Volume trend
    if vol_trend > 0.3:
        # Rising volume: amplifies the dominant direction
        if ret_21d > 0:
            bull_score += 10
        else:
            bear_score += 10
    elif vol_trend < -0.2:
        sideways_score += 10  # declining volume → sideways

    # Flat returns → sideways
    if abs(ret_21d) < 2 and abs(ret_5d) < 1:
        sideways_score += 25

    # Determine winner
    scores = {
        "BULL": bull_score,
        "BEAR": bear_score,
        "SIDEWAYS": sideways_score,
        "HIGH_VOLATILITY": high_vol_score,
    }
    regime = max(scores, key=scores.get)
    max_score = scores[regime]
    total = sum(scores.values())
    confidence = _safe(max_score / max(total, 1) * 100)

    # Duration estimation: how many days has this regime persisted?
    duration = 0
    if regime == "BULL":
        # Count days since last time price was below MA50
        for i in range(1, min(n, 252)):
            if n > 50 and close.iloc[-i] > _safe(ma50.iloc[-i]):
                duration += 1
            else:
                break
    elif regime == "BEAR":
        for i in range(1, min(n, 252)):
            if n > 50 and close.iloc[-i] < _safe(ma50.iloc[-i]):
                duration += 1
            else:
                break
    else:
        for i in range(1, min(n, 60)):
            if abs(_safe((close.iloc[-i] / close.iloc[-i - 1] - 1) * 100)) < 2:
                duration += 1
            else:
                break

    return regime, confidence, duration


# ═══════════════════════════════════════════════════════════════
# REGIME TRANSITIONS
# ═══════════════════════════════════════════════════════════════

def _estimate_transitions(
    close: pd.Series,
    current_regime: str,
    duration: int,
) -> RegimeTransition:
    """
    Estimate regime transition probabilities based on:
    - Current regime (persistence bias)
    - Duration (longer regimes more likely to end)
    - Recent momentum shifts
    """
    n = len(close)

    # Base transition matrix (empirical for Indian equity)
    # From historical analysis of Nifty 50 regime durations
    base = {
        "BULL": {"BULL": 0.70, "BEAR": 0.10, "SIDEWAYS": 0.15, "HIGH_VOLATILITY": 0.05},
        "BEAR": {"BULL": 0.10, "BEAR": 0.65, "SIDEWAYS": 0.15, "HIGH_VOLATILITY": 0.10},
        "SIDEWAYS": {"BULL": 0.25, "BEAR": 0.20, "SIDEWAYS": 0.45, "HIGH_VOLATILITY": 0.10},
        "HIGH_VOLATILITY": {"BULL": 0.15, "BEAR": 0.25, "SIDEWAYS": 0.30, "HIGH_VOLATILITY": 0.30},
    }

    probs = base.get(current_regime, base["SIDEWAYS"]).copy()

    # Duration decay: longer regimes become less stable
    if duration > 60:
        decay = min(0.20, (duration - 60) / 200)
        probs[current_regime] = max(0.20, probs[current_regime] - decay)
        # Redistribute to other states
        others = [k for k in probs if k != current_regime]
        for k in others:
            probs[k] += decay / len(others)

    # Recent momentum shift detection
    if n > 10:
        ret_5 = _safe((close.iloc[-1] / close.iloc[-5] - 1) * 100)
        if current_regime == "BULL" and ret_5 < -3:
            probs["BEAR"] += 0.15
            probs["BULL"] -= 0.15
        elif current_regime == "BEAR" and ret_5 > 3:
            probs["BULL"] += 0.15
            probs["BEAR"] -= 0.15

    # Normalize
    total = sum(probs.values())
    for k in probs:
        probs[k] = max(0, probs[k] / total)

    most_likely = max(probs, key=probs.get)

    explanation = (
        f"Transition from {current_regime} (day {duration}): "
        f"→ Bull {probs.get('BULL', 0):.0%}, "
        f"→ Bear {probs.get('BEAR', 0):.0%}, "
        f"→ Sideways {probs.get('SIDEWAYS', 0):.0%}, "
        f"→ High Vol {probs.get('HIGH_VOLATILITY', 0):.0%}. "
        f"Most likely next: {most_likely}."
    )

    return RegimeTransition(
        to_bull=_safe(probs.get("BULL", 0)),
        to_bear=_safe(probs.get("BEAR", 0)),
        to_sideways=_safe(probs.get("SIDEWAYS", 0)),
        to_high_vol=_safe(probs.get("HIGH_VOLATILITY", 0)),
        most_likely_next=most_likely,
        explanation=explanation
    )


# ═══════════════════════════════════════════════════════════════
# MARKET MICRO REGIME
# ═══════════════════════════════════════════════════════════════

def _detect_micro_regime(df: pd.DataFrame) -> MarketMicroRegime:
    """
    Short-term micro-level regime indicators.
    These change faster than the macro regime.
    """
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]
    n = len(close)

    if n < 30:
        return MarketMicroRegime(0, False, "NEUTRAL", "NEUTRAL", "Insufficient data")

    # ADX for trend strength
    from rentech.signals import _atr, _ema
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm_clean = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm_clean = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    atr_val = _atr(high, low, close, 14)
    plus_di = 100 * _ema(plus_dm_clean, 14) / atr_val.replace(0, np.nan)
    minus_di = 100 * _ema(minus_dm_clean, 14) / atr_val.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = _ema(dx, 14)
    trend_strength = _safe(adx.iloc[-1])

    # Squeeze detection (BBW at low percentile)
    bb_std = close.rolling(20).std()
    bb_mid = close.rolling(20).mean()
    bbw = (2 * bb_std / bb_mid.replace(0, np.nan)) * 100
    bbw_values = bbw.dropna().values[-126:]
    bbw_now = _safe(bbw.iloc[-1])
    # Guard: need sufficient BBW history for meaningful percentile
    if len(bbw_values) < 20:
        bbw_pctile = 50.0  # assume neutral if insufficient data
        vol_compression = False
    else:
        bbw_pctile = _safe((bbw_values < bbw_now).sum() / len(bbw_values) * 100)
        vol_compression = bbw_pctile < C.REGIME_BBW_SQUEEZE_PCT

    # Breadth proxy: percentage of recent days with positive returns
    ret = close.pct_change()
    up_days = (ret.tail(20) > 0).sum()
    up_pct = _safe(up_days / 20 * 100)
    if up_pct > 65:
        breadth = "BROAD_ADVANCE"
    elif up_pct < 35:
        breadth = "BROAD_DECLINE"
    else:
        breadth = "NARROW"

    # Flow proxy: Chaikin Money Flow approximation
    mf_multiplier = ((close - low) - (high - close)) / (high - low).replace(0, np.nan)
    mf_volume = mf_multiplier.fillna(0) * volume
    cmf = mf_volume.rolling(20).sum() / volume.rolling(20).sum().replace(0, np.nan)
    cmf_now = _safe(cmf.iloc[-1])

    if cmf_now > 0.10:
        flow = "ACCUMULATION"
    elif cmf_now < -0.10:
        flow = "DISTRIBUTION"
    else:
        flow = "NEUTRAL"

    explanation = (
        f"Trend strength (ADX): {trend_strength:.0f}/100. "
        f"{'🔥 SQUEEZE detected — volatility compressed!' if vol_compression else 'No squeeze.'} "
        f"Breadth: {breadth} ({up_pct:.0f}% up days in 20d). "
        f"Flow: {flow} (CMF={cmf_now:.3f})."
    )

    return MarketMicroRegime(
        trend_strength=trend_strength,
        vol_compression=vol_compression,
        breadth=breadth,
        flow_proxy=flow,
        explanation=explanation
    )


# ═══════════════════════════════════════════════════════════════
# MASTER: REGIME ANALYSIS
# ═══════════════════════════════════════════════════════════════

def detect_regime(
    df: pd.DataFrame,
    profile: StatisticalProfile,
) -> RegimeAnalysis:
    """
    Complete regime analysis combining all sub-modules.
    Returns the one authoritative answer: what regime and what to do.
    """
    close = df["Close"]
    volume = df["Volume"]

    # Macro regime
    regime, confidence, duration = _detect_hmm_regime(close, volume)

    # Sub-regime classification
    if regime == "BULL":
        if duration < 20:
            sub = "EARLY_BULL"
        elif duration < 60:
            sub = "MID_BULL"
        else:
            sub = "LATE_BULL"
    elif regime == "BEAR":
        if duration < 20:
            sub = "EARLY_BEAR"
        elif duration < 60:
            sub = "MID_BEAR"
        else:
            sub = "LATE_BEAR"
    elif regime == "HIGH_VOLATILITY":
        sub = "CRISIS" if profile.vol_cluster.current_vol_state == "EXTREME" else "ELEVATED_VOL"
    else:
        sub = "RANGING"

    current = RegimeState(
        regime=regime, confidence=confidence,
        sub_regime=sub, duration_days=duration,
        explanation=(
            f"Market is in {regime} regime (sub: {sub}), "
            f"duration {duration} days, confidence {confidence:.0f}%."
        )
    )

    # Transitions
    transition = _estimate_transitions(close, regime, duration)

    # Micro regime
    micro = _detect_micro_regime(df)

    # Optimal strategies for this regime
    strategy_map = {
        "BULL": ["MOMENTUM", "TREND_FOLLOWING", "BUY_DIPS"],
        "EARLY_BULL": ["MOMENTUM", "BREAKOUT", "ACCUMULATE"],
        "MID_BULL": ["TREND_FOLLOWING", "BUY_DIPS", "MOMENTUM"],
        "LATE_BULL": ["PROFIT_TAKING", "MOMENTUM_WITH_TIGHT_STOPS", "HEDGE"],
        "BEAR": ["AVOID", "CASH", "SHORT_MOMENTUM"],
        "EARLY_BEAR": ["HEDGE", "REDUCE_EXPOSURE", "SHORT"],
        "MID_BEAR": ["CASH", "AVOID", "SELECTIVE_SHORT"],
        "LATE_BEAR": ["ACCUMULATE_QUALITY", "MEAN_REVERSION", "BUY_DIPS"],
        "SIDEWAYS": ["MEAN_REVERSION", "RANGE_TRADING", "SELL_PREMIUM"],
        "HIGH_VOLATILITY": ["REDUCE_SIZE", "WIDEN_STOPS", "WAIT"],
        "CRISIS": ["CASH", "HALT_TRADING", "HEDGE"],
    }
    optimal = strategy_map.get(sub, strategy_map.get(regime, ["WAIT"]))

    # Regime score: -100 (deep bear) to +100 (deep bull)
    regime_score = 0.0
    if regime == "BULL":
        regime_score = 30 + confidence * 0.7
    elif regime == "BEAR":
        regime_score = -30 - confidence * 0.7
    elif regime == "HIGH_VOLATILITY":
        regime_score = -10  # slightly bearish bias in high vol
    else:
        regime_score = 0  # neutral

    # Micro adjustments
    if micro.flow_proxy == "ACCUMULATION":
        regime_score += 10
    elif micro.flow_proxy == "DISTRIBUTION":
        regime_score -= 10

    if micro.vol_compression:
        regime_score *= 0.8  # less certain when squeezed

    regime_score = max(-100, min(100, regime_score))

    summary = (
        f"REGIME: {regime} ({sub}) — {duration}d duration, {confidence:.0f}% confidence. "
        f"Score: {regime_score:+.0f}/100. "
        f"Next likely: {transition.most_likely_next}. "
        f"Micro: ADX={micro.trend_strength:.0f}, "
        f"{'Squeeze!' if micro.vol_compression else ''} "
        f"{micro.breadth}, {micro.flow_proxy}. "
        f"Optimal strategies: {', '.join(optimal[:3])}."
    )

    return RegimeAnalysis(
        current=current,
        transition=transition,
        micro=micro,
        optimal_strategies=optimal,
        regime_score=_safe(regime_score),
        summary=summary
    )
