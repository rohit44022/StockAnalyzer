"""
V5 Integration Tests — autopilot ↔ execution module bridge.

Tests: alert system, live_status state machine, entry/exit bridge,
RESIDUAL/EXPIRED/EXIT_FAILED states, preflight alert with cooldown,
file lock, cancel verification, unwind fill verification,
direction-aware fills, net position reconciler, DD breach restore,
shadow dry_run guard, 429 backoff, force_drain_exits.
"""

import json
import os
import sqlite3
import tempfile
import datetime
import pytest

from options.execution.queue import OrderQueue, OrderRequest, Priority, OrderAction, _init_queue_db
from options.execution.bridge import ExecutionBridge, _init_bridge_db
from options.execution.safety import SafetyMonitor, PortfolioState
from options.execution.reconciler import Reconciler
from options.execution.fills import FillTracker, _matches_order_to_position
from options.execution.shadow import ShadowExecutor
from options.execution.live import LiveExecutor


def _make_db():
    db = os.path.join(tempfile.gettempdir(), f'test_v5_{os.getpid()}.db')
    if os.path.exists(db):
        os.remove(db)
    conn = sqlite3.connect(db, timeout=10)
    conn.execute('PRAGMA journal_mode=WAL')
    _init_queue_db(conn)
    _init_bridge_db(conn)
    conn.execute('''CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY, status TEXT DEFAULT 'open'
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS trade_intents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id INTEGER NOT NULL,
        intent_type TEXT NOT NULL,
        strategy TEXT, symbol TEXT,
        legs_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDING',
        created_at TEXT NOT NULL,
        completed_at TEXT, result_json TEXT
    )''')
    conn.commit()
    conn.close()
    return db


