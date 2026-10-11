"""
Catastrophe scenario analysis.

Sinclair Ch.8: before entering ANY position, compute P/L under stress.
3D grid: spot_change × iv_change × time_elapsed.
Rule: if worst-case > 2× expected theta income, don't enter.

Indian market stress references:
  2008: -60%, 2020 March: -38%, VIX max ~90 (March 2020), min ~9
  BankNifty: higher beta, multiply Nifty stress by 1.3-1.5×
"""

import math
from ..core import bsm

# Standard scenario grid
SPOT_CHANGES = [-0.30, -0.20, -0.10, -0.05, 0.0, 0.05, 0.10, 0.20, 0.30]
IV_CHANGES = [-0.50, -0.25, 0.0, 0.25, 0.50, 1.00]
DAYS_ELAPSED = [0, 7, 14, 21, 28]

# T1: Taleb Ch.8 — BSM underprices puts in down-moves by this factor
SHADOW_GAMMA = {'low_vol': 1.3, 'high_vol': 1.5}  # VIX < 20 vs ≥ 20

# Named stress events
STRESS_PRESETS = {
    '2008_crash':    {'spot_change': -0.60, 'iv_mult': 4.0},
    '2020_covid':    {'spot_change': -0.38, 'iv_mult': 3.5},
    '2024_election': {'spot_change': -0.08, 'iv_mult': 1.8},
    'flash_crash':   {'spot_change': -0.15, 'iv_mult': 2.5},
    'rally':         {'spot_change': 0.15,  'iv_mult': 0.6},
}

# T3: Taleb Ch.11 — joint spot+vol scenarios (DdeltaDvol)
TALEB_JOINT_SCENARIOS = {
    'mild_stress':   {'spot_change': -0.03, 'iv_add': 0.05},   # NIFTY −3%, VIX +5pts
    'blow_up':       {'spot_change': -0.05, 'iv_add': 0.10},   # NIFTY −5%, VIX +10pts
    'relief_rally':  {'spot_change': 0.03,  'iv_add': -0.03},  # NIFTY +3%, VIX −3pts
}


