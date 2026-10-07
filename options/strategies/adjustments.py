"""
Position adjustment rules: when and how to modify live positions.

Cohen (exits), Sinclair (stops + survival via actual P/L), Davey (discipline).
GA2 fix: BSM repricing replaces spot-change heuristic.
GA5 fix: Cohen's long-option exit rule hardened.
"""

from ..core import bsm


def check(position, spot, days_held=0, entry_spot=None, dte=None, r=0.07,
          live_iv=None):
    """
    Check if a position needs adjustment.

    Parameters
    ----------
    position : dict — from builder.build()
    spot : float — current underlying price
    days_held : int
    entry_spot : float — spot at entry
    dte : int — days to expiry
    r : float — risk-free rate
    live_iv : dict or None — {(strike, option_type): iv} from current chain

    Returns
    -------
    list of dicts: {action, urgency (1=act now, 2=soon, 3=review), reason}
    """
    recs = []
    dte_years = dte / 365 if dte is not None else None

    if dte is not None:
        recs.extend(_dte_rules(position, dte))

    recs.extend(_pnl_rules(position, spot, entry_spot, dte_years, r, live_iv))

    recs.extend(_general_rules(position, days_held))

    recs.sort(key=lambda r: r['urgency'])
    return recs


def _dte_rules(position, dte):
    recs = []
    key = position.get('strategy', '')

    if dte <= 0:
        recs.append({'action': 'close', 'urgency': 1,
                     'reason': 'At expiry — close all legs'})
    elif dte <= 2:
        recs.append({'action': 'close', 'urgency': 1,
                     'reason': f'DTE={dte} — close before expiry-day gamma/margin spike'})
    elif dte <= 5 and ('short' in key or 'iron' in key or 'spread' in key):
        recs.append({'action': 'consider_roll', 'urgency': 2,
                     'reason': f'DTE={dte} — consider rolling to next expiry'})

    # Cohen: NEVER hold OTM/ATM long options into final 3 weeks
    if key.startswith('long_'):
        if dte <= 7:
            recs.append({'action': 'close', 'urgency': 1,
                         'reason': f'DTE={dte} — Cohen: close long options now'})
        elif dte <= 21:
            recs.append({'action': 'close_or_roll', 'urgency': 2,
                         'reason': f'DTE={dte} — Cohen: exit long options before final 3 weeks'})

    return recs


def _reprice_pnl(legs, spot, dte_years, r=0.07, live_iv=None):
    """
    BSM-based per-unit P/L. Sinclair Ch.9: stops on actual P/L, not spot.

    Parameters
    ----------
    live_iv : dict or None — {(strike, option_type): iv} from current chain.
        Falls back to entry IV per leg when not available.
    """
    pnl = 0.0
    t = max(dte_years, 1 / 365)
    for leg in legs:
        strike = leg.get('strike')
        otype = leg.get('option_type')
        entry_iv = leg.get('iv')
        entry = leg.get('premium')
        if None in (strike, otype, entry_iv, entry):
            return None
        iv = entry_iv
        if live_iv:
            iv = live_iv.get((strike, otype), live_iv.get(strike, entry_iv))
        current = bsm.bsm_price(spot, strike, t, r, max(iv, 0.01), otype)
        if leg.get('action') == 'SELL':
            pnl += entry - current
        else:
            pnl += current - entry
    return pnl


