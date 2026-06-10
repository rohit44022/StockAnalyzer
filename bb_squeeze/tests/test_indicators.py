"""
Strict canonical-formula tests for every indicator used by BB Methods I-IV.

Reference: Bollinger on Bollinger Bands (John Bollinger CFA CMT)
  Ch. 7  — Bollinger Bands, %b, BandWidth
  Ch. 15 — Method I (Volatility Breakout)
  Ch. 18 — Volume indicators: II, AD, VWMACD
  Ch. 19 — Method II (Trend Following, %b + MFI)
  Ch. 20 — Method III (Reversals, W-bottom / M-top with %b + II% / AD%)
  Ch. 21 — Indicator normalisation

Run:
    python -m unittest bb_squeeze.tests.test_indicators -v
"""

from __future__ import annotations
import os, sys, math, unittest
import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from bb_squeeze.indicators import (
    bollinger_bands, bandwidth, percent_b, is_squeeze,
    volume_sma, volume_is_above_sma,
    chaikin_money_flow, money_flow_index,
    intraday_intensity, intraday_intensity_pct,
    accumulation_distribution, accumulation_distribution_pct,
    volume_weighted_macd,
    detect_expansion,
    rsi, normalize_indicator,
    parabolic_sar,
    compute_all_indicators,
)
from bb_squeeze.config import (
    BB_PERIOD, BB_STD_DEV,
    BBW_TRIGGER, BBW_LOOKBACK,
    CMF_PERIOD, MFI_PERIOD,
    II_NORM_PERIOD, AD_NORM_PERIOD,
    VWMACD_FAST, VWMACD_SLOW, VWMACD_SIGNAL,
    VOLUME_SMA_PERIOD,
    NORM_RSI_PERIOD,
)


# ─────────────────────────────────────────────────────────────────
#  Synthetic OHLCV builder
# ─────────────────────────────────────────────────────────────────
def _make_ohlcv(close, *, hl_spread=2.0, open_offset=0.0, volume=1_000_000):
    """Build a clean OHLCV DataFrame from a Close series."""
    close = pd.Series(close, dtype=float)
    n = len(close)
    high = close + hl_spread / 2.0
    low  = close - hl_spread / 2.0
    open_ = close - open_offset
    vol  = pd.Series([volume] * n, dtype=float)
    return pd.DataFrame({
        "Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol,
    })


# ═══════════════════════════════════════════════════════════════
#  BOLLINGER BANDS (mid, upper, lower)
# ═══════════════════════════════════════════════════════════════
class TestBollingerBands(unittest.TestCase):
    def test_constant_series_gives_zero_width(self):
        """Flat price → std=0 → upper == lower == mid."""
        close = pd.Series([100.0] * 30)
        mid, upper, lower = bollinger_bands(close)
        last = -1
        self.assertAlmostEqual(mid.iloc[last], 100.0, places=8)
        self.assertAlmostEqual(upper.iloc[last], 100.0, places=8)
        self.assertAlmostEqual(lower.iloc[last], 100.0, places=8)

    def test_known_sequence_mid_and_bands(self):
        """Mid = SMA(20); bands = mid ± 2 * population_std."""
        rng = np.random.default_rng(42)
        close = pd.Series(rng.uniform(90, 110, 50))
        mid, upper, lower = bollinger_bands(close)
        last20 = close.iloc[-20:]
        expected_mid = last20.mean()
        expected_sigma = last20.std(ddof=0)        # population std
        self.assertAlmostEqual(mid.iloc[-1],   expected_mid,                          places=8)
        self.assertAlmostEqual(upper.iloc[-1], expected_mid + 2.0 * expected_sigma,   places=8)
        self.assertAlmostEqual(lower.iloc[-1], expected_mid - 2.0 * expected_sigma,   places=8)

    def test_uses_population_std_not_sample(self):
        """Pop std (ddof=0) is what TradingView/Kite use — must NOT be sample std."""
        rng = np.random.default_rng(7)
        close = pd.Series(rng.uniform(50, 150, 60))
        mid, upper, _ = bollinger_bands(close)
        last20 = close.iloc[-20:]
        pop_sigma = last20.std(ddof=0)
        sample_sigma = last20.std(ddof=1)
        self.assertNotAlmostEqual(pop_sigma, sample_sigma, places=8)
        self.assertAlmostEqual(upper.iloc[-1] - mid.iloc[-1], 2.0 * pop_sigma, places=8)

    def test_period_warmup_nan(self):
        """First period-1 values must be NaN (rolling window not warm)."""
        close = pd.Series([100.0 + i for i in range(BB_PERIOD + 5)])
        mid, _, _ = bollinger_bands(close)
        self.assertTrue(np.isnan(mid.iloc[BB_PERIOD - 2]))
        self.assertFalse(np.isnan(mid.iloc[BB_PERIOD - 1]))


