"""
IV term structure and skew analysis.

Term Structure (Natenberg Ch.20):
  - ATM IV across expiries: normal = upward-sloping (short < long)
  - Inverted = fear/event (short > long), historically strong mean-reversion signal

Skew (Natenberg Ch.24):
  - India/equity: negative skew (OTM puts > OTM calls) — crash protection
  - 25-delta skew: standard metric for skew steepness
  - Butterfly: curvature of the smile

Sticky-Strike vs Sticky-Delta:
  - Sticky-strike: IV stays with the strike (good for hedging near ATM)
  - Sticky-delta: IV stays with the delta (better for trend following)
"""

import math
import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Term structure
# ---------------------------------------------------------------------------

def term_structure(chain_df, spot, r=0.07, q=0.0):
    """
    ATM implied vol across expiries.

    Parameters
    ----------
    chain_df : DataFrame – must have columns: strike, expiry_years, iv, option_type
    spot : float – current underlying price
    r : float – risk-free rate
    q : float – dividend yield

    Returns
    -------
    DataFrame: expiry_years, atm_iv, n_strikes
        Sorted by expiry_years ascending.
    """
    df = chain_df.copy()
    df = df.dropna(subset=['iv'])
    df = df[df['iv'] > 0.01]

    rows = []
    for expiry, group in df.groupby('expiry_years'):
        calls = group[group['option_type'] == 'CE']
        if calls.empty:
            continue
        # ATM = strike closest to spot
        idx = (calls['strike'] - spot).abs().idxmin()
        atm_iv = calls.loc[idx, 'iv']
        rows.append({
            'expiry_years': float(expiry),
            'expiry_days': int(round(float(expiry) * 365)),
            'atm_iv': float(atm_iv),
            'n_strikes': len(group),
        })

    result = pd.DataFrame(rows).sort_values('expiry_years').reset_index(drop=True)
    return result


def is_inverted(ts_df):
    """True if term structure is inverted (nearest expiry IV > farthest)."""
    if len(ts_df) < 2:
        return False
    return ts_df.iloc[0]['atm_iv'] > ts_df.iloc[-1]['atm_iv']


# ---------------------------------------------------------------------------
# Skew at a single expiry
# ---------------------------------------------------------------------------

def skew_at_expiry(chain_df, expiry_years, spot, option_type='PE'):
    """
    IV skew for one expiry: IV by moneyness (strike/spot).

    Parameters
    ----------
    chain_df : DataFrame – strike, expiry_years, iv, option_type
    expiry_years : float – which expiry to extract
    spot : float – underlying price
    option_type : str – 'CE' or 'PE'

    Returns
    -------
    DataFrame: strike, moneyness, iv – sorted by strike
    """
    df = chain_df.copy()
    mask = (df['expiry_years'] == expiry_years) & (df['option_type'] == option_type)
    df = df[mask].dropna(subset=['iv'])
    df = df[df['iv'] > 0.01]

    df = df[['strike', 'iv']].copy()
    df['moneyness'] = df['strike'] / spot
    return df.sort_values('strike').reset_index(drop=True)


# ---------------------------------------------------------------------------
# Skew metrics
# ---------------------------------------------------------------------------

def skew_metrics(chain_df, expiry_years, spot, r=0.07, t=None):
    """
    Standard skew metrics for one expiry.

    Parameters
    ----------
    chain_df : DataFrame – strike, expiry_years, iv, option_type, and optionally delta
    expiry_years : float – target expiry
    spot : float – underlying price
    r : float – risk-free rate
    t : float – time to expiry (overrides expiry_years if given)

    Returns
    -------
    dict:
        atm_iv       – at-the-money IV
        skew_25d     – IV(25δ put) − IV(25δ call). Positive = normal skew.
        skew_ratio   – IV(25δ put) / IV(25δ call). >1.0 = normal skew.
        butterfly    – (IV(25δ put) + IV(25δ call)) / 2 − IV(ATM). Positive = smile.
        rr_10d       – 10-delta risk reversal (if enough strikes)
    """
    if t is None:
        t = expiry_years

    df = chain_df.copy()
    df = df[df['expiry_years'] == expiry_years].dropna(subset=['iv'])
    df = df[df['iv'] > 0.01]

    puts = df[df['option_type'] == 'PE'].copy()
    calls = df[df['option_type'] == 'CE'].copy()

    if puts.empty or calls.empty:
        return {'atm_iv': float('nan'), 'skew_25d': float('nan'),
                'skew_ratio': float('nan'), 'butterfly': float('nan'),
                'rr_10d': float('nan')}

    # ATM IV: strike closest to spot, from calls
    atm_idx = (calls['strike'] - spot).abs().idxmin()
    atm_iv = float(calls.loc[atm_idx, 'iv'])

    # 25-delta: moneyness = z·σ√t + (r + σ²/2)·t (Natenberg Ch.4 full formula)
    t_safe = max(t, 1 / 365)
    sqrt_t = math.sqrt(t_safe)
    drift = (0.07 + atm_iv ** 2 / 2) * t_safe
    offset = 0.674 * atm_iv * sqrt_t + drift
    target_put_k = spot * math.exp(-offset)
    target_call_k = spot * math.exp(offset)

    put_25d_idx = (puts['strike'] - target_put_k).abs().idxmin()
    call_25d_idx = (calls['strike'] - target_call_k).abs().idxmin()
    iv_put_25d = float(puts.loc[put_25d_idx, 'iv'])
    iv_call_25d = float(calls.loc[call_25d_idx, 'iv'])

    skew_25d = iv_put_25d - iv_call_25d
    skew_ratio = iv_put_25d / iv_call_25d if iv_call_25d > 0 else float('nan')
    butterfly = (iv_put_25d + iv_call_25d) / 2 - atm_iv

    # 10-delta risk reversal: N_inv(0.10) ≈ 1.282
    offset_10d = 1.282 * atm_iv * math.sqrt(max(t, 1 / 365))
    target_put_10d = spot * math.exp(-offset_10d)
    target_call_10d = spot * math.exp(offset_10d)

    put_10d_avail = puts[(puts['strike'] - target_put_10d).abs() < spot * 0.03]
    call_10d_avail = calls[(calls['strike'] - target_call_10d).abs() < spot * 0.03]

    if not put_10d_avail.empty and not call_10d_avail.empty:
        p10_idx = (put_10d_avail['strike'] - target_put_10d).abs().idxmin()
        c10_idx = (call_10d_avail['strike'] - target_call_10d).abs().idxmin()
        rr_10d = float(put_10d_avail.loc[p10_idx, 'iv']) - float(call_10d_avail.loc[c10_idx, 'iv'])
    else:
        rr_10d = float('nan')

    return {
        'atm_iv': atm_iv,
        'skew_25d': float(skew_25d),
        'skew_ratio': float(skew_ratio),
        'butterfly': float(butterfly),
        'rr_10d': float(rr_10d),
    }


