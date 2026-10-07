"""
Phase 2 tests: vol_forecast, vol_surface, and all data modules.

Run: python -m pytest options/core/tests/test_phase2.py -v
"""

import math
import datetime
import tempfile
import os
import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gbm_prices(n=500, true_vol=0.20, seed=42):
    """Generate GBM prices for testing."""
    np.random.seed(seed)
    dt = 1 / 252
    prices = [100.0]
    for _ in range(n):
        z = np.random.randn()
        prices.append(prices[-1] * math.exp(-0.5 * true_vol ** 2 * dt + true_vol * math.sqrt(dt) * z))
    return np.array(prices)


def _synthetic_chain(spot=24000):
    """Build synthetic chain DataFrame."""
    rows = []
    for exp_y in [7 / 365, 30 / 365, 90 / 365]:
        for otype in ['CE', 'PE']:
            for strike in range(22000, 26001, 100):
                moneyness = strike / spot
                base_iv = 0.14
                if otype == 'PE':
                    base_iv += max(0, (1 - moneyness)) * 0.3
                else:
                    base_iv += max(0, (moneyness - 1)) * 0.15
                base_iv += exp_y * 0.05

                oi = max(0, int(50000 - abs(strike - spot) * 20 + np.random.normal(0, 3000)))
                rows.append({
                    'strike': strike, 'expiry_years': exp_y,
                    'option_type': otype, 'iv': base_iv,
                    'oi': oi, 'volume': oi // 5,
                    'ltp': 100.0, 'bid': 99.0, 'ask': 101.0,
                    'expiry': datetime.date.today() + datetime.timedelta(days=int(exp_y * 365)),
                    'change_oi': int(np.random.normal(0, 1000)),
                })
    return pd.DataFrame(rows)


# ===========================================================================
# core/vol_forecast.py
# ===========================================================================

class TestEWMA:
    def test_basic(self):
        from options.core.vol_forecast import ewma_vol
        prices = _gbm_prices()
        r = np.log(prices[1:] / prices[:-1])
        vol = ewma_vol(r)
        assert 0.10 < vol < 0.35

    def test_lambda_sensitivity(self):
        from options.core.vol_forecast import ewma_vol
        r = np.log(_gbm_prices()[1:] / _gbm_prices()[:-1])
        fast = ewma_vol(r, lambda_=0.90)
        slow = ewma_vol(r, lambda_=0.97)
        # both should be reasonable, but can differ
        assert 0.05 < fast < 0.50
        assert 0.05 < slow < 0.50

    def test_too_short(self):
        from options.core.vol_forecast import ewma_vol
        assert math.isnan(ewma_vol([0.01]))


class TestGARCH:
    def test_basic(self):
        from options.core.vol_forecast import garch_vol
        r = np.log(_gbm_prices()[1:] / _gbm_prices()[:-1])
        g = garch_vol(r)
        assert 0.10 < g['forecast'] < 0.40
        assert g['persistence'] < 1.0
        assert g['alpha'] > 0
        assert g['beta'] > 0

    def test_too_short(self):
        from options.core.vol_forecast import garch_vol
        g = garch_vol(np.array([0.01] * 10))
        assert math.isnan(g['forecast'])


class TestMeanReversion:
    def test_basic(self):
        from options.core.vol_forecast import mean_reversion_vol
        prices = _gbm_prices()
        m = mean_reversion_vol(prices)
        assert 0.10 < m['forecast'] < 0.35
        assert len(m['components']) > 0
        assert m['long_run'] > 0


class TestEnsemble:
    def test_basic(self):
        from options.core.vol_forecast import ensemble_forecast
        prices = _gbm_prices()
        e = ensemble_forecast(prices)
        assert 0.10 < e['forecast'] < 0.35
        lo, hi = e['confidence']
        assert lo < e['forecast'] < hi

    def test_has_all_components(self):
        from options.core.vol_forecast import ensemble_forecast
        e = ensemble_forecast(_gbm_prices())
        for key in ['ewma', 'garch', 'garch_long_run', 'mean_rev']:
            assert key in e


