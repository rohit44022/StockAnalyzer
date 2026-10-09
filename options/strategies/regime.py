"""
2x2 market regime detection: trend (composite RoC ±2%) × vol (VIX/IV).

Sinclair Ch.4: VP edge is regime-dependent — sell vol when IV > RV.
Cohen Ch.7: match strategy outlook to market direction.
Natenberg Ch.11: long gamma profits when realized > implied.

Used by engine.py (signal_mode='regime'), scorer.py (live recommender),
and pipeline runners.
"""

import math


# Which strategies are allowed in each regime cell.
# Hard gate: scorer and backtest engine both use this.
REGIME_STRATEGIES = {
    'trending_up':   {'bull_put_spread', 'bull_call_spread', 'iron_condor', 'long_call',
                      'long_straddle', 'long_strangle'},
    'trending_down': {'bear_call_spread', 'bear_put_spread', 'iron_condor', 'long_put',
                      'long_straddle', 'long_strangle', 'ratio_put_backspread'},
    'rangebound':    {'iron_condor', 'iron_butterfly', 'short_straddle', 'short_strangle',
                      'jade_lizard', 'long_butterfly',
                      'long_straddle', 'long_strangle'},
    'high_vol':      {'iron_condor', 'jade_lizard', 'iron_butterfly',
                      'bear_call_spread', 'bull_put_spread',
                      'long_put', 'long_straddle', 'long_strangle',
                      'ratio_put_backspread'},
}


def detect_regime(spot_list, date_idx, dt, atm_iv, rv, lookback=20,
                  prev_regime=None):
    """
    Classify current market regime from price history + vol.

    Parameters
    ----------
    prev_regime : str, optional — previous regime for hysteresis.
        Enter trending at ±2%, exit only below ±1.5% to avoid whipsaw.

    Returns dict with:
        regime: 'trending_up' | 'trending_down' | 'rangebound' | 'high_vol'
        trend: 'up' | 'down' | 'flat'  (legacy compat)
        vp: 'sell_vol' | 'buy_vol' | 'neutral'
        trend_strength: float 0-1
        vp_value: float (IV - RV)
        roc: float (composite rate of change)
    """
    idx = date_idx if isinstance(date_idx, int) else 0

    # Composite RoC (3d+5d+10d weighted)
    roc = 0.0
    if idx >= 3 and len(spot_list) > idx:
        components = {}
        w = {'roc_3d': 0.33, 'roc_5d': 0.34, 'roc_10d': 0.33}
        if idx >= 3:
            components['roc_3d'] = spot_list[idx] / spot_list[idx - 3] - 1
        if idx >= 5:
            components['roc_5d'] = spot_list[idx] / spot_list[idx - 5] - 1
        if idx >= 10:
            components['roc_10d'] = spot_list[idx] / spot_list[idx - 10] - 1
        num = sum(components[k] * w[k] for k in components if k in w)
        denom = sum(w[k] for k in components if k in w)
        roc = num / denom if denom else 0

    # VIX proxy from ATM IV (backtest doesn't have direct VIX)
    vix_proxy = (atm_iv * 100) if atm_iv is not None else 14

    # 4-state regime with hysteresis (enter trending ±2%, exit ±1.5%)
    _ENTER = 0.02
    _EXIT = 0.015
    if roc > _ENTER:
        regime = 'trending_up'
    elif roc < -_ENTER:
        regime = 'trending_down'
    elif prev_regime == 'trending_up' and roc > _EXIT:
        regime = 'trending_up'
    elif prev_regime == 'trending_down' and roc < -_EXIT:
        regime = 'trending_down'
    elif vix_proxy >= 22:
        regime = 'high_vol'
    else:
        regime = 'rangebound'

    # Legacy trend field
    if regime == 'trending_up':
        trend = 'up'
    elif regime == 'trending_down':
        trend = 'down'
    else:
        trend = 'flat'

    trend_strength = min(1.0, abs(roc) / 0.05) if abs(roc) > 0.01 else 0.0

    # VP from IV vs RV (Sinclair)
    vp = 'neutral'
    vp_value = 0.0
    if atm_iv is not None and rv is not None and not math.isnan(rv):
        vp_value = atm_iv - rv
        if vp_value >= 0.02:
            vp = 'sell_vol'
        elif vp_value <= -0.01:
            vp = 'buy_vol'

    return {
        'regime': regime,
        'trend': trend,
        'vp': vp,
        'trend_strength': trend_strength,
        'vp_value': vp_value,
        'roc': roc,
    }


def strategy_fits_regime(strategy, regime_dict):
    """Check if strategy is allowed in the current regime cell."""
    regime = regime_dict.get('regime', 'rangebound')
    allowed = REGIME_STRATEGIES.get(regime, set())
    return strategy.key in allowed


if __name__ == '__main__':
    r = detect_regime([100 + i * 0.5 for i in range(30)], 29, None, 0.18, 0.14)
    assert r['regime'] == 'trending_up'
    assert r['trend'] == 'up'
    assert r['vp'] == 'sell_vol'

    r2 = detect_regime([100 - i * 0.5 for i in range(30)], 29, None, 0.12, 0.18)
    assert r2['regime'] == 'trending_down'
    assert r2['trend'] == 'down'
    assert r2['vp'] == 'buy_vol'

    # Rangebound
    r3 = detect_regime([100 + (0.1 if i % 2 else -0.1) for i in range(30)], 29, None, 0.14, 0.12)
    assert r3['regime'] == 'rangebound'

    # High vol
    r4 = detect_regime([100 + (0.1 if i % 2 else -0.1) for i in range(30)], 29, None, 0.25, 0.20)
    assert r4['regime'] == 'high_vol'

    # strategy_fits_regime
    from . import registry
    bcs = registry.get('bear_call_spread')
    assert strategy_fits_regime(bcs, r2)  # trending_down
    assert not strategy_fits_regime(bcs, r3)  # rangebound

    ibf = registry.get('iron_butterfly')
    assert strategy_fits_regime(ibf, r3)  # rangebound
    assert not strategy_fits_regime(ibf, r)  # trending_up

    print("regime.py: self-check passed")
