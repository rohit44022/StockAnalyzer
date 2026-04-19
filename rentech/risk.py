"""
RenTech Risk Management & Portfolio Optimization
═════════════════════════════════════════════════

This is the module that keeps you alive. As Jim Simons said:
"The best signal in the world is worthless if your position
sizing blows up your account."

Implements:
  1. Kelly Criterion (fractional) — optimal position sizing
  2. Volatility Targeting — scale positions to hit target vol
  3. ATR-Based Stop/Target — adaptive risk levels
  4. Drawdown Control — dynamic exposure reduction
  5. Correlation-Aware Sizing — reduce when portfolio is correlated
  6. Transaction Cost Model — Indian market specific (STT, stamp duty)
  7. Risk-Reward Assessment — expected value of the trade

All functions are pure: data in → risk parameters out.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from rentech import config as C
from rentech.statistical import _safe, _pct_returns


# ═══════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════

@dataclass
class PositionSize:
    """Complete position sizing recommendation."""
    shares: int
    capital_allocated: float      # ₹
    capital_pct: float            # % of total capital
    risk_per_trade: float         # ₹ at risk
    risk_pct: float               # % of capital at risk
    method: str                   # KELLY | VOL_TARGET | ATR_RISK
    explanation: str


@dataclass
class RiskLevels:
    """Stop loss, targets, and trailing stops."""
    entry_price: float
    stop_loss: float
    stop_distance_pct: float
    target_1: float               # conservative (1.5 R:R)
    target_2: float               # full (2.5 R:R)
    target_3: float               # stretched (4.0 R:R)
    trailing_stop: float          # current trailing stop level
    risk_reward_1: float
    risk_reward_2: float
    risk_reward_3: float
    atr_value: float
    explanation: str


@dataclass
class TransactionCosts:
    """Indian market transaction cost breakdown."""
    buy_cost_pct: float
    sell_cost_pct: float
    round_trip_pct: float
    round_trip_rupees: float      # for given trade size
    breakeven_move_pct: float     # price must move this much to break even
    explanation: str


@dataclass
class DrawdownControl:
    """Dynamic exposure based on drawdown."""
    current_drawdown_pct: float
    max_drawdown_pct: float
    exposure_multiplier: float    # 0.0–1.0 (reduce when in drawdown)
    status: str                   # NORMAL | CAUTION | REDUCED | HALTED
    explanation: str


@dataclass
class RiskAssessment:
    """Complete risk analysis for a trade."""
    position_size: PositionSize
    risk_levels: RiskLevels
    costs: TransactionCosts
    drawdown: DrawdownControl
    expected_value: float         # ₹ expected P&L
    expected_value_pct: float     # % expected return
    win_probability: float        # estimated from historical
    sharpe_estimate: float        # annualized Sharpe ratio estimate
    max_loss_rupees: float        # worst case ₹ loss
    risk_rating: str              # LOW | MODERATE | HIGH | EXTREME
    summary: str


# ═══════════════════════════════════════════════════════════════
# 1. ATR-BASED RISK LEVELS
# ═══════════════════════════════════════════════════════════════

def compute_risk_levels(
    df: pd.DataFrame,
    direction: str = "LONG",
) -> RiskLevels:
    """
    Compute stop loss and profit targets using ATR.

    ATR is the ONLY volatility-adjusted stop method that adapts
    to each stock's personality. A ₹1000 stock moving 3%/day
    needs wider stops than a ₹1000 stock moving 0.5%/day.

    Jim Simons: "Risk management is more important than signal
    generation. You can have a 55% win rate and still compound
    wealth IF your losses are controlled."
    """
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    n = len(close)

    entry = _safe(close.iloc[-1])

    if n < 20:
        return RiskLevels(
            entry, entry * 0.95, 5.0,
            entry * 1.05, entry * 1.10, entry * 1.15,
            entry * 0.97, 1.0, 2.0, 3.0, 0, "Insufficient data"
        )

    # ATR(14)
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = _safe(tr.rolling(14).mean().iloc[-1])

    if atr < 0.01:
        atr = entry * 0.02  # fallback: 2% of price

    if direction in ("LONG", "STRONG_LONG"):
        stop = entry - C.STOP_ATR_MULTIPLE * atr
        t1 = entry + 1.5 * C.STOP_ATR_MULTIPLE * atr  # 1.5R
        t2 = entry + 2.5 * C.STOP_ATR_MULTIPLE * atr  # 2.5R
        t3 = entry + 4.0 * C.STOP_ATR_MULTIPLE * atr  # 4.0R
        trailing = entry - C.TRAILING_ATR_MULTIPLE * atr
    else:
        stop = entry + C.STOP_ATR_MULTIPLE * atr
        t1 = entry - 1.5 * C.STOP_ATR_MULTIPLE * atr
        t2 = entry - 2.5 * C.STOP_ATR_MULTIPLE * atr
        t3 = entry - 4.0 * C.STOP_ATR_MULTIPLE * atr
        trailing = entry + C.TRAILING_ATR_MULTIPLE * atr

    risk = abs(entry - stop)
    stop_dist = _safe(risk / entry * 100)
    rr1 = _safe(abs(t1 - entry) / risk) if risk > 0 else 0
    rr2 = _safe(abs(t2 - entry) / risk) if risk > 0 else 0
    rr3 = _safe(abs(t3 - entry) / risk) if risk > 0 else 0

    explanation = (
        f"ATR(14) = ₹{atr:.2f} ({atr/entry*100:.2f}% of price). "
        f"Stop = {C.STOP_ATR_MULTIPLE}×ATR from entry. "
        f"Targets at 1.5R (₹{t1:.2f}), 2.5R (₹{t2:.2f}), 4.0R (₹{t3:.2f}). "
        f"Trailing stop = {C.TRAILING_ATR_MULTIPLE}×ATR from current price. "
        f"This ensures the stop adapts to the stock's natural volatility — "
        f"wide enough to avoid noise, tight enough to limit damage."
    )

    return RiskLevels(
        entry_price=_safe(entry), stop_loss=_safe(stop),
        stop_distance_pct=stop_dist,
        target_1=_safe(t1), target_2=_safe(t2), target_3=_safe(t3),
        trailing_stop=_safe(trailing),
        risk_reward_1=rr1, risk_reward_2=rr2, risk_reward_3=rr3,
        atr_value=_safe(atr), explanation=explanation
    )


# ═══════════════════════════════════════════════════════════════
# 2. KELLY CRITERION POSITION SIZING
# ═══════════════════════════════════════════════════════════════

def kelly_position_size(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    entry_price: float,
    capital: float = C.CAPITAL_DEFAULT,
) -> PositionSize:
    """
    Kelly Criterion: f* = (p × b - q) / b

    Where:
      p = win probability
      q = 1 - p (loss probability)
      b = avg_win / avg_loss (win/loss ratio)
      f* = fraction of capital to bet

    We use QUARTER-KELLY (f*/4) because:
    1. Full Kelly assumes perfect knowledge of probabilities
    2. Estimation error can lead to catastrophic overbetting
    3. Quarter-Kelly achieves 75% of growth with 50% of variance

    Jim Simons: "We bet less than the theory suggests. Over-betting
    is the #1 killer of quantitative strategies."
    """
    if avg_loss <= 0 or win_rate <= 0 or win_rate >= 1 or entry_price <= 0 or capital <= 0:
        if entry_price <= 0 or capital <= 0:
            return PositionSize(
                shares=0, capital_allocated=0, capital_pct=0,
                risk_per_trade=0, risk_pct=0,
                method="FIXED_2PCT",
                explanation="Invalid entry price or capital. Cannot compute position size."
            )
        shares = int(capital * 0.02 / max(entry_price, 1))
        return PositionSize(
            shares=shares, capital_allocated=shares * entry_price,
            capital_pct=_safe(shares * entry_price / capital * 100),
            risk_per_trade=0, risk_pct=0,
            method="FIXED_2PCT",
            explanation="Cannot compute Kelly (invalid inputs). Using fixed 2% allocation."
        )

    b = avg_win / avg_loss
    q = 1 - win_rate
    kelly_full = (win_rate * b - q) / b
    kelly_frac = kelly_full * C.KELLY_FRACTION  # quarter-Kelly

    # Clamp to maximum position size
    kelly_frac = max(0, min(kelly_frac, C.MAX_POSITION_PCT))

    allocated = capital * kelly_frac
    shares = int(allocated / max(entry_price, 1))
    actual_allocated = shares * entry_price
    risk_amount = actual_allocated * avg_loss  # expected loss if wrong
    risk_pct = _safe(risk_amount / capital * 100)

    explanation = (
        f"Kelly f* = {kelly_full:.2%} → Quarter-Kelly = {kelly_frac:.2%}. "
        f"Win rate: {win_rate:.0%}, Avg W/L ratio: {b:.2f}. "
        f"Allocate ₹{actual_allocated:,.0f} ({kelly_frac:.1%} of ₹{capital:,.0f}). "
        f"= {shares} shares @ ₹{entry_price:.2f}. "
        f"Max risk: ₹{risk_amount:,.0f} ({risk_pct:.2f}% of capital)."
    )

    return PositionSize(
        shares=shares, capital_allocated=_safe(actual_allocated),
        capital_pct=_safe(kelly_frac * 100),
        risk_per_trade=_safe(risk_amount), risk_pct=risk_pct,
        method="KELLY_QUARTER",
        explanation=explanation
    )


# ═══════════════════════════════════════════════════════════════
# 3. VOLATILITY-TARGETED POSITION SIZING
# ═══════════════════════════════════════════════════════════════

def vol_target_position_size(
    df: pd.DataFrame,
    capital: float = C.CAPITAL_DEFAULT,
    target_vol: float = C.VOL_TARGET_ANNUAL,
) -> PositionSize:
    """
    Size positions to target a specific annualized volatility.

    RenTech sizes every position so that the marginal contribution
    to portfolio volatility is controlled. If a stock is 2x as
    volatile, you hold half the shares.

    Position $ = (Capital × Target Vol) / (Stock Annual Vol × √N)
    where N = number of positions
    """
    close = df["Close"]
    n = len(close)
    entry = _safe(close.iloc[-1])

    if n < 30 or entry <= 0:
        return PositionSize(0, 0, 0, 0, 0, "VOL_TARGET", "Insufficient data")

    ret = _pct_returns(close).dropna()
    daily_vol = _safe(ret.std())
    annual_vol = daily_vol * np.sqrt(C.TRADING_DAYS_PER_YEAR)

    if annual_vol < 0.001:
        annual_vol = 0.05  # conservative fallback 5% (not 20%)

    # Position size = capital × (target_vol / stock_vol) / assumed_positions
    assumed_positions = 10  # diversified portfolio
    alloc_frac = (target_vol / annual_vol) / assumed_positions
    alloc_frac = max(0, min(alloc_frac, C.MAX_POSITION_PCT))

    allocated = capital * alloc_frac
    shares = int(allocated / max(entry, 1))
    actual_allocated = shares * entry

    # Risk at 2-sigma daily move
    daily_risk = actual_allocated * daily_vol * 2
    risk_pct = _safe(daily_risk / capital * 100)

    explanation = (
        f"Stock annual vol: {annual_vol:.1%}. Target portfolio vol: {target_vol:.1%}. "
        f"Allocation: {alloc_frac:.2%} of capital = ₹{actual_allocated:,.0f}. "
        f"= {shares} shares @ ₹{entry:.2f}. "
        f"Daily 2σ risk: ₹{daily_risk:,.0f} ({risk_pct:.2f}% of capital). "
        f"This ensures each position contributes equally to portfolio risk."
    )

    return PositionSize(
        shares=shares, capital_allocated=_safe(actual_allocated),
        capital_pct=_safe(alloc_frac * 100),
        risk_per_trade=_safe(daily_risk), risk_pct=risk_pct,
        method="VOL_TARGET",
        explanation=explanation
    )


# ═══════════════════════════════════════════════════════════════
# 4. TRANSACTION COST MODEL (Indian Market)
# ═══════════════════════════════════════════════════════════════

def compute_transaction_costs(
    entry_price: float,
    shares: int,
    brokerage_per_order: float = 20.0,  # ₹20 flat (Zerodha-style)
) -> TransactionCosts:
    """
    Indian equity delivery transaction costs:
      Buy side:  Stamp Duty (0.015%) + Exchange (0.00345%) + Brokerage + GST
      Sell side: STT (0.1%) + Exchange (0.00345%) + Brokerage + GST

    These costs are REAL and erode alpha. RenTech models every
    basis point of friction because at scale, costs compound.
    """
    trade_value = entry_price * shares
    if trade_value <= 0:
        return TransactionCosts(0, 0, 0, 0, 0, "Zero trade value")

    # Buy side
    stamp = trade_value * C.STAMP_DUTY_BUY
    exchange_buy = trade_value * C.EXCHANGE_FEES
    gst_buy = brokerage_per_order * C.GST_ON_BROKERAGE
    sebi_buy = trade_value * C.SEBI_TURNOVER_FEE
    buy_total = stamp + exchange_buy + brokerage_per_order + gst_buy + sebi_buy
    buy_pct = _safe(buy_total / trade_value * 100)

    # Sell side
    stt = trade_value * C.STT_DELIVERY_SELL
    exchange_sell = trade_value * C.EXCHANGE_FEES
    gst_sell = brokerage_per_order * C.GST_ON_BROKERAGE
    sebi_sell = trade_value * C.SEBI_TURNOVER_FEE
    sell_total = stt + exchange_sell + brokerage_per_order + gst_sell + sebi_sell
    sell_pct = _safe(sell_total / trade_value * 100)

    round_trip = buy_total + sell_total
    round_trip_pct = _safe(round_trip / trade_value * 100)
    breakeven = round_trip_pct  # price must move at least this much

    explanation = (
        f"Trade value: ₹{trade_value:,.0f} ({shares} × ₹{entry_price:.2f}). "
        f"Buy costs: ₹{buy_total:.2f} ({buy_pct:.3f}%) — "
        f"Stamp ₹{stamp:.2f}, Exchange ₹{exchange_buy:.2f}, "
        f"Brokerage ₹{brokerage_per_order:.0f}, GST ₹{gst_buy:.2f}. "
        f"Sell costs: ₹{sell_total:.2f} ({sell_pct:.3f}%) — "
        f"STT ₹{stt:.2f}, Exchange ₹{exchange_sell:.2f}, "
        f"Brokerage ₹{brokerage_per_order:.0f}, GST ₹{gst_sell:.2f}. "
        f"Round-trip: ₹{round_trip:.2f} ({round_trip_pct:.3f}%). "
        f"Price must move ≥{breakeven:.3f}% just to BREAK EVEN."
    )

    return TransactionCosts(
        buy_cost_pct=buy_pct, sell_cost_pct=sell_pct,
        round_trip_pct=round_trip_pct,
        round_trip_rupees=_safe(round_trip),
        breakeven_move_pct=_safe(breakeven),
        explanation=explanation
    )


# ═══════════════════════════════════════════════════════════════
# 5. DRAWDOWN CONTROL
# ═══════════════════════════════════════════════════════════════

def compute_drawdown_control(close: pd.Series) -> DrawdownControl:
    """
    Dynamic exposure reduction when the stock is in drawdown.

    RenTech rule: When cumulative loss exceeds threshold,
    REDUCE position size automatically. Don't wait for
    emotional decision-making.

    Exposure multiplier:
      DD < 5%  → 1.00 (full exposure)
      DD 5-8%  → 0.75 (reduce by 25%)
      DD 8-12% → 0.50 (half exposure)
      DD > 12% → 0.25 (minimal exposure)
      DD > 20% → 0.00 (HALTED)
    """
    n = len(close)
    if n < 10:
        return DrawdownControl(0, 0, 1.0, "NORMAL", "Insufficient data")

    # Compute running drawdown from peak
    peak = close.expanding().max()
    dd = ((close - peak) / peak * 100)
    current_dd = _safe(abs(dd.iloc[-1]))
    max_dd = _safe(abs(dd.min()))

    if current_dd < 5:
        multiplier = 1.0
        status = "NORMAL"
    elif current_dd < 8:
        multiplier = 0.75
        status = "CAUTION"
    elif current_dd < 12:
        multiplier = 0.50
        status = "REDUCED"
    elif current_dd < 20:
        multiplier = 0.25
        status = "REDUCED"
    else:
        multiplier = 0.0
        status = "HALTED"

    explanation = (
        f"Current drawdown from peak: {current_dd:.1f}%. "
        f"Max historical drawdown: {max_dd:.1f}%. "
        f"Exposure multiplier: {multiplier:.0%} ({status}). "
        f"{'⚠ POSITION SIZE REDUCED — drawdown exceeds caution threshold.' if multiplier < 1.0 else ''}"
        f"{'🛑 TRADING HALTED — drawdown exceeds maximum limit.' if multiplier == 0 else ''}"
    )

    return DrawdownControl(
        current_drawdown_pct=current_dd,
        max_drawdown_pct=max_dd,
        exposure_multiplier=multiplier,
        status=status,
        explanation=explanation
    )


# ═══════════════════════════════════════════════════════════════
# 6. COMPLETE RISK ASSESSMENT
# ═══════════════════════════════════════════════════════════════

def compute_risk_assessment(
    df: pd.DataFrame,
    composite_score: float,
    direction: str,
    capital: float = C.CAPITAL_DEFAULT,
) -> RiskAssessment:
    """
    Full risk analysis combining all sub-modules.

    This is the final gate before any trade recommendation.
    Even if the signal is perfect, risk management can veto it.
    """
    close = df["Close"]
    entry = _safe(close.iloc[-1])

    # Risk levels
    risk_levels = compute_risk_levels(df, direction)

    # Estimate win rate from historical performance
    ret = _pct_returns(close).dropna()
    n = len(ret)

    if direction in ("LONG", "STRONG_LONG"):
        # Historical win rate for positive returns
        win_rate = _safe((ret > 0).sum() / max(n, 1))
        avg_win = _safe(ret[ret > 0].mean()) if (ret > 0).any() else 0.01
        avg_loss = _safe(abs(ret[ret < 0].mean())) if (ret < 0).any() else 0.01
    elif direction in ("SHORT", "STRONG_SHORT"):
        win_rate = _safe((ret < 0).sum() / max(n, 1))
        avg_win = _safe(abs(ret[ret < 0].mean())) if (ret < 0).any() else 0.01
        avg_loss = _safe(ret[ret > 0].mean()) if (ret > 0).any() else 0.01
    else:
        win_rate = 0.50
        avg_win = _safe(abs(ret).mean()) if len(ret) > 0 else 0.01
        avg_loss = avg_win

    # Adjust win rate by signal strength
    signal_boost = (abs(composite_score) / 100) * 0.10  # up to 10% boost
    adj_win_rate = min(0.85, max(0.10, win_rate + signal_boost))

    # Guard: NaN win rate (empty return data)
    if np.isnan(adj_win_rate):
        adj_win_rate = 0.50

    # Position sizing (use volatility targeting as primary)
    vol_size = vol_target_position_size(df, capital)
    kelly_size = kelly_position_size(adj_win_rate, avg_win, avg_loss, entry, capital)

    # Use the MORE CONSERVATIVE of the two
    if kelly_size.shares > 0 and vol_size.shares > 0:
        position_size = kelly_size if kelly_size.shares < vol_size.shares else vol_size
    elif vol_size.shares > 0:
        position_size = vol_size
    else:
        position_size = kelly_size

    # Drawdown control
    drawdown = compute_drawdown_control(close)

    # Apply drawdown multiplier
    adjusted_shares = int(position_size.shares * drawdown.exposure_multiplier)
    position_size.shares = adjusted_shares
    position_size.capital_allocated = _safe(adjusted_shares * entry)
    position_size.capital_pct = _safe(adjusted_shares * entry / capital * 100)

    # Transaction costs
    costs = compute_transaction_costs(entry, adjusted_shares)

    # Expected value
    ev_gross = entry * adjusted_shares * (adj_win_rate * avg_win - (1 - adj_win_rate) * avg_loss)
    ev_net = ev_gross - costs.round_trip_rupees
    ev_pct = _safe(ev_net / max(position_size.capital_allocated, 1) * 100)

    # Max loss
    risk_per_share = abs(entry - risk_levels.stop_loss)
    max_loss = risk_per_share * adjusted_shares + costs.round_trip_rupees

    # Annualized Sharpe estimate
    daily_ret_est = _safe(avg_win * win_rate - avg_loss * (1 - win_rate))
    daily_vol_est = _safe(ret.std()) if len(ret) > 0 else 0.02
    sharpe = _safe(daily_ret_est / max(daily_vol_est, 1e-6) * np.sqrt(C.TRADING_DAYS_PER_YEAR))

    # Risk rating
    risk_per_capital = _safe(max_loss / capital * 100)
    if risk_per_capital > 5:
        risk_rating = "EXTREME"
    elif risk_per_capital > 3:
        risk_rating = "HIGH"
    elif risk_per_capital > 1:
        risk_rating = "MODERATE"
    else:
        risk_rating = "LOW"

    summary = (
        f"Position: {adjusted_shares} shares × ₹{entry:.2f} = ₹{position_size.capital_allocated:,.0f} "
        f"({position_size.capital_pct:.1f}% of capital). "
        f"Stop: ₹{risk_levels.stop_loss:.2f} ({risk_levels.stop_distance_pct:.1f}% risk). "
        f"Targets: T1=₹{risk_levels.target_1:.2f} ({risk_levels.risk_reward_1:.1f}R), "
        f"T2=₹{risk_levels.target_2:.2f} ({risk_levels.risk_reward_2:.1f}R), "
        f"T3=₹{risk_levels.target_3:.2f} ({risk_levels.risk_reward_3:.1f}R). "
        f"EV: ₹{ev_net:,.0f} ({ev_pct:+.2f}%). Max loss: ₹{max_loss:,.0f}. "
        f"Costs: ₹{costs.round_trip_rupees:.0f} ({costs.round_trip_pct:.3f}%). "
        f"Risk rating: {risk_rating}. Sharpe est: {sharpe:.2f}."
    )

    return RiskAssessment(
        position_size=position_size,
        risk_levels=risk_levels,
        costs=costs,
        drawdown=drawdown,
        expected_value=_safe(ev_net),
        expected_value_pct=_safe(ev_pct),
        win_probability=_safe(adj_win_rate),
        sharpe_estimate=_safe(sharpe),
        max_loss_rupees=_safe(max_loss),
        risk_rating=risk_rating,
        summary=summary
    )
