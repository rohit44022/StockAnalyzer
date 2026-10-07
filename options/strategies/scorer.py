"""
Production scorer: layers backtest performance, seasonal, and market-state
modifiers on top of selector.py signal scores.

Only strategies that pass Davey gates (WFA + MC) get recommended.
Seasonal data from brainstorm Round 2 (NIFTY 10yr daily vol by month).
"""

import datetime
import json
import os

from . import selector, registry
from ..core import event_calendar


GATE_PASS = {'short_straddle', 'short_strangle', 'iron_butterfly', 'jade_lizard'}

# 10-year backtest reference metrics (Davey Ch.23: track actual vs expected)
BACKTEST_REF = {
    'short_straddle':  {'win_rate': 66, 'max_dd': 31, 'avg_trade': 161},
    'short_strangle':  {'win_rate': 77, 'max_dd': 24, 'avg_trade': 93},
    'iron_butterfly':  {'win_rate': 55, 'max_dd': 14, 'avg_trade': 109},
    'jade_lizard':     {'win_rate': 82, 'max_dd': 21, 'avg_trade': 130},
}

# Monthly risk multiplier for income strategies.
# Mar vol = 2.4x Jul. Feb has Budget. Jul-Aug-Nov-Dec sweet spot.
_SEASONAL = {
    1: 0.85, 2: 0.70, 3: 0.65, 4: 0.90, 5: 0.95, 6: 0.90,
    7: 1.00, 8: 1.00, 9: 0.90, 10: 0.85, 11: 1.00, 12: 1.00,
}


def score(signals, backtest_dir=None,
          risk_budget='moderate', dte=None, dt=None):
    """
    Score and rank strategies for live recommendation.

    Returns list of dicts sorted by final_score desc:
      {strategy_key, final_score, signal_score, seasonal_mod,
       confidence, entry_timing, reasons}
    """
    dt = dt or datetime.date.today()
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

    scored = []
    for key, signal_score, reasons in ranked:
        if key not in gate_set or signal_score <= 0:
            continue

        strat = registry.get(key)

        # Engine Fix #7 mirror: suppress income strategies when VIX < 11%
        if vix_too_low and strat and strat.category == 'income':
            continue

        # Engine Fix #3 mirror: suppress income strategies near known events
        if event_imminent and strat and strat.category == 'income':
            continue

        seasonal = _SEASONAL.get(dt.month, 0.90)
        if strat and strat.category != 'income':
            seasonal = max(seasonal, 0.95)

        vp_boost = _vp_boost(signals)
        final = signal_score * seasonal + vp_boost
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
            if gates and all(g.get('pass') for g in gates.values()):
                gate_set.add(fname.replace('_10yr_nifty.json', ''))
        except Exception:
            pass
    return gate_set or GATE_PASS


def _is_vix_too_low(sig_map):
    """Engine Fix #7: suppress sell when ATM IV < 11%.
    Extract VIX value from signal detail rather than relying on text content."""
    vix = sig_map.get('vix_regime', {})
    if vix.get('direction') != 'caution':
        return False
    detail = vix.get('detail', '')
    import re
    m = re.search(r'VIX=([\d.]+)', detail)
    if m:
        return float(m.group(1)) < 11
    # Fallback: caution + high strength but NOT crisis (strength 0.8 = crisis)
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
    sigs = [
        {'type': 'variance_premium', 'direction': 'sell_premium',
         'strength': 0.7, 'detail': 'VP=3.5%'},
        {'type': 'vix_regime', 'direction': 'sell_premium',
         'strength': 0.6, 'detail': 'VIX=15'},
        {'type': 'pcr', 'direction': 'neutral', 'strength': 0.1, 'detail': ''},
        {'type': 'oi_regime', 'direction': 'neutral', 'strength': 0.1, 'detail': ''},
        {'type': 'skew', 'direction': 'neutral', 'strength': 0.2, 'detail': ''},
        {'type': 'term_structure', 'direction': 'neutral', 'strength': 0.1, 'detail': ''},
    ]

    # Normal month — income strategies should rank
    results = score(sigs, dt=datetime.date(2026, 8, 15))
    assert len(results) > 0, "No strategies scored"
    assert all(r['strategy_key'] in GATE_PASS for r in results)
    assert results[0]['confidence'] in ('high', 'medium', 'low')
    assert results[0]['seasonal_mod'] == 1.0  # August = sweet spot

    # Dangerous month — seasonal should penalize
    feb = score(sigs, dt=datetime.date(2026, 2, 15))
    assert feb[0]['seasonal_mod'] == 0.70
    assert feb[0]['final_score'] < results[0]['final_score']

    # Entry timing
    for r in results:
        strat = registry.get(r['strategy_key'])
        if strat and strat.category == 'income':
            assert 'afternoon' in r['entry_timing']

    # Non-gate-pass strategy filtered out
    keys = {r['strategy_key'] for r in results}
    assert 'iron_condor' not in keys
    assert 'long_butterfly' not in keys

    # VIX < 11% guard — no income strategies
    low_vix = [
        {'type': 'variance_premium', 'direction': 'sell_premium',
         'strength': 0.5, 'detail': ''},
        {'type': 'vix_regime', 'direction': 'caution',
         'strength': 0.7, 'detail': 'VIX=9 — too low, premium thin'},
    ]
    vix_results = score(low_vix, dt=datetime.date(2026, 8, 1))
    for r in vix_results:
        s = registry.get(r['strategy_key'])
        assert s is None or s.category != 'income', \
            f"VIX guard failed: {r['strategy_key']} recommended at VIX=9"

    # Event imminent guard — no income strategies
    event_sigs = [
        {'type': 'variance_premium', 'direction': 'sell_premium',
         'strength': 0.7, 'detail': ''},
        {'type': 'vix_regime', 'direction': 'sell_premium',
         'strength': 0.6, 'detail': 'VIX=16'},
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
