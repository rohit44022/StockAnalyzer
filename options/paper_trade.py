"""
Paper trading: end-to-end workflow from signal to P/L tracking.

Usage:
  .venv/bin/python -m options.paper_trade recommend [NIFTY|BANKNIFTY]
  .venv/bin/python -m options.paper_trade enter [REC_ID]
  .venv/bin/python -m options.paper_trade check [--spot SPOT]
  .venv/bin/python -m options.paper_trade exit TRADE_ID [--spot SPOT] [--reason TEXT]
  .venv/bin/python -m options.paper_trade journal
  .venv/bin/python -m options.paper_trade expire

Schedule daily check via cron (after EOD):
  40 16 * * 1-5 cd /path && .venv/bin/python -m options.paper_trade check
"""

import os
import sys
import json
import math
import sqlite3
import datetime
import logging
import argparse

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s %(levelname)s %(message)s',
)
log = logging.getLogger(__name__)

_DB_NAME = 'paper_trades.db'
DEFAULT_CAPITAL = 500_000
SLIPPAGE_PER_LEG = 2.0  # ₹2 per point per unit; total = 2 × legs × lot_size × lots

_last_good_spot = {}  # {symbol: (spot, timestamp)}


def _db_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), _DB_NAME)


def _connect(db=None):
    conn = sqlite3.connect(db or _db_path(), timeout=10)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


def init_db(db=None):
    db = db or _db_path()
    conn = _connect(db)
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS recommendations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        symbol TEXT NOT NULL,
        strategy TEXT NOT NULL,
        spot REAL NOT NULL,
        legs TEXT NOT NULL,
        lots INTEGER NOT NULL,
        lot_size INTEGER NOT NULL,
        max_profit_per_lot REAL,
        max_loss_per_lot REAL,
        cost_per_lot REAL,
        margin_per_lot REAL,
        entry_gate TEXT,
        audit TEXT,
        signals TEXT,
        reasons TEXT,
        score REAL,
        vix REAL,
        dte INTEGER,
        status TEXT DEFAULT 'pending'
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recommendation_id INTEGER,
        opened_at TEXT NOT NULL,
        symbol TEXT NOT NULL,
        strategy TEXT NOT NULL,
        entry_spot REAL NOT NULL,
        legs TEXT NOT NULL,
        lots INTEGER NOT NULL,
        lot_size INTEGER NOT NULL,
        capital_risked REAL,
        entry_cost REAL,
        entry_reason TEXT,
        target_expiry TEXT,
        status TEXT DEFAULT 'open',
        closed_at TEXT,
        exit_spot REAL,
        exit_reason TEXT,
        exit_cost REAL,
        gross_pnl REAL,
        net_pnl REAL,
        FOREIGN KEY (recommendation_id) REFERENCES recommendations(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS daily_checks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id INTEGER NOT NULL,
        check_date TEXT NOT NULL,
        spot REAL NOT NULL,
        dte INTEGER,
        current_pnl REAL,
        adjustments TEXT,
        max_urgency INTEGER,
        FOREIGN KEY (trade_id) REFERENCES trades(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS strategy_lifecycle (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        strategy_key TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL DEFAULT 'INCUBATING',
        start_date TEXT NOT NULL,
        wfa_report_path TEXT,
        wfa_oos_trades_json TEXT,
        wfa_avg_pnl REAL,
        wfa_std_pnl REAL,
        wfa_max_dd_pct REAL,
        wfa_expected_return REAL,
        mc_abort_dd_pct REAL,
        t_test_compare_p REAL,
        trade_count INTEGER DEFAULT 0,
        current_dd_pct REAL DEFAULT 0,
        return_efficiency REAL,
        dd_efficiency REAL,
        last_checked TEXT,
        graduation_date TEXT,
        abort_date TEXT,
        abort_reason TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS autopilot_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        cycle_id TEXT NOT NULL,
        cycle_type TEXT NOT NULL,
        action TEXT NOT NULL,
        symbol TEXT,
        trade_id INTEGER,
        recommendation_id INTEGER,
        strategy TEXT,
        score REAL,
        spot REAL,
        vix REAL,
        pnl REAL,
        reason TEXT NOT NULL,
        context_json TEXT
    )''')

    # Migrate existing DBs
    cols = {r[1] for r in c.execute("PRAGMA table_info(trades)").fetchall()}
    if 'target_expiry' not in cols:
        c.execute("ALTER TABLE trades ADD COLUMN target_expiry TEXT")
    if 'source' not in cols:
        c.execute("ALTER TABLE trades ADD COLUMN source TEXT DEFAULT 'manual'")
    if 'max_profit_per_lot' not in cols:
        c.execute("ALTER TABLE trades ADD COLUMN max_profit_per_lot REAL")
    if 'max_loss_per_lot' not in cols:
        c.execute("ALTER TABLE trades ADD COLUMN max_loss_per_lot REAL")
    if 'margin_per_lot' not in cols:
        c.execute("ALTER TABLE trades ADD COLUMN margin_per_lot REAL")
    if 'live_status' not in cols:
        c.execute("ALTER TABLE trades ADD COLUMN live_status TEXT")
    if 'standing_sl_ids' not in cols:
        c.execute("ALTER TABLE trades ADD COLUMN standing_sl_ids TEXT")

    c.execute('''CREATE TABLE IF NOT EXISTS autopilot_alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        severity TEXT NOT NULL,
        category TEXT NOT NULL,
        title TEXT NOT NULL,
        detail TEXT,
        context_json TEXT,
        acknowledged INTEGER DEFAULT 0
    )''')

    c.execute('CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_trades_source_status ON trades(source, status)')

    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA busy_timeout=10000')

    conn.commit()
    conn.close()


# ── Phase 7: Incubation lifecycle (Davey Ch.14) ─────────────────


def incubate(strategy_key, wfa_report_path, db=None):
    """
    Start incubation for a Davey-validated strategy.
    Loads WFA report, extracts baseline metrics, computes abort threshold,
    and inserts a lifecycle row with status='INCUBATING'.
    """
    from .backtest import metrics, monte_carlo

    db = db or _db_path()
    init_db(db)

    if not os.path.exists(wfa_report_path):
        return {'status': 'error', 'reason': f'Report not found: {wfa_report_path}'}

    with open(wfa_report_path) as f:
        report = json.load(f)

    # Extract trades for baseline comparison
    # Priority: WFA OOS trades > full trade log
    wfa_section = report.get('walk_forward', {})
    oos_trades = wfa_section.get('oos_trades', [])
    if not oos_trades:
        oos_trades = report.get('trades', [])

    if not oos_trades:
        return {'status': 'error', 'reason': 'No trades found in report'}

    # Normalize trade keys — reports may use 'net'/'gross'/'costs'
    oos_trades = [{'net_pnl': t.get('net_pnl', t.get('net', 0)),
                   'gross_pnl': t.get('gross_pnl', t.get('gross', 0)),
                   'costs_total': t.get('costs_total', t.get('costs', 0))}
                  for t in oos_trades]

    # Guard: don't silently overwrite a finalized strategy
    conn_check = _connect(db)
    conn_check.row_factory = sqlite3.Row
    existing = conn_check.execute(
        'SELECT status FROM strategy_lifecycle WHERE strategy_key=?',
        (strategy_key,)
    ).fetchone()
    conn_check.close()
    if existing and existing['status'] in ('GRADUATED', 'ABORTED'):
        return {'status': 'error',
                'reason': f'{strategy_key} is {existing["status"]} — '
                          f'use abort first or choose a different key'}

    # Baseline metrics
    pnls = [t.get('net_pnl', 0) for t in oos_trades]
    avg_pnl = sum(pnls) / len(pnls) if pnls else 0.0
    if len(pnls) >= 2:
        var = sum((p - avg_pnl) ** 2 for p in pnls) / (len(pnls) - 1)
        std_pnl = math.sqrt(var)
    else:
        std_pnl = 0.0

    # DD from report metrics
    risk_metrics = report.get('risk_metrics', {})
    dd_info = risk_metrics.get('max_drawdown', {})
    wfa_max_dd = dd_info.get('pct', 0.0) if isinstance(dd_info, dict) else 0.0

    # Expected return from summary
    summary = report.get('summary', {})
    expected_return = summary.get('net_pnl', sum(pnls))

    # MC abort threshold
    mc_section = report.get('monte_carlo', {})
    abort = monte_carlo.abort_threshold(wfa_max_dd, mc_section if mc_section else None)

    # Davey gates check
    gates = report.get('davey_gates', {})
    all_pass = all(g.get('pass') for g in gates.values()) if gates else False
    if not all_pass:
        log.warning(f'{strategy_key}: not all Davey gates pass — incubating anyway for monitoring')

    conn = _connect(db)
    try:
        conn.execute(
            '''INSERT OR REPLACE INTO strategy_lifecycle
               (strategy_key, status, start_date, wfa_report_path,
                wfa_oos_trades_json, wfa_avg_pnl, wfa_std_pnl,
                wfa_max_dd_pct, wfa_expected_return, mc_abort_dd_pct,
                last_checked)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            (strategy_key, 'INCUBATING',
             datetime.date.today().isoformat(), wfa_report_path,
             json.dumps(oos_trades, default=_json_default),
             round(avg_pnl, 2), round(std_pnl, 2),
             round(wfa_max_dd, 2), round(expected_return, 2),
             abort['abort_dd_pct'],
             datetime.datetime.now().isoformat())
        )
        conn.commit()
    finally:
        conn.close()

    result = {
        'status': 'incubating',
        'strategy_key': strategy_key,
        'wfa_trades': len(oos_trades),
        'avg_pnl': round(avg_pnl, 2),
        'std_pnl': round(std_pnl, 2),
        'expected_return': round(expected_return, 2),
        'wfa_max_dd_pct': round(wfa_max_dd, 2),
        'abort_dd_pct': abort['abort_dd_pct'],
        'abort_source': abort['source'],
        'davey_gates_pass': all_pass,
    }
    log.info(f'Incubation started: {strategy_key} | abort DD={abort["abort_dd_pct"]}% '
             f'| baseline {len(oos_trades)} trades, avg ₹{avg_pnl:,.0f}')
    return result


