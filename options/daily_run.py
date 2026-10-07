"""
Daily paper-trading + chain collection runner.

Run after market close (~15:45 IST, Mon-Fri).
Orchestrates: chain collection → recommend → enter → check → lifecycle.

Usage:
    python -m options.daily_run
    python -m options.daily_run --skip-chain    # skip chain collection
    python -m options.daily_run --dry-run       # no DB writes
"""

import argparse
import datetime
import json
import logging
import sys

log = logging.getLogger('daily_run')


def run(skip_chain=False, dry_run=False):
    results = {}
    today = datetime.date.today().isoformat()
    log.info(f'=== Daily run {today} ===')

    # 1. Collect chain data for historical DB
    if not skip_chain:
        log.info('[1/5] Collecting chain snapshots...')
        try:
            from options.data import collect_daily
            chain_result = collect_daily.collect(
                symbols=['NIFTY', 'BANKNIFTY'], n_expiries=3, dry_run=dry_run
            )
            results['chain'] = chain_result
            nifty = chain_result.get('NIFTY', {})
            log.info(f'  Chain: {nifty.get("status")} — {nifty.get("rows", 0)} rows')
        except Exception as e:
            log.error(f'  Chain collection failed: {e}')
            results['chain'] = {'status': 'error', 'reason': str(e)}
    else:
        log.info('[1/5] Chain collection skipped')
        results['chain'] = {'status': 'skipped'}

    # 2. Generate recommendation
    log.info('[2/5] Generating recommendation...')
    try:
        from options import paper_trade
        if dry_run:
            log.info('  Dry run — skipping recommend')
            results['recommend'] = {'status': 'dry_run'}
        else:
            rec = paper_trade.recommend(symbol='NIFTY')
            results['recommend'] = rec
            status = rec.get('status', 'unknown')
            strategy = rec.get('strategy', rec.get('strategy_key', '-'))
            log.info(f'  Recommend: {status} — {strategy}')
    except Exception as e:
        log.error(f'  Recommend failed: {e}')
        results['recommend'] = {'status': 'error', 'reason': str(e)}

    # 3. Auto-enter pending recommendations
    log.info('[3/5] Entering pending trades...')
    try:
        if dry_run:
            log.info('  Dry run — skipping enter')
            results['enter'] = {'status': 'dry_run'}
        else:
            enter_result = paper_trade.enter()
            results['enter'] = enter_result
            log.info(f'  Enter: {enter_result.get("status", "unknown")}')
    except Exception as e:
        log.error(f'  Enter failed: {e}')
        results['enter'] = {'status': 'error', 'reason': str(e)}

    # 4. Check open trades (P/L, stops, expiry)
    log.info('[4/5] Checking open trades...')
    try:
        if dry_run:
            log.info('  Dry run — skipping check')
            results['check'] = {'status': 'dry_run'}
        else:
            check_result = paper_trade.daily_check()
            if isinstance(check_result, list):
                results['check'] = {'status': 'ok', 'trades_checked': len(check_result)}
                log.info(f'  Check: {len(check_result)} trades checked')
            else:
                results['check'] = check_result
                log.info(f'  Check: {check_result.get("status", "unknown")}')
    except Exception as e:
        log.error(f'  Check failed: {e}')
        results['check'] = {'status': 'error', 'reason': str(e)}

    # 5. Lifecycle check on incubating strategies
    log.info('[5/5] Checking incubation lifecycle...')
    try:
        import sqlite3
        db = paper_trade._db_path()
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        try:
            strats = conn.execute(
                "SELECT strategy_key FROM strategy_lifecycle WHERE status='INCUBATING'"
            ).fetchall()
        finally:
            conn.close()

        lifecycle_results = {}
        for row in strats:
            key = row['strategy_key']
            lr = paper_trade.check_lifecycle(key)
            dd_pct = lr.get('actual_dd_pct') or 0
            lifecycle_results[key] = {
                'status': lr.get('status'),
                'trades': lr.get('trade_count', 0),
                'return_eff': lr.get('return_efficiency'),
                'dd_pct': dd_pct,
            }
            log.info(f'  {key}: {lr["status"]} — {lr.get("trade_count", 0)} trades, '
                     f'DD={dd_pct:.1f}%')

        results['lifecycle'] = lifecycle_results
        if not strats:
            log.info('  No strategies incubating')
    except Exception as e:
        log.error(f'  Lifecycle check failed: {e}')
        results['lifecycle'] = {'status': 'error', 'reason': str(e)}

    # Summary
    errors = [k for k, v in results.items()
              if isinstance(v, dict) and v.get('status') == 'error']
    if errors:
        log.warning(f'Daily run complete with errors in: {errors}')
    else:
        log.info('Daily run complete — all steps OK')

    return results


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(name)s %(levelname)s %(message)s'
    )

    parser = argparse.ArgumentParser(description='Daily paper-trading runner')
    parser.add_argument('--skip-chain', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    results = run(skip_chain=args.skip_chain, dry_run=args.dry_run)

    errors = [k for k, v in results.items()
              if isinstance(v, dict) and v.get('status') == 'error']
    sys.exit(1 if errors else 0)
