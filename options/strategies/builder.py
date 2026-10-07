"""
Position builder: resolve strategy templates to concrete positions.

Takes a strategy from registry + live chain data, picks actual strikes
with liquidity filters, estimates costs via cost_model.
"""

from collections import Counter
from . import registry
from ..core import bsm, cost_model, payoff


def build(strategy_key, chain_df, spot, r=0.07,
          lot_size=65, expiry_years=None, config=None):
    """
    Build a concrete position from a strategy template.

    Parameters
    ----------
    strategy_key : str
    chain_df : DataFrame — strike, option_type, expiry_years, ltp/bid/ask, oi, iv
    spot : float
    r : float — risk-free rate
    lot_size : int — Nifty=65, BankNifty=30
    expiry_years : float — override; else nearest expiry in chain
    config : dict — min_oi (1000), max_spread_pct (0.05), offset_scale (1.0)

    Returns
    -------
    dict with strategy, legs, net_premium, max_profit, max_loss, breakevens,
    cost_estimate, warnings.  None if can't build.
    """
    strat = registry.get(strategy_key)
    if strat is None:
        return None

    # Cohen: OI ≥ 500, bid-ask < 4%
    cfg = {'min_oi': 500, 'max_spread_pct': 0.04, 'offset_scale': 1.0}
    if config:
        cfg.update(config)

    interval = _infer_interval(chain_df)
    if interval <= 0:
        return None

    expiries = sorted(chain_df['expiry_years'].unique())
    if not expiries:
        return None
    near_exp = expiries[0]
    far_exp = expiries[1] if len(expiries) > 1 else near_exp
    if expiry_years is not None:
        near_exp = expiry_years

    # Calendar spreads need distinct expiries — reject if only one
    needs_far = any(s.expiry == 'far' for s in strat.legs)
    if needs_far and abs(near_exp - far_exp) < 0.001:
        return None

    atm = _atm_strike(chain_df, spot)
    legs = []
    warnings = []

    for spec in strat.legs:
        exp = near_exp if spec.expiry == 'near' else far_exp
        offset = int(spec.strike_offset * cfg['offset_scale'])
        target_strike = atm + offset * interval

        exp_chain = chain_df[
            (abs(chain_df['expiry_years'] - exp) < 0.001) &
            (chain_df['option_type'] == spec.option_type)
        ]
        if exp_chain.empty:
            warnings.append(f'No {spec.option_type} data for expiry {exp:.4f}')
            return None

        idx = (exp_chain['strike'] - target_strike).abs().idxmin()
        row = exp_chain.loc[idx]
        strike = float(row['strike'])

        oi = row.get('oi', 0) if 'oi' in row.index else 0
        if oi < cfg['min_oi']:
            warnings.append(f'Low OI at {spec.option_type} {strike}: {oi}')

        bid = row.get('bid', 0) if 'bid' in row.index else 0
        ask = row.get('ask', 0) if 'ask' in row.index else 0
        ltp = row.get('ltp', 0) if 'ltp' in row.index else 0

        if bid > 0 and ask > 0:
            mid = (bid + ask) / 2
            spread_pct = (ask - bid) / mid if mid > 0 else 1.0
            if spread_pct > cfg['max_spread_pct']:
                warnings.append(f'Wide spread at {spec.option_type} {strike}: {spread_pct:.1%}')
            premium = mid
        else:
            premium = max(ltp, 0.05)

        iv = row.get('iv', 0.15) if 'iv' in row.index else 0.15
        delta = row.get('delta', None) if 'delta' in row.index else None
        if delta is None and iv > 0 and exp > 0:
            g = bsm.bsm_greeks(spot, strike, exp, r, iv, spec.option_type)
            delta = g['delta']

        leg = {
            'strike': strike,
            'option_type': spec.option_type,
            'action': spec.action,
            'premium': float(premium),
            'qty': 1,
            'iv': float(iv),
            'delta': float(delta) if delta is not None else None,
            'oi': int(oi),
            'expiry_years': float(exp),
        }
        for _ in range(spec.qty):
            legs.append(leg.copy())

    net_premium = sum(
        l['premium'] * (1 if l['action'] == 'SELL' else -1)
        for l in legs
    )

    payoff_legs = [
        {'strike': l['strike'], 'option_type': l['option_type'],
         'action': l['action'], 'premium': l['premium'], 'qty': 1}
        for l in legs
    ]
    summary = payoff.strategy_summary(payoff_legs, lot_size=lot_size)

    cost_legs = [{'premium': l['premium'], 'action': l['action']} for l in legs]
    cost_est = cost_model.round_trip_cost(cost_legs, lot_size=lot_size)

    max_profit = summary['max_profit']
    max_loss = summary['max_loss']

    # GA4: Cohen — equal wing widths for butterflies/condors
    warnings.extend(_validate_wings(strategy_key, legs))

    # GA1: flag when registry says 'limited' but actual risk is extreme
    if strat.max_loss == 'limited' and max_profit and max_profit > 0:
        if max_loss is not None and max_loss < 0 and max_loss != float('-inf'):
            risk_ratio = abs(max_loss) / max_profit
            if risk_ratio > 10:
                warnings.append(
                    f'Extreme risk ratio {risk_ratio:.0f}:1 — '
                    f'max_loss=₹{abs(max_loss):.0f} vs max_profit=₹{max_profit:.0f}')

    # Jade lizard: credit must exceed call-spread width for no-upside-risk
    if strategy_key == 'jade_lizard':
        ce_sells = [l for l in legs if l['option_type'] == 'CE' and l['action'] == 'SELL']
        ce_buys = [l for l in legs if l['option_type'] == 'CE' and l['action'] == 'BUY']
        if ce_sells and ce_buys:
            call_width = ce_buys[0]['strike'] - ce_sells[0]['strike']
            if net_premium < call_width:
                warnings.append(
                    f'Credit ({net_premium:.2f}) < call spread width ({call_width:.0f}) '
                    f'— upside risk exists')

    return {
        'strategy': strategy_key,
        'legs': legs,
        'net_premium': round(net_premium, 2),
        'max_profit': max_profit,
        'max_loss': max_loss,
        'breakevens': summary['breakevens'],
        'cost_estimate': cost_est,
        'net_premium_after_cost': round(
            net_premium * lot_size - cost_est.get('total', 0), 2),
        'warnings': warnings,
    }