def check_lifecycle(strategy_key, db=None):
    """
    Evaluate incubation state against Davey Ch.14 graduation/abort criteria.

    Graduation (ALL must be true):
      1. duration >= 3 months          (Davey Ch.14)
      2. trade_count >= 30             (Davey Ch.6)
      3. t_test_compare p > 0.44       (Davey Ch.14: 56% not different)
      4. return_efficiency 0.70-1.30   (Davey Ch.23)
      5. dd_efficiency > 0.0           (Davey Ch.23)
      6. equity above 2σ lower band   (Davey Ch.23)
      7. return/DD > 2.0               (Davey Ch.7)
      8. profit_factor > 1.0           (Davey Ch.7)
      9. max DD < 40%                  (Davey Ch.7)
      10. MC risk of ruin < 10%        (Davey Ch.14)
      11. current DD < abort threshold (Davey Ch.14)

    Abort (ANY one):
      - current DD > abort threshold
      - t_test_compare p < 0.10 with n >= 20 (distributions diverged)
    """
    from .backtest import metrics, monte_carlo

    db = db or _db_path()
    init_db(db)

    conn = _connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        'SELECT * FROM strategy_lifecycle WHERE strategy_key=?',
        (strategy_key,)
    ).fetchone()

    if not row:
        conn.close()
        return {'status': 'error', 'reason': f'No lifecycle for {strategy_key}'}

    if row['status'] in ('GRADUATED', 'ABORTED'):
        conn.close()
        return {'status': row['status'].lower(), 'strategy_key': strategy_key,
                'reason': row['abort_reason'] or 'previously finalized'}

    # Load closed paper trades for this strategy
    paper_rows = conn.execute(
        "SELECT net_pnl, gross_pnl, entry_cost, exit_cost FROM trades "
        "WHERE strategy=? AND status='closed' ORDER BY closed_at",
        (strategy_key,)
    ).fetchall()
    conn.close()

    paper_trades = [{'net_pnl': r['net_pnl'],
                     'gross_pnl': r['gross_pnl'] or 0,
                     'costs_total': (r['entry_cost'] or 0) + (r['exit_cost'] or 0)}
                    for r in paper_rows if r['net_pnl'] is not None]
    n_paper = len(paper_trades)

    # Load WFA baseline
    wfa_trades = json.loads(row['wfa_oos_trades_json'] or '[]')
    avg_pnl = row['wfa_avg_pnl'] or 0.0
    std_pnl = row['wfa_std_pnl'] or 0.0
    expected_return = row['wfa_expected_return'] or 0.0
    expected_dd = row['wfa_max_dd_pct'] or 0.0
    abort_dd = row['mc_abort_dd_pct'] or 50.0

    # Duration
    start = datetime.date.fromisoformat(row['start_date'])
    months_elapsed = (datetime.date.today() - start).days / 30.44

    # Compute paper trade metrics
    paper_pnls = [t['net_pnl'] for t in paper_trades]
    actual_return = sum(paper_pnls)
    equity = metrics.equity_from_trades(paper_trades, initial=DEFAULT_CAPITAL)
    dd = metrics.max_drawdown(equity)
    actual_dd = dd['pct'] if isinstance(dd, dict) else dd

    # Davey Ch.23: efficiencies
    ret_eff = metrics.return_efficiency(actual_return, expected_return)
    dd_eff = metrics.dd_efficiency(actual_dd, expected_dd)

    # Davey Ch.23: equity bands
    bands = metrics.equity_bands(n_paper, avg_pnl, std_pnl)
    above_2sigma_floor = actual_return >= bands['lower_2sigma']

    # Davey Ch.14: t-test compare (only meaningful with enough trades)
    t_compare = metrics.t_test_compare(paper_trades, wfa_trades)

    # Davey Ch.7: standard gates on paper trades
    paper_metrics = metrics.compute_all(paper_trades) if n_paper >= 3 else {}
    ret_dd = paper_metrics.get('return_dd_ratio', 0)
    pf = paper_metrics.get('profit_factor', 0)

    # MC on paper trades (if enough)
    mc_ruin = 0.0
    if n_paper >= 3:
        mc = monte_carlo.run_mc(paper_trades, {'n_sims': 10_000, 'seed': 42})
        mc_ruin = mc.get('risk_of_ruin_pct', 0)

    # ── Abort checks ──
    abort_reason = None
    if actual_dd > abort_dd:
        abort_reason = f'DD {actual_dd:.1f}% > abort threshold {abort_dd:.1f}%'
    elif n_paper >= 20 and t_compare['p_value'] < 0.10:
        abort_reason = (f't-test p={t_compare["p_value"]:.4f} < 0.10 with '
                        f'{n_paper} trades — distributions diverged')

    # ── Graduation checks ──
    graduation_criteria = {
        'duration_months': {'value': round(months_elapsed, 1), 'threshold': '>=3', 'pass': months_elapsed >= 3},
        'trade_count': {'value': n_paper, 'threshold': '>=30', 'pass': n_paper >= 30},
        't_test_compare': {'value': round(t_compare['p_value'], 4), 'threshold': '>0.44', 'pass': n_paper >= 3 and t_compare['pass_incubation']},
        'return_efficiency': {'value': round(ret_eff, 4), 'threshold': '0.70-1.30', 'pass': n_paper >= 3 and (0.70 <= ret_eff <= 1.30 if expected_return > 0 else ret_eff >= 0)},
        'dd_efficiency': {'value': round(dd_eff, 4), 'threshold': '>0.0', 'pass': n_paper >= 3 and dd_eff > 0.0},
        'equity_above_2sigma': {'value': round(actual_return, 2), 'floor': round(bands['lower_2sigma'], 2), 'pass': n_paper >= 3 and above_2sigma_floor},
        'return_dd_ratio': {'value': round(ret_dd, 2), 'threshold': '>2.0', 'pass': ret_dd > 2.0},
        'profit_factor': {'value': round(pf, 2), 'threshold': '>1.0', 'pass': pf > 1.0},
        'max_dd_pct': {'value': round(actual_dd, 2), 'threshold': '<40%', 'pass': actual_dd < 40},
        'mc_risk_of_ruin': {'value': round(mc_ruin, 2), 'threshold': '<10%', 'pass': n_paper >= 3 and mc_ruin < 10},
        'below_abort_threshold': {'value': round(actual_dd, 2), 'threshold': f'<{abort_dd}%', 'pass': actual_dd < abort_dd},
    }

    # Determine status
    if abort_reason:
        new_status = 'ABORTED'
    elif all(c['pass'] for c in graduation_criteria.values()):
        new_status = 'GRADUATED'
    else:
        new_status = 'INCUBATING'

    # Update DB
    conn = _connect(db)
    try:
        updates = {
            'trade_count': n_paper,
            'current_dd_pct': round(actual_dd, 2),
            'return_efficiency': round(ret_eff, 4),
            'dd_efficiency': round(dd_eff, 4),
            't_test_compare_p': round(t_compare['p_value'], 6),
            'last_checked': datetime.datetime.now().isoformat(),
            'status': new_status,
        }
        if new_status == 'GRADUATED':
            updates['graduation_date'] = datetime.date.today().isoformat()
        elif new_status == 'ABORTED':
            updates['abort_date'] = datetime.date.today().isoformat()
            updates['abort_reason'] = abort_reason

        set_clause = ', '.join(f'{k}=?' for k in updates)
        conn.execute(
            f'UPDATE strategy_lifecycle SET {set_clause} WHERE strategy_key=?',
            (*updates.values(), strategy_key)
        )
        conn.commit()
    finally:
        conn.close()

    result = {
        'status': new_status.lower(),
        'strategy_key': strategy_key,
        'months_elapsed': round(months_elapsed, 1),
        'trade_count': n_paper,
        'actual_return': round(actual_return, 2),
        'expected_return': round(expected_return, 2),
        'return_efficiency': round(ret_eff, 4),
        'actual_dd_pct': round(actual_dd, 2),
        'dd_efficiency': round(dd_eff, 4),
        'abort_dd_pct': abort_dd,
        't_test_p': round(t_compare['p_value'], 4),
        'graduation_criteria': graduation_criteria,
    }
    if abort_reason:
        result['abort_reason'] = abort_reason

    return result


