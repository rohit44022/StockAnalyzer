"""
Reconciler — continuously verifies our position state matches Dhan's.
Detects phantoms (positions on Dhan we don't know about) and orphans
(orders in our DB that Dhan doesn't have). Recovers from crashes.
"""

import json
import sqlite3
import logging
import datetime
from dataclasses import dataclass, field
from typing import Optional, Callable

log = logging.getLogger(__name__)


@dataclass
class ReconcileResult:
    matched: int = 0
    phantoms: list = field(default_factory=list)
    orphans: list = field(default_factory=list)
    quantity_mismatches: list = field(default_factory=list)
    timestamp: str = ''
    clean: bool = True


@dataclass
class RecoveryResult:
    intents_found: int = 0
    completed: int = 0
    partial_recovered: int = 0
    cancelled: int = 0
    errors: list = field(default_factory=list)


class Reconciler:

    def __init__(self, db_path: str, safety_config: dict,
                 position_fetcher: Optional[Callable] = None,
                 order_fetcher: Optional[Callable] = None,
                 on_phantom: Optional[Callable] = None,
                 on_mismatch: Optional[Callable] = None,
                 queue=None):
        """
        Parameters
        ----------
        position_fetcher : callable() -> list[dict] — returns Dhan positions
        order_fetcher : callable() -> list[dict] — returns today's Dhan orders
        on_phantom : callback for phantom positions
        on_mismatch : callback for any reconciliation issue
        """
        self._db_path = db_path
        self._config = safety_config
        self._position_fetcher = position_fetcher
        self._order_fetcher = order_fetcher
        self._on_phantom = on_phantom
        self._on_mismatch = on_mismatch
        self._queue = queue
        self._last_result = None

    def reconcile(self) -> ReconcileResult:
        result = ReconcileResult(timestamp=datetime.datetime.now().isoformat())

        dhan_positions = self._position_fetcher() if self._position_fetcher else []
        dhan_orders = self._order_fetcher() if self._order_fetcher else []

        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            our_open = conn.execute(
                "SELECT * FROM order_queue WHERE status IN ('SENT','DONE') "
                "AND dhan_order_id IS NOT NULL"
            ).fetchall()
            our_open_by_sid = {}
            for row in our_open:
                params = json.loads(row['dhan_params']) if row['dhan_params'] else {}
                sid = str(params.get('securityId', params.get('security_id', '')))
                qty = params.get('quantity', 0)
                txn = params.get('transactionType', params.get('transaction_type', ''))
                if sid:
                    sign = 1 if txn == 'BUY' else -1
                    our_open_by_sid[sid] = our_open_by_sid.get(sid, 0) + (sign * qty)
            our_open_by_sid = {k: v for k, v in our_open_by_sid.items() if v != 0}

            for pos in dhan_positions:
                pos_sid = str(pos.get('securityId', pos.get('security_id', '')))
                pos_qty = pos.get('netQty', pos.get('quantity', 0))
                if not pos_sid or pos_qty == 0:
                    continue

                if pos_sid in our_open_by_sid:
                    result.matched += 1
                    our_qty = our_open_by_sid[pos_sid]
                    if our_qty and abs(pos_qty) != abs(our_qty):
                        mismatch = {
                            'security_id': pos_sid,
                            'our_qty': our_qty, 'dhan_qty': pos_qty,
                            'symbol': pos.get('tradingSymbol', pos.get('symbol', '')),
                        }
                        result.quantity_mismatches.append(mismatch)
                        log.warning(f'QUANTITY MISMATCH: {mismatch}')
                else:
                    phantom = {
                        'security_id': pos_sid,
                        'quantity': pos_qty,
                        'symbol': pos.get('tradingSymbol', pos.get('symbol', '')),
                        'average_price': pos.get('averagePrice', 0),
                    }
                    result.phantoms.append(phantom)
                    log.warning(f'PHANTOM position: {phantom}')

            our_pending = conn.execute(
                "SELECT * FROM order_queue WHERE status IN ('SENT','PROCESSING')"
            ).fetchall()
            dhan_order_ids = set()
            for o in dhan_orders:
                oid = str(o.get('orderId', o.get('order_id', '')))
                if oid:
                    dhan_order_ids.add(oid)

            for row in our_pending:
                if row['dhan_order_id'] and row['dhan_order_id'] not in dhan_order_ids:
                    orphan = {
                        'queue_id': row['id'],
                        'dhan_order_id': row['dhan_order_id'],
                        'action': row['action'],
                    }
                    result.orphans.append(orphan)
                    conn.execute(
                        'UPDATE order_queue SET status=?, error=? WHERE id=?',
                        ('FAILED', 'Orphan: not found in Dhan orders', row['id'])
                    )
                    log.warning(f'ORPHAN order: {orphan}')

            conn.commit()
        finally:
            conn.close()

        result.clean = (len(result.phantoms) == 0 and
                        len(result.orphans) == 0 and
                        len(result.quantity_mismatches) == 0)

        if not result.clean and self._on_mismatch:
            self._on_mismatch(result)
        if result.phantoms and self._on_phantom:
            for p in result.phantoms:
                self._on_phantom(p)

        self._last_result = result
        self._log_reconciliation(result)
        return result

    def recover_from_crash(self) -> RecoveryResult:
        if self._queue:
            self._queue.set_recovering(True)
        result = RecoveryResult()
        try:
            conn = sqlite3.connect(self._db_path, timeout=10)
            conn.row_factory = sqlite3.Row
            try:
                pending_intents = conn.execute(
                    "SELECT * FROM trade_intents WHERE status='PENDING' ORDER BY id"
                ).fetchall()
                result.intents_found = len(pending_intents)

                if not pending_intents:
                    return result

                dhan_positions = self._position_fetcher() if self._position_fetcher else []
                dhan_orders = self._order_fetcher() if self._order_fetcher else []

                dhan_pos_sids = {}
                for p in dhan_positions:
                    sid = str(p.get('securityId', ''))
                    if sid:
                        dhan_pos_sids[sid] = p

                for intent in pending_intents:
                    try:
                        legs = json.loads(intent['legs_json'])
                        filled_count = 0
                        total_legs = len(legs)

                        for leg in legs:
                            sid = str(leg.get('security_id', ''))
                            if sid in dhan_pos_sids:
                                filled_count += 1

                        if filled_count == total_legs:
                            conn.execute(
                                "UPDATE trade_intents SET status='COMPLETED', completed_at=? WHERE id=?",
                                (datetime.datetime.now().isoformat(), intent['id'])
                            )
                            result.completed += 1
                            log.info(f"Crash recovery: intent {intent['id']} fully filled")
                        elif filled_count > 0:
                            conn.execute(
                                "UPDATE trade_intents SET status='PARTIAL_RECOVERED', completed_at=? WHERE id=?",
                                (datetime.datetime.now().isoformat(), intent['id'])
                            )
                            result.partial_recovered += 1
                            log.warning(f"Crash recovery: intent {intent['id']} partial "
                                        f"({filled_count}/{total_legs})")
                        else:
                            intent_sids = {str(leg.get('security_id', '')) for leg in legs} - {''}
                            for o in dhan_orders:
                                if o.get('orderStatus') not in ('PENDING', 'TRANSIT'):
                                    continue
                                o_sid = str(o.get('securityId', o.get('security_id', '')))
                                if intent_sids and o_sid not in intent_sids:
                                    continue
                                oid = o.get('orderId', o.get('order_id'))
                                log.info(f"Crash recovery: cancelling stale order {oid}")
                                if self._queue and self._queue._executor:
                                    try:
                                        self._queue._executor('CANCEL', {'orderId': str(oid)})
                                    except Exception as cancel_err:
                                        log.error(f"Failed to cancel stale order {oid}: {cancel_err}")
                            conn.execute(
                                "UPDATE trade_intents SET status='CANCELLED', completed_at=? WHERE id=?",
                                (datetime.datetime.now().isoformat(), intent['id'])
                            )
                            result.cancelled += 1
                    except Exception as e:
                        result.errors.append(str(e))
                        log.error(f"Crash recovery error on intent {intent['id']}: {e}")

                conn.commit()
                log.info(f'Crash recovery: {result.intents_found} intents, '
                         f'{result.completed} completed, {result.partial_recovered} partial, '
                         f'{result.cancelled} cancelled')
            finally:
                conn.close()
        finally:
            if self._queue:
                self._queue.set_recovering(False)
        return result

    @property
    def last_result(self) -> Optional[ReconcileResult]:
        return self._last_result

    def _log_reconciliation(self, result: ReconcileResult):
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute('''CREATE TABLE IF NOT EXISTS reconciliation_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            matched INTEGER,
            phantoms INTEGER,
            orphans INTEGER,
            mismatches INTEGER,
            clean INTEGER,
            detail TEXT
        )''')
        conn.execute(
            '''INSERT INTO reconciliation_log
               (timestamp, matched, phantoms, orphans, mismatches, clean, detail)
               VALUES (?,?,?,?,?,?,?)''',
            (result.timestamp, result.matched, len(result.phantoms),
             len(result.orphans), len(result.quantity_mismatches),
             1 if result.clean else 0,
             json.dumps({'phantoms': result.phantoms, 'orphans': result.orphans},
                        default=str))
        )
        conn.commit()
        conn.close()


