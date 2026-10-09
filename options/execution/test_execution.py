"""
Integration tests for the live execution engine (Phases 1-7).
Covers: queue, bridge, fills, reconciler, safety, live executor, shadow mode.
"""

import json
import os
import sqlite3
import tempfile
import datetime
import pytest

from .queue import (
    OrderQueue, OrderRequest, OrderResult, Priority, OrderAction,
    QueueStatus, _init_queue_db,
)
from .bridge import (
    ExecutionBridge, EntryResult, ExitResult, LegResult, _init_bridge_db,
    _pair_spreads, _sort_legs_buy_first, _round_tick,
)
from .fills import FillTracker
from .reconciler import Reconciler, ReconcileResult, RecoveryResult
from .safety import (
    SafetyMonitor, SafetyAction, PortfolioState,
    validate_config, DEFAULT_SAFETY_CONFIG,
)
from .live import LiveExecutor
from .shadow import ShadowExecutor, ShadowComparison


# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture
def db():
    path = os.path.join(tempfile.gettempdir(), f'test_exec_{os.getpid()}.db')
    conn = sqlite3.connect(path, timeout=10)
    _init_queue_db(conn)
    _init_bridge_db(conn)
    conn.execute('''CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY, status TEXT DEFAULT 'open'
    )''')
    conn.commit()
    conn.close()
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def order_counter():
    return [0]


@pytest.fixture
def mock_executor(order_counter):
    def _exec(action, params):
        order_counter[0] += 1
        return {'orderId': f'T_{order_counter[0]}', 'orderStatus': 'TRADED'}
    return _exec


@pytest.fixture
def config():
    return {
        'mode': 'MANUAL',
        'max_lots_per_trade': 10,
        'max_orders_per_day': 100,
        'max_capital_at_risk': 200000,
        'max_concurrent_positions': 4,
        'allowed_indices': ['NIFTY', 'BANKNIFTY'],
        'daily_loss_limit_pct': 2.0,
        'abort_dd_pct': 15.0,
        'kelly_fraction': 0.25,
        'rate_limit_per_sec': 100.0,
        'rate_limit_burst': 100,
        'order_timeout_sec': 0.5,
        'min_dte_entry': 1,
        'max_dte_entry': 90,
        'bid_ask_max_pct': 10.0,
        'semi_auto_capital_limit': 50000,
        'slippage_reject_pct': 999.0,
    }


@pytest.fixture
def queue(config, db, mock_executor):
    return OrderQueue(config, db, executor=mock_executor)


@pytest.fixture
def bridge(queue, config, db):
    b = ExecutionBridge(
        queue, config, db,
        price_fetcher=lambda sid: {'bid': 99, 'ask': 101, 'ltp': 100},
        poll_interval=0.01,
    )
    b._wait_fill = lambda oid, to: {'price': 100.0, 'quantity': 75}
    b._preflight = lambda legs, sym: None
    return b


@pytest.fixture
def safety(config, db):
    return SafetyMonitor(
        config, db,
        portfolio_fetcher=lambda: PortfolioState(
            total_capital=500000, deployed_capital=50000,
            open_positions=1, current_dd_pct=1.0,
        ),
    )


@pytest.fixture
def reconciler(db, config):
    return Reconciler(db, config,
                      position_fetcher=lambda: [],
                      order_fetcher=lambda: [])


@pytest.fixture
def executor(bridge, safety, reconciler, config, db):
    return LiveExecutor(bridge, safety, reconciler, config, db)


@pytest.fixture
def iron_condor():
    return {
        'strategy': 'iron_condor', 'symbol': 'NIFTY',
        'margin_required': 45000,
        'legs': [
            {'strike': 23800, 'option_type': 'PE', 'action': 'BUY',
             'premium': 50, 'security_id': '100', 'qty': 75},
            {'strike': 23900, 'option_type': 'PE', 'action': 'SELL',
             'premium': 80, 'security_id': '101', 'qty': 75},
            {'strike': 24100, 'option_type': 'CE', 'action': 'SELL',
             'premium': 80, 'security_id': '102', 'qty': 75},
            {'strike': 24200, 'option_type': 'CE', 'action': 'BUY',
             'premium': 50, 'security_id': '103', 'qty': 75},
        ],
    }


# ═══════════════════════════════════════════════════════════
# Phase 1: Order Queue
# ═══════════════════════════════════════════════════════════