def lifecycle_status(strategy_key=None, db=None):
    """Print lifecycle status for one or all strategies."""
    db = db or _db_path()
    init_db(db)

    conn = _connect(db)
    conn.row_factory = sqlite3.Row
    if strategy_key:
        rows = conn.execute(
            'SELECT * FROM strategy_lifecycle WHERE strategy_key=?', (strategy_key,)
        ).fetchall()
    else:
        rows = conn.execute('SELECT * FROM strategy_lifecycle ORDER BY status, strategy_key').fetchall()
    conn.close()

    if not rows:
        print('No strategies in lifecycle tracking.')
        return {'status': 'NOT_FOUND'} if strategy_key else []

    for r in rows:
        months = (datetime.date.today() - datetime.date.fromisoformat(r['start_date'])).days / 30.44
        print(f"\n{'═' * 60}")
        print(f"  {r['strategy_key']}  —  {r['status']}")
        print(f"{'═' * 60}")
        print(f"  Started:         {r['start_date']} ({months:.1f} months)")
        print(f"  Trades:          {r['trade_count'] or 0} / 30 required")
        print(f"  Return eff:      {r['return_efficiency'] or '-'}")
        print(f"  DD eff:          {r['dd_efficiency'] or '-'}")
        print(f"  Current DD:      {r['current_dd_pct'] or 0:.1f}% / {r['mc_abort_dd_pct'] or 50:.1f}% abort")
        print(f"  t-test p:        {r['t_test_compare_p'] or '-'} (want > 0.44)")
        print(f"  Last checked:    {r['last_checked'] or 'never'}")
        if r['status'] == 'GRADUATED':
            print(f"  Graduated:       {r['graduation_date']}")
        elif r['status'] == 'ABORTED':
            print(f"  Aborted:         {r['abort_date']} — {r['abort_reason']}")

    results = [{'status': r['status'], 'strategy_key': r['strategy_key'],
                'trade_count': r['trade_count'] or 0,
                'current_dd_pct': r['current_dd_pct'] or 0.0,
                'mc_abort_dd_pct': r['mc_abort_dd_pct'] or 50.0,
                'return_efficiency': r['return_efficiency'],
                'dd_efficiency': r['dd_efficiency'],
                't_test_compare_p': r['t_test_compare_p'],
                'last_checked': r['last_checked']} for r in rows]
    return results[0] if strategy_key else results


