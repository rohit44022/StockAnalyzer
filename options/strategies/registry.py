"""
Strategy catalog: 16 NSE-practical option strategies.

Each strategy is a template — builder.py resolves to actual positions.
Catalog: Cohen's selection matrix + Sinclair's variance premium framework,
filtered to what's liquid on NSE (European, cash-settled indices).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class LegSpec:
    option_type: str      # 'CE' or 'PE'
    action: str           # 'BUY' or 'SELL'
    strike_offset: int    # intervals from ATM (0=ATM, +4=4 above, -4=4 below)
    expiry: str = 'near'  # 'near' or 'far' (for calendars)
    qty: int = 1          # lot multiplier (2 for ratio spreads)


@dataclass(frozen=True)
class Strategy:
    key: str
    name: str
    category: str        # 'income', 'directional', 'volatility', 'rangebound'
    outlook: str         # 'bullish', 'bearish', 'neutral', 'vol_up', 'vol_down'
    legs: tuple          # tuple of LegSpec
    max_profit: str      # 'limited' or 'unlimited'
    max_loss: str        # 'limited' or 'unlimited'
    margin_required: bool
    greeks: tuple        # (delta, gamma, theta, vega) sign as -1/0/+1
    vol_regimes: tuple   # regimes where this works: 'low', 'normal', 'high'
    min_dte: int         # minimum days to expiry
    complexity: int      # 1-3


L = LegSpec

STRATEGIES = {
    # ── Income (sell premium = the edge) ──────────────────────────
    'short_straddle': Strategy(
        'short_straddle', 'Short Straddle', 'income', 'neutral',
        (L('CE', 'SELL', 0), L('PE', 'SELL', 0)),
        'limited', 'unlimited', True,
        (0, -1, +1, -1), ('high', 'normal'), 7, 2,
    ),
    'short_strangle': Strategy(
        'short_strangle', 'Short Strangle', 'income', 'neutral',
        (L('CE', 'SELL', +4), L('PE', 'SELL', -4)),
        'limited', 'unlimited', True,
        (0, -1, +1, -1), ('high', 'normal'), 7, 2,
    ),
    'iron_condor': Strategy(
        'iron_condor', 'Iron Condor', 'income', 'neutral',
        (L('PE', 'BUY', -6), L('PE', 'SELL', -4),
         L('CE', 'SELL', +4), L('CE', 'BUY', +6)),
        'limited', 'limited', True,
        (0, -1, +1, -1), ('high', 'normal'), 14, 2,
    ),
    'iron_butterfly': Strategy(
        'iron_butterfly', 'Iron Butterfly', 'income', 'neutral',
        (L('PE', 'BUY', -4), L('PE', 'SELL', 0),
         L('CE', 'SELL', 0), L('CE', 'BUY', +4)),
        'limited', 'limited', True,
        (0, -1, +1, -1), ('high',), 14, 2,
    ),
    'bull_put_spread': Strategy(
        'bull_put_spread', 'Bull Put Spread', 'income', 'bullish',
        (L('PE', 'SELL', -2), L('PE', 'BUY', -4)),
        'limited', 'limited', True,
        (+1, -1, +1, -1), ('high', 'normal'), 7, 1,
    ),
    'bear_call_spread': Strategy(
        'bear_call_spread', 'Bear Call Spread', 'income', 'bearish',
        (L('CE', 'SELL', +2), L('CE', 'BUY', +4)),
        'limited', 'limited', True,
        (-1, -1, +1, -1), ('high', 'normal'), 7, 1,
    ),
    'jade_lizard': Strategy(
        'jade_lizard', 'Jade Lizard', 'income', 'bullish',
        (L('PE', 'SELL', -4),
         L('CE', 'SELL', +4), L('CE', 'BUY', +6)),
        'limited', 'unlimited', True,
        (+1, -1, +1, -1), ('high', 'normal'), 14, 3,
    ),
    'calendar_call': Strategy(
        'calendar_call', 'Calendar Call Spread', 'income', 'neutral',
        (L('CE', 'SELL', 0, 'near'), L('CE', 'BUY', 0, 'far')),
        'limited', 'limited', True,
        (0, -1, +1, +1), ('low', 'normal'), 21, 2,
    ),

    # ── Directional ───────────────────────────────────────────────
    'bull_call_spread': Strategy(
        'bull_call_spread', 'Bull Call Spread', 'directional', 'bullish',
        (L('CE', 'BUY', 0), L('CE', 'SELL', +4)),
        'limited', 'limited', False,
        (+1, +1, -1, +1), ('low', 'normal'), 14, 1,
    ),
    'bear_put_spread': Strategy(
        'bear_put_spread', 'Bear Put Spread', 'directional', 'bearish',
        (L('PE', 'BUY', 0), L('PE', 'SELL', -4)),
        'limited', 'limited', False,
        (-1, +1, -1, +1), ('low', 'normal'), 14, 1,
    ),
    'long_call': Strategy(
        'long_call', 'Long Call', 'directional', 'bullish',
        (L('CE', 'BUY', 0),),
        'unlimited', 'limited', False,
        (+1, +1, -1, +1), ('low',), 21, 1,
    ),
    'long_put': Strategy(
        'long_put', 'Long Put', 'directional', 'bearish',
        (L('PE', 'BUY', 0),),
        'limited', 'limited', False,
        (-1, +1, -1, +1), ('low',), 21, 1,
    ),

    # ── Volatility ────────────────────────────────────────────────
    'long_straddle': Strategy(
        'long_straddle', 'Long Straddle', 'volatility', 'vol_up',
        (L('CE', 'BUY', 0), L('PE', 'BUY', 0)),
        'unlimited', 'limited', False,
        (0, +1, -1, +1), ('low',), 21, 1,
    ),
    'long_strangle': Strategy(
        'long_strangle', 'Long Strangle', 'volatility', 'vol_up',
        (L('CE', 'BUY', +4), L('PE', 'BUY', -4)),
        'unlimited', 'limited', False,
        (0, +1, -1, +1), ('low',), 21, 1,
    ),
    # Cohen Ch.6: sell 1 ITM/ATM put, buy 2 OTM puts (net long options)
    'ratio_put_backspread': Strategy(
        'ratio_put_backspread', 'Ratio Put Backspread', 'volatility', 'bearish',
        (L('PE', 'SELL', 0), L('PE', 'BUY', -4, qty=2)),
        'limited', 'limited', True,
        (-1, +1, -1, +1), ('normal', 'high'), 21, 3,
    ),

    # ── Rangebound ────────────────────────────────────────────────
    'long_butterfly': Strategy(
        'long_butterfly', 'Long Call Butterfly', 'rangebound', 'neutral',
        (L('CE', 'BUY', -4), L('CE', 'SELL', 0, qty=2), L('CE', 'BUY', +4)),
        'limited', 'limited', False,
        (0, -1, +1, -1), ('normal', 'high'), 14, 2,
    ),
}


def get(key):
    return STRATEGIES.get(key)


def list_strategies(category=None, outlook=None, vol_regime=None):
    results = list(STRATEGIES.values())
    if category:
        results = [s for s in results if s.category == category]
    if outlook:
        results = [s for s in results if s.outlook == outlook]
    if vol_regime:
        results = [s for s in results if vol_regime in s.vol_regimes]
    return results


def _self_check():
    assert len(STRATEGIES) == 16
    for key, s in STRATEGIES.items():
        assert s.key == key
        assert len(s.legs) >= 1
        assert s.category in ('income', 'directional', 'volatility', 'rangebound')
        assert s.outlook in ('bullish', 'bearish', 'neutral', 'vol_up', 'vol_down')
        assert len(s.greeks) == 4
        for leg in s.legs:
            assert leg.option_type in ('CE', 'PE')
            assert leg.action in ('BUY', 'SELL')

    assert len(list_strategies(category='income')) == 8
    assert len(list_strategies(outlook='neutral')) >= 5
    assert len(list_strategies(vol_regime='low')) >= 5

    print("registry.py: all checks passed")


if __name__ == '__main__':
    _self_check()
