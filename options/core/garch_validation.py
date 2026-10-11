"""
GARCH(1,1) validation for Indian markets.

Standard GARCH may not capture India's event-driven spikes (RBI, elections,
budget). This module validates fit quality and flags when the model is unreliable.

Diagnostics: Ljung-Box on squared residuals, persistence check, long-run vol
vs realized, tail behavior (kurtosis of standardized residuals).
"""

import math
import numpy as np
from .vol_forecast import garch_vol, ewma_vol


def validate_garch_fit(returns, label=''):
    """
    Fit GARCH(1,1) and run diagnostics.

    Parameters
    ----------
    returns : array-like — daily log returns (≥60 observations)
    label : str — identifier (e.g. 'NIFTY', 'BANKNIFTY')

    Returns
    -------
    dict:
        fit       — GARCH parameters (alpha, beta, persistence, long_run)
        diagnostics — pass/fail checks
        verdict   — 'reliable', 'caution', or 'unreliable'
        issues    — list of specific problems
    """
    r = np.asarray(returns, dtype=float)
    issues = []

    if len(r) < 60:
        return {'fit': {}, 'diagnostics': {}, 'verdict': 'unreliable',
                'issues': [f'Too few observations: {len(r)} (need ≥60)']}

    g = garch_vol(r, horizon_days=1, annualize=True)

    if math.isnan(g.get('persistence', float('nan'))):
        return {'fit': g, 'diagnostics': {}, 'verdict': 'unreliable',
                'issues': ['GARCH fit failed (NaN parameters)']}

    alpha, beta = g['alpha'], g['beta']
    persistence = g['persistence']
    long_run_vol = g['long_run']

    # 1. Stationarity: α + β < 1
    stationary = persistence < 0.999
    if not stationary:
        issues.append(f'Non-stationary: persistence={persistence:.4f} ≥ 0.999')

    # 2. Persistence sanity: typical range 0.90-0.99 for equity
    persistence_ok = 0.85 < persistence < 0.999
    if not persistence_ok and stationary:
        issues.append(f'Unusual persistence: {persistence:.4f} (typical 0.90-0.99)')

    # 3. Alpha check: news impact. Too low = ignores shocks, too high = overreacts
    alpha_ok = 0.01 < alpha < 0.25
    if not alpha_ok:
        issues.append(f'Alpha={alpha:.4f} outside normal range (0.01-0.25)')

    # 4. Long-run vol sanity for India: Nifty ~14%, BankNifty ~18%
    rv_annual = float(np.std(r, ddof=1) * math.sqrt(252))
    lr_ratio = long_run_vol / rv_annual if rv_annual > 0 else float('inf')
    lr_ok = 0.5 < lr_ratio < 2.0
    if not lr_ok:
        issues.append(f'Long-run vol ({long_run_vol:.1%}) vs realized ({rv_annual:.1%}): '
                      f'ratio {lr_ratio:.2f} outside 0.5-2.0')

    # 5. Standardized residuals: should be ~N(0,1) if model is good
    omega = long_run_vol**2 / 252 * (1 - persistence) if persistence < 1 else 1e-8
    var_t = np.var(r)
    std_resid = []
    for ret in r:
        std_resid.append(ret / math.sqrt(max(var_t, 1e-12)))
        var_t = omega + alpha * ret**2 + beta * var_t
        var_t = max(var_t, 1e-12)

    std_resid = np.array(std_resid)
    resid_kurt = float(np.mean(std_resid**4) / np.mean(std_resid**2)**2) if np.mean(std_resid**2) > 0 else 0
    # Normal kurtosis = 3; fat tails > 5 is common for equity
    kurt_ok = resid_kurt < 8
    if not kurt_ok:
        issues.append(f'Residual kurtosis={resid_kurt:.1f} (>8 = extreme tails not captured)')

    # 6. Ljung-Box proxy: autocorrelation of squared standardized residuals
    sq_resid = std_resid**2
    if len(sq_resid) > 20:
        acf_1 = float(np.corrcoef(sq_resid[1:], sq_resid[:-1])[0, 1])
        acf_ok = abs(acf_1) < 0.15  # low autocorrelation = vol clustering captured
        if not acf_ok:
            issues.append(f'Squared residual ACF(1)={acf_1:.3f} (>0.15 = vol clustering not fully captured)')
    else:
        acf_1 = float('nan')
        acf_ok = True

    # Verdict
    critical = not stationary or math.isnan(g['forecast'])
    n_issues = len(issues)
    if critical or n_issues >= 3:
        verdict = 'unreliable'
    elif n_issues >= 1:
        verdict = 'caution'
    else:
        verdict = 'reliable'

    return {
        'label': label,
        'n_obs': len(r),
        'fit': {
            'alpha': round(alpha, 4),
            'beta': round(beta, 4),
            'persistence': round(persistence, 4),
            'long_run_vol': round(long_run_vol, 4),
            'forecast_1d': round(g['forecast_1d'], 4),
        },
        'diagnostics': {
            'stationary': stationary,
            'persistence_ok': persistence_ok,
            'alpha_ok': alpha_ok,
            'long_run_ratio': round(lr_ratio, 2),
            'long_run_ok': lr_ok,
            'residual_kurtosis': round(resid_kurt, 1),
            'kurtosis_ok': kurt_ok,
            'sq_resid_acf1': round(acf_1, 3) if not math.isnan(acf_1) else None,
            'acf_ok': acf_ok,
            'realized_vol': round(rv_annual, 4),
        },
        'verdict': verdict,
        'issues': issues,
    }


