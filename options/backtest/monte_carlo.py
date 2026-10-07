"""
Monte Carlo simulation (Davey Ch.7/14).

Shuffle completed trades 10,000 times, build equity curves,
compute percentile bands for max drawdown and return.

Key gates (Davey):
  - Return/DD > 2.0
  - Risk of ruin < 10%
  - Max DD (95th percentile) < 40% of equity
"""

import math
import random as _random
from . import metrics


def run_mc(trades, config=None):
    """
    Monte Carlo simulation on completed trade P/Ls.

    trades : list of dicts with 'net_pnl' key
    config : dict
        n_sims : int (default 10000)
        initial_capital : float (default 1_000_000)
        ruin_threshold : float (default 0.50 = 50% DD)
        seed : int or None
        percentiles : list of floats (default [5, 10, 25, 50, 75, 90, 95])
    """
    cfg = {
        'n_sims': 10_000,
        'initial_capital': 1_000_000,
        'ruin_threshold': 0.50,
        'seed': None,
        'percentiles': [5, 10, 25, 50, 75, 90, 95],
    }
    if config:
        cfg.update(config)

    if len(trades) < 3:
        return _empty_result(cfg)

    pnls = [t['net_pnl'] for t in trades]
    n = len(pnls)
    n_sims = cfg['n_sims']
    cap = cfg['initial_capital']
    ruin_thresh = cfg['ruin_threshold']

    rng = _random.Random(cfg['seed'])

    dd_pcts = []
    final_returns = []
    return_dd_ratios = []
    ruin_count = 0

    for _ in range(n_sims):
        shuffled = pnls[:]
        rng.shuffle(shuffled)

        equity = cap
        peak = cap
        worst_dd_pct = 0.0

        for p in shuffled:
            equity += p
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else 0.0
            if dd > worst_dd_pct:
                worst_dd_pct = dd

        total_ret = (equity - cap) / cap
        final_returns.append(total_ret)
        dd_pcts.append(worst_dd_pct)

        rdd = total_ret / worst_dd_pct if worst_dd_pct > 0.001 else (
            float('inf') if total_ret > 0 else 0.0)
        return_dd_ratios.append(rdd)

        if worst_dd_pct >= ruin_thresh:
            ruin_count += 1

    pctls = cfg['percentiles']
    dd_pcts_sorted = sorted(dd_pcts)
    ret_sorted = sorted(final_returns)
    rdd_sorted = sorted(return_dd_ratios)

    return {
        'n_sims': n_sims,
        'n_trades': n,
        'risk_of_ruin_pct': round(ruin_count / n_sims * 100, 2),
        'ruin_threshold': ruin_thresh,
        'max_dd_percentiles': {
            p: round(_percentile(dd_pcts_sorted, p) * 100, 2) for p in pctls
        },
        'return_percentiles': {
            p: round(_percentile(ret_sorted, p) * 100, 2) for p in pctls
        },
        'return_dd_percentiles': {
            p: round(_percentile(rdd_sorted, p), 2) for p in pctls
        },
        'median_dd_pct': round(_percentile(dd_pcts_sorted, 50) * 100, 2),
        'median_return_pct': round(_percentile(ret_sorted, 50) * 100, 2),
        'median_return_dd': round(_percentile(rdd_sorted, 50), 2),
        'pass_davey': _percentile(rdd_sorted, 10) >= 2.0,
    }


def _percentile(sorted_list, pct):
    if not sorted_list:
        return 0.0
    k = (len(sorted_list) - 1) * pct / 100
    f = math.floor(k)
    c = min(f + 1, len(sorted_list) - 1)
    if f == c:
        return sorted_list[int(f)]
    return sorted_list[int(f)] + (k - f) * (sorted_list[int(c)] - sorted_list[int(f)])


def _empty_result(cfg):
    pctls = cfg['percentiles']
    return {
        'n_sims': 0, 'n_trades': 0, 'risk_of_ruin_pct': 0.0,
        'ruin_threshold': cfg['ruin_threshold'],
        'max_dd_percentiles': {p: 0.0 for p in pctls},
        'return_percentiles': {p: 0.0 for p in pctls},
        'return_dd_percentiles': {p: 0.0 for p in pctls},
        'median_dd_pct': 0.0, 'median_return_pct': 0.0,
        'median_return_dd': 0.0, 'pass_davey': False,
    }


def abort_threshold(historical_max_dd_pct, mc_result=None):
    """
    Davey Ch.14 quitting point: AVERAGE of 1.5× worst historical DD and
    95th percentile Monte Carlo DD. If live DD exceeds this → ABORT.

    Returns dict with abort_dd_pct and components.
    """
    hist_component = 1.5 * historical_max_dd_pct if historical_max_dd_pct > 0 else 0.0

    mc_component = 0.0
    if mc_result:
        dd_pctls = mc_result.get('max_dd_percentiles', {})
        # JSON roundtrip turns int keys to strings
        mc_component = dd_pctls.get(95, dd_pctls.get('95', 0.0))
        if mc_component <= 0:
            mc_component = mc_result.get('median_dd_pct', 0.0)

    if hist_component > 0 and mc_component > 0:
        threshold = (hist_component + mc_component) / 2.0
        source = 'average'
    elif hist_component > 0:
        threshold = hist_component
        source = '1.5x_historical_only'
    elif mc_component > 0:
        threshold = mc_component
        source = 'mc_95th_only'
    else:
        threshold = 50.0  # fallback to ruin threshold
        source = 'default_50pct'

    return {
        'abort_dd_pct': round(threshold, 2),
        'historical_component': round(hist_component, 2),
        'mc_95th_component': round(mc_component, 2),
        'source': source,
    }


def _self_check():
    # 20 trades: 14 wins of ₹5,000, 6 losses of -₹10,000 → net +₹10,000
    trades = (
        [{'net_pnl': 5000}] * 14 +
        [{'net_pnl': -10000}] * 6
    )

    result = run_mc(trades, {'n_sims': 5000, 'seed': 42, 'initial_capital': 500_000})

    assert result['n_sims'] == 5000
    assert result['n_trades'] == 20
    assert result['risk_of_ruin_pct'] >= 0

    # Median return should be near +2% (10K / 500K)
    assert result['median_return_pct'] > 0, f"Median return: {result['median_return_pct']}%"

    # Max DD should be positive
    assert result['median_dd_pct'] > 0

    # With these numbers, risk of ruin (50% DD) should be low
    assert result['risk_of_ruin_pct'] < 50, f"Risk of ruin: {result['risk_of_ruin_pct']}%"

    print(f"monte_carlo.py: median return {result['median_return_pct']}%, "
          f"median DD {result['median_dd_pct']}%, "
          f"risk of ruin {result['risk_of_ruin_pct']}%, "
          f"pass_davey={result['pass_davey']}")
    # abort_threshold: average of 1.5×hist and 95th MC
    at = abort_threshold(10.0, result)
    assert at['abort_dd_pct'] > 0
    assert at['historical_component'] == 15.0  # 1.5 × 10
    assert at['source'] == 'average'

    # abort_threshold: no MC
    at2 = abort_threshold(10.0, None)
    assert at2['abort_dd_pct'] == 15.0
    assert at2['source'] == '1.5x_historical_only'

    # abort_threshold: zero historical
    at3 = abort_threshold(0.0, result)
    assert at3['source'] == 'mc_95th_only'

    print("monte_carlo.py: all checks passed")


if __name__ == '__main__':
    _self_check()
