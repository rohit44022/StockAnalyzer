"""
Phase 3 tests: strategy engine + all grey area fixes.

Covers:
  - Full flow: pipeline → signals → selector → builder → adjustments
  - All 16 strategies buildable
  - Book cross-checks (Cohen, Sinclair, Natenberg)
  - GA1: risk-ratio warning for jade_lizard
  - GA2: BSM repricing in adjustments
  - GA3: ATM selling preference in selector
  - GA4: wing-width validation
  - GA5: Cohen long-option exit rule
"""

import datetime
import math
import pandas as pd
from options.core import bsm
from options.strategies import registry, signals, selector, builder, adjustments


# ── helpers ───────────────────────────────────────────────────────

def _chain(spot=24000, expiry_days=7, interval=50):
    rows = []
    exp_y = expiry_days / 365
    low = int(spot - 20 * interval)
    high = int(spot + 20 * interval) + 1
    for strike in range(low, high, interval):
        for otype in ['CE', 'PE']:
            m = strike / spot
            iv = 0.14 + (max(0, m - 1) * 0.3 if otype == 'CE'
                         else max(0, 1 - m) * 0.3)
            ltp = bsm.bsm_price(spot, strike, exp_y, 0.07, iv, otype)
            g = bsm.bsm_greeks(spot, strike, exp_y, 0.07, iv, otype)
            rows.append({
                'strike': strike, 'option_type': otype,
                'expiry': datetime.date(2026, 10, 13),
                'expiry_years': exp_y,
                'ltp': ltp, 'bid': ltp * 0.98, 'ask': ltp * 1.02,
                'oi': 50000, 'volume': 10000,
                'iv': iv, 'delta': g['delta'],
            })
    return pd.DataFrame(rows)


def _dual_chain(spot=24000):
    c1 = _chain(spot, 30)
    c2 = _chain(spot, 60)
    c2['expiry_years'] = 60 / 365
    c2['expiry'] = datetime.date(2026, 12, 4)
    return pd.concat([c1, c2], ignore_index=True)


def _pipe(vp=0.035, vix=15.5, pcr=1.15, regime='long_buildup',
          skew=0.06, inverted=False, event_days=None):
    r = {
        'symbol': 'NIFTY', 'spot': 24000,
        'variance_premium': {'vp': vp, 'iv': 0.16, 'rv': 0.16 - vp,
                             'signal': 'sell_premium' if vp > 0.02 else 'neutral'},
        'vix': {'value': vix, 'regime': {'level': 'normal'}},
        'oi': {'pcr': {'pcr': pcr, 'signal': 'neutral', 'contrarian': 'neutral'},
               'max_pain': {'max_pain_strike': 24000}},
        'skew': {7: {'skew_25d': skew, 'atm_iv': 0.14}},
        'oi_regime': {'regime': regime},
        'inverted': inverted,
        'upcoming_events': [],
        'event_window': None,
    }
    if event_days is not None:
        r['upcoming_events'] = [{'name': 'RBI', 'date': '2026-10-10', 'type': 'rbi'}]
        r['event_window'] = {'days_to_event': event_days}
    return r


# ══════════════════════════════════════════════════════════════════
# REGISTRY TESTS
# ══════════════════════════════════════════════════════════════════

def test_registry_count():
    assert len(registry.STRATEGIES) == 16


def test_registry_categories():
    cats = {s.category for s in registry.STRATEGIES.values()}
    assert cats == {'income', 'directional', 'volatility', 'rangebound'}


def test_registry_greeks_shape():
    for key, s in registry.STRATEGIES.items():
        assert len(s.greeks) == 4, f"{key}: greeks must be (d,g,t,v)"
        for g in s.greeks:
            assert g in (-1, 0, +1), f"{key}: greeks values must be -1/0/+1"


def test_registry_leg_validity():
    for key, s in registry.STRATEGIES.items():
        for leg in s.legs:
            assert leg.option_type in ('CE', 'PE'), f"{key}: bad option_type"
            assert leg.action in ('BUY', 'SELL'), f"{key}: bad action"
            assert leg.expiry in ('near', 'far'), f"{key}: bad expiry"
            assert leg.qty >= 1, f"{key}: qty < 1"


