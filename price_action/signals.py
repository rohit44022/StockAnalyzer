"""
Price Action Signal Generation — Al Brooks Methodology
========================================================
Combines all PA analysis components (bars, patterns, trend, channels,
breakouts) into actionable BUY / SELL / HOLD signals with confidence
scoring and risk management.

Signal Types
------------
- **BREAKOUT_BUY / BREAKOUT_SELL**: Price breaking key level with conviction
- **PULLBACK_BUY / PULLBACK_SELL**: H2/L2 entries in established trends
- **REVERSAL_BUY / REVERSAL_SELL**: Wedge/climax/signal bar reversals
- **TREND_CONTINUATION**: Strong trend bar after pullback
- **FAILED_BREAKOUT**: Trap setup — trade against the failed side
- **SECOND_ENTRY**: Failed failure — highest probability trade
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Optional

from price_action.bar_types import BarAnalysis, bar_summary
from price_action.patterns import PatternSummary
from price_action.trend_analyzer import TrendState
from price_action.channels import ChannelAnalysis
from price_action.breakouts import BreakoutAnalysis
from price_action import config as C


# ─────────────────────────────────────────────────────────────────
#  DATA CLASSES
# ─────────────────────────────────────────────────────────────────

@dataclass
class PASignal:
    """A price action signal with full context."""
    signal_type: str            # "BUY" | "SELL" | "HOLD"
    setup_type: str             # BREAKOUT | PULLBACK | REVERSAL | TREND_CONT |
                                # FAILED_BREAKOUT | SECOND_ENTRY
    strength: str               # "STRONG" | "MODERATE" | "WEAK"
    confidence: int             # 0-100

    # Price levels
    entry_price: float = 0.0
    stop_loss: float = 0.0
    target_1: float = 0.0      # Conservative target
    target_2: float = 0.0      # Aggressive target
    risk_reward: float = 0.0   # Risk/reward ratio

    # Component scores (contributing to confidence)
    scores: Dict[str, float] = field(default_factory=dict)

    # Context
    reasons: List[str] = field(default_factory=list)
    al_brooks_context: str = ""  # Human-readable Al Brooks explanation
    description: str = ""


@dataclass
class PASignalResult:
    """Complete signal generation result."""
    primary_signal: PASignal = field(default_factory=lambda: PASignal(
        signal_type="HOLD", setup_type="NONE", strength="NONE", confidence=0,
    ))
    secondary_signals: List[PASignal] = field(default_factory=list)

    # Component summaries for the UI
    bar_summary: dict = field(default_factory=dict)
    trend_summary: str = ""
    pattern_summary: str = ""
    channel_summary: str = ""
    breakout_summary: str = ""

    # Overall PA verdict
    pa_score: float = 0.0       # -100 to +100 (+ve = bullish)
    pa_verdict: str = "HOLD"    # "STRONG BUY" | "BUY" | "HOLD" | "SELL" | "STRONG SELL"
    pa_confidence: float = 0.0  # 0-100


# ─────────────────────────────────────────────────────────────────
#  SIGNAL SCORING ENGINE
# ─────────────────────────────────────────────────────────────────

def _score_trend_direction(trend: TrendState, direction: str) -> float:
    """Score: Is the signal aligned with the trend? (0-25 points)"""
    score = 0.0

    # Always-in alignment
    if direction == "BUY" and trend.always_in == "LONG":
        score += 15
    elif direction == "SELL" and trend.always_in == "SHORT":
        score += 15
    elif trend.always_in == "FLAT":
        score += 5  # Neutral — no bonus, no penalty

    # Trend strength bonus
    if trend.trend_strength >= 70:
        if (direction == "BUY" and trend.trend_direction == "BULL") or \
           (direction == "SELL" and trend.trend_direction == "BEAR"):
            score += 10
    elif trend.trend_strength >= 40:
        score += 5

    return min(score, C.W_TREND_DIRECTION)


def _score_bar_quality(bars: List[BarAnalysis], direction: str) -> float:
    """Score: Quality of the last bar as a signal bar. (0-15 points)"""
    if not bars:
        return 0.0

    last = bars[-1]
    score = 0.0

    # Signal bar present
    if last.is_signal_bar:
        if direction == "BUY" and last.signal_direction == "BULL_REVERSAL":
            quality_map = {"STRONG": 15, "MODERATE": 10, "WEAK": 5}
            score += quality_map.get(last.signal_quality, 0)
        elif direction == "SELL" and last.signal_direction == "BEAR_REVERSAL":
            quality_map = {"STRONG": 15, "MODERATE": 10, "WEAK": 5}
            score += quality_map.get(last.signal_quality, 0)

    # Trend bar in signal direction
    elif direction == "BUY" and last.is_trend_bar and last.is_bull:
        score += 10 if last.is_strong_trend_bar else 7
    elif direction == "SELL" and last.is_trend_bar and last.is_bear:
        score += 10 if last.is_strong_trend_bar else 7

    # Doji at the right place (possible reversal)
    elif last.is_doji:
        score += 3

    return min(score, C.W_BAR_QUALITY)


def _score_pattern_match(patterns: PatternSummary, direction: str) -> float:
    """Score: Active patterns supporting the signal direction. (0-15 points)"""
    score = 0.0

    for p in patterns.active_patterns:
        if direction == "BUY" and p.direction in ("BULL", "NEUTRAL"):
            reliability_map = {"HIGH": 12, "MODERATE": 7, "LOW": 3}
            score += reliability_map.get(p.reliability, 0)

            # Special bonus for H2 (best Al Brooks setup)
            if p.name == "H2":
                score += 5
            # Wedge reversal bonus
            if p.name == "WEDGE_BULL":
                score += 5

        elif direction == "SELL" and p.direction in ("BEAR", "NEUTRAL"):
            reliability_map = {"HIGH": 12, "MODERATE": 7, "LOW": 3}
            score += reliability_map.get(p.reliability, 0)

            if p.name == "L2":
                score += 5
            if p.name == "WEDGE_BEAR":
                score += 5

    return min(score, C.W_PATTERN_MATCH)


def _score_pressure(trend: TrendState, direction: str) -> float:
    """Score: Buying/selling pressure alignment. (0-15 points)"""
    if direction == "BUY":
        if trend.pressure_balance == "BUYERS":
            return 15
        elif trend.pressure_balance == "NEUTRAL":
            return 7
        return 2
    else:
        if trend.pressure_balance == "SELLERS":
            return 15
        elif trend.pressure_balance == "NEUTRAL":
            return 7
        return 2


def _score_breakout(breakout_analysis: BreakoutAnalysis, direction: str) -> float:
    """Score: Breakout context. (0-10 points)"""
    score = 0.0

    if breakout_analysis.in_breakout:
        if (direction == "BUY" and breakout_analysis.breakout_direction == "BULL") or \
           (direction == "SELL" and breakout_analysis.breakout_direction == "BEAR"):
            strength_map = {"STRONG": 10, "MODERATE": 7, "WEAK": 3}
            score += strength_map.get(breakout_analysis.breakout_strength, 0)

    # Failed breakout in opposite direction is a signal for our direction
    if breakout_analysis.recent_failed:
        for fb in breakout_analysis.recent_failed:
            if direction == "BUY" and "BEAR" in fb.breakout_type:
                score += 5  # Failed bear breakout = bull signal
            elif direction == "SELL" and "BULL" in fb.breakout_type:
                score += 5

    # Failed failure (second entry) — very strong
    if breakout_analysis.recent_failed_failures:
        for ff in breakout_analysis.recent_failed_failures:
            if direction == "BUY" and "BULL" in ff.breakout_type:
                score += 8
            elif direction == "SELL" and "BEAR" in ff.breakout_type:
                score += 8

    return min(score, C.W_BREAKOUT)


def _score_channel_position(channels: ChannelAnalysis, direction: str) -> float:
    """Score: Position in channel/trend line context. (0-10 points)"""
    score = 0.0

    if direction == "BUY":
        if channels.price_position == "AT_TREND_LINE":
            score += 10  # At support — best buy location
        elif channels.price_position == "MIDDLE":
            score += 5
        elif channels.price_position == "AT_CHANNEL_LINE":
            score += 0  # At resistance — bad buy location
        elif channels.price_position == "BEYOND_CHANNEL":
            score += 0  # Already overextended
    else:
        if channels.price_position == "AT_CHANNEL_LINE":
            score += 10  # At resistance — best sell location
        elif channels.price_position == "MIDDLE":
            score += 5
        elif channels.price_position == "AT_TREND_LINE":
            score += 0  # At support — bad sell location

    # Micro channel bonus
    if channels.active_micro_channel:
        mc = channels.active_micro_channel
        if direction == "BUY" and mc.direction == "BULL":
            score += 5  # In bull micro channel — buy first pullback
        elif direction == "SELL" and mc.direction == "BEAR":
            score += 5

    return min(score, C.W_CHANNEL_POSITION)


def _score_two_leg(trend: TrendState, direction: str) -> float:
    """Score: Two-leg analysis. (0-5 points)"""
    if trend.two_leg_complete:
        # Two-leg complete — possible reversal
        if direction == "BUY" and trend.trend_direction == "BEAR":
            return 5  # Two-leg bear move complete → buy
        elif direction == "SELL" and trend.trend_direction == "BULL":
            return 5  # Two-leg bull move complete → sell
        return 2
    elif trend.current_leg == 1:
        # First leg — expecting second
        return 2
    return 0


def _score_follow_through(bars: List[BarAnalysis], direction: str) -> float:
    """Score: Follow-through on prior bars. (0-5 points)"""
    if len(bars) < 3:
        return 0.0

    # Check if last 2-3 bars show follow-through in signal direction
    recent = bars[-3:]
    if direction == "BUY":
        follow = sum(1 for i in range(1, len(recent)) if recent[i].close > recent[i - 1].close)
    else:
        follow = sum(1 for i in range(1, len(recent)) if recent[i].close < recent[i - 1].close)

    return min(follow * 2.5, C.W_FOLLOW_THROUGH)


# ─────────────────────────────────────────────────────────────────
#  SIGNAL DETERMINATION
# ─────────────────────────────────────────────────────────────────

def _determine_setup_type(
    trend: TrendState,
    patterns: PatternSummary,
    breakouts: BreakoutAnalysis,
    bars: List[BarAnalysis],
    direction: str,
) -> str:
    """Determine the type of setup for this signal."""
    # Check for second entry (highest priority)
    if breakouts.recent_failed_failures:
        for ff in breakouts.recent_failed_failures:
            if direction == "BUY" and "BULL" in ff.breakout_type:
                return "SECOND_ENTRY"
            if direction == "SELL" and "BEAR" in ff.breakout_type:
                return "SECOND_ENTRY"

    # Check for failed breakout trade
    if breakouts.recent_failed:
        for fb in breakouts.recent_failed:
            if direction == "BUY" and "BEAR" in fb.breakout_type:
                return "FAILED_BREAKOUT"
            if direction == "SELL" and "BULL" in fb.breakout_type:
                return "FAILED_BREAKOUT"

    # Check for breakout
    if breakouts.in_breakout:
        if (direction == "BUY" and breakouts.breakout_direction == "BULL") or \
           (direction == "SELL" and breakouts.breakout_direction == "BEAR"):
            if breakouts.awaiting_pullback:
                return "PULLBACK"
            return "BREAKOUT"

    # Check for pullback entry (H2/L2)
    if direction == "BUY" and patterns.last_hl_bull in ("H1", "H2"):
        return "PULLBACK"
    if direction == "SELL" and patterns.last_hl_bear in ("L1", "L2"):
        return "PULLBACK"

    # Check for reversal (wedge, climax, signal bar)
    for p in patterns.active_patterns:
        if p.name in ("WEDGE_BULL", "DB_BULL_FLAG") and direction == "BUY":
            return "REVERSAL"
        if p.name in ("WEDGE_BEAR", "DT_BEAR_FLAG") and direction == "SELL":
            return "REVERSAL"

    if bars and bars[-1].is_signal_bar:
        if direction == "BUY" and bars[-1].signal_direction == "BULL_REVERSAL":
            return "REVERSAL"
        if direction == "SELL" and bars[-1].signal_direction == "BEAR_REVERSAL":
            return "REVERSAL"

    # Default: trend continuation
    if trend.in_spike:
        return "BREAKOUT"

    return "TREND_CONT"


def _compute_price_levels(
    bars: List[BarAnalysis],
    direction: str,
    setup_type: str,
    trend: TrendState,
    patterns: PatternSummary,
    breakouts: BreakoutAnalysis,
) -> dict:
    """Compute entry, stop, and target prices."""
    if not bars:
        return {"entry": 0, "stop": 0, "target_1": 0, "target_2": 0, "rr": 0}

    last = bars[-1]

    if direction == "BUY":
        # Entry: just above current high (or last bar's high)
        entry = last.high

        # Stop: Al Brooks — below signal bar low or recent swing low (tighter)
        signal_bar_stop = last.low
        recent_lows = [b.low for b in bars[-5:]]
        swing_stop = min(recent_lows) if recent_lows else last.low
        atr_val = last.atr if last.atr > 0 else last.range_size
        # Only widen to swing stop if within 1 ATR of signal bar stop
        if swing_stop >= signal_bar_stop - atr_val:
            stop = swing_stop
        else:
            stop = signal_bar_stop

        # Pattern stop — only if tighter
        for p in patterns.active_patterns:
            if p.direction == "BULL" and p.stop_price > 0:
                if p.stop_price >= stop - atr_val * 0.5:
                    stop = min(stop, p.stop_price)
                break

        if breakouts.pullback_entry_price > 0 and setup_type == "PULLBACK":
            entry = breakouts.pullback_entry_price

    else:  # SELL
        entry = last.low

        signal_bar_stop = last.high
        recent_highs = [b.high for b in bars[-5:]]
        swing_stop = max(recent_highs) if recent_highs else last.high
        atr_val = last.atr if last.atr > 0 else last.range_size
        if swing_stop <= signal_bar_stop + atr_val:
            stop = swing_stop
        else:
            stop = signal_bar_stop

        for p in patterns.active_patterns:
            if p.direction == "BEAR" and p.stop_price > 0:
                if p.stop_price <= stop + atr_val * 0.5:
                    stop = max(stop, p.stop_price)
                break

        if breakouts.pullback_entry_price > 0 and setup_type == "PULLBACK":
            entry = breakouts.pullback_entry_price

    # Risk — cap at 3% of entry to keep targets realistic on daily charts
    risk = abs(entry - stop)
    if risk == 0:
        risk = last.atr if last.atr > 0 else last.range_size
    max_risk = entry * 0.03
    if risk > max_risk and max_risk > 0:
        risk = max_risk
        if direction == "BUY":
            stop = entry - risk
        else:
            stop = entry + risk

    # Targets
    if direction == "BUY":
        target_1 = entry + risk * 1.5     # 1.5R
        target_2 = entry + risk * 2.5     # 2.5R

        # Use measured move if available
        if trend.measured_move_target > entry:
            target_2 = trend.measured_move_target
    else:
        target_1 = entry - risk * 1.5
        target_2 = entry - risk * 2.5

        if 0 < trend.measured_move_target < entry:
            target_2 = trend.measured_move_target

    rr = abs(target_1 - entry) / risk if risk > 0 else 0

    return {
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "target_1": round(target_1, 2),
        "target_2": round(target_2, 2),
        "rr": round(rr, 2),
    }


def _build_reasons(
    direction: str,
    setup_type: str,
    trend: TrendState,
    patterns: PatternSummary,
    bars: List[BarAnalysis],
    breakouts: BreakoutAnalysis,
    channels: ChannelAnalysis,
    scores: dict,
) -> List[str]:
    """Build list of reasons for the signal."""
    reasons = []

    # Trend direction
    if trend.always_in == "LONG" and direction == "BUY":
        reasons.append(f"Always-in LONG (score {trend.always_in_score:+.0f})")
    elif trend.always_in == "SHORT" and direction == "SELL":
        reasons.append(f"Always-in SHORT (score {trend.always_in_score:+.0f})")

    # Setup type
    setup_names = {
        "BREAKOUT": "Breakout entry",
        "PULLBACK": "Pullback entry (H2/L2 second entry)",
        "REVERSAL": "Reversal setup (wedge/climax/signal bar)",
        "TREND_CONT": "Trend continuation",
        "FAILED_BREAKOUT": "Failed breakout trap — trading against trapped side",
        "SECOND_ENTRY": "Failed failure / second entry — highest probability setup",
    }
    reasons.append(setup_names.get(setup_type, setup_type))

    # Pressure
    if direction == "BUY" and trend.pressure_balance == "BUYERS":
        reasons.append(f"Buying pressure dominant ({trend.buying_pressure:.0f}%)")
    elif direction == "SELL" and trend.pressure_balance == "SELLERS":
        reasons.append(f"Selling pressure dominant ({trend.selling_pressure:.0f}%)")

    # Patterns
    for p in patterns.active_patterns:
        if (direction == "BUY" and p.direction in ("BULL", "NEUTRAL")) or \
           (direction == "SELL" and p.direction in ("BEAR", "NEUTRAL")):
            reasons.append(f"Pattern: {p.name} — {p.description[:80]}")

    # Channel position
    if channels.price_position == "AT_TREND_LINE" and direction == "BUY":
        reasons.append("Price at trend line support")
    elif channels.price_position == "AT_CHANNEL_LINE" and direction == "SELL":
        reasons.append("Price at channel line resistance")

    # Phase
    reasons.append(f"Phase: {trend.trend_phase}")

    # Spike
    if trend.in_spike:
        reasons.append(f"Currently in {trend.spike_direction} SPIKE "
                       f"({trend.spike_bars} bars, strength {trend.spike_strength:.0f})")

    # Two-leg
    if trend.two_leg_complete:
        reasons.append(f"Two-leg move complete → measured target {trend.measured_move_target:.2f}")

    # Consecutive bars
    if trend.consecutive_bull_trend >= 3 and direction == "BUY":
        reasons.append(f"{trend.consecutive_bull_trend} consecutive bull trend bars")
    elif trend.consecutive_bear_trend >= 3 and direction == "SELL":
        reasons.append(f"{trend.consecutive_bear_trend} consecutive bear trend bars")

    return reasons


def _build_al_brooks_context(
    direction: str,
    setup_type: str,
    trend: TrendState,
    patterns: PatternSummary,
    confidence: int,
) -> str:
    """Build Al Brooks-style explanation for the signal."""
    parts = []

    if setup_type == "SECOND_ENTRY":
        parts.append("SECOND ENTRY — This is the strongest Al Brooks setup. "
                      "The initial breakout failed, trapping early traders, "
                      "but the failure itself failed, creating a high-probability "
                      "re-entry in the original direction.")

    elif setup_type == "PULLBACK" and "H2" in (patterns.last_hl_bull or ""):
        parts.append("H2 PULLBACK BUY — Al Brooks' most reliable long entry. "
                      "This is the second pullback in a bull trend. "
                      "H2 entries have the highest win rate of any pullback setup.")

    elif setup_type == "PULLBACK" and "L2" in (patterns.last_hl_bear or ""):
        parts.append("L2 PULLBACK SELL — Al Brooks' most reliable short entry. "
                      "This is the second pullback in a bear trend.")

    elif setup_type == "REVERSAL":
        if direction == "BUY":
            parts.append("BULL REVERSAL — Price action shows exhaustion of sellers. "
                          "Look for follow-through on the next bar to confirm.")
        else:
            parts.append("BEAR REVERSAL — Price action shows exhaustion of buyers. "
                          "Look for follow-through on the next bar to confirm.")

    elif setup_type == "BREAKOUT":
        parts.append(f"BREAKOUT — Strong {'bull' if direction == 'BUY' else 'bear'} "
                      "momentum. The breakout bar closed beyond the key level. "
                      "Watch for a pullback entry if you missed the initial move.")

    elif setup_type == "FAILED_BREAKOUT":
        parts.append("FAILED BREAKOUT TRADE — The other side tried to break out "
                      "and failed. This traps them and creates urgency to exit, "
                      "fueling the move in our direction.")

    else:
        parts.append(f"TREND CONTINUATION — Price action supports continued "
                      f"{'buying' if direction == 'BUY' else 'selling'} "
                      f"in the {trend.trend_phase.lower().replace('_', ' ')} phase.")

    if trend.in_spike:
        parts.append(f"The market is in a {trend.spike_direction.lower()} spike — "
                      "momentum is very strong.")

    if confidence >= 75:
        parts.append("High confidence — multiple factors align.")
    elif confidence >= 50:
        parts.append("Moderate confidence — most factors supportive.")
    else:
        parts.append("Lower confidence — fewer confirming factors.")

    return " ".join(parts)


# ─────────────────────────────────────────────────────────────────
#  MAIN ENTRY POINT: GENERATE SIGNALS
# ─────────────────────────────────────────────────────────────────

def generate_pa_signals(
    bars: List[BarAnalysis],
    trend: TrendState,
    patterns: PatternSummary,
    channels: ChannelAnalysis,
    breakouts: BreakoutAnalysis,
) -> PASignalResult:
    """
    Generate price action signals from all analyzed components.

    Parameters
    ----------
    bars : list[BarAnalysis]
    trend : TrendState
    patterns : PatternSummary
    channels : ChannelAnalysis
    breakouts : BreakoutAnalysis

    Returns
    -------
    PASignalResult
        Primary signal with full context, scoring, and Al Brooks explanation.
    """
    result = PASignalResult()
    result.bar_summary = bar_summary(bars)
    result.trend_summary = trend.description
    result.pattern_summary = (
        f"{patterns.bull_setups} bull / {patterns.bear_setups} bear active setups"
        + (f" | Breakout mode ({[p.name for p in patterns.active_patterns if p.pattern_type == 'INSIDE']})"
           if patterns.breakout_mode else "")
    )
    result.channel_summary = channels.description
    result.breakout_summary = breakouts.description

    if not bars:
        result.primary_signal = PASignal(
            signal_type="HOLD", setup_type="NONE", strength="NONE",
            confidence=0, description="No data",
        )
        return result

    # Score BOTH directions and pick the stronger one
    buy_score = _score_direction("BUY", bars, trend, patterns, channels, breakouts)
    sell_score = _score_direction("SELL", bars, trend, patterns, channels, breakouts)

    # Determine primary direction
    if buy_score["total"] > sell_score["total"] and buy_score["total"] >= C.CONF_MIN_ACTIONABLE:
        primary_dir = "BUY"
        primary_scores = buy_score
        secondary_dir = "SELL"
        secondary_scores = sell_score
    elif sell_score["total"] > buy_score["total"] and sell_score["total"] >= C.CONF_MIN_ACTIONABLE:
        primary_dir = "SELL"
        primary_scores = sell_score
        secondary_dir = "BUY"
        secondary_scores = buy_score
    else:
        # Neither direction strong enough → HOLD
        primary_dir = "HOLD"
        primary_scores = buy_score if buy_score["total"] >= sell_score["total"] else sell_score
        secondary_dir = None
        secondary_scores = None

    # Build primary signal
    confidence = primary_scores["total"]
    if primary_dir == "HOLD":
        strength = "NONE"
        setup_type = "NONE"
    else:
        # Determine strength
        if confidence >= C.CONF_STRONG_SIGNAL:
            strength = "STRONG"
        elif confidence >= C.CONF_MODERATE_SIGNAL:
            strength = "MODERATE"
        else:
            strength = "WEAK"

        setup_type = _determine_setup_type(trend, patterns, breakouts, bars, primary_dir)

    # Compute price levels
    if primary_dir != "HOLD":
        levels = _compute_price_levels(bars, primary_dir, setup_type, trend, patterns, breakouts)
    else:
        levels = {"entry": 0, "stop": 0, "target_1": 0, "target_2": 0, "rr": 0}

    # Build reasons
    if primary_dir != "HOLD":
        reasons = _build_reasons(
            primary_dir, setup_type, trend, patterns, bars, breakouts, channels, primary_scores
        )
        al_context = _build_al_brooks_context(primary_dir, setup_type, trend, patterns, confidence)
    else:
        reasons = ["No clear setup — waiting for better price action"]
        al_context = ("HOLD — Al Brooks teaches patience. Without a clear setup "
                      "(breakout, pullback, or reversal), staying out is the best trade.")

    result.primary_signal = PASignal(
        signal_type=primary_dir,
        setup_type=setup_type,
        strength=strength,
        confidence=confidence,
        entry_price=levels["entry"],
        stop_loss=levels["stop"],
        target_1=levels["target_1"],
        target_2=levels["target_2"],
        risk_reward=levels["rr"],
        scores=primary_scores,
        reasons=reasons,
        al_brooks_context=al_context,
        description=f"{primary_dir} ({strength}) — {setup_type.replace('_', ' ').title()}",
    )

    # Build secondary signal if applicable
    if secondary_dir and secondary_scores and secondary_scores["total"] >= C.CONF_MIN_ACTIONABLE:
        sec_setup = _determine_setup_type(trend, patterns, breakouts, bars, secondary_dir)
        sec_levels = _compute_price_levels(bars, secondary_dir, sec_setup, trend, patterns, breakouts)
        sec_conf = secondary_scores["total"]
        sec_strength = "STRONG" if sec_conf >= 75 else ("MODERATE" if sec_conf >= 50 else "WEAK")

        result.secondary_signals.append(PASignal(
            signal_type=secondary_dir,
            setup_type=sec_setup,
            strength=sec_strength,
            confidence=sec_conf,
            entry_price=sec_levels["entry"],
            stop_loss=sec_levels["stop"],
            target_1=sec_levels["target_1"],
            target_2=sec_levels["target_2"],
            risk_reward=sec_levels["rr"],
            scores=secondary_scores,
            description=f"{secondary_dir} ({sec_strength}) — {sec_setup.replace('_', ' ').title()}",
        ))

    # Overall PA score and verdict
    result.pa_score = round(buy_score["total"] - sell_score["total"], 1)
    result.pa_confidence = float(max(buy_score["total"], sell_score["total"]))

    if result.pa_score >= C.VERDICT_STRONG_BUY:
        result.pa_verdict = "STRONG BUY"
    elif result.pa_score >= C.VERDICT_BUY:
        result.pa_verdict = "BUY"
    elif result.pa_score >= C.VERDICT_WEAK_BUY:
        result.pa_verdict = "WEAK BUY"
    elif result.pa_score <= -C.VERDICT_STRONG_BUY:
        result.pa_verdict = "STRONG SELL"
    elif result.pa_score <= -C.VERDICT_BUY:
        result.pa_verdict = "SELL"
    elif result.pa_score <= -C.VERDICT_WEAK_BUY:
        result.pa_verdict = "WEAK SELL"
    else:
        result.pa_verdict = "HOLD"

    return result


def _score_direction(
    direction: str,
    bars: List[BarAnalysis],
    trend: TrendState,
    patterns: PatternSummary,
    channels: ChannelAnalysis,
    breakouts: BreakoutAnalysis,
) -> dict:
    """Score a single direction (BUY or SELL) across all components."""
    s_trend = _score_trend_direction(trend, direction)
    s_bar = _score_bar_quality(bars, direction)
    s_pattern = _score_pattern_match(patterns, direction)
    s_pressure = _score_pressure(trend, direction)
    s_breakout = _score_breakout(breakouts, direction)
    s_channel = _score_channel_position(channels, direction)
    s_two_leg = _score_two_leg(trend, direction)
    s_follow = _score_follow_through(bars, direction)

    total = s_trend + s_bar + s_pattern + s_pressure + s_breakout + s_channel + s_two_leg + s_follow

    return {
        "trend_direction": round(s_trend, 1),
        "bar_quality": round(s_bar, 1),
        "pattern_match": round(s_pattern, 1),
        "pressure": round(s_pressure, 1),
        "breakout": round(s_breakout, 1),
        "channel_position": round(s_channel, 1),
        "two_leg": round(s_two_leg, 1),
        "follow_through": round(s_follow, 1),
        "total": round(total, 1),
    }
