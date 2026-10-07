"""
Backtest report generator — JSON-serializable output.

Combines engine result, walk-forward, and Monte Carlo into one report.
"""

import json
import os
import datetime
from . import metrics


def generate(engine_result, mc_result=None, wfa_result=None):
    """
    Build a complete backtest report.

    Returns dict suitable for json.dumps() or template rendering.
    """
    cfg = engine_result.get('config', {})
    m = engine_result.get('metrics', {})
    trades = engine_result.get('trades', [])

    report = {
        'generated': datetime.datetime.now().isoformat(),
        'strategy': cfg.get('strategy_key', ''),
        'symbol': cfg.get('symbol', 'NIFTY'),
        'period': {
            'start': engine_result['equity_dates'][0].isoformat() if engine_result.get('equity_dates') else '',
            'end': engine_result['equity_dates'][-1].isoformat() if engine_result.get('equity_dates') else '',
            'trading_days': len(engine_result.get('equity_dates', [])),
        },
        'config': {k: _jsonable(v) for k, v in cfg.items()},
        'summary': {
            'total_trades': m.get('total_trades', 0),
            'net_pnl': m.get('net_pnl', 0),
            'gross_pnl': m.get('gross_pnl', 0),
            'total_costs': m.get('total_costs', 0),
            'cost_pct_of_gross': m.get('cost_pct_of_gross', 0),
            'win_rate_pct': m.get('win_rate_pct', 0),
            'profit_factor': m.get('profit_factor', 0),
            'avg_trade': m.get('avg_trade', {}),
        },
        'risk_metrics': {
            'sharpe': m.get('sharpe', 0),
            'sortino': m.get('sortino', 0),
            'gsr': m.get('gsr', 0),
            'calmar': m.get('calmar', 0),
            'return_dd_ratio': m.get('return_dd_ratio', 0),
            'max_drawdown': m.get('max_drawdown', {}),
            'tharp_expectancy': m.get('tharp_expectancy', 0),
        },
        'davey_gates': _davey_gates(m, mc_result, trades),
        'cost_analysis': _cost_analysis(trades),
        'trades': [_trade_summary(t) for t in trades],
        'warnings': engine_result.get('warnings', []),
    }

    if mc_result:
        report['monte_carlo'] = mc_result
    if wfa_result:
        report['walk_forward'] = {
            'windows': wfa_result.get('windows', []),
            'oos_metrics': wfa_result.get('oos_metrics', {}),
        }

    return report


def summary_text(report):
    """One-page text summary for terminal output."""
    s = report.get('summary', {})
    r = report.get('risk_metrics', {})
    d = report.get('davey_gates', {})
    lines = [
        f"═══ {report.get('strategy', '?')} on {report.get('symbol', '?')} ═══",
        f"Period: {report['period']['start']} → {report['period']['end']} "
        f"({report['period']['trading_days']} days)",
        f"Trades: {s['total_trades']}  Win: {s['win_rate_pct']}%  "
        f"PF: {s['profit_factor']}",
        f"Gross: ₹{s['gross_pnl']:,.0f}  Costs: ₹{s['total_costs']:,.0f} "
        f"({s['cost_pct_of_gross']}%)  Net: ₹{s['net_pnl']:,.0f}",
        f"Avg win: ₹{s['avg_trade'].get('avg_win', 0):,.0f}  "
        f"Avg loss: ₹{s['avg_trade'].get('avg_loss', 0):,.0f}",
        "",
        f"Sharpe: {r['sharpe']}  Sortino: {r['sortino']}  "
        f"GSR: {r['gsr']}  Calmar: {r['calmar']}",
        f"Return/DD: {r['return_dd_ratio']}  "
        f"Max DD: ₹{r['max_drawdown'].get('amount', 0):,.0f} "
        f"({r['max_drawdown'].get('pct', 0)}%)",
        f"Tharp: {r['tharp_expectancy']}",
        "",
        "Davey gates:",
    ]
    for gate, info in d.items():
        status = "✓" if info.get('pass') else "✗"
        lines.append(f"  {status} {gate}: {info.get('value', '?')} "
                      f"(need {info.get('threshold', '?')})")

    mc = report.get('monte_carlo')
    if mc:
        lines.append("")
        lines.append(f"Monte Carlo ({mc['n_sims']} sims):")
        lines.append(f"  Median DD: {mc['median_dd_pct']}%  "
                      f"Risk of ruin: {mc['risk_of_ruin_pct']}%")
        lines.append(f"  Pass Davey (10th pctl return/DD ≥ 2.0): "
                      f"{'YES' if mc.get('pass_davey') else 'NO'}")

    return "\n".join(lines)


