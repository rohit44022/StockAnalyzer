"""
ai_ml/position_sizer.py — Vince-Based Position Sizing

Connects the existing Vince Optimal-f and Kelly modules to
produce per-pick position size recommendations.

Uses the method's backtest win rate and R:R ratio to compute
how much capital to allocate to each pick.

Adds sizing fields to picks WITHOUT modifying existing fields.
"""
from __future__ import annotations

import json
import os
import logging

from ai_ml.config import (
    METHOD_ROUTER_DATA, DEFAULT_CAPITAL,
    MAX_SINGLE_POSITION_PCT, MIN_SINGLE_POSITION_PCT,
)

logger = logging.getLogger("ai_ml.position_sizer")

# Backtest stats per method (fallback if router data missing)
_FALLBACK_STATS = {
    "M1": {"win_rate": 0.49, "avg_winner_r": 1.6, "avg_loser_r": 1.0, "profit_factor": 1.44},
    "M2": {"win_rate": 0.472, "avg_winner_r": 1.5, "avg_loser_r": 1.0, "profit_factor": 1.34},
    "M3": {"win_rate": 0.455, "avg_winner_r": 1.5, "avg_loser_r": 1.0, "profit_factor": 1.25},
    "M4": {"win_rate": 0.451, "avg_winner_r": 1.5, "avg_loser_r": 1.0, "profit_factor": 1.23},
}


def _load_method_stats() -> dict:
    """Load per-method stats from router data, fall back to hardcoded."""
    if os.path.exists(METHOD_ROUTER_DATA):
        try:
            with open(METHOD_ROUTER_DATA) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _kelly_fraction(win_rate: float, win_loss_ratio: float) -> float:
    """
    Kelly Criterion: f* = W - (1-W)/R
    where W = win_rate, R = avg_winner / avg_loser

    Returns the fraction of capital to risk (0-1).
    Capped at half-Kelly for safety (full Kelly is too aggressive).
    """
    if win_loss_ratio <= 0:
        return 0.0
    f = win_rate - (1 - win_rate) / win_loss_ratio
    # Half-Kelly is the standard conservative approach
    f = f / 2.0
    return max(0.0, min(f, MAX_SINGLE_POSITION_PCT))


def compute_position_sizes(
    picks: list[dict],
    capital: float = DEFAULT_CAPITAL,
) -> list[dict]:
    """
    Compute recommended position size for each pick using Kelly/Vince.

    Added fields per pick:
      - size_kelly_fraction: raw half-Kelly fraction (0-1)
      - size_recommended_pct: recommended % of capital (capped)
      - size_recommended_amount: ₹ amount to allocate
      - size_shares: approximate share count
      - size_risk_per_trade: ₹ at risk (entry - stop) × shares
      - size_method_stats: {win_rate, avg_winner_r, avg_loser_r} used
    """
    router_data = _load_method_stats()

    for pick in picks:
        method = pick.get("method", "M2")
        price = pick.get("price") or pick.get("current_price") or 0

        # Get method stats (from ML router or fallback)
        if method in router_data:
            rd = router_data[method]
            win_rate = rd.get("overall_win_rate", _FALLBACK_STATS.get(method, {}).get("win_rate", 0.45))
            stats = _FALLBACK_STATS.get(method, {})
        else:
            stats = _FALLBACK_STATS.get(method, {})
            win_rate = stats.get("win_rate", 0.45)

        avg_w = stats.get("avg_winner_r", 1.5)
        avg_l = stats.get("avg_loser_r", 1.0)
        wl_ratio = avg_w / avg_l if avg_l > 0 else 1.5

        kelly = _kelly_fraction(win_rate, wl_ratio)

        # Adjust kelly by ML confidence if available
        ml_conf = pick.get("ml_confidence")
        if ml_conf is not None:
            # Scale Kelly by ML confidence — high confidence = full Kelly, low = reduce
            kelly = kelly * (0.5 + ml_conf * 0.5)

        # Clamp to bounds
        rec_pct = max(MIN_SINGLE_POSITION_PCT, min(MAX_SINGLE_POSITION_PCT, kelly))
        rec_amount = capital * rec_pct
        shares = int(rec_amount / price) if price > 0 else 0
        actual_amount = shares * price

        # Risk per trade
        stop = pick.get("stop_loss") or pick.get("stop", 0)
        risk_per_share = (price - stop) if stop and stop > 0 else price * 0.02
        total_risk = risk_per_share * shares

        pick["size_kelly_fraction"] = round(kelly, 4)
        pick["size_recommended_pct"] = round(rec_pct * 100, 1)
        pick["size_recommended_amount"] = round(actual_amount, 0)
        pick["size_shares"] = shares
        pick["size_risk_per_trade"] = round(total_risk, 0)
        pick["size_method_stats"] = {
            "win_rate": round(win_rate, 4),
            "avg_winner_r": avg_w,
            "avg_loser_r": avg_l,
            "profit_factor": stats.get("profit_factor", 0),
        }

    return picks
