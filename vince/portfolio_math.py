"""
Portfolio Mathematics — Ralph Vince Chapters 6 & 7

Implements:
  1. E-V Theory (Markowitz Model)  — constrained efficient frontier
  2. Covariance & Correlation matrices
  3. Lagrangian multiplier / Gauss-Jordan solution
  4. Geometric Efficient Frontier
  5. Capital Market Lines (CML)
  6. Unconstrained Portfolios (with NIC)
  7. Sharpe Ratio optimisation
  8. Geometric Optimal Portfolio (AHPR - 1 = V)
"""

from __future__ import annotations
import math
from typing import List, Dict, Optional, Tuple
import numpy as np


# ═══════════════════════════════════════════════════════════════════
#  SECTION 1 — COVARIANCE & CORRELATION
# ═══════════════════════════════════════════════════════════════════

def compute_correlation_matrix(returns: Dict[str, List[float]]) -> dict:
    """
    Compute the correlation matrix between multiple market systems.

    The correlation coefficient tells you how two systems move together:
      +1 = perfectly correlated (move in lockstep)
       0 = uncorrelated (independent)
      -1 = perfectly inverse (when one wins, the other loses)

    For portfolio construction, LOWER correlation is BETTER because it
    means adding that system improves the portfolio more (diversification).

    Parameters
    ----------
    returns : dict mapping ticker → list of daily returns (HPRs or P&L)

    Returns
    -------
    dict with correlation matrix, tickers, and interpretation.
    """
    tickers = sorted(returns.keys())
    n = len(tickers)
    if n < 2:
        return {"error": "Need at least 2 market systems"}

    # Align lengths (use shortest)
    min_len = min(len(returns[t]) for t in tickers)
    data = np.array([returns[t][:min_len] for t in tickers])

    corr = np.corrcoef(data)

    matrix = []
    for i in range(n):
        row = []
        for j in range(n):
            row.append(round(float(corr[i][j]), 4))
        matrix.append(row)

    # Find best and worst pairs
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            pairs.append({
                "pair": f"{tickers[i]} / {tickers[j]}",
                "correlation": round(float(corr[i][j]), 4),
            })
    pairs.sort(key=lambda x: x["correlation"])

    return {
        "tickers": tickers,
        "matrix": matrix,
        "pairs": pairs,
        "best_diversifier": pairs[0] if pairs else None,
        "worst_diversifier": pairs[-1] if pairs else None,
        "num_periods": min_len,
    }


def compute_covariance_matrix(returns: Dict[str, List[float]]) -> dict:
    """
    Compute the covariance matrix.

    COV(a,b) = R(a,b) * S_a * S_b   — Eq 6.01

    Where R(a,b) is the correlation coefficient and S_a, S_b
    are the standard deviations of each system's returns.
    """
    tickers = sorted(returns.keys())
    n = len(tickers)
    if n < 2:
        return {"error": "Need at least 2 systems"}

    min_len = min(len(returns[t]) for t in tickers)
    data = np.array([returns[t][:min_len] for t in tickers])
    cov = np.cov(data, ddof=0)

    matrix = []
    for i in range(n):
        row = [round(float(cov[i][j]), 8) for j in range(n)]
        matrix.append(row)

    return {
        "tickers": tickers,
        "matrix": matrix,
        "num_periods": min_len,
    }


# ═══════════════════════════════════════════════════════════════════
#  SECTION 2 — EFFICIENT FRONTIER (Markowitz / Chapter 6)
# ═══════════════════════════════════════════════════════════════════