def save_json(report, path):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    return path


def _davey_gates(m, mc_result, trades=None):
    gates = {
        'return_dd_ratio': {
            'value': m.get('return_dd_ratio', 0),
            'threshold': '>2.0',
            'pass': (m.get('return_dd_ratio', 0) or 0) >= 2.0,
        },
        'profit_factor': {
            'value': m.get('profit_factor', 0),
            'threshold': '>1.0',
            'pass': (m.get('profit_factor', 0) or 0) > 1.0,
        },
        'max_dd_pct': {
            'value': m.get('max_drawdown', {}).get('pct', 0),
            'threshold': '<40%',
            'pass': m.get('max_drawdown', {}).get('pct', 0) < 40,
        },
        'min_trades': {
            'value': m.get('total_trades', 0),
            'threshold': '≥30',
            'pass': m.get('total_trades', 0) >= 30,
        },
    }
    if mc_result:
        gates['mc_risk_of_ruin'] = {
            'value': mc_result.get('risk_of_ruin_pct', 0),
            'threshold': '<10%',
            'pass': mc_result.get('risk_of_ruin_pct', 0) < 10,
        }
    if trades and len(trades) >= 3:
        t_result = metrics.t_test_oos(trades)
        gates['t_test_significance'] = {
            'value': round(t_result['p_value'], 4),
            'threshold': '<0.05',
            'pass': t_result['significant'],
        }
    return gates


def _cost_analysis(trades):
    if not trades:
        return {'total': 0, 'per_trade_avg': 0, 'pct_of_gross': 0}
    total = sum(t.get('costs_total', 0) for t in trades)
    gross = sum(abs(t.get('gross_pnl', 0)) for t in trades)
    return {
        'total': round(total, 2),
        'per_trade_avg': round(total / len(trades), 2),
        'pct_of_gross': round(total / gross * 100, 1) if gross > 0 else 0,
    }


def _trade_summary(t):
    return {
        'id': t.get('trade_id'),
        'entry': t.get('entry_date'),
        'exit': t.get('exit_date'),
        'days': t.get('holding_days'),
        'gross': t.get('gross_pnl'),
        'costs': t.get('costs_total'),
        'net': t.get('net_pnl'),
        'reason': t.get('exit_reason'),
    }


def _jsonable(v):
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    if isinstance(v, tuple):
        return list(v)
    if isinstance(v, float) and (v == float('inf') or v == float('-inf')):
        return str(v)
    return v


def _self_check():
    trades = [
        {'trade_id': 1, 'net_pnl': 5000, 'gross_pnl': 5200, 'costs_total': 200,
         'entry_date': '2026-09-01', 'exit_date': '2026-09-15', 'holding_days': 14,
         'exit_reason': 'profit_target'},
        {'trade_id': 2, 'net_pnl': -3000, 'gross_pnl': -2800, 'costs_total': 200,
         'entry_date': '2026-09-16', 'exit_date': '2026-09-28', 'holding_days': 12,
         'exit_reason': 'stop_loss'},
    ]

    engine_result = {
        'trades': trades,
        'equity_curve': [1_000_000, 1_005_000, 1_002_000],
        'equity_dates': [
            datetime.date(2026, 9, 1),
            datetime.date(2026, 9, 15),
            datetime.date(2026, 9, 28),
        ],
        'metrics': metrics.compute_all(trades),
        'config': {'strategy_key': 'short_straddle', 'symbol': 'NIFTY'},
        'warnings': [],
    }

    mc = {
        'n_sims': 1000, 'n_trades': 2, 'risk_of_ruin_pct': 0.0,
        'ruin_threshold': 0.50, 'median_dd_pct': 0.3, 'median_return_pct': 0.2,
        'median_return_dd': 0.67, 'pass_davey': False,
        'max_dd_percentiles': {}, 'return_percentiles': {},
        'return_dd_percentiles': {},
    }

    report = generate(engine_result, mc_result=mc)
    assert 'summary' in report
    assert 'davey_gates' in report
    assert 'monte_carlo' in report
    assert report['strategy'] == 'short_straddle'

    txt = summary_text(report)
    assert 'short_straddle' in txt
    assert 'Davey gates' in txt

    print(txt)
    print("\nreport.py: all checks passed")


if __name__ == '__main__':
    _self_check()
