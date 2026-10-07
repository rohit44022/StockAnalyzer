"""
Deep unit tests for Phase 1: Core Pricing.

Every formula is verified against:
  - Known analytical values from textbooks
  - Natenberg's 12 rules of thumb (Workbook Ch.20)
  - Numerical finite-difference verification for all Greeks
  - NSE-realistic values (Nifty/BankNifty, Indian rates, 2026 costs)
  - Edge cases that would break production
"""

import math
import pytest
import numpy as np
from options.core.bsm import bsm_price, bsm_greeks, put_call_parity
from options.core.iv import implied_vol, iv_chain
from options.core.volatility import (
    close_to_close_vol, parkinson_vol, garman_klass_vol,
    yang_zhang_vol, vol_cone,
)
from options.core.payoff import leg_payoff, strategy_payoff, strategy_summary
from options.core.cost_model import (
    trade_cost, round_trip_cost, cost_breakdown,
    STT_OPTION_SELL, EXCHANGE_CHARGE, GST_RATE,
)
from options.core.dividends import (
    dividend_adjusted_forward, bsm_price_with_dividends,
    bsm_greeks_with_dividends,
)


# ═══════════════════════════════════════════════════════════════════════════
# BSM PRICING — bsm.py
# ═══════════════════════════════════════════════════════════════════════════

class TestBSMPricing:
    """BSM pricing against known analytical values."""

    # Standard textbook case: S=100, K=100, t=1yr, r=5%, σ=20%
    # Known: C ≈ 10.4506, P ≈ 5.5735

    def test_atm_call_textbook(self):
        c = bsm_price(100, 100, 1.0, 0.05, 0.20, 'CE')
        assert abs(c - 10.4506) < 0.01

    def test_atm_put_textbook(self):
        p = bsm_price(100, 100, 1.0, 0.05, 0.20, 'PE')
        assert abs(p - 5.5735) < 0.01

    def test_itm_call(self):
        c = bsm_price(110, 100, 1.0, 0.05, 0.20, 'CE')
        assert c > 10.4506, "ITM call > ATM call"
        assert c > 10.0, "ITM call > intrinsic"

    def test_otm_call(self):
        c = bsm_price(90, 100, 1.0, 0.05, 0.20, 'CE')
        assert 0 < c < 10.4506, "OTM call: positive but < ATM"

    def test_price_increases_with_vol(self):
        c_lo = bsm_price(100, 100, 0.25, 0.05, 0.10, 'CE')
        c_hi = bsm_price(100, 100, 0.25, 0.05, 0.30, 'CE')
        assert c_hi > c_lo, "Higher vol = higher option price"

    def test_price_increases_with_time(self):
        c_short = bsm_price(100, 100, 0.1, 0.05, 0.20, 'CE')
        c_long = bsm_price(100, 100, 1.0, 0.05, 0.20, 'CE')
        assert c_long > c_short, "More time = higher option price"

    def test_call_upper_bound(self):
        """Call price ≤ S (Natenberg: call can never be worth more than stock)."""
        c = bsm_price(100, 50, 2.0, 0.10, 0.50, 'CE')
        assert c <= 100.0

    def test_call_lower_bound(self):
        """Call ≥ max(S·e^(-qt) - K·e^(-rt), 0)."""
        S, K, t, r = 120, 100, 1.0, 0.05
        c = bsm_price(S, K, t, r, 0.20, 'CE')
        lower = max(S - K * math.exp(-r * t), 0)
        assert c >= lower - 0.001

    def test_put_upper_bound(self):
        """Put ≤ K·e^(-rt)."""
        p = bsm_price(50, 100, 1.0, 0.05, 0.50, 'PE')
        assert p <= 100 * math.exp(-0.05)

    def test_put_lower_bound(self):
        """Put ≥ max(K·e^(-rt) - S, 0)."""
        S, K, t, r = 80, 100, 1.0, 0.05
        p = bsm_price(S, K, t, r, 0.20, 'PE')
        lower = max(K * math.exp(-r * t) - S, 0)
        assert p >= lower - 0.001

    def test_expiry_intrinsic_call_itm(self):
        assert bsm_price(110, 100, 0, 0.05, 0.20, 'CE') == 10.0

    def test_expiry_intrinsic_call_otm(self):
        assert bsm_price(90, 100, 0, 0.05, 0.20, 'CE') == 0.0

    def test_expiry_intrinsic_put_itm(self):
        assert bsm_price(90, 100, 0, 0.05, 0.20, 'PE') == 10.0

    def test_expiry_intrinsic_put_otm(self):
        assert bsm_price(110, 100, 0, 0.05, 0.20, 'PE') == 0.0

    def test_nifty_atm_30dte(self):
        """Realistic Nifty: S=24000, r=7%, σ=14%, 30 DTE."""
        c = bsm_price(24000, 24000, 30 / 365, 0.07, 0.14, 'CE')
        # Natenberg rule of thumb: ATM ≈ 0.4 × S × σ × √t
        approx = 0.4 * 24000 * 0.14 * math.sqrt(30 / 365)
        # BSM should be somewhat higher due to r>0 forward effect
        assert approx * 0.8 < c < approx * 1.5

    def test_nifty_weekly_7dte(self):
        """Weekly expiry Nifty option."""
        c = bsm_price(24000, 24000, 7 / 365, 0.07, 0.14, 'CE')
        assert 50 < c < 400, f"7-DTE ATM premium should be moderate, got {c}"

    def test_natenberg_rule_atm_approx(self):
        """Rule of thumb #1: ATM call ≈ 0.4 × S × σ × √t (Workbook Ch.20)."""
        for S in [100, 1000, 24000]:
            for sigma in [0.10, 0.20, 0.30]:
                for t in [30 / 365, 90 / 365, 1.0]:
                    c = bsm_price(S, S, t, 0.0, sigma, 'CE')
                    approx = 0.4 * S * sigma * math.sqrt(t)
                    ratio = c / approx
                    assert 0.95 < ratio < 1.05, (
                        f"ATM approx off: S={S}, σ={sigma}, t={t:.3f}, "
                        f"BSM={c:.4f}, approx={approx:.4f}, ratio={ratio:.4f}"
                    )

    def test_invalid_option_type(self):
        with pytest.raises(ValueError, match="option_type"):
            bsm_price(100, 100, 1.0, 0.05, 0.20, 'CALL')

    def test_zero_vol_raises(self):
        with pytest.raises(ValueError, match="sigma"):
            bsm_price(100, 100, 1.0, 0.05, 0.0, 'CE')

    def test_with_dividend_yield(self):
        """With q > 0, call price decreases and put price increases."""
        c_no_q = bsm_price(100, 100, 1.0, 0.05, 0.20, 'CE', q=0.0)
        c_with_q = bsm_price(100, 100, 1.0, 0.05, 0.20, 'CE', q=0.02)
        assert c_with_q < c_no_q

        p_no_q = bsm_price(100, 100, 1.0, 0.05, 0.20, 'PE', q=0.0)
        p_with_q = bsm_price(100, 100, 1.0, 0.05, 0.20, 'PE', q=0.02)
        assert p_with_q > p_no_q


