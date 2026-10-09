"""
Order queue — serializes all Dhan API order mutations through a
priority queue with rate limiting, pre-send guards, and idempotency.

Single-threaded by design: prevents race conditions on position state
and guarantees ordering (emergency exits before new entries).
Davey Ch.10: single-process constraint is a safety feature.
"""

import uuid
import time
import json
import sqlite3
import logging
import threading
import datetime
from dataclasses import dataclass, field, asdict
from enum import IntEnum
from typing import Optional, Callable

log = logging.getLogger(__name__)


class Priority(IntEnum):
    EMERGENCY = 0
    STOP_LOSS = 1
    ENTRY = 2
    ADJUSTMENT = 3


class OrderAction:
    PLACE = 'PLACE'
    MODIFY = 'MODIFY'
    CANCEL = 'CANCEL'


class QueueStatus:
    PENDING = 'PENDING'
    PROCESSING = 'PROCESSING'
    SENT = 'SENT'
    DONE = 'DONE'
    FAILED = 'FAILED'
    REJECTED_GUARD = 'REJECTED_GUARD'
    CANCELLED = 'CANCELLED'


@dataclass
class OrderRequest:
    priority: int
    action: str
    dhan_params: dict
    parent_trade_id: Optional[int] = None
    leg_index: Optional[int] = None
    max_attempts: int = 3
    timeout_sec: float = 5.0
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    created_at: str = field(default_factory=lambda: datetime.datetime.now().isoformat())
    attempts: int = 0


@dataclass
class OrderResult:
    queue_id: str
    success: bool
    dhan_order_id: Optional[str] = None
    dhan_status: Optional[str] = None
    error: Optional[str] = None
    raw_response: Optional[dict] = None


class _TokenBucket:
    """Rate limiter: tokens_per_sec with burst capacity."""

    def __init__(self, rate: float = 5.0, burst: int = 5):
        self._rate = rate
        self._burst = burst
        self._tokens = float(burst)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, timeout: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(self._burst, self._tokens + (now - self._last) * self._rate)
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)


