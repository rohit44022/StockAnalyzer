"""
Strict book-conformance tests for the decision-LAYER of every BB method.

The indicator layer (formulas, periods) is covered by test_indicators.py.
This file proves that each method's BUY/SELL/HOLD logic strictly applies
Bollinger's prescribed rules — and never compromises:

  M1 (Ch. 15) — ALL 5 squeeze BUY conditions required, no exceptions.
                ALL 5 squeeze SELL conditions required (short-side rule).
  M2 (Ch. 19) — BUY requires %b > 0.8 AND MFI > 80 AND volume confirm AND
                no bearish divergence (book p.155).
  M3 (Ch. 20) — W-Bottom: first low at lower band, second low above,
                ≥ minimum separation. M-Top: mirror.
  M4 (Ch. 18) — Walking-the-band: ≥3 tags AND ≥60% of bars in extreme zone
                AND every close held middle band — ALL three rules required.

Each "strict" test asserts the canonical signal fires; then it flips
exactly ONE condition off and asserts the signal does NOT fire — proving
the engine never accepts a "4-of-5" compromise.

Run:
    python -m unittest bb_squeeze.tests.test_strategies -v
"""

from __future__ import annotations
import os, sys, unittest
import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from bb_squeeze.indicators import compute_all_indicators
from bb_squeeze.signals import analyze_signals, _head_fake_check
from bb_squeeze.strategies import (
    _method_ii_trend_following,
    _detect_w_bottoms, _detect_m_tops,
    _detect_band_walk, _method_iv_walking_the_bands,
    run_all_strategies,
)
from bb_squeeze.strategy_config import (
    M2_PCT_B_BUY_THRESHOLD, M2_PCT_B_SELL_THRESHOLD,
    M2_MFI_CONFIRM_BUY, M2_MFI_CONFIRM_SELL,
    M3_W_LOOKBACK, M3_W_MIN_SEPARATION, M3_W_MAX_SEPARATION,
    M3_W_FIRST_LOW_PCT_B, M3_W_SECOND_LOW_PCT_B,
    M3_M_FIRST_HIGH_PCT_B, M3_M_SECOND_HIGH_PCT_B,
    M4_WALK_MIN_TOUCHES, M4_WALK_LOOKBACK, M4_WALK_TOUCH_TOLERANCE,
    M4_WALK_PCT_B_UPPER, M4_WALK_PCT_B_LOWER,
    M4_WALK_ZONE_CONSISTENCY, M4_WALK_BB_MID_PULLBACK,
    M4_WALK_DIP_BUY_PCT_B_MIN, M4_WALK_DIP_BUY_PCT_B_MAX,
)
from top_picks.engine import pick_passes_strict_checklist


# ─────────────────────────────────────────────────────────────────
#  HELPER — Build a fully-populated DataFrame with all indicators
# ─────────────────────────────────────────────────────────────────
def _synth_df(n=80, base=100.0, drift=0.0, hl_spread=2.0, volume=1_000_000):
    """Synthetic OHLCV with light drift. All indicators populated."""
    rng = np.random.default_rng(42)
    noise = rng.normal(0, 0.5, n)
    close = base + drift * np.arange(n) + noise
    open_ = close - rng.normal(0, 0.2, n)
    high  = np.maximum(close, open_) + hl_spread / 2.0
    low   = np.minimum(close, open_) - hl_spread / 2.0
    vol   = np.full(n, float(volume))
    df = pd.DataFrame({
        "Date": pd.date_range("2025-01-01", periods=n, freq="B").strftime("%Y-%m-%d"),
        "Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol,
    })
    return compute_all_indicators(df)


def _force_row(df, idx, **kv):
    """Forcefully set indicator cells in row `idx`. Returns a new DataFrame."""
    out = df.copy()
    for k, v in kv.items():
        out.at[out.index[idx], k] = v
    return out


