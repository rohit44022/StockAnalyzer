"""
Strategy selection: signals → ranked strategies.

Decision tree from ARCHITECTURE.md, grounded in Cohen Ch.7 + Sinclair.
"""

from . import registry


def select(signals, risk_budget='moderate', dte=None):
    """
    Select and rank strategies based on current signals.

    Parameters
    ----------
    signals : list of signal dicts from signals.scan_signals()
    risk_budget : str — 'conservative', 'moderate', 'aggressive'
    dte : int — days to nearest expiry (filters out strategies needing more)

    Returns
    -------
    list of (strategy_key, score, reasons) sorted by score descending
    """
    sig_map = {s['type']: s for s in signals}

    vol_regime = _infer_vol_regime(sig_map)
    direction = _infer_direction(sig_map)

    candidates = []
    for key, strat in registry.STRATEGIES.items():
        if dte is not None and dte < strat.min_dte:
            continue

        score, reasons = _score(strat, sig_map, vol_regime, direction, risk_budget)
        if score > 0:
            candidates.append((key, round(score, 2), reasons))

    candidates.sort(key=lambda x: -x[1])
    return candidates


def _infer_vol_regime(sig_map):
    vix_sig = sig_map.get('vix_regime', {})
    vp_sig = sig_map.get('variance_premium', {})
    detail = vix_sig.get('detail', '')

    if vix_sig.get('direction') == 'caution' and vix_sig.get('strength', 0) > 0.7:
        return 'low' if 'too low' in detail else 'crisis'

    if vp_sig.get('direction') == 'sell_premium' and vp_sig.get('strength', 0) > 0.5:
        return 'high'
    if vp_sig.get('direction') == 'buy_premium':
        return 'low'
    return 'normal'


def _infer_direction(sig_map):
    bullish = bearish = 0.0
    for t in ('pcr', 'oi_regime'):
        sig = sig_map.get(t, {})
        s = sig.get('strength', 0)
        if sig.get('direction') == 'bullish':
            bullish += s
        elif sig.get('direction') == 'bearish':
            bearish += s
    if bullish > bearish + 0.3:
        return 'bullish'
    if bearish > bullish + 0.3:
        return 'bearish'
    return 'neutral'


def _score(strat, sig_map, vol_regime, direction, risk_budget):
    score = 0.0
    reasons = []

    # 1. Vol-regime match
    if vol_regime in strat.vol_regimes:
        score += 2.0
        reasons.append(f'vol regime {vol_regime} matches')
    elif vol_regime == 'crisis':
        if strat.max_loss == 'limited':
            score += 1.0
            reasons.append('defined risk OK in crisis')
        else:
            score -= 5.0
            reasons.append('unlimited risk rejected in crisis')
    else:
        score -= 1.0

    # 2. Direction match
    o = strat.outlook
    if (o == 'neutral' and direction == 'neutral') or o == direction:
        score += 1.5
        reasons.append(f'{direction} direction matches {o}')
    elif o in ('neutral', 'vol_up', 'vol_down'):
        score += 0.5
    else:
        score -= 0.5

    # 3. VP boost for income / vol strategies
    vp = sig_map.get('variance_premium', {})
    if strat.category == 'income' and vp.get('direction') == 'sell_premium':
        boost = vp.get('strength', 0) * 2.0
        score += boost
        reasons.append(f'VP sell signal ({vp["strength"]})')
    if strat.category == 'volatility' and vp.get('direction') == 'buy_premium':
        score += vp.get('strength', 0) * 2.0
        reasons.append('VP buy signal')

    # 4. Sinclair Ch.6: ATM selling outperforms OTM on risk-adjusted basis
    if strat.category == 'income':
        atm_sells = sum(1 for l in strat.legs
                        if l.action == 'SELL' and l.strike_offset == 0)
        if atm_sells > 0:
            score += 0.3
            reasons.append('ATM selling (Sinclair: better risk-adjusted)')

    # 5. Skew boost for put-selling
    skew = sig_map.get('skew', {})
    if skew.get('direction') == 'sell_puts':
        if any(l.option_type == 'PE' and l.action == 'SELL' for l in strat.legs):
            score += skew.get('strength', 0)
            reasons.append('steep skew favors put selling')

    # 6. Event caution
    ev = sig_map.get('event', {})
    if ev.get('direction') == 'caution' and ev.get('strength', 0) > 0.7:
        if strat.category == 'income':
            score -= 2.0
            reasons.append('event imminent — premium selling risky')
        elif strat.category == 'volatility':
            score += 1.0
            reasons.append('event imminent — vol play opportunity')

    # 7. Risk budget
    if risk_budget == 'conservative':
        if strat.max_loss == 'unlimited':
            score -= 3.0
            reasons.append('unlimited risk rejected (conservative)')
        if strat.complexity > 2:
            score -= 1.0
    elif risk_budget == 'moderate':
        if strat.max_loss == 'unlimited':
            score -= 1.0

    # 8. Complexity penalty
    score -= (strat.complexity - 1) * 0.3

    return score, reasons


def _self_check():
    # High VP, normal VIX, neutral direction → income on top
    signals = [
        {'type': 'variance_premium', 'direction': 'sell_premium', 'strength': 0.7, 'detail': ''},
        {'type': 'vix_regime', 'direction': 'sell_premium', 'strength': 0.6, 'detail': ''},
        {'type': 'pcr', 'direction': 'neutral', 'strength': 0.1, 'detail': ''},
        {'type': 'oi_regime', 'direction': 'neutral', 'strength': 0.1, 'detail': ''},
        {'type': 'skew', 'direction': 'neutral', 'strength': 0.2, 'detail': ''},
        {'type': 'term_structure', 'direction': 'neutral', 'strength': 0.1, 'detail': ''},
    ]
    ranked = select(signals, risk_budget='moderate')
    assert len(ranked) > 0
    top_strat = registry.get(ranked[0][0])
    assert top_strat.category == 'income', f"Expected income on top, got {top_strat.category}"

    # Crisis → unlimited risk should be negative
    crisis = [
        {'type': 'variance_premium', 'direction': 'sell_premium', 'strength': 0.9, 'detail': ''},
        {'type': 'vix_regime', 'direction': 'caution', 'strength': 0.9,
         'detail': 'VIX=35 — crisis zone'},
    ]
    for key, score, _ in select(crisis, risk_budget='conservative'):
        s = registry.get(key)
        if s.max_loss == 'unlimited':
            assert score < 0, f"Unlimited risk {key} should be negative in crisis"

    # Low vol → vol strategies should rank
    low = [
        {'type': 'variance_premium', 'direction': 'buy_premium', 'strength': 0.6, 'detail': ''},
        {'type': 'vix_regime', 'direction': 'caution', 'strength': 0.7,
         'detail': 'VIX=9 — too low'},
    ]
    ranked_low = select(low)
    top_cats = {registry.get(r[0]).category for r in ranked_low[:3]}
    assert 'volatility' in top_cats or 'directional' in top_cats

    print("selector.py: all checks passed")


if __name__ == '__main__':
    _self_check()
