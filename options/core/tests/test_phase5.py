"""
Phase 5 tests: backtesting — metrics, engine, walk-forward, monte carlo, report.

Book cross-checks: Sinclair Ch.7 (GSR), Davey Ch.7/13/14 (WFA, MC, gates).
"""

import datetime
import math
import random
import pandas as pd
from options.core import bsm
from options.backtest import metrics, engine, walk_forward, monte_carlo, report
from options.strategies import regime, registry


# ── helpers ────────────────────────────────────────────────────────

SPOT = 24000.0
EXPIRY = datetime.date(2026, 9, 30)


def _synthetic_chain(dt, spot, expiry=EXPIRY, iv=0.16):
    rows = []
    t = max((expiry - dt).days, 1) / 365
    for k in range(int(spot - 500), int(spot + 600), 100):
        for ot in ['CE', 'PE']:
            p = max(0.05, bsm.bsm_price(spot, k, t, 0.07, iv, ot))
            rows.append({
                'strike': float(k), 'option_type': ot, 'expiry': expiry,
                'settle': round(p, 2), 'volume': 50000, 'oi': 100000,
            })
    return pd.DataFrame(rows)


def _spot_series(start, n_days=30, seed=42):
    rng = random.Random(seed)
    spots = {}
    s = SPOT
    for i in range(n_days):
        d = start + datetime.timedelta(days=i)
        if d.weekday() < 5:
            s += rng.gauss(0, 50)
            spots[d] = round(s, 2)
    return spots


def _make_loader(spots, expiry=EXPIRY):
    cache = {}
    def loader(dt):
        if dt not in spots:
            return None
        if dt not in cache:
            cache[dt] = _synthetic_chain(dt, spots[dt], expiry)
        return cache[dt]
    return loader


# ── metrics tests ─────────────────────────────────────────────────

class TestMetrics:
    def test_sharpe_positive_returns(self):
        rng = random.Random(1)
        rets = [0.01 + rng.gauss(0, 0.001) for _ in range(50)]
        sr = metrics.sharpe_ratio(rets, risk_free_annual=0.0)
        assert sr > 0, f"Positive returns → SR > 0, got {sr}"

    def test_sharpe_empty(self):
        assert metrics.sharpe_ratio([]) == 0.0
        assert metrics.sharpe_ratio([0.01]) == 0.0

    def test_sortino_only_downside(self):
        rets = [0.01] * 40 + [-0.05] * 10
        sr = metrics.sharpe_ratio(rets, 0.0)
        so = metrics.sortino_ratio(rets, 0.0)
        assert so != sr, "Sortino should differ from Sharpe with asymmetric returns"

    def test_gsr_penalises_short_vol(self):
        """Sinclair Ch.7: GSR < SR for negatively skewed, fat-tailed returns."""
        random.seed(42)
        short_vol = [0.003] * 90 + [-0.05] * 10
        random.shuffle(short_vol)
        sr = metrics.sharpe_ratio(short_vol, 0.0)
        g = metrics.gsr(short_vol, 0.0)
        assert g < sr, f"GSR ({g}) must be < SR ({sr}) for short-vol"

    def test_gsr_normal_close_to_sr(self):
        random.seed(42)
        normal = [random.gauss(0.001, 0.01) for _ in range(200)]
        sr = metrics.sharpe_ratio(normal, 0.0)
        g = metrics.gsr(normal, 0.0)
        assert abs(g - sr) < abs(sr) * 0.4, f"Normal: GSR ({g}) ≈ SR ({sr})"

    def test_max_drawdown(self):
        eq = [100, 110, 105, 95, 90, 100, 85, 95]
        dd = metrics.max_drawdown(eq)
        assert dd['amount'] == 25.0
        assert abs(dd['pct'] - 22.73) < 0.1

    def test_max_drawdown_monotonic_up(self):
        dd = metrics.max_drawdown([100, 110, 120, 130])
        assert dd['amount'] == 0.0

    def test_return_dd_ratio(self):
        trades = [{'net_pnl': 100}, {'net_pnl': -50}, {'net_pnl': 200}]
        rdd = metrics.return_dd_ratio(trades)
        assert rdd > 0, f"Positive net → positive return/DD, got {rdd}"

    def test_return_dd_all_losers(self):
        trades = [{'net_pnl': -100}, {'net_pnl': -200}]
        assert metrics.return_dd_ratio(trades) == 0.0

    def test_profit_factor(self):
        trades = [{'net_pnl': 300}, {'net_pnl': -100}]
        assert metrics.profit_factor(trades) == 3.0

    def test_win_rate(self):
        trades = [{'net_pnl': 10}, {'net_pnl': -5}, {'net_pnl': 20}]
        assert metrics.win_rate(trades) == pytest_approx(66.7, 0.1)

    def test_tharp_expectancy(self):
        trades = [{'net_pnl': 100}, {'net_pnl': -50}, {'net_pnl': 80}]
        te = metrics.tharp_expectancy(trades)
        assert te > 0, f"Positive edge → positive Tharp, got {te}"

    def test_equity_from_trades(self):
        trades = [{'net_pnl': 100}, {'net_pnl': -30}, {'net_pnl': 50}]
        eq = metrics.equity_from_trades(trades, initial=1000)
        assert eq == [1000, 1100, 1070, 1120]

    def test_compute_all_keys(self):
        trades = [{'net_pnl': 100, 'gross_pnl': 120, 'costs_total': 20}]
        result = metrics.compute_all(trades)
        for key in ['sharpe', 'sortino', 'gsr', 'calmar', 'return_dd_ratio',
                     'profit_factor', 'win_rate_pct', 'max_drawdown',
                     'avg_trade', 'tharp_expectancy', 'total_trades',
                     'net_pnl', 'total_costs', 'cost_pct_of_gross']:
            assert key in result, f"Missing key: {key}"