# ═══════════════════════════════════════════════════════════════
#  M1 — SQUEEZE METHOD (Book Ch. 15-16)
#  STRICT RULE: all 5 BUY conditions required, no exceptions.
# ═══════════════════════════════════════════════════════════════
class TestM1SqueezeBuyStrict(unittest.TestCase):
    """analyze_signals must fire BUY iff ALL 5 conditions are GREEN
    AND head-fake is False. Flipping any single condition off must
    cancel the BUY signal."""

    def _build_buy_ready_df(self):
        """Synthetic 80-bar frame with the last row hand-tuned so all 5
        M1 BUY conditions evaluate True."""
        df = _synth_df(n=80, drift=0.0, hl_spread=2.0)
        last = df.index[-1]
        prev = df.index[-2]
        bb_upper = float(df.at[last, "BB_Upper"])

        # Force prev close just below upper; current close clearly above.
        df.at[prev, "Close"]      = bb_upper - 1.0
        df.at[last, "Close"]      = bb_upper + 5.0           # cond2 + green candle
        df.at[last, "Squeeze_ON"] = True                     # cond1
        df.at[last, "Volume"]     = float(df.at[last, "Vol_SMA50"]) * 2.5   # cond3
        df.at[last, "CMF"]        = 0.20                     # cond4 (also bonus)
        df.at[prev, "MFI"]        = 60.0
        df.at[last, "MFI"]        = 85.0                     # cond5 (>50 and rising)
        # Prevent head-fake (bbw must expand vs 6m min)
        df.at[last, "BBW"]        = float(df.at[last, "BBW_6M_Min"]) * 1.20
        # Suppress upper-wick rejection: make close at/near high
        df.at[last, "High"]       = df.at[last, "Close"] + 0.1
        df.at[last, "Open"]       = df.at[last, "Close"] - 1.0
        df.at[last, "Low"]        = df.at[last, "Open"]  - 0.1
        return df

    def test_all_five_conditions_green_fires_buy(self):
        df = self._build_buy_ready_df()
        sig = analyze_signals("TEST", df)
        self.assertTrue(sig.cond1_squeeze_on,    "cond1 squeeze_on must be True")
        self.assertTrue(sig.cond2_price_above,   "cond2 price>upper must be True")
        self.assertTrue(sig.cond3_volume_ok,     "cond3 volume must be True")
        self.assertTrue(sig.cond4_cmf_positive,  "cond4 cmf>0 must be True")
        self.assertTrue(sig.cond5_mfi_above_50,  "cond5 mfi>50&rising must be True")
        self.assertFalse(sig.head_fake,          "head-fake must be False")
        self.assertTrue(sig.buy_signal,
            "BUY must fire when all 5 conditions GREEN and head_fake=False")

    def test_missing_squeeze_kills_buy(self):
        """Bollinger Ch.15: the SQUEEZE is the precondition. Without it, no BUY."""
        df = self._build_buy_ready_df()
        df = _force_row(df, -1, Squeeze_ON=False)
        sig = analyze_signals("TEST", df)
        self.assertFalse(sig.cond1_squeeze_on)
        self.assertFalse(sig.buy_signal, "BUY must NOT fire without an active Squeeze")

    def test_missing_price_breakout_kills_buy(self):
        """Close must be above the upper band."""
        df = self._build_buy_ready_df()
        bb_upper = float(df["BB_Upper"].iloc[-1])
        df = _force_row(df, -1, Close=bb_upper - 0.5)
        sig = analyze_signals("TEST", df)
        self.assertFalse(sig.cond2_price_above)
        self.assertFalse(sig.buy_signal, "BUY must NOT fire without a close above upper")

    def test_missing_volume_confirmation_kills_buy(self):
        """Volume must be above 50-SMA AND it must be a green candle."""
        df = self._build_buy_ready_df()
        df = _force_row(df, -1, Volume=float(df["Vol_SMA50"].iloc[-1]) * 0.5)   # below SMA
        sig = analyze_signals("TEST", df)
        self.assertFalse(sig.cond3_volume_ok)
        self.assertFalse(sig.buy_signal, "BUY must NOT fire without volume confirmation")

    def test_missing_cmf_positive_kills_buy(self):
        """CMF must be > 0 (institutional accumulation). This is the condition
        the holiday-bar bug had silently suppressed."""
        df = self._build_buy_ready_df()
        df = _force_row(df, -1, CMF=-0.05)
        sig = analyze_signals("TEST", df)
        self.assertFalse(sig.cond4_cmf_positive)
        self.assertFalse(sig.buy_signal, "BUY must NOT fire when CMF is not positive")

    def test_missing_mfi_above_50_kills_buy(self):
        """MFI must be > 50 AND rising vs previous bar."""
        df = self._build_buy_ready_df()
        df = _force_row(df, -1, MFI=45.0)
        sig = analyze_signals("TEST", df)
        self.assertFalse(sig.cond5_mfi_above_50)
        self.assertFalse(sig.buy_signal, "BUY must NOT fire when MFI ≤ 50")

    def test_mfi_above_50_but_not_rising_kills_buy(self):
        """MFI 'above 50' alone is not enough — the book also requires rising MFI
        (breakout fuel is INCREASING)."""
        df = self._build_buy_ready_df()
        # prev MFI > current MFI (still > 50, but falling)
        df = _force_row(df, -2, MFI=90.0)
        df = _force_row(df, -1, MFI=85.0)
        sig = analyze_signals("TEST", df)
        self.assertFalse(sig.cond5_mfi_above_50, "Falling MFI must invalidate cond5")
        self.assertFalse(sig.buy_signal)


class TestM1SqueezeSellStrict(unittest.TestCase):
    """Book Ch.16 short side: SELL requires squeeze + price<lower
    + red candle on volume + II% negative + MFI < 50."""

    def _build_sell_ready_df(self):
        df = _synth_df(n=80, drift=0.0, hl_spread=2.0)
        last = df.index[-1]
        prev = df.index[-2]
        bb_lower = float(df.at[last, "BB_Lower"])
        df.at[prev, "Close"]      = bb_lower + 1.0
        df.at[last, "Close"]      = bb_lower - 5.0           # below lower (cond_short_price)
        df.at[last, "Squeeze_ON"] = True                     # cond_short_squeeze
        df.at[last, "Volume"]     = float(df.at[last, "Vol_SMA50"]) * 2.5  # cond_short_volume
        df.at[last, "II_Pct"]     = -0.15                    # cond_short_ii_neg
        df.at[last, "MFI"]        = 25.0                     # cond_short_mfi_low (<50)
        return df

    def test_all_five_short_conditions_fire_short_signal(self):
        df = self._build_sell_ready_df()
        sig = analyze_signals("TEST", df)
        self.assertTrue(sig.cond_short_squeeze)
        self.assertTrue(sig.cond_short_price)
        self.assertTrue(sig.cond_short_volume)
        self.assertTrue(sig.cond_short_ii_neg)
        self.assertTrue(sig.cond_short_mfi_low)
        self.assertTrue(sig.short_signal, "SHORT must fire when all 5 short conditions met")

    def test_short_requires_squeeze(self):
        df = self._build_sell_ready_df()
        df = _force_row(df, -1, Squeeze_ON=False)
        sig = analyze_signals("TEST", df)
        self.assertFalse(sig.short_signal)

    def test_short_requires_ii_pct_negative(self):
        """Book Ch.18: II% < 0 = institutional distribution."""
        df = self._build_sell_ready_df()
        df = _force_row(df, -1, II_Pct=0.05)
        sig = analyze_signals("TEST", df)
        self.assertFalse(sig.short_signal)

    def test_short_requires_mfi_below_50(self):
        df = self._build_sell_ready_df()
        df = _force_row(df, -1, MFI=60.0)
        sig = analyze_signals("TEST", df)
        self.assertFalse(sig.short_signal)