def recommend(symbol='NIFTY', capital=DEFAULT_CAPITAL, db=None):
    """Full pipeline → recommend.generate() → risk checks → store recommendation."""
    from .data import dhan_fetch, pipeline, chain as chain_mod
    from .strategies import recommend as recommend_mod
    from .risk import sizing, scenarios, audit as audit_mod

    db = db or _db_path()
    init_db(db)
    lot_size = chain_mod.lot_size(symbol)

    # 1. Fetch chain
    log.info(f'[{symbol}] Fetching chain from Dhan...')
    try:
        chain_df, spot = dhan_fetch.fetch_multi_expiry_chain(symbol, n_expiries=3)
    except Exception as e:
        return {'status': 'error', 'reason': f'Dhan fetch failed: {e}'}
    if spot and spot > 0:
        _last_good_spot[symbol] = (spot, datetime.datetime.now())
    if chain_df.empty or not spot or spot <= 0:
        cached = _last_good_spot.get(symbol)
        if cached:
            age_min = (datetime.datetime.now() - cached[1]).total_seconds() / 60
            if age_min < 30:
                log.warning(f'[{symbol}] Spot=0 from API, using cached {cached[0]:.2f} ({age_min:.0f}m old)')
                spot = cached[0]
            else:
                return {'status': 'error', 'reason': f'Spot stale ({age_min:.0f}m) and chain empty'}
        else:
            return {'status': 'error', 'reason': 'Empty chain or invalid spot from Dhan'}
    log.info(f'[{symbol}] {len(chain_df)} rows, spot={spot:.2f}')

    # 2. VIX
    vix_value = None
    try:
        from .data import india_vix
        vdf = india_vix.load_vix_history()
        if not vdf.empty:
            vix_value = float(vdf.iloc[-1]['close'])
    except Exception as e:
        log.warning(f'VIX load failed: {e}')
    if vix_value is None:
        # ponytail: don't pretend VIX=14 — that silently enables premium-selling.
        # Use chain ATM IV as proxy; if that also fails, flag it.
        try:
            atm = chain_df.iloc[(chain_df['strike'] - spot).abs().argsort()[:2]]
            vix_value = float(atm['iv'].mean()) * 100 if 'iv' in atm.columns else None
        except Exception:
            pass
        if vix_value is None:
            vix_value = 14.0
            log.warning('VIX unavailable, ATM IV unavailable — using fallback 14.0')

    # 3. Historical prices for vol forecast
    prices = None
    try:
        import pandas as pd
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidates = [
            f'{symbol}.csv',
            f'{symbol}.NS.csv',
            f'{symbol}BEES.NS.csv',
            f'{symbol}1.NS.csv',
        ]
        for fname in candidates:
            csv_path = os.path.join(base, 'stock_csv', fname)
            if os.path.exists(csv_path):
                raw = pd.read_csv(csv_path)['Close']
                prices = pd.to_numeric(raw, errors='coerce').dropna().values[-300:]
                if len(prices) >= 30:
                    log.info(f'Loaded {len(prices)} prices from {fname}')
                    break
                prices = None
    except Exception:
        pass

    # 4-8. Unified recommendation pipeline (signals → scorer → builder → cost → margin)
    result = recommend_mod.generate(
        chain_df, spot, vix_value=vix_value, prices=prices,
        capital=capital, symbol=symbol, lot_size=lot_size)

    if not result.get('recommendations'):
        reason = result.get('error', 'No strategies passed signal/gate filters')
        return {'status': 'no_recommendation', 'reason': reason}

    sigs = result['signals']
    candidates = result['recommendations'][:3]

    # Try top-3: if #1 fails entry gate, try #2, #3
    reco = gate = lots = max_loss_per_lot = None
    for candidate in candidates:
        _key = candidate['strategy_key']
        _legs = candidate['raw_legs']
        _dte = candidate['dte']

        # Position sizing
        _max_loss_unit = candidate.get('max_loss') or float('-inf')
        if _max_loss_unit != float('-inf') and _max_loss_unit < 0:
            _max_loss_per_lot = abs(_max_loss_unit) * lot_size
        else:
            _max_loss_per_lot = spot * lot_size * 0.05

        _kelly_frac = 0.10
        conn_k = _connect(db)
        conn_k.row_factory = sqlite3.Row
        lc_row = conn_k.execute(
            'SELECT wfa_oos_trades_json FROM strategy_lifecycle WHERE strategy_key=? AND status=?',
            (_key, 'INCUBATING')
        ).fetchone()
        conn_k.close()
        if lc_row and lc_row['wfa_oos_trades_json']:
            wfa_trades = json.loads(lc_row['wfa_oos_trades_json'])
            pnls = [t.get('net_pnl', 0) for t in wfa_trades]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]
            if wins and losses:
                wr = len(wins) / len(pnls)
                avg_w = sum(wins) / len(wins)
                avg_l = abs(sum(losses) / len(losses))
                _kelly_frac = sizing.kelly_fraction(wr, avg_w, avg_l)

        size = sizing.position_size(capital, _kelly_frac, _max_loss_per_lot, lot_size=lot_size)
        _lots = max(1, size.get('lots', 1))

        _vp_conf = candidate.get('vp_confidence', 'moderate')
        _vp_scale = {'strong': 1.0, 'moderate': 0.75, 'weak': 0.5}.get(_vp_conf, 0.75)
        _lots = max(1, int(_lots * _vp_scale))

        # Entry gate (Sinclair Ch.8)
        _daily_theta = abs(candidate.get('daily_theta', 0)) * lot_size
        _gate = scenarios.entry_gate(_legs, spot, daily_theta=max(_daily_theta, 0.01),
                                     lot_size=lot_size, dte=_dte)

        reco, gate, lots, max_loss_per_lot = candidate, _gate, _lots, _max_loss_per_lot
        if _gate.get('passes', False):
            log.info(f'[{symbol}] Candidate {_key} passes entry gate')
            break
        log.info(f'[{symbol}] Candidate {_key} failed gate (ratio={_gate.get("ratio",0):.1f}), trying next')

    top_key = reco['strategy_key']
    legs = reco['raw_legs']
    dte = reco['dte']

    # 10b. Opposite-direction check: warn if new strategy conflicts with open positions
    conn_chk = _connect(db)
    conn_chk.row_factory = sqlite3.Row
    try:
        open_trades = conn_chk.execute(
            "SELECT strategy FROM trades WHERE status='open' AND symbol=?", (symbol,)
        ).fetchall()
        if open_trades:
            from .strategies import registry
            new_strat = registry.get(top_key)
            new_bias = getattr(new_strat, 'outlook', 'neutral') if new_strat else 'neutral'
            for ot in open_trades:
                old_strat = registry.get(ot['strategy'])
                old_bias = getattr(old_strat, 'outlook', 'neutral') if old_strat else 'neutral'
                if (new_bias == 'bullish' and old_bias == 'bearish') or \
                   (new_bias == 'bearish' and old_bias == 'bullish'):
                    log.warning(f'[{symbol}] Opposite-direction conflict: {top_key}({new_bias}) vs open {ot["strategy"]}({old_bias})')
                    return {'status': 'blocked', 'reason': f'Opposite-direction conflict: {top_key} vs open {ot["strategy"]}'}
    finally:
        conn_chk.close()

    # 11. Pre-trade audit
    net_premium = sum(
        (l.get('premium', 0) if l.get('action') == 'SELL' else -l.get('premium', 0))
        for l in legs
    )
    trade_for_audit = {
        'symbol': symbol,
        'strategy': top_key,
        'legs': [{'strike': l['strike'], 'option_type': l['option_type'],
                  'action': l['action'], 'premium': l.get('premium', 0)}
                 for l in legs],
        'net_premium': net_premium * lot_size,
        'lots': lots,
        'entry_rationale': f'Signals: {", ".join(reco["reasons"][:5])}',
        'estimated_margin': reco.get('margin_required') or 0,
        'available_capital': capital,
        'max_loss': max_loss_per_lot * lots,
        'exit_plan': {
            'stop_loss': -max_loss_per_lot if max_loss_per_lot != float('-inf') else None,
            'take_profit': (reco.get('max_profit') or 0) * lot_size * 0.5,
        },
    }
    audit_result = audit_mod.audit_trade(trade_for_audit, capital, capital)

    # 12. Assemble and store
    rec = {
        'status': 'recommended',
        'timestamp': datetime.datetime.now().isoformat(),
        'symbol': symbol,
        'strategy': top_key,
        'spot': spot,
        'dte': dte,
        'legs': legs,
        'lots': lots,
        'lot_size': lot_size,
        'score': reco['final_score'],
        'reasons': reco['reasons'],
        'max_profit_per_lot': round((reco.get('max_profit') or 0) * lot_size, 2),
        'max_loss_per_lot': round(max_loss_per_lot, 2),
        'cost_per_lot': reco.get('round_trip_cost', 0),
        'margin_per_lot': round(reco.get('margin_required') or 0, 2),
        'entry_gate': gate,
        'audit': audit_result,
        'signals': sigs,
        'vix': vix_value,
        'regime': reco.get('regime'),
        'vp_confidence': reco.get('vp_confidence'),
        'build_warnings': reco.get('build_warnings', []),
    }

    conn = _connect(db)
    conn.execute(
        '''INSERT INTO recommendations
           (timestamp, symbol, strategy, spot, legs, lots, lot_size,
            max_profit_per_lot, max_loss_per_lot, cost_per_lot, margin_per_lot,
            entry_gate, audit, signals, reasons, score, vix, dte, status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (rec['timestamp'], symbol, top_key, spot,
         json.dumps(legs, default=_json_default), lots, lot_size,
         rec['max_profit_per_lot'], rec['max_loss_per_lot'],
         rec['cost_per_lot'], rec['margin_per_lot'],
         json.dumps(gate, default=_json_default),
         json.dumps(audit_result, default=_json_default),
         json.dumps(sigs, default=_json_default),
         json.dumps(reco['reasons']), rec['score'], vix_value, dte, 'pending')
    )
    conn.commit()
    rec['recommendation_id'] = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.close()
    return rec


def enter(recommendation_id=None, db=None):
    """Confirm a pending recommendation as a paper trade."""
    db = db or _db_path()
    init_db(db)
    conn = _connect(db)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('BEGIN IMMEDIATE')

        if recommendation_id is None:
            row = conn.execute(
                "SELECT * FROM recommendations WHERE status='pending' "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM recommendations WHERE id=?", (recommendation_id,)
            ).fetchone()

        if row is None:
            conn.rollback()
            return {'status': 'error', 'reason': 'No pending recommendation found'}

        existing = conn.execute(
            "SELECT id FROM trades WHERE recommendation_id=?", (row['id'],)
        ).fetchone()
        if existing:
            conn.rollback()
            return {'status': 'error',
                    'reason': f'Recommendation #{row["id"]} already entered as trade #{existing["id"]}'}

        audit_result = json.loads(row['audit'])
        if audit_result.get('decision') == 'REJECT':
            reasons = audit_result.get('rejection_reasons', [])
            conn.rollback()
            return {'status': 'rejected', 'reason': f'Audit rejected: {reasons}'}

        legs = json.loads(row['legs'])

        from .core import cost_model
        cost_legs = [{'premium': l.get('premium', l.get('ltp', 0)),
                      'action': l['action']} for l in legs]
        cost_est = cost_model.round_trip_cost(cost_legs, lot_size=row['lot_size'])
        n_legs = len(legs)
        slippage = SLIPPAGE_PER_LEG * n_legs * row['lot_size'] * row['lots']
        entry_cost = round(cost_est.get('total', 0) * row['lots'] + slippage, 2)

        capital_risked = round(
            (row['max_loss_per_lot'] or row['spot'] * row['lot_size'] * 0.05) * row['lots'], 2
        )

        reasons_json = row['reasons'] or '[]'
        reasons = json.loads(reasons_json)
        sig_summary = '; '.join(reasons[:5]) if reasons else row['strategy']

        from .data import event_calendar
        target_exp = event_calendar.next_expiry(row['symbol'])

        now = datetime.datetime.now().isoformat()
        conn.execute(
            '''INSERT INTO trades
               (recommendation_id, opened_at, symbol, strategy, entry_spot, legs,
                lots, lot_size, capital_risked, entry_cost, entry_reason,
                target_expiry, status,
                max_profit_per_lot, max_loss_per_lot, margin_per_lot)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (row['id'], now, row['symbol'], row['strategy'], row['spot'],
             row['legs'], row['lots'], row['lot_size'],
             capital_risked, entry_cost, sig_summary,
             target_exp.isoformat(), 'open',
             row['max_profit_per_lot'], row['max_loss_per_lot'], row['margin_per_lot'])
        )
        conn.execute("UPDATE recommendations SET status='entered' WHERE id=?", (row['id'],))
        trade_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    log.info(f'Trade #{trade_id} entered: {row["strategy"]} {row["symbol"]} '
             f'{row["lots"]}L @{row["spot"]:.0f}')
    return {
        'status': 'entered', 'trade_id': trade_id,
        'symbol': row['symbol'], 'strategy': row['strategy'],
        'spot': row['spot'], 'lots': row['lots'],
        'entry_cost': entry_cost, 'capital_risked': capital_risked,
    }


