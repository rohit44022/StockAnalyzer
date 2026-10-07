"""
EOD runner: fetch live chain from Dhan, run full pipeline, persist everything.

Usage:
  .venv/bin/python -m options.run_eod                  # NIFTY
  .venv/bin/python -m options.run_eod BANKNIFTY         # BANKNIFTY
  .venv/bin/python -m options.run_eod NIFTY BANKNIFTY   # both

Schedule via cron (after 4:30 PM IST when bhavcopy is available):
  30 16 * * 1-5 cd /path/to/historical_data && .venv/bin/python -m options.run_eod
"""

import sys
import logging
import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s %(levelname)s %(message)s',
)
log = logging.getLogger(__name__)


def run(symbol='NIFTY'):
    from .data import dhan_fetch, pipeline

    log.info(f'[{symbol}] Fetching chain from Dhan...')
    df, spot = dhan_fetch.fetch_multi_expiry_chain(symbol, n_expiries=3)
    log.info(f'[{symbol}] Got {len(df)} rows, spot={spot:.2f}')

    vix_value = None
    try:
        if symbol == 'NIFTY':
            from .data import india_vix
            vix_df = india_vix.load_vix_history()
            if not vix_df.empty:
                vix_value = float(vix_df.iloc[-1]['close'])
                log.info(f'[{symbol}] VIX={vix_value:.2f}')
    except Exception as e:
        log.warning(f'[{symbol}] VIX load failed: {e}')

    # Load index price history for vol forecast / variance premium
    prices = None
    try:
        import os, pandas as pd
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for fname in [f'{symbol}.csv', f'{symbol}.NS.csv',
                      f'{symbol}BEES.NS.csv', f'{symbol}1.NS.csv']:
            csv_path = os.path.join(base, 'stock_csv', fname)
            if os.path.exists(csv_path):
                raw = pd.read_csv(csv_path)['Close']
                prices = pd.to_numeric(raw, errors='coerce').dropna().values[-300:]
                if len(prices) >= 30:
                    log.info(f'[{symbol}] Loaded {len(prices)} prices from {fname}')
                    break
                prices = None
    except Exception as e:
        log.warning(f'[{symbol}] Price history load failed: {e}')

    log.info(f'[{symbol}] Running EOD pipeline...')
    result = pipeline.run_eod_pipeline(
        symbol=symbol,
        chain_df=df,
        spot=spot,
        vix_value=vix_value,
        prices=prices,
    )

    log.info(f'[{symbol}] Pipeline status: {result["status"]}')
    if result['errors']:
        for err in result['errors']:
            log.warning(f'[{symbol}] {err}')

    # Print key metrics
    if 'oi' in result:
        pcr = result['oi'].get('pcr', {})
        mp = result['oi'].get('max_pain', {})
        log.info(f'[{symbol}] PCR={pcr.get("pcr", "?"):.3f} ({pcr.get("signal")}) '
                 f'MaxPain={mp.get("max_pain_strike", "?")}')

    if 'variance_premium' in result:
        vp = result['variance_premium']
        log.info(f'[{symbol}] VP: iv={vp["iv"]:.4f} rv={vp["rv"]} signal={vp["signal"]}')

    return result


if __name__ == '__main__':
    symbols = sys.argv[1:] or ['NIFTY']
    for sym in symbols:
        try:
            run(sym.upper())
        except Exception as e:
            log.error(f'[{sym}] FAILED: {e}', exc_info=True)