# ═══════════════════════════════════════════════════════════════
#  M2 — TREND FOLLOWING (Book Ch. 19 p.155)
#  STRICT RULE: BUY ↔ %b > 0.8 AND MFI > 80 (+ volume confirm).
# ═══════════════════════════════════════════════════════════════
class TestM2TrendFollowingStrict(unittest.TestCase):
    """Book p.155: 'Buy when %b > 0.8 and MFI > 80; sell when %b < 0.2
    and MFI < 20.' Strictly enforce both thresholds."""

    def _build_m2_buy_ready(self):
        df = _synth_df(n=80, drift=0.5)
        last = df.index[-1]
        prev = df.index[-2]
        df.at[prev, "Percent_B"] = 0.70
        df.at[prev, "MFI"]       = 75.0
        df.at[last, "Percent_B"] = 0.90              # > 0.8
        df.at[last, "MFI"]       = 85.0              # > 80
        df.at[last, "Volume"]    = float(df.at[last, "Vol_SMA50"]) * 2.0
        df.at[last, "CMF"]       = 0.15              # positive (checklist item)
        return df

    def test_strict_buy_fires_when_pct_b_above_080_and_mfi_above_80(self):
        df = self._build_m2_buy_ready()
        r = _method_ii_trend_following(df)
        self.assertEqual(r.signal.signal_type, "BUY",
            "M2 BUY must fire on %b > 0.8 + MFI > 80 per book p.155")

    def test_pct_b_at_080_exactly_does_not_fire(self):
        """The book says > 0.8, NOT >= 0.8. Strict greater-than."""
        df = self._build_m2_buy_ready()
        df = _force_row(df, -1, Percent_B=M2_PCT_B_BUY_THRESHOLD)   # == 0.8
        r = _method_ii_trend_following(df)
        self.assertNotEqual(r.signal.signal_type, "BUY",
            "M2 BUY must NOT fire at %b == 0.8 exactly (book says > 0.8)")

    def test_mfi_below_80_invalidates_buy_even_with_high_pct_b(self):
        """%b > 0.8 alone is NOT enough — MFI must also confirm > 80."""
        df = self._build_m2_buy_ready()
        df = _force_row(df, -1, MFI=75.0)
        r = _method_ii_trend_following(df)
        self.assertNotEqual(r.signal.signal_type, "BUY",
            "M2 BUY must NOT fire when MFI ≤ 80 (no MFI compromise)")

    def test_pct_b_below_080_invalidates_buy_even_with_high_mfi(self):
        df = self._build_m2_buy_ready()
        df = _force_row(df, -1, Percent_B=0.75)
        r = _method_ii_trend_following(df)
        self.assertNotEqual(r.signal.signal_type, "BUY",
            "M2 BUY must NOT fire when %b ≤ 0.8 (no %b compromise)")

    def test_low_volume_invalidates_buy(self):
        """Volume must confirm the move (vol > 50-SMA)."""
        df = self._build_m2_buy_ready()
        df = _force_row(df, -1, Volume=float(df["Vol_SMA50"].iloc[-1]) * 0.5)
        r = _method_ii_trend_following(df)
        self.assertNotEqual(r.signal.signal_type, "BUY",
            "M2 BUY must NOT fire on low volume (volume_confirm required)")

    def test_bearish_divergence_invalidates_buy(self):
        """Book: 'When %b and MFI disagree, believe MFI.' If %b rises but MFI
        falls (bearish divergence), BUY must NOT fire."""
        df = self._build_m2_buy_ready()
        # Make MFI fall while %b still rising
        df = _force_row(df, -2, Percent_B=0.80, MFI=95.0)
        df = _force_row(df, -1, Percent_B=0.90, MFI=85.0)    # %b ↑, MFI ↓
        r = _method_ii_trend_following(df)
        self.assertNotEqual(r.signal.signal_type, "BUY",
            "M2 BUY must NOT fire under bearish %b/MFI divergence")


class TestM2SellStrict(unittest.TestCase):
    def _build_m2_sell_ready(self):
        df = _synth_df(n=80, drift=-0.5)
        last = df.index[-1]
        df.at[last, "Percent_B"] = 0.10              # < 0.2
        df.at[last, "MFI"]       = 15.0              # < 20
        df.at[last, "BB_Mid"]    = float(df.at[last, "Close"]) + 5.0   # close < mid
        return df

    def test_strict_sell_fires_when_pct_b_below_020_and_mfi_below_20(self):
        df = self._build_m2_sell_ready()
        r = _method_ii_trend_following(df)
        self.assertEqual(r.signal.signal_type, "SELL",
            "M2 SELL must fire on %b < 0.2 + MFI < 20 per book p.155")

    def test_pct_b_at_020_does_not_fire_sell(self):
        """Strict less-than."""
        df = self._build_m2_sell_ready()
        df = _force_row(df, -1, Percent_B=M2_PCT_B_SELL_THRESHOLD)   # == 0.2
        r = _method_ii_trend_following(df)
        self.assertNotEqual(r.signal.signal_type, "SELL")

    def test_mfi_at_or_above_20_does_not_fire_sell(self):
        df = self._build_m2_sell_ready()
        df = _force_row(df, -1, MFI=25.0)
        r = _method_ii_trend_following(df)
        self.assertNotEqual(r.signal.signal_type, "SELL")


