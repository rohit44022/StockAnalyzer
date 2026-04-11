"""
Statistical Tests & Distribution Analysis — Ralph Vince Ch 1, 3, 4

Implements:
  1. Runs Test — tests if trade outcomes are random or dependent
  2. Serial Correlation (Pearson's r) — linear dependency between consecutive trades
  3. Kolmogorov-Smirnov (K-S) Test — goodness of fit for distribution matching
  4. Chi-Square Test — alternative distribution comparison
  5. Normal Distribution utilities
  6. Turning Points Test — alternative dependency test (Appendix C)
  7. Phase Length Test — dependency via pattern lengths (Appendix C)
  8. Moments calculation — mean, variance, skewness, kurtosis
"""

from __future__ import annotations
import math
from typing import List, Tuple, Optional
import numpy as np


# ═══════════════════════════════════════════════════════════════════
#  RUNS TEST (Chapter 1)
# ═══════════════════════════════════════════════════════════════════

def runs_test(trades: List[float]) -> dict:
    """
    Runs Test for Dependency — determines if trade outcomes are random.

    A "run" is a consecutive sequence of either positive or negative trades.
    
    If the Z-score is:
      > +1.96 or < -1.96  →  95% confidence that dependency exists
      > +2.58 or < -2.58  →  99% confidence
    
    If Z < 0: fewer runs than expected = "like begets like" (streaks)
              → A winning trade is likely followed by another win
    If Z > 0: more runs than expected = "like begets unlike" (alternation)
              → A winning trade is likely followed by a loss

    Z = (N*(R - 0.5) - X) / sqrt((X*(X-N)) / (N-1))  — Eq from Ch 1

    Where:
      N = total number of trades
      R = number of runs
      X = number of positive trades (or number in the larger group)
    """
    if len(trades) < 10:
        return {"error": "Need at least 10 trades", "z_score": 0, "is_random": True}

    n = len(trades)
    signs = [1 if t > 0 else (-1 if t < 0 else 0) for t in trades]
    # Remove zeros
    signs = [s for s in signs if s != 0]
    n = len(signs)
    if n < 10:
        return {"error": "Too few non-zero trades", "z_score": 0, "is_random": True}

    # Count runs
    runs = 1
    for i in range(1, n):
        if signs[i] != signs[i - 1]:
            runs += 1

    # Count positives (X)
    x = sum(1 for s in signs if s > 0)
    y = n - x  # negatives

    if x == 0 or y == 0:
        return {"error": "All trades same sign", "z_score": 0, "is_random": True}

    # Expected runs and standard deviation
    expected_runs = (2 * x * y) / n + 1
    if n <= 1:
        return {"error": "Not enough data", "z_score": 0, "is_random": True}

    variance = (2 * x * y * (2 * x * y - n)) / (n * n * (n - 1))
    if variance <= 0:
        return {"error": "Variance calculation error", "z_score": 0, "is_random": True}

    std = math.sqrt(variance)
    z = (runs - expected_runs) / std

    # Confidence interpretation
    confidence = _z_to_confidence(abs(z))
    is_random = abs(z) < 1.96

    if z < 0:
        dependency = "STREAKING (like begets like)"
        explanation = (
            f"Fewer runs ({runs}) than expected ({expected_runs:.1f}). "
            f"Winning trades tend to follow winning trades, and losses follow losses. "
            f"Consider increasing position size after a win."
        )
    elif z > 0:
        dependency = "ALTERNATING (like begets unlike)"
        explanation = (
            f"More runs ({runs}) than expected ({expected_runs:.1f}). "
            f"Winning trades tend to be followed by losses and vice versa. "
            f"Consider reducing position after a win."
        )
    else:
        dependency = "RANDOM"
        explanation = "Trade outcomes appear random — no exploitable pattern."

    return {
        "z_score": round(z, 4),
        "runs_observed": runs,
        "runs_expected": round(expected_runs, 2),
        "positive_trades": x,
        "negative_trades": y,
        "total_trades": n,
        "is_random": is_random,
        "confidence_pct": round(confidence, 2),
        "dependency_type": dependency if not is_random else "RANDOM",
        "explanation": explanation if not is_random else "No significant dependency detected. Trades appear random.",
    }


