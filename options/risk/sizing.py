"""
Position sizing: fractional Kelly criterion.

Sinclair Ch.9: 0.05-0.48× Kelly. 25% over-bet turns +EV into loss.
Non-normal adjustment: f*_adj = f* × [1 + (skew/6)×f* + ((kurt-3)/24)×f*²]
"""

import math


# Hard guardrails (ARCHITECTURE.md + Sinclair Ch.9)
MAX_PER_POSITION = 0.05       # 5% of capital per position
MAX_CORRELATED = 0.20         # 20% in correlated positions
MAX_DEPLOYED = 0.50           # 50% total deployed
PORTFOLIO_STOP_DD = 0.15      # -15% drawdown → cut all by 50%
DEFAULT_FRACTIONAL = 0.25     # quarter-Kelly default


def kelly_fraction(win_prob, win_loss_ratio):
    """
    Classic Kelly: f* = (p×b - q) / b

    Parameters
    ----------
    win_prob : float — probability of winning (0-1)
    win_loss_ratio : float — avg_win / avg_loss (b)

    Returns
    -------
    float: optimal fraction (can be negative → don't bet)
    """
    if win_loss_ratio <= 0:
        return 0.0
    p = max(0.0, min(1.0, win_prob))
    q = 1.0 - p
    return (p * win_loss_ratio - q) / win_loss_ratio


def adjusted_kelly(raw_kelly, skewness=0.0, kurtosis=3.0):
    """
    Non-normal Kelly adjustment (Sinclair eq.9.37-9.38).

    f*_adj = f* × [1 + (skew/6)×f* + ((kurt-3)/24)×f*²]

    Short-vol has negative skew → reduces Kelly.
    Fat tails (kurt > 3) → also reduces Kelly.
    """
    f = raw_kelly
    adj = 1.0 + (skewness / 6) * f + ((kurtosis - 3) / 24) * f * f
    return f * adj


def position_size(capital, kelly_frac, max_loss_per_lot, lot_size=65,
                  fractional=DEFAULT_FRACTIONAL):
    """
    Compute number of lots from Kelly fraction.

    Parameters
    ----------
    capital : float — total trading capital
    kelly_frac : float — raw or adjusted Kelly fraction
    max_loss_per_lot : float — worst-case loss per lot (positive number)
    lot_size : int
    fractional : float — fraction of Kelly to use (default 0.25)

    Returns
    -------
    dict: lots, capital_at_risk, kelly_raw, kelly_used, warnings
    """
    warnings = []

    if kelly_frac <= 0:
        return {'lots': 0, 'capital_at_risk': 0, 'kelly_raw': kelly_frac,
                'kelly_used': 0, 'warnings': ['Negative edge — do not trade']}

    # Sinclair: practical range 0.05-0.48×
    frac = max(0.05, min(0.48, fractional))
    kelly_used = kelly_frac * frac

    # Capital to risk
    risk_capital = capital * min(kelly_used, MAX_PER_POSITION)

    if max_loss_per_lot <= 0:
        warnings.append('Cannot size: max_loss_per_lot must be positive')
        return {'lots': 0, 'capital_at_risk': 0, 'kelly_raw': kelly_frac,
                'kelly_used': kelly_used, 'warnings': warnings}

    lots = int(risk_capital / max_loss_per_lot)
    lots = max(lots, 0)

    actual_risk = lots * max_loss_per_lot
    risk_pct = actual_risk / capital if capital > 0 else 0

    if risk_pct > MAX_PER_POSITION:
        lots = int(capital * MAX_PER_POSITION / max_loss_per_lot)
        actual_risk = lots * max_loss_per_lot
        warnings.append(f'Capped at {MAX_PER_POSITION:.0%} per-position limit')

    return {
        'lots': lots,
        'capital_at_risk': round(actual_risk, 2),
        'capital_pct': round(actual_risk / capital * 100, 2) if capital > 0 else 0,
        'kelly_raw': round(kelly_frac, 4),
        'kelly_used': round(kelly_used, 4),
        'fractional': frac,
        'warnings': warnings,
    }