# ═══════════════════════════════════════════════════════════════
#  M3 — REVERSALS (Book Ch. 17/20: W-Bottom / M-Top)
#  STRICT RULE: %b structure must match book; separation in range;
#  price levels honored.
# ═══════════════════════════════════════════════════════════════
class TestM3WBottomStrict(unittest.TestCase):
    """Book W-Bottom: first low at lower band (%b ≤ 0.05), second low
    holds above lower band (%b > 0.2), price ≥ first within tolerance."""

    def _build_w_bottom_df(self, sep=12):
        """Construct a clean W-Bottom on synthetic OHLCV."""
        n = 60
        close = np.full(n, 100.0)
        # Drift gently
        for i in range(n):
            close[i] = 100.0 - 0.05 * i
        # Two depressed lows positioned in the recent window
        first_idx  = n - sep - 5
        second_idx = n - 5
        close[first_idx-1:first_idx+2] = [95.0, 92.0, 95.0]
        close[second_idx-1:second_idx+2] = [97.0, 94.0, 97.0]
        # Final bar recovery so window ends after second low
        for i in range(second_idx + 2, n):
            close[i] = 98.0 + 0.2 * (i - second_idx)
        df_raw = pd.DataFrame({
            "Date": pd.date_range("2025-01-01", periods=n, freq="B").strftime("%Y-%m-%d"),
            "Open": close,
            "High": close + 1.0,
            "Low":  close - 1.0,
            "Close": close,
            "Volume": np.full(n, 1_000_000.0),
        })
        df = compute_all_indicators(df_raw)
        # Force %b values to enforce W shape exactly per book
        df.at[df.index[first_idx],  "Percent_B"] = -0.05   # at/below lower
        df.at[df.index[first_idx],  "MFI"]       = 25.0
        df.at[df.index[second_idx], "Percent_B"] = 0.35    # ABOVE lower
        df.at[df.index[second_idx], "MFI"]       = 45.0    # MFI diverged up
        return df, first_idx, second_idx

    def test_canonical_w_bottom_is_detected(self):
        df, _, _ = self._build_w_bottom_df(sep=12)
        patterns = _detect_w_bottoms(df, lookback=M3_W_LOOKBACK)
        self.assertGreater(len(patterns), 0,
            "Canonical W-Bottom (first low %b≤0, second low %b>0.2) must be detected")
        self.assertTrue(all(p.name == "W-BOTTOM" for p in patterns))

    def test_w_bottom_requires_first_low_at_lower_band(self):
        """If the first low's %b is well above 0, it is NOT a W-Bottom."""
        df, first_idx, _ = self._build_w_bottom_df(sep=12)
        df = _force_row(df, first_idx, Percent_B=0.40)   # first low NOT at lower band
        patterns = _detect_w_bottoms(df, lookback=M3_W_LOOKBACK)
        self.assertEqual(len(patterns), 0,
            "W-Bottom requires first low %b ≤ 0.05 — must NOT match without it")

    def test_w_bottom_requires_second_low_above_lower_band(self):
        """If the second low is still tagging the lower band, NOT a W-Bottom."""
        df, _, second_idx = self._build_w_bottom_df(sep=12)
        df = _force_row(df, second_idx, Percent_B=-0.10)   # also at/below lower
        patterns = _detect_w_bottoms(df, lookback=M3_W_LOOKBACK)
        self.assertEqual(len(patterns), 0,
            "W-Bottom requires second low %b > 0.2 — must NOT match without it")

    def test_w_bottom_respects_minimum_separation(self):
        """Two lows too close together (< M3_W_MIN_SEPARATION) are not a W."""
        df, _, _ = self._build_w_bottom_df(sep=max(M3_W_MIN_SEPARATION - 2, 1))
        patterns = _detect_w_bottoms(df, lookback=M3_W_LOOKBACK)
        self.assertEqual(len(patterns), 0,
            f"W-Bottom requires ≥ {M3_W_MIN_SEPARATION} bars between lows")


class TestM3MTopStrict(unittest.TestCase):
    """Book M-Top: first high at upper band (%b ≥ 1), second high below
    (%b < 0.8), MFI diverged down."""

    def _build_m_top_df(self, sep=12):
        n = 60
        close = np.full(n, 100.0)
        for i in range(n):
            close[i] = 100.0 + 0.05 * i
        first_idx  = n - sep - 5
        second_idx = n - 5
        close[first_idx-1:first_idx+2]  = [108.0, 110.0, 108.0]
        close[second_idx-1:second_idx+2]= [106.0, 109.0, 106.0]
        for i in range(second_idx + 2, n):
            close[i] = 105.0 - 0.2 * (i - second_idx)
        df_raw = pd.DataFrame({
            "Date": pd.date_range("2025-01-01", periods=n, freq="B").strftime("%Y-%m-%d"),
            "Open": close,
            "High": close + 1.0,
            "Low":  close - 1.0,
            "Close": close,
            "Volume": np.full(n, 1_000_000.0),
        })
        df = compute_all_indicators(df_raw)
        df.at[df.index[first_idx],  "Percent_B"] = 1.05    # at/above upper
        df.at[df.index[first_idx],  "MFI"]       = 80.0
        df.at[df.index[second_idx], "Percent_B"] = 0.70    # BELOW upper
        df.at[df.index[second_idx], "MFI"]       = 60.0    # MFI diverged down
        return df, first_idx, second_idx

    def test_canonical_m_top_is_detected(self):
        df, _, _ = self._build_m_top_df(sep=12)
        patterns = _detect_m_tops(df, lookback=M3_W_LOOKBACK)
        self.assertGreater(len(patterns), 0,
            "Canonical M-Top (first high %b≥1, second high %b<0.8) must be detected")
        self.assertTrue(all(p.name == "M-TOP" for p in patterns))

    def test_m_top_requires_first_high_at_upper_band(self):
        df, first_idx, _ = self._build_m_top_df(sep=12)
        df = _force_row(df, first_idx, Percent_B=0.65)
        patterns = _detect_m_tops(df, lookback=M3_W_LOOKBACK)
        self.assertEqual(len(patterns), 0,
            "M-Top requires first high %b ≥ ~1.0 — must NOT match without it")

    def test_m_top_requires_second_high_below_upper_band(self):
        df, _, second_idx = self._build_m_top_df(sep=12)
        df = _force_row(df, second_idx, Percent_B=1.10)   # still tagging upper
        patterns = _detect_m_tops(df, lookback=M3_W_LOOKBACK)
        self.assertEqual(len(patterns), 0,
            "M-Top requires second high %b < ~0.8 — must NOT match without it")


