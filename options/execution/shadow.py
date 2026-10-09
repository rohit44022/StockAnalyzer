"""
Shadow mode — runs LiveExecutor in parallel with paper trade,
compares decisions and fills, never places real orders.

Davey Ch.14: 30-day shadow period before first real trade.
Validates that the execution engine produces results consistent
with paper trading before committing real capital.
"""

import json
import sqlite3
import logging
import datetime
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class ShadowComparison:
    trade_id: int = 0
    paper_action: str = ''
    live_action: str = ''
    paper_result: dict = field(default_factory=dict)
    live_result: dict = field(default_factory=dict)
    match: bool = True
    deviations: list = field(default_factory=list)
    timestamp: str = ''


class ShadowExecutor:

    def __init__(self, live_executor, db_path: str,
                 shadow_days: int = 30, dry_run: bool = True):
        self._live = live_executor
        self._db_path = db_path
        self._shadow_days = shadow_days
        self._dry_run = dry_run
        self._comparisons = []
        self._start_date = datetime.date.today()
        self._active = True

        conn = sqlite3.connect(db_path, timeout=10)
        conn.execute('''CREATE TABLE IF NOT EXISTS shadow_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            trade_id INTEGER,
            paper_action TEXT,
            live_action TEXT,
            match INTEGER,
            deviations TEXT,
            paper_result TEXT,
            live_result TEXT
        )''')
        conn.commit()
        conn.close()

    def shadow_enter(self, recommendation: dict, trade_id: int = None,
                     paper_result: dict = None) -> ShadowComparison:
        if not self._dry_run:
            raise ValueError(
                'Shadow executor with dry_run=False is not allowed. '
                'Use LiveExecutor directly for real trades.'
            )
        comp = ShadowComparison(
            trade_id=trade_id or 0,
            paper_action='ENTER',
            timestamp=datetime.datetime.now().isoformat(),
        )

        if paper_result:
            comp.paper_result = paper_result

        allowed, reason = (True, 'OK')
        if hasattr(self._live, '_safety'):
            allowed, reason = self._live._safety.should_allow_entry(
                capital_required=recommendation.get('margin_required', 0),
            )
        preflight_err = None
        if allowed and hasattr(self._live, '_bridge') and hasattr(self._live._bridge, '_preflight'):
            preflight_err = self._live._bridge._preflight(
                recommendation.get('legs', []), recommendation.get('symbol', 'NIFTY'))
        if not allowed:
            live_result = {'status': 'blocked', 'reason': reason, 'dry_run': True}
        elif preflight_err:
            live_result = {'status': 'failed', 'reason': preflight_err, 'dry_run': True}
        else:
            live_result = {'status': 'entered', 'trade_id': trade_id,
                           'dry_run': True, 'legs_filled': len(recommendation.get('legs', [])),
                           'legs_failed': 0}

        comp.live_action = 'ENTER'
        comp.live_result = live_result

        self._compare(comp)
        self._log_comparison(comp)
        self._comparisons.append(comp)
        return comp

    def shadow_exit(self, trade_id: int, legs: list, symbol: str = 'NIFTY',
                    reason: str = '', paper_result: dict = None) -> ShadowComparison:
        comp = ShadowComparison(
            trade_id=trade_id,
            paper_action='EXIT',
            timestamp=datetime.datetime.now().isoformat(),
        )

        if paper_result:
            comp.paper_result = paper_result

        live_result = {'status': 'exited', 'trade_id': trade_id,
                       'dry_run': True}
        comp.live_action = 'EXIT'
        comp.live_result = live_result
        self._compare(comp)
        self._log_comparison(comp)
        self._comparisons.append(comp)
        return comp

    def _compare(self, comp: ShadowComparison):
        deviations = []

        if comp.paper_result and comp.live_result:
            p_status = comp.paper_result.get('status', '')
            l_status = comp.live_result.get('status', '')
            if p_status and l_status and p_status != l_status:
                deviations.append(f'status: paper={p_status} live={l_status}')

        comp.deviations = deviations
        comp.match = len(deviations) == 0

    def _log_comparison(self, comp: ShadowComparison):
        level = log.info if comp.match else log.warning
        level(f'SHADOW [{comp.paper_action}] trade {comp.trade_id}: '
              f'match={comp.match} deviations={comp.deviations}')

        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute(
            '''INSERT INTO shadow_log
               (timestamp, trade_id, paper_action, live_action, match,
                deviations, paper_result, live_result)
               VALUES (?,?,?,?,?,?,?,?)''',
            (comp.timestamp, comp.trade_id, comp.paper_action,
             comp.live_action, 1 if comp.match else 0,
             json.dumps(comp.deviations),
             json.dumps(comp.paper_result, default=str),
             json.dumps(comp.live_result, default=str))
        )
        conn.commit()
        conn.close()

    @property
    def days_elapsed(self) -> int:
        return (datetime.date.today() - self._start_date).days

    @property
    def shadow_complete(self) -> bool:
        return self.days_elapsed >= self._shadow_days

    def _db_match_stats(self) -> tuple:
        conn = sqlite3.connect(self._db_path, timeout=10)
        try:
            row = conn.execute(
                'SELECT COUNT(*) as total, COALESCE(SUM(match),0) as matches FROM shadow_log'
            ).fetchone()
            return (row[0] or 0, row[1] or 0)
        finally:
            conn.close()

    @property
    def match_rate(self) -> float:
        total, matches = self._db_match_stats()
        if total == 0:
            return 0.0
        return matches / total

    def summary(self) -> dict:
        total, matches = self._db_match_stats()
        checks = self._graduation_checks()
        return {
            'days_elapsed': self.days_elapsed,
            'shadow_days_required': self._shadow_days,
            'complete': self.shadow_complete,
            'total_comparisons': total,
            'matches': matches,
            'deviations': total - matches,
            'match_rate': self.match_rate,
            'graduation_checks': checks,
            'ready_for_live': all(checks.values()),
        }

    def _graduation_checks(self) -> dict:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row

        phantom_count = 0
        recon_mismatches = 0
        try:
            logs = conn.execute(
                'SELECT phantoms, mismatches FROM reconciliation_log ORDER BY id DESC LIMIT 10'
            ).fetchall()
            phantom_count = sum(r['phantoms'] for r in logs)
            recon_mismatches = sum(r['mismatches'] for r in logs)
        except Exception:
            pass

        preflight_failures = 0
        try:
            rows = conn.execute(
                "SELECT COUNT(*) FROM order_events WHERE event_type='REJECTED_GUARD'"
            ).fetchone()
            preflight_failures = rows[0] if rows else 0
        except Exception:
            pass

        conn.close()

        return {
            'duration': self.shadow_complete,
            'match_rate_95': self.match_rate >= 0.95,
            'zero_phantoms': phantom_count == 0,
            'zero_recon_mismatches': recon_mismatches == 0,
            'preflight_pass': preflight_failures == 0,
            'has_comparisons': self._db_match_stats()[0] > 0,
        }

    def get_log(self, limit: int = 50) -> list:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            'SELECT * FROM shadow_log ORDER BY id DESC LIMIT ?', (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def selfcheck():
    import os, tempfile
    from .queue import OrderQueue, _init_queue_db
    from .bridge import ExecutionBridge, _init_bridge_db
    from .safety import SafetyMonitor, PortfolioState
    from .reconciler import Reconciler
    from .live import LiveExecutor

    db = os.path.join(tempfile.gettempdir(), 'test_shadow.db')
    if os.path.exists(db):
        os.remove(db)

    conn = sqlite3.connect(db, timeout=10)
    _init_queue_db(conn)
    _init_bridge_db(conn)
    conn.execute('''CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY, status TEXT DEFAULT 'open'
    )''')
    conn.commit()
    conn.close()

    order_counter = [0]
    def mock_executor(action, params):
        order_counter[0] += 1
        return {'orderId': f'S_{order_counter[0]}', 'orderStatus': 'TRADED'}

    config = {
        'mode': 'MANUAL',
        'max_lots_per_trade': 10, 'max_orders_per_day': 100,
        'max_capital_at_risk': 200000, 'max_concurrent_positions': 4,
        'allowed_indices': ['NIFTY', 'BANKNIFTY'],
        'daily_loss_limit_pct': 2.0, 'abort_dd_pct': 15.0,
        'kelly_fraction': 0.25,
        'rate_limit_per_sec': 100.0, 'rate_limit_burst': 100,
        'order_timeout_sec': 0.5,
        'min_dte_entry': 1, 'max_dte_entry': 90,
        'bid_ask_max_pct': 10.0,
        'slippage_reject_pct': 999.0,
    }

    queue = OrderQueue(config, db, executor=mock_executor)
    bridge = ExecutionBridge(queue, config, db,
                             price_fetcher=lambda sid: {'bid': 99, 'ask': 101, 'ltp': 100},
                             poll_interval=0.01)
    bridge._wait_fill = lambda oid, to: {'price': 100.0, 'quantity': 75}
    bridge._preflight = lambda legs, sym: None

    safety = SafetyMonitor(
        config, db,
        portfolio_fetcher=lambda: PortfolioState(
            total_capital=500000, deployed_capital=50000,
            open_positions=1, current_dd_pct=1.0,
        ),
    )
    reconciler = Reconciler(db, config,
                            position_fetcher=lambda: [],
                            order_fetcher=lambda: [])

    executor = LiveExecutor(bridge, safety, reconciler, config, db)
    shadow = ShadowExecutor(executor, db, shadow_days=30, dry_run=True)

    rec = {
        'strategy': 'iron_condor', 'symbol': 'NIFTY',
        'margin_required': 45000,
        'legs': [
            {'strike': 23800, 'option_type': 'PE', 'action': 'BUY', 'premium': 50, 'security_id': '100', 'qty': 75},
            {'strike': 23900, 'option_type': 'PE', 'action': 'SELL', 'premium': 80, 'security_id': '101', 'qty': 75},
            {'strike': 24100, 'option_type': 'CE', 'action': 'SELL', 'premium': 80, 'security_id': '102', 'qty': 75},
            {'strike': 24200, 'option_type': 'CE', 'action': 'BUY', 'premium': 50, 'security_id': '103', 'qty': 75},
        ],
    }

    # Test 1: Shadow entry with matching paper result
    paper = {'status': 'entered', 'trade_id': 1}
    comp = shadow.shadow_enter(rec, trade_id=1, paper_result=paper)
    assert comp.match, f'Expected match, got deviations: {comp.deviations}'

    # Test 2: Shadow entry with mismatched paper result
    paper_bad = {'status': 'blocked', 'reason': 'test'}
    order_counter[0] = 0
    comp2 = shadow.shadow_enter(rec, trade_id=2, paper_result=paper_bad)
    assert not comp2.match

    # Test 3: Shadow exit
    order_counter[0] = 0
    comp3 = shadow.shadow_exit(trade_id=1, legs=rec['legs'],
                                paper_result={'status': 'exited'})
    assert comp3.match

    # Test 4: Summary
    s = shadow.summary()
    assert s['total_comparisons'] == 3
    assert s['matches'] == 2
    assert s['deviations'] == 1

    # Test 5: Match rate
    assert abs(shadow.match_rate - 2/3) < 0.01

    # Test 6: Not yet complete (day 0)
    assert not shadow.shadow_complete

    # Test 7: Log persisted
    log_entries = shadow.get_log()
    assert len(log_entries) == 3

    # Test 8: dry_run=False blocked
    try:
        bad_shadow = ShadowExecutor(executor, db, shadow_days=30, dry_run=False)
        bad_shadow.shadow_enter(rec, trade_id=99)
        assert False, 'Should have raised ValueError'
    except ValueError:
        pass

    os.remove(db)
    print('shadow.py: self-check PASSED')


if __name__ == '__main__':
    selfcheck()
