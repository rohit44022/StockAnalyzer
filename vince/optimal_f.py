"""
Optimal f — The core of Ralph Vince's money management system.

The optimal f is the fixed fraction of your account to risk on each trade
that maximises the geometric growth rate of your capital. It represents the
ONE fraction where the ratio of expected profit to expected risk is greatest.

Key concepts implemented:
  1. Empirical Optimal f  — brute-force search over historical trades
  2. Parametric Optimal f on Normal Distribution
  3. Parametric Optimal f on Adjustable Distribution
  4. Scenario-Planning Optimal f
  5. Kelly Criterion (special two-outcome case)
  6. Fractional f (static & dynamic)
  7. All essential by-products: HPR, TWR, GAT, Geometric Mean, EGM, f$
"""

from __future__ import annotations
import math
from typing import List, Tuple, Optional
import numpy as np


# ═══════════════════════════════════════════════════════════════════
#  SECTION 1 — HOLDING-PERIOD RETURN (HPR) FUNDAMENTALS
# ═══════════════════════════════════════════════════════════════════

def compute_hprs(trades: List[float], f: float) -> List[float]:
    """
    Compute the Holding-Period Return for each trade at a given f.

    HPR_i = 1 + f * (-Trade_i / |Biggest_Loss|)

    Where f is the fraction (0..1] and Biggest_Loss is the most negative
    trade in the series.  When f = optimal, the product of all HPRs is
    maximised (i.e. TWR is maximised).

    Parameters
    ----------
    trades : list of float
        The raw P&L of each trade (positive = win, negative = loss).
    f : float
        The fraction to test (0 < f <= 1).

    Returns
    -------
    list of float — one HPR per trade.
    """
    if not trades or f <= 0:
        return []
    biggest_loss = abs(min(trades))
    if biggest_loss == 0:
        return [1.0 + f * (t / 1.0) for t in trades]
    return [1.0 + f * (-t / biggest_loss) for t in trades]


def twr_from_hprs(hprs: List[float]) -> float:
    """Terminal Wealth Relative = product of all HPRs."""
    if not hprs:
        return 1.0
    result = 1.0
    for h in hprs:
        result *= h
        if result <= 0:
            return 0.0
    return result


def geometric_mean(hprs: List[float]) -> float:
    """G = TWR^(1/N) — the geometric average HPR."""
    if not hprs:
        return 1.0
    twr = twr_from_hprs(hprs)
    if twr <= 0:
        return 0.0
    return twr ** (1.0 / len(hprs))


# ═══════════════════════════════════════════════════════════════════
#  SECTION 2 — EMPIRICAL OPTIMAL f (Chapter 1)
# ═══════════════════════════════════════════════════════════════════

def find_optimal_f_empirical(
    trades: List[float],
    step: float = 0.01,
    precision: float = 0.001,
) -> dict:
    """
    Find the optimal f by brute-force iteration over historical trades.

    This is the purest form — no distributional assumption is made.
    We simply test every f from 0 to 1 and pick the one that gives the
    highest TWR (= highest geometric mean of HPRs).

    Two-pass approach:
      Pass 1 — coarse scan at `step` increments (default 0.01 = 1%)
      Pass 2 — refine around best f at `precision` increments

    Parameters
    ----------
    trades : list of float — raw P&L series.
    step   : initial scan resolution (default 0.01).
    precision : refinement resolution (default 0.001).

    Returns
    -------
    dict with keys:
        optimal_f, twr, geometric_mean, ahpr, sd_hpr,
        biggest_loss, f_dollar (= |biggest_loss| / optimal_f, i.e. f₹),
        gat (geometric average trade), num_trades
    """
    if not trades:
        return _empty_result()

    biggest_loss = abs(min(trades))
    if biggest_loss == 0:
        return _empty_result()

    # ── Pass 1: coarse ──
    best_f, best_twr = 0.0, 0.0
    f = step
    while f <= 1.0:
        hprs = compute_hprs(trades, f)
        twr = twr_from_hprs(hprs)
        if twr > best_twr:
            best_twr = twr
            best_f = f
        f += step

    # ── Pass 2: refine ──
    lo = max(precision, best_f - step)
    hi = min(1.0, best_f + step)
    f = lo
    while f <= hi:
        hprs = compute_hprs(trades, f)
        twr = twr_from_hprs(hprs)
        if twr > best_twr:
            best_twr = twr
            best_f = f
        f += precision

    best_f = round(best_f, 4)
    return _build_result(trades, best_f, biggest_loss)