# ═══════════════════════════════════════════════════════════════
#  M4 — WALKING THE BANDS (Book Ch. 18)
#  STRICT RULE: ALL three book rules required for a band walk.
# ═══════════════════════════════════════════════════════════════
class TestM4WalkingTheBandsStrict(unittest.TestCase):
    """A walk requires ALL of:
       Rule 1 — ≥3 closes within 0.5% of upper band (or beyond)
       Rule 2 — ≥60% of the 10-bar window with %b ≥ 0.85
       Rule 3 — every close at or above the middle band
    Strip any single rule → no walk."""

    def _build_upper_walk_df(self):
        """Hand-constructed 10-bar upper walk satisfying all three rules."""
        n = M4_WALK_LOOKBACK + 30      # extra context for indicators
        close = np.full(n, 100.0)
        for i in range(n - 10):
            close[i] = 95.0 + 0.05 * i
        # Last 10 bars: close hugs and exceeds the (upcoming) upper band
        for i in range(10):
            close[n - 10 + i] = 110.0 + 0.5 * i
        df_raw = pd.DataFrame({
            "Date": pd.date_range("2025-01-01", periods=n, freq="B").strftime("%Y-%m-%d"),
            "Open": close,
            "High": close + 0.3,
            "Low":  close - 0.3,
            "Close": close,
            "Volume": np.full(n, 1_000_000.0),
        })
        df = compute_all_indicators(df_raw)

        # Force the last 10 bars: close is on the upper band, %b extreme, mid below
        for k in range(M4_WALK_LOOKBACK):
            i = df.index[-M4_WALK_LOOKBACK + k]
            df.at[i, "BB_Upper"]  = df.at[i, "Close"]            # exact tag
            df.at[i, "BB_Mid"]    = df.at[i, "Close"] - 5.0      # close above mid
            df.at[i, "BB_Lower"]  = df.at[i, "Close"] - 10.0
            df.at[i, "Percent_B"] = 0.95                          # ≥ 0.85
        return df

    def test_canonical_upper_walk_is_detected(self):
        df = self._build_upper_walk_df()
        walk = _detect_band_walk(df, "upper", lookback=M4_WALK_LOOKBACK)
        self.assertIsNotNone(walk, "Canonical upper band walk must be detected")
        self.assertEqual(walk.name, "WALK-UPPER")

    def test_upper_walk_rejected_when_touch_count_too_low(self):
        """Strip Rule 1: pull last 8 closes well below the band → only 2 tags
        remain. Walk must NOT register."""
        df = self._build_upper_walk_df()
        n = len(df)
        for k in range(2, M4_WALK_LOOKBACK):
            i = df.index[n - M4_WALK_LOOKBACK + k]
            df.at[i, "Close"] = float(df.at[i, "BB_Upper"]) * 0.92   # far below band
        walk = _detect_band_walk(df, "upper", lookback=M4_WALK_LOOKBACK)
        self.assertIsNone(walk,
            f"Upper walk must NOT fire with < {M4_WALK_MIN_TOUCHES} tags (Rule 1)")

    def test_upper_walk_rejected_when_zone_consistency_too_low(self):
        """Strip Rule 2: keep tags but drop %b across most bars → ZONE rule fails."""
        df = self._build_upper_walk_df()
        n = len(df)
        # Drop %b on 7/10 bars below the zone threshold
        for k in range(M4_WALK_LOOKBACK - 3):
            i = df.index[n - M4_WALK_LOOKBACK + k]
            df.at[i, "Percent_B"] = M4_WALK_PCT_B_UPPER - 0.1
        walk = _detect_band_walk(df, "upper", lookback=M4_WALK_LOOKBACK)
        self.assertIsNone(walk,
            f"Upper walk must NOT fire when zone < {M4_WALK_ZONE_CONSISTENCY*100:.0f}% (Rule 2)")

    def test_upper_walk_rejected_when_middle_band_breached(self):
        """Strip Rule 3: drop one close below the middle band → walk dies."""
        if not M4_WALK_BB_MID_PULLBACK:
            self.skipTest("Rule 3 (middle-band support) is disabled in config")
        df = self._build_upper_walk_df()
        # Push one close clearly below its BB_Mid
        i = df.index[-3]
        df.at[i, "Close"] = float(df.at[i, "BB_Mid"]) - 1.0
        walk = _detect_band_walk(df, "upper", lookback=M4_WALK_LOOKBACK)
        self.assertIsNone(walk,
            "Upper walk must NOT survive a close that breaches the middle band (Rule 3)")


class TestM4LowerWalkStrict(unittest.TestCase):
    def _build_lower_walk_df(self):
        n = M4_WALK_LOOKBACK + 30
        close = np.full(n, 100.0)
        for i in range(n - 10):
            close[i] = 105.0 - 0.05 * i
        for i in range(10):
            close[n - 10 + i] = 90.0 - 0.5 * i
        df_raw = pd.DataFrame({
            "Date": pd.date_range("2025-01-01", periods=n, freq="B").strftime("%Y-%m-%d"),
            "Open": close, "High": close + 0.3, "Low": close - 0.3,
            "Close": close, "Volume": np.full(n, 1_000_000.0),
        })
        df = compute_all_indicators(df_raw)
        for k in range(M4_WALK_LOOKBACK):
            i = df.index[-M4_WALK_LOOKBACK + k]
            df.at[i, "BB_Lower"]  = df.at[i, "Close"]            # exact tag
            df.at[i, "BB_Mid"]    = df.at[i, "Close"] + 5.0      # close below mid
            df.at[i, "BB_Upper"]  = df.at[i, "Close"] + 10.0
            df.at[i, "Percent_B"] = 0.05                          # ≤ 0.15
        return df

    def test_canonical_lower_walk_is_detected(self):
        df = self._build_lower_walk_df()
        walk = _detect_band_walk(df, "lower", lookback=M4_WALK_LOOKBACK)
        self.assertIsNotNone(walk, "Canonical lower band walk must be detected")
        self.assertEqual(walk.name, "WALK-LOWER")

    def test_lower_walk_rejected_when_middle_band_breached(self):
        if not M4_WALK_BB_MID_PULLBACK:
            self.skipTest("Rule 3 disabled")
        df = self._build_lower_walk_df()
        i = df.index[-3]
        df.at[i, "Close"] = float(df.at[i, "BB_Mid"]) + 1.0       # close ABOVE mid
        walk = _detect_band_walk(df, "lower", lookback=M4_WALK_LOOKBACK)
        self.assertIsNone(walk,
            "Lower walk must NOT survive a close that breaches the middle band (Rule 3)")


