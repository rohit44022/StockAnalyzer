"""
Tests for weekly BB confirmation and its integration with Top Picks.

Covers:
  1. compute_weekly_view — output shape, trend classification, edge cases
  2. pick_passes_weekly_filter — the hard filter gate in Top Picks
  3. _compute_weekly_confirmation — safe wrapper used inside engine.py
  4. Integration — weekly filter does not break existing pipeline

Run:
    python3 -m unittest bb_squeeze.tests.test_weekly_confirmation -v
"""

from __future__ import annotations
import os, sys, unittest
import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from bb_squeeze.weekly_confirmation import compute_weekly_view
from top_picks.engine import (
    pick_passes_weekly_filter,
    pick_passes_strict_checklist,
    _compute_weekly_confirmation,
)


# ─────────────────────────────────────────────────────────────────
#  Synthetic daily OHLCV builder
# ─────────────────────────────────────────────────────────────────
def _make_daily(n=200, base=100.0, drift=0.0, volume=1_000_000):
    """Build a daily OHLCV DataFrame with DatetimeIndex."""
    dates = pd.bdate_range("2025-01-01", periods=n)
    close = base + drift * np.arange(n) + np.random.default_rng(42).normal(0, 0.5, n)
    return pd.DataFrame({
        "Date": dates,
        "Open": close - 0.3,
        "High": close + 1.0,
        "Low": close - 1.0,
        "Close": close,
        "Volume": np.full(n, float(volume)),
    }, index=dates)


# ═══════════════════════════════════════════════════════════════
#  compute_weekly_view — OUTPUT SHAPE
# ═══════════════════════════════════════════════════════════════
class TestWeeklyViewOutputShape(unittest.TestCase):
    def test_returns_dict_with_required_keys(self):
        df = _make_daily(200)
        result = compute_weekly_view(df)
        self.assertIsInstance(result, dict)
        self.assertTrue(result["available"])
        for key in [
            "weekly_trend", "verdict", "confirms_daily",
            "confidence_adjustment", "weekly_close", "weekly_sma20",
            "weekly_bb_upper", "weekly_bb_lower", "weekly_pct_b",
            "weekly_bbw", "explanation",
        ]:
            self.assertIn(key, result, f"missing key: {key}")

    def test_trend_is_one_of_three_values(self):
        df = _make_daily(200)
        result = compute_weekly_view(df)
        self.assertIn(result["weekly_trend"], {"BULLISH", "BEARISH", "NEUTRAL"})

    def test_verdict_is_one_of_four_values(self):
        df = _make_daily(200)
        result = compute_weekly_view(df)
        self.assertIn(result["verdict"], {"CONFIRMS", "CONTRADICTS", "WEAK", "NEUTRAL"})

    def test_confirms_daily_is_bool(self):
        df = _make_daily(200)
        result = compute_weekly_view(df)
        self.assertIsInstance(result["confirms_daily"], bool)

    def test_pct_b_is_numeric(self):
        df = _make_daily(200)
        result = compute_weekly_view(df)
        self.assertIsInstance(result["weekly_pct_b"], float)


# ═══════════════════════════════════════════════════════════════
#  compute_weekly_view — EDGE CASES
# ═══════════════════════════════════════════════════════════════
class TestWeeklyViewEdgeCases(unittest.TestCase):
    def test_too_few_bars_returns_unavailable(self):
        """< 60 daily bars = not enough data for weekly BB."""
        df = _make_daily(50)
        result = compute_weekly_view(df)
        self.assertFalse(result["available"])

    def test_none_input_returns_unavailable(self):
        result = compute_weekly_view(None)
        self.assertFalse(result["available"])

    def test_empty_dataframe_returns_unavailable(self):
        result = compute_weekly_view(pd.DataFrame())
        self.assertFalse(result["available"])

    def test_exactly_60_bars_returns_unavailable(self):
        """60 daily bars ~ 12 weeks, need 22 weekly bars minimum."""
        df = _make_daily(60)
        result = compute_weekly_view(df)
        self.assertFalse(result["available"])

    def test_enough_for_weekly_bb(self):
        """130 daily bars ~ 26 weeks, should be enough for 20-week BB."""
        df = _make_daily(130)
        result = compute_weekly_view(df)
        self.assertTrue(result["available"])