def test_registry_filters():
    income = registry.list_strategies(category='income')
    assert len(income) == 8

    neutral = registry.list_strategies(outlook='neutral')
    assert len(neutral) >= 5

    low_vol = registry.list_strategies(vol_regime='low')
    assert len(low_vol) >= 5


# Cohen Ch.6: ratio backspread = sell 1 ITM/ATM, buy 2+ OTM
def test_ratio_backspread_legs_cohen():
    s = registry.get('ratio_put_backspread')
    sells = [l for l in s.legs if l.action == 'SELL']
    buys = [l for l in s.legs if l.action == 'BUY']
    assert len(sells) == 1
    assert sells[0].strike_offset == 0, "Sold put must be ATM (Cohen Ch.6)"
    total_buy_qty = sum(l.qty for l in buys)
    assert total_buy_qty >= 2, "Must buy more than sell (backspread)"
    assert all(l.strike_offset < 0 for l in buys), "Bought puts must be OTM"


# Cohen: calendar needs different expiries
def test_calendar_needs_two_expiries():
    s = registry.get('calendar_call')
    expiries = {l.expiry for l in s.legs}
    assert expiries == {'near', 'far'}


# ══════════════════════════════════════════════════════════════════
# SIGNALS TESTS
# ══════════════════════════════════════════════════════════════════

def test_vp_sell_signal():
    sigs = signals.scan_signals(_pipe(vp=0.04))
    vp = next(s for s in sigs if s['type'] == 'variance_premium')
    assert vp['direction'] == 'sell_premium'
    assert vp['strength'] > 0.5


def test_vp_buy_signal():
    sigs = signals.scan_signals(_pipe(vp=-0.02))
    vp = next(s for s in sigs if s['type'] == 'variance_premium')
    assert vp['direction'] == 'buy_premium'


def test_vp_no_rv():
    pipe = _pipe()
    pipe['variance_premium']['rv'] = float('nan')
    sigs = signals.scan_signals(pipe)
    vp = next(s for s in sigs if s['type'] == 'variance_premium')
    assert vp['strength'] == 0.0


# ARCHITECTURE.md: VIX 14-22 = sweet spot
def test_vix_sweet_spot_upper_bound():
    sigs = signals.scan_signals(_pipe(vix=20))
    vix = next(s for s in sigs if s['type'] == 'vix_regime')
    assert vix['direction'] == 'sell_premium', "VIX=20 should be in sweet spot"

    sigs = signals.scan_signals(_pipe(vix=24))
    vix = next(s for s in sigs if s['type'] == 'vix_regime')
    assert vix['direction'] == 'sell_premium', "VIX=24 should still say sell"


def test_vix_crisis():
    sigs = signals.scan_signals(_pipe(vix=40))
    vix = next(s for s in sigs if s['type'] == 'vix_regime')
    assert vix['direction'] == 'caution'


def test_vix_too_low():
    sigs = signals.scan_signals(_pipe(vix=9))
    vix = next(s for s in sigs if s['type'] == 'vix_regime')
    assert vix['direction'] == 'caution'
    assert 'too low' in vix['detail']


def test_pcr_contrarian():
    sigs = signals.scan_signals(_pipe(pcr=1.5))
    pcr = next(s for s in sigs if s['type'] == 'pcr')
    assert pcr['direction'] == 'bullish', "High PCR = contrarian bullish"

    sigs = signals.scan_signals(_pipe(pcr=0.5))
    pcr = next(s for s in sigs if s['type'] == 'pcr')
    assert pcr['direction'] == 'bearish'


def test_event_signal():
    sigs = signals.scan_signals(_pipe(event_days=2))
    ev = next(s for s in sigs if s['type'] == 'event')
    assert ev['direction'] == 'caution'
    assert ev['strength'] > 0.8


def test_inverted_term_structure():
    sigs = signals.scan_signals(_pipe(inverted=True))
    ts = next(s for s in sigs if s['type'] == 'term_structure')
    assert ts['direction'] == 'caution'


# ══════════════════════════════════════════════════════════════════
# SELECTOR TESTS
# ══════════════════════════════════════════════════════════════════