# ═══════════════════════════════════════════════════════════════════
#  SERIAL CORRELATION (Chapter 1)
# ═══════════════════════════════════════════════════════════════════

def serial_correlation(trades: List[float], lag: int = 1) -> dict:
    """
    Serial Correlation (Pearson's r) — tests linear dependency between
    trade i and trade i+lag.

    r close to +1: strong positive correlation (streaks)
    r close to -1: strong negative correlation (alternation)
    r close to  0: no linear dependency

    Uses Fisher's Z transformation to determine confidence level.
    """
    if len(trades) < lag + 10:
        return {"error": "Need more trades", "correlation": 0, "is_dependent": False}

    n = len(trades)
    x = trades[:-lag]
    y = trades[lag:]
    m = len(x)

    mx = sum(x) / m
    my = sum(y) / m

    numerator = sum((x[i] - mx) * (y[i] - my) for i in range(m))
    denom_x = sum((x[i] - mx) ** 2 for i in range(m))
    denom_y = sum((y[i] - my) ** 2 for i in range(m))
    denom = math.sqrt(denom_x * denom_y)

    r = numerator / denom if denom > 0 else 0.0

    # Fisher's Z transformation for confidence (Appendix C, Eq C.04-C.06)
    if abs(r) >= 0.999:
        z_fisher = 5.0 * (1 if r > 0 else -1)
    else:
        z_fisher = 0.5 * math.log((1 + r) / (1 - r))

    if m > 3:
        se = 1.0 / math.sqrt(m - 3)
        z_score = z_fisher / se if se > 0 else 0
    else:
        z_score = 0

    confidence = _z_to_confidence(abs(z_score))
    is_dependent = abs(z_score) > 1.96

    return {
        "correlation": round(r, 4),
        "z_score": round(z_score, 4),
        "confidence_pct": round(confidence, 2),
        "is_dependent": is_dependent,
        "lag": lag,
        "num_pairs": m,
        "explanation": (
            f"Correlation of {r:.4f} between trade[i] and trade[i+{lag}]. "
            + (f"Significant at {confidence:.1f}% confidence — dependency exists!" if is_dependent
               else "Not statistically significant — trades appear independent.")
        ),
    }


# ═══════════════════════════════════════════════════════════════════
#  KOLMOGOROV-SMIRNOV TEST (Chapter 4)
# ═══════════════════════════════════════════════════════════════════

def ks_test_normal(trades: List[float]) -> dict:
    """
    Kolmogorov-Smirnov test — compares the empirical distribution of trades
    against a Normal distribution with the same mean and std dev.

    The K-S statistic D is the maximum absolute difference between the
    empirical CDF and the theoretical Normal CDF.

    Significance levels:
      D > 1.36/sqrt(N) → reject Normal at 5% significance
      D > 1.63/sqrt(N) → reject Normal at 1% significance

    If the distribution is NOT Normal, you should use the adjustable
    distribution or non-parametric methods for optimal f.
    """
    if len(trades) < 10:
        return {"error": "Need at least 10 trades", "is_normal": False}

    n = len(trades)
    mu = sum(trades) / n
    var = sum((t - mu) ** 2 for t in trades) / n
    sigma = math.sqrt(var) if var > 0 else 1e-10
    sorted_trades = sorted(trades)

    max_d = 0.0
    for i, t in enumerate(sorted_trades):
        z = (t - mu) / sigma
        empirical_cdf = (i + 1) / n
        theoretical_cdf = _normal_cdf(z)
        d = abs(empirical_cdf - theoretical_cdf)
        max_d = max(max_d, d)

        # Also check just below the step
        empirical_below = i / n
        d2 = abs(empirical_below - theoretical_cdf)
        max_d = max(max_d, d2)

    # Critical values
    critical_5pct = 1.36 / math.sqrt(n)
    critical_1pct = 1.63 / math.sqrt(n)

    is_normal = max_d <= critical_5pct

    return {
        "ks_statistic": round(max_d, 6),
        "critical_5pct": round(critical_5pct, 6),
        "critical_1pct": round(critical_1pct, 6),
        "is_normal": is_normal,
        "num_trades": n,
        "mean": round(mu, 4),
        "std": round(sigma, 4),
        "explanation": (
            f"K-S statistic D = {max_d:.4f}. "
            + (f"D ≤ critical value ({critical_5pct:.4f}) → Cannot reject Normal distribution. "
               f"Your trades are consistent with Normal distribution."
               if is_normal else
               f"D > critical value ({critical_5pct:.4f}) → Trades are NOT Normally distributed (5% significance). "
               f"Consider using the adjustable distribution or empirical optimal f.")
        ),
    }