# ---------------------------------------------------------------------------
# Full surface builder
# ---------------------------------------------------------------------------

def build_surface(chain_df, spot, r=0.07):
    """
    Build full IV surface: strike × expiry → IV.

    Parameters
    ----------
    chain_df : DataFrame – strike, expiry_years, iv, option_type
    spot : float – underlying price

    Returns
    -------
    dict:
        surface     – DataFrame pivot (index=strike, columns=expiry_days, values=iv)
        term_struct – term structure DataFrame
        skew_by_exp – dict of expiry_days → skew_metrics
    """
    ts = term_structure(chain_df, spot, r)

    # OTM options for cleaner IVs: puts for K < spot, calls for K >= spot
    df = chain_df[chain_df['iv'] > 0.01].dropna(subset=['iv']).copy()
    otm = pd.concat([
        df[(df['option_type'] == 'PE') & (df['strike'] < spot)],
        df[(df['option_type'] == 'CE') & (df['strike'] >= spot)],
    ])

    if otm.empty:
        return {'surface': pd.DataFrame(), 'term_struct': ts, 'skew_by_exp': {}}

    otm['expiry_days'] = (otm['expiry_years'] * 365).round().astype(int)

    surface = otm.pivot_table(index='strike', columns='expiry_days',
                               values='iv', aggfunc='first')

    skew_by_exp = {}
    for _, row in ts.iterrows():
        exp_y = row['expiry_years']
        exp_d = row['expiry_days']
        sm = skew_metrics(chain_df, exp_y, spot, r)
        skew_by_exp[exp_d] = sm

    return {
        'surface': surface,
        'term_struct': ts,
        'skew_by_exp': skew_by_exp,
    }


# ---------------------------------------------------------------------------
# self-check
# ---------------------------------------------------------------------------

def _self_check():
    """Verify surface analysis on synthetic chain data."""
    np.random.seed(42)
    spot = 24000

    rows = []
    for exp_y in [7 / 365, 30 / 365, 90 / 365]:
        for otype in ['CE', 'PE']:
            for strike in range(22000, 26001, 100):
                moneyness = strike / spot
                # synthetic skew: puts have higher IV when OTM
                base_iv = 0.14
                if otype == 'PE':
                    base_iv += max(0, (1 - moneyness)) * 0.3
                else:
                    base_iv += max(0, (moneyness - 1)) * 0.15
                # term structure: longer expiry → slightly higher IV
                base_iv += exp_y * 0.05
                iv = base_iv + np.random.uniform(-0.005, 0.005)
                rows.append({
                    'strike': strike, 'expiry_years': exp_y,
                    'option_type': otype, 'iv': iv,
                })

    chain = pd.DataFrame(rows)

    # term structure
    ts = term_structure(chain, spot)
    assert len(ts) == 3, f"Expected 3 expiries, got {len(ts)}"
    assert ts.iloc[0]['atm_iv'] < ts.iloc[-1]['atm_iv'], "Should be upward-sloping"
    assert not is_inverted(ts), "Should not be inverted"

    # skew
    exp_y = 30 / 365
    skew = skew_at_expiry(chain, exp_y, spot, 'PE')
    assert len(skew) > 0, "Should have put skew data"

    sm = skew_metrics(chain, exp_y, spot)
    assert sm['skew_25d'] > 0, f"Normal skew should be positive, got {sm['skew_25d']}"
    assert sm['skew_ratio'] > 1.0, f"Put IV should exceed call IV"

    # surface
    surf = build_surface(chain, spot)
    assert not surf['surface'].empty, "Surface should have data"
    assert len(surf['skew_by_exp']) == 3

    print("vol_surface.py: all checks passed")


if __name__ == '__main__':
    _self_check()
