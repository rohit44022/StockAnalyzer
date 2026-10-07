"""Tests for the recommender pipeline: scorer → recommend → explainer."""
import datetime
import math
import unittest.mock as mock

import pandas as pd
import pytest

from options.strategies import scorer, recommend, explainer, signals, selector, registry
from options.core import event_calendar


# ── Fixtures ──────────────────────────────────────────────────────────

def _chain(spot=24000):
    rows = []
    for strike in range(int(spot - 500), int(spot + 550), 50):
        for ot in ['CE', 'PE']:
            ltp = max(0.5, 200 - abs(strike - spot) * 0.5)
            rows.append({
                'strike': float(strike), 'option_type': ot,
                'expiry': datetime.date(2026, 11, 17), 'expiry_years': 7 / 365,
                'ltp': ltp, 'settle': ltp,
                'bid': max(0.4, ltp - 1), 'ask': ltp + 1,
                'oi': 100000, 'volume': 50000, 'iv': 0.14, 'change_oi': 1000,
            })
    return pd.DataFrame(rows)


def _pipe():
    return {
        'variance_premium': {'vp': 0.035, 'iv': 0.16, 'rv': 0.125, 'signal': 'sell_premium'},
        'vix': {'value': 15.5, 'regime': {'level': 'normal'}},
        'oi': {'pcr': {'pcr': 1.1}},
        'upcoming_events': [],
    }


def _sigs():
    return [
        {'type': 'variance_premium', 'direction': 'sell_premium', 'strength': 0.7, 'detail': 'VP=3.5%'},
        {'type': 'vix_regime', 'direction': 'sell_premium', 'strength': 0.6, 'detail': 'VIX=15'},
        {'type': 'pcr', 'direction': 'neutral', 'strength': 0.1, 'detail': ''},
        {'type': 'oi_regime', 'direction': 'neutral', 'strength': 0.1, 'detail': ''},
        {'type': 'skew', 'direction': 'neutral', 'strength': 0.2, 'detail': ''},
        {'type': 'term_structure', 'direction': 'neutral', 'strength': 0.1, 'detail': ''},
    ]


def _gen(**kw):
    with mock.patch('options.core.event_calendar.event_near', return_value=None):
        with mock.patch('options.data.event_calendar.next_expiry',
                        return_value=datetime.date(2026, 11, 17)):
            return recommend.generate(
                _chain(), spot=24000, vix_value=15.5,
                pipe_result=_pipe(), capital=500_000, **kw)


# ── Scorer ────────────────────────────────────────────────────────────