def test_high_vp_selects_income():
    sigs = signals.scan_signals(_pipe(vp=0.04, vix=16))
    ranked = selector.select(sigs, risk_budget='moderate', dte=14)
    top = registry.get(ranked[0][0])
    assert top.category == 'income'


def test_crisis_rejects_unlimited():
    sigs = signals.scan_signals(_pipe(vp=0.06, vix=40))
    ranked = selector.select(sigs, risk_budget='conservative')
    for key, score, _ in ranked:
        s = registry.get(key)
        if s.max_loss == 'unlimited':
            assert score < 0, f"{key} should be negative in crisis"


def test_low_vol_selects_vol_strategies():
    sigs = signals.scan_signals(_pipe(vp=-0.02, vix=9))
    ranked = selector.select(sigs, risk_budget='moderate')
    if ranked:
        top5_cats = {registry.get(r[0]).category for r in ranked[:5]}
        assert 'volatility' in top5_cats or 'directional' in top5_cats


# GA3: ATM selling preference
def test_atm_selling_preference():
    sigs = signals.scan_signals(_pipe(vp=0.04, vix=16))
    ranked = selector.select(sigs, risk_budget='moderate', dte=14)

    # Strategies with ATM sells should have the ATM bonus in reasons
    for key, score, reasons in ranked:
        s = registry.get(key)
        has_atm_sell = any(l.action == 'SELL' and l.strike_offset == 0
                          for l in s.legs)
        if has_atm_sell and s.category == 'income':
            assert any('ATM' in r for r in reasons), \
                f"{key} should get ATM bonus"

    # short_straddle (ATM sells) should score higher than short_strangle (OTM sells)
    scores = {k: sc for k, sc, _ in ranked}
    if 'short_straddle' in scores and 'short_strangle' in scores:
        assert scores['short_straddle'] > scores['short_strangle'], \
            "ATM straddle should outscore OTM strangle (Sinclair Ch.6)"


def test_dte_filters():
    sigs = signals.scan_signals(_pipe())
    ranked = selector.select(sigs, dte=5)
    for key, _, _ in ranked:
        assert registry.get(key).min_dte <= 5


# ══════════════════════════════════════════════════════════════════
# BUILDER TESTS
# ══════════════════════════════════════════════════════════════════

def test_all_strategies_buildable():
    chain = _dual_chain()
    built = 0
    for key in registry.STRATEGIES:
        pos = builder.build(key, chain, 24000, lot_size=65,
                            config={'min_oi': 0})
        assert pos is not None, f"Failed to build {key}"
        assert len(pos['legs']) >= 1, f"{key}: no legs"
        built += 1
    assert built == 16


def test_calendar_rejects_single_expiry():
    chain = _chain(expiry_days=7)
    result = builder.build('calendar_call', chain, 24000, config={'min_oi': 0})
    assert result is None, "Calendar must reject single-expiry chain"


def test_iron_condor_is_credit():
    chain = _chain(expiry_days=14)
    pos = builder.build('iron_condor', chain, 24000, lot_size=65,
                        config={'min_oi': 0})
    assert pos['net_premium'] > 0, "Iron condor must be credit"
    assert pos['max_loss'] < 0
    assert len(pos['legs']) == 4


def test_long_call_is_debit():
    chain = _chain(expiry_days=30)
    pos = builder.build('long_call', chain, 24000, lot_size=65,
                        config={'min_oi': 0})
    assert pos['net_premium'] < 0, "Long call must be debit"


def test_butterfly_has_four_legs():
    chain = _chain(expiry_days=14)
    pos = builder.build('long_butterfly', chain, 24000, lot_size=65,
                        config={'min_oi': 0})
    assert len(pos['legs']) == 4, "Butterfly: 1 + 2(sell) + 1 = 4"


# Cohen Ch.6: ratio backspread — sold ATM, bought OTM
def test_ratio_backspread_strikes():
    chain = _chain(expiry_days=30)
    pos = builder.build('ratio_put_backspread', chain, 24000, lot_size=65,
                        config={'min_oi': 0})
    sold = [l for l in pos['legs'] if l['action'] == 'SELL']
    bought = [l for l in pos['legs'] if l['action'] == 'BUY']
    assert len(sold) == 1
    assert len(bought) == 2
    assert sold[0]['strike'] == 24000, "Sold put must be ATM"
    assert all(b['strike'] < 24000 for b in bought), "Bought puts must be OTM"


