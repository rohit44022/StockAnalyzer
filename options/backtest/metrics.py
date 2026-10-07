"""
Performance metrics for options backtesting.

GSR (Sinclair Ch.7, Pezier & White 2006): penalizes short-vol skew/kurtosis.
Return/DD (Davey Ch.7): primary acceptance gate, >2.0.
"""

import math


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _variance(xs, mu=None):
    if len(xs) < 2:
        return 0.0
    if mu is None:
        mu = _mean(xs)
    return sum((x - mu) ** 2 for x in xs) / (len(xs) - 1)


def _std(xs, mu=None):
    return math.sqrt(max(0, _variance(xs, mu)))


def _skewness(xs):
    n = len(xs)
    if n < 3:
        return 0.0
    mu = _mean(xs)
    s = _std(xs, mu)
    if s < 1e-12:
        return 0.0
    return (n / ((n - 1) * (n - 2))) * sum(((x - mu) / s) ** 3 for x in xs)


def _kurtosis(xs):
    """Raw kurtosis (normal = 3.0)."""
    n = len(xs)
    if n < 4:
        return 3.0
    mu = _mean(xs)
    s = _std(xs, mu)
    if s < 1e-12:
        return 3.0
    m4 = sum(((x - mu) / s) ** 4 for x in xs) / n
    # Bias-corrected excess kurtosis + 3
    excess = ((n * (n + 1)) / ((n - 1) * (n - 2) * (n - 3))) * n * m4 \
             - 3.0 * (n - 1) ** 2 / ((n - 2) * (n - 3))
    return excess + 3.0


def sharpe_ratio(returns, risk_free_annual=0.07, periods_per_year=252):
    if len(returns) < 2:
        return 0.0
    rf_per = risk_free_annual / periods_per_year
    excess = [r - rf_per for r in returns]
    mu = _mean(excess)
    sigma = _std(excess)
    if sigma < 1e-10:
        return 0.0
    return round(mu / sigma * math.sqrt(periods_per_year), 4)


def sortino_ratio(returns, risk_free_annual=0.07, periods_per_year=252):
    if len(returns) < 2:
        return 0.0
    rf_per = risk_free_annual / periods_per_year
    excess = [r - rf_per for r in returns]
    mu = _mean(excess)
    downside = [min(0, x) ** 2 for x in excess]
    dd = math.sqrt(sum(downside) / len(downside)) if downside else 0.0
    if dd < 1e-10:
        return 0.0
    return round(mu / dd * math.sqrt(periods_per_year), 4)


def gsr(returns, risk_free_annual=0.07, periods_per_year=252):
    """
    Generalized Sharpe Ratio (Sinclair Ch.7, Pezier & White 2006).
    GSR = SR × [1 + (skew/6)×SR - ((kurt-3)/24)×SR²]

    Penalizes negative skew and fat tails — exactly what short-vol has.
    A short straddle with SR=1.0, skew=-2, kurt=8 → GSR ≈ 0.46.
    """
    if len(returns) < 10:
        return 0.0
    rf_per = risk_free_annual / periods_per_year
    excess = [r - rf_per for r in returns]
    mu = _mean(excess)
    sigma = _std(excess)
    if sigma < 1e-10:
        return 0.0
    sr_per = mu / sigma
    skew = _skewness(excess)
    kurt = _kurtosis(excess)
    gsr_per = sr_per * (1 + (skew / 6) * sr_per - ((kurt - 3) / 24) * sr_per ** 2)
    return round(gsr_per * math.sqrt(periods_per_year), 4)


def max_drawdown(equity_curve):
    if len(equity_curve) < 2:
        return {'amount': 0.0, 'pct': 0.0, 'peak_idx': 0, 'trough_idx': 0, 'duration': 0}
    peak = equity_curve[0]
    peak_idx = 0
    worst_dd = 0.0
    worst_pct = 0.0
    w_peak = 0
    w_trough = 0
    for i, val in enumerate(equity_curve):
        if val > peak:
            peak = val
            peak_idx = i
        dd = peak - val
        if dd > worst_dd:
            worst_dd = dd
            worst_pct = dd / peak if peak > 0 else 0.0
            w_peak = peak_idx
            w_trough = i
    return {
        'amount': round(worst_dd, 2),
        'pct': round(worst_pct * 100, 2),
        'peak_idx': w_peak,
        'trough_idx': w_trough,
        'duration': w_trough - w_peak,
    }


def calmar_ratio(equity_curve, periods_per_year=252):
    if len(equity_curve) < 2:
        return 0.0
    total_return = equity_curve[-1] / equity_curve[0] - 1
    years = len(equity_curve) / periods_per_year
    if years < 0.01:
        return 0.0
    annual_return = (1 + total_return) ** (1 / years) - 1 if total_return > -1 else -1.0
    dd = max_drawdown(equity_curve)
    if dd['pct'] < 0.01:
        return 0.0
    return round(annual_return / (dd['pct'] / 100), 2)


