"""
Phase 4 tests: risk management — position, sizing, scenarios, margin,
limits, portfolio, physical_settlement, audit.

Book cross-checks: Sinclair Ch.8-9-10, Natenberg Ch.6-7, Cohen risk,
Davey Ch.5, NSE/SEBI rules.
"""

from options.core import bsm
from options.risk import (position, sizing, scenarios, margin,
                          limits, portfolio, physical_settlement, audit)


# ── helpers ───────────────────────────────────────────────────────

def _straddle_legs(spot=24000, iv=0.15, t=14/365):
    return [
        {'strike': spot, 'option_type': 'CE', 'action': 'SELL',
         'premium': bsm.bsm_price(spot, spot, t, 0.07, iv, 'CE'),
         'iv': iv, 'expiry_years': t, 'qty': 1},
        {'strike': spot, 'option_type': 'PE', 'action': 'SELL',
         'premium': bsm.bsm_price(spot, spot, t, 0.07, iv, 'PE'),
         'iv': iv, 'expiry_years': t, 'qty': 1},
    ]


def _ic_legs(spot=24000, iv=0.15, t=14/365, width=100):
    return [
        {'strike': spot - 2*width, 'option_type': 'PE', 'action': 'BUY',
         'premium': bsm.bsm_price(spot, spot-2*width, t, 0.07, iv, 'PE'),
         'iv': iv, 'expiry_years': t, 'qty': 1},
        {'strike': spot - width, 'option_type': 'PE', 'action': 'SELL',
         'premium': bsm.bsm_price(spot, spot-width, t, 0.07, iv, 'PE'),
         'iv': iv, 'expiry_years': t, 'qty': 1},
        {'strike': spot + width, 'option_type': 'CE', 'action': 'SELL',
         'premium': bsm.bsm_price(spot, spot+width, t, 0.07, iv, 'CE'),
         'iv': iv, 'expiry_years': t, 'qty': 1},
        {'strike': spot + 2*width, 'option_type': 'CE', 'action': 'BUY',
         'premium': bsm.bsm_price(spot, spot+2*width, t, 0.07, iv, 'CE'),
         'iv': iv, 'expiry_years': t, 'qty': 1},
    ]


# ══════════════════════════════════════════════════════════════════
# POSITION TESTS (Natenberg Ch.6-7)
# ══════════════════════════════════════════════════════════════════

def test_straddle_greeks():
    legs = _straddle_legs()
    agg = position.aggregate_greeks(legs, 24000)
    assert agg['gamma'] < 0, "Short straddle = short gamma"
    assert agg['theta'] > 0, "Short straddle = positive theta"
    assert agg['vega'] < 0, "Short straddle = short vega"


def test_ic_greeks():
    legs = _ic_legs()
    agg = position.aggregate_greeks(legs, 24000)
    assert agg['gamma'] < 0, "Iron condor = short gamma"
    assert agg['theta'] > 0, "Iron condor = positive theta"
    assert agg['vega'] < 0, "Iron condor = short vega"
    assert abs(agg['delta']) < 0.3, "IC should be near delta-neutral"


def test_long_call_greeks():
    legs = [{'strike': 24000, 'option_type': 'CE', 'action': 'BUY',
             'premium': 300, 'iv': 0.15, 'expiry_years': 14/365, 'qty': 1}]
    agg = position.aggregate_greeks(legs, 24000)
    assert agg['delta'] > 0, "Long call = positive delta"
    assert agg['gamma'] > 0, "Long call = positive gamma"
    assert agg['theta'] < 0, "Long call = negative theta"
    assert agg['vega'] > 0, "Long call = positive vega"


def test_position_pnl_theta_decay():
    """Short straddle with time passing and stable spot → profit."""
    legs = _straddle_legs(t=14/365)
    # Reprice at 3 DTE
    for l in legs:
        l['expiry_years'] = 3/365
    pnl = position.position_pnl(legs, 24000)
    assert pnl['total_pnl'] > 0, "Theta should generate profit"
    assert pnl['daily_theta'] > 0


