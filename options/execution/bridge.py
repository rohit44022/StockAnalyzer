"""
Execution bridge — converts multi-leg strategy recommendations into
sequenced OrderRequests with buy-first safety, 3-tier pricing,
partial-fill recovery, and write-ahead intent logging.

THE CRITICAL RULE: BUY legs first, then SELL legs. Always. No exceptions.
Natenberg Ch.12: never hold a naked short, even transiently.
"""

import json
import time
import sqlite3
import logging
import datetime
from dataclasses import dataclass, field
from typing import Optional

from .queue import OrderQueue, OrderRequest, OrderResult, Priority, OrderAction, QueueStatus

log = logging.getLogger(__name__)

TICK_SIZE = 0.05  # NSE options tick


@dataclass
class LegResult:
    leg_index: int
    action: str  # BUY or SELL
    success: bool
    dhan_order_id: Optional[str] = None
    fill_price: Optional[float] = None
    fill_qty: Optional[int] = None
    queue_id: Optional[str] = None
    error: Optional[str] = None


@dataclass
class EntryResult:
    success: bool
    trade_id: int
    legs_filled: list = field(default_factory=list)
    legs_failed: list = field(default_factory=list)
    total_cost: float = 0.0
    slippage: float = 0.0
    execution_time_sec: float = 0.0
    intent_id: Optional[int] = None


@dataclass
class ExitResult:
    success: bool
    trade_id: int
    legs_closed: list = field(default_factory=list)
    legs_failed: list = field(default_factory=list)
    realized_pnl: float = 0.0
    execution_time_sec: float = 0.0


def _init_bridge_db(conn):
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
    conn.commit()


def _round_tick(price: float, tick: float = TICK_SIZE) -> float:
    return round(round(price / tick) * tick, 2)


def _sort_legs_buy_first(legs: list) -> list:
    """BUY legs first, SELL legs second. Within each group, lower premium first."""
    buys = [l for l in legs if l.get('action') == 'BUY']
    sells = [l for l in legs if l.get('action') == 'SELL']
    buys.sort(key=lambda l: l.get('premium', 0))
    sells.sort(key=lambda l: l.get('premium', 0))
    return buys + sells


def _pair_spreads(legs: list) -> list:
    """
    Group legs into paired spreads: put_buy+put_sell, call_buy+call_sell.
    Within each pair, BUY first.
    Returns list of pairs: [[buy_leg, sell_leg], ...]
    Unpaired legs returned as single-item lists.
    """
    pe_buys = [l for l in legs if l.get('option_type') == 'PE' and l.get('action') == 'BUY']
    pe_sells = [l for l in legs if l.get('option_type') == 'PE' and l.get('action') == 'SELL']
    ce_buys = [l for l in legs if l.get('option_type') == 'CE' and l.get('action') == 'BUY']
    ce_sells = [l for l in legs if l.get('option_type') == 'CE' and l.get('action') == 'SELL']

    pairs = []
    for buy_list, sell_list in [(pe_buys, pe_sells), (ce_buys, ce_sells)]:
        while buy_list and sell_list:
            pairs.append([buy_list.pop(0), sell_list.pop(0)])
        for leftover in buy_list:
            pairs.append([leftover])
        for leftover in sell_list:
            pairs.append([leftover])

    return pairs