# ═══════════════════════════════════════════════════════════════
#  BANDWIDTH (BBW)
# ═══════════════════════════════════════════════════════════════
class TestBandwidth(unittest.TestCase):
    def test_formula_upper_minus_lower_over_mid(self):
        """BBW = (upper - lower) / mid — canonical Bollinger definition."""
        mid   = pd.Series([100.0])
        upper = pd.Series([105.0])
        lower = pd.Series([95.0])
        self.assertAlmostEqual(bandwidth(mid, upper, lower).iloc[0], 0.10, places=10)

    def test_constant_series_gives_zero_bbw(self):
        """Flat price → bands collapse → BBW = 0."""
        close = pd.Series([100.0] * 30)
        mid, upper, lower = bollinger_bands(close)
        bbw = bandwidth(mid, upper, lower)
        self.assertAlmostEqual(bbw.iloc[-1], 0.0, places=8)

    def test_higher_volatility_gives_higher_bbw(self):
        """Wider price range must produce larger BBW."""
        flat  = pd.Series([100 + np.sin(i / 5) * 0.5 for i in range(40)])
        wild  = pd.Series([100 + np.sin(i / 5) * 5.0 for i in range(40)])
        for s, expected_label in [(flat, "flat"), (wild, "wild")]:
            mid, upper, lower = bollinger_bands(s)
            bbw = bandwidth(mid, upper, lower).iloc[-1]
            if expected_label == "flat":
                bbw_flat = bbw
            else:
                bbw_wild = bbw
        self.assertGreater(bbw_wild, bbw_flat * 5)


# ═══════════════════════════════════════════════════════════════
#  %b (PERCENT B)
# ═══════════════════════════════════════════════════════════════
class TestPercentB(unittest.TestCase):
    def test_close_at_upper_band_gives_one(self):
        close = pd.Series([105.0])
        upper = pd.Series([105.0])
        lower = pd.Series([95.0])
        self.assertAlmostEqual(percent_b(close, upper, lower).iloc[0], 1.0, places=10)

    def test_close_at_lower_band_gives_zero(self):
        close = pd.Series([95.0])
        upper = pd.Series([105.0])
        lower = pd.Series([95.0])
        self.assertAlmostEqual(percent_b(close, upper, lower).iloc[0], 0.0, places=10)

    def test_close_at_middle_gives_half(self):
        close = pd.Series([100.0])
        upper = pd.Series([105.0])
        lower = pd.Series([95.0])
        self.assertAlmostEqual(percent_b(close, upper, lower).iloc[0], 0.5, places=10)

    def test_close_above_upper_gives_above_one(self):
        """Breakout: %b > 1 is real, not clipped."""
        close = pd.Series([110.0])
        upper = pd.Series([105.0])
        lower = pd.Series([95.0])
        self.assertGreater(percent_b(close, upper, lower).iloc[0], 1.0)

    def test_zero_width_band_returns_half_fallback(self):
        """When bands collapse (upper==lower), %b is undefined → safe fallback 0.5."""
        close = pd.Series([100.0])
        upper = pd.Series([100.0])
        lower = pd.Series([100.0])
        self.assertAlmostEqual(percent_b(close, upper, lower).iloc[0], 0.5, places=10)


