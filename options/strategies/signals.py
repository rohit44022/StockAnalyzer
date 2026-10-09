"""
Signal generation from pipeline output.

Primary signal: variance premium (Sinclair Ch.4-5).
India VP: ~2.5 pts avg, positive ~70% of time.
Secondary: VIX regime, PCR, skew, OI regime, events.
"""


def scan_signals(pipeline_result):
    """
    Interpret pipeline output into structured trading signals.

    Parameters
    ----------
    pipeline_result : dict — output of pipeline.run_eod_pipeline()

    Returns
    -------
    list of dicts, each: {type, direction, strength (0-1), detail}
    """
    signals = []

    vp = pipeline_result.get('variance_premium')
    if vp:
        signals.append(_vp_signal(vp))

    vix = pipeline_result.get('vix')
    if vix:
        signals.append(_vix_signal(vix))

    oi = pipeline_result.get('oi')
    if oi:
        pcr_data = oi.get('pcr')
        if pcr_data:
            signals.append(_pcr_signal(pcr_data))

    skew = pipeline_result.get('skew')
    if skew:
        signals.append(_skew_signal(skew))

    oi_regime = pipeline_result.get('oi_regime')
    if oi_regime:
        signals.append(_oi_regime_signal(oi_regime))

    events = pipeline_result.get('upcoming_events', [])
    event_window = pipeline_result.get('event_window')
    sig = _event_signal(events, event_window)
    if sig:
        signals.append(sig)

    inverted = pipeline_result.get('inverted')
    if inverted is not None:
        signals.append(_term_structure_signal(inverted))

    trend = pipeline_result.get('price_trend')
    if trend:
        signals.append(_trend_signal(trend))

    return signals


def _vp_signal(vp):
    """Variance premium: THE primary edge signal."""
    vp_val = vp.get('vp', 0)
    iv = vp.get('iv', 0)
    rv = vp.get('rv', float('nan'))

    if rv != rv:  # NaN
        return {'type': 'variance_premium', 'direction': 'neutral',
                'strength': 0.0, 'detail': f'No RV data (IV={iv:.1%})'}

    abs_vp = abs(vp_val)
    if vp_val > 0.04:
        strength = min(1.0, abs_vp / 0.06)
        direction = 'sell_premium'
    elif vp_val > 0.02:
        strength = 0.4 + (vp_val - 0.02) / 0.02 * 0.3
        direction = 'sell_premium'
    elif vp_val < -0.01:
        strength = min(0.8, abs_vp / 0.03)
        direction = 'buy_premium'
    else:
        strength = 0.1
        direction = 'neutral'

    return {
        'type': 'variance_premium',
        'direction': direction,
        'strength': round(strength, 2),
        'detail': f'VP={vp_val:.1%} (IV={iv:.1%} − RV={rv:.1%})',
    }


# India VIX long-term mean ~14% (NOT 15-20% like US VIX)
_VIX_MEAN = 14.0

def _vix_signal(vix):
    """VIX regime — determines premium adequacy and risk."""
    value = vix.get('value', _VIX_MEAN)
    regime = vix.get('regime', {})

    if value < 11:
        return {'type': 'vix_regime', 'direction': 'caution',
                'strength': 0.7, 'value': value,
                'detail': f'VIX={value:.1f} — too low, premium thin'}
    if value <= 22:
        strength = min(1.0, 0.5 + (value - 11) / 22)
        return {'type': 'vix_regime', 'direction': 'sell_premium',
                'strength': round(strength, 2), 'value': value,
                'detail': f'VIX={value:.1f} — sweet spot for premium selling'}
    if value <= 25:
        return {'type': 'vix_regime', 'direction': 'sell_premium',
                'strength': 0.6, 'value': value,
                'detail': f'VIX={value:.1f} — elevated, rich premium but size down'}
    return {'type': 'vix_regime', 'direction': 'caution',
            'strength': 0.8, 'value': value,
            'detail': f'VIX={value:.1f} — crisis zone, spreads only'}


def _pcr_signal(pcr_data):
    """PCR as contrarian indicator."""
    pcr_val = pcr_data.get('pcr', 1.0)

    if pcr_val > 1.3:
        return {'type': 'pcr', 'direction': 'bullish',
                'strength': round(min(0.7, (pcr_val - 1.0) / 1.0), 2),
                'detail': f'PCR={pcr_val:.2f} — high fear, contrarian bullish'}
    if pcr_val < 0.7:
        return {'type': 'pcr', 'direction': 'bearish',
                'strength': round(min(0.7, (1.0 - pcr_val) / 1.0), 2),
                'detail': f'PCR={pcr_val:.2f} — complacent, contrarian bearish'}
    return {'type': 'pcr', 'direction': 'neutral',
            'strength': 0.1,
            'detail': f'PCR={pcr_val:.2f} — balanced'}