class TestVariancePremium:
    def test_basic(self):
        from options.core.vol_forecast import variance_premium, vp_percentile
        assert abs(variance_premium(0.20, 0.15) - 0.05) < 1e-10
        assert abs(variance_premium(0.10, 0.15) - (-0.05)) < 1e-10

    def test_percentile(self):
        from options.core.vol_forecast import vp_percentile
        p = vp_percentile(0.03, [0.01, 0.02, 0.03, 0.04, 0.05])
        assert p == 60.0


# ===========================================================================
# core/vol_surface.py
# ===========================================================================

class TestTermStructure:
    def test_basic(self):
        from options.core.vol_surface import term_structure
        np.random.seed(42)
        chain = _synthetic_chain()
        ts = term_structure(chain, 24000)
        assert len(ts) == 3
        assert list(ts.columns) == ['expiry_years', 'expiry_days', 'atm_iv', 'n_strikes']

    def test_upward_sloping(self):
        from options.core.vol_surface import term_structure, is_inverted
        np.random.seed(42)
        ts = term_structure(_synthetic_chain(), 24000)
        # synthetic chain has positive term structure
        assert ts.iloc[0]['atm_iv'] < ts.iloc[-1]['atm_iv']
        assert not is_inverted(ts)


class TestSkewMetrics:
    def test_basic(self):
        from options.core.vol_surface import skew_metrics
        np.random.seed(42)
        chain = _synthetic_chain()
        sm = skew_metrics(chain, 30 / 365, 24000)
        assert sm['skew_25d'] > 0  # normal negative skew = put IV > call IV
        assert sm['skew_ratio'] > 1.0

    def test_butterfly(self):
        from options.core.vol_surface import skew_metrics
        np.random.seed(42)
        sm = skew_metrics(_synthetic_chain(), 30 / 365, 24000)
        assert 'butterfly' in sm


class TestBuildSurface:
    def test_basic(self):
        from options.core.vol_surface import build_surface
        np.random.seed(42)
        surf = build_surface(_synthetic_chain(), 24000)
        assert not surf['surface'].empty
        assert len(surf['skew_by_exp']) == 3
        assert not surf['term_struct'].empty


# ===========================================================================
# data modules
# ===========================================================================

class TestRate:
    def test_current(self):
        from options.data.rate import risk_free_rate, CURRENT_RATE
        assert risk_free_rate() == CURRENT_RATE
        assert 0.03 < CURRENT_RATE < 0.10

    def test_historical(self):
        from options.data.rate import risk_free_rate
        assert risk_free_rate(datetime.date(2024, 7, 1)) == 0.065


class TestEventCalendar:
    def test_upcoming(self):
        from options.data.event_calendar import upcoming_events
        events = upcoming_events(30, as_of=datetime.date(2026, 10, 1))
        assert len(events) > 0

    def test_next_expiry(self):
        from options.data.event_calendar import next_expiry
        exp = next_expiry('NIFTY', as_of=datetime.date(2026, 10, 5))
        # should be a weekday
        assert exp.weekday() < 5

    def test_event_window(self):
        from options.data.event_calendar import event_iv_window
        w = event_iv_window(as_of=datetime.date(2026, 10, 5), window_days=5)
        assert w is not None


class TestOIAnalysis:
    def test_pcr(self):
        from options.data.oi_analysis import pcr_oi
        np.random.seed(42)
        chain = _synthetic_chain()
        pcr = pcr_oi(chain)
        assert pcr['pcr'] == pcr['pcr']  # not NaN
        assert pcr['total_call_oi'] > 0

    def test_pcr_contrarian(self):
        from options.data.oi_analysis import pcr_oi
        np.random.seed(42)
        chain = _synthetic_chain()
        pcr = pcr_oi(chain)
        assert 'contrarian' in pcr
        # crowd and contrarian should be opposite when extreme
        high_put = pd.DataFrame([
            {'strike': 24000, 'option_type': 'CE', 'oi': 10000},
            {'strike': 24000, 'option_type': 'PE', 'oi': 20000},
        ])
        r = pcr_oi(high_put)
        assert r['signal'] == 'bearish_extreme'
        assert r['contrarian'] == 'bullish'

    def test_max_pain(self):
        from options.data.oi_analysis import max_pain
        np.random.seed(42)
        chain = _synthetic_chain()
        mp = max_pain(chain)
        assert 22000 <= mp['max_pain_strike'] <= 26000

    def test_support_resistance(self):
        from options.data.oi_analysis import oi_support_resistance
        np.random.seed(42)
        chain = _synthetic_chain()
        sr = oi_support_resistance(chain, 24000)
        assert len(sr['support']) > 0
        assert len(sr['resistance']) > 0

    def test_regime(self):
        from options.data.oi_analysis import oi_price_regime
        r = oi_price_regime(100, 50000)
        assert r['regime'] == 'long_build'
        assert r['signal'] == 'bullish'


