"""
Volatility forecasting: EWMA, GARCH(1,1), mean-reversion ensemble.

Ensemble approach (Sinclair Ch.3): combine multiple estimators because
no single model dominates across regimes. EWMA reacts fast, GARCH
captures clustering, mean-reversion anchors to long-run average.

Variance Premium (Sinclair Ch.4-5): IV − RV is the primary edge.
India: ~2.5 pts avg, positive ~70% of time (vs ~4 pts / 85% SPX).
"""

import math
import numpy as np
from scipy.optimize import minimize


# ---------------------------------------------------------------------------
# EWMA (RiskMetrics)
# ---------------------------------------------------------------------------

def ewma_vol(returns, lambda_=0.94, annualize=True):
    """
    Exponentially Weighted Moving Average volatility.

    σ²_t = λ·σ²_{t-1} + (1−λ)·r²_t

    λ=0.94 is RiskMetrics default (97% of weight in last ~40 days).

    Parameters
    ----------
    returns : array-like – log returns (newest last)
    lambda_ : float – decay factor (0.90–0.97 typical)
    annualize : bool – multiply by √252

    Returns
    -------
    float – EWMA volatility estimate
    """
    r = np.asarray(returns, dtype=float)
    if len(r) < 2:
        return float('nan')

    var = r[0] ** 2
    for ret in r[1:]:
        var = lambda_ * var + (1 - lambda_) * ret ** 2

    vol = math.sqrt(var)
    if annualize:
        vol *= math.sqrt(252)
    return float(vol)


# ---------------------------------------------------------------------------
# GARCH(1,1) via MLE
# ---------------------------------------------------------------------------

def _garch_negloglik(params, returns):
    """Negative log-likelihood for GARCH(1,1)."""
    omega, alpha, beta = params
    n = len(returns)
    var = np.var(returns)  # unconditional as starting value
    ll = 0.0
    for i in range(n):
        ll += -0.5 * (math.log(2 * math.pi) + math.log(var) + returns[i] ** 2 / var)
        var = omega + alpha * returns[i] ** 2 + beta * var
        var = max(var, 1e-12)
    return -ll


def garch_vol(returns, horizon_days=1, annualize=True):
    """
    Fit GARCH(1,1) and return volatility forecast.

    σ²_t = ω + α·r²_{t-1} + β·σ²_{t-1}
    Long-run vol = √(ω / (1 − α − β))

    Multi-day horizon (Sinclair eq for h-step GARCH):
      σ²_h = h·V_L + (σ²_1 − V_L)·(1 − (α+β)^h) / (1 − (α+β))
      where V_L = ω/(1−α−β) is long-run variance

    Parameters
    ----------
    returns : array-like – log returns (newest last), needs ≥30 observations
    horizon_days : int – forecast horizon (1=next day, 30=next month)
    annualize : bool – multiply by √252

    Returns
    -------
    dict:
        forecast  – h-step-ahead vol (annualized if requested)
        forecast_1d – one-step-ahead daily vol (always annualized if annualize=True)
        long_run  – unconditional (long-run) vol
        alpha     – news coefficient
        beta      – persistence
        persistence – α + β (should be < 1)
    """
    r = np.asarray(returns, dtype=float)
    if len(r) < 30:
        return {'forecast': float('nan'), 'forecast_1d': float('nan'),
                'long_run': float('nan'), 'alpha': float('nan'),
                'beta': float('nan'), 'persistence': float('nan')}

    sample_var = np.var(r)
    x0 = [sample_var * 0.05, 0.08, 0.88]

    bounds = [(1e-10, sample_var * 10), (0.001, 0.5), (0.3, 0.999)]
    constraints = {'type': 'ineq', 'fun': lambda p: 0.999 - p[1] - p[2]}

    result = minimize(_garch_negloglik, x0, args=(r,), method='SLSQP',
                       bounds=bounds, constraints=constraints,
                       options={'maxiter': 500, 'ftol': 1e-10})

    omega, alpha, beta = result.x
    persistence = alpha + beta

    # one-step forecast: run filter through all data
    var = sample_var
    for ret in r:
        var = omega + alpha * ret ** 2 + beta * var

    var_1d = var
    long_run_var = omega / max(1 - persistence, 1e-6)

    # h-step forecast: mean-reverts toward long-run variance
    h = horizon_days
    if abs(persistence - 1.0) > 1e-6 and h > 1:
        # σ²_h = h·V_L + (σ²_1 − V_L) × (1 − p^h) / (1 − p)
        total_var_h = h * long_run_var + (var_1d - long_run_var) * (1 - persistence ** h) / (1 - persistence)
        avg_daily_var_h = total_var_h / h
    else:
        avg_daily_var_h = var_1d

    forecast_1d = math.sqrt(max(var_1d, 0))
    forecast = math.sqrt(max(avg_daily_var_h, 0))
    long_run = math.sqrt(max(long_run_var, 0))

    if annualize:
        forecast_1d *= math.sqrt(252)
        forecast *= math.sqrt(252)
        long_run *= math.sqrt(252)

    return {
        'forecast': float(forecast),
        'forecast_1d': float(forecast_1d),
        'long_run': float(long_run),
        'alpha': float(alpha),
        'beta': float(beta),
        'persistence': float(persistence),
    }


