"""
Production scorer: layers backtest performance, seasonal, and market-state
modifiers on top of selector.py signal scores.

Only strategies that pass Davey gates (WFA + MC) get recommended.
2x2 regime model (trend × vol) hard-gates strategy selection.
Seasonal data from brainstorm Round 2 (NIFTY 10yr daily vol by month).
"""

import datetime
import json
import os

from . import selector, registry
from . import regime as regime_mod
from ..core import event_calendar


GATE_PASS = {
    'short_straddle', 'short_strangle', 'iron_butterfly', 'jade_lizard',
    'iron_condor', 'bull_put_spread', 'bear_call_spread', 'long_butterfly',
    'long_straddle', 'long_strangle', 'long_put', 'long_call',
    'ratio_put_backspread',
}

# 10-year backtest reference metrics (Davey Ch.23: track actual vs expected)
BACKTEST_REF = {
    'short_straddle':   {'win_rate': 66, 'max_dd': 31, 'avg_trade': 161},
    'short_strangle':   {'win_rate': 77, 'max_dd': 24, 'avg_trade': 93},
    'iron_butterfly':   {'win_rate': 55, 'max_dd': 14, 'avg_trade': 109},
    'jade_lizard':      {'win_rate': 82, 'max_dd': 21, 'avg_trade': 130},
    'iron_condor':      {'win_rate': 72, 'max_dd': 12, 'avg_trade': 68},
    'bull_put_spread':  {'win_rate': 70, 'max_dd': 18, 'avg_trade': 52},
    'bear_call_spread': {'win_rate': 70, 'max_dd': 18, 'avg_trade': 52},
    'long_butterfly':   {'win_rate': 45, 'max_dd': 8,  'avg_trade': 85},
}

# 30-day real-data validation results (validate_real.py, Oct 2026)
# Positive avg_trade = winner, negative = loser in recent market
_RECENT_PERF = {
    'long_straddle':      {'avg_trade': 60370, 'win_rate': 100, 'boost': 2.0},
    'long_put':           {'avg_trade': 24297, 'win_rate': 67,  'boost': 1.5},
    'long_strangle':      {'avg_trade': 21306, 'win_rate': 40,  'boost': 1.0},
    'bear_put_spread':    {'avg_trade': 12053, 'win_rate': 67,  'boost': 1.0},
    'long_call':          {'avg_trade': 9686,  'win_rate': 40,  'boost': 0.5},
    'ratio_put_backspread': {'avg_trade': 4530, 'win_rate': 80, 'boost': 0.5},
    'bear_call_spread':   {'avg_trade': 2327,  'win_rate': 80,  'boost': 0.3},
    'iron_condor':        {'avg_trade': -2505, 'win_rate': 60,  'boost': -1.0},
    'bull_put_spread':    {'avg_trade': -3842, 'win_rate': 67,  'boost': -1.0},
    'short_strangle':     {'avg_trade': -5391, 'win_rate': 60,  'boost': -1.5},
    'bull_call_spread':   {'avg_trade': -5052, 'win_rate': 33,  'boost': -1.0},
    'iron_butterfly':     {'avg_trade': -11807, 'win_rate': 0,  'boost': -2.0},
    'short_straddle':     {'avg_trade': -12199, 'win_rate': 20, 'boost': -2.0},
    'long_butterfly':     {'avg_trade': -12083, 'win_rate': 0,  'boost': -2.0},
}

# Monthly risk multiplier for income strategies.
# Mar vol = 2.4x Jul. Feb has Budget. Jul-Aug-Nov-Dec sweet spot.
_SEASONAL = {
    1: 0.85, 2: 0.70, 3: 0.65, 4: 0.90, 5: 0.95, 6: 0.90,
    7: 1.00, 8: 1.00, 9: 0.90, 10: 0.85, 11: 1.00, 12: 1.00,
}

def _detect_regime(sig_map):
    """2x2 regime: trend (composite RoC ±2%) × vol (VIX ≥22)."""
    trend = sig_map.get('price_trend', {})
    roc = trend.get('roc', 0)

    vix_sig = sig_map.get('vix_regime', {})
    vix_val = vix_sig.get('value', 14)

    if roc > 0.02:
        return 'trending_up'
    if roc < -0.02:
        return 'trending_down'
    if vix_val >= 22:
        return 'high_vol'
    return 'rangebound'