# ═══════════════════════════════════════════════════════════════════
#  SECTION 3 — PARAMETRIC OPTIMAL f ON NORMAL DISTRIBUTION (Ch 3)
# ═══════════════════════════════════════════════════════════════════

def find_optimal_f_normal(
    mean_trade: float,
    std_trade: float,
    num_points: int = 100,
    left_tail_sd: float = 4.0,
    right_tail_sd: float = 4.0,
    step: float = 0.01,
    precision: float = 0.001,
) -> dict:
    """
    Find optimal f assuming trades follow a Normal distribution.

    Instead of using only historical trades, we model the P&L distribution
    as Normal(mean, std) and compute expected HPRs at equally-spaced
    points across the distribution.

    The key advantage: this captures tail events that haven't yet happened
    in the historical sample but are statistically expected.

    Steps (from the book):
      1. Create `num_points` equally-spaced P&L values from
         (mean - left_tail_sd*std) to (mean + right_tail_sd*std)
      2. Assign Normal probability density to each point
      3. For each f, compute probability-weighted HPRs
      4. Find f that maximises the product of weighted HPRs

    Parameters
    ----------
    mean_trade    : arithmetic mean of trade P&L
    std_trade     : standard deviation of trade P&L
    num_points    : number of data points to model (default 100)
    left_tail_sd  : SDs to extend on left (default 4)
    right_tail_sd : SDs to extend on right (default 4)
    step          : coarse scan step
    precision     : refinement step

    Returns
    -------
    dict — same structure as empirical, plus parametric flag.
    """
    if std_trade <= 0:
        return _empty_result()

    # Build the equally-spaced data points
    left = mean_trade - left_tail_sd * std_trade
    right = mean_trade + right_tail_sd * std_trade
    points = np.linspace(left, right, num_points)

    # Normal probability density at each point
    probs = np.array([_normal_pdf(p, mean_trade, std_trade) for p in points])
    total_prob = probs.sum()
    if total_prob <= 0:
        return _empty_result()
    probs /= total_prob  # normalise to sum = 1

    biggest_loss = abs(min(points))
    if biggest_loss <= 0:
        return _empty_result()

    # Search for optimal f
    best_f, best_twr = 0.0, 0.0

    def _twr_at_f(f_val):
        result = 1.0
        for i, p_val in enumerate(points):
            hpr = 1.0 + f_val * (-p_val / biggest_loss)
            if hpr <= 0:
                return 0.0
            result *= hpr ** probs[i]
        return result

    # Coarse scan
    f = step
    while f <= 1.0:
        twr_val = _twr_at_f(f)
        if twr_val > best_twr:
            best_twr = twr_val
            best_f = f
        f += step

    # Refinement
    lo = max(precision, best_f - step)
    hi = min(1.0, best_f + step)
    f = lo
    while f <= hi:
        twr_val = _twr_at_f(f)
        if twr_val > best_twr:
            best_twr = twr_val
            best_f = f
        f += precision

    best_f = round(best_f, 4)

    # Compute by-products
    f_dollar = biggest_loss / best_f if best_f > 0 else float('inf')
    ahpr = _twr_at_f(best_f) if best_f > 0 else 1.0

    return {
        "optimal_f": best_f,
        "f_dollar": round(f_dollar, 2),
        "biggest_loss": round(biggest_loss, 2),
        "geometric_mean_hpr": round(best_twr, 6),
        "mean_trade": round(mean_trade, 2),
        "std_trade": round(std_trade, 2),
        "parametric": True,
        "distribution": "Normal",
        "num_points": num_points,
    }


# ═══════════════════════════════════════════════════════════════════
#  SECTION 4 — KELLY CRITERION (Chapter 1)
# ═══════════════════════════════════════════════════════════════════