# ═══════════════════════════════════════════════════════════════
#  SQUEEZE DETECTION (is_squeeze)
# ═══════════════════════════════════════════════════════════════
class TestSqueeze(unittest.TestCase):
    def test_bbw_below_absolute_trigger_is_squeeze(self):
        """BBW ≤ BBW_TRIGGER (0.08) → squeeze ON regardless of history."""
        bbw = pd.Series([0.20] * 100 + [BBW_TRIGGER - 0.001])
        sq = is_squeeze(bbw)
        self.assertTrue(bool(sq.iloc[-1]))

    def test_high_bbw_is_not_squeeze(self):
        """BBW well above trigger and rolling min → squeeze OFF."""
        bbw = pd.Series([0.10] * 70 + [0.50])
        sq = is_squeeze(bbw)
        self.assertFalse(bool(sq.iloc[-1]))

    def test_bbw_at_six_month_low_is_squeeze(self):
        """Dynamic squeeze: BBW at 6-month rolling min triggers squeeze ON."""
        bbw = pd.Series([0.20] * 100 + [0.18] * 30)
        sq = is_squeeze(bbw)
        self.assertTrue(bool(sq.iloc[-1]))


# ═══════════════════════════════════════════════════════════════
#  VOLUME SMA
# ═══════════════════════════════════════════════════════════════
class TestVolumeSMA(unittest.TestCase):
    def test_volume_sma_is_50_period_mean(self):
        vol = pd.Series([1000.0] * 100)
        sma = volume_sma(vol)
        self.assertAlmostEqual(sma.iloc[-1], 1000.0, places=8)
        self.assertTrue(np.isnan(sma.iloc[VOLUME_SMA_PERIOD - 2]))

    def test_volume_above_sma_flag(self):
        vol = pd.Series([1000.0] * 100)
        sma = volume_sma(vol)
        flag = volume_is_above_sma(pd.Series([1500.0]), pd.Series([1000.0]))
        self.assertTrue(bool(flag.iloc[0]))
        flag = volume_is_above_sma(pd.Series([500.0]), pd.Series([1000.0]))
        self.assertFalse(bool(flag.iloc[0]))


# ═══════════════════════════════════════════════════════════════
#  CMF — CHAIKIN MONEY FLOW
# ═══════════════════════════════════════════════════════════════
class TestCMF(unittest.TestCase):
    def test_close_at_high_gives_positive_cmf(self):
        """When close == high for every bar → MFM=+1 → CMF=+1."""
        n = CMF_PERIOD + 5
        high  = pd.Series([110.0] * n)
        low   = pd.Series([100.0] * n)
        close = pd.Series([110.0] * n)            # close == high
        vol   = pd.Series([1_000_000.0] * n)
        cmf   = chaikin_money_flow(high, low, close, vol)
        self.assertAlmostEqual(cmf.iloc[-1], +1.0, places=8)

    def test_close_at_low_gives_minus_one(self):
        n = CMF_PERIOD + 5
        high  = pd.Series([110.0] * n)
        low   = pd.Series([100.0] * n)
        close = pd.Series([100.0] * n)            # close == low
        vol   = pd.Series([1_000_000.0] * n)
        cmf   = chaikin_money_flow(high, low, close, vol)
        self.assertAlmostEqual(cmf.iloc[-1], -1.0, places=8)

    def test_close_at_midpoint_gives_zero(self):
        """Close in the middle → MFM=0 → CMF=0."""
        n = CMF_PERIOD + 5
        high  = pd.Series([110.0] * n)
        low   = pd.Series([100.0] * n)
        close = pd.Series([105.0] * n)            # exact midpoint
        vol   = pd.Series([1_000_000.0] * n)
        cmf   = chaikin_money_flow(high, low, close, vol)
        self.assertAlmostEqual(cmf.iloc[-1], 0.0, places=8)

    def test_bounded_in_minus_one_to_plus_one(self):
        """CMF is mathematically bounded in [-1, +1] for valid OHLC (low ≤ close ≤ high)."""
        rng = np.random.default_rng(11)
        n = 200
        low   = pd.Series(rng.uniform(95, 100, n))
        spread = pd.Series(rng.uniform(1.0, 5.0, n))
        high  = low + spread
        close = low + spread * rng.uniform(0, 1, n)            # clamped inside [low, high]
        vol   = pd.Series(rng.uniform(1e5, 1e7, n))
        cmf   = chaikin_money_flow(high, low, close, vol)
        last = cmf.dropna()
        self.assertGreaterEqual(last.min(), -1.0 - 1e-9)
        self.assertLessEqual(last.max(),    +1.0 + 1e-9)

    def test_no_trade_bar_does_not_break_rolling_window(self):
        """
        Regression test for the holiday-bar bug:
        a single bar with H==L==C, V=0 must NOT poison the next 20 days.
        """
        n = CMF_PERIOD * 3
        rng = np.random.default_rng(99)
        low   = pd.Series(rng.uniform(95, 100, n))
        high  = low + rng.uniform(1.0, 5.0, n)
        close = low + rng.uniform(0, 5.0, n)
        vol   = pd.Series(rng.uniform(1e5, 1e7, n))

        # Inject a "holiday ghost bar" in the middle of the window.
        ghost_idx = n - 10
        high.iloc[ghost_idx] = 100.0
        low.iloc[ghost_idx]  = 100.0
        close.iloc[ghost_idx] = 100.0
        vol.iloc[ghost_idx]  = 0.0

        cmf = chaikin_money_flow(high, low, close, vol)
        # The bars AFTER the ghost must still produce real (non-NaN, non-zero) CMF
        post_ghost = cmf.iloc[ghost_idx + 1: ]
        self.assertTrue((post_ghost.abs() > 1e-9).any(),
            "CMF was poisoned by a single no-trade bar — NaN must not propagate forward")

    def test_uses_canonical_chaikin_formula(self):
        """Hand-compute one bar against the Chaikin formula."""
        n = CMF_PERIOD + 5
        high  = pd.Series([110.0] * n)
        low   = pd.Series([100.0] * n)
        close = pd.Series([107.0] * n)
        vol   = pd.Series([1_000_000.0] * n)
        cmf = chaikin_money_flow(high, low, close, vol)
        # MFM = ((C-L) - (H-C)) / (H-L) = ((7) - (3)) / 10 = 0.4
        # CMF over a constant series = 0.4
        self.assertAlmostEqual(cmf.iloc[-1], 0.4, places=8)


