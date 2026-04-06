"""
risk_manager.py — Money Management & Position Sizing.

Murphy Ch 16: "Money Management and Trading Tactics"

Core rules implemented:
  1. Never risk more than 1–2% of capital on a single trade
  2. Maximum portfolio risk: 6%
  3. Risk:Reward ratio minimum 1:2
  4. Position sizing based on ATR stop-loss distance
  5. Multiple stop-loss methods (ATR, %, support, MA)
  6. Kelly Criterion (for optimal sizing)
"""

from __future__ import annotations

import math
from technical_analysis.config import (
    MAX_RISK_PER_TRADE,
    MAX_PORTFOLIO_RISK,
    DEFAULT_CAPITAL,
    RISK_FREE_RATE,
)


# ═══════════════════════════════════════════════════════════════
#  POSITION SIZING
# ═══════════════════════════════════════════════════════════════

def calculate_position_size(
    entry: float,
    stop_loss: float,
    capital: float = DEFAULT_CAPITAL,
    risk_pct: float = MAX_RISK_PER_TRADE,
) -> dict:
    """
    Calculate how many shares to buy based on the 2% rule.

    Formula:
        Risk Amount = Capital × Risk%
        Risk Per Share = Entry - Stop Loss
        Shares = Risk Amount / Risk Per Share
    """
    risk_per_share = abs(entry - stop_loss)
    if risk_per_share <= 0:
        return {"error": "Stop loss must be different from entry price"}

    risk_amount = capital * risk_pct
    shares = int(risk_amount / risk_per_share)
    # Cap position size to total capital
    max_shares = int(capital / entry)
    shares = min(shares, max_shares)
    position_value = shares * entry
    pct_of_capital = (position_value / capital * 100) if capital > 0 else 0

    return {
        "shares": shares,
        "entry": round(entry, 2),
        "stop_loss": round(stop_loss, 2),
        "risk_per_share": round(risk_per_share, 2),
        "risk_amount": round(risk_amount, 2),
        "position_value": round(position_value, 2),
        "pct_of_capital": round(pct_of_capital, 1),
        "explanation": (
            f"With ₹{capital:,.0f} capital and {risk_pct*100:.0f}% max risk per trade, "
            f"you can risk ₹{risk_amount:,.0f}. "
            f"At entry ₹{entry:.2f} with stop ₹{stop_loss:.2f} "
            f"(risk = ₹{risk_per_share:.2f}/share), "
            f"buy {shares} shares (₹{position_value:,.0f} = {pct_of_capital:.1f}% of capital)."
        ),
    }


# ═══════════════════════════════════════════════════════════════
#  STOP LOSS METHODS
# ═══════════════════════════════════════════════════════════════

def calculate_stop_losses(snap: dict, sr_data: dict) -> dict:
    """
    Calculate multiple stop loss levels using different methods.

    Methods:
      1. ATR Stop (2× ATR below entry) — most reliable
      2. Percentage Stop (5%, 8%)
      3. Support Level Stop (below nearest support)
      4. Moving Average Stop (below 20-SMA or 50-SMA)
      5. Supertrend Stop
    """
    price = snap.get("price")
    if not price:
        return {"error": "No price data"}

    stops = {}

    # 1. ATR Stop
    atr = snap.get("atr")
    if atr:
        atr_2x_level = max(price - 2 * atr, price * 0.01)  # Floor at 1% of price
        atr_3x_level = max(price - 3 * atr, price * 0.01)
        stops["atr_2x"] = {
            "level": round(atr_2x_level, 2),
            "method": "2× ATR below price",
            "explanation": (
                f"Stop at ₹{atr_2x_level:.2f} — this accounts for normal volatility. "
                f"ATR = ₹{atr:.2f}, so 2× ATR = ₹{2*atr:.2f} cushion."
            ),
        }
        stops["atr_3x"] = {
            "level": round(atr_3x_level, 2),
            "method": "3× ATR below price (wider)",
            "explanation": f"Wider stop at ₹{atr_3x_level:.2f} for swing trades.",
        }

    # 2. Percentage Stop
    for pct in [0.05, 0.08]:
        stops[f"pct_{int(pct*100)}"] = {
            "level": round(price * (1 - pct), 2),
            "method": f"{int(pct*100)}% below entry",
            "explanation": f"Stop at ₹{price*(1-pct):.2f} ({int(pct*100)}% loss from entry).",
        }

    # 3. Support Level Stop
    supports = sr_data.get("support", [])
    if supports:
        nearest = supports[0]["level"]
        stops["support"] = {
            "level": round(nearest * 0.99, 2),  # Just below support
            "method": f"Below nearest support (₹{nearest})",
            "explanation": (
                f"Stop at ₹{nearest*0.99:.2f} — just below the nearest "
                f"support level at ₹{nearest}. If support breaks, exit."
            ),
        }

    # 4. Moving Average Stop
    for ma_key, ma_name in [("sma_20", "20-day SMA"), ("sma_50", "50-day SMA")]:
        ma_val = snap.get(ma_key)
        if ma_val and ma_val < price:
            stops[ma_key] = {
                "level": round(ma_val * 0.99, 2),
                "method": f"Below {ma_name}",
                "explanation": f"Stop at ₹{ma_val*0.99:.2f} — below the {ma_name} (₹{ma_val:.2f}).",
            }

    # 5. Supertrend Stop
    st = snap.get("supertrend")
    if st and snap.get("supertrend_bullish"):
        stops["supertrend"] = {
            "level": round(st, 2),
            "method": "Supertrend level",
            "explanation": f"Stop at ₹{st:.2f} — the Supertrend acts as a dynamic trailing stop.",
        }

    # Recommend best stop
    if "atr_2x" in stops:
        recommended = "atr_2x"
    elif "support" in stops:
        recommended = "support"
    elif "pct_5" in stops:
        recommended = "pct_5"
    else:
        recommended = list(stops.keys())[0] if stops else None

    return {
        "stops": stops,
        "recommended": recommended,
        "recommended_level": stops[recommended]["level"] if recommended else None,
    }