# ── engine tests ─────────────────────────────────────────────────

class TestEngine:
    def test_basic_run(self):
        start = datetime.date(2026, 9, 1)
        spots = _spot_series(start, 30)
        loader = _make_loader(spots)

        result = engine.run({
            'strategy_key': 'short_straddle',
            'lot_size': 65,
            'signal_mode': 'always',
            'entry_dte_range': (5, 35),
            'exit_dte': 2,
        }, loader, spots)

        assert len(result['trades']) >= 1
        assert len(result['equity_curve']) > 1
        assert 'metrics' in result

    def test_costs_always_positive(self):
        start = datetime.date(2026, 9, 1)
        spots = _spot_series(start, 30)
        loader = _make_loader(spots)

        result = engine.run({
            'strategy_key': 'short_straddle',
            'lot_size': 65,
            'signal_mode': 'always',
            'entry_dte_range': (5, 35),
        }, loader, spots)

        for t in result['trades']:
            assert t['costs_total'] > 0, f"Trade {t['trade_id']}: costs must be > 0"

    def test_no_chain_skips_day(self):
        spots = {datetime.date(2026, 9, 1): 24000, datetime.date(2026, 9, 2): 24010}
        def empty_loader(dt):
            return None

        result = engine.run({
            'strategy_key': 'short_straddle',
            'signal_mode': 'always',
        }, empty_loader, spots)

        assert len(result['trades']) == 0

    def test_fill_simulation_buy_higher(self):
        """Buy fills must be above LTP, sell fills below."""
        fill_buy = engine._fill_price(100.0, 0.10, 'BUY', 1.5)
        fill_sell = engine._fill_price(100.0, 0.10, 'SELL', 1.5)
        assert fill_buy > 100.0, f"Buy fill {fill_buy} must be > LTP 100"
        assert fill_sell < 100.0, f"Sell fill {fill_sell} must be < LTP 100"

    def test_vp_signal_mode(self):
        """VP mode: only enter when IV - RV >= threshold."""
        start = datetime.date(2026, 8, 1)
        spots = _spot_series(start, 60, seed=7)
        loader = _make_loader(spots)

        result = engine.run({
            'strategy_key': 'short_straddle',
            'lot_size': 65,
            'signal_mode': 'vp',
            'entry_dte_range': (5, 45),
            'rv_window': 15,
            'vp_threshold': 0.0,
        }, loader, spots)

        assert 'metrics' in result
        # High threshold should produce fewer or no trades
        result_strict = engine.run({
            'strategy_key': 'short_straddle',
            'lot_size': 65,
            'signal_mode': 'vp',
            'entry_dte_range': (5, 45),
            'rv_window': 15,
            'vp_threshold': 1.0,
        }, loader, spots)

        assert len(result_strict['trades']) <= len(result['trades'])

    def test_multi_lot_exit_threshold(self):
        """Multi-lot must not trigger profit/stop earlier than single-lot."""
        start = datetime.date(2026, 9, 1)
        spots = _spot_series(start, 30)
        loader = _make_loader(spots)
        base = {
            'strategy_key': 'iron_condor',
            'lot_size': 65,
            'signal_mode': 'always',
            'entry_dte_range': (5, 35),
            'profit_target_pct': 0.50,
        }

        r1 = engine.run(dict(base, max_lots=1), loader, spots)
        r2 = engine.run(dict(base, max_lots=2), loader, spots)

        if r1['trades'] and r2['trades']:
            assert r1['trades'][0]['exit_date'] == r2['trades'][0]['exit_date'], \
                f"1-lot exit {r1['trades'][0]['exit_date']} != 2-lot exit {r2['trades'][0]['exit_date']}"
            assert r1['trades'][0]['exit_reason'] == r2['trades'][0]['exit_reason']

    def test_low_volume_wider_spread(self):
        """Low-volume options get wider synthetic spreads (C10)."""
        from options.core import iv as iv_mod
        dt = datetime.date(2026, 9, 15)
        rows = []
        for k in [23500, 24500]:
            for ot in ['CE', 'PE']:
                p = max(0.05, bsm.bsm_price(24000, k, 15 / 365, 0.07, 0.16, ot))
                vol = 100000 if k == 23500 else 100
                rows.append({'strike': float(k), 'option_type': ot,
                             'expiry': datetime.date(2026, 9, 30),
                             'settle': round(p, 2), 'volume': vol, 'oi': 50000})
        chain_raw = pd.DataFrame(rows)
        chain = engine._enrich_chain(chain_raw, 24000, dt, 0.07, iv_mod, 65)

        high_vol = chain[chain['strike'] == 23500.0].iloc[0]['spread']
        low_vol = chain[chain['strike'] == 24500.0].iloc[0]['spread']
        assert low_vol > high_vol, \
            f"Low-volume spread ({low_vol}) must exceed high-volume ({high_vol})"

    def test_iron_condor(self):
        start = datetime.date(2026, 9, 1)
        spots = _spot_series(start, 30)
        loader = _make_loader(spots)

        result = engine.run({
            'strategy_key': 'iron_condor',
            'lot_size': 65,
            'signal_mode': 'always',
            'entry_dte_range': (5, 35),
        }, loader, spots)

        assert 'metrics' in result


