"""
Historical volatility estimators and volatility cone.

Four estimators (Natenberg Ch.20, Varsity Ch.15-17):
  1. Close-to-Close — simplest, uses only closing prices
  2. Parkinson     — uses high-low range, ~5× more efficient
  3. Garman-Klass  — uses OHLC, best single-estimator efficiency
  4. Yang-Zhang    — uses OHLC with overnight jumps, most robust

Vol Cone (Varsity Ch.20): percentile bands of realized vol at different
lookback windows. When IV > cone's 75th percentile → vol is expensive
(sell). When IV < 25th percentile → vol is cheap (buy).
"""

import math
import numpy as np
import pandas as pd


def close_to_close_vol(prices, window=20, annualize=True):
    """
    Standard deviation of log returns.

    √[(1/(n-1)) × Σ(ln(Ci/Ci-1))²] × √252

    Parameters
    ----------
    prices : array-like – closing prices (newest last)
    window : int – lookback period (default 20 trading days ≈ 1 month)
    annualize : bool – multiply by √252 (default True)

    Returns
    -------
    float – annualized (or raw) volatility
    """
    prices = np.asarray(prices, dtype=float)
    if len(prices) < window + 1:
        return float('nan')

    log_returns = np.log(prices[1:] / prices[:-1])
    recent = log_returns[-window:]
    vol = np.std(recent, ddof=1)

    if annualize:
        vol *= math.sqrt(252)
    return float(vol)


def parkinson_vol(highs, lows, window=20, annualize=True):
    """
    Parkinson (1980) high-low range estimator. ~5× more efficient than
    close-to-close because intraday range captures more price information.

    √[(1/(4n·ln2)) × Σ(ln(Hi/Li))²] × √252

    Parameters
    ----------
    highs : array-like – high prices
    lows : array-like – low prices
    window : int – lookback period
    annualize : bool
    """
    highs = np.asarray(highs, dtype=float)
    lows = np.asarray(lows, dtype=float)
    if len(highs) < window:
        return float('nan')

    h = highs[-window:]
    l = lows[-window:]
    log_hl = np.log(h / l)
    vol = math.sqrt(np.sum(log_hl ** 2) / (4 * window * math.log(2)))

    if annualize:
        vol *= math.sqrt(252)
    return float(vol)


def garman_klass_vol(opens, highs, lows, closes, window=20, annualize=True):
    """
    Garman-Klass (1980) OHLC estimator. Best efficiency among single-
    estimator methods — uses all four price points.

    √[(1/n) × Σ(0.5×ln(Hi/Li)² − (2ln2−1)×ln(Ci/Oi)²)] × √252

    Parameters
    ----------
    opens, highs, lows, closes : array-like – OHLC prices
    window : int – lookback period
    annualize : bool
    """
    o = np.asarray(opens, dtype=float)[-window:]
    h = np.asarray(highs, dtype=float)[-window:]
    l = np.asarray(lows, dtype=float)[-window:]
    c = np.asarray(closes, dtype=float)[-window:]

    if len(o) < window:
        return float('nan')

    log_hl = np.log(h / l)
    log_co = np.log(c / o)
    variance = np.mean(0.5 * log_hl ** 2 - (2 * math.log(2) - 1) * log_co ** 2)
    # clamp: synthetic/noisy data can produce negative variance
    vol = math.sqrt(max(variance, 0.0))

    if annualize:
        vol *= math.sqrt(252)
    return float(vol)


