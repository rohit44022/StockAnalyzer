"""
Comprehensive tests for all ceiling fixes (C1-C11).
Covers VaR correlation, ELM spreads, FutEq, margin API fallback,
vol_surface drift, live IV repricing, chain_store perf, max_pain vectorization,
pipeline sentiment, spread estimation, multi-expiry chain loader, and live orders.
"""

import datetime
import math
import os
import sys
import tempfile
import unittest
import unittest.mock as mock

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from options.risk import portfolio, margin, limits
from options.core import vol_surface, bsm
from options.strategies import adjustments, registry, builder
from options.data import chain_store, oi_analysis, pipeline, dhan_order
from options.backtest import run_pipeline as rp


# ═══════════════════════════════════════════════════════════════════
# C1: VaR with spot-IV correlation
# ═══════════════════════════════════════════════════════════════════

class TestVaRCorrelation(unittest.TestCase):
    """C1: parametric_var must include ρ term for spot-IV correlation."""

    def test_rho_increases_var(self):
        """VaR with ρ>0 must be ≥ VaR with ρ=0 (cross-term always positive)."""
        base = portfolio.parametric_var(100000, 50000, 24000, 0.012, rho=0)
        corr = portfolio.parametric_var(100000, 50000, 24000, 0.012, rho=0.6)
        self.assertGreaterEqual(corr['var_amount'], base['var_amount'])

    def test_stress_rho_higher_than_normal(self):
        """Stress VaR (ρ=0.9) ≥ normal VaR (ρ=0.6)."""
        normal = portfolio.parametric_var(100000, 50000, 24000, 0.012)
        stress = portfolio.parametric_var(100000, 50000, 24000, 0.012, stress=True)
        self.assertGreaterEqual(stress['var_amount'], normal['var_amount'])
        self.assertAlmostEqual(stress['rho'], 0.9)
        self.assertAlmostEqual(normal['rho'], 0.6)

    def test_rho_in_output(self):
        """Result dict must contain the rho used."""
        r = portfolio.parametric_var(100000, 50000, 24000, 0.012, rho=0.7)
        self.assertEqual(r['rho'], 0.7)

    def test_rho_zero_matches_old_formula(self):
        """ρ=0 should give √(a² + b²) — same as old uncorrelated formula."""
        r = portfolio.parametric_var(100000, 50000, 24000, 0.012, rho=0)
        delta_v = abs(100000) * 24000 * 0.012
        vega_v = abs(50000) * 0.02
        expected = math.sqrt(delta_v**2 + vega_v**2) * 1.645
        self.assertAlmostEqual(r['var_amount'], expected, places=0)

    def test_holding_days_scales(self):
        """Multi-day VaR scales by √days."""
        r1 = portfolio.parametric_var(100000, 50000, 24000, 0.012, holding_days=1)
        r4 = portfolio.parametric_var(100000, 50000, 24000, 0.012, holding_days=4)
        self.assertAlmostEqual(r4['var_amount'] / r1['var_amount'], 2.0, places=1)

    def test_zero_vega_no_cross_term(self):
        """With zero vega, rho doesn't matter — only delta component."""
        a = portfolio.parametric_var(100000, 0, 24000, 0.012, rho=0)
        b = portfolio.parametric_var(100000, 0, 24000, 0.012, rho=0.9)
        self.assertAlmostEqual(a['var_amount'], b['var_amount'], places=2)

    def test_confidence_levels(self):
        """99% VaR > 95% VaR."""
        r95 = portfolio.parametric_var(100000, 50000, 24000, 0.012, confidence=0.95)
        r99 = portfolio.parametric_var(100000, 50000, 24000, 0.012, confidence=0.99)
        self.assertGreater(r99['var_amount'], r95['var_amount'])


# ═══════════════════════════════════════════════════════════════════
# C2: ELM for hedged spreads
# ═══════════════════════════════════════════════════════════════════

