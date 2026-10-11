"""
Rollover management: near→far month roll cost + timing.

Roll = close near-month legs + open far-month legs at new premiums.
Timing: avoid last 2 days (illiquidity + expiry margin spike).
OI rollover %: market's rollover as sentiment signal.
"""

def roll_cost(near_legs, far_legs, lot_size=None, n_lots=1):
    """
    Compute cost to roll near-month position to far-month.

    Parameters
    ----------
    near_legs : list of dicts — current legs (strike, option_type, action, premium)
    far_legs : list of dicts — replacement legs (same fields)
    lot_size : int
    n_lots : int

    Returns
    -------
    dict: close_cost, open_cost, net_roll_cost (negative = you pay),
          net_credit (positive = you receive)
    """
    close_cost = 0.0
    for leg in near_legs:
        p = leg.get('premium', 0)
        if leg.get('action') == 'SELL':
            close_cost -= p  # buy back short = pay
        else:
            close_cost += p  # sell long = receive

    open_cost = 0.0
    for leg in far_legs:
        p = leg.get('premium', 0)
        if leg.get('action') == 'SELL':
            open_cost += p  # sell new short = receive
        else:
            open_cost -= p  # buy new long = pay

    net_per_unit = close_cost + open_cost
    net_total = net_per_unit * lot_size * n_lots

    return {
        'close_credit_per_unit': round(close_cost, 2),
        'open_credit_per_unit': round(open_cost, 2),
        'net_per_unit': round(net_per_unit, 2),
        'net_total': round(net_total, 2),
        'net_credit': net_total > 0,
    }


def optimal_roll_dte(dte, strategy_key=''):
    """
    Should we roll now? Returns (should_roll, urgency, reason).

    Rules:
    - DTE <= 2: MUST roll (expiry margin spike + illiquidity)
    - DTE 3-5: SHOULD roll (theta decay accelerating)
    - DTE 6-10 + short premium: CONSIDER (roll while there's still time value)
    - DTE > 10: no need
    """
    is_short = 'short' in strategy_key or 'iron' in strategy_key or 'spread' in strategy_key

    if dte <= 0:
        return True, 1, 'At expiry — must roll or close immediately'
    if dte <= 2:
        return True, 1, f'DTE={dte} — roll now (expiry margin spike + illiquidity)'
    if dte <= 5:
        return True, 2, f'DTE={dte} — theta accelerating, optimal roll window'
    if dte <= 10 and is_short:
        return False, 3, f'DTE={dte} — consider rolling short premium strategy'
    return False, 0, f'DTE={dte} — no roll needed'


def oi_rollover_pct(near_oi, far_oi, prev_near_oi=None, prev_far_oi=None):
    """
    Market rollover percentage — what fraction of OI has moved to far month.

    High rollover (>60%) before expiry week = market expects continuation.
    Low rollover (<30%) near expiry = potential squeeze / delivery pressure.

    Parameters
    ----------
    near_oi, far_oi : int — current OI in near and far month
    prev_near_oi, prev_far_oi : int or None — previous day OI for change tracking
    """
    total = near_oi + far_oi
    if total <= 0:
        return {'rollover_pct': 0, 'signal': 'no_data'}

    pct = far_oi / total * 100

    if prev_near_oi is not None and prev_far_oi is not None:
        prev_total = prev_near_oi + prev_far_oi
        prev_pct = prev_far_oi / prev_total * 100 if prev_total > 0 else 0
        daily_change = pct - prev_pct
    else:
        daily_change = None

    if pct >= 60:
        signal = 'high_rollover'
    elif pct >= 30:
        signal = 'normal'
    else:
        signal = 'low_rollover'

    result = {
        'rollover_pct': round(pct, 1),
        'near_oi': near_oi,
        'far_oi': far_oi,
        'signal': signal,
    }
    if daily_change is not None:
        result['daily_change_pct'] = round(daily_change, 1)
    return result


def suggest_roll_strikes(strategy_key, chain_df, spot, far_expiry, r=0.07,
                         lot_size=65):
    """
    Build far-month legs for rolling using the existing strategy builder.

    Returns None if chain_df lacks far_expiry data or builder can't construct.
    """
    from . import builder

    far_chain = chain_df[chain_df['expiry'] == far_expiry] if 'expiry' in chain_df.columns else chain_df
    if far_chain.empty:
        return None

    result = builder.build(strategy_key, far_chain, spot, r=r, lot_size=lot_size)
    return result


def _self_check():
    # Roll cost: iron condor near → far
    near = [
        {'strike': 23800, 'option_type': 'PE', 'action': 'BUY', 'premium': 30},
        {'strike': 23900, 'option_type': 'PE', 'action': 'SELL', 'premium': 50},
        {'strike': 24100, 'option_type': 'CE', 'action': 'SELL', 'premium': 50},
        {'strike': 24200, 'option_type': 'CE', 'action': 'BUY', 'premium': 25},
    ]
    far = [
        {'strike': 23700, 'option_type': 'PE', 'action': 'BUY', 'premium': 45},
        {'strike': 23800, 'option_type': 'PE', 'action': 'SELL', 'premium': 70},
        {'strike': 24200, 'option_type': 'CE', 'action': 'SELL', 'premium': 65},
        {'strike': 24300, 'option_type': 'CE', 'action': 'BUY', 'premium': 40},
    ]
    rc = roll_cost(near, far, lot_size=65, n_lots=1)
    # Close: sell PE buy +30, buy back PE sell -50, buy back CE sell -50, sell CE buy +25 = -45
    # Open: buy PE -45, sell PE +70, sell CE +65, buy CE -40 = +50
    # Net per unit = -45 + 50 = +5
    assert rc['net_per_unit'] == 5.0, f"Expected +5, got {rc['net_per_unit']}"
    assert rc['net_credit'] is True
    assert rc['net_total'] == 5.0 * 65

    # Timing
    should, urg, _ = optimal_roll_dte(1, 'iron_condor')
    assert should and urg == 1
    should, urg, _ = optimal_roll_dte(4, 'short_straddle')
    assert should and urg == 2
    should, urg, _ = optimal_roll_dte(8, 'iron_condor')
    assert not should and urg == 3
    should, urg, _ = optimal_roll_dte(15, 'iron_condor')
    assert not should and urg == 0

    # OI rollover
    ro = oi_rollover_pct(40000, 60000)
    assert ro['rollover_pct'] == 60.0
    assert ro['signal'] == 'high_rollover'
    ro = oi_rollover_pct(80000, 20000)
    assert ro['signal'] == 'low_rollover'
    ro = oi_rollover_pct(50000, 50000, 60000, 40000)
    assert ro['daily_change_pct'] > 0

    # Edge: empty legs
    rc_empty = roll_cost([], [], 65, 1)
    assert rc_empty['net_per_unit'] == 0
    assert rc_empty['net_credit'] is False

    # Edge: negative DTE (past expiry)
    should, urg, _ = optimal_roll_dte(-1, 'iron_condor')
    assert should and urg == 1

    # Edge: zero OI
    ro_zero = oi_rollover_pct(0, 0)
    assert ro_zero['signal'] == 'no_data'

    print("rollover.py: all checks passed")


if __name__ == '__main__':
    _self_check()