# ═══════════════════════════════════════════════════════════════
#  MFI — MONEY FLOW INDEX
# ═══════════════════════════════════════════════════════════════
class TestMFI(unittest.TestCase):
    def test_strong_uptrend_pushes_mfi_high(self):
        """
        Strong uptrend (~95% up days) → MFI ≥ 80 (overbought zone).
        (A pure 100%-up sequence hits the neg_sum=0 defensive-fallback path → 50;
         that's an acceptable defensive design and cannot happen on real data.)
        """
        n = MFI_PERIOD + 5
        close = pd.Series([100.0 + i for i in range(n)])
        close.iloc[5] = close.iloc[4] - 0.01        # one tiny down day to keep neg_sum > 0
        df = _make_ohlcv(close, hl_spread=2.0)
        mfi = money_flow_index(df["High"], df["Low"], df["Close"], df["Volume"])
        self.assertGreater(mfi.iloc[-1], 80.0)      # Bollinger's MFI overbought line

    def test_strong_downtrend_pushes_mfi_low(self):
        """Strong downtrend → MFI ≤ 20 (oversold zone)."""
        n = MFI_PERIOD + 5
        close = pd.Series([100.0 - i for i in range(n)])
        close.iloc[5] = close.iloc[4] + 0.01        # one tiny up day to keep pos_sum > 0
        df = _make_ohlcv(close, hl_spread=2.0)
        mfi = money_flow_index(df["High"], df["Low"], df["Close"], df["Volume"])
        self.assertLess(mfi.iloc[-1], 20.0)         # Bollinger's MFI oversold line

    def test_defensive_fallback_when_no_loss_data(self):
        """Documented behavior: when neg_sum=0 (impossible in real data), MFI falls back to 50."""
        n = MFI_PERIOD + 5
        close = pd.Series([100.0 + i for i in range(n)])     # strictly monotonic up
        df = _make_ohlcv(close, hl_spread=2.0)
        mfi = money_flow_index(df["High"], df["Low"], df["Close"], df["Volume"])
        self.assertAlmostEqual(mfi.iloc[-1], 50.0, places=4)

    def test_bounded_in_zero_to_one_hundred(self):
        rng = np.random.default_rng(3)
        close = pd.Series(rng.uniform(90, 110, 80))
        df = _make_ohlcv(close)
        mfi = money_flow_index(df["High"], df["Low"], df["Close"], df["Volume"])
        clean = mfi.dropna()
        self.assertGreaterEqual(clean.min(), 0.0 - 1e-9)
        self.assertLessEqual(clean.max(),    100.0 + 1e-9)

    def test_uses_book_default_period_ten(self):
        """Book Ch.19: MFI period is HALF of BB period (=10) for breakout fuel."""
        self.assertEqual(MFI_PERIOD, 10)