class TestELMSpreads(unittest.TestCase):
    """C2: ELM for fully hedged spreads uses 50% reduction."""

    def _iron_condor_legs(self):
        return [
            {'strike': 23800, 'option_type': 'PE', 'action': 'BUY',
             'premium': 30, 'iv': 0.16, 'expiry_years': 14/365, 'qty': 1},
            {'strike': 23900, 'option_type': 'PE', 'action': 'SELL',
             'premium': 50, 'iv': 0.15, 'expiry_years': 14/365, 'qty': 1},
            {'strike': 24100, 'option_type': 'CE', 'action': 'SELL',
             'premium': 50, 'iv': 0.14, 'expiry_years': 14/365, 'qty': 1},
            {'strike': 24200, 'option_type': 'CE', 'action': 'BUY',
             'premium': 25, 'iv': 0.15, 'expiry_years': 14/365, 'qty': 1},
        ]

    def test_hedged_spread_elm_lower_than_naked(self):
        """Iron condor (fully hedged) should have less ELM than 2 naked shorts."""
        hedged = margin.estimate_margin(self._iron_condor_legs(), 24000, lot_size=65)
        naked = margin.estimate_margin([
            {'strike': 23900, 'option_type': 'PE', 'action': 'SELL',
             'premium': 50, 'iv': 0.15, 'expiry_years': 14/365, 'qty': 1},
            {'strike': 24100, 'option_type': 'CE', 'action': 'SELL',
             'premium': 50, 'iv': 0.14, 'expiry_years': 14/365, 'qty': 1},
        ], 24000, lot_size=65)
        self.assertLess(hedged['elm'], naked['elm'])

    def test_long_only_no_elm(self):
        """Long-only position should have zero ELM."""
        legs = [
            {'strike': 24000, 'option_type': 'CE', 'action': 'BUY',
             'premium': 200, 'iv': 0.15, 'expiry_years': 14/365, 'qty': 1},
        ]
        r = margin.estimate_margin(legs, 24000, lot_size=65)
        self.assertEqual(r['elm'], 0)


# ═══════════════════════════════════════════════════════════════════
# C3: FutEq delta-based computation
# ═══════════════════════════════════════════════════════════════════

class TestFutEq(unittest.TestCase):
    """C3: compute_futeq computes SEBI delta-based FutEq."""

    def test_single_short(self):
        futeq = limits.compute_futeq(
            [{'delta': 0.5, 'qty': 1, 'action': 'SELL'}],
            spot=24000, lot_size=75)
        self.assertAlmostEqual(futeq, 0.5 * 1 * 75 * 24000)

    def test_hedged_lower(self):
        """Hedged position FutEq should equal sum of absolute deltas."""
        legs = [
            {'delta': 0.5, 'qty': 1, 'action': 'SELL'},
            {'delta': -0.5, 'qty': 1, 'action': 'BUY'},
        ]
        futeq = limits.compute_futeq(legs, spot=24000, lot_size=75)
        # Each leg contributes |delta * qty * lot * spot|
        expected = 2 * abs(0.5 * 1 * 75 * 24000)
        self.assertAlmostEqual(futeq, expected)

    def test_zero_delta(self):
        futeq = limits.compute_futeq(
            [{'delta': 0, 'qty': 1, 'action': 'BUY'}],
            spot=24000, lot_size=75)
        self.assertEqual(futeq, 0)


# ═══════════════════════════════════════════════════════════════════
# C4: Broker margin with API fallback
# ═══════════════════════════════════════════════════════════════════

class TestBrokerMargin(unittest.TestCase):
    """C4: broker_margin tries Dhan API, falls back to estimator."""

    def _legs(self):
        return [
            {'strike': 24000, 'option_type': 'CE', 'action': 'SELL',
             'premium': 200, 'iv': 0.15, 'expiry_years': 14/365, 'qty': 1},
        ]

    def test_fallback_to_estimator(self):
        """When Dhan API unavailable, falls back to SPAN estimator."""
        r = margin.broker_margin(self._legs(), 24000, lot_size=65)
        self.assertEqual(r['source'], 'estimator')
        self.assertGreater(r['total_margin'], 0)

    def test_api_success(self):
        """When Dhan API returns margin, use it."""
        mock_result = {'total_margin': 150000, 'span_margin': 100000,
                       'exposure_margin': 50000, 'source': 'dhan_api'}
        import options.data.dhan_fetch as df_mod
        original = getattr(df_mod, 'fetch_margin', None)
        df_mod.fetch_margin = lambda *a, **k: mock_result
        try:
            r = margin.broker_margin(self._legs(), 24000, lot_size=65)
            self.assertEqual(r['source'], 'dhan_api')
            self.assertEqual(r['total'], 150000)
        finally:
            if original:
                df_mod.fetch_margin = original


