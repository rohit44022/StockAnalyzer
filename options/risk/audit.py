"""
Post-trade audit and compliance checks.

SEBI requirements:
  - Trade log with timestamps, prices, quantities
  - Position limits verified pre-trade
  - Risk limits documented
  - Margin adequacy
  - P/L attribution

Davey Ch.5: every trade must be logged with entry rationale,
exit rationale, and deviation from plan.
"""

import datetime
import json
import os


def audit_trade(trade, capital, margin_available, mwpl_status='ok'):
    """
    Pre-trade compliance audit.

    Parameters
    ----------
    trade : dict — strategy, legs, lots, entry_rationale
    capital : float
    margin_available : float
    mwpl_status : str — from limits.mwpl_check

    Returns
    -------
    dict: approved (bool), checks (list of pass/fail), rejection_reasons
    """
    checks = []
    rejections = []

    # 1. MWPL check
    if mwpl_status == 'ban':
        checks.append({'check': 'mwpl', 'status': 'FAIL',
                        'detail': 'Underlying is in ban period'})
        rejections.append('MWPL ban — no new positions')
    else:
        checks.append({'check': 'mwpl', 'status': 'PASS',
                        'detail': f'MWPL status: {mwpl_status}'})

    # 2. Entry rationale documented (Davey)
    rationale = trade.get('entry_rationale', '')
    if rationale:
        checks.append({'check': 'rationale', 'status': 'PASS',
                        'detail': 'Entry rationale documented'})
    else:
        checks.append({'check': 'rationale', 'status': 'WARN',
                        'detail': 'No entry rationale — Davey: document every trade'})

    # 3. Margin check
    estimated_margin = trade.get('estimated_margin') or 0
    if estimated_margin > 0 and margin_available > 0:
        if estimated_margin > margin_available:
            checks.append({'check': 'margin', 'status': 'FAIL',
                            'detail': f'Need ₹{estimated_margin:,.0f}, '
                                      f'have ₹{margin_available:,.0f}'})
            rejections.append('Insufficient margin')
        else:
            util = estimated_margin / margin_available * 100
            checks.append({'check': 'margin', 'status': 'PASS',
                            'detail': f'Margin utilization: {util:.1f}%'})
    else:
        checks.append({'check': 'margin', 'status': 'SKIP',
                        'detail': 'Margin data not provided'})

    # 4. Position size vs capital
    max_loss = abs(trade.get('max_loss') or 0)
    if max_loss > 0 and capital > 0:
        risk_pct = max_loss / capital * 100
        if risk_pct > 5:
            checks.append({'check': 'position_size', 'status': 'FAIL',
                            'detail': f'Risk {risk_pct:.1f}% exceeds 5% limit'})
            rejections.append(f'Position risk {risk_pct:.1f}% > 5% limit')
        elif risk_pct > 3:
            checks.append({'check': 'position_size', 'status': 'WARN',
                            'detail': f'Risk {risk_pct:.1f}% — near 5% limit'})
        else:
            checks.append({'check': 'position_size', 'status': 'PASS',
                            'detail': f'Risk {risk_pct:.1f}% of capital'})

    # 5. Strategy has exit plan
    exit_plan = trade.get('exit_plan', {})
    if exit_plan.get('stop_loss') and exit_plan.get('take_profit'):
        checks.append({'check': 'exit_plan', 'status': 'PASS',
                        'detail': 'Stop-loss and take-profit defined'})
    else:
        checks.append({'check': 'exit_plan', 'status': 'WARN',
                        'detail': 'Define stop-loss AND take-profit before entry'})

    return {
        'approved': len(rejections) == 0,
        'checks': checks,
        'rejection_reasons': rejections,
        'timestamp': datetime.datetime.now().isoformat(),
    }


def log_trade(trade, result, log_dir='trade_logs'):
    """
    Append trade to JSON log file (Davey: log everything).

    Parameters
    ----------
    trade : dict — strategy, legs, lots, rationale, etc.
    result : dict — from audit_trade
    log_dir : str — directory for log files

    Returns
    -------
    str: path to log file
    """
    os.makedirs(log_dir, exist_ok=True)
    today = datetime.date.today().isoformat()
    path = os.path.join(log_dir, f'trades_{today}.jsonl')

    entry = {
        'timestamp': datetime.datetime.now().isoformat(),
        'trade': trade,
        'audit_result': result,
    }

    with open(path, 'a') as f:
        f.write(json.dumps(entry, default=str) + '\n')

    return path


def daily_summary(trades):
    """
    End-of-day trade summary for review.

    Parameters
    ----------
    trades : list of trade dicts with 'pnl', 'strategy', 'status'

    Returns
    -------
    dict: total_pnl, trade_count, win/loss, by_strategy
    """
    if not trades:
        return {'total_pnl': 0, 'trade_count': 0, 'wins': 0, 'losses': 0,
                'by_strategy': {}}

    total_pnl = sum(t.get('pnl', 0) for t in trades)
    wins = sum(1 for t in trades if t.get('pnl', 0) > 0)
    losses = sum(1 for t in trades if t.get('pnl', 0) < 0)

    by_strategy = {}
    for t in trades:
        s = t.get('strategy', 'unknown')
        by_strategy.setdefault(s, {'count': 0, 'pnl': 0})
        by_strategy[s]['count'] += 1
        by_strategy[s]['pnl'] += t.get('pnl', 0)

    return {
        'total_pnl': round(total_pnl, 2),
        'trade_count': len(trades),
        'wins': wins,
        'losses': losses,
        'win_rate': round(wins / len(trades) * 100, 1) if trades else 0,
        'by_strategy': by_strategy,
    }


def _self_check():
    trade = {
        'strategy': 'iron_condor',
        'legs': [{'strike': 23900, 'action': 'SELL'}],
        'lots': 2,
        'entry_rationale': 'VP=4.2%, VIX=16, neutral outlook',
        'estimated_margin': 80_000,
        'max_loss': 30_000,
        'exit_plan': {'stop_loss': -21_000, 'take_profit': 15_000},
    }

    # Passes all
    result = audit_trade(trade, capital=1_000_000, margin_available=500_000)
    assert result['approved']
    assert all(c['status'] in ('PASS', 'WARN') for c in result['checks'])

    # Ban → rejected
    result_ban = audit_trade(trade, 1_000_000, 500_000, mwpl_status='ban')
    assert not result_ban['approved']

    # Oversized → rejected
    big_trade = {**trade, 'max_loss': 60_000}
    result_big = audit_trade(big_trade, capital=1_000_000, margin_available=500_000)
    assert not result_big['approved']

    # Daily summary
    trades = [
        {'strategy': 'iron_condor', 'pnl': 5000},
        {'strategy': 'iron_condor', 'pnl': -3000},
        {'strategy': 'bull_put_spread', 'pnl': 2000},
    ]
    ds = daily_summary(trades)
    assert ds['total_pnl'] == 4000
    assert ds['wins'] == 2
    assert ds['losses'] == 1
    assert ds['win_rate'] == 66.7

    print("audit.py: all checks passed")


if __name__ == '__main__':
    _self_check()
