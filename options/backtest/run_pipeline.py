"""
Full Davey pipeline with real NIFTY data from Dhan API.

Data: NIFTY daily spot + ATM IV from expired weekly options (Dhan).
Chains: BSM-generated at real daily IV (skew is a known ceiling).
Pipeline: engine → WFA → MC → report with Davey gates.
"""

import datetime
import os
import time
import pandas as pd
from dotenv import load_dotenv

from options.core import bsm
from options.backtest import engine, walk_forward, monte_carlo, report


def _init_dhan():
    load_dotenv()
    from dhanhq import DhanContext, HistoricalData
    dhan = DhanContext(os.getenv('DHAN_CLIENT_ID'), os.getenv('DHAN_ACCESS_TOKEN'))
    return HistoricalData(dhan)


def fetch_nifty_spot(hd, months=6):
    end = datetime.date.today()
    start = end - datetime.timedelta(days=months * 31)
    resp = hd.historical_daily_data('13', 'IDX_I', 'INDEX', str(start), str(end))
    if resp['status'] != 'success':
        raise RuntimeError(f"Dhan spot fetch failed: {resp}")
    d = resp['data']
    spots = {}
    for i, ts in enumerate(d['timestamp']):
        dt = datetime.datetime.fromtimestamp(ts).date()
        spots[dt] = d['close'][i]
    return spots


def fetch_atm_iv(hd, months=6):
    """Fetch daily closing ATM IV from expired weekly options, month by month."""
    daily_iv = {}
    end = datetime.date.today()

    for m in range(months):
        m_end = end - datetime.timedelta(days=m * 30)
        m_start = m_end - datetime.timedelta(days=31)

        try:
            resp = hd.expired_options_data(
                security_id='13', exchange_segment='NSE_FNO',
                instrument_type='OPTIDX', expiry_flag='WEEK',
                expiry_code=1, strike='ATM', drv_option_type='CALL',
                required_data=['iv', 'spot'],
                from_date=str(m_start), to_date=str(m_end),
                interval=60
            )
        except Exception as e:
            print(f"  Month {m+1}: error {e}, skipping")
            time.sleep(2)
            continue

        if resp['status'] != 'success':
            print(f"  Month {m+1}: API failed, skipping")
            time.sleep(1)
            continue

        ce = resp.get('data', {})
        if isinstance(ce, dict):
            ce = ce.get('data', {}).get('ce', {})
        if not ce or not isinstance(ce, dict):
            print(f"  Month {m+1}: no CE data")
            time.sleep(1)
            continue

        ivs = ce.get('iv', [])
        timestamps = ce.get('timestamp', [])

        day_data = {}
        for i, ts in enumerate(timestamps):
            dt = datetime.datetime.fromtimestamp(ts).date()
            if ivs[i] > 0:
                day_data[dt] = ivs[i]

        daily_iv.update(day_data)
        print(f"  Month {m+1} ({m_start} → {m_end}): {len(day_data)} days")
        time.sleep(1)

    return daily_iv


def _next_thursday(dt):
    days = (3 - dt.weekday()) % 7
    return dt + datetime.timedelta(days=days or 7)


def make_chain_loader(spots, daily_iv):
    cache = {}

    def loader(dt):
        if dt not in spots:
            return None
        if dt in cache:
            return cache[dt]

        spot = spots[dt]
        iv = daily_iv.get(dt)
        if iv is None or iv <= 0:
            known = sorted(daily_iv.keys())
            near = min(known, key=lambda d: abs((d - dt).days), default=None)
            iv = daily_iv.get(near, 14.0) if near else 14.0

        # Dhan IV is percentage (14.5 = 14.5% annual), BSM needs decimal
        if iv > 1:
            iv = iv / 100.0

        near_expiry = _next_thursday(dt)
        # Generate near + far expiry for calendar/diagonal strategies
        far_expiry = _next_thursday(near_expiry + datetime.timedelta(days=1))

        rows = []
        for expiry in [near_expiry, far_expiry]:
            t = max((expiry - dt).days, 1) / 365
            for k in range(int(spot - 800), int(spot + 850), 50):
                for ot in ['CE', 'PE']:
                    p = max(0.05, bsm.bsm_price(spot, float(k), t, 0.07, iv, ot))
                    rows.append({
                        'strike': float(k), 'option_type': ot, 'expiry': expiry,
                        'settle': round(p, 2), 'volume': 50000, 'oi': 100000,
                    })

        cache[dt] = pd.DataFrame(rows)
        return cache[dt]

    return loader