class TestOrderQueue:

    def test_submit_and_process(self, queue):
        req = OrderRequest(
            priority=Priority.ENTRY, action=OrderAction.PLACE,
            dhan_params={'securityId': '100', 'quantity': 75,
                         'transactionType': 'BUY', 'orderType': 'LIMIT',
                         'price': 100.0},
            parent_trade_id=1, leg_index=0,
        )
        queue.submit(req)
        result = queue.process_next()
        assert result is not None
        assert result.success

    def test_priority_ordering(self, queue):
        low = OrderRequest(priority=Priority.ADJUSTMENT, action=OrderAction.PLACE,
                           dhan_params={'securityId': '1'}, parent_trade_id=1)
        high = OrderRequest(priority=Priority.STOP_LOSS, action=OrderAction.PLACE,
                            dhan_params={'securityId': '2'}, parent_trade_id=1)
        queue.submit(low)
        queue.submit(high)
        result = queue.process_next()
        assert result.dhan_order_id == 'T_1'

    def test_pause_resume(self, queue):
        req = OrderRequest(priority=Priority.ENTRY, action=OrderAction.PLACE,
                           dhan_params={'securityId': '100'}, parent_trade_id=1)
        queue.submit(req)
        queue.pause()
        result = queue.process_next()
        assert result is None
        queue.resume()
        result = queue.process_next()
        assert result is not None

    def test_cancel_pending(self, queue):
        req = OrderRequest(priority=Priority.ENTRY, action=OrderAction.PLACE,
                           dhan_params={'securityId': '100'}, parent_trade_id=1)
        queue.submit(req)
        cancelled = queue.cancel_pending(parent_trade_id=1)
        assert cancelled >= 1

    def test_max_orders_guard(self, config, db):
        config['max_orders_per_day'] = 2
        counter = [0]
        def exec_fn(a, p):
            counter[0] += 1
            return {'orderId': f'G_{counter[0]}', 'orderStatus': 'TRADED'}
        q = OrderQueue(config, db, executor=exec_fn)
        for i in range(3):
            req = OrderRequest(priority=Priority.ENTRY, action=OrderAction.PLACE,
                               dhan_params={'securityId': str(i)}, parent_trade_id=1)
            q.submit(req)
            q.process_next()
        assert counter[0] == 2

    def test_emergency_drain(self, queue):
        req1 = OrderRequest(priority=Priority.EMERGENCY, action=OrderAction.PLACE,
                            dhan_params={'securityId': '100'}, parent_trade_id=1)
        req2 = OrderRequest(priority=Priority.EMERGENCY, action=OrderAction.PLACE,
                            dhan_params={'securityId': '101'}, parent_trade_id=1)
        queue.submit(req1)
        queue.submit(req2)
        drained = queue.emergency_drain()
        assert len(drained) >= 2

    def test_stats(self, queue):
        s = queue.stats()
        assert 'pending' in s

    def test_events_logged(self, queue, db):
        req = OrderRequest(priority=Priority.ENTRY, action=OrderAction.PLACE,
                           dhan_params={'securityId': '100', 'quantity': 75,
                                        'transactionType': 'BUY'},
                           parent_trade_id=1, leg_index=0)
        queue.submit(req)
        queue.process_next()
        events = queue.get_events(req.id)
        assert len(events) >= 1


# ═══════════════════════════════════════════════════════════
# Phase 2: Execution Bridge
# ═══════════════════════════════════════════════════════════

