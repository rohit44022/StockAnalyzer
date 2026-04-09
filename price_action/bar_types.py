"""
Bar-by-Bar Classification — Al Brooks Methodology
===================================================
Classifies each bar on a price chart according to Al Brooks'
price action terminology from "Trading Price Action: TRENDS".

Bar Types
---------
- **Trend Bar** (Bull/Bear): Body is large relative to range, close near extreme.
  Strong conviction — bears/bulls clearly in control.
- **Doji**: Small body relative to range. Neither side dominant.
  Signals indecision, possible reversal in context.
- **Outside Bar**: High > prior high AND low < prior low. Engulfs prior bar.
  Very significant — direction of close matters.
- **Inside Bar**: High ≤ prior high AND low ≥ prior low. Contained by prior.
  Breakout mode setup — watch for direction of breakout.
- **Signal/Reversal Bar**: Bar with prominent tail showing rejection.
  Bull reversal bar at bottom: lower tail, close near high.
  Bear reversal bar at top: upper tail, close near low.
- **Climax Bar**: Extreme range bar (>2x ATR) late in a trend.
  Often signals exhaustion and pending reversal.

Each bar gets a full BarAnalysis object with classification, metrics,
and contextual notes relevant to Al Brooks' methodology.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Literal

import numpy as np
import pandas as pd

from price_action import config as C


# ─────────────────────────────────────────────────────────────────
#  DATA CLASSES
# ─────────────────────────────────────────────────────────────────

@dataclass
class BarAnalysis:
    """Complete Al Brooks classification for a single bar."""

    # Identity
    index: int                              # Position in DataFrame
    date: str = ""                          # ISO date string

    # OHLCV
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0

    # ── Primary Classification ──
    bar_type: str = "UNKNOWN"
    # One of: STRONG_BULL_TREND, BULL_TREND, MODERATE_BULL,
    #         DOJI, MODERATE_BEAR, BEAR_TREND, STRONG_BEAR_TREND

    is_bull: bool = False                   # Close >= Open
    is_bear: bool = False                   # Close < Open

    # ── Body & Tail Metrics ──
    range_size: float = 0.0                 # High - Low
    body_size: float = 0.0                  # abs(Close - Open)
    body_pct: float = 0.0                   # body / range (0-1)
    upper_tail: float = 0.0                 # High - max(Open, Close)
    lower_tail: float = 0.0                 # min(Open, Close) - Low
    upper_tail_pct: float = 0.0             # upper_tail / range
    lower_tail_pct: float = 0.0             # lower_tail / range

    # Close position (0=low, 1=high)
    close_position: float = 0.0            # (Close - Low) / Range
    close_zone: str = "MIDDLE"             # UPPER_THIRD / MIDDLE / LOWER_THIRD

    # ── Special Bar Types ──
    is_outside_bar: bool = False            # Engulfs prior bar
    is_inside_bar: bool = False             # Contained by prior bar
    is_doji: bool = False                   # Small body
    is_trend_bar: bool = False              # Significant body, close near extreme
    is_strong_trend_bar: bool = False       # Very large body, close at extreme

    # ── Signal / Reversal Bar ──
    is_signal_bar: bool = False             # Potential reversal bar
    signal_direction: str = "NONE"          # "BULL_REVERSAL" / "BEAR_REVERSAL" / "NONE"
    signal_quality: str = "NONE"            # "STRONG" / "MODERATE" / "WEAK" / "NONE"

    # ── Climax Bar ──
    is_climax_bar: bool = False             # Range > 2x ATR late in trend
    climax_direction: str = "NONE"          # "BULL_CLIMAX" / "BEAR_CLIMAX" / "NONE"

    # ── Shaved Bar ──
    is_shaved_top: bool = False             # No upper tail (close = high for bull)
    is_shaved_bottom: bool = False          # No lower tail

    # ── Context Flags (set by higher-level analysis) ──
    bars_in_current_move: int = 0           # How many bars into current leg
    atr: float = 0.0                        # ATR at this bar

    # ── Summary ──
    description: str = ""                   # Human-readable Al Brooks description


# ─────────────────────────────────────────────────────────────────
#  CORE CLASSIFICATION
# ─────────────────────────────────────────────────────────────────

def _classify_single_bar(
    o: float, h: float, l: float, c: float, v: float,
    prev_h: float, prev_l: float, atr: float,
) -> BarAnalysis:
    """Classify a single bar using Al Brooks' methodology."""

    ba = BarAnalysis(index=0)
    ba.open, ba.high, ba.low, ba.close, ba.volume = o, h, l, c, v

    range_size = h - l
    ba.range_size = range_size

    # ── Zero-range bar (rare: single tick or no movement) ──
    if range_size <= 0 or math.isnan(range_size):
        ba.bar_type = "DOJI"
        ba.is_doji = True
        ba.description = "Zero-range bar — no price movement"
        return ba

    # ── Body & tail metrics ──
    ba.is_bull = c >= o
    ba.is_bear = c < o

    ba.body_size = abs(c - o)
    ba.body_pct = ba.body_size / range_size

    bar_high_body = max(o, c)
    bar_low_body = min(o, c)

    ba.upper_tail = h - bar_high_body
    ba.lower_tail = bar_low_body - l
    ba.upper_tail_pct = ba.upper_tail / range_size
    ba.lower_tail_pct = ba.lower_tail / range_size

    # Close position within range (0 = at low, 1 = at high)
    ba.close_position = (c - l) / range_size

    if ba.close_position >= C.CLOSE_UPPER_THIRD:
        ba.close_zone = "UPPER_THIRD"
    elif ba.close_position <= C.CLOSE_LOWER_THIRD:
        ba.close_zone = "LOWER_THIRD"
    else:
        ba.close_zone = "MIDDLE"

    # ── Shaved bars ──
    ba.is_shaved_top = ba.upper_tail_pct < C.SMALL_TAIL_PCT
    ba.is_shaved_bottom = ba.lower_tail_pct < C.SMALL_TAIL_PCT

    # ── Primary bar type classification ──
    if ba.body_pct < C.DOJI_BODY_PCT:
        ba.bar_type = "DOJI"
        ba.is_doji = True
    elif ba.body_pct >= C.STRONG_TREND_BAR_BODY_PCT:
        if ba.is_bull and ba.close_zone == "UPPER_THIRD":
            ba.bar_type = "STRONG_BULL_TREND"
            ba.is_trend_bar = True
            ba.is_strong_trend_bar = True
        elif ba.is_bear and ba.close_zone == "LOWER_THIRD":
            ba.bar_type = "STRONG_BEAR_TREND"
            ba.is_trend_bar = True
            ba.is_strong_trend_bar = True
        elif ba.is_bull:
            ba.bar_type = "BULL_TREND"
            ba.is_trend_bar = True
        else:
            ba.bar_type = "BEAR_TREND"
            ba.is_trend_bar = True
    elif ba.body_pct >= C.TREND_BAR_BODY_PCT:
        if ba.is_bull:
            ba.bar_type = "BULL_TREND"
            ba.is_trend_bar = True
        else:
            ba.bar_type = "BEAR_TREND"
            ba.is_trend_bar = True
    else:
        ba.bar_type = "MODERATE_BULL" if ba.is_bull else "MODERATE_BEAR"

    # ── Outside / Inside bar detection ──
    if not (math.isnan(prev_h) or math.isnan(prev_l)):
        tol = range_size * C.INSIDE_BAR_TOLERANCE
        if h >= prev_h and l <= prev_l:
            ba.is_outside_bar = True
        if h <= prev_h + tol and l >= prev_l - tol:
            ba.is_inside_bar = True

    # ── Climax bar detection ──
    if atr > 0 and range_size > C.CLIMAX_ATR_MULTIPLE * atr:
        ba.is_climax_bar = True
        ba.climax_direction = "BULL_CLIMAX" if ba.is_bull else "BEAR_CLIMAX"

    ba.atr = atr

    # ── Build description ──
    ba.description = _build_description(ba)

    return ba