# ═══════════════════════════════════════════════════════════════
#  RISK : REWARD CALCULATION
# ═══════════════════════════════════════════════════════════════

def calculate_risk_reward(
    entry: float,
    stop_loss: float,
    target: float,
) -> dict:
    """
    Calculate risk:reward ratio and expected value.

    Murphy: "Only take trades with at least 1:2 risk:reward."
    """
    risk = abs(entry - stop_loss)
    reward = abs(target - entry)

    if risk <= 0:
        return {"error": "Invalid stop loss"}

    ratio = reward / risk
    is_acceptable = ratio >= 2.0

    # Expected value with 40% win rate (realistic for trend following)
    win_rate = 0.40
    ev = (win_rate * reward) - ((1 - win_rate) * risk)

    return {
        "entry": round(entry, 2),
        "stop_loss": round(stop_loss, 2),
        "target": round(target, 2),
        "risk": round(risk, 2),
        "reward": round(reward, 2),
        "ratio": round(ratio, 2),
        "ratio_display": f"1:{ratio:.1f}",
        "is_acceptable": is_acceptable,
        "expected_value": round(ev, 2),
        "explanation": (
            f"Risk ₹{risk:.2f} to make ₹{reward:.2f} → "
            f"R:R = 1:{ratio:.1f}. "
            f"{'✅ ACCEPTABLE — reward justifies the risk.' if is_acceptable else '❌ TOO RISKY — reward doesn\'t justify the risk. Min 1:2 needed.'} "
            f"With 40% win rate, expected value per share = ₹{ev:.2f}."
        ),
    }


# ═══════════════════════════════════════════════════════════════
#  KELLY CRITERION
# ═══════════════════════════════════════════════════════════════

def kelly_criterion(win_rate: float = 0.45, avg_win: float = 2.0, avg_loss: float = 1.0) -> dict:
    """
    Kelly Criterion: Optimal fraction of capital to bet.

    f* = (bp - q) / b
    where:  b = average win/loss ratio
            p = probability of winning
            q = 1 - p
    """
    b = avg_win / avg_loss if avg_loss > 0 else 1.0
    p = win_rate
    q = 1 - p

    kelly = (b * p - q) / b if b > 0 else 0
    half_kelly = kelly / 2  # Murphy recommends conservative sizing

    return {
        "kelly_pct": round(max(kelly * 100, 0), 1),
        "half_kelly_pct": round(max(half_kelly * 100, 0), 1),
        "win_rate": round(win_rate * 100, 1),
        "avg_win_loss_ratio": round(b, 2),
        "explanation": (
            f"With a {win_rate*100:.0f}% win rate and {b:.1f}:1 avg win/loss, "
            f"Kelly suggests risking {kelly*100:.1f}% per trade. "
            f"Half-Kelly (safer) = {half_kelly*100:.1f}%. "
            f"Murphy recommends conservative sizing — use Half-Kelly or less."
        ),
    }


# ═══════════════════════════════════════════════════════════════
#  COMPREHENSIVE RISK REPORT
# ═══════════════════════════════════════════════════════════════

def generate_risk_report(
    snap: dict,
    sr_data: dict,
    capital: float = DEFAULT_CAPITAL,
) -> dict:
    """
    Generate a complete risk management report:
      - Multiple stop loss levels
      - Position sizing for each stop
      - Risk:Reward ratio to nearest resistance
      - Kelly criterion
    """
    price = snap.get("price")
    if not price:
        return {"error": "No price data available"}

    # Calculate stops
    stop_data = calculate_stop_losses(snap, sr_data)

    # Position sizing with recommended stop
    rec_stop = stop_data.get("recommended_level")
    position = {}
    if rec_stop and rec_stop < price:
        position = calculate_position_size(price, rec_stop, capital)

    # Risk:Reward to nearest resistance
    rr = {}
    resistances = sr_data.get("resistance", [])
    if resistances and rec_stop and rec_stop < price:
        target = resistances[0]["level"]
        if target > price:
            rr = calculate_risk_reward(price, rec_stop, target)

    # Kelly
    kelly = kelly_criterion()

    return {
        "price": round(price, 2),
        "capital": capital,
        "stop_losses": stop_data,
        "position_sizing": position,
        "risk_reward": rr,
        "kelly": kelly,
        "max_risk_per_trade": f"{MAX_RISK_PER_TRADE*100:.0f}%",
        "max_portfolio_risk": f"{MAX_PORTFOLIO_RISK*100:.0f}%",
        "rules": [
            f"Never risk more than {MAX_RISK_PER_TRADE*100:.0f}% of capital (₹{capital*MAX_RISK_PER_TRADE:,.0f}) on any single trade.",
            f"Maximum total portfolio risk: {MAX_PORTFOLIO_RISK*100:.0f}% (₹{capital*MAX_PORTFOLIO_RISK:,.0f}).",
            "Always use a stop loss — never trade without one.",
            "Minimum Risk:Reward ratio: 1:2 (risk ₹1 to potentially make ₹2).",
            "Cut losses quickly, let winners run.",
            "Scale into positions — don't buy all at once.",
        ],
    }