# ── walk-forward tests ────────────────────────────────────────────

class TestWalkForward:
    def test_window_splitting(self):
        dates = [datetime.date(2026, 1, 1) + datetime.timedelta(days=i) for i in range(100)]
        wc = {'in_ratio': 0.70, 'out_ratio': 0.30, 'n_windows': 3, 'anchored': False}
        windows = walk_forward._split_windows(dates, wc)
        assert len(windows) >= 1
        for in_d, out_d in windows:
            assert len(in_d) > 0
            assert len(out_d) > 0
            assert in_d[-1] < out_d[0], "In-sample must end before out-of-sample"

    def test_grid_combos(self):
        grid = {'a': [1, 2], 'b': [10, 20]}
        combos = walk_forward._grid_combos(grid)
        assert len(combos) == 4

    def test_basic_wfa(self):
        start = datetime.date(2026, 6, 1)
        expiry_dates = [datetime.date(2026, m, 25) for m in range(6, 11)]
        spots = {}
        rng = random.Random(99)
        s = SPOT
        for i in range(150):
            d = start + datetime.timedelta(days=i)
            if d.weekday() < 5:
                s += rng.gauss(0, 40)
                spots[d] = round(s, 2)

        cache = {}
        def loader(dt):
            if dt not in spots:
                return None
            if dt not in cache:
                near = min((e for e in expiry_dates if e >= dt), default=None)
                if not near:
                    return None
                cache[dt] = _synthetic_chain(dt, spots[dt], near)
            return cache[dt]

        result = walk_forward.run_wfa(
            {'strategy_key': 'short_straddle', 'lot_size': 65, 'signal_mode': 'always'},
            loader, spots,
            {'n_windows': 2, 'param_grid': {'entry_dte_min': [7, 14], 'entry_dte_max': [25, 35]}},
        )

        assert len(result['windows']) >= 1
        assert 'oos_metrics' in result


