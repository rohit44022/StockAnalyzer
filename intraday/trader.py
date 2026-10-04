"""
Automated intraday trader — places and manages orders via Dhan API.

Start:  .venv/bin/python -m intraday.trader [--live] [--capital 50000]
Toggle: Web UI at /intraday (ON/OFF switch)

PAPER mode (default): simulates orders, no real money.
LIVE mode (--live):   real orders via Dhan. Requires funded account.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time as _time
from dataclasses import dataclass, field, asdict, fields
from datetime import datetime, time, timedelta
from typing import List, Optional, Dict, Any
from uuid import uuid4

import socket
# Force IPv4 — Dhan API rejects IPv6 with DH-905 "Invalid IP"
_orig_getaddrinfo = socket.getaddrinfo
def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = _ipv4_getaddrinfo

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from intraday.data import _load_dhan_context, _ticker_to_sid
from intraday.scanner import scan_intraday, IntradaySetup
from intraday import event_bus
from bb_squeeze.trade_calculator import calculate_trade, TradeCharges

log = logging.getLogger("intraday.trader")

def _atomic_json_write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


# --- Constants ---
MAX_POSITIONS = 3
MAX_DAILY_LOSS_PCT = 2.0
SCAN_INTERVAL_SEC = 5 * 60
MIN_CONFIDENCE = 75  # Brooks: only the best setups (Ch.26 scalper's equation)
ALLOWED_SETUPS = {
    ("SHORT_FIRST", "SECOND_ENTRY"),
    ("LONG_FIRST", "PULLBACK"),
    ("SHORT_FIRST", "PULLBACK"),
    ("LONG_FIRST", "SECOND_ENTRY"),
}
HARD_EXIT = time(15, 15)
NO_NEW_ENTRY = time(14, 45)
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
STATE_FILE = os.path.join(os.path.dirname(__file__), ".trader_state.json")
TRADE_LOG = os.path.join(os.path.dirname(__file__), ".trade_log.jsonl")
PID_FILE = os.path.join(os.path.dirname(__file__), ".trader_pid")
PAPER_CAPITAL = 100_000.0
PARTIAL_EXIT_PCT = 0.0    # 0 = full exit at target (no partial)
TRAIL_STOP_MULT = 0.5     # unused when PARTIAL_EXIT_PCT=0

_NIFTY500_CACHE_FILE = os.path.join(os.path.dirname(__file__), ".nifty500_cache.json")
# Nifty 50 fallback if NSE fetch fails
_NIFTY50_FALLBACK = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS", "SBIN.NS",
    "BHARTIARTL.NS", "ITC.NS", "LT.NS", "KOTAKBANK.NS", "HINDUNILVR.NS", "BAJFINANCE.NS",
    "AXISBANK.NS", "MARUTI.NS", "SUNPHARMA.NS", "TITAN.NS", "WIPRO.NS", "ULTRACEMCO.NS",
    "ADANIENT.NS", "HCLTECH.NS", "ASIANPAINT.NS", "BAJAJFINSV.NS", "ONGC.NS", "NTPC.NS",
    "POWERGRID.NS", "M&M.NS", "JSWSTEEL.NS", "TATASTEEL.NS", "TECHM.NS", "INDUSINDBK.NS",
    "HINDALCO.NS", "NESTLEIND.NS", "DRREDDY.NS", "DIVISLAB.NS", "CIPLA.NS", "APOLLOHOSP.NS",
    "HEROMOTOCO.NS", "EICHERMOT.NS", "BPCL.NS", "TATACONSUM.NS", "COALINDIA.NS", "GRASIM.NS",
    "BRITANNIA.NS", "SBILIFE.NS", "HDFCLIFE.NS", "BAJAJ-AUTO.NS", "SHRIRAMFIN.NS", "TRENT.NS",
    "BEL.NS", "ADANIPORTS.NS",
]


def _fetch_nifty500() -> List[str]:
    """Fetch Nifty 500 constituents from niftyindices.com CSV. Cached for 24h.
    Validates every ticker against Dhan scrip master to drop delisted/renamed stocks."""
    if os.path.exists(_NIFTY500_CACHE_FILE):
        try:
            with open(_NIFTY500_CACHE_FILE) as f:
                cache = json.load(f)
            if cache.get("date") == datetime.now().strftime("%Y-%m-%d") and cache.get("tickers"):
                return cache["tickers"]
        except Exception:
            pass
    try:
        import requests, csv, io
        resp = requests.get(
            "https://niftyindices.com/IndexConstituent/ind_nifty500list.csv",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=10,
        )
        resp.raise_for_status()
        reader = csv.DictReader(io.StringIO(resp.text))
        raw = [row["Symbol"] + ".NS" for row in reader
               if row.get("Symbol") and not row["Symbol"].startswith("DUMMY")]
        from intraday.data import validate_tickers
        tickers = validate_tickers(raw)
        if len(tickers) >= 400:
            log.info("Nifty 500: %d valid of %d fetched (dropped %d)",
                     len(tickers), len(raw), len(raw) - len(tickers))
            with open(_NIFTY500_CACHE_FILE, "w") as f:
                json.dump({"date": datetime.now().strftime("%Y-%m-%d"), "tickers": tickers}, f)
            return tickers
    except Exception as e:
        log.warning("Nifty 500 fetch failed: %s — using stale cache", e)
    if os.path.exists(_NIFTY500_CACHE_FILE):
        try:
            with open(_NIFTY500_CACHE_FILE) as f:
                cache = json.load(f)
            if cache.get("tickers"):
                log.info("Using stale Nifty 500 cache (%d stocks)", len(cache["tickers"]))
                return cache["tickers"]
        except Exception:
            pass
    return _NIFTY50_FALLBACK


DEFAULT_WATCHLIST = _fetch_nifty500()


@dataclass
class Position:
    ticker: str
    security_id: str
    direction: str          # LONG or SHORT
    entry_price: float
    quantity: int
    stop_loss: float
    target: float
    entry_order_id: str
    stop_order_id: str = ""
    entry_time: str = ""
    status: str = "PENDING"  # PENDING, OPEN, CLOSED
    exit_price: float = 0.0
    exit_time: str = ""
    exit_reason: str = ""
    pnl: float = 0.0
    setup_type: str = ""
    confidence: int = 0
    gap_type: str = ""
    orb_direction: str = ""
    time_quality: str = ""
    always_in: str = ""
    trend_phase: str = ""
    stop_pct: float = 0.0
    target_2: float = 0.0
    risk_reward: float = 0.0
    charges: Dict = field(default_factory=dict)
    net_pnl: float = 0.0
    trade_id: int = 0
    # Stale trade tracking
    original_stop: float = 0.0
    best_favorable: float = 0.0
    last_new_extreme_ts: float = 0.0  # monotonic timestamp
    # Trailing state
    trailing: bool = False
    partial_exit_price: float = 0.0
    partial_qty: int = 0
    trail_stop: float = 0.0
    trail_best: float = 0.0
    trail_dist: float = 0.0
    original_qty: int = 0


_POS_FIELDS = {f.name for f in fields(Position)}


class AutoTrader:
    def __init__(self, mode: str = "PAPER", watchlist: List[str] = None,
                 capital: float = 0.0):
        self.mode = mode
        self.watchlist = watchlist or DEFAULT_WATCHLIST
        self.ctx = None
        self.positions: List[Position] = []
        self.closed_today: List[Position] = []
        self.starting_capital = capital or PAPER_CAPITAL
        self.daily_pnl = 0.0
        self.circuit_breaker = False
        self.enabled = False
        self.last_scan = ""
        self._today = datetime.now().strftime("%Y-%m-%d")
        self.leverage = 1.0  # resets to 1.0 each new day
        self._ltp_cache: Dict[int, float] = {}
        self._ws_market = None
        self._ws_orders = None
        self._ws_threads: List[threading.Thread] = []
        self._kill_switch_active = False
        self._registered_ip: str = ""
        self._pos_lock = threading.Lock()

    # --- Dhan API helpers ---

    def init_dhan(self) -> bool:
        ctx, ok = _load_dhan_context()
        if not ok:
            log.error("Dhan credentials missing — check .env")
            return False
        self.ctx = ctx
        self._auto_register_ip()
        self._deactivate_kill_switch()
        return True

    def _auto_register_ip(self):
        """Check IP whitelist status and warn if mismatched.
        IP must be set on Dhan Web portal + token regenerated for orders to work."""
        try:
            info = self.ctx.dhan_http.get('/ip/getIP')
            data = info.get("data", {}) if isinstance(info, dict) else {}
            detected = data.get("detectedIP", "")
            self._registered_ip = detected
            primary = data.get("primaryIP", "NA")
            match = data.get("ipMatchStatus", "UNKNOWN")

            orders_allowed = data.get("ordersAllowed", False)
            if orders_allowed:
                log.info("IP %s orders allowed (primary=%s, status=%s)", detected, primary, match)
                self._ip_blocked = False
            else:
                log.warning("IP BLOCKED by Dhan: detected=%s primary=%s status=%s ordersAllowed=%s — "
                            "add IP on Dhan Web portal → Profile → Trading API, "
                            "then regenerate access token", detected, primary, match, orders_allowed)
                self._ip_blocked = True
        except Exception as e:
            log.warning("IP check failed (non-fatal): %s", e)

    def _deactivate_kill_switch(self):
        """Deactivate kill switch at start of day / on init."""
        if self.mode != "LIVE":
            return
        try:
            from dhanhq import TraderControl
            TraderControl(self.ctx).kill_switch("DEACTIVATE")
            self._kill_switch_active = False
            log.info("Kill switch deactivated")
        except Exception as e:
            log.warning("Kill switch deactivate failed: %s", e)

    def check_funds(self) -> float:
        if self.mode == "PAPER":
            used = sum(p.entry_price * (p.original_qty if p.trailing else p.quantity)
                       for p in self.positions if p.status == "OPEN")
            return max(0, self.starting_capital - used + self.daily_pnl) * self.leverage
        try:
            from dhanhq import Funds
            resp = Funds(self.ctx).get_fund_limits()
            if resp.get("status") == "success":
                return float(resp["data"].get("availabelBalance", 0)) * self.leverage
        except Exception as e:
            log.error("Fund check failed: %s", e)
        return 0.0

    def get_positions_from_broker(self) -> Optional[List[Dict]]:
        """Returns list of positions on success, None on API failure."""
        if self.mode == "PAPER":
            return []
        try:
            from dhanhq import Portfolio
            resp = Portfolio(self.ctx).get_positions()
            if resp.get("status") == "success":
                return resp.get("data", [])
            log.warning("Broker positions API non-success: %s", resp.get("remarks", resp))
        except Exception as e:
            log.error("Position fetch failed: %s", e)
        return None

    # --- WebSocket management ---

    def _start_websockets(self):
        """Start OrderUpdate + MarketFeed WebSocket threads (LIVE mode only)."""
        if self.mode != "LIVE" or not self.ctx:
            return
        # macOS Python 3.12 ships without root CA certs — patch ssl to use certifi
        try:
            import certifi, ssl
            _orig = ssl.create_default_context
            def _patched(*a, **kw):
                ctx = _orig(*a, **kw)
                ctx.load_verify_locations(certifi.where())
                return ctx
            ssl.create_default_context = _patched
        except Exception:
            pass
        # OrderUpdate WS
        t1 = threading.Thread(target=self._run_order_ws, daemon=True, name="order-ws")
        t1.start()
        self._ws_threads.append(t1)
        # MarketFeed WS
        t2 = threading.Thread(target=self._run_market_ws, daemon=True, name="market-ws")
        t2.start()
        self._ws_threads.append(t2)
        log.info("WebSocket threads started (OrderUpdate + MarketFeed)")

    def _close_websockets(self):
        """Close WS connections so Dhan releases the connection slots."""
        for ws, name in [(self._ws_market, "MarketFeed"), (self._ws_orders, "OrderUpdate")]:
            if ws is None:
                continue
            try:
                if hasattr(ws, 'close_connection'):
                    ws.close_connection()
                elif hasattr(ws, 'disconnect'):
                    ws.disconnect()
            except Exception:
                pass
        self._ws_market = None
        self._ws_orders = None

    def _run_order_ws(self):
        """OrderUpdate WS — only during market hours, with reconnect + backoff."""
        from dhanhq import OrderUpdate
        from datetime import time as dtime
        backoff = 5
        while True:
            now_t = datetime.now().time()
            if now_t < dtime(9, 0) or now_t > dtime(15, 30):
                self._ws_orders = None
                _time.sleep(60)
                continue
            t0 = _time.monotonic()
            try:
                ou = OrderUpdate(self.ctx)
                ou.on_update = self._on_order_update
                self._ws_orders = ou
                log.info("OrderUpdate WS connecting...")
                ou.connect_to_dhan_websocket_sync()
            except Exception as e:
                log.warning("OrderUpdate WS error, reconnecting in %ds: %s", backoff, e)
            self._ws_orders = None
            lived = _time.monotonic() - t0
            if lived > 30:
                backoff = 5
            else:
                backoff = min(backoff * 2, 300)
            _time.sleep(backoff)

    def _run_market_ws(self):
        """MarketFeed WS — only during market hours, with reconnect + backoff."""
        from dhanhq import MarketFeed
        from datetime import time as dtime
        def on_connect(ws=None):
            log.info("MarketFeed WS connected — subscribing open positions")
            for pos in list(self.positions):
                if pos.status == "OPEN":
                    self._subscribe_ltp(pos)
        backoff = 5
        while True:
            now_t = datetime.now().time()
            if now_t < dtime(9, 0) or now_t > dtime(15, 30):
                self._ws_market = None
                _time.sleep(60)
                continue
            t0 = _time.monotonic()
            try:
                mf = MarketFeed(self.ctx, instruments=[], version='v2',
                                on_connect=on_connect,
                                on_ticks=self._on_market_tick)
                self._ws_market = mf
                log.info("MarketFeed WS connecting...")
                mf.run()
            except Exception as e:
                log.warning("MarketFeed WS error, reconnecting in %ds: %s", backoff, e)
            self._ws_market = None
            lived = _time.monotonic() - t0
            if lived > 30:
                backoff = 5  # was a real connection, reset
            else:
                backoff = min(backoff * 2, 300)  # short-lived, back off
            _time.sleep(backoff)

    def _on_order_update(self, data):
        """Callback for order fills — instant SL/target detection."""
        try:
            info = data.get("Data", data) if isinstance(data, dict) else data
            order_id = str(info.get("orderNo", info.get("orderId", "")))
            status = info.get("orderStatus", info.get("status", ""))
            txn_type = info.get("transactionType", "")
            if not order_id or status not in ("TRADED", "CANCELLED", "REJECTED"):
                return
            for pos in list(self.positions):
                if pos.status != "OPEN":
                    continue
                if order_id == pos.stop_order_id and status == "TRADED":
                    fill = float(info.get("tradedPrice", info.get("price", pos.stop_loss)))
                    log.info("SL FILLED via WS: %s @ ₹%.2f", pos.ticker, fill)
                    self.close_position(pos, "STOP_HIT_WS", fill)
                elif order_id == pos.entry_order_id and status == "REJECTED":
                    log.warning("Entry REJECTED via WS: %s — %s",
                                pos.ticker, info.get("rejectionReason", ""))
                    pos.status = "CLOSED"
                    pos.exit_reason = "ENTRY_REJECTED"
                    event_bus.publish("order_rejected", {
                        "ticker": pos.ticker, "reason": info.get("rejectionReason", ""),
                    })
                    self.save_state()
        except Exception as e:
            log.warning("Order update callback error: %s", e)

    def _on_market_tick(self, tick):
        """Callback for LTP ticks — updates _ltp_cache."""
        try:
            sid = tick.get("security_id")
            ltp = float(tick.get("LTP", 0))
            if sid and ltp > 0:
                self._ltp_cache[sid] = ltp
        except Exception:
            pass

    def _subscribe_ltp(self, pos: 'Position'):
        """Subscribe a position's security_id to MarketFeed ticker mode."""
        if not self._ws_market:
            return
        try:
            from dhanhq import MarketFeed
            sid = int(pos.security_id)
            self._ws_market.subscribe_symbols(
                [(MarketFeed.NSE, sid, MarketFeed.Ticker)]
            )
        except Exception as e:
            log.warning("LTP subscribe failed for %s: %s", pos.ticker, e)

    def _unsubscribe_ltp(self, pos: 'Position'):
        """Unsubscribe a position's security_id from MarketFeed."""
        if not self._ws_market:
            return
        try:
            from dhanhq import MarketFeed
            sid = int(pos.security_id)
            self._ws_market.unsubscribe_symbols([(MarketFeed.NSE, sid)])
        except Exception as e:
            log.warning("LTP unsubscribe failed for %s: %s", pos.ticker, e)

    def _get_ltp(self, pos: 'Position') -> Optional[float]:
        """Get latest tick price from WS cache. Returns None if WS hasn't delivered yet."""
        if not pos.security_id:
            return None
        sid = int(pos.security_id)
        ltp = self._ltp_cache.get(sid)
        return ltp if ltp and ltp > 0 else None

    # --- Position sizing ---

    def calc_quantity(self, price: float, available: float) -> int:
        open_count = sum(1 for p in self.positions if p.status == "OPEN")
        slots = MAX_POSITIONS - open_count
        if slots <= 0 or price <= 0:
            return 0
        per_slot = available / slots
        return int(per_slot // price)

    # --- Order placement ---

    def _place_order(self, security_id: str, txn_type: str, qty: int,
                     order_type: str = "MARKET", price: float = 0,
                     trigger_price: float = 0, tag: str = None) -> Optional[str]:
        if self.mode == "PAPER":
            oid = f"PAPER-{uuid4().hex[:8]}"
            log.info("[PAPER] %s %d @ %s oid=%s", txn_type, qty, order_type, oid)
            return oid
        if getattr(self, '_ip_blocked', False):
            log.warning("Order blocked — IP mismatch, fix on Dhan portal and restart")
            return None
        try:
            log.info("Order attempt: sid=%s txn=%s qty=%d type=%s price=%.2f tag=%s",
                     security_id, txn_type, qty, order_type, price, tag)
            if order_type.upper() != "MARKET":
                price = self._tick_round(price)
                if trigger_price:
                    trigger_price = self._tick_round(trigger_price)
            payload = {
                "transactionType": txn_type.upper(),
                "exchangeSegment": "NSE_EQ",
                "productType": "INTRADAY",
                "orderType": order_type.upper(),
                "validity": "DAY",
                "securityId": str(security_id),
                "quantity": int(qty),
                "price": float(price),
                "triggerPrice": float(trigger_price),
            }
            if tag:
                payload["correlationId"] = tag
            resp = self.ctx.dhan_http.post('/orders', payload)
            log.info("Order response sid=%s: %s", security_id, resp)
            if resp.get("status") == "success":
                return resp.get("data", {}).get("orderId")
            log.error("Order failed: %s", resp.get("remarks", resp))
        except Exception as e:
            log.error("Order error: %s", e)
        return None

    def _verify_order(self, order_id: str, max_wait: float = 2.0) -> dict:
        """Check order status. Returns {status, tradedPrice, tradedQty} or None."""
        if self.mode == "PAPER" or not order_id:
            return {"status": "TRADED", "tradedPrice": 0, "tradedQty": 0}
        deadline = _time.monotonic() + max_wait
        while _time.monotonic() < deadline:
            try:
                resp = self.ctx.dhan_http.get(f'/orders/{order_id}')
                if resp.get("status") != "success":
                    break
                d = resp.get("data", {})
                st = (d.get("orderStatus") or "").upper()
                if st in ("TRADED", "PART_TRADED"):
                    return {"status": st,
                            "tradedPrice": float(d.get("averageTradedPrice", 0)),
                            "tradedQty": int(d.get("tradedQuantity", 0))}
                if st in ("REJECTED", "CANCELLED", "EXPIRED"):
                    return {"status": st, "tradedPrice": 0, "tradedQty": 0}
                _time.sleep(0.3)
            except Exception:
                break
        return None

    def _cancel_order(self, order_id: str) -> bool:
        if self.mode == "PAPER":
            log.info("[PAPER] Cancel %s", order_id)
            return True
        try:
            from dhanhq import Order
            resp = Order(self.ctx).cancel_order(order_id)
            return resp.get("status") == "success"
        except Exception as e:
            log.error("Cancel failed for %s: %s", order_id, e)
        return False

    # --- Trade execution ---

    def open_position(self, setup: IntradaySetup, available: float) -> Optional[Position]:
        if any(p.ticker == setup.ticker and p.status in ("PENDING", "OPEN")
               for p in self.positions):
            return None

        qty = self.calc_quantity(setup.entry_price, available)
        if qty <= 0:
            log.info("Skip %s — qty=0 (price=%.2f, avail=%.2f)",
                     setup.ticker, setup.entry_price, available)
            return None

        sid = _ticker_to_sid(setup.ticker)
        if sid is None:
            log.error("No security_id for %s", setup.ticker)
            return None

        is_short = setup.direction == "SHORT_FIRST"
        entry_txn = "SELL" if is_short else "BUY"

        entry_oid = self._place_order(
            str(sid), entry_txn, qty, tag="INTRA-ENTRY")
        if not entry_oid:
            return None

        # Verify order actually filled before creating position
        if self.mode == "LIVE":
            vf = self._verify_order(entry_oid)
            if vf is None:
                log.warning("Entry order %s verify TIMED OUT for %s — cancelling to avoid phantom position",
                            entry_oid, setup.ticker)
                self._cancel_order(entry_oid)
                return None
            if vf["status"] in ("REJECTED", "CANCELLED", "EXPIRED"):
                log.warning("Entry order %s was %s for %s — skipping position",
                            entry_oid, vf["status"], setup.ticker)
                return None
            fill_price = float(vf["tradedPrice"])
            fill_qty = int(vf["tradedQty"])
            if fill_price > 0:
                setup = setup._replace(entry_price=fill_price)
            if fill_qty > 0:
                qty = fill_qty

        pos = Position(
            ticker=setup.ticker,
            security_id=str(sid),
            direction="SHORT" if is_short else "LONG",
            entry_price=setup.entry_price,
            quantity=qty,
            stop_loss=setup.stop_loss,
            original_stop=setup.stop_loss,
            last_new_extreme_ts=_time.monotonic(),
            target=setup.target_1,
            entry_order_id=entry_oid,
            entry_time=datetime.now().strftime("%H:%M:%S"),
            status="OPEN",
            setup_type=getattr(setup, "setup_type", ""),
            confidence=getattr(setup, "confidence", 0),
            gap_type=getattr(setup, "gap_type", ""),
            orb_direction=getattr(setup, "opening_range_breakout", ""),
            time_quality=getattr(setup, "time_quality", ""),
            always_in=getattr(setup, "always_in", ""),
            trend_phase=getattr(setup, "trend_phase", ""),
            stop_pct=getattr(setup, "stop_pct", 0.0),
            target_2=getattr(setup, "target_2", 0.0),
            risk_reward=getattr(setup, "risk_reward", 0.0),
        )

        stop_txn = "BUY" if is_short else "SELL"
        stop_oid = self._place_order(
            str(sid), stop_txn, qty,
            order_type="STOP_LOSS_MARKET",
            trigger_price=setup.stop_loss,
            tag="INTRA-SL",
        )
        pos.stop_order_id = stop_oid or ""

        self._subscribe_ltp(pos)
        self.positions.append(pos)
        self._log_trade("OPEN", pos)
        cost = qty * setup.entry_price
        log.info("OPENED %s %s %d @ ₹%.2f (₹%.0f) stop=₹%.2f target=₹%.2f",
                 pos.direction, setup.ticker, qty, setup.entry_price,
                 cost, setup.stop_loss, setup.target_1)
        event_bus.publish("position_open", {
            "ticker": setup.ticker, "direction": pos.direction,
            "entry": setup.entry_price, "stop": setup.stop_loss,
            "target": setup.target_1,
        })
        return pos

    @staticmethod
    def _tick_round(price: float, tick: float = 0.05) -> float:
        """Round price to nearest NSE tick size (₹0.05 for equity)."""
        return round(round(price / tick) * tick, 2)

    def close_position(self, pos: Position, reason: str,
                       exit_price: float = 0.0) -> bool:
        with self._pos_lock:
            if pos.status != "OPEN":
                return False
            pos.status = "CLOSING"

        is_short = pos.direction == "SHORT"
        exit_txn = "BUY" if is_short else "SELL"

        if pos.stop_order_id:
            self._cancel_order(pos.stop_order_id)
        # BROKER_CLOSED = position already gone from broker; don't place exit (would create opposite position)
        if reason != "BROKER_CLOSED" and pos.security_id:
            self._place_order(pos.security_id, exit_txn, pos.quantity, tag="INTRA-EXIT")

        if exit_price <= 0:
            ltp = self._get_ltp(pos)
            exit_price = ltp if ltp and ltp > 0 else pos.entry_price

        sign = -1 if is_short else 1
        trail_pnl = sign * (exit_price - pos.entry_price) * pos.quantity

        if pos.trailing and pos.partial_qty > 0:
            partial_pnl = sign * (pos.partial_exit_price - pos.entry_price) * pos.partial_qty
            pos.pnl = round(partial_pnl + trail_pnl, 2)
        else:
            pos.pnl = round(trail_pnl, 2)

        # Compute Dhan intraday charges
        stock_name = pos.ticker.replace(".NS", "")
        try:
            if pos.trailing and pos.partial_qty > 0:
                charges_total = 0.0
                charges_dict = {}
                for ep, eq in [(pos.partial_exit_price, pos.partial_qty),
                               (exit_price, pos.quantity)]:
                    bp = ep if is_short else pos.entry_price
                    sp = pos.entry_price if is_short else ep
                    p = calculate_trade(
                        stock=stock_name, platform="dhan",
                        trade_type="intraday", exchange="NSE",
                        quantity=eq, buy_price=bp, sell_price=sp,
                        buy_date=self._today, sell_date=self._today)
                    charges_total += p.charges.total
                    d = p.charges.to_dict()
                    charges_dict = {k: round(charges_dict.get(k, 0) + d.get(k, 0), 2)
                                    for k in set(charges_dict) | set(d)}
                pos.charges = charges_dict
                pos.net_pnl = round(pos.pnl - charges_total, 2)
            else:
                buy_p = exit_price if is_short else pos.entry_price
                sell_p = pos.entry_price if is_short else exit_price
                pnl_obj = calculate_trade(
                    stock=stock_name, platform="dhan",
                    trade_type="intraday", exchange="NSE",
                    quantity=pos.quantity, buy_price=buy_p, sell_price=sell_p,
                    buy_date=self._today, sell_date=self._today)
                pos.charges = pnl_obj.charges.to_dict()
                pos.net_pnl = round(pos.pnl - pnl_obj.charges.total, 2)
        except Exception as e:
            log.warning("Charge calc failed: %s", e)
            pos.charges = {}
            pos.net_pnl = pos.pnl

        # Restore original qty and compute weighted avg exit for trailing trades
        if pos.trailing and pos.original_qty:
            trail_qty = pos.quantity
            pos.exit_price = round(
                (pos.partial_exit_price * pos.partial_qty +
                 exit_price * trail_qty) / pos.original_qty, 2)
            pos.quantity = pos.original_qty
        else:
            pos.exit_price = exit_price

        self._unsubscribe_ltp(pos)
        pos.status = "CLOSED"
        pos.exit_time = datetime.now().strftime("%H:%M:%S")
        pos.exit_reason = reason
        self.daily_pnl += pos.net_pnl
        self.closed_today.append(pos)
        self._log_trade("CLOSE", pos)

        self._log_to_trades_db(pos)

        log.info("CLOSED %s %s @ ₹%.2f reason=%s gross=₹%.2f charges=₹%.2f net=₹%.2f",
                 pos.ticker, pos.direction, pos.exit_price, reason,
                 pos.pnl, pos.charges.get("total", 0), pos.net_pnl)
        event_bus.publish("position_close", {
            "ticker": pos.ticker, "direction": pos.direction,
            "pnl": pos.net_pnl, "reason": reason,
        })
        self.save_state()
        return True

    def _partial_exit(self, pos: Position, target_price: float):
        """Exit 50% at target, trail remaining with tighter stop."""
        partial_qty = max(1, int(pos.quantity * 0.5))
        if partial_qty <= 0:
            self.close_position(pos, "TARGET_HIT", target_price)
            return

        trail_qty = pos.quantity - partial_qty
        stop_dist = abs(pos.entry_price - pos.stop_loss)

        if stop_dist < pos.entry_price * 0.001:
            self.close_position(pos, "TARGET_HIT", target_price)
            return

        if pos.stop_order_id:
            self._cancel_order(pos.stop_order_id)
            pos.stop_order_id = ""

        exit_txn = "BUY" if pos.direction == "SHORT" else "SELL"
        oid = self._place_order(pos.security_id, exit_txn, partial_qty, tag="INTRA-PARTIAL")

        if not oid and self.mode == "LIVE":
            log.warning("Partial exit order FAILED for %s — falling back to full close", pos.ticker)
            self.close_position(pos, "TARGET_HIT", target_price)
            return

        if oid and self.mode == "LIVE":
            vf = self._verify_order(oid, max_wait=2.0)
            if vf and vf["status"] in ("REJECTED", "CANCELLED", "EXPIRED"):
                log.warning("Partial exit REJECTED for %s — falling back to full close", pos.ticker)
                self.close_position(pos, "TARGET_HIT", target_price)
                return
            if vf and vf["tradedPrice"] > 0:
                target_price = vf["tradedPrice"]

        pos.original_qty = pos.quantity
        pos.partial_exit_price = target_price
        pos.partial_qty = partial_qty
        pos.quantity = trail_qty
        pos.trailing = True
        pos.trail_dist = stop_dist * TRAIL_STOP_MULT
        pos.trail_best = target_price
        pos.trail_stop = pos.entry_price   # breakeven
        pos.stop_loss = pos.entry_price

        self._update_sl_order(pos)
        self._log_trade("PARTIAL_EXIT", pos)
        log.info("PARTIAL %s %s: exited %d/%d @ ₹%.2f, trailing %d stop=₹%.2f",
                 pos.direction, pos.ticker, partial_qty, pos.original_qty,
                 target_price, trail_qty, pos.entry_price)
        event_bus.publish("partial_exit", {
            "ticker": pos.ticker, "price": target_price, "qty": partial_qty,
        })
        self.save_state()

    def _update_sl_order(self, pos: Position):
        """Cancel and re-place SL-M order at current trail_stop."""
        if pos.stop_order_id:
            cancelled = self._cancel_order(pos.stop_order_id)
            if not cancelled and self.mode == "LIVE":
                log.warning("SL cancel failed for %s order %s — skipping update to avoid duplicate",
                            pos.ticker, pos.stop_order_id)
                return
            pos.stop_order_id = ""
        sl_txn = "BUY" if pos.direction == "SHORT" else "SELL"
        oid = self._place_order(
            pos.security_id, sl_txn, pos.quantity,
            order_type="STOP_LOSS_MARKET",
            trigger_price=self._tick_round(pos.trail_stop),
            tag="INTRA-TRAIL-SL",
        )
        if oid:
            pos.stop_order_id = oid

    def _log_to_trades_db(self, pos: Position):
        """Log closed position to the trades database for /trades page."""
        try:
            from bb_squeeze.trade_db import add_trade
            is_short = pos.direction == "SHORT"
            buy_p = pos.exit_price if is_short else pos.entry_price
            sell_p = pos.entry_price if is_short else pos.exit_price
            data = {
                "stock": pos.ticker.replace(".NS", ""),
                "quantity": pos.quantity,
                "buy_price": buy_p,
                "sell_price": sell_p,
                "buy_date": self._today,
                "sell_date": self._today,
                "platform": "dhan",
                "trade_type": "intraday",
                "exchange": "NSE",
                "notes": (f"AUTO | {pos.direction} | {pos.setup_type} | "
                          f"conf={pos.confidence} | {pos.exit_reason} | "
                          f"net=₹{pos.net_pnl:.2f} | {self.mode}"),
            }
            tid = add_trade(data, user_id="auto_trader")
            pos.trade_id = tid
            log.info("Logged trade #%d to /trades DB", tid)
        except Exception as e:
            log.warning("Failed to log trade to DB: %s", e)

    def exit_all(self, reason: str = "HARD_EXIT"):
        open_pos = [p for p in self.positions if p.status == "OPEN"]
        for pos in open_pos:
            self.close_position(pos, reason)
        if open_pos:
            log.info("Exited %d positions — %s. Daily P&L: ₹%.2f",
                     len(open_pos), reason, self.daily_pnl)

    # --- Monitoring ---

    def _monitor_ltp(self):
        """Fast 1-second monitoring using WS LTP cache only. No API calls."""
        for pos in list(self.positions):
            if pos.status != "OPEN":
                continue
            ltp = self._get_ltp(pos)
            if not ltp:
                continue
            try:
                if pos.trailing:
                    if pos.direction == "LONG":
                        if ltp > pos.trail_best:
                            pos.trail_best = ltp
                            new_ts = max(pos.trail_stop, pos.trail_best - pos.trail_dist)
                            if new_ts > pos.trail_stop:
                                pos.trail_stop = round(new_ts, 2)
                                pos.stop_loss = pos.trail_stop
                                self._update_sl_order(pos)
                        if ltp <= pos.trail_stop:
                            self.close_position(pos, "TRAIL_STOP", pos.trail_stop)
                    else:
                        if ltp < pos.trail_best:
                            pos.trail_best = ltp
                            new_ts = min(pos.trail_stop, pos.trail_best + pos.trail_dist)
                            if new_ts < pos.trail_stop:
                                pos.trail_stop = round(new_ts, 2)
                                pos.stop_loss = pos.trail_stop
                                self._update_sl_order(pos)
                        if ltp >= pos.trail_stop:
                            self.close_position(pos, "TRAIL_STOP", pos.trail_stop)
                else:
                    has_broker_sl = bool(pos.stop_order_id)
                    check_stop = self.mode == "PAPER" or not has_broker_sl
                    now_mono = _time.monotonic()
                    fav = (ltp - pos.entry_price) if pos.direction == "LONG" else (pos.entry_price - ltp)
                    if fav > pos.best_favorable:
                        pos.best_favorable = fav
                        pos.last_new_extreme_ts = now_mono
                    stale_secs = now_mono - pos.last_new_extreme_ts if pos.last_new_extreme_ts > 0 else 0
                    current_pnl = fav
                    if pos.direction == "LONG":
                        if pos.stop_loss > 0 and ltp <= pos.stop_loss and check_stop:
                            self.close_position(pos, "STOP_HIT", pos.stop_loss)
                        elif pos.target > 0 and ltp >= pos.target:
                            self.close_position(pos, "TARGET_HIT", pos.target)
                        elif stale_secs >= 5400 and current_pnl > 0:
                            log.info("Stale exit %s — no new high for %.0f min, locking profit", pos.ticker, stale_secs/60)
                            self.close_position(pos, "STALE_EXIT", ltp)
                    else:
                        if pos.stop_loss > 0 and ltp >= pos.stop_loss and check_stop:
                            self.close_position(pos, "STOP_HIT", pos.stop_loss)
                        elif pos.target > 0 and ltp <= pos.target:
                            self.close_position(pos, "TARGET_HIT", pos.target)
                        elif stale_secs >= 5400 and current_pnl > 0:
                            log.info("Stale exit %s — no new low for %.0f min, locking profit", pos.ticker, stale_secs/60)
                            self.close_position(pos, "STALE_EXIT", ltp)
            except Exception as e:
                log.error("Monitor error for %s: %s", pos.ticker, e)

    def monitor_positions(self):
        """Full position check — candle fallback + broker sync (runs less often)."""
        if self.mode == "LIVE":
            self._sync_with_broker()

        for pos in self.positions:
            if pos.status != "OPEN":
                continue
            try:
                # Try real-time LTP first (zero API calls), fall back to candles
                ltp = self._get_ltp(pos)
                if ltp:
                    session_high = max(ltp, pos.entry_price)
                    session_low = min(ltp, pos.entry_price)
                else:
                    from intraday.data import fetch_today_candles
                    df = fetch_today_candles(pos.ticker)
                    if df is None or df.empty:
                        continue
                    session_high = float(df["High"].max())
                    session_low = float(df["Low"].min())

                if pos.trailing:
                    if pos.direction == "LONG":
                        if session_high > pos.trail_best:
                            pos.trail_best = session_high
                            new_ts = max(pos.trail_stop, pos.trail_best - pos.trail_dist)
                            if new_ts > pos.trail_stop:
                                pos.trail_stop = round(new_ts, 2)
                                pos.stop_loss = pos.trail_stop
                                self._update_sl_order(pos)
                        if session_low <= pos.trail_stop:
                            self.close_position(pos, "TRAIL_STOP", pos.trail_stop)
                    else:
                        if session_low < pos.trail_best:
                            pos.trail_best = session_low
                            new_ts = min(pos.trail_stop, pos.trail_best + pos.trail_dist)
                            if new_ts < pos.trail_stop:
                                pos.trail_stop = round(new_ts, 2)
                                pos.stop_loss = pos.trail_stop
                                self._update_sl_order(pos)
                        if session_high >= pos.trail_stop:
                            self.close_position(pos, "TRAIL_STOP", pos.trail_stop)
                else:
                    has_broker_sl = bool(pos.stop_order_id)
                    check_stop = self.mode == "PAPER" or not has_broker_sl
                    now_mono = _time.monotonic()
                    cur_price = ltp if ltp else float(df["Close"].iloc[-1]) if df is not None and not df.empty else None
                    if cur_price:
                        fav = (cur_price - pos.entry_price) if pos.direction == "LONG" else (pos.entry_price - cur_price)
                        if fav > pos.best_favorable:
                            pos.best_favorable = fav
                            pos.last_new_extreme_ts = now_mono
                    stale_secs = now_mono - pos.last_new_extreme_ts if pos.last_new_extreme_ts > 0 else 0
                    current_pnl = (cur_price - pos.entry_price) if cur_price and pos.direction == "LONG" else (pos.entry_price - cur_price) if cur_price else 0
                    if pos.direction == "LONG":
                        if pos.stop_loss > 0 and session_low <= pos.stop_loss and check_stop:
                            self.close_position(pos, "STOP_HIT", pos.stop_loss)
                        elif pos.target > 0 and session_high >= pos.target:
                            self.close_position(pos, "TARGET_HIT", pos.target)
                        elif stale_secs >= 5400 and current_pnl > 0:
                            log.info("Stale exit %s (candle path) — no new high for %.0f min", pos.ticker, stale_secs/60)
                            self.close_position(pos, "STALE_EXIT", cur_price)
                    else:
                        if pos.stop_loss > 0 and session_high >= pos.stop_loss and check_stop:
                            self.close_position(pos, "STOP_HIT", pos.stop_loss)
                        elif pos.target > 0 and session_low <= pos.target:
                            self.close_position(pos, "TARGET_HIT", pos.target)
                        elif stale_secs >= 5400 and current_pnl > 0:
                            log.info("Stale exit %s (candle path) — no new low for %.0f min", pos.ticker, stale_secs/60)
                            self.close_position(pos, "STALE_EXIT", cur_price)
            except Exception:
                pass

    def _sync_with_broker(self):
        """In LIVE mode, sync position status from broker — ghost cleanup + orphan recovery."""
        broker_pos = self.get_positions_from_broker()
        if broker_pos is None:
            return
        broker_tickers = {p.get("tradingSymbol", ""): p for p in broker_pos}
        open_count = sum(1 for p in self.positions if p.status == "OPEN")
        our_syms = {p.ticker.replace(".NS", "") for p in self.positions if p.status == "OPEN"}

        # Ghost cleanup: we track it but broker doesn't have it
        # Only skip cleanup if broker returned NO intraday positions but we have open ones
        # (could be a stale API response)
        broker_intraday = {s: p for s, p in broker_tickers.items()
                           if p.get("productType") == "INTRADAY" and int(p.get("netQty", 0)) != 0}
        if not broker_intraday and open_count > 0:
            log.warning("Broker returned 0 intraday positions but we have %d open — skipping ghost cleanup", open_count)
        else:
            for pos in self.positions:
                if pos.status != "OPEN":
                    continue
                sym = pos.ticker.replace(".NS", "")
                bp = broker_tickers.get(sym)
                if bp is None or int(bp.get("netQty", 0)) == 0:
                    # Double-check: verify via order status before closing
                    if pos.entry_order_id and pos.entry_order_id != "RECOVERED":
                        vf = self._verify_order(pos.entry_order_id, max_wait=1.0)
                        if vf and vf["status"] in ("TRADED", "PART_TRADED"):
                            log.warning("Ghost %s order shows TRADED but not in broker positions — keeping for 1 more cycle", sym)
                            continue
                    last_price = self._fetch_actual_exit_price(pos)
                    log.info("Ghost cleanup: %s not on broker (sym=%s, exit=₹%.2f, broker_syms=%s)",
                             pos.ticker, sym, last_price, list(broker_tickers.keys())[:8])
                    self.close_position(pos, "BROKER_CLOSED", last_price)

        # Orphan recovery: broker has intraday position we don't track
        for sym, bp in broker_tickers.items():
            net_qty = int(bp.get("netQty", 0))
            if net_qty == 0 or sym in our_syms:
                continue
            if bp.get("productType", "") != "INTRADAY":
                continue
            ticker = f"{sym}.NS"
            entry = float(bp.get("averagePrice", bp.get("buyAvg", 0)))
            ltp = float(bp.get("lastPrice", entry))
            direction = "LONG" if net_qty > 0 else "SHORT"
            sid = _ticker_to_sid(ticker)
            sid_str = str(sid) if sid else ""

            # Default stop 1.5%, target 3.0% (2:1 R:R)
            if direction == "LONG":
                stop = round(entry * 0.985, 2)
                target = round(entry * 1.030, 2)
            else:
                stop = round(entry * 1.015, 2)
                target = round(entry * 0.970, 2)

            pos = Position(
                ticker=ticker,
                security_id=sid_str,
                direction=direction,
                entry_price=entry,
                quantity=abs(net_qty),
                stop_loss=stop,
                target=target,
                entry_order_id="RECOVERED",
                entry_time=datetime.now().strftime("%H:%M:%S"),
                status="OPEN",
                setup_type="ORPHAN_RECOVERED",
                last_new_extreme_ts=_time.monotonic(),
                stop_pct=1.5,
                risk_reward=2.0,
            )

            # Place SL order on broker for protection
            if sid_str and self.mode == "LIVE":
                sl_txn = "BUY" if direction == "SHORT" else "SELL"
                sl_oid = self._place_order(
                    sid_str, sl_txn, abs(net_qty),
                    order_type="STOP_LOSS_MARKET",
                    trigger_price=stop, tag="INTRA-SL-RECOVERED")
                pos.stop_order_id = sl_oid or ""

            self._subscribe_ltp(pos)
            self.positions.append(pos)
            log.warning("RECOVERED orphan: %s %s %d @ ₹%.2f stop=₹%.2f target=₹%.2f (LTP ₹%.2f)",
                        direction, ticker, abs(net_qty), entry, stop, target, ltp)

    def _fetch_actual_exit_price(self, pos: Position) -> float:
        """Fetch real exit price from Dhan order history when broker closed the position."""
        if self.mode == "PAPER":
            return pos.entry_price
        try:
            resp = self.ctx.dhan_http.get('/orders')
            if resp.get("status") == "success":
                sym = pos.ticker.replace(".NS", "")
                for order in reversed(resp.get("data", [])):
                    if order.get("tradingSymbol") != sym:
                        continue
                    if order.get("orderStatus") not in ("TRADED", "PART_TRADED"):
                        continue
                    txn = order.get("transactionType", "")
                    is_exit = (pos.direction == "LONG" and txn == "SELL") or \
                              (pos.direction == "SHORT" and txn == "BUY")
                    if is_exit:
                        price = float(order.get("averageTradedPrice", 0))
                        if price > 0:
                            log.info("Found real exit price for %s: ₹%.2f (order %s)",
                                     pos.ticker, price, order.get("orderId"))
                            return price
        except Exception as e:
            log.warning("Failed to fetch exit price for %s: %s", pos.ticker, e)
        ltp = self._get_ltp(pos)
        if ltp and ltp > 0:
            return ltp
        return pos.entry_price

    def check_circuit_breaker(self) -> bool:
        if self.starting_capital <= 0:
            return False
        loss_limit = self.starting_capital * MAX_DAILY_LOSS_PCT / 100
        if self.daily_pnl < -loss_limit:
            self.circuit_breaker = True
            log.warning("CIRCUIT BREAKER: P&L ₹%.2f exceeds -%.1f%% of ₹%.0f",
                        self.daily_pnl, MAX_DAILY_LOSS_PCT, self.starting_capital)
            self.exit_all("CIRCUIT_BREAKER")
            self._activate_kill_switch()
            return True
        return False

    def _activate_kill_switch(self):
        """Activate broker-side kill switch — prevents any new orders."""
        if self.mode != "LIVE" or not self.ctx:
            return
        try:
            from dhanhq import TraderControl
            TraderControl(self.ctx).kill_switch("ACTIVATE")
            self._kill_switch_active = True
            log.warning("KILL SWITCH ACTIVATED — broker blocks all new orders")
        except Exception as e:
            log.error("Kill switch activate failed: %s", e)

    # --- Scan & trade cycle ---

    def run_scan_cycle(self):
        now_t = datetime.now().time()
        if now_t < time(9, 30) or now_t > NO_NEW_ENTRY:
            return

        open_count = sum(1 for p in self.positions if p.status == "OPEN")
        if open_count >= MAX_POSITIONS:
            log.info("All %d slots filled, skipping scan", MAX_POSITIONS)
            return

        log.info("Scanning %d stocks...", len(self.watchlist))
        result = scan_intraday(watchlist=self.watchlist, top_n=5)
        self.last_scan = datetime.now().strftime("%H:%M:%S")
        self.last_scan_feed = result.get("scan_feed", [])
        self.last_scan_stats = {
            "scanned": result.get("scanned", 0),
            "total_setups": result.get("total_setups", 0),
            "errors": result.get("errors", 0),
            "time": self.last_scan,
        }

        all_setups = result.get("short_first_raw", []) + result.get("long_first_raw", [])
        if not all_setups:
            log.info("No setups found")
            return

        available = self.check_funds()
        log.info("Available funds: ₹%.2f", available)

        for setup in all_setups:
            if open_count >= MAX_POSITIONS:
                break
            if setup.confidence < MIN_CONFIDENCE:
                log.info("Skip %s — confidence %d < %d", setup.ticker, setup.confidence, MIN_CONFIDENCE)
                continue
            combo = (setup.direction, setup.setup_type)  # e.g. ("SHORT_FIRST", "PULLBACK")
            if combo not in ALLOWED_SETUPS:
                log.info("Skip %s — combo %s not in allowed list", setup.ticker, combo)
                continue
            pos = self.open_position(setup, available)
            if pos:
                open_count += 1
                available -= pos.quantity * pos.entry_price

    # --- State persistence ---

    def save_state(self):
        state = {
            "enabled": self.enabled,
            "mode": self.mode,
            "starting_capital": self.starting_capital,
            "daily_pnl": round(self.daily_pnl, 2),
            "circuit_breaker": self.circuit_breaker,
            "last_scan": self.last_scan,
            "date": self._today,
            "positions": [asdict(p) for p in self.positions],
            "closed_today": [asdict(p) for p in self.closed_today],
            "watchlist": self.watchlist,
            "leverage": self.leverage,
            "scan_feed": getattr(self, "last_scan_feed", []),
            "scan_stats": getattr(self, "last_scan_stats", {}),
            "ws_market": self._ws_market is not None,
            "ws_orders": self._ws_orders is not None,
            "kill_switch": self._kill_switch_active,
            "registered_ip": self._registered_ip,
            "ltp": {str(k): v for k, v in self._ltp_cache.items()},
        }
        _atomic_json_write(STATE_FILE, state)

    def load_state(self):
        if not os.path.exists(STATE_FILE):
            return
        try:
            with open(STATE_FILE) as f:
                state = json.load(f)
            if state.get("date") != self._today:
                log.info("New day — resetting state (leverage→1x)")
                state["leverage"] = 1.0
                state["date"] = self._today
                state["daily_pnl"] = 0
                state["circuit_breaker"] = False
                state["kill_switch"] = False
                state["positions"] = []
                state["closed_today"] = []
                with open(STATE_FILE, "w") as f:
                    json.dump(state, f, indent=2)
                return
            self.enabled = state.get("enabled", False)
            self.daily_pnl = state.get("daily_pnl", 0.0)
            self.circuit_breaker = state.get("circuit_breaker", False)
            self.last_scan = state.get("last_scan", "")
            self.leverage = state.get("leverage", 1.0)
            self.starting_capital = state.get("starting_capital", self.starting_capital)
            for pd_ in state.get("positions", []):
                pos = Position(**{k: v for k, v in pd_.items() if k in _POS_FIELDS})
                if pos.status == "OPEN":
                    pos.last_new_extreme_ts = _time.monotonic()
                self.positions.append(pos)
            for pd_ in state.get("closed_today", []):
                self.closed_today.append(Position(**{k: v for k, v in pd_.items() if k in _POS_FIELDS}))
            log.info("Loaded state: %d open, %d closed, P&L ₹%.2f",
                     sum(1 for p in self.positions if p.status == "OPEN"),
                     len(self.closed_today), self.daily_pnl)
        except Exception as e:
            log.warning("State load failed: %s", e)

    def _log_trade(self, action: str, pos: Position):
        entry = {
            "action": action,
            "time": datetime.now().isoformat(),
            "mode": self.mode,
            **asdict(pos),
        }
        try:
            with open(TRADE_LOG, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

    # --- Main loop ---

    def _start_caffeinate(self):
        """Prevent macOS idle sleep while daemon runs."""
        try:
            self._caffeine = subprocess.Popen(
                ["caffeinate", "-i", "-w", str(os.getpid())],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            log.info("caffeinate started (pid=%d) — Mac won't idle-sleep", self._caffeine.pid)
        except FileNotFoundError:
            self._caffeine = None
            log.warning("caffeinate not found — Mac may sleep during trading")

    def _stop_caffeinate(self):
        if getattr(self, "_caffeine", None) and self._caffeine.poll() is None:
            self._caffeine.terminate()
            self._caffeine = None

    def run(self):
        log.info("AutoTrader started — mode=%s capital=₹%.0f watchlist=%d stocks",
                 self.mode, self.starting_capital, len(self.watchlist))

        if self.mode == "LIVE" and not self.init_dhan():
            log.error("Cannot start LIVE mode without Dhan credentials")
            return

        # Kill ALL previous trader daemons so stale WS connections close
        my_pid = os.getpid()
        try:
            import re
            out = subprocess.check_output(
                ["pgrep", "-f", "intraday.trader"], text=True, stderr=subprocess.DEVNULL
            )
            for line in out.strip().splitlines():
                pid = int(line.strip())
                if pid != my_pid:
                    try:
                        os.kill(pid, signal.SIGTERM)
                        log.info("Killed stale trader pid=%d", pid)
                    except ProcessLookupError:
                        pass
            _time.sleep(2)
        except (subprocess.CalledProcessError, ValueError):
            pass

        # Write PID file so web UI can detect running daemon
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))

        # Graceful shutdown on SIGTERM — save state before exit
        self._shutdown = False
        def _handle_term(signum, frame):
            log.info("SIGTERM received — saving state and shutting down")
            self._shutdown = True
            self._close_websockets()
            self.save_state()
            sys.exit(0)
        signal.signal(signal.SIGTERM, _handle_term)

        self._start_caffeinate()
        self._last_cycle = _time.monotonic()

        self.load_state()

        if self.mode == "LIVE":
            capital = self.check_funds()
            if capital > 0:
                self.starting_capital = capital
                log.info("Live capital: ₹%.2f", capital)

        self._start_websockets()
        _time.sleep(2)  # let WS threads connect
        self.save_state()

        try:
            self._run_loop()
        finally:
            self._stop_caffeinate()

    def _run_loop(self):
        BROKER_SYNC_SEC = 30
        next_scan = _time.monotonic()
        next_broker_sync = _time.monotonic() + BROKER_SYNC_SEC
        next_truncate = _time.monotonic() + 300

        while True:
            now = datetime.now()
            now_t = now.time()

            # Gap detection (adjusted for 1s cycle)
            elapsed = _time.monotonic() - self._last_cycle
            if elapsed > 60 and any(
                p.status == "OPEN" for p in self.positions
            ):
                log.warning("SLEEP GAP detected: %.1f min — checking positions", elapsed / 60)
                self.monitor_positions()
                if now_t >= HARD_EXIT:
                    self.exit_all("HARD_EXIT_AFTER_SLEEP_GAP")
                    self.save_state()
                self._last_cycle = _time.monotonic()
                continue
            self._last_cycle = _time.monotonic()

            if now.weekday() >= 5:
                self.save_state()
                _time.sleep(60)
                continue

            if now.strftime("%Y-%m-%d") != self._today:
                log.info("New trading day — resetting")
                self._today = now.strftime("%Y-%m-%d")
                self.positions = []
                self.closed_today = []
                self.daily_pnl = 0.0
                self.circuit_breaker = False
                self.leverage = 1.0
                self._ltp_cache.clear()
                self._deactivate_kill_switch()
                event_bus.clear()
                if self.mode == "LIVE":
                    cap = self.check_funds()
                    if cap > 0:
                        self.starting_capital = cap

            self._read_toggle()

            if now_t < MARKET_OPEN:
                self.save_state()
                _time.sleep(5)
                continue

            if now_t >= HARD_EXIT:
                self.exit_all("HARD_EXIT_3:15PM")
                self.enabled = False
                self.save_state()
                log.info("Market closing — sleeping until tomorrow")
                _time.sleep(max(60, (24 - now.hour) * 3600))
                continue

            if not self.enabled:
                self.save_state()
                _time.sleep(5)
                continue

            if self.circuit_breaker:
                self.save_state()
                _time.sleep(10)
                continue

            # Fast: LTP monitoring (every 1s)
            self._monitor_ltp()

            # Medium: broker position sync (every 30s)
            if self.mode == "LIVE" and _time.monotonic() >= next_broker_sync:
                self._sync_with_broker()
                next_broker_sync = _time.monotonic() + BROKER_SYNC_SEC

            if self.check_circuit_breaker():
                self.save_state()
                continue

            # Slow: scan cycle (every 5 min)
            if _time.monotonic() >= next_scan:
                self.run_scan_cycle()
                next_scan = _time.monotonic() + SCAN_INTERVAL_SEC
                log.info("Next scan in %d min. Open: %d, P&L: ₹%.2f",
                         SCAN_INTERVAL_SEC // 60,
                         sum(1 for p in self.positions if p.status == "OPEN"),
                         self.daily_pnl)

            self.save_state()

            if _time.monotonic() >= next_truncate:
                event_bus.truncate()
                next_truncate = _time.monotonic() + 300

            _time.sleep(1)

    def _read_toggle(self):
        """Re-read flags from state file (web UI may have changed them)."""
        if not os.path.exists(STATE_FILE):
            return
        try:
            with open(STATE_FILE) as f:
                state = json.load(f)
            self.enabled = state.get("enabled", False)
            self.leverage = state.get("leverage", 1.0)
            if state.get("circuit_breaker") and not self.circuit_breaker:
                self.circuit_breaker = True
                log.warning("Circuit breaker activated via UI")
            if state.get("kill_switch") and not self._kill_switch_active:
                self._kill_switch_active = True
                self.circuit_breaker = True
                log.warning("Kill switch activated via UI — stopping all trading")
        except Exception:
            pass


# --- Web API helpers (called from intraday_routes.py) ---

def get_trader_state() -> Dict[str, Any]:
    if not os.path.exists(STATE_FILE):
        return {
            "enabled": False, "mode": "PAPER", "starting_capital": 0,
            "daily_pnl": 0, "circuit_breaker": False, "last_scan": "",
            "positions": [], "closed_today": [], "date": "",
        }
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"enabled": False, "error": "state file corrupt"}