# ═══════════════════════════════════════════════════════════════════════════
# PUT-CALL PARITY — bsm.py
# ═══════════════════════════════════════════════════════════════════════════

class TestPutCallParity:
    """
    Natenberg Ch.15: C - P = S·e^(-qt) - K·e^(-rt)
    Must hold for ALL strikes, expiries, vols.
    """

    @pytest.mark.parametrize("S,K,t,r,sigma,q", [
        (100, 100, 1.0, 0.05, 0.20, 0.0),    # textbook ATM
        (100, 110, 0.5, 0.07, 0.30, 0.0),     # OTM call
        (100, 90, 0.25, 0.03, 0.15, 0.0),     # ITM call
        (24000, 24000, 30/365, 0.07, 0.14, 0.0),  # Nifty ATM
        (24000, 24500, 7/365, 0.07, 0.18, 0.0),   # Nifty weekly OTM
        (2500, 2500, 90/365, 0.07, 0.25, 0.02),   # stock with div yield
        (100, 100, 2.0, 0.10, 0.40, 0.05),    # high rate + yield
    ])
    def test_parity_holds(self, S, K, t, r, sigma, q):
        c = bsm_price(S, K, t, r, sigma, 'CE', q)
        p = bsm_price(S, K, t, r, sigma, 'PE', q)
        violation = put_call_parity(S, K, t, r, q, c, p)
        assert abs(violation) < 1e-10, f"Parity violated by {violation}"

    def test_recover_put_from_call(self):
        c = bsm_price(100, 100, 1.0, 0.05, 0.20, 'CE')
        p_bsm = bsm_price(100, 100, 1.0, 0.05, 0.20, 'PE')
        p_parity = put_call_parity(100, 100, 1.0, 0.05, 0.0, call_price=c)
        assert abs(p_parity - p_bsm) < 1e-10

    def test_recover_call_from_put(self):
        p = bsm_price(100, 100, 1.0, 0.05, 0.20, 'PE')
        c_bsm = bsm_price(100, 100, 1.0, 0.05, 0.20, 'CE')
        c_parity = put_call_parity(100, 100, 1.0, 0.05, 0.0, put_price=p)
        assert abs(c_parity - c_bsm) < 1e-10


# ═══════════════════════════════════════════════════════════════════════════
# GREEKS — bsm.py (numerical finite-difference verification)
# ═══════════════════════════════════════════════════════════════════════════