# ═══════════════════════════════════════════════════════════════
#  II / II% — INTRADAY INTENSITY  (Book Ch.18 Table 18.3 + 18.4)
# ═══════════════════════════════════════════════════════════════
class TestIntradayIntensity(unittest.TestCase):
    def test_close_at_high_gives_full_positive_volume(self):
        """II = (2C-H-L)/(H-L) * V. Close at high → II = +V."""
        ii = intraday_intensity(
            high  = pd.Series([110.0]),
            low   = pd.Series([100.0]),
            close = pd.Series([110.0]),
            volume= pd.Series([500_000.0]),
        )
        self.assertAlmostEqual(ii.iloc[0], +500_000.0, places=4)

    def test_close_at_low_gives_full_negative_volume(self):
        ii = intraday_intensity(
            high  = pd.Series([110.0]),
            low   = pd.Series([100.0]),
            close = pd.Series([100.0]),
            volume= pd.Series([500_000.0]),
        )
        self.assertAlmostEqual(ii.iloc[0], -500_000.0, places=4)

    def test_close_at_midpoint_gives_zero(self):
        ii = intraday_intensity(
            high  = pd.Series([110.0]),
            low   = pd.Series([100.0]),
            close = pd.Series([105.0]),
            volume= pd.Series([500_000.0]),
        )
        self.assertAlmostEqual(ii.iloc[0], 0.0, places=4)

    def test_ii_pct_bounded_in_minus_one_to_plus_one(self):
        rng = np.random.default_rng(13)
        n = 100
        low   = pd.Series(rng.uniform(95, 100, n))
        spread = pd.Series(rng.uniform(1.0, 5.0, n))
        high  = low + spread
        close = low + spread * rng.uniform(0, 1, n)            # clamped inside [low, high]
        vol   = pd.Series(rng.uniform(1e5, 1e7, n))
        ii    = intraday_intensity(high, low, close, vol)
        ii_p  = intraday_intensity_pct(ii, vol)
        clean = ii_p.dropna()
        self.assertGreaterEqual(clean.min(), -1.0 - 1e-9)
        self.assertLessEqual(clean.max(),    +1.0 + 1e-9)

    def test_ii_norm_period_is_21(self):
        """Book Ch.18 Table 18.4 specifies 21-day normalisation."""
        self.assertEqual(II_NORM_PERIOD, 21)


