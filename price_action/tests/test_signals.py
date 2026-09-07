"""Brooks' trader's equation.

"To take a trade, you must believe that the probability of success times the
 potential reward is greater than the probability of failure times the risk."
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from price_action.signals import compute_traders_equation


class TestTradersEquation(unittest.TestCase):
    def test_coin_flip_at_1r_is_not_a_trade(self):
        # p=0.5, reward == risk: the equation is exactly zero. Brooks requires
        # "greater than", so this is not an edge.
        eq, verdict = compute_traders_equation(50.0, entry=100.0, stop=90.0, target=110.0)
        self.assertEqual(eq, 0.0)
        self.assertEqual(verdict, "NO_EDGE")

    def test_low_probability_high_reward_is_an_edge(self):
        # Brooks' own worked case: "the probability might be only 40 percent.
        # However, since the reward is several times the risk, the trader's
        # equation is still very positive."
        eq, verdict = compute_traders_equation(40.0, entry=100.0, stop=90.0, target=130.0)
        self.assertGreater(eq, 0)
        self.assertEqual(verdict, "EDGE")

    def test_scalp_needs_a_high_win_rate(self):
        # Reward far smaller than risk. Brooks: with a scalp "the risk is at
        # least as large as the reward and the probability is rarely high
        # enough to make the trader's equation favorable."
        eq, verdict = compute_traders_equation(70.0, entry=100.0, stop=90.0, target=102.0)
        self.assertLess(eq, 0)
        self.assertEqual(verdict, "NO_EDGE")

    def test_barely_favorable_is_risky_not_an_edge(self):
        # Positive, but small relative to the risk taken. Brooks calls this
        # "risky", not an edge.
        eq, verdict = compute_traders_equation(52.0, entry=100.0, stop=90.0, target=110.0)
        self.assertGreater(eq, 0)
        self.assertEqual(verdict, "RISKY")

    def test_degenerate_levels_are_not_an_edge(self):
        self.assertEqual(compute_traders_equation(90.0, 100.0, 100.0, 120.0)[1], "NO_EDGE")
        self.assertEqual(compute_traders_equation(90.0, 100.0, 90.0, 100.0)[1], "NO_EDGE")


if __name__ == "__main__":
    unittest.main()
