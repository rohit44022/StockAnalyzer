"""
wyckoff/engine.py — Main Wyckoff/Villahermosa Analysis Engine
======================================================

TRUTHFULNESS AUDIT
──────────────────
Source Book: Rubén Villahermosa, "The Wyckoff Methodology in Depth" (2019)

This engine orchestrates all Wyckoff sub-modules and produces a
unified WyckoffResult. The concepts (phases, effort vs result,
waves, springs, etc.) are grounded in Villahermosa's systematic
Wyckoff framework.

WHAT IS FROM VILLAHERMOSA:
  - Phase identification (5 Phases A-E, 4 Schematics)
  - Event detection (7 Events: PS, Climax, Reaction, Test, Shaking,
    Breakout, Confirmation mapped to SC, BC, Spring, Upthrust, SOS, SOW, Test)
  - 3 Laws: Supply & Demand, Cause & Effect, Effort vs Result
  - Wave volume comparison, shortening of thrust, effort vs result
  - Creek/Ice framework, Composite Man theory
  - The qualitative DIRECTION of each signal (bullish/bearish)

WHAT IS NOT FROM VILLAHERMOSA (our integration design):
  - The entire SCORING SYSTEM (±30 bonus, point values per signal)
    [CALIBRATION] — Villahermosa does not prescribe numeric scores
  - The sub-phase names (EARLY/MIDDLE/CONFIRMED/LATE)
    [INFERRED] — formalized from Villahermosa's progression descriptions
  - The "bias" classification (BULLISH/BEARISH/NEUTRAL at ±5)
    [CALIBRATION] — our threshold for the score interpretation
  - Hint texts are PARAPHRASES, not Villahermosa quotes

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
    compute_wyckoff_waves, detect_shortening_of_thrust,
    compare_wave_volumes, analyze_effort_vs_result,
    assess_volume_character, WyckoffWave, EffortResult, VolumeCharacter,
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
    """Complete Wyckoff/Villahermosa analysis result."""

    # ── Phase identification ──
    phase: WyckoffPhase

    # ── Volume analysis ──
    volume_character: VolumeCharacter
    wave_balance: Dict[str, Any]           # compare_wave_volumes result
    shortening: Dict[str, Any]             # shortening_of_thrust result
    effort_result: List[EffortResult]      # Last N bars effort/result
    waves: List[WyckoffWave]               # Raw wave data
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
    Villahermosa teaches QUALITATIVE reading of volume-price
    relationships through 3 Laws. He does NOT prescribe point
    values, weighted scores, or numeric bonuses. This scoring
    system is OUR quantification designed to integrate Villahermosa's
    insights into the existing triple-engine framework.

    The DIRECTION of each score (bullish/bearish) is from Villahermosa.
    The MAGNITUDE (specific point values) is our design choice.

    Scoring Components:

    [VILLAHERMOSA concept, CALIBRATION magnitude] Phase alignment:
      Accumulation → BUY bias        → up to +10 [CALIBRATION]
      Distribution → SELL bias       → up to -10 [CALIBRATION]
      Markup       → BUY bias        → up to +5  [CALIBRATION]
      Markdown     → SELL bias       → up to -5  [CALIBRATION]

    [VILLAHERMOSA concept, CALIBRATION magnitude] Wave volume balance:
      Demand dominant → +5 to +8 [CALIBRATION]
      Supply dominant → -5 to -8 [CALIBRATION]

    [VILLAHERMOSA concept, CALIBRATION magnitude] Shortening of thrust:
      Up exhaustion   → -5 to -8 (bearish) [CALIBRATION]
      Down exhaustion → +5 to +8 (bullish) [CALIBRATION]

    [VILLAHERMOSA concept, CALIBRATION magnitude] Recent effort vs result:
      Absorption (up bar, close>50%) → +3 (bullish: absorbing selling) [CALIBRATION]
      Absorption (dn bar, close<50%) → -3 (bearish: absorbing buying)  [CALIBRATION]
      No supply/demand confirming    → ±3 [CALIBRATION]
      Climax in opposing direction   → ±5 (reversal signal) [CALIBRATION]

    [VILLAHERMOSA concept, CALIBRATION magnitude] Spring/Upthrust events:
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
            # ABSORPTION is directional: close_position > 0.5 means up bar
            # (Composite Man absorbing selling pressure = bullish),
            # close_position <= 0.5 means down bar (absorbing buying = bearish)
            "NO_DEMAND": -3,
            "NO_SUPPLY": 3,
            "CLIMAX_UP": -5,
            "CLIMAX_DOWN": 5,
            "NORMAL": 0,
        }
        if last_er.effort_result == "ABSORPTION":
            er_bonus = 3 if last_er.close_position > 0.5 else -3
        else:
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
    labels["phase"] = "[VILLAHERMOSA]"
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
    labels["volume"] = "[VILLAHERMOSA]"
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
        labels["wave_balance"] = "[VILLAHERMOSA]"
        bal = wave_balance.get("balance", "")
        if "DEMAND" in bal:
            hints.append("Buyers are putting in more effort than sellers — bullish sign.")
        elif "SUPPLY" in bal:
            hints.append("Sellers are putting in more effort than buyers — bearish sign.")

    # Shortening
    if shortening.get("detected"):
        parts.append(f"Thrust Analysis: {shortening['description']}")
        labels["shortening"] = "[VILLAHERMOSA]"
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
        labels[f"event_{ev.event_type}"] = "[VILLAHERMOSA]"
        event_hints = {
            "SPRING": "The stock briefly broke below its support and bounced back — this is a TRAP for sellers. "
                      "The Composite Man just bought at the best possible price.",
            "UPTHRUST": "The stock briefly broke above resistance and fell back — this is a TRAP for buyers. "
                        "The Composite Man just sold at the best possible price.",
            "SC": "There was panic selling with extreme volume — but the close was near the high. "
                  "The Composite Man was buying all that selling. Potential bottom.",
            "BC": "There was euphoric buying with extreme volume — but the close was near the low. "
                  "The Composite Man was selling into all that buying. Potential top.",
            "SOS": "A strong upward bar with heavy volume — like a sprinter exploding off the blocks. "
                   "The move up is real.",
            "SOW": "A strong downward bar with heavy volume — like a dam breaking. "
                   "The move down is real.",
            "TEST": "The stock returned to a key level with low volume — confirming the prior signal. "
                    "Think of it as a 'double-check' that came back clean.",
            "ABSORPTION": ("Supply is being absorbed by demand (or vice versa) within the range. "
                           "This is a core Villahermosa pattern — the Composite Man is quietly "
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
            labels["effort_result"] = "[VILLAHERMOSA]"

    # Overall
    summary = " | ".join(parts)
    return summary, hints, labels


# ═══════════════════════════════════════════════════════════════
#  MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════

def run_wyckoff_analysis(df: pd.DataFrame, ticker: str = "") -> WyckoffResult:
    """
    Run complete Wyckoff/Villahermosa analysis on OHLCV data.

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

    # ── Step 1: Compute Wyckoff Waves ──
    waves = compute_wyckoff_waves(df)

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

    # ── Step 6b: Follow-through on key events [VILLAHERMOSA] ──
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
        # ── Enriched Villahermosa sections for UI ──
        "villahermosa": _compute_villahermosa_sections(result),
    }