def _build_description(ba: BarAnalysis) -> str:
    """Build human-readable Al Brooks bar description."""
    parts: List[str] = []

    if ba.is_climax_bar:
        parts.append(f"{'Bull' if ba.is_bull else 'Bear'} CLIMAX bar")
    elif ba.is_strong_trend_bar:
        parts.append(f"Strong {'bull' if ba.is_bull else 'bear'} trend bar")
    elif ba.is_trend_bar:
        parts.append(f"{'Bull' if ba.is_bull else 'Bear'} trend bar")
    elif ba.is_doji:
        parts.append("Doji — indecision")
    else:
        parts.append(f"Moderate {'bull' if ba.is_bull else 'bear'} bar")

    if ba.is_outside_bar:
        parts.append("outside bar (engulfs prior)")
    if ba.is_inside_bar:
        parts.append("inside bar (breakout mode)")

    if ba.is_shaved_top and ba.is_bull:
        parts.append("shaved top (strong bull close)")
    if ba.is_shaved_bottom and ba.is_bear:
        parts.append("shaved bottom (strong bear close)")

    if ba.is_signal_bar:
        parts.append(f"{ba.signal_direction.replace('_', ' ').title()} signal ({ba.signal_quality.lower()})")

    tail_parts = []
    if ba.upper_tail_pct > C.SIGNIFICANT_TAIL_PCT:
        tail_parts.append("prominent upper tail (selling pressure)")
    if ba.lower_tail_pct > C.SIGNIFICANT_TAIL_PCT:
        tail_parts.append("prominent lower tail (buying pressure)")
    if tail_parts:
        parts.extend(tail_parts)

    return "; ".join(parts)


