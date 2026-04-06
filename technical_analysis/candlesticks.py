"""
candlesticks.py — Japanese Candlestick Pattern Recognition.

Murphy Ch 12: "Japanese Candlesticks"
Detects 20+ reversal and continuation candlestick patterns.

Every pattern returns:
  - name       : pattern label
  - type       : BULLISH / BEARISH / NEUTRAL
  - strength   : 1-3 (1=weak, 2=moderate, 3=strong)
  - meaning    : plain-English explanation
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from technical_analysis.config import (
    CANDLE_DOJI_THRESHOLD as DOJI_BODY_THRESHOLD,
    CANDLE_LONG_BODY_MULT as LONG_BODY_MULTIPLIER,
    CANDLE_SHADOW_RATIO as SHADOW_RATIO,
    CANDLE_LOOKBACK,
)


# ═══════════════════════════════════════════════════════════════
#  HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def _body(o, c):
    return abs(c - o)


def _upper_shadow(o, c, h):
    return h - max(o, c)


def _lower_shadow(o, c, l):
    return min(o, c) - l


def _is_bullish(o, c):
    return c > o


def _is_bearish(o, c):
    return c < o


def _avg_body(df: pd.DataFrame, idx: int, lookback: int = CANDLE_LOOKBACK) -> float:
    """Average body size over the lookback window ending at idx."""
    start = max(0, idx - lookback)
    bodies = []
    for i in range(start, idx):
        bodies.append(_body(df["Open"].iloc[i], df["Close"].iloc[i]))
    return np.mean(bodies) if bodies else 1.0


def _is_uptrend(df: pd.DataFrame, idx: int, n: int = 10) -> bool:
    """Check if price was generally rising over last n bars."""
    if idx < n:
        return False
    return float(df["Close"].iloc[idx]) > float(df["Close"].iloc[idx - n])


def _is_downtrend(df: pd.DataFrame, idx: int, n: int = 10) -> bool:
    """Check if price was generally falling over last n bars."""
    if idx < n:
        return False
    return float(df["Close"].iloc[idx]) < float(df["Close"].iloc[idx - n])


# ═══════════════════════════════════════════════════════════════
#  SINGLE-CANDLE PATTERNS
# ═══════════════════════════════════════════════════════════════

def _check_doji(o, h, l, c, avg_b) -> str | None:
    """Doji and its variants."""
    body = _body(o, c)
    total_range = h - l
    if total_range == 0:
        return None

    # Body must be very small relative to range
    if body / total_range > DOJI_BODY_THRESHOLD:
        return None

    us = _upper_shadow(o, c, h)
    ls = _lower_shadow(o, c, l)

    if ls > 2 * us and ls > 0.3 * total_range:
        return "DRAGONFLY_DOJI"       # Long lower shadow, bullish
    elif us > 2 * ls and us > 0.3 * total_range:
        return "GRAVESTONE_DOJI"      # Long upper shadow, bearish
    elif us > 0.3 * total_range and ls > 0.3 * total_range:
        return "LONG_LEGGED_DOJI"     # Both shadows long, high indecision
    else:
        return "DOJI"                 # Standard doji


def _check_hammer(o, h, l, c, avg_b, in_downtrend: bool) -> dict | None:
    """Hammer (bullish at bottom) / Hanging Man (bearish at top)."""
    body = _body(o, c)
    us = _upper_shadow(o, c, h)
    ls = _lower_shadow(o, c, l)

    if body < 0.001:
        return None
    if ls < SHADOW_RATIO * body:     # Lower shadow must be ≥2× body
        return None
    if us > body * 0.5:             # Upper shadow should be small
        return None

    if in_downtrend:
        return {
            "name": "Hammer",
            "type": "BULLISH",
            "strength": 2,
            "meaning": (
                "After a decline, sellers pushed price down but buyers "
                "fought back and closed near the high — potential bullish reversal."
            ),
        }
    else:
        return {
            "name": "Hanging Man",
            "type": "BEARISH",
            "strength": 2,
            "meaning": (
                "After a rally, a long lower shadow appeared — sellers showed "
                "up during the day which is a bearish warning sign."
            ),
        }


def _check_shooting_star(o, h, l, c, avg_b, in_uptrend: bool) -> dict | None:
    """Shooting Star (bearish at top) / Inverted Hammer (bullish at bottom)."""
    body = _body(o, c)
    us = _upper_shadow(o, c, h)
    ls = _lower_shadow(o, c, l)

    if body < 0.001:
        return None
    if us < SHADOW_RATIO * body:     # Upper shadow must be ≥2× body
        return None
    if ls > body * 0.5:             # Lower shadow should be small
        return None

    if in_uptrend:
        return {
            "name": "Shooting Star",
            "type": "BEARISH",
            "strength": 2,
            "meaning": (
                "After a rally, buyers pushed price up but sellers took over "
                "and closed near the low — bearish reversal warning."
            ),
        }
    else:
        return {
            "name": "Inverted Hammer",
            "type": "BULLISH",
            "strength": 1,
            "meaning": (
                "After a decline, price tried to rally (long upper shadow). "
                "If the next day confirms with a gap up, it's bullish."
            ),
        }


def _check_marubozu(o, h, l, c, avg_b) -> dict | None:
    """Marubozu — strong candle with no/tiny shadows."""
    body = _body(o, c)
    total = h - l
    if total == 0 or body < avg_b * LONG_BODY_MULTIPLIER:
        return None

    us = _upper_shadow(o, c, h)
    ls = _lower_shadow(o, c, l)

    if us < total * 0.03 and ls < total * 0.03:
        if _is_bullish(o, c):
            return {
                "name": "Bullish Marubozu",
                "type": "BULLISH",
                "strength": 3,
                "meaning": "Complete buyer domination — opened at low, closed at high. Very bullish.",
            }
        else:
            return {
                "name": "Bearish Marubozu",
                "type": "BEARISH",
                "strength": 3,
                "meaning": "Complete seller domination — opened at high, closed at low. Very bearish.",
            }
    return None


def _check_spinning_top(o, h, l, c, avg_b) -> dict | None:
    """Spinning Top — small body, roughly equal shadows."""
    body = _body(o, c)
    us = _upper_shadow(o, c, h)
    ls = _lower_shadow(o, c, l)
    total = h - l

    if total == 0:
        return None
    if body > avg_b * 0.5:
        return None  # Body too large
    if us < total * 0.2 or ls < total * 0.2:
        return None  # Shadows should both be meaningful

    return {
        "name": "Spinning Top",
        "type": "NEUTRAL",
        "strength": 1,
        "meaning": (
            "Indecision candle — both buyers and sellers were active "
            "but neither side won. May signal a pause or reversal."
        ),
    }


# ═══════════════════════════════════════════════════════════════
#  TWO-CANDLE PATTERNS
# ═══════════════════════════════════════════════════════════════

def _check_engulfing(o1, h1, l1, c1, o2, h2, l2, c2, in_uptrend, in_downtrend) -> dict | None:
    """Bullish / Bearish Engulfing."""
    body1 = _body(o1, c1)
    body2 = _body(o2, c2)

    if body1 < 0.001 or body2 < 0.001:
        return None

    # Bullish Engulfing: prev bearish, curr bullish, curr body engulfs prev body
    if in_downtrend and _is_bearish(o1, c1) and _is_bullish(o2, c2):
        if o2 <= c1 and c2 >= o1:
            return {
                "name": "Bullish Engulfing",
                "type": "BULLISH",
                "strength": 3,
                "meaning": (
                    "A large green candle completely covers yesterday's red candle. "
                    "Bulls overwhelmed bears in one day — strong bullish reversal."
                ),
            }

    # Bearish Engulfing: prev bullish, curr bearish, curr body engulfs prev body
    if in_uptrend and _is_bullish(o1, c1) and _is_bearish(o2, c2):
        if o2 >= c1 and c2 <= o1:
            return {
                "name": "Bearish Engulfing",
                "type": "BEARISH",
                "strength": 3,
                "meaning": (
                    "A large red candle completely covers yesterday's green candle. "
                    "Bears overwhelmed bulls in one day — strong bearish reversal."
                ),
            }
    return None


def _check_harami(o1, h1, l1, c1, o2, h2, l2, c2, in_uptrend, in_downtrend) -> dict | None:
    """Bullish / Bearish Harami (opposite of Engulfing)."""
    body1 = _body(o1, c1)
    body2 = _body(o2, c2)

    if body1 < 0.001:
        return None

    # Small body must be inside large body
    top2 = max(o2, c2)
    bot2 = min(o2, c2)
    top1 = max(o1, c1)
    bot1 = min(o1, c1)

    if not (bot2 >= bot1 and top2 <= top1):
        return None

    if body2 > body1 * 0.6:
        return None  # Second candle should be noticeably smaller

    if in_downtrend and _is_bearish(o1, c1) and _is_bullish(o2, c2):
        return {
            "name": "Bullish Harami",
            "type": "BULLISH",
            "strength": 2,
            "meaning": (
                "A small green candle contained inside yesterday's large red candle. "
                "Selling pressure may be exhausting — potential bullish reversal."
            ),
        }

    if in_uptrend and _is_bullish(o1, c1) and _is_bearish(o2, c2):
        return {
            "name": "Bearish Harami",
            "type": "BEARISH",
            "strength": 2,
            "meaning": (
                "A small red candle contained inside yesterday's large green candle. "
                "Buying pressure may be fading — potential bearish reversal."
            ),
        }
    return None


def _check_piercing_dark_cloud(o1, h1, l1, c1, o2, h2, l2, c2, in_uptrend, in_downtrend) -> dict | None:
    """Piercing Line / Dark Cloud Cover."""
    body1 = _body(o1, c1)
    body1_mid = (o1 + c1) / 2.0

    if body1 < 0.001:
        return None

    # Piercing Line (bullish): at bottom of downtrend
    if in_downtrend and _is_bearish(o1, c1) and _is_bullish(o2, c2):
        if o2 < l1 and c2 > body1_mid and c2 < o1:
            return {
                "name": "Piercing Line",
                "type": "BULLISH",
                "strength": 2,
                "meaning": (
                    "After a decline, today opened below yesterday's low "
                    "but closed above yesterday's midpoint — buyers stepped in strongly."
                ),
            }

    # Dark Cloud Cover (bearish): at top of uptrend
    if in_uptrend and _is_bullish(o1, c1) and _is_bearish(o2, c2):
        if o2 > h1 and c2 < body1_mid and c2 > o1:
            return {
                "name": "Dark Cloud Cover",
                "type": "BEARISH",
                "strength": 2,
                "meaning": (
                    "After a rally, today opened above yesterday's high "
                    "but closed below yesterday's midpoint — sellers came in hard."
                ),
            }
    return None


# ═══════════════════════════════════════════════════════════════
#  THREE-CANDLE PATTERNS
# ═══════════════════════════════════════════════════════════════

def _check_morning_evening_star(
    o1, h1, l1, c1,
    o2, h2, l2, c2,
    o3, h3, l3, c3,
    in_uptrend, in_downtrend,
) -> dict | None:
    """Morning Star / Evening Star."""
    body1 = _body(o1, c1)
    body2 = _body(o2, c2)
    body3 = _body(o3, c3)
    body1_mid = (o1 + c1) / 2.0

    # Morning Star (bullish)
    if in_downtrend and _is_bearish(o1, c1):
        if body2 < body1 * 0.4:  # Middle candle = small body (star)
            if _is_bullish(o3, c3) and c3 > body1_mid:
                return {
                    "name": "Morning Star",
                    "type": "BULLISH",
                    "strength": 3,
                    "meaning": (
                        "Three-candle reversal: (1) long red candle, (2) small indecision "
                        "candle, (3) long green candle closing above midpoint of first. "
                        "Night is ending — bullish reversal."
                    ),
                }

    # Evening Star (bearish)
    if in_uptrend and _is_bullish(o1, c1):
        if body2 < body1 * 0.4:
            if _is_bearish(o3, c3) and c3 < body1_mid:
                return {
                    "name": "Evening Star",
                    "type": "BEARISH",
                    "strength": 3,
                    "meaning": (
                        "Three-candle reversal: (1) long green candle, (2) small indecision "
                        "candle, (3) long red candle closing below midpoint of first. "
                        "Daylight fading — bearish reversal."
                    ),
                }
    return None


def _check_three_soldiers_crows(
    o1, h1, l1, c1,
    o2, h2, l2, c2,
    o3, h3, l3, c3,
    avg_b,
) -> dict | None:
    """Three White Soldiers / Three Black Crows."""
    body1 = _body(o1, c1)
    body2 = _body(o2, c2)
    body3 = _body(o3, c3)

    min_body = avg_b * 0.7

    # Three White Soldiers
    if (
        _is_bullish(o1, c1) and _is_bullish(o2, c2) and _is_bullish(o3, c3)
        and body1 > min_body and body2 > min_body and body3 > min_body
        and o2 > o1 and o2 < c1  # Open within previous body
        and o3 > o2 and o3 < c2
        and c3 > c2 > c1
    ):
        return {
            "name": "Three White Soldiers",
            "type": "BULLISH",
            "strength": 3,
            "meaning": (
                "Three consecutive long green candles, each opening within the "
                "previous body and closing higher. Powerful bullish signal."
            ),
        }

    # Three Black Crows
    if (
        _is_bearish(o1, c1) and _is_bearish(o2, c2) and _is_bearish(o3, c3)
        and body1 > min_body and body2 > min_body and body3 > min_body
        and o2 < o1 and o2 > c1  # Open within previous body
        and o3 < o2 and o3 > c2
        and c3 < c2 < c1
    ):
        return {
            "name": "Three Black Crows",
            "type": "BEARISH",
            "strength": 3,
            "meaning": (
                "Three consecutive long red candles, each opening within the "
                "previous body and closing lower. Powerful bearish signal."
            ),
        }
    return None


# ═══════════════════════════════════════════════════════════════
#  TWEEZER TOPS / BOTTOMS
# ═══════════════════════════════════════════════════════════════

def _check_tweezers(o1, h1, l1, c1, o2, h2, l2, c2, avg_b, in_uptrend, in_downtrend) -> dict | None:
    """Tweezer Top / Bottom."""
    tolerance = avg_b * 0.05  # Highs/lows must be nearly equal

    # Tweezer Top
    if in_uptrend and abs(h1 - h2) <= tolerance:
        if _is_bullish(o1, c1) and _is_bearish(o2, c2):
            return {
                "name": "Tweezer Top",
                "type": "BEARISH",
                "strength": 2,
                "meaning": (
                    "Two candles with nearly identical highs after an uptrend. "
                    "Resistance held twice — bearish reversal signal."
                ),
            }

    # Tweezer Bottom
    if in_downtrend and abs(l1 - l2) <= tolerance:
        if _is_bearish(o1, c1) and _is_bullish(o2, c2):
            return {
                "name": "Tweezer Bottom",
                "type": "BULLISH",
                "strength": 2,
                "meaning": (
                    "Two candles with nearly identical lows after a downtrend. "
                    "Support held twice — bullish reversal signal."
                ),
            }
    return None


# ═══════════════════════════════════════════════════════════════
#  MASTER SCANNER — DETECT ALL PATTERNS ON RECENT CANDLES
# ═══════════════════════════════════════════════════════════════

def scan_candlestick_patterns(df: pd.DataFrame, lookback: int = 5) -> list[dict]:
    """
    Scan the last `lookback` candles for ALL candlestick patterns.
    Returns a list of detected patterns with details.
    """
    if len(df) < lookback + CANDLE_LOOKBACK:
        return []

    patterns = []
    n = len(df)
    start = max(3, n - lookback)

    for idx in range(start, n):
        o = float(df["Open"].iloc[idx])
        h = float(df["High"].iloc[idx])
        l = float(df["Low"].iloc[idx])
        c = float(df["Close"].iloc[idx])

        avg_b = _avg_body(df, idx)
        uptrend = _is_uptrend(df, idx)
        downtrend = _is_downtrend(df, idx)
        candle_date = str(df.index[idx])[:10] if hasattr(df.index[idx], 'strftime') else str(df.index[idx])[:10]

        # ── Single-candle patterns ──────────────────
        doji = _check_doji(o, h, l, c, avg_b)
        if doji:
            dtype = "BEARISH" if uptrend else ("BULLISH" if downtrend else "NEUTRAL")
            patterns.append({
                "name": doji.replace("_", " ").title(),
                "type": dtype,
                "strength": 1,
                "date": candle_date,
                "meaning": f"Indecision candle ({doji.replace('_', ' ').lower()}) — "
                           f"{'buyers may be exhausted after rally' if uptrend else 'sellers may be exhausted after decline' if downtrend else 'market undecided'}."
            })

        hammer = _check_hammer(o, h, l, c, avg_b, downtrend)
        if hammer:
            hammer["date"] = candle_date
            patterns.append(hammer)

        star = _check_shooting_star(o, h, l, c, avg_b, uptrend)
        if star:
            star["date"] = candle_date
            patterns.append(star)

        maru = _check_marubozu(o, h, l, c, avg_b)
        if maru:
            maru["date"] = candle_date
            patterns.append(maru)

        spin = _check_spinning_top(o, h, l, c, avg_b)
        if spin:
            spin["date"] = candle_date
            patterns.append(spin)

        # ── Two-candle patterns (need previous candle) ──
        if idx >= 1:
            o1 = float(df["Open"].iloc[idx - 1])
            h1 = float(df["High"].iloc[idx - 1])
            l1 = float(df["Low"].iloc[idx - 1])
            c1 = float(df["Close"].iloc[idx - 1])

            uptrend_2 = _is_uptrend(df, idx - 1)
            downtrend_2 = _is_downtrend(df, idx - 1)

            eng = _check_engulfing(o1, h1, l1, c1, o, h, l, c, uptrend_2, downtrend_2)
            if eng:
                eng["date"] = candle_date
                patterns.append(eng)

            har = _check_harami(o1, h1, l1, c1, o, h, l, c, uptrend_2, downtrend_2)
            if har:
                har["date"] = candle_date
                patterns.append(har)

            pdc = _check_piercing_dark_cloud(o1, h1, l1, c1, o, h, l, c, uptrend_2, downtrend_2)
            if pdc:
                pdc["date"] = candle_date
                patterns.append(pdc)

            twz = _check_tweezers(o1, h1, l1, c1, o, h, l, c, avg_b, uptrend_2, downtrend_2)
            if twz:
                twz["date"] = candle_date
                patterns.append(twz)

        # ── Three-candle patterns (need two previous candles) ──
        if idx >= 2:
            o1 = float(df["Open"].iloc[idx - 2])
            h1 = float(df["High"].iloc[idx - 2])
            l1 = float(df["Low"].iloc[idx - 2])
            c1 = float(df["Close"].iloc[idx - 2])

            o2 = float(df["Open"].iloc[idx - 1])
            h2 = float(df["High"].iloc[idx - 1])
            l2 = float(df["Low"].iloc[idx - 1])
            c2 = float(df["Close"].iloc[idx - 1])

            uptrend_3 = _is_uptrend(df, idx - 2)
            downtrend_3 = _is_downtrend(df, idx - 2)

            star_pat = _check_morning_evening_star(o1, h1, l1, c1, o2, h2, l2, c2, o, h, l, c, uptrend_3, downtrend_3)
            if star_pat:
                star_pat["date"] = candle_date
                patterns.append(star_pat)

            sol_crow = _check_three_soldiers_crows(o1, h1, l1, c1, o2, h2, l2, c2, o, h, l, c, avg_b)
            if sol_crow:
                sol_crow["date"] = candle_date
                patterns.append(sol_crow)

    return patterns