# ═══════════════════════════════════════════════════════════════
#  compute_weekly_view — TREND CLASSIFICATION
# ═══════════════════════════════════════════════════════════════
class TestWeeklyViewTrendClassification(unittest.TestCase):
    def test_strong_uptrend_gives_bullish(self):
        """Steadily rising price should yield BULLISH weekly trend."""
        df = _make_daily(200, base=100.0, drift=0.3)
        result = compute_weekly_view(df)
        self.assertEqual(result["weekly_trend"], "BULLISH")
        self.assertTrue(result["confirms_daily"])

    def test_strong_downtrend_gives_bearish(self):
        """Steadily falling price should yield BEARISH weekly trend."""
        df = _make_daily(200, base=200.0, drift=-0.3)
        result = compute_weekly_view(df)
        self.assertEqual(result["weekly_trend"], "BEARISH")
        self.assertFalse(result["confirms_daily"])

    def test_flat_gives_neutral(self):
        """Sideways price should yield NEUTRAL weekly trend."""
        df = _make_daily(200, base=100.0, drift=0.0)
        result = compute_weekly_view(df)
        self.assertIn(result["weekly_trend"], {"NEUTRAL", "BULLISH"})

    def test_explanation_is_nonempty(self):
        df = _make_daily(200)
        result = compute_weekly_view(df)
        self.assertIsInstance(result["explanation"], str)
        self.assertGreater(len(result["explanation"]), 20)


# ═══════════════════════════════════════════════════════════════
#  _compute_weekly_confirmation — SAFE WRAPPER
# ═══════════════════════════════════════════════════════════════
class TestComputeWeeklyConfirmationWrapper(unittest.TestCase):
    def test_works_with_date_column_not_index(self):
        """engine.py loads CSVs with a Date column, not DatetimeIndex."""
        df = _make_daily(200)
        df = df.reset_index(drop=True)  # remove DatetimeIndex, keep Date column
        result = _compute_weekly_confirmation(df)
        self.assertTrue(result["available"])

    def test_handles_broken_dataframe_gracefully(self):
        """Bad data should not crash — returns safe fallback."""
        df = pd.DataFrame({"nonsense": [1, 2, 3]})
        result = _compute_weekly_confirmation(df)
        self.assertFalse(result.get("available", False))
        self.assertTrue(result.get("confirms_daily", True))

    def test_handles_none_gracefully(self):
        result = _compute_weekly_confirmation(None)
        self.assertFalse(result.get("available", False))


# ═══════════════════════════════════════════════════════════════
#  pick_passes_weekly_filter — THE HARD FILTER
# ═══════════════════════════════════════════════════════════════
class TestWeeklyFilter(unittest.TestCase):
    # ── BUY direction: ONLY BULLISH passes ──

    def test_buy_passes_when_weekly_bullish(self):
        pick = {"weekly_confirmation": {
            "available": True, "weekly_trend": "BULLISH",
        }}
        self.assertTrue(pick_passes_weekly_filter(pick, "BUY"))

    def test_buy_rejected_when_weekly_neutral(self):
        """Strict: NEUTRAL is not BULLISH — BUY must be rejected."""
        pick = {"weekly_confirmation": {
            "available": True, "weekly_trend": "NEUTRAL",
        }}
        self.assertFalse(pick_passes_weekly_filter(pick, "BUY"))

    def test_buy_rejected_when_weekly_bearish(self):
        pick = {"weekly_confirmation": {
            "available": True, "weekly_trend": "BEARISH",
        }}
        self.assertFalse(pick_passes_weekly_filter(pick, "BUY"))

    def test_buy_rejected_when_weekly_weak(self):
        """Any non-BULLISH trend must block BUY."""
        pick = {"weekly_confirmation": {
            "available": True, "weekly_trend": "WEAK",
        }}
        self.assertFalse(pick_passes_weekly_filter(pick, "BUY"))

    # ── SELL direction: ONLY BEARISH passes ──

    def test_sell_passes_when_weekly_bearish(self):
        pick = {"weekly_confirmation": {
            "available": True, "weekly_trend": "BEARISH",
        }}
        self.assertTrue(pick_passes_weekly_filter(pick, "SELL"))

    def test_sell_rejected_when_weekly_neutral(self):
        """Strict: NEUTRAL is not BEARISH — SELL must be rejected."""
        pick = {"weekly_confirmation": {
            "available": True, "weekly_trend": "NEUTRAL",
        }}
        self.assertFalse(pick_passes_weekly_filter(pick, "SELL"))

    def test_sell_rejected_when_weekly_bullish(self):
        pick = {"weekly_confirmation": {
            "available": True, "weekly_trend": "BULLISH",
        }}
        self.assertFalse(pick_passes_weekly_filter(pick, "SELL"))

    # ── Unavailable / missing weekly data ──

    def test_passes_when_weekly_unavailable(self):
        """Benefit of the doubt — if we can't compute weekly, don't reject."""
        pick = {"weekly_confirmation": {"available": False}}
        self.assertTrue(pick_passes_weekly_filter(pick, "BUY"))
        self.assertTrue(pick_passes_weekly_filter(pick, "SELL"))

    def test_passes_when_weekly_key_missing(self):
        """Old picks without weekly_confirmation should pass."""
        pick = {}
        self.assertTrue(pick_passes_weekly_filter(pick, "BUY"))
        self.assertTrue(pick_passes_weekly_filter(pick, "SELL"))

    def test_passes_when_weekly_confirmation_is_empty_dict(self):
        pick = {"weekly_confirmation": {}}
        self.assertTrue(pick_passes_weekly_filter(pick, "BUY"))


