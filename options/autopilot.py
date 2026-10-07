"""
Autonomous paper trading engine (Davey Ch.14 incubation).

Runs two daily cycles (morning entry scan + EOD exit check) using
the existing paper_trade pipeline.  The only manual action required
is refreshing the Dhan token every 24 hours.

Usage:
  from options.autopilot import Autopilot
  ap = Autopilot()
  ap.start()   # schedules background cycles
  ap.stop()
  ap.run_cycle()  # single cycle (for CLI / testing)
"""
from __future__ import annotations
import datetime
import json
import logging
import math
import os
import sqlite3
import uuid

log = logging.getLogger(__name__)

_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_FILE = os.path.join(_DIR, '.autopilot_config.json')

DEFAULT_CONFIG = {
    'enabled': False,
    'symbols': ['NIFTY'],
    'capital': 500000,
    'min_score': 7.0,
    'max_concurrent_trades': 3,
    'capital_reserve_pct': 30,
    'profit_target_pct': 50,
    'stop_loss_multiplier': 1.0,
    'weekly_dte_exit': 1,
    'monthly_dte_exit': 2,
    'max_daily_loss': 15000,
    'max_drawdown_pct': 15,
    'max_trades_per_day': 2,
    'max_consecutive_losses': 5,
    'scan_times': ['09:45', '15:20'],
    'only_incubating': True,
}

_CONFIG_BOUNDS = {
    'capital':              (100_000, 10_000_000),
    'min_score':            (1.0, 10.0),
    'max_concurrent_trades':(1, 5),
    'capital_reserve_pct':  (10, 80),
    'profit_target_pct':    (20, 90),
    'stop_loss_multiplier': (0.5, 3.0),
    'weekly_dte_exit':      (0, 3),
    'monthly_dte_exit':     (1, 7),
    'max_daily_loss':       (1_000, 500_000),
    'max_drawdown_pct':     (5, 50),
    'max_trades_per_day':   (1, 5),
    'max_consecutive_losses':(2, 20),
}


# ── Config ──────────────────────────────────────────────────────

def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(_CONFIG_FILE):
        try:
            with open(_CONFIG_FILE) as f:
                saved = json.load(f)
            cfg.update(saved)
        except Exception:
            pass
    return cfg


def save_config(cfg: dict) -> dict:
    validated = dict(DEFAULT_CONFIG)
    for k, v in cfg.items():
        if k not in DEFAULT_CONFIG:
            continue
        if k in _CONFIG_BOUNDS:
            lo, hi = _CONFIG_BOUNDS[k]
            v = type(DEFAULT_CONFIG[k])(v)
            v = max(lo, min(hi, v))
        if k == 'symbols':
            v = [s.upper() for s in v if s.upper() in ('NIFTY', 'BANKNIFTY')]
            if not v:
                v = ['NIFTY']
        validated[k] = v
    with open(_CONFIG_FILE, 'w') as f:
        json.dump(validated, f, indent=2)
    return validated


# ── Decision Log ────────────────────────────────────────────────

def _conn(db):
    """WAL-mode SQLite connection for concurrent cron + web access."""
    c = sqlite3.connect(db, timeout=10)
    c.execute('PRAGMA journal_mode=WAL')
    return c


