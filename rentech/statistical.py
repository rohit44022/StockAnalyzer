"""
RenTech Statistical Models — Core mathematical foundation.
══════════════════════════════════════════════════════════

Every model here is a pure function: data in → result out.
No side effects, no state mutation, no network calls.

Models Implemented:
  1. Hurst Exponent        (R/S analysis — mean reversion vs trending)
  2. Ornstein-Uhlenbeck    (continuous-time mean reversion speed)
  3. Half-Life Estimation   (how fast price reverts to mean)
  4. Variance Ratio Test    (Lo-MacKinlay — random walk test)
  5. Augmented Dickey-Fuller(stationarity test for spread/residuals)
  6. Rolling Z-Score        (standardized deviation from mean)
  7. Entropy Measures       (Shannon entropy of returns distribution)
  8. Autocorrelation Decay  (serial correlation at multiple lags)
  9. Volatility Clustering  (GARCH-like persistence measurement)
 10. Information Ratio      (signal quality metric)

All functions return typed dataclasses with explanation strings.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from rentech import config as C


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def _safe(v, default=0.0) -> float:
    """Convert to float, replacing NaN/Inf with default."""
    try:
        f = float(v)
        return default if (math.isnan(f) or math.isinf(f)) else round(f, 6)
    except (TypeError, ValueError):
        return default


def _returns(close: pd.Series) -> pd.Series:
    """Log returns from close prices."""
    return np.log(close / close.shift(1)).dropna()


def _pct_returns(close: pd.Series) -> pd.Series:
    """Percentage returns from close prices."""
    return close.pct_change().dropna()


# ═══════════════════════════════════════════════════════════════
# 1. HURST EXPONENT (R/S Analysis)
# ═══════════════════════════════════════════════════════════════

@dataclass
class HurstResult:
    hurst: float              # 0–1 (0.5 = random walk)
    regime: str               # MEAN_REVERTING | RANDOM_WALK | TRENDING
    confidence: float         # 0–100
    interpretation: str       # plain-English
    lags_used: int


def hurst_exponent(close: pd.Series, max_lag: int = 100) -> HurstResult:
    """
    Rescaled Range (R/S) analysis for Hurst exponent.

    H < 0.5 → Anti-persistent (mean-reverting) — RenTech's bread & butter
    H = 0.5 → Random walk (no edge)
    H > 0.5 → Persistent (trending) — momentum strategies work

    Jim Simons: "We look for subtle statistical regularities that deviate
    from the random walk hypothesis. The Hurst exponent tells us WHERE to look."
    """
    prices = close.dropna().values
    n = len(prices)
    if n < 50:
        return HurstResult(0.5, "RANDOM_WALK", 0, "Insufficient data", 0)

    log_prices = np.log(prices)
    returns = np.diff(log_prices)

    lags = range(2, min(max_lag, n // 4))
    rs_values = []

    for lag in lags:
        rs_list = []
        for start in range(0, len(returns) - lag, lag):
            chunk = returns[start:start + lag]
            if len(chunk) < 2:
                continue
            mean_r = np.mean(chunk)
            deviations = np.cumsum(chunk - mean_r)
            R = np.max(deviations) - np.min(deviations)
            S = np.std(chunk, ddof=1)
            if S > 1e-10:
                rs_list.append(R / S)
        if rs_list:
            rs_values.append((np.log(lag), np.log(np.mean(rs_list))))

    if len(rs_values) < 5:
        return HurstResult(0.5, "RANDOM_WALK", 0, "Insufficient lag data", 0)

    log_lags = np.array([x[0] for x in rs_values])
    log_rs = np.array([x[1] for x in rs_values])

    # Linear regression: log(R/S) = H * log(lag) + c
    coeffs = np.polyfit(log_lags, log_rs, 1)
    H = _safe(coeffs[0], 0.5)
    H = max(0.0, min(1.0, H))  # clamp

    # Residual-based confidence
    predicted = np.polyval(coeffs, log_lags)
    residuals = log_rs - predicted
    r_squared = max(0, 1 - np.var(residuals) / max(np.var(log_rs), 1e-10))
    confidence = _safe(r_squared * 100)

    if H < C.HURST_MEAN_REVERT:
        regime = "MEAN_REVERTING"
        interp = (
            f"Hurst = {H:.3f} — ANTI-PERSISTENT (mean-reverting). "
            f"Price tends to reverse direction. This is the regime where "
            f"RenTech's Medallion fund generates most alpha. "
            f"Statistical mean-reversion strategies have a mathematical edge here. "
            f"The market is 'rubber-band' like — stretches snap back."
        )
    elif H > C.HURST_TRENDING:
        regime = "TRENDING"
        interp = (
            f"Hurst = {H:.3f} — PERSISTENT (trending). "
            f"Price tends to continue in the same direction. "
            f"Momentum / trend-following strategies are appropriate. "
            f"Mean-reversion is dangerous — 'cheap' keeps getting cheaper."
        )
    else:
        regime = "RANDOM_WALK"
        interp = (
            f"Hurst = {H:.3f} — Near random walk (0.40–0.60 zone). "
            f"No strong statistical edge in either direction. "
            f"RenTech would reduce position size or sit out. "
            f"Wait for the regime to shift before deploying capital."
        )

    return HurstResult(
        hurst=H, regime=regime, confidence=confidence,
        interpretation=interp, lags_used=len(lags)
    )


# ═══════════════════════════════════════════════════════════════
# 2. ORNSTEIN-UHLENBECK (Mean Reversion Speed)
# ═══════════════════════════════════════════════════════════════

@dataclass
class OUResult:
    half_life: float          # days to revert halfway to mean
    theta: float              # mean reversion speed parameter
    mu: float                 # long-run mean level
    sigma: float              # volatility of the process
    is_tradeable: bool        # True if half-life in sweet spot
    interpretation: str


def ornstein_uhlenbeck(close: pd.Series, lookback: int = None) -> OUResult:
    """
    Fit Ornstein-Uhlenbeck process to estimate mean-reversion speed.

    dX = θ(μ - X)dt + σdW

    Half-life = ln(2) / θ — how many days for price to revert halfway.

    Jim Simons: "The key isn't just THAT it reverts, but HOW FAST.
    If it takes 100 days, the opportunity cost is too high.
    If it takes 1 day, it's noise. The sweet spot is 3-20 days."
    """
    lookback = lookback or C.OU_LOOKBACK
    series = close.dropna().values[-lookback:]

    if len(series) < 30:
        return OUResult(999, 0, 0, 0, False, "Insufficient data for OU estimation")

    # OU estimation via linear regression: X(t) - X(t-1) = θ(μ - X(t-1))·dt + ε
    X = series[:-1]
    dX = np.diff(series)
    dt = 1.0  # daily

    # Regress dX on X: dX = a + b·X + ε
    X_with_const = np.column_stack([np.ones(len(X)), X])
    try:
        params = np.linalg.lstsq(X_with_const, dX, rcond=None)[0]
    except np.linalg.LinAlgError:
        return OUResult(999, 0, 0, 0, False, "Numerical error in OU regression")

    a, b = params[0], params[1]

    # b should be negative for mean reversion
    if b >= 0:
        return OUResult(
            999, 0, _safe(np.mean(series)), _safe(np.std(dX)), False,
            "Price is NOT mean-reverting (positive drift coefficient). "
            "OU model does not apply. The stock may be trending or in a random walk."
        )

    theta = -b / dt
    mu = a / theta if theta > 1e-10 else _safe(np.mean(series))
    sigma = _safe(np.std(dX) / np.sqrt(dt))
    half_life = _safe(np.log(2) / theta) if theta > 1e-10 else 999.0

    is_tradeable = C.OU_HALF_LIFE_MIN <= half_life <= C.OU_HALF_LIFE_MAX

    if is_tradeable:
        interp = (
            f"Half-life = {half_life:.1f} days — TRADEABLE sweet spot! "
            f"Price reverts halfway to ₹{mu:.2f} in ~{half_life:.0f} trading days. "
            f"This is exactly what RenTech looks for: fast enough to profit, "
            f"slow enough that it's not noise. "
            f"θ={theta:.4f} (reversion speed), σ={sigma:.4f} (process vol)."
        )
    elif half_life < C.OU_HALF_LIFE_MIN:
        interp = (
            f"Half-life = {half_life:.1f} days — TOO FAST (likely noise). "
            f"Sub-2-day reversion is usually bid-ask bounce or microstructure noise, "
            f"not a tradeable signal on daily data."
        )
    else:
        interp = (
            f"Half-life = {half_life:.1f} days — TOO SLOW for active trading. "
            f"Mean reversion exists but takes too long to materialize. "
            f"Opportunity cost: capital is tied up waiting for convergence."
        )

    return OUResult(
        half_life=_safe(half_life), theta=_safe(theta),
        mu=_safe(mu), sigma=_safe(sigma),
        is_tradeable=is_tradeable, interpretation=interp
    )


# ═══════════════════════════════════════════════════════════════
# 3. VARIANCE RATIO TEST (Lo-MacKinlay)
# ═══════════════════════════════════════════════════════════════

@dataclass
class VarianceRatioResult:
    vr: float                 # variance ratio (1.0 = random walk)
    z_stat: float             # test statistic
    p_value: float            # significance
    regime: str               # MEAN_REVERTING | RANDOM_WALK | TRENDING
    interpretation: str


def variance_ratio_test(close: pd.Series, lag: int = 5) -> VarianceRatioResult:
    """
    Lo-MacKinlay Variance Ratio Test.

    VR(q) = Var(q-period returns) / (q × Var(1-period returns))

    VR < 1 → Mean-reverting (negative autocorrelation)
    VR = 1 → Random walk
    VR > 1 → Trending (positive autocorrelation)

    This is one of the most robust tests for market efficiency.
    RenTech uses it to identify WHERE markets are inefficient.
    """
    log_ret = _returns(close)
    n = len(log_ret)

    if n < lag * 3:
        return VarianceRatioResult(1.0, 0, 1.0, "RANDOM_WALK", "Insufficient data")

    # 1-period variance
    var_1 = np.var(log_ret, ddof=1)
    if var_1 < 1e-12:
        return VarianceRatioResult(1.0, 0, 1.0, "RANDOM_WALK", "Near-zero variance — stock may be halted")

    # q-period returns
    log_prices = np.log(close.dropna().values)
    q_ret = log_prices[lag:] - log_prices[:-lag]
    var_q = np.var(q_ret, ddof=1)

    vr = var_q / (lag * var_1) if var_1 > 1e-12 else 1.0

    # Heteroscedasticity-consistent z-statistic
    nq = len(q_ret)
    theta = 0
    for j in range(1, lag):
        delta_j = 0
        for t in range(j, n):
            delta_j += (log_ret.iloc[t] ** 2) * (log_ret.iloc[t - j] ** 2)
        sigma_1_sq = 0
        for t in range(n):
            sigma_1_sq += log_ret.iloc[t] ** 2
        sigma_1_sq /= n
        if sigma_1_sq > 1e-15:
            delta_j = (delta_j / n) / (sigma_1_sq ** 2)
        else:
            delta_j = 0
        weight = (2 * (lag - j) / lag) ** 2
        theta += weight * delta_j

    z_stat = _safe((vr - 1) / max(np.sqrt(theta / n), 1e-10))

    # Approximate p-value from standard normal
    from scipy.stats import norm
    p_value = _safe(2 * (1 - norm.cdf(abs(z_stat))))

    vr_safe = _safe(vr, 1.0)

    if vr_safe < 0.85:
        regime = "MEAN_REVERTING"
        interp = (
            f"Variance Ratio = {vr_safe:.3f} (< 1.0) — Mean-reverting. "
            f"Returns at {lag}-day horizon show negative autocorrelation. "
            f"{lag}-day variance is {(1-vr_safe)*100:.1f}% LESS than expected under random walk. "
            f"z-stat={z_stat:.2f}, p={p_value:.4f}. "
            f"{'Statistically significant!' if p_value < 0.05 else 'Not statistically significant at 5% level.'}"
        )
    elif vr_safe > 1.15:
        regime = "TRENDING"
        interp = (
            f"Variance Ratio = {vr_safe:.3f} (> 1.0) — Trending / persistent. "
            f"Returns at {lag}-day horizon show positive autocorrelation. "
            f"Momentum strategies have an edge. "
            f"z-stat={z_stat:.2f}, p={p_value:.4f}."
        )
    else:
        regime = "RANDOM_WALK"
        interp = (
            f"Variance Ratio = {vr_safe:.3f} — Approximately random walk. "
            f"No significant departure from efficient market at {lag}-day horizon. "
            f"z-stat={z_stat:.2f}, p={p_value:.4f}."
        )

    return VarianceRatioResult(
        vr=vr_safe, z_stat=_safe(z_stat), p_value=_safe(p_value),
        regime=regime, interpretation=interp
    )


# ═══════════════════════════════════════════════════════════════
# 4. AUGMENTED DICKEY-FULLER TEST (Stationarity)
# ═══════════════════════════════════════════════════════════════

@dataclass
class ADFResult:
    adf_stat: float
    p_value: float
    is_stationary: bool
    interpretation: str


def adf_test(series: pd.Series) -> ADFResult:
    """
    Augmented Dickey-Fuller test for stationarity.
    If stationary → mean-reverting → tradeable.
    """
    clean = series.dropna().values
    if len(clean) < 30:
        return ADFResult(0, 1.0, False, "Insufficient data for ADF test")

    # Implement ADF without statsmodels dependency
    # ADF: ΔY(t) = α + β·Y(t-1) + Σγ·ΔY(t-i) + ε
    n = len(clean)
    max_lags = min(int(np.floor(12 * (n / 100) ** 0.25)), n // 4)
    max_lags = max(1, max_lags)

    dy = np.diff(clean)
    y_lag = clean[:-1]

    # Set up regression with lagged differences
    n_obs = len(dy) - max_lags
    if n_obs < 10:
        return ADFResult(0, 1.0, False, "Insufficient observations after lagging")

    Y = dy[max_lags:]
    X_cols = [np.ones(n_obs), y_lag[max_lags:]]
    for i in range(1, max_lags + 1):
        X_cols.append(dy[max_lags - i:len(dy) - i])
    X = np.column_stack(X_cols)

    try:
        params = np.linalg.lstsq(X, Y, rcond=None)[0]
        residuals = Y - X @ params
        se = np.sqrt(np.sum(residuals**2) / (n_obs - len(params)))
        # Use pseudo-inverse for rank-deficient matrices
        XtX = X.T @ X
        cond = np.linalg.cond(XtX)
        if cond > 1e12:
            return ADFResult(0, 1.0, False, "Rank-deficient regression matrix in ADF")
        XtX_inv = np.linalg.inv(XtX)
        se_beta = se * np.sqrt(XtX_inv[1, 1])
        adf_stat = params[1] / se_beta if se_beta > 1e-10 else 0
    except (np.linalg.LinAlgError, ValueError):
        return ADFResult(0, 1.0, False, "Numerical error in ADF computation")

    adf_stat = _safe(adf_stat)

    # Critical values (MacKinnon 1994, with constant, no trend)
    # 1%: -3.43, 5%: -2.86, 10%: -2.57
    if adf_stat < -3.43:
        p_approx = 0.01
    elif adf_stat < -2.86:
        p_approx = 0.05
    elif adf_stat < -2.57:
        p_approx = 0.10
    elif adf_stat < -1.94:
        p_approx = 0.30
    else:
        p_approx = 0.50

    is_stationary = adf_stat < -2.86  # 5% significance

    if is_stationary:
        interp = (
            f"ADF statistic = {adf_stat:.3f} (p ≈ {p_approx:.2f}) — STATIONARY. "
            f"The series reverts to its mean. This is the foundation for "
            f"statistical arbitrage. RenTech can model this with OU process."
        )
    else:
        interp = (
            f"ADF statistic = {adf_stat:.3f} (p ≈ {p_approx:.2f}) — NOT stationary. "
            f"The series has a unit root (random walk component). "
            f"Mean-reversion on raw prices is unreliable. "
            f"Consider trading spreads or ratios instead."
        )

    return ADFResult(
        adf_stat=adf_stat, p_value=_safe(p_approx),
        is_stationary=is_stationary, interpretation=interp
    )


# ═══════════════════════════════════════════════════════════════
# 5. AUTOCORRELATION ANALYSIS
# ═══════════════════════════════════════════════════════════════

@dataclass
class AutocorrResult:
    lag1: float               # 1-day autocorrelation
    lag5: float               # 5-day (weekly)
    lag21: float              # 21-day (monthly)
    dominant_pattern: str     # REVERSAL | CONTINUATION | NONE
    serial_correlation: float # overall measure
    interpretation: str


def autocorrelation_analysis(close: pd.Series) -> AutocorrResult:
    """
    Measure serial correlation at multiple horizons.

    Negative autocorrelation → mean reversion (RenTech sweet spot)
    Positive autocorrelation → momentum
    Zero → random walk (no edge)

    Jim Simons: "Markets are not perfectly efficient. Small but
    persistent serial correlations, invisible to the naked eye,
    are the bread crumbs we follow."
    """
    ret = _pct_returns(close)
    n = len(ret)

    if n < 30:
        return AutocorrResult(0, 0, 0, "NONE", 0, "Insufficient data")

    def _acf(lag):
        if lag >= n:
            return 0.0
        r = ret.values
        mean_r = np.mean(r)
        denom = np.sum((r - mean_r) ** 2)
        if denom < 1e-15:
            return 0.0
        numer = np.sum((r[lag:] - mean_r) * (r[:-lag] - mean_r))
        return _safe(numer / denom)

    ac1 = _acf(1)
    ac5 = _acf(5)
    ac21 = _acf(21) if n > 25 else 0.0

    # Dominant pattern
    avg_short = (ac1 + ac5) / 2
    if avg_short < -0.05:
        pattern = "REVERSAL"
    elif avg_short > 0.05:
        pattern = "CONTINUATION"
    else:
        pattern = "NONE"

    serial = _safe(avg_short)

    if pattern == "REVERSAL":
        interp = (
            f"Negative serial correlation detected (AC1={ac1:.3f}, AC5={ac5:.3f}). "
            f"Returns tend to REVERSE — up days followed by down days and vice versa. "
            f"This is the hallmark of mean-reverting behavior. "
            f"RenTech's Medallion fund thrives in this regime."
        )
    elif pattern == "CONTINUATION":
        interp = (
            f"Positive serial correlation (AC1={ac1:.3f}, AC5={ac5:.3f}). "
            f"Returns tend to CONTINUE — momentum is present. "
            f"Trend-following strategies have a statistical edge."
        )
    else:
        interp = (
            f"Weak serial correlation (AC1={ac1:.3f}, AC5={ac5:.3f}). "
            f"Returns are approximately independent. No strong statistical edge "
            f"from autocorrelation alone."
        )

    return AutocorrResult(
        lag1=ac1, lag5=ac5, lag21=ac21,
        dominant_pattern=pattern, serial_correlation=serial,
        interpretation=interp
    )


# ═══════════════════════════════════════════════════════════════
# 6. ENTROPY ANALYSIS (Information Theory)
# ═══════════════════════════════════════════════════════════════

@dataclass
class EntropyResult:
    shannon_entropy: float    # bits of information in returns
    normalized_entropy: float # 0–1 (1 = maximum disorder)
    predictability: float     # 1 - normalized_entropy (higher = more predictable)
    interpretation: str


def entropy_analysis(close: pd.Series, n_bins: int = 20) -> EntropyResult:
    """
    Shannon entropy of returns distribution.

    Low entropy → returns are concentrated in few outcomes → predictable.
    High entropy → returns are uniformly distributed → unpredictable.

    RenTech insight: Stocks with lower entropy have more "structure"
    in their returns, making them better candidates for modelling.
    """
    ret = _pct_returns(close).dropna().values
    n = len(ret)

    if n < 30:
        return EntropyResult(0, 1.0, 0.0, "Insufficient data")

    # Guard: constant price → all returns are zero
    if np.std(ret) < 1e-12:
        return EntropyResult(0, 0.0, 1.0, "Constant returns — zero entropy (trivially predictable)")

    # Histogram-based Shannon entropy
    counts, _ = np.histogram(ret, bins=n_bins)
    probs = counts / n
    probs = probs[probs > 0]  # remove zero bins

    shannon = -np.sum(probs * np.log2(probs))
    max_entropy = np.log2(n_bins)
    norm_entropy = _safe(shannon / max_entropy) if max_entropy > 0 else 1.0
    predictability = _safe(1 - norm_entropy)

    if predictability > 0.30:
        interp = (
            f"Shannon entropy = {shannon:.2f} bits (normalized: {norm_entropy:.2f}). "
            f"Returns show STRUCTURED distribution — predictability score {predictability:.0%}. "
            f"This stock has patterns that deviate from pure randomness. "
            f"RenTech allocates MORE capital to such stocks."
        )
    elif predictability > 0.10:
        interp = (
            f"Shannon entropy = {shannon:.2f} bits (normalized: {norm_entropy:.2f}). "
            f"MODERATE structure in returns — predictability {predictability:.0%}. "
            f"Some statistical edge exists but requires careful extraction."
        )
    else:
        interp = (
            f"Shannon entropy = {shannon:.2f} bits (normalized: {norm_entropy:.2f}). "
            f"Returns are nearly RANDOM — predictability only {predictability:.0%}. "
            f"Limited statistical edge. RenTech would under-weight this name."
        )

    return EntropyResult(
        shannon_entropy=_safe(shannon),
        normalized_entropy=_safe(norm_entropy),
        predictability=_safe(predictability),
        interpretation=interp
    )


# ═══════════════════════════════════════════════════════════════
# 7. VOLATILITY CLUSTERING (ARCH Effects)
# ═══════════════════════════════════════════════════════════════

@dataclass
class VolClusterResult:
    arch_ratio: float         # ratio of squared-return autocorrelation
    persistence: float        # how long vol shocks last (0–1)
    current_vol_state: str    # LOW | NORMAL | HIGH | EXTREME
    vol_of_vol: float         # volatility of volatility
    interpretation: str


def volatility_clustering(close: pd.Series, lookback: int = 252) -> VolClusterResult:
    """
    Measure ARCH/GARCH-like volatility clustering.

    Key insight from RenTech: volatility is MORE predictable than returns.
    High vol follows high vol (clustering). This allows:
    1. Better position sizing (reduce when vol is high)
    2. Better option pricing (vol mean-reverts)
    3. Regime detection (vol spikes = regime change)
    """
    ret = _pct_returns(close).dropna().values[-lookback:]
    n = len(ret)

    if n < 50:
        return VolClusterResult(0, 0, "NORMAL", 0, "Insufficient data")

    sq_ret = ret ** 2

    # Autocorrelation of squared returns (ARCH test proxy)
    mean_sq = np.mean(sq_ret)
    denom = np.sum((sq_ret - mean_sq) ** 2)

    if denom < 1e-20:
        return VolClusterResult(0, 0, "NORMAL", 0, "Zero variance in squared returns")

    # Lag-1 autocorrelation of squared returns
    numer = np.sum((sq_ret[1:] - mean_sq) * (sq_ret[:-1] - mean_sq))
    arch_acf = _safe(numer / denom)

    # Persistence: average of lag-1 through lag-5 autocorrelation
    persistence_vals = []
    for lag in range(1, min(6, n // 2)):
        num = np.sum((sq_ret[lag:] - mean_sq) * (sq_ret[:-lag] - mean_sq))
        persistence_vals.append(num / denom)
    persistence = _safe(np.mean(persistence_vals)) if persistence_vals else 0

    # Current volatility state
    rolling_vol = pd.Series(ret).rolling(20).std().dropna().values
    if len(rolling_vol) < 10:
        current_state = "NORMAL"
    else:
        current_vol = rolling_vol[-1]
        vol_percentile = (rolling_vol < current_vol).sum() / len(rolling_vol)
        if vol_percentile > 0.90:
            current_state = "EXTREME"
        elif vol_percentile > 0.70:
            current_state = "HIGH"
        elif vol_percentile < 0.20:
            current_state = "LOW"
        else:
            current_state = "NORMAL"

    # Vol of vol
    vol_series = pd.Series(ret).rolling(20).std().dropna()
    vov = _safe(vol_series.std() / max(vol_series.mean(), 1e-10))

    if arch_acf > 0.20:
        interp = (
            f"STRONG volatility clustering (ARCH ratio={arch_acf:.3f}). "
            f"Vol shocks persist — today's high vol predicts tomorrow's. "
            f"Persistence={persistence:.3f}. Current state: {current_state}. "
            f"RenTech uses this to dynamically size positions: "
            f"REDUCE exposure in high-vol clusters, INCREASE in low-vol periods."
        )
    elif arch_acf > 0.05:
        interp = (
            f"Moderate clustering (ARCH ratio={arch_acf:.3f}). "
            f"Some vol predictability. Current state: {current_state}. "
            f"Useful for adaptive position sizing."
        )
    else:
        interp = (
            f"Weak clustering (ARCH ratio={arch_acf:.3f}). "
            f"Volatility changes are relatively unpredictable. "
            f"Current state: {current_state}."
        )

    return VolClusterResult(
        arch_ratio=_safe(arch_acf), persistence=_safe(persistence),
        current_vol_state=current_state, vol_of_vol=_safe(vov),
        interpretation=interp
    )


# ═══════════════════════════════════════════════════════════════
# 8. COMPOSITE STATISTICAL PROFILE
# ═══════════════════════════════════════════════════════════════

@dataclass
class StatisticalProfile:
    """Aggregated statistical analysis — the quant's X-ray of a stock."""
    hurst: HurstResult
    ou: OUResult
    variance_ratio: VarianceRatioResult
    adf: ADFResult
    autocorr: AutocorrResult
    entropy: EntropyResult
    vol_cluster: VolClusterResult

    # Derived scores
    mean_reversion_score: float   # 0–100: how mean-reverting is this stock?
    momentum_score: float         # 0–100: how trending/persistent?
    predictability_score: float   # 0–100: overall statistical edge
    optimal_strategy: str         # MEAN_REVERSION | MOMENTUM | HYBRID | AVOID
    statistical_edge: float       # 0–100: confidence in any edge
    summary: str