def test_position_pnl_adverse():
    """Short straddle with big move → loss."""
    legs = _straddle_legs(t=14/365)
    pnl = position.position_pnl(legs, 25000)  # +1000 move
    assert pnl['total_pnl'] < 0, "Big move should cause loss"


def test_dollar_delta():
    legs = _ic_legs()
    dd = position.dollar_delta(legs, 24000, 65)
    assert isinstance(dd, float)
    # IC is near delta-neutral → dollar delta should be modest
    assert abs(dd) < 500_000


# ══════════════════════════════════════════════════════════════════
# SIZING TESTS (Sinclair Ch.9)
# ══════════════════════════════════════════════════════════════════

def test_kelly_basic():
    f = sizing.kelly_fraction(0.55, 1.0)
    assert 0.09 < f < 0.11, f"55/45 coin flip with 1:1 → ~10%: got {f}"


def test_kelly_edge_cases():
    assert sizing.kelly_fraction(0.5, 1.0) == 0.0, "50/50 fair coin → 0"
    assert sizing.kelly_fraction(0.4, 1.0) < 0, "Losing game → negative"
    assert sizing.kelly_fraction(0.0, 1.0) < 0


def test_kelly_high_payoff():
    f = sizing.kelly_fraction(0.3, 5.0)
    assert f > 0, "Low prob but high payoff can be positive"


# Sinclair eq.9.37-9.38: negative skew reduces Kelly
def test_adjusted_kelly_negative_skew():
    raw = 0.10
    adj = sizing.adjusted_kelly(raw, skewness=-2.0, kurtosis=8.0)
    assert adj < raw, f"Negative skew should reduce: {adj} vs {raw}"


def test_adjusted_kelly_normal():
    raw = 0.10
    adj = sizing.adjusted_kelly(raw, skewness=0.0, kurtosis=3.0)
    assert abs(adj - raw) < 0.001, "Normal dist → no adjustment"


# Sinclair: 0.05-0.48× Kelly practical range
def test_fractional_clamping():
    r1 = sizing.position_size(1_000_000, 0.20, 15_000, fractional=0.01)
    assert r1['fractional'] == 0.05, "Should clamp up to 0.05"

    r2 = sizing.position_size(1_000_000, 0.20, 15_000, fractional=0.90)
    assert r2['fractional'] == 0.48, "Should clamp down to 0.48"


def test_position_size_cap():
    result = sizing.position_size(1_000_000, 0.50, 5_000)
    assert result['capital_pct'] <= 5.0, "Must respect 5% per-position cap"


def test_negative_edge_no_trade():
    result = sizing.position_size(1_000_000, -0.05, 15_000)
    assert result['lots'] == 0
    assert 'Negative edge' in result['warnings'][0]


# Portfolio limits
def test_portfolio_deployed_limit():
    positions = [{'capital_at_risk': 200_000}] * 3
    check = sizing.validate_portfolio_limits(positions, 1_000_000)
    assert check['deployed_pct'] == 60.0
    assert not check['ok'], "60% > 50% limit"


def test_portfolio_correlated_limit():
    positions = [
        {'capital_at_risk': 110_000, 'correlated_group': 'nifty'},
        {'capital_at_risk': 110_000, 'correlated_group': 'nifty'},
    ]
    check = sizing.validate_portfolio_limits(positions, 500_000)
    assert not check['ok']
    assert any('nifty' in v for v in check['violations'])


# Sinclair Ch.9: -15% DD → reduce by 50%
def test_drawdown_stop():
    curve = [100, 110, 115, 100, 90, 85]
    dd = sizing.drawdown_check(curve)
    assert dd['action'] == 'reduce_50pct'
    assert dd['max_dd'] > 15

    curve_ok = [100, 105, 108, 106, 105]
    dd = sizing.drawdown_check(curve_ok)
    assert dd['action'] == 'none'


# ══════════════════════════════════════════════════════════════════
# SCENARIOS TESTS (Sinclair Ch.8)
# ══════════════════════════════════════════════════════════════════

