"""
Batch-run multiple strategies through the Davey pipeline using cached Dhan data.
Loads spot + IV from _data_cache.json, runs WFA → MC → report for each strategy.
"""

import datetime
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import pandas as pd
from options.core import bsm
from options.backtest import engine, walk_forward, monte_carlo, report
from options.strategies import registry


CACHE_PATH = os.path.join(os.path.dirname(__file__), 'reports', '_data_cache.json')

STRATEGIES = [
    'bear_put_spread',
    'bear_call_spread',
    'short_strangle',
    'iron_butterfly',
    'bull_put_spread',
    'jade_lizard',
    'ratio_put_backspread',
    'short_straddle',
    'iron_condor',
    'long_butterfly',
    'bull_call_spread',
    'long_put',
    'long_straddle',
    'long_strangle',
    'long_call',
]


def _skewed_iv(atm_iv, strike, spot, t, b=-0.12, c=0.004):
    """Natenberg Ch.24 parabolic skew for equity indices.

    σ(K) = σ_ATM × (1 + b·x + c·x²)
    x = ln(K/S) / (σ_ATM·√t)   [standardized moneyness]

    b < 0 = investment skew (OTM puts more expensive).
    c > 0 = slight smile curvature (both tails lift).
    Defaults calibrated to typical NIFTY 25-delta put skew (~3-5 vol pts).
    """
    denom = atm_iv * math.sqrt(max(t, 1 / 365))
    if denom < 0.001:
        return atm_iv
    x = math.log(strike / spot) / denom
    return max(0.01, atm_iv * (1.0 + b * x + c * x * x))


def nifty_lot_size(dt):
    """NSE standard NIFTY lot sizes by period."""
    if dt < datetime.date(2019, 6, 28):
        return 75
    if dt < datetime.date(2024, 11, 22):
        return 50
    return 75


def load_cache():
    with open(CACHE_PATH) as f:
        raw = json.load(f)
    spots = {datetime.date.fromisoformat(k): v for k, v in raw['spots'].items()}
    daily_iv = {datetime.date.fromisoformat(k): v for k, v in raw['daily_iv'].items()}
    return spots, daily_iv


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

        if iv > 1:
            iv = iv / 100.0

        expiry = _next_thursday(dt)
        t = max((expiry - dt).days, 1) / 365

        rows = []
        for k in range(int(spot - 800), int(spot + 850), 50):
            for ot in ['CE', 'PE']:
                strike_iv = _skewed_iv(iv, float(k), spot, t)
                p = max(0.05, bsm.bsm_price(spot, float(k), t, 0.07, strike_iv, ot))
                rows.append({
                    'strike': float(k), 'option_type': ot, 'expiry': expiry,
                    'settle': round(p, 2), 'iv': round(strike_iv, 4),
                    'volume': 50000, 'oi': 100000,
                })

        cache[dt] = pd.DataFrame(rows)
        return cache[dt]

    return loader


def run_one(strategy, loader, spots):
    mid_date = sorted(spots.keys())[len(spots) // 2]
    base_config = {
        'strategy_key': strategy,
        'lot_size': nifty_lot_size(mid_date),
        'signal_mode': 'vp',
        'vp_threshold': 0.02,
        'entry_dte_range': (3, 7),
        'exit_dte': 1,
        'profit_target_pct': 0.50,
        'initial_capital': 500_000,
        'max_lots': 4,
        'max_concurrent': 2,
        'max_margin_usage': 0.40,
        'symbol': 'NIFTY',
    }

    # WFA
    wfa_result = walk_forward.run_wfa(base_config, loader, spots, {
        'n_windows': 4,
        'in_ratio': 0.70,
        'param_grid': {
            'entry_dte_min': [2, 3, 4],
            'entry_dte_max': [5, 7],
        },
    })

    oos_trades = wfa_result['oos_trades']
    oos_metrics = wfa_result['oos_metrics']

    # MC
    mc_result = None
    if len(oos_trades) >= 3:
        mc_result = monte_carlo.run_mc(oos_trades, {'n_sims': 10_000, 'seed': 42})

    # Full backtest
    full_result = engine.run(base_config, loader, spots)
    r = report.generate(full_result, mc_result=mc_result, wfa_result=wfa_result)

    os.makedirs('options/backtest/reports', exist_ok=True)
    report.save_json(r, f'options/backtest/reports/{strategy}_nifty.json')

    return r


def print_summary(strategy, r):
    m = r.get('metrics', {})
    gates = r.get('davey_gates', {})
    mc = r.get('monte_carlo', {})
    all_pass = all(g.get('pass') for g in gates.values()) if gates else False

    net = m.get('net_pnl', 0)
    trades = m.get('total_trades', 0)
    wr = m.get('win_rate', 0)
    pf = m.get('profit_factor', 0)
    dd = m.get('max_drawdown_pct', 0)
    sr = m.get('sharpe_ratio', 0)
    gsr_val = m.get('gsr', 0)
    ret_dd = m.get('return_dd_ratio', 0)
    ruin = mc.get('risk_of_ruin_pct', '-')

    status = 'PASS' if all_pass else 'FAIL'
    print(f"  {strategy:<22s} | {trades:3d} trades | net ₹{net:>8,.0f} | "
          f"WR {wr:4.0%} | PF {pf:4.2f} | DD {dd:5.1f}% | "
          f"SR {sr:5.2f} | GSR {gsr_val:5.2f} | ret/DD {ret_dd:4.1f} | "
          f"ruin {ruin}% | {status}")
    return all_pass


def main():
    strategies = sys.argv[1:] if len(sys.argv) > 1 else STRATEGIES

    print("Loading cached data...")
    spots, daily_iv = load_cache()
    loader = make_chain_loader(spots, daily_iv)
    dates = sorted(spots.keys())
    print(f"  {len(dates)} days: {dates[0]} → {dates[-1]}")
    print(f"  Spot: ₹{min(spots.values()):,.0f} — ₹{max(spots.values()):,.0f}")
    iv_vals = [v for v in daily_iv.values() if v > 0]
    if iv_vals:
        print(f"  IV: {min(iv_vals):.1f}% — {max(iv_vals):.1f}%\n")

    print("═" * 130)
    print(f"  {'Strategy':<22s} | {'Trd':>3s} trades | {'Net P/L':>12s} | "
          f"{'WR':>4s} | {'PF':>4s} | {'DD':>5s} | "
          f"{'SR':>5s} | {'GSR':>5s} | {'R/DD':>4s} | "
          f"{'Ruin':>4s} | Gate")
    print("═" * 130)

    bad = [s for s in strategies if registry.get(s) is None]
    if bad:
        print(f"  ERROR: unknown strategies: {bad}")
        print(f"  Valid: {[s.key for s in registry.list_strategies()]}")
        return

    results = {}
    for strat in strategies:
        try:
            r = run_one(strat, loader, spots)
            passed = print_summary(strat, r)
            results[strat] = (r, passed)
        except Exception as e:
            print(f"  {strat:<22s} | ERROR: {e}")
            results[strat] = (None, False)

    print("═" * 130)

    passing = [s for s, (_, p) in results.items() if p]
    failing = [s for s, (_, p) in results.items() if not p]
    errored = [s for s, (r, _) in results.items() if r is None]

    print(f"\n  Davey gates PASS: {', '.join(passing) if passing else 'none'}")
    print(f"  Davey gates FAIL: {', '.join(failing) if failing else 'none'}")
    if errored:
        print(f"  Errored: {', '.join(errored)}")


if __name__ == '__main__':
    main()
