"""
Risk Metrics & Drawdown Analysis — Ralph Vince Chapters 2, 4, 8

Implements:
  1. Drawdown analysis — max drawdown, drawdown duration, recovery
  2. Risk of ruin calculation
  3. Position sizing from optimal f
  4. Asset allocation — dynamic vs static f
  5. Margin constraint handling (Eq 8.08)
  6. Historical volatility (20-day annualised)
  7. Time-to-goal calculations
  8. Rupee/share averaging analysis
"""

from __future__ import annotations
import math
from typing import List, Optional, Dict
import numpy as np


# ═══════════════════════════════════════════════════════════════════
#  SECTION 1 — DRAWDOWN ANALYSIS
# ═══════════════════════════════════════════════════════════════════

def drawdown_analysis(equity_curve: List[float]) -> dict:
    """
    Comprehensive drawdown analysis of an equity curve.

    Drawdowns are the biggest psychological and financial challenge.
    At optimal f, expect drawdowns of 30-95% of the peak equity.

    Key insight from the book: drawdowns at optimal f are SEVERE.
    This is WHY we use fractional f strategies — to manage the
    drawdown to an acceptable level.

    Returns
    -------
    dict with max_drawdown, current_drawdown, all drawdowns,
    and recovery statistics.
    """
    if not equity_curve or len(equity_curve) < 2:
        return {"error": "Need at least 2 equity points"}

    eq = np.array(equity_curve, dtype=float)
    n = len(eq)

    # Running maximum
    running_max = np.maximum.accumulate(eq)

    # Drawdown at each point
    dd = (eq - running_max) / running_max
    dd_pct = dd * 100

    # Max drawdown
    max_dd_idx = int(np.argmin(dd))
    max_dd_pct = float(dd[max_dd_idx]) * 100

    # Find peak before max drawdown
    peak_idx = int(np.argmax(eq[:max_dd_idx + 1])) if max_dd_idx > 0 else 0
    peak_val = float(eq[peak_idx])
    trough_val = float(eq[max_dd_idx])

    # Recovery from max drawdown
    recovered = False
    recovery_idx = None
    for i in range(max_dd_idx + 1, n):
        if eq[i] >= peak_val:
            recovered = True
            recovery_idx = i
            break

    # Current drawdown
    current_dd_pct = float(dd[-1]) * 100

    # Count all significant drawdowns (> 5%)
    in_dd = False
    drawdowns = []
    dd_start = 0
    for i in range(n):
        if dd[i] < -0.05 and not in_dd:
            in_dd = True
            dd_start = i
        elif (dd[i] >= 0 or i == n - 1) and in_dd:
            in_dd = False
            dd_min = float(dd[dd_start:i+1].min()) * 100
            drawdowns.append({
                "start_idx": dd_start,
                "end_idx": i,
                "depth_pct": round(dd_min, 2),
                "duration": i - dd_start,
            })

    # Average drawdown duration
    avg_dd_duration = (sum(d["duration"] for d in drawdowns) / len(drawdowns)
                       if drawdowns else 0)

    return {
        "max_drawdown_pct": round(max_dd_pct, 2),
        "max_drawdown_peak": round(peak_val, 2),
        "max_drawdown_trough": round(trough_val, 2),
        "max_dd_peak_idx": peak_idx,
        "max_dd_trough_idx": max_dd_idx,
        "recovered": recovered,
        "recovery_trades": recovery_idx - max_dd_idx if recovered else None,
        "current_drawdown_pct": round(current_dd_pct, 2),
        "significant_drawdowns": len(drawdowns),
        "avg_drawdown_duration": round(avg_dd_duration, 1),
        "drawdowns": drawdowns[:20],  # Top 20
        "dd_series": [round(float(v), 4) for v in dd_pct],
        "explanation": (
            f"Maximum drawdown: {max_dd_pct:.1f}% (peak ₹{peak_val:,.0f} → trough ₹{trough_val:,.0f}). "
            + (f"Recovered after {recovery_idx - max_dd_idx} trades. " if recovered else
               "Not yet recovered. ")
            + f"{len(drawdowns)} significant drawdowns (>5%), "
            + f"average duration {avg_dd_duration:.0f} periods. "
            + f"Current drawdown: {current_dd_pct:.1f}%."
        ),
    }


