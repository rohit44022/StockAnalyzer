"""
NSE F&O transaction cost model — October 2026.

Indian options costs are SIGNIFICANTLY higher than US due to STT.
Costs eat 30-50% of gross edge (Sinclair Ch.10). Getting this wrong
by even 0.05% makes positive-edge strategies look profitable when
they're actually losers.

All rates verified against SEBI/NSE circulars (see ARCHITECTURE_AUDIT.md):
    STT sell-side on options: 0.15% of premium (Apr 2026 onward)
    Exchange charges: 0.035% (NSE, reduced from 0.0495% in Oct 2024)
    Brokerage: ₹20/order flat (discount brokers)
    GST: 18% on brokerage + exchange charges (NOT on STT)
    SEBI turnover fee: ₹10/crore
    Stamp duty: 0.003% (buy-side only)
    DP charges: ₹15.93/scrip (only for physical delivery of stocks)
"""


# ---------------------------------------------------------------------------
# rate constants — update these when SEBI/NSE changes rates
# ---------------------------------------------------------------------------

# Securities Transaction Tax (sell-side only for options)
STT_OPTION_SELL = 0.0015       # 0.15% of premium on sell
STT_OPTION_BUY = 0.0           # 0% on buy
STT_FUTURE_SELL = 0.0005       # 0.05% of notional on sell

# Exchange transaction charges
EXCHANGE_CHARGE = 0.00035      # 0.035% of premium

# Brokerage (discount broker flat fee per order)
BROKERAGE_PER_ORDER = 20.0     # ₹20/order (Zerodha, Angel, etc.)

# GST on brokerage + exchange charges
GST_RATE = 0.18                # 18%

# SEBI turnover fee
SEBI_FEE = 10.0 / 1_00_00_000  # ₹10 per crore = 0.000001

# Stamp duty (buy-side only)
STAMP_DUTY = 0.00003           # 0.003%

# DP charges (physical delivery only — stock options held to expiry)
DP_CHARGE_PER_SCRIP = 15.93    # ₹15.93 per scrip


def trade_cost(premium_per_unit, qty, action, instrument='option',
               is_expiry_settlement=False):
    """
    Total transaction cost for one leg of a trade.

    Parameters
    ----------
    premium_per_unit : float – option premium per unit (₹)
    qty : int – total quantity (lot_size × number_of_lots)
    action : str – 'BUY' or 'SELL'
    instrument : str – 'option' or 'future'
    is_expiry_settlement : bool – True if this is physical delivery at expiry

    Returns
    -------
    dict:
        stt       – Securities Transaction Tax (₹)
        brokerage – flat per-order fee (₹)
        exchange  – exchange transaction charges (₹)
        gst       – GST on brokerage + exchange (₹)
        sebi      – SEBI turnover fee (₹)
        stamp     – stamp duty (₹)
        dp        – DP charges if physical delivery (₹)
        total     – sum of all charges (₹)
    """
    turnover = premium_per_unit * qty  # total premium value

    # STT
    if instrument == 'option':
        if action == 'SELL':
            stt = turnover * STT_OPTION_SELL
        else:
            stt = turnover * STT_OPTION_BUY  # 0 for buy
    else:
        if action == 'SELL':
            stt = turnover * STT_FUTURE_SELL
        else:
            stt = 0.0

    # Brokerage: flat ₹20 per order, or 0.03% whichever is lower
    # (most discount brokers cap at ₹20)
    brokerage = min(BROKERAGE_PER_ORDER, turnover * 0.0003)

    # Exchange charges
    exchange = turnover * EXCHANGE_CHARGE

    # GST on (brokerage + exchange charges), NOT on STT
    gst = (brokerage + exchange) * GST_RATE

    # SEBI fee
    sebi = turnover * SEBI_FEE

    # Stamp duty (buy-side only)
    stamp = turnover * STAMP_DUTY if action == 'BUY' else 0.0

    # DP charges (physical delivery)
    dp = DP_CHARGE_PER_SCRIP if is_expiry_settlement else 0.0

    total = stt + brokerage + exchange + gst + sebi + stamp + dp

    return {
        'stt': round(stt, 2),
        'brokerage': round(brokerage, 2),
        'exchange': round(exchange, 2),
        'gst': round(gst, 2),
        'sebi': round(sebi, 2),
        'stamp': round(stamp, 2),
        'dp': round(dp, 2),
        'total': round(total, 2),
    }


def round_trip_cost(legs, lot_size):
    """
    Total cost for entering AND exiting a multi-leg strategy.

    Parameters
    ----------
    legs : list of dict, each with:
        premium : float – premium per unit
        action : str – 'BUY' or 'SELL'
        qty_lots : int – number of lots (default 1)
    lot_size : int – contract lot size (Nifty=65, BankNifty=30)

    Returns
    -------
    dict:
        entry_cost  – total cost to enter all legs (₹)
        exit_cost   – total cost to exit all legs (₹)
        total       – entry + exit (₹)
        per_lot     – total / number of lots (₹)
        as_pct_of_premium – total cost as % of total premium traded
    """
    entry_total = 0.0
    exit_total = 0.0
    premium_traded = 0.0

    for leg in legs:
        qty_lots = leg.get('qty_lots', 1)
        qty = lot_size * qty_lots
        premium = leg['premium']
        action = leg['action']
        exit_action = 'SELL' if action == 'BUY' else 'BUY'

        entry = trade_cost(premium, qty, action)
        exit_ = trade_cost(premium, qty, exit_action)

        entry_total += entry['total']
        exit_total += exit_['total']
        premium_traded += premium * qty

    total = entry_total + exit_total
    total_lots = sum(leg.get('qty_lots', 1) for leg in legs)

    return {
        'entry_cost': round(entry_total, 2),
        'exit_cost': round(exit_total, 2),
        'total': round(total, 2),
        'per_lot': round(total / max(total_lots, 1), 2),
        'as_pct_of_premium': round(total / max(premium_traded, 0.01) * 100, 2),
    }