class TestGreeks:
    """
    Every Greek verified by finite difference:
      Greek ≈ (f(x + h) - f(x - h)) / (2h)
    This catches formula typos that self-checks miss.
    """
    S, K, t, r, sigma = 100.0, 100.0, 0.5, 0.05, 0.20

    def _greeks(self, **overrides):
        params = dict(S=self.S, K=self.K, t=self.t, r=self.r,
                      sigma=self.sigma, option_type='CE', q=0.0)
        params.update(overrides)
        return bsm_greeks(**params)

    def _price(self, **overrides):
        params = dict(S=self.S, K=self.K, t=self.t, r=self.r,
                      sigma=self.sigma, option_type='CE', q=0.0)
        params.update(overrides)
        return bsm_price(**params)

    # --- delta: ∂price/∂S ---
    def test_delta_finite_diff(self):
        h = 0.01
        numerical = (self._price(S=self.S + h) - self._price(S=self.S - h)) / (2 * h)
        analytical = self._greeks()['delta']
        assert abs(numerical - analytical) < 1e-5, f"Delta: num={numerical}, ana={analytical}"

    # --- gamma: ∂²price/∂S² ---
    def test_gamma_finite_diff(self):
        h = 0.01
        d_up = bsm_greeks(self.S + h, self.K, self.t, self.r, self.sigma, 'CE')['delta']
        d_dn = bsm_greeks(self.S - h, self.K, self.t, self.r, self.sigma, 'CE')['delta']
        numerical = (d_up - d_dn) / (2 * h)
        analytical = self._greeks()['gamma']
        assert abs(numerical - analytical) < 1e-5, f"Gamma: num={numerical}, ana={analytical}"

    # --- theta: ∂price/∂t (annual) → per day = / 365 ---
    def test_theta_finite_diff(self):
        h = 1 / 365  # 1 day in years
        # theta = -(price_later - price_now) / h  (time passing = t decreases)
        p_now = self._price()
        p_later = self._price(t=self.t - h)
        numerical_per_day = -(p_now - p_later) / 1  # change over 1 day
        # negative because less time = lower price for long option
        analytical = self._greeks()['theta']  # already per day
        assert abs(numerical_per_day - analytical) < 0.05, (
            f"Theta: num={numerical_per_day:.6f}, ana={analytical:.6f}"
        )

    # --- vega: ∂price/∂σ per 1% ---
    def test_vega_finite_diff(self):
        h = 0.001  # 0.1% change in sigma
        numerical_raw = (self._price(sigma=self.sigma + h) -
                         self._price(sigma=self.sigma - h)) / (2 * h)
        numerical_per_1pct = numerical_raw / 100
        analytical = self._greeks()['vega']
        assert abs(numerical_per_1pct - analytical) < 1e-4, (
            f"Vega: num={numerical_per_1pct}, ana={analytical}"
        )

    # --- rho: ∂price/∂r per 1% ---
    def test_rho_finite_diff(self):
        h = 0.0001
        numerical_raw = (self._price(r=self.r + h) -
                         self._price(r=self.r - h)) / (2 * h)
        numerical_per_1pct = numerical_raw / 100
        analytical = self._greeks()['rho']
        assert abs(numerical_per_1pct - analytical) < 1e-4

    # --- charm: ∂delta/∂t per day ---
    def test_charm_finite_diff(self):
        h = 0.5 / 365  # half a day
        d_now = bsm_greeks(self.S, self.K, self.t, self.r, self.sigma, 'CE')['delta']
        d_later = bsm_greeks(self.S, self.K, self.t - h, self.r, self.sigma, 'CE')['delta']
        # charm = change in delta as time passes (t decreases)
        numerical = -(d_now - d_later) / (h * 365)  # per day
        analytical = self._greeks()['charm']
        assert abs(numerical - analytical) < 1e-4, (
            f"Charm: num={numerical:.8f}, ana={analytical:.8f}"
        )

    # --- vanna: ∂delta/∂σ per 1% ---
    def test_vanna_finite_diff(self):
        h = 0.001
        d_up = bsm_greeks(self.S, self.K, self.t, self.r, self.sigma + h, 'CE')['delta']
        d_dn = bsm_greeks(self.S, self.K, self.t, self.r, self.sigma - h, 'CE')['delta']
        numerical_raw = (d_up - d_dn) / (2 * h)
        numerical_per_1pct = numerical_raw / 100
        analytical = self._greeks()['vanna']
        assert abs(numerical_per_1pct - analytical) < 1e-5, (
            f"Vanna: num={numerical_per_1pct:.8f}, ana={analytical:.8f}"
        )

    # --- vomma: ∂vega/∂σ per 1% ---
    def test_vomma_finite_diff(self):
        h = 0.001
        v_up = bsm_greeks(self.S, self.K, self.t, self.r, self.sigma + h, 'CE')['vega']
        v_dn = bsm_greeks(self.S, self.K, self.t, self.r, self.sigma - h, 'CE')['vega']
        numerical = (v_up - v_dn) / (2 * h) / 100
        analytical = self._greeks()['vomma']
        assert abs(numerical - analytical) < 1e-5, (
            f"Vomma: num={numerical:.8f}, ana={analytical:.8f}"
        )

    # --- Greek properties (Natenberg Ch.7-9) ---

    def test_call_delta_range(self):
        """Call delta is between 0 and 1."""
        for K in [80, 90, 100, 110, 120]:
            g = bsm_greeks(100, K, 0.5, 0.05, 0.20, 'CE')
            assert 0 <= g['delta'] <= 1.0, f"Call delta out of range: {g['delta']}"

    def test_put_delta_range(self):
        """Put delta is between -1 and 0."""
        for K in [80, 90, 100, 110, 120]:
            g = bsm_greeks(100, K, 0.5, 0.05, 0.20, 'PE')
            assert -1.0 <= g['delta'] <= 0, f"Put delta out of range: {g['delta']}"

    def test_call_put_delta_relationship(self):
        """Call delta - Put delta = e^(-qt) (Natenberg Ch.7)."""
        for K in [90, 100, 110]:
            gc = bsm_greeks(100, K, 0.5, 0.05, 0.20, 'CE')
            gp = bsm_greeks(100, K, 0.5, 0.05, 0.20, 'PE')
            diff = gc['delta'] - gp['delta']
            expected = math.exp(0)  # q=0, so e^(-qt) = 1
            assert abs(diff - expected) < 1e-10

    def test_gamma_same_for_call_put(self):
        """Gamma is identical for call and put at same strike."""
        gc = bsm_greeks(100, 100, 0.5, 0.05, 0.20, 'CE')
        gp = bsm_greeks(100, 100, 0.5, 0.05, 0.20, 'PE')
        assert abs(gc['gamma'] - gp['gamma']) < 1e-12

    def test_gamma_highest_at_atm(self):
        """Gamma peaks at ATM, falls for ITM/OTM (Natenberg Ch.7)."""
        g_atm = bsm_greeks(100, 100, 0.5, 0.05, 0.20, 'CE')['gamma']
        g_itm = bsm_greeks(100, 90, 0.5, 0.05, 0.20, 'CE')['gamma']
        g_otm = bsm_greeks(100, 110, 0.5, 0.05, 0.20, 'CE')['gamma']
        assert g_atm > g_itm
        assert g_atm > g_otm

    def test_vega_same_for_call_put(self):
        """Vega is identical for call and put (Natenberg Ch.7)."""
        gc = bsm_greeks(100, 100, 0.5, 0.05, 0.20, 'CE')
        gp = bsm_greeks(100, 100, 0.5, 0.05, 0.20, 'PE')
        assert abs(gc['vega'] - gp['vega']) < 1e-12

    def test_vega_highest_at_atm(self):
        """Vega peaks at ATM (Natenberg Ch.9)."""
        v_atm = bsm_greeks(100, 100, 0.5, 0.05, 0.20, 'CE')['vega']
        v_itm = bsm_greeks(100, 90, 0.5, 0.05, 0.20, 'CE')['vega']
        v_otm = bsm_greeks(100, 110, 0.5, 0.05, 0.20, 'CE')['vega']
        assert v_atm > v_itm
        assert v_atm > v_otm

    def test_theta_negative_for_long_call(self):
        """Long options have negative theta (time decay hurts buyer)."""
        g = bsm_greeks(100, 100, 0.5, 0.05, 0.20, 'CE')
        assert g['theta'] < 0

    def test_theta_negative_for_long_put(self):
        g = bsm_greeks(100, 100, 0.5, 0.05, 0.20, 'PE')
        assert g['theta'] < 0

    def test_rho_positive_for_call(self):
        """Higher rates → higher call value (Natenberg Ch.7)."""
        g = bsm_greeks(100, 100, 0.5, 0.05, 0.20, 'CE')
        assert g['rho'] > 0

    def test_rho_negative_for_put(self):
        g = bsm_greeks(100, 100, 0.5, 0.05, 0.20, 'PE')
        assert g['rho'] < 0

    def test_vanna_near_zero_at_atm(self):
        """Vanna ≈ 0 at ATM, largest at ~20Δ and ~80Δ (Natenberg Ch.9)."""
        g_atm = bsm_greeks(100, 100, 0.5, 0.05, 0.20, 'CE')
        g_otm = bsm_greeks(100, 115, 0.5, 0.05, 0.20, 'CE')  # ~20Δ
        # ATM vanna magnitude should be smaller than OTM
        assert abs(g_atm['vanna']) < abs(g_otm['vanna'])

    def test_greeks_at_expiry(self):
        """At expiry: delta = ±1 (ITM) or 0 (OTM), all others = 0."""
        g = bsm_greeks(110, 100, 0, 0.05, 0.20, 'CE')
        assert g['delta'] == 1.0
        assert g['gamma'] == 0.0
        assert g['theta'] == 0.0
        assert g['vega'] == 0.0

        g2 = bsm_greeks(90, 100, 0, 0.05, 0.20, 'PE')
        assert g2['delta'] == -1.0

    def test_nifty_greeks_realistic(self):
        """Nifty ATM: delta ~0.55, gamma small, theta negative."""
        g = bsm_greeks(24000, 24000, 30 / 365, 0.07, 0.14, 'CE')
        assert 0.50 < g['delta'] < 0.65, f"ATM delta: {g['delta']}"
        assert g['gamma'] > 0
        assert g['theta'] < 0
        assert g['vega'] > 0