# ═══════════════════════════════════════════════════════════════════
#  SECTION 2 — POSITION SIZING
# ═══════════════════════════════════════════════════════════════════

def position_sizing(
    account_equity: float,
    optimal_f: float,
    biggest_loss: float,
    current_price: float,
    fraction_of_f: float = 1.0,
) -> dict:
    """
    Calculate position size based on optimal f.

    f₹ = |Biggest_Loss| / f   — rupees to allocate per unit
    Units = Account_Equity / f₹
    Shares = Units * (f₹ / Current_Price)

    The fraction_of_f parameter allows trading at a reduced f level
    (recommended for real trading to manage drawdowns).

    Parameters
    ----------
    account_equity : total account value
    optimal_f      : the optimal fraction (0..1)
    biggest_loss   : magnitude of biggest losing trade
    current_price  : current price per share
    fraction_of_f  : what fraction of optimal f to use (0..1, default 1.0)
    """
    if optimal_f <= 0 or biggest_loss <= 0 or current_price <= 0:
        return {"error": "Invalid inputs"}

    effective_f = optimal_f * fraction_of_f
    f_dollar = biggest_loss / effective_f
    units = account_equity / f_dollar
    shares = int(units * (f_dollar / current_price))
    # Risk per trade
    risk_per_trade = account_equity * effective_f

    return {
        "account_equity": round(account_equity, 2),
        "optimal_f": round(optimal_f, 4),
        "fraction_used": round(fraction_of_f, 2),
        "effective_f": round(effective_f, 4),
        "f_dollar": round(f_dollar, 2),
        "units": round(units, 2),
        "shares_to_buy": shares,
        "investment_amount": round(shares * current_price, 2),
        "risk_per_trade": round(risk_per_trade, 2),
        "risk_pct": round(effective_f * 100, 2),
        "current_price": round(current_price, 2),
        "explanation": (
            f"At {fraction_of_f*100:.0f}% of optimal f ({effective_f*100:.2f}%), "
            f"allocate ₹{f_dollar:,.0f} per unit (f₹). "
            f"With ₹{account_equity:,.0f} equity → buy {shares} shares "
            f"(₹{shares * current_price:,.0f}). "
            f"Maximum risk per trade: ₹{risk_per_trade:,.0f} ({effective_f*100:.2f}% of equity)."
        ),
    }


def small_trader_allocation(
    optimal_f_dollar: float,
    margin_per_unit: float,
    max_drawdown: float,
) -> dict:
    """
    Minimum account allocation for a small trader (Chapter 2).

    A = max(f$, Margin + |Drawdown|)

    You need at least f$ to trade one unit at the optimal level.
    But you also need enough to survive the worst drawdown plus margin.
    """
    a = max(optimal_f_dollar, margin_per_unit + abs(max_drawdown))
    return {
        "minimum_allocation": round(a, 2),
        "f_dollar": round(optimal_f_dollar, 2),
        "margin_plus_dd": round(margin_per_unit + abs(max_drawdown), 2),
        "binding_constraint": "f_dollar" if optimal_f_dollar >= margin_per_unit + abs(max_drawdown) else "margin+drawdown",
        "explanation": (
            f"Minimum account: ₹{a:,.0f}. "
            f"(f₹ = ₹{optimal_f_dollar:,.0f}, Margin+DD = ₹{margin_per_unit + abs(max_drawdown):,.0f}). "
            f"The {'optimal f allocation' if a == optimal_f_dollar else 'margin + max drawdown'} is the binding constraint."
        ),
    }


# ═══════════════════════════════════════════════════════════════════
#  SECTION 3 — ASSET ALLOCATION & REALLOCATION (Chapter 8)
# ═══════════════════════════════════════════════════════════════════