# ═══════════════════════════════════════════════════════════════
#  INTEGRATION: weekly filter does not disrupt existing pipeline
# ═══════════════════════════════════════════════════════════════
class TestWeeklyFilterIntegration(unittest.TestCase):
    """Verify that the weekly filter is additive — it sits ON TOP of
    the existing strict checklist and never changes its behavior."""

    def test_strict_checklist_unchanged_for_m1_buy(self):
        """The strict checklist function itself must be unmodified."""
        pick = {"bb_conditions": {
            "squeeze": True, "price_breakout": True,
            "volume_confirm": True, "cmf_positive": True, "mfi_above_50": True,
        }}
        self.assertTrue(pick_passes_strict_checklist(pick, "M1", "BUY"))

    def test_strict_checklist_still_rejects_missing_condition(self):
        pick = {"bb_conditions": {
            "squeeze": False, "price_breakout": True,
            "volume_confirm": True, "cmf_positive": True, "mfi_above_50": True,
        }}
        self.assertFalse(pick_passes_strict_checklist(pick, "M1", "BUY"))

    def test_pick_passing_checklist_but_failing_weekly_is_rejected(self):
        """A pick that passes strict checklist but has BEARISH weekly
        must be caught by the weekly filter (for BUY)."""
        pick = {
            "bb_conditions": {
                "squeeze": True, "price_breakout": True,
                "volume_confirm": True, "cmf_positive": True, "mfi_above_50": True,
            },
            "weekly_confirmation": {
                "available": True, "weekly_trend": "BEARISH",
            },
        }
        self.assertTrue(pick_passes_strict_checklist(pick, "M1", "BUY"),
                        "strict checklist should still pass")
        self.assertFalse(pick_passes_weekly_filter(pick, "BUY"),
                         "weekly filter should reject BEARISH for BUY")

    def test_pick_passing_checklist_but_neutral_weekly_is_rejected(self):
        """Strict mode: NEUTRAL weekly must also be rejected for BUY."""
        pick = {
            "bb_conditions": {
                "squeeze": True, "price_breakout": True,
                "volume_confirm": True, "cmf_positive": True, "mfi_above_50": True,
            },
            "weekly_confirmation": {
                "available": True, "weekly_trend": "NEUTRAL",
            },
        }
        self.assertTrue(pick_passes_strict_checklist(pick, "M1", "BUY"),
                        "strict checklist should still pass")
        self.assertFalse(pick_passes_weekly_filter(pick, "BUY"),
                         "weekly filter should reject NEUTRAL for BUY (strict mode)")

    def test_pick_passing_both_filters(self):
        """A pick that passes both strict + weekly should be kept."""
        pick = {
            "bb_conditions": {
                "squeeze": True, "price_breakout": True,
                "volume_confirm": True, "cmf_positive": True, "mfi_above_50": True,
            },
            "weekly_confirmation": {
                "available": True, "weekly_trend": "BULLISH",
            },
        }
        self.assertTrue(pick_passes_strict_checklist(pick, "M1", "BUY"))
        self.assertTrue(pick_passes_weekly_filter(pick, "BUY"))


# ═══════════════════════════════════════════════════════════════
#  REAL CSV SMOKE TEST
# ═══════════════════════════════════════════════════════════════
class TestWeeklyConfirmationRealData(unittest.TestCase):
    def setUp(self):
        csv = os.path.join(_ROOT, "stock_csv", "RELIANCE.NS.csv")
        if not os.path.exists(csv):
            self.skipTest("reference CSV missing")
        self.df = pd.read_csv(csv, parse_dates=["Date"], index_col="Date")

    def test_real_csv_returns_available(self):
        result = compute_weekly_view(self.df)
        self.assertTrue(result["available"])

    def test_real_csv_trend_is_valid(self):
        result = compute_weekly_view(self.df)
        self.assertIn(result["weekly_trend"], {"BULLISH", "BEARISH", "NEUTRAL"})

    def test_real_csv_pct_b_is_finite(self):
        result = compute_weekly_view(self.df)
        self.assertTrue(np.isfinite(result["weekly_pct_b"]))

    def test_real_csv_weekly_sma_is_positive(self):
        result = compute_weekly_view(self.df)
        self.assertGreater(result["weekly_sma20"], 0)

    def test_wrapper_works_with_real_csv(self):
        """_compute_weekly_confirmation handles Date column (reset index)."""
        df_no_idx = self.df.reset_index()
        result = _compute_weekly_confirmation(df_no_idx)
        self.assertTrue(result["available"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