# ---------------------------------------------------------------------------
# Mean-reversion model
# ---------------------------------------------------------------------------

def mean_reversion_vol(prices, windows=(5, 10, 20, 60), long_window=252,
                       annualize=True):
    """
    Weighted blend of short-term vol toward long-run average.

    Short windows capture recent regime, long window anchors to mean.
    Weights: more recent windows get higher weight (Natenberg 5-period).

    Parameters
    ----------
    prices : array-like – closing prices (newest last)
    windows : tuple – short-term lookback windows
    long_window : int – long-run lookback
    annualize : bool

    Returns
    -------
    dict:
        forecast  – blended vol estimate
        components – vol at each window
        long_run  – long-run vol
    """
    prices = np.asarray(prices, dtype=float)
    if len(prices) < long_window + 1:
        return {'forecast': float('nan'), 'components': {},
                'long_run': float('nan')}

    log_returns = np.log(prices[1:] / prices[:-1])

    components = {}
    for w in windows:
        if len(log_returns) >= w:
            recent = log_returns[-w:]
            v = float(np.std(recent, ddof=1))
            if annualize:
                v *= math.sqrt(252)
            components[w] = v

    long_run_r = log_returns[-long_window:]
    long_run = float(np.std(long_run_r, ddof=1))
    if annualize:
        long_run *= math.sqrt(252)

    if not components:
        return {'forecast': float('nan'), 'components': components,
                'long_run': long_run}

    # weights: linearly increasing for shorter windows + long-run anchor
    vals = list(components.values()) + [long_run]
    n = len(vals)
    weights = list(range(n, 0, -1))
    total_w = sum(weights)
    forecast = sum(v * w / total_w for v, w in zip(vals, weights))

    return {
        'forecast': float(forecast),
        'components': components,
        'long_run': float(long_run),
    }


# ---------------------------------------------------------------------------
# Ensemble forecast
# ---------------------------------------------------------------------------