def scenario_table(legs, spot, r=0.07, lot_size=None,
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


def stress_test(legs, spot, stress_type='2020_covid', r=0.07, lot_size=None):
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

    is_down = preset['spot_change'] < 0
    pnl = 0.0
    for leg in legs:
        t = max(leg.get('expiry_years', 0.01), 1 / 365)
        base_iv = max(leg.get('iv', 0.15), 0.01)
        stressed_iv = min(base_iv * iv_mult, 2.0)  # cap at 200% IV
        entry = leg.get('premium', 0)
        qty = leg.get('qty', 1)

        current = bsm.bsm_price(new_spot, leg['strike'], t, r,
                                 stressed_iv, leg['option_type'])

        # T1: shadow gamma on down-move puts (only when put gained value)
        if is_down and leg['option_type'] == 'PE':
            price_move = current - entry
            if price_move > 0:
                sf = SHADOW_GAMMA['high_vol'] if stressed_iv >= 0.20 else SHADOW_GAMMA['low_vol']
                current = entry + price_move * sf

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


def entry_gate(legs, spot, daily_theta, r=0.07, lot_size=None, dte=None):
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

    # ponytail: gate is Sinclair Ch.8 for premium-selling only;
    # BUY strategies (long straddle/strangle/put/call) pay theta, don't collect it
    net_premium = sum(l.get('premium', 0) if l.get('action') == 'SELL'
                      else -l.get('premium', 0) for l in legs)
    is_net_debit = net_premium < 0
    theta_income = daily_theta * dte

    if theta_income <= 0 or is_net_debit:
        return {
            'worst_pnl': worst_pnl,
            'theta_income': theta_income,
            'horizon_days': dte,
            'ratio': 0.0,
            'passes': True,
            'reason': 'Premium-buying strategy — theta gate N/A',
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


def _scenario_pnl(legs, new_spot, entry_spot, iv_change_pct, days_elapsed, r,
                  shadow_gamma=True):
    """Compute P/L for one scenario point.

    shadow_gamma: if True, inflate put prices by Taleb's shadow factor on down-moves.
    """
    pnl = 0.0
    is_down = new_spot < entry_spot
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

        # T1: shadow gamma — puts gain more than BSM predicts in down-moves
        if shadow_gamma and is_down and leg['option_type'] == 'PE':
            price_move = current - entry
            if price_move > 0:
                sf = SHADOW_GAMMA['high_vol'] if new_iv >= 0.20 else SHADOW_GAMMA['low_vol']
                current = entry + price_move * sf

        if leg.get('action') == 'SELL':
            pnl += (entry - current) * qty
        else:
            pnl += (current - entry) * qty

    return pnl


def taleb_joint_scenarios(legs, spot, r=0.07, lot_size=None):
    """T3: Taleb Ch.11 DdeltaDvol — named joint spot+vol scenarios."""
    results = []
    for name, params in TALEB_JOINT_SCENARIOS.items():
        new_spot = spot * (1.0 + params['spot_change'])
        pnl = 0.0
        is_down = params['spot_change'] < 0
        for leg in legs:
            t = max(leg.get('expiry_years', 0.01), 1 / 365)
            base_iv = max(leg.get('iv', 0.15), 0.01)
            new_iv = max(min(base_iv + params['iv_add'], 2.0), 0.01)
            entry = leg.get('premium', 0)
            qty = leg.get('qty', 1)
            current = bsm.bsm_price(new_spot, leg['strike'], t, r,
                                     new_iv, leg['option_type'])
            if is_down and leg['option_type'] == 'PE':
                price_move = current - entry
                if price_move > 0:
                    sf = SHADOW_GAMMA['high_vol'] if new_iv >= 0.20 else SHADOW_GAMMA['low_vol']
                    current = entry + price_move * sf
            if leg.get('action') == 'SELL':
                pnl += (entry - current) * qty
            else:
                pnl += (current - entry) * qty
        pnl_lot = pnl * lot_size
        results.append({
            'scenario': name,
            'spot_change': params['spot_change'],
            'iv_add': params['iv_add'],
            'new_spot': round(new_spot, 2),
            'pnl_per_unit': round(pnl, 2),
            'pnl_per_lot': round(pnl_lot, 2),
        })
    return results


# T4: Taleb — up/down move asymmetry
# Equity puts gain more than calls for equal-magnitude moves (leverage effect +
# vol-spot negative correlation). Inflate down-move scenario P/L by asymmetry factor.
ASYMMETRY_FACTOR = 1.2  # down-moves hit 1.2× harder than BSM alone predicts

def asymmetry_ratio(legs, spot, r=0.07, lot_size=None, pct=0.05):
    """T4: Compare P/L for equal up and down moves.
    Returns ratio of |down_pnl| / |up_pnl| — values > 1.0 = put-side risk dominates."""
    if not spot or spot <= 0:
        return {'down_pnl': 0, 'up_pnl': 0, 'ratio': 1.0, 'move_pct': pct, 'warning': False}
    lot_size = lot_size or 1
    down_pnl = _scenario_pnl(legs, spot * (1 - pct), spot, 0.0, 0, r) * lot_size
    up_pnl = _scenario_pnl(legs, spot * (1 + pct), spot, 0.0, 0, r) * lot_size
    # Apply asymmetry inflation to down move
    down_pnl_adj = down_pnl * ASYMMETRY_FACTOR
    up_abs = abs(up_pnl) if up_pnl != 0 else 1e-6
    return {
        'down_pnl': float(round(down_pnl_adj, 2)),
        'up_pnl': float(round(up_pnl, 2)),
        'ratio': float(round(abs(down_pnl_adj) / up_abs, 2)),
        'move_pct': pct,
        'warning': bool(abs(down_pnl_adj) > abs(up_pnl) * 2),
    }


# T8: Taleb Ch.3 — path-dependent P&L tracking
def path_metrics(spot_history):
    """T8: Compute MAE, MFE, and path roughness from spot history during a trade.
    spot_history: list of spot prices [entry, ..., exit]."""
    if len(spot_history) < 2:
        return {'mae': 0, 'mfe': 0, 'roughness': 1.0}
    entry = spot_history[0]
    returns_from_entry = [(s - entry) / entry for s in spot_history]
    mae = min(returns_from_entry)  # max adverse excursion (negative)
    mfe = max(returns_from_entry)  # max favorable excursion (positive)
    # Roughness: realized path length / direct distance (Parkinson-style)
    total_path = sum(abs(spot_history[i+1] - spot_history[i])
                     for i in range(len(spot_history) - 1))
    direct = abs(spot_history[-1] - entry)
    # True round-trip (direct≈0): path went nowhere despite possible movement
    if direct < 1e-6:
        roughness = min(total_path / max(entry * 1e-3, 1e-6), 99.0) if total_path > 0 else 1.0
    else:
        roughness = total_path / direct
    return {
        'mae': round(mae * 100, 2),   # as % of entry
        'mfe': round(mfe * 100, 2),
        'roughness': round(roughness, 2),
        'path_length': len(spot_history),
    }


# T9: Taleb — fat-tail BSM correction
# Real kurtosis ~5-8 for equity indices vs BSM's 3.
# For extreme moves (> 2σ), actual probability ≈ (kurt/3) × BSM probability.
NIFTY_KURTOSIS = 5.0

def fat_tail_factor(spot_change_pct, annual_vol=0.15, kurtosis=NIFTY_KURTOSIS):
    """T9: Tail inflation factor for a given spot move.
    Returns multiplier ≥ 1.0 to apply to BSM scenario P/L at extreme moves.
    Down-moves get extra 20% (negative skew — leverage effect, Taleb Ch.4)."""
    if annual_vol <= 0:
        return 1.0
    daily_vol = annual_vol / math.sqrt(252)
    n_sigma = abs(spot_change_pct) / (daily_vol * math.sqrt(5))
    if n_sigma <= 2:
        factor = 1.0
    elif n_sigma <= 3:
        factor = kurtosis / 3.0
    elif n_sigma <= 5:
        factor = (kurtosis / 3.0) ** 2
    else:
        # Beyond 5σ: scale linearly so 30% crash ≠ 10% dip
        base = (kurtosis / 3.0) ** 2
        factor = base * (n_sigma / 5.0)
    # Negative skew: down-moves are fatter-tailed than up-moves
    if spot_change_pct < 0 and factor > 1.0:
        factor *= 1.2
    return factor


def scenario_table_fat_tail(legs, spot, r=0.07, lot_size=None, annual_vol=0.15):
    """T9: Scenario table with fat-tail adjusted worst case."""
    lot_size = lot_size or 1
    base = scenario_table(legs, spot, r, lot_size)
    worst_adj = base['worst_case'].copy()
    for row in base['grid']:
        ft = fat_tail_factor(row['spot_change'], annual_vol)
        adj_pnl = row['pnl_per_lot'] * ft if row['pnl_per_lot'] < 0 else row['pnl_per_lot']
        if adj_pnl < worst_adj.get('pnl_per_lot', 0):
            worst_adj = {**row, 'pnl_per_lot': float(round(adj_pnl, 2)), 'tail_factor': float(ft)}
    base['fat_tail_worst'] = worst_adj
    bsm_worst = float(base['worst_case']['pnl_per_lot'])
    ft_worst = float(worst_adj['pnl_per_lot'])
    base['fat_tail_ratio'] = float(round(ft_worst / min(bsm_worst, -1), 2)) if bsm_worst < 0 else 1.0
    return base


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

    # T3: Taleb joint scenarios
    tj = taleb_joint_scenarios(legs, 24000, lot_size=65)
    assert len(tj) == 3
    blow_up = [s for s in tj if s['scenario'] == 'blow_up'][0]
    assert blow_up['pnl_per_lot'] < 0, "Iron condor should lose in blow-up scenario"

    # T4: asymmetry
    ar = asymmetry_ratio(legs, 24000, lot_size=65)
    assert ar['ratio'] > 0, "Asymmetry ratio must be positive"
    assert 'down_pnl' in ar and 'up_pnl' in ar
    # T4: spot=0 must not crash
    ar0 = asymmetry_ratio(legs, 0, lot_size=65)
    assert ar0['ratio'] == 1.0, "spot=0 should return safe defaults"

    # T8: path metrics
    pm = path_metrics([24000, 24100, 24200, 23800, 23900])
    assert pm['mae'] < 0, "MAE should be negative"
    assert pm['mfe'] > 0, "MFE should be positive"
    assert pm['roughness'] >= 1.0, "Roughness ≥ 1 (path ≥ direct distance)"
    # T8: flat path (same entry and exit) must not return 0 roughness
    pm_flat = path_metrics([24000, 24100, 23900, 24000])
    assert pm_flat['roughness'] > 0, "Flat path with intra-movement must have roughness > 0"

    # T9: fat-tail
    assert fat_tail_factor(0.01) == 1.0, "Small moves: no adjustment"
    assert fat_tail_factor(0.10) > 1.0, "Large moves: tail inflation"
    ft_table = scenario_table_fat_tail(legs, 24000, lot_size=65)
    assert ft_table['fat_tail_worst']['pnl_per_lot'] <= ft_table['worst_case']['pnl_per_lot']

    print("scenarios.py: all checks passed")


if __name__ == '__main__':
    _self_check()
