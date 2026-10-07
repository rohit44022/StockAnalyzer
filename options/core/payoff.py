"""
N-leg option strategy payoff calculator.

Given any combination of calls, puts, and underlying positions, computes
the net payoff at any underlying price at expiry. Handles all 58 strategies
from Cohen's Bible of Options Strategies.

NSE conventions:
    - lot_size: Nifty=65, BankNifty=30 (Jan 2026 SEBI mandate)
    - All payoffs in ₹ per strategy unit (1 lot per leg unless specified)
"""


def leg_payoff(S_expiry, strike, option_type, action, premium, qty=1):
    """
    Payoff of a single option leg at expiry.

    Parameters
    ----------
    S_expiry : float – underlying price at expiry
    strike : float – strike price
    option_type : str – 'CE' (call) or 'PE' (put)
    action : str – 'BUY' or 'SELL'
    premium : float – premium paid/received per unit
    qty : int – number of units (lot_size × number_of_lots)

    Returns
    -------
    float – net P&L for this leg
    """
    if option_type == 'CE':
        intrinsic = max(S_expiry - strike, 0)
    elif option_type == 'PE':
        intrinsic = max(strike - S_expiry, 0)
    else:
        raise ValueError(f"option_type must be 'CE' or 'PE', got '{option_type}'")

    if action == 'BUY':
        return (intrinsic - premium) * qty
    elif action == 'SELL':
        return (premium - intrinsic) * qty
    else:
        raise ValueError(f"action must be 'BUY' or 'SELL', got '{action}'")


def strategy_payoff(legs, S_range=None, underlying_qty=0, underlying_entry=0):
    """
    Net payoff of a multi-leg strategy across a range of expiry prices.

    Parameters
    ----------
    legs : list of dict, each with keys:
        strike, option_type, action, premium, qty
    S_range : array-like of float – underlying prices to evaluate
        If None, auto-generates ±20% around the weighted average strike
    underlying_qty : int – net underlying shares (positive=long, negative=short)
    underlying_entry : float – entry price for underlying position

    Returns
    -------
    list of dict: [{price, payoff, per_leg: [payoff_leg_0, ...]}]
    """
    if S_range is None:
        strikes = [leg['strike'] for leg in legs]
        center = sum(strikes) / len(strikes)
        S_range = [center * (1 + (i - 200) * 0.001) for i in range(401)]

    results = []
    for S in S_range:
        per_leg = []
        total = 0.0
        for leg in legs:
            lp = leg_payoff(
                S, leg['strike'], leg['option_type'],
                leg['action'], leg['premium'],
                leg.get('qty', 1),
            )
            per_leg.append(lp)
            total += lp

        # underlying P&L if any
        if underlying_qty != 0:
            total += (S - underlying_entry) * underlying_qty

        results.append({'price': S, 'payoff': total, 'per_leg': per_leg})

    return results