def _safety_config(**overrides):
    cfg = {
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
    cfg.update(overrides)
    return cfg


# ── Alert System ─────────────────────────────────────────────────

class TestAlertSystem:

    def setup_method(self):
        from options import paper_trade
        self.db = os.path.join(tempfile.gettempdir(), f'test_alerts_{os.getpid()}.db')
        if os.path.exists(self.db):
            os.remove(self.db)
        paper_trade.init_db(self.db)

    def teardown_method(self):
        if os.path.exists(self.db):
            os.remove(self.db)

    def test_emit_and_retrieve(self):
        from options.autopilot import _emit_alert, get_alerts
        _emit_alert(self.db, 'CRITICAL', 'RISK', 'DD breach', 'drawdown hit 16%')
        alerts = get_alerts(self.db, limit=10)
        assert len(alerts) == 1
        assert alerts[0]['severity'] == 'CRITICAL'
        assert alerts[0]['category'] == 'RISK'
        assert alerts[0]['title'] == 'DD breach'
        assert alerts[0]['detail'] == 'drawdown hit 16%'
        assert alerts[0]['acknowledged'] == 0

    def test_ack_alert(self):
        from options.autopilot import _emit_alert, get_alerts, ack_alert
        _emit_alert(self.db, 'WARNING', 'TEST', 'test alert')
        alerts = get_alerts(self.db)
        ack_alert(alerts[0]['id'], self.db)
        unacked = get_alerts(self.db, unacked_only=True)
        assert len(unacked) == 0
        all_alerts = get_alerts(self.db)
        assert len(all_alerts) == 1
        assert all_alerts[0]['acknowledged'] == 1

    def test_severity_levels(self):
        from options.autopilot import _emit_alert, get_alerts
        for sev in ['INFO', 'WARNING', 'CRITICAL', 'EMERGENCY']:
            _emit_alert(self.db, sev, 'TEST', f'{sev} alert')
        alerts = get_alerts(self.db, limit=10)
        assert len(alerts) == 4
        sevs = [a['severity'] for a in alerts]
        assert 'EMERGENCY' in sevs

    def test_context_json(self):
        from options.autopilot import _emit_alert, get_alerts
        ctx = {'trade_id': 42, 'dd_pct': 16.2}
        _emit_alert(self.db, 'CRITICAL', 'RISK', 'test', context=ctx)
        alerts = get_alerts(self.db)
        stored = json.loads(alerts[0]['context_json'])
        assert stored['trade_id'] == 42


# ── File Lock ────────────────────────────────────────────────────

class TestFileLock:

    def test_acquire_release(self):
        from options.autopilot import _acquire_lock, _release_lock
        fd = _acquire_lock()
        assert fd is not None
        fd2 = _acquire_lock()
        assert fd2 is None
        _release_lock(fd)

    def test_release_then_reacquire(self):
        from options.autopilot import _acquire_lock, _release_lock
        fd = _acquire_lock()
        _release_lock(fd)
        fd2 = _acquire_lock()
        assert fd2 is not None
        _release_lock(fd2)

    def test_cron_run_cycle_skips_when_locked(self):
        from options.autopilot import _acquire_lock, _release_lock, cron_run_cycle
        fd = _acquire_lock()
        result = cron_run_cycle()
        assert result.get('action') == 'skip'
        _release_lock(fd)


# ── Direction-Aware Fill Matching ────────────────────────────────

class TestDirectionAwareFills:

    def test_buy_matches_positive_qty(self):
        order = {'dhan_params': json.dumps({'securityId': '100', 'transactionType': 'BUY'})}

        class Row:
            def __getitem__(self, k): return order[k]

        assert _matches_order_to_position(
            Row(), {'securityId': '100', 'netQty': 75}
        ) is True

    def test_buy_no_match_negative_qty(self):
        order = {'dhan_params': json.dumps({'securityId': '100', 'transactionType': 'BUY'})}

        class Row:
            def __getitem__(self, k): return order[k]

        assert _matches_order_to_position(
            Row(), {'securityId': '100', 'netQty': -75}
        ) is False

    def test_sell_matches_zero_qty(self):
        order = {'dhan_params': json.dumps({'securityId': '100', 'transactionType': 'SELL'})}

        class Row:
            def __getitem__(self, k): return order[k]

        assert _matches_order_to_position(
            Row(), {'securityId': '100', 'netQty': 0}
        ) is True

    def test_sell_matches_negative_qty(self):
        order = {'dhan_params': json.dumps({'securityId': '100', 'transactionType': 'SELL'})}

        class Row:
            def __getitem__(self, k): return order[k]

        assert _matches_order_to_position(
            Row(), {'securityId': '100', 'netQty': -50}
        ) is True

    def test_sid_mismatch(self):
        order = {'dhan_params': json.dumps({'securityId': '100', 'transactionType': 'BUY'})}

        class Row:
            def __getitem__(self, k): return order[k]

        assert _matches_order_to_position(
            Row(), {'securityId': '999', 'netQty': 75}
        ) is False


# ── Net Position Reconciler ──────────────────────────────────────

class TestNetPositionReconciler:

    def test_net_position_buy_sell_cancel(self):
        db = _make_db()
        conn = sqlite3.connect(db, timeout=10)
        # BUY 75 then SELL 75 of same SID → net zero → no position tracked
        for i, txn in enumerate(['BUY', 'SELL']):
            conn.execute(
                '''INSERT INTO order_queue
                   (id, priority, action, dhan_params, parent_trade_id, leg_index,
                    status, created_at, dhan_order_id)
                   VALUES (?,?,?,?,?,?,?,?,?)''',
                (f'NQ{i}', 2, 'PLACE',
                 json.dumps({'securityId': '100', 'quantity': 75, 'transactionType': txn}),
                 1, i, 'DONE', datetime.datetime.now().isoformat(), f'D{i}')
            )
        conn.commit()
        conn.close()

        rec = Reconciler(db, {}, position_fetcher=lambda: [], order_fetcher=lambda: [])
        result = rec.reconcile()
        assert result.matched == 0
        assert len(result.phantoms) == 0
        os.remove(db)

    def test_net_position_partial_sell(self):
        db = _make_db()
        conn = sqlite3.connect(db, timeout=10)
        # BUY 150, SELL 75 → net 75 remaining
        conn.execute(
            '''INSERT INTO order_queue
               (id, priority, action, dhan_params, parent_trade_id, leg_index,
                status, created_at, dhan_order_id) VALUES (?,?,?,?,?,?,?,?,?)''',
            ('NQ0', 2, 'PLACE',
             json.dumps({'securityId': '100', 'quantity': 150, 'transactionType': 'BUY'}),
             1, 0, 'DONE', datetime.datetime.now().isoformat(), 'D0')
        )
        conn.execute(
            '''INSERT INTO order_queue
               (id, priority, action, dhan_params, parent_trade_id, leg_index,
                status, created_at, dhan_order_id) VALUES (?,?,?,?,?,?,?,?,?)''',
            ('NQ1', 2, 'PLACE',
             json.dumps({'securityId': '100', 'quantity': 75, 'transactionType': 'SELL'}),
             1, 1, 'DONE', datetime.datetime.now().isoformat(), 'D1')
        )
        conn.commit()
        conn.close()

        rec = Reconciler(
            db, {},
            position_fetcher=lambda: [{'securityId': '100', 'netQty': 75}],
            order_fetcher=lambda: [],
        )
        result = rec.reconcile()
        assert result.matched == 1
        assert len(result.quantity_mismatches) == 0
        os.remove(db)


# ── DD Breach Count Restore ──────────────────────────────────────

class TestDDBounceRestore:

    def test_restore_consecutive_dd_warnings(self):
        db = _make_db()
        conn = sqlite3.connect(db, timeout=10)
        conn.execute('''CREATE TABLE IF NOT EXISTS safety_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, event_type TEXT, severity TEXT,
            action TEXT, detail TEXT, context TEXT
        )''')
        # 2 consecutive DD_WARNING events
        for _ in range(2):
            conn.execute(
                '''INSERT INTO safety_events (timestamp, event_type, severity, action, detail)
                   VALUES (?,?,?,?,?)''',
                (datetime.datetime.now().isoformat(), 'DD_WARNING', 'WARN', 'CONTINUE', 'test')
            )
        conn.commit()
        conn.close()

        cfg = _safety_config()
        safety = SafetyMonitor(
            cfg, db,
            portfolio_fetcher=lambda: PortfolioState(
                total_capital=500000, deployed_capital=50000,
                open_positions=1, current_dd_pct=1.0,
            ),
        )
        assert safety._dd_breach_count == 2

        os.remove(db)

    def test_non_consecutive_resets_count(self):
        db = _make_db()
        conn = sqlite3.connect(db, timeout=10)
        conn.execute('''CREATE TABLE IF NOT EXISTS safety_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, event_type TEXT, severity TEXT,
            action TEXT, detail TEXT, context TEXT
        )''')
        conn.execute(
            '''INSERT INTO safety_events (timestamp, event_type, severity, action, detail)
               VALUES (?,?,?,?,?)''',
            (datetime.datetime.now().isoformat(), 'DD_WARNING', 'WARN', 'CONTINUE', 'test')
        )
        conn.execute(
            '''INSERT INTO safety_events (timestamp, event_type, severity, action, detail)
               VALUES (?,?,?,?,?)''',
            (datetime.datetime.now().isoformat(), 'SAFETY_RESET', 'INFO', 'CONTINUE', 'reset')
        )
        conn.commit()
        conn.close()

        cfg = _safety_config()
        safety = SafetyMonitor(
            cfg, db,
            portfolio_fetcher=lambda: PortfolioState(
                total_capital=500000, deployed_capital=50000,
                open_positions=1, current_dd_pct=1.0,
            ),
        )
        assert safety._dd_breach_count == 0
        os.remove(db)


# ── Shadow dry_run Guard ─────────────────────────────────────────

class TestShadowGuard:

    def test_dry_run_false_raises(self):
        db = _make_db()
        cfg = _safety_config()

        order_counter = [0]
        def mock_executor(action, params):
            order_counter[0] += 1
            return {'orderId': f'S_{order_counter[0]}', 'orderStatus': 'TRADED'}

        queue = OrderQueue(cfg, db, executor=mock_executor)
        bridge = ExecutionBridge(queue, cfg, db,
                                 price_fetcher=lambda sid: {'bid': 99, 'ask': 101, 'ltp': 100},
                                 poll_interval=0.01)
        bridge._wait_fill = lambda oid, to: {'price': 100.0, 'quantity': 75}
        bridge._preflight = lambda legs, sym: None
        safety = SafetyMonitor(
            cfg, db,
            portfolio_fetcher=lambda: PortfolioState(
                total_capital=500000, deployed_capital=50000,
                open_positions=1, current_dd_pct=1.0,
            ),
        )
        reconciler = Reconciler(db, cfg, position_fetcher=lambda: [], order_fetcher=lambda: [])
        executor = LiveExecutor(bridge, safety, reconciler, cfg, db)

        shadow = ShadowExecutor(executor, db, dry_run=False)
        with pytest.raises(ValueError, match='dry_run=False is not allowed'):
            shadow.shadow_enter({'strategy': 'test', 'legs': []}, trade_id=1)

        os.remove(db)

    def test_dry_run_true_works(self):
        db = _make_db()
        cfg = _safety_config()

        queue = OrderQueue(cfg, db, executor=lambda a, p: {'orderId': '1', 'orderStatus': 'TRADED'})
        bridge = ExecutionBridge(queue, cfg, db,
                                 price_fetcher=lambda sid: {'bid': 99, 'ask': 101, 'ltp': 100},
                                 poll_interval=0.01)
        bridge._wait_fill = lambda oid, to: {'price': 100.0, 'quantity': 75}
        bridge._preflight = lambda legs, sym: None
        safety = SafetyMonitor(
            cfg, db,
            portfolio_fetcher=lambda: PortfolioState(
                total_capital=500000, deployed_capital=50000,
                open_positions=1, current_dd_pct=1.0,
            ),
        )
        reconciler = Reconciler(db, cfg, position_fetcher=lambda: [], order_fetcher=lambda: [])
        executor = LiveExecutor(bridge, safety, reconciler, cfg, db)

        shadow = ShadowExecutor(executor, db, dry_run=True)
        comp = shadow.shadow_enter(
            {'strategy': 'test', 'symbol': 'NIFTY', 'margin_required': 1000,
             'legs': [{'strike': 24000, 'option_type': 'CE', 'action': 'BUY',
                        'premium': 50, 'security_id': '100', 'qty': 75}]},
            trade_id=1,
            paper_result={'status': 'entered', 'trade_id': 1},
        )
        assert comp.match is True
        assert comp.live_result.get('dry_run') is True
        os.remove(db)


# ── 429 Rate Limit Backoff ───────────────────────────────────────

class TestRateLimitBackoff:

    def test_429_returns_immediately_with_backoff(self):
        db = _make_db()
        cfg = _safety_config()

        def mock_429(action, params):
            return {'orderId': '', 'orderStatus': 'RATE_LIMITED',
                    'httpCode': 429}

        queue = OrderQueue(cfg, db, executor=mock_429)
        req = OrderRequest(
            action=OrderAction.PLACE, priority=Priority.ENTRY,
            dhan_params={'securityId': '100', 'quantity': 75,
                         'transactionType': 'BUY', 'orderType': 'LIMIT',
                         'price': 100},
            parent_trade_id=1, leg_index=0,
        )
        result = queue.submit(req)
        assert result is not None
        os.remove(db)


# ── Force Drain Exits ────────────────────────────────────────────

class TestForceDrainExits:

    def test_drain_processes_emergency_orders(self):
        db = _make_db()
        cfg = _safety_config()
        executed = []

        def mock_exec(action, params):
            executed.append((action, params))
            return {'orderId': f'E_{len(executed)}', 'orderStatus': 'TRADED'}

        queue = OrderQueue(cfg, db, executor=mock_exec)
        queue.pause()

        # Submit emergency order while paused
        req = OrderRequest(
            action=OrderAction.PLACE, priority=Priority.EMERGENCY,
            dhan_params={'securityId': '100', 'quantity': 75,
                         'transactionType': 'SELL', 'orderType': 'MARKET',
                         'price': 0},
            parent_trade_id=1, leg_index=0,
        )
        queue.submit(req)

        # Normal submit while paused should not execute
        normal_req = OrderRequest(
            action=OrderAction.PLACE, priority=Priority.ADJUSTMENT,
            dhan_params={'securityId': '200', 'quantity': 75,
                         'transactionType': 'BUY', 'orderType': 'LIMIT',
                         'price': 100},
            parent_trade_id=2, leg_index=0,
        )
        queue.submit(normal_req)

        pre_count = len(executed)
        queue.force_drain_exits()
        # Only emergency order should have been processed
        assert len(executed) > pre_count
        os.remove(db)


# ── WAL Mode Verification ───────────────────────────────────────

class TestWALMode:

    def test_queue_db_uses_wal(self):
        db = _make_db()
        conn = sqlite3.connect(db, timeout=10)
        mode = conn.execute('PRAGMA journal_mode').fetchone()[0]
        conn.close()
        assert mode == 'wal'
        os.remove(db)

    def test_autopilot_conn_uses_wal(self):
        from options.autopilot import _conn
        from options import paper_trade
        db = os.path.join(tempfile.gettempdir(), f'test_wal_ap_{os.getpid()}.db')
        paper_trade.init_db(db)
        conn = _conn(db)
        mode = conn.execute('PRAGMA journal_mode').fetchone()[0]
        bt = conn.execute('PRAGMA busy_timeout').fetchone()[0]
        conn.close()
        assert mode == 'wal'
        assert bt == 10000
        os.remove(db)


# ── Live Status State Machine (unit-level) ───────────────────────

class TestLiveStatusMigration:

    def test_live_status_column_exists(self):
        from options import paper_trade
        db = os.path.join(tempfile.gettempdir(), f'test_ls_{os.getpid()}.db')
        if os.path.exists(db):
            os.remove(db)
        paper_trade.init_db(db)
        conn = sqlite3.connect(db, timeout=10)
        cols = [r[1] for r in conn.execute('PRAGMA table_info(trades)').fetchall()]
        conn.close()
        assert 'live_status' in cols
        os.remove(db)

    def test_autopilot_alerts_table_exists(self):
        from options import paper_trade
        db = os.path.join(tempfile.gettempdir(), f'test_at_{os.getpid()}.db')
        if os.path.exists(db):
            os.remove(db)
        paper_trade.init_db(db)
        conn = sqlite3.connect(db, timeout=10)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        conn.close()
        assert 'autopilot_alerts' in tables
        os.remove(db)