def test_scenario_table_shape():
    legs = _ic_legs()
    table = scenarios.scenario_table(legs, 24000, lot_size=65)
    expected = len(scenarios.SPOT_CHANGES) * len(scenarios.IV_CHANGES) * len(scenarios.DAYS_ELAPSED)
    assert table['scenarios_computed'] == expected
    assert table['worst_case']['pnl_per_lot'] < 0
    assert table['best_case']['pnl_per_lot'] > 0


def test_scenario_symmetry():
    """IC should lose similarly on both sides."""
    legs = _ic_legs()
    table = scenarios.scenario_table(legs, 24000, lot_size=65,
                                     spot_changes=[-0.10, 0.10],
                                     iv_changes=[0.0], days_list=[0])
    pnls = {r['spot_change']: r['pnl_per_lot'] for r in table['grid']}
    # Both should be negative (IC loses on big moves)
    assert pnls[-0.10] < 0
    assert pnls[0.10] < 0


def test_stress_2020():
    legs = _ic_legs()
    st = scenarios.stress_test(legs, 24000, '2020_covid', lot_size=65)
    assert st['pnl_per_lot'] < 0
    assert st['new_spot'] == round(24000 * 0.62, 2)


def test_stress_rally():
    legs = _ic_legs()
    st = scenarios.stress_test(legs, 24000, 'rally', lot_size=65)
    assert st['iv_mult'] == 0.6  # IV drops in rallies


def test_stress_unknown():
    result = scenarios.stress_test([], 24000, 'fake_event')
    assert 'error' in result


# Sinclair Ch.8: entry gate — worst-case < 2× theta
def test_entry_gate_passes():
    legs = _ic_legs()
    gate = scenarios.entry_gate(legs, 24000, daily_theta=500, lot_size=65)
    assert 'passes' in gate
    assert 'ratio' in gate
    assert gate['horizon_days'] == 14, "Should infer DTE from legs"


def test_entry_gate_rejects_low_theta():
    legs = _ic_legs()
    gate = scenarios.entry_gate(legs, 24000, daily_theta=0.1, lot_size=65)
    assert not gate['passes'], "Tiny theta should fail gate"


def test_entry_gate_dte_matters():
    """7-DTE gate must be stricter than 30-DTE (less theta to earn)."""
    legs = _ic_legs()
    gate_7 = scenarios.entry_gate(legs, 24000, daily_theta=500, lot_size=65, dte=7)
    gate_30 = scenarios.entry_gate(legs, 24000, daily_theta=500, lot_size=65, dte=30)
    assert gate_7['ratio'] > gate_30['ratio'], \
        "Shorter DTE = less theta = stricter gate"
    assert gate_7['horizon_days'] == 7
    assert gate_30['horizon_days'] == 30


# ══════════════════════════════════════════════════════════════════
# MARGIN TESTS (NSE SPAN + ELM)
# ══════════════════════════════════════════════════════════════════

def test_spread_margin_benefit():
    ic_legs = _ic_legs()
    naked_legs = _straddle_legs()
    m_ic = margin.estimate_margin(ic_legs, 24000, lot_size=65)
    m_naked = margin.estimate_margin(naked_legs, 24000, lot_size=65)
    assert m_ic['total_margin'] < m_naked['total_margin'], \
        "Spread should need less margin than naked"
    assert m_ic['margin_benefit'] > 0


def test_elm_index_vs_stock():
    legs = _straddle_legs()
    m_idx = margin.estimate_margin(legs, 24000, underlying='NIFTY')
    m_stk = margin.estimate_margin(legs, 24000, underlying='RELIANCE')
    assert m_stk['elm'] > m_idx['elm'], "Stock ELM (3.5%) > index ELM (2%)"


# SEBI 2025: expiry-day margin ramp
def test_expiry_surcharge():
    legs = _ic_legs()
    m_normal = margin.estimate_margin(legs, 24000, dte=10)
    m_expiry = margin.estimate_margin(legs, 24000, dte=1)
    assert m_expiry['expiry_surcharge'] > 0
    assert m_expiry['total_margin'] > m_normal['total_margin']


