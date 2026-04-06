"""
Breakout Detection — Al Brooks Methodology
============================================
Implements breakout, breakout pullback, failed breakout,
and failed failure detection from "Trading Price Action: TRENDS".

Concepts
--------
- **Breakout**: Price closes beyond a key level (prior swing, trend line,
  trading range boundary) with conviction (trend bar close).
- **Breakout Pullback**: After breakout, price pulls back to test the
  breakout level. The pullback should hold — this is the entry.
- **Failed Breakout**: Breakout that reverses within 1-5 bars.
  This traps one side and is a strong signal for the other side.
- **Failed Failure (Second Entry)**: When a "failed breakout" itself fails,
  creating a second entry in the original breakout direction.
  This is one of the most reliable Al Brooks setups.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from price_action.bar_types import BarAnalysis
from price_action.patterns import _find_swing_points
from price_action import config as C


# ─────────────────────────────────────────────────────────────────
#  DATA CLASSES
# ─────────────────────────────────────────────────────────────────

@dataclass
class Breakout:
    """A detected breakout event."""
    breakout_type: str          # "BULL_BREAKOUT" | "BEAR_BREAKOUT"
    level_type: str             # "SWING_HIGH" | "SWING_LOW" | "TREND_LINE" | "RANGE"
    level_price: float          # The price level that was broken
    bar_idx: int                # Bar that broke the level
    bar_date: str = ""
    strength: str = "MODERATE"  # "STRONG" | "MODERATE" | "WEAK"
    close_beyond: bool = False  # Did the bar close beyond the level?
    has_follow_through: bool = False  # Did next bar(s) continue?
    is_failed: bool = False     # Did the breakout fail?
    failure_idx: int = -1       # Bar where it failed
    is_failed_failure: bool = False  # Did the failure itself fail? (second entry)
    pullback_entry: float = 0.0  # Entry price on the pullback
    description: str = ""


@dataclass
class BreakoutAnalysis:
    """Complete breakout analysis result."""
    breakouts: List[Breakout] = field(default_factory=list)
    active_breakouts: List[Breakout] = field(default_factory=list)
    recent_failed: List[Breakout] = field(default_factory=list)
    recent_failed_failures: List[Breakout] = field(default_factory=list)

    # Current state
    in_breakout: bool = False
    breakout_direction: str = "NONE"
    breakout_strength: str = "NONE"
    awaiting_pullback: bool = False
    pullback_entry_price: float = 0.0

    description: str = ""


# ─────────────────────────────────────────────────────────────────
#  BREAKOUT FROM SWING POINTS
# ─────────────────────────────────────────────────────────────────

def detect_swing_breakouts(bars: List[BarAnalysis]) -> List[Breakout]:
    """
    Detect breakouts above swing highs and below swing lows.

    A breakout above a swing high is bullish.
    A breakout below a swing low is bearish.
    """
    breakouts: List[Breakout] = []
    if len(bars) < 10:
        return breakouts

    swing_highs = _find_swing_points(bars, "HIGH", lookback=3)
    swing_lows = _find_swing_points(bars, "LOW", lookback=3)
    n = len(bars)

    # Detect breakouts above swing highs
    for sh_idx, sh_price in swing_highs:
        # Look for bars after this swing high that close above it
        for i in range(sh_idx + 1, min(n, sh_idx + 30)):
            if bars[i].close > sh_price:
                strength = _assess_breakout_strength(bars[i], sh_price, "BULL")
                follow = _check_follow_through(bars, i, "BULL")
                failed, fail_idx = _check_failed_breakout(bars, i, sh_price, "BULL")
                ff = _check_failed_failure(bars, fail_idx, sh_price, "BULL") if failed else False

                bo = Breakout(
                    breakout_type="BULL_BREAKOUT",
                    level_type="SWING_HIGH",
                    level_price=sh_price,
                    bar_idx=i,
                    bar_date=bars[i].date,
                    strength=strength,
                    close_beyond=True,
                    has_follow_through=follow,
                    is_failed=failed,
                    failure_idx=fail_idx,
                    is_failed_failure=ff,
                )
                bo.description = _bo_description(bo)
                breakouts.append(bo)
                break  # Only first breakout per swing point

    # Detect breakouts below swing lows
    for sl_idx, sl_price in swing_lows:
        for i in range(sl_idx + 1, min(n, sl_idx + 30)):
            if bars[i].close < sl_price:
                strength = _assess_breakout_strength(bars[i], sl_price, "BEAR")
                follow = _check_follow_through(bars, i, "BEAR")
                failed, fail_idx = _check_failed_breakout(bars, i, sl_price, "BEAR")
                ff = _check_failed_failure(bars, fail_idx, sl_price, "BEAR") if failed else False

                bo = Breakout(
                    breakout_type="BEAR_BREAKOUT",
                    level_type="SWING_LOW",
                    level_price=sl_price,
                    bar_idx=i,
                    bar_date=bars[i].date,
                    strength=strength,
                    close_beyond=True,
                    has_follow_through=follow,
                    is_failed=failed,
                    failure_idx=fail_idx,
                    is_failed_failure=ff,
                )
                bo.description = _bo_description(bo)
                breakouts.append(bo)
                break

    return breakouts


# ─────────────────────────────────────────────────────────────────
#  BREAKOUT FROM TRADING RANGE
# ─────────────────────────────────────────────────────────────────

def detect_range_breakouts(bars: List[BarAnalysis]) -> List[Breakout]:
    """
    Detect breakouts from trading ranges.

    A trading range is identified by finding a period with roughly
    equal highs and lows (horizontal support/resistance).
    """
    breakouts: List[Breakout] = []
    if len(bars) < 20:
        return breakouts

    n = len(bars)

    # Find recent range boundaries using the last 20-40 bars
    lookback = min(40, len(bars))
    recent = bars[-lookback:]

    highs = [b.high for b in recent]
    lows = [b.low for b in recent]

    range_high = max(highs)
    range_low = min(lows)
    range_size = range_high - range_low

    if range_size == 0:
        return breakouts

    # Check the most recent bars for range breakout
    last_bars = bars[-5:]
    for bar in last_bars:
        # Bull breakout: close above range high
        if bar.close > range_high:
            strength = _assess_breakout_strength(bar, range_high, "BULL")
            bo = Breakout(
                breakout_type="BULL_BREAKOUT",
                level_type="RANGE",
                level_price=range_high,
                bar_idx=bar.index,
                bar_date=bar.date,
                strength=strength,
                close_beyond=True,
            )
            bo.description = f"Bull breakout above trading range high {range_high:.2f}"
            breakouts.append(bo)
            break

        # Bear breakout: close below range low
        if bar.close < range_low:
            strength = _assess_breakout_strength(bar, range_low, "BEAR")
            bo = Breakout(
                breakout_type="BEAR_BREAKOUT",
                level_type="RANGE",
                level_price=range_low,
                bar_idx=bar.index,
                bar_date=bar.date,
                strength=strength,
                close_beyond=True,
            )
            bo.description = f"Bear breakout below trading range low {range_low:.2f}"
            breakouts.append(bo)
            break

    return breakouts


# ─────────────────────────────────────────────────────────────────
#  BREAKOUT ASSESSMENT HELPERS
# ─────────────────────────────────────────────────────────────────

def _assess_breakout_strength(
    bar: BarAnalysis,
    level: float,
    direction: str,
) -> str:
    """Assess breakout bar strength."""
    # Strong: trend bar with body closing well beyond the level
    if bar.is_strong_trend_bar:
        return "STRONG"
    if bar.is_trend_bar and bar.body_pct >= C.BREAKOUT_STRENGTH_MIN_BODY:
        # Check how far beyond
        if direction == "BULL":
            penetration = (bar.close - level) / level if level > 0 else 0
        else:
            penetration = (level - bar.close) / level if level > 0 else 0
        if penetration > 0.01:  # 1%+ beyond
            return "STRONG"
        return "MODERATE"
    return "WEAK"


def _check_follow_through(
    bars: List[BarAnalysis],
    break_idx: int,
    direction: str,
) -> bool:
    """Check if the breakout has follow-through (next bar continues)."""
    n = len(bars)
    if break_idx + 1 >= n:
        return False  # Can't know yet

    next_bar = bars[break_idx + 1]
    if direction == "BULL":
        return next_bar.close > bars[break_idx].close
    else:
        return next_bar.close < bars[break_idx].close


def _check_failed_breakout(
    bars: List[BarAnalysis],
    break_idx: int,
    level: float,
    direction: str,
) -> tuple:
    """
    Check if the breakout failed (price returned through the level).

    Returns (is_failed, failure_idx)
    """
    n = len(bars)
    check_end = min(n, break_idx + C.FAILED_BREAKOUT_BARS + 1)

    for i in range(break_idx + 1, check_end):
        if direction == "BULL" and bars[i].close < level:
            return True, i
        elif direction == "BEAR" and bars[i].close > level:
            return True, i

    return False, -1


def _check_failed_failure(
    bars: List[BarAnalysis],
    fail_idx: int,
    level: float,
    original_direction: str,
) -> bool:
    """
    Check if the failed breakout itself failed (second entry).

    This is when price first breaks out, then pulls back through the
    level (failure), then crosses back in the original direction.
    """
    n = len(bars)
    if fail_idx < 0 or fail_idx + 1 >= n:
        return False

    check_end = min(n, fail_idx + C.BREAKOUT_PULLBACK_MAX_BARS + 1)

    for i in range(fail_idx + 1, check_end):
        if original_direction == "BULL" and bars[i].close > level:
            return True
        elif original_direction == "BEAR" and bars[i].close < level:
            return True

    return False


def _bo_description(bo: Breakout) -> str:
    """Build breakout description."""
    parts = []
    direction = "Bull" if "BULL" in bo.breakout_type else "Bear"
    parts.append(f"{direction} breakout ({bo.strength.lower()}) above "
                 if "BULL" in bo.breakout_type else
                 f"{direction} breakout ({bo.strength.lower()}) below ")
    parts.append(f"{bo.level_type.lower().replace('_', ' ')} at {bo.level_price:.2f}")

    if bo.has_follow_through:
        parts.append(" — with follow-through")
    if bo.is_failed:
        parts.append(" — FAILED")
        if bo.is_failed_failure:
            parts.append(" — but failure also failed (SECOND ENTRY, very reliable)")
    return "".join(parts)


# ─────────────────────────────────────────────────────────────────
#  BREAKOUT PULLBACK DETECTION
# ─────────────────────────────────────────────────────────────────

def detect_breakout_pullbacks(
    bars: List[BarAnalysis],
    breakouts: List[Breakout],
) -> None:
    """
    Detect breakout pullbacks and set entry prices.

    Al Brooks: "The breakout pullback is often the best entry. Price
    breaks out, pulls back to test the breakout level, and then
    continues in the breakout direction."

    Mutates breakout objects in-place.
    """
    n = len(bars)

    for bo in breakouts:
        if bo.is_failed:
            continue  # Can't have pullback entry on failed breakout

        # Look for pullback after breakout
        search_end = min(n, bo.bar_idx + C.BREAKOUT_PULLBACK_DEEP_MAX + 1)
        level = bo.level_price

        for i in range(bo.bar_idx + 1, search_end):
            bar = bars[i]

            if "BULL" in bo.breakout_type:
                # Pullback to the level (bar low near or at breakout level)
                if bar.low <= level * 1.01:  # Within 1% of level
                    # Entry on next bar above this bar's high
                    if i + 1 < n:
                        bo.pullback_entry = bars[i + 1].high if bars[i + 1].high > bar.high else bar.high
                    else:
                        bo.pullback_entry = bar.high
                    break
            else:
                if bar.high >= level * 0.99:
                    if i + 1 < n:
                        bo.pullback_entry = bars[i + 1].low if bars[i + 1].low < bar.low else bar.low
                    else:
                        bo.pullback_entry = bar.low
                    break


# ─────────────────────────────────────────────────────────────────
#  MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────

def analyze_breakouts(bars: List[BarAnalysis]) -> BreakoutAnalysis:
    """
    Perform complete breakout analysis.

    Parameters
    ----------
    bars : list[BarAnalysis]
        Classified bars from bar_types.classify_bars().

    Returns
    -------
    BreakoutAnalysis
        All breakouts, failures, failed failures, and current state.
    """
    result = BreakoutAnalysis()

    if len(bars) < 10:
        result.description = "Insufficient data for breakout analysis"
        return result

    # Detect breakouts
    swing_bos = detect_swing_breakouts(bars)
    range_bos = detect_range_breakouts(bars)
    all_bos = swing_bos + range_bos

    # Detect pullback entries
    detect_breakout_pullbacks(bars, all_bos)

    result.breakouts = all_bos

    # Categorize
    last_idx = len(bars) - 1
    result.active_breakouts = [
        bo for bo in all_bos
        if not bo.is_failed and bo.bar_idx >= last_idx - 10
    ]
    result.recent_failed = [
        bo for bo in all_bos
        if bo.is_failed and not bo.is_failed_failure and bo.bar_idx >= last_idx - 10
    ]
    result.recent_failed_failures = [
        bo for bo in all_bos
        if bo.is_failed_failure and bo.bar_idx >= last_idx - 10
    ]

    # Current state
    if result.active_breakouts:
        latest = result.active_breakouts[-1]
        result.in_breakout = True
        result.breakout_direction = "BULL" if "BULL" in latest.breakout_type else "BEAR"
        result.breakout_strength = latest.strength
        if latest.pullback_entry > 0:
            result.awaiting_pullback = True
            result.pullback_entry_price = latest.pullback_entry

    # Description
    parts = []
    if result.in_breakout:
        parts.append(f"Active {result.breakout_direction} breakout "
                     f"({result.breakout_strength.lower()})")
        if result.awaiting_pullback:
            parts.append(f"Pullback entry at {result.pullback_entry_price:.2f}")
    if result.recent_failed:
        parts.append(f"{len(result.recent_failed)} recent failed breakout(s) — "
                     f"traps in play")
    if result.recent_failed_failures:
        parts.append(f"{len(result.recent_failed_failures)} FAILED FAILURE(S) — "
                     f"strong second entry signal")
    if not parts:
        parts.append("No significant breakouts detected recently")

    result.description = " | ".join(parts)

    return result