def daily_check(spot=None, db=None):
    """Check all open trades: reprice, run adjustments, log."""
    db = db or _db_path()
    init_db(db)
    conn = _connect(db)
    conn.row_factory = sqlite3.Row
    try:
        open_trades = conn.execute("SELECT * FROM trades WHERE status='open'").fetchall()
        if not open_trades:
            log.info('No open trades.')
            return []

        from .strategies import adjustments
        from .data import event_calendar
        from .core import bsm

        today = datetime.date.today()
        results = []

        # Pre-fetch chain for LTP pricing when any trade is near expiry
        _ltp_chain = None
        for t in open_trades:
            if t['target_expiry']:
                d = max(0, (datetime.date.fromisoformat(t['target_expiry']) - today).days)
                if d < 3:
                    try:
                        from .data import dhan_fetch
                        _ltp_chain, _ = dhan_fetch.fetch_multi_expiry_chain(
                            open_trades[0]['symbol'], n_expiries=1)
                    except Exception:
                        pass
                    break

        for trade in open_trades:
            symbol = trade['symbol']
            legs = json.loads(trade['legs'])
            entry_spot = trade['entry_spot']
            lot_size = trade['lot_size']

            trade_spot = spot
            if trade_spot is None:
                try:
                    from .data import dhan_fetch
                    trade_spot = dhan_fetch.fetch_spot(symbol)
                except Exception:
                    log.warning(f'Trade #{trade["id"]}: Dhan spot fetch failed, using entry spot')
                    trade_spot = entry_spot

            if trade['target_expiry']:
                exp = datetime.date.fromisoformat(trade['target_expiry'])
            else:
                exp = event_calendar.next_expiry(symbol)
            dte = max(0, (exp - today).days)

            current_pnl = _reprice_pnl(legs, trade_spot, dte, chain_df=_ltp_chain)
            pnl_per_lot = current_pnl * lot_size
            total_pnl = round(pnl_per_lot * trade['lots'], 2)

            net_premium = sum(
                (l.get('premium', 0) if l.get('action') == 'SELL' else -l.get('premium', 0))
                for l in legs
            )
            position = {
                'strategy': trade['strategy'], 'legs': legs,
                'max_loss': None, 'max_profit': None,
                'net_premium': net_premium,
            }

            adj = adjustments.check(position, spot=trade_spot,
                                    entry_spot=entry_spot, dte=dte)
            max_urg = min((r.get('urgency', 3) for r in adj), default=3) if adj else 3

            result = {
                'trade_id': trade['id'], 'symbol': symbol,
                'strategy': trade['strategy'],
                'entry_spot': entry_spot, 'current_spot': trade_spot,
                'dte': dte, 'lots': trade['lots'],
                'pnl_per_lot': round(pnl_per_lot, 2),
                'total_pnl': total_pnl,
                'adjustments': adj, 'max_urgency': max_urg,
                'opened': trade['opened_at'][:10],
            }
            results.append(result)

            conn.execute(
                '''INSERT INTO daily_checks
                   (trade_id, check_date, spot, dte, current_pnl, adjustments, max_urgency)
                   VALUES (?,?,?,?,?,?,?)''',
                (trade['id'], today.isoformat(), trade_spot, dte,
                 total_pnl, json.dumps(adj, default=_json_default), max_urg)
            )

        conn.commit()
        return results
    finally:
        conn.close()