def asset_allocation_dynamic(
    total_equity: float,
    active_pct: float,
    optimal_f: float,
    biggest_loss: float,
    current_price: float,
) -> dict:
    """
    Dynamic Fractional f Asset Allocation (Chapter 8).

    Split equity into:
      - Active portion: traded at full optimal f
      - Inactive portion: untouched (cash/risk-free)

    As equity GROWS: active fraction → 1.0 (approach full f)
    As equity FALLS: active fraction → 0.0 (natural protection)

    This creates built-in portfolio insurance WITHOUT buying puts.
    """
    if total_equity <= 0 or active_pct <= 0:
        return {"error": "Invalid inputs"}

    active_equity = total_equity * active_pct
    inactive_equity = total_equity - active_equity

    f_dollar = biggest_loss / optimal_f if optimal_f > 0 else 0
    shares = int(active_equity / current_price) if current_price > 0 else 0

    # Insurance floor = inactive equity
    floor = inactive_equity
    floor_pct = (floor / total_equity) * 100

    return {
        "total_equity": round(total_equity, 2),
        "active_equity": round(active_equity, 2),
        "inactive_equity": round(inactive_equity, 2),
        "active_pct": round(active_pct * 100, 1),
        "shares_to_trade": shares,
        "investment_amount": round(shares * current_price, 2),
        "insurance_floor": round(floor, 2),
        "floor_pct": round(floor_pct, 1),
        "f_dollar": round(f_dollar, 2),
        "explanation": (
            f"Split ₹{total_equity:,.0f} → ₹{active_equity:,.0f} active ({active_pct*100:.0f}%) + "
            f"₹{inactive_equity:,.0f} inactive. Trade {shares} shares at full f on active portion. "
            f"Floor (guaranteed minimum): ₹{floor:,.0f} ({floor_pct:.0f}% of total). "
            f"As active equity grows, your effective f approaches optimal. "
            f"As it shrinks, your exposure automatically decreases — built-in insurance!"
        ),
    }


def margin_constraint(
    f_dollars: List[float],
    margins: List[float],
) -> dict:
    """
    Margin Constraint — Maximum fraction of f (Eq 8.08).

    U = sum(f$_i) / (sum(margin_i) * N)

    This is the highest fraction of f you can use without
    incurring a margin call. If U > 1, use 1.

    Parameters
    ----------
    f_dollars : optimal f in rupees for each market system
    margins   : initial margin requirement for each system
    """
    if not f_dollars or not margins or len(f_dollars) != len(margins):
        return {"error": "Need matching f$ and margin arrays"}

    n = len(f_dollars)
    sum_f = sum(f_dollars)
    sum_margin = sum(margins)

    u = sum_f / (sum_margin * n) if sum_margin * n > 0 else 1.0
    u = min(u, 1.0)

    return {
        "max_fraction": round(u, 4),
        "sum_f_dollar": round(sum_f, 2),
        "sum_margins": round(sum_margin, 2),
        "num_systems": n,
        "explanation": (
            f"Maximum fraction of f without margin call: {u*100:.2f}%. "
            f"(Sum f$ = ₹{sum_f:,.0f}, Sum margins = ₹{sum_margin:,.0f}, N = {n}). "
            + ("You can trade at full optimal f!" if u >= 1.0 else
               f"Must limit to {u*100:.1f}% of optimal f to avoid margin calls.")
        ),
    }