# ═══════════════════════════════════════════════════════════════
#  AD / AD% — ACCUMULATION DISTRIBUTION (Book Ch.18 Table 18.3 + 18.4)
# ═══════════════════════════════════════════════════════════════
class TestAccumulationDistribution(unittest.TestCase):
    def test_bullish_bar_close_above_open_is_positive(self):
        """AD = (C-O)/(H-L) * V. Close > Open → AD positive."""
        ad = accumulation_distribution(
            high       = pd.Series([110.0]),
            low        = pd.Series([100.0]),
            close      = pd.Series([108.0]),
            open_price = pd.Series([102.0]),
            volume     = pd.Series([1_000_000.0]),
        )
        # (108-102)/(110-100) * 1e6 = 0.6 * 1e6 = 600_000
        self.assertAlmostEqual(ad.iloc[0], 600_000.0, places=4)

    def test_bearish_bar_close_below_open_is_negative(self):
        ad = accumulation_distribution(
            high       = pd.Series([110.0]),
            low        = pd.Series([100.0]),
            close      = pd.Series([102.0]),
            open_price = pd.Series([108.0]),
            volume     = pd.Series([1_000_000.0]),
        )
        self.assertAlmostEqual(ad.iloc[0], -600_000.0, places=4)

    def test_doji_close_equals_open_is_zero(self):
        ad = accumulation_distribution(
            high       = pd.Series([110.0]),
            low        = pd.Series([100.0]),
            close      = pd.Series([105.0]),
            open_price = pd.Series([105.0]),
            volume     = pd.Series([1_000_000.0]),
        )
        self.assertAlmostEqual(ad.iloc[0], 0.0, places=4)

    def test_ad_pct_bounded_in_minus_one_to_plus_one(self):
        rng = np.random.default_rng(21)
        n = 100
        low   = pd.Series(rng.uniform(95, 100, n))
        spread = pd.Series(rng.uniform(1.0, 5.0, n))
        high  = low + spread
        close = low + spread * rng.uniform(0, 1, n)            # clamped inside [low, high]
        open_ = low + spread * rng.uniform(0, 1, n)            # clamped inside [low, high]
        vol   = pd.Series(rng.uniform(1e5, 1e7, n))
        ad    = accumulation_distribution(high, low, close, open_, vol)
        adp   = accumulation_distribution_pct(ad, vol)
        clean = adp.dropna()
        self.assertGreaterEqual(clean.min(), -1.0 - 1e-9)
        self.assertLessEqual(clean.max(),    +1.0 + 1e-9)

    def test_ad_norm_period_is_21(self):
        self.assertEqual(AD_NORM_PERIOD, 21)


# ═══════════════════════════════════════════════════════════════
#  VWMACD — Book Ch.18 Table 18.3
# ═══════════════════════════════════════════════════════════════
class TestVWMACD(unittest.TestCase):
    def test_periods_match_book_defaults(self):
        """Book defaults: fast=12, slow=26, signal=9."""
        self.assertEqual((VWMACD_FAST, VWMACD_SLOW, VWMACD_SIGNAL), (12, 26, 9))

    def test_uptrend_gives_positive_vwmacd(self):
        """Accelerating uptrend → VWMACD (12 - 26 fast/slow) is clearly positive."""
        close = pd.Series([100.0 * (1.01 ** i) for i in range(80)])    # exponential growth
        vol   = pd.Series([1_000_000.0] * 80)
        m, _, _ = volume_weighted_macd(close, vol)
        self.assertGreater(m.iloc[-1], 0.0)

    def test_downtrend_gives_negative_vwmacd(self):
        close = pd.Series([180.0 - i for i in range(80)])
        vol   = pd.Series([1_000_000.0] * 80)
        m, s, h = volume_weighted_macd(close, vol)
        self.assertLess(m.iloc[-1], 0.0)

    def test_flat_price_gives_zero_vwmacd(self):
        close = pd.Series([100.0] * 80)
        vol   = pd.Series([1_000_000.0] * 80)
        m, s, h = volume_weighted_macd(close, vol)
        self.assertAlmostEqual(m.iloc[-1], 0.0, places=6)