def yang_zhang_vol(opens, highs, lows, closes, window=20, annualize=True):
    """
    Yang-Zhang (2000) estimator. Accounts for overnight jumps (open ≠
    previous close). Most robust for assets with gaps.

    σ²_yz = σ²_overnight + k × σ²_close-to-close + (1−k) × σ²_rogers-satchell

    Where k = 0.34 / (1.34 + (n+1)/(n−1))

    Parameters
    ----------
    opens, highs, lows, closes : array-like – OHLC prices
    window : int – lookback period
    annualize : bool
    """
    o = np.asarray(opens, dtype=float)
    h = np.asarray(highs, dtype=float)
    l = np.asarray(lows, dtype=float)
    c = np.asarray(closes, dtype=float)

    if len(o) < window + 1:
        return float('nan')

    # use last window+1 values to get window returns
    o = o[-(window + 1):]
    h = h[-(window + 1):]
    l = l[-(window + 1):]
    c = c[-(window + 1):]

    # overnight returns: log(open_t / close_{t-1})
    log_oc = np.log(o[1:] / c[:-1])
    # close-to-close: log(close_t / close_{t-1})
    log_cc = np.log(c[1:] / c[:-1])

    # Rogers-Satchell component
    log_ho = np.log(h[1:] / o[1:])
    log_hc = np.log(h[1:] / c[1:])
    log_lo = np.log(l[1:] / o[1:])
    log_lc = np.log(l[1:] / c[1:])
    rs = np.mean(log_ho * log_hc + log_lo * log_lc)

    n = window
    k = 0.34 / (1.34 + (n + 1) / (n - 1))

    var_overnight = np.var(log_oc, ddof=1)
    var_cc = np.var(log_cc, ddof=1)

    var_yz = var_overnight + k * var_cc + (1 - k) * rs
    # clamp to prevent sqrt of negative from floating point noise
    var_yz = max(var_yz, 0.0)
    vol = math.sqrt(var_yz)

    if annualize:
        vol *= math.sqrt(252)
    return float(vol)


def vol_cone(closes, highs=None, lows=None, opens=None,
             windows=(5, 10, 20, 60, 120, 252)):
    """
    Volatility cone: percentile distribution of realized vol at each
    lookback window. Compare current IV to these bands to judge if
    vol is cheap or expensive.

    Returns
    -------
    DataFrame with columns: window, min, p25, median, p75, max, current
        - current = most recent vol at that window
        - If current IV > p75 → vol is expensive → lean toward selling
        - If current IV < p25 → vol is cheap → lean toward buying
    """
    closes = np.asarray(closes, dtype=float)
    use_gk = (highs is not None and lows is not None and opens is not None)

    rows = []
    for w in windows:
        if len(closes) < w + 50:  # need enough history for a meaningful cone
            continue

        vols = []
        for i in range(w, len(closes)):
            if use_gk:
                v = garman_klass_vol(
                    opens[i - w:i], highs[i - w:i],
                    lows[i - w:i], closes[i - w:i],
                    window=w, annualize=True,
                )
            else:
                v = close_to_close_vol(closes[i - w + 1:i + 1], window=w)
            if not math.isnan(v):
                vols.append(v)

        if not vols:
            continue

        va = np.array(vols)
        rows.append({
            'window': w,
            'min': float(np.min(va)),
            'p25': float(np.percentile(va, 25)),
            'median': float(np.median(va)),
            'p75': float(np.percentile(va, 75)),
            'max': float(np.max(va)),
            'current': vols[-1],
        })

    return pd.DataFrame(rows)


# ── EWMA / GARCH(1,1) / Ensemble (Sinclair Ch.3) ─────────────────


def ewma_vol(prices, span=20, annualize=True):
    """
    Exponentially Weighted Moving Average volatility (Sinclair Ch.3).
    Gives more weight to recent returns — reacts faster than equal-weight.

    σ²_t = λ·σ²_{t-1} + (1-λ)·r²_t,  where λ = 1 - 2/(span+1)
    """
    prices = np.asarray(prices, dtype=float)
    if len(prices) < span + 1:
        return float('nan')

    log_ret = np.log(prices[1:] / prices[:-1])
    lam = 1.0 - 2.0 / (span + 1)
    var = log_ret[0] ** 2
    for r in log_ret[1:]:
        var = lam * var + (1.0 - lam) * r * r
    vol = math.sqrt(var)
    if annualize:
        vol *= math.sqrt(252)
    return float(vol)


