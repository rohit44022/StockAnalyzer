"""Always-In is a latching state that flips only on a confirmed spike."""
import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from price_action.bar_types import classify_bars
from price_action.trend_analyzer import compute_always_in


def _quiet(n, base=100.0):
    """n small dojis around `base` — no spike, nothing to flip the state."""
    return [(base, base + 0.4, base - 0.4, base + 0.1) for _ in range(n)]


def _spike(base, up=True, size=8.0):
    """A strong trend bar that closes beyond the range, plus follow-through."""
    if up:
        return [
            (base, base + size, base - 0.2, base + size - 0.3),
            (base + size, base + size + 2, base + size - 0.5, base + size + 1.5),
        ]
    return [
        (base, base + 0.2, base - size, base - size + 0.3),
        (base - size, base - size + 0.5, base - size - 2, base - size - 1.5),
    ]


def _bars(rows):
    df = pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"])
    df["Volume"] = 100000
    df.index = pd.date_range("2024-01-01", periods=len(df), freq="D")
    return classify_bars(df), df


class TestAlwaysInLatches(unittest.TestCase):
    def test_no_spike_means_no_direction(self):
        bars, df = _bars(_quiet(80))
        self.assertEqual(compute_always_in(bars, df)[0], "FLAT")

    def test_confirmed_bull_spike_flips_long(self):
        bars, df = _bars(_quiet(70) + _spike(100.0, up=True))
        self.assertEqual(compute_always_in(bars, df)[0], "LONG")

    def test_state_latches_through_quiet_bars(self):
        # Brooks: the always-in position is whatever it last was. Quiet
        # bars after the spike must not reset it to FLAT.
        rows = _quiet(70) + _spike(100.0, up=True) + _quiet(25, base=109.0)
        bars, df = _bars(rows)
        self.assertEqual(compute_always_in(bars, df)[0], "LONG")

    def test_opposite_spike_flips_it_back(self):
        rows = (_quiet(70) + _spike(100.0, up=True)
                + _quiet(15, base=109.0) + _spike(109.0, up=False))
        bars, df = _bars(rows)
        self.assertEqual(compute_always_in(bars, df)[0], "SHORT")

    def test_spike_without_follow_through_does_not_flip(self):
        # Big bull spike, but the next bar closes bear — "the reversal
        # attempt has failed", so the state must not flip.
        failed = [
            (100.0, 108.0, 99.8, 107.7),
            (107.7, 108.0, 105.0, 105.2),   # bear close, below the spike close
        ]
        bars, df = _bars(_quiet(70) + failed)
        self.assertEqual(compute_always_in(bars, df)[0], "FLAT")


if __name__ == "__main__":
    unittest.main()