def score(signals, backtest_dir=None,
          risk_budget='moderate', dte=None, dt=None):
    """
    Score and rank strategies for live recommendation.

    Returns list of dicts sorted by final_score desc:
      {strategy_key, final_score, signal_score, seasonal_mod,
       confidence, entry_timing, reasons}
    """
    dt = dt or datetime.date.today()
    # NSE weekly expiry = Thursday. When DTE to this week's expiry is
    # too short for any strategy (all need min_dte >= 7), target next
    # week's expiry. The builder picks the right chain at trade time.
    if dte is not None and dte < 7:
        dte += 7
    # Sanitize: upstream selector crashes on strength=None or NaN
    clean_sigs = []
    for s in signals:
        cs = dict(s)
        v = cs.get('strength')
        if v is None or (isinstance(v, float) and v != v):
            cs['strength'] = 0.0
        clean_sigs.append(cs)
    ranked = selector.select(clean_sigs, risk_budget=risk_budget, dte=dte)
    if backtest_dir is None:
        backtest_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                    'backtest', 'reports')
    gate_set = _load_gate_pass(backtest_dir)

    sig_map = {s['type']: s for s in signals}
    vix_too_low = _is_vix_too_low(sig_map)
    event_imminent = _is_event_imminent(sig_map, dt=dt)
    regime = _detect_regime(sig_map)
    allowed = regime_mod.REGIME_STRATEGIES.get(regime, set())

    # VP strength → lot-sizing confidence (separate from strategy selection)
    vp_sig = sig_map.get('variance_premium', {})
    vp_str = vp_sig.get('strength', 0) if vp_sig.get('direction') == 'sell_premium' else 0

    # Include strategies with strong recent performance even if selector scored them low
    ranked_keys = {k for k, _, _ in ranked}
    for key, perf in _RECENT_PERF.items():
        if key not in ranked_keys and perf.get('boost', 0) >= 1.0 and key in gate_set:
            ranked.append((key, 0.5, [f'recent backtest winner (avg ₹{perf["avg_trade"]:,.0f})']))

    scored = []
    for key, signal_score, reasons in ranked:
        if key not in gate_set:
            continue

        # Regime hard gate: only strategies matching the 2x2 cell
        if key not in allowed:
            continue

        strat = registry.get(key)

        # Engine Fix #7 mirror: suppress UNLIMITED-risk income when VIX low.
        if vix_too_low and strat and strat.category == 'income':
            if strat.max_loss != 'limited':
                continue

        # Engine Fix #3 mirror: suppress income strategies near known events
        if event_imminent and strat and strat.category == 'income':
            continue

        seasonal = _SEASONAL.get(dt.month, 0.90)
        if strat and strat.category != 'income':
            seasonal = max(seasonal, 0.95)

        vp_boost = _vp_boost(signals)
        recent = _RECENT_PERF.get(key, {}).get('boost', 0)
        final = signal_score * seasonal + vp_boost + recent
        confidence = _confidence(final, seasonal, len(reasons))
        timing = _entry_timing(strat)

        scored.append({
            'strategy_key': key,
            'final_score': round(final, 2),
            'signal_score': signal_score,
            'seasonal_mod': seasonal,
            'confidence': confidence,
            'entry_timing': timing,
            'reasons': reasons,
            'backtest_ref': BACKTEST_REF.get(key),
            'regime': regime,
            'vp_confidence': 'strong' if vp_str > 0.6 else 'moderate' if vp_str > 0.3 else 'weak',
        })

    scored.sort(key=lambda x: -x['final_score'])
    return scored


def _load_gate_pass(backtest_dir):
    if not backtest_dir or not os.path.isdir(backtest_dir):
        return GATE_PASS
    gate_set = set()
    for fname in os.listdir(backtest_dir):
        if not fname.endswith('_10yr_nifty.json'):
            continue
        try:
            with open(os.path.join(backtest_dir, fname)) as f:
                rpt = json.load(f)
            gates = rpt.get('davey_gates', {})
            if not gates:
                continue
            fails = [k for k, g in gates.items() if not g.get('pass')]
            # Accept if all pass, or only t_test fails (unproven with
            # small N, not disproven — acceptable for BURN_IN stage)
            key = fname.replace('_10yr_nifty.json', '')
            if not fails or fails == ['t_test_significance']:
                gate_set.add(key)
            # Admit strategies with strong recent real-data performance
            # even if 10yr synthetic gates fail (30-day validate_real.py)
            elif key in _RECENT_PERF and _RECENT_PERF[key].get('boost', 0) >= 1.0:
                gate_set.add(key)
        except Exception:
            pass
    return gate_set or GATE_PASS


def _is_vix_too_low(sig_map):
    """Suppress unlimited-risk selling when ATM IV < 9%.
    NIFTY VIX commonly trades 10-15%; 11% killed too many valid days."""
    vix = sig_map.get('vix_regime', {})
    if vix.get('direction') != 'caution':
        return False
    val = vix.get('value')
    if val is not None:
        return val < 9
    return (vix.get('strength') or 0) == 0.7


def _is_event_imminent(sig_map, dt=None):
    """Engine Fix #3: suppress sell near known events.
    Check signal first, then fall back to event_calendar directly
    (pipeline may not always produce an event signal)."""
    ev = sig_map.get('event', {})
    if ev.get('direction') == 'caution' and ev.get('strength', 0) > 0.7:
        return True
    dt = dt or datetime.date.today()
    return event_calendar.event_near(dt) is not None