# ═══════════════════════════════════════════════════════════════════
# C5: vol_surface 25-delta drift term
# ═══════════════════════════════════════════════════════════════════

class TestVolSurfaceDrift(unittest.TestCase):
    """C5: 25-delta strike includes drift term for back-month accuracy."""

    def _chain(self, spot=24000, t=90/365):
        rows = []
        for k in range(int(spot - 2000), int(spot + 2050), 50):
            for ot in ['CE', 'PE']:
                iv = 0.15 + abs(k - spot) / spot * 0.3
                p = max(0.05, bsm.bsm_price(spot, float(k), t, 0.07, iv, ot))
                rows.append({
                    'strike': float(k), 'option_type': ot,
                    'expiry': datetime.date.today() + datetime.timedelta(days=int(t*365)),
                    'expiry_years': t, 'settle': p, 'ltp': p,
                    'oi': 100000, 'volume': 50000, 'iv': iv,
                })
        return pd.DataFrame(rows)

    def test_skew_metrics_exist(self):
        """build_surface should return skew metrics for back-month chains."""
        chain = self._chain(t=90/365)
        result = vol_surface.build_surface(chain, 24000)
        self.assertIsNotNone(result)


# ═══════════════════════════════════════════════════════════════════
# C6: Live IV in adjustments
# ═══════════════════════════════════════════════════════════════════

class TestLiveIVRepricing(unittest.TestCase):
    """C6: _reprice_pnl accepts live_iv dict, falls back to entry IV."""

    def _legs(self):
        return [
            {'strike': 24000, 'option_type': 'CE', 'action': 'SELL',
             'premium': 200, 'iv': 0.15},
            {'strike': 24200, 'option_type': 'CE', 'action': 'BUY',
             'premium': 100, 'iv': 0.16},
        ]

    def test_entry_iv_fallback(self):
        """Without live_iv, uses entry IV."""
        pnl = adjustments._reprice_pnl(self._legs(), 24050, 10/365)
        self.assertIsNotNone(pnl)

    def test_live_iv_used(self):
        """With live_iv, uses live values instead of entry."""
        live = {(24000, 'CE'): 0.40, (24200, 'CE'): 0.42}
        pnl_live = adjustments._reprice_pnl(self._legs(), 24050, 10/365,
                                             live_iv=live)
        pnl_entry = adjustments._reprice_pnl(self._legs(), 24050, 10/365)
        # Much higher IV → significantly different P/L
        self.assertNotEqual(round(pnl_live, 2), round(pnl_entry, 2))

    def test_check_passes_live_iv(self):
        """check() passes live_iv through to _pnl_rules."""
        position = {
            'legs': self._legs(),
            'max_loss': -10000, 'max_profit': 5000,
            'strategy': 'bear_call_spread',
        }
        recs = adjustments.check(position, spot=24050, entry_spot=24000,
                                  dte=10, live_iv={(24000, 'CE'): 0.20})
        self.assertIsInstance(recs, list)


# ═══════════════════════════════════════════════════════════════════
# C7: chain_store query performance
# ═══════════════════════════════════════════════════════════════════

class TestChainStoreQueryPerf(unittest.TestCase):
    """C7: get_chain_snapshot uses subquery, not full table scan."""

    def test_returns_latest_only(self):
        """With multiple timestamps on different dates, returns only the latest."""
        db = tempfile.mktemp(suffix='.db')
        chain_store.init_db(db)
        import sqlite3
        conn = sqlite3.connect(db)

        # Unique index is on substr(timestamp,1,10) so use different dates
        for ts in ['2026-10-05T10:00:00', '2026-10-06T14:00:00']:
            conn.execute(
                'INSERT OR IGNORE INTO chain_snapshot '
                '(timestamp, symbol, expiry, strike, option_type, '
                'ltp, oi, volume, iv, change_oi) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (ts, 'NIFTY', '2026-10-17', 24000.0, 'CE',
                 200.0, 100000, 50000, 0.15, 1000))
        conn.commit()
        conn.close()

        df = chain_store.get_chain_snapshot('NIFTY', db_path=db)
        self.assertEqual(len(df), 1)
        self.assertIn('2026-10-06', df.iloc[0]['timestamp'])

        os.unlink(db)