class ExecutionBridge:

    def __init__(self, queue: OrderQueue, safety_config: dict, db_path: str,
                 price_fetcher=None, vix_fetcher=None, poll_interval: float = 0.5):
        """
        Parameters
        ----------
        queue : OrderQueue instance
        safety_config : dict with order_timeout_sec, slippage_reject_pct, bid_ask_max_pct, etc.
        db_path : str — same DB as queue
        price_fetcher : callable(security_id) -> {'bid': float, 'ask': float, 'ltp': float}
        vix_fetcher : callable() -> float — returns current India VIX. Sinclair Ch.4.
        poll_interval : float — how often to check order status (seconds)
        """
        self._queue = queue
        self._config = safety_config
        self._db_path = db_path
        self._price_fetcher = price_fetcher
        self._vix_fetcher = vix_fetcher
        self._poll_interval = poll_interval

        conn = sqlite3.connect(db_path, timeout=10)
        _init_bridge_db(conn)
        conn.close()

    def execute_entry(self, trade_id: int, legs: list, symbol: str,
                      strategy: str = '') -> EntryResult:
        start = time.monotonic()
        timeout = self._config.get('order_timeout_sec', 30)

        preflight = self._preflight(legs, symbol)
        if preflight:
            return EntryResult(success=False, trade_id=trade_id,
                               legs_failed=[{'reason': preflight}])

        intent_id = self._write_intent(trade_id, 'ENTRY', strategy, symbol, legs)

        pairs = _pair_spreads(legs)
        filled_legs = []
        failed_legs = []

        for pair in pairs:
            pair_results = self._execute_pair(pair, trade_id, timeout)
            for lr in pair_results:
                if lr.success:
                    filled_legs.append(lr)
                else:
                    failed_legs.append(lr)

            if failed_legs:
                break

        if failed_legs and filled_legs:
            unwind = self._unwind_legs(filled_legs, trade_id, timeout, original_legs=legs)
            failed_legs.extend([LegResult(leg_index=u.leg_index, action='UNWIND',
                                          success=u.success, error=u.error)
                                for u in unwind if not u.success])
            filled_legs = []

        total_cost, slippage = self._calc_slippage(filled_legs, legs)

        max_loss = sum(l.get('premium', 0) * l.get('qty', l.get('quantity', 0))
                       for l in legs if l.get('action') == 'BUY')
        slippage_limit = self._config.get('slippage_reject_pct', 2.0)
        if max_loss > 0 and abs(slippage) > max_loss * slippage_limit / 100:
            log.warning(f'Slippage {slippage:.0f} > {slippage_limit}% of max_loss {max_loss:.0f} — unwinding')
            if filled_legs:
                unwind = self._unwind_legs(filled_legs, trade_id, timeout, original_legs=legs)
                failed_legs.extend([LegResult(leg_index=u.leg_index, action='UNWIND',
                                              success=u.success, error=u.error)
                                    for u in unwind if not u.success])
                unwind_cost = sum(
                    (lr.fill_price or 0) * (lr.fill_qty or 0)
                    for lr in unwind if lr.success
                )
                total_cost = total_cost + unwind_cost
                filled_legs = []

        result = EntryResult(
            success=len(filled_legs) > 0 and len(failed_legs) == 0,
            trade_id=trade_id,
            legs_filled=[_leg_result_dict(lr) for lr in filled_legs],
            legs_failed=[_leg_result_dict(lr) for lr in failed_legs],
            total_cost=total_cost,
            slippage=slippage,
            execution_time_sec=round(time.monotonic() - start, 2),
            intent_id=intent_id,
        )

        self._complete_intent(intent_id,
                              'COMPLETED' if result.success else 'FAILED',
                              result)
        return result

    def execute_exit(self, trade_id: int, legs: list, symbol: str,
                     reason: str = '') -> ExitResult:
        start = time.monotonic()
        timeout = self._config.get('order_timeout_sec', 30)

        intent_id = self._write_intent(trade_id, 'EXIT', reason, symbol, legs)

        exit_legs = self._invert_legs(legs)
        sorted_legs = _sort_legs_buy_first(exit_legs)

        filled = []
        failed = []
        for i, leg in enumerate(sorted_legs):
            lr = self._execute_single_leg(leg, trade_id, i, timeout)
            if lr.success:
                filled.append(lr)
            else:
                failed.append(lr)

        result = ExitResult(
            success=len(filled) > 0 and len(failed) == 0,
            trade_id=trade_id,
            legs_closed=[_leg_result_dict(lr) for lr in filled],
            legs_failed=[_leg_result_dict(lr) for lr in failed],
            execution_time_sec=round(time.monotonic() - start, 2),
        )

        self._complete_intent(intent_id,
                              'COMPLETED' if result.success else 'FAILED',
                              result)
        return result

    def _preflight(self, legs: list, symbol: str) -> Optional[str]:
        if not legs:
            return 'No legs provided'

        max_spread_pct = self._config.get('bid_ask_max_pct', 4.0)
        vix_halt = self._config.get('vix_halt_above', 30)
        min_dte = self._config.get('min_dte_entry', 7)
        max_dte = self._config.get('max_dte_entry', 45)

        has_sell = any(l.get('action') == 'SELL' for l in legs)

        # Sinclair Ch.4: VIX > 30 = don't sell vol
        if has_sell and self._vix_fetcher:
            vix = self._vix_fetcher()
            if vix and vix > vix_halt:
                return f'VIX {vix:.1f} > halt threshold {vix_halt} (Sinclair Ch.4)'

        for leg in legs:
            if self._price_fetcher and leg.get('security_id'):
                quote = self._price_fetcher(leg['security_id'])
                if quote:
                    bid, ask = quote.get('bid', 0), quote.get('ask', 0)
                    if bid > 0 and ask > 0:
                        mid = (bid + ask) / 2
                        spread_pct = ((ask - bid) / mid) * 100 if mid > 0 else 999
                        if spread_pct > max_spread_pct:
                            return (f'Bid-ask spread {spread_pct:.1f}% > '
                                    f'{max_spread_pct}% on leg {leg.get("strike")} '
                                    f'{leg.get("option_type")}')

            dte = leg.get('dte', leg.get('days_to_expiry'))
            if dte is not None:
                if dte < min_dte:
                    return f'DTE {dte} < minimum {min_dte}'
                if dte > max_dte:
                    return f'DTE {dte} > maximum {max_dte}'

        _IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        now = datetime.datetime.now(_IST)
        if now.hour == 15 and now.minute >= 15:
            return 'No entries in last 15 min of session (after 3:15 PM)'
        if now.hour > 15 or (now.hour < 9) or (now.hour == 9 and now.minute < 15):
            return 'Market is closed'

        return None

    def _execute_pair(self, pair: list, trade_id: int,
                      timeout: float) -> list:
        results = []
        for i, leg in enumerate(pair):
            lr = self._execute_single_leg(leg, trade_id,
                                          leg.get('_orig_index', i), timeout)
            results.append(lr)
            if not lr.success:
                break
        return results

    def _execute_single_leg(self, leg: dict, trade_id: int,
                            leg_index: int, timeout: float) -> LegResult:
        prices = self._get_tier_prices(leg)

        prev_order_id = None
        for tier, (price, tier_timeout) in enumerate(prices):
            request = OrderRequest(
                priority=Priority.ENTRY,
                action=OrderAction.PLACE if tier == 0 else OrderAction.MODIFY,
                dhan_params=self._leg_to_dhan(leg, price),
                parent_trade_id=trade_id,
                leg_index=leg_index,
                timeout_sec=tier_timeout,
            )

            if tier == 0:
                queue_id = self._queue.submit(request)
                result = self._queue.process_next()
            else:
                if not prev_order_id:
                    break
                request.action = OrderAction.MODIFY
                request.dhan_params['orderId'] = prev_order_id
                request.dhan_params['price'] = price
                queue_id = self._queue.submit(request)
                result = self._queue.process_next()

            if result is None:
                return LegResult(leg_index=leg_index, action=leg.get('action', ''),
                                 success=False, error='Queue returned None (paused?)')

            prev_order_id = result.dhan_order_id

            if result.success and result.dhan_order_id:
                filled = self._wait_fill(result.dhan_order_id, tier_timeout)
                if filled:
                    return LegResult(
                        leg_index=leg_index, action=leg.get('action', ''),
                        success=True, dhan_order_id=result.dhan_order_id,
                        fill_price=filled.get('price', price),
                        fill_qty=filled.get('quantity'),
                        queue_id=queue_id,
                    )

        if prev_order_id:
            cancel_req = OrderRequest(
                priority=Priority.STOP_LOSS,
                action=OrderAction.CANCEL,
                dhan_params={'orderId': prev_order_id},
                parent_trade_id=trade_id,
                leg_index=leg_index,
            )
            self._queue.submit(cancel_req)
            self._queue.process_next()
            # Verify cancel took effect
            time.sleep(1)
            conn = sqlite3.connect(self._db_path, timeout=10)
            conn.row_factory = sqlite3.Row
            ev = conn.execute(
                "SELECT event_type FROM order_events "
                "WHERE dhan_order_id=? ORDER BY id DESC LIMIT 1",
                (prev_order_id,)
            ).fetchone()
            conn.close()
            if ev and ev['event_type'] not in ('CANCELLED', 'REJECTED', 'CANCEL_SENT'):
                log.warning(f'Cancel unconfirmed for {prev_order_id}, '
                            f'last event: {ev["event_type"]}')
                return LegResult(leg_index=leg_index, action=leg.get('action', ''),
                                 success=False,
                                 error=f'Cancel unconfirmed — order {prev_order_id} may still fill',
                                 dhan_order_id=prev_order_id)

        return LegResult(leg_index=leg_index, action=leg.get('action', ''),
                         success=False, error=f'All {len(prices)} pricing tiers exhausted')

    def _get_tier_prices(self, leg: dict) -> list:
        timeout = self._config.get('order_timeout_sec', 30)
        tier_time = timeout / 3.0

        premium = leg.get('premium', leg.get('ltp', 0))
        bid = leg.get('bid', premium * 0.98)
        ask = leg.get('ask', premium * 1.02)

        if self._price_fetcher and leg.get('security_id'):
            quote = self._price_fetcher(leg['security_id'])
            if quote:
                bid = quote.get('bid', bid)
                ask = quote.get('ask', ask)

        mid = _round_tick((bid + ask) / 2)
        is_buy = leg.get('action') == 'BUY'

        if is_buy:
            aggressive = _round_tick(mid + TICK_SIZE)
            best = _round_tick(ask)
        else:
            aggressive = _round_tick(mid - TICK_SIZE)
            best = _round_tick(bid)

        return [(mid, tier_time), (aggressive, tier_time), (best, tier_time)]

    def _wait_fill(self, dhan_order_id: str, timeout: float) -> Optional[dict]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            conn = sqlite3.connect(self._db_path, timeout=10)
            conn.row_factory = sqlite3.Row
            ev = conn.execute(
                '''SELECT * FROM order_events
                   WHERE dhan_order_id=? AND event_type IN ('FILLED','TRADED')
                   ORDER BY id DESC LIMIT 1''',
                (dhan_order_id,)
            ).fetchone()
            conn.close()
            if ev:
                return dict(ev)

            conn2 = sqlite3.connect(self._db_path, timeout=10)
            conn2.row_factory = sqlite3.Row
            orow = conn2.execute(
                'SELECT status, dhan_response FROM order_queue WHERE dhan_order_id=?',
                (dhan_order_id,)
            ).fetchone()
            conn2.close()
            if orow and orow['status'] in (QueueStatus.DONE, QueueStatus.FAILED):
                if orow['status'] == QueueStatus.DONE:
                    resp = json.loads(orow['dhan_response'] or '{}')
                    return {'price': resp.get('price'), 'quantity': resp.get('quantity')}
                return None

            time.sleep(self._poll_interval)
        return None

    def _calc_slippage(self, filled_legs: list, original_legs: list) -> tuple:
        """Sinclair Ch.10: track actual vs theoretical cost."""
        total_cost = 0.0
        theoretical_cost = 0.0
        for lr in filled_legs:
            if lr.fill_price and lr.fill_qty:
                sign = 1 if lr.action == 'BUY' else -1
                total_cost += sign * lr.fill_price * lr.fill_qty
        for leg in original_legs:
            premium = leg.get('premium', leg.get('ltp', 0))
            qty = leg.get('qty', leg.get('quantity', 0))
            sign = 1 if leg.get('action') == 'BUY' else -1
            theoretical_cost += sign * premium * qty
        slippage = total_cost - theoretical_cost if theoretical_cost else 0.0
        return round(total_cost, 2), round(slippage, 2)

    def _unwind_legs(self, filled_legs: list, trade_id: int,
                     timeout: float, original_legs: list = None) -> list:
        sid_by_index = {}
        if original_legs:
            for i, leg in enumerate(original_legs):
                sid_by_index[i] = str(leg.get('security_id', ''))
        results = []
        for lr in filled_legs:
            inverse_action = 'SELL' if lr.action == 'BUY' else 'BUY'
            unwind_price = lr.fill_price or 0
            if unwind_price:
                unwind_price = _round_tick(unwind_price * (0.95 if inverse_action == 'SELL' else 1.05))
            sid = sid_by_index.get(lr.leg_index, '')
            if not sid:
                conn = sqlite3.connect(self._db_path, timeout=10)
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    'SELECT dhan_params FROM order_queue WHERE id=?', (lr.queue_id,)
                ).fetchone()
                conn.close()
                if row:
                    p = json.loads(row['dhan_params']) if row['dhan_params'] else {}
                    sid = str(p.get('securityId', p.get('security_id', '')))
            unwind_params = {
                'transactionType': inverse_action,
                'exchangeSegment': 'NSE_FNO',
                'productType': 'NORMAL',
                'orderType': 'LIMIT',
                'quantity': lr.fill_qty or 0,
                'price': unwind_price,
                'validity': 'DAY',
                'securityId': sid,
            }
            req = OrderRequest(
                priority=Priority.STOP_LOSS,
                action=OrderAction.PLACE,
                dhan_params=unwind_params,
                parent_trade_id=trade_id,
                leg_index=lr.leg_index,
            )
            self._queue.submit(req)
            r = self._queue.process_next()
            if r and r.success and r.dhan_order_id:
                filled = self._wait_fill(r.dhan_order_id, timeout)
                if filled:
                    results.append(LegResult(
                        leg_index=lr.leg_index, action='UNWIND',
                        success=True, dhan_order_id=r.dhan_order_id,
                        fill_price=filled.get('price'),
                        fill_qty=filled.get('quantity'),
                    ))
                else:
                    results.append(LegResult(
                        leg_index=lr.leg_index, action='UNWIND',
                        success=False, dhan_order_id=r.dhan_order_id,
                        error=f'Unwind order {r.dhan_order_id} accepted but not filled',
                    ))
            else:
                results.append(LegResult(
                    leg_index=lr.leg_index, action='UNWIND',
                    success=False,
                    dhan_order_id=r.dhan_order_id if r else None,
                    error=r.error if r else 'Queue returned None',
                ))
        return results

    def _invert_legs(self, legs: list) -> list:
        inverted = []
        for leg in legs:
            inv = dict(leg)
            inv['action'] = 'SELL' if leg.get('action') == 'BUY' else 'BUY'
            inverted.append(inv)
        return inverted

    def _leg_to_dhan(self, leg: dict, price: float) -> dict:
        return {
            'transactionType': leg.get('action', 'BUY'),
            'exchangeSegment': 'NSE_FNO',
            'productType': 'NORMAL',
            'orderType': 'LIMIT',
            'quantity': leg.get('qty', leg.get('quantity', 75)),
            'price': price,
            'validity': 'DAY',
            'securityId': str(leg.get('security_id', '')),
        }

    def _write_intent(self, trade_id: int, intent_type: str,
                      strategy: str, symbol: str, legs: list) -> int:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute(
            '''INSERT INTO trade_intents
               (trade_id, intent_type, strategy, symbol, legs_json, status, created_at)
               VALUES (?,?,?,?,?,?,?)''',
            (trade_id, intent_type, strategy, symbol,
             json.dumps(legs, default=str),
             'PENDING', datetime.datetime.now().isoformat())
        )
        intent_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        conn.commit()
        conn.close()
        return intent_id

    def _complete_intent(self, intent_id: int, status: str, result):
        conn = sqlite3.connect(self._db_path, timeout=10)
        data = {'success': result.success, 'trade_id': result.trade_id}
        if hasattr(result, 'legs_filled'):
            data['legs_filled'] = result.legs_filled
            data['legs_failed'] = result.legs_failed
        if hasattr(result, 'total_cost'):
            data['total_cost'] = result.total_cost
            data['slippage'] = result.slippage
        if hasattr(result, 'legs_closed'):
            data['legs_closed'] = result.legs_closed
        if hasattr(result, 'execution_time_sec'):
            data['execution_time_sec'] = result.execution_time_sec
        result_json = json.dumps(data, default=str)
        conn.execute(
            '''UPDATE trade_intents
               SET status=?, completed_at=?, result_json=?
               WHERE id=?''',
            (status, datetime.datetime.now().isoformat(), result_json, intent_id)
        )
        conn.commit()
        conn.close()

    def get_pending_intents(self) -> list:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM trade_intents WHERE status='PENDING' ORDER BY id"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def _leg_result_dict(lr: LegResult) -> dict:
    return {
        'leg_index': lr.leg_index, 'action': lr.action,
        'success': lr.success, 'dhan_order_id': lr.dhan_order_id,
        'fill_price': lr.fill_price, 'fill_qty': lr.fill_qty,
        'error': lr.error,
    }


