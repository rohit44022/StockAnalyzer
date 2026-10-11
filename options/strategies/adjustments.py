"""
Position adjustment rules: when and how to modify live positions.

Cohen (exits), Sinclair (stops + survival via actual P/L), Davey (discipline).
GA2 fix: BSM repricing replaces spot-change heuristic.
GA5 fix: Cohen's long-option exit rule hardened.
"""

from ..core import bsm


_ATR_NOISE_MULT = 1.5  # S10: moves < 1.5× ATR are noise


def check(position, spot, days_held=0, entry_spot=None, dte=None, r=0.07,
          live_iv=None, atr_14=None):
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
    atr_14 : float or None — 14-day ATR for noise filter (S10)

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

    # T10: barrier proximity — warn when spot nears a short strike
    recs.extend(_barrier_rules(position, spot))

    # S10: ATR noise filter — downgrade non-emergency recs if move < 1.5× ATR
    if atr_14 and entry_spot and entry_spot > 0:
        recs = _atr_filter(recs, spot, entry_spot, atr_14)

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


def _barrier_rules(position, spot):
    """T10: Taleb — warn when spot approaches short strikes (gamma acceleration zone)."""
    recs = []
    if spot <= 0:
        return recs
    for leg in position.get('legs', []):
        if leg.get('action') != 'SELL':
            continue
        strike = leg.get('strike')
        if not strike:
            continue
        dist = abs(strike - spot) / spot
        otype = leg.get('option_type', '')
        if dist < 0.005:
            recs.append({'action': 'close', 'urgency': 1,
                         'reason': f'Barrier breach: spot {dist:.1%} from short {otype} {strike}'})
        elif dist < 0.015:
            recs.append({'action': 'adjust', 'urgency': 2,
                         'reason': f'Barrier approach: spot {dist:.1%} from short {otype} {strike}'})
    return recs


def _general_rules(position, days_held):
    recs = []
    if days_held > 30:
        recs.append({'action': 'review', 'urgency': 3,
                     'reason': f'Held {days_held} days — review if thesis still valid'})
    return recs


def _atr_filter(recs, spot, entry_spot, atr_14):
    """S10: Sebastian — downgrade non-emergency adjustments if move < 1.5× ATR (noise)."""
    move = abs(spot - entry_spot)
    if move >= _ATR_NOISE_MULT * atr_14:
        return recs
    filtered = []
    for r in recs:
        if r.get('urgency', 3) <= 1:
            filtered.append(r)
        else:
            r = r.copy()
            r['urgency'] = 3
            r['reason'] += f' [ATR: move {move:.0f} < {_ATR_NOISE_MULT}×ATR {atr_14:.0f}]'
            filtered.append(r)
    return filtered


def should_defer(rec, signal_days=0):
    """S6: Sebastian Ch.12 — require 2 of 3 consecutive signal days before non-emergency adjustment.
    Caller tracks signal_days in trade metadata."""
    if rec.get('urgency', 3) <= 1:
        return False
    return signal_days < 2


def liquidity_alert(legs, chain_df=None):
    """T6: warn if bid-ask spread is abnormally wide on short legs."""
    if chain_df is None or chain_df.empty:
        return []
    recs = []
    for leg in legs:
        if leg.get('action') != 'SELL':
            continue
        strike = leg.get('strike')
        otype = leg.get('option_type')
        match = chain_df[
            (chain_df['strike'] == strike) & (chain_df['option_type'] == otype)
        ]
        if match.empty:
            continue
        row = match.iloc[0]
        bid = row.get('bid', 0) if 'bid' in row.index else 0
        ask = row.get('ask', 0) if 'ask' in row.index else 0
        if bid > 0 and ask > 0:
            spread_pct = (ask - bid) / ((bid + ask) / 2)
            if spread_pct > 0.10:
                recs.append({
                    'action': 'review', 'urgency': 2,
                    'reason': f'Liquidity hole: {otype} {strike} spread {spread_pct:.1%} — exit costly'
                })
    return recs


def adjustment_gate(adjustment_count, max_adjustments=3):
    """S8: Sebastian Ch.12 — hard cap on adjustments per trade.
    Returns (allowed, warning_or_None)."""
    if adjustment_count >= max_adjustments:
        return False, f'Over-adjustment: {adjustment_count} adjustments ≥ {max_adjustments} — close instead'
    if adjustment_count >= max_adjustments - 1:
        return True, f'{adjustment_count} adjustments — next triggers forced exit'
    return True, None


def adjustment_priority(strategy, breach_side):
    """S11: Sebastian Ch.9 — cascade order for iron condor adjustments.
    Returns ordered list; caller tries each until one is feasible."""
    if 'iron' not in strategy and 'condor' not in strategy:
        return ['close']
    if breach_side == 'upside':
        return ['kite_spread', 'ratio_spread', 'call_spread', 'add_margin', 'close']
    return ['ratio_put', 'put_spread', 'add_margin', 'close']


def suggest_roll(position, chain_df, spot, r=0.07, lot_size=None):
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

    # S10: ATR noise filter — small move should downgrade urgency
    pos2 = {'strategy': 'iron_condor', 'net_premium': 5.0, 'legs': []}
    recs = check(pos2, spot=24100, entry_spot=24000, dte=10, atr_14=200)
    assert all(r['urgency'] >= 3 or r['urgency'] <= 1 for r in recs if 'ATR' in r.get('reason', ''))

    # S6: should_defer
    assert not should_defer({'urgency': 1}, signal_days=0)
    assert should_defer({'urgency': 2}, signal_days=1)
    assert not should_defer({'urgency': 2}, signal_days=2)

    # S8: adjustment gate
    ok, _ = adjustment_gate(0)
    assert ok
    ok, _ = adjustment_gate(2)
    assert ok  # allowed but warned
    ok, reason = adjustment_gate(3)
    assert not ok and 'close' in reason

    # S11: adjustment priority
    pri = adjustment_priority('iron_condor', 'upside')
    assert pri[0] == 'kite_spread' and pri[-1] == 'close'
    pri = adjustment_priority('iron_condor', 'downside')
    assert pri[0] == 'ratio_put'

    # T10: barrier proximity
    pos3 = {'strategy': 'iron_condor', 'legs': [
        {'strike': 24100, 'option_type': 'CE', 'action': 'SELL'},
    ]}
    recs = _barrier_rules(pos3, 24090)
    assert any(r['urgency'] == 1 for r in recs), "Should urgency=1 within 0.5%"
    recs = _barrier_rules(pos3, 23700)
    assert not recs, "No barrier warning when far away"

    print("adjustments.py: all checks passed")


if __name__ == '__main__':
    _self_check()