def return_dd_ratio(trades):
    """Davey Ch.7: total net return / max drawdown. Gate: >2.0."""
    if not trades:
        return 0.0
    pnls = [t.get('net_pnl', 0) for t in trades]
    total = sum(pnls)
    if total <= 0:
        return 0.0
    equity = [0.0]
    for p in pnls:
        equity.append(equity[-1] + p)
    dd = max_drawdown(equity)
    if dd['amount'] < 0.01:
        return float('inf') if total > 0 else 0.0
    return round(total / dd['amount'], 2)


def profit_factor(trades):
    if not trades:
        return 0.0
    wins = sum(t['net_pnl'] for t in trades if t.get('net_pnl', 0) > 0)
    losses = abs(sum(t['net_pnl'] for t in trades if t.get('net_pnl', 0) < 0))
    if losses < 0.01:
        return float('inf') if wins > 0 else 0.0
    return round(wins / losses, 2)


def win_rate(trades):
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.get('net_pnl', 0) > 0)
    return round(wins / len(trades) * 100, 1)


def avg_trade(trades):
    if not trades:
        return {'avg_win': 0.0, 'avg_loss': 0.0, 'avg_all': 0.0, 'n_wins': 0, 'n_losses': 0}
    winners = [t['net_pnl'] for t in trades if t.get('net_pnl', 0) > 0]
    losers = [t['net_pnl'] for t in trades if t.get('net_pnl', 0) < 0]
    return {
        'avg_win': round(_mean(winners), 2) if winners else 0.0,
        'avg_loss': round(_mean(losers), 2) if losers else 0.0,
        'avg_all': round(_mean([t['net_pnl'] for t in trades]), 2),
        'n_wins': len(winners),
        'n_losses': len(losers),
    }


def tharp_expectancy(trades):
    """(Davey Ch.6): (avg_trade_pnl) / |avg_loss|. Good: >0.10."""
    if not trades:
        return 0.0
    at = avg_trade(trades)
    if abs(at['avg_loss']) < 0.01:
        return 0.0
    return round(at['avg_all'] / abs(at['avg_loss']), 2)


def equity_from_trades(trades, initial=1_000_000):
    equity = [float(initial)]
    for t in trades:
        equity.append(equity[-1] + t.get('net_pnl', 0))
    return equity