def selfcheck():
    """Verify bridge: buy-first ordering, paired spreads, intent logging, unwind."""
    import os
    import tempfile

    db = os.path.join(tempfile.gettempdir(), 'test_bridge.db')
    if os.path.exists(db):
        os.remove(db)

    fill_log = []
    order_counter = [0]

    def mock_executor(action, params):
        order_counter[0] += 1
        oid = f'ORD_{order_counter[0]}'
        fill_log.append({
            'action': action, 'type': params.get('transactionType'),
            'price': params.get('price'), 'order_id': oid,
        })
        return {'orderId': oid, 'orderStatus': 'TRADED'}

    config = {
        'max_lots_per_trade': 10, 'max_orders_per_day': 100,
        'allowed_indices': ['NIFTY', 'BANKNIFTY'],
        'rate_limit_per_sec': 100.0, 'rate_limit_burst': 100,
        'order_timeout_sec': 0.5,
        'bid_ask_max_pct': 10.0, 'slippage_reject_pct': 999.0,
        'min_dte_entry': 1, 'max_dte_entry': 90,
    }

    queue = OrderQueue(config, db, executor=mock_executor)

    def instant_fill_fetcher(sid):
        return {'bid': 99.0, 'ask': 101.0, 'ltp': 100.0}

    bridge = ExecutionBridge(queue, config, db,
                             price_fetcher=instant_fill_fetcher,
                             poll_interval=0.01)

    # Monkey-patch _wait_fill to return immediately (mock fills instantly)
    bridge._wait_fill = lambda oid, timeout: {'price': 100.0, 'quantity': 75}

    # Override preflight market-hours check for testing
    orig_preflight = bridge._preflight
    bridge._preflight = lambda legs, sym: None

    # Test 1: Buy-first ordering with iron condor
    legs = [
        {'strike': 23800, 'option_type': 'PE', 'action': 'BUY', 'premium': 50, 'security_id': '100', 'qty': 75},
        {'strike': 23900, 'option_type': 'PE', 'action': 'SELL', 'premium': 80, 'security_id': '101', 'qty': 75},
        {'strike': 24100, 'option_type': 'CE', 'action': 'SELL', 'premium': 80, 'security_id': '102', 'qty': 75},
        {'strike': 24200, 'option_type': 'CE', 'action': 'BUY', 'premium': 50, 'security_id': '103', 'qty': 75},
    ]

    fill_log.clear()
    order_counter[0] = 0
    result = bridge.execute_entry(trade_id=1, legs=legs, symbol='NIFTY',
                                  strategy='iron_condor')

    assert result.success, f'Entry should succeed: {result.legs_failed}'
    # Verify buy-first: within each pair, BUY comes before SELL
    types = [f['type'] for f in fill_log if f['action'] == 'PLACE']
    # First pair (PE): BUY then SELL
    assert types[0] == 'BUY', f'First leg should be BUY, got {types[0]}'
    assert types[1] == 'SELL', f'Second leg should be SELL, got {types[1]}'
    # Second pair (CE): BUY then SELL
    assert types[2] == 'BUY', f'Third leg should be BUY, got {types[2]}'
    assert types[3] == 'SELL', f'Fourth leg should be SELL, got {types[3]}'

    # Test 2: Intent logging
    conn = sqlite3.connect(db, timeout=10)
    conn.row_factory = sqlite3.Row
    intents = conn.execute('SELECT * FROM trade_intents').fetchall()
    assert len(intents) >= 1, 'Should have at least 1 intent'
    assert intents[0]['status'] == 'COMPLETED'
    conn.close()

    # Test 3: Paired spread grouping
    pairs = _pair_spreads(legs)
    assert len(pairs) == 2, f'Iron condor should have 2 pairs, got {len(pairs)}'
    assert pairs[0][0]['action'] == 'BUY', 'First in pair should be BUY'
    assert pairs[0][1]['action'] == 'SELL', 'Second in pair should be SELL'

    # Test 4: Exit (inverts actions)
    fill_log.clear()
    order_counter[0] = 0
    exit_result = bridge.execute_exit(trade_id=1, legs=legs, symbol='NIFTY',
                                      reason='target hit')
    assert exit_result.success, f'Exit should succeed: {exit_result.legs_failed}'

    # Test 5: sort_legs_buy_first
    sorted_l = _sort_legs_buy_first(legs)
    assert sorted_l[0]['action'] == 'BUY'
    assert sorted_l[1]['action'] == 'BUY'
    assert sorted_l[2]['action'] == 'SELL'
    assert sorted_l[3]['action'] == 'SELL'

    os.remove(db)
    print('bridge.py: self-check PASSED')


if __name__ == '__main__':
    selfcheck()