def test_margin_utilization():
    assert margin.margin_utilization(100_000, 500_000)['status'] == 'ok'
    assert margin.margin_utilization(300_000, 500_000)['status'] == 'warning'
    assert margin.margin_utilization(450_000, 500_000)['status'] == 'danger'


# ══════════════════════════════════════════════════════════════════
# LIMITS TESTS (NSE MWPL + SEBI)
# ══════════════════════════════════════════════════════════════════

def test_mwpl_ok():
    r = limits.mwpl_check(500, 1000)
    assert r['status'] == 'ok'
    assert r['can_open_new']


def test_mwpl_caution():
    r = limits.mwpl_check(700, 1000)
    assert r['status'] == 'caution'
    assert r['can_open_new']


def test_mwpl_ban():
    r = limits.mwpl_check(960, 1000)
    assert r['status'] == 'ban'
    assert not r['can_open_new']


def test_client_limit():
    cl = limits.client_limit_check(50, 10000)
    assert not cl['breached']
    assert cl['oi_limit'] == 100  # 1% of 10000

    cl2 = limits.client_limit_check(200, 10000)
    assert cl2['breached']


def test_ban_actions():
    pos = [{'strategy': 'ic', 'legs': [{'action': 'SELL'}, {'action': 'BUY'}]}]
    acts = limits.ban_period_actions('ban', pos)
    assert acts[0]['urgency'] == 1
    assert limits.ban_period_actions('ok', pos) == []


def test_sqoff_warning():
    w = limits.sqoff_warning(5, True)
    assert w['urgency'] == 1
    w = limits.sqoff_warning(20, True)
    assert w['urgency'] == 2
    assert limits.sqoff_warning(60, True) is None
    assert limits.sqoff_warning(5, False) is None


# ══════════════════════════════════════════════════════════════════
# PORTFOLIO TESTS (Sinclair Ch.8)
# ══════════════════════════════════════════════════════════════════

def test_portfolio_aggregate():
    positions = [
        {'strategy': 'iron_condor', 'underlying': 'NIFTY',
         'spot': 24000, 'lot_size': 65, 'lots': 1, 'legs': _ic_legs()},
    ]
    agg = portfolio.aggregate(positions)
    assert agg['position_count'] == 1
    assert agg['total_exposure'] > 0
    assert 'delta' in agg['net_greeks']


def test_portfolio_var():
    var = portfolio.parametric_var(
        portfolio_delta=-0.08, portfolio_vega=-5.0,
        spot=24000, daily_vol=0.012, confidence=0.95)
    assert var['var_amount'] > 0
    assert var['delta_component'] > 0


# Sinclair Ch.8: concentration warning
def test_concentration_single_underlying():
    breakdown = [{'underlying': 'NIFTY', 'notional': 1_000_000}]
    conc = portfolio.concentration_check(breakdown, 1_000_000)
    assert len(conc['warnings']) > 0, "100% concentration should warn"


def test_concentration_diversified():
    breakdown = [
        {'underlying': 'NIFTY', 'notional': 400_000},
        {'underlying': 'BANKNIFTY', 'notional': 400_000},
        {'underlying': 'FINNIFTY', 'notional': 200_000},
    ]
    conc = portfolio.concentration_check(breakdown, 1_000_000)
    assert len(conc['warnings']) == 0


# ══════════════════════════════════════════════════════════════════
# PHYSICAL SETTLEMENT TESTS (SEBI 2019+)
# ══════════════════════════════════════════════════════════════════

def test_applies_index_vs_stock():
    assert not physical_settlement.applies('NIFTY')
    assert not physical_settlement.applies('BANKNIFTY')
    assert physical_settlement.applies('RELIANCE')
    assert physical_settlement.applies('TCS')