def _skew_signal(skew_by_exp):
    """Skew steepness → OTM put premium richness."""
    if not skew_by_exp:
        return {'type': 'skew', 'direction': 'neutral',
                'strength': 0.0, 'detail': 'No skew data'}

    nearest_key = min(skew_by_exp.keys(),
                      key=lambda k: int(k) if str(k).isdigit() else 999)
    sm = skew_by_exp[nearest_key]
    skew_25d = sm.get('skew_25d', 0)

    if isinstance(skew_25d, float) and skew_25d != skew_25d:
        return {'type': 'skew', 'direction': 'neutral',
                'strength': 0.0, 'detail': 'Skew data incomplete'}

    if skew_25d > 0.08:
        return {'type': 'skew', 'direction': 'sell_puts',
                'strength': round(min(0.8, skew_25d / 0.12), 2),
                'detail': f'25d skew={skew_25d:.1%} — steep, OTM puts rich'}
    if skew_25d < 0.03:
        return {'type': 'skew', 'direction': 'buy_protection',
                'strength': 0.5,
                'detail': f'25d skew={skew_25d:.1%} — flat, tail protection cheap'}
    return {'type': 'skew', 'direction': 'neutral',
            'strength': 0.2,
            'detail': f'25d skew={skew_25d:.1%} — normal'}


def _oi_regime_signal(oi_regime):
    """OI-price regime → market conviction."""
    regime = oi_regime.get('regime', 'neutral') if isinstance(oi_regime, dict) else str(oi_regime)

    _map = {
        'long_buildup':    ('bullish', 0.6, 'fresh longs entering'),
        'short_buildup':   ('bearish', 0.6, 'fresh shorts entering'),
        'short_covering':  ('bullish', 0.3, 'shorts exiting, weak rally'),
        'long_unwinding':  ('bearish', 0.3, 'longs exiting, weak selloff'),
    }
    direction, strength, desc = _map.get(regime, ('neutral', 0.1, 'no clear signal'))
    return {'type': 'oi_regime', 'direction': direction,
            'strength': strength, 'detail': f'{regime}: {desc}'}


def _event_signal(events, event_window):
    """Upcoming events → vol regime shift."""
    if not events:
        return None

    nearest = events[0]
    days_away = None
    if event_window and isinstance(event_window, dict):
        days_away = event_window.get('days_to_event')

    if days_away is not None and days_away <= 3:
        return {'type': 'event', 'direction': 'caution', 'strength': 0.9,
                'detail': f'{nearest.get("name", "Event")} in {days_away}d — IV crush risk'}
    if days_away is not None and days_away <= 7:
        return {'type': 'event', 'direction': 'vol_up', 'strength': 0.5,
                'detail': f'{nearest.get("name", "Event")} in {days_away}d — IV may expand'}
    return None


def _trend_signal(trend):
    """Price trend from composite RoC (3d+5d+10d) — the directional edge."""
    roc = trend.get('composite', trend.get('roc_5d', 0))
    abs_roc = abs(roc)
    if abs_roc < 0.01:
        return {'type': 'price_trend', 'direction': 'neutral',
                'strength': 0.1, 'detail': f'RoC={roc:+.1%} — rangebound',
                'roc': roc}
    direction = 'bullish' if roc > 0 else 'bearish'
    strength = min(0.9, abs_roc / 0.05)
    return {'type': 'price_trend', 'direction': direction,
            'strength': round(strength, 2),
            'detail': f'RoC={roc:+.1%} — trending {direction}',
            'roc': roc}


def _term_structure_signal(inverted):
    if inverted:
        return {'type': 'term_structure', 'direction': 'caution',
                'strength': 0.6, 'detail': 'Inverted — near > far IV, fear signal'}
    return {'type': 'term_structure', 'direction': 'neutral',
            'strength': 0.1, 'detail': 'Normal term structure'}


def _self_check():
    result = {
        'variance_premium': {'vp': 0.035, 'iv': 0.16, 'rv': 0.125, 'signal': 'sell_premium'},
        'vix': {'value': 15.5, 'regime': {'level': 'normal'}},
        'oi': {'pcr': {'pcr': 1.15, 'signal': 'bearish', 'contrarian': 'bullish'}},
        'skew': {7: {'skew_25d': 0.06, 'atm_iv': 0.14}},
        'oi_regime': {'regime': 'long_buildup'},
        'inverted': False,
        'upcoming_events': [],
    }

    signals = scan_signals(result)
    assert len(signals) >= 5, f"Expected ≥5 signals, got {len(signals)}"

    types = {s['type'] for s in signals}
    assert 'variance_premium' in types
    assert 'vix_regime' in types
    assert 'pcr' in types

    vp_sig = next(s for s in signals if s['type'] == 'variance_premium')
    assert vp_sig['direction'] == 'sell_premium'
    assert vp_sig['strength'] > 0.4

    vix_sig = next(s for s in signals if s['type'] == 'vix_regime')
    assert vix_sig['direction'] == 'sell_premium'

    # No-VP case
    no_rv = {'variance_premium': {'vp': 0, 'iv': 0.14, 'rv': float('nan')}}
    sigs = scan_signals(no_rv)
    assert sigs[0]['strength'] == 0.0

    # Crisis VIX
    crisis = {'vix': {'value': 40, 'regime': {}}}
    sigs = scan_signals(crisis)
    assert sigs[0]['direction'] == 'caution'

    print("signals.py: all checks passed")


if __name__ == '__main__':
    _self_check()
