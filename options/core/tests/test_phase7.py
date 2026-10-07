"""Phase 7: Incubation lifecycle tests (Davey Ch.14, Ch.23)."""

import json
import math
import os
import sqlite3
import tempfile
import unittest

from options.backtest import metrics, monte_carlo


class TestTTestOOS(unittest.TestCase):
    def test_profitable_significant(self):
        trades = [{'net_pnl': 5000}] * 25 + [{'net_pnl': -2000}] * 5
        r = metrics.t_test_oos(trades)
        self.assertTrue(r['significant'])
        self.assertLess(r['p_value'], 0.05)
        self.assertGreater(r['t_stat'], 0)

    def test_unprofitable(self):
        trades = [{'net_pnl': -3000}] * 20 + [{'net_pnl': 1000}] * 10
        r = metrics.t_test_oos(trades)
        self.assertFalse(r['significant'])

    def test_zero_trades(self):
        r = metrics.t_test_oos([{'net_pnl': 0}] * 10)
        self.assertFalse(r['significant'])
        self.assertAlmostEqual(r['p_value'], 1.0)

    def test_too_few_trades(self):
        r = metrics.t_test_oos([{'net_pnl': 100}])
        self.assertFalse(r['significant'])


class TestTTestCompare(unittest.TestCase):
    def test_same_distribution(self):
        wfa = [{'net_pnl': 1000 + i * 100} for i in range(30)]
        paper = [{'net_pnl': 1000 + i * 100} for i in range(30)]
        r = metrics.t_test_compare(paper, wfa)
        self.assertTrue(r['pass_incubation'])
        self.assertGreater(r['p_value'], 0.44)

    def test_different_distribution(self):
        wfa = [{'net_pnl': 5000}] * 30
        paper = [{'net_pnl': -5000}] * 30
        r = metrics.t_test_compare(paper, wfa)
        self.assertFalse(r['pass_incubation'])
        self.assertLess(r['p_value'], 0.10)

    def test_too_few(self):
        r = metrics.t_test_compare([{'net_pnl': 100}], [{'net_pnl': 200}])
        self.assertTrue(r['pass_incubation'])


class TestEfficiency(unittest.TestCase):
    def test_return_efficiency_normal(self):
        self.assertAlmostEqual(metrics.return_efficiency(80_000, 100_000), 0.8)

    def test_return_efficiency_zero_expected(self):
        self.assertEqual(metrics.return_efficiency(50_000, 0), 0.0)

    def test_dd_efficiency_better_than_expected(self):
        r = metrics.dd_efficiency(5.0, 10.0)
        self.assertAlmostEqual(r, 0.5)

    def test_dd_efficiency_worse_than_expected(self):
        r = metrics.dd_efficiency(15.0, 10.0)
        self.assertLess(r, 0)

    def test_dd_efficiency_zero_expected(self):
        r = metrics.dd_efficiency(5.0, 0.0)
        self.assertIsInstance(r, float)


class TestEquityBands(unittest.TestCase):
    def test_basic(self):
        b = metrics.equity_bands(100, 500, 2000)
        self.assertAlmostEqual(b['expected'], 50_000)
        self.assertAlmostEqual(b['upper_1sigma'], 50_000 + 10 * 2000)
        self.assertAlmostEqual(b['lower_1sigma'], 50_000 - 10 * 2000)
        self.assertAlmostEqual(b['upper_2sigma'], 50_000 + 20 * 2000)
        self.assertAlmostEqual(b['lower_2sigma'], 50_000 - 20 * 2000)

    def test_zero_std(self):
        b = metrics.equity_bands(50, 1000, 0)
        self.assertEqual(b['upper_1sigma'], b['expected'])
        self.assertEqual(b['lower_1sigma'], b['expected'])

    def test_zero_n(self):
        b = metrics.equity_bands(0, 1000, 500)
        self.assertEqual(b['expected'], 0)


class TestAbortThreshold(unittest.TestCase):
    def test_average_of_both(self):
        mc = {'max_dd_percentiles': {95: 20.0}, 'median_dd_pct': 15.0}
        r = monte_carlo.abort_threshold(10.0, mc)
        self.assertAlmostEqual(r['abort_dd_pct'], (15.0 + 20.0) / 2)
        self.assertEqual(r['source'], 'average')

    def test_hist_only(self):
        r = monte_carlo.abort_threshold(10.0, None)
        self.assertAlmostEqual(r['abort_dd_pct'], 15.0)
        self.assertEqual(r['source'], '1.5x_historical_only')

    def test_mc_only(self):
        mc = {'max_dd_percentiles': {95: 25.0}}
        r = monte_carlo.abort_threshold(0.0, mc)
        self.assertAlmostEqual(r['abort_dd_pct'], 25.0)
        self.assertEqual(r['source'], 'mc_95th_only')

    def test_fallback(self):
        r = monte_carlo.abort_threshold(0.0, None)
        self.assertAlmostEqual(r['abort_dd_pct'], 50.0)
        self.assertEqual(r['source'], 'default_50pct')


class TestLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = os.path.join(self.tmpdir, 'test_lifecycle.db')

        from options import paper_trade
        self.pt = paper_trade
        self.pt.init_db(self.db)

        self.report_path = os.path.join(self.tmpdir, 'wfa_report.json')
        trades = [{'net_pnl': 3000 + i * 100, 'gross_pnl': 3500 + i * 100,
                    'costs_total': 500, 'entry_date': '2026-01-01',
                    'exit_date': '2026-01-10', 'holding_days': 9}
                   for i in range(40)]
        report = {
            'walk_forward': {'oos_trades': trades},
            'risk_metrics': {'max_drawdown': {'pct': 8.5}},
            'summary': {'net_pnl': sum(t['net_pnl'] for t in trades)},
            'davey_gates': {
                'return_dd_ratio': {'pass': True},
                'profit_factor': {'pass': True},
                'max_dd_pct': {'pass': True},
                'min_trades': {'pass': True},
                'mc_risk_of_ruin': {'pass': True},
            },
        }
        with open(self.report_path, 'w') as f:
            json.dump(report, f)

    def test_incubate_starts(self):
        r = self.pt.incubate('test_strat', self.report_path, db=self.db)
        self.assertEqual(r['status'], 'incubating')
        self.assertEqual(r['wfa_trades'], 40)
        self.assertGreater(r['abort_dd_pct'], 0)

    def test_incubate_missing_report(self):
        r = self.pt.incubate('test_strat', '/nonexistent.json', db=self.db)
        self.assertEqual(r['status'], 'error')

    def test_check_lifecycle_no_trades(self):
        self.pt.incubate('test_strat', self.report_path, db=self.db)
        r = self.pt.check_lifecycle('test_strat', db=self.db)
        self.assertEqual(r['status'], 'incubating')
        self.assertEqual(r['trade_count'], 0)

    def test_check_lifecycle_not_found(self):
        r = self.pt.check_lifecycle('nonexistent', db=self.db)
        self.assertEqual(r['status'], 'error')

    def test_lifecycle_status_empty(self):
        import io
        import sys
        captured = io.StringIO()
        sys.stdout = captured
        self.pt.lifecycle_status(db=self.db)
        sys.stdout = sys.__stdout__
        self.assertIn('No strategies', captured.getvalue())

    def test_lifecycle_status_shows_strategy(self):
        self.pt.incubate('test_strat', self.report_path, db=self.db)
        import io
        import sys
        captured = io.StringIO()
        sys.stdout = captured
        self.pt.lifecycle_status(db=self.db)
        sys.stdout = sys.__stdout__
        output = captured.getvalue()
        self.assertIn('test_strat', output)
        self.assertIn('INCUBATING', output)

    def test_abort_on_dd_breach(self):
        self.pt.incubate('test_strat', self.report_path, db=self.db)
        conn = sqlite3.connect(self.db)
        # Insert paper trades with massive losses to breach DD
        for i in range(25):
            conn.execute(
                """INSERT INTO trades
                   (strategy, symbol, status, net_pnl, gross_pnl,
                    entry_cost, exit_cost, opened_at, closed_at,
                    entry_spot, legs, lots, lot_size)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ('test_strat', 'NIFTY', 'closed', -50000, -49000,
                 500, 500, '2026-05-01', '2026-06-01', 24000.0, '[]', 1, 50)
            )
        conn.commit()
        conn.close()

        r = self.pt.check_lifecycle('test_strat', db=self.db)
        self.assertEqual(r['status'], 'aborted')
        self.assertIn('DD', r.get('abort_reason', ''))

    def test_incubate_refuses_graduated(self):
        self.pt.incubate('test_strat', self.report_path, db=self.db)
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE strategy_lifecycle SET status='GRADUATED' WHERE strategy_key='test_strat'")
        conn.commit()
        conn.close()
        r = self.pt.incubate('test_strat', self.report_path, db=self.db)
        self.assertEqual(r['status'], 'error')
        self.assertIn('GRADUATED', r['reason'])

    def test_zero_trades_criteria_all_false(self):
        self.pt.incubate('test_strat', self.report_path, db=self.db)
        r = self.pt.check_lifecycle('test_strat', db=self.db)
        for key in ('t_test_compare', 'return_efficiency', 'dd_efficiency',
                     'equity_above_2sigma', 'mc_risk_of_ruin'):
            self.assertFalse(r['graduation_criteria'][key]['pass'],
                             f'{key} should be False with 0 trades')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class TestIncubateRealReports(unittest.TestCase):
    def test_long_strangle_report(self):
        import tempfile
        from options import paper_trade
        db = os.path.join(tempfile.mkdtemp(), 'test.db')
        report = 'options/backtest/reports/long_strangle_wfa_nifty.json'
        if not os.path.exists(report):
            self.skipTest('WFA report not found')
        r = paper_trade.incubate('ls_test', report, db=db)
        self.assertEqual(r['status'], 'incubating')
        self.assertGreater(r['wfa_trades'], 0)
        self.assertGreater(r['avg_pnl'], 0)
        self.assertGreater(r['abort_dd_pct'], 0)


class TestAbortThresholdJSONRoundtrip(unittest.TestCase):
    def test_string_keys_after_json(self):
        mc = {'max_dd_percentiles': {95: 25.0}}
        mc_json = json.loads(json.dumps(mc))
        r = monte_carlo.abort_threshold(10.0, mc_json)
        self.assertAlmostEqual(r['abort_dd_pct'], (15.0 + 25.0) / 2)
        self.assertEqual(r['source'], 'average')


if __name__ == '__main__':
    unittest.main()