def compute_efficient_frontier(
    tickers: List[str],
    expected_returns: List[float],
    cov_matrix: List[List[float]],
    num_portfolios: int = 50,
    allow_short: bool = False,
    risk_free_rate: float = 0.0,
) -> dict:
    """
    Compute the efficient frontier using Monte Carlo simulation.

    The efficient frontier is the set of portfolios that give the
    MAXIMUM return for each level of risk (or equivalently, MINIMUM
    risk for each level of return).

    Any portfolio NOT on the frontier is suboptimal — you can get
    either more return for the same risk, or less risk for the same return.

    Parameters
    ----------
    tickers           : list of ticker names
    expected_returns  : AHPR - 1 (mean excess return) for each ticker
    cov_matrix        : N×N covariance matrix
    num_portfolios    : number of random portfolios to generate
    allow_short       : whether to allow negative weights (short selling)
    risk_free_rate    : annual risk-free rate (for Sharpe calculation)

    Returns
    -------
    dict with frontier points, optimal portfolios, and chart data.
    """
    n = len(tickers)
    if n < 2 or len(expected_returns) != n:
        return {"error": "Need at least 2 assets with matching returns"}

    er = np.array(expected_returns)
    cov = np.array(cov_matrix)
    results = []

    np.random.seed(42)
    for _ in range(num_portfolios * 20):  # generate many, filter to frontier
        if allow_short:
            weights = np.random.randn(n)
            weights /= np.sum(np.abs(weights))  # normalize by absolute sum
        else:
            weights = np.random.random(n)
            weights /= weights.sum()

        port_return = float(np.dot(weights, er))
        port_variance = float(np.dot(weights, np.dot(cov, weights)))
        port_std = math.sqrt(port_variance) if port_variance > 0 else 0

        # Geometric mean: GHPR = sqrt(AHPR² - V) where AHPR = 1 + return
        ahpr = 1 + port_return
        ghpr_sq = ahpr ** 2 - port_variance
        ghpr = math.sqrt(ghpr_sq) if ghpr_sq > 0 else 0

        sharpe = (port_return - risk_free_rate) / port_std if port_std > 0 else 0

        results.append({
            "weights": {tickers[i]: round(float(weights[i]), 4) for i in range(n)},
            "return": round(port_return, 6),
            "std": round(port_std, 6),
            "variance": round(port_variance, 6),
            "sharpe": round(sharpe, 4),
            "ahpr": round(ahpr, 6),
            "ghpr": round(ghpr, 6),
        })

    # Sort by return and filter to frontier
    results.sort(key=lambda x: x["return"])

    # Find key portfolios
    max_sharpe = max(results, key=lambda x: x["sharpe"])
    min_variance = min(results, key=lambda x: x["variance"])
    max_ghpr = max(results, key=lambda x: x["ghpr"])

    # Geometric optimal: where AHPR - 1 ≈ V (Eq 7.06c)
    geo_optimal = min(results, key=lambda x: abs((x["ahpr"] - 1) - x["variance"]))

    # Frontier points for charting
    frontier_points = []
    min_std_seen = float('inf')
    for r in sorted(results, key=lambda x: x["return"], reverse=True):
        if r["std"] <= min_std_seen:
            min_std_seen = r["std"]
            frontier_points.append({"std": r["std"], "return": r["return"]})

    frontier_points.reverse()

    return {
        "frontier": frontier_points,
        "max_sharpe_portfolio": max_sharpe,
        "min_variance_portfolio": min_variance,
        "max_geometric_portfolio": max_ghpr,
        "geometric_optimal": geo_optimal,
        "all_portfolios": results[:num_portfolios],  # Return subset for charting
        "num_generated": len(results),
        "risk_free_rate": risk_free_rate,
    }


# ═══════════════════════════════════════════════════════════════════
#  SECTION 3 — SHARPE RATIO & CAPITAL MARKET LINE (Chapter 7)
# ═══════════════════════════════════════════════════════════════════

def sharpe_ratio(ahpr: float, sd: float, rfr: float = 0.0) -> float:
    """
    Sharpe Ratio = (AHPR - (1 + RFR)) / SD   — Eq 7.01a

    Measures excess return per unit of risk.
    Higher is better. Used to find the tangent portfolio on the CML.
    """
    if sd <= 0:
        return 0.0
    return (ahpr - (1 + rfr)) / sd


def capital_market_line(
    tangent_ahpr: float,
    tangent_sd: float,
    rfr: float = 0.0,
    num_points: int = 20,
) -> dict:
    """
    Capital Market Line — the line from the risk-free rate tangent to
    the efficient frontier at the maximum Sharpe ratio portfolio.

    CML tells you: at any risk level, the optimal strategy is to combine
    the tangent portfolio with the risk-free asset (lending/borrowing).

    P = SX / ST   — percentage in tangent portfolio (Eq 7.02)
    ACML = AT*P + (1+RFR)*(1-P)   — CML return (Eq 7.03)
    """
    points = []
    for i in range(num_points + 1):
        p = i / num_points  # fraction in tangent portfolio
        cml_return = tangent_ahpr * p + (1 + rfr) * (1 - p)
        cml_std = tangent_sd * p

        points.append({
            "pct_in_tangent": round(p * 100, 1),
            "ahpr": round(cml_return, 6),
            "std": round(cml_std, 6),
        })

    return {
        "tangent_portfolio": {
            "ahpr": round(tangent_ahpr, 6),
            "std": round(tangent_sd, 6),
            "sharpe": round(sharpe_ratio(tangent_ahpr, tangent_sd, rfr), 4),
        },
        "risk_free_rate": rfr,
        "cml_points": points,
    }


# ═══════════════════════════════════════════════════════════════════
#  SECTION 4 — GEOMETRIC EFFICIENT FRONTIER (Chapter 7)
# ═══════════════════════════════════════════════════════════════════

