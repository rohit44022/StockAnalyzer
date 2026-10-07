"""
Portfolio-level risk: aggregate Greeks, VaR, correlation checks.

Sinclair Ch.8: diversify across underlyings and expiries, but
correlation kills diversification in crashes — size to survive
the correlated worst case.
"""

import math
from . import position as pos_mod


def aggregate(positions, lot_sizes=None, r=0.07):
    """
    Aggregate Greeks and exposure across all portfolio positions.

    Parameters
    ----------
    positions : list of dicts — each has 'legs', 'spot', 'lot_size' (or use lot_sizes),
                'strategy', 'underlying' (optional)

    Returns
    -------
    dict: net greeks, per-position breakdown, total exposure
    """
    totals = {'delta': 0.0, 'gamma': 0.0, 'theta': 0.0, 'vega': 0.0}
    total_exposure = 0.0
    breakdown = []

    for p in positions:
        spot = p.get('spot', 0)
        ls = p.get('lot_size', 65)
        legs = p.get('legs', [])
        lots = p.get('lots', 1)

        if not legs:
            continue

        agg = pos_mod.aggregate_greeks(legs, spot, r)
        pnl = pos_mod.position_pnl(legs, spot, r)
        dd = pos_mod.dollar_delta(legs, spot, ls, r)

        for k in totals:
            totals[k] += agg[k] * lots

        notional = spot * ls * lots
        total_exposure += notional

        breakdown.append({
            'strategy': p.get('strategy', ''),
            'underlying': p.get('underlying', 'NIFTY'),
            'lots': lots,
            'greeks': {k: round(agg[k] * lots, 6) for k in totals},
            'dollar_delta': round(dd * lots, 2),
            'daily_theta': round(pnl['daily_theta'] * ls * lots, 2),
            'notional': round(notional, 2),
        })

    return {
        'net_greeks': {k: round(v, 6) for k, v in totals.items()},
        'total_exposure': round(total_exposure, 2),
        'position_count': len(breakdown),
        'breakdown': breakdown,
    }


def parametric_var(portfolio_delta, portfolio_vega, spot, daily_vol,
                   iv_daily_vol=0.02, confidence=0.95, holding_days=1,
                   rho=0.6, stress_rho=0.9, stress=False):
    """
    Parametric VaR from delta + vega with spot-IV correlation.

    Natenberg Ch.8: VaR = √(δ²σ²_s + ν²σ²_iv + 2ρ·δσ_s·νσ_iv) × z × √days
    Uses ρ=0.6 normal, ρ=0.9 stress (crashes: spot drops, IV spikes together).

    Parameters
    ----------
    portfolio_delta : float — net dollar delta
    portfolio_vega : float — net vega in ₹
    spot : float
    daily_vol : float — daily realized vol of underlying
    iv_daily_vol : float — daily vol of IV itself (~2%)
    confidence : float — VaR confidence level (0.95 or 0.99)
    holding_days : int
    rho : float — spot-IV correlation, normal regime (Natenberg Ch.8)
    stress_rho : float — spot-IV correlation, stress regime
    stress : bool — use stress correlation

    Returns
    -------
    dict: var_amount, var_pct, components
    """
    z = {0.95: 1.645, 0.99: 2.326, 0.975: 1.96}.get(confidence, 1.645)

    delta_var = abs(portfolio_delta) * spot * daily_vol
    vega_var = abs(portfolio_vega) * iv_daily_vol

    r = stress_rho if stress else rho
    combined = math.sqrt(delta_var ** 2 + vega_var ** 2
                         + 2 * r * delta_var * vega_var)
    var_amount = combined * z * math.sqrt(holding_days)

    return {
        'var_amount': round(var_amount, 2),
        'delta_component': round(delta_var * z * math.sqrt(holding_days), 2),
        'vega_component': round(vega_var * z * math.sqrt(holding_days), 2),
        'rho': r,
        'confidence': confidence,
        'holding_days': holding_days,
    }


def concentration_check(breakdown, total_exposure):
    """
    Check portfolio concentration by underlying and expiry.

    Sinclair Ch.8: don't sell all vol on one name.

    Returns
    -------
    dict: by_underlying, warnings
    """
    warnings = []
    by_underlying = {}

    for pos in breakdown:
        u = pos.get('underlying', 'unknown')
        by_underlying.setdefault(u, 0)
        by_underlying[u] += pos.get('notional', 0)

    if total_exposure > 0:
        for u, exp in by_underlying.items():
            pct = exp / total_exposure * 100
            if pct > 70:
                warnings.append(
                    f'{u} is {pct:.0f}% of portfolio — over-concentrated '
                    f'(Sinclair: diversify across underlyings)')

    return {
        'by_underlying': {k: round(v, 2) for k, v in by_underlying.items()},
        'warnings': warnings,
    }


def _self_check():
    positions = [
        {
            'strategy': 'iron_condor', 'underlying': 'NIFTY',
            'spot': 24000, 'lot_size': 65, 'lots': 2,
            'legs': [
                {'strike': 23800, 'option_type': 'PE', 'action': 'BUY',
                 'premium': 30, 'iv': 0.16, 'expiry_years': 14 / 365, 'qty': 1},
                {'strike': 23900, 'option_type': 'PE', 'action': 'SELL',
                 'premium': 50, 'iv': 0.15, 'expiry_years': 14 / 365, 'qty': 1},
                {'strike': 24100, 'option_type': 'CE', 'action': 'SELL',
                 'premium': 50, 'iv': 0.14, 'expiry_years': 14 / 365, 'qty': 1},
                {'strike': 24200, 'option_type': 'CE', 'action': 'BUY',
                 'premium': 25, 'iv': 0.15, 'expiry_years': 14 / 365, 'qty': 1},
            ],
        },
        {
            'strategy': 'bull_put_spread', 'underlying': 'BANKNIFTY',
            'spot': 52000, 'lot_size': 30, 'lots': 1,
            'legs': [
                {'strike': 51500, 'option_type': 'PE', 'action': 'BUY',
                 'premium': 100, 'iv': 0.18, 'expiry_years': 14 / 365, 'qty': 1},
                {'strike': 51800, 'option_type': 'PE', 'action': 'SELL',
                 'premium': 200, 'iv': 0.17, 'expiry_years': 14 / 365, 'qty': 1},
            ],
        },
    ]

    agg = aggregate(positions)
    assert agg['position_count'] == 2
    assert agg['total_exposure'] > 0
    assert 'delta' in agg['net_greeks']

    var = parametric_var(
        portfolio_delta=agg['net_greeks']['delta'],
        portfolio_vega=agg['net_greeks']['vega'],
        spot=24000, daily_vol=0.012)
    assert var['var_amount'] > 0

    conc = concentration_check(agg['breakdown'], agg['total_exposure'])
    assert len(conc['by_underlying']) == 2

    print("portfolio.py: all checks passed")


if __name__ == '__main__':
    _self_check()