# ═══════════════════════════════════════════════════════════════
#  STRATEGY CONFIG INVARIANTS — lock down the book thresholds
# ═══════════════════════════════════════════════════════════════
class TestStrategyConfigLockdown(unittest.TestCase):
    """Block silent drift of the canonical method thresholds."""

    def test_m2_buy_thresholds_match_book_p155(self):
        self.assertAlmostEqual(M2_PCT_B_BUY_THRESHOLD, 0.8, places=8)
        self.assertEqual(M2_MFI_CONFIRM_BUY, 80)

    def test_m2_sell_thresholds_match_book_p155(self):
        self.assertAlmostEqual(M2_PCT_B_SELL_THRESHOLD, 0.2, places=8)
        self.assertEqual(M2_MFI_CONFIRM_SELL, 20)

    def test_m3_w_bottom_thresholds_match_book(self):
        """Book Ch.17: first low at/below lower band, second above."""
        self.assertLessEqual(M3_W_FIRST_LOW_PCT_B, 0.05)
        self.assertGreaterEqual(M3_W_SECOND_LOW_PCT_B, 0.15)
        self.assertGreater(M3_W_SECOND_LOW_PCT_B, M3_W_FIRST_LOW_PCT_B)

    def test_m3_m_top_thresholds_match_book(self):
        self.assertGreaterEqual(M3_M_FIRST_HIGH_PCT_B, 0.95)
        self.assertLess(M3_M_SECOND_HIGH_PCT_B, M3_M_FIRST_HIGH_PCT_B)

    def test_m4_walk_rules_match_book_ch18(self):
        """Ch.18: ≥3 tags in 10 bars, %b ≥ 0.85 / ≤ 0.15, mid held."""
        self.assertEqual(M4_WALK_MIN_TOUCHES, 3)
        self.assertEqual(M4_WALK_LOOKBACK, 10)
        self.assertAlmostEqual(M4_WALK_TOUCH_TOLERANCE, 0.005, places=8)
        self.assertGreaterEqual(M4_WALK_PCT_B_UPPER, 0.80)
        self.assertLessEqual(M4_WALK_PCT_B_LOWER, 0.20)
        self.assertGreaterEqual(M4_WALK_ZONE_CONSISTENCY, 0.5)


# ═══════════════════════════════════════════════════════════════
#  M1 HEAD-FAKE DETECTION (signals.py:_head_fake_check)
#  Strategy guide: 5 sub-signals; ≥ 2 of them = likely head fake → cancel BUY.
# ═══════════════════════════════════════════════════════════════
class TestM1HeadFakeDetection(unittest.TestCase):
    """The head-fake filter cancels a M1 BUY when ≥ 2 of these fire:
       1. Volume below 50-SMA
       2. CMF negative on upside breakout
       3. MFI < 50 on upside breakout
       4. BBW not expanding after the breakout (< 1.02 × 6-month min)
       5. Long upper wick rejection (> 60% of candle range)
    """

    def _clean_breakout_row(self):
        """A clean, healthy breakout row: NO head-fake signals fire."""
        return pd.Series({
            "Close":      105.0,
            "High":       105.5,
            "Low":        100.0,
            "Open":       101.0,
            "BB_Upper":   103.0,           # close > upper → breakout
            "Volume":     2_000_000.0,
            "Vol_SMA50":  1_000_000.0,     # vol well above SMA
            "CMF":        0.20,            # positive
            "MFI":        85.0,            # > 50
            "BBW":        0.20,            # well expanded
            "BBW_6M_Min": 0.05,            # bbw ÷ min = 4.0 >> 1.02
        })

    def test_clean_breakout_is_not_head_fake(self):
        self.assertFalse(_head_fake_check(self._clean_breakout_row()),
            "Healthy breakout (high vol, positive CMF, MFI>50, bands expanding, "
            "no wick rejection) must NOT trigger head-fake")

    # ── Each individual signal alone is NOT enough (threshold is ≥ 2) ──

    def test_low_volume_alone_is_not_head_fake(self):
        """Signal 1 alone (vol < SMA) — needs another signal to trigger."""
        row = self._clean_breakout_row()
        row["Volume"] = 500_000.0           # below SMA
        self.assertFalse(_head_fake_check(row),
            "Single signal (low volume) must not by itself trigger head-fake")

    def test_negative_cmf_alone_is_not_head_fake(self):
        row = self._clean_breakout_row()
        row["CMF"] = -0.05
        self.assertFalse(_head_fake_check(row))

    def test_low_mfi_alone_is_not_head_fake(self):
        row = self._clean_breakout_row()
        row["MFI"] = 45.0
        self.assertFalse(_head_fake_check(row))

    # ── Two signals together → head-fake fires ──

    def test_low_volume_plus_negative_cmf_triggers_head_fake(self):
        """Signals 1 + 2 — classic distribution breakout."""
        row = self._clean_breakout_row()
        row["Volume"] = 500_000.0
        row["CMF"]    = -0.05
        self.assertTrue(_head_fake_check(row),
            "Low volume + negative CMF on breakout is the textbook head-fake pattern")

    def test_low_volume_plus_low_mfi_triggers_head_fake(self):
        row = self._clean_breakout_row()
        row["Volume"] = 500_000.0
        row["MFI"]    = 45.0
        self.assertTrue(_head_fake_check(row))

    def test_negative_cmf_plus_low_mfi_triggers_head_fake(self):
        row = self._clean_breakout_row()
        row["CMF"] = -0.05
        row["MFI"] = 45.0
        self.assertTrue(_head_fake_check(row))

    def test_non_expanding_bbw_plus_low_volume_triggers_head_fake(self):
        """Signals 4 + 1 — fake breakout without volatility expansion."""
        row = self._clean_breakout_row()
        row["BBW"]        = 0.05            # ≈ 6-month min (not expanding)
        row["BBW_6M_Min"] = 0.05
        row["Volume"]     = 500_000.0
        self.assertTrue(_head_fake_check(row))

    def test_long_upper_wick_plus_low_volume_triggers_head_fake(self):
        """Signal 5 + 1 — pierce-and-reject candle on weak volume."""
        row = self._clean_breakout_row()
        # Construct a long-upper-wick candle: high 115, body topping at 102 → wick 13/14 ≈ 93%
        row["Open"]  = 101.0
        row["Close"] = 102.0
        row["Low"]   = 101.0
        row["High"]  = 115.0
        row["Volume"] = 500_000.0
        # Verify the wick math is what we expect
        wick = row["High"] - max(row["Open"], row["Close"])
        rng  = row["High"] - row["Low"]
        self.assertGreater(wick / rng, 0.6, "Test data must produce > 60% upper wick")
        self.assertTrue(_head_fake_check(row))

    def test_head_fake_cancels_m1_buy_in_full_pipeline(self):
        """End-to-end: build a row that satisfies all 5 M1 BUY conditions,
        then add 2 head-fake signals — buy_signal must flip to False."""
        # Use the strict-buy fixture, then poison it with 2 head-fake signals
        helper = TestM1SqueezeBuyStrict()
        df = helper._build_buy_ready_df()
        df = _force_row(df, -1,
                        CMF=-0.05,                    # head-fake signal 2
                        Volume=float(df["Vol_SMA50"].iloc[-1]) * 0.5)  # head-fake signal 1
        sig = analyze_signals("TEST", df)
        self.assertTrue(sig.head_fake,
            "≥2 head-fake signals must set head_fake=True")
        self.assertFalse(sig.buy_signal,
            "head_fake=True must cancel M1 BUY even if other conditions look OK")


