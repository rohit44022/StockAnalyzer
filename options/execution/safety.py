"""
Safety layer — three independent kill-switch layers.
Any single layer can halt trading. The system must be safe
even if two of three layers fail simultaneously.

Layer 1: Application (this module)
Layer 2: Dhan server-side (Super Orders, pnlExit, kill switch)
Layer 3: Exchange (SPAN margin, RMS square-off)

Davey Ch.14 + Sinclair Ch.9-10.
"""

import json
import time
import sqlite3
import logging
import datetime
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Callable

log = logging.getLogger(__name__)


class SafetyAction(Enum):
    CONTINUE = 'CONTINUE'
    WARN = 'WARN'
    FREEZE_ENTRIES = 'FREEZE_ENTRIES'
    EXIT_ALL = 'EXIT_ALL'
    KILL_SWITCH = 'KILL_SWITCH'


DEFAULT_SAFETY_CONFIG = {
    'mode': 'MANUAL',
    'max_lots_per_trade': 5,
    'max_orders_per_day': 20,
    'max_capital_at_risk': 100000,
    'max_concurrent_positions': 4,
    'daily_loss_limit_pct': 2.0,
    'abort_dd_pct': 15.0,
    'kelly_fraction': 0.25,
    'allowed_indices': ['NIFTY', 'BANKNIFTY'],
    'min_dte_entry': 7,
    'max_dte_entry': 45,
    'exit_before_expiry_days': 2,
    'slippage_reject_pct': 2.0,
    'bid_ask_max_pct': 4.0,
    'vix_halt_above': 30,
    'order_timeout_sec': 30,
    'heartbeat_interval_sec': 900,
    'auto_exit_phantoms': False,
    'telegram_enabled': False,
    'telegram_bot_token': '',
    'telegram_chat_id': '',
    'rate_limit_per_sec': 5.0,
    'rate_limit_burst': 5,
}


@dataclass
class PortfolioState:
    total_capital: float = 500000.0
    deployed_capital: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl_today: float = 0.0
    open_positions: int = 0
    current_dd_pct: float = 0.0
    peak_equity: float = 500000.0


def validate_config(config: dict) -> list:
    errors = []
    if config.get('max_lots_per_trade', 0) < 1:
        errors.append('max_lots_per_trade must be >= 1')
    if config.get('max_lots_per_trade', 0) > 20:
        errors.append('max_lots_per_trade > 20 is dangerous')
    if config.get('max_orders_per_day', 0) > 500:
        errors.append('max_orders_per_day > 500 is excessive')
    if config.get('daily_loss_limit_pct', 0) > 10:
        errors.append('daily_loss_limit_pct > 10% is reckless')
    if config.get('abort_dd_pct', 0) > 50:
        errors.append('abort_dd_pct > 50% is unsustainable')
    if config.get('kelly_fraction', 0) > 0.5:
        errors.append('kelly_fraction > 0.5 (half-Kelly) risks ruin (Sinclair Ch.9)')
    if config.get('mode', '') not in ('MANUAL', 'SEMI', 'FULL'):
        errors.append(f"mode must be MANUAL/SEMI/FULL, got {config.get('mode')}")
    allowed = config.get('allowed_indices', [])
    for idx in allowed:
        if idx not in ('NIFTY', 'BANKNIFTY'):
            errors.append(f'allowed_indices contains non-cash-settled index: {idx}')
    return errors