def _infer_interval(chain_df):
    strikes = sorted(chain_df['strike'].unique())
    if len(strikes) < 2:
        return 50
    diffs = [strikes[i + 1] - strikes[i]
             for i in range(min(20, len(strikes) - 1))]
    return Counter(diffs).most_common(1)[0][0]


def _atm_strike(chain_df, spot):
    strikes = chain_df['strike'].unique()
    return float(min(strikes, key=lambda k: abs(k - spot)))


def strike_selection_by_dte(dte, target_days=None, direction='buy'):
    """
    Varsity Ch.22: optimal strike moneyness based on DTE and expected
    move timing.  Returns one of: 'deep_itm', 'itm', 'slight_itm',
    'atm', 'slight_otm', 'otm', 'far_otm'.

    Parameters
    ----------
    dte : int — days to expiry
    target_days : int or None — how many days until you expect the move.
        None = at expiry.
    direction : str — 'buy' for long options, 'sell' for short options.
        Sellers always want ATM or slight OTM (Sinclair Ch.6: ATM
        captures most variance premium).

    The table (Varsity Ch.22):
      >15 DTE + fast move (≤5d)    → far OTM
      >15 DTE + medium (≤15d)      → slight OTM / ATM
      >15 DTE + slow (≤25d)        → slight ITM
      >15 DTE + at expiry           → ITM
      <15 DTE + same day            → far OTM
      <15 DTE + fast (≤5d)          → slight OTM
      <15 DTE + medium (≤10d)      → ATM / slight ITM
      <15 DTE + at expiry           → ITM

    Key principle: fast move + time = OTM (gamma); slow move or near
    expiry = ITM (theta kills OTM).
    """
    if direction == 'sell':
        return 'atm'

    if target_days is None:
        target_days = dte

    if dte > 15:
        if target_days <= 5:
            return 'far_otm'
        elif target_days <= 15:
            return 'slight_otm'
        elif target_days <= 25:
            return 'slight_itm'
        else:
            return 'itm'
    else:
        if target_days <= 1:
            return 'far_otm'
        elif target_days <= 5:
            return 'slight_otm'
        elif target_days <= 10:
            return 'atm'
        else:
            return 'itm'


