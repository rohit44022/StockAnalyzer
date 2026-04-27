"""
hybrid_pa_engine.py — Triple Conviction Engine: BB + TA + PA
=============================================================

The ultimate stock analysis system combining three independent frameworks:

  1. Bollinger Bands (John Bollinger, 4 Methods)  →  WHAT is happening
     - Volatility squeeze, breakout, trend, reversal, band walk
     - Score range: -100 to +100

  2. Technical Analysis (John Murphy, 6 categories) →  WHY it's happening
     - Trend, momentum, volume, patterns, S/R, risk
     - Score range: -100 to +100

  3. Price Action (Al Brooks, bar-by-bar)           →  HOW it's happening
     - Always-in direction, bar quality, patterns, pressure, breakouts
     - Score range: -100 to +100

Architecture:
  - Each system scores independently (-100 to +100)
  - Triple cross-validation adds conviction (-60 to +60, clamped)
  - Combined score: -360 to +360
  - Final verdict based on combined score + alignment

Why 3 systems?
  - Bollinger measures VOLATILITY (statistical bands around price)
  - TA measures MOMENTUM + TREND (oscillators, MAs, divergences)
  - PA measures PRICE STRUCTURE (what actual bars are doing)
  - All three agreeing = maximum probability of correct direction
  - Any one disagreeing = caution flag reducing position size

Scoring Philosophy:
  Each system contributes 100 points. The cross-validation bonus rewards
  agreement and penalizes conflict. A stock scoring +200 with all 3 aligned
  is far more trustworthy than +200 from 2 systems with the third opposing.
"""

from __future__ import annotations
import math
import numpy as np
import pandas as pd
from typing import Optional

# ── BB Squeeze System ──
from bb_squeeze.indicators import compute_all_indicators as compute_bb_indicators
from bb_squeeze.signals import analyze_signals as generate_bb_signal
from bb_squeeze.strategies import run_all_strategies, strategy_result_to_dict

# ── Technical Analysis System ──
from technical_analysis.indicators import (
    compute_all_ta_indicators,
    get_indicator_snapshot,
    detect_ma_crossovers,
    detect_all_divergences,
    compute_pivot_points,
    compute_fibonacci,
)
from technical_analysis.candlesticks import scan_candlestick_patterns
from technical_analysis.patterns import (
    detect_support_resistance,
    identify_trend,
    detect_all_chart_patterns,
    analyze_volume,
    analyze_ichimoku,
)
from technical_analysis.signals import generate_signal as generate_ta_signal
from technical_analysis.risk_manager import generate_risk_report
from technical_analysis.target_price import calculate_target_prices

# ── Price Action System ──
from price_action.engine import run_price_action_analysis, PriceActionResult

# ── Wyckoff/Villahermosa System (Rubén Villahermosa — Volume-Phase Context Layer) ──
from wyckoff.engine import run_wyckoff_analysis, wyckoff_to_dict

# ── Market Profile System (James Dalton — Auction Context Layer) ──
from market_profile.engine import run_market_profile_analysis, market_profile_to_dict

# ── Unified target/stop calculator across BB + TA + PA + Wyckoff ──
from triple_targets import compute_triple_targets

# ── Common ──
from bb_squeeze.data_loader import get_data_freshness


# ═══════════════════════════════════════════════════════════════
#  SAFE JSON HELPERS
# ═══════════════════════════════════════════════════════════════

def _safe(v):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return None
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        v = float(v)
        return None if math.isnan(v) or math.isinf(v) else v
    return v


def _safe_json(obj):
    if isinstance(obj, dict):
        return {k: _safe_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_safe_json(v) for v in obj]
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if math.isnan(v) or math.isinf(v) else v
    if isinstance(obj, np.ndarray):
        return _safe_json(obj.tolist())
    return obj


# ═══════════════════════════════════════════════════════════════
#  BOLLINGER BAND SCORING (100 points max)
#  Reused from hybrid_engine.py — identical logic
# ═══════════════════════════════════════════════════════════════

def _score_bb_method_1(bb_signal) -> dict:
    """Method I — Volatility Squeeze Breakout (40 pts max)."""
    score = 0.0
    details = []

    if bb_signal.buy_signal:
        score += 30
        details.append(f"✅ BUY SIGNAL — All 5 conditions met (Confidence: {bb_signal.confidence}%)")
    elif bb_signal.short_signal:
        score -= 30
        details.append(f"🔴 SHORT SIGNAL — All 5 short conditions met (Confidence: {bb_signal.confidence}%)")
    elif bb_signal.head_fake:
        score -= 20
        details.append("❌ HEAD FAKE — breakout is likely false")
    elif bb_signal.cond1_squeeze_on:
        details.append("⏳ Squeeze ON — waiting for breakout")
        if bb_signal.direction_lean == "BULLISH":
            score += 10
            details.append("✅ Direction lean: BULLISH")
        elif bb_signal.direction_lean == "BEARISH":
            score -= 10
            details.append("❌ Direction lean: BEARISH")
    elif bb_signal.sell_signal:
        score -= 25
        details.append("🔴 SELL/EXIT — SAR flip or band tag")

    if bb_signal.cond2_price_above:
        score += 5
        details.append("✅ Price above upper BB")
    if bb_signal.cond3_volume_ok:
        score += 3
        details.append("✅ Volume above 50-SMA")
    if bb_signal.cond4_cmf_positive:
        score += 2
        details.append("✅ CMF positive")
    if bb_signal.cond5_mfi_above_50:
        score += 2
        details.append("✅ MFI > 50")

    # Short-side condition bonuses (symmetric with buy conditions)
    if hasattr(bb_signal, 'cond_short_price') and bb_signal.cond_short_price:
        score -= 5
        details.append("🔴 Price below lower BB")
    if hasattr(bb_signal, 'cond_short_ii_neg') and bb_signal.cond_short_ii_neg:
        score -= 2
        details.append("🔴 II% negative (distribution)")
    if hasattr(bb_signal, 'cond_short_mfi_low') and bb_signal.cond_short_mfi_low:
        score -= 2
        details.append("🔴 MFI < 50 (weak money flow)")

    if bb_signal.exit_sar_flip:
        score -= 10
        details.append("⚠️ SAR bearish flip")
    if bb_signal.exit_double_neg:
        score -= 5
        details.append("⚠️ CMF < 0 AND MFI < 50")

    return {"score": round(max(-40, min(40, score)), 1), "max": 40,
            "method": "Method I — Volatility Squeeze", "details": details,
            "phase": bb_signal.phase, "squeeze_days": bb_signal.squeeze_days}


