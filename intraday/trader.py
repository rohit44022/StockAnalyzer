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
import sys
import time as _time
from dataclasses import dataclass, field, asdict
from datetime import datetime, time, timedelta
from typing import List, Optional, Dict, Any
from uuid import uuid4

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from intraday.data import _load_dhan_context, _ticker_to_sid
from intraday.scanner import scan_intraday, IntradaySetup
from bb_squeeze.trade_calculator import calculate_trade, TradeCharges

log = logging.getLogger("intraday.trader")

# --- Constants ---
MAX_POSITIONS = 3
MAX_DAILY_LOSS_PCT = 2.0
SCAN_INTERVAL_SEC = 15 * 60
HARD_EXIT = time(15, 15)
NO_NEW_ENTRY = time(14, 45)
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
STATE_FILE = os.path.join(os.path.dirname(__file__), ".trader_state.json")
TRADE_LOG = os.path.join(os.path.dirname(__file__), ".trade_log.jsonl")
PID_FILE = os.path.join(os.path.dirname(__file__), ".trader_pid")
PAPER_CAPITAL = 100_000.0
TRAIL_STOP_MULT = 0.5     # trail distance = 50% of original stop distance

DEFAULT_WATCHLIST = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS",
    "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "LT.NS", "KOTAKBANK.NS",
    "HINDUNILVR.NS", "BAJFINANCE.NS", "AXISBANK.NS", "MARUTI.NS",
    "SUNPHARMA.NS", "TITAN.NS", "WIPRO.NS", "ULTRACEMCO.NS",
    "TATAMOTORS.NS", "ADANIENT.NS",
]


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
    # Trailing state
    trailing: bool = False
    partial_exit_price: float = 0.0
    partial_qty: int = 0
    trail_stop: float = 0.0
    trail_best: float = 0.0
    trail_dist: float = 0.0
    original_qty: int = 0


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

    # --- Dhan API helpers ---

    def init_dhan(self) -> bool:
        ctx, ok = _load_dhan_context()
        if not ok:
            log.error("Dhan credentials missing — check .env")
            return False
        self.ctx = ctx
        return True

    def check_funds(self) -> float:
        if self.mode == "PAPER":
            used = sum(p.entry_price * (p.original_qty if p.trailing else p.quantity)
                       for p in self.positions if p.status == "OPEN")
            return max(0, self.starting_capital - used + self.daily_pnl)
        try:
            from dhanhq import Funds
            resp = Funds(self.ctx).get_fund_limits()
            if resp.get("status") == "success":
                return float(resp["data"].get("availabelBalance", 0))
        except Exception as e:
            log.error("Fund check failed: %s", e)
        return 0.0

    def get_positions_from_broker(self) -> List[Dict]:
        if self.mode == "PAPER":
            return []
        try:
            from dhanhq import Portfolio
            resp = Portfolio(self.ctx).get_positions()
            if resp.get("status") == "success":
                return resp.get("data", [])
        except Exception as e:
            log.error("Position fetch failed: %s", e)
        return []

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
        try:
            from dhanhq import Order
            resp = Order(self.ctx).place_order(
                security_id=str(security_id),
                exchange_segment="NSE_EQ",
                transaction_type=txn_type,
                quantity=qty,
                order_type=order_type,
                product_type="INTRADAY",
                price=price,
                trigger_price=trigger_price,
                tag=tag,
            )
            log.info("Order response: %s", resp)
            if resp.get("status") == "success":
                return resp.get("data", {}).get("orderId")
            log.error("Order failed: %s", resp.get("remarks", resp))
        except Exception as e:
            log.error("Order error: %s", e)
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
            str(sid), entry_txn, qty, tag="INTRA-ENTRY"
        )
        if not entry_oid:
            return None

        pos = Position(
            ticker=setup.ticker,
            security_id=str(sid),
            direction="SHORT" if is_short else "LONG",
            entry_price=setup.entry_price,
            quantity=qty,
            stop_loss=setup.stop_loss,
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

        # Place protective stop
        stop_txn = "BUY" if is_short else "SELL"
        stop_oid = self._place_order(
            str(sid), stop_txn, qty,
            order_type="STOP_LOSS_MARKET",
            trigger_price=setup.stop_loss,
            tag="INTRA-SL",
        )
        pos.stop_order_id = stop_oid or ""

        self.positions.append(pos)
        self._log_trade("OPEN", pos)
        cost = qty * setup.entry_price
        log.info("OPENED %s %s %d @ ₹%.2f (₹%.0f) stop=₹%.2f target=₹%.2f",
                 pos.direction, setup.ticker, qty, setup.entry_price,
                 cost, setup.stop_loss, setup.target_1)
        return pos

    def close_position(self, pos: Position, reason: str,
                       exit_price: float = 0.0) -> bool:
        if pos.status != "OPEN":
            return False

        is_short = pos.direction == "SHORT"
        exit_txn = "BUY" if is_short else "SELL"

        if pos.stop_order_id:
            self._cancel_order(pos.stop_order_id)

        self._place_order(
            pos.security_id, exit_txn, pos.quantity, tag="INTRA-EXIT"
        )

        if exit_price <= 0:
            exit_price = pos.entry_price

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
            trigger_price=round(pos.trail_stop, 2),
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

    def monitor_positions(self):
        """Check stops/targets and manage trailing positions (both modes)."""
        if self.mode == "LIVE":
            self._sync_with_broker()

        for pos in self.positions:
            if pos.status != "OPEN":
                continue
            try:
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
                    if pos.direction == "LONG":
                        if session_low <= pos.stop_loss and self.mode == "PAPER":
                            self.close_position(pos, "STOP_HIT", pos.stop_loss)
                        elif session_high >= pos.target:
                            self._partial_exit(pos, pos.target)
                    else:
                        if session_high >= pos.stop_loss and self.mode == "PAPER":
                            self.close_position(pos, "STOP_HIT", pos.stop_loss)
                        elif session_low <= pos.target:
                            self._partial_exit(pos, pos.target)
            except Exception:
                pass

    def _sync_with_broker(self):
        """In LIVE mode, sync position status from broker."""
        broker_pos = self.get_positions_from_broker()
        broker_tickers = {p.get("tradingSymbol", ""): p for p in broker_pos}

        for pos in self.positions:
            if pos.status != "OPEN":
                continue
            sym = pos.ticker.replace(".NS", "")
            bp = broker_tickers.get(sym)
            if bp is None or int(bp.get("netQty", 0)) == 0:
                last_price = float(bp.get("lastPrice", pos.entry_price)) if bp else pos.entry_price
                self.close_position(pos, "BROKER_CLOSED", last_price)

    def check_circuit_breaker(self) -> bool:
        if self.starting_capital <= 0:
            return False
        loss_limit = self.starting_capital * MAX_DAILY_LOSS_PCT / 100
        if self.daily_pnl < -loss_limit:
            self.circuit_breaker = True
            log.warning("CIRCUIT BREAKER: P&L ₹%.2f exceeds -%.1f%% of ₹%.0f",
                        self.daily_pnl, MAX_DAILY_LOSS_PCT, self.starting_capital)
            self.exit_all("CIRCUIT_BREAKER")
            return True
        return False

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

        all_setups = result.get("short_first", []) + result.get("long_first", [])
        if not all_setups:
            log.info("No setups found")
            return

        available = self.check_funds()
        log.info("Available funds: ₹%.2f", available)

        for setup in all_setups:
            if open_count >= MAX_POSITIONS:
                break
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
        }
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)

    def load_state(self):
        if not os.path.exists(STATE_FILE):
            return
        try:
            with open(STATE_FILE) as f:
                state = json.load(f)
            if state.get("date") != self._today:
                log.info("New day — resetting state")
                return
            self.enabled = state.get("enabled", False)
            self.daily_pnl = state.get("daily_pnl", 0.0)
            self.circuit_breaker = state.get("circuit_breaker", False)
            self.last_scan = state.get("last_scan", "")
            self.starting_capital = state.get("starting_capital", self.starting_capital)
            for pd_ in state.get("positions", []):
                self.positions.append(Position(**pd_))
            for pd_ in state.get("closed_today", []):
                self.closed_today.append(Position(**pd_))
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

    def run(self):
        log.info("AutoTrader started — mode=%s capital=₹%.0f watchlist=%d stocks",
                 self.mode, self.starting_capital, len(self.watchlist))

        if self.mode == "LIVE" and not self.init_dhan():
            log.error("Cannot start LIVE mode without Dhan credentials")
            return

        # Write PID file so web UI can detect running daemon
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))

        self.load_state()

        if self.mode == "LIVE":
            capital = self.check_funds()
            if capital > 0:
                self.starting_capital = capital
                log.info("Live capital: ₹%.2f", capital)

        while True:
            now = datetime.now()
            now_t = now.time()

            if now.weekday() >= 5:
                log.info("Weekend — sleeping 1h")
                _time.sleep(3600)
                continue

            if now.strftime("%Y-%m-%d") != self._today:
                log.info("New trading day — resetting")
                self._today = now.strftime("%Y-%m-%d")
                self.positions = []
                self.closed_today = []
                self.daily_pnl = 0.0
                self.circuit_breaker = False
                if self.mode == "LIVE":
                    cap = self.check_funds()
                    if cap > 0:
                        self.starting_capital = cap

            # Re-read toggle from state file (web UI writes it)
            self._read_toggle()

            if now_t < MARKET_OPEN:
                _time.sleep(60)
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
                _time.sleep(60)
                continue

            if self.circuit_breaker:
                log.info("Circuit breaker active — no new trades")
                self.save_state()
                _time.sleep(300)
                continue

            self.monitor_positions()
            if self.check_circuit_breaker():
                self.save_state()
                continue

            self.run_scan_cycle()
            self.save_state()

            log.info("Next scan in %d min. Open: %d, P&L: ₹%.2f",
                     SCAN_INTERVAL_SEC // 60,
                     sum(1 for p in self.positions if p.status == "OPEN"),
                     self.daily_pnl)
            _time.sleep(SCAN_INTERVAL_SEC)

    def _read_toggle(self):
        """Re-read enabled flag from state file (web UI may have changed it)."""
        if not os.path.exists(STATE_FILE):
            return
        try:
            with open(STATE_FILE) as f:
                state = json.load(f)
            self.enabled = state.get("enabled", False)
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
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
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
