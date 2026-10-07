"""
Margin estimation: SPAN-like + ELM for NSE F&O.

NSE uses SPAN (Standard Portfolio Analysis of Risk) + ELM (Extreme Loss Margin).
ELM: +2% of notional for index, +3.5% for stock options (SEBI 2024).
Expiry-day margins increase via E-4→E-day ramp (SEBI 2025).

This is an ESTIMATOR — actual margins come from NSCCL/broker.
"""

from ..core import bsm

# NSE SPAN scan ranges (approximate, varies by underlying)
_SCAN_RANGES = {
    'NIFTY':     {'up_pct': 0.10, 'down_pct': 0.10, 'vol_up': 0.25, 'vol_dn': 0.25},
    'BANKNIFTY': {'up_pct': 0.12, 'down_pct': 0.12, 'vol_up': 0.25, 'vol_dn': 0.25},
    'DEFAULT':   {'up_pct': 0.10, 'down_pct': 0.10, 'vol_up': 0.25, 'vol_dn': 0.25},
}

# ELM rates
ELM_INDEX = 0.02   # 2% for index options
ELM_STOCK = 0.035  # 3.5% for stock options

# Expiry-day margin ramp (SEBI 2025)
_EXPIRY_RAMP = {4: 0.10, 3: 0.25, 2: 0.45, 1: 0.70, 0: 1.00}


def estimate_margin(legs, spot, lot_size=65, underlying='NIFTY',
                    dte=None, r=0.07):
    """
    Estimate initial margin for a multi-leg position.

    Uses SPAN-like worst-case scanning + ELM.
    For spreads, the margin benefit is the max-loss cap.

    Parameters
    ----------
    legs : list of dicts — strike, option_type, action, iv, expiry_years, qty, premium
    spot : float
    lot_size : int
    underlying : str — for scan range lookup
    dte : int — days to expiry (for expiry-day ramp)

    Returns
    -------
    dict: span_margin, elm, total_margin, margin_benefit, expiry_surcharge
    """
    scan = _SCAN_RANGES.get(underlying, _SCAN_RANGES['DEFAULT'])

    # SPAN: worst-case portfolio loss across 16 scenarios
    # (±1/3, ±2/3, ±1 of scan range) × (vol up, vol down)
    fracs = [1/3, 2/3, 1.0]
    scenarios = []
    for f in fracs:
        for direction in [1, -1]:
            for vol_shift in [scan['vol_up'], -scan['vol_dn']]:
                spot_shift = direction * f * scan['up_pct' if direction > 0 else 'down_pct']
                scenarios.append((spot_shift, vol_shift))

    # Deep OTM scenario: spot moves to extreme, vol doubles
    scenarios.append((-scan['down_pct'] * 2, scan['vol_up'] * 2))
    scenarios.append((scan['up_pct'] * 2, scan['vol_up'] * 2))

    worst_loss = 0.0
    for spot_pct, vol_pct in scenarios:
        new_spot = spot * (1.0 + spot_pct)
        loss = 0.0
        for leg in legs:
            t = max(leg.get('expiry_years', 0.01), 1 / 365)
            base_iv = max(leg.get('iv', 0.15), 0.01)
            new_iv = max(base_iv * (1.0 + vol_pct), 0.01)
            entry_price = leg.get('premium', 0)
            qty = leg.get('qty', 1)

            new_price = bsm.bsm_price(new_spot, leg['strike'], t, r,
                                       new_iv, leg['option_type'])
            if leg.get('action') == 'SELL':
                leg_loss = (new_price - entry_price) * qty
            else:
                leg_loss = (entry_price - new_price) * qty
            loss += leg_loss

        # Loss is positive when portfolio loses money
        worst_loss = max(worst_loss, loss)

    span = worst_loss * lot_size

    # ELM: percentage of notional
    notional = spot * lot_size
    is_index = underlying.upper() in ('NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCAPNIFTY')
    elm_rate = ELM_INDEX if is_index else ELM_STOCK

    # NSCCL: ELM on net shorts; hedged spreads get 50% reduction per covered lot
    net_short_qty = sum(leg.get('qty', 1) for leg in legs if leg.get('action') == 'SELL')
    net_long_qty = sum(leg.get('qty', 1) for leg in legs if leg.get('action') == 'BUY')
    net_exposed = max(0, net_short_qty - net_long_qty)
    hedged_qty = min(net_short_qty, net_long_qty)
    elm = notional * elm_rate * (net_exposed + hedged_qty * 0.5)

    # Expiry-day surcharge (SEBI 2025)
    expiry_surcharge = 0.0
    if dte is not None and dte <= 4:
        ramp_pct = _EXPIRY_RAMP.get(dte, 0)
        expiry_surcharge = span * ramp_pct

    total = span + elm + expiry_surcharge

    # Margin benefit: how much less than naked margin
    naked_margin = _naked_margin(legs, spot, lot_size, r, scan, elm_rate)

    return {
        'span_margin': round(span, 2),
        'elm': round(elm, 2),
        'expiry_surcharge': round(expiry_surcharge, 2),
        'total_margin': round(total, 2),
        'naked_margin': round(naked_margin, 2),
        'margin_benefit': round(max(0, naked_margin - total), 2),
        'margin_pct_of_notional': round(total / notional * 100, 2) if notional > 0 else 0,
    }