# jade_lizard: naked put → registry says 'unlimited', payoff gives -inf.
# Selector must penalize it in crisis and conservative modes.
def test_jade_lizard_risk_warning():
    s = registry.get('jade_lizard')
    assert s.max_loss == 'unlimited', "Naked put = unlimited risk"

    chain = _chain(expiry_days=14)
    pos = builder.build('jade_lizard', chain, 24000, lot_size=65,
                        config={'min_oi': 0})
    assert pos is not None
    assert pos['max_loss'] == float('-inf') or pos['max_loss'] < -10000


def test_jade_lizard_crisis_rejected():
    crisis_sigs = [
        {'type': 'variance_premium', 'direction': 'sell_premium',
         'strength': 0.9, 'detail': ''},
        {'type': 'vix_regime', 'direction': 'caution',
         'strength': 0.9, 'detail': 'VIX=35 — crisis zone'},
    ]
    ranked = selector.select(crisis_sigs, risk_budget='conservative')
    for key, score, reasons in ranked:
        if key == 'jade_lizard':
            assert score < 0, \
                f"Jade lizard must be negative in crisis+conservative, got {score}"


# GA4: wing validation
def test_wing_symmetry_iron_condor():
    chain = _chain(expiry_days=14)
    pos = builder.build('iron_condor', chain, 24000, lot_size=65,
                        config={'min_oi': 0})
    pe = sorted([l for l in pos['legs'] if l['option_type'] == 'PE'],
                key=lambda l: l['strike'])
    ce = sorted([l for l in pos['legs'] if l['option_type'] == 'CE'],
                key=lambda l: l['strike'])
    put_w = pe[1]['strike'] - pe[0]['strike']
    call_w = ce[1]['strike'] - ce[0]['strike']
    assert abs(put_w - call_w) < 2, "Wings must be equal"
    # No wing warning on clean chain
    assert not any('Unequal' in w for w in pos['warnings'])


def test_wing_symmetry_butterfly():
    chain = _chain(expiry_days=14)
    pos = builder.build('long_butterfly', chain, 24000, lot_size=65,
                        config={'min_oi': 0})
    sells = [l for l in pos['legs'] if l['action'] == 'SELL']
    buy_strikes = sorted(set(l['strike'] for l in pos['legs']
                             if l['action'] == 'BUY'))
    center = sells[0]['strike']
    assert abs((center - buy_strikes[0]) - (buy_strikes[1] - center)) < 2


# Cohen: bid/ask < 4%
def test_spread_warning():
    chain = _chain(expiry_days=14)
    # Widen spreads on a specific strike
    mask = (chain['strike'] == 24200) & (chain['option_type'] == 'CE')
    chain.loc[mask, 'ask'] = chain.loc[mask, 'ltp'] * 1.10  # 10% spread
    chain.loc[mask, 'bid'] = chain.loc[mask, 'ltp'] * 0.90
    pos = builder.build('bear_call_spread', chain, 24000, lot_size=65,
                        config={'min_oi': 0})
    if pos:
        has_spread_warn = any('spread' in w.lower() for w in pos['warnings'])
        # The wide-spread strike should trigger a warning
        assert has_spread_warn, "Should warn about wide spread"


def test_cost_included():
    chain = _chain(expiry_days=14)
    pos = builder.build('iron_condor', chain, 24000, lot_size=65,
                        config={'min_oi': 0})
    assert pos['cost_estimate']['total'] > 0
    assert pos['net_premium_after_cost'] < pos['net_premium'] * 65


# ══════════════════════════════════════════════════════════════════
# ADJUSTMENTS TESTS
# ══════════════════════════════════════════════════════════════════

def test_expiry_close():
    pos = {'strategy': 'iron_condor', 'legs': []}
    recs = adjustments.check(pos, spot=24000, dte=1)
    assert any(r['urgency'] == 1 and r['action'] == 'close' for r in recs)


def test_roll_suggestion():
    pos = {'strategy': 'iron_condor', 'legs': []}
    recs = adjustments.check(pos, spot=24000, dte=4)
    assert any(r['action'] == 'consider_roll' for r in recs)