class TestIndiaVIX:
    def test_regime(self):
        from options.data.india_vix import vix_regime
        assert vix_regime(12)['vol_selling_ok'] is True
        assert vix_regime(30)['vol_selling_ok'] is False
        assert vix_regime(9)['level'] == 'extreme_low'
        assert vix_regime(50)['level'] == 'crisis'

    def test_mean_reversion(self):
        from options.data.india_vix import vix_mean_reversion_signal
        sig = vix_mean_reversion_signal(8)
        assert sig['expected_direction'] == 'up'


class TestChain:
    def test_mwpl(self):
        from options.data.chain import mwpl_check
        assert mwpl_check(960000, 1000000)['status'] == 'ban'
        assert mwpl_check(500000, 1000000)['status'] == 'normal'

    def test_lot_size(self):
        from options.data.chain import lot_size
        assert lot_size('NIFTY') == 65
        assert lot_size('BANKNIFTY') == 30


class TestFIIDII:
    def test_sentiment(self):
        from options.data.fii_dii import fii_dii_sentiment
        s = fii_dii_sentiment(100000, 70000)
        assert s['fii_sentiment'] == 'bullish'

    def test_zero_positions(self):
        from options.data.fii_dii import fii_dii_sentiment
        s = fii_dii_sentiment(0, 0)
        assert s['fii_sentiment'] == 'no_data'
        assert math.isnan(s['fii_ratio'])
        assert s['divergence'] is False

    def test_divergence(self):
        from options.data.fii_dii import fii_dii_sentiment
        # FII bullish, DII bearish → divergence
        s = fii_dii_sentiment(100000, 50000, dii_long=30000, dii_short=60000)
        assert s['divergence'] is True
        # FII no_data, DII bullish → no divergence (can't diverge from no data)
        s2 = fii_dii_sentiment(0, 0, dii_long=100000, dii_short=50000)
        assert s2['divergence'] is False

    def test_option_bias(self):
        from options.data.fii_dii import fii_option_bias
        pos = {
            'option_call_long': 80000, 'option_call_short': 50000,
            'option_put_long': 40000, 'option_put_short': 70000,
        }
        b = fii_option_bias(pos)
        assert b['bias'] == 'bullish'


class TestChainStore:
    def test_roundtrip(self):
        from options.data.chain_store import init_db, store_snapshot, get_chain_snapshot
        db = os.path.join(tempfile.gettempdir(), 'test_phase2_chain.db')
        if os.path.exists(db):
            os.remove(db)

        init_db(db)
        chain = pd.DataFrame([
            {'strike': 24000, 'option_type': 'CE', 'expiry': '2026-10-08',
             'ltp': 150, 'bid': 149, 'ask': 151, 'oi': 50000, 'volume': 10000,
             'iv': 0.14, 'change_oi': 5000},
        ])
        store_snapshot(chain, 'NIFTY', '2026-10-06T15:30:00', db)
        result = get_chain_snapshot('NIFTY', db_path=db)
        assert len(result) == 1
        os.remove(db)

    def test_spread_estimate(self):
        from options.data.chain_store import estimate_spread
        assert estimate_spread(24000, 24000) == 0.05  # ATM
        assert estimate_spread(25000, 24000) > 0.10   # OTM

    def test_analytics_roundtrip(self):
        from options.data.chain_store import init_db, store_analytics, get_analytics
        db = os.path.join(tempfile.gettempdir(), 'test_phase2_analytics.db')
        if os.path.exists(db):
            os.remove(db)
        init_db(db)

        store_analytics('2026-10-06', 'NIFTY', {
            'pcr': (0.95, {'signal': 'neutral'}),
            'max_pain': 24000,
            'vix': 14.5,
            'spot': 24100,
        }, db)

        df = get_analytics('NIFTY', db_path=db)
        assert len(df) == 4
        assert set(df['metric']) == {'pcr', 'max_pain', 'vix', 'spot'}

        pcr_row = df[df['metric'] == 'pcr'].iloc[0]
        assert pcr_row['value'] == 0.95

        # test upsert: re-store same date updates instead of duplicating
        store_analytics('2026-10-06', 'NIFTY', {'pcr': (1.1, None)}, db)
        df2 = get_analytics('NIFTY', metric='pcr', db_path=db)
        assert len(df2) == 1
        assert df2.iloc[0]['value'] == 1.1

        os.remove(db)

    def test_bhavcopy_dedup(self):
        from options.data.chain_store import init_db, store_bhavcopy, get_bhavcopy
        db = os.path.join(tempfile.gettempdir(), 'test_phase2_bhav.db')
        if os.path.exists(db):
            os.remove(db)
        init_db(db)

        row = pd.DataFrame([{
            'date': '2026-10-06', 'symbol': 'NIFTY', 'expiry': '2026-10-08',
            'strike': 24000, 'option_type': 'CE',
            'open': 150, 'high': 160, 'low': 140, 'close': 155,
            'settle_price': 155, 'oi': 50000, 'volume': 10000,
        }])
        store_bhavcopy(row, db)
        store_bhavcopy(row, db)  # re-import should NOT duplicate
        result = get_bhavcopy('NIFTY', '2026-10-06', db_path=db)
        assert len(result) == 1, f'Expected 1 row after dedup, got {len(result)}'
        os.remove(db)