def selfcheck():
    import os, tempfile
    from .queue import _init_queue_db

    db = os.path.join(tempfile.gettempdir(), 'test_reconciler.db')
    if os.path.exists(db):
        os.remove(db)

    conn = sqlite3.connect(db, timeout=10)
    _init_queue_db(conn)
    conn.execute('''CREATE TABLE IF NOT EXISTS trade_intents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id INTEGER NOT NULL,
        intent_type TEXT NOT NULL,
        strategy TEXT,
        symbol TEXT,
        legs_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDING',
        created_at TEXT NOT NULL,
        completed_at TEXT,
        result_json TEXT
    )''')

    # Known order in our DB
    conn.execute(
        '''INSERT INTO order_queue
           (id, priority, action, dhan_params, parent_trade_id, leg_index,
            status, created_at, dhan_order_id)
           VALUES (?,?,?,?,?,?,?,?,?)''',
        ('Q1', 2, 'PLACE', json.dumps({'securityId': '13', 'quantity': 75}),
         1, 0, 'DONE', datetime.datetime.now().isoformat(), 'DHAN_001')
    )

    # Pending order (orphan test)
    conn.execute(
        '''INSERT INTO order_queue
           (id, priority, action, dhan_params, parent_trade_id, leg_index,
            status, created_at, dhan_order_id)
           VALUES (?,?,?,?,?,?,?,?,?)''',
        ('Q2', 2, 'PLACE', json.dumps({'securityId': '25', 'quantity': 30}),
         2, 0, 'SENT', datetime.datetime.now().isoformat(), 'DHAN_GONE')
    )

    # Pending intent (crash recovery test)
    conn.execute(
        '''INSERT INTO trade_intents
           (trade_id, intent_type, strategy, symbol, legs_json, status, created_at)
           VALUES (?,?,?,?,?,?,?)''',
        (3, 'ENTRY', 'iron_condor', 'NIFTY',
         json.dumps([{'security_id': '13'}, {'security_id': '14'}]),
         'PENDING', datetime.datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

    phantom_log = []
    mismatch_log = []

    def mock_positions():
        return [
            {'securityId': '13', 'netQty': 75, 'tradingSymbol': 'NIFTY'},
            {'securityId': '99', 'netQty': 50, 'tradingSymbol': 'UNKNOWN_PHANTOM'},
        ]

    def mock_orders():
        return [{'orderId': 'DHAN_001', 'orderStatus': 'TRADED'}]

    rec = Reconciler(
        db, {'auto_exit_phantoms': False},
        position_fetcher=mock_positions,
        order_fetcher=mock_orders,
        on_phantom=lambda p: phantom_log.append(p),
        on_mismatch=lambda r: mismatch_log.append(r),
    )

    # Test 1: Reconciliation
    result = rec.reconcile()
    assert result.matched == 1, f'Expected 1 match, got {result.matched}'
    assert len(result.phantoms) == 1, f'Expected 1 phantom, got {len(result.phantoms)}'
    assert result.phantoms[0]['security_id'] == '99'
    assert len(result.orphans) == 1, f'Expected 1 orphan, got {len(result.orphans)}'
    assert result.orphans[0]['dhan_order_id'] == 'DHAN_GONE'
    assert not result.clean
    assert len(phantom_log) == 1
    assert len(mismatch_log) == 1

    # Test 2: Crash recovery
    def mock_positions_for_recovery():
        return [{'securityId': '13', 'netQty': 75}]

    rec2 = Reconciler(
        db, {}, position_fetcher=mock_positions_for_recovery,
        order_fetcher=lambda: [],
    )
    recovery = rec2.recover_from_crash()
    assert recovery.intents_found == 1
    # Only 1 of 2 legs found → partial
    assert recovery.partial_recovered == 1

    # Test 3: Reconciliation log persisted
    conn = sqlite3.connect(db, timeout=10)
    conn.row_factory = sqlite3.Row
    logs = conn.execute('SELECT * FROM reconciliation_log').fetchall()
    assert len(logs) >= 1
    conn.close()

    os.remove(db)
    print('reconciler.py: self-check PASSED')


if __name__ == '__main__':
    selfcheck()