# moneyness label → strike offset in intervals from ATM
MONEYNESS_OFFSETS = {
    'deep_itm': -4,
    'itm': -2,
    'slight_itm': -1,
    'atm': 0,
    'slight_otm': 1,
    'otm': 2,
    'far_otm': 3,
}


def resolve_strike_for_moneyness(moneyness, spot, interval, option_type):
    """Convert moneyness label to actual strike price.
    For puts, ITM means strike > spot, so offsets flip."""
    offset = MONEYNESS_OFFSETS.get(moneyness, 0)
    if option_type == 'PE':
        offset = -offset
    return spot + offset * interval


def _validate_wings(strat_key, legs):
    """Cohen: equal strike spacing for butterflies/condors."""
    warnings = []
    if strat_key in ('iron_condor', 'iron_butterfly'):
        pe = sorted([l for l in legs if l['option_type'] == 'PE'],
                    key=lambda l: l['strike'])
        ce = sorted([l for l in legs if l['option_type'] == 'CE'],
                    key=lambda l: l['strike'])
        if len(pe) == 2 and len(ce) == 2:
            put_w = pe[1]['strike'] - pe[0]['strike']
            call_w = ce[1]['strike'] - ce[0]['strike']
            if abs(put_w - call_w) > 1:
                warnings.append(
                    f'Unequal wings: put={put_w}, call={call_w} — '
                    f'Cohen: need equal spacing')
    elif strat_key == 'long_butterfly':
        sells = [l for l in legs if l['action'] == 'SELL']
        buy_strikes = sorted(set(l['strike'] for l in legs if l['action'] == 'BUY'))
        if sells and len(buy_strikes) == 2:
            center = sells[0]['strike']
            low = center - buy_strikes[0]
            high = buy_strikes[1] - center
            if abs(low - high) > 1:
                warnings.append(
                    f'Unequal wings: low={low}, high={high} — '
                    f'Cohen: need equal spacing')
    return warnings


def _self_check():
    import pandas as pd
    import datetime

    spot = 24000
    rows = []
    for strike in range(23500, 24501, 50):
        for otype in ['CE', 'PE']:
            m = strike / spot
            iv = 0.14 + (max(0, m - 1) * 0.3 if otype == 'CE'
                         else max(0, 1 - m) * 0.3)
            ltp = bsm.bsm_price(spot, strike, 7 / 365, 0.07, iv, otype)
            g = bsm.bsm_greeks(spot, strike, 7 / 365, 0.07, iv, otype)
            rows.append({
                'strike': strike, 'option_type': otype,
                'expiry': datetime.date(2026, 10, 13),
                'expiry_years': 7 / 365,
                'ltp': ltp, 'bid': ltp * 0.98, 'ask': ltp * 1.02,
                'oi': 50000, 'volume': 10000,
                'iv': iv, 'delta': g['delta'],
            })
    chain = pd.DataFrame(rows)

    r1 = build('iron_condor', chain, spot, lot_size=65)
    assert r1 is not None
    assert r1['strategy'] == 'iron_condor'
    assert len(r1['legs']) == 4
    assert r1['net_premium'] > 0, "Iron condor should be credit"
    assert r1['max_loss'] < 0
    assert r1['cost_estimate']['total'] > 0

    r2 = build('short_straddle', chain, spot, lot_size=65)
    assert r2 is not None
    assert len(r2['legs']) == 2
    assert r2['net_premium'] > 0

    r3 = build('long_call', chain, spot, lot_size=65)
    assert r3 is not None
    assert r3['net_premium'] < 0, "Long call is debit"

    r4 = build('long_butterfly', chain, spot, lot_size=65)
    assert r4 is not None
    assert len(r4['legs']) == 4  # 1 + 2 + 1

    print("builder.py: all checks passed")


if __name__ == '__main__':
    _self_check()
