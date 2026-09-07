"""Micro channels: no upper bar cap, and Brooks' small pullbacks allowed."""
import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from price_action.bar_types import classify_bars
from price_action.channels import detect_micro_channels


def _bars(rows):
    df = pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"])
    df["Volume"] = 100000
    df.index = pd.date_range("2024-01-01", periods=len(df), freq="D")
    return classify_bars(df)


def _rising(n, start=100.0, step=1.0):
    """n bars each making a higher low — a textbook bull micro channel."""
    return [(start + i * step, start + i * step + 0.8,
             start + i * step - 0.1, start + i * step + 0.6) for i in range(n)]


def _flat(n, base=100.0):
    """Choppy filler — alternating lows, so it cannot itself form a channel.
    classify_bars() needs C.MIN_BARS_REQUIRED (60) bars, hence the padding."""
    return [(base, base + 0.3, base - 0.3 - (i % 2), base) for i in range(n)]


class TestMicroChannels(unittest.TestCase):
    def _bull(self, bars):
        return [c for c in detect_micro_channels(bars) if c.direction == "BULL"]

    def test_long_channel_is_not_truncated(self):
        # 25 rising bars is ONE micro channel, not 15 + a remainder.
        # Brooks: "the more bars ... the more likely that the bear breakout
        # will not reverse the bull trend."
        bars = _bars(_flat(55) + _rising(25, start=100.0))
        longest = max(self._bull(bars), key=lambda c: c.bars)
        self.assertGreaterEqual(longest.bars, 25)

    def test_small_pullback_does_not_end_the_channel(self):
        # One bar dips below the prior low, the next bar recovers above it.
        rows = _flat(55) + _rising(8, start=100.0)
        rows.append((108.0, 108.5, 106.5, 107.0))   # the small pullback
        rows += _rising(8, start=108.5)
        bars = _bars(rows)
        longest = max(self._bull(bars), key=lambda c: c.bars)
        self.assertGreater(longest.bars, 9, "pullback split the channel in two")

    def test_touch_pct_is_measured_not_constant(self):
        # The old code computed count/(i-start+1), which is 1.0 by
        # construction. A channel containing a pullback must report < 100.
        rows = _flat(55) + _rising(8, start=100.0)
        rows.append((108.0, 108.5, 106.5, 107.0))
        rows += _rising(8, start=108.5)
        bars = _bars(rows)
        longest = max(self._bull(bars), key=lambda c: c.bars)
        self.assertLess(longest.touch_pct, 100.0)

    def test_choppy_action_is_not_a_micro_channel(self):
        bars = _bars(_flat(60))
        self.assertEqual(self._bull(bars), [])


if __name__ == "__main__":
    unittest.main()
