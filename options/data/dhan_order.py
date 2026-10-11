"""
Dhan order execution for options strategies.

Safety: every order requires explicit confirmation. No market orders by default.
All orders are LIMIT. Kill switch aborts all pending orders.

Davey Ch.14: live execution only after strategy graduates incubation.
"""

import logging
import datetime
from . import dhan_fetch

log = logging.getLogger(__name__)

# Dhan exchange segment for index options
from .ref_data import LOT_SIZES, DHAN_SEGMENTS as SEGMENT_MAP


def _build_order(leg, symbol, lots=1, product='NORMAL'):
    """Convert a strategy leg dict to Dhan order payload."""
    from .ref_data import lot_size as _ls
    lot_size = _ls(symbol)
    return {
        'transactionType': 'BUY' if leg['action'] == 'BUY' else 'SELL',
        'exchangeSegment': SEGMENT_MAP.get(symbol.upper(), 'NSE_FNO'),
        'productType': product,
        'orderType': 'LIMIT',
        'quantity': lot_size * lots,
        'price': leg.get('limit_price', leg.get('premium', 0)),
        'validity': 'DAY',
        'securityId': str(leg.get('security_id', '')),
        'strike': leg.get('strike'),
        'option_type': leg.get('option_type'),
    }


def place_strategy(legs, symbol='NIFTY', lots=1, product='NORMAL',
                   dry_run=True):
    """
    Place orders for all legs of a strategy.

    Parameters
    ----------
    legs : list of dicts — from builder.build()['legs']
    symbol : str
    lots : int
    product : str — 'NORMAL' (carry) or 'INTRADAY'
    dry_run : bool — if True, returns orders without placing (default: safe)

    Returns
    -------
    dict: status, orders (list of order dicts with Dhan response)
    """
    orders = [_build_order(leg, symbol, lots, product) for leg in legs]

    if dry_run:
        log.info(f'DRY RUN: {len(orders)} orders for {symbol}')
        return {
            'status': 'dry_run',
            'orders': orders,
            'message': 'Set dry_run=False to execute. Review orders first.',
        }

    if not all(o.get('securityId') for o in orders):
        return {'status': 'error',
                'reason': 'Missing security_id on one or more legs'}

    results = []
    try:
        client = dhan_fetch._get_client()
        for order in orders:
            resp = client.place_order(
                transaction_type=order['transactionType'],
                exchange_segment=order['exchangeSegment'],
                product_type=order['productType'],
                order_type=order['orderType'],
                validity=order['validity'],
                security_id=order['securityId'],
                quantity=order['quantity'],
                price=order['price'],
            )
            results.append({
                'leg': order,
                'response': resp,
                'order_id': resp.get('orderId') if resp else None,
                'status': resp.get('orderStatus', 'unknown') if resp else 'failed',
            })
            log.info(f"Order placed: {order['transactionType']} "
                     f"{order['quantity']}x @ ₹{order['price']:.2f} "
                     f"→ {results[-1]['status']}")
    except Exception as e:
        log.error(f'Order execution failed: {e}')
        return {
            'status': 'partial_error',
            'reason': str(e),
            'completed': results,
            'remaining': orders[len(results):],
        }

    return {
        'status': 'executed',
        'orders': results,
        'timestamp': datetime.datetime.now().isoformat(),
    }


def cancel_all(symbol='NIFTY'):
    """
    Kill switch: cancel all pending orders for a symbol.
    """
    try:
        client = dhan_fetch._get_client()
        orders = client.get_order_list()
        if not orders or orders.get('status') != 'success':
            return {'status': 'error', 'reason': 'Could not fetch order list'}

        sym_upper = symbol.upper()
        sid = dhan_fetch.INDEX_SID.get(sym_upper)
        cancelled = []
        for order in orders.get('data', []):
            if order.get('orderStatus') not in ('PENDING', 'TRANSIT'):
                continue
            if sid and str(order.get('securityId')) != str(sid):
                continue
            client.cancel_order(order['orderId'])
            cancelled.append(order['orderId'])
            log.info(f"Cancelled order {order['orderId']}")

        return {'status': 'ok', 'cancelled': cancelled}
    except Exception as e:
        return {'status': 'error', 'reason': str(e)}


def order_status(order_id):
    """Check status of a specific order."""
    try:
        client = dhan_fetch._get_client()
        return client.get_order_by_id(order_id)
    except Exception as e:
        return {'status': 'error', 'reason': str(e)}