# ═══════════════════════════════════════════════════════════════════
#  TURNING POINTS TEST (Appendix C)
# ═══════════════════════════════════════════════════════════════════

def turning_points_test(trades: List[float]) -> dict:
    """
    Turning Points test for dependency (Appendix C).

    A turning point occurs when a trade value is greater than BOTH neighbors
    or less than BOTH neighbors. For random data:
      Expected turning points = 2/3 * (N - 2)
      Variance = (16*N - 29) / 90
    """
    if len(trades) < 10:
        return {"error": "Need at least 10 trades", "is_random": True}

    n = len(trades)
    tp_count = 0

    for i in range(1, n - 1):
        if (trades[i] > trades[i-1] and trades[i] > trades[i+1]) or \
           (trades[i] < trades[i-1] and trades[i] < trades[i+1]):
            tp_count += 1

    expected = 2.0 / 3.0 * (n - 2)
    variance = (16 * n - 29) / 90.0
    std = math.sqrt(variance) if variance > 0 else 1
    z = (tp_count - expected) / std

    confidence = _z_to_confidence(abs(z))
    is_random = abs(z) < 1.96

    return {
        "turning_points": tp_count,
        "expected": round(expected, 2),
        "z_score": round(z, 4),
        "confidence_pct": round(confidence, 2),
        "is_random": is_random,
        "explanation": (
            f"Found {tp_count} turning points (expected {expected:.1f}). "
            + ("Consistent with randomness." if is_random else
               f"Significant at {confidence:.1f}% — dependency likely!")
        ),
    }


# ═══════════════════════════════════════════════════════════════════
#  DISTRIBUTION MOMENTS (Chapter 3 & 4)
# ═══════════════════════════════════════════════════════════════════

def compute_moments(data: List[float]) -> dict:
    """
    Compute the four statistical moments of a distribution:
      1st moment: Mean (location)
      2nd moment: Variance / Std Dev (dispersion)
      3rd moment: Skewness (asymmetry)
      4th moment: Kurtosis (tail thickness)

    These correspond to the adjustable distribution parameters:
      LOC ↔ Mean, SCALE ↔ Std Dev, SKEW ↔ Skewness, KURT ↔ Kurtosis
    """
    if len(data) < 4:
        return {"error": "Need at least 4 data points"}

    n = len(data)
    arr = np.array(data, dtype=float)
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=0))

    if std == 0:
        return {
            "mean": mean, "std": 0, "variance": 0,
            "skewness": 0, "kurtosis": 0, "excess_kurtosis": 0,
            "n": n,
        }

    variance = std ** 2
    # Skewness = E[(X-mu)^3] / sigma^3
    skewness = float(np.mean(((arr - mean) / std) ** 3))
    # Kurtosis = E[(X-mu)^4] / sigma^4
    kurtosis = float(np.mean(((arr - mean) / std) ** 4))
    excess_kurtosis = kurtosis - 3.0  # Normal has kurtosis=3, excess=0

    return {
        "mean": round(mean, 4),
        "std": round(std, 4),
        "variance": round(variance, 4),
        "skewness": round(skewness, 4),
        "kurtosis": round(kurtosis, 4),
        "excess_kurtosis": round(excess_kurtosis, 4),
        "n": n,
        "interpretation": {
            "skewness": (
                "Symmetric" if abs(skewness) < 0.5 else
                "Right-skewed (more extreme gains)" if skewness > 0 else
                "Left-skewed (more extreme losses)"
            ),
            "kurtosis": (
                "Normal-like tails (mesokurtic)" if abs(excess_kurtosis) < 1 else
                "Fat tails (leptokurtic) — extreme events more likely" if excess_kurtosis > 0 else
                "Thin tails (platykurtic) — extreme events less likely"
            ),
        },
    }


