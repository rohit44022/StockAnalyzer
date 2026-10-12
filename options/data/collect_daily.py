"""
Daily option chain collector — run after market close (~15:30 IST).

Fetches NIFTY (and optionally BANKNIFTY) chains from Dhan API,
stores snapshots in chain_store SQLite for backtesting.

Usage:
    python -m options.data.collect_daily                    # NIFTY only
    python -m options.data.collect_daily --symbols NIFTY BANKNIFTY
    python -m options.data.collect_daily --expiries 3       # nearest 3 expiries
    python -m options.data.collect_daily --dry-run          # fetch but don't store

Cron (daily 15:45 IST):
    45 15 * * 1-5 cd /path/to/historical_data && .venv/bin/python -m options.data.collect_daily >> logs/chain_collect.log 2>&1
"""

import argparse
import datetime
import logging
import sys
import time

from . import dhan_fetch, chain_store

log = logging.getLogger(__name__)

_IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
_now_ist = lambda: datetime.datetime.now(_IST).replace(tzinfo=None)


def collect(symbols=None, n_expiries=3, dry_run=False, db_path=None):
    symbols = symbols or ['NIFTY']
    timestamp = _now_ist().isoformat()
    results = {}

    for symbol in symbols:
        log.info(f'Collecting {symbol} chain (nearest {n_expiries} expiries)...')
        try:
            df, spot = dhan_fetch.fetch_multi_expiry_chain(
                symbol=symbol, n_expiries=n_expiries
            )
        except Exception as e:
            log.error(f'{symbol}: fetch failed — {e}')
            results[symbol] = {'status': 'error', 'reason': str(e)}
            continue

        if df.empty:
            log.warning(f'{symbol}: empty chain returned')
            results[symbol] = {'status': 'empty', 'rows': 0}
            continue

        n_rows = len(df)
        n_expiries_found = df['expiry'].nunique()
        n_strikes = df['strike'].nunique()

        log.info(f'{symbol}: {n_rows} rows, {n_expiries_found} expiries, {n_strikes} strikes')

        if dry_run:
            log.info(f'{symbol}: dry run — not storing')
            results[symbol] = {'status': 'dry_run', 'rows': n_rows,
                               'expiries': n_expiries_found, 'strikes': n_strikes}
            continue

        try:
            db = chain_store.init_db(db_path)
            chain_store.store_snapshot(df, symbol, timestamp=timestamp, db_path=db)
            log.info(f'{symbol}: stored {n_rows} rows')
            results[symbol] = {'status': 'ok', 'rows': n_rows,
                               'expiries': n_expiries_found, 'strikes': n_strikes}
        except Exception as e:
            log.error(f'{symbol}: store failed — {e}')
            results[symbol] = {'status': 'store_error', 'reason': str(e)}

        if len(symbols) > 1:
            time.sleep(3)

    return results


def _self_check():
    """Verify fetch + store roundtrip with a single expiry."""
    import tempfile, os

    db = os.path.join(tempfile.mkdtemp(), 'test_collect.db')
    log.info('Self-check: fetching NIFTY nearest 1 expiry...')

    try:
        result = collect(symbols=['NIFTY'], n_expiries=1, db_path=db)
    except RuntimeError as e:
        if 'DHAN_CLIENT_ID' in str(e) or 'DHAN_ACCESS_TOKEN' in str(e):
            print('collect_daily.py: SKIPPED (no Dhan credentials)')
            return
        raise

    r = result.get('NIFTY', {})
    if r.get('status') == 'error' and 'credentials' in r.get('reason', '').lower():
        print('collect_daily.py: SKIPPED (no Dhan credentials)')
        return

    assert r.get('status') == 'ok', f'Expected ok, got {r}'
    assert r.get('rows', 0) > 50, f'Expected >50 rows, got {r.get("rows")}'

    # Verify data is in DB
    import sqlite3
    conn = sqlite3.connect(db)
    try:
        count = conn.execute('SELECT COUNT(*) FROM chain_snapshot').fetchone()[0]
    finally:
        conn.close()
    assert count == r['rows'], f'DB has {count} rows, expected {r["rows"]}'

    print(f'collect_daily.py: stored {count} rows for NIFTY — all checks passed')

    # Cleanup
    os.unlink(db)


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(name)s %(levelname)s %(message)s'
    )

    parser = argparse.ArgumentParser(description='Daily option chain collector')
    parser.add_argument('--symbols', nargs='+', default=['NIFTY'],
                        help='Symbols to collect (default: NIFTY)')
    parser.add_argument('--expiries', type=int, default=3,
                        help='Number of nearest expiries (default: 3)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Fetch but do not store')
    parser.add_argument('--selfcheck', action='store_true',
                        help='Run self-check')
    args = parser.parse_args()

    if args.selfcheck:
        _self_check()
    else:
        results = collect(
            symbols=args.symbols,
            n_expiries=args.expiries,
            dry_run=args.dry_run,
        )
        ok = sum(1 for r in results.values() if r.get('status') in ('ok', 'dry_run'))
        total = len(results)
        if ok == total:
            log.info(f'Collection complete: {ok}/{total} symbols stored')
        else:
            log.warning(f'Collection partial: {ok}/{total} symbols stored')
            sys.exit(1)