# ─────────────────────────────────────────────────────────────────
#  SIGNAL BAR DETECTION (requires context of prior bars)
# ─────────────────────────────────────────────────────────────────

def _detect_signal_bars(bars: List[BarAnalysis]) -> None:
    """
    Detect signal (reversal) bars in context of prior price action.
    Mutates the bar objects in-place.

    Al Brooks signal bar criteria:
    - Bull reversal bar: appears after down move, prominent lower tail,
      close near or above midpoint, ideally bull body
    - Bear reversal bar: appears after up move, prominent upper tail,
      close near or below midpoint, ideally bear body

    Brooks Ch 5: "The stronger the trend, the less important it is to have
    a strong signal bar for a with-trend trade."
    Brooks Ch 5: Overlap check — if midpoint of bull reversal bar is above
    low of prior bar, overlap may be excessive (trading range, not reversal).
    """
    if len(bars) < C.MIN_BARS_IN_MOVE + 1:
        return

    for i in range(C.MIN_BARS_IN_MOVE, len(bars)):
        bar = bars[i]

        # Count recent move direction
        recent = bars[max(0, i - C.MIN_BARS_IN_MOVE):i]
        bear_count = sum(1 for b in recent if b.is_bear)
        bull_count = sum(1 for b in recent if b.is_bull)

        # Also check if there's a directional move (lower lows / higher highs)
        move_lows = [b.low for b in recent]
        move_highs = [b.high for b in recent]

        down_move = move_lows[-1] < move_lows[0]  # trending down
        up_move = move_highs[-1] > move_highs[0]  # trending up

        prev_bar = bars[i - 1]

        # ── Bull Reversal Bar ──
        # After a down move: prominent lower tail, close in upper half
        # Brooks: body_max constraint relaxed — strong trend bars can be signal bars
        if (down_move or bear_count >= bull_count) and \
           bar.lower_tail_pct >= C.REVERSAL_BAR_TAIL_MIN and \
           bar.close_position >= 0.50:

            bar.is_signal_bar = True
            bar.signal_direction = "BULL_REVERSAL"

            # Brooks Ch 5: Overlap check for countertrend entries
            # If midpoint of reversal bar is above low of prior bar = excessive overlap
            bar_midpoint = (bar.high + bar.low) / 2.0
            excessive_overlap = bar_midpoint > prev_bar.low

            # Quality assessment (Brooks: tail, body, close position, overlap)
            if bar.is_bull and bar.lower_tail_pct > 0.40 and bar.close_zone == "UPPER_THIRD" and not excessive_overlap:
                bar.signal_quality = "STRONG"
            elif bar.is_bull or bar.lower_tail_pct > 0.35:
                bar.signal_quality = "MODERATE" if not excessive_overlap else "WEAK"
            else:
                bar.signal_quality = "WEAK"

        # ── Bear Reversal Bar ──
        # After an up move: prominent upper tail, close in lower half
        elif (up_move or bull_count >= bear_count) and \
             bar.upper_tail_pct >= C.REVERSAL_BAR_TAIL_MIN and \
             bar.close_position <= 0.50:

            bar.is_signal_bar = True
            bar.signal_direction = "BEAR_REVERSAL"

            # Overlap check: if midpoint of bear reversal is below high of prior bar
            bar_midpoint = (bar.high + bar.low) / 2.0
            excessive_overlap = bar_midpoint < prev_bar.high

            if bar.is_bear and bar.upper_tail_pct > 0.40 and bar.close_zone == "LOWER_THIRD" and not excessive_overlap:
                bar.signal_quality = "STRONG"
            elif bar.is_bear or bar.upper_tail_pct > 0.35:
                bar.signal_quality = "MODERATE" if not excessive_overlap else "WEAK"
            else:
                bar.signal_quality = "WEAK"

    # Rebuild descriptions for signal bars
    for bar in bars:
        if bar.is_signal_bar:
            bar.description = _build_description(bar)


# ─────────────────────────────────────────────────────────────────
#  MAIN ENTRY POINT — CLASSIFY ALL BARS
# ─────────────────────────────────────────────────────────────────