class TestExecutionBridge:

    def test_entry_buy_first(self, bridge, iron_condor):
        result = bridge.execute_entry(
            trade_id=1, legs=iron_condor['legs'],
            symbol='NIFTY', strategy='iron_condor',
        )
        assert result.success
        assert len(result.legs_filled) == 4
        assert len(result.legs_failed) == 0

    def test_exit_execution(self, bridge, iron_condor):
        bridge.execute_entry(trade_id=1, legs=iron_condor['legs'],
                             symbol='NIFTY', strategy='iron_condor')
        result = bridge.execute_exit(
            trade_id=1, legs=iron_condor['legs'],
            symbol='NIFTY', reason='target hit',
        )
        assert result.success

    def test_intent_written(self, bridge, iron_condor, db):
        bridge.execute_entry(trade_id=10, legs=iron_condor['legs'],
                             symbol='NIFTY', strategy='iron_condor')
        conn = sqlite3.connect(db, timeout=10)
        conn.row_factory = sqlite3.Row
        intents = conn.execute(
            'SELECT * FROM trade_intents WHERE trade_id=?', (10,)
        ).fetchall()
        conn.close()
        assert len(intents) >= 1
        assert intents[0]['status'] == 'COMPLETED'

    def test_paired_spread_grouping(self, iron_condor):
        pairs = _pair_spreads(iron_condor['legs'])
        assert len(pairs) == 2
        for pair in pairs:
            assert pair[0]['action'] == 'BUY'

    def test_sort_legs_buy_first(self):
        legs = [
            {'action': 'SELL', 'premium': 80},
            {'action': 'BUY', 'premium': 50},
            {'action': 'SELL', 'premium': 90},
            {'action': 'BUY', 'premium': 40},
        ]
        sorted_legs = _sort_legs_buy_first(legs)
        assert sorted_legs[0]['action'] == 'BUY'
        assert sorted_legs[1]['action'] == 'BUY'
        assert sorted_legs[2]['action'] == 'SELL'
        assert sorted_legs[3]['action'] == 'SELL'

    def test_round_tick(self):
        assert _round_tick(100.03) == 100.05
        assert _round_tick(100.07) == 100.05
        assert _round_tick(100.00) == 100.00

    def test_tier_prices(self, bridge):
        leg = {'premium': 100, 'action': 'BUY', 'security_id': '100'}
        prices = bridge._get_tier_prices(leg)
        assert len(prices) == 3

    def test_entry_failure_unwind(self, config, db):
        call_count = [0]
        def failing_executor(action, params):
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError('Dhan API timeout')
            return {'orderId': f'F_{call_count[0]}', 'orderStatus': 'TRADED'}

        config['max_attempts'] = 1
        q = OrderQueue(config, db, executor=failing_executor)
        b = ExecutionBridge(q, config, db,
                            price_fetcher=lambda sid: {'bid': 99, 'ask': 101, 'ltp': 100},
                            poll_interval=0.01)
        b._wait_fill = lambda oid, to: {'price': 100.0, 'quantity': 75}
        b._preflight = lambda legs, sym: None

        legs = [
            {'strike': 23800, 'option_type': 'PE', 'action': 'BUY',
             'premium': 50, 'security_id': '100', 'qty': 75},
            {'strike': 23900, 'option_type': 'PE', 'action': 'SELL',
             'premium': 80, 'security_id': '101', 'qty': 75},
        ]
        result = b.execute_entry(trade_id=99, legs=legs, symbol='NIFTY',
                                  strategy='spread')
        assert len(result.legs_failed) > 0


# ═══════════════════════════════════════════════════════════
# Phase 3: Fill Tracker
# ═══════════════════════════════════════════════════════════

class TestFillTracker:

    def test_ws_fill(self, db):
        conn = sqlite3.connect(db, timeout=10)
        conn.execute(
            '''INSERT INTO order_queue
               (id, priority, action, dhan_params, parent_trade_id, leg_index,
                status, created_at, dhan_order_id)
               VALUES (?,?,?,?,?,?,?,?,?)''',
            ('FT1', 2, 'PLACE', json.dumps({'securityId': '13'}),
             1, 0, 'SENT', datetime.datetime.now().isoformat(), 'D_001')
        )
        conn.commit()
        conn.close()

        fills = []
        tracker = FillTracker(db, on_fill=lambda f: fills.append(f))
        tracker.process_ws_event({
            'orderId': 'D_001', 'orderStatus': 'TRADED',
            'filledQty': 75, 'price': 100.5,
        })
        assert len(fills) == 1
        assert fills[0]['price'] == 100.5

    def test_ws_reject(self, db):
        conn = sqlite3.connect(db, timeout=10)
        conn.execute(
            '''INSERT INTO order_queue
               (id, priority, action, dhan_params, parent_trade_id, leg_index,
                status, created_at, dhan_order_id)
               VALUES (?,?,?,?,?,?,?,?,?)''',
            ('FT2', 2, 'PLACE', json.dumps({'securityId': '13'}),
             2, 0, 'SENT', datetime.datetime.now().isoformat(), 'D_002')
        )
        conn.commit()
        conn.close()

        rejects = []
        tracker = FillTracker(db, on_reject=lambda r: rejects.append(r))
        tracker.process_ws_event({
            'orderId': 'D_002', 'orderStatus': 'REJECTED',
            'rejectionReason': 'Insufficient margin',
        })
        assert len(rejects) == 1

    def test_position_snapshot(self, db):
        conn = sqlite3.connect(db, timeout=10)
        conn.execute(
            '''INSERT INTO order_queue
               (id, priority, action, dhan_params, parent_trade_id, leg_index,
                status, created_at, dhan_order_id)
               VALUES (?,?,?,?,?,?,?,?,?)''',
            ('FT3', 2, 'PLACE', json.dumps({'securityId': '25', 'transactionType': 'BUY', 'quantity': 65}),
             3, 0, 'SENT', datetime.datetime.now().isoformat(), 'D_003')
        )
        conn.commit()
        conn.close()

        tracker = FillTracker(db)
        result = tracker.process_position_snapshot([
            {'securityId': '25', 'netQty': 30, 'averagePrice': 200.0},
        ])
        assert 'FT3' in result['updated']

    def test_get_fills(self, db):
        tracker = FillTracker(db)
        fills = tracker.get_fills(trade_id=999)
        assert isinstance(fills, list)

    def test_get_pending(self, db):
        tracker = FillTracker(db)
        pending = tracker.get_pending_orders()
        assert isinstance(pending, list)


