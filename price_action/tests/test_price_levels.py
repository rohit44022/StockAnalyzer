"""Where the protective stop goes.

Brooks puts the stop beyond the signal bar, and sizes the position to whatever
risk that implies. He does not move the stop closer to fit a position:

  "the stop is below the signal bar, and the trader has to be willing to risk
   to that price"

A cap that relocates the stop to a fixed percentage of entry puts it inside
the signal bar's own noise, where the market has no reason to respect it. On
the NSE universe that cap bound on 74.9% of BUY signals and turned a
+0.101R/trade edge into -0.104R.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from price_action.bar_types import BarAnalysis
from price_action.breakouts import BreakoutAnalysis
from price_action.patterns import PatternSummary
from price_action.signals import _compute_price_levels
from price_action.trend_analyzer import TrendState


def _bars(lows, highs):
    """Minimal bar series; only OHLC is needed to place entry and stop."""
    out = []
    for i, (lo, hi) in enumerate(zip(lows, highs)):
        out.append(BarAnalysis(
            index=i, date=f"2024-01-{i+1:02d}",
            open=lo, high=hi, low=lo, close=hi,
            range_size=hi - lo, atr=hi - lo,
        ))
    return out


def _levels(bars, direction="BUY"):
    return _compute_price_levels(
        bars, direction, "PULLBACK",
        TrendState(), PatternSummary(), BreakoutAnalysis(),
    )


class TestStopPlacement(unittest.TestCase):
    def test_wide_signal_bar_keeps_its_structural_stop(self):
        # Signal bar spans 100 -> 120, so the stop belongs below 100 -- a risk
        # of ~17% of the 120 entry. The old 3% cap would have dragged it up to
        # ~116.4, inside the bar.
        # (The stop is placed at the bar low rather than one tick below it.
        # On daily bars a tick is 0.01, immaterial next to a stop this wide.)
        bars = _bars([100.0] * 5, [120.0] * 5)
        lv = _levels(bars)
        self.assertLessEqual(lv["stop"], 100.0, "stop must not sit inside the signal bar")
        risk_pct = (lv["entry"] - lv["stop"]) / lv["entry"] * 100
        self.assertGreater(risk_pct, 3.0, "risk must not be clamped to 3% of entry")

    def test_sell_stop_sits_above_the_signal_bar(self):
        bars = _bars([100.0] * 5, [120.0] * 5)
        lv = _levels(bars, "SELL")
        self.assertGreaterEqual(lv["stop"], 120.0, "stop must not sit inside the signal bar")
        risk_pct = (lv["stop"] - lv["entry"]) / lv["entry"] * 100
        self.assertGreater(risk_pct, 3.0, "risk must not be clamped to 3% of entry")

    def test_stale_pullback_level_cannot_invert_the_stop(self):
        # The pullback level is read off a bar earlier in the window, so it can
        # sit below a stop taken from the last five bars. Accepting it would
        # put the stop ABOVE a long entry -- a guaranteed exit in profit, not a
        # stop. 4,037 trades did exactly that and booked 37% of all P&L.
        bars = _bars([100.0] * 5, [120.0] * 5)
        bo = BreakoutAnalysis()
        bo.pullback_entry_price = 90.0          # below the 100 stop
        lv = _compute_price_levels(bars, "BUY", "PULLBACK",
                                   TrendState(), PatternSummary(), bo)
        self.assertLess(lv["stop"], lv["entry"],
                        "a long's stop must stay below its entry")

    def test_usable_pullback_level_is_still_taken(self):
        bars = _bars([100.0] * 5, [120.0] * 5)
        bo = BreakoutAnalysis()
        bo.pullback_entry_price = 110.0         # above the 100 stop
        lv = _compute_price_levels(bars, "BUY", "PULLBACK",
                                   TrendState(), PatternSummary(), bo)
        self.assertEqual(lv["entry"], 110.0)
        self.assertLess(lv["stop"], lv["entry"])

    def test_pullback_buy_targets_the_bull_projection_not_a_placeholder(self):
        # Bear leg running inside a bull trend: the headline measured move
        # points DOWN (100) while the bull projection points UP (145). A buy
        # must take the upward one. Reading the headline instead leaves no
        # target above entry and silently falls back to a flat 1.5R.
        bars = _bars([100.0] * 5, [120.0] * 5)
        trend = TrendState()
        trend.measured_move_target = 100.0
        trend.measured_move_down = 100.0
        trend.measured_move_up = 145.0
        lv = _compute_price_levels(bars, "BUY", "PULLBACK",
                                   trend, PatternSummary(), BreakoutAnalysis())
        self.assertEqual(lv["target_1"], 145.0)
        fallback = lv["entry"] + (lv["entry"] - lv["stop"]) * 1.5
        self.assertNotEqual(lv["target_1"], fallback,
                            "target must come from structure, not the 1.5R placeholder")

    def test_risk_is_not_pinned_to_one_value_across_different_bars(self):
        # The tell for a binding cap: unrelated bar geometries producing the
        # same risk-as-%-of-entry.
        tight = _levels(_bars([119.0] * 5, [120.0] * 5))
        wide = _levels(_bars([100.0] * 5, [120.0] * 5))
        r_tight = (tight["entry"] - tight["stop"]) / tight["entry"]
        r_wide = (wide["entry"] - wide["stop"]) / wide["entry"]
        self.assertLess(r_tight, r_wide)


if __name__ == "__main__":
    unittest.main()