class TestEventCalendarExpiry:
    def test_expiry_week_mon_thu(self):
        from options.data.event_calendar import is_expiry_week
        # Oct 5-8 2026: Mon-Thu → all True
        assert is_expiry_week(datetime.date(2026, 10, 5)) is True   # Mon
        assert is_expiry_week(datetime.date(2026, 10, 6)) is True   # Tue
        assert is_expiry_week(datetime.date(2026, 10, 7)) is True   # Wed
        assert is_expiry_week(datetime.date(2026, 10, 8)) is True   # Thu
        assert is_expiry_week(datetime.date(2026, 10, 9)) is False  # Fri
        assert is_expiry_week(datetime.date(2026, 10, 10)) is False # Sat


class TestVolSurfaceOTM:
    def test_surface_uses_otm(self):
        from options.core.vol_surface import build_surface
        np.random.seed(42)
        chain = _synthetic_chain()
        surf = build_surface(chain, 24000)
        assert not surf['surface'].empty
        # surface should have strikes both above and below spot
        strikes = surf['surface'].index
        assert min(strikes) < 24000
        assert max(strikes) > 24000


class TestPipelineVP:
    def test_no_prices_gives_no_rv_data(self):
        from options.data.pipeline import run_vol_analysis
        np.random.seed(42)
        chain = _synthetic_chain()
        result = run_vol_analysis(prices=None, chain_df=chain, spot=24000)
        assert 'variance_premium' in result
        assert result['variance_premium']['signal'] == 'no_rv_data'
        assert math.isnan(result['variance_premium']['rv'])
        assert result['variance_premium']['iv'] > 0


class TestPipeline:
    def test_eod(self):
        from options.data.pipeline import run_eod_pipeline
        np.random.seed(42)
        chain = _synthetic_chain()
        result = run_eod_pipeline('NIFTY', chain_df=chain, spot=24000,
                                   vix_value=15.0, db_path=':memory:')
        assert result['status'] in ('ok', 'partial')
        assert 'oi' in result
        assert 'vix' in result

    def test_eod_persists_analytics(self):
        from options.data.pipeline import run_eod_pipeline
        from options.data.chain_store import init_db, get_analytics
        db = os.path.join(tempfile.gettempdir(), 'test_phase2_pipeline.db')
        if os.path.exists(db):
            os.remove(db)
        init_db(db)

        np.random.seed(42)
        chain = _synthetic_chain()
        result = run_eod_pipeline('NIFTY', chain_df=chain, spot=24000,
                                   vix_value=15.0, db_path=db)

        analytics = get_analytics('NIFTY', db_path=db)
        assert len(analytics) > 0
        metrics = set(analytics['metric'])
        assert 'pcr' in metrics
        assert 'max_pain' in metrics
        assert 'spot' in metrics
        assert 'vix' in metrics
        os.remove(db)