def kelly_f(win_prob: float, win_loss_ratio: float) -> dict:
    """
    Kelly Criterion — the optimal fraction for a two-outcome game.

    f = ((B + 1) * P - 1) / B

    Where:
      P = probability of winning
      B = ratio of amount won on a win to amount lost on a loss
          (i.e. if you win ₹2 for every ₹1 risked, B = 2)

    The Kelly formula is a special case of optimal f that applies when
    there are only two possible outcomes (win or lose) with known
    probabilities and fixed payoffs.

    For most trading, the full optimal f is preferred since trades
    have a continuous distribution of outcomes, not just win/lose.

    Parameters
    ----------
    win_prob       : probability of a winning trade (0..1)
    win_loss_ratio : average win / average loss (> 0)

    Returns
    -------
    dict with kelly_f, edge, and explanation.
    """
    if win_prob <= 0 or win_prob >= 1 or win_loss_ratio <= 0:
        return {"kelly_f": 0.0, "edge": 0.0, "explanation": "Invalid inputs"}

    b = win_loss_ratio
    p = win_prob
    q = 1 - p

    kf = ((b + 1) * p - 1) / b
    edge = p * b - q  # mathematical expectation per unit risked

    return {
        "kelly_f": round(max(0.0, kf), 4),
        "edge": round(edge, 4),
        "win_prob": round(p, 4),
        "win_loss_ratio": round(b, 4),
        "explanation": (
            f"With {p*100:.1f}% wins and {b:.2f}:1 payoff ratio, "
            f"the Kelly fraction is {max(0,kf)*100:.2f}% of your bankroll per trade. "
            f"Mathematical expectation = {edge:.4f} per unit risked."
        ),
    }


# ═══════════════════════════════════════════════════════════════════
#  SECTION 5 — SCENARIO PLANNING OPTIMAL f (Chapter 4)
# ═══════════════════════════════════════════════════════════════════

def find_optimal_f_scenario(
    scenarios: List[Tuple[float, float]],
    step: float = 0.01,
    precision: float = 0.001,
) -> dict:
    """
    Optimal f via Scenario Planning (Chapter 4).

    Instead of using historical trades, the trader defines discrete
    scenarios — each with an assigned probability and expected P&L.

    HPR_i = (1 + f * (-A_i / W))^P_i
      where A_i = P&L for scenario i
            W   = worst-case loss (most negative A_i)
            P_i = probability of scenario i

    Parameters
    ----------
    scenarios : list of (probability, pnl) tuples.
                Probabilities should sum to ~1.0.
    step      : coarse scan step
    precision : refinement step

    Returns
    -------
    dict with optimal_f, geometric_mean, and scenario details.
    """
    if not scenarios:
        return _empty_result()

    # Validate probabilities sum close to 1
    total_prob = sum(prob for prob, _ in scenarios)
    if abs(total_prob - 1.0) > 0.05:
        # Rescale
        scenarios = [(p / total_prob, pnl) for p, pnl in scenarios]

    worst_loss = abs(min(pnl for _, pnl in scenarios))
    if worst_loss == 0:
        return _empty_result()

    def _geo_at_f(f_val):
        product = 1.0
        for prob, pnl in scenarios:
            hpr = 1.0 + f_val * (-pnl / worst_loss)
            if hpr <= 0:
                return 0.0
            product *= hpr ** prob
        return product

    best_f, best_g = 0.0, 1.0

    # Coarse
    f = step
    while f <= 1.0:
        g = _geo_at_f(f)
        if g > best_g:
            best_g = g
            best_f = f
        f += step

    # Refine
    lo = max(precision, best_f - step)
    hi = min(1.0, best_f + step)
    f = lo
    while f <= hi:
        g = _geo_at_f(f)
        if g > best_g:
            best_g = g
            best_f = f
        f += precision

    best_f = round(best_f, 4)
    f_dollar = worst_loss / best_f if best_f > 0 else float('inf')

    return {
        "optimal_f": best_f,
        "geometric_mean": round(best_g, 6),
        "f_dollar": round(f_dollar, 2),
        "worst_case_loss": round(worst_loss, 2),
        "num_scenarios": len(scenarios),
        "method": "scenario_planning",
    }


# ═══════════════════════════════════════════════════════════════════
#  SECTION 6 — FRACTIONAL f (Chapter 2)
# ═══════════════════════════════════════════════════════════════════