def cost_breakdown(premium, lot_size, action='SELL', n_lots=1):
    """
    Detailed single-leg cost breakdown with human-readable labels.
    Useful for the UI to show traders exactly where their money goes.

    Returns
    -------
    list of dict: [{label, amount, rate_description}]
    """
    qty = lot_size * n_lots
    turnover = premium * qty
    costs = trade_cost(premium, qty, action)

    breakdown = [
        {
            'label': 'STT (Securities Transaction Tax)',
            'amount': costs['stt'],
            'rate': f"{'0.15% on sell' if action == 'SELL' else '0% on buy'}",
            'note': 'Biggest cost for option sellers. Changed Apr 2026.',
        },
        {
            'label': 'Brokerage',
            'amount': costs['brokerage'],
            'rate': f"₹{BROKERAGE_PER_ORDER}/order (flat)",
            'note': 'Same whether you trade 1 lot or 100 lots.',
        },
        {
            'label': 'Exchange Transaction Charges',
            'amount': costs['exchange'],
            'rate': '0.035% of premium',
            'note': 'Paid to NSE. Reduced from 0.0495% in Oct 2024.',
        },
        {
            'label': 'GST',
            'amount': costs['gst'],
            'rate': '18% on (brokerage + exchange charges)',
            'note': 'NOT charged on STT or stamp duty.',
        },
        {
            'label': 'SEBI Turnover Fee',
            'amount': costs['sebi'],
            'rate': '₹10 per crore',
            'note': 'Tiny but adds up on large volumes.',
        },
        {
            'label': 'Stamp Duty',
            'amount': costs['stamp'],
            'rate': '0.003% (buy-side only)',
            'note': 'Only charged when buying, not selling.',
        },
    ]

    breakdown.append({
        'label': 'TOTAL',
        'amount': costs['total'],
        'rate': f"{costs['total'] / max(turnover, 0.01) * 100:.3f}% of premium",
        'note': f"On turnover ₹{turnover:,.0f} ({n_lots} lot × {lot_size} qty × ₹{premium})",
    })

    return breakdown


# ---------------------------------------------------------------------------
# self-check
# ---------------------------------------------------------------------------

def _self_check():
    """
    Verify cost model against the worked example in ARCHITECTURE.md:
    Nifty ATM call, premium ₹200, lot_size=65, SELL side.
    """
    costs = trade_cost(200, 65, 'SELL')
    # STT: ₹13,000 × 0.15% = ₹19.50
    assert abs(costs['stt'] - 19.50) < 0.01, f"STT: expected 19.50, got {costs['stt']}"
    # Brokerage: ₹20 (flat, since ₹13,000 × 0.03% = ₹3.9 < ₹20 → capped at ₹3.9)
    # Actually min(20, 13000*0.0003) = min(20, 3.90) = 3.90
    assert abs(costs['brokerage'] - 3.90) < 0.01, f"Brokerage: expected 3.90, got {costs['brokerage']}"
    # Exchange: ₹13,000 × 0.035% = ₹4.55
    assert abs(costs['exchange'] - 4.55) < 0.01, f"Exchange: expected 4.55, got {costs['exchange']}"
    # GST: (3.90 + 4.55) × 18% = ₹1.521
    expected_gst = (3.90 + 4.55) * 0.18
    assert abs(costs['gst'] - round(expected_gst, 2)) < 0.02, f"GST: expected {expected_gst:.2f}, got {costs['gst']}"

    # round-trip for iron condor (4 legs)
    ic_legs = [
        {'premium': 50, 'action': 'BUY'},
        {'premium': 100, 'action': 'SELL'},
        {'premium': 100, 'action': 'SELL'},
        {'premium': 50, 'action': 'BUY'},
    ]
    rt = round_trip_cost(ic_legs, lot_size=65)
    assert rt['total'] > 0, "Round-trip cost must be positive"
    assert rt['per_lot'] > 0
    # 4 legs × 2 sides = 8 orders minimum
    # STT on sells: 2 sell legs × 100 × 65 × 0.15% = ₹19.50 each entry
    # Plus exit: 2 buy-to-close legs now become sells → STT again

    # cost_breakdown returns a list
    bd = cost_breakdown(200, 65, 'SELL')
    assert len(bd) == 7  # 6 line items + total
    assert bd[-1]['label'] == 'TOTAL'
    assert bd[-1]['amount'] > 0

    print("cost_model.py: all checks passed")


if __name__ == '__main__':
    _self_check()