def share_averaging_reallocation(
    total_equity: float,
    inactive_pct_target: float,
    num_periods: int,
) -> dict:
    """
    Share Averaging Reallocation (Chapter 8, Eq 8.02-8.03).

    Periodically pull a percentage from active to inactive equity.

    P = 1 - INACTIVE^(1/N)     — Eq 8.02 (periodic % to reallocate)
    N = ln(INACTIVE) / ln(1-P) — Eq 8.03 (periods to reach target)

    Parameters
    ----------
    total_equity       : current total equity
    inactive_pct_target: target inactive percentage (0..1)
    num_periods        : number of rebalancing periods
    """
    if inactive_pct_target <= 0 or inactive_pct_target >= 1 or num_periods <= 0:
        return {"error": "Invalid inputs"}

    p = 1 - inactive_pct_target ** (1.0 / num_periods)
    p = max(0.0, min(p, 1.0))

    schedule = []
    active = total_equity
    inactive = 0
    for i in range(1, num_periods + 1):
        transfer = active * p
        active -= transfer
        inactive += transfer
        schedule.append({
            "period": i,
            "transfer": round(transfer, 2),
            "active": round(active, 2),
            "inactive": round(inactive, 2),
            "inactive_pct": round((inactive / total_equity) * 100, 1),
        })

    return {
        "periodic_pct": round(p * 100, 2),
        "num_periods": num_periods,
        "target_inactive_pct": round(inactive_pct_target * 100, 1),
        "schedule": schedule,
        "explanation": (
            f"Reallocate {p*100:.2f}% from active to inactive each period. "
            f"After {num_periods} periods, {inactive_pct_target*100:.0f}% will be inactive. "
            f"This provides systematic risk reduction while allowing active trading."
        ),
    }


# ═══════════════════════════════════════════════════════════════════
#  SECTION 4 — HISTORICAL VOLATILITY (Chapter 5)
# ═══════════════════════════════════════════════════════════════════

def historical_volatility(
    closes: List[float],
    period: int = 20,
    trading_days_per_year: int = 252,
) -> dict:
    """
    Historical Volatility — annualised standard deviation of log returns.

    HV = SD(ln(close_i/close_{i-1})) * sqrt(trading_days)

    This is the same volatility used in Black-Scholes and
    other option pricing models. It measures the "wildness" of
    price movements.

    Parameters
    ----------
    closes : list of closing prices
    period : lookback window (default 20 days)
    trading_days_per_year : annualisation factor (default 252)
    """
    if len(closes) < period + 1:
        return {"error": f"Need at least {period + 1} closing prices"}

    arr = np.array(closes, dtype=float)
    log_returns = np.log(arr[1:] / arr[:-1])

    # Rolling volatility
    vols = []
    dates_idx = []
    for i in range(period, len(log_returns)):
        window = log_returns[i - period:i]
        vol = float(np.std(window, ddof=0)) * math.sqrt(trading_days_per_year)
        vols.append(round(vol * 100, 2))  # as percentage
        dates_idx.append(i + 1)  # offset for the first close

    current_vol = vols[-1] if vols else 0
    avg_vol = sum(vols) / len(vols) if vols else 0
    max_vol = max(vols) if vols else 0
    min_vol = min(vols) if vols else 0

    return {
        "current_volatility_pct": round(current_vol, 2),
        "average_volatility_pct": round(avg_vol, 2),
        "max_volatility_pct": round(max_vol, 2),
        "min_volatility_pct": round(min_vol, 2),
        "period": period,
        "vol_series": vols,
        "annualisation_factor": trading_days_per_year,
        "explanation": (
            f"Current {period}-day annualised volatility: {current_vol:.1f}% "
            f"(avg: {avg_vol:.1f}%, range: {min_vol:.1f}%–{max_vol:.1f}%). "
            + ("HIGH volatility — larger position swings expected. Consider reducing f fraction."
               if current_vol > avg_vol * 1.5 else
               "NORMAL volatility range." if current_vol > avg_vol * 0.5 else
               "LOW volatility — potential squeeze building.")
        ),
    }


# ═══════════════════════════════════════════════════════════════════
#  SECTION 5 — TIME TO GOAL CALCULATIONS (Chapter 2)
# ═══════════════════════════════════════════════════════════════════

def time_to_goal(
    geometric_mean: float,
    goal_multiple: float = 2.0,
) -> dict:
    """
    How many trades to reach a given equity multiple?

    N = ln(Goal) / ln(G)   — Eq 2.09a

    Parameters
    ----------
    geometric_mean : the geometric mean HPR
    goal_multiple  : target (e.g., 2.0 = double your money)
    """
    if geometric_mean <= 1.0 or goal_multiple <= 1.0:
        return {"trades_needed": None, "explanation": "Cannot reach goal — geometric mean ≤ 1"}

    n = math.log(goal_multiple) / math.log(geometric_mean)

    return {
        "trades_needed": round(n, 0),
        "geometric_mean": round(geometric_mean, 6),
        "goal_multiple": goal_multiple,
        "explanation": (
            f"At geometric mean {geometric_mean:.4f}, need ~{n:.0f} trades to "
            f"multiply equity by {goal_multiple}x."
        ),
    }