# ═══════════════════════════════════════════════════════════════════════════
# IMPLIED VOLATILITY — iv.py
# ═══════════════════════════════════════════════════════════════════════════

class TestImpliedVol:
    """IV solver: round-trip accuracy, edge cases, convergence."""

    @pytest.mark.parametrize("S,K,t,r,sigma,otype", [
        (100, 100, 1.0, 0.05, 0.20, 'CE'),     # ATM call
        (100, 100, 1.0, 0.05, 0.20, 'PE'),     # ATM put
        (100, 110, 0.5, 0.07, 0.30, 'CE'),     # OTM call
        (100, 90, 0.25, 0.07, 0.25, 'PE'),     # OTM put
        (100, 80, 1.0, 0.05, 0.15, 'CE'),      # deep ITM call
        (100, 120, 0.5, 0.05, 0.35, 'PE'),     # deep ITM put
        (24000, 24000, 30/365, 0.07, 0.14, 'CE'),  # Nifty ATM
        (24000, 24500, 7/365, 0.07, 0.16, 'PE'),   # Nifty weekly
        (100, 100, 0.01, 0.05, 0.20, 'CE'),    # 3.6 days to expiry
        (100, 100, 1.0, 0.05, 0.05, 'CE'),     # very low vol
        (100, 100, 1.0, 0.05, 0.80, 'CE'),     # very high vol
        (2500, 2500, 90/365, 0.07, 0.25, 'CE'),  # stock option
    ])
    def test_iv_roundtrip(self, S, K, t, r, sigma, otype):
        """Price → IV → should recover original sigma."""
        price = bsm_price(S, K, t, r, sigma, otype)
        recovered = implied_vol(price, S, K, t, r, otype)
        assert abs(recovered - sigma) < 0.001, (
            f"IV roundtrip: σ={sigma}, recovered={recovered:.6f}"
        )

    def test_iv_nan_at_expiry(self):
        assert math.isnan(implied_vol(5.0, 100, 95, 0, 0.05, 'CE'))

    def test_iv_nan_zero_price(self):
        assert math.isnan(implied_vol(0, 100, 100, 1.0, 0.05, 'CE'))

    def test_iv_nan_negative_price(self):
        assert math.isnan(implied_vol(-1, 100, 100, 1.0, 0.05, 'CE'))

    def test_iv_nan_price_exceeds_spot(self):
        """Call price can't exceed spot (arbitrage)."""
        assert math.isnan(implied_vol(110, 100, 100, 1.0, 0.05, 'CE'))

    def test_iv_nan_price_below_intrinsic(self):
        """Price below intrinsic → no valid IV."""
        # ITM call intrinsic = S - K·e^(-rt) ≈ 20 - discount
        result = implied_vol(1.0, 120, 100, 1.0, 0.05, 'CE')
        assert math.isnan(result)

    def test_iv_chain_with_dataframe(self):
        """iv_chain adds IV column to a chain DataFrame."""
        import pandas as pd
        chain = pd.DataFrame({
            'strike': [23500, 24000, 24500],
            'option_type': ['CE', 'CE', 'CE'],
            'ltp': [600, 400, 200],
        })
        result = iv_chain(chain, S=24000, t=30 / 365, r=0.07)
        assert 'iv' in result.columns
        assert not all(np.isnan(result['iv']))

    def test_iv_chain_skips_zero_price(self):
        import pandas as pd
        chain = pd.DataFrame({
            'strike': [25000],
            'option_type': ['CE'],
            'ltp': [0.0],
        })
        result = iv_chain(chain, S=24000, t=7 / 365, r=0.07)
        assert math.isnan(result['iv'].iloc[0])


# ═══════════════════════════════════════════════════════════════════════════
# VOLATILITY ESTIMATORS — volatility.py
# ═══════════════════════════════════════════════════════════════════════════