def set_trader_toggle(enabled: bool) -> Dict[str, Any]:
    state = get_trader_state()
    state["enabled"] = enabled
    state["date"] = datetime.now().strftime("%Y-%m-%d")
    _atomic_json_write(STATE_FILE, state)
    return state


def set_leverage(multiplier: float) -> Dict[str, Any]:
    multiplier = max(1.0, min(multiplier, 5.0))
    state = get_trader_state()
    state["leverage"] = multiplier
    _atomic_json_write(STATE_FILE, state)
    return state


def get_available_funds() -> float:
    try:
        ctx, ok = _load_dhan_context()
        if not ok:
            return 0.0
        from dhanhq import Funds
        resp = Funds(ctx).get_fund_limits()
        if resp.get("status") == "success":
            return float(resp["data"].get("availabelBalance", 0))
    except Exception:
        pass
    return 0.0


def exit_all_positions() -> int:
    """Exit all open positions via Dhan API. Called from Flask, not the daemon."""
    state = get_trader_state()
    open_pos = [p for p in state.get("positions", []) if p.get("status") == "OPEN"]
    if not open_pos:
        return 0

    ctx, ok = _load_dhan_context()
    if not ok:
        log.warning("exit_all_positions: no Dhan credentials")
        return 0

    closed = 0
    now = datetime.now().strftime("%H:%M:%S")
    for p in open_pos:
        sid = p.get("security_id", "")
        direction = p.get("direction", "LONG")
        qty = p.get("quantity", 0)
        exit_txn = "SELL" if direction == "LONG" else "BUY"
        if not sid or qty <= 0:
            continue
        try:
            payload = {
                "transactionType": exit_txn,
                "exchangeSegment": "NSE_EQ",
                "productType": "INTRADAY",
                "orderType": "MARKET",
                "validity": "DAY",
                "securityId": str(sid),
                "quantity": int(qty),
                "price": 0.0,
                "triggerPrice": 0.0,
                "correlationId": "EXIT-ALL",
            }
            resp = ctx.dhan_http.post('/orders', payload)
            if resp.get("status") == "success":
                p["status"] = "CLOSED"
                p["exit_reason"] = "HARD_EXIT"
                p["exit_time"] = now
                closed += 1
                log.info("exit_all: closed %s %s qty=%d", exit_txn, p.get("ticker", sid), qty)
            else:
                log.error("exit_all: failed %s — %s", p.get("ticker", sid), resp.get("remarks", resp))
        except Exception as e:
            log.error("exit_all: error %s — %s", p.get("ticker", sid), e)

    if closed:
        closed_today = state.get("closed_today", [])
        closed_today.extend([p for p in open_pos if p.get("status") == "CLOSED"])
        state["positions"] = [p for p in state["positions"] if p.get("status") != "CLOSED"]
        state["closed_today"] = closed_today
        _atomic_json_write(STATE_FILE, state)
    return closed


