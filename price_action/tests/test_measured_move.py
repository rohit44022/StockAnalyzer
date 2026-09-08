"""The measured move must be available in the direction being traded.

  "Almost every move, whether a trend or a pullback, has two legs. After the
   first leg, expect a second leg approximately equal in size."

A buy taken during a two-legged pullback is betting the bear leg is ending.
Its target is the bull projection -- leg 1's height measured up from the
pullback low -- not the bear leg's own downward projection, which sits below
the entry and gets discarded, leaving the signal with no target at all.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from price_action import trend_analyzer as ta
from price_action.bar_types import BarAnalysis
from price_action.trend_analyzer import TrendLeg, analyze_two_legs


def _leg(direction, start, end, idx):
    return TrendLeg(direction=direction, start_idx=idx, end_idx=idx + 5,
                    start_price=start, end_price=end, size=abs(end - start),
                    bars=5)


def _bars(n=20):
    return [BarAnalysis(index=i, date=f"2024-01-{i+1:02d}", open=110.0,
                        high=112.0, low=108.0, close=110.0,
                        range_size=4.0, atr=4.0) for i in range(n)]


# Leg 1 runs 100 -> 120 (up 20). Leg 2 is the pullback, 120 -> 110.
BULL_THEN_PULLBACK = [_leg("BULL", 100.0, 120.0, 0), _leg("BEAR", 120.0, 110.0, 5)]
# Mirror: leg 1 runs 120 -> 100 (down 20), leg 2 bounces 100 -> 110.
BEAR_THEN_BOUNCE = [_leg("BEAR", 120.0, 100.0, 0), _leg("BULL", 100.0, 110.0, 5)]


class TestMeasuredMoveDirection(unittest.TestCase):
    def test_pullback_buy_gets_a_target_above_the_pullback_low(self):
        with patch.object(ta, "_find_trend_legs", return_value=BULL_THEN_PULLBACK):
            r = analyze_two_legs(_bars())
        # Leg 1 was 20 tall; project it up from the 110 pullback low.
        self.assertEqual(r["measured_move_up"], 130.0)
        self.assertGreater(r["measured_move_up"], 110.0,
                           "a pullback buy must have a target above the entry")

    def test_running_leg_still_drives_the_headline_target(self):
        with patch.object(ta, "_find_trend_legs", return_value=BULL_THEN_PULLBACK):
            r = analyze_two_legs(_bars())
        # The bear leg is the one running, so the headline stays its own
        # downward projection -- 120 high less leg 1's 20.
        self.assertEqual(r["measured_move_target"], 100.0)
        self.assertEqual(r["measured_move_down"], 100.0)

    def test_bounce_sell_gets_a_target_below_the_bounce_high(self):
        with patch.object(ta, "_find_trend_legs", return_value=BEAR_THEN_BOUNCE):
            r = analyze_two_legs(_bars())
        self.assertEqual(r["measured_move_down"], 90.0)
        self.assertLess(r["measured_move_down"], 110.0,
                        "a bounce sell must have a target below the entry")

    def test_both_directions_are_always_populated(self):
        for legs in (BULL_THEN_PULLBACK, BEAR_THEN_BOUNCE):
            with patch.object(ta, "_find_trend_legs", return_value=legs):
                r = analyze_two_legs(_bars())
            self.assertGreater(r["measured_move_up"], 0.0)
            self.assertGreater(r["measured_move_down"], 0.0)
            self.assertGreater(r["measured_move_up"], r["measured_move_down"])


if __name__ == "__main__":
    unittest.main()
