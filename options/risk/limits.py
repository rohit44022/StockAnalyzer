"""
NSE regulatory limits: MWPL, ban period, client limits, auto-sq-off.

MWPL (Market Wide Position Limit):
  - Set by NSE per underlying based on free-float market cap
  - OI > 60% MWPL: caution
  - OI > 95% MWPL: NO new positions allowed (ban period)
  - OI < 80% MWPL: ban lifted

Client-level limits (SEBI):
  - Max 1% of MWPL or ₹500 crore FutEq, whichever is lower
  - Delta-based FutEq (SEBI 2025): weighted by option delta

Auto-sq-off:
  - 3:20 PM: broker starts square-off
  - 3:00 PM: RMS team may act on ANY short option
"""

# MWPL thresholds
MWPL_CAUTION = 0.60    # OI > 60% → caution
MWPL_BAN = 0.95        # OI > 95% → ban
MWPL_UNBAN = 0.80      # OI < 80% → ban lifted

# Client limit
CLIENT_LIMIT_PCT = 0.01   # 1% of MWPL
CLIENT_LIMIT_ABS = 500e7  # ₹500 crore in FutEq

# Auto sq-off times (minutes before market close at 15:30)
SQOFF_BROKER = 10   # 3:20 PM
SQOFF_RMS = 30      # 3:00 PM


def mwpl_check(current_oi, mwpl_limit):
    """
    Check MWPL status for an underlying.

    Parameters
    ----------
    current_oi : int — total market-wide OI in contracts
    mwpl_limit : int — MWPL limit set by NSE

    Returns
    -------
    dict: utilization_pct, status, can_open_new, action
    """
    if mwpl_limit <= 0:
        return {'utilization_pct': 0, 'status': 'unknown',
                'can_open_new': True, 'action': 'none'}

    util = current_oi / mwpl_limit

    if util >= MWPL_BAN:
        return {
            'utilization_pct': round(util * 100, 2),
            'status': 'ban',
            'can_open_new': False,
            'action': 'No new positions. Only closing trades allowed.',
        }
    elif util >= MWPL_CAUTION:
        return {
            'utilization_pct': round(util * 100, 2),
            'status': 'caution',
            'can_open_new': True,
            'action': 'Near ban. Reduce or avoid new positions.',
        }
    else:
        return {
            'utilization_pct': round(util * 100, 2),
            'status': 'ok',
            'can_open_new': True,
            'action': 'none',
        }


def compute_futeq(legs, spot, lot_size):
    """
    SEBI 2025 delta-based FutEq: Σ|delta_i × qty_i × lot_size × spot|.

    Parameters
    ----------
    legs : list of dicts with 'delta', 'qty', 'action'
    spot : float
    lot_size : int
    """
    total = 0.0
    for leg in legs:
        delta = leg.get('delta', 0)
        qty = leg.get('qty', 1)
        sign = -1 if leg.get('action') == 'SELL' else 1
        total += abs(sign * delta * qty * lot_size * spot)
    return total


def client_limit_check(client_oi, mwpl_limit, client_futeq=0):
    """
    Check client-level position limits.

    Parameters
    ----------
    client_oi : int — client's OI in contracts
    mwpl_limit : int — MWPL for this underlying
    client_futeq : float — client's FutEq exposure in ₹

    Returns
    -------
    dict: oi_limit, oi_used_pct, futeq_limit, futeq_used_pct, breached, action
    """
    oi_limit = int(mwpl_limit * CLIENT_LIMIT_PCT) if mwpl_limit > 0 else 0
    oi_pct = (client_oi / oi_limit * 100) if oi_limit > 0 else 0

    futeq_pct = (client_futeq / CLIENT_LIMIT_ABS * 100) if CLIENT_LIMIT_ABS > 0 else 0

    breached = (client_oi > oi_limit) or (client_futeq > CLIENT_LIMIT_ABS)

    action = 'none'
    if breached:
        action = 'BREACH: close positions to come within limits. Penalty risk.'
    elif oi_pct > 80 or futeq_pct > 80:
        action = 'Approaching client limit — avoid adding.'

    return {
        'oi_limit': oi_limit,
        'oi_used_pct': round(oi_pct, 2),
        'futeq_limit': CLIENT_LIMIT_ABS,
        'futeq_used_pct': round(futeq_pct, 2),
        'breached': breached,
        'action': action,
    }


def ban_period_actions(status, positions):
    """
    What to do during ban period.

    Parameters
    ----------
    status : str — from mwpl_check ('ban', 'caution', 'ok')
    positions : list of dicts — strategy, legs, etc.

    Returns
    -------
    list of action dicts
    """
    if status != 'ban':
        return []

    actions = []
    for i, pos in enumerate(positions):
        key = pos.get('strategy', f'position_{i}')
        has_short = any(l.get('action') == 'SELL' for l in pos.get('legs', []))
        if has_short:
            actions.append({
                'position': key,
                'urgency': 1,
                'action': 'close_short_legs',
                'reason': 'Ban period — cannot roll or adjust short legs. '
                          'Close before forced sq-off.',
            })
        else:
            actions.append({
                'position': key,
                'urgency': 3,
                'action': 'monitor',
                'reason': 'Ban period — long positions can be held but not added to.',
            })

    return actions


def sqoff_warning(minutes_to_close, has_short_options=True):
    """
    Auto-sq-off time warnings.

    Parameters
    ----------
    minutes_to_close : int — minutes until 15:30 IST

    Returns
    -------
    dict: urgency, action, reason (or None if no warning)
    """
    if not has_short_options:
        return None

    if minutes_to_close <= SQOFF_BROKER:
        return {
            'urgency': 1,
            'action': 'close_now',
            'reason': f'{minutes_to_close}min to close — broker sq-off imminent',
        }
    elif minutes_to_close <= SQOFF_RMS:
        return {
            'urgency': 2,
            'action': 'plan_exit',
            'reason': f'{minutes_to_close}min to close — RMS may act on short options',
        }
    return None


def _self_check():
    # MWPL
    assert mwpl_check(500, 1000)['status'] == 'ok'
    assert mwpl_check(700, 1000)['status'] == 'caution'
    assert mwpl_check(960, 1000)['status'] == 'ban'
    assert not mwpl_check(960, 1000)['can_open_new']

    # Client limits
    cl = client_limit_check(50, 10000)
    assert not cl['breached']
    cl2 = client_limit_check(200, 10000)
    assert cl2['breached']

    # Ban actions
    pos = [{'strategy': 'iron_condor', 'legs': [{'action': 'SELL'}, {'action': 'BUY'}]}]
    acts = ban_period_actions('ban', pos)
    assert len(acts) == 1
    assert acts[0]['urgency'] == 1
    assert ban_period_actions('ok', pos) == []

    # Sq-off
    assert sqoff_warning(5, True)['urgency'] == 1
    assert sqoff_warning(20, True)['urgency'] == 2
    assert sqoff_warning(60, True) is None
    assert sqoff_warning(5, False) is None

    print("limits.py: all checks passed")


if __name__ == '__main__':
    _self_check()
