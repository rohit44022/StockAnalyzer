"""
RenTech Master Engine — The Orchestrator
════════════════════════════════════════

This is the single entry point. One function call runs the entire
RenTech quant analysis pipeline on any Indian equity.

Pipeline:
  1. Data validation & preparation
  2. Statistical profiling (Hurst, OU, VR, ADF, entropy, ARCH)
  3. Regime detection (HMM-inspired, macro/micro)
  4. Signal generation (7 alpha sources → ensemble)
  5. Risk assessment (Kelly, vol-target, ATR stops, drawdown)
  6. Final verdict with confidence and actionable output

Returns a JSON-serializable dict for web consumption.

Jim Simons: "The whole is greater than the sum of its parts.
Each model alone has a small edge. Together, they compound
into something remarkable."
"""

from __future__ import annotations

import time
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from rentech import config as C
from rentech.statistical import build_statistical_profile, _safe
from rentech.signals import generate_composite_signal, AlphaSignal, CompositeSignal
from rentech.regime import detect_regime, RegimeAnalysis
from rentech.risk import compute_risk_assessment, RiskAssessment


# ═══════════════════════════════════════════════════════════════
# DATA VALIDATION
# ═══════════════════════════════════════════════════════════════

def _validate_data(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Validate OHLCV data before running analysis.
    Returns dict with is_valid, issues, cleaned_df.
    """
    issues = []

    required_cols = ["Open", "High", "Low", "Close", "Volume"]
    for col in required_cols:
        if col not in df.columns:
            issues.append(f"Missing column: {col}")

    if issues:
        return {"is_valid": False, "issues": issues, "df": df}

    n = len(df)
    if n < C.MIN_BARS_REQUIRED:
        issues.append(f"Only {n} bars, need ≥{C.MIN_BARS_REQUIRED}")
        return {"is_valid": False, "issues": issues, "df": df}

    # Check for excessive NaNs
    nan_pct = df[required_cols].isna().sum().max() / n * 100
    if nan_pct > 10:
        issues.append(f"Too many NaN values ({nan_pct:.0f}%)")
        return {"is_valid": False, "issues": issues, "df": df}

    # Forward-fill small gaps, then drop remaining NaNs
    cleaned = df.copy()
    cleaned[required_cols] = cleaned[required_cols].ffill().bfill()

    # Post-ffill NaN check — if still NaN, data is truly missing
    remaining_nan = cleaned[required_cols].isna().sum().sum()
    if remaining_nan > 0:
        cleaned = cleaned.dropna(subset=required_cols)
        issues.append(f"Dropped {remaining_nan} unfillable NaN rows")

    # Verify price sanity
    if (cleaned["Close"] <= 0).any():
        issues.append("Negative or zero prices found")
        cleaned = cleaned[cleaned["Close"] > 0]

    if (cleaned["Volume"] < 0).any():
        cleaned["Volume"] = cleaned["Volume"].clip(lower=0)

    # Sort by date
    if not cleaned.index.is_monotonic_increasing:
        cleaned = cleaned.sort_index()

    return {
        "is_valid": len(issues) == 0 or (nan_pct <= 10 and len(cleaned) >= C.MIN_BARS_REQUIRED),
        "issues": issues,
        "df": cleaned
    }


# ═══════════════════════════════════════════════════════════════
# VERDICT GENERATION
# ═══════════════════════════════════════════════════════════════

def _generate_verdict(
    composite: CompositeSignal,
    regime: RegimeAnalysis,
    risk: RiskAssessment,
    profile_edge: float,
) -> Dict[str, Any]:
    """
    Final verdict combining signal, regime, and risk.
    This is the human-readable trading recommendation.
    """
    score = composite.composite_score
    direction = composite.direction
    conviction = composite.conviction
    regime_str = regime.current.regime
    risk_rating = risk.risk_rating

    # Action matrix
    if risk_rating == "EXTREME":
        action = "AVOID"
        reason = "Risk level is extreme — no trade recommended regardless of signal."
    elif risk.drawdown.status == "HALTED":
        action = "HALT"
        reason = "Drawdown exceeds safety threshold — all trading halted."
    elif direction == "STRONG_LONG" and conviction > 60 and regime_str in ("BULL", "SIDEWAYS"):
        action = "STRONG_BUY"
        reason = f"{int(conviction)}% alpha agreement, {regime_str} regime supports longs."
    elif direction == "LONG" and conviction > 40:
        if regime_str == "BEAR":
            action = "WATCH"
            reason = "Bullish signal but bear regime — wait for regime confirmation."
        else:
            action = "BUY"
            reason = f"Moderate bullish signal ({score:+.0f}) with {conviction:.0f}% agreement."
    elif direction == "STRONG_SHORT" and conviction > 60:
        action = "STRONG_SELL"
        reason = f"Strong bearish signal with {int(conviction)}% agreement."
    elif direction == "SHORT" and conviction > 40:
        if regime_str == "BULL":
            action = "WATCH"
            reason = "Bearish signal but bull regime — proceed with caution."
        else:
            action = "SELL"
            reason = f"Moderate bearish signal ({score:+.0f}) in {regime_str} regime."
    else:
        action = "HOLD"
        reason = (
            f"No clear signal (score={score:+.0f}, conviction={conviction:.0f}%). "
            f"Wait for higher-conviction setup."
        )

    # Confidence grade
    if conviction >= 70 and abs(score) > 50:
        grade = "A"
    elif conviction >= 50 and abs(score) > 30:
        grade = "B"
    elif conviction >= 30 and abs(score) > 15:
        grade = "C"
    else:
        grade = "D"

    # Edge assessment
    if profile_edge > 70:
        edge_desc = "STRONG STATISTICAL EDGE"
    elif profile_edge > 50:
        edge_desc = "MODERATE EDGE"
    elif profile_edge > 30:
        edge_desc = "WEAK EDGE"
    else:
        edge_desc = "NO CLEAR EDGE"

    return {
        "action": action,
        "reason": reason,
        "grade": grade,
        "score": _safe(score),
        "conviction": _safe(conviction),
        "direction": direction,
        "regime": regime_str,
        "sub_regime": regime.current.sub_regime,
        "risk_rating": risk_rating,
        "edge": edge_desc,
        "edge_score": _safe(profile_edge),
        "ev_pct": risk.expected_value_pct,
        "sharpe_est": risk.sharpe_estimate,
        "decay_days": composite.decay_estimate,
    }


# ═══════════════════════════════════════════════════════════════
# SERIALIZATION HELPERS
# ═══════════════════════════════════════════════════════════════

def _alpha_to_dict(a: AlphaSignal) -> Dict[str, Any]:
    return {
        "name": a.name,
        "score": _safe(a.raw_score),
        "weight": _safe(a.weight),
        "confidence": _safe(a.confidence),
        "direction": a.direction,
        "metrics": {k: _safe(v) if isinstance(v, (int, float)) else str(v)
                    for k, v in a.metrics.items()},
        "explanation": a.explanation,
    }


def _risk_to_dict(r: RiskAssessment) -> Dict[str, Any]:
    return {
        "position": {
            "shares": r.position_size.shares,
            "capital": _safe(r.position_size.capital_allocated),
            "capital_pct": _safe(r.position_size.capital_pct),
            "risk_rupees": _safe(r.position_size.risk_per_trade),
            "risk_pct": _safe(r.position_size.risk_pct),
            "method": r.position_size.method,
            "explanation": r.position_size.explanation,
        },
        "levels": {
            "entry": _safe(r.risk_levels.entry_price),
            "stop_loss": _safe(r.risk_levels.stop_loss),
            "stop_distance_pct": _safe(r.risk_levels.stop_distance_pct),
            "target_1": _safe(r.risk_levels.target_1),
            "target_2": _safe(r.risk_levels.target_2),
            "target_3": _safe(r.risk_levels.target_3),
            "trailing_stop": _safe(r.risk_levels.trailing_stop),
            "rr_1": _safe(r.risk_levels.risk_reward_1),
            "rr_2": _safe(r.risk_levels.risk_reward_2),
            "rr_3": _safe(r.risk_levels.risk_reward_3),
            "atr": _safe(r.risk_levels.atr_value),
            "explanation": r.risk_levels.explanation,
        },
        "costs": {
            "buy_pct": _safe(r.costs.buy_cost_pct),
            "sell_pct": _safe(r.costs.sell_cost_pct),
            "round_trip_pct": _safe(r.costs.round_trip_pct),
            "round_trip_rupees": _safe(r.costs.round_trip_rupees),
            "breakeven_pct": _safe(r.costs.breakeven_move_pct),
            "explanation": r.costs.explanation,
        },
        "drawdown": {
            "current_pct": _safe(r.drawdown.current_drawdown_pct),
            "max_pct": _safe(r.drawdown.max_drawdown_pct),
            "exposure_mult": _safe(r.drawdown.exposure_multiplier),
            "status": r.drawdown.status,
            "explanation": r.drawdown.explanation,
        },
        "expected_value": _safe(r.expected_value),
        "expected_value_pct": _safe(r.expected_value_pct),
        "win_probability": _safe(r.win_probability),
        "sharpe_estimate": _safe(r.sharpe_estimate),
        "max_loss_rupees": _safe(r.max_loss_rupees),
        "risk_rating": r.risk_rating,
        "summary": r.summary,
    }


def _regime_to_dict(r: RegimeAnalysis) -> Dict[str, Any]:
    return {
        "current": {
            "regime": r.current.regime,
            "confidence": _safe(r.current.confidence),
            "sub_regime": r.current.sub_regime,
            "duration_days": r.current.duration_days,
            "explanation": r.current.explanation,
        },
        "transition": {
            "to_bull": _safe(r.transition.to_bull),
            "to_bear": _safe(r.transition.to_bear),
            "to_sideways": _safe(r.transition.to_sideways),
            "to_high_vol": _safe(r.transition.to_high_vol),
            "most_likely_next": r.transition.most_likely_next,
            "explanation": r.transition.explanation,
        },
        "micro": {
            "trend_strength": _safe(r.micro.trend_strength),
            "vol_compression": r.micro.vol_compression,
            "breadth": r.micro.breadth,
            "flow_proxy": r.micro.flow_proxy,
            "explanation": r.micro.explanation,
        },
        "optimal_strategies": r.optimal_strategies,
        "regime_score": _safe(r.regime_score),
        "summary": r.summary,
    }


def _profile_to_dict(p) -> Dict[str, Any]:
    return {
        "hurst": {
            "value": _safe(p.hurst.hurst),
            "regime": p.hurst.regime,
            "confidence": _safe(p.hurst.confidence),
            "explanation": p.hurst.interpretation,
        },
        "ou": {
            "half_life": _safe(p.ou.half_life),
            "theta": _safe(p.ou.theta),
            "mu": _safe(p.ou.mu),
            "sigma": _safe(p.ou.sigma),
            "is_tradeable": p.ou.is_tradeable,
            "explanation": p.ou.interpretation,
        },
        "variance_ratio": {
            "ratio": _safe(p.variance_ratio.vr),
            "z_stat": _safe(p.variance_ratio.z_stat),
            "regime": p.variance_ratio.regime,
            "explanation": p.variance_ratio.interpretation,
        },
        "adf": {
            "statistic": _safe(p.adf.adf_stat),
            "is_stationary": p.adf.is_stationary,
            "explanation": p.adf.interpretation,
        },
        "autocorrelation": {
            "lag1": _safe(p.autocorr.lag1),
            "lag5": _safe(p.autocorr.lag5),
            "lag21": _safe(p.autocorr.lag21),
            "pattern": p.autocorr.dominant_pattern,
            "explanation": p.autocorr.interpretation,
        },
        "entropy": {
            "value": _safe(p.entropy.shannon_entropy),
            "normalized": _safe(p.entropy.normalized_entropy),
            "predictability": _safe(p.entropy.predictability),
            "explanation": p.entropy.interpretation,
        },
        "vol_cluster": {
            "persistence": _safe(p.vol_cluster.persistence),
            "arch_ratio": _safe(p.vol_cluster.arch_ratio),
            "vol_state": p.vol_cluster.current_vol_state,
            "explanation": p.vol_cluster.interpretation,
        },
        "scores": {
            "mean_reversion": _safe(p.mean_reversion_score),
            "momentum": _safe(p.momentum_score),
            "predictability": _safe(p.predictability_score),
            "statistical_edge": _safe(p.statistical_edge),
        },
        "optimal_strategy": p.optimal_strategy,
    }


# ═══════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════

def run_rentech_analysis(
    df: pd.DataFrame,
    ticker: str = "",
    capital: float = C.CAPITAL_DEFAULT,
) -> Dict[str, Any]:
    """
    Run the complete RenTech quant analysis on a stock.

    Parameters:
        df: OHLCV DataFrame with DatetimeIndex
        ticker: stock ticker symbol (for display)
        capital: portfolio capital in ₹

    Returns:
        JSON-serializable dict with all analysis results
    """
    start = time.time()

    # ── 0. VALIDATE CAPITAL ──
    if capital <= 0 or np.isnan(capital):
        capital = C.CAPITAL_DEFAULT

    # ── 1. VALIDATE DATA ──
    validation = _validate_data(df)
    if not validation["is_valid"]:
        return {
            "success": False,
            "ticker": ticker,
            "error": "Data validation failed",
            "issues": validation["issues"],
        }
    df = validation["df"]

    try:
        # ── 2. STATISTICAL PROFILING ──
        profile = build_statistical_profile(df["Close"])

        # ── 3. REGIME DETECTION ──
        regime = detect_regime(df, profile)

        # ── 4. SIGNAL GENERATION ──
        composite = generate_composite_signal(
            df, profile, regime.current.regime
        )

        # ── 5. RISK ASSESSMENT ──
        risk = compute_risk_assessment(
            df, composite.composite_score,
            composite.direction, capital
        )

        # ── 6. FINAL VERDICT ──
        verdict = _generate_verdict(
            composite, regime, risk,
            profile.statistical_edge
        )

        elapsed = time.time() - start

        return {
            "success": True,
            "ticker": ticker,
            "version": "1.0.0",
            "compute_time_ms": round(elapsed * 1000),
            "data_bars": len(df),

            "verdict": verdict,

            "statistical_profile": _profile_to_dict(profile),

            "regime": _regime_to_dict(regime),

            "signals": {
                "composite": {
                    "score": _safe(composite.composite_score),
                    "direction": composite.direction,
                    "conviction": _safe(composite.conviction),
                    "quality": _safe(composite.signal_quality),
                    "decay_days": composite.decay_estimate,
                    "explanation": composite.explanation,
                },
                "alphas": [_alpha_to_dict(a) for a in composite.alphas],
            },

            "risk": _risk_to_dict(risk),
        }

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"[RenTech] Error analyzing {ticker}: {e}\n{tb}")
        elapsed = time.time() - start
        return {
            "success": False,
            "ticker": ticker,
            "error": str(e),
            "compute_time_ms": round(elapsed * 1000),
        }
