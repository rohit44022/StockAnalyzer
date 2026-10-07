"""
Black-Scholes-Merton pricing and Greeks for European options.

All NSE options are European (index: cash-settled, stock: physically settled
since 2019). BSM handles ~93% of industry pricing (Sinclair App.1).

Conventions:
    S  = spot price of underlying
    K  = strike price
    t  = time to expiry in YEARS (e.g. 30 days = 30/365)
    r  = annualized risk-free rate (RBI 91-day T-bill, ~7% as of 2026)
    sigma = annualized volatility (decimal, e.g. 0.20 = 20%)
    q  = continuous dividend yield (0 for index options)
"""

import math
from scipy.stats import norm


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _d1(S, K, t, r, sigma, q=0.0):
    return (math.log(S / K) + (r - q + 0.5 * sigma ** 2) * t) / (sigma * math.sqrt(t))


def _d2(S, K, t, r, sigma, q=0.0):  # used by iv.py and external callers
    return _d1(S, K, t, r, sigma, q) - sigma * math.sqrt(t)


# ---------------------------------------------------------------------------
# pricing
# ---------------------------------------------------------------------------

def bsm_price(S, K, t, r, sigma, option_type='CE', q=0.0):
    """
    Black-Scholes-Merton price for a European option.

    Parameters
    ----------
    S : float – spot price
    K : float – strike price
    t : float – time to expiry in years (must be > 0)
    r : float – risk-free rate (annualized, decimal)
    sigma : float – volatility (annualized, decimal, must be > 0)
    option_type : str – 'CE' (call) or 'PE' (put)
    q : float – continuous dividend yield (default 0)

    Returns
    -------
    float – option premium
    """
    if t <= 0:
        # at expiry: intrinsic value only
        if option_type == 'CE':
            return max(S - K, 0.0)
        return max(K - S, 0.0)
    if sigma <= 0:
        raise ValueError("sigma must be > 0")

    d1 = _d1(S, K, t, r, sigma, q)
    d2 = d1 - sigma * math.sqrt(t)

    if option_type == 'CE':
        return S * math.exp(-q * t) * norm.cdf(d1) - K * math.exp(-r * t) * norm.cdf(d2)
    elif option_type == 'PE':
        return K * math.exp(-r * t) * norm.cdf(-d2) - S * math.exp(-q * t) * norm.cdf(-d1)
    else:
        raise ValueError(f"option_type must be 'CE' or 'PE', got '{option_type}'")


# ---------------------------------------------------------------------------
# Greeks
# ---------------------------------------------------------------------------