class TestVolatility:
    """Four estimators against synthetic GBM with known σ."""

    @pytest.fixture
    def gbm_data(self):
        """Generate 2 years of daily GBM data with σ=20%."""
        np.random.seed(42)
        n = 504  # ~2 years trading days
        true_vol = 0.20
        mu = 0.10
        dt = 1 / 252
        prices = [1000.0]
        for _ in range(n):
            z = np.random.randn()
            prices.append(
                prices[-1] * math.exp((mu - 0.5 * true_vol ** 2) * dt +
                                       true_vol * math.sqrt(dt) * z)
            )
        closes = np.array(prices)
        # synthesize realistic OHLC
        daily_range = np.abs(np.random.randn(len(closes))) * true_vol / math.sqrt(252) * closes
        highs = closes + daily_range * 0.6
        lows = closes - daily_range * 0.6
        opens = np.roll(closes, 1) + np.random.randn(len(closes)) * 2
        opens[0] = closes[0]
        return closes, opens, highs, lows, true_vol

    def test_close_to_close_reasonable(self, gbm_data):
        closes, _, _, _, true_vol = gbm_data
        vol = close_to_close_vol(closes, window=252)
        assert 0.10 < vol < 0.35, f"CC vol={vol:.4f}, expected ~{true_vol}"

    def test_parkinson_reasonable(self, gbm_data):
        _, _, highs, lows, true_vol = gbm_data
        vol = parkinson_vol(highs, lows, window=252)
        assert 0.05 < vol < 0.40, f"Parkinson vol={vol:.4f}"

    def test_garman_klass_reasonable(self, gbm_data):
        closes, opens, highs, lows, true_vol = gbm_data
        vol = garman_klass_vol(opens, highs, lows, closes, window=252)
        assert 0.05 < vol < 0.40, f"GK vol={vol:.4f}"

    def test_yang_zhang_reasonable(self, gbm_data):
        closes, opens, highs, lows, true_vol = gbm_data
        vol = yang_zhang_vol(opens, highs, lows, closes, window=252)
        assert 0.05 < vol < 0.40, f"YZ vol={vol:.4f}"

    def test_insufficient_data_returns_nan(self):
        assert math.isnan(close_to_close_vol([100, 101, 102], window=20))
        assert math.isnan(parkinson_vol([100, 101], [99, 100], window=20))

    def test_vol_annualization(self):
        """Annualized vol should be ~√252× raw daily vol."""
        np.random.seed(123)
        prices = np.cumprod(1 + np.random.randn(300) * 0.01) * 100
        raw = close_to_close_vol(prices, window=20, annualize=False)
        ann = close_to_close_vol(prices, window=20, annualize=True)
        assert abs(ann / raw - math.sqrt(252)) < 0.1

    def test_vol_cone_structure(self, gbm_data):
        closes, opens, highs, lows, _ = gbm_data
        cone = vol_cone(closes, highs, lows, opens, windows=(20, 60))
        assert len(cone) >= 1
        for _, row in cone.iterrows():
            assert row['min'] <= row['p25'] <= row['median'] <= row['p75'] <= row['max']
            assert row['min'] >= 0

    def test_vol_cone_current_within_range(self, gbm_data):
        closes, opens, highs, lows, _ = gbm_data
        cone = vol_cone(closes, highs, lows, opens, windows=(20,))
        if len(cone) > 0:
            row = cone.iloc[0]
            assert row['min'] <= row['current'] <= row['max']

    def test_short_window_more_variable(self):
        """Short lookback windows produce noisier estimates (Natenberg Ch.20)."""
        np.random.seed(99)
        prices = np.cumprod(1 + np.random.randn(500) * 0.012) * 100
        vols_5 = [close_to_close_vol(prices[:i + 1], window=5)
                  for i in range(20, len(prices))]
        vols_60 = [close_to_close_vol(prices[:i + 1], window=60)
                   for i in range(80, len(prices))]
        vols_5 = [v for v in vols_5 if not math.isnan(v)]
        vols_60 = [v for v in vols_60 if not math.isnan(v)]
        assert np.std(vols_5) > np.std(vols_60), "Short windows should be noisier"


# ═══════════════════════════════════════════════════════════════════════════
# PAYOFF — payoff.py
# ═══════════════════════════════════════════════════════════════════════════