def ensemble_forecast(prices, weights=(0.4, 0.4, 0.2), lambda_=0.94,
                      horizon_days=1):
    """
    Ensemble: w1·EWMA + w2·GARCH + w3·mean_reversion.

    Parameters
    ----------
    prices : array-like – closing prices (newest last, ≥252 values)
    weights : tuple – (ewma_weight, garch_weight, mean_rev_weight)
    lambda_ : float – EWMA decay
    horizon_days : int – forecast horizon for GARCH (1=next day, 30=monthly)

    Returns
    -------
    dict:
        forecast       – ensemble vol
        ewma           – EWMA component
        garch          – GARCH forecast
        garch_long_run – GARCH long-run vol
        mean_rev       – mean-reversion forecast
        confidence     – (low, high) 80% interval based on component spread
    """
    prices = np.asarray(prices, dtype=float)
    log_returns = np.log(prices[1:] / prices[:-1])

    e = ewma_vol(log_returns, lambda_=lambda_, annualize=True)
    g = garch_vol(log_returns, horizon_days=horizon_days, annualize=True)
    m = mean_reversion_vol(prices, annualize=True)

    components = [e, g['forecast'], m['forecast']]
    valid = [(c, w) for c, w in zip(components, weights)
             if not (c != c)]  # filter NaN

    if not valid:
        return {'forecast': float('nan'), 'ewma': e,
                'garch': g['forecast'], 'garch_long_run': g['long_run'],
                'mean_rev': m['forecast'], 'confidence': (float('nan'), float('nan'))}

    vals, wts = zip(*valid)
    total_w = sum(wts)
    forecast = sum(v * w / total_w for v, w in zip(vals, wts))

    spread = max(vals) - min(vals)
    lo = forecast - 0.5 * spread
    hi = forecast + 0.5 * spread

    return {
        'forecast': float(forecast),
        'ewma': float(e),
        'garch': float(g['forecast']),
        'garch_long_run': float(g['long_run']),
        'mean_rev': float(m['forecast']),
        'confidence': (float(lo), float(hi)),
    }


# ---------------------------------------------------------------------------
# Variance Premium
# ---------------------------------------------------------------------------

def variance_premium(iv, rv):
    """IV − RV in volatility points. Positive = sell premium."""
    return iv - rv


def vp_percentile(current_vp, vp_history):
    """
    Where current VP sits in its historical distribution.

    Parameters
    ----------
    current_vp : float – current IV − RV
    vp_history : array-like – historical VP values

    Returns
    -------
    float – percentile (0-100)
    """
    h = np.asarray(vp_history, dtype=float)
    h = h[~np.isnan(h)]
    if len(h) == 0:
        return float('nan')
    return float(np.sum(h <= current_vp) / len(h) * 100)


# ---------------------------------------------------------------------------
# self-check
# ---------------------------------------------------------------------------

def _self_check():
    """Verify forecasters on synthetic GBM data."""
    np.random.seed(42)
    true_vol = 0.20
    n = 500
    dt = 1 / 252
    prices = [100.0]
    for _ in range(n):
        z = np.random.randn()
        prices.append(prices[-1] * math.exp(-0.5 * true_vol ** 2 * dt + true_vol * math.sqrt(dt) * z))
    prices = np.array(prices)
    log_r = np.log(prices[1:] / prices[:-1])

    # EWMA
    e = ewma_vol(log_r)
    assert 0.10 < e < 0.35, f"EWMA vol={e:.4f} out of range"

    # GARCH
    g = garch_vol(log_r)
    assert 0.10 < g['forecast'] < 0.40, f"GARCH forecast={g['forecast']:.4f} out of range"
    assert g['persistence'] < 1.0, f"GARCH not stationary: persistence={g['persistence']:.4f}"

    # Mean-reversion
    m = mean_reversion_vol(prices)
    assert 0.10 < m['forecast'] < 0.35, f"Mean-rev forecast={m['forecast']:.4f} out of range"

    # Ensemble
    ens = ensemble_forecast(prices)
    assert 0.10 < ens['forecast'] < 0.35, f"Ensemble forecast={ens['forecast']:.4f} out of range"
    lo, hi = ens['confidence']
    assert lo < ens['forecast'] < hi, "Confidence interval should bracket forecast"

    # Variance premium
    assert abs(variance_premium(0.22, 0.18) - 0.04) < 1e-10
    assert vp_percentile(0.03, [0.01, 0.02, 0.03, 0.04, 0.05]) == 60.0

    print("vol_forecast.py: all checks passed")


if __name__ == '__main__':
    _self_check()
