"""
wyckoff/engine.py — Main Wyckoff/Weis Analysis Engine
======================================================

TRUTHFULNESS AUDIT
──────────────────
Source Book: David H. Weis, "Trades About to Happen" (Wiley, 2013)

This engine orchestrates all Wyckoff sub-modules and produces a
unified WyckoffResult. The concepts (phases, effort vs result,
waves, springs, etc.) are ALL from Weis's book.

WHAT IS FROM WEIS:
  - Phase identification (Accumulation/Markup/Distribution/Markdown)
  - Event detection (SC, BC, Spring, Upthrust, SOS, SOW, Test)
  - Wave volume comparison, shortening of thrust, effort vs result
  - The qualitative DIRECTION of each signal (bullish/bearish)

WHAT IS NOT FROM WEIS (our integration design):
  - The entire SCORING SYSTEM (±30 bonus, point values per signal)
    [CALIBRATION] — Weis does not prescribe numeric scores
  - The sub-phase names (EARLY/MIDDLE/CONFIRMED/LATE)
    [INFERRED] — formalized from Weis's progression descriptions
  - The "bias" classification (BULLISH/BEARISH/NEUTRAL at ±5)
    [CALIBRATION] — our threshold for the score interpretation
  - Hint texts are PARAPHRASES, not Weis quotes

Integration Design:
  - Wyckoff does NOT produce its own 0-100 score
  - Instead it produces a BONUS/PENALTY (-30 to +30) that
    adjusts the cross-validation section of the triple engine
  - This ensures existing BB/TA/PA scores are NEVER modified
  - Wyckoff acts as a "phase context" and "volume truth" layer
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import pandas as pd

from wyckoff.config import WYCKOFF_MAX_BONUS
from wyckoff.volume_analysis import (
    compute_weis_waves, detect_shortening_of_thrust,
    compare_wave_volumes, analyze_effort_vs_result,
    assess_volume_character, WeisWave, EffortResult, VolumeCharacter,
)
from wyckoff.phases import (
    identify_wyckoff_phase, WyckoffPhase, WyckoffEvent,
    assess_follow_through, detect_absorption, detect_change_in_behavior,
)


# ═══════════════════════════════════════════════════════════════
#  MAIN RESULT STRUCTURE
# ═══════════════════════════════════════════════════════════════

@dataclass
class WyckoffResult:
    """Complete Wyckoff/Weis analysis result."""

    # ── Phase identification ──
    phase: WyckoffPhase

    # ── Volume analysis ──
    volume_character: VolumeCharacter
    wave_balance: Dict[str, Any]           # compare_wave_volumes result
    shortening: Dict[str, Any]             # shortening_of_thrust result
    effort_result: List[EffortResult]      # Last N bars effort/result
    waves: List[WeisWave]                  # Raw wave data
    follow_through: Dict[str, Any]         # Follow-through assessment for key events

    # ── Scoring ──
    wyckoff_bonus: int                     # -30 to +30
    bias: str                              # "BULLISH" | "BEARISH" | "NEUTRAL"

    # ── Human-readable ──
    summary: str                           # One-paragraph plain-English summary
    hints: List[str]                       # Layman-friendly bullet points
    source_labels: Dict[str, str]          # Maps each insight to its source


# ═══════════════════════════════════════════════════════════════
#  SCORING LOGIC
# ═══════════════════════════════════════════════════════════════

def _compute_wyckoff_bonus(
    phase: WyckoffPhase,
    wave_balance: dict,
    shortening: dict,
    effort_results: List[EffortResult],
    volume_char: VolumeCharacter,
) -> tuple:
    """
    Compute the Wyckoff bonus/penalty for cross-validation.

    NOTE: The entire scoring system below is [CALIBRATION].
    Weis teaches QUALITATIVE reading of volume-price relationships.
    He does NOT prescribe point values, weighted scores, or numeric
    bonuses. This scoring system is OUR quantification designed to
    integrate Weis's insights into the existing triple-engine framework.

    The DIRECTION of each score (bullish/bearish) is from Weis.
    The MAGNITUDE (specific point values) is our design choice.

    Scoring Components:

    [WEIS concept, CALIBRATION magnitude] Phase alignment:
      Accumulation → BUY bias        → up to +10 [CALIBRATION]
      Distribution → SELL bias       → up to -10 [CALIBRATION]
      Markup       → BUY bias        → up to +5  [CALIBRATION]
      Markdown     → SELL bias       → up to -5  [CALIBRATION]

    [WEIS concept, CALIBRATION magnitude] Wave volume balance:
      Demand dominant → +5 to +8 [CALIBRATION]
      Supply dominant → -5 to -8 [CALIBRATION]

    [WEIS concept, CALIBRATION magnitude] Shortening of thrust:
      Up exhaustion   → -5 to -8 (bearish) [CALIBRATION]
      Down exhaustion → +5 to +8 (bullish) [CALIBRATION]

    [WEIS concept, CALIBRATION magnitude] Recent effort vs result:
      Absorption in trend direction  → -3 (warns of reversal) [CALIBRATION]
      No supply/demand confirming    → +3 [CALIBRATION]
      Climax in opposing direction   → +5 (reversal signal) [CALIBRATION]

    [WEIS concept, CALIBRATION magnitude] Spring/Upthrust events:
      Spring detected   → +8 [CALIBRATION]
      Upthrust detected → -8 [CALIBRATION]

    Total clamped to [-WYCKOFF_MAX_BONUS, +WYCKOFF_MAX_BONUS]
    Positive = bullish, Negative = bearish

    Returns:
        (score: int, bias: str, breakdown: dict)
    """
    score = 0
    breakdown = {}

    # ── Phase alignment ──
    phase_scores = {
        "ACCUMULATION": {"EARLY": 5, "MIDDLE": 8, "LATE": 10},
        "MARKUP": {"EARLY": 3, "MIDDLE": 5, "CONFIRMED": 7, "LATE": 4},
        "DISTRIBUTION": {"EARLY": -5, "MIDDLE": -8, "LATE": -10},
        "MARKDOWN": {"EARLY": -3, "MIDDLE": -5, "CONFIRMED": -7, "LATE": -4},
    }
    phs = phase_scores.get(phase.phase, {})
    phase_bonus = phs.get(phase.sub_phase, 0)
    score += phase_bonus
    breakdown["phase"] = phase_bonus

    # ── Wave volume balance ──
    bal = wave_balance.get("balance", "BALANCED")
    wave_scores = {
        "DEMAND_DOMINANT": 8,
        "SLIGHT_DEMAND": 5,
        "BALANCED": 0,
        "SLIGHT_SUPPLY": -5,
        "SUPPLY_DOMINANT": -8,
    }
    wave_bonus = wave_scores.get(bal, 0)
    score += wave_bonus
    breakdown["wave_balance"] = wave_bonus

    # ── Shortening of thrust ──
    if shortening.get("detected"):
        direction = shortening.get("direction", "")
        severity = shortening.get("severity", "MODERATE")
        if direction == "UP_EXHAUSTION":
            short_bonus = -8 if severity == "STRONG" else -5
        elif direction == "DOWN_EXHAUSTION":
            short_bonus = 8 if severity == "STRONG" else 5
        else:
            short_bonus = 0
        score += short_bonus
        breakdown["shortening"] = short_bonus
    else:
        breakdown["shortening"] = 0

    # ── Effort vs Result from last bar ──
    er_bonus = 0
    if effort_results:
        last_er = effort_results[-1]
        er_map = {
            "ABSORPTION": -3,
            "NO_DEMAND": -3,
            "NO_SUPPLY": 3,
            "CLIMAX_UP": -5,
            "CLIMAX_DOWN": 5,
            "NORMAL": 0,
        }
        er_bonus = er_map.get(last_er.effort_result, 0)
    score += er_bonus
    breakdown["effort_result"] = er_bonus

    # ── Spring / Upthrust / Absorption / Change-in-Behavior events ──
    event_bonus = 0
    for ev in phase.events:
        if ev.event_type == "SPRING":
            event_bonus += 8
        elif ev.event_type == "UPTHRUST":
            event_bonus -= 8
        elif ev.event_type == "SC":
            event_bonus += 5
        elif ev.event_type == "BC":
            event_bonus -= 5
        elif ev.event_type == "SOS":
            event_bonus += 4
        elif ev.event_type == "SOW":
            event_bonus -= 4
        elif ev.event_type == "TEST":
            event_bonus += 3 if ev.bullish else -3
        elif ev.event_type == "ABSORPTION":
            event_bonus += 5 if ev.bullish else -5
        elif ev.event_type == "CHANGE_IN_BEHAVIOR":
            event_bonus += 4 if ev.bullish else -4
    score += event_bonus
    breakdown["events"] = event_bonus

    # Clamp
    score = max(-WYCKOFF_MAX_BONUS, min(WYCKOFF_MAX_BONUS, score))

    if score >= 5:
        bias = "BULLISH"
    elif score <= -5:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    return score, bias, breakdown


# ═══════════════════════════════════════════════════════════════
#  HUMAN-READABLE GENERATION
# ═══════════════════════════════════════════════════════════════

def _generate_summary(
    phase: WyckoffPhase,
    volume_char: VolumeCharacter,
    wave_balance: dict,
    shortening: dict,
    effort_results: List[EffortResult],
    bias: str,
    bonus: int,
) -> tuple:
    """Generate plain-English summary and layman hints."""

    parts = []
    hints = []
    labels = {}

    # Phase context
    parts.append(f"Wyckoff Phase: {phase.phase} ({phase.sub_phase})")
    parts.append(phase.description)
    labels["phase"] = "[WEIS]"
    _phase_hints = {
        "ACCUMULATION": "Think of it like smart investors quietly buying while others are scared.",
        "MARKUP": {
            "EARLY": ("The stock is starting to climb — higher highs and higher lows are forming, "
                      "like a staircase going up. But the move isn't fully confirmed by volume yet. "
                      "It's like a plane on the runway speeding up — it LOOKS like takeoff, but "
                      "we need to see it actually lift off (volume expanding on rallies)."),
            "MIDDLE": ("The uptrend is real and developing. Buyers have shown their strength "
                       "(Sign of Strength bar detected), but volume isn't fully behind every rally yet. "
                       "Think of it like a plane that's just left the ground — climbing, but not at "
                       "cruising altitude. Hold your position and watch for the next rally's volume."),
            "CONFIRMED": ("This is the SWEET SPOT — prices are climbing with genuine buying pressure. "
                          "Volume expands when the stock goes up and shrinks when it dips — that's exactly "
                          "what a healthy uptrend looks like. Think of a river flowing strongly in one direction. "
                          "Small dips on quiet volume (LPS) are chances to buy more."),
            "LATE": ("The uptrend has been running for a while and is now mature. Like a runner "
                     "approaching the finish line — still moving fast, but getting tired. "
                     "Watch for warning signs: if the up-pushes start getting shorter, or if you "
                     "see a huge volume bar that closes near the low (Buying Climax), the smart "
                     "money may be starting to sell. Tighten your stops and don't add new buys."),
        },
        "DISTRIBUTION": "Think of it like smart investors quietly selling while others are excited.",
        "MARKDOWN": "Prices are falling — smart money already left the party.",
        "RANGING": "The market is undecided, moving sideways. Wait for a clear signal.",
    }
    markup_hint = _phase_hints.get(phase.phase, "Phase is unclear — proceed with caution.")
    if isinstance(markup_hint, dict):
        markup_hint = markup_hint.get(phase.sub_phase, markup_hint.get("EARLY", ""))
    hints.append(
        f"The market is currently in a {phase.phase.lower()} phase. " + markup_hint
    )

    # For MARKUP, add extra context about what to watch for
    if phase.phase == "MARKUP":
        hints.append(
            "📈 MARKUP means the stock has finished accumulating and is now trending upward. "
            "The key question is: HOW MATURE is the uptrend? Early markup = exciting opportunity. "
            "Late markup = be careful, the end may be near. Look at pullback volume to judge: "
            "pullbacks on LOW volume mean the uptrend is healthy; pullbacks on HIGH volume mean "
            "sellers are getting aggressive."
        )

    # Volume character
    parts.append(f"Volume: {volume_char.description}")
    labels["volume"] = "[WEIS]"
    hints.append(
        f"Volume is {volume_char.status.lower()} (×{volume_char.ratio} of average). "
        + {
            "CLIMAX": "Extreme volume often marks turning points — major buying or selling is happening.",
            "SPIKE": "Unusual volume means big players are active right now.",
            "ABOVE_AVG": "Healthy volume supports the current price movement.",
            "NORMAL": "Nothing unusual about today's trading activity.",
            "DRYUP": "Very quiet trading — like the calm before a storm. A big move may be building.",
        }.get(volume_char.status, "")
    )

    # Wave balance
    wb = wave_balance.get("description", "")
    if wb:
        parts.append(f"Wave Balance: {wb}")
        labels["wave_balance"] = "[WEIS]"
        bal = wave_balance.get("balance", "")
        if "DEMAND" in bal:
            hints.append("Buyers are putting in more effort than sellers — bullish sign.")
        elif "SUPPLY" in bal:
            hints.append("Sellers are putting in more effort than buyers — bearish sign.")

    # Shortening
    if shortening.get("detected"):
        parts.append(f"Thrust Analysis: {shortening['description']}")
        labels["shortening"] = "[WEIS]"
        direction = shortening.get("direction", "")
        if "UP_EXHAUSTION" in direction:
            hints.append("The upward pushes are getting weaker each time — like a ball bouncing lower. "
                         "The rally may be running out of energy.")
        elif "DOWN_EXHAUSTION" in direction:
            hints.append("The downward pushes are getting weaker each time — sellers are losing power. "
                         "The decline may be ending soon.")

    # Key events
    for ev in phase.events:
        parts.append(f"Event — {ev.event_type}: {ev.description}")
        labels[f"event_{ev.event_type}"] = "[WEIS]"
        event_hints = {
            "SPRING": "The stock briefly broke below its support and bounced back — this is a TRAP for sellers. "
                      "Smart money just bought at the best possible price.",
            "UPTHRUST": "The stock briefly broke above resistance and fell back — this is a TRAP for buyers. "
                        "Smart money just sold at the best possible price.",
            "SC": "There was panic selling with extreme volume — but the close was near the high. "
                  "Someone big was buying all that selling. Potential bottom.",
            "BC": "There was euphoric buying with extreme volume — but the close was near the low. "
                  "Someone big was selling into all that buying. Potential top.",
            "SOS": "A strong upward bar with heavy volume — like a sprinter exploding off the blocks. "
                   "The move up is real.",
            "SOW": "A strong downward bar with heavy volume — like a dam breaking. "
                   "The move down is real.",
            "TEST": "The stock returned to a key level with low volume — confirming the prior signal. "
                    "Think of it as a 'double-check' that came back clean.",
            "ABSORPTION": ("Supply is being absorbed by demand (or vice versa) within the range. "
                           "This is one of Weis's three core patterns — smart money is quietly "
                           "taking the other side of the trade."),
            "CHANGE_IN_BEHAVIOR": ("The largest opposite-direction bar appeared — the other side "
                                   "is waking up. This is often the first warning of a trend change."),
        }
        if ev.event_type in event_hints:
            hints.append(event_hints[ev.event_type])

    # Effort vs Result on last bar
    if effort_results:
        last_er = effort_results[-1]
        if last_er.effort_result != "NORMAL":
            parts.append(f"Effort/Result: {last_er.description}")
            labels["effort_result"] = "[WEIS]"

    # Overall
    summary = " | ".join(parts)
    return summary, hints, labels


# ═══════════════════════════════════════════════════════════════
#  MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════

def run_wyckoff_analysis(df: pd.DataFrame, ticker: str = "") -> WyckoffResult:
    """
    Run complete Wyckoff/Weis analysis on OHLCV data.

    This is the ONLY function external code needs to call.

    Args:
        df: DataFrame with columns: Open, High, Low, Close, Volume
        ticker: Optional ticker symbol for display

    Returns:
        WyckoffResult with phase, events, volume analysis, scoring,
        and human-readable insights.
    """
    # Guard: need enough data
    if df is None or len(df) < 30:
        empty_phase = WyckoffPhase("UNKNOWN", "UNKNOWN", 0,
                                   description="Insufficient data for Wyckoff analysis")
        empty_vol = VolumeCharacter("UNKNOWN", 0, "UNKNOWN", "Insufficient data")
        return WyckoffResult(
            phase=empty_phase,
            volume_character=empty_vol,
            wave_balance={"balance": "INSUFFICIENT", "ratio": 1.0},
            shortening={"detected": False},
            effort_result=[],
            waves=[],
            follow_through={},
            wyckoff_bonus=0,
            bias="NEUTRAL",
            summary="Insufficient data for Wyckoff analysis.",
            hints=["Not enough price history to run Wyckoff analysis."],
            source_labels={},
        )

    # ── Step 1: Compute Weis Waves ──
    waves = compute_weis_waves(df)

    # ── Step 2: Wave volume balance ──
    wave_balance = compare_wave_volumes(waves)

    # ── Step 3: Shortening of thrust ──
    shortening = detect_shortening_of_thrust(waves)

    # ── Step 4: Effort vs Result (last 5 bars) ──
    effort_results = analyze_effort_vs_result(df, lookback=5)

    # ── Step 5: Volume character ──
    vol_char = assess_volume_character(df)

    # ── Step 6: Phase identification (includes event detection) ──
    phase = identify_wyckoff_phase(df)

    # ── Step 6b: Follow-through on key events [WEIS Ch. 5-6] ──
    follow_through = {}
    for ev in phase.events:
        if ev.event_type in ("SPRING", "UPTHRUST", "SC", "BC"):
            ft = assess_follow_through(df, ev)
            follow_through[ev.event_type] = ft

    # ── Step 7: Compute bonus/penalty ──
    bonus, bias, breakdown = _compute_wyckoff_bonus(
        phase, wave_balance, shortening, effort_results, vol_char
    )

    # ── Step 8: Generate human-readable output ──
    summary, hints, labels = _generate_summary(
        phase, vol_char, wave_balance, shortening, effort_results, bias, bonus
    )

    return WyckoffResult(
        phase=phase,
        volume_character=vol_char,
        wave_balance=wave_balance,
        shortening=shortening,
        effort_result=effort_results,
        waves=waves,
        follow_through=follow_through,
        wyckoff_bonus=bonus,
        bias=bias,
        summary=summary,
        hints=hints,
        source_labels=labels,
    )


def wyckoff_to_dict(result: WyckoffResult) -> dict:
    """Convert WyckoffResult to a JSON-serializable dictionary for API/web."""
    return {
        "phase": {
            "name": result.phase.phase,
            "sub_phase": result.phase.sub_phase,
            "confidence": result.phase.confidence,
            "support": result.phase.support,
            "resistance": result.phase.resistance,
            "description": result.phase.description,
            "events": [
                {
                    "type": e.event_type,
                    "confidence": e.confidence,
                    "price": e.price,
                    "volume_ratio": e.volume_ratio,
                    "bullish": e.bullish,
                    "description": e.description,
                }
                for e in result.phase.events
            ],
        },
        "volume": {
            "status": result.volume_character.status,
            "ratio": result.volume_character.ratio,
            "trend": result.volume_character.trend,
            "description": result.volume_character.description,
        },
        "wave_balance": result.wave_balance,
        "shortening": result.shortening,
        "effort_result": [
            {
                "effort_result": er.effort_result,
                "spread": er.spread,
                "volume": er.volume,
                "close_position": er.close_position,
                "description": er.description,
            }
            for er in result.effort_result
        ],
        "waves": [
            {
                "direction": w.direction,
                "bars": w.bars,
                "price_move": round(w.price_move, 2),
                "cum_volume": w.cum_volume,
                "start_price": round(w.start_price, 2),
                "end_price": round(w.end_price, 2),
            }
            for w in (result.waves[-12:] if result.waves else [])
        ],
        "scoring": {
            "wyckoff_bonus": result.wyckoff_bonus,
            "bias": result.bias,
        },
        "follow_through": result.follow_through,
        "summary": result.summary,
        "hints": result.hints,
    }
