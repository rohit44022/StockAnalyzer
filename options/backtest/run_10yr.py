"""
10-year multi-regime backtest: fast single-pass for all strategies.
Skips WFA parameter optimization — uses default params to answer:
"Which strategies survive bull, bear, flat, and crash markets?"
"""

import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from options.backtest import engine, monte_carlo, report
from options.backtest.run_batch import load_cache, make_chain_loader, STRATEGIES, nifty_lot_size


REGIMES = [
    ('2016-10 to 2018-10 (BULL+FLAT)', '2016-10-06', '2018-10-05'),
    ('2018-10 to 2020-03 (BULL→CRASH)', '2018-10-06', '2020-03-31'),
    ('2020-04 to 2021-10 (STRONG BULL)', '2020-04-01', '2021-10-05'),
    ('2021-10 to 2023-10 (FLAT+BULL)', '2021-10-06', '2023-10-05'),
    ('2023-10 to 2026-10 (BULL→BEAR)', '2023-10-06', '2026-10-06'),
    ('FULL 10 YEARS', '2016-10-06', '2026-10-06'),
]


def run_regime(strategy, loader, spots, start, end):
    start_dt = datetime.date.fromisoformat(start)
    config = {
        'strategy_key': strategy,
        'lot_size': nifty_lot_size(start_dt),
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
        'start_date': start_dt,
        'end_date': datetime.date.fromisoformat(end),
    }
    result = engine.run(config, loader, spots)
    m = result.get('metrics', {})
    dd = m.get('max_drawdown', {})
    at = m.get('avg_trade', {})
    return {
        'trades': m.get('total_trades', 0),
        'net_pnl': m.get('net_pnl', 0),
        'win_rate': m.get('win_rate_pct', 0),
        'profit_factor': m.get('profit_factor', 0),
        'max_dd_pct': dd.get('pct', 0) if isinstance(dd, dict) else 0,
        'sharpe': m.get('sharpe', 0),
        'return_dd': m.get('return_dd_ratio', 0),
        'avg_pnl': at.get('avg_all', 0) if isinstance(at, dict) else 0,
        'result': result,
    }


def main():
    strategies = sys.argv[1:] if len(sys.argv) > 1 else STRATEGIES

    print("Loading 10-year data cache...")
    spots, daily_iv = load_cache()
    loader = make_chain_loader(spots, daily_iv)
    dates = sorted(spots.keys())
    print(f"  {len(dates)} days: {dates[0]} → {dates[-1]}")
    print(f"  Spot: ₹{min(spots.values()):,.0f} — ₹{max(spots.values()):,.0f}")

    # Full 10-year backtest for each strategy
    print(f"\n{'═' * 120}")
    print(f"  {'Strategy':<22s} | {'Trd':>4s} | {'Net P/L':>10s} | "
          f"{'WR':>5s} | {'PF':>5s} | {'DD':>6s} | "
          f"{'SR':>5s} | {'R/DD':>5s} | {'Avg':>8s} | MC Ruin")
    print(f"{'═' * 120}")

    all_results = {}
    for strat in strategies:
        t0 = time.time()
        try:
            r = run_regime(strat, loader, spots,
                           REGIMES[-1][1], REGIMES[-1][2])

            mc = None
            if r['result'] and len(r['result'].get('trades', [])) >= 3:
                mc = monte_carlo.run_mc(
                    r['result']['trades'],
                    {'n_sims': 10_000, 'seed': 42})

            ruin = f"{mc['risk_of_ruin_pct']:.0f}%" if mc else '-'
            elapsed = time.time() - t0

            print(f"  {strat:<22s} | {r['trades']:4d} | ₹{r['net_pnl']:>9,.0f} | "
                  f"{r['win_rate']:5.1f}% | {r['profit_factor']:5.2f} | "
                  f"{r['max_dd_pct']:5.1f}% | {r['sharpe']:5.2f} | "
                  f"{r['return_dd']:5.1f} | ₹{r['avg_pnl']:>7,.0f} | "
                  f"{ruin:>6s}  ({elapsed:.0f}s)")

            # Generate full report for passing strategies
            full_report = report.generate(
                r['result'], mc_result=mc)
            gates = full_report.get('davey_gates', {})
            all_pass = all(g.get('pass') for g in gates.values()) if gates else False

            all_results[strat] = {
                'full': r, 'mc': mc, 'report': full_report,
                'all_pass': all_pass,
            }

        except Exception as e:
            print(f"  {strat:<22s} | ERROR: {e}")
            import traceback
            traceback.print_exc()
            all_results[strat] = None

    print(f"{'═' * 120}")

    # Regime breakdown for top strategies (profitable over full period)
    profitable = [s for s, r in all_results.items()
                  if r and r['full']['net_pnl'] > 0]

    if profitable:
        print(f"\n\n{'═' * 130}")
        print(f"  REGIME BREAKDOWN — {len(profitable)} profitable strategies")
        print(f"{'═' * 130}")

        for strat in profitable:
            print(f"\n  {strat}:")
            print(f"  {'Regime':<40s} | {'Trd':>4s} | {'Net P/L':>10s} | "
                  f"{'WR':>5s} | {'PF':>5s} | {'DD':>6s} | {'Avg/Trade':>10s}")
            print(f"  {'-' * 100}")

            for regime_name, start, end in REGIMES[:-1]:
                try:
                    rr = run_regime(strat, loader, spots, start, end)
                    print(f"  {regime_name:<40s} | {rr['trades']:4d} | "
                          f"₹{rr['net_pnl']:>9,.0f} | {rr['win_rate']:5.1f}% | "
                          f"{rr['profit_factor']:5.2f} | {rr['max_dd_pct']:5.1f}% | "
                          f"₹{rr['avg_pnl']:>9,.0f}")
                except Exception as e:
                    print(f"  {regime_name:<40s} | ERROR: {e}")

    # Summary
    print(f"\n\n{'═' * 120}")
    passing = [s for s, r in all_results.items() if r and r.get('all_pass')]
    failing_profitable = [s for s in profitable if s not in passing]
    losing = [s for s, r in all_results.items()
              if r and r['full']['net_pnl'] <= 0]

    print(f"  ALL DAVEY GATES PASS: {', '.join(passing) if passing else 'none'}")
    print(f"  PROFITABLE but gates fail: {', '.join(failing_profitable) if failing_profitable else 'none'}")
    print(f"  UNPROFITABLE: {', '.join(losing) if losing else 'none'}")

    # Save reports
    os.makedirs('options/backtest/reports', exist_ok=True)
    for strat, r in all_results.items():
        if r and r.get('report'):
            report.save_json(
                r['report'],
                f'options/backtest/reports/{strat}_10yr_nifty.json')

    print(f"\n  Reports saved to options/backtest/reports/*_10yr_nifty.json")


if __name__ == '__main__':
    main()