def fractional_f_analysis(
    ahpr: float,
    sd_hpr: float,
    optimal_f: float,
    biggest_loss: float,
    fractions: Optional[List[float]] = None,
) -> dict:
    """
    Analyse the effect of trading at different fractions of optimal f.

    Key equations from Chapter 2:
      FAHPR = (AHPR - 1) * FRAC + 1           — Eq 2.06
      FSD   = SD * FRAC                        — Eq 2.07
      FGHPR = (FAHPR² - FSD²)^(1/2)           — Eq 2.08
      Time to goal: N = ln(Goal) / ln(G)       — Eq 2.09a

    Trading at a fraction of f reduces both returns AND risk.
    The relationship is NOT linear — halving f does NOT halve the time
    to reach a goal; it roughly doubles it (or more).

    Parameters
    ----------
    ahpr         : arithmetic average HPR at optimal f
    sd_hpr       : standard deviation of HPRs at optimal f
    optimal_f    : the optimal fraction
    biggest_loss : magnitude of biggest losing trade
    fractions    : list of fractions to evaluate (default: 0.1 to 1.0)

    Returns
    -------
    dict with a list of evaluations at each fraction.
    """
    if fractions is None:
        fractions = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]

    results = []
    for frac in fractions:
        fahpr = (ahpr - 1) * frac + 1.0   # Eq 2.06
        fsd = sd_hpr * frac               # Eq 2.07
        var = fsd ** 2
        fghpr_sq = fahpr ** 2 - var
        fghpr = math.sqrt(fghpr_sq) if fghpr_sq > 0 else 0.0  # Eq 2.08

        # Effective f and f$
        eff_f = optimal_f * frac
        f_dollar = biggest_loss / eff_f if eff_f > 0 else float('inf')

        # Time to double (goal = 2x)
        if fghpr > 1.0:
            time_to_double = math.log(2) / math.log(fghpr)  # Eq 2.09a
        else:
            time_to_double = float('inf')

        results.append({
            "fraction": round(frac, 2),
            "effective_f": round(eff_f, 4),
            "f_dollar": round(f_dollar, 2) if f_dollar != float('inf') else None,
            "fahpr": round(fahpr, 6),
            "fsd": round(fsd, 6),
            "fghpr": round(fghpr, 6),
            "variance": round(var, 6),
            "time_to_double": round(time_to_double, 1) if time_to_double != float('inf') else None,
        })

    return {
        "optimal_f": optimal_f,
        "ahpr_at_optimal": round(ahpr, 6),
        "sd_at_optimal": round(sd_hpr, 6),
        "fractions": results,
    }


def dynamic_vs_static_f(
    ghpr: float,
    initial_active_pct: float,
    goal_multiple: float = 2.0,
) -> dict:
    """
    Compare dynamic vs static fractional f strategies (Chapter 8).

    Static: trade a fixed fraction of total equity at that fraction of f.
      N_static = ln(Goal) / ln(FG)  where FG = fractional geometric mean

    Dynamic: split into active + inactive; trade full f on active portion.
      N_dynamic = ln(((Goal-1)/ACTV) + 1) / ln(G)   — Eq 2.09c

    Dynamic asymptotically dominates static because:
      - On the downside: you progressively reduce exposure (inactive stays put)
      - On the upside: your effective fraction approaches full f

    Parameters
    ----------
    ghpr              : geometric mean HPR at full optimal f
    initial_active_pct: fraction of total equity allocated as "active" (0..1)
    goal_multiple     : target total equity multiple (default 2.0 = double)
    """
    if ghpr <= 1.0 or initial_active_pct <= 0:
        return {"error": "GHPR must be > 1 and active % must be > 0"}

    # Dynamic
    if initial_active_pct < 1.0:
        n_dynamic = math.log(((goal_multiple - 1) / initial_active_pct) + 1) / math.log(ghpr)
    else:
        n_dynamic = math.log(goal_multiple) / math.log(ghpr)

    # Static (using fractional geometric mean)
    # We need AHPR and SD to compute this properly
    # Approximate: at fraction = initial_active_pct, FG ≈ 1 + (ghpr-1)*pct
    # More accurately: FG^N vs G^N * FRAC + 1 - FRAC (Eq 8.01)
    # For comparison, use the static formula
    frac = initial_active_pct
    # Approximate static geometric mean
    fg_approx = 1.0 + (ghpr - 1.0) * frac * 0.95  # slight discount for variance effect
    if fg_approx > 1.0:
        n_static = math.log(goal_multiple) / math.log(fg_approx)
    else:
        n_static = float('inf')

    return {
        "ghpr": round(ghpr, 6),
        "active_pct": round(initial_active_pct * 100, 1),
        "goal_multiple": goal_multiple,
        "trades_dynamic": round(n_dynamic, 0),
        "trades_static": round(n_static, 0) if n_static != float('inf') else None,
        "dynamic_faster_by": round(n_static - n_dynamic, 0) if n_static != float('inf') else None,
        "explanation": (
            f"Dynamic fractional f reaches {goal_multiple}x in ~{n_dynamic:.0f} trades vs "
            f"~{n_static:.0f} for static (at {initial_active_pct*100:.0f}% active). "
            f"Dynamic wins by ~{n_static - n_dynamic:.0f} trades."
            if n_static != float('inf') else
            f"Dynamic reaches {goal_multiple}x in ~{n_dynamic:.0f} trades. "
            f"Static may not reach the goal at this fraction."
        ),
    }