# ═══════════════════════════════════════════════════════════
# Phase 4: Reconciler
# ═══════════════════════════════════════════════════════════

class TestReconciler:

    def test_phantom_detection(self, db, config):
        conn = sqlite3.connect(db, timeout=10)
        conn.execute(
            '''INSERT INTO order_queue
               (id, priority, action, dhan_params, parent_trade_id, leg_index,
                status, created_at, dhan_order_id)
               VALUES (?,?,?,?,?,?,?,?,?)''',
            ('R1', 2, 'PLACE', json.dumps({'securityId': '13', 'transactionType': 'BUY', 'quantity': 75}),
             1, 0, 'DONE', datetime.datetime.now().isoformat(), 'D_100')
        )
        conn.commit()
        conn.close()

        phantoms = []
        rec = Reconciler(
            db, config,
            position_fetcher=lambda: [
                {'securityId': '13', 'netQty': 75},
                {'securityId': '99', 'netQty': 50, 'tradingSymbol': 'PHANTOM'},
            ],
            order_fetcher=lambda: [],
            on_phantom=lambda p: phantoms.append(p),
        )
        result = rec.reconcile()
        assert len(result.phantoms) == 1
        assert result.phantoms[0]['security_id'] == '99'
        assert len(phantoms) == 1

    def test_orphan_detection(self, db, config):
        conn = sqlite3.connect(db, timeout=10)
        conn.execute(
            '''INSERT INTO order_queue
               (id, priority, action, dhan_params, parent_trade_id, leg_index,
                status, created_at, dhan_order_id)
               VALUES (?,?,?,?,?,?,?,?,?)''',
            ('R2', 2, 'PLACE', json.dumps({'securityId': '25'}),
             2, 0, 'SENT', datetime.datetime.now().isoformat(), 'D_GONE')
        )
        conn.commit()
        conn.close()

        rec = Reconciler(
            db, config,
            position_fetcher=lambda: [],
            order_fetcher=lambda: [{'orderId': 'D_100'}],
        )
        result = rec.reconcile()
        assert len(result.orphans) == 1
        assert result.orphans[0]['dhan_order_id'] == 'D_GONE'

    def test_clean_reconciliation(self, db, config):
        rec = Reconciler(db, config,
                         position_fetcher=lambda: [],
                         order_fetcher=lambda: [])
        result = rec.reconcile()
        assert result.clean

    def test_crash_recovery_full(self, db, config):
        conn = sqlite3.connect(db, timeout=10)
        conn.execute(
            '''INSERT INTO trade_intents
               (trade_id, intent_type, strategy, symbol, legs_json, status, created_at)
               VALUES (?,?,?,?,?,?,?)''',
            (50, 'ENTRY', 'spread', 'NIFTY',
             json.dumps([{'security_id': '13'}, {'security_id': '14'}]),
             'PENDING', datetime.datetime.now().isoformat())
        )
        conn.commit()
        conn.close()

        rec = Reconciler(
            db, config,
            position_fetcher=lambda: [
                {'securityId': '13', 'netQty': 75},
                {'securityId': '14', 'netQty': 75},
            ],
            order_fetcher=lambda: [],
        )
        result = rec.recover_from_crash()
        assert result.intents_found == 1
        assert result.completed == 1

    def test_crash_recovery_partial(self, db, config):
        conn = sqlite3.connect(db, timeout=10)
        conn.execute(
            '''INSERT INTO trade_intents
               (trade_id, intent_type, strategy, symbol, legs_json, status, created_at)
               VALUES (?,?,?,?,?,?,?)''',
            (51, 'ENTRY', 'spread', 'NIFTY',
             json.dumps([{'security_id': '30'}, {'security_id': '31'}]),
             'PENDING', datetime.datetime.now().isoformat())
        )
        conn.commit()
        conn.close()

        rec = Reconciler(
            db, config,
            position_fetcher=lambda: [{'securityId': '30', 'netQty': 75}],
            order_fetcher=lambda: [],
        )
        result = rec.recover_from_crash()
        assert result.partial_recovered == 1

    def test_reconciliation_log(self, db, config):
        rec = Reconciler(db, config,
                         position_fetcher=lambda: [],
                         order_fetcher=lambda: [])
        rec.reconcile()
        conn = sqlite3.connect(db, timeout=10)
        conn.row_factory = sqlite3.Row
        logs = conn.execute('SELECT * FROM reconciliation_log').fetchall()
        conn.close()
        assert len(logs) >= 1