# SEBI margin ramp: E-4=10%, E-3=25%, E-2=45%, E-1=70%, E-day=100%
def test_delivery_ramp():
    legs = [{'strike': 2500, 'option_type': 'CE', 'action': 'SELL', 'qty': 1}]
    for dte, expected_pct in [(4, 0.10), (3, 0.25), (2, 0.45), (1, 0.70), (0, 1.00)]:
        dm = physical_settlement.delivery_margin(legs, 2600, 250, dte)
        assert dm['margin_pct'] == expected_pct, f"DTE={dte}: expected {expected_pct}"


def test_no_delivery_far():
    legs = [{'strike': 2500, 'option_type': 'CE', 'action': 'SELL', 'qty': 1}]
    dm = physical_settlement.delivery_margin(legs, 2600, 250, 10)
    assert dm['additional_margin'] == 0


def test_ctm_detection():
    # OTM CE by only 10pts on a 50pt interval → CTM
    legs = [{'strike': 24010, 'option_type': 'CE', 'action': 'SELL'}]
    ctm = physical_settlement.ctm_check(legs, 24000, strike_interval=50)
    assert len(ctm) == 1
    assert 'CTM' in ctm[0]['warning']

    # OTM CE by 500pts → not CTM
    legs2 = [{'strike': 24500, 'option_type': 'CE', 'action': 'SELL'}]
    ctm2 = physical_settlement.ctm_check(legs2, 24000, strike_interval=50)
    assert len(ctm2) == 0


# SEBI: delivery margin on spot value, NOT strike
def test_delivery_uses_spot_not_strike():
    legs = [{'strike': 2500, 'option_type': 'CE', 'action': 'SELL', 'qty': 1}]
    dm = physical_settlement.delivery_margin(legs, spot=2600, lot_size=250, dte=0)
    # Delivery value = spot × lot_size = 2600 × 250 = 650,000
    assert dm['delivery_value'] == 2600 * 250, \
        f"Must use spot (2600), not strike (2500): got {dm['delivery_value']}"


def test_settlement_cash_settled():
    sc = physical_settlement.settlement_check([], 24000, 65, 2, 'NIFTY')
    assert not sc['applies']


def test_settlement_stock_near_expiry():
    legs = [{'strike': 2500, 'option_type': 'PE', 'action': 'SELL', 'qty': 1}]
    sc = physical_settlement.settlement_check(legs, 2400, 250, 2, 'RELIANCE')
    assert sc['applies']
    assert sc['urgency'] == 1


# ══════════════════════════════════════════════════════════════════
# AUDIT TESTS (Davey Ch.5 + SEBI)
# ══════════════════════════════════════════════════════════════════

def test_audit_passes():
    trade = {
        'strategy': 'iron_condor', 'lots': 2,
        'entry_rationale': 'VP=4.2%, VIX=16',
        'estimated_margin': 80_000, 'max_loss': 30_000,
        'exit_plan': {'stop_loss': -21_000, 'take_profit': 15_000},
    }
    result = audit.audit_trade(trade, 1_000_000, 500_000)
    assert result['approved']


def test_audit_ban_rejects():
    trade = {'strategy': 'ic', 'entry_rationale': 'test'}
    result = audit.audit_trade(trade, 1_000_000, 500_000, mwpl_status='ban')
    assert not result['approved']
    assert 'ban' in result['rejection_reasons'][0].lower()


def test_audit_oversized_rejects():
    trade = {'strategy': 'ic', 'entry_rationale': 'test', 'max_loss': 60_000}
    result = audit.audit_trade(trade, 1_000_000, 500_000)
    assert not result['approved']
    assert any('5%' in r for r in result['rejection_reasons'])


# Davey: document entry rationale
def test_audit_no_rationale_warns():
    trade = {'strategy': 'ic'}
    result = audit.audit_trade(trade, 1_000_000, 500_000)
    warns = [c for c in result['checks'] if c['status'] == 'WARN']
    assert any('rationale' in w['detail'].lower() for w in warns)


def test_daily_summary():
    trades = [
        {'strategy': 'ic', 'pnl': 5000},
        {'strategy': 'ic', 'pnl': -3000},
        {'strategy': 'bps', 'pnl': 2000},
    ]
    ds = audit.daily_summary(trades)
    assert ds['total_pnl'] == 4000
    assert ds['wins'] == 2
    assert ds['losses'] == 1
    assert ds['win_rate'] == 66.7