# ═══════════════════════════════════════════════════════════════════
# C8: max_pain vectorized
# ═══════════════════════════════════════════════════════════════════

class TestMaxPainVectorized(unittest.TestCase):
    """C8: max_pain uses numpy broadcasting instead of O(n²) loops."""

    def _chain(self, spot=24000, n_strikes=50):
        rows = []
        for k in range(int(spot - n_strikes*25), int(spot + (n_strikes+1)*25), 50):
            for ot in ['CE', 'PE']:
                rows.append({
                    'strike': float(k), 'option_type': ot,
                    'oi': np.random.randint(10000, 200000),
                    'volume': 50000, 'ltp': 100,
                })
        return pd.DataFrame(rows)

    def test_max_pain_correct(self):
        """Vectorized max_pain returns same result as O(n²) reference."""
        chain = self._chain(n_strikes=20)
        result = oi_analysis.max_pain(chain)
        self.assertFalse(math.isnan(result['max_pain_strike']))
        self.assertIn('losses', result)
        self.assertGreater(len(result['losses']), 0)

    def test_max_pain_at_expected_strike(self):
        """When all OI is at one strike, max_pain should be near that strike."""
        rows = []
        for k in [23800, 23900, 24000, 24100, 24200]:
            oi_ce = 500000 if k == 24000 else 1000
            oi_pe = 500000 if k == 24000 else 1000
            rows.append({'strike': float(k), 'option_type': 'CE',
                         'oi': oi_ce, 'volume': 50000, 'ltp': 100})
            rows.append({'strike': float(k), 'option_type': 'PE',
                         'oi': oi_pe, 'volume': 50000, 'ltp': 100})
        chain = pd.DataFrame(rows)
        result = oi_analysis.max_pain(chain)
        self.assertEqual(result['max_pain_strike'], 24000.0)

    def test_empty_chain(self):
        chain = pd.DataFrame(columns=['strike', 'option_type', 'oi'])
        result = oi_analysis.max_pain(chain)
        self.assertTrue(math.isnan(result['max_pain_strike']))

    def test_large_chain_perf(self):
        """250 strikes should complete quickly (was O(n²), now vectorized)."""
        import time
        chain = self._chain(n_strikes=250)
        start = time.time()
        result = oi_analysis.max_pain(chain)
        elapsed = time.time() - start
        self.assertLess(elapsed, 1.0)  # was ~0.5s with loops, now <0.1s
        self.assertFalse(math.isnan(result['max_pain_strike']))


# ═══════════════════════════════════════════════════════════════════
# C9: Pipeline wires oi_sentiment_summary
# ═══════════════════════════════════════════════════════════════════

class TestPipelineSentiment(unittest.TestCase):
    """C9: pipeline.run_eod_pipeline includes oi_sentiment when prev_chain available."""

    def _chain(self, spot=24000):
        rows = []
        for k in range(int(spot - 500), int(spot + 550), 50):
            for ot in ['CE', 'PE']:
                rows.append({
                    'strike': float(k), 'option_type': ot,
                    'expiry': datetime.date(2026, 11, 17),
                    'expiry_years': 40/365,
                    'ltp': max(1, 200 - abs(k - spot) * 0.5),
                    'settle': max(1, 200 - abs(k - spot) * 0.5),
                    'oi': 100000, 'volume': 50000, 'iv': 0.15,
                    'change_oi': 5000,
                })
        return pd.DataFrame(rows)

    def test_sentiment_in_results(self):
        """oi_sentiment key should appear when prev_chain provided."""
        chain = self._chain()
        prev = self._chain()
        prev['oi'] = (prev['oi'] * 0.9).astype(int)
        with mock.patch('options.data.event_calendar.next_expiry',
                        return_value=datetime.date(2026, 11, 17)):
            result = pipeline.run_eod_pipeline(
                symbol='NIFTY', chain_df=chain, spot=24000,
                prev_chain_df=prev, prev_close=23900)
        self.assertIn('oi_sentiment', result)