def _score_bb_method_2(strat: dict) -> dict:
    """Method II — Trend Following %b + MFI (25 pts max)."""
    score = 0.0
    details = []
    sig = strat.get("signal", {})
    indicators = strat.get("indicators", {})
    sig_type = sig.get("type", "NONE")
    confidence = sig.get("confidence", 0)

    if sig_type == "BUY":
        score += 20 * (confidence / 100)
        details.append(f"✅ M-II BUY — {sig.get('reason', '')}")
    elif sig_type == "SELL":
        score -= 20 * (confidence / 100)
        details.append(f"❌ M-II SELL — {sig.get('reason', '')}")
    elif sig_type == "HOLD":
        score += 5
        details.append("✅ M-II HOLD — trend intact")
    elif sig_type == "WATCH":
        details.append("👀 M-II WATCH — monitoring for signal")

    if indicators.get("bearish_divergence"):
        score -= 5
        details.append("⚠️ Bearish div: %b↑ MFI↓")
    if indicators.get("bullish_divergence"):
        score += 5
        details.append("✅ Bullish div: %b↓ MFI↑")

    return {"score": round(max(-25, min(25, score)), 1), "max": 25,
            "method": "Method II — Trend Following", "details": details}


def _score_bb_method_3(strat: dict) -> dict:
    """Method III — Reversals W-Bottom / M-Top (20 pts max)."""
    score = 0.0
    details = []
    sig = strat.get("signal", {})
    sig_type = sig.get("type", "NONE")
    confidence = sig.get("confidence", 0)

    if sig_type == "BUY":
        score += 15 * (confidence / 100)
        details.append("✅ M-III BUY — reversal pattern detected")
    elif sig_type == "SELL":
        score -= 15 * (confidence / 100)
        details.append("❌ M-III SELL — reversal pattern detected")

    for p in strat.get("patterns", []):
        details.append(f"📊 {p.get('name', '')}")

    return {"score": round(max(-20, min(20, score)), 1), "max": 20,
            "method": "Method III — Reversals",
            "details": details or ["No W-Bottom or M-Top detected"]}


def _score_bb_method_4(strat: dict) -> dict:
    """Method IV — Walking the Bands (15 pts max)."""
    score = 0.0
    details = []
    sig = strat.get("signal", {})
    sig_type = sig.get("type", "NONE")
    confidence = sig.get("confidence", 0)

    if sig_type == "BUY":
        score += 12 * (confidence / 100)
        details.append("✅ M-IV — walking upper bands")
    elif sig_type == "SELL":
        score -= 12 * (confidence / 100)
        details.append("❌ M-IV — walking lower bands")

    return {"score": round(max(-15, min(15, score)), 1), "max": 15,
            "method": "Method IV — Walking the Bands",
            "details": details or ["No band-walking detected"]}


# ═══════════════════════════════════════════════════════════════
#  PRICE ACTION SCORING (100 points max)
#  Normalizes PA engine output to -100..+100 unified scale
# ═══════════════════════════════════════════════════════════════

def _score_pa(pa_result: PriceActionResult) -> dict:
    """
    Score the PA system output.

    PA engine already returns pa_score in [-100, +100] and 8 component scores.
    We extract and normalize for the triple engine dashboard.

    Component breakdown (100 pts total):
      1. Always-In Direction:  25 pts  — Are we long, short, or flat?
      2. Bar Quality:          15 pts  — Is the signal bar strong?
      3. Pattern Match:        15 pts  — H2/L2, wedges, flags etc.
      4. Buying/Selling Press: 15 pts  — Who controls the market?
      5. Breakout Strength:    10 pts  — Is there a breakout?
      6. Channel Position:     10 pts  — Where in the channel?
      7. Two-Leg Status:        5 pts  — Two-leg pullback complete?
      8. Follow-Through:        5 pts  — Consecutive bars confirming?
    """
    pa_total = pa_result.pa_score  # already -100 to +100

    # Extract component scores
    components = {}
    sd = pa_result.score_details if hasattr(pa_result, "score_details") else {}
    if isinstance(sd, dict):
        components = {
            "always_in": {"score": round(sd.get("trend_direction", 0), 1), "max": 25,
                          "label": "Always-In Direction"},
            "bar_quality": {"score": round(sd.get("bar_quality", 0), 1), "max": 15,
                            "label": "Bar Quality"},
            "pattern": {"score": round(sd.get("pattern_match", 0), 1), "max": 15,
                        "label": "Pattern Match"},
            "pressure": {"score": round(sd.get("pressure", 0), 1), "max": 15,
                         "label": "Buying/Selling Pressure"},
            "breakout": {"score": round(sd.get("breakout", 0), 1), "max": 10,
                         "label": "Breakout Strength"},
            "channel": {"score": round(sd.get("channel_position", 0), 1), "max": 10,
                        "label": "Channel Position"},
            "two_leg": {"score": round(sd.get("two_leg", 0), 1), "max": 5,
                        "label": "Two-Leg Status"},
            "follow_through": {"score": round(sd.get("follow_through", 0), 1), "max": 5,
                                "label": "Follow-Through"},
        }

    details = []
    if pa_result.signal_type == "BUY":
        details.append(f"✅ PA BUY — {pa_result.setup_type} ({pa_result.strength})")
    elif pa_result.signal_type == "SELL":
        details.append(f"❌ PA SELL — {pa_result.setup_type} ({pa_result.strength})")
    else:
        details.append("⏳ PA HOLD — no actionable setup")

    if pa_result.always_in != "FLAT":
        details.append(f"Always-In: {pa_result.always_in} (score: {pa_result.always_in_score:.0f})")
    if pa_result.trend_phase and pa_result.trend_phase != "UNKNOWN":
        details.append(f"Trend Phase: {pa_result.trend_phase}")
    if pa_result.active_patterns:
        details.append(f"Patterns: {', '.join(pa_result.active_patterns[:5])}")
    if pa_result.breakout_mode:
        details.append("⚡ BREAKOUT MODE (inside bar / ii / iii pattern)")
    if pa_result.in_breakout:
        details.append(f"🔥 Active breakout: {pa_result.breakout_direction}")
    if hasattr(pa_result, 'gap_bar_setup') and pa_result.gap_bar_setup:
        details.append("⚡ MA Gap Bar Setup — first EMA touch after 20+ gap bars (Brooks)")
    if "BARBWIRE" in (pa_result.active_patterns or []):
        details.append("⚠️ BARBWIRE — choppy action, stay out per Brooks")

    return {
        "total": round(pa_total, 1),
        "max": 100,
        "components": components,
        "details": details,
        "signal_type": pa_result.signal_type,
        "setup_type": pa_result.setup_type,
        "strength": pa_result.strength,
        "confidence": pa_result.confidence,
        "always_in": pa_result.always_in,
        "trend_phase": pa_result.trend_phase,
        "entry_price": _safe(pa_result.entry_price),
        "stop_loss": _safe(pa_result.stop_loss),
        "target_1": _safe(pa_result.target_1),
        "target_2": _safe(pa_result.target_2),
        "risk_reward": _safe(pa_result.risk_reward),
    }