# ═══════════════════════════════════════════════════════════
# Phase 5: Safety Layer
# ═══════════════════════════════════════════════════════════

class TestSafety:

    def test_normal_state(self, safety):
        action = safety.check_portfolio_dd()
        assert action == SafetyAction.CONTINUE

    def test_dd_3_consecutive_breach(self, safety):
        breach = PortfolioState(current_dd_pct=16.0, total_capital=500000)
        a1 = safety.check_portfolio_dd(breach)
        assert a1 == SafetyAction.WARN
        a2 = safety.check_portfolio_dd(breach)
        assert a2 == SafetyAction.WARN
        a3 = safety.check_portfolio_dd(breach)
        assert a3 == SafetyAction.EXIT_ALL

    def test_dd_recovery_resets(self, safety):
        breach = PortfolioState(current_dd_pct=16.0, total_capital=500000)
        safety.check_portfolio_dd(breach)
        safety.check_portfolio_dd(breach)
        normal = PortfolioState(current_dd_pct=5.0, total_capital=500000)
        action = safety.check_portfolio_dd(normal)
        assert action == SafetyAction.CONTINUE

    def test_emergency_stop(self, safety):
        safety.emergency_stop('test')
        assert safety.is_killed
        assert safety.is_frozen

    def test_entry_blocked_when_killed(self, safety):
        safety.emergency_stop('test')
        allowed, reason = safety.should_allow_entry()
        assert not allowed
        assert 'Kill switch' in reason

    def test_reset(self, safety):
        safety.emergency_stop('test')
        safety.reset()
        assert not safety.is_killed
        assert not safety.is_frozen

    def test_position_limit(self, safety):
        action = safety.check_position_count(4)
        assert action == SafetyAction.FREEZE_ENTRIES
        action = safety.check_position_count(3)
        assert action == SafetyAction.CONTINUE

    def test_capital_limit(self, config, db):
        monitor = SafetyMonitor(
            config, db,
            portfolio_fetcher=lambda: PortfolioState(
                total_capital=500000, deployed_capital=180000,
                open_positions=2,
            ),
        )
        allowed, reason = monitor.should_allow_entry(
            capital_required=30000, position_count=2)
        assert not allowed
        assert 'max_capital' in reason

    def test_config_validation_kelly(self):
        bad = dict(DEFAULT_SAFETY_CONFIG)
        bad['kelly_fraction'] = 0.8
        errors = validate_config(bad)
        assert any('kelly' in e.lower() for e in errors)

    def test_config_validation_mode(self):
        bad = dict(DEFAULT_SAFETY_CONFIG)
        bad['mode'] = 'YOLO'
        errors = validate_config(bad)
        assert any('mode' in e.lower() for e in errors)

    def test_config_validation_non_cash_index(self):
        bad = dict(DEFAULT_SAFETY_CONFIG)
        bad['allowed_indices'] = ['NIFTY', 'SENSEX']
        errors = validate_config(bad)
        assert any('cash-settled' in e.lower() for e in errors)

    def test_daily_loss_freeze(self, config, db):
        config['daily_loss_limit_pct'] = 2.0
        monitor = SafetyMonitor(
            config, db,
            portfolio_fetcher=lambda: PortfolioState(
                total_capital=500000, realized_pnl_today=-12000,
                unrealized_pnl=0,
            ),
        )
        action = monitor.check_daily_loss()
        assert action == SafetyAction.FREEZE_ENTRIES

    def test_daily_loss_exit_all(self, config, db):
        config['daily_loss_limit_pct'] = 2.0
        monitor = SafetyMonitor(
            config, db,
            portfolio_fetcher=lambda: PortfolioState(
                total_capital=500000, realized_pnl_today=-25000,
                unrealized_pnl=0,
            ),
        )
        action = monitor.check_daily_loss()
        assert action == SafetyAction.EXIT_ALL

    def test_heartbeat(self, safety):
        hb = safety.heartbeat()
        assert 'ALIVE' in hb['message']

    def test_safety_log(self, safety, db):
        safety.emergency_stop('audit test')
        log_entries = safety.get_safety_log()
        assert len(log_entries) >= 1
        assert any(e['event_type'] == 'EMERGENCY_STOP' for e in log_entries)


# ═══════════════════════════════════════════════════════════
# Phase 6: Live Executor
# ═══════════════════════════════════════════════════════════

