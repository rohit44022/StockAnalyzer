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
