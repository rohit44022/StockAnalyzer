"""
Human-readable explanation of recommendations.
Formats recommend.generate() output for CLI or web UI.
"""


def explain(recommendation):
    """Format full recommendation into readable text."""
    lines = []
    ms = recommendation.get('market_state', {})

    symbol = recommendation.get('symbol', 'NIFTY')
    lines.append(f"{'═' * 70}")
    lines.append(f"  {symbol} OPTIONS RECOMMENDATION")
    lines.append(f"  {recommendation.get('timestamp', '')[:19]}  |  "
                 f"Expires: {recommendation.get('expires_at', '')[:16]}")
    lines.append(f"{'═' * 70}")

    lines.append(f"\n  MARKET STATE")
    lines.append(f"  {'─' * 50}")
    lines.append(f"  Spot: ₹{ms.get('spot', 0):,.0f}  |  "
                 f"VIX: {ms.get('vix') or 0:.1f}  |  DTE: {ms.get('dte', '-')}")

    iv = ms.get('iv')
    rv = ms.get('rv')
    vp = ms.get('vp')
    if iv is not None and rv is not None:
        vp_str = f"{vp:+.1%}" if vp is not None else "N/A"
        lines.append(f"  IV: {iv:.1%}  |  RV: {rv:.1%}  |  "
                     f"VP: {vp_str} → {ms.get('vp_signal', '?')}")

    ev = ms.get('event_near')
    if ev:
        lines.append(f"  !! Event near: {ev}")

    recos = recommendation.get('recommendations', [])
    if not recos:
        lines.append(f"\n  NO TRADES RECOMMENDED")
        lines.append(f"  (No strategy passes all filters)")
        lines.append(f"{'═' * 70}")
        return '\n'.join(lines)

    for i, reco in enumerate(recos, 1):
        lines.append(f"\n  {'─' * 50}")
        lines.append(f"  #{i}  {reco['strategy_name'].upper()}"
                     f"  [{reco['confidence'].upper()} confidence]")
        lines.append(f"  Score: {reco['final_score']}  |  "
                     f"Category: {reco['category']}  |  DTE: {reco['dte']}")
        lines.append(f"  Entry: {reco['entry_timing']}")

        lines.append(f"\n  {'Action':<6s} {'Type':<4s} {'Strike':>8s}  "
                     f"{'Ref':>8s}  {'Range':>18s}  {'Qty':>3s}")
        for leg in reco.get('legs', []):
            lines.append(
                f"  {leg['action']:<6s} {leg['option_type']:<4s} "
                f"{leg['strike']:>8.0f}  "
                f"₹{leg['ref_price']:>7.2f}  "
                f"₹{leg['price_low']:.2f}–₹{leg['price_high']:.2f}  "
                f"{leg.get('qty', 1):>3d}")

        net = reco.get('net_premium', 0)
        wc = reco.get('worst_case_net')
        cost = reco.get('round_trip_cost', 0)
        margin = reco.get('margin_required')
        mp = reco.get('max_profit')
        ml = reco.get('max_loss')
        lines.append(f"\n  Net premium: ₹{net:,.2f}/lot")
        if wc is not None:
            lines.append(f"  Worst-case:  ₹{wc:,.2f}/lot (after slippage)")
        if cost:
            lines.append(f"  Round-trip:  ₹{cost:,.2f}/lot (STT+brokerage+charges)")
        if margin:
            lines.append(f"  Margin req:  ₹{margin:,.0f}")
        if mp is not None:
            lines.append(f"  Max profit:  ₹{mp:,.0f}/lot")
        if ml is not None and ml != float('-inf'):
            lines.append(f"  Max loss:    ₹{ml:,.0f}/lot")

        lots = reco.get('recommended_lots')
        if lots:
            lines.append(f"  Lots:        {lots} (half-Kelly, 40% margin cap)")

        bt = reco.get('backtest_ref')
        if bt:
            lines.append(f"\n  10yr backtest: WR={bt['win_rate']}%  "
                         f"DD={bt['max_dd']}%  avg=₹{bt['avg_trade']}/trade")

        if reco.get('reasons'):
            lines.append(f"\n  Why:")
            for r in reco['reasons'][:5]:
                lines.append(f"    - {r}")

    lines.append(f"\n{'═' * 70}")
    lines.append(f"  Prices are RANGES — verify against live chain.")
    lines.append(f"  Expires in {recommendation.get('ttl_minutes', 30)} min.")
    lines.append(f"{'═' * 70}")
    return '\n'.join(lines)


