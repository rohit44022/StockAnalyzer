"""
Trend Lines & Channels — Al Brooks Methodology
================================================
Implements trend line, channel line, and micro channel detection
from "Trading Price Action: TRENDS".

Concepts
--------
- **Trend Line**: Line connecting swing lows (bull) or swing highs (bear).
  A break of the trend line signals a possible reversal.
- **Channel Line**: Line parallel to the trend line on the opposite side.
  Overshoot of the channel line = likely reversal.
- **Micro Channel**: Very tight channel (nearly every bar touches the line).
  Strong trend — first pullback is typically bought/sold.
- **Horizontal Lines**: Support and resistance from prior swing points.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from price_action.bar_types import BarAnalysis
from price_action.patterns import _find_swing_points
from price_action import config as C


# ─────────────────────────────────────────────────────────────────
#  DATA CLASSES
# ─────────────────────────────────────────────────────────────────

@dataclass
class TrendLine:
    """A detected trend line."""
    line_type: str          # "BULL_TREND" | "BEAR_TREND" | "BULL_CHANNEL" | "BEAR_CHANNEL"
    slope: float            # Price change per bar (positive = up)
    intercept: float        # Price at index 0
    start_idx: int = 0
    end_idx: int = 0
    start_price: float = 0.0
    end_price: float = 0.0
    touches: int = 0        # Number of bars touching the line
    current_value: float = 0.0  # Line value at the last bar
    broken: bool = False     # Has price broken through this line?
    break_idx: int = -1      # Bar index where break occurred
    description: str = ""

    def value_at(self, idx: int) -> float:
        """Get trend line value at a given bar index."""
        return self.intercept + self.slope * idx


@dataclass
class MicroChannel:
    """A detected micro channel (tight channel per Al Brooks)."""
    direction: str          # "BULL" | "BEAR"
    start_idx: int = 0
    end_idx: int = 0
    bars: int = 0
    slope: float = 0.0
    touch_pct: float = 0.0  # % of bars touching the trend line
    upper_line: Optional[TrendLine] = None
    lower_line: Optional[TrendLine] = None
    still_active: bool = False
    description: str = ""


@dataclass
class ChannelAnalysis:
    """Complete channel analysis result."""
    bull_trend_lines: List[TrendLine] = field(default_factory=list)
    bear_trend_lines: List[TrendLine] = field(default_factory=list)
    channel_lines: List[TrendLine] = field(default_factory=list)
    micro_channels: List[MicroChannel] = field(default_factory=list)
    active_trend_line: Optional[TrendLine] = None
    active_channel_line: Optional[TrendLine] = None
    active_micro_channel: Optional[MicroChannel] = None
    price_position: str = "MIDDLE"  # "AT_TREND_LINE" | "AT_CHANNEL_LINE" | "MIDDLE" | "BEYOND_CHANNEL"
    description: str = ""


# ─────────────────────────────────────────────────────────────────
#  TREND LINE DETECTION
# ─────────────────────────────────────────────────────────────────

def detect_trend_lines(bars: List[BarAnalysis]) -> Tuple[List[TrendLine], List[TrendLine]]:
    """
    Detect bull and bear trend lines from swing points.

    Bull trend line: connects ascending swing lows.
    Bear trend line: connects descending swing highs.

    Returns (bull_trend_lines, bear_trend_lines)
    """
    bull_lines: List[TrendLine] = []
    bear_lines: List[TrendLine] = []

    if len(bars) < 10:
        return bull_lines, bear_lines

    swing_lows = _find_swing_points(bars, "LOW", lookback=2)
    swing_highs = _find_swing_points(bars, "HIGH", lookback=2)

    # Bull trend lines from ascending swing lows
    _build_trend_lines_from_swings(swing_lows, bars, "BULL_TREND", bull_lines, ascending=True)

    # Bear trend lines from descending swing highs
    _build_trend_lines_from_swings(swing_highs, bars, "BEAR_TREND", bear_lines, ascending=False)

    return bull_lines, bear_lines


def _build_trend_lines_from_swings(
    swings: List[tuple],
    bars: List[BarAnalysis],
    line_type: str,
    lines: List[TrendLine],
    ascending: bool,
) -> None:
    """Build trend lines from pairs of swing points."""
    if len(swings) < C.TRENDLINE_MIN_TOUCHES:
        return

    n = len(bars)
    last_idx = n - 1

    # Try all pairs of swings within lookback
    # Focus on most recent and significant pairs
    recent_swings = [s for s in swings if s[0] >= last_idx - C.TRENDLINE_MAX_LOOKBACK]

    # Cap to 15 most recent swings to avoid O(n^2) blow-up
    recent_swings = recent_swings[-15:]

    for i in range(len(recent_swings)):
        for j in range(i + 1, len(recent_swings)):
            idx1, p1 = recent_swings[i]
            idx2, p2 = recent_swings[j]

            if idx2 - idx1 < 3:
                continue

            # Check direction
            if ascending and p2 <= p1:
                continue
            if not ascending and p2 >= p1:
                continue

            # Calculate slope and intercept
            slope = (p2 - p1) / (idx2 - idx1)
            intercept = p1 - slope * idx1

            # Count touches only within the relevant range
            touches = _count_line_touches(bars, slope, intercept, line_type, idx1, n)

            if touches >= C.TRENDLINE_MIN_TOUCHES:
                current_val = intercept + slope * last_idx

                # Check if broken (only check last 30 bars for speed)
                broken = False
                break_idx = -1
                check_start = max(idx2 + 1, n - 30)
                if line_type == "BULL_TREND":
                    for k in range(check_start, n):
                        line_val = intercept + slope * k
                        if bars[k].close < line_val:
                            broken = True
                            break_idx = k
                            break
                else:  # BEAR_TREND
                    for k in range(check_start, n):
                        line_val = intercept + slope * k
                        if bars[k].close > line_val:
                            broken = True
                            break_idx = k
                            break

                lines.append(TrendLine(
                    line_type=line_type,
                    slope=round(slope, 4),
                    intercept=round(intercept, 2),
                    start_idx=idx1,
                    end_idx=idx2,
                    start_price=round(p1, 2),
                    end_price=round(p2, 2),
                    touches=touches,
                    current_value=round(current_val, 2),
                    broken=broken,
                    break_idx=break_idx,
                    description=_tl_description(line_type, p1, p2, touches, broken, current_val),
                ))

    # Keep only the most significant lines (highest touch count)
    lines.sort(key=lambda tl: tl.touches, reverse=True)
    del lines[3:]  # Keep top 3


def _count_line_touches(
    bars: List[BarAnalysis],
    slope: float,
    intercept: float,
    line_type: str,
    start_idx: int = 0,
    end_idx: int = 0,
) -> int:
    """Count how many bars touch or are near the trend line (within range)."""
    touches = 0
    end = end_idx if end_idx else len(bars)
    for i in range(start_idx, end):
        line_val = intercept + slope * i
        if line_val <= 0:
            continue
        tol = line_val * C.CHANNEL_LINE_TOLERANCE

        if "BULL" in line_type:
            if abs(bars[i].low - line_val) <= tol:
                touches += 1
        else:
            if abs(bars[i].high - line_val) <= tol:
                touches += 1

    return touches


def _tl_description(
    line_type: str, p1: float, p2: float,
    touches: int, broken: bool, current: float,
) -> str:
    """Build trend line description."""
    kind = "Bull trend" if "BULL" in line_type else "Bear trend"
    status = "BROKEN" if broken else "ACTIVE"
    return (f"{kind} line ({status}): {p1:.2f} → {p2:.2f}, "
            f"{touches} touches, current value {current:.2f}")


# ─────────────────────────────────────────────────────────────────
#  CHANNEL LINE DETECTION
# ─────────────────────────────────────────────────────────────────

def detect_channel_lines(
    bars: List[BarAnalysis],
    bull_trend_lines: List[TrendLine],
    bear_trend_lines: List[TrendLine],
) -> List[TrendLine]:
    """
    Detect channel lines (parallel to trend lines on opposite side).

    Al Brooks: A channel line is the line drawn parallel to the trend line
    on the other side of the price action. When price reaches the channel
    line, it often reverses (at least temporarily).
    """
    channel_lines: List[TrendLine] = []
    n = len(bars)

    # For each bull trend line, find parallel channel line on the highs
    for tl in bull_trend_lines:
        if tl.broken:
            continue
        # Find the highest point above the trend line
        max_dist = 0
        max_idx = tl.start_idx
        for i in range(tl.start_idx, min(n, tl.end_idx + 20)):
            line_val = tl.value_at(i)
            dist = bars[i].high - line_val
            if dist > max_dist:
                max_dist = dist
                max_idx = i

        if max_dist > 0:
            ch_intercept = tl.intercept + max_dist
            current_val = ch_intercept + tl.slope * (n - 1)
            channel_lines.append(TrendLine(
                line_type="BULL_CHANNEL",
                slope=tl.slope,
                intercept=round(ch_intercept, 2),
                start_idx=tl.start_idx,
                end_idx=max_idx,
                start_price=round(tl.value_at(tl.start_idx) + max_dist, 2),
                end_price=round(bars[max_idx].high, 2),
                touches=1,
                current_value=round(current_val, 2),
                description=f"Bull channel line: parallel above trend line, "
                            f"current value {current_val:.2f}",
            ))

    # For each bear trend line, find parallel channel line on the lows
    for tl in bear_trend_lines:
        if tl.broken:
            continue
        max_dist = 0
        max_idx = tl.start_idx
        for i in range(tl.start_idx, min(n, tl.end_idx + 20)):
            line_val = tl.value_at(i)
            dist = line_val - bars[i].low
            if dist > max_dist:
                max_dist = dist
                max_idx = i

        if max_dist > 0:
            ch_intercept = tl.intercept - max_dist
            current_val = ch_intercept + tl.slope * (n - 1)
            channel_lines.append(TrendLine(
                line_type="BEAR_CHANNEL",
                slope=tl.slope,
                intercept=round(ch_intercept, 2),
                start_idx=tl.start_idx,
                end_idx=max_idx,
                start_price=round(tl.value_at(tl.start_idx) - max_dist, 2),
                end_price=round(bars[max_idx].low, 2),
                touches=1,
                current_value=round(current_val, 2),
                description=f"Bear channel line: parallel below trend line, "
                            f"current value {current_val:.2f}",
            ))

    return channel_lines


# ─────────────────────────────────────────────────────────────────
#  MICRO CHANNEL DETECTION
# ─────────────────────────────────────────────────────────────────

def detect_micro_channels(bars: List[BarAnalysis]) -> List[MicroChannel]:
    """
    Detect micro channels — very tight trend channels.

    Al Brooks: "A micro channel is a series of bars where almost every
    bar's low (bull) or high (bear) touches the trend line. It indicates
    very strong buying/selling. The first pullback is usually bought/sold."

    Bull micro channel: almost every bar's low is at or above prior bar's low
    Bear micro channel: almost every bar's high is at or below prior bar's high
    """
    channels: List[MicroChannel] = []
    if len(bars) < C.MICRO_CHANNEL_MIN_BARS:
        return channels

    n = len(bars)

    # Detect bull micro channels
    i = 0
    while i < n:
        # Look for streak of bars with lows >= prior low (bull micro channel)
        if i + 1 < n and bars[i + 1].low >= bars[i].low - bars[i].range_size * 0.05:
            start = i
            count = 1
            while i + 1 < n and \
                  bars[i + 1].low >= bars[i].low - bars[i].range_size * 0.05 and \
                  count < C.MICRO_CHANNEL_MAX_BARS:
                i += 1
                count += 1

            if count >= C.MICRO_CHANNEL_MIN_BARS:
                slope = (bars[i].low - bars[start].low) / (i - start) if i > start else 0
                channels.append(MicroChannel(
                    direction="BULL",
                    start_idx=start,
                    end_idx=i,
                    bars=count,
                    slope=round(slope, 4),
                    touch_pct=round(count / (i - start + 1) * 100, 1),
                    still_active=(i >= n - 2),
                    description=f"Bull micro channel ({count} bars) — every bar's "
                                f"low >= prior low. Very strong buying. First pullback "
                                f"is buy opportunity.",
                ))
        i += 1

    # Detect bear micro channels
    i = 0
    while i < n:
        if i + 1 < n and bars[i + 1].high <= bars[i].high + bars[i].range_size * 0.05:
            start = i
            count = 1
            while i + 1 < n and \
                  bars[i + 1].high <= bars[i].high + bars[i].range_size * 0.05 and \
                  count < C.MICRO_CHANNEL_MAX_BARS:
                i += 1
                count += 1

            if count >= C.MICRO_CHANNEL_MIN_BARS:
                slope = (bars[i].high - bars[start].high) / (i - start) if i > start else 0
                channels.append(MicroChannel(
                    direction="BEAR",
                    start_idx=start,
                    end_idx=i,
                    bars=count,
                    slope=round(slope, 4),
                    touch_pct=round(count / (i - start + 1) * 100, 1),
                    still_active=(i >= n - 2),
                    description=f"Bear micro channel ({count} bars) — every bar's "
                                f"high <= prior high. Very strong selling. First pullback "
                                f"is sell opportunity.",
                ))
        i += 1

    return channels


# ─────────────────────────────────────────────────────────────────
#  PRICE POSITION IN CHANNEL
# ─────────────────────────────────────────────────────────────────

def _determine_price_position(
    bars: List[BarAnalysis],
    bull_tl: List[TrendLine],
    bear_tl: List[TrendLine],
    channel_lines: List[TrendLine],
) -> str:
    """Determine where current price sits relative to trend lines."""
    if not bars:
        return "MIDDLE"

    last = bars[-1]
    last_idx = last.index

    # Check active (unbroken) trend lines
    for tl in bull_tl:
        if not tl.broken:
            line_val = tl.value_at(last_idx)
            if line_val > 0:
                dist_pct = abs(last.close - line_val) / line_val
                if dist_pct < 0.01:
                    return "AT_TREND_LINE"

    for tl in bear_tl:
        if not tl.broken:
            line_val = tl.value_at(last_idx)
            if line_val > 0:
                dist_pct = abs(last.close - line_val) / line_val
                if dist_pct < 0.01:
                    return "AT_TREND_LINE"

    # Check channel lines
    for cl in channel_lines:
        line_val = cl.value_at(last_idx)
        if line_val > 0:
            dist_pct = abs(last.close - line_val) / line_val
            if dist_pct < 0.01:
                return "AT_CHANNEL_LINE"
            # Beyond channel line
            if "BULL" in cl.line_type and last.close > line_val * 1.01:
                return "BEYOND_CHANNEL"
            if "BEAR" in cl.line_type and last.close < line_val * 0.99:
                return "BEYOND_CHANNEL"

    return "MIDDLE"


# ─────────────────────────────────────────────────────────────────
#  MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────

def analyze_channels(bars: List[BarAnalysis]) -> ChannelAnalysis:
    """
    Perform complete trend line and channel analysis.

    Parameters
    ----------
    bars : list[BarAnalysis]
        Classified bars from bar_types.classify_bars().

    Returns
    -------
    ChannelAnalysis
        All detected trend lines, channel lines, micro channels,
        and current price position relative to these structures.
    """
    result = ChannelAnalysis()

    if len(bars) < 10:
        result.description = "Insufficient data for channel analysis"
        return result

    # 1. Trend lines
    bull_tl, bear_tl = detect_trend_lines(bars)
    result.bull_trend_lines = bull_tl
    result.bear_trend_lines = bear_tl

    # 2. Channel lines (parallel to trend lines)
    result.channel_lines = detect_channel_lines(bars, bull_tl, bear_tl)

    # 3. Micro channels
    result.micro_channels = detect_micro_channels(bars)

    # 4. Active structures (unbroken, most recent)
    active_bull = [tl for tl in bull_tl if not tl.broken]
    active_bear = [tl for tl in bear_tl if not tl.broken]

    if active_bull:
        result.active_trend_line = active_bull[0]
    elif active_bear:
        result.active_trend_line = active_bear[0]

    if result.channel_lines:
        result.active_channel_line = result.channel_lines[0]

    active_mc = [mc for mc in result.micro_channels if mc.still_active]
    if active_mc:
        result.active_micro_channel = active_mc[-1]

    # 5. Price position
    result.price_position = _determine_price_position(
        bars, bull_tl, bear_tl, result.channel_lines
    )

    # 6. Description
    parts = []
    if result.active_trend_line:
        parts.append(f"Active {result.active_trend_line.line_type.replace('_', ' ').lower()}: "
                     f"{result.active_trend_line.current_value:.2f}")
    if result.active_channel_line:
        parts.append(f"Channel line: {result.active_channel_line.current_value:.2f}")
    if result.active_micro_channel:
        parts.append(f"Micro channel: {result.active_micro_channel.direction} "
                     f"({result.active_micro_channel.bars} bars)")
    parts.append(f"Price position: {result.price_position}")
    result.description = " | ".join(parts) if parts else "No significant trend lines detected"

    return result