def _compute_villahermosa_sections(r: WyckoffResult) -> dict:
    """Derive all 20 Villahermosa section data from the WyckoffResult."""
    ph = r.phase
    events = ph.events
    ev_types = [e.event_type for e in events]
    bias = r.bias
    vol = r.volume_character
    wb = r.wave_balance
    sh = r.shortening
    waves = r.waves

    # ── Composite Man assessment ──
    cm_action = "UNCLEAR"
    cm_desc = ""
    if ph.phase == "ACCUMULATION":
        cm_action = "ACCUMULATING"
        cm_desc = ("The Composite Man (large institutions) is quietly buying stock from weak, "
                   "fearful sellers at bargain prices. Like a billionaire shopping at a fire sale "
                   "while everyone else is running for the exits.")
    elif ph.phase == "DISTRIBUTION":
        cm_action = "DISTRIBUTING"
        cm_desc = ("The Composite Man is quietly selling to greedy latecomers who think the "
                   "rally will last forever. Like a savvy poker player cashing out while "
                   "others keep betting.")
    elif ph.phase == "MARKUP":
        cm_action = "MARKING_UP"
        cm_desc = ("The Composite Man has finished accumulating and is now letting the price rise. "
                   "Public demand is supporting the uptrend. Like a store owner raising prices "
                   "after buying inventory cheap.")
    elif ph.phase == "MARKDOWN":
        cm_action = "MARKING_DOWN"
        cm_desc = ("The Composite Man has finished distributing and the price is falling under its "
                   "own weight. Late buyers are trapped and selling at a loss.")
    else:
        cm_action = "TESTING"
        cm_desc = ("The Composite Man is probing — testing whether sellers or buyers will give up "
                   "first. The direction is not yet decided.")

    # Composite Man counterparty logic
    cm_counterparty = ""
    if "SPRING" in ev_types:
        cm_counterparty = ("A Spring was detected — the Composite Man deliberately pushed price "
                           "below support to trigger stop-losses and panic selling, then bought "
                           "every share those panicking sellers dumped. Classic trap.")
    elif "UPTHRUST" in ev_types:
        cm_counterparty = ("An Upthrust was detected — the Composite Man pushed price above "
                           "resistance to lure breakout buyers and FOMO traders, then sold "
                           "into all that buying enthusiasm. Classic bull trap.")

    # ── Creek / Ice levels ──
    creek = ph.resistance  # Creek = AR high = resistance in accumulation
    ice = ph.support       # Ice = AR low = support in distribution
    creek_desc = ("The Creek is the resistance level (AR high) that price must 'jump across' "
                  "to confirm accumulation. Think of it as a river the stock must cross to "
                  "reach higher ground.")
    ice_desc = ("The Ice is the support level (AR low) that price must 'fall through' to "
                "confirm distribution. Think of it as thin ice that breaks when sellers "
                "overwhelm buyers.")

    # ── Schematic detection ──
    has_spring = "SPRING" in ev_types
    has_ut = "UPTHRUST" in ev_types
    has_sc = "SC" in ev_types
    has_bc = "BC" in ev_types
    has_sos = "SOS" in ev_types
    has_sow = "SOW" in ev_types
    has_test = "TEST" in ev_types

    schematic = "UNKNOWN"
    schematic_desc = ""
    if ph.phase == "ACCUMULATION":
        if has_spring:
            schematic = "ACCUMULATION_1"
            schematic_desc = ("Accumulation Schematic #1 (with Spring): The classic textbook pattern. "
                              "Price broke below the range (Spring), trapping sellers, then reversed. "
                              "This is the EASIEST to identify and often produces explosive moves upward.")
        else:
            schematic = "ACCUMULATION_2"
            schematic_desc = ("Accumulation Schematic #2 (without Spring): Price formed a higher low "
                              "instead of breaking below the range. This shows EXTREME background "
                              "strength — buyers were so dominant they didn't even let price reach "
                              "the lows. Harder to spot but equally powerful.")
    elif ph.phase == "DISTRIBUTION":
        if has_ut:
            schematic = "DISTRIBUTION_1"
            schematic_desc = ("Distribution Schematic #1 (with UTAD): Price broke above the range "
                              "(Upthrust After Distribution), trapping buyers, then reversed down. "
                              "Classic head-fake before a major decline.")
        else:
            schematic = "DISTRIBUTION_2"
            schematic_desc = ("Distribution Schematic #2 (without UTAD): Price formed a lower high "
                              "instead of breaking above. This shows EXTREME background weakness — "
                              "sellers were so dominant they didn't even let price reach the highs.")

    # ── Trading Zone ──
    zone = 0
    zone_name = ""
    zone_desc = ""
    zone_rr = ""
    zone_size = ""
    if ph.phase in ("ACCUMULATION", "DISTRIBUTION"):
        sub = ph.sub_phase or ""
        if sub in ("EARLY", "MIDDLE"):
            if has_spring or has_ut:
                zone = 1
                zone_name = "Zone 1 — Phase C (The Shake)"
                zone_desc = ("You are at the EXTREME of the structure — right where the Composite Man "
                             "just set a trap. This is the BEST risk/reward entry but the lowest "
                             "certainty. Like buying at the absolute bottom of a clearance sale.")
                zone_rr = "3:1 or better"
                zone_size = "Small (25-50% of full position) — highest R:R but least confirmed"
            else:
                zone = 0
                zone_name = "No Zone — Structure Incomplete"
                zone_desc = ("The structure is still forming. Phase A or B is in progress. "
                             "No valid entry zone yet — WAIT for Phase C events.")
                zone_rr = "N/A"
                zone_size = "DO NOT TRADE — wait for signal"
        elif sub == "LATE":
            if has_sos or has_sow:
                zone = 2
                zone_name = "Zone 2 — Phase D (Confirmation)"
                zone_desc = ("The structure is confirmed! An SOS/SOW breakout occurred and price is "
                             "now testing back for entry. This is Wyckoff's PREFERRED entry — "
                             "you can see the full structure on the left and enter with confidence.")
                zone_rr = "2:1"
                zone_size = "Standard (50-75% of full position) — best balance of R:R and reliability"
            else:
                zone = 1
                zone_name = "Zone 1 — Phase C (The Shake)"
                zone_desc = "Spring/Upthrust detected but breakout not yet confirmed."
                zone_rr = "3:1 or better"
                zone_size = "Small (25-50%) — awaiting confirmation"
    elif ph.phase in ("MARKUP", "MARKDOWN"):
        zone = 3
        zone_name = "Zone 3 — Phase E (Trend)"
        zone_desc = ("The trend is confirmed and in motion. Enter on pullbacks (LPS/LPSY). "
                     "This has the HIGHEST reliability but the SMALLEST reward-to-risk ratio. "
                     "Like joining a race after seeing who's winning — safe but less upside.")
        zone_rr = "1.5:1"
        zone_size = "Add to existing (25% increments on pullbacks)"

    # ── Re-accumulation vs Distribution detection ──
    reaccum_dist = {"type": "N/A", "description": "", "signals": []}
    if ph.phase in ("RANGING",) or (ph.phase in ("ACCUMULATION", "DISTRIBUTION") and ph.sub_phase in ("EARLY", "MIDDLE")):
        signals = []
        vol_decreasing = wb.get("balance", "") in ("DEMAND_DOMINANT", "SLIGHT_DEMAND", "BALANCED")
        higher_lows = False
        lower_highs = False
        if waves and len(waves) >= 4:
            down_waves = [w for w in waves if w.direction == "DOWN"]
            up_waves = [w for w in waves if w.direction == "UP"]
            if len(down_waves) >= 2:
                higher_lows = down_waves[-1].end_price > down_waves[-2].end_price
                lower_highs = False
            if len(up_waves) >= 2:
                lower_highs = up_waves[-1].end_price < up_waves[-2].end_price

        if vol_decreasing and higher_lows:
            signals.append("Volume decreasing + higher lows forming")
            reaccum_dist["type"] = "RE_ACCUMULATION"
            reaccum_dist["description"] = ("This range likely represents RE-ACCUMULATION — a pause "
                                            "in an uptrend before it resumes. Volume is declining "
                                            "(absorption in progress) and the range shows higher lows "
                                            "(buyers are dominant). BULLISH continuation expected.")
        elif not vol_decreasing and lower_highs:
            signals.append("Volume persistently high + lower highs forming")
            reaccum_dist["type"] = "DISTRIBUTION"
            reaccum_dist["description"] = ("This range likely represents DISTRIBUTION — smart money "
                                            "selling after an advance. Volume is persistently high "
                                            "(urgent selling) and the range shows lower highs "
                                            "(sellers are dominant). BEARISH reversal expected.")
        else:
            reaccum_dist["type"] = "UNDETERMINED"
            reaccum_dist["description"] = ("Cannot yet distinguish between re-accumulation and "
                                            "distribution. Wait for more price action to develop.")
        reaccum_dist["signals"] = signals

    # ── Failed structure detection ──
    # Use follow-through data: if a key event (Spring/Upthrust) has WEAK/NO
    # follow-through, the structure is failing. The old polarity check was
    # dead code (Spring always bullish=True, Upthrust always bullish=False).
    ft = r.follow_through
    failed_structure = {"detected": False, "type": "", "description": ""}
    for ev in events:
        if ev.event_type == "SPRING":
            spring_ft = ft.get("SPRING", {})
            if spring_ft.get("follow_through") == "NO" and spring_ft.get("quality") == "WEAK":
                failed_structure = {
                    "detected": True,
                    "type": "FAILED_SPRING",
                    "description": ("The Spring FAILED — price did not follow through to the upside "
                                    "after the shakeout. The accumulation thesis is weakening. "
                                    "The Composite Man may have abandoned the campaign. "
                                    "Reduce longs and tighten stops immediately.")
                }
        elif ev.event_type == "UPTHRUST":
            ut_ft = ft.get("UPTHRUST", {})
            if ut_ft.get("follow_through") == "NO" and ut_ft.get("quality") == "WEAK":
                failed_structure = {
                    "detected": True,
                    "type": "FAILED_UTAD",
                    "description": ("The UTAD FAILED — price did not follow through to the downside "
                                    "after the breakout trap. The distribution thesis is weakening. "
                                    "Reduce shorts and tighten stops immediately.")
                }

    # ── Phase volume behavior assessment ──
    phase_vol = {"phase": ph.phase, "assessment": "", "expected": "", "actual": ""}
    vol_status = vol.status
    if ph.phase == "ACCUMULATION":
        phase_vol["expected"] = "Volume should DECREASE progressively (absorption in progress)"
        if vol_status in ("DRYUP", "NORMAL"):
            phase_vol["actual"] = "Volume IS low/normal — consistent with absorption"
            phase_vol["assessment"] = "HEALTHY"
        else:
            phase_vol["actual"] = f"Volume is {vol_status} — higher than expected for absorption"
            phase_vol["assessment"] = "WATCH"
    elif ph.phase == "MARKUP":
        phase_vol["expected"] = "Volume should EXPAND on rallies and CONTRACT on pullbacks"
        if vol_status in ("ABOVE_AVG", "SPIKE"):
            phase_vol["actual"] = "Volume IS elevated — healthy markup confirmation"
            phase_vol["assessment"] = "HEALTHY"
        else:
            phase_vol["actual"] = f"Volume is {vol_status} — thin markup, watch for weakness"
            phase_vol["assessment"] = "WATCH"
    elif ph.phase == "DISTRIBUTION":
        phase_vol["expected"] = "Volume remains PERSISTENTLY HIGH (urgent selling by institutions)"
        if vol_status in ("ABOVE_AVG", "SPIKE", "CLIMAX"):
            phase_vol["actual"] = "Volume IS high — consistent with distribution"
            phase_vol["assessment"] = "CONFIRMS_DIST"
        else:
            phase_vol["actual"] = f"Volume is {vol_status} — may be re-accumulation instead"
            phase_vol["assessment"] = "POSSIBLE_REACCUM"
    elif ph.phase == "MARKDOWN":
        phase_vol["expected"] = "Volume should expand on drops, contract on bounces"
        phase_vol["actual"] = f"Current volume: {vol_status}"
        phase_vol["assessment"] = "ACTIVE"

    # ── Do Not Trade conditions ──
    dnt_reasons = []
    if ph.phase in ("RANGING",) and ph.sub_phase in ("EARLY", ""):
        dnt_reasons.append("Phase A/early B — structure still forming. Wait for Phase C minimum.")
    if ph.sub_phase in ("EARLY",) and ph.phase in ("ACCUMULATION", "DISTRIBUTION"):
        dnt_reasons.append("Phase still early — no confirmed events yet. Patience required.")
    if any(e.event_type == "TEST" and e.volume_ratio > 1.5 for e in events):
        dnt_reasons.append("Test event shows HIGH volume — unresolved supply/demand. Wait for clean retest.")
    if failed_structure["detected"]:
        dnt_reasons.append(f"Structure FAILED ({failed_structure['type']}). Wait for complete new Phase A.")
    if not any(e.event_type in ("SPRING", "UPTHRUST", "SOS", "SOW") for e in events):
        if ph.phase in ("ACCUMULATION", "DISTRIBUTION", "RANGING"):
            dnt_reasons.append("No significant Wyckoff event detected. No entry trigger present.")

    # ── Wyckoff Phase letter mapping ──
    phase_letter = "?"
    if ph.phase in ("ACCUMULATION", "DISTRIBUTION"):
        if ph.sub_phase == "EARLY":
            phase_letter = "A"
        elif ph.sub_phase == "MIDDLE":
            phase_letter = "B"
        elif ph.sub_phase == "LATE":
            if has_spring or has_ut:
                phase_letter = "C" if not (has_sos or has_sow) else "D"
            else:
                phase_letter = "B"
    elif ph.phase in ("MARKUP", "MARKDOWN"):
        phase_letter = "E" if ph.sub_phase in ("CONFIRMED", "LATE") else "D"

    # ── Last confirmed event + next expected ──
    last_event = events[-1].event_type if events else "NONE"
    next_expected = ""
    event_sequence = {"SC": "AR (Automatic Rally)", "BC": "AR (Automatic Reaction)",
                      "AR": "ST (Secondary Test)", "ST": "Spring or UTAD (Phase C Shake)",
                      "SPRING": "Test of Spring → SOS (Sign of Strength)",
                      "UPTHRUST": "Test of UTAD → SOW (Sign of Weakness)",
                      "SOS": "LPS/BUEC (Last Point of Support / Back Up to Creek)",
                      "SOW": "LPSY/FTI (Last Point of Supply)",
                      "TEST": "SOS or SOW (breakout)",
                      "NONE": "PS (Preliminary Stop/Supply)"}
    next_expected = event_sequence.get(last_event, "Monitor for new events")

    # ── Entry rules context ──
    entry_context = {"type": "NONE", "description": "", "stop": "", "target": ""}
    if has_spring and ph.phase == "ACCUMULATION":
        if has_sos:
            entry_context = {
                "type": "LPS_BUEC_BUY",
                "description": ("Wyckoff's PREFERRED entry: SOS has broken the Creek. Wait for pullback "
                                "to Creek with narrow ranges + low volume (LPS/BUEC). Enter at appearance "
                                "of the next bullish bar on the pullback."),
                "stop": f"Below the LPS low AND below the broken Creek (₹{ph.support:.2f})",
                "target": "Phase E trend targets — measured move from accumulation width"
            }
        else:
            entry_context = {
                "type": "SPRING_BUY",
                "description": ("Spring detected in accumulation! Enter at the close of the next "
                                "strong bullish bar (SOS bar) after the Spring test holds. "
                                "Volume on test must be LOWER than Spring volume."),
                "stop": f"Below the Spring low (below ₹{ph.support:.2f})",
                "target": f"Creek/AR high (₹{ph.resistance:.2f}), then Phase E targets"
            }
    elif has_ut and ph.phase == "DISTRIBUTION":
        if has_sow:
            entry_context = {
                "type": "LPSY_FTI_SELL",
                "description": ("Wyckoff's preferred SHORT entry: SOW has broken the Ice. Wait for rally "
                                "to Ice area with narrow ranges + low volume (LPSY). Enter at appearance "
                                "of the next bearish bar on the rally."),
                "stop": f"Above the LPSY high AND above the broken Ice (₹{ph.resistance:.2f})",
                "target": "Phase E downtrend targets — measured move from distribution width"
            }
        else:
            entry_context = {
                "type": "UTAD_SELL",
                "description": ("UTAD detected in distribution! Enter short at the close of the next "
                                "strong bearish bar (SOW bar) after the UTAD test holds."),
                "stop": f"Above the UTAD high (above ₹{ph.resistance:.2f})",
                "target": f"Ice/AR low (₹{ph.support:.2f}), then Phase E targets"
            }
    elif ph.phase == "MARKUP":
        entry_context = {
            "type": "PHASE_E_LPS_BUY",
            "description": ("Phase E trend in progress. Enter on corrective pullbacks (LPS) "
                            "with contracting volume. Look for minor re-accumulation structures."),
            "stop": "Below the most recent LPS low",
            "target": "Next liquidity zone (previous significant highs)"
        }
    elif ph.phase == "MARKDOWN":
        entry_context = {
            "type": "PHASE_E_LPSY_SELL",
            "description": ("Phase E downtrend in progress. Enter short on corrective rallies (LPSY) "
                            "with contracting volume."),
            "stop": "Above the most recent LPSY high",
            "target": "Next liquidity zone (previous significant lows)"
        }

    # ── Stop loss rules ──
    stop_rules = []
    if has_spring:
        stop_rules.append({"entry": "Spring (direct)", "stop": "Below the Spring low",
                           "reason": "If price goes below Spring low → it wasn't a Spring, exit"})
        stop_rules.append({"entry": "Spring test", "stop": "Below SOS bar OR below Spring low",
                           "reason": "Two options — below Spring low = safer but wider"})
    if has_ut:
        stop_rules.append({"entry": "UTAD (direct)", "stop": "Above the UTAD high",
                           "reason": "If price exceeds UTAD → it wasn't a UTAD, exit"})
    if has_sos:
        stop_rules.append({"entry": "LPS/BUEC", "stop": "Below SOS bar AND below broken Creek",
                           "reason": "Both levels must be below your stop for safety"})
    if has_sow:
        stop_rules.append({"entry": "LPSY/FTI", "stop": "Above SOW bar AND above broken Ice",
                           "reason": "Both levels must be above your stop for safety"})
    if not stop_rules:
        stop_rules.append({"entry": "General", "stop": f"Below support (₹{ph.support:.2f})" if bias != "BEARISH" else f"Above resistance (₹{ph.resistance:.2f})",
                           "reason": "No specific Wyckoff event detected — use range boundaries"})

    # ── Exit rules context ──
    exit_rules = []
    if vol.status == "CLIMAX":
        exit_rules.append("⚡ CLIMACTIC VOLUME detected — potential turning point. Consider exiting or tightening stops.")
    if sh.get("detected") and sh.get("direction") == "UP_EXHAUSTION" and bias == "BULLISH":
        exit_rules.append("📉 Shortening of upward thrust detected — rally momentum fading. Tighten stops.")
    if sh.get("detected") and sh.get("direction") == "DOWN_EXHAUSTION" and bias == "BEARISH":
        exit_rules.append("📈 Shortening of downward thrust — selling pressure waning. Consider covering shorts.")
    if ph.phase == "MARKUP" and ph.sub_phase == "LATE":
        exit_rules.append("⚠️ Late Markup — the uptrend is mature. Tighten stops, no new longs.")
    if ph.phase == "MARKDOWN" and ph.sub_phase == "LATE":
        exit_rules.append("⚠️ Late Markdown — the downtrend is mature. Consider covering shorts.")
    if ph.phase == "DISTRIBUTION":
        exit_rules.append("🔴 Distribution phase — take profits on longs or tighten stops significantly.")
    if ph.phase == "ACCUMULATION":
        exit_rules.append("🟢 Accumulation phase — cover shorts, potential bottom forming.")
    if not exit_rules:
        exit_rules.append("No immediate exit signals. Monitor for phase transitions and climactic volume.")

    return {
        "composite_man": {
            "action": cm_action,
            "description": cm_desc,
            "counterparty": cm_counterparty,
        },
        "three_laws": {
            "supply_demand": wb.get("balance", "BALANCED"),
            "cause_effect": {
                "cause_duration": ph.sub_phase or "UNKNOWN",
                "expected_effect": ("LARGE" if ph.sub_phase in ("LATE", "CONFIRMED") else
                                    "SMALL" if ph.sub_phase == "EARLY" else "MODERATE"),
            },
            "effort_result": vol.status,
        },
        "creek_ice": {
            "creek": creek,
            "ice": ice,
            "creek_desc": creek_desc,
            "ice_desc": ice_desc,
        },
        "schematic": {
            "type": schematic,
            "description": schematic_desc,
        },
        "trading_zone": {
            "zone": zone,
            "name": zone_name,
            "description": zone_desc,
            "risk_reward": zone_rr,
            "position_size": zone_size,
        },
        "reaccum_dist": reaccum_dist,
        "failed_structure": failed_structure,
        "phase_volume": phase_vol,
        "phase_letter": phase_letter,
        "last_event": last_event,
        "next_expected": next_expected,
        "entry_context": entry_context,
        "stop_rules": stop_rules,
        "exit_rules": exit_rules,
        "do_not_trade": dnt_reasons,
    }