# ═══════════════════════════════════════════════════════════════
#  M4 DIP-BUY / RALLY-SELL DURING ACTIVE WALK (Book Ch. 18 rule 4b)
#  Strict rule: BUY only when active upper walk + %b in dip zone +
#  SAR bullish + MFI > 50.  Mirror for lower walk SELL.
# ═══════════════════════════════════════════════════════════════
class TestM4DipBuyDuringActiveWalk(unittest.TestCase):
    """Book Ch.18 add-on entry: during an active upper band walk,
    a pullback toward the middle band (%b in [DIP_MIN, DIP_MAX])
    with SAR bullish and MFI > 50 is the textbook BUY add-on.
    All 4 sub-conditions are strict."""

    def _build_active_upper_walk_with_dip(self):
        """Build a confirmed upper walk where the LAST bar has pulled back
        into the dip zone with SAR bullish and MFI > 50."""
        walk_helper = TestM4WalkingTheBandsStrict()
        df = walk_helper._build_upper_walk_df()
        # Last bar is the "dip" — %b drops to the middle of the dip zone,
        # SAR is bullish, MFI > 50.
        last = df.index[-1]
        df.at[last, "Percent_B"] = (M4_WALK_DIP_BUY_PCT_B_MIN
                                     + M4_WALK_DIP_BUY_PCT_B_MAX) / 2.0
        df.at[last, "SAR_Bull"]  = True
        df.at[last, "MFI"]       = 65.0
        return df

    def test_dip_buy_fires_when_all_four_conditions_met(self):
        df = self._build_active_upper_walk_with_dip()
        r = _method_iv_walking_the_bands(df)
        self.assertEqual(r.signal.signal_type, "BUY",
            "M4 dip-buy must fire: active upper walk + %b in dip zone + "
            "SAR bullish + MFI > 50")

    def test_dip_buy_rejected_when_no_active_walk(self):
        """If there's no upper walk at all, dip-buy must NOT fire — even
        if the standalone conditions (%b zone, SAR, MFI) look fine."""
        df = _synth_df(n=80)
        last = df.index[-1]
        df.at[last, "Percent_B"] = (M4_WALK_DIP_BUY_PCT_B_MIN
                                     + M4_WALK_DIP_BUY_PCT_B_MAX) / 2.0
        df.at[last, "SAR_Bull"]  = True
        df.at[last, "MFI"]       = 65.0
        r = _method_iv_walking_the_bands(df)
        self.assertNotEqual(r.signal.signal_type, "BUY",
            "Dip-buy must NOT fire without a confirmed active upper walk")

    def test_dip_buy_rejected_when_pct_b_above_dip_ceiling(self):
        """%b above DIP_MAX → still in HOLD zone, not dip — no add-on entry."""
        df = self._build_active_upper_walk_with_dip()
        df = _force_row(df, -1,
                        Percent_B=M4_WALK_DIP_BUY_PCT_B_MAX + 0.05)
        r = _method_iv_walking_the_bands(df)
        # In this zone the method emits HOLD (still walking), NOT BUY
        self.assertNotEqual(r.signal.signal_type, "BUY",
            "Dip-buy must NOT fire when %b is above the dip-zone ceiling")

    def test_dip_buy_rejected_when_pct_b_below_dip_floor(self):
        """%b below DIP_MIN → walk has broken (close fell to/under mid) — book
        rule says SELL, not BUY."""
        df = self._build_active_upper_walk_with_dip()
        df = _force_row(df, -1,
                        Percent_B=M4_WALK_DIP_BUY_PCT_B_MIN - 0.10)
        r = _method_iv_walking_the_bands(df)
        self.assertNotEqual(r.signal.signal_type, "BUY",
            "Dip-buy must NOT fire when price has broken below the dip zone")

    def test_dip_buy_rejected_when_sar_not_bullish(self):
        """SAR flipped bearish → trend confirmation lost — no add-on."""
        df = self._build_active_upper_walk_with_dip()
        df = _force_row(df, -1, SAR_Bull=False)
        r = _method_iv_walking_the_bands(df)
        self.assertNotEqual(r.signal.signal_type, "BUY",
            "Dip-buy must NOT fire when SAR has flipped bearish")

    def test_dip_buy_rejected_when_mfi_not_above_50(self):
        """MFI ≤ 50 → money flow not supporting → no add-on."""
        df = self._build_active_upper_walk_with_dip()
        df = _force_row(df, -1, MFI=45.0)
        r = _method_iv_walking_the_bands(df)
        self.assertNotEqual(r.signal.signal_type, "BUY",
            "Dip-buy must NOT fire when MFI ≤ 50")