# ══════════════════════════════════════════════════════════════════
# INTEGRATION: FULL RISK PIPELINE
# ══════════════════════════════════════════════════════════════════

def test_full_risk_pipeline():
    """Build position → greeks → sizing → margin → scenario → audit."""
    legs = _ic_legs()
    spot = 24000
    capital = 1_000_000

    # 1. Position Greeks
    agg = position.aggregate_greeks(legs, spot)
    assert agg['theta'] > 0

    # 2. Sizing
    max_loss_per_lot = 100 * 65  # 100pt wing × 65 lot
    size = sizing.position_size(capital, 0.10, max_loss_per_lot)
    assert size['lots'] > 0

    # 3. Margin
    m = margin.estimate_margin(legs, spot, lot_size=65, underlying='NIFTY')
    assert m['total_margin'] > 0

    # 4. Scenario gate
    daily_theta = agg['theta'] * 65  # per lot
    gate = scenarios.entry_gate(legs, spot, daily_theta, lot_size=65)
    assert 'passes' in gate

    # 5. Stress test
    st = scenarios.stress_test(legs, spot, '2020_covid', lot_size=65)
    assert st['pnl_per_lot'] < 0

    # 6. Limits
    mwpl = limits.mwpl_check(500, 1000)
    assert mwpl['can_open_new']

    # 7. Audit
    trade = {
        'strategy': 'iron_condor',
        'entry_rationale': 'VP positive, VIX in sweet spot',
        'estimated_margin': m['total_margin'],
        'max_loss': max_loss_per_lot * size['lots'],
        'exit_plan': {'stop_loss': -4500, 'take_profit': 3000},
    }
    result = audit.audit_trade(trade, capital, capital * 0.5, mwpl['status'])
    assert result['approved']


# ══════════════════════════════════════════════════════════════════

ALL_TESTS = [
    # Position
    test_straddle_greeks, test_ic_greeks, test_long_call_greeks,
    test_position_pnl_theta_decay, test_position_pnl_adverse,
    test_dollar_delta,
    # Sizing
    test_kelly_basic, test_kelly_edge_cases, test_kelly_high_payoff,
    test_adjusted_kelly_negative_skew, test_adjusted_kelly_normal,
    test_fractional_clamping, test_position_size_cap,
    test_negative_edge_no_trade, test_portfolio_deployed_limit,
    test_portfolio_correlated_limit, test_drawdown_stop,
    # Scenarios
    test_scenario_table_shape, test_scenario_symmetry,
    test_stress_2020, test_stress_rally, test_stress_unknown,
    test_entry_gate_passes, test_entry_gate_rejects_low_theta,
    test_entry_gate_dte_matters,
    # Margin
    test_spread_margin_benefit, test_elm_index_vs_stock,
    test_expiry_surcharge, test_margin_utilization,
    # Limits
    test_mwpl_ok, test_mwpl_caution, test_mwpl_ban,
    test_client_limit, test_ban_actions, test_sqoff_warning,
    # Portfolio
    test_portfolio_aggregate, test_portfolio_var,
    test_concentration_single_underlying, test_concentration_diversified,
    # Physical settlement
    test_applies_index_vs_stock, test_delivery_ramp, test_delivery_uses_spot_not_strike,
    test_no_delivery_far, test_ctm_detection,
    test_settlement_cash_settled, test_settlement_stock_near_expiry,
    # Audit
    test_audit_passes, test_audit_ban_rejects,
    test_audit_oversized_rejects, test_audit_no_rationale_warns,
    test_daily_summary,
    # Integration
    test_full_risk_pipeline,
]


if __name__ == '__main__':
    passed = failed = 0
    for test in ALL_TESTS:
        try:
            test()
            print(f"  ✓ {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {test.__name__}: {e}")
            failed += 1

    print(f"\ntest_phase4.py: {passed} passed, {failed} failed "
          f"({passed + failed} total)")
    if failed:
        raise SystemExit(1)