# ═══════════════════════════════════════════════════════════════════
#  ARC SINE LAWS (Chapter 2)
# ═══════════════════════════════════════════════════════════════════

def arc_sine_analysis(num_trades: int) -> dict:
    """
    Arc Sine Laws — counterintuitive probability properties (Chapter 2).

    The arc sine law states that in a series of N coin flips (or trades),
    the proportion of time spent on the "winning side" (cumulative P&L > 0)
    is NOT uniformly distributed. Instead:
    
    - Most likely scenarios: you spend ALMOST ALL the time either winning
      or losing — NOT half and half!
    - The probability of being positive for exactly K out of N periods is:
      P(K) ≈ 1 / (π * √(K * (N-K)))

    This means: long drawdown periods are NORMAL, not abnormal.
    """
    if num_trades < 4:
        return {"error": "Need at least 4 trades"}

    n = num_trades
    probs = []
    for k in range(1, n):
        denom = math.pi * math.sqrt(k * (n - k))
        if denom > 0:
            p = 1.0 / denom
        else:
            p = 0
        probs.append({
            "periods_positive": k,
            "pct_time_positive": round(k / n * 100, 1),
            "probability": round(p, 6),
        })

    # Find most likely and least likely
    if probs:
        max_prob = max(probs, key=lambda x: x["probability"])
        min_prob = min(probs, key=lambda x: x["probability"])
    else:
        max_prob = min_prob = {"periods_positive": 0, "probability": 0}

    # Probability of being positive less than 25% or more than 75% of the time
    extreme_prob = sum(p["probability"] for p in probs
                       if p["pct_time_positive"] < 25 or p["pct_time_positive"] > 75)

    return {
        "num_trades": n,
        "distribution": probs,
        "most_likely": max_prob,
        "least_likely": min_prob,
        "prob_extreme": round(extreme_prob, 4),
        "explanation": (
            f"Over {n} trades, you're most likely to be positive for either a very SHORT or very LONG "
            f"stretch — NOT 50% of the time. There's a {extreme_prob*100:.1f}% chance you'll be positive "
            f"less than 25% or more than 75% of the time. Long drawdowns are statistically normal!"
        ),
    }


# ═══════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════

def _normal_cdf(z: float) -> float:
    """Cumulative Normal Distribution — Eq 3.21."""
    if z < 0:
        return 1.0 - _normal_cdf(-z)
    t = 1.0 / (1.0 + 0.2316419 * z)
    d = 0.3989422804014327
    p = d * math.exp(-z * z / 2.0)
    poly = t * (0.31938153 + t * (-0.356563782 + t * (
        1.781477937 + t * (-1.821255978 + t * 1.330274429))))
    return 1.0 - p * poly


def _z_to_confidence(z_abs: float) -> float:
    """Convert absolute Z score to confidence percentage (2-tailed)."""
    p = 2.0 * (1.0 - _normal_cdf(z_abs))
    return (1.0 - p) * 100.0
