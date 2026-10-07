"""
Position-level Greeks aggregation and P/L attribution.

Greeks are additive across legs (Natenberg Ch.6-7).
Sign convention: SELL legs contribute negative of raw greek.
"""

from ..core import bsm


def aggregate_greeks(legs, spot, r=0.07):
    """
    Compute net Greeks for a multi-leg position.

    Parameters
    ----------
    legs : list of dicts — strike, option_type, action, qty, iv, expiry_years
    spot : float
    r : float

    Returns
    -------
    dict: delta, gamma, theta, vega, net_premium, leg_details
    """
    totals = {'delta': 0.0, 'gamma': 0.0, 'theta': 0.0, 'vega': 0.0}
    details = []

    for leg in legs:
        t = max(leg.get('expiry_years', 0.01), 1 / 365)
        iv = max(leg.get('iv', 0.15), 0.01)
        g = bsm.bsm_greeks(spot, leg['strike'], t, r, iv, leg['option_type'])
        sign = -1 if leg.get('action') == 'SELL' else 1
        qty = leg.get('qty', 1)

        scaled = {k: g[k] * sign * qty for k in totals}
        for k in totals:
            totals[k] += scaled[k]

        details.append({**leg, 'greeks': g, 'sign': sign, 'scaled': scaled})

    return {**{k: round(v, 6) for k, v in totals.items()}, 'leg_details': details}


def position_pnl(legs, spot, r=0.07):
    """
    BSM-based mark-to-market P/L per unit (Sinclair Ch.9: actual P/L, not spot proxy).

    Returns
    -------
    dict: total_pnl, per_leg list, theta_pnl (estimated daily)
    """
    total = 0.0
    per_leg = []
    theta_total = 0.0

    for leg in legs:
        t = max(leg.get('expiry_years', 0.01), 1 / 365)
        iv = max(leg.get('iv', 0.15), 0.01)
        entry = leg.get('premium', 0)
        current = bsm.bsm_price(spot, leg['strike'], t, r, iv, leg['option_type'])
        g = bsm.bsm_greeks(spot, leg['strike'], t, r, iv, leg['option_type'])

        sign = -1 if leg.get('action') == 'SELL' else 1
        qty = leg.get('qty', 1)

        if leg.get('action') == 'SELL':
            leg_pnl = (entry - current) * qty
        else:
            leg_pnl = (current - entry) * qty

        total += leg_pnl
        theta_total += g['theta'] * sign * qty
        per_leg.append({
            'strike': leg['strike'], 'option_type': leg['option_type'],
            'action': leg.get('action'), 'entry': entry,
            'current': round(current, 4), 'pnl': round(leg_pnl, 4),
        })

    return {
        'total_pnl': round(total, 4),
        'per_leg': per_leg,
        'daily_theta': round(theta_total, 4),
    }


def dollar_delta(legs, spot, lot_size, r=0.07):
    """Net dollar delta = delta × spot × lot_size. For portfolio aggregation."""
    agg = aggregate_greeks(legs, spot, r)
    return round(agg['delta'] * spot * lot_size, 2)


def _self_check():
    legs = [
        {'strike': 24000, 'option_type': 'CE', 'action': 'SELL',
         'premium': 300, 'iv': 0.15, 'expiry_years': 14 / 365, 'qty': 1},
        {'strike': 24000, 'option_type': 'PE', 'action': 'SELL',
         'premium': 280, 'iv': 0.15, 'expiry_years': 14 / 365, 'qty': 1},
    ]
    agg = aggregate_greeks(legs, 24000)
    assert abs(agg['delta']) < 0.15, "Straddle should be near delta-neutral"
    assert agg['gamma'] < 0, "Short straddle = short gamma"
    assert agg['theta'] > 0, "Short straddle = positive theta"
    assert agg['vega'] < 0, "Short straddle = short vega"

    pnl = position_pnl(legs, 24000)
    assert pnl['daily_theta'] > 0

    dd = dollar_delta(legs, 24000, 65)
    # ~-0.08 × 24000 × 65 ≈ -130K — near neutral for a ₹15.6L notional
    assert abs(dd) < 250_000

    print("position.py: all checks passed")


if __name__ == '__main__':
    _self_check()