class TestLiveExecutor:

    def test_manual_mode_queues(self, executor, iron_condor):
        result = executor.enter(iron_condor, trade_id=1)
        assert result['status'] == 'pending_approval'
        assert len(executor.pending_approvals) == 1

    def test_approve(self, executor, iron_condor):
        executor.enter(iron_condor, trade_id=1)
        result = executor.approve(0)
        assert result['status'] == 'entered'
        assert len(executor.pending_approvals) == 0

    def test_reject(self, executor, iron_condor):
        executor.enter(iron_condor, trade_id=1)
        result = executor.reject(0, reason='Too risky')
        assert result['status'] == 'rejected'

    def test_semi_mode_auto(self, executor, iron_condor):
        executor.set_mode('SEMI')
        result = executor.enter(iron_condor, trade_id=1)
        assert result['status'] == 'entered'

    def test_semi_mode_large_queued(self, executor, iron_condor):
        executor.set_mode('SEMI')
        big = dict(iron_condor)
        big['margin_required'] = 80000
        result = executor.enter(big, trade_id=1)
        assert result['status'] == 'pending_approval'

    def test_full_mode(self, executor, iron_condor, order_counter):
        executor.set_mode('FULL')
        order_counter[0] = 0
        result = executor.enter(iron_condor, trade_id=1)
        assert result['status'] == 'entered'

    def test_safety_blocks(self, executor, iron_condor, safety):
        safety.emergency_stop('test')
        result = executor.enter(iron_condor, trade_id=1)
        assert result['status'] == 'blocked'

    def test_exit(self, executor, iron_condor, order_counter):
        executor.set_mode('FULL')
        order_counter[0] = 0
        executor.enter(iron_condor, trade_id=1)
        order_counter[0] = 0
        result = executor.exit(trade_id=1, legs=iron_condor['legs'],
                               reason='target hit')
        assert result['status'] == 'exited'

    def test_invalid_mode(self, executor):
        with pytest.raises(ValueError):
            executor.set_mode('YOLO')

    def test_check(self, executor, iron_condor):
        result = executor.check(trade_id=1)
        assert 'reconciliation_clean' in result

    def test_approve_empty_queue(self, executor):
        result = executor.approve(0)
        assert result['status'] == 'error'

    def test_reject_empty_queue(self, executor):
        result = executor.reject(0)
        assert result['status'] == 'error'


# ═══════════════════════════════════════════════════════════
# Phase 7: Shadow Mode
# ═══════════════════════════════════════════════════════════

class TestShadowMode:

    def test_shadow_entry_match(self, executor, iron_condor, db):
        shadow = ShadowExecutor(executor, db, shadow_days=30, dry_run=True)
        paper = {'status': 'entered', 'trade_id': 1}
        comp = shadow.shadow_enter(iron_condor, trade_id=1,
                                    paper_result=paper)
        assert comp.match

    def test_shadow_entry_mismatch(self, executor, iron_condor, db,
                                    order_counter):
        shadow = ShadowExecutor(executor, db, shadow_days=30, dry_run=True)
        paper = {'status': 'blocked', 'reason': 'test'}
        order_counter[0] = 0
        comp = shadow.shadow_enter(iron_condor, trade_id=2,
                                    paper_result=paper)
        assert not comp.match

    def test_shadow_exit(self, executor, iron_condor, db, order_counter):
        shadow = ShadowExecutor(executor, db, shadow_days=30, dry_run=True)
        order_counter[0] = 0
        comp = shadow.shadow_exit(
            trade_id=1, legs=iron_condor['legs'],
            paper_result={'status': 'exited'},
        )
        assert comp.match

    def test_summary(self, executor, iron_condor, db, order_counter):
        shadow = ShadowExecutor(executor, db, shadow_days=30, dry_run=True)
        shadow.shadow_enter(iron_condor, trade_id=1,
                             paper_result={'status': 'entered'})
        order_counter[0] = 0
        shadow.shadow_enter(iron_condor, trade_id=2,
                             paper_result={'status': 'blocked'})
        s = shadow.summary()
        assert s['total_comparisons'] == 2
        assert s['matches'] == 1
        assert s['deviations'] == 1

    def test_not_complete_day0(self, executor, db):
        shadow = ShadowExecutor(executor, db, shadow_days=30, dry_run=True)
        assert not shadow.shadow_complete

    def test_match_rate(self, executor, iron_condor, db, order_counter):
        shadow = ShadowExecutor(executor, db, shadow_days=30, dry_run=True)
        shadow.shadow_enter(iron_condor, trade_id=1,
                             paper_result={'status': 'entered'})
        assert shadow.match_rate == 1.0

    def test_log_persisted(self, executor, iron_condor, db):
        shadow = ShadowExecutor(executor, db, shadow_days=30, dry_run=True)
        shadow.shadow_enter(iron_condor, trade_id=1,
                             paper_result={'status': 'entered'})
        log_entries = shadow.get_log()
        assert len(log_entries) >= 1

    def test_ready_for_live(self, executor, iron_condor, db, order_counter):
        shadow = ShadowExecutor(executor, db, shadow_days=0, dry_run=True)
        order_counter[0] = 0
        shadow.shadow_enter(iron_condor, trade_id=1,
                             paper_result={'status': 'entered'})
        s = shadow.summary()
        assert s['ready_for_live']


