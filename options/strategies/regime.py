"""
Market regime detection from spot + IV history.

Sinclair Ch.4: VP edge is regime-dependent — sell vol when IV > RV, buy when trending.
Natenberg Ch.11: long gamma profits when realized > implied.
Cohen Ch.7: match strategy outlook to market direction.

Used by engine.py (signal_mode='regime') and pipeline runners.
"""

import math


def detect_regime(spot_list, date_idx, dt, atm_iv, rv, lookback=20):
    """
    Classify current market regime from price history + vol.

    Returns dict with:
        trend: 'up' | 'down' | 'flat'
        vp: 'sell_vol' | 'buy_vol' | 'neutral'  (sell_vol = IV > RV = short premium edge)
        trend_strength: float 0-1
        vp_value: float (IV - RV)
    """
    idx = date_idx if isinstance(date_idx, int) else 0

    # Trend from lookback-period return
    trend = 'flat'
    trend_strength = 0.0
    if idx >= lookback and len(spot_list) > idx:
        ret = (spot_list[idx] - spot_list[idx - lookback]) / spot_list[idx - lookback]
        if ret > 0.03:
            trend = 'up'
            trend_strength = min(1.0, ret / 0.10)
        elif ret < -0.03:
            trend = 'down'
            trend_strength = min(1.0, abs(ret) / 0.10)
        else:
            trend = 'flat'
            trend_strength = 1.0 - abs(ret) / 0.03

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
        'trend': trend,
        'vp': vp,
        'trend_strength': trend_strength,
        'vp_value': vp_value,
    }


def strategy_fits_regime(strategy, regime):
    """
    Check if a strategy is compatible with the current regime.

    strategy: Strategy namedtuple from registry (has .outlook, .category)
    regime: dict from detect_regime()

    Sinclair: sell premium only when VP > 0 (IV > RV).
    Cohen: match outlook to trend direction.
    Natenberg: long gamma when trending (realized > implied).
    """
    trend = regime['trend']
    vp = regime['vp']
    outlook = strategy.outlook   # 'bullish', 'bearish', 'neutral'
    cat = strategy.category      # 'income', 'vol', 'directional'

    # Rule 1: never sell premium when VP says buy (IV < RV) — Sinclair
    if cat == 'income' and vp == 'buy_vol':
        return False

    # Rule 2: trending market → strategy outlook must match or be neutral
    if trend == 'up' and outlook == 'bearish':
        return False
    if trend == 'down' and outlook == 'bullish':
        return False

    # Rule 3: flat market → prefer income/neutral, skip directional
    if trend == 'flat' and cat == 'directional' and outlook != 'neutral':
        return False

    # Rule 4: sell premium in flat + sell_vol only (the core VP edge)
    if cat == 'income' and trend != 'flat' and regime['trend_strength'] > 0.5:
        return False

    return True


# ponytail: simple 3-state trend + 3-state VP. Add momentum/mean-reversion
# sub-states when the 6-state model measurably underperforms.

if __name__ == '__main__':
    r = detect_regime([100 + i * 0.5 for i in range(30)], 29, None, 0.18, 0.14)
    assert r['trend'] == 'up'
    assert r['vp'] == 'sell_vol'

    r2 = detect_regime([100 - i * 0.5 for i in range(30)], 29, None, 0.12, 0.18)
    assert r2['trend'] == 'down'
    assert r2['vp'] == 'buy_vol'

    print("regime.py: self-check passed")