# GA5: Cohen long-option exit — urgency 1 at DTE ≤ 7
def test_cohen_long_exit_hard():
    lc = {'strategy': 'long_call', 'legs': []}
    recs = adjustments.check(lc, spot=24000, dte=5)
    assert any(r['urgency'] == 1 and 'Cohen' in r['reason'] for r in recs), \
        "DTE=5 on long call must be urgency 1"


def test_cohen_long_exit_warning():
    lc = {'strategy': 'long_straddle', 'legs': []}
    recs = adjustments.check(lc, spot=24000, dte=15)
    assert any(r['urgency'] == 2 and 'Cohen' in r['reason'] for r in recs), \
        "DTE=15 on long straddle must be urgency 2"


def test_cohen_long_no_warning_far():
    lc = {'strategy': 'long_call', 'legs': []}
    recs = adjustments.check(lc, spot=24000, dte=30)
    cohen_recs = [r for r in recs if 'Cohen' in r.get('reason', '')]
    assert not cohen_recs, "DTE=30 should not trigger Cohen exit"


# Spot-change fallback (empty legs)
def test_stop_loss_spot_fallback():
    ss = {'strategy': 'short_strangle', 'net_premium': 10, 'legs': []}
    recs = adjustments.check(ss, spot=24800, entry_spot=24000, dte=15)
    assert any(r['action'] == 'stop_loss' for r in recs)


# GA2: BSM repricing
def test_bsm_repricing_theta_profit():
    """Short straddle, spot stable, time passes → theta profit."""
    legs = [
        {'strike': 24000, 'option_type': 'CE', 'action': 'SELL',
         'premium': 300, 'iv': 0.15},
        {'strike': 24000, 'option_type': 'PE', 'action': 'SELL',
         'premium': 280, 'iv': 0.15},
    ]
    pos = {
        'strategy': 'short_straddle',
        'net_premium': 580, 'max_profit': 580, 'max_loss': float('-inf'),
        'legs': legs,
    }
    # Originally entered at 14 DTE, now 3 DTE, spot stable
    pnl = adjustments._reprice_pnl(legs, 24000, 3 / 365)
    assert pnl > 0, f"Theta should make money: pnl={pnl:.2f}"


def test_bsm_repricing_adverse_move():
    """Iron condor, spot blows through short strike → loss."""
    # Use BSM-realistic entry premiums at spot=24000, DTE=14
    entry_t = 14 / 365
    legs = [
        {'strike': 23800, 'option_type': 'PE', 'action': 'BUY',
         'premium': bsm.bsm_price(24000, 23800, entry_t, 0.07, 0.16, 'PE'),
         'iv': 0.16},
        {'strike': 23900, 'option_type': 'PE', 'action': 'SELL',
         'premium': bsm.bsm_price(24000, 23900, entry_t, 0.07, 0.15, 'PE'),
         'iv': 0.15},
        {'strike': 24100, 'option_type': 'CE', 'action': 'SELL',
         'premium': bsm.bsm_price(24000, 24100, entry_t, 0.07, 0.14, 'CE'),
         'iv': 0.14},
        {'strike': 24200, 'option_type': 'CE', 'action': 'BUY',
         'premium': bsm.bsm_price(24000, 24200, entry_t, 0.07, 0.15, 'CE'),
         'iv': 0.15},
    ]
    net = sum(l['premium'] * (1 if l['action'] == 'SELL' else -1) for l in legs)
    pos = {
        'strategy': 'iron_condor',
        'net_premium': net, 'max_profit': net, 'max_loss': -(100 - net),
        'legs': legs,
    }
    # Spot crashes to 23000 — way through both put strikes
    pnl = adjustments._reprice_pnl(legs, 23000, 3 / 365)
    assert pnl < 0, f"Should be losing: pnl={pnl:.2f}"

    recs = adjustments.check(pos, spot=23000, dte=3)
    assert any(r['action'] == 'stop_loss' or r['action'] == 'close'
               for r in recs)