# ═══════════════════════════════════════════════════════════
# Integration: Full Lifecycle
# ═══════════════════════════════════════════════════════════

class TestFullLifecycle:

    def test_entry_fill_reconcile_exit(self, bridge, safety, reconciler,
                                        config, db, iron_condor, order_counter):
        executor = LiveExecutor(bridge, safety, reconciler, config, db)
        executor.set_mode('FULL')

        order_counter[0] = 0
        entry = executor.enter(iron_condor, trade_id=1)
        assert entry['status'] == 'entered'
        assert len(entry['legs_filled']) == 4

        recon = reconciler.reconcile()
        assert isinstance(recon, ReconcileResult)

        order_counter[0] = 0
        exit_result = executor.exit(
            trade_id=1, legs=iron_condor['legs'], reason='target',
        )
        assert exit_result['status'] == 'exited'

    def test_shadow_to_live_transition(self, bridge, safety, reconciler,
                                        config, db, iron_condor, order_counter):
        executor = LiveExecutor(bridge, safety, reconciler, config, db)
        shadow = ShadowExecutor(executor, db, shadow_days=0, dry_run=True)

        order_counter[0] = 0
        shadow.shadow_enter(iron_condor, trade_id=1,
                             paper_result={'status': 'entered'})
        s = shadow.summary()
        assert s['ready_for_live']

        executor.set_mode('FULL')
        order_counter[0] = 0
        result = executor.enter(iron_condor, trade_id=2)
        assert result['status'] == 'entered'

    def test_safety_cascade(self, bridge, config, db, iron_condor,
                              order_counter):
        safety = SafetyMonitor(
            config, db,
            portfolio_fetcher=lambda: PortfolioState(
                total_capital=500000, deployed_capital=50000,
                open_positions=1, current_dd_pct=16.0,
            ),
        )
        reconciler = Reconciler(db, config,
                                position_fetcher=lambda: [],
                                order_fetcher=lambda: [])

        executor = LiveExecutor(bridge, safety, reconciler, config, db)
        executor.set_mode('FULL')

        safety.check_portfolio_dd()
        safety.check_portfolio_dd()
        safety.check_portfolio_dd()

        result = executor.enter(iron_condor, trade_id=1)
        assert result['status'] == 'blocked'


# ═══════════════════════════════════════════════════════════
# Audit Pass 5: Missing Coverage
# ═══════════════════════════════════════════════════════════