class TestPayoff:
    """All basic positions and major strategies."""

    # --- single legs ---
    def test_long_call_itm(self):
        assert leg_payoff(110, 100, 'CE', 'BUY', 5) == 5.0

    def test_long_call_atm(self):
        assert leg_payoff(100, 100, 'CE', 'BUY', 5) == -5.0

    def test_long_call_otm(self):
        assert leg_payoff(90, 100, 'CE', 'BUY', 5) == -5.0

    def test_short_call_itm(self):
        assert leg_payoff(110, 100, 'CE', 'SELL', 5) == -5.0

    def test_short_call_otm(self):
        assert leg_payoff(90, 100, 'CE', 'SELL', 5) == 5.0

    def test_long_put_itm(self):
        assert leg_payoff(90, 100, 'PE', 'BUY', 5) == 5.0

    def test_long_put_otm(self):
        assert leg_payoff(110, 100, 'PE', 'BUY', 5) == -5.0

    def test_short_put_itm(self):
        assert leg_payoff(90, 100, 'PE', 'SELL', 5) == -5.0

    def test_short_put_otm(self):
        assert leg_payoff(110, 100, 'PE', 'SELL', 5) == 5.0

    def test_qty_multiplier(self):
        """qty scales the P&L linearly."""
        assert leg_payoff(110, 100, 'CE', 'BUY', 5, qty=65) == 5.0 * 65

    def test_invalid_action(self):
        with pytest.raises(ValueError):
            leg_payoff(100, 100, 'CE', 'HOLD', 5)

    # --- strategies ---

    def test_bull_call_spread(self):
        legs = [
            {'strike': 100, 'option_type': 'CE', 'action': 'BUY', 'premium': 8},
            {'strike': 110, 'option_type': 'CE', 'action': 'SELL', 'premium': 3},
        ]
        s = strategy_summary(legs)
        assert s['net_premium'] == -5.0  # debit spread
        assert abs(s['max_profit'] - 5.0) < 0.2  # (110-100) - 5
        assert abs(s['max_loss'] - (-5.0)) < 0.2
        assert len(s['breakevens']) == 1
        assert abs(s['breakevens'][0] - 105.0) < 0.5

    def test_bear_put_spread(self):
        legs = [
            {'strike': 100, 'option_type': 'PE', 'action': 'BUY', 'premium': 8},
            {'strike': 90, 'option_type': 'PE', 'action': 'SELL', 'premium': 3},
        ]
        s = strategy_summary(legs)
        assert s['net_premium'] == -5.0
        assert abs(s['max_profit'] - 5.0) < 0.2  # (100-90) - 5
        assert abs(s['max_loss'] - (-5.0)) < 0.2

    def test_long_straddle(self):
        """Unlimited profit on both sides, max loss = total debit."""
        legs = [
            {'strike': 100, 'option_type': 'CE', 'action': 'BUY', 'premium': 5},
            {'strike': 100, 'option_type': 'PE', 'action': 'BUY', 'premium': 5},
        ]
        s = strategy_summary(legs)
        assert s['net_premium'] == -10.0
        assert abs(s['max_loss'] - (-10.0)) < 0.2
        assert s['max_profit'] == float('inf')
        assert len(s['breakevens']) == 2

    def test_short_straddle(self):
        """Max profit = credit, unlimited loss (Varsity Ch.11)."""
        legs = [
            {'strike': 100, 'option_type': 'CE', 'action': 'SELL', 'premium': 5},
            {'strike': 100, 'option_type': 'PE', 'action': 'SELL', 'premium': 5},
        ]
        s = strategy_summary(legs)
        assert s['net_premium'] == 10.0
        assert abs(s['max_profit'] - 10.0) < 0.2
        assert s['max_loss'] == float('-inf')

    def test_iron_condor(self):
        """Defined risk: max_profit = credit, max_loss = wing_width - credit."""
        legs = [
            {'strike': 90, 'option_type': 'PE', 'action': 'BUY', 'premium': 1},
            {'strike': 95, 'option_type': 'PE', 'action': 'SELL', 'premium': 3},
            {'strike': 105, 'option_type': 'CE', 'action': 'SELL', 'premium': 3},
            {'strike': 110, 'option_type': 'CE', 'action': 'BUY', 'premium': 1},
        ]
        s = strategy_summary(legs)
        assert s['net_premium'] == 4.0  # (3+3) - (1+1)
        assert abs(s['max_profit'] - 4.0) < 0.2
        assert abs(s['max_loss'] - (-1.0)) < 0.2  # 5 (width) - 4 (credit)
        assert len(s['breakevens']) == 2

    def test_long_butterfly(self):
        """Cohen Ch.5: limited profit, limited loss, two breakevens."""
        legs = [
            {'strike': 95, 'option_type': 'CE', 'action': 'BUY', 'premium': 8},
            {'strike': 100, 'option_type': 'CE', 'action': 'SELL', 'premium': 5, 'qty': 2},
            {'strike': 105, 'option_type': 'CE', 'action': 'BUY', 'premium': 3},
        ]
        s = strategy_summary(legs)
        # net debit = 8 + 3 - 5×2 = 1
        assert s['net_premium'] == -1.0
        assert s['max_profit'] != float('inf')
        assert s['max_loss'] != float('-inf')
        assert len(s['breakevens']) == 2

    def test_collar(self):
        """Cohen Ch.7: protective put + covered call (with underlying)."""
        legs = [
            {'strike': 95, 'option_type': 'PE', 'action': 'BUY', 'premium': 2},
            {'strike': 105, 'option_type': 'CE', 'action': 'SELL', 'premium': 2},
        ]
        s = strategy_summary(legs, underlying_qty=1, underlying_entry=100)
        assert s['net_premium'] == 0.0  # zero-cost collar
        # max profit: 105 - 100 = 5, max loss: 100 - 95 = -5
        assert abs(s['max_profit'] - 5.0) < 0.2
        assert abs(s['max_loss'] - (-5.0)) < 0.2

    def test_nifty_lot_size_scaling(self):
        """With Nifty lot_size=65, all ₹ values scale."""
        legs = [
            {'strike': 24000, 'option_type': 'CE', 'action': 'BUY', 'premium': 200},
        ]
        s = strategy_summary(legs, lot_size=65)
        assert s['max_loss'] == -200.0 * 65  # = -₹13,000


# ═══════════════════════════════════════════════════════════════════════════
# COST MODEL — cost_model.py
# ═══════════════════════════════════════════════════════════════════════════

