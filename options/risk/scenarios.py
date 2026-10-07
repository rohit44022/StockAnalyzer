"""
Catastrophe scenario analysis.

Sinclair Ch.8: before entering ANY position, compute P/L under stress.
3D grid: spot_change × iv_change × time_elapsed.
Rule: if worst-case > 2× expected theta income, don't enter.

Indian market stress references:
  2008: -60%, 2020 March: -38%, VIX max ~90 (March 2020), min ~9
  BankNifty: higher beta, multiply Nifty stress by 1.3-1.5×
"""

from ..core import bsm

# Standard scenario grid
SPOT_CHANGES = [-0.30, -0.20, -0.10, -0.05, 0.0, 0.05, 0.10, 0.20, 0.30]
IV_CHANGES = [-0.50, -0.25, 0.0, 0.25, 0.50, 1.00]
DAYS_ELAPSED = [0, 7, 14, 21, 28]

# Named stress events
STRESS_PRESETS = {
    '2008_crash':    {'spot_change': -0.60, 'iv_mult': 4.0},
    '2020_covid':    {'spot_change': -0.38, 'iv_mult': 3.5},
    '2024_election': {'spot_change': -0.08, 'iv_mult': 1.8},
    'flash_crash':   {'spot_change': -0.15, 'iv_mult': 2.5},
    'rally':         {'spot_change': 0.15,  'iv_mult': 0.6},
}


def scenario_table(legs, spot, r=0.07, lot_size=65,
                   spot_changes=None, iv_changes=None, days_list=None):
    """
    Build 3D P/L grid across spot, IV, and time scenarios.

    Parameters
    ----------
    legs : list of dicts — strike, option_type, action, premium, iv, expiry_years, qty
    spot : float
    lot_size : int

    Returns
    -------
    dict: grid (list of scenario dicts), worst_case, best_case, summary
    """
    sc = spot_changes or SPOT_CHANGES
    ic = iv_changes or IV_CHANGES
    dl = days_list or DAYS_ELAPSED

    grid = []
    worst = {'pnl_per_lot': float('inf')}
    best = {'pnl_per_lot': float('-inf')}

    for spot_pct in sc:
        for iv_pct in ic:
            for days in dl:
                new_spot = spot * (1.0 + spot_pct)
                pnl = _scenario_pnl(legs, new_spot, spot, iv_pct, days, r)
                pnl_lot = pnl * lot_size

                row = {
                    'spot_change': spot_pct,
                    'iv_change': iv_pct,
                    'days_elapsed': days,
                    'new_spot': round(new_spot, 2),
                    'pnl_per_unit': round(pnl, 2),
                    'pnl_per_lot': round(pnl_lot, 2),
                }
                grid.append(row)

                if pnl_lot < worst['pnl_per_lot']:
                    worst = row.copy()
                if pnl_lot > best['pnl_per_lot']:
                    best = row.copy()

    return {
        'grid': grid,
        'worst_case': worst,
        'best_case': best,
        'scenarios_computed': len(grid),
    }


def stress_test(legs, spot, stress_type='2020_covid', r=0.07, lot_size=65):
    """
    Named stress scenario P/L.

    Returns
    -------
    dict: stress_type, spot_change, new_spot, iv_mult, pnl_per_lot, passes_rule
    """
    preset = STRESS_PRESETS.get(stress_type)
    if preset is None:
        return {'error': f'Unknown stress type: {stress_type}'}

    new_spot = spot * (1.0 + preset['spot_change'])
    # IV multiplied (not additive) — VIX can 3-4× in a crash
    iv_mult = preset['iv_mult']

    pnl = 0.0
    for leg in legs:
        t = max(leg.get('expiry_years', 0.01), 1 / 365)
        base_iv = max(leg.get('iv', 0.15), 0.01)
        stressed_iv = min(base_iv * iv_mult, 2.0)  # cap at 200% IV
        entry = leg.get('premium', 0)
        qty = leg.get('qty', 1)

        current = bsm.bsm_price(new_spot, leg['strike'], t, r,
                                 stressed_iv, leg['option_type'])
        if leg.get('action') == 'SELL':
            pnl += (entry - current) * qty
        else:
            pnl += (current - entry) * qty

    pnl_lot = pnl * lot_size

    return {
        'stress_type': stress_type,
        'spot_change': preset['spot_change'],
        'new_spot': round(new_spot, 2),
        'iv_mult': iv_mult,
        'pnl_per_unit': round(pnl, 2),
        'pnl_per_lot': round(pnl_lot, 2),
    }