# ── monte carlo tests ─────────────────────────────────────────────

class TestMonteCarlo:
    def test_basic_mc(self):
        trades = [{'net_pnl': 5000}] * 14 + [{'net_pnl': -10000}] * 6
        result = monte_carlo.run_mc(trades, {'n_sims': 1000, 'seed': 42})

        assert result['n_sims'] == 1000
        assert result['n_trades'] == 20
        assert result['median_return_pct'] > 0
        assert result['median_dd_pct'] > 0

    def test_all_winners_no_ruin(self):
        trades = [{'net_pnl': 1000}] * 20
        result = monte_carlo.run_mc(trades, {'n_sims': 500, 'seed': 1})
        assert result['risk_of_ruin_pct'] == 0.0
        assert result['median_dd_pct'] == 0.0

    def test_too_few_trades(self):
        result = monte_carlo.run_mc([{'net_pnl': 100}], {'n_sims': 100})
        assert result['n_sims'] == 0

    def test_deterministic_with_seed(self):
        trades = [{'net_pnl': 500}] * 10 + [{'net_pnl': -800}] * 5
        r1 = monte_carlo.run_mc(trades, {'n_sims': 100, 'seed': 7})
        r2 = monte_carlo.run_mc(trades, {'n_sims': 100, 'seed': 7})
        assert r1['median_dd_pct'] == r2['median_dd_pct']


# ── report tests ──────────────────────────────────────────────────

class TestReport:
    def test_report_structure(self):
        trades = [
            {'trade_id': 1, 'net_pnl': 5000, 'gross_pnl': 5200, 'costs_total': 200,
             'entry_date': '2026-09-01', 'exit_date': '2026-09-15', 'holding_days': 14,
             'exit_reason': 'profit_target'},
        ]
        engine_result = {
            'trades': trades,
            'equity_curve': [1_000_000, 1_005_000],
            'equity_dates': [datetime.date(2026, 9, 1), datetime.date(2026, 9, 15)],
            'metrics': metrics.compute_all(trades),
            'config': {'strategy_key': 'short_straddle', 'symbol': 'NIFTY'},
            'warnings': [],
        }
        r = report.generate(engine_result)
        assert 'summary' in r
        assert 'risk_metrics' in r
        assert 'davey_gates' in r
        assert 'cost_analysis' in r
        assert r['strategy'] == 'short_straddle'

    def test_summary_text(self):
        trades = [{'trade_id': 1, 'net_pnl': 5000, 'gross_pnl': 5200, 'costs_total': 200,
                    'entry_date': '2026-09-01', 'exit_date': '2026-09-15',
                    'holding_days': 14, 'exit_reason': 'dte_2'}]
        engine_result = {
            'trades': trades,
            'equity_curve': [1_000_000, 1_005_000],
            'equity_dates': [datetime.date(2026, 9, 1), datetime.date(2026, 9, 15)],
            'metrics': metrics.compute_all(trades),
            'config': {'strategy_key': 'iron_condor', 'symbol': 'NIFTY'},
            'warnings': [],
        }
        txt = report.summary_text(report.generate(engine_result))
        assert 'iron_condor' in txt
        assert 'Davey gates' in txt

    def test_davey_gates_with_mc(self):
        m = {'return_dd_ratio': 3.0, 'profit_factor': 1.5,
             'max_drawdown': {'pct': 15}, 'total_trades': 50}
        mc = {'risk_of_ruin_pct': 2.0}
        gates = report._davey_gates(m, mc)
        assert gates['return_dd_ratio']['pass'] is True
        assert gates['mc_risk_of_ruin']['pass'] is True


# ── regime tests ─────────────────────────────────────────────────

