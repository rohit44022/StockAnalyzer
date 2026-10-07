"""
Implied Volatility solver using Newton-Raphson with bisection fallback.

IV is the volatility that makes BSM price = market price. It's the market's
consensus forecast of future realized volatility for that strike/expiry.

Newton-Raphson converges in 3-5 iterations for typical options. Bisection
is the fallback for edge cases (deep ITM/OTM, near-expiry).
"""

import math
from .bsm import bsm_price, bsm_greeks


def implied_vol(market_price, S, K, t, r, option_type='CE', q=0.0,
                tol=0.0001, max_iter=100):
    """
    Solve for implied volatility given a market price.

    Parameters
    ----------
    market_price : float – observed option price (must be > 0)
    S : float – spot price
    K : float – strike price
    t : float – time to expiry in years (must be > 0)
    r : float – risk-free rate
    option_type : str – 'CE' or 'PE'
    q : float – continuous dividend yield
    tol : float – convergence tolerance (0.01% = 1 basis point of vol)
    max_iter : int – maximum iterations

    Returns
    -------
    float – implied volatility (annualized, decimal), or NaN if no solution
    """
    if t <= 0 or market_price <= 0:
        return float('nan')

    # intrinsic value check: price must exceed intrinsic
    if option_type == 'CE':
        intrinsic = max(S * math.exp(-q * t) - K * math.exp(-r * t), 0)
    else:
        intrinsic = max(K * math.exp(-r * t) - S * math.exp(-q * t), 0)
    if market_price < intrinsic - 0.01:
        return float('nan')

    # upper bound check: price can't exceed S (call) or K·e^(-rt) (put)
    if option_type == 'CE' and market_price > S * math.exp(-q * t):
        return float('nan')
    if option_type == 'PE' and market_price > K * math.exp(-r * t):
        return float('nan')

    # initial guess: ATM approximation σ ≈ price × √(2π/t) / S
    # (Brenner-Subrahmanyam 1988)
    sigma = market_price * math.sqrt(2 * math.pi / t) / S
    sigma = max(0.01, min(sigma, 5.0))

    # Newton-Raphson: σ_{n+1} = σ_n - (BSM(σ_n) - market) / vega(σ_n)
    for _ in range(max_iter):
        g = bsm_greeks(S, K, t, r, sigma, option_type, q)
        price_diff = g['price'] - market_price

        if abs(price_diff) < tol * 0.01:  # tol is in vol terms, price tolerance
            return sigma

        # vega in greeks is per 1% IV change, need per 1.0 change
        vega_raw = g['vega'] * 100
        if vega_raw < 1e-12:
            break  # vega too small, Newton can't converge

        sigma -= price_diff / vega_raw
        sigma = max(0.001, min(sigma, 5.0))  # clamp to (0.1%, 500%)

    # fallback: bisection (slower but guaranteed to converge)
    lo, hi = 0.001, 5.0
    for _ in range(100):
        mid = (lo + hi) / 2
        mid_price = bsm_price(S, K, t, r, mid, option_type, q)
        if abs(mid_price - market_price) < tol * 0.01:
            return mid
        if mid_price > market_price:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-8:
            break

    return (lo + hi) / 2


def iv_chain(chain_df, S, t, r, q=0.0):
    """
    Compute IV for every row in an option chain DataFrame.

    Parameters
    ----------
    chain_df : DataFrame with columns: strike, option_type, ltp (or price)
    S : float – underlying spot price
    t : float – time to expiry in years
    r : float – risk-free rate
    q : float – continuous dividend yield

    Returns
    -------
    DataFrame – copy of input with 'iv' column added.
    Rows where IV can't be solved get NaN (e.g. bid=0, spread > 20% of mid).
    """
    import pandas as pd

    df = chain_df.copy()
    price_col = 'ltp' if 'ltp' in df.columns else 'price'

    ivs = []
    for _, row in df.iterrows():
        price = row[price_col]
        strike = row['strike']
        otype = row['option_type']

        if price <= 0 or pd.isna(price):
            ivs.append(float('nan'))
            continue

        # skip obviously bad data: bid-ask spread > 20% of mid
        if 'bid' in df.columns and 'ask' in df.columns:
            bid, ask = row.get('bid', 0), row.get('ask', 0)
            if bid > 0 and ask > 0:
                mid = (bid + ask) / 2
                if (ask - bid) / mid > 0.20:
                    ivs.append(float('nan'))
                    continue

        ivs.append(implied_vol(price, S, strike, t, r, otype, q))

    df['iv'] = ivs
    return df


# ---------------------------------------------------------------------------
# self-check
# ---------------------------------------------------------------------------

def _self_check():
    """Round-trip test: price → IV → price should match."""
    from .bsm import bsm_price as bp

    test_cases = [
        # (S, K, t, r, sigma, option_type)
        (100, 100, 1.0, 0.05, 0.20, 'CE'),  # ATM call
        (100, 100, 1.0, 0.05, 0.20, 'PE'),  # ATM put
        (100, 110, 0.5, 0.07, 0.30, 'CE'),  # OTM call
        (100, 90, 0.25, 0.07, 0.25, 'PE'),  # OTM put
        (24000, 24000, 30/365, 0.07, 0.14, 'CE'),  # Nifty ATM (realistic)
        (24000, 24500, 7/365, 0.07, 0.16, 'PE'),  # Nifty weekly OTM put
    ]

    for S, K, t, r, sigma, otype in test_cases:
        price = bp(S, K, t, r, sigma, otype)
        recovered = implied_vol(price, S, K, t, r, otype)
        assert abs(recovered - sigma) < 0.001, (
            f"IV round-trip failed: σ={sigma}, recovered={recovered:.6f} "
            f"for S={S}, K={K}, t={t:.4f}, {otype}"
        )

    # edge case: at-expiry returns NaN
    result = implied_vol(5.0, 100, 95, 0, 0.05, 'CE')
    assert math.isnan(result), "At-expiry IV should be NaN"

    # edge case: zero price returns NaN
    result = implied_vol(0, 100, 100, 1.0, 0.05, 'CE')
    assert math.isnan(result), "Zero-price IV should be NaN"

    print("iv.py: all checks passed")


if __name__ == '__main__':
    _self_check()