def explain_short(recommendation):
    """One-line summary for logs/alerts."""
    recos = recommendation.get('recommendations', [])
    if not recos:
        return "No trade: filters block all strategies"
    top = recos[0]
    ms = recommendation.get('market_state', {})
    vp = ms.get('vp', 0) or 0
    return (f"{top['strategy_name']} [{top['confidence']}] "
            f"score={top['final_score']} VP={vp:+.1%} "
            f"net=₹{top.get('net_premium', 0):,.0f}")


def explain_risk(recommendation):
    """Risk-focused summary."""
    recos = recommendation.get('recommendations', [])
    if not recos:
        return "No position risk — no trade recommended."
    ms = recommendation.get('market_state', {})
    lines = []
    for reco in recos:
        ml = reco.get('max_loss')
        mp = reco.get('max_profit')
        lot = reco.get('lot_size', 75)
        lines.append(f"{reco['strategy_name']}:")
        if ml is not None and ml != float('-inf'):
            lines.append(f"  Max loss/lot: ₹{abs(ml):,.0f} "
                         f"(₹{abs(ml) * lot:,.0f} per position)")
        else:
            lines.append(f"  Max loss: UNLIMITED — stop-loss required")
        if mp is not None:
            lines.append(f"  Max profit/lot: ₹{mp:,.0f}")
        ev = ms.get('event_near')
        if ev:
            lines.append(f"  WARNING: {ev} nearby — gap risk elevated")
    return '\n'.join(lines)


def _self_check():
    reco = {
        'symbol': 'NIFTY',
        'timestamp': '2026-10-06T15:45:00',
        'expires_at': '2026-10-06T16:15:00',
        'ttl_minutes': 30,
        'capital': 500_000,
        'risk_budget': 'moderate',
        'market_state': {
            'spot': 24000, 'vix': 15.5,
            'iv': 0.16, 'rv': 0.125, 'vp': 0.035,
            'vp_signal': 'sell_premium', 'dte': 7, 'event_near': None,
        },
        'recommendations': [
            {
                'strategy_key': 'short_straddle',
                'strategy_name': 'Short Straddle',
                'category': 'income',
                'final_score': 6.2,
                'confidence': 'high',
                'entry_timing': 'afternoon (14:00-14:30 IST)',
                'legs': [
                    {'strike': 24000, 'option_type': 'CE', 'action': 'SELL',
                     'qty': 1, 'ref_price': 200.0,
                     'price_low': 196.0, 'price_high': 204.0},
                    {'strike': 24000, 'option_type': 'PE', 'action': 'SELL',
                     'qty': 1, 'ref_price': 195.0,
                     'price_low': 191.1, 'price_high': 198.9},
                ],
                'net_premium': 395.0,
                'max_profit': 395,
                'max_loss': float('-inf'),
                'breakevens': [23605, 24395],
                'lot_size': 65,
                'dte': 7,
                'reasons': ['VP sell signal (0.7)', 'vol regime high matches',
                            'neutral direction matches neutral'],
            },
        ],
        'signals': [],
    }

    text = explain(reco)
    assert 'NIFTY OPTIONS RECOMMENDATION' in text
    assert 'SHORT STRADDLE' in text
    assert 'HIGH confidence' in text
    assert '196.00' in text
    assert 'RANGES' in text

    short = explain_short(reco)
    assert 'Short Straddle' in short
    assert 'high' in short

    risk = explain_risk(reco)
    assert 'UNLIMITED' in risk

    empty_reco = dict(reco, recommendations=[])
    assert 'NO TRADES' in explain(empty_reco)
    assert 'No trade' in explain_short(empty_reco)

    # vp=None must not crash
    none_vp = dict(reco, market_state=dict(reco['market_state'], vp=None))
    text_nv = explain(none_vp)
    assert 'None' not in text_nv or 'N/A' in text_nv

    # Symbol should be dynamic
    bn = dict(reco, symbol='BANKNIFTY')
    assert 'BANKNIFTY' in explain(bn)

    print("explainer.py: all checks passed")


if __name__ == '__main__':
    _self_check()