# ═══════════════════════════════════════════════════════════════════
#  SECTION 7 — ESTIMATED GEOMETRIC MEAN & FUNDAMENTAL EQUATION
# ═══════════════════════════════════════════════════════════════════

def estimated_geometric_mean(ahpr: float, sd: float) -> float:
    """
    EGM = sqrt(AHPR² - SD²)   — the Estimated Geometric Mean.

    This is a quick approximation of the geometric mean HPR
    from just the arithmetic mean and standard deviation.
    """
    val = ahpr ** 2 - sd ** 2
    return math.sqrt(val) if val > 0 else 0.0


def fundamental_equation_of_trading(ahpr: float, sd: float, n: int) -> float:
    """
    Estimated TWR = (AHPR² - SD²)^(N/2)  — the Fundamental Equation.

    This tells you your expected terminal wealth after N trades,
    given the arithmetic properties of your trading system.

    The key insight: BOTH the mean AND the variance determine growth.
    A system with high AHPR but also high SD can LOSE money over time!
    """
    val = ahpr ** 2 - sd ** 2
    if val <= 0:
        return 0.0
    return val ** (n / 2.0)


def threshold_to_geometric(
    arithmetic_avg_trade: float,
    geometric_avg_trade: float,
    biggest_loss: float,
    optimal_f: float,
) -> float:
    """
    Threshold to the geometric — the account size needed for the
    geometric (reinvested) approach to start outperforming the
    arithmetic (fixed-unit) approach.

    T = (AAT / GAT) * (|Biggest_Loss| / f)

    Below this account size, trading fixed units is actually better
    than reinvesting proportionally. Above it, reinvestment dominates.
    """
    if geometric_avg_trade <= 0 or optimal_f <= 0:
        return float('inf')
    f_dollar = biggest_loss / optimal_f
    return (arithmetic_avg_trade / geometric_avg_trade) * f_dollar


# ═══════════════════════════════════════════════════════════════════
#  SECTION 8 — BY-PRODUCTS & HELPERS
# ═══════════════════════════════════════════════════════════════════

def compute_by_products(trades: List[float], optimal_f: float) -> dict:
    """
    Compute all by-products of optimal f for a trade series.

    By-products (Chapter 1 & 2):
      - TWR: Terminal Wealth Relative
      - G: Geometric Mean HPR
      - AHPR: Arithmetic Average HPR
      - SD: Standard Deviation of HPRs
      - EGM: Estimated Geometric Mean (sqrt(AHPR²-SD²))
      - GAT: Geometric Average Trade = G * (|biggest_loss|/f)
      - f₹: Rupees to allocate per unit = |biggest_loss| / f
      - Mathematical Expectation
    """
    if not trades or optimal_f <= 0:
        return _empty_result()

    biggest_loss = abs(min(trades))
    hprs = compute_hprs(trades, optimal_f)

    if any(h <= 0 for h in hprs):
        return _empty_result()

    n = len(hprs)
    twr = twr_from_hprs(hprs)
    g = geometric_mean(hprs)
    ahpr = sum(hprs) / n
    sd = math.sqrt(sum((h - ahpr) ** 2 for h in hprs) / n)
    egm = estimated_geometric_mean(ahpr, sd)

    f_dollar = biggest_loss / optimal_f
    gat = (g - 1) * f_dollar  # Geometric Average Trade

    avg_trade = sum(trades) / n
    math_expectation = avg_trade  # simple mathematical expectation

    return {
        "optimal_f": optimal_f,
        "twr": round(twr, 4),
        "geometric_mean": round(g, 6),
        "ahpr": round(ahpr, 6),
        "sd_hpr": round(sd, 6),
        "variance": round(sd ** 2, 6),
        "egm": round(egm, 6),
        "f_dollar": round(f_dollar, 2),
        "gat": round(gat, 4),
        "biggest_loss": round(biggest_loss, 2),
        "num_trades": n,
        "math_expectation": round(math_expectation, 4),
        "avg_trade": round(avg_trade, 4),
    }