def compare_forecasters(returns, prices=None):
    """
    Compare EWMA vs GARCH vs realized vol for the given data.

    Returns dict with each forecaster's estimate and which is closest to
    recent realized vol (last 20 days).
    """
    r = np.asarray(returns, dtype=float)
    if len(r) < 60:
        return {'error': f'Need ≥60 returns, got {len(r)}'}

    ewma = ewma_vol(r, annualize=True)
    garch = garch_vol(r, annualize=True)
    rv_20 = float(np.std(r[-20:], ddof=1) * math.sqrt(252))
    rv_60 = float(np.std(r[-60:], ddof=1) * math.sqrt(252))

    forecasts = {
        'ewma': ewma,
        'garch': garch['forecast_1d'],
        'garch_long_run': garch['long_run'],
    }

    # Which is closest to recent realized?
    errors = {k: abs(v - rv_20) for k, v in forecasts.items() if not math.isnan(v)}
    best = min(errors, key=errors.get) if errors else 'none'

    return {
        'rv_20d': round(rv_20, 4),
        'rv_60d': round(rv_60, 4),
        'forecasts': {k: round(v, 4) for k, v in forecasts.items()},
        'closest_to_rv20': best,
        'errors_vs_rv20': {k: round(v, 4) for k, v in errors.items()},
    }


def _self_check():
    np.random.seed(42)
    n = 300
    dt = 1 / 252
    true_vol = 0.18
    prices = [100.0]
    for _ in range(n):
        z = np.random.randn()
        prices.append(prices[-1] * math.exp(-0.5 * true_vol**2 * dt + true_vol * math.sqrt(dt) * z))
    log_r = np.log(np.array(prices[1:]) / np.array(prices[:-1]))

    # Validation on well-behaved GBM data
    v = validate_garch_fit(log_r, label='Synthetic_GBM')
    assert v['verdict'] in ('reliable', 'caution'), f"GBM should be reliable/caution, got {v['verdict']}"
    assert v['fit']['persistence'] < 1.0
    assert v['diagnostics']['stationary']

    # Too few observations
    v2 = validate_garch_fit(log_r[:20])
    assert v2['verdict'] == 'unreliable'

    # Compare forecasters
    comp = compare_forecasters(log_r)
    assert 'rv_20d' in comp
    assert 'ewma' in comp['forecasts']
    assert comp['closest_to_rv20'] in ('ewma', 'garch', 'garch_long_run')

    # Stress: add fat-tailed event (India-like RBI spike)
    spiked = log_r.copy()
    spiked[100] = -0.08  # 8% drop
    spiked[101] = 0.05   # 5% bounce
    v3 = validate_garch_fit(spiked, label='With_spike')
    assert v3['diagnostics']['residual_kurtosis'] > 3.0, "Spike should increase kurtosis"

    print("garch_validation.py: all checks passed")


if __name__ == '__main__':
    _self_check()
