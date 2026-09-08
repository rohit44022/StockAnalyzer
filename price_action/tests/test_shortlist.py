"""What is allowed onto the daily top-5 BUY shortlist.

Each filter here was measured on NSE signals from 2018 onward, held out from
the half used to pick it. Dropping any of them quietly costs money, and a
shortlist that silently stops filtering looks exactly like one that works --
hence a test per filter.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from price_action import config as C
from price_action.engine import PriceActionResult
from price_action.scanner import top_buy_shortlist


def _ok(ticker="OK.NS", **over):
    """A signal that clears every filter; override one field to break it."""
    r = PriceActionResult(ticker=ticker)
    r.signal_type = "BUY"
    r.setup_type = "SECOND_ENTRY"
    r.confidence = 80
    r.pa_score = 60.0
    r.entry_price = 100.0
    r.stop_loss = 95.0
    r.target_1 = 110.0
    r.target_2 = 120.0
    r.risk_reward = 2.0
    r.equation_verdict = "EDGE"
    r.always_in = "LONG"
    r.trend_phase = "CHANNEL"
    for k, v in over.items():
        setattr(r, k, v)
    return r


def _run(*rs):
    return top_buy_shortlist({"buy_signals": list(rs)})


class TestShortlistFilters(unittest.TestCase):
    def test_a_clean_signal_gets_through(self):
        self.assertEqual([p["ticker"] for p in _run(_ok())], ["OK.NS"])

    def test_equation_must_read_edge(self):
        # RISKY averaged +0.125%/trade out-of-sample and NO_EDGE lost money.
        for verdict in ("RISKY", "NO_EDGE", "NONE"):
            self.assertEqual(_run(_ok(equation_verdict=verdict)), [], verdict)

    def test_losing_setups_are_excluded(self):
        # REVERSAL and TREND_CONT lost money in both halves of the sample.
        for setup in ("REVERSAL", "TREND_CONT", "NONE"):
            self.assertEqual(_run(_ok(setup_type=setup)), [], setup)

    def test_counter_trend_buys_are_excluded(self):
        # Buying against the always-in read scored better in this data, but
        # Brooks does not permit it and it is not what this list is for.
        for direction in ("SHORT", "FLAT"):
            self.assertEqual(_run(_ok(always_in=direction)), [], direction)

    def test_low_confidence_is_excluded(self):
        self.assertEqual(_run(_ok(confidence=C.SHORTLIST_MIN_CONFIDENCE - 1)), [])
        self.assertEqual(len(_run(_ok(confidence=C.SHORTLIST_MIN_CONFIDENCE))), 1)

    def test_thin_reward_is_excluded(self):
        # Eligible signals paying under 1.0x their risk lost money out-of-sample,
        # and showing one would contradict the explanation's own claim that the
        # gain outweighs the loss.
        self.assertEqual(_run(_ok(risk_reward=1.0)), [])
        self.assertEqual(_run(_ok(risk_reward=C.SHORTLIST_MIN_RR - 0.01)), [])
        self.assertEqual(len(_run(_ok(risk_reward=C.SHORTLIST_MIN_RR))), 1)

    def test_inverted_stop_never_reaches_a_human(self):
        # The defect that fabricated 37% of the old backtest's P&L: a stop at
        # or above entry is not a trade, whatever else it scores.
        self.assertEqual(_run(_ok(stop_loss=105.0)), [])
        self.assertEqual(_run(_ok(stop_loss=100.0)), [])

    def test_ranked_by_confidence_and_capped(self):
        many = [_ok(f"T{i}.NS", confidence=70 + i) for i in range(9)]
        picks = _run(*many)
        self.assertEqual(len(picks), C.SHORTLIST_SIZE)
        self.assertEqual([p["ticker"] for p in picks],
                         ["T8.NS", "T7.NS", "T6.NS", "T5.NS", "T4.NS"])
        self.assertEqual([p["rank"] for p in picks], [1, 2, 3, 4, 5])

    def test_quiet_day_returns_nothing_rather_than_filler(self):
        self.assertEqual(_run(_ok(confidence=40), _ok(setup_type="REVERSAL")), [])


class TestPlainEnglish(unittest.TestCase):
    def test_explanation_carries_the_numbers_and_no_jargon(self):
        text = _run(_ok())[0]["explanation"]
        self.assertIn("100.00", text)          # entry
        self.assertIn("95.00", text)           # stop
        self.assertIn("110.00", text)          # first target
        self.assertIn("5.0%", text)            # risk as % of entry
        for jargon in ("always_in", "EDGE", "SECOND_ENTRY", "PF", "R-multiple"):
            self.assertNotIn(jargon, text, f"jargon leaked: {jargon}")

    def test_explanation_states_that_most_trades_lose(self):
        # The win rate is 42%. A shortlist that does not say so reads like a
        # promise, and the user acts on it as one.
        self.assertIn("lose", _run(_ok())[0]["explanation"])


if __name__ == "__main__":
    unittest.main()
