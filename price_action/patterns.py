"""
Multi-Bar Pattern Detection — Al Brooks Methodology
=====================================================
Detects all key Al Brooks price action patterns from
"Trading Price Action: TRENDS".

Pattern Categories
------------------
1. **Inside Bar Patterns**: ii, iii, ioi — breakout mode setups
2. **High/Low Counting**: H1-H4, L1-L4 — pullback entry counting
3. **Double Bottom/Top Flags**: Failed breakout of prior extreme
4. **Wedge / 3-Push Patterns**: Three pushes to a new extreme,
   channels tightening — high-probability reversal
5. **Micro Double Bottom/Top**: Small consecutive equal lows/highs
6. **Expanding Triangle**: Higher highs AND lower lows alternating

Each pattern includes location, direction, and reliability rating.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from price_action.bar_types import BarAnalysis
from price_action import config as C


# ─────────────────────────────────────────────────────────────────
#  DATA CLASSES
# ─────────────────────────────────────────────────────────────────

@dataclass
class PatternDetection:
    """A detected multi-bar pattern."""
    name: str                   # Pattern name (e.g. "ii", "H2", "WEDGE_BULL")
    pattern_type: str           # Category: INSIDE | HL_COUNT | DOUBLE | WEDGE | EXPANDING
    direction: str              # "BULL" | "BEAR" | "NEUTRAL"
    start_idx: int = 0          # First bar index of pattern
    end_idx: int = 0            # Last bar index of pattern
    start_date: str = ""
    end_date: str = ""
    reliability: str = "MODERATE"  # "HIGH" | "MODERATE" | "LOW"
    description: str = ""
    trigger_price: float = 0.0  # Price that triggers the pattern
    stop_price: float = 0.0     # Suggested stop if pattern triggers


@dataclass
class PatternSummary:
    """Summary of all patterns detected in the chart."""
    patterns: List[PatternDetection] = field(default_factory=list)
    active_patterns: List[PatternDetection] = field(default_factory=list)  # Patterns at/near last bar
    bull_setups: int = 0
    bear_setups: int = 0
    breakout_mode: bool = False  # Inside bars at end = breakout imminent
    last_hl_bull: str = ""       # Last H-count (e.g. "H2")
    last_hl_bear: str = ""       # Last L-count (e.g. "L1")


# ─────────────────────────────────────────────────────────────────
#  1. INSIDE BAR PATTERNS: ii, iii, ioi
# ─────────────────────────────────────────────────────────────────

def detect_inside_bar_patterns(bars: List[BarAnalysis]) -> List[PatternDetection]:
    """
    Detect consecutive inside bars (ii, iii) and inside-outside-inside (ioi).

    Al Brooks: "ii" (two consecutive inside bars) is a BREAKOUT MODE setup.
    The tighter the range, the bigger the potential breakout.
    "iii" is even more compressed — bigger expected move.
    "ioi" (inside-outside-inside) is another breakout mode pattern.
    """
    patterns: List[PatternDetection] = []
    if len(bars) < 3:
        return patterns

    i = 1
    while i < len(bars):
        # Check for consecutive inside bars
        if bars[i].is_inside_bar:
            start = i
            count = 1
            # Count how many consecutive inside bars
            while i + 1 < len(bars) and bars[i + 1].is_inside_bar:
                i += 1
                count += 1

            if count >= 2:
                name = "iii" if count >= 3 else "ii"
                trigger_high = max(b.high for b in bars[start - 1:i + 1])
                trigger_low = min(b.low for b in bars[start - 1:i + 1])

                patterns.append(PatternDetection(
                    name=name,
                    pattern_type="INSIDE",
                    direction="NEUTRAL",  # Direction unknown until breakout
                    start_idx=start - 1,
                    end_idx=i,
                    start_date=bars[start - 1].date,
                    end_date=bars[i].date,
                    reliability="HIGH" if count >= 3 else "MODERATE",
                    description=f"{name} breakout mode — {count} consecutive inside bars. "
                                f"Buy above {trigger_high:.2f}, sell below {trigger_low:.2f}",
                    trigger_price=trigger_high,
                    stop_price=trigger_low,
                ))

        i += 1

    # Detect ioi (inside-outside-inside)
    for i in range(2, len(bars)):
        if bars[i - 2].is_inside_bar and bars[i - 1].is_outside_bar and bars[i].is_inside_bar:
            trigger_high = bars[i - 1].high
            trigger_low = bars[i - 1].low

            patterns.append(PatternDetection(
                name="ioi",
                pattern_type="INSIDE",
                direction="NEUTRAL",
                start_idx=i - 2,
                end_idx=i,
                start_date=bars[i - 2].date,
                end_date=bars[i].date,
                reliability="MODERATE",
                description=f"ioi breakout mode — inside-outside-inside. "
                            f"Buy above {trigger_high:.2f}, sell below {trigger_low:.2f}",
                trigger_price=trigger_high,
                stop_price=trigger_low,
            ))

    return patterns


# ─────────────────────────────────────────────────────────────────
#  2. HIGH / LOW COUNTING: H1-H4, L1-L4
# ─────────────────────────────────────────────────────────────────

def detect_hl_counts(bars: List[BarAnalysis]) -> List[PatternDetection]:
    """
    Detect Al Brooks H1-H4 and L1-L4 pullback entries.

    In a BULL trend:
    - H1: First bar whose high exceeds prior bar's high after a pullback (1st pullback entry)
    - H2: High above prior high after second pullback (BEST entry — "second entry long")
    - H3, H4: Third and fourth such entries (less reliable, trend aging)

    In a BEAR trend:
    - L1: First bar whose low is below prior bar's low after a pullback up
    - L2: Low below prior low after second pullback (BEST short entry)
    - L3, L4: Less reliable

    H2 and L2 are the MOST reliable entries per Al Brooks.
    """
    patterns: List[PatternDetection] = []
    if len(bars) < 5:
        return patterns

    # We need to detect pullback legs and count entries
    # Strategy: Walk bars, identify directional legs, count H/L entries

    _detect_h_counts(bars, patterns)
    _detect_l_counts(bars, patterns)

    return patterns


def _detect_h_counts(bars: List[BarAnalysis], patterns: List[PatternDetection]) -> None:
    """Detect H1, H2, H3, H4 in context of a bull trend."""
    n = len(bars)
    h_count = 0                  # How many H entries we've counter
    in_pullback = False          # Are we in a pullback?
    pullback_started = False
    trend_high = bars[0].high    # Highest high of the current bull leg

    for i in range(1, n):
        bar = bars[i]
        prev = bars[i - 1]

        # Track the trend high
        if bar.high > trend_high:
            trend_high = bar.high

        # Detect start of pullback: bar makes a lower high than prev
        if not in_pullback and bar.high < prev.high and bar.low < prev.low:
            in_pullback = True
            pullback_started = True

        # Detect end of pullback: bar's high exceeds prior bar's high
        # This is an H-entry
        if in_pullback and bar.high > prev.high:
            h_count += 1
            in_pullback = False

            if h_count <= 4:
                name = f"H{h_count}"
                if h_count == 2:
                    reliability = "HIGH"
                    desc = f"H2 — second entry long (most reliable). Buy above {bar.high:.2f}"
                elif h_count == 1:
                    reliability = "MODERATE"
                    desc = f"H1 — first pullback buy. Consider waiting for H2. Trigger {bar.high:.2f}"
                elif h_count == 3:
                    reliability = "MODERATE"
                    desc = f"H3 — third pullback buy, trend may be aging. Trigger {bar.high:.2f}"
                else:
                    reliability = "LOW"
                    desc = f"H4 — fourth entry, trend likely exhausted. Trigger {bar.high:.2f}"

                patterns.append(PatternDetection(
                    name=name,
                    pattern_type="HL_COUNT",
                    direction="BULL",
                    start_idx=i - 1,
                    end_idx=i,
                    start_date=prev.date,
                    end_date=bar.date,
                    reliability=reliability,
                    description=desc,
                    trigger_price=bar.high,
                    stop_price=bar.low,
                ))

        # Reset counters if significant reversal (e.g. 3+ bear trend bars)
        if i >= 3:
            recent_bears = sum(1 for b in bars[i - 2:i + 1] if b.is_trend_bar and b.is_bear)
            if recent_bears >= 3:
                h_count = 0
                in_pullback = False


def _detect_l_counts(bars: List[BarAnalysis], patterns: List[PatternDetection]) -> None:
    """Detect L1, L2, L3, L4 in context of a bear trend."""
    n = len(bars)
    l_count = 0
    in_pullback = False
    trend_low = bars[0].low

    for i in range(1, n):
        bar = bars[i]
        prev = bars[i - 1]

        if bar.low < trend_low:
            trend_low = bar.low

        # Start of pullback (up): bar makes higher low than prev
        if not in_pullback and bar.low > prev.low and bar.high > prev.high:
            in_pullback = True

        # End of pullback: bar's low goes below prior bar's low = L entry
        if in_pullback and bar.low < prev.low:
            l_count += 1
            in_pullback = False

            if l_count <= 4:
                name = f"L{l_count}"
                if l_count == 2:
                    reliability = "HIGH"
                    desc = f"L2 — second entry short (most reliable). Sell below {bar.low:.2f}"
                elif l_count == 1:
                    reliability = "MODERATE"
                    desc = f"L1 — first pullback sell. Consider waiting for L2. Trigger {bar.low:.2f}"
                elif l_count == 3:
                    reliability = "MODERATE"
                    desc = f"L3 — third pullback sell, trend may be aging. Trigger {bar.low:.2f}"
                else:
                    reliability = "LOW"
                    desc = f"L4 — fourth entry, trend likely exhausted. Trigger {bar.low:.2f}"

                patterns.append(PatternDetection(
                    name=name,
                    pattern_type="HL_COUNT",
                    direction="BEAR",
                    start_idx=i - 1,
                    end_idx=i,
                    start_date=prev.date,
                    end_date=bar.date,
                    reliability=reliability,
                    description=desc,
                    trigger_price=bar.low,
                    stop_price=bar.high,
                ))

        # Reset on 3+ bull trend bars
        if i >= 3:
            recent_bulls = sum(1 for b in bars[i - 2:i + 1] if b.is_trend_bar and b.is_bull)
            if recent_bulls >= 3:
                l_count = 0
                in_pullback = False


# ─────────────────────────────────────────────────────────────────
#  3. DOUBLE BOTTOM / TOP FLAGS
# ─────────────────────────────────────────────────────────────────

def detect_double_patterns(bars: List[BarAnalysis]) -> List[PatternDetection]:
    """
    Detect Double Bottom Bull Flag and Double Top Bear Flag.

    Al Brooks: A double bottom in a bear trend is actually a BULL FLAG
    (failed breakout below the first low → bears trapped → bulls enter).

    Double Bottom Bull Flag:
    - Two lows within tolerance that hold (within 1.5%)
    - Second low doesn't follow through below first
    - Triggered when price breaks above the bar between the two lows

    Double Top Bear Flag:
    - Two highs within tolerance that hold
    - Second high doesn't follow through
    - Triggered on break below the bar between the two highs
    """
    patterns: List[PatternDetection] = []
    if len(bars) < C.DB_MIN_SPACING + 2:
        return patterns

    n = len(bars)

    # Scan for swing lows (double bottom bull flag)
    swing_lows = _find_swing_points(bars, "LOW")
    for i in range(len(swing_lows) - 1):
        idx1, price1 = swing_lows[i]
        idx2, price2 = swing_lows[i + 1]

        spacing = idx2 - idx1
        if spacing < C.DB_MIN_SPACING or spacing > C.DB_MAX_SPACING:
            continue

        # Check if the two lows are within tolerance
        avg_price = (price1 + price2) / 2
        if avg_price == 0:
            continue
        diff_pct = abs(price1 - price2) / avg_price
        if diff_pct > C.DB_PRICE_TOLERANCE:
            continue

        # Find the high between the two lows (the neckline)
        between = bars[idx1:idx2 + 1]
        neckline = max(b.high for b in between)

        patterns.append(PatternDetection(
            name="DB_BULL_FLAG",
            pattern_type="DOUBLE",
            direction="BULL",
            start_idx=idx1,
            end_idx=idx2,
            start_date=bars[idx1].date,
            end_date=bars[idx2].date,
            reliability="HIGH",
            description=f"Double Bottom Bull Flag — two equal lows at ~{avg_price:.2f}. "
                        f"Buy above neckline {neckline:.2f}, stop below {min(price1, price2):.2f}",
            trigger_price=neckline,
            stop_price=min(price1, price2),
        ))

    # Scan for swing highs (double top bear flag)
    swing_highs = _find_swing_points(bars, "HIGH")
    for i in range(len(swing_highs) - 1):
        idx1, price1 = swing_highs[i]
        idx2, price2 = swing_highs[i + 1]

        spacing = idx2 - idx1
        if spacing < C.DB_MIN_SPACING or spacing > C.DB_MAX_SPACING:
            continue

        avg_price = (price1 + price2) / 2
        if avg_price == 0:
            continue
        diff_pct = abs(price1 - price2) / avg_price
        if diff_pct > C.DB_PRICE_TOLERANCE:
            continue

        between = bars[idx1:idx2 + 1]
        neckline = min(b.low for b in between)

        patterns.append(PatternDetection(
            name="DT_BEAR_FLAG",
            pattern_type="DOUBLE",
            direction="BEAR",
            start_idx=idx1,
            end_idx=idx2,
            start_date=bars[idx1].date,
            end_date=bars[idx2].date,
            reliability="HIGH",
            description=f"Double Top Bear Flag — two equal highs at ~{avg_price:.2f}. "
                        f"Sell below neckline {neckline:.2f}, stop above {max(price1, price2):.2f}",
            trigger_price=neckline,
            stop_price=max(price1, price2),
        ))

    return patterns


# ─────────────────────────────────────────────────────────────────
#  4. WEDGE / 3-PUSH PATTERNS
# ─────────────────────────────────────────────────────────────────

def detect_wedge_patterns(bars: List[BarAnalysis]) -> List[PatternDetection]:
    """
    Detect wedge (3-push) patterns.

    Al Brooks: "Most reversals begin with a wedge — three pushes to a new
    extreme with each push creating a new high/low but with diminishing
    momentum."

    Bull Wedge (at bottom, reversal to upside):
    - Three lower lows, each progressively less deep
    - Momentum diminishing (smaller trend bars, more overlap)
    - Triggered on break above the high of the third push

    Bear Wedge (at top, reversal to downside):
    - Three higher highs, each progressively less extreme
    - Triggered on break below the low of the third push
    """
    patterns: List[PatternDetection] = []
    if len(bars) < C.WEDGE_MIN_PUSHES * 3:
        return patterns

    # Detect bull wedges (3 lower lows with diminishing momentum)
    swing_lows = _find_swing_points(bars, "LOW")
    _detect_wedge_from_swings(swing_lows, bars, "BULL", patterns)

    # Detect bear wedges (3 higher highs with diminishing momentum)
    swing_highs = _find_swing_points(bars, "HIGH")
    _detect_wedge_from_swings(swing_highs, bars, "BEAR", patterns)

    return patterns


def _detect_wedge_from_swings(
    swings: List[tuple],
    bars: List[BarAnalysis],
    direction: str,
    patterns: List[PatternDetection],
) -> None:
    """Search swing points for 3-push wedge pattern."""
    if len(swings) < 3:
        return

    for i in range(len(swings) - 2):
        idx1, p1 = swings[i]
        idx2, p2 = swings[i + 1]
        idx3, p3 = swings[i + 2]

        # Check spacing
        total_span = idx3 - idx1
        if total_span > C.WEDGE_MAX_LOOKBACK:
            continue
        if total_span < C.WEDGE_MIN_PUSHES * 2:
            continue

        if direction == "BULL":
            # Looking for 3 lower lows (wedge bottom)
            if p2 < p1 and p3 < p2:
                # Diminishing momentum: distance between pushes decreasing
                drop1 = p1 - p2
                drop2 = p2 - p3
                if drop2 < drop1:  # Momentum slowing
                    trigger = bars[idx3].high
                    stop = p3

                    patterns.append(PatternDetection(
                        name="WEDGE_BULL",
                        pattern_type="WEDGE",
                        direction="BULL",
                        start_idx=idx1,
                        end_idx=idx3,
                        start_date=bars[idx1].date,
                        end_date=bars[idx3].date,
                        reliability="HIGH",
                        description=f"Bull Wedge (3-push bottom) — three lower lows "
                                    f"({p1:.2f} → {p2:.2f} → {p3:.2f}) with diminishing "
                                    f"momentum. Buy above {trigger:.2f}, stop {stop:.2f}",
                        trigger_price=trigger,
                        stop_price=stop,
                    ))
        else:  # BEAR
            # Looking for 3 higher highs (wedge top)
            if p2 > p1 and p3 > p2:
                rise1 = p2 - p1
                rise2 = p3 - p2
                if rise2 < rise1:
                    trigger = bars[idx3].low
                    stop = p3

                    patterns.append(PatternDetection(
                        name="WEDGE_BEAR",
                        pattern_type="WEDGE",
                        direction="BEAR",
                        start_idx=idx1,
                        end_idx=idx3,
                        start_date=bars[idx1].date,
                        end_date=bars[idx3].date,
                        reliability="HIGH",
                        description=f"Bear Wedge (3-push top) — three higher highs "
                                    f"({p1:.2f} → {p2:.2f} → {p3:.2f}) with diminishing "
                                    f"momentum. Sell below {trigger:.2f}, stop {stop:.2f}",
                        trigger_price=trigger,
                        stop_price=stop,
                    ))


# ─────────────────────────────────────────────────────────────────
#  5. MICRO DOUBLE BOTTOM / TOP
# ─────────────────────────────────────────────────────────────────

def detect_micro_doubles(bars: List[BarAnalysis]) -> List[PatternDetection]:
    """
    Detect micro double bottom/top (2-3 bars with equal extremes).

    Al Brooks: Small double bottoms/tops are very common and provide
    excellent entries when they occur at the right location (e.g. at
    a pullback in a trend).
    """
    patterns: List[PatternDetection] = []
    if len(bars) < 3:
        return patterns

    for i in range(1, len(bars)):
        bar = bars[i]
        prev = bars[i - 1]
        avg_range = (bar.range_size + prev.range_size) / 2
        if avg_range == 0:
            continue

        # Micro double bottom: two adjacent lows nearly equal
        low_diff = abs(bar.low - prev.low)
        if low_diff / avg_range < 0.15:  # Very close lows
            trigger = max(bar.high, prev.high)
            patterns.append(PatternDetection(
                name="MICRO_DB",
                pattern_type="DOUBLE",
                direction="BULL",
                start_idx=i - 1,
                end_idx=i,
                start_date=prev.date,
                end_date=bar.date,
                reliability="MODERATE",
                description=f"Micro double bottom — equal lows ~{min(bar.low, prev.low):.2f}. "
                            f"Buy above {trigger:.2f}",
                trigger_price=trigger,
                stop_price=min(bar.low, prev.low),
            ))

        # Micro double top: two adjacent highs nearly equal
        high_diff = abs(bar.high - prev.high)
        if high_diff / avg_range < 0.15:
            trigger = min(bar.low, prev.low)
            patterns.append(PatternDetection(
                name="MICRO_DT",
                pattern_type="DOUBLE",
                direction="BEAR",
                start_idx=i - 1,
                end_idx=i,
                start_date=prev.date,
                end_date=bar.date,
                reliability="MODERATE",
                description=f"Micro double top — equal highs ~{max(bar.high, prev.high):.2f}. "
                            f"Sell below {trigger:.2f}",
                trigger_price=trigger,
                stop_price=max(bar.high, prev.high),
            ))

    return patterns


# ─────────────────────────────────────────────────────────────────
#  6. EXPANDING TRIANGLE
# ─────────────────────────────────────────────────────────────────

def detect_expanding_triangle(bars: List[BarAnalysis]) -> List[PatternDetection]:
    """
    Detect expanding triangle (higher highs AND lower lows).

    Al Brooks: Expanding triangles are rare but significant — they show
    extreme indecision. The breakout from the final swing is usually decisive.
    """
    patterns: List[PatternDetection] = []
    if len(bars) < 10:
        return patterns

    swing_highs = _find_swing_points(bars, "HIGH")
    swing_lows = _find_swing_points(bars, "LOW")

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return patterns

    # Check recent swings for expanding pattern
    for i in range(len(swing_highs) - 1):
        hi_idx1, hi_p1 = swing_highs[i]
        hi_idx2, hi_p2 = swing_highs[i + 1]

        if hi_p2 <= hi_p1:
            continue  # Need higher highs

        # Find matching lower lows between these highs
        matching_lows = [
            (li, lp) for li, lp in swing_lows
            if hi_idx1 <= li <= hi_idx2
        ]
        if len(matching_lows) < 1:
            continue

        # Check there's also a lower low in that region
        for j in range(len(swing_lows) - 1):
            lo_idx1, lo_p1 = swing_lows[j]
            lo_idx2, lo_p2 = swing_lows[j + 1]

            if lo_p2 >= lo_p1:
                continue  # Need lower lows

            # Both expanding and overlapping in time?
            start = min(hi_idx1, lo_idx1)
            end = max(hi_idx2, lo_idx2)
            if end - start > 40 or end - start < 6:
                continue

            patterns.append(PatternDetection(
                name="EXPANDING_TRIANGLE",
                pattern_type="EXPANDING",
                direction="NEUTRAL",
                start_idx=start,
                end_idx=end,
                start_date=bars[start].date,
                end_date=bars[end].date,
                reliability="MODERATE",
                description=f"Expanding Triangle — higher highs AND lower lows. "
                            f"Extreme indecision. Watch for decisive breakout.",
                trigger_price=hi_p2,
                stop_price=lo_p2,
            ))
            break  # Only one per high pair

    return patterns


# ─────────────────────────────────────────────────────────────────
#  HELPER: SWING POINT DETECTION
# ─────────────────────────────────────────────────────────────────

def _find_swing_points(
    bars: List[BarAnalysis],
    point_type: str,  # "HIGH" or "LOW"
    lookback: int = 3,
) -> List[tuple]:
    """
    Find swing highs or swing lows.

    A swing high: bar whose high is higher than the `lookback` bars on each side.
    A swing low: bar whose low is lower than the `lookback` bars on each side.

    Returns list of (index, price) tuples.
    """
    points: List[tuple] = []
    if len(bars) < 2 * lookback + 1:
        return points

    for i in range(lookback, len(bars) - lookback):
        if point_type == "HIGH":
            val = bars[i].high
            is_swing = all(val >= bars[i - j].high for j in range(1, lookback + 1)) and \
                       all(val >= bars[i + j].high for j in range(1, lookback + 1))
        else:
            val = bars[i].low
            is_swing = all(val <= bars[i - j].low for j in range(1, lookback + 1)) and \
                       all(val <= bars[i + j].low for j in range(1, lookback + 1))

        if is_swing:
            points.append((i, val))

    return points


# ─────────────────────────────────────────────────────────────────
#  MASTER PATTERN DETECTOR
# ─────────────────────────────────────────────────────────────────

def detect_all_patterns(bars: List[BarAnalysis]) -> PatternSummary:
    """
    Run all pattern detectors and return a comprehensive PatternSummary.

    Parameters
    ----------
    bars : list[BarAnalysis]
        Fully classified bars from bar_types.classify_bars().

    Returns
    -------
    PatternSummary
        All detected patterns with active patterns near the last bar.
    """
    if not bars:
        return PatternSummary()

    all_patterns: List[PatternDetection] = []

    # Run all detectors
    all_patterns.extend(detect_inside_bar_patterns(bars))
    all_patterns.extend(detect_hl_counts(bars))
    all_patterns.extend(detect_double_patterns(bars))
    all_patterns.extend(detect_wedge_patterns(bars))
    all_patterns.extend(detect_micro_doubles(bars))
    all_patterns.extend(detect_expanding_triangle(bars))

    # Sort by end_idx (most recent patterns last)
    all_patterns.sort(key=lambda p: p.end_idx)

    # Identify active patterns (within last 5 bars)
    last_idx = len(bars) - 1
    active = [p for p in all_patterns if p.end_idx >= last_idx - 5]

    # Count setups
    bull_setups = sum(1 for p in active if p.direction == "BULL")
    bear_setups = sum(1 for p in active if p.direction == "BEAR")

    # Check if we're in breakout mode (recent inside bars)
    breakout_mode = any(p.pattern_type == "INSIDE" for p in active)

    # Find last H/L counts near the end
    recent_h = [p for p in all_patterns if p.name.startswith("H") and p.end_idx >= last_idx - 10]
    recent_l = [p for p in all_patterns if p.name.startswith("L") and p.end_idx >= last_idx - 10]

    last_hl_bull = recent_h[-1].name if recent_h else ""
    last_hl_bear = recent_l[-1].name if recent_l else ""

    return PatternSummary(
        patterns=all_patterns,
        active_patterns=active,
        bull_setups=bull_setups,
        bear_setups=bear_setups,
        breakout_mode=breakout_mode,
        last_hl_bull=last_hl_bull,
        last_hl_bear=last_hl_bear,
    )
