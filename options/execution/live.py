"""
Live executor — drop-in replacement for paper trade execution.
Routes trades through the execution bridge with safety checks.

Modes (Davey Ch.14):
  MANUAL  — queue everything for human approval
  SEMI    — auto-enter if risk < auto_limit, else queue
  FULL    — auto-enter within all safety limits
"""

import sqlite3
import logging
import datetime

from .queue import OrderQueue
from .bridge import ExecutionBridge
from .safety import SafetyMonitor, SafetyAction, PortfolioState
from .reconciler import Reconciler

log = logging.getLogger(__name__)


class LiveExecutor:

    def __init__(self, bridge: ExecutionBridge, safety: SafetyMonitor,
                 reconciler: Reconciler, config: dict, db_path: str):
        self._bridge = bridge
        self._safety = safety
        self._reconciler = reconciler
        self._config = config
        self._db_path = db_path
        self._mode = config.get('mode', 'MANUAL')
        self._approval_queue = []

    def enter(self, recommendation: dict, trade_id: int = None) -> dict:
        legs = recommendation.get('legs', [])
        symbol = recommendation.get('symbol', 'NIFTY')
        strategy = recommendation.get('strategy', '')
        capital_required = recommendation.get('margin_required', 0)

        allowed, reason = self._safety.should_allow_entry(
            capital_required=capital_required,
            position_count=self._count_open_positions(),
        )
        if not allowed:
            log.warning(f'Entry blocked by safety: {reason}')
            return {'status': 'blocked', 'reason': reason}

        if self._mode == 'MANUAL':
            entry = {
                'trade_id': trade_id, 'recommendation': recommendation,
                'status': 'pending_approval',
                'queued_at': datetime.datetime.now().isoformat(),
            }
            self._approval_queue.append(entry)
            log.info(f'Entry queued for approval: {strategy} {symbol}')
            return {'status': 'pending_approval', 'queue_position': len(self._approval_queue)}

        if self._mode == 'SEMI':
            auto_limit = self._config.get('semi_auto_capital_limit', 50000)
            if capital_required > auto_limit:
                entry = {
                    'trade_id': trade_id, 'recommendation': recommendation,
                    'status': 'pending_approval',
                    'reason': f'capital {capital_required} > auto_limit {auto_limit}',
                    'queued_at': datetime.datetime.now().isoformat(),
                }
                self._approval_queue.append(entry)
                return {'status': 'pending_approval', 'reason': entry['reason']}

        result = self._bridge.execute_entry(
            trade_id=trade_id or self._next_trade_id(),
            legs=legs, symbol=symbol, strategy=strategy,
        )

        return {
            'status': 'entered' if result.success else 'failed',
            'trade_id': result.trade_id,
            'legs_filled': result.legs_filled,
            'legs_failed': result.legs_failed,
            'execution_time': result.execution_time_sec,
        }

    def approve(self, index: int = 0) -> dict:
        if index >= len(self._approval_queue):
            return {'status': 'error', 'reason': 'No pending entry at that index'}

        entry = self._approval_queue.pop(index)
        rec = entry['recommendation']
        capital_required = rec.get('margin_required', 0)

        allowed, reason = self._safety.should_allow_entry(
            capital_required=capital_required,
            position_count=self._count_open_positions(),
        )
        if not allowed:
            log.warning(f'Approval blocked by safety: {reason}')
            return {'status': 'blocked', 'reason': reason}

        trade_id = entry.get('trade_id') or self._next_trade_id()

        result = self._bridge.execute_entry(
            trade_id=trade_id,
            legs=rec.get('legs', []),
            symbol=rec.get('symbol', 'NIFTY'),
            strategy=rec.get('strategy', ''),
        )
        return {
            'status': 'entered' if result.success else 'failed',
            'trade_id': result.trade_id,
            'legs_filled': result.legs_filled,
            'legs_failed': result.legs_failed,
            'execution_time': result.execution_time_sec,
        }

    def reject(self, index: int = 0, reason: str = '') -> dict:
        if index >= len(self._approval_queue):
            return {'status': 'error', 'reason': 'No pending entry at that index'}
        entry = self._approval_queue.pop(index)
        log.info(f'Entry rejected: {reason}')
        return {'status': 'rejected', 'reason': reason}

    def exit(self, trade_id: int, legs: list, symbol: str = 'NIFTY',
             reason: str = '') -> dict:
        result = self._bridge.execute_exit(
            trade_id=trade_id, legs=legs, symbol=symbol, reason=reason,
        )
        return {
            'status': 'exited' if result.success else 'failed',
            'trade_id': result.trade_id,
            'legs_closed': result.legs_closed,
            'legs_failed': result.legs_failed,
            'execution_time': result.execution_time_sec,
        }

    def check(self, trade_id: int, spot: float = None) -> dict:
        recon = self._reconciler.reconcile()
        return {
            'trade_id': trade_id,
            'reconciliation_clean': recon.clean,
            'phantoms': len(recon.phantoms),
            'orphans': len(recon.orphans),
        }

    @property
    def pending_approvals(self) -> list:
        return list(self._approval_queue)

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str):
        if mode not in ('MANUAL', 'SEMI', 'FULL'):
            raise ValueError(f'Invalid mode: {mode}')
        log.info(f'Executor mode changed: {self._mode} → {mode}')
        self._mode = mode

    def _count_open_positions(self) -> int:
        try:
            conn = sqlite3.connect(self._db_path, timeout=10)
            count = conn.execute(
                "SELECT COUNT(*) FROM trades WHERE status='open'"
            ).fetchone()[0]
            conn.close()
            return count
        except Exception:
            # fail-closed: assume max positions to block new entries
            return self._config.get('max_concurrent_positions', 4)

    def _next_trade_id(self) -> int:
        try:
            conn = sqlite3.connect(self._db_path, timeout=10)
            row = conn.execute('SELECT MAX(id) FROM trades').fetchone()
            conn.close()
            return (row[0] or 0) + 1
        except Exception:
            return 1