class TestScorer:
    def test_basic_scoring(self):
        results = scorer.score(_sigs(), dt=datetime.date(2026, 8, 15))
        assert len(results) > 0
        assert all(r['strategy_key'] in scorer.GATE_PASS for r in results)

    def test_seasonal_sweet_spot(self):
        results = scorer.score(_sigs(), dt=datetime.date(2026, 8, 15))
        assert results[0]['seasonal_mod'] == 1.0

    def test_seasonal_penalty(self):
        feb = scorer.score(_sigs(), dt=datetime.date(2026, 2, 15))
        aug = scorer.score(_sigs(), dt=datetime.date(2026, 8, 15))
        assert feb[0]['seasonal_mod'] == 0.70
        assert feb[0]['final_score'] < aug[0]['final_score']

    def test_confidence_values(self):
        results = scorer.score(_sigs(), dt=datetime.date(2026, 8, 15))
        for r in results:
            assert r['confidence'] in ('high', 'medium', 'low')

    def test_non_gate_pass_filtered(self):
        results = scorer.score(_sigs(), dt=datetime.date(2026, 8, 15))
        keys = {r['strategy_key'] for r in results}
        assert 'iron_condor' not in keys
        assert 'long_butterfly' not in keys

    def test_entry_timing_income(self):
        results = scorer.score(_sigs(), dt=datetime.date(2026, 8, 15))
        for r in results:
            strat = registry.get(r['strategy_key'])
            if strat and strat.category == 'income':
                assert 'afternoon' in r['entry_timing']

    def test_vix_too_low_guard(self):
        low_vix = [
            {'type': 'variance_premium', 'direction': 'sell_premium', 'strength': 0.5, 'detail': ''},
            {'type': 'vix_regime', 'direction': 'caution', 'strength': 0.7, 'detail': 'VIX=9 — too low'},
        ]
        results = scorer.score(low_vix, dt=datetime.date(2026, 8, 1))
        for r in results:
            s = registry.get(r['strategy_key'])
            assert s is None or s.category != 'income', \
                f"VIX guard failed: {r['strategy_key']} at VIX=9"

    def test_vix_guard_alternate_text(self):
        sig = {'type': 'vix_regime', 'direction': 'caution',
               'strength': 0.7, 'detail': 'VIX=9.0 — premium inadequate'}
        assert scorer._is_vix_too_low({'vix_regime': sig})

    def test_event_imminent_guard(self):
        event_sigs = [
            {'type': 'variance_premium', 'direction': 'sell_premium', 'strength': 0.7, 'detail': ''},
            {'type': 'vix_regime', 'direction': 'sell_premium', 'strength': 0.6, 'detail': 'VIX=16'},
            {'type': 'event', 'direction': 'caution', 'strength': 0.9, 'detail': 'RBI MPC in 1d'},
        ]
        results = scorer.score(event_sigs, dt=datetime.date(2026, 8, 1))
        for r in results:
            s = registry.get(r['strategy_key'])
            assert s is None or s.category != 'income', \
                f"Event guard failed: {r['strategy_key']} near RBI"

    def test_event_guard_no_signal_fallback(self):
        with mock.patch('options.core.event_calendar.event_near', return_value='RBI MPC'):
            assert scorer._is_event_imminent({}, dt=datetime.date(2026, 10, 6))

    def test_nan_strength_no_propagation(self):
        nan_sigs = [{'type': 'variance_premium', 'direction': 'sell_premium',
                     'strength': float('nan'), 'detail': ''}]
        results = scorer.score(nan_sigs, dt=datetime.date(2026, 8, 1))
        for r in results:
            assert not math.isnan(r['final_score'])

    def test_none_strength_no_crash(self):
        none_sigs = [{'type': 'variance_premium', 'direction': 'sell_premium',
                      'strength': None, 'detail': ''}]
        scorer.score(none_sigs, dt=datetime.date(2026, 8, 1))


# ── Recommend ─────────────────────────────────────────────────────────

class TestRecommend:
    def test_output_fields_complete(self):
        result = _gen()
        for f in ['recommendations', 'market_state', 'timestamp',
                   'expires_at', 'ttl_minutes', 'signals']:
            assert f in result

    def test_reco_fields_complete(self):
        result = _gen()
        if not result['recommendations']:
            pytest.skip('no recommendations')
        top = result['recommendations'][0]
        for f in ['strategy_key', 'legs', 'raw_legs', 'net_premium', 'worst_case_net',
                   'round_trip_cost', 'margin_required', 'max_profit', 'max_loss',
                   'confidence', 'entry_timing', 'lot_size', 'dte', 'daily_theta']:
            assert f in top, f"missing field: {f}"

    def test_leg_fields_complete(self):
        result = _gen()
        if not result['recommendations']:
            pytest.skip('no recommendations')
        leg = result['recommendations'][0]['legs'][0]
        for f in ['strike', 'option_type', 'action', 'qty',
                   'ref_price', 'price_low', 'price_high']:
            assert f in leg

    def test_price_range_order(self):
        result = _gen()
        for reco in result.get('recommendations', []):
            for leg in reco['legs']:
                assert leg['price_low'] <= leg['ref_price'] <= leg['price_high']

    def test_worst_case_direction(self):
        result = _gen()
        for reco in result.get('recommendations', []):
            net = reco['net_premium']
            wc = reco['worst_case_net']
            if net > 0:
                assert wc <= net, "worst_case > net for credit strategy"

    def test_margin_positive(self):
        result = _gen()
        for reco in result.get('recommendations', []):
            m = reco.get('margin_required')
            if m is not None:
                assert m >= 0

    def test_ltp_floor(self):
        from options.strategies.recommend import _build_reco
        fake_scored = {'strategy_key': 'short_straddle', 'final_score': 5.0,
                       'confidence': 'medium', 'entry_timing': 'afternoon', 'reasons': ['test']}
        fake_build = {'legs': [
            {'strike': 23000, 'option_type': 'PE', 'action': 'SELL',
             'premium': 0.0, 'qty': 1}
        ], 'net_premium': 0, 'max_profit': 0, 'max_loss': 0}
        reco = _build_reco(fake_scored, fake_build, 7, 75)
        assert reco['legs'][0]['ref_price'] == 0.05

    def test_invalid_spot(self):
        result = recommend.generate(_chain(), spot=0, vix_value=15)
        assert result['recommendations'] == []
        assert 'error' in result

    def test_ttl(self):
        result = _gen()
        assert result['ttl_minutes'] == 30
        assert not recommend.is_stale(result)

    def test_stale_detection(self):
        result = _gen()
        result['expires_at'] = '2020-01-01T00:00:00'
        assert recommend.is_stale(result)

    def test_lot_recommendation_present(self):
        result = _gen()
        for reco in result.get('recommendations', []):
            assert 'recommended_lots' in reco
            assert reco['recommended_lots'] >= 1

    def test_backtest_ref_present(self):
        result = _gen()
        for reco in result.get('recommendations', []):
            if reco['strategy_key'] in scorer.BACKTEST_REF:
                assert reco['backtest_ref'] is not None