def exit_trade(trade_id, spot=None, reason='manual', db=None):
    """Close a paper trade, compute final P/L with costs."""
    db = db or _db_path()
    init_db(db)
    conn = _connect(db)
    conn.row_factory = sqlite3.Row
    try:
        trade = conn.execute(
            "SELECT * FROM trades WHERE id=? AND status='open'", (trade_id,)
        ).fetchone()
        if trade is None:
            return {'status': 'error', 'reason': f'No open trade #{trade_id}'}

        from .core import bsm, cost_model
        from .data import event_calendar

        symbol = trade['symbol']
        legs = json.loads(trade['legs'])
        lot_size = trade['lot_size']
        lots = trade['lots']

        if spot is None:
            try:
                from .data import dhan_fetch
                spot = dhan_fetch.fetch_spot(symbol)
            except Exception:
                return {'status': 'error', 'reason': 'Provide --spot (Dhan unavailable)'}

        if trade['target_expiry']:
            exp = datetime.date.fromisoformat(trade['target_expiry'])
        else:
            exp = event_calendar.next_expiry(symbol)
        dte = max(0, (exp - datetime.date.today()).days)

        exit_chain = None
        if dte < 3:
            try:
                from .data import dhan_fetch as _df
                exit_chain, _ = _df.fetch_multi_expiry_chain(symbol, n_expiries=1)
            except Exception:
                pass

        gross_pnl_unit = _reprice_pnl(legs, spot, dte, chain_df=exit_chain)
        gross_pnl = round(gross_pnl_unit * lot_size * lots, 2)

        ltp_map = {}
        if exit_chain is not None and not exit_chain.empty:
            for _, row in exit_chain.iterrows():
                key = (float(row.get('strike', 0)), row.get('option_type', ''))
                ltp = row.get('ltp', row.get('last_price', 0))
                if ltp and ltp > 0:
                    ltp_map[key] = float(ltp)
        exit_legs = []
        for l in legs:
            key = (float(l['strike']), l['option_type'])
            price = ltp_map.get(key) if dte < 3 and key in ltp_map else _bsm_reprice(l, spot, dte)
            exit_legs.append({'premium': price,
                              'action': 'BUY' if l['action'] == 'SELL' else 'SELL'})
        exit_cost_est = cost_model.round_trip_cost(exit_legs, lot_size=lot_size)
        exit_slippage = SLIPPAGE_PER_LEG * len(legs) * lot_size * lots
        exit_cost = round(exit_cost_est.get('total', 0) * lots + exit_slippage, 2)

        entry_cost = trade['entry_cost'] or 0
        net_pnl = round(gross_pnl - entry_cost - exit_cost, 2)

        now = datetime.datetime.now().isoformat()
        conn.execute(
            '''UPDATE trades SET status='closed', closed_at=?, exit_spot=?,
               exit_reason=?, exit_cost=?, gross_pnl=?, net_pnl=? WHERE id=?''',
            (now, spot, reason, exit_cost, gross_pnl, net_pnl, trade_id)
        )
        conn.commit()
    finally:
        conn.close()

    log.info(f'Trade #{trade_id} closed: gross=₹{gross_pnl:,.0f} '
             f'costs=₹{entry_cost + exit_cost:,.0f} net=₹{net_pnl:,.0f}')
    return {
        'status': 'closed', 'trade_id': trade_id,
        'symbol': symbol, 'strategy': trade['strategy'],
        'entry_spot': trade['entry_spot'], 'exit_spot': spot,
        'gross_pnl': gross_pnl, 'entry_cost': entry_cost,
        'exit_cost': exit_cost, 'net_pnl': net_pnl, 'reason': reason,
    }


def expire_old(db=None):
    """Expire pending recommendations older than 1 trading day."""
    db = db or _db_path()
    init_db(db)
    cutoff = (datetime.datetime.now() - datetime.timedelta(hours=20)).isoformat()
    conn = _connect(db)
    n = conn.execute(
        "UPDATE recommendations SET status='expired' "
        "WHERE status='pending' AND timestamp < ?", (cutoff,)
    ).rowcount
    conn.commit()
    conn.close()
    if n > 0:
        log.info(f'Expired {n} old recommendation(s)')
    return n


def journal(symbol=None, db=None):
    """Trade journal with P/L summary."""
    import pandas as pd

    db = db or _db_path()
    init_db(db)
    conn = _connect(db)

    query = "SELECT id, opened_at, symbol, strategy, entry_spot, lots, " \
            "status, exit_spot, entry_cost, exit_cost, gross_pnl, net_pnl, " \
            "exit_reason FROM trades ORDER BY id"
    params = []
    if symbol:
        query = query.replace("ORDER BY", "WHERE symbol=? ORDER BY")
        params = [symbol]

    df = pd.read_sql_query(query, conn, params=params)
    conn.close()

    if df.empty:
        print('No trades yet.')
        return

    print('\n' + '=' * 90)
    print(f'{"#":>3} {"Date":10} {"Symbol":8} {"Strategy":20} {"Entry":>8} '
          f'{"Lots":>4} {"Status":>7} {"Net P/L":>10}')
    print('-' * 90)
    for _, r in df.iterrows():
        pnl_str = f'₹{r["net_pnl"]:,.0f}' if r['net_pnl'] is not None else '—'
        print(f'{r["id"]:3} {str(r["opened_at"])[:10]:10} {r["symbol"]:8} '
              f'{r["strategy"]:20} {r["entry_spot"]:8.0f} '
              f'{r["lots"]:4} {r["status"]:>7} {pnl_str:>10}')

    closed = df[df['status'] == 'closed']
    if not closed.empty:
        total = closed['net_pnl'].sum()
        wins = (closed['net_pnl'] > 0).sum()
        total_count = len(closed)
        costs = closed['entry_cost'].sum() + closed['exit_cost'].sum()
        print('-' * 90)
        print(f'Closed: {total_count} | Win rate: {wins/total_count*100:.0f}% | '
              f'Net P/L: ₹{total:,.0f} | Costs: ₹{costs:,.0f}')

    open_count = (df['status'] == 'open').sum()
    if open_count:
        print(f'Open: {open_count}')
    print('=' * 90 + '\n')


def _reprice_pnl(legs, spot, dte, chain_df=None):
    """Per-unit P/L at given spot/DTE. Uses LTP when DTE<3 and chain available."""
    use_ltp = dte < 3 and chain_df is not None and not chain_df.empty
    ltp_map = {}
    if use_ltp:
        for _, row in chain_df.iterrows():
            key = (float(row.get('strike', 0)), row.get('option_type', ''))
            ltp = row.get('ltp', row.get('last_price', 0))
            if ltp and ltp > 0:
                ltp_map[key] = float(ltp)

    pnl = 0.0
    for leg in legs:
        key = (float(leg['strike']), leg['option_type'])
        if use_ltp and key in ltp_map:
            exit_price = ltp_map[key]
        else:
            exit_price = _bsm_reprice(leg, spot, dte)
        entry_price = leg.get('premium', 0)
        qty = leg.get('qty', 1)
        if leg.get('action') == 'SELL':
            pnl += (entry_price - exit_price) * qty
        else:
            pnl += (exit_price - entry_price) * qty
    return pnl