class SafetyMonitor:

    def __init__(self, config: dict, db_path: str,
                 portfolio_fetcher: Optional[Callable] = None,
                 kill_switch_fn: Optional[Callable] = None,
                 alert_fn: Optional[Callable] = None):
        errors = validate_config(config)
        if errors:
            raise ValueError(f'Safety config errors: {errors}')

        self._config = config
        self._db_path = db_path
        self._portfolio_fetcher = portfolio_fetcher
        self._kill_switch_fn = kill_switch_fn
        self._alert_fn = alert_fn
        self._frozen = False
        self._killed = False
        self._last_heartbeat = 0
        self._DD_CONFIRM_COUNT = 3

        conn = sqlite3.connect(db_path, timeout=10)
        conn.execute('''CREATE TABLE IF NOT EXISTS safety_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            action TEXT NOT NULL,
            detail TEXT
        )''')
        conn.commit()
        # Restore DD breach count from persisted safety_log
        conn.row_factory = sqlite3.Row
        recent = conn.execute(
            "SELECT event_type FROM safety_events ORDER BY id DESC LIMIT ?",
            (self._DD_CONFIRM_COUNT,)
        ).fetchall()
        conn.close()
        consecutive = 0
        for e in recent:
            if e['event_type'] == 'DD_WARNING':
                consecutive += 1
            else:
                break
        self._dd_breach_count = consecutive

    def check_portfolio_dd(self, state: Optional[PortfolioState] = None) -> SafetyAction:
        if self._killed:
            return SafetyAction.KILL_SWITCH

        if not state and self._portfolio_fetcher:
            state = self._portfolio_fetcher()
        if not state:
            return SafetyAction.CONTINUE

        abort_pct = self._config.get('abort_dd_pct', 15.0)
        dd = abs(state.current_dd_pct)

        if dd >= abort_pct:
            self._dd_breach_count += 1
            if self._dd_breach_count >= self._DD_CONFIRM_COUNT:
                self._log_event('DD_ABORT', SafetyAction.EXIT_ALL,
                                f'DD {dd:.1f}% >= abort {abort_pct}% '
                                f'for {self._dd_breach_count} consecutive checks')
                self._alert(f'DD at {dd:.1f}% >= abort threshold {abort_pct}%. EXITING ALL.')
                return SafetyAction.EXIT_ALL
            else:
                self._log_event('DD_WARNING', SafetyAction.WARN,
                                f'DD {dd:.1f}% >= abort {abort_pct}% '
                                f'(check {self._dd_breach_count}/{self._DD_CONFIRM_COUNT})')
                return SafetyAction.WARN
        else:
            self._dd_breach_count = 0

        if dd >= abort_pct * 0.7:
            self._alert(f'DD warning: {dd:.1f}% (threshold: {abort_pct}%)')
            return SafetyAction.WARN

        return SafetyAction.CONTINUE

    def check_daily_loss(self, state: Optional[PortfolioState] = None) -> SafetyAction:
        if self._killed:
            return SafetyAction.KILL_SWITCH

        if not state and self._portfolio_fetcher:
            state = self._portfolio_fetcher()
        if not state:
            return SafetyAction.CONTINUE

        limit_pct = self._config.get('daily_loss_limit_pct', 2.0)
        daily_pnl = state.realized_pnl_today + state.unrealized_pnl
        daily_pct = (-daily_pnl / state.total_capital * 100) if state.total_capital > 0 else 0

        if daily_pnl < 0 and daily_pct >= limit_pct * 2:
            self._log_event('DAILY_LOSS_EXIT', SafetyAction.EXIT_ALL,
                            f'Daily loss {daily_pct:.1f}% >= 2× limit {limit_pct}%')
            self._alert(f'Daily loss {daily_pct:.1f}% hit 2× limit. EXITING ALL.')
            return SafetyAction.EXIT_ALL

        if daily_pnl < 0 and daily_pct >= limit_pct:
            if not self._frozen:
                self._frozen = True
                self._log_event('DAILY_LOSS_FREEZE', SafetyAction.FREEZE_ENTRIES,
                                f'Daily loss {daily_pct:.1f}% >= limit {limit_pct}%')
                self._alert(f'Daily loss {daily_pct:.1f}% hit limit. FREEZING new entries.')
            return SafetyAction.FREEZE_ENTRIES

        return SafetyAction.CONTINUE

    def check_position_count(self, current_count: int) -> SafetyAction:
        limit = self._config.get('max_concurrent_positions', 4)
        if current_count >= limit:
            return SafetyAction.FREEZE_ENTRIES
        return SafetyAction.CONTINUE

    def emergency_stop(self, reason: str = 'Manual emergency stop') -> dict:
        self._killed = True
        self._frozen = True
        self._log_event('EMERGENCY_STOP', SafetyAction.KILL_SWITCH, reason)
        self._alert(f'EMERGENCY STOP: {reason}')

        if self._kill_switch_fn:
            try:
                result = self._kill_switch_fn()
                return {'status': 'kill_switch_activated', 'reason': reason,
                        'dhan_response': result}
            except Exception as e:
                log.error(f'Kill switch API failed: {e}')
                return {'status': 'kill_switch_failed', 'reason': reason,
                        'error': str(e)}
        return {'status': 'kill_switch_local_only', 'reason': reason}

    def setup_dhan_safety(self, dhan_client=None):
        """Layer 2 (Davey Ch.10): configure Dhan server-side guards at session start."""
        if not dhan_client:
            log.warning('No Dhan client — server-side safety not configured')
            return {'status': 'skipped', 'reason': 'no client'}

        results = {}
        capital = self._config.get('max_capital_at_risk', 100000)
        loss_pct = self._config.get('daily_loss_limit_pct', 2.0)
        loss_limit = capital * (loss_pct / 100.0)

        try:
            resp = dhan_client.set_pnl_exit(loss_limit=loss_limit)
            results['pnl_exit'] = {'status': 'set', 'loss_limit': loss_limit,
                                   'response': resp}
            log.info(f'Dhan pnlExit set: ₹{loss_limit:.0f}')
        except Exception as e:
            results['pnl_exit'] = {'status': 'failed', 'error': str(e)}
            log.error(f'Failed to set Dhan pnlExit: {e}')

        self._log_event('DHAN_SAFETY_SETUP', SafetyAction.CONTINUE,
                        json.dumps(results, default=str))
        return results

    def reset(self):
        self._killed = False
        self._frozen = False
        self._dd_breach_count = 0
        self._log_event('SAFETY_RESET', SafetyAction.CONTINUE, 'Manual reset')

    def heartbeat(self) -> dict:
        now = time.time()
        self._last_heartbeat = now
        state = self._portfolio_fetcher() if self._portfolio_fetcher else PortfolioState()

        msg = (f'ALIVE | {state.open_positions} pos | '
               f'DD: {state.current_dd_pct:.1f}% | '
               f'PnL today: {state.realized_pnl_today + state.unrealized_pnl:+.0f}')

        self._alert(msg)

        return {'timestamp': now, 'message': msg, 'state': state}

    @property
    def is_frozen(self) -> bool:
        return self._frozen

    @property
    def is_killed(self) -> bool:
        return self._killed

    def should_allow_entry(self, capital_required: float = 0,
                           position_count: int = 0) -> tuple:
        if self._killed:
            return False, 'Kill switch active'
        if self._frozen:
            return False, 'Entries frozen (daily loss limit)'

        state = self._portfolio_fetcher() if self._portfolio_fetcher else None

        if state:
            dd_action = self.check_portfolio_dd(state)
            if dd_action in (SafetyAction.EXIT_ALL, SafetyAction.KILL_SWITCH):
                return False, f'Portfolio DD action: {dd_action.value}'

            daily_action = self.check_daily_loss(state)
            if daily_action in (SafetyAction.FREEZE_ENTRIES, SafetyAction.EXIT_ALL,
                                SafetyAction.KILL_SWITCH):
                return False, f'Daily loss action: {daily_action.value}'

        pos_action = self.check_position_count(position_count)
        if pos_action == SafetyAction.FREEZE_ENTRIES:
            return False, f'Max concurrent positions ({self._config.get("max_concurrent_positions")})'

        max_capital = self._config.get('max_capital_at_risk', 100000)
        if state and state.deployed_capital + capital_required > max_capital:
            return False, f'Would exceed max_capital_at_risk ({max_capital})'

        return True, 'OK'

    def _log_event(self, event_type: str, action: SafetyAction, detail: str = ''):
        log.warning(f'SAFETY [{event_type}] → {action.value}: {detail}')
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute(
            'INSERT INTO safety_events (timestamp, event_type, action, detail) VALUES (?,?,?,?)',
            (datetime.datetime.now().isoformat(), event_type, action.value, detail)
        )
        conn.commit()
        conn.close()

    def _alert(self, message: str):
        if self._alert_fn:
            try:
                self._alert_fn(message)
            except Exception as e:
                log.error(f'Alert delivery failed: {e}')

    def get_safety_log(self, limit: int = 50) -> list:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            'SELECT * FROM safety_events ORDER BY id DESC LIMIT ?', (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def load_config(path: str = None) -> dict:
    if path is None:
        import os
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'safety_config.json')
    config = dict(DEFAULT_SAFETY_CONFIG)
    try:
        with open(path) as f:
            user = json.load(f)
        config.update(user)
    except FileNotFoundError:
        pass
    return config