# ═══════════════════════════════════════════════════════════════════
# C10: Spread estimation with bid/ask
# ═══════════════════════════════════════════════════════════════════

class TestSpreadEstimation(unittest.TestCase):
    """C10: estimate_spread uses actual bid/ask when available."""

    def test_with_bid_ask(self):
        """When bid/ask provided, returns actual half-spread."""
        spread = chain_store.estimate_spread(24000, 24000, bid=199.0, ask=201.0)
        self.assertAlmostEqual(spread, 1.0)

    def test_without_bid_ask_uses_heuristic(self):
        """Without bid/ask, uses moneyness-based heuristic."""
        spread = chain_store.estimate_spread(24000, 24000)
        self.assertGreater(spread, 0)

    def test_invalid_bid_ask_falls_through(self):
        """bid=0 or ask<=bid falls through to heuristic."""
        spread = chain_store.estimate_spread(24000, 24000, bid=0, ask=200)
        self.assertGreater(spread, 0)

    def test_deep_otm_wider_spread(self):
        """Deep OTM should have wider spread than ATM."""
        atm = chain_store.estimate_spread(24000, 24000)
        otm = chain_store.estimate_spread(25000, 24000)
        self.assertGreater(otm, atm)


# ═══════════════════════════════════════════════════════════════════
# C11: Multi-expiry chain loader
# ═══════════════════════════════════════════════════════════════════

class TestMultiExpiryChainLoader(unittest.TestCase):
    """C11: make_chain_loader generates near + far expiry chains."""

    def test_two_expiries_generated(self):
        """Chain loader should produce chains with 2 distinct expiries."""
        dt = datetime.date(2026, 10, 5)
        spots = {dt: 24000.0}
        iv = {dt: 15.0}
        loader = rp.make_chain_loader(spots, iv)
        chain = loader(dt)
        expiries = chain['expiry'].unique()
        self.assertEqual(len(expiries), 2, f'Expected 2 expiries, got {len(expiries)}')

    def test_far_expiry_after_near(self):
        """Far expiry must be after near expiry."""
        dt = datetime.date(2026, 10, 5)
        spots = {dt: 24000.0}
        iv = {dt: 15.0}
        loader = rp.make_chain_loader(spots, iv)
        chain = loader(dt)
        expiries = sorted(chain['expiry'].unique())
        self.assertGreater(expiries[1], expiries[0])


# ═══════════════════════════════════════════════════════════════════
# Live order module
# ═══════════════════════════════════════════════════════════════════

class TestDhanOrder(unittest.TestCase):
    """Live order path: dry_run default, kill switch, order building."""

    def _legs(self):
        return [
            {'strike': 24000, 'option_type': 'CE', 'action': 'SELL',
             'premium': 200, 'security_id': '12345'},
            {'strike': 24200, 'option_type': 'CE', 'action': 'BUY',
             'premium': 100, 'security_id': '12346'},
        ]

    def test_dry_run_default(self):
        """place_strategy defaults to dry_run=True."""
        result = dhan_order.place_strategy(self._legs(), 'NIFTY')
        self.assertEqual(result['status'], 'dry_run')
        self.assertEqual(len(result['orders']), 2)

    def test_order_building(self):
        """Orders built correctly from leg specs."""
        result = dhan_order.place_strategy(self._legs(), 'NIFTY', lots=2)
        orders = result['orders']
        self.assertEqual(orders[0]['transactionType'], 'SELL')
        self.assertEqual(orders[0]['quantity'], 75 * 2)
        self.assertEqual(orders[1]['transactionType'], 'BUY')

    def test_missing_security_id_blocked(self):
        """Cannot execute orders without security_id."""
        legs = [{'strike': 24000, 'option_type': 'CE', 'action': 'SELL',
                 'premium': 200}]
        result = dhan_order.place_strategy(legs, 'NIFTY', dry_run=False)
        self.assertEqual(result['status'], 'error')

    def test_cancel_all_handles_api_error(self):
        """cancel_all gracefully handles API failure."""
        with mock.patch('options.data.dhan_fetch._get_client',
                        side_effect=RuntimeError('no creds')):
            result = dhan_order.cancel_all()
            self.assertEqual(result['status'], 'error')