def _init_queue_db(conn):
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=10000')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS order_queue (
        id TEXT PRIMARY KEY,
        priority INTEGER NOT NULL,
        action TEXT NOT NULL,
        dhan_params TEXT NOT NULL,
        parent_trade_id INTEGER,
        leg_index INTEGER,
        status TEXT NOT NULL DEFAULT 'PENDING',
        created_at TEXT NOT NULL,
        sent_at TEXT,
        completed_at TEXT,
        attempts INTEGER DEFAULT 0,
        max_attempts INTEGER DEFAULT 3,
        timeout_sec REAL DEFAULT 5.0,
        dhan_order_id TEXT,
        dhan_response TEXT,
        error TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS order_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        queue_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        dhan_order_id TEXT,
        dhan_status TEXT,
        filled_qty INTEGER,
        price REAL,
        raw_response TEXT,
        FOREIGN KEY (queue_id) REFERENCES order_queue(id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS daily_counters (
        date TEXT PRIMARY KEY,
        orders_sent INTEGER DEFAULT 0,
        orders_filled INTEGER DEFAULT 0,
        orders_failed INTEGER DEFAULT 0,
        capital_deployed REAL DEFAULT 0
    )''')
    conn.commit()


class OrderQueue:
    """Priority-ordered, rate-limited, guarded order queue."""

    def __init__(self, safety_config: dict, db_path: str,
                 executor: Optional[Callable] = None):
        """
        Parameters
        ----------
        safety_config : dict with max_lots_per_trade, max_orders_per_day,
                        max_capital_at_risk, max_concurrent_positions, allowed_indices
        db_path : str — SQLite database path
        executor : callable(action, dhan_params) -> dict — Dhan API caller.
                   If None, uses dhan_order module. Inject mock for tests.
        """
        self._config = safety_config
        self._db_path = db_path
        self._executor = executor
        self._bucket = _TokenBucket(
            rate=safety_config.get('rate_limit_per_sec', 5.0),
            burst=safety_config.get('rate_limit_burst', 5),
        )
        self._paused = False
        self._recovering = False
        self._running = False
        self._lock = threading.Lock()
        self._consecutive_429 = 0

        conn = sqlite3.connect(db_path, timeout=10)
        _init_queue_db(conn)
        conn.close()

    def submit(self, request: OrderRequest) -> str:
        conn = sqlite3.connect(self._db_path, timeout=10)
        try:
            conn.execute(
                '''INSERT INTO order_queue
                   (id, priority, action, dhan_params, parent_trade_id, leg_index,
                    status, created_at, attempts, max_attempts, timeout_sec)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (request.id, request.priority, request.action,
                 json.dumps(request.dhan_params), request.parent_trade_id,
                 request.leg_index, QueueStatus.PENDING, request.created_at,
                 request.attempts, request.max_attempts, request.timeout_sec)
            )
            _log_event(conn, request.id, 'SUBMITTED')
            conn.commit()
        except sqlite3.IntegrityError:
            log.info(f'Idempotent resubmit: {request.id} already exists')
        finally:
            conn.close()
        return request.id

    def process_next(self) -> Optional[OrderResult]:
        if self._paused or self._recovering:
            return None

        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            '''SELECT * FROM order_queue
               WHERE status = ?
               ORDER BY priority ASC, created_at ASC
               LIMIT 1''',
            (QueueStatus.PENDING,)
        ).fetchone()

        if not row:
            conn.close()
            return None

        queue_id = row['id']
        dhan_params = json.loads(row['dhan_params'])
        action = row['action']
        attempts = row['attempts']
        max_attempts = row['max_attempts']

        guard_error = self._check_guards(dhan_params, conn)
        if guard_error:
            conn.execute(
                'UPDATE order_queue SET status=?, error=?, completed_at=? WHERE id=?',
                (QueueStatus.REJECTED_GUARD, guard_error,
                 datetime.datetime.now().isoformat(), queue_id)
            )
            _log_event(conn, queue_id, 'REJECTED_GUARD', error=guard_error)
            conn.commit()
            conn.close()
            return OrderResult(queue_id=queue_id, success=False, error=guard_error)

        conn.execute(
            'UPDATE order_queue SET status=?, attempts=?, sent_at=? WHERE id=?',
            (QueueStatus.PROCESSING, attempts + 1,
             datetime.datetime.now().isoformat(), queue_id)
        )
        conn.commit()
        conn.close()

        if not self._bucket.acquire(timeout=2.0):
            conn = sqlite3.connect(self._db_path, timeout=10)
            try:
                conn.execute(
                    'UPDATE order_queue SET status=? WHERE id=?',
                    (QueueStatus.PENDING, queue_id)
                )
                _log_event(conn, queue_id, 'RATE_LIMITED')
                conn.commit()
            finally:
                conn.close()
            return None

        try:
            result = self._send_to_dhan(action, dhan_params, queue_id)
        except Exception as e:
            log.error(f'Unhandled error sending order {queue_id}: {e}')
            result = OrderResult(queue_id=queue_id, success=False, error=str(e))

        if not isinstance(result, OrderResult):
            log.error(f'_send_to_dhan returned {type(result)} for order {queue_id}')
            result = OrderResult(queue_id=queue_id, success=False,
                                 error=f'Unexpected result type: {type(result).__name__}')

        conn = sqlite3.connect(self._db_path, timeout=10)
        try:
            if not result.success and result.error and result.error.startswith('Unhandled:'):
                conn.execute(
                    'UPDATE order_queue SET status=?, error=? WHERE id=?',
                    (QueueStatus.PENDING if attempts + 1 < max_attempts else QueueStatus.FAILED,
                     result.error, queue_id)
                )
                _log_event(conn, queue_id, 'ERROR', error=result.error)
                conn.commit()
                return result

            if result.success:
                conn.execute(
                    '''UPDATE order_queue
                       SET status=?, dhan_order_id=?, dhan_response=?, completed_at=?
                       WHERE id=?''',
                    (QueueStatus.SENT, result.dhan_order_id,
                     json.dumps(result.raw_response) if result.raw_response else None,
                     datetime.datetime.now().isoformat(), queue_id)
                )
                _log_event(conn, queue_id, 'SENT',
                           dhan_order_id=result.dhan_order_id,
                           dhan_status=result.dhan_status,
                           raw_response=result.raw_response)
                _increment_daily(conn, 'orders_sent')
                order_value = dhan_params.get('quantity', 0) * dhan_params.get('price', 0)
                if order_value > 0:
                    _increment_daily_capital(conn, order_value)
            else:
                new_status = QueueStatus.PENDING if attempts + 1 < max_attempts else QueueStatus.FAILED
                conn.execute(
                    'UPDATE order_queue SET status=?, error=? WHERE id=?',
                    (new_status, result.error, queue_id)
                )
                event = 'RETRY' if new_status == QueueStatus.PENDING else 'FAILED'
                _log_event(conn, queue_id, event, error=result.error)
                if new_status == QueueStatus.FAILED:
                    _increment_daily(conn, 'orders_failed')

            conn.commit()
        finally:
            conn.close()
        return result

    def process_all_pending(self) -> list:
        results = []
        while True:
            r = self.process_next()
            if r is None:
                break
            results.append(r)
        return results

    def emergency_drain(self) -> list:
        was_paused = self._paused
        self._paused = False
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            '''SELECT id FROM order_queue
               WHERE status=? AND priority=?
               ORDER BY created_at ASC''',
            (QueueStatus.PENDING, Priority.EMERGENCY)
        ).fetchall()
        conn.close()

        results = []
        for _ in rows:
            r = self.process_next()
            if r:
                results.append(r)
        self._paused = self._paused or was_paused
        return results

    def force_drain_exits(self) -> list:
        """Force-process EMERGENCY + STOP_LOSS orders even when paused (EXIT_ALL)."""
        was_paused = self._paused
        self._paused = False
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            '''SELECT id FROM order_queue
               WHERE status=? AND priority<=?
               ORDER BY priority ASC, created_at ASC''',
            (QueueStatus.PENDING, Priority.STOP_LOSS)
        ).fetchall()
        conn.close()
        results = []
        for _ in rows:
            r = self.process_next()
            if r:
                results.append(r)
        self._paused = self._paused or was_paused
        return results

    def pause(self):
        self._paused = True
        log.warning('Order queue PAUSED')

    def resume(self):
        self._paused = False
        log.info('Order queue RESUMED')

    @property
    def is_paused(self) -> bool:
        return self._paused

    def set_recovering(self, state: bool):
        self._recovering = state
        if state:
            log.warning('Queue LOCKED for crash recovery')
        else:
            log.info('Queue UNLOCKED after crash recovery')

    def cancel_pending(self, parent_trade_id: int) -> int:
        conn = sqlite3.connect(self._db_path, timeout=10)
        cur = conn.execute(
            '''UPDATE order_queue SET status=?, completed_at=?
               WHERE parent_trade_id=? AND status=?''',
            (QueueStatus.CANCELLED, datetime.datetime.now().isoformat(),
             parent_trade_id, QueueStatus.PENDING)
        )
        count = cur.rowcount
        conn.commit()
        conn.close()
        return count

    def stats(self) -> dict:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row

        pending = conn.execute(
            'SELECT priority, COUNT(*) as cnt FROM order_queue WHERE status=? GROUP BY priority',
            (QueueStatus.PENDING,)
        ).fetchall()
        pending_by_priority = {Priority(r['priority']).name: r['cnt'] for r in pending}

        today = datetime.date.today().isoformat()
        daily = conn.execute(
            'SELECT * FROM daily_counters WHERE date=?', (today,)
        ).fetchone()

        conn.close()
        return {
            'paused': self._paused,
            'pending': pending_by_priority,
            'total_pending': sum(pending_by_priority.values()),
            'daily': dict(daily) if daily else {
                'orders_sent': 0, 'orders_filled': 0,
                'orders_failed': 0, 'capital_deployed': 0,
            },
        }

    def get_order(self, queue_id: str) -> Optional[dict]:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT * FROM order_queue WHERE id=?', (queue_id,)).fetchone()
        conn.close()
        if not row:
            return None
        d = dict(row)
        d['dhan_params'] = json.loads(d['dhan_params']) if d.get('dhan_params') else {}
        d['dhan_response'] = json.loads(d['dhan_response']) if d.get('dhan_response') else None
        return d

    def get_events(self, queue_id: str) -> list:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            'SELECT * FROM order_events WHERE queue_id=? ORDER BY id', (queue_id,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def _check_guards(self, params: dict, conn) -> Optional[str]:
        cfg = self._config

        security_id = params.get('securityId', params.get('security_id', ''))
        qty = params.get('quantity', 0)

        max_lots = cfg.get('max_lots_per_trade', 5)
        lot_size = _lot_size_for_security(security_id)
        if lot_size and qty > max_lots * lot_size:
            return f'Quantity {qty} exceeds max_lots_per_trade ({max_lots} × {lot_size}={max_lots * lot_size})'

        allowed = cfg.get('allowed_indices', ['NIFTY', 'BANKNIFTY'])
        symbol = _symbol_for_security(security_id)
        if symbol and symbol not in allowed:
            return f'Symbol {symbol} not in allowed_indices {allowed}'

        today = datetime.date.today().isoformat()
        daily = conn.execute(
            'SELECT orders_sent, capital_deployed FROM daily_counters WHERE date=?',
            (today,)
        ).fetchone()
        sent_today = daily[0] if daily else 0
        max_daily = cfg.get('max_orders_per_day', 20)
        if sent_today >= max_daily:
            return f'Daily order limit reached ({sent_today}/{max_daily})'

        max_capital = cfg.get('max_capital_at_risk', 0)
        if max_capital > 0:
            deployed = daily[1] if daily else 0
            order_value = qty * params.get('price', 0)
            if deployed + order_value > max_capital:
                return (f'Would exceed max_capital_at_risk '
                        f'({deployed + order_value:.0f} > {max_capital})')

        return None

    def _send_to_dhan(self, action: str, params: dict, queue_id: str) -> OrderResult:
        if self._executor:
            try:
                resp = self._executor(action, params)
                order_id = (resp.get('orderId') or resp.get('order_id')
                            or resp.get('data', {}).get('orderId'))
                status = resp.get('orderStatus') or resp.get('status', 'unknown')
                http_code = resp.get('httpCode', resp.get('status_code', 200))
                if http_code == 401:
                    self.pause()
                    ev_conn = sqlite3.connect(self._db_path, timeout=10)
                    _log_event(ev_conn, queue_id, 'TOKEN_EXPIRED')
                    ev_conn.commit()
                    ev_conn.close()
                    log.error('Dhan 401: token expired — queue paused')
                    return OrderResult(queue_id=queue_id, success=False,
                                       error='TOKEN_EXPIRED')
                if http_code == 429:
                    self._consecutive_429 = min(self._consecutive_429 + 1, 3)
                    backoff = 2.0 * (2 ** (self._consecutive_429 - 1))
                    log.warning(f'Dhan 429: rate limited — retry after {backoff}s')
                    return OrderResult(queue_id=queue_id, success=False,
                                       error='RATE_LIMITED_BY_DHAN',
                                       raw_response={'backoff_sec': backoff})
                self._consecutive_429 = 0
                return OrderResult(
                    queue_id=queue_id, success=True,
                    dhan_order_id=str(order_id) if order_id else None,
                    dhan_status=status, raw_response=resp,
                )
            except Exception as e:
                return OrderResult(queue_id=queue_id, success=False, error=str(e))

        try:
            from options.data import dhan_fetch
            client = dhan_fetch._get_client()
        except Exception as e:
            return OrderResult(queue_id=queue_id, success=False,
                               error=f'Cannot get Dhan client: {e}')

        try:
            if action == OrderAction.PLACE:
                resp = client.place_order(
                    transaction_type=params.get('transactionType', params.get('transaction_type')),
                    exchange_segment=params.get('exchangeSegment', params.get('exchange_segment', 'NSE_FNO')),
                    product_type=params.get('productType', params.get('product_type', 'NORMAL')),
                    order_type=params.get('orderType', params.get('order_type', 'LIMIT')),
                    validity=params.get('validity', 'DAY'),
                    security_id=str(params.get('securityId', params.get('security_id', ''))),
                    quantity=params.get('quantity', 0),
                    price=params.get('price', 0),
                    trigger_price=params.get('triggerPrice', params.get('trigger_price', 0)),
                )
            elif action == OrderAction.MODIFY:
                resp = client.modify_order(
                    order_id=params['orderId'],
                    order_type=params.get('orderType', 'LIMIT'),
                    quantity=params.get('quantity'),
                    price=params.get('price'),
                    trigger_price=params.get('triggerPrice', 0),
                    validity=params.get('validity', 'DAY'),
                    leg_name=params.get('legName'),
                )
            elif action == OrderAction.CANCEL:
                resp = client.cancel_order(params['orderId'])
            else:
                return OrderResult(queue_id=queue_id, success=False,
                                   error=f'Unknown action: {action}')

            order_id = None
            if resp:
                order_id = (resp.get('orderId') or resp.get('order_id')
                            or (resp.get('data', {}) or {}).get('orderId'))

            return OrderResult(
                queue_id=queue_id, success=True,
                dhan_order_id=str(order_id) if order_id else None,
                dhan_status=resp.get('orderStatus', 'unknown') if resp else 'unknown',
                raw_response=resp,
            )
        except Exception as e:
            return OrderResult(queue_id=queue_id, success=False, error=str(e))


def _log_event(conn, queue_id, event_type, dhan_order_id=None,
               dhan_status=None, filled_qty=None, price=None,
               raw_response=None, error=None):
    raw = None
    if raw_response:
        raw = json.dumps(raw_response)
    elif error:
        raw = json.dumps({'error': error})
    conn.execute(
        '''INSERT INTO order_events
           (queue_id, event_type, timestamp, dhan_order_id, dhan_status,
            filled_qty, price, raw_response)
           VALUES (?,?,?,?,?,?,?,?)''',
        (queue_id, event_type, datetime.datetime.now().isoformat(),
         dhan_order_id, dhan_status, filled_qty, price, raw)
    )


_DAILY_COLUMNS = frozenset({'orders_sent', 'orders_failed', 'capital_deployed'})

def _increment_daily(conn, column):
    if column not in _DAILY_COLUMNS:
        raise ValueError(f'Invalid daily counter column: {column}')
    today = datetime.date.today().isoformat()
    conn.execute(
        f'''INSERT INTO daily_counters (date, {column})
            VALUES (?, 1)
            ON CONFLICT(date) DO UPDATE SET {column} = {column} + 1''',
        (today,)
    )


def _increment_daily_capital(conn, amount):
    today = datetime.date.today().isoformat()
    conn.execute(
        '''INSERT INTO daily_counters (date, capital_deployed)
           VALUES (?, ?)
           ON CONFLICT(date) DO UPDATE SET capital_deployed = capital_deployed + ?''',
        (today, amount, amount)
    )


# Dhan security_id → symbol mapping (index options)
_SID_MAP = {'13': 'NIFTY', '25': 'BANKNIFTY', '27': 'FINNIFTY'}
_LOT_MAP = {'NIFTY': 75, 'BANKNIFTY': 30, 'FINNIFTY': 25}


def _symbol_for_security(security_id) -> Optional[str]:
    return _SID_MAP.get(str(security_id))


def _lot_size_for_security(security_id) -> Optional[int]:
    sym = _symbol_for_security(security_id)
    if sym:
        return _LOT_MAP.get(sym)
    return None


def selfcheck():
    """Verify queue works: submit, guard, priority ordering, idempotency."""
    import os
    import tempfile

    db = os.path.join(tempfile.gettempdir(), 'test_order_queue.db')
    if os.path.exists(db):
        os.remove(db)

    call_log = []

    def mock_executor(action, params):
        call_log.append((action, params))
        return {'orderId': f'MOCK_{len(call_log)}', 'orderStatus': 'TRANSIT'}

    config = {
        'max_lots_per_trade': 5,
        'max_orders_per_day': 10,
        'max_capital_at_risk': 100000,
        'max_concurrent_positions': 4,
        'allowed_indices': ['NIFTY', 'BANKNIFTY'],
        'rate_limit_per_sec': 100.0,
        'rate_limit_burst': 100,
    }

    q = OrderQueue(config, db, executor=mock_executor)

    # Priority ordering: submit P3, P1, P0 — should drain P0 first
    q.submit(OrderRequest(priority=Priority.ADJUSTMENT, action=OrderAction.PLACE,
                          dhan_params={'securityId': '13', 'quantity': 75, 'price': 100}))
    q.submit(OrderRequest(priority=Priority.STOP_LOSS, action=OrderAction.PLACE,
                          dhan_params={'securityId': '13', 'quantity': 75, 'price': 50}))
    q.submit(OrderRequest(priority=Priority.EMERGENCY, action=OrderAction.PLACE,
                          dhan_params={'securityId': '13', 'quantity': 75, 'price': 10}))

    results = q.process_all_pending()
    assert len(results) == 3, f'Expected 3 results, got {len(results)}'
    assert call_log[0][1]['price'] == 10, 'P0 (emergency) should process first'
    assert call_log[1][1]['price'] == 50, 'P1 (stop_loss) should process second'
    assert call_log[2][1]['price'] == 100, 'P3 (adjustment) should process third'

    # Guard: quantity exceeds max_lots
    oversized = OrderRequest(
        priority=Priority.ENTRY, action=OrderAction.PLACE,
        dhan_params={'securityId': '13', 'quantity': 75 * 10, 'price': 200}
    )
    q.submit(oversized)
    r = q.process_next()
    assert not r.success, 'Oversized order should be rejected'
    assert 'max_lots' in r.error, f'Error should mention max_lots: {r.error}'

    # Guard: disallowed symbol
    bad_sym = OrderRequest(
        priority=Priority.ENTRY, action=OrderAction.PLACE,
        dhan_params={'securityId': '27', 'quantity': 40, 'price': 100}
    )
    q.submit(bad_sym)
    r = q.process_next()
    assert not r.success, 'FINNIFTY should be rejected'
    assert 'allowed_indices' in r.error

    # Stats
    s = q.stats()
    assert s['total_pending'] == 0
    assert s['daily']['orders_sent'] == 3

    # Pause/resume
    q.pause()
    q.submit(OrderRequest(priority=Priority.ENTRY, action=OrderAction.PLACE,
                          dhan_params={'securityId': '13', 'quantity': 75, 'price': 300}))
    r = q.process_next()
    assert r is None, 'Queue should return None when paused'
    q.resume()
    r = q.process_next()
    assert r is not None and r.success

    # Cancel pending
    tid = 999
    q.submit(OrderRequest(priority=Priority.ENTRY, action=OrderAction.PLACE,
                          dhan_params={'securityId': '13', 'quantity': 75, 'price': 400},
                          parent_trade_id=tid))
    cancelled = q.cancel_pending(tid)
    assert cancelled == 1

    # Events log
    order = q.get_order(results[0].queue_id)
    assert order is not None
    events = q.get_events(results[0].queue_id)
    assert len(events) >= 2  # SUBMITTED + SENT

    os.remove(db)
    print('queue.py: self-check PASSED')


if __name__ == '__main__':
    selfcheck()