def daily_returns(equity_curve):
    if len(equity_curve) < 2:
        return []
    return [
        (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
        if equity_curve[i - 1] > 0 else 0.0
        for i in range(1, len(equity_curve))
    ]


def compute_all(trades, equity_curve=None, risk_free=0.07):
    if equity_curve is None:
        equity_curve = equity_from_trades(trades)
    dr = daily_returns(equity_curve)
    dd = max_drawdown(equity_curve)
    total_costs = sum(t.get('costs_total', 0) for t in trades)
    gross = sum(t.get('gross_pnl', 0) for t in trades)
    return {
        'total_trades': len(trades),
        'net_pnl': round(sum(t.get('net_pnl', 0) for t in trades), 2),
        'gross_pnl': round(gross, 2),
        'total_costs': round(total_costs, 2),
        'cost_pct_of_gross': round(total_costs / gross * 100, 1) if abs(gross) > 0.01 else 0.0,
        'sharpe': sharpe_ratio(dr, risk_free),
        'sortino': sortino_ratio(dr, risk_free),
        'gsr': gsr(dr, risk_free),
        'calmar': calmar_ratio(equity_curve),
        'return_dd_ratio': return_dd_ratio(trades),
        'profit_factor': profit_factor(trades),
        'win_rate_pct': win_rate(trades),
        'max_drawdown': dd,
        'avg_trade': avg_trade(trades),
        'tharp_expectancy': tharp_expectancy(trades),
    }


# ── Phase 7: Incubation metrics (Davey Ch.14, Ch.23) ────────────


def t_test_oos(trades, alpha=0.05):
    """
    One-sample t-test on OOS trade P/L (Davey Ch.14).
    H0: mean P/L <= 0.  Reject (p < alpha) → edge is statistically significant.
    """
    from scipy.stats import ttest_1samp
    pnls = [t.get('net_pnl', 0) for t in trades]
    n = len(pnls)
    if n < 3:
        return {'t_stat': 0.0, 'p_value': 1.0, 'n': n, 'significant': False,
                'alpha': alpha}
    t_stat, p_two = ttest_1samp(pnls, 0)
    if math.isnan(t_stat):
        return {'t_stat': 0.0, 'p_value': 1.0, 'n': n, 'significant': False,
                'alpha': alpha}
    # One-sided: we care about mean > 0
    p_one = p_two / 2 if t_stat > 0 else 1.0 - p_two / 2
    return {
        't_stat': round(t_stat, 4),
        'p_value': round(p_one, 6),
        'n': n,
        'significant': bool(p_one < alpha and n >= 30),
        'alpha': alpha,
    }


def t_test_compare(paper_trades, wfa_trades, threshold=0.44):
    """
    Two-sample Welch's t-test comparing paper vs WFA trade distributions (Davey Ch.14).
    H0: same distribution. Want p > threshold (can't distinguish → GOOD).
    Davey: "56%+ chance distributions not different" → threshold = 0.44.
    """
    from scipy.stats import ttest_ind
    paper_pnls = [t.get('net_pnl', 0) for t in paper_trades]
    wfa_pnls = [t.get('net_pnl', 0) for t in wfa_trades]
    if len(paper_pnls) < 3 or len(wfa_pnls) < 3:
        return {'t_stat': 0.0, 'p_value': 1.0, 'n_paper': len(paper_pnls),
                'n_wfa': len(wfa_pnls), 'pass_incubation': True,
                'threshold': threshold}
    t_stat, p_value = ttest_ind(paper_pnls, wfa_pnls, equal_var=False)
    if math.isnan(t_stat):
        return {'t_stat': 0.0, 'p_value': 1.0, 'n_paper': len(paper_pnls),
                'n_wfa': len(wfa_pnls), 'pass_incubation': True,
                'threshold': threshold}
    return {
        't_stat': round(t_stat, 4),
        'p_value': round(p_value, 6),
        'n_paper': len(paper_pnls),
        'n_wfa': len(wfa_pnls),
        'pass_incubation': bool(p_value > threshold),
        'threshold': threshold,
    }


def dd_recovery_days(equity_curve):
    """
    Drawdown recovery analysis (Davey Ch.14/23).
    Tracks each DD episode: start → trough → recovery.
    Returns stats with mean ± sigma recovery duration bands.
    """
    if len(equity_curve) < 2:
        return {'max_dd_days': 0, 'current_dd_days': 0, 'mean_recovery': 0.0,
                'std_recovery': 0.0, 'x1_days': 0.0, 'x2_days': 0.0,
                'episodes': 0}

    peak = equity_curve[0]
    dd_start = None
    episodes = []
    current_dd_days = 0

    for i in range(len(equity_curve)):
        val = equity_curve[i]
        if val >= peak:
            if dd_start is not None:
                episodes.append(i - dd_start)
            peak = val
            dd_start = None
        else:
            if dd_start is None:
                dd_start = i

    # Current unrecovered DD
    if dd_start is not None:
        current_dd_days = len(equity_curve) - dd_start

    max_dd_days = max(episodes) if episodes else current_dd_days
    max_dd_days = max(max_dd_days, current_dd_days)

    if episodes:
        mean_r = sum(episodes) / len(episodes)
        if len(episodes) >= 2:
            var = sum((e - mean_r) ** 2 for e in episodes) / (len(episodes) - 1)
            std_r = math.sqrt(var)
        else:
            std_r = 0.0
    else:
        mean_r = 0.0
        std_r = 0.0

    return {
        'max_dd_days': max_dd_days,
        'current_dd_days': current_dd_days,
        'mean_recovery': round(mean_r, 1),
        'std_recovery': round(std_r, 1),
        'x1_days': round(mean_r + std_r, 1),
        'x2_days': round(mean_r + 2 * std_r, 1),
        'episodes': len(episodes),
    }


def return_efficiency(actual_return, expected_return):
    """
    Davey Ch.23: actual/expected return. Target 0.70-1.00. >1.30 suspicious.
    """
    if abs(expected_return) < 1e-6:
        return 0.0
    return round(actual_return / expected_return, 4)


def dd_efficiency(actual_dd_pct, expected_dd_pct):
    """
    Davey Ch.23: 1 - (actual_dd / expected_dd). Target close to 1.0.
    Negative means actual DD exceeds expected.
    """
    if expected_dd_pct < 1e-6:
        return 1.0 if actual_dd_pct < 1e-6 else 0.0
    return round(1.0 - (actual_dd_pct / expected_dd_pct), 4)


def equity_bands(n_trades, avg_pnl, std_pnl):
    """
    Davey Ch.23: expected equity ± confidence bands.
    expected = n × avg
    band = sqrt(n) × std × X  (X=1 for 68%, X=2 for 95%)
    """
    expected = n_trades * avg_pnl
    if n_trades <= 0 or std_pnl < 1e-6:
        return {'expected': round(expected, 2),
                'lower_1sigma': round(expected, 2), 'upper_1sigma': round(expected, 2),
                'lower_2sigma': round(expected, 2), 'upper_2sigma': round(expected, 2)}
    spread_1 = math.sqrt(n_trades) * std_pnl
    spread_2 = 2 * spread_1
    return {
        'expected': round(expected, 2),
        'lower_1sigma': round(expected - spread_1, 2),
        'upper_1sigma': round(expected + spread_1, 2),
        'lower_2sigma': round(expected - spread_2, 2),
        'upper_2sigma': round(expected + spread_2, 2),
    }


def _self_check():
    # GSR: short-vol returns (negative skew, high kurtosis) should penalize
    import random
    random.seed(42)
    # Simulate short-vol: many small wins, rare big losses
    short_vol_returns = [0.003] * 90 + [-0.05] * 10
    random.shuffle(short_vol_returns)

    sr = sharpe_ratio(short_vol_returns, 0.0, 252)
    g = gsr(short_vol_returns, 0.0, 252)
    assert g < sr, f"GSR ({g}) should be < SR ({sr}) for short-vol"

    # Normal returns should have GSR ≈ SR
    normal = [random.gauss(0.001, 0.01) for _ in range(200)]
    sr_n = sharpe_ratio(normal, 0.0, 252)
    g_n = gsr(normal, 0.0, 252)
    assert abs(g_n - sr_n) < abs(sr_n) * 0.3, f"Normal: GSR ({g_n}) should be close to SR ({sr_n})"

    # Max drawdown
    eq = [100, 110, 105, 95, 90, 100, 85, 95]
    dd = max_drawdown(eq)
    assert dd['amount'] == 25.0, f"DD amount: {dd['amount']}"
    assert abs(dd['pct'] - 22.73) < 0.1, f"DD pct: {dd['pct']}"

    # Return/DD
    trades = [
        {'net_pnl': 100}, {'net_pnl': -50}, {'net_pnl': 200},
        {'net_pnl': -30}, {'net_pnl': 150},
    ]
    rdd = return_dd_ratio(trades)
    assert rdd > 2.0, f"Return/DD: {rdd}"

    # Win rate
    wr = win_rate(trades)
    assert wr == 60.0, f"Win rate: {wr}"

    # Profit factor
    pf = profit_factor(trades)
    assert pf > 1.0, f"Profit factor: {pf}"

    # Tharp
    te = tharp_expectancy(trades)
    assert te > 0, f"Tharp: {te}"

    # Equity from trades
    eq2 = equity_from_trades(trades, initial=1000)
    assert len(eq2) == 6
    assert eq2[-1] == 1370.0

    # ── Phase 7 checks ──

    # t_test_oos: profitable trades should be significant with enough samples
    big_wins = [{'net_pnl': 1000}] * 35
    tt = t_test_oos(big_wins)
    assert tt['significant'] is True, f"t_test_oos: should be significant, got {tt}"
    assert tt['p_value'] < 0.05

    # t_test_oos: tiny sample → not significant
    tt2 = t_test_oos([{'net_pnl': 100}])
    assert tt2['significant'] is False

    # t_test_compare: same distribution → pass
    tc = t_test_compare(big_wins, [{'net_pnl': 1000}] * 30)
    assert tc['pass_incubation'] is True, f"t_test_compare same dist: {tc}"

    # t_test_compare: very different → fail
    tc2 = t_test_compare(big_wins, [{'net_pnl': -5000}] * 30)
    assert tc2['pass_incubation'] is False, f"t_test_compare diff dist: {tc2}"

    # dd_recovery_days
    eq_dd = [100, 110, 95, 90, 85, 100, 110, 105, 95, 110]
    ddr = dd_recovery_days(eq_dd)
    assert ddr['episodes'] >= 1
    assert ddr['max_dd_days'] > 0
    assert ddr['current_dd_days'] == 0  # ended at new high

    # dd_recovery_days: currently in DD
    eq_indd = [100, 110, 105, 95]
    ddr2 = dd_recovery_days(eq_indd)
    assert ddr2['current_dd_days'] == 2

    # return_efficiency
    assert return_efficiency(80, 100) == 0.8
    assert return_efficiency(0, 0) == 0.0

    # dd_efficiency
    assert dd_efficiency(5.0, 10.0) == 0.5
    assert dd_efficiency(0.0, 0.0) == 1.0
    assert dd_efficiency(15.0, 10.0) < 0  # worse than expected

    # equity_bands
    eb = equity_bands(25, 1000, 500)
    assert eb['expected'] == 25000
    assert eb['lower_1sigma'] < eb['expected'] < eb['upper_1sigma']
    assert eb['lower_2sigma'] < eb['lower_1sigma']

    # equity_bands: zero trades
    eb0 = equity_bands(0, 0, 0)
    assert eb0['expected'] == 0

    print("metrics.py: all checks passed")


if __name__ == '__main__':
    _self_check()