def run_pipeline(strategy='short_straddle', months=6):
    hd = _init_dhan()

    print("═══ Fetching Data from Dhan ═══")
    spots = fetch_nifty_spot(hd, months)
    dates = sorted(spots.keys())
    print(f"  {len(dates)} trading days: {dates[0]} → {dates[-1]}")
    print(f"  Spot range: ₹{min(spots.values()):,.0f} — ₹{max(spots.values()):,.0f}")

    print("Fetching ATM IV (month by month)...")
    daily_iv = fetch_atm_iv(hd, months)
    iv_vals = [v for v in daily_iv.values() if v > 0]
    print(f"  {len(daily_iv)} days of IV data")
    if iv_vals:
        print(f"  IV range: {min(iv_vals):.1f}% — {max(iv_vals):.1f}%")

    loader = make_chain_loader(spots, daily_iv)

    base_config = {
        'strategy_key': strategy,
        'lot_size': 25,
        'signal_mode': 'always',
        'entry_dte_range': (3, 7),
        'exit_dte': 1,
        'profit_target_pct': 0.50,
        'initial_capital': 500_000,
        'symbol': 'NIFTY',
    }

    # Step 1: Walk-Forward Analysis
    print("\n═══ Walk-Forward Analysis ═══")
    wfa_result = walk_forward.run_wfa(base_config, loader, spots, {
        'n_windows': 4,
        'in_ratio': 0.70,
        'param_grid': {
            'entry_dte_min': [2, 3, 4],
            'entry_dte_max': [5, 7],
        },
    })
    for w in wfa_result['windows']:
        print(f"  Window {w['window']}: IS fitness={w['in_sample_fitness']}, "
              f"OOS trades={w['out_trades']}, OOS P/L=₹{w['out_net_pnl']:,.0f}")

    oos_trades = wfa_result['oos_trades']
    oos_metrics = wfa_result['oos_metrics']
    print(f"\n  Combined OOS: {len(oos_trades)} trades, "
          f"net ₹{oos_metrics['net_pnl']:,.0f}, "
          f"return/DD {oos_metrics.get('return_dd_ratio', 0)}")

    # Step 2: Monte Carlo on OOS trades
    print("\n═══ Monte Carlo (10,000 sims) ═══")
    mc_result = None
    if len(oos_trades) >= 3:
        mc_result = monte_carlo.run_mc(oos_trades, {'n_sims': 10_000, 'seed': 42})
        print(f"  Median return: {mc_result['median_return_pct']}%")
        print(f"  Median DD: {mc_result['median_dd_pct']}%")
        print(f"  Risk of ruin: {mc_result['risk_of_ruin_pct']}%")
        print(f"  Pass Davey (10th pctl return/DD ≥ 2.0): "
              f"{'YES' if mc_result['pass_davey'] else 'NO'}")
    else:
        print(f"  Skipped: only {len(oos_trades)} OOS trades (need ≥ 3)")

    # Step 3: Full backtest for equity curve + report
    print("\n═══ Full Backtest ═══")
    full_result = engine.run(base_config, loader, spots)

    r = report.generate(full_result, mc_result=mc_result, wfa_result=wfa_result)
    txt = report.summary_text(r)
    print(f"\n{txt}")

    os.makedirs('options/backtest/reports', exist_ok=True)
    path = report.save_json(r, f'options/backtest/reports/{strategy}_nifty.json')
    print(f"\nReport saved: {path}")

    gates = r['davey_gates']
    all_pass = all(g.get('pass') for g in gates.values())
    print(f"\n{'✓ ALL DAVEY GATES PASS — strategy viable' if all_pass else '✗ SOME GATES FAIL — strategy needs work'}")

    return r


if __name__ == '__main__':
    run_pipeline('short_straddle', months=6)