# ── Selector ──────────────────────────────────────────────────────────

class TestSelector:
    def test_return_format(self):
        sigs = signals.scan_signals(_pipe())
        ranked = selector.select(sigs, risk_budget='moderate', dte=7)
        if ranked:
            key, score, reasons = ranked[0]
            assert isinstance(key, str)
            assert isinstance(score, (int, float))
            assert isinstance(reasons, list)

    def test_dte_filter(self):
        sigs = signals.scan_signals(_pipe())
        results = scorer.score(sigs, dte=2, dt=datetime.date(2026, 8, 1))
        for r in results:
            strat = registry.get(r['strategy_key'])
            if strat:
                assert strat.min_dte <= 2, \
                    f"{r['strategy_key']} recommended at DTE=2 but min_dte={strat.min_dte}"


# ── Explainer ─────────────────────────────────────────────────────────

class TestExplainer:
    def _reco(self):
        return {
            'symbol': 'NIFTY', 'timestamp': '2026-10-06T15:45:00',
            'expires_at': '2026-10-06T16:15:00', 'ttl_minutes': 30,
            'capital': 500_000, 'risk_budget': 'moderate',
            'market_state': {
                'spot': 24000, 'vix': 15.5, 'iv': 0.16, 'rv': 0.125,
                'vp': 0.035, 'vp_signal': 'sell_premium', 'dte': 7, 'event_near': None,
            },
            'recommendations': [{
                'strategy_key': 'short_straddle', 'strategy_name': 'Short Straddle',
                'category': 'income', 'final_score': 6.2, 'confidence': 'high',
                'entry_timing': 'afternoon (14:00-14:30 IST)', 'dte': 7,
                'legs': [
                    {'strike': 24000, 'option_type': 'CE', 'action': 'SELL',
                     'qty': 1, 'ref_price': 200.0, 'price_low': 196.0, 'price_high': 204.0},
                    {'strike': 24000, 'option_type': 'PE', 'action': 'SELL',
                     'qty': 1, 'ref_price': 195.0, 'price_low': 191.1, 'price_high': 198.9},
                ],
                'net_premium': 395.0, 'max_profit': 395, 'max_loss': float('-inf'),
                'breakevens': [23605, 24395], 'lot_size': 65,
                'reasons': ['VP sell signal (0.7)'],
            }],
            'signals': [],
        }

    def test_full_format(self):
        text = explainer.explain(self._reco())
        assert 'NIFTY OPTIONS RECOMMENDATION' in text
        assert 'SHORT STRADDLE' in text
        assert 'HIGH confidence' in text
        assert 'RANGES' in text

    def test_short_format(self):
        short = explainer.explain_short(self._reco())
        assert 'Short Straddle' in short
        assert 'high' in short

    def test_risk_unlimited(self):
        risk = explainer.explain_risk(self._reco())
        assert 'UNLIMITED' in risk

    def test_empty_recommendation(self):
        empty = dict(self._reco(), recommendations=[])
        assert 'NO TRADES' in explainer.explain(empty)
        assert 'No trade' in explainer.explain_short(empty)
        assert 'No position' in explainer.explain_risk(empty)

    def test_vp_none_no_crash(self):
        r = self._reco()
        r['market_state']['vp'] = None
        text = explainer.explain(r)
        assert 'N/A' in text or 'None' not in text

    def test_dynamic_symbol(self):
        r = dict(self._reco(), symbol='BANKNIFTY')
        assert 'BANKNIFTY' in explainer.explain(r)