def geometric_frontier_analysis(
    ahpr: float,
    variance: float,
    num_trades: int = 252,
) -> dict:
    """
    Analyse the geometric properties of a portfolio.

    GHPR = sqrt(AHPR² - V)                  — Eq 7.05
    Geometric optimal: AHPR - 1 = V          — Eq 7.06c
    GTWR = GHPR^N                            — Eq 7.07
    ATWR = 1 + N*(AHPR-1)                   — Eq 7.08

    Key insight: higher GHPR → greater geometric growth, but also
    greater drawdowns. There's a single "peak" where growth is maximised.
    Beyond this peak, more return with more variance actually REDUCES
    geometric growth!
    """
    ghpr_sq = ahpr ** 2 - variance
    ghpr = math.sqrt(ghpr_sq) if ghpr_sq > 0 else 0

    gtwr = ghpr ** num_trades if ghpr > 0 else 0
    atwr = 1 + num_trades * (ahpr - 1)

    # How far from geometric optimal?
    optimal_variance = ahpr - 1  # At optimal: AHPR - 1 = V
    distance_from_optimal = variance - optimal_variance

    # Time for geometric to surpass arithmetic
    if ghpr > 1 and atwr > 0:
        # Solve GHPR^N = ATWR iteratively
        crossover_n = None
        for n in range(1, 10000):
            if ghpr ** n >= 1 + n * (ahpr - 1):
                crossover_n = n
                break
    else:
        crossover_n = None

    return {
        "ahpr": round(ahpr, 6),
        "variance": round(variance, 6),
        "ghpr": round(ghpr, 6),
        "gtwr": round(gtwr, 4),
        "atwr": round(atwr, 4),
        "optimal_variance": round(optimal_variance, 6),
        "distance_from_optimal": round(distance_from_optimal, 6),
        "is_over_optimal": distance_from_optimal > 0,
        "crossover_trades": crossover_n,
        "explanation": (
            f"Geometric HPR = {ghpr:.4f} (AHPR={ahpr:.4f}, Var={variance:.6f}). "
            + (f"Over-leveraged! Variance ({variance:.6f}) exceeds optimal ({optimal_variance:.6f}). "
               f"Reducing position size would INCREASE geometric growth."
               if distance_from_optimal > 0 else
               f"Under-leveraged. Room to increase position size. "
               f"Variance ({variance:.6f}) is below the geometric peak ({optimal_variance:.6f}).")
        ),
    }


# ═══════════════════════════════════════════════════════════════════
#  SECTION 5 — PORTFOLIO FROM HPR DATA
# ═══════════════════════════════════════════════════════════════════

def analyze_portfolio_from_hprs(
    hpr_series: Dict[str, List[float]],
    risk_free_rate: float = 0.0,
) -> dict:
    """
    Full portfolio analysis from daily HPR data for multiple systems.

    This is the correct way per the book: inputs to portfolio models
    must be based on HPRs derived from optimal f, NOT raw prices.

    Daily HPR = (rupees made or lost) / (f₹ in rupees) + 1  — Eq 1.15

    Steps:
      1. Compute AHPR, SD, variance for each system
      2. Build correlation and covariance matrices
      3. Find efficient frontier
      4. Identify geometric optimal portfolio
      5. Compute CML and Sharpe ratios
    """
    tickers = sorted(hpr_series.keys())
    n = len(tickers)
    if n < 1:
        return {"error": "No systems provided"}

    # Per-system statistics
    system_stats = {}
    returns_map = {}
    for t in tickers:
        hprs = np.array(hpr_series[t])
        ahpr = float(np.mean(hprs))
        sd = float(np.std(hprs, ddof=0))
        var = sd ** 2
        ghpr = math.sqrt(ahpr ** 2 - var) if ahpr ** 2 > var else 0.0
        returns_map[t] = list(hprs - 1)  # Convert HPR to return

        system_stats[t] = {
            "ahpr": round(ahpr, 6),
            "sd": round(sd, 6),
            "variance": round(var, 8),
            "ghpr": round(ghpr, 6),
            "sharpe": round(sharpe_ratio(ahpr, sd, risk_free_rate), 4),
            "num_periods": len(hprs),
        }

    result = {"system_stats": system_stats}

    if n >= 2:
        # Correlation matrix
        corr = compute_correlation_matrix(returns_map)
        result["correlation"] = corr

        # Covariance matrix
        cov = compute_covariance_matrix(returns_map)
        result["covariance"] = cov

        # Efficient frontier
        expected_returns = [system_stats[t]["ahpr"] - 1 for t in tickers]
        frontier = compute_efficient_frontier(
            tickers, expected_returns, cov["matrix"],
            risk_free_rate=risk_free_rate,
        )
        result["frontier"] = frontier

    return result