# ═══════════════════════════════════════════════════════════════
#  TOP PICKS STRICT CHECKLIST (top_picks/engine.py)
#  The final filter before Top 5 — must reject any pick missing
#  even ONE of the method's canonical conditions.
# ═══════════════════════════════════════════════════════════════
class TestTopPicksStrictFilter(unittest.TestCase):
    """Stage-5 strict filter must enforce: ALL conditions for the method
    + direction must be True. No 4-of-5 compromise can slip through."""

    # ── M1 BUY: requires all 5 BB conditions ──

    def _m1_buy_pick_all_green(self):
        return {
            "bb_conditions": {
                "squeeze":         True,
                "price_breakout":  True,
                "volume_confirm":  True,
                "cmf_positive":    True,
                "mfi_above_50":    True,
            }
        }

    def test_m1_buy_all_green_passes(self):
        self.assertTrue(
            pick_passes_strict_checklist(self._m1_buy_pick_all_green(), "M1", "BUY"),
            "M1 BUY pick with all 5 conditions green must pass the strict filter")

    def test_m1_buy_drops_pick_missing_squeeze(self):
        pick = self._m1_buy_pick_all_green()
        pick["bb_conditions"]["squeeze"] = False
        self.assertFalse(pick_passes_strict_checklist(pick, "M1", "BUY"),
            "M1 BUY without an active squeeze must be rejected")

    def test_m1_buy_drops_pick_missing_cmf_positive(self):
        """The CMF holiday-bar bug we fixed — make sure the strict filter
        would have caught it even if the indicator had failed."""
        pick = self._m1_buy_pick_all_green()
        pick["bb_conditions"]["cmf_positive"] = False
        self.assertFalse(pick_passes_strict_checklist(pick, "M1", "BUY"))

    def test_m1_buy_drops_pick_missing_any_single_condition(self):
        """Iterate: flip each of the 5 conditions off one at a time — every
        single one must independently cause rejection (no 4/5 acceptance)."""
        keys = ["squeeze","price_breakout","volume_confirm","cmf_positive","mfi_above_50"]
        for k in keys:
            with self.subTest(missing=k):
                pick = self._m1_buy_pick_all_green()
                pick["bb_conditions"][k] = False
                self.assertFalse(pick_passes_strict_checklist(pick, "M1", "BUY"),
                    f"Strict filter must reject when {k}=False")

    # ── M1 SELL: requires all 5 short conditions ──

    def test_m1_sell_requires_all_5_short_conditions(self):
        pick = {"bb_short_conditions": {
            "squeeze":        True,
            "price_below":    True,
            "volume_confirm": True,
            "ii_negative":    True,
            "mfi_low":        True,
        }}
        self.assertTrue(pick_passes_strict_checklist(pick, "M1", "SELL"))
        for k in list(pick["bb_short_conditions"].keys()):
            with self.subTest(missing=k):
                p = {"bb_short_conditions": dict(pick["bb_short_conditions"])}
                p["bb_short_conditions"][k] = False
                self.assertFalse(pick_passes_strict_checklist(p, "M1", "SELL"))

    # ── M2/M3/M4: every item in buy_checklist / sell_checklist must be ok ──

    def _strat_pick(self, code, checklist_key, items):
        """Build a pick dict with a single strategy result + its checklist."""
        return {"bb_strategies": [{
            "code": code,
            "indicators": {checklist_key: [{"ok": v, "name": n} for n, v in items]},
        }]}

    def test_m2_buy_passes_when_all_checklist_items_green(self):
        items = [("%b > 0.8", True), ("MFI > 80", True), ("volume", True),
                 ("no divergence", True), ("CMF > 0", True)]
        pick = self._strat_pick("M2", "buy_checklist", items)
        self.assertTrue(pick_passes_strict_checklist(pick, "M2", "BUY"))

    def test_m2_buy_rejects_when_any_checklist_item_fails(self):
        base = [("%b > 0.8", True), ("MFI > 80", True), ("volume", True),
                ("no divergence", True), ("CMF > 0", True)]
        for i, (name, _) in enumerate(base):
            with self.subTest(failing_item=name):
                items = list(base)
                items[i] = (name, False)        # flip one item to False
                pick = self._strat_pick("M2", "buy_checklist", items)
                self.assertFalse(pick_passes_strict_checklist(pick, "M2", "BUY"),
                    f"Strict filter must reject M2 BUY when {name} fails")

    def test_m3_buy_rejects_when_any_checklist_item_fails(self):
        items = [("W-Bottom present", True), ("MFI divergence", False),
                 ("volume confirm", True)]
        pick = self._strat_pick("M3", "buy_checklist", items)
        self.assertFalse(pick_passes_strict_checklist(pick, "M3", "BUY"))

    def test_m4_buy_rejects_when_any_checklist_item_fails(self):
        items = [("tag count", True), ("zone consistency", True),
                 ("mid held", False)]
        pick = self._strat_pick("M4", "buy_checklist", items)
        self.assertFalse(pick_passes_strict_checklist(pick, "M4", "BUY"))

    def test_missing_method_strategy_means_rejected(self):
        """If the pick doesn't contain a result for the requested method,
        it cannot pass — protects against silently accepting unscored picks."""
        pick = {"bb_strategies": []}
        self.assertFalse(pick_passes_strict_checklist(pick, "M2", "BUY"))
        self.assertFalse(pick_passes_strict_checklist(pick, "M3", "SELL"))
        self.assertFalse(pick_passes_strict_checklist(pick, "M4", "BUY"))

    def test_empty_checklist_is_rejected(self):
        """An empty checklist must not vacuously pass (all([]) == True risk)."""
        pick = self._strat_pick("M2", "buy_checklist", [])
        self.assertFalse(pick_passes_strict_checklist(pick, "M2", "BUY"),
            "Empty checklist must be treated as failure, not vacuous truth")


# ═══════════════════════════════════════════════════════════════
#  END-TO-END: run_all_strategies returns coherent shape
# ═══════════════════════════════════════════════════════════════
class TestStrategyRunner(unittest.TestCase):
    def test_run_all_strategies_returns_m2_m3_m4(self):
        df = _synth_df(n=80)
        results = run_all_strategies(df)
        codes = sorted(r.code for r in results)
        self.assertEqual(codes, ["M2", "M3", "M4"])
        for r in results:
            self.assertIn(r.signal.signal_type, {"BUY","SELL","HOLD","WATCH","NONE"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