# ═══════════════════════════════════════════════════════════════
#  TRIPLE CROSS-VALIDATION ENGINE
#  The mathematical core — measures agreement across all 3 systems
# ═══════════════════════════════════════════════════════════════

def _direction_from_score(score: float, threshold: float = 10) -> str:
    """Convert a numeric score to directional string."""
    if score > threshold:
        return "BULLISH"
    if score < -threshold:
        return "BEARISH"
    return "NEUTRAL"


def _triple_cross_validate(
    bb_total: float,
    ta_total: float,
    pa_total: float,
    bb_methods: list,
    ta_signal: dict,
    pa_data: dict,
    wyckoff_result=None,
    mp_result=None,
) -> dict:
    """
    Triple cross-validation across BB, TA, and PA systems,
    enhanced by Wyckoff/Villahermosa phase context and Dalton Market Profile
    auction context.

    Scoring matrix:
      All 3 agree (same direction):     +40 bonus  (very high conviction)
      2 agree, 1 neutral:               +25 bonus  (high conviction)
      2 agree, 1 conflicts:             -10 penalty (caution — one system disagrees)
      All 3 neutral:                      0         (no signal)
      All 3 disagree / mixed:           -20 penalty (stay out)
      1 active + 2 neutral:             +5          (wait for confirmation)

    Additional context bonuses:
      Squeeze + PA trend + TA momentum:  +15        (explosive setup)
      Squeeze + PA/TA divergent:         -10        (caution)
      Volume confirms across systems:    +5         (real participation)

    Context layers (NOT separate scores — they enhance/reduce conviction):
      [VILLAHERMOSA]   Wyckoff phase + volume:   ±30        (phase context)
      [DALTON] Market Profile auction:   ±35        (value/auction context)

    Final result clamped to [-125, +125] for combined context layers.
    """
    bb_dir = _direction_from_score(bb_total)
    ta_dir = _direction_from_score(ta_total)
    pa_dir = _direction_from_score(pa_total, threshold=15)

    dirs = [bb_dir, ta_dir, pa_dir]
    active = [d for d in dirs if d != "NEUTRAL"]
    bullish_count = dirs.count("BULLISH")
    bearish_count = dirs.count("BEARISH")
    neutral_count = dirs.count("NEUTRAL")

    agreement_score = 0
    observations = []
    alignment = "PARTIAL"

    # ── Case 1: All 3 agree ──
    if bullish_count == 3 or bearish_count == 3:
        agreement_score += 40
        direction = "BULLISH" if bullish_count == 3 else "BEARISH"
        alignment = "TRIPLE_ALIGNED"
        observations.append(
            f"🟢 TRIPLE ALIGNMENT: BB ({bb_dir}), TA ({ta_dir}), PA ({pa_dir}) — "
            f"all 3 independent systems point {direction}. This is the highest conviction "
            f"signal possible. Bollinger sees it in volatility, Murphy confirms in momentum, "
            f"and Brooks validates in price structure."
        )

    # ── Case 2: 2 agree, 1 neutral ──
    elif (bullish_count == 2 and neutral_count == 1) or (bearish_count == 2 and neutral_count == 1):
        agreement_score += 25
        alignment = "DOUBLE_ALIGNED"
        active_dir = "BULLISH" if bullish_count == 2 else "BEARISH"
        neutral_sys = ["BB", "TA", "PA"][[bb_dir, ta_dir, pa_dir].index("NEUTRAL")]
        observations.append(
            f"✅ DOUBLE ALIGNMENT: 2 of 3 systems agree ({active_dir}), {neutral_sys} is neutral. "
            f"Strong signal — watch for {neutral_sys} to confirm for maximum conviction."
        )

    # ── Case 3: 2 agree, 1 conflicts ──
    elif (bullish_count == 2 and bearish_count == 1) or (bearish_count == 2 and bullish_count == 1):
        agreement_score -= 10
        alignment = "CONFLICTING"
        majority_dir = "BULLISH" if bullish_count > bearish_count else "BEARISH"
        minority_sys = ["BB", "TA", "PA"][
            [bb_dir, ta_dir, pa_dir].index("BEARISH" if majority_dir == "BULLISH" else "BULLISH")
        ]
        observations.append(
            f"⚠️ CONFLICT: 2 systems say {majority_dir} but {minority_sys} disagrees. "
            f"This reduces conviction. The dissenting system may be seeing something the "
            f"others miss — or it may be lagging. Trade with reduced position size."
        )

    # ── Case 4: All neutral ──
    elif neutral_count == 3:
        alignment = "ALL_NEUTRAL"
        observations.append(
            "⏳ ALL NEUTRAL: No system shows a clear directional bias. "
            "The market is coiling — a big move may be coming but direction is uncertain."
        )

    # ── Case 5: 1 active, 2 neutral ──
    elif len(active) == 1:
        agreement_score += 5
        alignment = "SINGLE"
        observations.append(
            f"One system ({active[0]}) shows a signal while the other two are neutral. "
            f"Early signal — wait for at least one more system to confirm."
        )

    # ── Case 6: Other mixed ──
    else:
        agreement_score -= 20
        alignment = "MIXED"
        observations.append(
            "⚠️ MIXED SIGNALS: Systems show conflicting directions. "
            "This is a high-uncertainty environment — best to stay out."
        )

    # ── Context bonuses ──

    # Squeeze + PA strong trend + TA positive momentum = explosive setup
    bb_squeeze_active = any(
        m.get("phase") in ("COMPRESSION", "DIRECTION") for m in bb_methods
    )
    ta_momentum = ta_signal.get("categories", {}).get("momentum", {}).get("score", 0)
    pa_always_in = pa_data.get("always_in", "FLAT")

    if bb_squeeze_active and pa_always_in != "FLAT":
        if (pa_always_in == "LONG" and ta_momentum > 5) or \
           (pa_always_in == "SHORT" and ta_momentum < -5):
            agreement_score += 15
            observations.append(
                f"🔥 EXPLOSIVE SETUP: BB squeeze active + PA always-in {pa_always_in} + "
                f"TA momentum aligned. When a squeeze resolves into an established PA trend "
                f"with TA momentum confirmation, the move is typically large and sustained."
            )
        elif (pa_always_in == "LONG" and ta_momentum < -5) or \
             (pa_always_in == "SHORT" and ta_momentum > 5):
            agreement_score -= 10
            observations.append(
                "⚠️ CAUTION: BB squeeze active but PA trend and TA momentum disagree on direction. "
                "The squeeze could resolve against the PA trend."
            )

    # Volume cross-confirmation
    ta_volume = ta_signal.get("categories", {}).get("volume", {}).get("score", 0)
    if abs(ta_volume) > 5 and (
        (ta_volume > 0 and bb_total > 10 and pa_total > 15) or
        (ta_volume < 0 and bb_total < -10 and pa_total < -15)
    ):
        agreement_score += 5
        observations.append(
            "✅ VOLUME CONFIRMS: Strong volume activity aligns with both BB and PA direction. "
            "Volume is the lie detector — when it confirms price structure, the signal is real."
        )

    # ── [VILLAHERMOSA] Wyckoff Phase & Volume Context Layer (±30 pts) ──
    # Blends Villahermosa volume-spread analysis into cross-validation.
    # This does NOT create a 4th score — it adds context that strengthens
    # or weakens the existing agreement based on Wyckoff phase and volume truth.
    wyckoff_bonus = 0
    wyckoff_bias = "NEUTRAL"
    if wyckoff_result is not None:
        wyckoff_bonus = wyckoff_result.wyckoff_bonus
        wyckoff_bias = wyckoff_result.bias
        phase_name = wyckoff_result.phase.phase

        # [VILLAHERMOSA] Phase confirms direction = bonus, contradicts = penalty
        if wyckoff_bonus != 0:
            agreement_score += wyckoff_bonus
            if wyckoff_bonus > 0:
                observations.append(
                    f"📊 [VILLAHERMOSA] Wyckoff {phase_name} phase adds +{wyckoff_bonus} conviction. "
                    f"{wyckoff_result.phase.description}"
                )
            else:
                observations.append(
                    f"📊 [VILLAHERMOSA] Wyckoff {phase_name} phase adds {wyckoff_bonus} penalty. "
                    f"{wyckoff_result.phase.description}"
                )

        # [CONFLUENCE — VILLAHERMOSA + BOLLINGER] Squeeze + Accumulation = explosive buy
        if bb_squeeze_active and phase_name == "ACCUMULATION":
            agreement_score += 8
            observations.append(
                "🔥 [CONFLUENCE — VILLAHERMOSA + BOLLINGER] BB Squeeze INSIDE Wyckoff Accumulation! "
                "When volatility compresses while smart money accumulates, the breakout "
                "is typically explosive. This is the highest-confluence buy setup."
            )
        elif bb_squeeze_active and phase_name == "DISTRIBUTION":
            agreement_score -= 8
            observations.append(
                "⚠️ [CONFLUENCE — VILLAHERMOSA + BOLLINGER] BB Squeeze INSIDE Wyckoff Distribution! "
                "Smart money is distributing while volatility compresses. The breakout "
                "may be a trap — watch for upthrust patterns."
            )

        # [CONFLUENCE — VILLAHERMOSA + BROOKS] Spring + PA failed breakdown = max buy
        has_spring = any(e.event_type == "SPRING" for e in wyckoff_result.phase.events)
        has_upthrust = any(e.event_type == "UPTHRUST" for e in wyckoff_result.phase.events)

        if has_spring and pa_always_in == "LONG":
            agreement_score += 6
            observations.append(
                "🎯 [CONFLUENCE — VILLAHERMOSA + BROOKS] Wyckoff Spring + PA Always-In Long! "
                "Brooks' failed breakdown confirmed by Villahermosa's low-volume shakeout. "
                "Smart money just bought the dip. Maximum-probability buy."
            )
        elif has_upthrust and pa_always_in == "SHORT":
            agreement_score -= 6
            observations.append(
                "🎯 [CONFLUENCE — VILLAHERMOSA + BROOKS] Wyckoff Upthrust + PA Always-In Short! "
                "Brooks' failed breakout confirmed by Villahermosa's low-demand trap. "
                "Smart money just sold the top. Maximum-probability sell."
            )

        # [VILLAHERMOSA] Shortening of thrust warning
        if wyckoff_result.shortening.get("detected"):
            sdir = wyckoff_result.shortening.get("direction", "")
            if "UP_EXHAUSTION" in sdir and bb_total > 10:
                agreement_score -= 5
                observations.append(
                    "⚠️ [VILLAHERMOSA] Shortening of upward thrust detected — upward pushes losing "
                    "momentum despite positive BB signal. The rally may be exhausting."
                )
            elif "DOWN_EXHAUSTION" in sdir and bb_total < -10:
                agreement_score += 5
                observations.append(
                    "📊 [VILLAHERMOSA] Shortening of downward thrust — selling pressure weakening "
                    "despite negative BB signal. A bottom may be forming."
                )

    # Defensive clamp — ensures agreement stays within documented bounds
    # Extended from ±60 to ±90 to accommodate Wyckoff bonus (±30)
    agreement_score = max(-90, min(90, agreement_score))

    # ── [DALTON] Market Profile Auction Context Layer (±35 pts) ──
    # Blends Dalton's Market Profile thinking into cross-validation.
    # Like Wyckoff, this does NOT create a separate score — it adds
    # auction-theory context that strengthens or weakens conviction.
    dalton_bonus = 0
    dalton_signals = []
    if mp_result is not None:
        dalton_bonus = mp_result.cv_bonus

        if dalton_bonus != 0:
            agreement_score += dalton_bonus

        # Add Dalton observations to the unified observation list
        for obs in mp_result.observations:
            observations.append(obs)

        dalton_signals = mp_result.dalton_signals

        # ── [CONFLUENCE — DALTON + BOLLINGER] ──
        # Squeeze inside a Dalton bracket = breakout imminent
        if bb_squeeze_active and mp_result.market_structure == "BRACKETING":
            agreement_score += 5
            observations.append(
                "🔥 [CONFLUENCE — DALTON + BOLLINGER] BB Squeeze inside Dalton Bracket! "
                "Volatility compressing while price oscillates in a balance area. "
                "Dalton: \"Markets test bracket extremes 3-5 times before breaking out.\" "
                "The squeeze resolution will likely be the bracket breakout."
            )

        # [CONFLUENCE — DALTON + BOLLINGER] Balance breakout + squeeze resolution
        if mp_result.is_balance_breakout and bb_squeeze_active:
            d = mp_result.balance_breakout_direction
            bonus_dir = 8 if d == "BULLISH" else -8
            agreement_score += bonus_dir
            observations.append(
                f"🔥 [CONFLUENCE — DALTON + BOLLINGER] Balance-area breakout {d} + "
                f"BB squeeze resolution! Dalton: \"A trade you almost have to do.\" "
                f"Bollinger squeeze confirming the bracket escape. Maximum conviction."
            )

        # ── [CONFLUENCE — DALTON + BROOKS] ──
        # One-timeframing + Always-In aligned = maximum trend conviction
        if mp_result.one_timeframing != "NONE" and pa_always_in != "FLAT":
            otf_dir = mp_result.one_timeframing
            if (otf_dir == "UP" and pa_always_in == "LONG") or \
               (otf_dir == "DOWN" and pa_always_in == "SHORT"):
                agreement_score += 5
                observations.append(
                    f"🎯 [CONFLUENCE — DALTON + BROOKS] One-timeframing {otf_dir} + "
                    f"PA Always-In {pa_always_in}! Dalton says \"financially dangerous "
                    f"to trade counter.\" Brooks confirms with always-in direction. "
                    f"Do NOT fade this move."
                )

        # ── [CONFLUENCE — DALTON + MURPHY] ──
        # Initiative activity + strong TA momentum = institutional conviction
        if mp_result.activity_type == "INITIATIVE_BUYING" and ta_momentum > 5:
            agreement_score += 4
            observations.append(
                "🎯 [CONFLUENCE — DALTON + MURPHY] Initiative Buying + TA momentum "
                "positive! Dalton: \"Initiative = they came hunting.\" Murphy confirms "
                "with momentum indicators. Institutional conviction for upside."
            )
        elif mp_result.activity_type == "INITIATIVE_SELLING" and ta_momentum < -5:
            agreement_score -= 4
            observations.append(
                "🎯 [CONFLUENCE — DALTON + MURPHY] Initiative Selling + TA momentum "
                "negative! Institutional conviction for downside."
            )

        # ── [CONFLUENCE — DALTON + VILLAHERMOSA] ──
        # 3-to-I + Wyckoff phase alignment = nuclear conviction
        if mp_result.is_3_to_i and wyckoff_result is not None:
            phase_name = wyckoff_result.phase.phase
            tti_dir = mp_result.three_to_i_direction
            if tti_dir == "BULLISH" and phase_name in ("ACCUMULATION", "MARKUP"):
                agreement_score += 6
                observations.append(
                    f"🔥 [CONFLUENCE — DALTON + VILLAHERMOSA] 3-to-I BULLISH + Wyckoff {phase_name}! "
                    f"Dalton's highest-probability setup (94%/97%) confirmed by Villahermosa phase. "
                    f"This is as close to a guaranteed trade as markets get."
                )
            elif tti_dir == "BEARISH" and phase_name in ("DISTRIBUTION", "MARKDOWN"):
                agreement_score -= 6
                observations.append(
                    f"🔥 [CONFLUENCE — DALTON + VILLAHERMOSA] 3-to-I BEARISH + Wyckoff {phase_name}! "
                    f"Dalton's highest-probability setup confirmed by Villahermosa distribution. "
                    f"Maximum bearish conviction."
                )

        # ── [DALTON D62] Too-elongated profile = reversal warning ──
        if mp_result.profile_shape == "ELONGATED":
            # If profile is elongated but in opposite direction of systems
            observations.append(
                "⚠️ [DALTON D62] Too-elongated profile — Dalton: \"When the profile "
                "is too elongated, the result is often just the opposite.\" "
                "Watch for inventory correction / reversal."
            )

    # Final defensive clamp — extended to ±125 for Wyckoff (±30) + Dalton (±35) + confluences
    agreement_score = max(-125, min(125, agreement_score))

    return {
        "agreement_score": round(agreement_score, 1),
        "bb_direction": bb_dir,
        "ta_direction": ta_dir,
        "pa_direction": pa_dir,
        "wyckoff_bias": wyckoff_bias,
        "wyckoff_bonus": wyckoff_bonus,
        "dalton_bonus": round(dalton_bonus, 1),
        "dalton_signals": dalton_signals,
        "alignment": alignment,
        "observations": observations,
        "systems_aligned": bullish_count if bullish_count >= bearish_count else -bearish_count,
    }