def bsm_greeks(S, K, t, r, sigma, option_type='CE', q=0.0):
    """
    All Greeks for a European option.

    Returns
    -------
    dict with keys:
        price   – BSM theoretical price
        delta   – price change per ₹1 move in underlying
        gamma   – delta change per ₹1 move in underlying
        theta   – price decay per calendar day (negative for long options)
        vega    – price change per 1% (absolute) change in IV
        rho     – price change per 1% change in interest rate
        charm   – delta decay per calendar day (DdeltaDtime)
        vanna   – delta change per 1% IV change (DdeltaDvol)
        vomma   – vega change per 1% IV change (DvegaDvol)
    """
    if t <= 0:
        price = max(S - K, 0.0) if option_type == 'CE' else max(K - S, 0.0)
        itm = (S > K) if option_type == 'CE' else (K > S)
        return {
            'price': price,
            'delta': (1.0 if itm else 0.0) * (1 if option_type == 'CE' else -1),
            'gamma': 0.0, 'theta': 0.0, 'vega': 0.0, 'rho': 0.0,
            'charm': 0.0, 'vanna': 0.0, 'vomma': 0.0,
        }

    d1 = _d1(S, K, t, r, sigma, q)
    d2 = d1 - sigma * math.sqrt(t)
    sqrt_t = math.sqrt(t)
    exp_qt = math.exp(-q * t)
    exp_rt = math.exp(-r * t)
    n_d1 = norm.pdf(d1)  # standard normal PDF at d1

    # --- price ---
    if option_type == 'CE':
        price = S * exp_qt * norm.cdf(d1) - K * exp_rt * norm.cdf(d2)
    else:
        price = K * exp_rt * norm.cdf(-d2) - S * exp_qt * norm.cdf(-d1)

    # --- delta ---
    if option_type == 'CE':
        delta = exp_qt * norm.cdf(d1)
    else:
        delta = -exp_qt * norm.cdf(-d1)

    # --- gamma (same for call and put) ---
    gamma = exp_qt * n_d1 / (S * sigma * sqrt_t)

    # --- theta (per calendar day) ---
    # Natenberg: theta = -(S·σ·n(d1))/(2√t) - r·K·e^(-rt)·N(±d2) + q·S·e^(-qt)·N(±d1)
    term1 = -(S * exp_qt * n_d1 * sigma) / (2 * sqrt_t)
    if option_type == 'CE':
        theta = term1 - r * K * exp_rt * norm.cdf(d2) + q * S * exp_qt * norm.cdf(d1)
    else:
        theta = term1 + r * K * exp_rt * norm.cdf(-d2) - q * S * exp_qt * norm.cdf(-d1)
    theta /= 365  # convert annual theta to per-calendar-day

    # --- vega (per 1% absolute IV change = 0.01 in sigma) ---
    vega = S * exp_qt * n_d1 * sqrt_t / 100

    # --- rho (per 1% change in r = 0.01 in r) ---
    if option_type == 'CE':
        rho = K * t * exp_rt * norm.cdf(d2) / 100
    else:
        rho = -K * t * exp_rt * norm.cdf(-d2) / 100

    # --- charm: DdeltaDtime (per calendar day) ---
    # charm = -e^(-qt) · [n(d1) · (2(r-q)t - d2·σ·√t) / (2·t·σ·√t) + q·N(±d1)]
    charm_base = n_d1 * (2 * (r - q) * t - d2 * sigma * sqrt_t) / (2 * t * sigma * sqrt_t)
    if option_type == 'CE':
        charm = -exp_qt * (charm_base + q * norm.cdf(d1))
    else:
        charm = -exp_qt * (charm_base - q * norm.cdf(-d1))
    charm /= 365  # per calendar day

    # --- vanna: DdeltaDvol (per 1% IV change) ---
    # vanna = -e^(-qt) · n(d1) · d2 / σ
    vanna = -exp_qt * n_d1 * d2 / sigma / 100

    # --- vomma: DvegaDvol (per 1% IV change) ---
    # vomma = vega · d1 · d2 / σ
    vomma = (vega * d1 * d2) / sigma / 100

    return {
        'price': price,
        'delta': delta,
        'gamma': gamma,
        'theta': theta,
        'vega': vega,
        'rho': rho,
        'charm': charm,
        'vanna': vanna,
        'vomma': vomma,
    }


# ---------------------------------------------------------------------------
# put-call parity (Natenberg Ch.15)
# ---------------------------------------------------------------------------

def put_call_parity(S, K, t, r, q=0.0, call_price=None, put_price=None):
    """
    Put-call parity: C - P = S·e^(-qt) - K·e^(-rt)

    Given one of call_price or put_price, returns the other.
    Given both, returns the parity violation (should be ~0 for fair prices).
    """
    forward_diff = S * math.exp(-q * t) - K * math.exp(-r * t)

    if call_price is not None and put_price is not None:
        return (call_price - put_price) - forward_diff
    elif call_price is not None:
        return call_price - forward_diff
    elif put_price is not None:
        return put_price + forward_diff
    else:
        raise ValueError("provide at least one of call_price or put_price")


# ---------------------------------------------------------------------------
# self-check
# ---------------------------------------------------------------------------

def _self_check():
    """Verify BSM against known analytical values."""
    # Standard test: S=100, K=100, t=1yr, r=5%, σ=20%, no dividends
    c = bsm_price(100, 100, 1.0, 0.05, 0.20, 'CE')
    p = bsm_price(100, 100, 1.0, 0.05, 0.20, 'PE')
    # Known values: C ≈ 10.4506, P ≈ 5.5735
    assert abs(c - 10.4506) < 0.01, f"Call price wrong: {c}"
    assert abs(p - 5.5735) < 0.01, f"Put price wrong: {p}"

    # Put-call parity: C - P = S - K·e^(-rt)
    parity = put_call_parity(100, 100, 1.0, 0.05, 0.0, c, p)
    assert abs(parity) < 1e-10, f"Put-call parity violated: {parity}"

    # Greeks sanity
    g = bsm_greeks(100, 100, 1.0, 0.05, 0.20, 'CE')
    assert 0.5 < g['delta'] < 0.7, f"ATM call delta should be ~0.6, got {g['delta']}"
    assert g['gamma'] > 0, "Gamma must be positive"
    assert g['theta'] < 0, "Long call theta must be negative"
    assert g['vega'] > 0, "Vega must be positive"

    # At-expiry returns intrinsic
    assert bsm_price(110, 100, 0, 0.05, 0.20, 'CE') == 10.0
    assert bsm_price(90, 100, 0, 0.05, 0.20, 'PE') == 10.0
    assert bsm_price(90, 100, 0, 0.05, 0.20, 'CE') == 0.0

    print("bsm.py: all checks passed")


if __name__ == '__main__':
    _self_check()