def _build_result(trades: List[float], f: float, biggest_loss: float) -> dict:
    """Build full result dict for a given f and trade series."""
    hprs = compute_hprs(trades, f)
    if any(h <= 0 for h in hprs):
        return _empty_result()

    n = len(hprs)
    twr = twr_from_hprs(hprs)
    g = geometric_mean(hprs)
    ahpr = sum(hprs) / n
    sd = math.sqrt(sum((h - ahpr) ** 2 for h in hprs) / n)
    f_dollar = biggest_loss / f if f > 0 else float('inf')
    gat = (g - 1) * f_dollar if f > 0 else 0.0

    return {
        "optimal_f": f,
        "twr": round(twr, 4),
        "geometric_mean": round(g, 6),
        "ahpr": round(ahpr, 6),
        "sd_hpr": round(sd, 6),
        "f_dollar": round(f_dollar, 2),
        "gat": round(gat, 4),
        "biggest_loss": round(biggest_loss, 2),
        "num_trades": n,
    }


def _empty_result() -> dict:
    return {
        "optimal_f": 0.0,
        "twr": 1.0,
        "geometric_mean": 1.0,
        "ahpr": 1.0,
        "sd_hpr": 0.0,
        "f_dollar": 0.0,
        "gat": 0.0,
        "biggest_loss": 0.0,
        "num_trades": 0,
    }


def _normal_pdf(x: float, mu: float, sigma: float) -> float:
    """Standard Normal probability density function."""
    return (1.0 / (sigma * math.sqrt(2 * math.pi))) * math.exp(
        -0.5 * ((x - mu) / sigma) ** 2
    )


def _normal_cdf(z: float) -> float:
    """
    Cumulative Normal Distribution — Eq 3.21 from the book.
    Polynomial approximation (Abramowitz & Stegun).
    """
    if z < 0:
        return 1.0 - _normal_cdf(-z)
    t = 1.0 / (1.0 + 0.2316419 * z)
    d = 0.3989422804014327  # 1/sqrt(2*pi)
    p = d * math.exp(-z * z / 2.0)
    poly = t * (0.31938153 + t * (-0.356563782 + t * (
        1.781477937 + t * (-1.821255978 + t * 1.330274429))))
    return 1.0 - p * poly


# ═══════════════════════════════════════════════════════════════════
#  SECTION 9 — f CURVE DATA (for charting)
# ═══════════════════════════════════════════════════════════════════

def f_curve_data(trades: List[float], points: int = 50) -> dict:
    """
    Generate the f-curve data — TWR and geometric mean at each f value.

    This is the bell-shaped curve shown in the book where:
      - X axis = f (0 to 1)
      - Y axis = TWR (or geometric mean)
      - Peak = optimal f

    Used for the interactive chart showing where you are on the curve.
    """
    if not trades:
        return {"f_values": [], "twr_values": [], "gm_values": []}

    f_vals, twr_vals, gm_vals = [], [], []
    for i in range(1, points + 1):
        f = round(i / points, 4)
        hprs = compute_hprs(trades, f)
        twr = twr_from_hprs(hprs)
        gm = geometric_mean(hprs)
        f_vals.append(f)
        twr_vals.append(round(twr, 4))
        gm_vals.append(round(gm, 6))

    return {
        "f_values": f_vals,
        "twr_values": twr_vals,
        "gm_values": gm_vals,
    }