def selfcheck():
    import os, tempfile
    from .queue import OrderQueue, _init_queue_db
    from .bridge import ExecutionBridge, _init_bridge_db

    db = os.path.join(tempfile.gettempdir(), 'test_live_executor.db')
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
        return {'orderId': f'M_{order_counter[0]}', 'orderStatus': 'TRADED'}

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
        'semi_auto_capital_limit': 50000,
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

    # Test 1: MANUAL mode → queued
    result = executor.enter(rec, trade_id=1)
    assert result['status'] == 'pending_approval'
    assert len(executor.pending_approvals) == 1

    # Test 2: Approve
    result = executor.approve(0)
    assert result['status'] == 'entered', f"Expected entered, got {result}"
    assert len(executor.pending_approvals) == 0

    # Test 3: SEMI mode — small trade auto-enters
    executor.set_mode('SEMI')
    order_counter[0] = 0
    result = executor.enter(rec, trade_id=2)
    assert result['status'] == 'entered'

    # Test 4: SEMI mode — large trade queued
    big_rec = dict(rec)
    big_rec['margin_required'] = 80000
    result = executor.enter(big_rec, trade_id=3)
    assert result['status'] == 'pending_approval'

    # Test 5: Reject
    result = executor.reject(0, reason='Too risky')
    assert result['status'] == 'rejected'

    # Test 6: FULL mode
    executor.set_mode('FULL')
    order_counter[0] = 0
    result = executor.enter(rec, trade_id=4)
    assert result['status'] == 'entered'

    # Test 7: Safety blocks entry when killed
    safety.emergency_stop('test')
    result = executor.enter(rec, trade_id=5)
    assert result['status'] == 'blocked'
    safety.reset()

    # Test 8: Exit
    order_counter[0] = 0
    result = executor.exit(trade_id=1, legs=rec['legs'], reason='target hit')
    assert result['status'] == 'exited'

    os.remove(db)
    print('live.py: self-check PASSED')


if __name__ == '__main__':
    selfcheck()
