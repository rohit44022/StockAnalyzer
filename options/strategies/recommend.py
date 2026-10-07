"""
Recommendation engine: pipeline → signals → scorer → build → price ranges.

Outputs price RANGES with freshness timestamp.
A recommendation expires in 30 minutes (ATM options move 17%/hour).
"""

import datetime

from . import scorer, signals, builder, registry
from ..core import event_calendar as core_calendar, cost_model
from ..data import event_calendar as data_calendar
from ..risk import margin as margin_mod


RECO_TTL_MINUTES = 30


def generate(chain_df, spot, vix_value=None, prices=None,
             pipe_result=None, capital=500_000, risk_budget='moderate',
             symbol='NIFTY', lot_size=None, r=0.07, backtest_dir=None):
    """
    Generate ranked recommendations with price ranges.

    Returns dict:
      recommendations: list of strategy reco dicts with leg price ranges
      market_state: current conditions snapshot
      timestamp/expires_at: freshness window
    """
    if spot is None or spot <= 0:
        return {'symbol': symbol, 'recommendations': [],
                'market_state': {}, 'signals': [],
                'timestamp': datetime.datetime.now().isoformat(),
                'expires_at': datetime.datetime.now().isoformat(),
                'ttl_minutes': 0, 'capital': capital,
                'risk_budget': risk_budget,
                'error': 'Invalid spot price'}

    if lot_size is None:
        from ..backtest.run_batch import nifty_lot_size
        lot_size = nifty_lot_size(datetime.date.today())

    now = datetime.datetime.now()
    today = now.date()

    if pipe_result is None:
        from ..data import pipeline
        pipe_result = pipeline.run_eod_pipeline(
            symbol=symbol, chain_df=chain_df, spot=spot,
            vix_value=vix_value, prices=prices)

    sigs = signals.scan_signals(pipe_result)

    next_exp = data_calendar.next_expiry(symbol)
    dte = max(0, (next_exp - today).days)

    scored = scorer.score(
        sigs, backtest_dir=backtest_dir,
        risk_budget=risk_budget, dte=dte, dt=today)

    recommendations = []
    for s in scored[:5]:
        br = builder.build(s['strategy_key'], chain_df, spot,
                           r=r, lot_size=lot_size)
        if not br or not br.get('legs'):
            continue
        recommendations.append(_build_reco(s, br, dte, lot_size,
                                           symbol=symbol, spot=spot,
                                           capital=capital))

    return {
        'symbol': symbol,
        'recommendations': recommendations,
        'market_state': _market_state(sigs, pipe_result, spot, vix_value, dte),
        'signals': sigs,
        'timestamp': now.isoformat(),
        'expires_at': (now + datetime.timedelta(minutes=RECO_TTL_MINUTES)).isoformat(),
        'ttl_minutes': RECO_TTL_MINUTES,
        'capital': capital,
        'risk_budget': risk_budget,
    }


def _build_reco(scored_item, build_result, dte, lot_size,
                symbol='NIFTY', spot=0, capital=500_000):
    strat = registry.get(scored_item['strategy_key'])
    legs = build_result.get('legs', [])

    leg_ranges = []
    worst_case_net = 0.0
    for leg in legs:
        ltp = max(0.05, leg.get('premium', leg.get('ltp', 0)))
        spread_pct = 0.02 if ltp > 30 else 0.05 if ltp > 10 else 0.10
        lo = round(ltp * (1 - spread_pct), 2)
        hi = round(ltp * (1 + spread_pct), 2)
        action = leg.get('action', 'BUY')
        qty = leg.get('qty', 1)
        # SELL fills at low end (worse), BUY fills at high end (worse)
        fill = lo if action == 'SELL' else hi
        worst_case_net += fill * qty * (1 if action == 'SELL' else -1)

        leg_ranges.append({
            'strike': leg.get('strike'),
            'option_type': leg.get('option_type'),
            'action': action,
            'qty': qty,
            'ref_price': round(ltp, 2),
            'price_low': lo,
            'price_high': hi,
        })

    # Cost estimate (Natenberg Ch.4: transaction costs eat edge)
    cost_legs = [{'premium': max(0.05, l.get('premium', l.get('ltp', 0))),
                  'action': l.get('action', 'BUY'),
                  'qty_lots': l.get('qty', 1)}
                 for l in legs]
    try:
        cost_est = cost_model.round_trip_cost(cost_legs, lot_size=lot_size)
        total_cost = cost_est.get('total', 0)
    except Exception:
        total_cost = len(legs) * 40

    # Margin estimate
    try:
        m_est = margin_mod.estimate_margin(legs, spot=spot,
                                           lot_size=lot_size, underlying=symbol)
        margin_req = m_est.get('total_margin', 0)
    except Exception:
        margin_req = None

    # Sinclair Ch.9: half-Kelly position sizing
    max_margin = capital * 0.40
    if margin_req and margin_req > 0:
        recommended_lots = max(1, int(max_margin / margin_req))
    else:
        recommended_lots = 1

    return {
        'strategy_key': scored_item['strategy_key'],
        'strategy_name': strat.name if strat else scored_item['strategy_key'],
        'category': strat.category if strat else 'unknown',
        'final_score': scored_item['final_score'],
        'confidence': scored_item['confidence'],
        'entry_timing': scored_item['entry_timing'],
        'legs': leg_ranges,
        'raw_legs': legs,
        'daily_theta': build_result.get('daily_theta', 0),
        'build_warnings': build_result.get('warnings', []),
        'net_premium': round(build_result.get('net_premium', 0), 2),
        'worst_case_net': round(worst_case_net, 2),
        'round_trip_cost': round(total_cost, 2),
        'margin_required': margin_req,
        'recommended_lots': recommended_lots,
        'max_profit': build_result.get('max_profit'),
        'max_loss': build_result.get('max_loss'),
        'breakevens': build_result.get('breakevens', []),
        'lot_size': lot_size,
        'dte': dte,
        'reasons': scored_item['reasons'],
        'backtest_ref': scored_item.get('backtest_ref'),
    }