def _naked_margin(legs, spot, lot_size, r, scan, elm_rate):
    """Sum of individual leg margins without spread benefit."""
    total = 0.0
    notional = spot * lot_size
    for leg in legs:
        if leg.get('action') != 'SELL':
            continue
        t = max(leg.get('expiry_years', 0.01), 1 / 365)
        iv = max(leg.get('iv', 0.15), 0.01)
        qty = leg.get('qty', 1)

        worst = 0.0
        for sign in [1, -1]:
            pct = scan['up_pct'] if sign > 0 else scan['down_pct']
            new_spot = spot * (1.0 + sign * pct)
            new_iv = iv * (1.0 + scan['vol_up'])
            new_price = bsm.bsm_price(new_spot, leg['strike'], t, r,
                                       new_iv, leg['option_type'])
            entry = leg.get('premium', 0)
            loss = (new_price - entry) * qty
            worst = max(worst, loss)

        total += worst * lot_size + notional * elm_rate * qty

    return total


def margin_utilization(total_margin, available_capital):
    """
    Check margin as percentage of capital.

    Returns
    -------
    dict: utilization_pct, status ('ok', 'warning', 'danger')
    """
    if available_capital <= 0:
        return {'utilization_pct': 100, 'status': 'danger'}

    util = total_margin / available_capital * 100
    if util > 80:
        status = 'danger'
    elif util > 50:
        status = 'warning'
    else:
        status = 'ok'

    return {'utilization_pct': round(util, 2), 'status': status}


def broker_margin(legs, spot, lot_size=65, underlying='NIFTY', dte=None, r=0.07):
    """
    Try Dhan API margin first; fall back to SPAN estimator.

    Returns
    -------
    dict: same as span_margin(), with 'source' field ('dhan_api' or 'estimator')
    """
    try:
        from ..data import dhan_fetch
        api_result = dhan_fetch.fetch_margin(legs, symbol=underlying)
        if api_result and api_result.get('total_margin', 0) > 0:
            estimate = estimate_margin(legs, spot, lot_size, underlying, dte, r)
            estimate['broker_margin'] = api_result['total_margin']
            estimate['source'] = 'dhan_api'
            estimate['total'] = api_result['total_margin']
            return estimate
    except Exception:
        pass
    result = estimate_margin(legs, spot, lot_size, underlying, dte, r)
    result['source'] = 'estimator'
    return result


def _self_check():
    # Iron condor — defined risk, should have margin benefit over naked
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
    m = estimate_margin(legs, 24000, lot_size=65)
    assert m['total_margin'] > 0
    assert m['margin_benefit'] > 0, "Spread should save margin vs naked"

    # Naked short straddle — higher margin
    naked = [
        {'strike': 24000, 'option_type': 'CE', 'action': 'SELL',
         'premium': 300, 'iv': 0.15, 'expiry_years': 14 / 365, 'qty': 1},
        {'strike': 24000, 'option_type': 'PE', 'action': 'SELL',
         'premium': 280, 'iv': 0.15, 'expiry_years': 14 / 365, 'qty': 1},
    ]
    mn = estimate_margin(naked, 24000, lot_size=65)
    assert mn['total_margin'] > m['total_margin'], "Naked should need more margin"

    # Expiry-day surcharge
    me = estimate_margin(legs, 24000, lot_size=65, dte=1)
    assert me['expiry_surcharge'] > 0
    assert me['total_margin'] > m['total_margin']

    # Margin utilization
    mu = margin_utilization(100_000, 500_000)
    assert mu['status'] == 'ok'
    mu2 = margin_utilization(450_000, 500_000)
    assert mu2['status'] == 'danger'

    print("margin.py: all checks passed")


if __name__ == '__main__':
    _self_check()