def validate_portfolio_limits(positions, capital):
    """
    Check portfolio-level hard guardrails.

    Parameters
    ----------
    positions : list of dicts — each has 'capital_at_risk', 'correlated_group' (optional)

    Returns
    -------
    dict: deployed_pct, correlated_groups, violations (list of strings)
    """
    violations = []

    total_risk = sum(p.get('capital_at_risk', 0) for p in positions)
    deployed_pct = total_risk / capital if capital > 0 else 0

    if deployed_pct > MAX_DEPLOYED:
        violations.append(
            f'Total deployed {deployed_pct:.0%} exceeds {MAX_DEPLOYED:.0%} limit')

    # Check correlated groups (Sinclair Ch.8: correlation kills diversification)
    groups = {}
    for p in positions:
        grp = p.get('correlated_group', 'default')
        groups.setdefault(grp, 0)
        groups[grp] += p.get('capital_at_risk', 0)

    for grp, risk in groups.items():
        grp_pct = risk / capital if capital > 0 else 0
        if grp_pct > MAX_CORRELATED:
            violations.append(
                f'Correlated group "{grp}" at {grp_pct:.0%} exceeds '
                f'{MAX_CORRELATED:.0%} limit')

    return {
        'total_deployed': round(total_risk, 2),
        'deployed_pct': round(deployed_pct * 100, 2),
        'correlated_groups': {k: round(v, 2) for k, v in groups.items()},
        'violations': violations,
        'ok': len(violations) == 0,
    }


def drawdown_check(equity_curve):
    """
    Portfolio-level stop: -15% drawdown → reduce all by 50% (Sinclair Ch.9).

    Parameters
    ----------
    equity_curve : list of floats — sequential equity values

    Returns
    -------
    dict: max_dd, current_dd, action
    """
    if not equity_curve or len(equity_curve) < 2:
        return {'max_dd': 0, 'current_dd': 0, 'action': 'none'}

    peak = equity_curve[0]
    max_dd = 0.0
    current_dd = 0.0

    for val in equity_curve:
        if val > peak:
            peak = val
        dd = (peak - val) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)
        current_dd = dd

    action = 'none'
    if current_dd >= PORTFOLIO_STOP_DD:
        action = 'reduce_50pct'

    return {
        'max_dd': round(max_dd * 100, 2),
        'current_dd': round(current_dd * 100, 2),
        'peak': peak,
        'action': action,
    }


def _self_check():
    # Classic Kelly
    f = kelly_fraction(0.55, 1.0)
    assert abs(f - 0.10) < 0.01, f"Expected ~0.10, got {f}"

    # Non-normal adjustment (negative skew reduces Kelly)
    adj = adjusted_kelly(0.10, skewness=-2.0, kurtosis=8.0)
    assert adj < 0.10, f"Negative skew should reduce Kelly: {adj}"

    # Normal distribution (skew=0, kurt=3) → no adjustment
    adj_normal = adjusted_kelly(0.10, 0.0, 3.0)
    assert abs(adj_normal - 0.10) < 0.001

    # Position sizing
    result = position_size(1_000_000, 0.10, 15000, lot_size=65)
    assert result['lots'] > 0
    assert result['capital_pct'] <= 5.0, "Must respect 5% cap"

    # Negative edge → 0 lots
    result = position_size(1_000_000, -0.05, 15000)
    assert result['lots'] == 0

    # Portfolio limits — within limits
    positions = [
        {'capital_at_risk': 40_000, 'correlated_group': 'nifty'},
        {'capital_at_risk': 40_000, 'correlated_group': 'banknifty'},
        {'capital_at_risk': 30_000, 'correlated_group': 'finnifty'},
    ]
    check = validate_portfolio_limits(positions, 500_000)
    assert check['ok'], f"Should be within limits: {check['violations']}"

    # Breach correlated limit
    positions[0]['capital_at_risk'] = 150_000
    check = validate_portfolio_limits(positions, 500_000)
    assert not check['ok']
    assert any('nifty' in v for v in check['violations'])

    # Drawdown check
    curve = [100, 105, 110, 95, 85, 82]
    dd = drawdown_check(curve)
    assert dd['action'] == 'reduce_50pct'
    assert dd['max_dd'] > 15

    curve_ok = [100, 105, 110, 108, 107]
    dd = drawdown_check(curve_ok)
    assert dd['action'] == 'none'

    print("sizing.py: all checks passed")


if __name__ == '__main__':
    _self_check()