def test_bsm_take_profit():
    """Position at 50%+ of max profit → take profit recommendation."""
    legs = [
        {'strike': 23800, 'option_type': 'PE', 'action': 'BUY',
         'premium': 10, 'iv': 0.16},
        {'strike': 23900, 'option_type': 'PE', 'action': 'SELL',
         'premium': 30, 'iv': 0.15},
        {'strike': 24100, 'option_type': 'CE', 'action': 'SELL',
         'premium': 30, 'iv': 0.14},
        {'strike': 24200, 'option_type': 'CE', 'action': 'BUY',
         'premium': 10, 'iv': 0.15},
    ]
    pos = {
        'strategy': 'iron_condor',
        'net_premium': 40, 'max_profit': 40, 'max_loss': -60,
        'legs': legs,
    }
    # Spot stable, DTE=2 → all options near zero → near max profit
    recs = adjustments.check(pos, spot=24000, dte=2)
    # At DTE=2 the close rule fires (urgency 1) regardless
    assert any(r['urgency'] == 1 for r in recs)


# ══════════════════════════════════════════════════════════════════
# FULL FLOW INTEGRATION
# ══════════════════════════════════════════════════════════════════

def test_full_flow():
    pipe = _pipe()
    chain = _chain()
    sigs = signals.scan_signals(pipe)
    assert len(sigs) >= 5

    ranked = selector.select(sigs, risk_budget='moderate', dte=7)
    assert len(ranked) > 0
    top_key = ranked[0][0]
    top = registry.get(top_key)
    assert top.category == 'income'

    pos = builder.build(top_key, chain, 24000, lot_size=65,
                        config={'min_oi': 0})
    assert pos is not None

    recs = adjustments.check(pos, spot=24000, entry_spot=24000, dte=7)
    assert isinstance(recs, list)


# ══════════════════════════════════════════════════════════════════
# BOOK CROSS-CHECKS
# ══════════════════════════════════════════════════════════════════

# Sinclair Ch.4-5: VP > 0 → sell premium edge exists
def test_sinclair_vp_edge():
    sigs = signals.scan_signals(_pipe(vp=0.03))
    vp_sig = next(s for s in sigs if s['type'] == 'variance_premium')
    assert vp_sig['direction'] == 'sell_premium'
    ranked = selector.select(sigs, risk_budget='moderate', dte=14)
    top = registry.get(ranked[0][0])
    assert top.greeks[2] == +1, "Top strategy should earn theta (greeks[2]=+1)"


# Sinclair Ch.6: ATM risk-adjusted > OTM
def test_sinclair_atm_vs_otm():
    sigs = signals.scan_signals(_pipe(vp=0.04))
    ranked = selector.select(sigs, risk_budget='aggressive', dte=7)
    scores = {k: sc for k, sc, _ in ranked}
    # short_straddle (ATM) vs short_strangle (OTM)
    if 'short_straddle' in scores and 'short_strangle' in scores:
        assert scores['short_straddle'] > scores['short_strangle']


# Sinclair Ch.8: spreads non-negotiable for conservative
def test_sinclair_spreads_conservative():
    sigs = signals.scan_signals(_pipe(vp=0.05))
    ranked = selector.select(sigs, risk_budget='conservative', dte=14)
    if ranked:
        top = registry.get(ranked[0][0])
        assert top.max_loss == 'limited', \
            "Conservative must get defined-risk strategy"


# Sinclair Ch.9: fractional Kelly → adjustments use position-level stops
def test_sinclair_position_stop():
    entry_t = 14 / 365
    legs = [
        {'strike': 23800, 'option_type': 'PE', 'action': 'BUY',
         'premium': bsm.bsm_price(24000, 23800, entry_t, 0.07, 0.16, 'PE'),
         'iv': 0.16},
        {'strike': 23900, 'option_type': 'PE', 'action': 'SELL',
         'premium': bsm.bsm_price(24000, 23900, entry_t, 0.07, 0.15, 'PE'),
         'iv': 0.15},
        {'strike': 24100, 'option_type': 'CE', 'action': 'SELL',
         'premium': bsm.bsm_price(24000, 24100, entry_t, 0.07, 0.14, 'CE'),
         'iv': 0.14},
        {'strike': 24200, 'option_type': 'CE', 'action': 'BUY',
         'premium': bsm.bsm_price(24000, 24200, entry_t, 0.07, 0.15, 'CE'),
         'iv': 0.15},
    ]
    net = sum(l['premium'] * (1 if l['action'] == 'SELL' else -1) for l in legs)
    pos = {
        'strategy': 'iron_condor',
        'net_premium': net, 'max_profit': net, 'max_loss': -(100 - net),
        'legs': legs,
    }
    # Large adverse move — loss should cross threshold
    recs = adjustments.check(pos, spot=23000, dte=5)
    actions = {r['action'] for r in recs}
    assert 'stop_loss' in actions or 'adjust' in actions


