"""
Walk-forward analysis (Davey Ch.13).

Anchored: expanding in-sample, fixed out-of-sample.
Unanchored (default): rolling in/out windows.
Fitness: net profit, return/DD, or custom.

ponytail: grid search over VP threshold + DTE range only. 3 params,
small grid (~27-64 combos). Add params when edge stabilises.
"""

import datetime
from . import engine, metrics


DEFAULT_PARAM_GRID = {
    'vp_threshold': [0.01, 0.02, 0.03, 0.04],
    'entry_dte_min': [7, 14],
    'entry_dte_max': [21, 30],
}


def run_wfa(config_base, chain_loader, spot_series, wfa_config=None):
    """
    Walk-forward analysis.

    config_base : dict — base backtest config (strategy, symbol, lot_size, etc.)
    chain_loader : callable(date) -> DataFrame or None
    spot_series : dict {date: close}
    wfa_config : dict
        in_ratio : float — in-sample fraction (default 0.70)
        out_ratio : float — out-of-sample fraction (default 0.30)
        n_windows : int — number of WFA windows (default 4)
        anchored : bool — expanding in-sample (default False = rolling)
        param_grid : dict — {param_name: [values]}
        fitness : str — 'net_profit' or 'return_dd' (default 'return_dd')
    """
    wc = {
        'in_ratio': 0.70,
        'out_ratio': 0.30,
        'n_windows': 4,
        'anchored': False,
        'param_grid': DEFAULT_PARAM_GRID,
        'fitness': 'return_dd',
    }
    if wfa_config:
        wc.update(wfa_config)

    dates = sorted(spot_series.keys())
    start = config_base.get('start_date', dates[0])
    end = config_base.get('end_date', dates[-1])
    trading_dates = [d for d in dates if start <= d <= end]

    windows = _split_windows(trading_dates, wc)
    oos_trades = []
    window_results = []

    for i, (in_dates, out_dates) in enumerate(windows):
        best_params = _optimize(
            config_base, chain_loader, spot_series,
            in_dates, wc['param_grid'], wc['fitness']
        )

        out_config = dict(config_base)
        out_config.update(best_params)
        out_config['start_date'] = out_dates[0]
        out_config['end_date'] = out_dates[-1]

        out_result = engine.run(out_config, chain_loader, spot_series)

        oos_trades.extend(out_result['trades'])
        window_results.append({
            'window': i + 1,
            'in_start': in_dates[0].isoformat(),
            'in_end': in_dates[-1].isoformat(),
            'out_start': out_dates[0].isoformat(),
            'out_end': out_dates[-1].isoformat(),
            'best_params': best_params,
            'in_sample_fitness': best_params.get('_fitness', 0),
            'out_trades': len(out_result['trades']),
            'out_net_pnl': out_result['metrics']['net_pnl'],
        })

    combined_eq = metrics.equity_from_trades(oos_trades, config_base.get('initial_capital', 1_000_000))
    combined_metrics = metrics.compute_all(oos_trades, combined_eq, config_base.get('r', 0.07))

    return {
        'windows': window_results,
        'oos_trades': oos_trades,
        'oos_equity': combined_eq,
        'oos_metrics': combined_metrics,
        'config': wc,
    }


def _split_windows(dates, wc):
    n = len(dates)
    n_win = wc['n_windows']
    in_ratio = wc['in_ratio']
    anchored = wc['anchored']

    in_size = max(1, int(n * in_ratio))
    oos_total = n - in_size
    if oos_total < n_win:
        if n > 10:
            return [(dates[:int(n * in_ratio)], dates[int(n * in_ratio):])]
        return []

    out_size = oos_total // n_win

    windows = []
    for i in range(n_win):
        out_start = in_size + i * out_size
        out_end = out_start + out_size if i < n_win - 1 else n

        if out_start >= n:
            break

        if anchored:
            in_s = dates[0:out_start]
        else:
            in_start_idx = max(0, out_start - in_size)
            in_s = dates[in_start_idx:out_start]

        out_s = dates[out_start:out_end]
        if in_s and out_s:
            windows.append((in_s, out_s))

    return windows


