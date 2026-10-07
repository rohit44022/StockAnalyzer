"""
Validate strategies against real Dhan option chain data (last 30 days).
Downloads expired option data, builds real chain loader, runs engine.

Usage:
  .venv/bin/python -m options.backtest.validate_real
"""

import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import pandas as pd
from options.backtest import engine
from options.backtest.run_batch import nifty_lot_size, STRATEGIES

CACHE_PATH = os.path.join(os.path.dirname(__file__), 'reports', '_real_chain_cache.json')

STRIKE_LABELS = [f'ATM{s:+d}' if s != 0 else 'ATM'
                 for s in range(-10, 11)]


def _get_dhan():
    from dotenv import load_dotenv
    from dhanhq import dhanhq, DhanContext
    load_dotenv()
    cid = os.getenv('DHAN_CLIENT_ID')
    tok = os.getenv('DHAN_ACCESS_TOKEN')
    if not cid or not tok:
        raise RuntimeError('DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN not in .env')
    return dhanhq(DhanContext(cid, tok))


def download_chains(days_back=45):
    """Download real option chain data from Dhan expired_options_data API."""
    dhan = _get_dhan()
    to_d = datetime.date.today().isoformat()
    from_d = (datetime.date.today() - datetime.timedelta(days=days_back)).isoformat()

    all_data = {}
    total_calls = len(STRIKE_LABELS) * 2  # CE + PE
    call_num = 0

    for opt_type in ['CALL', 'PUT']:
        for strike_label in STRIKE_LABELS:
            call_num += 1
            print(f'  [{call_num}/{total_calls}] {opt_type} {strike_label}...', end='', flush=True)

            try:
                resp = dhan.expired_options_data(
                    security_id='13',
                    exchange_segment='NSE_FNO',
                    instrument_type='OPTIDX',
                    expiry_flag='WEEK',
                    expiry_code=1,
                    strike=strike_label,
                    drv_option_type=opt_type,
                    required_data=['close', 'iv', 'oi', 'volume', 'strike', 'spot'],
                    from_date=from_d,
                    to_date=to_d,
                    interval=60,
                )

                data = resp.get('data', '')
                if not isinstance(data, dict):
                    print(' no data')
                    time.sleep(3)
                    continue

                inner = data.get('data', data)
                if not isinstance(inner, dict):
                    print(' no inner data')
                    time.sleep(3)
                    continue

                resp_key = 'ce' if opt_type == 'CALL' else 'pe'
                series = inner.get(resp_key, {})
                if not series or not series.get('timestamp'):
                    print(' empty')
                    time.sleep(3)
                    continue

                n = len(series['timestamp'])
                print(f' {n} candles')

                key = f'{opt_type}_{strike_label}'
                all_data[key] = {
                    'timestamp': series['timestamp'],
                    'close': series['close'],
                    'iv': series.get('iv', [0] * n),
                    'oi': series.get('oi', [0] * n),
                    'volume': series.get('volume', [0] * n),
                    'strike': series.get('strike', [0] * n),
                    'spot': series.get('spot', [0] * n),
                }

            except Exception as e:
                print(f' ERROR: {e}')

            time.sleep(3)

    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, 'w') as f:
        json.dump({
            'downloaded': datetime.datetime.now().isoformat(),
            'from_date': from_d,
            'to_date': to_d,
            'data': all_data,
        }, f)

    print(f'\nSaved {len(all_data)} series to {CACHE_PATH}')
    return all_data


def load_real_cache():
    """Load cached real chain data, download if missing."""
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH) as f:
            cache = json.load(f)
        print(f'Loaded real chain cache ({cache["from_date"]} to {cache["to_date"]})')
        return cache['data']

    print('No cache found, downloading from Dhan...')
    return download_chains()