def classify_bars(df: pd.DataFrame) -> List[BarAnalysis]:
    """
    Classify every bar in a DataFrame using Al Brooks' methodology.

    Parameters
    ----------
    df : pd.DataFrame
        Must have columns: Open, High, Low, Close, Volume.
        Index should be DatetimeIndex.

    Returns
    -------
    list[BarAnalysis]
        One BarAnalysis object per row, fully classified.
    """
    if len(df) < C.MIN_BARS_REQUIRED:
        return []

    # Compute ATR for climax detection
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift(1)).abs(),
        (df["Low"] - df["Close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr_series = tr.rolling(window=C.ATR_PERIOD, min_periods=1).mean()

    opens = df["Open"].values
    highs = df["High"].values
    lows = df["Low"].values
    closes = df["Close"].values
    volumes = df["Volume"].values if "Volume" in df.columns else np.zeros(len(df))
    atrs = atr_series.values

    dates = df.index
    bars: List[BarAnalysis] = []

    for i in range(len(df)):
        prev_h = highs[i - 1] if i > 0 else float("nan")
        prev_l = lows[i - 1] if i > 0 else float("nan")

        ba = _classify_single_bar(
            o=opens[i], h=highs[i], l=lows[i], c=closes[i],
            v=volumes[i], prev_h=prev_h, prev_l=prev_l,
            atr=atrs[i],
        )
        ba.index = i

        # Set date
        try:
            ba.date = str(dates[i].date()) if hasattr(dates[i], "date") else str(dates[i])
        except Exception:
            ba.date = str(i)

        bars.append(ba)

    # Detect signal bars (requires context of surrounding bars)
    _detect_signal_bars(bars)

    # Count bars in current directional move
    _count_bars_in_move(bars)

    return bars


def _count_bars_in_move(bars: List[BarAnalysis]) -> None:
    """Count consecutive bars in the current directional move."""
    if not bars:
        return

    move_dir = "BULL" if bars[0].is_bull else "BEAR"
    count = 1
    bars[0].bars_in_current_move = 1

    for i in range(1, len(bars)):
        current_dir = "BULL" if bars[i].is_bull else "BEAR"
        if current_dir == move_dir:
            count += 1
        else:
            move_dir = current_dir
            count = 1
        bars[i].bars_in_current_move = count


# ─────────────────────────────────────────────────────────────────
#  SUMMARY STATISTICS
# ─────────────────────────────────────────────────────────────────

def bar_summary(bars: List[BarAnalysis], lookback: int = 20) -> dict:
    """
    Summarize recent bar classifications for quick overview.

    Returns dict with counts and ratios of bar types over the lookback period.
    """
    if not bars:
        return {}

    recent = bars[-lookback:]
    n = len(recent)

    bull_trend = sum(1 for b in recent if b.is_trend_bar and b.is_bull)
    bear_trend = sum(1 for b in recent if b.is_trend_bar and b.is_bear)
    strong_bull = sum(1 for b in recent if b.is_strong_trend_bar and b.is_bull)
    strong_bear = sum(1 for b in recent if b.is_strong_trend_bar and b.is_bear)
    dojis = sum(1 for b in recent if b.is_doji)
    outside = sum(1 for b in recent if b.is_outside_bar)
    inside = sum(1 for b in recent if b.is_inside_bar)
    signal = sum(1 for b in recent if b.is_signal_bar)
    climax = sum(1 for b in recent if b.is_climax_bar)
    bull_reversal = sum(1 for b in recent if b.signal_direction == "BULL_REVERSAL")
    bear_reversal = sum(1 for b in recent if b.signal_direction == "BEAR_REVERSAL")

    return {
        "lookback": n,
        "bull_trend_bars": bull_trend,
        "bear_trend_bars": bear_trend,
        "strong_bull_bars": strong_bull,
        "strong_bear_bars": strong_bear,
        "doji_bars": dojis,
        "outside_bars": outside,
        "inside_bars": inside,
        "signal_bars": signal,
        "climax_bars": climax,
        "bull_reversal_signals": bull_reversal,
        "bear_reversal_signals": bear_reversal,
        "bull_pct": round(bull_trend / n * 100, 1) if n > 0 else 0,
        "bear_pct": round(bear_trend / n * 100, 1) if n > 0 else 0,
        "doji_pct": round(dojis / n * 100, 1) if n > 0 else 0,
        "trend_dominance": "BULL" if bull_trend > bear_trend else ("BEAR" if bear_trend > bull_trend else "NEUTRAL"),
    }