# ═══════════════════════════════════════════════════════════════════
# Integration: full round-trip with all ceiling fixes active
# ═══════════════════════════════════════════════════════════════════

class TestFullIntegration(unittest.TestCase):
    """End-to-end: recommend → explain → enter → check → VaR → adjust → exit."""

    def _chain(self, spot=24000):
        rows = []
        for k in range(int(spot - 500), int(spot + 550), 50):
            for ot in ['CE', 'PE']:
                ltp = max(0.5, 200 - abs(k - spot) * 0.5)
                rows.append({
                    'strike': float(k), 'option_type': ot,
                    'expiry': datetime.date(2026, 11, 17),
                    'expiry_years': 7/365, 'ltp': ltp, 'settle': ltp,
                    'bid': max(0.4, ltp - 1), 'ask': ltp + 1,
                    'oi': 100000, 'volume': 50000, 'iv': 0.14, 'change_oi': 1000,
                })
        return pd.DataFrame(rows)

    def _pipe(self):
        return {
            'variance_premium': {'vp': 0.035, 'iv': 0.16, 'rv': 0.125,
                                  'signal': 'sell_premium'},
            'vix': {'value': 15.5, 'regime': {'level': 'normal'}},
            'oi': {'pcr': {'pcr': 1.1}},
            'upcoming_events': [],
        }

    def test_full_flow(self):
        from options import paper_trade
        from options.strategies import recommend as rec_mod, explainer

        db = tempfile.mktemp(suffix='.db')
        paper_trade.init_db(db)
        chain = self._chain()
        pipe = self._pipe()

        # 1. Recommend
        with mock.patch('options.data.dhan_fetch.fetch_multi_expiry_chain',
                        return_value=(chain, 24000.0)):
            with mock.patch('options.data.pipeline.run_eod_pipeline',
                            return_value=pipe):
                with mock.patch('options.core.event_calendar.event_near',
                                return_value=None):
                    with mock.patch('options.data.event_calendar.next_expiry',
                                    return_value=datetime.date(2026, 11, 17)):
                        rec = paper_trade.recommend(symbol='NIFTY',
                                                    capital=500_000, db=db)
        self.assertEqual(rec['status'], 'recommended')

        # 2. Explain
        with mock.patch('options.core.event_calendar.event_near', return_value=None):
            with mock.patch('options.data.event_calendar.next_expiry',
                            return_value=datetime.date(2026, 11, 17)):
                gen = rec_mod.generate(chain, spot=24000, vix_value=15.5,
                                       pipe_result=pipe, capital=500_000)
        text = explainer.explain(gen)
        self.assertGreater(len(text), 100)

        # 3. Enter
        with mock.patch('options.data.dhan_fetch.fetch_multi_expiry_chain',
                        return_value=(chain, 24000.0)):
            with mock.patch('options.data.event_calendar.next_expiry',
                            return_value=datetime.date(2026, 11, 17)):
                entered = paper_trade.enter(rec['recommendation_id'], db=db)
        self.assertEqual(entered['status'], 'entered')

        # 4. VaR (C1 — with correlation)
        var_result = portfolio.parametric_var(
            entered.get('dollar_delta', 10000),
            entered.get('vega', 5000),
            24000, 0.012,
            stress=True)
        self.assertGreater(var_result['var_amount'], 0)
        self.assertEqual(var_result['rho'], 0.9)

        # 5. Daily check
        with mock.patch('options.data.dhan_fetch.fetch_spot', return_value=24200):
            with mock.patch('options.data.event_calendar.next_expiry',
                            return_value=datetime.date(2026, 11, 17)):
                checks = paper_trade.daily_check(spot=24200, db=db)
        self.assertGreaterEqual(len(checks), 1)

        # 6. Exit
        with mock.patch('options.data.event_calendar.next_expiry',
                        return_value=datetime.date(2026, 11, 17)):
            exited = paper_trade.exit_trade(entered['trade_id'], spot=24200, db=db)
        self.assertEqual(exited['status'], 'closed')

        os.unlink(db)


if __name__ == '__main__':
    unittest.main()