def entry_gate(legs, spot, daily_theta, r=0.07, lot_size=65, dte=None):
    """
    Sinclair Ch.8: if worst-case loss > 2× expected theta income, don't enter.

    Parameters
    ----------
    daily_theta : float — expected daily theta income per lot (positive)
    dte : int — days to expiry; theta income = daily_theta × dte.
              If None, inferred from legs' expiry_years.

    Returns
    -------
    dict: worst_pnl, theta_income, horizon_days, ratio, passes, reason
    """
    if dte is None:
        exp_years = [l.get('expiry_years', 0) for l in legs if l.get('expiry_years')]
        dte = int(min(exp_years) * 365) if exp_years else 14

    table = scenario_table(legs, spot, r, lot_size)
    worst_pnl = table['worst_case']['pnl_per_lot']
    theta_income = daily_theta * dte

    if theta_income <= 0:
        return {
            'worst_pnl': worst_pnl,
            'theta_income': theta_income,
            'horizon_days': dte,
            'ratio': float('inf'),
            'passes': False,
            'reason': 'Non-positive theta — not a premium-selling position',
        }

    ratio = abs(worst_pnl) / theta_income

    return {
        'worst_pnl': round(worst_pnl, 2),
        'theta_income': round(theta_income, 2),
        'horizon_days': dte,
        'ratio': round(ratio, 2),
        'passes': ratio <= 2.0,
        'reason': ('OK — worst case within 2× theta'
                   if ratio <= 2.0
                   else f'REJECT — worst case is {ratio:.1f}× theta income'),
    }


def _scenario_pnl(legs, new_spot, entry_spot, iv_change_pct, days_elapsed, r):
    """Compute P/L for one scenario point."""
    pnl = 0.0
    for leg in legs:
        t_orig = max(leg.get('expiry_years', 0.01), 1 / 365)
        t_new = max(t_orig - days_elapsed / 365, 1 / 365)
        base_iv = max(leg.get('iv', 0.15), 0.01)
        new_iv = max(base_iv * (1.0 + iv_change_pct), 0.01)
        new_iv = min(new_iv, 2.0)
        entry = leg.get('premium', 0)
        qty = leg.get('qty', 1)

        current = bsm.bsm_price(new_spot, leg['strike'], t_new, r,
                                 new_iv, leg['option_type'])
        if leg.get('action') == 'SELL':
            pnl += (entry - current) * qty
        else:
            pnl += (current - entry) * qty

    return pnl


def _self_check():
    legs = [
        {'strike': 23800, 'option_type': 'PE', 'action': 'BUY',
         'premium': 30, 'iv': 0.16, 'expiry_years': 14 / 365, 'qty': 1},
        {'strike': 23900, 'option_type': 'PE', 'action': 'SELL',
         'premium': 50, 'iv': 0.15, 'expiry_years': 14 / 365, 'qty': 1},
        {'strike': 24100, 'option_type': 'CE', 'action': 'SELL',
         'premium': 50, 'iv': 0.14, 'expiry_years': 14 / 365, 'qty': 1},
        {'strike': 24200, 'option_type': 'CE', 'action': 'BUY',
         'premium': 25, 'iv': 0.15, 'expiry_years': 14 / 365, 'qty': 1},
    ]

    table = scenario_table(legs, 24000, lot_size=65)
    assert table['scenarios_computed'] == len(SPOT_CHANGES) * len(IV_CHANGES) * len(DAYS_ELAPSED)
    assert table['worst_case']['pnl_per_lot'] < 0
    assert table['best_case']['pnl_per_lot'] > 0

    st = stress_test(legs, 24000, '2020_covid', lot_size=65)
    assert st['pnl_per_lot'] < 0, "Iron condor should lose in a crash"
    assert st['new_spot'] < 24000

    st2 = stress_test(legs, 24000, 'rally', lot_size=65)
    assert 'error' not in st2

    gate = entry_gate(legs, 24000, daily_theta=5.0, lot_size=65)
    assert 'passes' in gate
    assert 'ratio' in gate

    print("scenarios.py: all checks passed")


if __name__ == '__main__':
    _self_check()