def _build_daily_chains(raw_data):
    """Convert hourly series into daily chain DataFrames keyed by date."""
    daily = {}

    for key, series in raw_data.items():
        opt_type_str, strike_label = key.split('_', 1)
        opt_type = 'CE' if opt_type_str == 'CALL' else 'PE'

        timestamps = series['timestamp']
        closes = series['close']
        ivs = series.get('iv', [0] * len(timestamps))
        ois = series.get('oi', [0] * len(timestamps))
        vols = series.get('volume', [0] * len(timestamps))
        strikes = series.get('strike', [0] * len(timestamps))
        spots = series.get('spot', [0] * len(timestamps))

        by_date = {}
        for i, ts in enumerate(timestamps):
            dt = datetime.datetime.fromtimestamp(ts)
            d = dt.date()
            by_date.setdefault(d, []).append(i)

        for d, indices in by_date.items():
            if d not in daily:
                daily[d] = {'rows': [], 'spot': 0}

            last_idx = indices[-1]
            iv_val = ivs[last_idx]

            # On expiry days the last candle often has iv=0;
            # walk backwards to find the last candle with valid IV
            if not iv_val or iv_val == 0:
                for j in reversed(indices[:-1]):
                    if ivs[j] and ivs[j] != 0:
                        iv_val = ivs[j]
                        break

            if isinstance(iv_val, (int, float)) and iv_val > 1:
                iv_val = iv_val / 100.0

            daily[d]['rows'].append({
                'strike': float(strikes[last_idx]),
                'option_type': opt_type,
                'settle': float(closes[last_idx]),
                'iv': float(iv_val) if iv_val else 0.0,
                'oi': int(ois[last_idx]) if ois[last_idx] else 0,
                'volume': int(vols[last_idx]) if vols[last_idx] else 0,
            })
            daily[d]['spot'] = float(spots[last_idx])

    return daily


def make_real_chain_loader(raw_data):
    """Build chain_loader and spot_series from real Dhan data."""
    daily = _build_daily_chains(raw_data)

    spot_series = {}
    chain_cache = {}

    for d in sorted(daily.keys()):
        spot = daily[d]['spot']
        if spot <= 0:
            continue
        spot_series[d] = spot

        rows = daily[d]['rows']
        if not rows:
            continue

        # Add expiry: assume weekly, next Thursday from this date
        days_to_thu = (3 - d.weekday()) % 7
        if days_to_thu == 0:
            days_to_thu = 7
        expiry = d + datetime.timedelta(days=days_to_thu)

        for r in rows:
            r['expiry'] = expiry

        chain_cache[d] = pd.DataFrame(rows)

    def loader(dt):
        return chain_cache.get(dt, pd.DataFrame())

    return loader, spot_series


def run_validation():
    """Run all strategies against real data and print results."""
    raw = load_real_cache()
    loader, spots = make_real_chain_loader(raw)

    dates = sorted(spots.keys())
    if len(dates) < 5:
        print(f'Only {len(dates)} trading days — need at least 5.')
        return

    print(f'\n{len(dates)} trading days: {dates[0]} → {dates[-1]}')
    print(f'Spot range: ₹{min(spots.values()):,.0f} — ₹{max(spots.values()):,.0f}')

    lot = nifty_lot_size(dates[0])
    start = dates[0]
    end = dates[-1]

    strategies = STRATEGIES

    print(f'\n{"═" * 100}')
    print(f'  REAL DATA VALIDATION ({start} → {end}, lot={lot})')
    print(f'{"═" * 100}')
    print(f'  {"Strategy":<22s} | {"Trd":>4s} | {"Net P/L":>10s} | '
          f'{"WR":>6s} | {"PF":>5s} | {"DD":>6s} | {"Avg":>8s}')
    print(f'  {"-" * 80}')

    for strat in strategies:
        config = {
            'strategy_key': strat,
            'lot_size': lot,
            'signal_mode': 'vp',
            'vp_threshold': 0.02,
            'rv_window': min(10, len(dates) - 2),
            'entry_dte_range': (3, 7),
            'exit_dte': 1,
            'profit_target_pct': 0.50,
            'initial_capital': 500_000,
            'max_lots': 4,
            'max_concurrent': 2,
            'max_margin_usage': 0.40,
            'symbol': 'NIFTY',
            'start_date': start,
            'end_date': end,
        }

        try:
            result = engine.run(config, loader, spots)
            m = result.get('metrics', {})
            dd = m.get('max_drawdown', {})
            at = m.get('avg_trade', {})
            trades = m.get('total_trades', 0)
            net = m.get('net_pnl', 0)
            wr = m.get('win_rate_pct', 0)
            pf = m.get('profit_factor', 0)
            dd_pct = dd.get('pct', 0) if isinstance(dd, dict) else 0
            avg = at.get('avg_all', 0) if isinstance(at, dict) else 0

            print(f'  {strat:<22s} | {trades:4d} | ₹{net:>9,.0f} | '
                  f'{wr:5.1f}% | {pf:5.2f} | {dd_pct:5.1f}% | ₹{avg:>7,.0f}')

        except Exception as e:
            print(f'  {strat:<22s} | ERROR: {e}')

    print(f'{"═" * 100}')


if __name__ == '__main__':
    run_validation()