# ═══════════════════════════════════════════════════════════════════
#  SECTION 6 — COMPREHENSIVE RISK REPORT
# ═══════════════════════════════════════════════════════════════════

def comprehensive_risk_report(
    trades: List[float],
    equity_curve: Optional[List[float]] = None,
    closes: Optional[List[float]] = None,
    account_equity: float = 100000,
    current_price: float = 100,
) -> dict:
    """
    Generate a comprehensive risk report combining all Vince metrics.

    This is the master function that runs everything and produces
    a layman-friendly risk assessment with all the book's key metrics.
    """
    from vince.optimal_f import (
        find_optimal_f_empirical, compute_by_products, 
        fractional_f_analysis, f_curve_data,
        kelly_f, estimated_geometric_mean, fundamental_equation_of_trading,
        threshold_to_geometric,
    )
    from vince.statistics import (
        runs_test, serial_correlation, ks_test_normal,
        compute_moments, arc_sine_analysis, turning_points_test,
    )

    report = {"sections": {}}

    # 1. Optimal f
    opt = find_optimal_f_empirical(trades)
    report["sections"]["optimal_f"] = opt

    # 2. By-products
    if opt["optimal_f"] > 0:
        bp = compute_by_products(trades, opt["optimal_f"])
        report["sections"]["by_products"] = bp

        # 3. f-curve data for chart
        fc = f_curve_data(trades, points=50)
        report["sections"]["f_curve"] = fc

        # 4. Fractional f analysis
        frac = fractional_f_analysis(
            bp["ahpr"], bp["sd_hpr"], opt["optimal_f"], opt["biggest_loss"]
        )
        report["sections"]["fractional_f"] = frac

        # 5. Fundamental equation
        egm = estimated_geometric_mean(bp["ahpr"], bp["sd_hpr"])
        fet = fundamental_equation_of_trading(bp["ahpr"], bp["sd_hpr"], len(trades))
        report["sections"]["fundamental_equation"] = {
            "egm": round(egm, 6),
            "estimated_twr": round(fet, 4),
            "actual_twr": bp["twr"],
        }

        # 6. Threshold to geometric
        avg_trade = sum(trades) / len(trades)
        thr = threshold_to_geometric(avg_trade, bp["gat"], opt["biggest_loss"], opt["optimal_f"])
        report["sections"]["threshold"] = {
            "value": round(thr, 2),
            "account_equity": account_equity,
            "above_threshold": account_equity >= thr,
        }

        # 7. Position sizing
        ps = position_sizing(account_equity, opt["optimal_f"], opt["biggest_loss"], current_price, 0.5)
        report["sections"]["position_sizing"] = ps

    # 8. Statistical tests
    report["sections"]["runs_test"] = runs_test(trades)
    report["sections"]["serial_correlation"] = serial_correlation(trades)
    report["sections"]["ks_test"] = ks_test_normal(trades)
    report["sections"]["moments"] = compute_moments(trades)
    report["sections"]["turning_points"] = turning_points_test(trades)
    report["sections"]["arc_sine"] = arc_sine_analysis(len(trades))

    # 9. Kelly criterion approximation
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t < 0]
    if wins and losses:
        wp = len(wins) / len(trades)
        wlr = (sum(wins) / len(wins)) / abs(sum(losses) / len(losses))
        report["sections"]["kelly"] = kelly_f(wp, wlr)

    # 10. Drawdown analysis
    if equity_curve:
        report["sections"]["drawdown"] = drawdown_analysis(equity_curve)

    # 11. Volatility
    if closes and len(closes) > 21:
        report["sections"]["volatility"] = historical_volatility(closes)

    return report