def _bsm_reprice(leg, spot, dte):
    from .core import bsm
    t = max(dte / 365, 1 / 365)
    iv = max(leg.get('iv', 0.15), 0.01)
    return bsm.bsm_price(spot, leg['strike'], t, 0.07, iv, leg['option_type'])


def portfolio_greeks(spot=None, db=None):
    """
    Aggregate Greeks (delta, gamma, theta, vega) across all open positions.

    Returns dict: {delta, gamma, theta, vega, by_trade: [{trade_id, strategy, ...}]}
    """
    from .core import bsm
    from .data import event_calendar

    conn = _connect(db)
    conn.row_factory = sqlite3.Row
    try:
        trades = conn.execute("SELECT * FROM trades WHERE status='open'").fetchall()
        if not trades:
            return {'delta': 0, 'gamma': 0, 'theta': 0, 'vega': 0, 'by_trade': []}

        if spot is None:
            try:
                from .data import dhan_fetch
                spot = dhan_fetch.fetch_spot(trades[0]['symbol'])
            except Exception:
                spot = trades[0]['entry_spot']

        today = datetime.date.today()
        totals = {'delta': 0.0, 'gamma': 0.0, 'theta': 0.0, 'vega': 0.0}
        by_trade = []

        for trade in trades:
            legs = json.loads(trade['legs'])
            lot_size = trade['lot_size']
            lots = trade['lots']

            if trade['target_expiry']:
                exp = datetime.date.fromisoformat(trade['target_expiry'])
            else:
                exp = event_calendar.next_expiry(trade['symbol'])
            dte = max(0, (exp - today).days)
            t = max(dte / 365, 1 / 365)

            trade_greeks = {'delta': 0.0, 'gamma': 0.0, 'theta': 0.0, 'vega': 0.0}
            for leg in legs:
                iv = max(leg.get('iv', 0.15), 0.01)
                g = bsm.bsm_greeks(spot, leg['strike'], t, 0.07, iv, leg['option_type'])
                qty = leg.get('qty', 1)
                sign = -1 if leg.get('action') == 'SELL' else 1
                multiplier = sign * qty * lot_size * lots
                trade_greeks['delta'] += g['delta'] * multiplier
                trade_greeks['gamma'] += g['gamma'] * multiplier
                trade_greeks['theta'] += g['theta'] * multiplier
                trade_greeks['vega'] += g['vega'] * multiplier

            for k in totals:
                totals[k] += trade_greeks[k]
            by_trade.append({
                'trade_id': trade['id'],
                'strategy': trade['strategy'],
                **{k: round(v, 4) for k, v in trade_greeks.items()},
            })

        return {
            **{k: round(v, 4) for k, v in totals.items()},
            'by_trade': by_trade,
        }
    finally:
        conn.close()


def _json_default(obj):
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    if isinstance(obj, float) and (math.isinf(obj) or math.isnan(obj)):
        return str(obj)
    try:
        import numpy as np
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
    except ImportError:
        pass
    raise TypeError(f'Not JSON serializable: {type(obj)}')


def _print_recommendation(rec):
    if rec.get('status') != 'recommended':
        print(f'\n  {rec.get("status", "error")}: {rec.get("reason", "")}')
        return

    print(f'\n{"=" * 70}')
    print(f'  RECOMMENDATION #{rec["recommendation_id"]}')
    print(f'{"=" * 70}')
    print(f'  Strategy : {rec["strategy"]}')
    print(f'  Symbol   : {rec["symbol"]}   Spot: {rec["spot"]:.2f}   DTE: {rec["dte"]}')
    print(f'  VIX      : {rec["vix"]:.1f}')
    print(f'  Score    : {rec["score"]:.2f}')
    print(f'  Reasons  : {", ".join(rec["reasons"][:5])}')
    print(f'\n  Legs:')
    for l in rec['legs']:
        print(f'    {l["action"]:4} {l["strike"]:.0f} {l["option_type"]} '
              f'@{l.get("premium", l.get("ltp", 0)):.2f}  '
              f'IV={l.get("iv", 0):.1%}  OI={l.get("oi", 0)}')
    print(f'\n  Max profit/lot : ₹{rec["max_profit_per_lot"]:,.0f}')
    print(f'  Max loss/lot   : ₹{rec["max_loss_per_lot"]:,.0f}')
    print(f'  Cost/lot (RT)  : ₹{rec["cost_per_lot"]:,.0f}')
    print(f'  Margin/lot     : ₹{rec["margin_per_lot"]:,.0f}')
    print(f'  Lots           : {rec["lots"]}')

    gate = rec['entry_gate']
    gate_str = 'PASS' if gate.get('passes') else 'REJECT'
    print(f'\n  Entry gate     : {gate_str} (ratio={gate.get("ratio", "?"):.1f}×)')

    audit = rec['audit']
    print(f'  Audit          : {audit.get("decision", "?")}')
    for c in audit.get('checks', []):
        if c.get('check') != 'PASS':
            print(f'    {c["check"]}: {c.get("detail", "")}')

    if rec.get('build_warnings'):
        print(f'\n  Warnings:')
        for w in rec['build_warnings']:
            print(f'    ⚠ {w}')

    print(f'\n  To enter: .venv/bin/python -m options.paper_trade enter')
    print(f'{"=" * 70}\n')


def _print_checks(results):
    if not results:
        print('\n  No open trades.\n')
        return

    print(f'\n{"=" * 80}')
    print(f'  DAILY CHECK — {datetime.date.today().isoformat()}')
    print(f'{"=" * 80}')
    for r in results:
        urgency_map = {1: 'ACT NOW', 2: 'SOON', 3: 'OK'}
        urg = urgency_map.get(r['max_urgency'], 'OK')
        pnl_sign = '+' if r['total_pnl'] >= 0 else ''
        print(f'\n  Trade #{r["trade_id"]}: {r["strategy"]} {r["symbol"]} '
              f'{r["lots"]}L | opened {r["opened"]}')
        print(f'    Spot: {r["entry_spot"]:.0f} → {r["current_spot"]:.0f}  '
              f'DTE={r["dte"]}  P/L: {pnl_sign}₹{r["total_pnl"]:,.0f}')
        print(f'    Status: [{urg}]')
        if r['adjustments']:
            for a in r['adjustments']:
                print(f'    → {a.get("reason", "")}')
    print(f'\n{"=" * 80}\n')