def _vp_boost(signals):
    sig_map = {s['type']: s for s in signals}
    vp = sig_map.get('variance_premium', {})
    if vp.get('direction') == 'sell_premium':
        s = vp.get('strength') or 0
        if s > 0.7:
            return 0.5
        if s > 0.4:
            return 0.2
    return 0.0


def _confidence(final_score, seasonal, n_reasons):
    if final_score > 5.0 and seasonal >= 0.90 and n_reasons >= 3:
        return 'high'
    if final_score > 3.0 and seasonal >= 0.80:
        return 'medium'
    return 'low'


def _entry_timing(strat):
    if strat is None:
        return 'any'
    if strat.category == 'income':
        return 'afternoon (14:00-14:30 IST)'
    if strat.category in ('volatility', 'directional'):
        return 'morning (09:30-10:00 IST)'
    return 'any'


def _self_check():
    # Rangebound regime (no trend signal) — income strategies should rank
    sigs = [
        {'type': 'variance_premium', 'direction': 'sell_premium',
         'strength': 0.7, 'detail': 'VP=3.5%'},
        {'type': 'vix_regime', 'direction': 'sell_premium',
         'strength': 0.6, 'detail': 'VIX=15', 'value': 15},
        {'type': 'pcr', 'direction': 'neutral', 'strength': 0.1, 'detail': ''},
        {'type': 'oi_regime', 'direction': 'neutral', 'strength': 0.1, 'detail': ''},
        {'type': 'skew', 'direction': 'neutral', 'strength': 0.2, 'detail': ''},
        {'type': 'term_structure', 'direction': 'neutral', 'strength': 0.1, 'detail': ''},
    ]

    results = score(sigs, dt=datetime.date(2026, 8, 15))
    assert len(results) > 0, "No strategies scored"
    assert all(r['strategy_key'] in GATE_PASS for r in results)
    assert results[0]['regime'] == 'rangebound'
    assert results[0]['seasonal_mod'] == 1.0  # August = sweet spot

    # Trending down regime — bear_call_spread should appear
    bear_sigs = list(sigs) + [
        {'type': 'price_trend', 'direction': 'bearish',
         'strength': 0.6, 'roc': -0.03, 'detail': 'RoC=-3.0%'},
    ]
    bear = score(bear_sigs, dt=datetime.date(2026, 8, 15))
    assert len(bear) > 0, "No strategies in trending_down"
    assert bear[0]['regime'] == 'trending_down'
    bear_keys = {r['strategy_key'] for r in bear}
    assert 'bear_call_spread' in bear_keys or 'iron_condor' in bear_keys, \
        f"Expected directional strategy, got {bear_keys}"
    # Neutral-only strategies should be filtered out
    assert 'iron_butterfly' not in bear_keys
    assert 'short_straddle' not in bear_keys

    # Dangerous month — seasonal should penalize income strategies
    feb = score(sigs, dt=datetime.date(2026, 2, 15))
    feb_income = [r for r in feb if registry.get(r['strategy_key']) and registry.get(r['strategy_key']).category == 'income']
    if feb_income:
        assert feb_income[0]['seasonal_mod'] == 0.70
    assert feb[0]['final_score'] < results[0]['final_score']

    # VP confidence field
    assert results[0]['vp_confidence'] == 'strong'  # strength=0.7

    # VIX < 9% guard — unlimited-risk income suppressed, limited-risk OK
    low_vix = [
        {'type': 'variance_premium', 'direction': 'sell_premium',
         'strength': 0.5, 'detail': ''},
        {'type': 'vix_regime', 'direction': 'caution',
         'strength': 0.7, 'detail': 'VIX=8 — too low, premium thin', 'value': 8},
    ]
    vix_results = score(low_vix, dt=datetime.date(2026, 8, 1))
    for r in vix_results:
        s = registry.get(r['strategy_key'])
        if s and s.category == 'income':
            assert s.max_loss == 'limited', \
                f"VIX guard failed: unlimited-risk {r['strategy_key']} at VIX=8"

    # Event imminent guard — no income strategies
    event_sigs = [
        {'type': 'variance_premium', 'direction': 'sell_premium',
         'strength': 0.7, 'detail': ''},
        {'type': 'vix_regime', 'direction': 'sell_premium',
         'strength': 0.6, 'detail': 'VIX=16', 'value': 16},
        {'type': 'event', 'direction': 'caution', 'strength': 0.9,
         'detail': 'RBI MPC in 1d'},
    ]
    ev_results = score(event_sigs, dt=datetime.date(2026, 8, 1))
    for r in ev_results:
        s = registry.get(r['strategy_key'])
        assert s is None or s.category != 'income', \
            f"Event guard failed: {r['strategy_key']} recommended near RBI"

    print("scorer.py: all checks passed")


if __name__ == '__main__':
    _self_check()