def get_trade_log(n: int = 20) -> List[Dict]:
    if not os.path.exists(TRADE_LOG):
        return []
    try:
        lines = open(TRADE_LOG).readlines()
        return [json.loads(l) for l in lines[-n:]]
    except Exception:
        return []


# --- CLI entry point ---

def main():
    parser = argparse.ArgumentParser(description="Intraday auto-trader")
    parser.add_argument("--live", action="store_true",
                        help="LIVE mode — places real orders (default: PAPER)")
    parser.add_argument("--capital", type=float, default=0,
                        help="Starting capital for PAPER mode (default: ₹1,00,000)")
    parser.add_argument("--watchlist", nargs="*",
                        help="Tickers to scan (default: Nifty top 20)")
    parser.add_argument("--enable", action="store_true",
                        help="Start with trading enabled (default: OFF)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    mode = "LIVE" if args.live else "PAPER"
    wl = [t if t.endswith(".NS") else t + ".NS"
          for t in args.watchlist] if args.watchlist else None
    capital = args.capital or (0 if args.live else PAPER_CAPITAL)

    trader = AutoTrader(mode=mode, watchlist=wl, capital=capital)
    if args.enable:
        trader.enabled = True

    if mode == "LIVE":
        log.warning("=" * 50)
        log.warning("  LIVE MODE — REAL ORDERS WILL BE PLACED")
        log.warning("  Toggle ON via web UI or --enable to start")
        log.warning("=" * 50)

    try:
        trader.run()
    finally:
        try:
            os.unlink(PID_FILE)
        except OSError:
            pass


def get_ws_status() -> Dict:
    """Return WebSocket + kill switch status from state file (daemon is a separate process)."""
    state = get_trader_state()
    return {
        "market_ws": state.get("ws_market", False),
        "order_ws": state.get("ws_orders", False),
        "kill_switch": state.get("kill_switch", False),
        "registered_ip": state.get("registered_ip", ""),
    }


def get_trade_book() -> list:
    """Fetch today's broker-confirmed trade book via Statement API."""
    try:
        ctx, ok = _load_dhan_context()
        if not ok:
            return []
        from dhanhq import Statement
        resp = Statement(ctx).get_trade_book()
        if isinstance(resp, dict) and resp.get("status") == "success":
            return resp.get("data", [])
    except Exception:
        pass
    return []


def get_trade_history(from_date: str, to_date: str, page: int = 0) -> list:
    """Fetch broker trade history for a date range."""
    try:
        ctx, ok = _load_dhan_context()
        if not ok:
            return []
        from dhanhq import Statement
        resp = Statement(ctx).get_trade_history(from_date, to_date, page)
        if isinstance(resp, dict) and resp.get("status") == "success":
            return resp.get("data", [])
    except Exception:
        pass
    return []


def activate_kill_switch() -> bool:
    """Manual kill switch activation from UI — also disables daemon trading."""
    try:
        ctx, ok = _load_dhan_context()
        if not ok:
            return False
        from dhanhq import TraderControl
        TraderControl(ctx).kill_switch("ACTIVATE")
        # Tell the daemon to stop trading by setting circuit_breaker + kill_switch in state
        state = get_trader_state()
        state["circuit_breaker"] = True
        state["kill_switch"] = True
        state["enabled"] = False
        _atomic_json_write(STATE_FILE, state)
        return True
    except Exception:
        return False


def is_daemon_running() -> bool:
    """Check if trader daemon process is alive via PID file."""
    if not os.path.exists(PID_FILE):
        return False
    try:
        pid = int(open(PID_FILE).read().strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        try:
            os.unlink(PID_FILE)
        except OSError:
            pass
        return False


if __name__ == "__main__":
    main()