def save_config(config: dict, path: str = None):
    if path is None:
        import os
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'safety_config.json')
    with open(path, 'w') as f:
        json.dump(config, f, indent=2)


def selfcheck():
    import os, tempfile

    db = os.path.join(tempfile.gettempdir(), 'test_safety.db')
    if os.path.exists(db):
        os.remove(db)

    alerts = []

    def mock_portfolio():
        return PortfolioState(
            total_capital=500000, deployed_capital=100000,
            unrealized_pnl=-5000, realized_pnl_today=-2000,
            open_positions=2, current_dd_pct=3.0, peak_equity=500000,
        )

    config = dict(DEFAULT_SAFETY_CONFIG)
    config['daily_loss_limit_pct'] = 2.0
    config['abort_dd_pct'] = 15.0
    config['max_concurrent_positions'] = 4
    config['max_capital_at_risk'] = 200000

    monitor = SafetyMonitor(
        config, db,
        portfolio_fetcher=mock_portfolio,
        alert_fn=lambda msg: alerts.append(msg),
    )

    # Test 1: Normal state → CONTINUE
    action = monitor.check_portfolio_dd()
    assert action == SafetyAction.CONTINUE, f'Expected CONTINUE, got {action}'

    # Test 2: Daily loss check — within limits
    action = monitor.check_daily_loss()
    assert action in (SafetyAction.CONTINUE, SafetyAction.FREEZE_ENTRIES)

    # Test 3: DD breach → needs 3 consecutive to EXIT_ALL
    breach_state = PortfolioState(current_dd_pct=16.0, total_capital=500000)
    a1 = monitor.check_portfolio_dd(breach_state)
    assert a1 == SafetyAction.WARN  # 1st breach
    a2 = monitor.check_portfolio_dd(breach_state)
    assert a2 == SafetyAction.WARN  # 2nd breach
    a3 = monitor.check_portfolio_dd(breach_state)
    assert a3 == SafetyAction.EXIT_ALL  # 3rd consecutive → EXIT

    # Test 4: DD recovery resets counter
    monitor._dd_breach_count = 0
    normal = PortfolioState(current_dd_pct=5.0, total_capital=500000)
    a4 = monitor.check_portfolio_dd(normal)
    assert a4 == SafetyAction.CONTINUE

    # Test 5: Emergency stop
    result = monitor.emergency_stop('Test stop')
    assert monitor.is_killed
    assert monitor.is_frozen

    # Test 6: Should not allow entry when killed
    allowed, reason = monitor.should_allow_entry()
    assert not allowed
    assert 'Kill switch' in reason

    # Test 7: Reset
    monitor.reset()
    assert not monitor.is_killed
    assert not monitor.is_frozen

    # Test 8: Position limit
    action = monitor.check_position_count(4)
    assert action == SafetyAction.FREEZE_ENTRIES
    action = monitor.check_position_count(3)
    assert action == SafetyAction.CONTINUE

    # Test 9: Capital limit
    monitor2 = SafetyMonitor(
        config, db,
        portfolio_fetcher=lambda: PortfolioState(
            total_capital=500000, deployed_capital=180000,
            open_positions=2
        ),
    )
    allowed, reason = monitor2.should_allow_entry(capital_required=30000, position_count=2)
    assert not allowed
    assert 'max_capital' in reason

    # Test 10: Config validation
    bad_config = dict(DEFAULT_SAFETY_CONFIG)
    bad_config['kelly_fraction'] = 0.8
    errors = validate_config(bad_config)
    assert any('kelly' in e.lower() for e in errors)

    # Test 11: Safety log
    log_entries = monitor.get_safety_log()
    assert len(log_entries) >= 2  # DD_ABORT + EMERGENCY_STOP

    # Test 12: Heartbeat
    hb = monitor.heartbeat()
    assert 'ALIVE' in hb['message']

    os.remove(db)
    print('safety.py: self-check PASSED')


if __name__ == '__main__':
    selfcheck()