def _log_decision(db, cycle_id, cycle_type, action, reason,
                  symbol=None, trade_id=None, rec_id=None,
                  strategy=None, score=None, spot=None, vix=None,
                  pnl=None, context=None):
    conn = _conn(db)
    conn.execute(
        '''INSERT INTO autopilot_log
           (timestamp, cycle_id, cycle_type, action, symbol, trade_id,
            recommendation_id, strategy, score, spot, vix, pnl, reason, context_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (datetime.datetime.now().isoformat(), cycle_id, cycle_type,
         action, symbol, trade_id, rec_id, strategy, score, spot, vix, pnl,
         reason, json.dumps(context) if context else None)
    )
    conn.commit()
    conn.close()


def get_decision_log(db=None, limit=50) -> list:
    from . import paper_trade
    db = db or paper_trade._db_path()
    paper_trade.init_db(db)
    conn = _conn(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        'SELECT * FROM autopilot_log ORDER BY id DESC LIMIT ?', (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Preflight ───────────────────────────────────────────────────

def _preflight(cfg, db) -> tuple[bool, str]:
    """Return (ok, reason). If not ok, cycle should skip."""
    # 1. Dhan token
    from .data import dhan_fetch
    status = dhan_fetch.get_token_status()
    if not status.get('active') and not os.getenv('DHAN_ACCESS_TOKEN'):
        return False, 'Dhan token expired and no .env fallback'

    # 2. Market day
    from .data import event_calendar
    today = datetime.date.today()
    if today.weekday() >= 5:
        return False, f'Weekend ({today.strftime("%A")})'
    if event_calendar.is_nse_holiday(today):
        return False, f'NSE holiday ({today.isoformat()})'

    # 3. Drawdown circuit breaker
    conn = _conn(db)
    conn.row_factory = sqlite3.Row
    closed = conn.execute(
        "SELECT net_pnl FROM trades WHERE status='closed' AND source='autopilot'"
    ).fetchall()
    conn.close()
    total_pnl = sum(r['net_pnl'] or 0 for r in closed)
    current_capital = cfg['capital'] + total_pnl
    if cfg['capital'] > 0:
        dd_pct = max(0, (cfg['capital'] - current_capital) / cfg['capital'] * 100)
        if dd_pct >= cfg['max_drawdown_pct']:
            return False, f'Drawdown {dd_pct:.1f}% >= {cfg["max_drawdown_pct"]}% circuit breaker'

    # 4. Incubating strategies exist
    if cfg['only_incubating']:
        conn = _conn(db)
        conn.row_factory = sqlite3.Row
        inc = conn.execute(
            "SELECT COUNT(*) as n FROM strategy_lifecycle WHERE status='INCUBATING'"
        ).fetchone()
        conn.close()
        if inc['n'] == 0:
            return False, 'No strategies in INCUBATING status — nothing to trade'

    return True, 'Preflight OK'


# ── Capital ─────────────────────────────────────────────────────

def _capital_state(cfg, db) -> dict:
    conn = _conn(db)
    conn.row_factory = sqlite3.Row
    closed_pnl = conn.execute(
        "SELECT COALESCE(SUM(net_pnl),0) as total FROM trades WHERE status='closed'"
    ).fetchone()['total']
    open_trades = [dict(r) for r in conn.execute(
        "SELECT * FROM trades WHERE status='open'"
    ).fetchall()]
    conn.close()

    current_capital = cfg['capital'] + closed_pnl
    deployed = sum((r.get('margin_per_lot') or 0) * (r.get('lots') or 1) for r in open_trades)
    available = current_capital - deployed
    reserve = cfg['capital_reserve_pct'] / 100.0 * current_capital

    return {
        'current_capital': current_capital,
        'deployed': deployed,
        'available': available,
        'reserve': reserve,
        'can_enter': available > reserve,
        'open_count': len(open_trades),
        'open_trades': [dict(r) for r in open_trades],
        'dd_pct': max(0, (cfg['capital'] - current_capital) / max(1, cfg['capital']) * 100),
    }


# ── Exit Logic ──────────────────────────────────────────────────

def _should_exit(trade, spot, cfg, db) -> tuple[bool, str]:
    """Evaluate if an open trade should be auto-exited. Returns (exit, reason)."""
    from .strategies import adjustments
    from .data import event_calendar
    from .core import bsm

    legs = json.loads(trade['legs']) if isinstance(trade['legs'], str) else trade['legs']
    lot_size = trade['lot_size'] or 75
    lots = trade['lots'] or 1

    # Compute DTE from target_expiry (trades table has no 'dte' column)
    target_exp = trade.get('target_expiry')
    if target_exp:
        try:
            dte_days = max(0, (datetime.date.fromisoformat(target_exp) - datetime.date.today()).days)
        except Exception:
            dte_days = 14
    else:
        dte_days = 14
    t_years = max(1, dte_days) / 365

    unit_pnl = 0.0
    for l in legs:
        entry_p = l.get('premium', 0)
        iv = max(l.get('iv', 0.15), 0.01)
        try:
            current_p = bsm.bsm_price(spot, l['strike'], t_years, 0.07, iv, l['option_type'])
        except Exception:
            current_p = entry_p
        sign = 1 if l.get('action') == 'BUY' else -1
        unit_pnl += sign * (current_p - entry_p)

    total_pnl = unit_pnl * lot_size * lots
    max_profit = (trade.get('max_profit_per_lot') or 0) * lots
    max_loss = (trade.get('max_loss_per_lot') or 0) * lots

    # 1. Profit target
    if max_profit > 0 and total_pnl >= max_profit * cfg['profit_target_pct'] / 100:
        pct = total_pnl / max_profit * 100
        return True, f'Profit target: P/L ₹{total_pnl:.0f} = {pct:.0f}% of max profit (target {cfg["profit_target_pct"]}%)'

    # 2. Stop loss
    if max_loss > 0 and total_pnl <= -(max_loss * cfg['stop_loss_multiplier']):
        return True, f'Stop loss: P/L ₹{total_pnl:.0f} exceeds -{cfg["stop_loss_multiplier"]}× max loss ₹{max_loss:.0f}'

    # 3. DTE exit — reuse dte_days computed above for BSM
    dte = dte_days if target_exp else None

    if dte is not None:
        if dte == 0:
            return True, 'Expiry day — force close'

        try:
            monthly_exp = event_calendar.next_expiry(trade['symbol'], monthly=True)
            is_monthly = (target_exp == monthly_exp.isoformat()) if monthly_exp else False
        except Exception:
            is_monthly = False

        threshold = cfg['monthly_dte_exit'] if is_monthly else cfg['weekly_dte_exit']
        if dte <= threshold:
            kind = 'monthly' if is_monthly else 'weekly'
            return True, f'DTE exit: {dte} DTE ≤ {threshold} ({kind} expiry approaching)'

    # 4. Expiry passed (ghost trade) — caught by Phase 1 too, but safety net
    if target_exp:
        try:
            if datetime.date.fromisoformat(target_exp) < datetime.date.today():
                return True, f'Target expiry {target_exp} has passed — ghost trade cleanup'
        except Exception:
            pass

    # 5. Adjustment engine urgency=1
    opened = trade.get('opened_at', '')
    entry_date = opened[:10] if opened else datetime.date.today().isoformat()
    days_held = max(0, (datetime.date.today() - datetime.date.fromisoformat(entry_date)).days)
    entry_spot = trade.get('entry_spot') or spot

    position = {
        'legs': legs,
        'net_premium': sum(
            (l.get('premium', 0) if l.get('action') == 'SELL' else -l.get('premium', 0))
            for l in legs
        ),
    }

    try:
        adj = adjustments.check(position, spot, days_held=days_held,
                                entry_spot=entry_spot, dte=dte)
    except Exception as e:
        log.warning(f'Adjustment check failed for trade {trade["id"]}: {e}')
        adj = []

    for a in adj:
        if a.get('urgency') == 1 and a.get('action') in ('close', 'stop_loss'):
            return True, f'Adjustment urgency=1: {a["action"]} — {a.get("reason", "")}'
        if a.get('urgency') == 1 and a.get('action') == 'take_profit':
            return True, f'Adjustment urgency=1: take_profit — {a.get("reason", "")}'

    return False, ''


# ── Entry Logic ─────────────────────────────────────────────────

def _should_enter(rec, cfg, cap_state, db) -> tuple[bool, str]:
    """Evaluate if a recommendation should be auto-entered."""
    score = rec.get('score', 0)
    if score < cfg['min_score']:
        return False, f'Score {score:.1f} < {cfg["min_score"]} threshold'

    if cap_state['open_count'] >= cfg['max_concurrent_trades']:
        return False, f'Max concurrent trades ({cfg["max_concurrent_trades"]}) reached'

    if not cap_state['can_enter']:
        return False, f'Capital reserve: available ₹{cap_state["available"]:.0f} < reserve ₹{cap_state["reserve"]:.0f}'

    # Max trades per day
    conn = _conn(db)
    today_str = datetime.date.today().isoformat()
    day_count = conn.execute(
        "SELECT COUNT(*) FROM trades WHERE source='autopilot' AND opened_at LIKE ?",
        (today_str + '%',)
    ).fetchone()[0]
    conn.close()
    if day_count >= cfg['max_trades_per_day']:
        return False, f'Max trades today ({cfg["max_trades_per_day"]}) reached'

    # Consecutive losses check
    conn = _conn(db)
    conn.row_factory = sqlite3.Row
    recent = conn.execute(
        "SELECT net_pnl FROM trades WHERE source='autopilot' AND status='closed' "
        "ORDER BY id DESC LIMIT ?",
        (cfg['max_consecutive_losses'],)
    ).fetchall()
    conn.close()
    if len(recent) >= cfg['max_consecutive_losses']:
        if all((r['net_pnl'] or 0) < 0 for r in recent):
            return False, f'{cfg["max_consecutive_losses"]} consecutive losses — pausing entries'

    # Conflict check: no same (symbol, strategy) open
    strategy = rec.get('strategy', '')
    symbol = rec.get('symbol', '')
    for t in cap_state['open_trades']:
        if t.get('symbol') == symbol and t.get('strategy') == strategy:
            return False, f'Conflict: already have open {strategy} on {symbol}'

    # Audit gate
    audit = rec.get('audit', {})
    if isinstance(audit, str):
        try:
            audit = json.loads(audit)
        except Exception:
            audit = {}
    if audit.get('decision') == 'REJECT':
        reasons = audit.get('rejection_reasons', [])
        return False, f'Audit rejected: {", ".join(reasons[:3])}'

    # Entry gate
    gate = rec.get('entry_gate', {})
    if isinstance(gate, str):
        try:
            gate = json.loads(gate)
        except Exception:
            gate = {}
    if gate and not gate.get('passes', True):
        return False, f'Entry gate failed: ratio={gate.get("ratio", 0):.2f}'

    # Only incubating strategies
    if cfg['only_incubating']:
        conn = _conn(db)
        inc = conn.execute(
            "SELECT status FROM strategy_lifecycle WHERE strategy_key=?",
            (strategy,)
        ).fetchone()
        conn.close()
        if not inc or inc[0] != 'INCUBATING':
            return False, f'Strategy {strategy} not in INCUBATING status'

    return True, f'Score {score:.1f} ≥ {cfg["min_score"]}, all gates passed'


# ── Core Cycle ──────────────────────────────────────────────────

def run_cycle(cycle_type='auto', db=None) -> dict:
    """
    Execute one autonomous cycle.

    cycle_type: 'morning' (entries + exits), 'eod' (exits only), 'auto' (detect from clock)
    Returns summary dict.
    """
    from . import paper_trade

    db = db or paper_trade._db_path()
    paper_trade.init_db(db)
    cfg = load_config()
    cycle_id = uuid.uuid4().hex[:12]

    if cycle_type == 'auto':
        hour = datetime.datetime.now().hour
        cycle_type = 'morning' if hour < 14 else 'eod'

    summary = {
        'cycle_id': cycle_id,
        'cycle_type': cycle_type,
        'timestamp': datetime.datetime.now().isoformat(),
        'entries': 0,
        'exits': 0,
        'checks': 0,
        'skips': 0,
        'errors': [],
    }

    # Preflight
    ok, reason = _preflight(cfg, db)
    if not ok:
        _log_decision(db, cycle_id, cycle_type, 'preflight_fail', reason)
        summary['preflight'] = reason
        log.info(f'Autopilot cycle {cycle_id} skipped: {reason}')
        return summary

    _log_decision(db, cycle_id, cycle_type, 'preflight_ok', reason)
    cap_state = _capital_state(cfg, db)

    # ── Phase 1: Expire ghost trades ──
    conn = _conn(db)
    conn.row_factory = sqlite3.Row
    ghosts = conn.execute(
        "SELECT id, target_expiry, strategy, symbol FROM trades "
        "WHERE status='open' AND target_expiry IS NOT NULL AND target_expiry < ?",
        (datetime.date.today().isoformat(),)
    ).fetchall()
    conn.close()
    for g in ghosts:
        try:
            paper_trade.exit_trade(g['id'], reason='Autopilot: target expiry passed', db=db)
            _log_decision(db, cycle_id, cycle_type, 'exit', f'Ghost trade cleanup: expiry {g["target_expiry"]}',
                          symbol=g['symbol'], trade_id=g['id'], strategy=g['strategy'])
            summary['exits'] += 1
        except Exception as e:
            summary['errors'].append(f'Ghost exit {g["id"]}: {e}')

    # ── Phase 2: Check & exit open trades ──
    conn = _conn(db)
    conn.row_factory = sqlite3.Row
    open_trades = conn.execute("SELECT * FROM trades WHERE status='open'").fetchall()
    conn.close()

    _spot_cache = {}
    def _get_spot(sym):
        if sym not in _spot_cache:
            try:
                from .data.live_feed import feed, INDEX_SID
                sid = INDEX_SID.get(sym.upper())
                ltp = feed.ltp(sid) if sid else None
                if ltp is not None:
                    _spot_cache[sym] = ltp
                else:
                    from .data import dhan_fetch
                    _spot_cache[sym] = dhan_fetch.fetch_spot(sym)
            except Exception:
                _spot_cache[sym] = None
        return _spot_cache[sym]

    for trade in open_trades:
        trade = dict(trade)
        summary['checks'] += 1
        symbol = trade.get('symbol', 'NIFTY')

        spot = _get_spot(symbol) or trade.get('entry_spot', 0)

        should_exit, exit_reason = _should_exit(trade, spot, cfg, db)

        if should_exit:
            # Only auto-exit autopilot trades; log manual trade status
            if trade.get('source', 'manual') != 'autopilot':
                _log_decision(db, cycle_id, cycle_type, 'skip_exit',
                              f'Manual trade — exit signal but not auto-managed: {exit_reason}',
                              symbol=symbol, trade_id=trade['id'], strategy=trade.get('strategy'))
                continue

            try:
                result = paper_trade.exit_trade(trade['id'], spot=spot,
                                                reason=f'Autopilot: {exit_reason}', db=db)
                pnl = result.get('net_pnl', 0) if isinstance(result, dict) else 0
                _log_decision(db, cycle_id, cycle_type, 'exit', exit_reason,
                              symbol=symbol, trade_id=trade['id'], strategy=trade.get('strategy'),
                              spot=spot, pnl=pnl)
                summary['exits'] += 1
                log.info(f'Autopilot EXIT trade {trade["id"]} ({trade.get("strategy")}): {exit_reason}')
            except Exception as e:
                summary['errors'].append(f'Exit trade {trade["id"]}: {e}')
                log.warning(f'Autopilot exit failed for trade {trade["id"]}: {e}')

    # Update capital after exits
    cap_state = _capital_state(cfg, db)

    # ── Phase 3: Scan for entries (morning only) ──
    if cycle_type == 'morning':
        # Expire stale recommendations first
        try:
            paper_trade.expire_old(db=db)
        except Exception:
            pass

        # Check daily loss
        conn = _conn(db)
        today_str = datetime.date.today().isoformat()
        daily_pnl = conn.execute(
            "SELECT COALESCE(SUM(net_pnl),0) FROM trades "
            "WHERE source='autopilot' AND status='closed' AND closed_at LIKE ?",
            (today_str + '%',)
        ).fetchone()[0]
        conn.close()

        if daily_pnl < -cfg['max_daily_loss']:
            _log_decision(db, cycle_id, cycle_type, 'skip_entry',
                          f'Daily loss ₹{daily_pnl:.0f} exceeds -₹{cfg["max_daily_loss"]}')
            summary['skips'] += 1
        else:
            for symbol in cfg['symbols']:
                try:
                    rec = paper_trade.recommend(symbol=symbol, capital=cfg['capital'], db=db)
                except Exception as e:
                    _log_decision(db, cycle_id, cycle_type, 'error',
                                  f'Recommend failed: {e}', symbol=symbol)
                    summary['errors'].append(f'Recommend {symbol}: {e}')
                    continue

                if rec.get('status') in ('error', 'no_recommendation'):
                    _log_decision(db, cycle_id, cycle_type, 'no_opportunity',
                                  rec.get('reason', 'No recommendation'),
                                  symbol=symbol, score=rec.get('score'))
                    summary['skips'] += 1
                    continue

                cap_state = _capital_state(cfg, db)
                should, reason = _should_enter(rec, cfg, cap_state, db)

                if should:
                    try:
                        rec_id = rec['recommendation_id']
                        result = paper_trade.enter(rec_id, db=db)
                        trade_id = result.get('trade_id')

                        # Tag as autopilot
                        if trade_id:
                            conn = _conn(db)
                            conn.execute("UPDATE trades SET source='autopilot' WHERE id=?", (trade_id,))
                            conn.commit()
                            conn.close()

                        _log_decision(db, cycle_id, cycle_type, 'enter', reason,
                                      symbol=symbol, trade_id=trade_id, rec_id=rec_id,
                                      strategy=rec.get('strategy'), score=rec.get('score'),
                                      spot=rec.get('spot'), vix=rec.get('vix'))
                        summary['entries'] += 1
                        log.info(f'Autopilot ENTER {symbol} {rec.get("strategy")} score={rec.get("score"):.1f}')
                    except Exception as e:
                        _log_decision(db, cycle_id, cycle_type, 'error',
                                      f'Enter failed: {e}', symbol=symbol,
                                      rec_id=rec.get('recommendation_id'),
                                      strategy=rec.get('strategy'))
                        summary['errors'].append(f'Enter {symbol}: {e}')
                else:
                    _log_decision(db, cycle_id, cycle_type, 'skip_entry', reason,
                                  symbol=symbol, strategy=rec.get('strategy'),
                                  score=rec.get('score'), spot=rec.get('spot'))
                    summary['skips'] += 1

    # ── Phase 4: Post-cycle ──
    # Update lifecycle for any strategies that had exits
    if summary['exits'] > 0:
        conn = _conn(db)
        conn.row_factory = sqlite3.Row
        incubating = conn.execute(
            "SELECT strategy_key FROM strategy_lifecycle WHERE status='INCUBATING'"
        ).fetchall()
        conn.close()
        for row in incubating:
            try:
                paper_trade.check_lifecycle(row['strategy_key'], db=db)
            except Exception as e:
                log.warning(f'Lifecycle check failed for {row["strategy_key"]}: {e}')

    cap_final = _capital_state(cfg, db)
    _log_decision(db, cycle_id, cycle_type, 'cycle_complete',
                  f'Entered={summary["entries"]}, exited={summary["exits"]}, '
                  f'checked={summary["checks"]}, open={cap_final["open_count"]}, '
                  f'capital_used={cap_final["deployed"]/max(1,cap_final["current_capital"])*100:.0f}%',
                  context={'capital': cap_final})

    log.info(f'Autopilot cycle {cycle_id} complete: {summary}')
    return summary


# ── Standalone functions (cron-friendly, no threading) ──────────

def enable(db=None):
    cfg = load_config()
    cfg['enabled'] = True
    save_config(cfg)
    try:
        cron = install_cron()
    except Exception as e:
        log.warning("cron install failed: %s", e)
        cron = {'installed': 0, 'error': str(e)}
    return {'status': 'enabled', 'cron': cron}


def disable(db=None):
    cfg = load_config()
    cfg['enabled'] = False
    save_config(cfg)
    try:
        uninstall_cron()
    except Exception as e:
        log.warning("cron uninstall failed: %s", e)
    return {'status': 'disabled'}


def emergency_stop(db=None):
    """Disable autopilot and close ALL autopilot trades at entry_spot."""
    from . import paper_trade
    db = db or paper_trade._db_path()
    disable()
    conn = _conn(db)
    conn.row_factory = sqlite3.Row
    open_trades = conn.execute(
        "SELECT id, symbol, entry_spot FROM trades WHERE status='open' AND source='autopilot'"
    ).fetchall()
    conn.close()
    closed = 0
    errors = []
    for t in open_trades:
        try:
            paper_trade.exit_trade(t['id'], spot=t['entry_spot'],
                                   reason='Emergency stop', db=db)
            closed += 1
        except Exception as e:
            errors.append(f'Trade {t["id"]}: {e}')
            log.warning(f'Emergency exit failed for trade {t["id"]}: {e}')
    log.info(f'Emergency stop: closed {closed} trades, {len(errors)} errors')
    return {'stopped': True, 'trades_closed': closed, 'errors': errors}


def status(db=None):
    """Current autopilot status — config, capital, last cycle from log."""
    from . import paper_trade
    db = db or paper_trade._db_path()
    paper_trade.init_db(db)
    cfg = load_config()
    cap = _capital_state(cfg, db)

    conn = _conn(db)
    conn.row_factory = sqlite3.Row
    last = conn.execute(
        "SELECT timestamp, reason FROM autopilot_log "
        "WHERE action='cycle_complete' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()

    return {
        'enabled': cfg.get('enabled', False),
        'last_cycle': dict(last) if last else None,
        'scan_times': cfg.get('scan_times', ['09:45', '15:20']),
        'config': cfg,
        'capital': cap,
    }


def dashboard_data(db=None):
    """Full dashboard payload — one call, all data the UI needs."""
    from . import paper_trade
    from .data import dhan_fetch

    db = db or paper_trade._db_path()
    paper_trade.init_db(db)
    cfg = load_config()

    conn = _conn(db)
    conn.row_factory = sqlite3.Row

    # ── Token status ──
    token = dhan_fetch.get_token_status()

    # ── Capital ──
    cap = _capital_state(cfg, db)

    # ── All trades ──
    all_trades = [dict(r) for r in conn.execute(
        "SELECT * FROM trades ORDER BY id DESC"
    ).fetchall()]

    open_trades = [t for t in all_trades if t['status'] == 'open']
    closed_trades = [t for t in all_trades if t['status'] == 'closed']

    # Parse legs JSON
    for t in all_trades:
        if isinstance(t.get('legs'), str):
            try:
                t['legs_parsed'] = json.loads(t['legs'])
            except Exception:
                t['legs_parsed'] = []
        else:
            t['legs_parsed'] = t.get('legs') or []

    # ── Enrich open trades (unrealized P/L from latest daily_check) ──
    today = datetime.date.today()
    for t in open_trades:
        # Latest daily check
        chk = conn.execute(
            "SELECT spot, current_pnl, dte, max_urgency FROM daily_checks "
            "WHERE trade_id=? ORDER BY id DESC LIMIT 1", (t['id'],)
        ).fetchone()
        if chk:
            t['last_check_spot'] = chk['spot']
            t['unrealized_pnl'] = chk['current_pnl']
            t['current_dte'] = chk['dte']
            t['max_urgency'] = chk['max_urgency']
        else:
            t['last_check_spot'] = t.get('entry_spot')
            t['unrealized_pnl'] = 0
            t['current_dte'] = None
            t['max_urgency'] = 3

        # Days held
        opened = t.get('opened_at', '')
        if opened:
            try:
                entry_date = datetime.date.fromisoformat(opened[:10])
                t['days_held'] = (today - entry_date).days
            except Exception:
                t['days_held'] = 0
        else:
            t['days_held'] = 0

        # DTE from target_expiry if not from daily_check
        if t['current_dte'] is None and t.get('target_expiry'):
            try:
                exp = datetime.date.fromisoformat(t['target_expiry'])
                t['current_dte'] = max(0, (exp - today).days)
            except Exception:
                pass

        t['legs_summary'] = _legs_summary(t['legs_parsed'])

        # Full per-leg repricing, greeks, breakevens, scenarios
        try:
            _enrich_open_trade(t, db)
        except Exception as e:
            log.warning(f'Enrichment failed for trade {t.get("id")}: {e}')
            t['leg_details'] = []
            t['greeks'] = {'delta': 0, 'gamma': 0, 'theta_daily': 0, 'vega': 0}
            t['breakevens'] = []
            t['scenarios'] = {}

    # ── Portfolio-level greeks ──
    portfolio_greeks = {'delta': 0, 'gamma': 0, 'theta_daily': 0, 'vega': 0}
    for t in open_trades:
        g = t.get('greeks', {})
        for k in portfolio_greeks:
            portfolio_greeks[k] += g.get(k, 0)
    portfolio_greeks = {k: round(v, 2) for k, v in portfolio_greeks.items()}

    # ── Enrich closed trades ──
    for t in closed_trades:
        opened = t.get('opened_at', '')
        closed_at = t.get('closed_at', '')
        t['hold_days'] = 0
        if opened and closed_at:
            try:
                t['hold_days'] = (datetime.date.fromisoformat(closed_at[:10])
                                  - datetime.date.fromisoformat(opened[:10])).days
            except Exception:
                pass
        t['total_cost'] = (t.get('entry_cost') or 0) + (t.get('exit_cost') or 0)
        t['legs_summary'] = _legs_summary(t['legs_parsed'])

    # ── Strategy aggregation ──
    strategies = {}
    for t in closed_trades:
        key = t.get('strategy', 'unknown')
        if key not in strategies:
            strategies[key] = {'key': key, 'trades': 0, 'wins': 0, 'losses': 0,
                               'gross_wins': 0, 'gross_losses': 0, 'total_pnl': 0,
                               'pnls': [], 'hold_days': []}
        s = strategies[key]
        pnl = t.get('net_pnl') or 0
        s['trades'] += 1
        s['pnls'].append(pnl)
        s['hold_days'].append(t.get('hold_days', 0))
        s['total_pnl'] += pnl
        if pnl > 0:
            s['wins'] += 1
            s['gross_wins'] += pnl
        elif pnl < 0:
            s['losses'] += 1
            s['gross_losses'] += abs(pnl)

    # Lifecycle data
    lc_rows = [dict(r) for r in conn.execute(
        "SELECT * FROM strategy_lifecycle"
    ).fetchall()]
    lc_map = {r['strategy_key']: r for r in lc_rows}

    strategy_cards = []
    for lc in lc_rows:
        key = lc['strategy_key']
        perf = strategies.get(key, {})
        trades = perf.get('trades', 0)
        wins = perf.get('wins', 0)
        losses = perf.get('losses', 0)
        total_pnl = perf.get('total_pnl', 0)
        gross_wins = perf.get('gross_wins', 0)
        gross_losses = perf.get('gross_losses', 0)

        win_rate = (wins / trades * 100) if trades > 0 else 0
        profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else (
            float('inf') if gross_wins > 0 else 0)
        avg_win = gross_wins / wins if wins > 0 else 0
        avg_loss = gross_losses / losses if losses > 0 else 0
        expectancy = (total_pnl / trades) if trades > 0 else 0

        # WFA comparison
        wfa_avg = lc.get('wfa_avg_pnl') or 0
        wfa_expected = lc.get('wfa_expected_return') or 0
        actual_return = total_pnl
        ret_eff = (actual_return / wfa_expected * 100) if wfa_expected > 0 else 0

        # Graduation progress
        start = lc.get('start_date', '')
        months_incubating = 0
        if start:
            try:
                sd = datetime.date.fromisoformat(start)
                months_incubating = round((today - sd).days / 30.44, 1)
            except Exception:
                pass

        strategy_cards.append({
            'key': key,
            'status': lc.get('status', 'UNKNOWN'),
            'start_date': start,
            'months_incubating': months_incubating,
            'trade_count': lc.get('trade_count') or trades,
            'wins': wins,
            'losses': losses,
            'win_rate': round(win_rate, 1),
            'profit_factor': round(profit_factor, 2) if profit_factor != float('inf') else None,
            'avg_win': round(avg_win),
            'avg_loss': round(avg_loss),
            'expectancy': round(expectancy),
            'total_pnl': round(total_pnl),
            'return_efficiency': round(ret_eff, 1),
            'wfa_avg_pnl': round(wfa_avg),
            'wfa_expected_return': round(wfa_expected),
            'wfa_max_dd_pct': lc.get('wfa_max_dd_pct'),
            'mc_abort_dd_pct': lc.get('mc_abort_dd_pct'),
            'current_dd_pct': lc.get('current_dd_pct') or 0,
            'dd_efficiency': lc.get('dd_efficiency'),
            # Graduation criteria progress
            'grad_months': months_incubating >= 3,
            'grad_trades': (lc.get('trade_count') or trades) >= 30,
            'grad_return_eff': 70 <= ret_eff <= 130 if trades >= 5 else None,
        })

    # ── Equity curve from closed trades ──
    equity_points = []
    cumulative = 0
    sorted_closed = sorted(closed_trades, key=lambda t: t.get('closed_at', ''))
    for t in sorted_closed:
        pnl = t.get('net_pnl') or 0
        cumulative += pnl
        equity_points.append({
            'date': (t.get('closed_at') or '')[:10],
            'pnl': round(pnl),
            'cumulative': round(cumulative),
            'strategy': t.get('strategy', ''),
        })

    # ── Risk state ──
    # Consecutive losses
    recent_closed = conn.execute(
        "SELECT net_pnl FROM trades WHERE status='closed' ORDER BY id DESC LIMIT 20"
    ).fetchall()
    consec_losses = 0
    for r in recent_closed:
        if (r['net_pnl'] or 0) < 0:
            consec_losses += 1
        else:
            break

    # Today's P/L
    today_str = today.isoformat()
    daily_pnl = conn.execute(
        "SELECT COALESCE(SUM(net_pnl), 0) FROM trades "
        "WHERE status='closed' AND closed_at LIKE ?",
        (today_str + '%',)
    ).fetchone()[0]

    # Today's autopilot cycle count
    today_cycles = conn.execute(
        "SELECT COUNT(*) FROM autopilot_log "
        "WHERE action='cycle_complete' AND timestamp LIKE ?",
        (today_str + '%',)
    ).fetchone()[0]

    # Last cycle
    last_cycle = conn.execute(
        "SELECT timestamp, reason FROM autopilot_log "
        "WHERE action='cycle_complete' ORDER BY id DESC LIMIT 1"
    ).fetchone()

    conn.close()

    # ── Aggregate stats ──
    total_closed = len(closed_trades)
    total_wins = sum(1 for t in closed_trades if (t.get('net_pnl') or 0) > 0)
    total_losses = sum(1 for t in closed_trades if (t.get('net_pnl') or 0) < 0)
    total_net = sum(t.get('net_pnl') or 0 for t in closed_trades)
    total_gross_w = sum(t['net_pnl'] for t in closed_trades if (t.get('net_pnl') or 0) > 0)
    total_gross_l = sum(abs(t['net_pnl']) for t in closed_trades if (t.get('net_pnl') or 0) < 0)
    total_gross = sum(t.get('gross_pnl') or 0 for t in closed_trades)
    total_costs = sum(t.get('total_cost') or 0 for t in closed_trades)

    # ── Cost analysis ──
    cost_drag_pct = round(total_costs / max(1, abs(total_gross)) * 100, 1) if total_gross else 0

    # ── Monthly P/L ──
    monthly = {}
    for t in closed_trades:
        month_key = (t.get('closed_at') or '')[:7]  # YYYY-MM
        if not month_key:
            continue
        if month_key not in monthly:
            monthly[month_key] = {'month': month_key, 'trades': 0, 'wins': 0,
                                  'gross': 0, 'costs': 0, 'net': 0}
        m = monthly[month_key]
        m['trades'] += 1
        pnl = t.get('net_pnl') or 0
        if pnl > 0:
            m['wins'] += 1
        m['gross'] += t.get('gross_pnl') or 0
        m['costs'] += t.get('total_cost') or 0
        m['net'] += pnl
    monthly_summary = sorted(monthly.values(), key=lambda m: m['month'], reverse=True)
    for m in monthly_summary:
        m['gross'] = round(m['gross'])
        m['costs'] = round(m['costs'])
        m['net'] = round(m['net'])
        m['win_rate'] = round(m['wins'] / max(1, m['trades']) * 100, 1)

    # ── Attention items ──
    attention = []
    # Token
    if not token.get('active'):
        attention.append({'level': 'error', 'icon': 'key', 'msg': 'Dhan token expired — autopilot cannot fetch live data'})
    elif token.get('remaining_hours', 99) < 2:
        attention.append({'level': 'warn', 'icon': 'key', 'msg': f'Dhan token expires in {token["remaining_hours"]:.1f}h — refresh soon'})

    # Watchdog: last successful cycle staleness
    if cfg.get('enabled') and last_cycle:
        try:
            lc_ts = datetime.datetime.fromisoformat(last_cycle['timestamp'])
            hours_ago = (datetime.datetime.now() - lc_ts).total_seconds() / 3600
            if hours_ago > 24:
                attention.append({'level': 'error', 'icon': 'exclamation-octagon',
                                  'msg': f'Last successful cycle was {hours_ago:.0f}h ago — cron may have failed silently. Check: crontab -l'})
            elif hours_ago > 6 and today.weekday() < 5:
                attention.append({'level': 'warn', 'icon': 'exclamation-octagon',
                                  'msg': f'No cycle in {hours_ago:.0f}h — if market was open, cron may need attention'})
        except Exception:
            pass
    elif cfg.get('enabled') and not last_cycle:
        attention.append({'level': 'warn', 'icon': 'exclamation-octagon',
                          'msg': 'Autopilot enabled but no cycle has ever run — verify cron is installed: crontab -l'})

    # Open trade risks — grouped by trade
    for t in open_trades:
        tid = t.get('id')
        sym = t.get('symbol', '?')
        strat = (t.get('strategy') or '').replace('_', ' ')
        issues = []

        dte = t.get('current_dte')
        if dte is not None and dte <= 1:
            issues.append(f'{dte} DTE — expiry imminent')
        elif dte is not None and dte <= 3:
            issues.append(f'{dte} DTE — approaching expiry')

        pnl = t.get('unrealized_pnl') or 0
        max_l = (t.get('max_loss_per_lot') or 0) * (t.get('lots') or 1)
        if max_l > 0 and pnl < 0 and abs(pnl) > max_l * 0.7:
            pct_of_max = abs(pnl) / max_l * 100
            issues.append(f'{pct_of_max:.0f}% of max loss (₹{pnl:,.0f} / -₹{max_l:,.0f})')

        urg = t.get('max_urgency', 3)
        if urg <= 1:
            issues.append('urgency-1 adjustment needed')

        if issues:
            level = 'error' if any('imminent' in i or 'max loss' in i or 'urgency' in i for i in issues) else 'warn'
            attention.append({'level': level, 'icon': 'exclamation-triangle',
                              'msg': f'Trade #{tid} {sym} ({strat}): {" · ".join(issues)}'})

    # Risk limits
    if cap['dd_pct'] > cfg['max_drawdown_pct'] * 0.7:
        attention.append({'level': 'warn', 'icon': 'shield-exclamation',
                          'msg': f'Drawdown at {cap["dd_pct"]:.1f}% — approaching {cfg["max_drawdown_pct"]}% limit'})
    if consec_losses >= cfg['max_consecutive_losses'] - 1:
        attention.append({'level': 'warn', 'icon': 'bar-chart',
                          'msg': f'{consec_losses} consecutive losses — 1 more triggers pause'})

    # Unrealized total
    total_unrealized = sum(t.get('unrealized_pnl') or 0 for t in open_trades)

    return {
        'config': cfg,
        'token': token,
        'last_cycle': dict(last_cycle) if last_cycle else None,
        'today_cycles': today_cycles,
        'capital': cap,
        'attention': attention,
        'portfolio_greeks': portfolio_greeks,
        'portfolio': {
            'starting_capital': cfg['capital'],
            'current_capital': cap['current_capital'],
            'total_pnl': round(total_net),
            'total_pnl_pct': round(total_net / max(1, cfg['capital']) * 100, 2),
            'total_trades': total_closed,
            'total_wins': total_wins,
            'total_losses': total_losses,
            'win_rate': round(total_wins / max(1, total_closed) * 100, 1),
            'profit_factor': round(total_gross_w / max(1, total_gross_l), 2),
            'avg_win': round(total_gross_w / max(1, total_wins)),
            'avg_loss': round(total_gross_l / max(1, total_losses)),
            'total_costs': round(total_costs),
            'cost_drag_pct': cost_drag_pct,
            'total_unrealized': round(total_unrealized),
        },
        'risk': {
            'dd_pct': cap['dd_pct'],
            'max_dd_pct': cfg['max_drawdown_pct'],
            'daily_pnl': round(daily_pnl),
            'max_daily_loss': cfg['max_daily_loss'],
            'consec_losses': consec_losses,
            'max_consec_losses': cfg['max_consecutive_losses'],
            'open_trades': cap['open_count'],
            'max_concurrent': cfg['max_concurrent_trades'],
            'capital_utilization': round(cap['deployed'] / max(1, cap['current_capital']) * 100, 1),
        },
        'strategies': strategy_cards,
        'open_trades': open_trades,
        'closed_trades': closed_trades,
        'equity_curve': equity_points,
        'monthly_summary': monthly_summary,
    }


def _legs_summary(legs):
    """Build a human-readable legs summary like 'SELL 22700PE + BUY 22600PE'."""
    parts = []
    for l in legs:
        action = l.get('action', '?')
        strike = l.get('strike', 0)
        otype = l.get('option_type', '?')
        premium = l.get('premium', 0)
        parts.append(f'{action} {strike:.0f}{otype} @{premium:.1f}')
    return ' + '.join(parts)


def _enrich_open_trade(t, db):
    """Add per-leg greeks, breakevens, risk meter, mini-scenarios to an open trade."""
    from .core import bsm

    legs = t['legs_parsed']
    spot = t.get('last_check_spot') or t.get('entry_spot') or 0
    if spot <= 0:
        return

    dte = t.get('current_dte')
    if dte is None and t.get('target_expiry'):
        try:
            dte = max(0, (datetime.date.fromisoformat(t['target_expiry']) - datetime.date.today()).days)
        except Exception:
            dte = 14
    dte = dte or 14
    t_years = max(1, dte) / 365.0
    lot_size = t.get('lot_size') or 75
    lots = t.get('lots') or 1

    # Per-leg detail
    leg_details = []
    port_delta = port_gamma = port_theta = port_vega = 0.0

    for l in legs:
        entry_p = l.get('premium', 0)
        strike = l.get('strike', 0)
        otype = l.get('option_type', 'CE')
        iv = max(l.get('iv', 0.15), 0.01)
        action = l.get('action', 'BUY')
        sign = 1 if action == 'BUY' else -1

        try:
            g = bsm.bsm_greeks(spot, strike, t_years, 0.07, iv, otype)
        except Exception:
            g = {'price': entry_p, 'delta': 0, 'gamma': 0, 'theta': 0, 'vega': 0}

        current_p = g['price']
        leg_pnl = sign * (current_p - entry_p) * lot_size * lots
        d = g['delta'] * sign
        ga = g['gamma'] * sign
        th = g['theta'] * sign
        ve = g['vega'] * sign

        port_delta += d * lot_size * lots
        port_gamma += ga * lot_size * lots
        port_theta += th * lot_size * lots
        port_vega += ve * lot_size * lots

        leg_details.append({
            'strike': strike, 'option_type': otype, 'action': action,
            'entry_premium': round(entry_p, 2),
            'current_premium': round(current_p, 2),
            'change': round(current_p - entry_p, 2),
            'change_pct': round((current_p / max(0.01, entry_p) - 1) * 100, 1),
            'leg_pnl': round(leg_pnl),
            'delta': round(d, 4), 'gamma': round(ga, 6),
            'theta': round(th, 2), 'vega': round(ve, 2),
            'iv_pct': round(iv * 100, 1),
        })

    t['leg_details'] = leg_details
    t['greeks'] = {
        'delta': round(port_delta, 2),
        'gamma': round(port_gamma, 4),
        'theta_daily': round(port_theta, 2),
        'vega': round(port_vega, 2),
    }

    # Risk meter: where is P/L between max_loss and max_profit
    max_p = (t.get('max_profit_per_lot') or 0) * lots
    max_l = (t.get('max_loss_per_lot') or 0) * lots
    pnl = t.get('unrealized_pnl') or 0
    if max_p > 0 and max_l > 0:
        # Scale -1 (max loss) to +1 (max profit), 0 = breakeven
        total_range = max_p + max_l
        t['risk_position'] = round((pnl + max_l) / max(1, total_range) * 100, 1)
        t['profit_captured_pct'] = round(pnl / max(1, max_p) * 100, 1)
    else:
        t['risk_position'] = 50
        t['profit_captured_pct'] = 0

    # Breakevens: find spot levels where position P/L = 0
    breakevens = []
    strikes = sorted(set(l.get('strike', 0) for l in legs))
    if strikes:
        test_range = [spot * (1 + p / 100) for p in range(-10, 11)]
        test_range.extend([s for s in strikes])
        test_range.sort()
        prev_pnl = None
        for test_spot in test_range:
            test_pnl = 0
            for l in legs:
                s_sign = 1 if l.get('action') == 'BUY' else -1
                try:
                    p = bsm.bsm_price(test_spot, l['strike'], t_years, 0.07,
                                       max(l.get('iv', 0.15), 0.01), l['option_type'])
                except Exception:
                    p = l.get('premium', 0)
                test_pnl += s_sign * (p - l.get('premium', 0))
            if prev_pnl is not None and prev_pnl * test_pnl < 0:
                breakevens.append(round(test_spot))
            prev_pnl = test_pnl
    t['breakevens'] = breakevens

    # Mini-scenarios: P/L at spot ±1%, ±2%, ±5%
    scenarios = {}
    for pct_move in [-5, -2, -1, 1, 2, 5]:
        new_spot = spot * (1 + pct_move / 100)
        sc_pnl = 0
        for l in legs:
            s_sign = 1 if l.get('action') == 'BUY' else -1
            try:
                p = bsm.bsm_price(new_spot, l['strike'], t_years, 0.07,
                                   max(l.get('iv', 0.15), 0.01), l['option_type'])
            except Exception:
                p = l.get('premium', 0)
            sc_pnl += s_sign * (p - l.get('premium', 0))
        scenarios[f'{pct_move:+d}%'] = round(sc_pnl * lot_size * lots)
    t['scenarios'] = scenarios


# ── Self-check ──────────────────────────────────────────────────

def _self_check():
    """Verify autopilot logic with synthetic data."""
    import tempfile
    from . import paper_trade

    db = os.path.join(tempfile.gettempdir(), 'test_autopilot.db')
    if os.path.exists(db):
        os.remove(db)
    paper_trade.init_db(db)

    # 1. Config round-trip
    cfg = dict(DEFAULT_CONFIG)
    cfg['capital'] = 500000
    cfg['min_score'] = 7.0
    saved = save_config(cfg)
    loaded = load_config()
    assert loaded['capital'] == 500000
    assert loaded['min_score'] == 7.0

    # 2. Config bounds validation
    bad = {'capital': -100, 'min_score': 999, 'max_concurrent_trades': 100}
    validated = save_config(bad)
    assert validated['capital'] == 100_000  # clamped to min
    assert validated['min_score'] == 10.0   # clamped to max
    assert validated['max_concurrent_trades'] == 5  # clamped to max

    # 3. Decision log
    _log_decision(db, 'test123', 'morning', 'test_action', 'test reason')
    log_entries = get_decision_log(db, limit=5)
    assert len(log_entries) == 1
    assert log_entries[0]['action'] == 'test_action'

    # 4. Preflight — weekend check
    cfg_test = dict(DEFAULT_CONFIG)
    cfg_test['enabled'] = True
    save_config(cfg_test)

    # 5. Capital state with empty DB
    cap = _capital_state(cfg_test, db)
    assert cap['current_capital'] == cfg_test['capital']
    assert cap['open_count'] == 0
    assert cap['can_enter'] is True

    # 6. Entry logic — score too low
    fake_rec = {'score': 3.0, 'strategy': 'test', 'symbol': 'NIFTY'}
    should, reason = _should_enter(fake_rec, cfg_test, cap, db)
    assert should is False
    assert 'Score' in reason

    # 7. Entry logic — max concurrent
    cfg_test['max_concurrent_trades'] = 0
    save_config(cfg_test)
    cap_full = dict(cap)
    cap_full['open_count'] = 5
    should, reason = _should_enter({'score': 9.0, 'strategy': 'x', 'symbol': 'NIFTY'},
                                   load_config(), cap_full, db)
    assert should is False

    # Restore config
    save_config(DEFAULT_CONFIG)

    # Cleanup
    os.remove(db)
    if os.path.exists(_CONFIG_FILE):
        os.remove(_CONFIG_FILE)
    print("autopilot.py: self-check PASSED")


CRON_TAG = '# autopilot-managed'


def _cron_lines():
    """Build crontab lines for autopilot scan times."""
    import sys
    venv_python = sys.executable
    module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = load_config()
    times = cfg.get('scan_times', ['09:45', '15:20'])
    lines = []
    for t in sorted(times):
        h, m = t.split(':')
        lines.append(f'{m} {h} * * 1-5  cd "{module_dir}" && "{venv_python}" -m options.autopilot run  {CRON_TAG}')
    return lines


def install_cron():
    """Install autopilot cron jobs. Idempotent — replaces existing ones."""
    import subprocess
    new_lines = _cron_lines()
    try:
        existing = subprocess.run(['crontab', '-l'], capture_output=True, text=True).stdout
    except Exception:
        existing = ''
    kept = [l for l in existing.splitlines() if CRON_TAG not in l]
    kept.extend(new_lines)
    final = '\n'.join(kept) + '\n'
    subprocess.run(['crontab', '-'], input=final, text=True, check=True)
    return {'installed': len(new_lines), 'lines': new_lines}


def uninstall_cron():
    """Remove autopilot cron jobs."""
    import subprocess
    try:
        existing = subprocess.run(['crontab', '-l'], capture_output=True, text=True).stdout
    except Exception:
        return {'removed': 0}
    kept = [l for l in existing.splitlines() if CRON_TAG not in l]
    final = '\n'.join(kept) + '\n' if kept else ''
    if final.strip():
        subprocess.run(['crontab', '-'], input=final, text=True, check=True)
    else:
        subprocess.run(['crontab', '-r'], capture_output=True)
    return {'removed': 1}


def _print_cron_setup():
    """Print crontab lines for autopilot scheduling."""
    lines = _cron_lines()
    print('\n  Crontab lines (auto-installed on enable):\n')
    for l in lines:
        print(f'  {l}')
    print(f'\n  Runs on weekdays only. Holiday/token checks are built in.\n')


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(name)s %(levelname)s %(message)s')

    args = sys.argv[1:]
    cmd = args[0] if args else 'status'

    if cmd == 'selfcheck':
        _self_check()
    elif cmd == 'run':
        cfg = load_config()
        if not cfg.get('enabled'):
            print('Autopilot is DISABLED. Enable with: python -m options.autopilot enable')
            sys.exit(0)
        cycle_type = args[1] if len(args) > 1 else 'auto'
        result = run_cycle(cycle_type=cycle_type)
        print(f'Cycle {result["cycle_id"]}: '
              f'{result["entries"]} entries, {result["exits"]} exits, '
              f'{result["checks"]} checked, {result["skips"]} skipped')
        if result.get('errors'):
            for e in result['errors']:
                print(f'  ERROR: {e}')
        if result.get('preflight'):
            print(f'  Skipped: {result["preflight"]}')
    elif cmd == 'enable':
        enable()
        print('Autopilot ENABLED')
    elif cmd == 'disable':
        disable()
        print('Autopilot DISABLED')
    elif cmd == 'emergency':
        result = emergency_stop()
        print(f'Emergency stop: {result["trades_closed"]} trades closed')
    elif cmd == 'status':
        s = status()
        print(f'Enabled: {s["enabled"]}')
        print(f'Scan times: {", ".join(s["scan_times"])}')
        cap = s['capital']
        print(f'Capital: ₹{cap["current_capital"]:,.0f}  '
              f'Deployed: ₹{cap["deployed"]:,.0f}  '
              f'Open: {cap["open_count"]}  DD: {cap["dd_pct"]:.1f}%')
        if s['last_cycle']:
            print(f'Last cycle: {s["last_cycle"]["timestamp"]}')
    elif cmd == 'cron':
        _print_cron_setup()
    elif cmd == 'log':
        limit = int(args[1]) if len(args) > 1 else 20
        entries = get_decision_log(limit=limit)
        for e in entries:
            ts = e['timestamp'][:16] if e.get('timestamp') else '?'
            print(f'  {ts}  {e.get("action","?"):20s}  {e.get("symbol",""):10s}  {e.get("reason","")[:60]}')
    else:
        print('Usage: python -m options.autopilot <command>')
        print('  run [morning|eod]  — run one cycle (cron calls this)')
        print('  enable / disable   — toggle autopilot')
        print('  emergency          — disable + close all autopilot trades')
        print('  status             — show current state')
        print('  log [N]            — show last N decisions')
        print('  cron               — print crontab setup lines')
        print('  selfcheck          — run self-check')
