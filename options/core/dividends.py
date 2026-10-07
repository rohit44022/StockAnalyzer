"""
Dividend-adjusted forward pricing for stock options.

NSE stock options are European (no early exercise), but dividends still
affect pricing because the forward price is:

    F = S × e^(rt) − FV(dividends)

Or equivalently with continuous yield:

    F = S × e^((r − q) × t)

NSE rules (Natenberg Ch.15, Varsity Ch.21):
    - Ordinary dividends: NO strike/lot adjustment (unlike some exchanges)
    - Extraordinary dividends: NSE adjusts both strike AND lot size
    - Ex-dividend date: option price drops by ~dividend amount
    - For index options: use continuous dividend yield (q)
    - For stock options: use discrete dividends when known
"""

import math
from datetime import date
from .bsm import bsm_price, bsm_greeks


def dividend_adjusted_forward(S, r, t, dividends=None, q=0.0):
    """
    Compute the forward price adjusted for dividends.

    Parameters
    ----------
    S : float – current spot price
    r : float – risk-free rate (annualized)
    t : float – time to expiry in years
    dividends : list of (ex_date_years_from_now, amount) or None
        Each tuple is (time until ex-date in years, dividend per share).
        Only dividends with ex-date before expiry affect pricing.
    q : float – continuous dividend yield (use instead of discrete for indices)

    Returns
    -------
    float – dividend-adjusted forward price

    Examples
    --------
    >>> # Stock at ₹2500, r=7%, 3 months to expiry, ₹10 dividend in 1 month
    >>> dividend_adjusted_forward(2500, 0.07, 0.25, [(0.083, 10)])
    2533.26...  # approximately
    """
    if dividends:
        # discrete dividends: F = S × e^(rt) − Σ(Di × e^(r×(t−ti)))
        pv_divs = sum(
            d_amount * math.exp(-r * d_time)
            for d_time, d_amount in dividends
            if 0 < d_time < t  # only future dividends before expiry
        )
        forward = (S - pv_divs) * math.exp(r * t)
    else:
        # continuous yield: F = S × e^((r−q)×t)
        forward = S * math.exp((r - q) * t)

    return forward


def bsm_price_with_dividends(S, K, t, r, sigma, option_type='CE',
                              dividends=None, q=0.0):
    """
    BSM price adjusted for known discrete dividends.

    Uses the standard approach: replace S with S − PV(dividends),
    then price normally. This is exact for European options.

    Parameters
    ----------
    S : float – spot price
    K : float – strike price
    t : float – time to expiry in years
    r : float – risk-free rate
    sigma : float – volatility
    option_type : str – 'CE' or 'PE'
    dividends : list of (ex_date_years_from_now, amount) or None
    q : float – continuous dividend yield (alternative to discrete)

    Returns
    -------
    float – dividend-adjusted option price
    """
    if dividends:
        pv_divs = sum(
            d_amount * math.exp(-r * d_time)
            for d_time, d_amount in dividends
            if 0 < d_time < t
        )
        S_adj = S - pv_divs
        return bsm_price(S_adj, K, t, r, sigma, option_type, q=0.0)
    else:
        return bsm_price(S, K, t, r, sigma, option_type, q)


def bsm_greeks_with_dividends(S, K, t, r, sigma, option_type='CE',
                               dividends=None, q=0.0):
    """
    All Greeks adjusted for known discrete dividends.
    Same approach: S → S − PV(dividends).
    """
    if dividends:
        pv_divs = sum(
            d_amount * math.exp(-r * d_time)
            for d_time, d_amount in dividends
            if 0 < d_time < t
        )
        S_adj = S - pv_divs
        return bsm_greeks(S_adj, K, t, r, sigma, option_type, q=0.0)
    else:
        return bsm_greeks(S, K, t, r, sigma, option_type, q)


def days_to_years(days):
    """Convert calendar days to year fraction (365-day basis for NSE)."""
    return days / 365


def ex_date_offset(ex_date, today=None):
    """
    Convert an ex-dividend date to years-from-now.

    Parameters
    ----------
    ex_date : date – the ex-dividend date
    today : date or None – reference date (default: today)

    Returns
    -------
    float – years from today to ex_date (negative if past)
    """
    if today is None:
        today = date.today()
    return (ex_date - today).days / 365


# ---------------------------------------------------------------------------
# self-check
# ---------------------------------------------------------------------------

def _self_check():
    """Verify dividend adjustment is mathematically correct."""
    # 1. No dividends: forward = S × e^(rt)
    f = dividend_adjusted_forward(100, 0.07, 1.0)
    assert abs(f - 100 * math.exp(0.07)) < 0.01

    # 2. With dividend: forward should be lower
    f_div = dividend_adjusted_forward(100, 0.07, 1.0, [(0.5, 5.0)])
    f_no = dividend_adjusted_forward(100, 0.07, 1.0)
    assert f_div < f_no, "Dividend should reduce forward price"

    # 3. Dividend-adjusted call should be cheaper than unadjusted
    c_no = bsm_price_with_dividends(100, 100, 1.0, 0.07, 0.20, 'CE')
    c_div = bsm_price_with_dividends(100, 100, 1.0, 0.07, 0.20, 'CE',
                                      dividends=[(0.25, 3.0)])
    assert c_div < c_no, "Dividend should reduce call price"

    # 4. Dividend-adjusted put should be more expensive than unadjusted
    p_no = bsm_price_with_dividends(100, 100, 1.0, 0.07, 0.20, 'PE')
    p_div = bsm_price_with_dividends(100, 100, 1.0, 0.07, 0.20, 'PE',
                                      dividends=[(0.25, 3.0)])
    assert p_div > p_no, "Dividend should increase put price"

    # 5. Continuous yield equivalent
    c_q = bsm_price_with_dividends(100, 100, 1.0, 0.07, 0.20, 'CE', q=0.02)
    c_no2 = bsm_price_with_dividends(100, 100, 1.0, 0.07, 0.20, 'CE', q=0.0)
    assert c_q < c_no2, "Dividend yield should reduce call price"

    # 6. Past dividends (ex-date already passed) should have no effect
    c_past = bsm_price_with_dividends(100, 100, 1.0, 0.07, 0.20, 'CE',
                                       dividends=[(-0.1, 5.0)])  # already past
    assert abs(c_past - c_no) < 0.001, "Past dividends should not affect price"

    print("dividends.py: all checks passed")


if __name__ == '__main__':
    _self_check()