def _market_state(sigs, pipe_result, spot, vix_value, dte):
    vp_data = pipe_result.get('variance_premium', {})
    vp = vp_data.get('vp', 0)
    iv = vp_data.get('iv', 0)
    rv = vp_data.get('rv', float('nan'))

    return {
        'spot': spot,
        'vix': vix_value,
        'iv': round(iv, 4) if iv is not None else None,
        'rv': round(rv, 4) if rv is not None and rv == rv else None,
        'vp': round(vp, 4) if vp is not None else None,
        'vp_signal': vp_data.get('signal', 'unknown'),
        'dte': dte,
        'event_near': core_calendar.event_near(datetime.date.today()),
    }


def is_stale(recommendation):
    """Check if a recommendation has expired."""
    exp = recommendation.get('expires_at', '')
    if not exp:
        return True
    try:
        expires = datetime.datetime.fromisoformat(exp)
        return datetime.datetime.now() > expires
    except (ValueError, TypeError):
        return True


def _self_check():
    import pandas as pd

    chain_rows = []
    for strike in range(23500, 24501, 100):
        for ot in ['CE', 'PE']:
            chain_rows.append({
                'strike': float(strike), 'option_type': ot,
                'expiry': datetime.date(2026, 10, 13),
                'expiry_years': 7 / 365,
                'ltp': max(0.5, 200 - abs(strike - 24000) * 0.5),
                'settle': max(0.5, 200 - abs(strike - 24000) * 0.5),
                'bid': max(0.4, 199 - abs(strike - 24000) * 0.5),
                'ask': max(0.6, 201 - abs(strike - 24000) * 0.5),
                'oi': 100000, 'volume': 50000,
                'iv': 0.14, 'change_oi': 1000,
            })
    chain = pd.DataFrame(chain_rows)

    pipe = {
        'variance_premium': {'vp': 0.035, 'iv': 0.16, 'rv': 0.125,
                             'signal': 'sell_premium'},
        'vix': {'value': 15.5, 'regime': {'level': 'normal'}},
        'oi': {'pcr': {'pcr': 1.1}},
        'upcoming_events': [],
    }

    result = generate(
        chain, spot=24000, vix_value=15.5,
        pipe_result=pipe, capital=500_000)

    assert 'recommendations' in result
    assert 'market_state' in result
    assert 'timestamp' in result
    assert 'expires_at' in result
    assert result['ttl_minutes'] == 30

    ms = result['market_state']
    assert ms['spot'] == 24000
    assert ms['vp'] is not None

    if result['recommendations']:
        top = result['recommendations'][0]
        assert top['strategy_key'] in scorer.GATE_PASS
        assert 'legs' in top
        assert all('price_low' in l and 'price_high' in l for l in top['legs'])
        assert top['confidence'] in ('high', 'medium', 'low')

    assert not is_stale(result)

    expired = dict(result, expires_at='2020-01-01T00:00:00')
    assert is_stale(expired)

    print("recommend.py: all checks passed")


if __name__ == '__main__':
    _self_check()