def strategy_summary(legs, lot_size=1, underlying_qty=0, underlying_entry=0):
    """
    Key metrics for a strategy: max profit, max loss, breakevens, net debit/credit.

    Parameters
    ----------
    legs : list of dict – same format as strategy_payoff
    lot_size : int – contract lot size (Nifty=65, BankNifty=30)
    underlying_qty : int – net underlying shares
    underlying_entry : float – entry price for underlying

    Returns
    -------
    dict:
        net_premium  – net debit (<0) or credit (>0) per unit
        max_profit   – maximum profit (₹, per strategy unit, can be float('inf'))
        max_loss     – maximum loss (₹, per strategy unit, can be float('-inf'))
        breakevens   – list of underlying prices where P&L = 0
        risk_reward  – max_profit / abs(max_loss) if both finite
        payoff_data  – list of {price, payoff} for charting
    """
    strikes = [leg['strike'] for leg in legs]
    center = sum(strikes) / len(strikes)

    # evaluate across a wide range (±30%)
    lo = center * 0.70
    hi = center * 1.30
    n_points = 1000
    step = (hi - lo) / n_points
    S_range = [lo + i * step for i in range(n_points + 1)]

    payoffs = strategy_payoff(legs, S_range, underlying_qty, underlying_entry)
    pnl = [p['payoff'] for p in payoffs]

    # net premium
    net_premium = 0.0
    for leg in legs:
        qty = leg.get('qty', 1)
        if leg['action'] == 'BUY':
            net_premium -= leg['premium'] * qty
        else:
            net_premium += leg['premium'] * qty

    max_profit = max(pnl)
    max_loss = min(pnl)

    # check if unlimited (payoff still increasing/decreasing at edges)
    if pnl[-1] > pnl[-2] + step * 0.01:
        max_profit = float('inf')
    if pnl[0] < pnl[1] - step * 0.01:
        max_loss = float('-inf')

    # breakevens: where payoff crosses zero
    breakevens = []
    for i in range(len(pnl) - 1):
        if (pnl[i] <= 0 and pnl[i + 1] > 0) or (pnl[i] >= 0 and pnl[i + 1] < 0):
            # linear interpolation
            p1, p2 = pnl[i], pnl[i + 1]
            s1, s2 = S_range[i], S_range[i + 1]
            if p2 != p1:
                be = s1 + (0 - p1) * (s2 - s1) / (p2 - p1)
                breakevens.append(round(be, 2))

    # risk/reward
    if max_loss != float('-inf') and max_loss < 0 and max_profit != float('inf'):
        risk_reward = max_profit / abs(max_loss)
    else:
        risk_reward = float('inf') if max_loss == 0 else float('nan')

    return {
        'net_premium': round(net_premium, 2),
        'max_profit': round(max_profit * lot_size, 2) if max_profit != float('inf') else float('inf'),
        'max_loss': round(max_loss * lot_size, 2) if max_loss != float('-inf') else float('-inf'),
        'breakevens': breakevens,
        'risk_reward': round(risk_reward, 2) if not (risk_reward != risk_reward) else None,
        'payoff_data': [{'price': p['price'], 'payoff': round(p['payoff'] * lot_size, 2)} for p in payoffs],
    }


# ---------------------------------------------------------------------------
# self-check
# ---------------------------------------------------------------------------

def _self_check():
    """Verify payoff calculations against known strategy outcomes."""
    # 1. Long call: buy 100 CE at ₹5, qty=1
    assert leg_payoff(110, 100, 'CE', 'BUY', 5, 1) == 5.0   # ITM: 10 - 5
    assert leg_payoff(100, 100, 'CE', 'BUY', 5, 1) == -5.0   # ATM: 0 - 5
    assert leg_payoff(90, 100, 'CE', 'BUY', 5, 1) == -5.0    # OTM: 0 - 5

    # 2. Short put: sell 100 PE at ₹4, qty=1
    assert leg_payoff(110, 100, 'PE', 'SELL', 4, 1) == 4.0   # OTM: keep premium
    assert leg_payoff(90, 100, 'PE', 'SELL', 4, 1) == -6.0   # ITM: 4 - 10

    # 3. Bull call spread: buy 100 CE at 8, sell 110 CE at 3
    legs = [
        {'strike': 100, 'option_type': 'CE', 'action': 'BUY', 'premium': 8, 'qty': 1},
        {'strike': 110, 'option_type': 'CE', 'action': 'SELL', 'premium': 3, 'qty': 1},
    ]
    summary = strategy_summary(legs)
    assert summary['net_premium'] == -5.0, f"Net debit should be -5, got {summary['net_premium']}"
    # max profit: (110-100) - 5 = 5 per unit
    # max loss: -5 per unit (net debit)
    assert abs(summary['max_profit'] - 5.0) < 0.1
    assert abs(summary['max_loss'] - (-5.0)) < 0.1
    assert len(summary['breakevens']) == 1
    assert abs(summary['breakevens'][0] - 105.0) < 0.5

    # 4. Iron condor: sell 95PE@2, buy 90PE@0.5, sell 105CE@2, buy 110CE@0.5
    legs = [
        {'strike': 90, 'option_type': 'PE', 'action': 'BUY', 'premium': 0.5},
        {'strike': 95, 'option_type': 'PE', 'action': 'SELL', 'premium': 2.0},
        {'strike': 105, 'option_type': 'CE', 'action': 'SELL', 'premium': 2.0},
        {'strike': 110, 'option_type': 'CE', 'action': 'BUY', 'premium': 0.5},
    ]
    summary = strategy_summary(legs)
    assert summary['net_premium'] == 3.0, f"Net credit should be 3, got {summary['net_premium']}"
    assert abs(summary['max_profit'] - 3.0) < 0.1
    assert abs(summary['max_loss'] - (-2.0)) < 0.1  # 5 (wing width) - 3 (credit)
    assert len(summary['breakevens']) == 2

    print("payoff.py: all checks passed")


if __name__ == '__main__':
    _self_check()
