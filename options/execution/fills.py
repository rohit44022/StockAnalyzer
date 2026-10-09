"""
Fill tracker — consumes OrderFeed WebSocket events and REST position
polls to track fills, partial fills, rejections, and cancellations.

Two input channels:
  1. OrderFeed WS (fast, ~100ms): real-time order status updates
  2. PositionPoller REST (reliable, 30s): periodic position snapshot

If they disagree, PositionPoller wins.
"""

import json
import sqlite3
import logging
import datetime
from typing import Optional, Callable

log = logging.getLogger(__name__)

# Dhan order status values
TERMINAL_STATUSES = frozenset({'TRADED', 'REJECTED', 'CANCELLED', 'EXPIRED'})
ACTIVE_STATUSES = frozenset({'TRANSIT', 'PENDING'})


class FillTracker:

    def __init__(self, db_path: str,
                 on_fill: Optional[Callable] = None,
                 on_reject: Optional[Callable] = None):
        self._db_path = db_path
        self._on_fill = on_fill
        self._on_reject = on_reject

    def process_ws_event(self, event: dict):
        dhan_order_id = str(event.get('orderId', event.get('order_id', '')))
        status = event.get('orderStatus', event.get('status', ''))
        filled_qty = event.get('filledQty', event.get('filled_qty'))
        price = event.get('price') or event.get('tradedPrice')

        if not dhan_order_id:
            return

        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            queue_row = conn.execute(
                'SELECT id, parent_trade_id, leg_index FROM order_queue WHERE dhan_order_id=?',
                (dhan_order_id,)
            ).fetchone()

            queue_id = queue_row['id'] if queue_row else dhan_order_id

            event_type = _status_to_event(status)
            conn.execute(
                '''INSERT INTO order_events
                   (queue_id, event_type, timestamp, dhan_order_id,
                    dhan_status, filled_qty, price, raw_response)
                   VALUES (?,?,?,?,?,?,?,?)''',
                (queue_id, event_type, datetime.datetime.now().isoformat(),
                 dhan_order_id, status, filled_qty, price,
                 json.dumps(event, default=str))
            )

            if queue_row:
                if status == 'TRADED':
                    conn.execute(
                        'UPDATE order_queue SET status=?, completed_at=? WHERE id=?',
                        ('DONE', datetime.datetime.now().isoformat(), queue_id)
                    )
                elif status == 'REJECTED':
                    conn.execute(
                        'UPDATE order_queue SET status=?, error=? WHERE id=?',
                        ('FAILED', event.get('rejectionReason', 'Rejected by exchange'), queue_id)
                    )
                elif status == 'CANCELLED':
                    conn.execute(
                        'UPDATE order_queue SET status=? WHERE id=?',
                        ('CANCELLED', queue_id)
                    )

            conn.commit()
        finally:
            conn.close()

        if status == 'TRADED' and self._on_fill:
            self._on_fill({
                'queue_id': queue_id, 'dhan_order_id': dhan_order_id,
                'price': price, 'filled_qty': filled_qty,
                'trade_id': queue_row['parent_trade_id'] if queue_row else None,
                'leg_index': queue_row['leg_index'] if queue_row else None,
            })
        elif status == 'REJECTED' and self._on_reject:
            self._on_reject({
                'queue_id': queue_id, 'dhan_order_id': dhan_order_id,
                'reason': event.get('rejectionReason', ''),
                'trade_id': queue_row['parent_trade_id'] if queue_row else None,
            })

    def process_position_snapshot(self, positions: list) -> dict:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        pending = conn.execute(
            "SELECT * FROM order_queue WHERE status IN ('SENT','PROCESSING')"
        ).fetchall()

        updates = []
        for order in pending:
            dhan_oid = order['dhan_order_id']
            if not dhan_oid:
                continue
            for pos in positions:
                if _matches_order_to_position(order, pos):
                    conn.execute(
                        'UPDATE order_queue SET status=?, completed_at=? WHERE id=?',
                        ('DONE', datetime.datetime.now().isoformat(), order['id'])
                    )
                    conn.execute(
                        '''INSERT INTO order_events
                           (queue_id, event_type, timestamp, dhan_order_id,
                            dhan_status, filled_qty, price, raw_response)
                           VALUES (?,?,?,?,?,?,?,?)''',
                        (order['id'], 'FILLED_VIA_POSITION',
                         datetime.datetime.now().isoformat(), dhan_oid,
                         'TRADED', pos.get('netQty', pos.get('quantity')),
                         pos.get('averagePrice', pos.get('buyAvg', 0)),
                         json.dumps(pos, default=str))
                    )
                    updates.append(order['id'])
                    break

        conn.commit()
        conn.close()
        return {'updated': updates, 'pending_remaining': len(pending) - len(updates)}

    def get_fills(self, trade_id: int) -> list:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            '''SELECT oe.* FROM order_events oe
               JOIN order_queue oq ON oe.queue_id = oq.id
               WHERE oq.parent_trade_id=? AND oe.event_type IN ('FILLED','TRADED','FILLED_VIA_POSITION')
               ORDER BY oe.id''',
            (trade_id,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_pending_orders(self) -> list:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM order_queue WHERE status IN ('PENDING','PROCESSING','SENT')"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def _status_to_event(dhan_status: str) -> str:
    return {
        'TRADED': 'FILLED', 'REJECTED': 'REJECTED',
        'CANCELLED': 'CANCELLED', 'EXPIRED': 'EXPIRED',
        'TRANSIT': 'TRANSIT', 'PENDING': 'PENDING',
    }.get(dhan_status, f'UNKNOWN_{dhan_status}')


def _matches_order_to_position(order_row, position: dict) -> bool:
    params = json.loads(order_row['dhan_params']) if order_row['dhan_params'] else {}
    sid = str(params.get('securityId', params.get('security_id', '')))
    pos_sid = str(position.get('securityId', position.get('security_id', '')))
    if sid != pos_sid or sid == '':
        return False
    txn = params.get('transactionType', params.get('transaction_type', ''))
    pos_qty = position.get('netQty', position.get('quantity', 0))
    if txn == 'BUY' and pos_qty > 0:
        return True
    if txn == 'SELL' and pos_qty <= 0:
        return True
    return False


def selfcheck():
    import os, tempfile
    from .queue import OrderQueue, OrderRequest, Priority, OrderAction, _init_queue_db

    db = os.path.join(tempfile.gettempdir(), 'test_fills.db')
    if os.path.exists(db):
        os.remove(db)

    conn = sqlite3.connect(db, timeout=10)
    _init_queue_db(conn)
    conn.commit()

    conn.execute(
        '''INSERT INTO order_queue
           (id, priority, action, dhan_params, parent_trade_id, leg_index,
            status, created_at, dhan_order_id)
           VALUES (?,?,?,?,?,?,?,?,?)''',
        ('Q1', 2, 'PLACE', json.dumps({'securityId': '13', 'quantity': 75}),
         1, 0, 'SENT', datetime.datetime.now().isoformat(), 'DHAN_001')
    )
    conn.commit()
    conn.close()

    fills_received = []
    rejects_received = []

    tracker = FillTracker(
        db, on_fill=lambda f: fills_received.append(f),
        on_reject=lambda r: rejects_received.append(r),
    )

    # Test 1: WS fill event
    tracker.process_ws_event({
        'orderId': 'DHAN_001', 'orderStatus': 'TRADED',
        'filledQty': 75, 'price': 100.5,
    })
    assert len(fills_received) == 1, f'Expected 1 fill, got {len(fills_received)}'
    assert fills_received[0]['price'] == 100.5

    # Verify DB updated
    conn = sqlite3.connect(db, timeout=10)
    conn.row_factory = sqlite3.Row
    order = conn.execute('SELECT * FROM order_queue WHERE id=?', ('Q1',)).fetchone()
    assert order['status'] == 'DONE'
    events = conn.execute('SELECT * FROM order_events WHERE queue_id=?', ('Q1',)).fetchall()
    assert len(events) == 1
    assert events[0]['event_type'] == 'FILLED'
    conn.close()

    # Test 2: WS reject event
    conn = sqlite3.connect(db, timeout=10)
    conn.execute(
        '''INSERT INTO order_queue
           (id, priority, action, dhan_params, parent_trade_id, leg_index,
            status, created_at, dhan_order_id)
           VALUES (?,?,?,?,?,?,?,?,?)''',
        ('Q2', 2, 'PLACE', json.dumps({'securityId': '13', 'quantity': 75}),
         2, 0, 'SENT', datetime.datetime.now().isoformat(), 'DHAN_002')
    )
    conn.commit()
    conn.close()

    tracker.process_ws_event({
        'orderId': 'DHAN_002', 'orderStatus': 'REJECTED',
        'rejectionReason': 'Insufficient margin',
    })
    assert len(rejects_received) == 1
    assert 'margin' in rejects_received[0]['reason'].lower()

    # Test 3: Position snapshot reconciliation
    conn = sqlite3.connect(db, timeout=10)
    conn.execute(
        '''INSERT INTO order_queue
           (id, priority, action, dhan_params, parent_trade_id, leg_index,
            status, created_at, dhan_order_id)
           VALUES (?,?,?,?,?,?,?,?,?)''',
        ('Q3', 2, 'PLACE', json.dumps({'securityId': '25', 'quantity': 30, 'transactionType': 'BUY'}),
         3, 0, 'SENT', datetime.datetime.now().isoformat(), 'DHAN_003')
    )
    conn.commit()
    conn.close()

    result = tracker.process_position_snapshot([
        {'securityId': '25', 'netQty': 30, 'averagePrice': 200.0},
    ])
    assert 'Q3' in result['updated']

    # Test 4: get_fills
    fills = tracker.get_fills(trade_id=1)
    assert len(fills) == 1

    # Test 5: get_pending
    pending = tracker.get_pending_orders()
    assert len(pending) == 0  # all resolved

    os.remove(db)
    print('fills.py: self-check PASSED')


if __name__ == '__main__':
    selfcheck()