# ═══════════════════════════════════════════════════════════════
#  TRIPLE VERDICT GENERATOR
# ═══════════════════════════════════════════════════════════════

_MAX_SCORE = 425  # 100 (BB) + 100 (TA) + 100 (PA) + 125 (cross-validation incl. Wyckoff + Dalton)

def _generate_triple_verdict(combined_score: float, cross: dict) -> dict:
    """
    Generate final verdict from the combined triple score.

    Thresholds (tighter than dual-system to avoid false signals):
      ≥ 130  SUPER STRONG BUY    (extremely rare — all 3 maxed + aligned)
      ≥  80  STRONG BUY
      ≥  45  BUY
      -44..44  HOLD / WAIT
      ≤ -45  SELL
      ≤ -80  STRONG SELL
      ≤ -130 SUPER STRONG SELL
    """
    if combined_score >= 130:
        verdict, color, emoji = "SUPER STRONG BUY", "bull", "🟢🟢🟢"
    elif combined_score >= 80:
        verdict, color, emoji = "STRONG BUY", "bull", "🟢🟢"
    elif combined_score >= 45:
        verdict, color, emoji = "BUY", "bull", "🟢"
    elif combined_score <= -130:
        verdict, color, emoji = "SUPER STRONG SELL", "bear", "🔴🔴🔴"
    elif combined_score <= -80:
        verdict, color, emoji = "STRONG SELL", "bear", "🔴🔴"
    elif combined_score <= -45:
        verdict, color, emoji = "SELL", "bear", "🔴"
    else:
        verdict, color, emoji = "HOLD / WAIT", "neutral", "🟡"

    confidence = min(abs(combined_score) / _MAX_SCORE * 100, 100)
    alignment = cross.get("alignment", "PARTIAL")

    # Build conviction text
    if alignment == "TRIPLE_ALIGNED":
        conviction = (
            f"ALL THREE systems — Bollinger Bands, Technical Analysis, AND Price Action — "
            f"agree on {verdict}. This triple alignment gives {confidence:.0f}% confidence. "
            f"When three independent frameworks built on different philosophies converge, "
            f"the probability of a correct signal is maximized."
        )
    elif alignment == "DOUBLE_ALIGNED":
        conviction = (
            f"Two of three systems agree on direction, giving {confidence:.0f}% confidence "
            f"in {verdict}. The third system is neutral — watch for it to confirm "
            f"for an even stronger setup."
        )
    elif alignment == "CONFLICTING":
        conviction = (
            f"Systems show CONFLICTING signals, reducing confidence to {confidence:.0f}%. "
            f"When independent analysis frameworks disagree, the market is in a "
            f"transition phase. Trade with caution or wait for alignment."
        )
    else:
        conviction = (
            f"Mixed or neutral signals across all three systems. "
            f"Confidence: {confidence:.0f}%. Wait for clarity before committing capital."
        )

    return {
        "verdict": verdict,
        "emoji": emoji,
        "color": color,
        "score": round(combined_score, 1),
        "max_score": _MAX_SCORE,
        "confidence": round(confidence, 1),
        "conviction_text": conviction,
        "alignment": alignment,
    }