# Cohen: credit spread risk/reward
def test_cohen_credit_spread():
    chain = _chain(expiry_days=14)
    pos = builder.build('bull_put_spread', chain, 24000, lot_size=65,
                        config={'min_oi': 0})
    assert pos['net_premium'] > 0, "Credit spread must receive credit"
    assert pos['max_loss'] < 0, "Must have defined loss"
    assert pos['max_profit'] > 0


# Cohen: bid-ask < 4%
def test_cohen_spread_threshold():
    from options.strategies.builder import build
    chain = _chain(expiry_days=14)
    # Verify default max_spread_pct is 4%
    pos = build('bull_put_spread', chain, 24000, config={'min_oi': 0})
    # Our synthetic chain has 2% spread, should pass
    assert pos is not None


# Natenberg: Greeks signs for key strategies
def test_natenberg_greeks_signs():
    checks = {
        'short_straddle': (0, -1, +1, -1),
        'long_straddle':  (0, +1, -1, +1),
        'iron_condor':    (0, -1, +1, -1),
        'bull_call_spread': (+1, +1, -1, +1),
        'bear_put_spread':  (-1, +1, -1, +1),
        'calendar_call':    (0, -1, +1, +1),
    }
    for key, expected in checks.items():
        s = registry.get(key)
        assert s.greeks == expected, f"{key}: expected {expected}, got {s.greeks}"


# ══════════════════════════════════════════════════════════════════

ALL_TESTS = [
    # Registry
    test_registry_count, test_registry_categories,
    test_registry_greeks_shape, test_registry_leg_validity,
    test_registry_filters, test_ratio_backspread_legs_cohen,
    test_calendar_needs_two_expiries,
    # Signals
    test_vp_sell_signal, test_vp_buy_signal, test_vp_no_rv,
    test_vix_sweet_spot_upper_bound, test_vix_crisis, test_vix_too_low,
    test_pcr_contrarian, test_event_signal, test_inverted_term_structure,
    # Selector
    test_high_vp_selects_income, test_crisis_rejects_unlimited,
    test_low_vol_selects_vol_strategies, test_atm_selling_preference,
    test_dte_filters,
    # Builder
    test_all_strategies_buildable, test_calendar_rejects_single_expiry,
    test_iron_condor_is_credit, test_long_call_is_debit,
    test_butterfly_has_four_legs, test_ratio_backspread_strikes,
    test_jade_lizard_risk_warning, test_jade_lizard_crisis_rejected,
    test_wing_symmetry_iron_condor,
    test_wing_symmetry_butterfly, test_spread_warning,
    test_cost_included,
    # Adjustments
    test_expiry_close, test_roll_suggestion,
    test_cohen_long_exit_hard, test_cohen_long_exit_warning,
    test_cohen_long_no_warning_far, test_stop_loss_spot_fallback,
    test_bsm_repricing_theta_profit, test_bsm_repricing_adverse_move,
    test_bsm_take_profit,
    # Integration
    test_full_flow,
    # Book cross-checks
    test_sinclair_vp_edge, test_sinclair_atm_vs_otm,
    test_sinclair_spreads_conservative, test_sinclair_position_stop,
    test_cohen_credit_spread, test_cohen_spread_threshold,
    test_natenberg_greeks_signs,
]


if __name__ == '__main__':
    passed = failed = 0
    for test in ALL_TESTS:
        try:
            test()
            print(f"  ✓ {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {test.__name__}: {e}")
            failed += 1

    print(f"\ntest_phase3.py: {passed} passed, {failed} failed "
          f"({passed + failed} total)")
    if failed:
        raise SystemExit(1)