class TestCostModel:
    """NSE 2026 cost verification (ARCHITECTURE_AUDIT.md numbers)."""

    def test_stt_sell_rate(self):
        """STT on option sell = 0.15% of premium (Apr 2026)."""
        assert STT_OPTION_SELL == 0.0015

    def test_stt_sell_calculation(self):
        costs = trade_cost(200, 65, 'SELL')
        # turnover = 200 × 65 = ₹13,000
        # STT = 13,000 × 0.15% = ₹19.50
        assert costs['stt'] == 19.50

    def test_stt_zero_on_buy(self):
        """No STT on option buy side."""
        costs = trade_cost(200, 65, 'BUY')
        assert costs['stt'] == 0.0

    def test_exchange_charge(self):
        """Exchange = 0.035% of premium."""
        costs = trade_cost(200, 65, 'SELL')
        expected = 13000 * 0.00035  # = ₹4.55
        assert abs(costs['exchange'] - expected) < 0.01

    def test_gst_on_brokerage_and_exchange_only(self):
        """GST = 18% on (brokerage + exchange), NOT on STT."""
        costs = trade_cost(200, 65, 'SELL')
        expected_gst = (costs['brokerage'] + costs['exchange']) * 0.18
        assert abs(costs['gst'] - round(expected_gst, 2)) < 0.02

    def test_stamp_duty_buy_only(self):
        """Stamp duty charged only on buy side."""
        buy = trade_cost(200, 65, 'BUY')
        sell = trade_cost(200, 65, 'SELL')
        assert buy['stamp'] > 0
        assert sell['stamp'] == 0.0

    def test_brokerage_capped_at_20(self):
        """Brokerage = min(₹20, 0.03% of turnover)."""
        # large trade: turnover = 1000 × 100 = ₹100,000
        costs = trade_cost(1000, 100, 'SELL')
        assert costs['brokerage'] == 20.0  # capped

    def test_brokerage_percentage_for_small_trade(self):
        """Small trade uses 0.03% (cheaper than ₹20 flat)."""
        costs = trade_cost(10, 65, 'SELL')
        # turnover = 10 × 65 = ₹650
        # 0.03% of 650 = ₹0.195 < ₹20
        assert costs['brokerage'] < 1.0

    def test_dp_charges_physical_settlement(self):
        """DP charges only for physical delivery at expiry."""
        normal = trade_cost(200, 65, 'SELL', is_expiry_settlement=False)
        delivery = trade_cost(200, 65, 'SELL', is_expiry_settlement=True)
        assert normal['dp'] == 0.0
        assert delivery['dp'] == 15.93

    def test_futures_stt_rate(self):
        """Futures STT = 0.05% sell-side (lower than options)."""
        costs = trade_cost(24000, 65, 'SELL', instrument='future')
        expected_stt = 24000 * 65 * 0.0005
        assert abs(costs['stt'] - expected_stt) < 0.01

    def test_round_trip_iron_condor(self):
        """4-leg entry + 4-leg exit = 8 transactions."""
        legs = [
            {'premium': 30, 'action': 'BUY'},
            {'premium': 70, 'action': 'SELL'},
            {'premium': 70, 'action': 'SELL'},
            {'premium': 30, 'action': 'BUY'},
        ]
        rt = round_trip_cost(legs, lot_size=65)
        assert rt['total'] > 0
        assert rt['entry_cost'] > 0
        assert rt['exit_cost'] > 0
        assert abs(rt['total'] - rt['entry_cost'] - rt['exit_cost']) < 0.01

    def test_cost_breakdown_labels(self):
        bd = cost_breakdown(200, 65, 'SELL')
        labels = [item['label'] for item in bd]
        assert 'STT (Securities Transaction Tax)' in labels
        assert 'TOTAL' in labels
        assert bd[-1]['label'] == 'TOTAL'

    def test_cost_as_percentage_of_edge(self):
        """
        Sinclair Ch.10: costs eat 30-50% of edge.
        For Nifty ATM sell at ₹200, edge ≈ 2.5% VP ≈ ₹5/unit.
        Single-side cost should be < ₹5/unit for the strategy to be viable.
        """
        costs = trade_cost(200, 65, 'SELL')
        cost_per_unit = costs['total'] / 65
        assert cost_per_unit < 5.0, f"Cost per unit = ₹{cost_per_unit:.2f}, too high for edge"


# ═══════════════════════════════════════════════════════════════════════════
# DIVIDENDS — dividends.py
# ═══════════════════════════════════════════════════════════════════════════

class TestDividends:
    """Dividend-adjusted pricing (Natenberg Ch.15, Varsity Ch.21)."""

    def test_forward_no_dividends(self):
        """F = S × e^(rt) when no dividends."""
        f = dividend_adjusted_forward(100, 0.07, 1.0)
        assert abs(f - 100 * math.exp(0.07)) < 0.01

    def test_forward_with_discrete_dividend(self):
        """Forward decreases with dividends."""
        f_no = dividend_adjusted_forward(100, 0.07, 1.0)
        f_div = dividend_adjusted_forward(100, 0.07, 1.0, [(0.5, 5.0)])
        assert f_div < f_no

    def test_forward_with_continuous_yield(self):
        """F = S × e^((r-q)t) with continuous yield."""
        f = dividend_adjusted_forward(100, 0.07, 1.0, q=0.02)
        expected = 100 * math.exp((0.07 - 0.02) * 1.0)
        assert abs(f - expected) < 0.01

    def test_call_cheaper_with_dividend(self):
        """Dividends reduce call value (Natenberg Ch.15)."""
        c_no = bsm_price_with_dividends(100, 100, 1.0, 0.07, 0.20, 'CE')
        c_div = bsm_price_with_dividends(100, 100, 1.0, 0.07, 0.20, 'CE',
                                          dividends=[(0.25, 3.0)])
        assert c_div < c_no

    def test_put_more_expensive_with_dividend(self):
        """Dividends increase put value (Natenberg Ch.15)."""
        p_no = bsm_price_with_dividends(100, 100, 1.0, 0.07, 0.20, 'PE')
        p_div = bsm_price_with_dividends(100, 100, 1.0, 0.07, 0.20, 'PE',
                                          dividends=[(0.25, 3.0)])
        assert p_div > p_no

    def test_past_dividend_no_effect(self):
        """Dividend with ex-date already passed should not affect price."""
        c_no = bsm_price_with_dividends(100, 100, 1.0, 0.07, 0.20, 'CE')
        c_past = bsm_price_with_dividends(100, 100, 1.0, 0.07, 0.20, 'CE',
                                           dividends=[(-0.1, 5.0)])
        assert abs(c_past - c_no) < 0.001

    def test_dividend_after_expiry_no_effect(self):
        """Dividend with ex-date after expiry should not affect price."""
        c_no = bsm_price_with_dividends(100, 100, 0.5, 0.07, 0.20, 'CE')
        c_post = bsm_price_with_dividends(100, 100, 0.5, 0.07, 0.20, 'CE',
                                           dividends=[(0.6, 5.0)])
        assert abs(c_post - c_no) < 0.001

    def test_multiple_dividends(self):
        """Multiple dividends before expiry all reduce call price."""
        c_no = bsm_price_with_dividends(100, 100, 1.0, 0.07, 0.20, 'CE')
        c_one = bsm_price_with_dividends(100, 100, 1.0, 0.07, 0.20, 'CE',
                                          dividends=[(0.25, 3.0)])
        c_two = bsm_price_with_dividends(100, 100, 1.0, 0.07, 0.20, 'CE',
                                          dividends=[(0.25, 3.0), (0.75, 3.0)])
        assert c_no > c_one > c_two

    def test_put_call_parity_with_dividends(self):
        """Parity must hold even with dividends (adjusted S)."""
        divs = [(0.25, 3.0), (0.75, 2.0)]
        c = bsm_price_with_dividends(100, 100, 1.0, 0.07, 0.20, 'CE', dividends=divs)
        p = bsm_price_with_dividends(100, 100, 1.0, 0.07, 0.20, 'PE', dividends=divs)
        # with dividends, parity uses S_adj
        pv_divs = sum(d * math.exp(-0.07 * t) for t, d in divs)
        S_adj = 100 - pv_divs
        parity = (c - p) - (S_adj - 100 * math.exp(-0.07))
        assert abs(parity) < 0.001, f"Parity violation with dividends: {parity}"

    def test_greeks_with_dividends(self):
        """Greeks should still be well-behaved with dividends."""
        g = bsm_greeks_with_dividends(
            2500, 2500, 90 / 365, 0.07, 0.25, 'CE',
            dividends=[(30 / 365, 15)]
        )
        assert 0 < g['delta'] < 1
        assert g['gamma'] > 0
        assert g['theta'] < 0
        assert g['vega'] > 0

    def test_nse_stock_option_with_dividend(self):
        """Realistic: Reliance at ₹2500, ₹10 quarterly dividend."""
        c_no = bsm_price_with_dividends(2500, 2500, 90 / 365, 0.07, 0.25, 'CE')
        c_div = bsm_price_with_dividends(2500, 2500, 90 / 365, 0.07, 0.25, 'CE',
                                          dividends=[(45 / 365, 10)])
        # dividend of ₹10 on ₹2500 stock → small effect (~₹5-10 on premium)
        diff = c_no - c_div
        assert 3 < diff < 15, f"Dividend effect: ₹{diff:.2f}"