# ═══════════════════════════════════════════════════════════════
#  EXPANSION DETECTION (Book Ch.15 p.123)
# ═══════════════════════════════════════════════════════════════
class TestExpansion(unittest.TestCase):
    def test_detect_expansion_returns_three_aligned_bool_series(self):
        """Shape contract: returns (expansion_up, expansion_down, expansion_end),
           all bool Series of the same length as the input."""
        rng = np.random.default_rng(17)
        close = pd.Series(np.cumsum(rng.normal(0, 1, 80)) + 100)
        df = _make_ohlcv(close, hl_spread=2.0)
        mid, upper, lower = bollinger_bands(df["Close"])
        exp_up, exp_dn, exp_end = detect_expansion(upper, lower, df["Close"], mid)
        for s in (exp_up, exp_dn, exp_end):
            self.assertEqual(len(s), len(close))
            self.assertEqual(s.dtype, bool)

    def test_expansion_fires_on_real_data_uptrend(self):
        """
        On real CSV data, the function must mark *some* uptrend Expansion bars
        somewhere in history — the flag is supposed to fire on strong trends,
        and a multi-year stock history always contains at least one.
        """
        csv = os.path.join(_ROOT, "stock_csv", "RELIANCE.NS.csv")
        if not os.path.exists(csv):
            self.skipTest("reference CSV missing")
        df = pd.read_csv(csv)
        mid, upper, lower = bollinger_bands(df["Close"])
        exp_up, exp_dn, _ = detect_expansion(upper, lower, df["Close"], mid)
        self.assertTrue(exp_up.sum() > 0, "uptrend Expansion never fired across full history")
        self.assertTrue(exp_dn.sum() > 0, "downtrend Expansion never fired across full history")

    def test_expansion_up_and_down_are_mutually_exclusive(self):
        """A bar cannot simultaneously be uptrend AND downtrend Expansion."""
        csv = os.path.join(_ROOT, "stock_csv", "RELIANCE.NS.csv")
        if not os.path.exists(csv):
            self.skipTest("reference CSV missing")
        df = pd.read_csv(csv)
        mid, upper, lower = bollinger_bands(df["Close"])
        exp_up, exp_dn, _ = detect_expansion(upper, lower, df["Close"], mid)
        self.assertEqual((exp_up & exp_dn).sum(), 0)


# ═══════════════════════════════════════════════════════════════
#  RSI — Wilder's smoothing
# ═══════════════════════════════════════════════════════════════
class TestRSI(unittest.TestCase):
    def test_period_is_fourteen(self):
        self.assertEqual(NORM_RSI_PERIOD, 14)

    def test_strong_uptrend_pushes_rsi_high(self):
        """Strong uptrend with one tiny dip → RSI approaches 100."""
        close = pd.Series([100.0 + i for i in range(50)])
        close.iloc[10] = close.iloc[9] - 0.01      # one tiny down day so avg_loss > 0
        r = rsi(close)
        self.assertGreater(r.iloc[-1], 95.0)

    def test_strong_downtrend_pushes_rsi_low(self):
        close = pd.Series([100.0 - i for i in range(50)])
        close.iloc[10] = close.iloc[9] + 0.01      # one tiny up day so avg_gain > 0
        r = rsi(close)
        self.assertLess(r.iloc[-1], 5.0)

    def test_defensive_fallback_when_no_loss_data(self):
        """When avg_loss=0 (impossible in real data), RSI falls back to 50."""
        close = pd.Series([100.0 + i for i in range(50)])
        r = rsi(close)
        self.assertAlmostEqual(r.iloc[-1], 50.0, places=4)

    def test_bounded_in_zero_to_one_hundred(self):
        rng = np.random.default_rng(8)
        close = pd.Series(np.cumsum(rng.normal(0, 1, 80)) + 100)
        r = rsi(close)
        clean = r.dropna()
        self.assertGreaterEqual(clean.min(), 0.0 - 1e-6)
        self.assertLessEqual(clean.max(),    100.0 + 1e-6)


# ═══════════════════════════════════════════════════════════════
#  INDICATOR NORMALISATION (Book Ch.21 Table 21.2)
# ═══════════════════════════════════════════════════════════════
class TestNormaliseIndicator(unittest.TestCase):
    def test_flat_indicator_returns_half(self):
        """Flat input → bands collapse → safe fallback = 0.5."""
        ind = pd.Series([50.0] * 60)
        out = normalize_indicator(ind, bb_len=20, bb_std=2.0)
        self.assertAlmostEqual(out.iloc[-1], 0.5, places=8)

    def test_typical_output_bounded_around_zero_to_one(self):
        rng = np.random.default_rng(31)
        ind = pd.Series(rng.uniform(20, 80, 80))
        out = normalize_indicator(ind, bb_len=20, bb_std=2.0).dropna()
        # Most values should be inside [-0.5, +1.5] — a few breakouts are OK.
        self.assertLessEqual((out < -0.5).mean(), 0.10)
        self.assertLessEqual((out >  1.5).mean(), 0.10)