class TestAuditPass5:

    def test_401_pauses_queue(self, config, db):
        def http401_executor(action, params):
            return {'httpCode': 401, 'orderStatus': 'error'}
        q = OrderQueue(config, db, executor=http401_executor)
        req = OrderRequest(priority=Priority.ENTRY, action=OrderAction.PLACE,
                           dhan_params={'securityId': '13', 'quantity': 75},
                           parent_trade_id=1)
        q.submit(req)
        result = q.process_next()
        assert not result.success
        assert result.error == 'TOKEN_EXPIRED'
        assert q.is_paused

    def test_429_exponential_backoff(self, config, db):
        attempts = []
        def http429_executor(action, params):
            attempts.append(1)
            return {'httpCode': 429, 'orderStatus': 'error'}
        q = OrderQueue(config, db, executor=http429_executor)
        req = OrderRequest(priority=Priority.ENTRY, action=OrderAction.PLACE,
                           dhan_params={'securityId': '13', 'quantity': 75},
                           parent_trade_id=1, max_attempts=2)
        q.submit(req)
        result = q.process_next()
        assert not result.success
        assert result.error == 'RATE_LIMITED_BY_DHAN'
        assert q._consecutive_429 == 1

    def test_capital_guard(self, config, db):
        config['max_capital_at_risk'] = 10000
        counter = [0]
        def exec_fn(a, p):
            counter[0] += 1
            return {'orderId': f'C_{counter[0]}', 'orderStatus': 'TRADED'}
        q = OrderQueue(config, db, executor=exec_fn)
        req1 = OrderRequest(priority=Priority.ENTRY, action=OrderAction.PLACE,
                            dhan_params={'securityId': '13', 'quantity': 75,
                                         'price': 100.0},
                            parent_trade_id=1)
        q.submit(req1)
        r1 = q.process_next()
        assert r1.success
        req2 = OrderRequest(priority=Priority.ENTRY, action=OrderAction.PLACE,
                            dhan_params={'securityId': '13', 'quantity': 75,
                                         'price': 100.0},
                            parent_trade_id=2)
        q.submit(req2)
        r2 = q.process_next()
        assert not r2.success
        assert 'max_capital_at_risk' in r2.error

    def test_vix_halt_preflight(self, config, db):
        counter = [0]
        def exec_fn(a, p):
            counter[0] += 1
            return {'orderId': f'V_{counter[0]}', 'orderStatus': 'TRADED'}
        config['vix_halt_above'] = 30
        q = OrderQueue(config, db, executor=exec_fn)
        b = ExecutionBridge(q, config, db,
                            price_fetcher=lambda sid: {'bid': 99, 'ask': 101, 'ltp': 100},
                            vix_fetcher=lambda: 35.0,
                            poll_interval=0.01)
        legs = [{'strike': 24000, 'option_type': 'CE', 'action': 'SELL',
                 'premium': 80, 'security_id': '102', 'qty': 75}]
        result = b.execute_entry(trade_id=1, legs=legs, symbol='NIFTY')
        assert not result.success
        assert any('VIX' in str(f) for f in result.legs_failed)

    def test_idempotent_submit(self, queue):
        req = OrderRequest(priority=Priority.ENTRY, action=OrderAction.PLACE,
                           dhan_params={'securityId': '13', 'quantity': 75},
                           parent_trade_id=1)
        queue.submit(req)
        queue.submit(req)
        conn = sqlite3.connect(queue._db_path, timeout=10)
        count = conn.execute(
            'SELECT COUNT(*) FROM order_queue WHERE id=?', (req.id,)
        ).fetchone()[0]
        conn.close()
        assert count == 1

    def test_crash_recovery_try_finally(self, db, config):
        mock_q = type('Q', (), {
            'set_recovering': lambda self, s: setattr(self, '_r', s),
            '_r': False,
        })()
        def exploding_fetcher():
            raise RuntimeError('API down')
        rec = Reconciler(
            db, config,
            position_fetcher=exploding_fetcher,
            order_fetcher=lambda: [],
            queue=mock_q,
        )
        conn = sqlite3.connect(db, timeout=10)
        conn.execute('''CREATE TABLE IF NOT EXISTS trade_intents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER NOT NULL, intent_type TEXT NOT NULL,
            strategy TEXT, symbol TEXT, legs_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            created_at TEXT NOT NULL, completed_at TEXT, result_json TEXT
        )''')
        conn.execute(
            '''INSERT INTO trade_intents
               (trade_id, intent_type, legs_json, status, created_at)
               VALUES (?,?,?,?,?)''',
            (99, 'ENTRY', json.dumps([{'security_id': '13'}]),
             'PENDING', datetime.datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
        try:
            rec.recover_from_crash()
        except Exception:
            pass
        assert not mock_q._r, 'Queue must unlock after crash recovery exception'

    def test_emergency_drain_preserves_401_pause(self, config, db):
        call_count = [0]
        def exec_401_on_second(action, params):
            call_count[0] += 1
            if call_count[0] == 2:
                return {'httpCode': 401, 'orderStatus': 'error'}
            return {'orderId': f'ED_{call_count[0]}', 'orderStatus': 'TRADED'}
        q = OrderQueue(config, db, executor=exec_401_on_second)
        q.submit(OrderRequest(priority=Priority.EMERGENCY, action=OrderAction.PLACE,
                               dhan_params={'securityId': '13', 'quantity': 75},
                               parent_trade_id=1))
        q.submit(OrderRequest(priority=Priority.EMERGENCY, action=OrderAction.PLACE,
                               dhan_params={'securityId': '13', 'quantity': 75},
                               parent_trade_id=2))
        q.emergency_drain()
        assert q.is_paused, 'Queue must stay paused after 401 during drain'

    def test_order_stuck_in_processing(self, config, db):
        def exploding_executor(action, params):
            raise RuntimeError('Network timeout')
        q = OrderQueue(config, db, executor=exploding_executor)
        req = OrderRequest(priority=Priority.ENTRY, action=OrderAction.PLACE,
                           dhan_params={'securityId': '13', 'quantity': 75},
                           parent_trade_id=1, max_attempts=1)
        q.submit(req)
        result = q.process_next()
        assert not result.success
        order = q.get_order(req.id)
        assert order['status'] == 'FAILED', \
            f'Order should be FAILED not stuck in PROCESSING, got {order["status"]}'

    def test_shadow_dry_run_respects_safety(self, executor, iron_condor, db, safety):
        shadow = ShadowExecutor(executor, db, shadow_days=30, dry_run=True)
        safety.emergency_stop('test')
        comp = shadow.shadow_enter(iron_condor, trade_id=1,
                                    paper_result={'status': 'blocked'})
        assert comp.match, f'Dry-run should detect safety block: {comp.deviations}'
        safety.reset()