# ═══════════════════════════════════════════════════════════════════════════
# CROSS-MODULE INTEGRATION
# ═══════════════════════════════════════════════════════════════════════════

class TestIntegration:
    """Tests that cross multiple modules together."""

    def test_price_then_iv_then_greeks(self):
        """Full pipeline: price → IV → greeks with recovered IV match originals."""
        S, K, t, r, sigma = 24000, 24000, 30 / 365, 0.07, 0.14
        price = bsm_price(S, K, t, r, sigma, 'CE')
        iv = implied_vol(price, S, K, t, r, 'CE')
        g_original = bsm_greeks(S, K, t, r, sigma, 'CE')
        g_recovered = bsm_greeks(S, K, t, r, iv, 'CE')
        assert abs(g_original['delta'] - g_recovered['delta']) < 0.001
        assert abs(g_original['vega'] - g_recovered['vega']) < 0.01

    def test_payoff_plus_costs_net_edge(self):
        """Strategy profit minus costs = net edge. Must be positive for viable trade."""
        # short straddle at ATM: credit = call + put premium
        S, K, t, r, sigma = 24000, 24000, 30 / 365, 0.07, 0.14
        c = bsm_price(S, K, t, r, sigma, 'CE')
        p = bsm_price(S, K, t, r, sigma, 'PE')
        total_credit = c + p

        # round-trip costs
        legs = [
            {'premium': c, 'action': 'SELL'},
            {'premium': p, 'action': 'SELL'},
        ]
        rt = round_trip_cost(legs, lot_size=65)

        # credit per unit vs cost per unit
        cost_per_unit = rt['total'] / 65
        assert cost_per_unit < total_credit, (
            f"Cost ₹{cost_per_unit:.2f}/unit > credit ₹{total_credit:.2f}/unit"
        )

    def test_gamma_theta_tradeoff(self):
        """
        Natenberg Ch.9: gamma and theta are always opposite.
        Long gamma = positive gamma + negative theta.
        """
        g = bsm_greeks(100, 100, 0.5, 0.05, 0.20, 'CE')
        assert g['gamma'] > 0
        assert g['theta'] < 0
        # gamma contribution to theta: -0.5 × gamma × S² × σ²
        # this is the dominant term; the r×K×e^(-rt)×N(d2) term adds ~30-60%
        gamma_theta = -0.5 * g['gamma'] * 100 ** 2 * 0.20 ** 2
        annual_theta = g['theta'] * 365
        # gamma term should be same sign and within 2× of total theta
        assert gamma_theta < 0
        assert abs(gamma_theta) < abs(annual_theta) * 2

    def test_straddle_delta_near_zero(self):
        """ATM straddle: net delta ≈ 0 (delta-neutral)."""
        g_c = bsm_greeks(24000, 24000, 30 / 365, 0.07, 0.14, 'CE')
        g_p = bsm_greeks(24000, 24000, 30 / 365, 0.07, 0.14, 'PE')
        net_delta = g_c['delta'] + g_p['delta']
        # not exactly 0 because forward ≠ spot (r > 0)
        assert abs(net_delta) < 0.15

    def test_vol_estimator_feeds_bsm(self):
        """Realized vol from estimator → BSM → price should be reasonable."""
        np.random.seed(42)
        prices = np.cumprod(1 + np.random.randn(300) * 0.01) * 24000
        rv = close_to_close_vol(prices, window=20)
        if not math.isnan(rv):
            c = bsm_price(24000, 24000, 30 / 365, 0.07, rv, 'CE')
            assert c > 0
            assert c < 24000