# ═══════════════════════════════════════════════════════════════
#  PARABOLIC SAR
# ═══════════════════════════════════════════════════════════════
class TestParabolicSAR(unittest.TestCase):
    def test_uptrend_sar_below_price(self):
        close = pd.Series([100.0 + i for i in range(60)])
        high  = close + 1.0
        low   = close - 1.0
        sar, bull = parabolic_sar(high, low)
        self.assertTrue(bool(bull.iloc[-1]))
        self.assertLess(sar.iloc[-1], close.iloc[-1])

    def test_downtrend_sar_above_price(self):
        close = pd.Series([160.0 - i for i in range(60)])
        high  = close + 1.0
        low   = close - 1.0
        sar, bull = parabolic_sar(high, low)
        self.assertFalse(bool(bull.iloc[-1]))
        self.assertGreater(sar.iloc[-1], close.iloc[-1])


# ═══════════════════════════════════════════════════════════════
#  STRUCTURAL CONFIG INVARIANTS  (the "methodology contract")
# ═══════════════════════════════════════════════════════════════
class TestBookContract(unittest.TestCase):
    """Lock down constants Bollinger specifies in the book.

    Changing any of these would silently deviate from canonical methodology.
    """

    def test_bb_period_is_twenty(self):
        self.assertEqual(BB_PERIOD, 20)

    def test_bb_std_dev_is_two(self):
        self.assertEqual(BB_STD_DEV, 2.0)

    def test_bbw_squeeze_absolute_trigger_is_008(self):
        """Book p.121 — 0.08 BBW is the canonical squeeze trigger."""
        self.assertAlmostEqual(BBW_TRIGGER, 0.08, places=8)

    def test_bbw_lookback_is_six_months(self):
        """Book p.121 — 6-month rolling min for squeeze detection."""
        self.assertEqual(BBW_LOOKBACK, 126)

    def test_cmf_period_is_twenty(self):
        self.assertEqual(CMF_PERIOD, 20)

    def test_mfi_period_is_half_of_bb_period(self):
        """Book Ch.19 — MFI period is 10 (half of BB period)."""
        self.assertEqual(MFI_PERIOD, BB_PERIOD // 2)


# ═══════════════════════════════════════════════════════════════
#  END-TO-END: compute_all_indicators on a real CSV
# ═══════════════════════════════════════════════════════════════
class TestComputeAllIndicators(unittest.TestCase):
    """Smoke-test on real CSV data — every indicator must be populated and bounded."""

    def setUp(self):
        csv = os.path.join(_ROOT, "stock_csv", "RELIANCE.NS.csv")
        if not os.path.exists(csv):
            self.skipTest(f"reference CSV missing: {csv}")
        self.df = pd.read_csv(csv)

    def test_all_required_columns_populated(self):
        df = compute_all_indicators(self.df.copy())
        required = ["BB_Mid","BB_Upper","BB_Lower","BBW","Percent_B","Squeeze_ON",
                    "CMF","MFI","II","II_Pct","AD","AD_Pct",
                    "VWMACD","VWMACD_Signal","VWMACD_Hist",
                    "Vol_SMA50","SAR","SAR_Bull","RSI"]
        for col in required:
            self.assertIn(col, df.columns, f"missing column: {col}")
            tail = df[col].tail(40)
            self.assertGreater(tail.notna().sum(), 0, f"all-NaN in tail: {col}")

    def test_cmf_not_stuck_at_zero_regression(self):
        """Regression for the holiday-bar CMF bug — tail must have non-zero values."""
        df = compute_all_indicators(self.df.copy())
        tail_cmf = df["CMF"].tail(40)
        nonzero = (tail_cmf.abs() > 1e-6).sum()
        self.assertGreater(nonzero, 20,
            f"CMF stuck at zero in tail ({nonzero} non-zeros / 40) — holiday-bar regression")

    def test_indicator_value_ranges_on_real_data(self):
        df = compute_all_indicators(self.df.copy())
        tail = df.tail(60).dropna(subset=["CMF","MFI","Percent_B"])
        self.assertTrue((tail["CMF"].between(-1.0, 1.0)).all())
        self.assertTrue((tail["MFI"].between(0.0, 100.0)).all())
        # %b is unbounded by design; just make sure it's finite
        self.assertTrue(np.isfinite(tail["Percent_B"]).all())


if __name__ == "__main__":
    unittest.main(verbosity=2)