def _optimize(config_base, chain_loader, spot_series, in_dates, param_grid, fitness_fn):
    combos = _grid_combos(param_grid)
    best_fitness = float('-inf')
    best_params = {}

    for combo in combos:
        cfg = dict(config_base)
        if 'entry_dte_min' in combo and 'entry_dte_max' in combo:
            cfg['entry_dte_range'] = (combo['entry_dte_min'], combo['entry_dte_max'])
        for k, v in combo.items():
            if k not in ('entry_dte_min', 'entry_dte_max'):
                cfg[k] = v
        cfg['start_date'] = in_dates[0]
        cfg['end_date'] = in_dates[-1]

        result = engine.run(cfg, chain_loader, spot_series)
        f = _fitness(result, fitness_fn)

        if f > best_fitness:
            best_fitness = f
            best_params = dict(combo)
            best_params['_fitness'] = round(f, 2)

    return best_params


def _grid_combos(grid):
    keys = list(grid.keys())
    if not keys:
        return [{}]
    combos = [{}]
    for key in keys:
        new = []
        for val in grid[key]:
            for c in combos:
                nc = dict(c)
                nc[key] = val
                new.append(nc)
        combos = new
    return combos


def _fitness(result, fn_name):
    if fn_name == 'net_profit':
        return result['metrics'].get('net_pnl', 0)
    if fn_name == 'return_dd':
        return result['metrics'].get('return_dd_ratio', 0)
    return result['metrics'].get('net_pnl', 0)


def _self_check():
    from ..core import bsm
    import random

    spot = 24000.0
    start = datetime.date(2026, 6, 1)
    expiry_dates = [
        datetime.date(2026, 6, 25), datetime.date(2026, 7, 30),
        datetime.date(2026, 8, 27), datetime.date(2026, 9, 24),
        datetime.date(2026, 10, 29),
    ]

    random.seed(99)
    spots = {}
    s = spot
    for i in range(150):
        d = start + datetime.timedelta(days=i)
        if d.weekday() < 5:
            s += random.gauss(0, 40)
            spots[d] = round(s, 2)

    def make_chain(dt, sp):
        near_exp = min(expiry_dates, key=lambda e: abs((e - dt).days)
                       if e >= dt else 999)
        if (near_exp - dt).days < 0:
            near_exp = min((e for e in expiry_dates if e >= dt), default=None)
        if not near_exp:
            return None
        rows = []
        t = max((near_exp - dt).days, 1) / 365
        for k in range(23000, 25001, 200):
            for ot in ['CE', 'PE']:
                p = max(0.05, bsm.bsm_price(sp, k, t, 0.07, 0.16, ot))
                rows.append({'strike': float(k), 'option_type': ot,
                             'expiry': near_exp, 'settle': round(p, 2),
                             'volume': 50000, 'oi': 100000})
        return pd.DataFrame(rows)

    import pandas as pd
    cache = {}
    def loader(dt):
        if dt not in spots:
            return None
        if dt not in cache:
            cache[dt] = make_chain(dt, spots[dt])
        return cache[dt]

    base_cfg = {
        'strategy_key': 'short_straddle',
        'lot_size': 65,
        'signal_mode': 'always',
        'initial_capital': 1_000_000,
    }

    result = run_wfa(base_cfg, loader, spots, {
        'n_windows': 2,
        'param_grid': {
            'entry_dte_min': [7, 14],
            'entry_dte_max': [25, 35],
        },
    })

    assert len(result['windows']) >= 1, f"Expected windows, got {len(result['windows'])}"
    assert 'oos_metrics' in result

    for w in result['windows']:
        print(f"  Window {w['window']}: IS fitness={w['in_sample_fitness']}, "
              f"OOS trades={w['out_trades']}, OOS P/L=₹{w['out_net_pnl']:,.0f}")

    m = result['oos_metrics']
    print(f"walk_forward.py: combined {m['total_trades']} OOS trades, "
          f"net ₹{m['net_pnl']:,.0f}, return/DD {m.get('return_dd_ratio', 0)}")
    print("walk_forward.py: all checks passed")


if __name__ == '__main__':
    _self_check()