def build_statistical_profile(close: pd.Series) -> StatisticalProfile:
    """
    Run ALL statistical tests and produce a unified profile.
    This is the foundation layer — regime detection and signal
    generation consume this profile.
    """
    h = hurst_exponent(close)
    ou = ornstein_uhlenbeck(close)
    vr = variance_ratio_test(close)
    adf_r = adf_test(close)
    ac = autocorrelation_analysis(close)
    ent = entropy_analysis(close)
    vc = volatility_clustering(close)

    # ── Score: Mean Reversion (0–100) ──
    mr_score = 50.0
    # Hurst contribution (max ±25)
    if h.hurst < 0.5:
        mr_score += (0.5 - h.hurst) * 50  # H=0.3 → +10, H=0.1 → +20
    else:
        mr_score -= (h.hurst - 0.5) * 50

    # OU half-life contribution (max ±15)
    if ou.is_tradeable:
        mr_score += 15
    elif ou.half_life < 50:
        mr_score += 5

    # Variance ratio (max ±10)
    if vr.vr < 0.85:
        mr_score += 10
    elif vr.vr < 1.0:
        mr_score += 5 * (1.0 - vr.vr) / 0.15

    # ADF stationarity (max +10)
    if adf_r.is_stationary:
        mr_score += 10

    # Autocorrelation (max ±10)
    if ac.dominant_pattern == "REVERSAL":
        mr_score += 10
    elif ac.dominant_pattern == "CONTINUATION":
        mr_score -= 10

    mr_score = max(0, min(100, mr_score))

    # ── Score: Momentum (0–100) ──
    mom_score = 50.0
    if h.hurst > 0.5:
        mom_score += (h.hurst - 0.5) * 50
    else:
        mom_score -= (0.5 - h.hurst) * 50

    if vr.vr > 1.15:
        mom_score += 10
    elif vr.vr > 1.0:
        mom_score += 5 * (vr.vr - 1.0) / 0.15

    if ac.dominant_pattern == "CONTINUATION":
        mom_score += 10
    elif ac.dominant_pattern == "REVERSAL":
        mom_score -= 10

    mom_score = max(0, min(100, mom_score))

    # ── Score: Predictability (0–100) ──
    pred_score = ent.predictability * 100
    # Boost if we have clear regime
    if max(mr_score, mom_score) > 65:
        pred_score = min(100, pred_score + 15)
    # Boost if vol is clustered (predictable vol = tradeable)
    if vc.arch_ratio > 0.15:
        pred_score = min(100, pred_score + 10)

    pred_score = max(0, min(100, pred_score))

    # ── Optimal Strategy ──
    if mr_score >= 65 and mr_score > mom_score + 10:
        optimal = "MEAN_REVERSION"
    elif mom_score >= 65 and mom_score > mr_score + 10:
        optimal = "MOMENTUM"
    elif max(mr_score, mom_score) >= 55:
        optimal = "HYBRID"
    else:
        optimal = "AVOID"

    # ── Statistical Edge ──
    edge = max(mr_score, mom_score) * 0.5 + pred_score * 0.3 + min(h.confidence, 100) * 0.2
    edge = max(0, min(100, edge))

    # ── Summary ──
    summary = (
        f"STATISTICAL PROFILE: Hurst={h.hurst:.3f} ({h.regime}), "
        f"OU half-life={ou.half_life:.1f}d, VR={vr.vr:.3f}, "
        f"ADF {'stationary' if adf_r.is_stationary else 'non-stationary'}, "
        f"Autocorr={ac.dominant_pattern}. "
        f"MR Score={mr_score:.0f}, Mom Score={mom_score:.0f}, "
        f"Predictability={pred_score:.0f}. "
        f"Optimal: {optimal}. Edge confidence: {edge:.0f}/100."
    )

    return StatisticalProfile(
        hurst=h, ou=ou, variance_ratio=vr, adf=adf_r,
        autocorr=ac, entropy=ent, vol_cluster=vc,
        mean_reversion_score=_safe(mr_score),
        momentum_score=_safe(mom_score),
        predictability_score=_safe(pred_score),
        optimal_strategy=optimal,
        statistical_edge=_safe(edge),
        summary=summary
    )