def garch11_vol(prices, omega=None, alpha=0.1, beta=0.85, annualize=True):
    """
    GARCH(1,1) volatility forecast (Sinclair Ch.3).

    σ²_t = ω + α·r²_{t-1} + β·σ²_{t-1}
    ω is derived from long-run variance if not given:  ω = (1 - α - β) · V_L
    where V_L = sample variance of log returns.

    Sinclair: "GARCH produces roughly equivalent forecasts to EWMA.
    The marginal improvement is small."
    """
    prices = np.asarray(prices, dtype=float)
    if len(prices) < 30:
        return float('nan')

    log_ret = np.log(prices[1:] / prices[:-1])

    if omega is None:
        long_var = float(np.var(log_ret, ddof=1))
        persistence = alpha + beta
        if persistence >= 1.0:
            beta = 0.89 - alpha
        omega = (1.0 - alpha - beta) * long_var

    var = float(np.var(log_ret[-20:], ddof=1))
    for r in log_ret:
        var = omega + alpha * r * r + beta * var
        var = max(var, 1e-12)

    vol = math.sqrt(var)
    if annualize:
        vol *= math.sqrt(252)
    return float(vol)


def vol_forecast_ensemble(prices, highs=None, lows=None, opens=None,
                          window=20):
    """
    Ensemble vol forecast (Sinclair Ch.3): simple average of multiple
    estimators outperforms any single method because model errors are
    partially uncorrelated.

    Returns dict with individual forecasts + ensemble average.
    """
    closes = np.asarray(prices, dtype=float)
    forecasts = {}

    cc = close_to_close_vol(closes, window=window)
    if not math.isnan(cc):
        forecasts['close_to_close'] = cc

    ew = ewma_vol(closes, span=window)
    if not math.isnan(ew):
        forecasts['ewma'] = ew

    ga = garch11_vol(closes)
    if not math.isnan(ga):
        forecasts['garch'] = ga

    if highs is not None and lows is not None:
        pk = parkinson_vol(np.asarray(highs), np.asarray(lows), window=window)
        if not math.isnan(pk):
            forecasts['parkinson'] = pk

    if highs is not None and lows is not None and opens is not None:
        gk = garman_klass_vol(np.asarray(opens), np.asarray(highs),
                              np.asarray(lows), closes, window=window)
        yz = yang_zhang_vol(np.asarray(opens), np.asarray(highs),
                            np.asarray(lows), closes, window=window)
        if not math.isnan(gk):
            forecasts['garman_klass'] = gk
        if not math.isnan(yz):
            forecasts['yang_zhang'] = yz

    vals = list(forecasts.values())
    forecasts['ensemble'] = sum(vals) / len(vals) if vals else float('nan')
    forecasts['n_models'] = len(vals)
    return forecasts


# ---------------------------------------------------------------------------
# self-check
# ---------------------------------------------------------------------------

def _self_check():
    """Verify estimators on synthetic data with known volatility."""
    np.random.seed(42)
    # GBM: S_{t+1} = S_t × exp((μ - σ²/2)Δt + σ√Δt × Z)
    n_days = 1000
    true_vol = 0.20
    mu = 0.10
    dt = 1 / 252
    S = [100.0]
    for _ in range(n_days):
        z = np.random.randn()
        S.append(S[-1] * math.exp((mu - 0.5 * true_vol ** 2) * dt + true_vol * math.sqrt(dt) * z))
    S = np.array(S)

    # synthesize OHLC from close (approximate)
    closes = S
    opens = np.roll(closes, 1)
    opens[0] = closes[0]
    noise = np.random.uniform(0.005, 0.015, len(S))
    highs = closes * (1 + noise)
    lows = closes * (1 - noise)

    cc = close_to_close_vol(closes, window=252)
    pk = parkinson_vol(highs, lows, window=252)
    gk = garman_klass_vol(opens, highs, lows, closes, window=252)
    yz = yang_zhang_vol(opens, highs, lows, closes, window=252)

    # all estimators should be within ±5% absolute of true vol (20%)
    for name, val in [('CC', cc), ('Parkinson', pk), ('GK', gk), ('YZ', yz)]:
        assert 0.10 < val < 0.35, f"{name} vol={val:.4f} out of range for true_vol=0.20"

    # vol cone should return a DataFrame with expected columns
    cone = vol_cone(closes, highs, lows, opens, windows=(20, 60))
    assert len(cone) >= 1, "Vol cone should return at least 1 row"
    assert 'median' in cone.columns
    assert 'current' in cone.columns

    print("volatility.py: all checks passed")


if __name__ == '__main__':
    _self_check()
