"""
Physical settlement rules for NSE stock options (SEBI 2019+).

Index options (Nifty, BankNifty) are CASH-SETTLED — this module only
applies to STOCK options (RELIANCE, TCS etc).

Margin ramp E-4 → E-day (SEBI):
  E-4: 10% of delivery value
  E-3: 25%
  E-2: 45%
  E-1: 70%
  E-day: 100% (full delivery margin)

Close-to-money (CTM): OTM options within 25% of ATM strike are
auto-exercised by NSE. Must exit 1-2 days before expiry to avoid
unintended delivery.
"""

# Margin ramp percentages
DELIVERY_RAMP = {4: 0.10, 3: 0.25, 2: 0.45, 1: 0.70, 0: 1.00}

# CTM: within 25% of the strike interval from ATM
CTM_OTM_THRESHOLD = 0.25

# Index underlyings — cash settled, no physical settlement
CASH_SETTLED = {'NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCAPNIFTY', 'SENSEX'}


def applies(underlying):
    """Does physical settlement apply to this underlying?"""
    return underlying.upper() not in CASH_SETTLED


def delivery_margin(legs, spot, lot_size, dte):
    """
    Compute additional delivery margin for stock options near expiry.

    Parameters
    ----------
    legs : list of dicts — strike, option_type, action, qty
    spot : float
    lot_size : int
    dte : int — days to expiry

    Returns
    -------
    dict: delivery_value, margin_pct, additional_margin, affected_legs, action
    """
    if dte > 4:
        return {'delivery_value': 0, 'margin_pct': 0,
                'additional_margin': 0, 'affected_legs': [], 'action': 'none'}

    ramp_pct = DELIVERY_RAMP.get(dte, 0)
    affected = []
    total_delivery = 0.0

    for leg in legs:
        strike = leg.get('strike', 0)
        otype = leg.get('option_type', '')
        action = leg.get('action', '')
        qty = leg.get('qty', 1)

        # ITM at current spot?
        itm = (otype == 'CE' and spot > strike) or (otype == 'PE' and spot < strike)
        # CTM: OTM but within 25% of strike interval from ATM
        moneyness_pct = abs(spot - strike) / spot if spot > 0 else 0

        needs_delivery = itm or (moneyness_pct < 0.03)  # ~within 1 interval

        if needs_delivery:
            # SEBI: delivery margin on SPOT value, not strike
            delivery_val = spot * lot_size * qty

            if action == 'SELL':
                obligation = 'deliver_shares' if otype == 'CE' else 'pay_for_shares'
            else:
                obligation = 'pay_for_shares' if otype == 'CE' else 'deliver_shares'

            total_delivery += delivery_val
            affected.append({
                'strike': strike, 'option_type': otype, 'action': action,
                'obligation': obligation,
                'delivery_value': round(delivery_val, 2),
            })

    additional = total_delivery * ramp_pct

    action = 'none'
    if dte <= 2 and affected:
        action = 'exit_before_expiry'
    elif dte <= 4 and affected:
        action = 'plan_exit_or_fund'

    return {
        'delivery_value': round(total_delivery, 2),
        'margin_pct': ramp_pct,
        'additional_margin': round(additional, 2),
        'affected_legs': affected,
        'action': action,
    }


def ctm_check(legs, spot, strike_interval=50):
    """
    Identify legs that are close-to-money and at risk of auto-exercise.

    NSE auto-exercises CTM options: OTM options within 25% of ATM strike
    interval. These can surprise you with delivery obligations.

    Returns
    -------
    list of dicts — legs at CTM risk with warnings
    """
    ctm_threshold = strike_interval * CTM_OTM_THRESHOLD
    warnings = []

    for leg in legs:
        strike = leg.get('strike', 0)
        otype = leg.get('option_type', '')

        if otype == 'CE':
            distance = strike - spot
        else:
            distance = spot - strike

        # OTM but close to ATM
        if 0 < distance <= ctm_threshold:
            warnings.append({
                'strike': strike, 'option_type': otype,
                'action': leg.get('action', ''),
                'distance_from_atm': round(distance, 2),
                'ctm_threshold': ctm_threshold,
                'warning': f'{otype} {strike} is CTM (OTM by only {distance:.0f}). '
                           f'NSE will auto-exercise. Exit 1-2 days before expiry.',
            })

    return warnings


def settlement_check(legs, spot, lot_size, dte, underlying, strike_interval=50):
    """
    Combined settlement risk check.

    Returns
    -------
    dict with all settlement warnings and actions
    """
    if not applies(underlying):
        return {
            'applies': False,
            'reason': f'{underlying} is cash-settled — no physical settlement',
        }

    dm = delivery_margin(legs, spot, lot_size, dte)
    ctm = ctm_check(legs, spot, strike_interval)

    urgency = 0
    if dte <= 2 and dm['affected_legs']:
        urgency = 1
    elif dte <= 4 and dm['affected_legs']:
        urgency = 2
    elif ctm:
        urgency = 3

    return {
        'applies': True,
        'delivery': dm,
        'ctm_warnings': ctm,
        'urgency': urgency,
    }


def _self_check():
    assert applies('RELIANCE')
    assert not applies('NIFTY')
    assert not applies('BANKNIFTY')

    # Stock option near expiry
    legs = [
        {'strike': 2500, 'option_type': 'CE', 'action': 'SELL',
         'qty': 1},
    ]
    dm = delivery_margin(legs, 2600, lot_size=250, dte=2)
    assert dm['additional_margin'] > 0
    assert dm['margin_pct'] == 0.45
    assert dm['action'] == 'exit_before_expiry'

    # Far from expiry
    dm_far = delivery_margin(legs, 2600, lot_size=250, dte=10)
    assert dm_far['additional_margin'] == 0

    # CTM
    ctm = ctm_check(
        [{'strike': 2610, 'option_type': 'CE', 'action': 'SELL'}],
        spot=2600, strike_interval=50)
    assert len(ctm) == 1
    assert 'CTM' in ctm[0]['warning']

    # Full check
    sc = settlement_check(legs, 2600, 250, 2, 'RELIANCE')
    assert sc['applies']
    assert sc['urgency'] == 1

    sc_idx = settlement_check(legs, 24000, 65, 2, 'NIFTY')
    assert not sc_idx['applies']

    print("physical_settlement.py: all checks passed")


if __name__ == '__main__':
    _self_check()