# ═══════════════════════════════════════════════════════════════
#  MASTER TRIPLE ANALYSIS — ENTRY POINT
# ═══════════════════════════════════════════════════════════════

def run_triple_analysis(
    df: pd.DataFrame,
    ticker: str = "UNKNOWN",
    capital: float = 500000,
) -> dict:
    """
    Run the complete BB + TA + PA + Wyckoff + Market Profile unified analysis.

    Pipeline:
      1. Compute BB indicators → BB signal + strategies → BB score (100 pts)
      2. Compute TA indicators → TA signal → TA score (100 pts)
      3. Classify PA bars → patterns → trend → channels → breakouts → PA score (100 pts)
      3.5 Run Wyckoff/Villahermosa analysis → phase + volume context (bonus layer)
      3.6 Run Market Profile analysis → auction + value context (bonus layer)
      4. Triple cross-validate + Wyckoff + Dalton → agreement bonus (±125 pts)
      5. Combined score → final verdict → full response

    Returns:
        Complete analysis dict with all systems' data for the dashboard.
    """
    if df is None or df.empty or len(df) < 60:
        return {"error": "Insufficient data (need at least 60 bars)"}

    freshness = get_data_freshness(df)

    # ══════════════════════════════════════════════════════════
    #  STEP 1: BOLLINGER BAND ANALYSIS (100 pts)
    # ══════════════════════════════════════════════════════════
    df_bb = compute_bb_indicators(df.copy())
    bb_signal = generate_bb_signal(ticker, df_bb)
    bb_strategies = run_all_strategies(df_bb)
    bb_strats_dict = [strategy_result_to_dict(s) for s in bb_strategies]

    m1 = _score_bb_method_1(bb_signal)
    _strat_map = {s.get("code"): s for s in bb_strats_dict}
    m2 = _score_bb_method_2(_strat_map.get("M2", {}))
    m3 = _score_bb_method_3(_strat_map.get("M3", {}))
    m4 = _score_bb_method_4(_strat_map.get("M4", {}))
    bb_total = m1["score"] + m2["score"] + m3["score"] + m4["score"]
    bb_methods = [m1, m2, m3, m4]

    # ══════════════════════════════════════════════════════════
    #  STEP 2: TECHNICAL ANALYSIS (100 pts)
    # ══════════════════════════════════════════════════════════
    df_ta = compute_all_ta_indicators(df.copy())
    snapshot = get_indicator_snapshot(df_ta)
    trend = identify_trend(df_ta)
    crossovers = detect_ma_crossovers(df_ta)
    divergences = detect_all_divergences(df_ta)
    candle_patterns = scan_candlestick_patterns(df_ta, lookback=5)
    chart_patterns = detect_all_chart_patterns(df_ta)
    vol_analysis = analyze_volume(df_ta)
    ichimoku = analyze_ichimoku(df_ta)
    sr_data = detect_support_resistance(df_ta)
    fib_data = compute_fibonacci(df_ta)
    pivot = compute_pivot_points(df_ta)

    ta_signal = generate_ta_signal(
        snap=snapshot, trend=trend, vol_analysis=vol_analysis,
        chart_patterns=chart_patterns, candle_patterns=candle_patterns,
        divergences=divergences, sr_data=sr_data, fib_data=fib_data,
    )
    ta_total = ta_signal.get("score", 0)

    risk = generate_risk_report(snapshot, sr_data, capital)
    target_prices = calculate_target_prices(
        snap=snapshot, trend=trend, sr_data=sr_data,
        fib_data=fib_data, pivot=pivot, chart_patterns=chart_patterns,
    )

    # ══════════════════════════════════════════════════════════
    #  STEP 3: PRICE ACTION ANALYSIS (100 pts)
    # ══════════════════════════════════════════════════════════
    pa_result = run_price_action_analysis(df, ticker=ticker)

    pa_scored = _score_pa(pa_result)
    pa_total = pa_scored["total"]

    # ══════════════════════════════════════════════════════════
    #  STEP 3.5: WYCKOFF/VILLAHERMOSA ANALYSIS (Phase + Volume Context)
    #  [VILLAHERMOSA] Not a 4th score — a cross-validation enhancer
    # ══════════════════════════════════════════════════════════
    try:
        wyckoff = run_wyckoff_analysis(df, ticker=ticker)
    except Exception:
        wyckoff = None

    # ══════════════════════════════════════════════════════════
    #  STEP 3.6: MARKET PROFILE ANALYSIS (Auction + Value Context)
    #  [DALTON] Not a 4th score — blended into cross-validation.
    #  Computes: Value Area, day types, initiative/responsive,
    #  one-timeframing, 3-to-I, poor highs/lows, bracket/trend,
    #  POC migration, directional performance, and gap classification.
    # ══════════════════════════════════════════════════════════
    try:
        market_profile = run_market_profile_analysis(df)
    except Exception:
        market_profile = None

    # ══════════════════════════════════════════════════════════
    #  STEP 4: TRIPLE CROSS-VALIDATION (±125 pts incl. Wyckoff + Dalton)
    # ══════════════════════════════════════════════════════════
    cross = _triple_cross_validate(
        bb_total, ta_total, pa_total,
        bb_methods, ta_signal, pa_scored,
        wyckoff_result=wyckoff,
        mp_result=market_profile,
    )

    # ══════════════════════════════════════════════════════════
    #  STEP 5: COMBINED SCORE + VERDICT
    # ══════════════════════════════════════════════════════════
    combined_score = bb_total + ta_total + pa_total + cross["agreement_score"]
    verdict = _generate_triple_verdict(combined_score, cross)

    # ══════════════════════════════════════════════════════════
    #  STEP 6: BUILD COMPLETE BB DATA (for dashboard display)
    # ══════════════════════════════════════════════════════════
    bb_data = {
        "phase": bb_signal.phase,
        "squeeze_on": bb_signal.cond1_squeeze_on,
        "squeeze_days": bb_signal.squeeze_days,
        "buy_signal": bb_signal.buy_signal,
        "sell_signal": bb_signal.sell_signal,
        "head_fake": bb_signal.head_fake,
        "confidence": bb_signal.confidence,
        "direction_lean": bb_signal.direction_lean,
        "summary": bb_signal.summary,
        "action_message": bb_signal.action_message,
        "indicators": {
            "price": _safe(bb_signal.current_price),
            "bb_upper": _safe(bb_signal.bb_upper),
            "bb_mid": _safe(bb_signal.bb_mid),
            "bb_lower": _safe(bb_signal.bb_lower),
            "bbw": _safe(bb_signal.bbw),
            "percent_b": _safe(bb_signal.percent_b),
            "sar": _safe(bb_signal.sar),
            "sar_bull": bb_signal.sar_bull,
            "cmf": _safe(bb_signal.cmf),
            "mfi": _safe(bb_signal.mfi),
            "volume": _safe(bb_signal.volume),
            "vol_sma50": _safe(bb_signal.vol_sma50),
            "ii_pct": _safe(bb_signal.ii_pct),
            "ad_pct": _safe(bb_signal.ad_pct),
            "vwmacd_hist": _safe(bb_signal.vwmacd_hist),
            "rsi_norm": _safe(bb_signal.rsi_norm),
            "mfi_norm": _safe(bb_signal.mfi_norm),
            "expansion_up": bb_signal.expansion_up,
            "expansion_down": bb_signal.expansion_down,
            "expansion_end": bb_signal.expansion_end,
        },
        "conditions": {
            "squeeze": bb_signal.cond1_squeeze_on,
            "price_breakout": bb_signal.cond2_price_above,
            "volume_confirm": bb_signal.cond3_volume_ok,
            "cmf_positive": bb_signal.cond4_cmf_positive,
            "mfi_above_50": bb_signal.cond5_mfi_above_50,
        },
        "exit_signals": {
            "sar_flip": bb_signal.exit_sar_flip,
            "lower_band_tag": bb_signal.exit_lower_band_tag,
            "double_negative": bb_signal.exit_double_neg,
            "expansion_end": bb_signal.expansion_end,
        },
        "short_signal": bb_signal.short_signal,
        "short_conditions": {
            "squeeze": bb_signal.cond_short_squeeze,
            "price_below": bb_signal.cond_short_price,
            "volume_confirm": bb_signal.cond_short_volume,
            "ii_negative": bb_signal.cond_short_ii_neg,
            "mfi_low": bb_signal.cond_short_mfi_low,
        },
        "stop_loss": _safe(bb_signal.stop_loss),
    }

    # ══════════════════════════════════════════════════════════
    #  STEP 7: BUILD COMPLETE PA DATA (for dashboard display)
    # ══════════════════════════════════════════════════════════
    pa_data = {
        "signal_type": pa_result.signal_type,
        "setup_type": pa_result.setup_type,
        "strength": pa_result.strength,
        "confidence": pa_result.confidence,
        "pa_score": round(pa_result.pa_score, 1),
        "always_in": pa_result.always_in,
        "always_in_score": round(pa_result.always_in_score, 1),
        "trend_direction": pa_result.trend_direction,
        "trend_phase": pa_result.trend_phase,
        "buying_pressure": round(pa_result.buying_pressure, 1),
        "selling_pressure": round(pa_result.selling_pressure, 1),
        "last_bar_type": pa_result.last_bar_type,
        "last_bar_signal": pa_result.last_bar_signal,
        "active_patterns": pa_result.active_patterns,
        "breakout_mode": pa_result.breakout_mode,
        "in_breakout": pa_result.in_breakout,
        "breakout_direction": pa_result.breakout_direction,
        "entry_price": _safe(pa_result.entry_price),
        "stop_loss": _safe(pa_result.stop_loss),
        "target_1": _safe(pa_result.target_1),
        "target_2": _safe(pa_result.target_2),
        "risk_reward": _safe(pa_result.risk_reward),
        "two_leg_complete": pa_result.two_leg_complete,
        "measured_move_target": _safe(pa_result.measured_move_target),
        "ema_gap_bar_count": pa_result.ema_gap_bar_count,
        "gap_bar_setup": pa_result.gap_bar_setup,
        "in_spike": pa_result.in_spike,
        "spike_direction": pa_result.spike_direction,
        "spike_bars": pa_result.spike_bars,
        "spike_strength": _safe(pa_result.spike_strength),
        "recent_climax": pa_result.recent_climax,
        "consecutive_bull_trend": pa_result.consecutive_bull_trend,
        "consecutive_bear_trend": pa_result.consecutive_bear_trend,
        "price_vs_ema": pa_result.price_vs_ema,
        "ema20": _safe(pa_result.ema20),
        "trend_strength": _safe(pa_result.trend_strength),
        "last_bar_description": pa_result.last_bar_description,
        "bar_summary": _safe_json(pa_result.bar_summary_data) if isinstance(pa_result.bar_summary_data, dict) else {},
        "al_brooks_context": pa_result.al_brooks_context,
        "reasons": pa_result.reasons[:10],
    }

    # ══════════════════════════════════════════════════════════
    #  STEP 7.5: UNIFIED TRIPLE TARGETS (BUY/SELL/Stop across BB + TA + PA + Wyckoff)
    # ══════════════════════════════════════════════════════════
    wyckoff_dict = wyckoff_to_dict(wyckoff) if wyckoff else None
    try:
        triple_targets = compute_triple_targets(
            triple_verdict=verdict,
            bb_data=bb_data,
            bb_score={"total": bb_total},
            ta_signal=ta_signal,
            ta_score={"total": ta_total},
            ta_risk=risk,
            ta_targets=target_prices,
            pa_data=pa_data,
            pa_score=pa_scored,
            wyckoff=wyckoff_dict,
            cross=cross,
        )
    except Exception as ex:
        triple_targets = {"error": f"compute_triple_targets failed: {ex}"}

    # ══════════════════════════════════════════════════════════
    #  STEP 8: ASSEMBLE FINAL RESPONSE
    # ══════════════════════════════════════════════════════════
    result = _safe_json({
        "triple_verdict": verdict,
        "data_freshness": freshness,
        "cross_validation": cross,

        # ── Unified Triple Targets (BUY/SELL plan across all 3 systems) ──
        "triple_targets": triple_targets,

        # ── System Scores ──
        "bb_score": {
            "total": round(bb_total, 1),
            "max": 100,
            "methods": bb_methods,
        },
        "ta_score": {
            "total": round(ta_total, 1),
            "max": 100,
            "categories": ta_signal.get("categories", {}),
        },
        "pa_score": pa_scored,

        # ── Wyckoff/Villahermosa Context Layer ──
        "wyckoff": wyckoff_dict,

        # ── Market Profile / Dalton Context Layer ──
        "market_profile": market_profile_to_dict(market_profile) if market_profile else None,

        # ── Raw System Data ──
        "bb_data": bb_data,
        "bb_strategies": bb_strats_dict,
        "ta_signal": ta_signal,
        "pa_data": pa_data,

        # ── TA Detail Data ──
        "snapshot": snapshot,
        "trend": trend,
        "crossovers": crossovers,
        "divergences": divergences,
        "candle_patterns": candle_patterns,
        "chart_patterns": chart_patterns,
        "volume": vol_analysis,
        "ichimoku": ichimoku,
        "support_resistance": sr_data,
        "fibonacci": fib_data,
        "pivot_points": pivot,
        "risk": risk,
        "target_prices": target_prices,
    })

    return result