class TestRegime:
    def test_detect_uptrend(self):
        spots = [100 + i * 0.5 for i in range(30)]
        r = regime.detect_regime(spots, 29, None, 0.18, 0.14)
        assert r['trend'] == 'up'
        assert r['vp'] == 'sell_vol'
        assert r['trend_strength'] > 0

    def test_detect_downtrend(self):
        spots = [100 - i * 0.5 for i in range(30)]
        r = regime.detect_regime(spots, 29, None, 0.12, 0.18)
        assert r['trend'] == 'down'
        assert r['vp'] == 'buy_vol'

    def test_detect_flat(self):
        spots = [100 + (i % 3 - 1) * 0.1 for i in range(30)]
        r = regime.detect_regime(spots, 29, None, 0.15, 0.14)
        assert r['trend'] == 'flat'

    def test_edge_empty_spots(self):
        r = regime.detect_regime([], 0, None, 0.15, 0.10)
        assert r['trend'] == 'flat'
        assert r['vp'] == 'sell_vol'

    def test_edge_short_history(self):
        r = regime.detect_regime([100, 101], 1, None, 0.15, 0.10, lookback=20)
        assert r['trend'] == 'flat'

    def test_edge_none_iv(self):
        spots = [100 + i for i in range(30)]
        r = regime.detect_regime(spots, 29, None, None, 0.10)
        assert r['vp'] == 'neutral'

    def test_edge_nan_rv(self):
        import math
        spots = [100 + i for i in range(30)]
        r = regime.detect_regime(spots, 29, None, 0.15, float('nan'))
        assert r['vp'] == 'neutral'

    def test_strategy_fits_income_blocks_buy_vol(self):
        """Sinclair: never sell premium when IV < RV."""
        strat = registry.get('short_straddle')
        reg = {'trend': 'flat', 'vp': 'buy_vol', 'trend_strength': 0.5, 'vp_value': -0.03}
        assert regime.strategy_fits_regime(strat, reg) is False

    def test_strategy_fits_income_allows_sell_vol_flat(self):
        strat = registry.get('short_straddle')
        reg = {'trend': 'flat', 'vp': 'sell_vol', 'trend_strength': 0.8, 'vp_value': 0.04}
        assert regime.strategy_fits_regime(strat, reg) is True

    def test_strategy_fits_bearish_blocks_uptrend(self):
        """Cohen: don't buy puts in uptrend."""
        strat = registry.get('long_put')
        reg = {'trend': 'up', 'vp': 'neutral', 'trend_strength': 0.7, 'vp_value': 0.0}
        assert regime.strategy_fits_regime(strat, reg) is False

    def test_strategy_fits_bearish_allows_downtrend(self):
        strat = registry.get('long_put')
        reg = {'trend': 'down', 'vp': 'neutral', 'trend_strength': 0.7, 'vp_value': 0.0}
        assert regime.strategy_fits_regime(strat, reg) is True

    def test_engine_regime_signal_mode(self):
        """Engine should accept signal_mode='regime' without error."""
        start = datetime.date(2026, 9, 1)
        spots = _spot_series(start, 30)
        loader = _make_loader(spots)
        result = engine.run({
            'strategy_key': 'short_straddle',
            'lot_size': 65,
            'signal_mode': 'regime',
            'entry_dte_range': (5, 35),
        }, loader, spots)
        assert 'metrics' in result
        # Regime filter should produce <= trades vs 'always'
        result_always = engine.run({
            'strategy_key': 'short_straddle',
            'lot_size': 65,
            'signal_mode': 'always',
            'entry_dte_range': (5, 35),
        }, loader, spots)
        assert len(result['trades']) <= len(result_always['trades'])


# ── runner ────────────────────────────────────────────────────────

def pytest_approx(expected, abs_tol):
    """Simple approx for non-pytest runner."""
    class _Approx:
        def __eq__(self, other):
            return abs(other - expected) <= abs_tol
        def __repr__(self):
            return f"≈{expected}±{abs_tol}"
    return _Approx()


def _run_all():
    passed = 0
    failed = 0

    for cls in [TestMetrics, TestEngine, TestWalkForward, TestMonteCarlo, TestReport, TestRegime]:
        obj = cls()
        for name in sorted(dir(obj)):
            if not name.startswith('test_'):
                continue
            try:
                getattr(obj, name)()
                passed += 1
            except Exception as e:
                failed += 1
                print(f"  FAIL {cls.__name__}.{name}: {e}")

    print(f"\ntest_phase5.py: {passed} passed, {failed} failed")
    assert failed == 0, f"{failed} test(s) failed"


if __name__ == '__main__':
    _run_all()
