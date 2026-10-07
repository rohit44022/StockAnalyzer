"""
Cross-strategy correlation and portfolio diversification (Davey Ch.15).

Measures how correlated two strategies' daily returns are. High R²
means adding a second strategy doesn't diversify — it just doubles
exposure. Davey: "a portfolio of uncorrelated strategies is the
closest thing to a free lunch in trading."
"""

import math


def strategy_correlation(equity_curves):
    """
    Davey Ch.15: pairwise return correlation between strategies.

    Parameters
    ----------
    equity_curves : dict[str, list[float]]
        {strategy_name: [daily_equity_values]}
        All curves must be same length.

    Returns
    -------
    dict with:
      correlations : list of {pair, r, r_squared}
      high_correlation_pairs : pairs with R² > 0.50
      combined_equity : sum of all curves (equal weight)
      combined_r_squared : R² of combined vs each strategy
      diversification_score : 1 - mean(pairwise R²), higher = better
    """
    names = list(equity_curves.keys())
    if len(names) < 2:
        return {
            'correlations': [],
            'high_correlation_pairs': [],
            'combined_equity': list(equity_curves.values())[0] if names else [],
            'combined_r_squared': {},
            'diversification_score': 1.0,
        }

    returns = {}
    for name, eq in equity_curves.items():
        if len(eq) < 2:
            returns[name] = []
        else:
            returns[name] = [eq[i] - eq[i - 1] for i in range(1, len(eq))]

    correlations = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = returns[names[i]], returns[names[j]]
            r = _pearson(a, b)
            correlations.append({
                'pair': (names[i], names[j]),
                'r': round(r, 4),
                'r_squared': round(r * r, 4),
            })

    high = [c for c in correlations if c['r_squared'] > 0.50]

    curves = list(equity_curves.values())
    n = min(len(c) for c in curves)
    combined = [sum(curves[k][t] for k in range(len(curves))) for t in range(n)]

    combined_rets = [combined[i] - combined[i - 1] for i in range(1, len(combined))]
    combined_r2 = {}
    for name in names:
        r = _pearson(combined_rets, returns[name][:len(combined_rets)])
        combined_r2[name] = round(r * r, 4)

    r2_vals = [c['r_squared'] for c in correlations]
    div_score = 1.0 - (sum(r2_vals) / len(r2_vals)) if r2_vals else 1.0

    return {
        'correlations': correlations,
        'high_correlation_pairs': high,
        'combined_equity': combined,
        'combined_r_squared': combined_r2,
        'diversification_score': round(div_score, 4),
    }


def _pearson(a, b):
    n = min(len(a), len(b))
    if n < 2:
        return 0.0
    a, b = a[:n], b[:n]
    ma = sum(a) / n
    mb = sum(b) / n
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    denom = math.sqrt(va * vb)
    if denom < 1e-12:
        return 0.0
    return cov / denom


def _self_check():
    import random
    random.seed(42)

    n = 100
    base = [0.0]
    for _ in range(n):
        base.append(base[-1] + random.gauss(0, 1))

    eq_a = base[:]
    eq_b = [x + random.gauss(0, 0.1) for x in base]
    eq_c = [0.0]
    for _ in range(n):
        eq_c.append(eq_c[-1] + random.gauss(0, 1))

    result = strategy_correlation({
        'strat_a': eq_a,
        'strat_b': eq_b,
        'strat_c': eq_c,
    })

    ab = next(c for c in result['correlations'] if 'strat_a' in c['pair'] and 'strat_b' in c['pair'])
    assert ab['r_squared'] > 0.9, f"A/B should be highly correlated: {ab['r_squared']}"

    assert len(result['high_correlation_pairs']) >= 1

    assert 0 <= result['diversification_score'] <= 1

    assert len(result['combined_equity']) == n + 1

    single = strategy_correlation({'only_one': eq_a})
    assert single['diversification_score'] == 1.0

    print("portfolio.py: all checks passed")


if __name__ == '__main__':
    _self_check()