def _self_check():
    """End-to-end self-check with synthetic data."""
    import tempfile
    db = os.path.join(tempfile.gettempdir(), 'test_paper_trade.db')
    if os.path.exists(db):
        os.remove(db)

    init_db(db)

    from .data import chain as chain_mod
    from .strategies import builder, signals, selector
    from .risk import sizing, margin, scenarios, audit as audit_mod
    from .core import cost_model, bsm
    from .data import event_calendar

    spot = 24000
    symbol = 'NIFTY'
    lot_size = 65
    capital = 500_000

    chain_df = chain_mod.synthetic_chain(spot, strike_range=0.10,
                                        strike_step=50, base_iv=0.14)

    # Build an iron condor directly
    legs = [
        {'strike': 23800, 'option_type': 'PE', 'action': 'BUY',
         'premium': bsm.bsm_price(spot, 23800, 14/365, 0.07, 0.16, 'PE'),
         'iv': 0.16, 'expiry_years': 14/365, 'qty': 1, 'oi': 50000},
        {'strike': 23900, 'option_type': 'PE', 'action': 'SELL',
         'premium': bsm.bsm_price(spot, 23900, 14/365, 0.07, 0.15, 'PE'),
         'iv': 0.15, 'expiry_years': 14/365, 'qty': 1, 'oi': 80000},
        {'strike': 24100, 'option_type': 'CE', 'action': 'SELL',
         'premium': bsm.bsm_price(spot, 24100, 14/365, 0.07, 0.14, 'CE'),
         'iv': 0.14, 'expiry_years': 14/365, 'qty': 1, 'oi': 80000},
        {'strike': 24200, 'option_type': 'CE', 'action': 'BUY',
         'premium': bsm.bsm_price(spot, 24200, 14/365, 0.07, 0.15, 'CE'),
         'iv': 0.15, 'expiry_years': 14/365, 'qty': 1, 'oi': 50000},
    ]

    net_prem = sum(
        (l['premium'] if l['action'] == 'SELL' else -l['premium']) for l in legs
    )

    # Insert a synthetic recommendation
    conn = _connect(db)
    conn.execute(
        '''INSERT INTO recommendations
           (timestamp, symbol, strategy, spot, legs, lots, lot_size,
            max_profit_per_lot, max_loss_per_lot, cost_per_lot, margin_per_lot,
            entry_gate, audit, signals, reasons, score, vix, dte, status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (datetime.datetime.now().isoformat(), symbol, 'iron_condor', spot,
         json.dumps(legs, default=_json_default), 2, lot_size,
         round(net_prem * lot_size, 2), round(100 * lot_size, 2),
         50.0, 45000.0,
         json.dumps({'passes': True, 'ratio': 1.5}),
         json.dumps({'decision': 'PASS', 'checks': []}),
         json.dumps([]), json.dumps(['vol sell OK', 'VIX normal']),
         8.5, 15.0, 14, 'pending')
    )
    conn.commit()
    conn.close()

    # enter
    result = enter(db=db)
    assert result['status'] == 'entered', f'Enter failed: {result}'
    trade_id = result['trade_id']
    assert trade_id == 1

    # daily check
    checks = daily_check(spot=24050, db=db)
    assert len(checks) == 1
    assert checks[0]['trade_id'] == 1
    assert checks[0]['dte'] >= 0

    # exit
    ex = exit_trade(trade_id, spot=24010, reason='target', db=db)
    assert ex['status'] == 'closed'
    assert 'net_pnl' in ex

    # expire
    conn = _connect(db)
    conn.execute(
        "INSERT INTO recommendations "
        "(timestamp, symbol, strategy, spot, legs, lots, lot_size, "
        "max_profit_per_lot, max_loss_per_lot, cost_per_lot, margin_per_lot, "
        "entry_gate, audit, signals, reasons, score, vix, dte, status) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ('2020-01-01T00:00:00', 'NIFTY', 'test', 24000,
         '[]', 1, 65, 0, 0, 0, 0, '{}', '{}', '[]', '[]', 0, 14, 7, 'pending')
    )
    conn.commit()
    conn.close()
    n = expire_old(db=db)
    assert n == 1

    # verify trade is closed
    conn = _connect(db)
    conn.row_factory = sqlite3.Row
    t = conn.execute("SELECT * FROM trades WHERE id=1").fetchone()
    assert t['status'] == 'closed'
    assert t['net_pnl'] is not None
    conn.close()

    os.remove(db)
    print("paper_trade.py: all checks passed")


def _cli():
    parser = argparse.ArgumentParser(
        prog='python -m options.paper_trade',
        description='Options paper trading workflow',
    )
    sub = parser.add_subparsers(dest='command')

    p_rec = sub.add_parser('recommend', help='Generate trade recommendation')
    p_rec.add_argument('symbol', nargs='?', default='NIFTY')
    p_rec.add_argument('--capital', type=float, default=DEFAULT_CAPITAL)

    p_enter = sub.add_parser('enter', help='Enter latest pending recommendation')
    p_enter.add_argument('rec_id', nargs='?', type=int, default=None)

    p_check = sub.add_parser('check', help='Daily check on open trades')
    p_check.add_argument('--spot', type=float, default=None)

    p_exit = sub.add_parser('exit', help='Exit an open trade')
    p_exit.add_argument('trade_id', type=int)
    p_exit.add_argument('--spot', type=float, default=None)
    p_exit.add_argument('--reason', default='manual')

    sub.add_parser('journal', help='Print trade journal')
    sub.add_parser('expire', help='Expire old pending recommendations')
    sub.add_parser('selfcheck', help='Run self-check')

    p_inc = sub.add_parser('incubate', help='Start incubation from WFA report')
    p_inc.add_argument('strategy_key')
    p_inc.add_argument('report_path')

    p_life = sub.add_parser('lifecycle', help='Show lifecycle status')
    p_life.add_argument('strategy_key', nargs='?', default=None)

    p_abort = sub.add_parser('abort', help='Manual abort')
    p_abort.add_argument('strategy_key')
    p_abort.add_argument('reason')

    args = parser.parse_args()

    if args.command == 'recommend':
        rec = recommend(args.symbol.upper(), capital=args.capital)
        _print_recommendation(rec)
    elif args.command == 'enter':
        result = enter(args.rec_id)
        print(json.dumps(result, indent=2, default=_json_default))
    elif args.command == 'check':
        results = daily_check(spot=args.spot)
        _print_checks(results)
    elif args.command == 'exit':
        result = exit_trade(args.trade_id, spot=args.spot, reason=args.reason)
        print(json.dumps(result, indent=2, default=_json_default))
    elif args.command == 'journal':
        journal()
    elif args.command == 'expire':
        n = expire_old()
        print(f'Expired {n} recommendation(s)')
    elif args.command == 'selfcheck':
        _self_check()
    elif args.command == 'incubate':
        result = incubate(args.strategy_key, args.report_path)
        print(json.dumps(result, indent=2, default=_json_default))
    elif args.command == 'lifecycle':
        if args.strategy_key:
            result = check_lifecycle(args.strategy_key)
            print(json.dumps(result, indent=2, default=_json_default))
        else:
            lifecycle_status()
    elif args.command == 'abort':
        db = _db_path()
        init_db(db)
        conn = _connect(db)
        cur = conn.execute(
            "UPDATE strategy_lifecycle SET status='ABORTED', abort_date=?, abort_reason=? "
            "WHERE strategy_key=? AND status='INCUBATING'",
            (datetime.date.today().isoformat(), args.reason, args.strategy_key)
        )
        conn.commit()
        if cur.rowcount == 0:
            row = conn.execute(
                'SELECT status FROM strategy_lifecycle WHERE strategy_key=?',
                (args.strategy_key,)
            ).fetchone()
            if row:
                print(f'Cannot abort: {args.strategy_key} is already {row[0]}')
            else:
                print(f'Not found: {args.strategy_key}')
        else:
            print(f'Aborted: {args.strategy_key} — {args.reason}')
        conn.close()
    else:
        parser.print_help()


if __name__ == '__main__':
    _cli()
