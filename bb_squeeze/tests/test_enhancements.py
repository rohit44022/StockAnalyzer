"""
Unit tests for the 7 enhancement layers added to the Top Picks pipeline.
Verifies that all new gates/filters work correctly and that the original
BB strict checklist is NOT modified.
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import date, timedelta
from unittest.mock import patch

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ═══════════════════════════════════════════════════════════════
# 1. Weight Integrity
# ═══════════════════════════════════════════════════════════════

class TestWeightIntegrity(unittest.TestCase):
    def test_weights_sum_to_one(self):
        from top_picks.config import WEIGHTS
        self.assertAlmostEqual(sum(WEIGHTS.values()), 1.0, places=9)

    def test_bb_strategy_is_dominant(self):
        from top_picks.config import WEIGHTS
        self.assertEqual(WEIGHTS["bb_strategy"], 0.35)

    def test_volume_quality_weight_exists(self):
        from top_picks.config import WEIGHTS
        self.assertIn("volume_quality", WEIGHTS)
        self.assertEqual(WEIGHTS["volume_quality"], 0.05)


# ═══════════════════════════════════════════════════════════════
# 2. Volume Quality Scoring
# ═══════════════════════════════════════════════════════════════

class TestVolumeQualityScoring(unittest.TestCase):
    def setUp(self):
        from top_picks.scorer import _score_volume_quality
        self.score = _score_volume_quality

    def test_none_returns_neutral(self):
        self.assertEqual(self.score(None), 50.0)

    def test_zero_returns_neutral(self):
        self.assertEqual(self.score(0), 50.0)

    def test_low_volume(self):
        self.assertEqual(self.score(1.0), 30.0)
        self.assertEqual(self.score(1.49), 30.0)

    def test_mid_volume(self):
        self.assertEqual(self.score(1.5), 60.0)
        self.assertEqual(self.score(2.0), 60.0)
        self.assertEqual(self.score(2.49), 60.0)

    def test_high_volume(self):
        self.assertEqual(self.score(2.5), 100.0)
        self.assertEqual(self.score(5.0), 100.0)

    def test_nan_returns_neutral(self):
        import math
        self.assertEqual(self.score(float("nan")), 50.0)


# ═══════════════════════════════════════════════════════════════
# 3. VIX Regime
# ═══════════════════════════════════════════════════════════════

class TestVixRegime(unittest.TestCase):
    @patch("bb_squeeze.vix_regime._fetch_vix")
    def test_normal_regime(self, mock_vix):
        mock_vix.return_value = 12.0
        from bb_squeeze.vix_regime import get_vix_regime
        r = get_vix_regime()
        self.assertTrue(r["available"])
        self.assertEqual(r["regime"], "NORMAL")
        self.assertIsNone(r["min_score_override"])
        self.assertIsNone(r["active_methods"])

    @patch("bb_squeeze.vix_regime._fetch_vix")
    def test_caution_regime(self, mock_vix):
        mock_vix.return_value = 18.0
        from bb_squeeze.vix_regime import get_vix_regime
        r = get_vix_regime()
        self.assertEqual(r["regime"], "CAUTION")
        self.assertEqual(r["min_score_override"], 45.0)
        self.assertIsNone(r["active_methods"])

    @patch("bb_squeeze.vix_regime._fetch_vix")
    def test_defensive_regime(self, mock_vix):
        mock_vix.return_value = 25.0
        from bb_squeeze.vix_regime import get_vix_regime
        r = get_vix_regime()
        self.assertEqual(r["regime"], "DEFENSIVE")
        self.assertEqual(r["active_methods"], ["M2"])

    @patch("bb_squeeze.vix_regime._fetch_vix")
    def test_unavailable(self, mock_vix):
        mock_vix.return_value = None
        from bb_squeeze.vix_regime import get_vix_regime
        r = get_vix_regime()
        self.assertFalse(r["available"])
        self.assertEqual(r["regime"], "UNKNOWN")

    def test_skip_flag(self):
        from bb_squeeze.vix_regime import get_vix_regime
        r = get_vix_regime(skip=True)
        self.assertFalse(r["available"])
        self.assertEqual(r["regime"], "UNKNOWN")

    @patch("bb_squeeze.vix_regime._fetch_vix")
    def test_boundary_at_15(self, mock_vix):
        mock_vix.return_value = 15.0
        from bb_squeeze.vix_regime import get_vix_regime
        r = get_vix_regime()
        self.assertEqual(r["regime"], "NORMAL")

    @patch("bb_squeeze.vix_regime._fetch_vix")
    def test_boundary_above_15(self, mock_vix):
        mock_vix.return_value = 15.01
        from bb_squeeze.vix_regime import get_vix_regime
        r = get_vix_regime()
        self.assertEqual(r["regime"], "CAUTION")


# ═══════════════════════════════════════════════════════════════
# 4. Sector RS Gate
# ═══════════════════════════════════════════════════════════════

class TestSectorRsGate(unittest.TestCase):
    def _filter(self, picks):
        return [p for p in picks
                if p.get("sector_rs", {}).get("sector_trend") != "LAGGING"]

    def test_lagging_dropped(self):
        picks = [
            {"ticker": "A", "sector_rs": {"sector_trend": "LAGGING"}},
            {"ticker": "B", "sector_rs": {"sector_trend": "LEADING"}},
        ]
        result = self._filter(picks)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["ticker"], "B")

    def test_inline_passes(self):
        picks = [{"ticker": "A", "sector_rs": {"sector_trend": "INLINE"}}]
        self.assertEqual(len(self._filter(picks)), 1)

    def test_unavailable_passes(self):
        picks = [{"ticker": "A", "sector_rs": {"available": False, "sector_trend": None}}]
        self.assertEqual(len(self._filter(picks)), 1)

    def test_missing_sector_rs_passes(self):
        picks = [{"ticker": "A"}]
        self.assertEqual(len(self._filter(picks)), 1)


# ═══════════════════════════════════════════════════════════════
# 5. Earnings Guard
# ═══════════════════════════════════════════════════════════════

class TestEarningsGate(unittest.TestCase):
    def test_high_risk(self):
        from bb_squeeze.earnings_guard import check_earnings_proximity
        future = (date.today() + timedelta(days=2)).isoformat()
        r = check_earnings_proximity("TEST.NS", future)
        self.assertEqual(r["risk_level"], "HIGH")
        self.assertTrue(r["warning"])

    def test_medium_risk(self):
        from bb_squeeze.earnings_guard import check_earnings_proximity
        future = (date.today() + timedelta(days=7)).isoformat()
        r = check_earnings_proximity("TEST.NS", future)
        self.assertEqual(r["risk_level"], "MEDIUM")

    def test_low_risk(self):
        from bb_squeeze.earnings_guard import check_earnings_proximity
        future = (date.today() + timedelta(days=14)).isoformat()
        r = check_earnings_proximity("TEST.NS", future)
        self.assertEqual(r["risk_level"], "LOW")

    def test_no_warning_far_future(self):
        from bb_squeeze.earnings_guard import check_earnings_proximity
        future = (date.today() + timedelta(days=30)).isoformat()
        r = check_earnings_proximity("TEST.NS", future)
        self.assertFalse(r["warning"])
        self.assertIsNone(r["risk_level"])

    def test_none_date(self):
        from bb_squeeze.earnings_guard import check_earnings_proximity
        r = check_earnings_proximity("TEST.NS", None)
        self.assertFalse(r["warning"])


# ═══════════════════════════════════════════════════════════════
# 6. Hold Period Guidance
# ═══════════════════════════════════════════════════════════════

class TestHoldPeriodGuidance(unittest.TestCase):
    def test_all_methods_mapped(self):
        from top_picks.config import HOLD_PERIOD_MAP
        for method in ["M1", "M2", "M3", "M4"]:
            self.assertIn(method, HOLD_PERIOD_MAP)
            self.assertIn("days", HOLD_PERIOD_MAP[method])
            self.assertIn("stop", HOLD_PERIOD_MAP[method])

    def test_m1_values(self):
        from top_picks.config import HOLD_PERIOD_MAP
        self.assertEqual(HOLD_PERIOD_MAP["M1"]["days"], "15-20")
        self.assertEqual(HOLD_PERIOD_MAP["M1"]["stop"], "SAR")

    def test_m2_values(self):
        from top_picks.config import HOLD_PERIOD_MAP
        self.assertEqual(HOLD_PERIOD_MAP["M2"]["days"], "20+")

    def test_m3_values(self):
        from top_picks.config import HOLD_PERIOD_MAP
        self.assertEqual(HOLD_PERIOD_MAP["M3"]["days"], "10-15")


# ═══════════════════════════════════════════════════════════════
# 7. Fundamental Floor Gate
# ═══════════════════════════════════════════════════════════════

class TestFundamentalFloor(unittest.TestCase):
    def _filter(self, picks):
        from top_picks.config import FUNDAMENTAL_FLOOR_SCORE, FUNDAMENTAL_FLOOR_SIGNAL
        result = []
        for pick in picks:
            fd = pick.get("fundamentals", {})
            if fd.get("available", False):
                if fd.get("score", 100) < FUNDAMENTAL_FLOOR_SCORE:
                    continue
                if fd.get("signal", "") == FUNDAMENTAL_FLOOR_SIGNAL:
                    continue
            result.append(pick)
        return result

    def test_low_score_dropped(self):
        picks = [{"ticker": "A", "fundamentals": {"available": True, "score": 20, "signal": "HOLD"}}]
        self.assertEqual(len(self._filter(picks)), 0)

    def test_avoid_signal_dropped(self):
        picks = [{"ticker": "A", "fundamentals": {"available": True, "score": 60, "signal": "AVOID"}}]
        self.assertEqual(len(self._filter(picks)), 0)

    def test_good_fundamentals_pass(self):
        picks = [{"ticker": "A", "fundamentals": {"available": True, "score": 55, "signal": "BUY"}}]
        self.assertEqual(len(self._filter(picks)), 1)

    def test_unavailable_passes(self):
        picks = [{"ticker": "A", "fundamentals": {"available": False}}]
        self.assertEqual(len(self._filter(picks)), 1)

    def test_missing_fundamentals_passes(self):
        picks = [{"ticker": "A"}]
        self.assertEqual(len(self._filter(picks)), 1)


# ═══════════════════════════════════════════════════════════════
# 8. Strict Checklist Regression — MUST NOT BE WEAKENED
# ═══════════════════════════════════════════════════════════════

class TestStrictChecklistUnchanged(unittest.TestCase):
    def test_missing_squeeze_fails_m1(self):
        from top_picks.engine import pick_passes_strict_checklist
        pick = {
            "bb_conditions": {
                "squeeze": False,
                "price_breakout": True,
                "volume_confirm": True,
                "cmf_positive": True,
                "mfi_above_50": True,
            }
        }
        self.assertFalse(pick_passes_strict_checklist(pick, "M1", "BUY"))

    def test_all_conditions_pass_m1(self):
        from top_picks.engine import pick_passes_strict_checklist
        pick = {
            "bb_conditions": {
                "squeeze": True,
                "price_breakout": True,
                "volume_confirm": True,
                "cmf_positive": True,
                "mfi_above_50": True,
            }
        }
        self.assertTrue(pick_passes_strict_checklist(pick, "M1", "BUY"))

    def test_missing_volume_fails_m1(self):
        from top_picks.engine import pick_passes_strict_checklist
        pick = {
            "bb_conditions": {
                "squeeze": True,
                "price_breakout": True,
                "volume_confirm": False,
                "cmf_positive": True,
                "mfi_above_50": True,
            }
        }
        self.assertFalse(pick_passes_strict_checklist(pick, "M1", "BUY"))


if __name__ == "__main__":
    unittest.main()