def _pnl_rules(position, spot, entry_spot, dte_years=None, r=0.07, live_iv=None):
    recs = []
    legs = position.get('legs', [])
    max_loss = position.get('max_loss', float('-inf'))
    max_profit = position.get('max_profit', 0)

    # Prefer BSM repricing when legs have data
    if legs and dte_years is not None:
        pnl = _reprice_pnl(legs, spot, dte_years, r, live_iv)
        if pnl is not None:
            # Sinclair: take profit when you can
            if max_profit and max_profit > 0 and max_profit != float('inf') and pnl > 0:
                pnl_pct = pnl / max_profit
                if pnl_pct >= 0.5:
                    recs.append({'action': 'take_profit', 'urgency': 2,
                                 'reason': f'P/L at {pnl_pct:.0%} of max profit — take profit'})
                elif pnl_pct >= 0.25:
                    recs.append({'action': 'take_profit', 'urgency': 3,
                                 'reason': f'P/L at {pnl_pct:.0%} of max profit — consider exit'})

            # Sinclair Ch.9: position-level stop at 2-3× expected
            if max_loss and max_loss < 0 and max_loss != float('-inf') and pnl < 0:
                loss_pct = pnl / max_loss  # both negative → positive
                if loss_pct >= 0.7:
                    recs.append({'action': 'stop_loss', 'urgency': 1,
                                 'reason': f'Loss at {loss_pct:.0%} of max loss — exit now'})
                elif loss_pct >= 0.5:
                    recs.append({'action': 'adjust', 'urgency': 2,
                                 'reason': f'Loss at {loss_pct:.0%} of max loss — adjust or exit'})
            return recs

    # Fallback: spot-change heuristic (when legs are empty or can't reprice)
    if entry_spot is not None and entry_spot > 0:
        pct = (spot - entry_spot) / entry_spot
        key = position.get('strategy', '')

        if 'straddle' in key or 'strangle' in key:
            if key.startswith('short') and abs(pct) > 0.03:
                recs.append({'action': 'stop_loss', 'urgency': 1,
                             'reason': f'Spot moved {pct:+.1%} — exceeds 3% stop'})
        elif 'iron' in key or 'spread' in key:
            if abs(pct) > 0.04:
                recs.append({'action': 'adjust', 'urgency': 2,
                             'reason': f'Spot moved {pct:+.1%} — short strike being tested'})

        if position.get('net_premium', 0) > 0 and abs(pct) < 0.005:
            recs.append({'action': 'take_profit', 'urgency': 3,
                         'reason': 'Spot stable — consider taking profit at 50% of max'})

    return recs


def _general_rules(position, days_held):
    recs = []
    if days_held > 30:
        recs.append({'action': 'review', 'urgency': 3,
                     'reason': f'Held {days_held} days — review if thesis still valid'})
    return recs


def suggest_roll(position, chain_df, spot, r=0.07, lot_size=65):
    """Suggest roll: close current, open same strategy on next expiry."""
    from . import builder
    key = position.get('strategy')
    if not key:
        return None
    new = builder.build(key, chain_df, spot, r=r, lot_size=lot_size)
    if new is None:
        return None
    return {'action': 'roll', 'close': position['legs'], 'open': new}


def _self_check():
    # Spot-change fallback (empty legs)
    pos = {
        'strategy': 'iron_condor',
        'net_premium': 5.0, 'max_profit': 5.0, 'max_loss': -15.0,
        'legs': [],
    }
    recs = check(pos, spot=24000, dte=2)
    assert any(r['urgency'] == 1 for r in recs), "Should warn at DTE=2"

    recs = check(pos, spot=25000, entry_spot=24000, dte=10)
    assert any('moved' in r['reason'] for r in recs)

    recs = check(pos, spot=24010, entry_spot=24000, dte=40)
    assert all(r['urgency'] >= 2 for r in recs)

    ss = {'strategy': 'short_strangle', 'net_premium': 10, 'legs': []}
    recs = check(ss, spot=24800, entry_spot=24000, dte=15)
    assert any(r['action'] == 'stop_loss' for r in recs)

    # GA5: Cohen long-option exit
    lc = {'strategy': 'long_call', 'legs': []}
    recs = check(lc, spot=24000, dte=15)
    assert any('Cohen' in r['reason'] for r in recs)
    recs = check(lc, spot=24000, dte=5)
    assert any(r['urgency'] == 1 and 'Cohen' in r['reason'] for r in recs)

    # GA2: BSM repricing path
    legs = [
        {'strike': 24000, 'option_type': 'CE', 'action': 'SELL',
         'premium': 300, 'iv': 0.15},
        {'strike': 24000, 'option_type': 'PE', 'action': 'SELL',
         'premium': 280, 'iv': 0.15},
    ]
    straddle = {
        'strategy': 'short_straddle', 'net_premium': 580,
        'max_profit': 580, 'max_loss': float('-inf'),
        'legs': legs,
    }
    # Spot stable, time passed → should profit from theta
    recs = check(straddle, spot=24000, entry_spot=24000, dte=3)
    pnl = _reprice_pnl(legs, 24000, 3 / 365)
    assert pnl > 0, f"Theta should help: pnl={pnl:.2f}"

    print("adjustments.py: all checks passed")


if __name__ == '__main__':
    _self_check()
