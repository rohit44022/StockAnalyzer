"""
portfolio_analyzer.py — Strategy-aware post-purchase analysis engine.

For each open portfolio position this module:
  1. Loads current daily OHLCV data from the existing data_loader
  2. Computes all technical indicators (reuses indicators.py)
  3. Runs the SAME strategy that was used to buy (M1/M2/M3/M4)
  4. Generates an actionable recommendation: HOLD / SELL / ADD
  5. Computes target prices based on Bollinger Bands + fundamentals
  6. Returns a rich analysis dict ready for the UI

This module NEVER modifies any existing module.  It only reads from them.
"""

from __future__ import annotations

import math
from datetime import datetime, date

import pandas as pd
import numpy as np

from bb_squeeze.data_loader import load_stock_data, normalise_ticker
from bb_squeeze.indicators import compute_all_indicators
from bb_squeeze.signals import analyze_signals
from bb_squeeze.strategies import run_all_strategies, strategy_result_to_dict
from bb_squeeze.config import CSV_DIR
from bb_squeeze.strategy_config import (
    M2_PCT_B_BUY_THRESHOLD, M2_PCT_B_SELL_THRESHOLD,
    M2_MFI_CONFIRM_BUY, M2_MFI_CONFIRM_SELL,
    M4_WALK_PCT_B_UPPER,
)

# Multi-system engines
from hybrid_pa_engine import run_triple_analysis
from price_action.engine import run_price_action_analysis


# ═══════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════

def _safe(v, decimals=2):
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, (float, np.floating)):
        return round(float(v), decimals)
    return v


def _holding_days(buy_date_str: str) -> int:
    try:
        bd = datetime.strptime(buy_date_str, "%Y-%m-%d").date()
        return (date.today() - bd).days
    except Exception:
        return 0


# ═══════════════════════════════════════════════════════════════
#  TARGET PRICE COMPUTATION
# ═══════════════════════════════════════════════════════════════

def _compute_targets(df: pd.DataFrame, buy_price: float) -> dict:
    """
    Generate target price levels based on Bollinger Bands and price action.

    Targets:
      - BB Upper:    Current upper band (resistance)
      - BB Mid:      Current middle band (support/resistance pivot)
      - BB Lower:    Current lower band (support)
      - 1-Sigma:     Mid + 1*sigma (intermediate target)
      - 2-Sigma:     Mid + 2*sigma (= BB Upper)
      - 3-Sigma:     Mid + 3*sigma (extended target if breaking upper)
      - Stop Loss:   SAR value or BB Lower, whichever is tighter
      - Risk:Reward  based on stop loss vs upper band target
    """
    row = df.iloc[-1]
    mid   = float(row["BB_Mid"])
    upper = float(row["BB_Upper"])
    lower = float(row["BB_Lower"])
    sigma = (upper - mid) / 2.0 if upper != mid else 0
    sar   = float(row["SAR"])
    price = float(row["Close"])

    # Stop loss = tighter of SAR and lower band (for long positions)
    stop_loss = max(sar, lower) if bool(row["SAR_Bull"]) else min(sar, lower)
    # For long positions stop is below price
    if stop_loss > price:
        stop_loss = lower

    # Targets
    t1_sigma = mid + sigma        # +1 sigma
    t2_sigma = upper               # +2 sigma = upper band
    t3_sigma = mid + 3 * sigma     # +3 sigma (extended)

    # 52-week high from available data
    lookback_252 = df.tail(252)
    high_52w = float(lookback_252["High"].max())
    low_52w  = float(lookback_252["Low"].min())

    # Risk:Reward ratio
    risk = buy_price - stop_loss
    reward_upper = upper - buy_price if upper > buy_price else 0
    if risk > 0 and reward_upper > 0:
        rr_ratio = round(reward_upper / risk, 2)
    elif risk <= 0:
        # Stock already above stop loss relative to buy — risk is effectively covered
        rr_ratio = 0  # N/A (already in profit relative to stop)
    else:
        rr_ratio = 0

    # Percentage distances from current price
    def pct_from(target):
        if price == 0:
            return 0
        return round((target - price) / price * 100, 2)

    return {
        "current_price":    _safe(price),
        "buy_price":        _safe(buy_price),
        "pnl_amount":       _safe(price - buy_price),
        "pnl_pct":          _safe((price - buy_price) / buy_price * 100 if buy_price else 0),
        "bb_upper":         _safe(upper),
        "bb_mid":           _safe(mid),
        "bb_lower":         _safe(lower),
        "sigma":            _safe(sigma),
        "target_1_sigma":   _safe(t1_sigma),
        "target_2_sigma":   _safe(t2_sigma),
        "target_3_sigma":   _safe(t3_sigma),
        "stop_loss":        _safe(stop_loss),
        "risk_reward":      rr_ratio,
        "high_52w":         _safe(high_52w),
        "low_52w":          _safe(low_52w),
        "pct_to_upper":     pct_from(upper),
        "pct_to_mid":       pct_from(mid),
        "pct_to_lower":     pct_from(lower),
        "pct_to_3sigma":    pct_from(t3_sigma),
        "pct_to_52w_high":  pct_from(high_52w),
    }


# ═══════════════════════════════════════════════════════════════
#  POST-PURCHASE RECOMMENDATION ENGINE
# ═══════════════════════════════════════════════════════════════

def _generate_recommendation(
    strategy_code: str,
    sig,          # Method I SignalResult
    strategies,   # [M2, M3, M4] StrategyResult list
    df: pd.DataFrame,
    buy_price: float,
) -> dict:
    """
    Generate HOLD / SELL / ADD recommendation based on the BUYING strategy
    plus confirming signals from other strategies.

    Returns dict with:
      action, strength, reasons[], warnings[], strategy_status, confirms[],
      action_triggers[], entry_quality{}, momentum{}
    """
    row = df.iloc[-1]
    price    = float(row["Close"])
    pct_b    = float(row["Percent_B"])
    mfi      = float(row["MFI"])
    cmf      = float(row["CMF"])
    sar_bull = bool(row["SAR_Bull"])
    bbw      = float(row["BBW"])
    upper    = float(row["BB_Upper"])
    mid      = float(row["BB_Mid"])
    lower    = float(row["BB_Lower"])
    sar      = float(row["SAR"])
    volume   = float(row["Volume"])
    vol_sma  = float(row["Vol_SMA50"]) if not math.isnan(row["Vol_SMA50"]) else 0

    m2 = strategies[0]
    m3 = strategies[1]
    m4 = strategies[2]

    reasons  = []
    warnings = []
    confirms = []
    action_triggers = []
    action   = "HOLD"
    strength = "MODERATE"

    # ── Entry Quality Assessment ──
    pnl_pct = (price - buy_price) / buy_price * 100 if buy_price else 0
    if buy_price <= lower:
        entry_zone = "EXCELLENT"
        entry_note = "Bought at or below lower band — textbook entry"
    elif buy_price <= mid:
        entry_zone = "GOOD"
        entry_note = "Bought between lower and mid band — favorable entry"
    elif buy_price <= upper:
        entry_zone = "FAIR"
        entry_note = "Bought between mid and upper band — average entry"
    else:
        entry_zone = "LATE"
        entry_note = "Bought above upper band — potentially chasing"

    entry_quality = {
        "zone": entry_zone,
        "note": entry_note,
        "buy_vs_mid_pct": _safe((buy_price - mid) / mid * 100 if mid else 0),
        "current_vs_buy_pct": _safe(pnl_pct),
    }

    # ── Momentum Assessment (last 5 bars) ──
    recent = df.tail(5)
    pct_b_slope = float(recent["Percent_B"].iloc[-1] - recent["Percent_B"].iloc[0])
    mfi_slope = float(recent["MFI"].iloc[-1] - recent["MFI"].iloc[0])
    vol_trend = "RISING" if volume > vol_sma * 1.1 else ("FADING" if volume < vol_sma * 0.8 else "NORMAL")
    bbw_expanding = float(df.tail(10)["BBW"].iloc[-1]) > float(df.tail(10)["BBW"].iloc[0])

    if pct_b_slope > 0.1 and mfi_slope > 5:
        momentum_label = "STRONG BULLISH"
    elif pct_b_slope > 0 and mfi_slope > 0:
        momentum_label = "BULLISH"
    elif pct_b_slope < -0.1 and mfi_slope < -5:
        momentum_label = "STRONG BEARISH"
    elif pct_b_slope < 0 and mfi_slope < 0:
        momentum_label = "BEARISH"
    else:
        momentum_label = "NEUTRAL"

    momentum = {
        "label": momentum_label,
        "pct_b_slope": _safe(pct_b_slope, 3),
        "mfi_slope": _safe(mfi_slope, 1),
        "volume_trend": vol_trend,
        "bbw_expanding": bbw_expanding,
    }

    # ── Strategy-specific primary signal ──
    if strategy_code == "M1":
        # Bought on squeeze breakout — check if breakout is still valid
        if sig.sell_signal:
            action = "SELL"
            strength = "STRONG"
            if sig.exit_sar_flip:
                reasons.append("SAR has flipped bearish — trend reversal confirmed")
            if sig.exit_lower_band_tag:
                reasons.append("Price tagged the lower Bollinger Band")
            if sig.exit_double_neg:
                reasons.append("Both CMF and MFI are negative — money outflow")
            action_triggers.append(f"EXIT NOW: SAR at ₹{sar:.2f} is above price — bearish confirmation")
        elif sig.hold_signal:
            action = "HOLD"
            reasons.append(f"SAR bullish, price above mid band, CMF & MFI supportive")
            if pct_b > 0.8 and mfi > 60:
                strength = "STRONG"
                reasons.append("Strong uptrend: %b > 0.8 with MFI confirmation")
            action_triggers.append(f"SELL if SAR flips bearish (SAR crosses above ₹{price:.2f})")
            action_triggers.append(f"SELL if price closes below ₹{lower:.2f} (lower band)")
            action_triggers.append(f"BOOK PARTIAL if price reaches ₹{upper:.2f} (upper band)")
        elif sig.buy_signal:
            action = "ADD"
            strength = "STRONG"
            reasons.append("Fresh squeeze breakout signal — consider adding to position")
            action_triggers.append(f"ADD on volume confirmation (current vol vs SMA50: {volume/vol_sma:.1f}x)" if vol_sma > 0 else "ADD on volume confirmation")
        else:
            # Squeeze ON but no buy/sell
            action = "HOLD"
            strength = "WEAK"
            reasons.append("Squeeze is active — waiting for directional breakout")
            if sig.direction_lean == "BULLISH":
                reasons.append("Direction lean is BULLISH — breakout likely upward")
            elif sig.direction_lean == "BEARISH":
                reasons.append("Direction lean is BEARISH — downside risk")
                warnings.append("Squeeze may resolve downward — tighten stop loss")
            action_triggers.append(f"BUY/ADD if price breaks above ₹{upper:.2f} with volume")
            action_triggers.append(f"SELL if price breaks below ₹{lower:.2f}")

    elif strategy_code == "M2":
        sig_type = m2.signal.signal_type
        if sig_type == "BUY":
            action = "ADD"
            strength = m2.signal.strength
            reasons.append(f"Method II confirms trend: %b={pct_b:.2f}, MFI={mfi:.0f}")
            action_triggers.append(f"ADD while %b stays above {M2_PCT_B_BUY_THRESHOLD} with MFI > {M2_MFI_CONFIRM_BUY}")
            action_triggers.append(f"SELL if %b drops below 0.5 (currently {pct_b:.2f})")
        elif sig_type == "SELL":
            action = "SELL"
            strength = m2.signal.strength
            reasons.append(f"Method II sell: %b={pct_b:.2f}, MFI={mfi:.0f} — both weak")
            action_triggers.append(f"EXIT: %b is below {M2_PCT_B_SELL_THRESHOLD} with MFI < {M2_MFI_CONFIRM_SELL}")
        elif sig_type == "HOLD":
            action = "HOLD"
            strength = "MODERATE"
            reasons.append(f"Trend intact: %b={pct_b:.2f}, MFI={mfi:.0f}")
            action_triggers.append(f"SELL if %b drops below {M2_PCT_B_SELL_THRESHOLD} (currently {pct_b:.2f})")
            action_triggers.append(f"ADD if %b rises above {M2_PCT_B_BUY_THRESHOLD} with MFI > {M2_MFI_CONFIRM_BUY}")
        elif sig_type == "WATCH":
            action = "HOLD"
            strength = "WEAK"
            reasons.append(f"Divergence detected — {m2.signal.reason}")
            warnings.append("Divergence between %b and MFI — trend may weaken")
            action_triggers.append("WATCH: Divergence may lead to reversal — tighten stop to mid band")
        else:
            action = "HOLD"
            strength = "WEAK"
            reasons.append("No clear Method II signal — hold and monitor")

    elif strategy_code == "M3":
        sig_type = m3.signal.signal_type
        if sig_type == "BUY":
            action = "ADD"
            strength = m3.signal.strength
            reasons.append(f"W-Bottom confirmed — reversal pattern active")
            if m3.patterns:
                p = m3.patterns[-1]
                reasons.append(f"Pattern: {p.description}")
            action_triggers.append(f"HOLD for rally toward mid band ₹{mid:.2f} then upper band ₹{upper:.2f}")
            action_triggers.append(f"SELL if price breaks below ₹{lower:.2f} (pattern failure)")
        elif sig_type == "SELL":
            action = "SELL"
            strength = m3.signal.strength
            reasons.append(f"M-Top detected — reversal to downside expected")
            if m3.patterns:
                p = m3.patterns[-1]
                reasons.append(f"Pattern: {p.description}")
            action_triggers.append(f"EXIT: M-Top confirms head at upper band — expect drop to ₹{mid:.2f}")
        else:
            action = "HOLD"
            strength = "MODERATE"
            reasons.append("No reversal pattern currently — hold position")
            action_triggers.append(f"WATCH for W-Bottom if price retests ₹{lower:.2f}")
            action_triggers.append(f"WATCH for M-Top if price retests ₹{upper:.2f}")

    elif strategy_code == "M4":
        sig_type = m4.signal.signal_type
        if sig_type == "HOLD":
            action = "HOLD"
            strength = m4.signal.strength
            reasons.append("Walking the upper band — strong uptrend continues")
            action_triggers.append(f"HOLD while price stays above mid band ₹{mid:.2f}")
            action_triggers.append(f"SELL if price closes below mid band (band walk break)")
        elif sig_type == "SELL":
            action = "SELL"
            strength = m4.signal.strength
            reasons.append(f"Band walk breaking: {m4.signal.reason}")
            action_triggers.append(f"EXIT: Band walk broken — expect mean reversion to ₹{mid:.2f}")
        elif sig_type == "BUY":
            action = "ADD"
            strength = m4.signal.strength
            reasons.append("Lower band walk breaking — reversal opportunity")
            action_triggers.append(f"ADD if reversal confirmed with MFI > 50 (currently {mfi:.0f})")
        else:
            action = "HOLD"
            strength = "WEAK"
            reasons.append("No active band walk — hold and monitor")
            action_triggers.append(f"WATCH for upper band walk if %b sustains > {M4_WALK_PCT_B_UPPER}")

    # ── Cross-strategy confirmation ──
    if m2.signal.signal_type == "BUY":
        confirms.append("M2 Trend Following: BUY confirmed (%b + MFI aligned)")
    elif m2.signal.signal_type == "SELL":
        confirms.append("M2 Trend Following: SELL — trend weakening")
    elif m2.signal.signal_type == "HOLD":
        confirms.append("M2 Trend Following: HOLD — trend intact")

    if m3.signal.signal_type == "BUY":
        confirms.append("M3 Reversals: W-Bottom pattern detected")
    elif m3.signal.signal_type == "SELL":
        confirms.append("M3 Reversals: M-Top pattern — potential reversal")

    if m4.signal.signal_type == "HOLD":
        confirms.append("M4 Band Walking: Upper band walk active — strong trend")
    elif m4.signal.signal_type == "SELL":
        confirms.append("M4 Band Walking: Walk breaking — momentum fading")

    if sig.sell_signal:
        confirms.append("M1 Squeeze: EXIT signals triggered")
    elif sig.hold_signal:
        confirms.append("M1 Squeeze: HOLD — technicals supportive")

    # ── Universal warnings ──
    if cmf < 0 and action != "SELL":
        warnings.append(f"CMF is negative ({cmf:.3f}) — money outflow detected")
    if mfi < 40 and action != "SELL":
        warnings.append(f"MFI is low ({mfi:.0f}) — buying pressure weak")
    if not sar_bull and action != "SELL":
        warnings.append("SAR is bearish (dots above price) — caution")
    if price < buy_price:
        loss_pct = (buy_price - price) / buy_price * 100
        if loss_pct > 10:
            warnings.append(f"Position is down {loss_pct:.1f}% — review stop loss")
        elif loss_pct > 5:
            warnings.append(f"Position is down {loss_pct:.1f}% — monitor closely")

    # ── Momentum-based refinements ──
    if "BEARISH" in momentum_label and action == "HOLD":
        strength = "WEAK"
        warnings.append(f"Momentum turning bearish (%b slope: {pct_b_slope:+.3f}, MFI slope: {mfi_slope:+.1f})")
    if vol_trend == "FADING" and action == "HOLD":
        warnings.append("Volume fading below 50-day average — conviction thinning")

    # ── If multiple strategies say SELL, upgrade strength ──
    sell_count = sum(1 for s in [m2, m3, m4] if s.signal.signal_type == "SELL")
    if sell_count >= 2 and action != "SELL":
        action = "SELL"
        strength = "STRONG"
        reasons.append("Multiple strategies confirm sell signal")

    return {
        "action":          action,
        "strength":        strength,
        "reasons":         reasons,
        "warnings":        warnings,
        "confirms":        confirms,
        "action_triggers": action_triggers,
        "entry_quality":   entry_quality,
        "momentum":        momentum,
        "strategy_code":   strategy_code,
    }


# ═══════════════════════════════════════════════════════════════
#  MULTI-SYSTEM ANALYSIS (Hybrid + Triple + PA)
# ═══════════════════════════════════════════════════════════════

def _run_multi_system(df_raw: pd.DataFrame, ticker: str, buy_price: float) -> dict:
    """
    Run Hybrid (BB+TA), Triple (BB+TA+PA), and standalone PA engines.
    Returns condensed results for each system + a master summary.
    """
    results = {}

    # 1. Triple Engine (BB + TA + PA) — replaces old hybrid engine
    try:
        triple = run_triple_analysis(df_raw, ticker=ticker)
        tv = triple.get("triple_verdict", {})
        pa_d = triple.get("pa_data", {})
        pa_s = triple.get("pa_score", {})
        cv = triple.get("cross_validation", {})
        # Provide backward-compatible "hybrid" key with triple data
        results["hybrid"] = {
            "verdict":    tv.get("verdict", "N/A"),
            "score":      _safe(tv.get("score", 0)),
            "max_score":  tv.get("max_score", 390),
            "confidence": _safe(tv.get("confidence", 0)),
            "alignment":  cv.get("alignment", "N/A"),
            "bb_score":   _safe(triple.get("bb_score", {}).get("total", 0)),
            "ta_score":   _safe(triple.get("ta_score", {}).get("total", 0)),
            "ta_verdict": triple.get("ta_signal", {}).get("verdict", "N/A"),
        }
        results["triple"] = {
            "verdict":     tv.get("verdict", "N/A"),
            "score":       _safe(tv.get("score", 0)),
            "max_score":   tv.get("max_score", 390),
            "confidence":  _safe(tv.get("confidence", 0)),
            "alignment":   cv.get("alignment", "N/A"),
            "bb_score":    _safe(triple.get("bb_score", {}).get("total", 0)),
            "ta_score":    _safe(triple.get("ta_score", {}).get("total", 0)),
            "pa_score":    _safe(pa_s.get("total", 0)),
        }
        # [WEIS] Extract Wyckoff data from triple engine
        wyckoff_raw = triple.get("wyckoff")
        if wyckoff_raw:
            wk_phase = wyckoff_raw.get("phase", {})
            results["wyckoff"] = {
                "phase":       wk_phase.get("name", "UNKNOWN"),
                "sub_phase":   wk_phase.get("sub_phase", "UNKNOWN"),
                "confidence":  wk_phase.get("confidence", 0),
                "bias":        wyckoff_raw.get("scoring", {}).get("bias", "NEUTRAL"),
                "bonus":       wyckoff_raw.get("scoring", {}).get("wyckoff_bonus", 0),
                "volume":      wyckoff_raw.get("volume", {}),
                "wave_balance": wyckoff_raw.get("wave_balance", {}),
                "shortening":  wyckoff_raw.get("shortening", {}),
                "events":      wk_phase.get("events", []),
                "hints":       wyckoff_raw.get("hints", []),
                "summary":     wyckoff_raw.get("summary", ""),
            }
        else:
            results["wyckoff"] = None

        # [DALTON] Extract Market Profile data from triple engine
        mp_raw = triple.get("market_profile")
        if mp_raw:
            results["dalton"] = {
                "value_area":     mp_raw.get("value_area", {}),
                "day_type":       mp_raw.get("day_type", {}),
                "open_type":      mp_raw.get("open_type", "UNKNOWN"),
                "open_vs_prev":   mp_raw.get("open_vs_prev", {}),
                "activity":       mp_raw.get("activity", "UNKNOWN"),
                "directional_performance": mp_raw.get("directional_performance", {}),
                "market_structure": mp_raw.get("market_structure", {}),
                "one_timeframing": mp_raw.get("one_timeframing", {}),
                "poor_extremes":  mp_raw.get("poor_extremes", {}),
                "profile_shape":  mp_raw.get("profile_shape", "NORMAL"),
                "high_probability": mp_raw.get("high_probability", {}),
                "gap":            mp_raw.get("gap", {}),
                "overnight_inventory": mp_raw.get("overnight_inventory", "NEUTRAL"),
                "rotation_factor": mp_raw.get("rotation_factor", 0),
                "poc_migration":  mp_raw.get("poc_migration", "STATIONARY"),
                "va_sequence":    mp_raw.get("va_sequence", []),
                "scoring":        mp_raw.get("scoring", {}),
                "dalton_signals": mp_raw.get("dalton_signals", []),
                "observations":   mp_raw.get("observations", []),
                "summary":        mp_raw.get("summary", ""),
            }
        else:
            results["dalton"] = None
    except Exception:
        results["hybrid"] = {"verdict": "ERROR", "score": 0, "max_score": 390,
                             "confidence": 0, "alignment": "N/A", "bb_score": 0, "ta_score": 0, "ta_verdict": "N/A"}
        results["triple"] = {"verdict": "ERROR", "score": 0, "max_score": 390,
                             "confidence": 0, "alignment": "N/A", "bb_score": 0, "ta_score": 0, "pa_score": 0}
        results["wyckoff"] = None
        results["dalton"] = None
    try:
        pa_result = run_price_action_analysis(df_raw, ticker=ticker)
        results["price_action"] = {
            "signal":        pa_result.signal_type,
            "setup":         pa_result.setup_type,
            "strength":      pa_result.strength,
            "confidence":    pa_result.confidence,
            "pa_score":      _safe(pa_result.pa_score),
            "always_in":     pa_result.always_in,
            "trend":         pa_result.trend_direction,
            "stop_loss":     _safe(pa_result.stop_loss),
            "target_1":      _safe(pa_result.target_1),
            "target_2":      _safe(pa_result.target_2),
            "risk_reward":   _safe(pa_result.risk_reward),
            "bar_type":      pa_result.last_bar_type,
            "bar_desc":      pa_result.last_bar_description,
            "patterns":      pa_result.active_patterns[:5] if pa_result.active_patterns else [],
            "context":       pa_result.al_brooks_context,
            "reasons":       pa_result.reasons[:5] if pa_result.reasons else [],
        }
    except Exception:
        results["price_action"] = {"signal": "ERROR", "setup": "N/A", "strength": "N/A",
                                   "confidence": 0, "pa_score": 0, "always_in": "N/A",
                                   "trend": "N/A", "stop_loss": None, "target_1": None,
                                   "target_2": None, "risk_reward": None, "bar_type": "N/A",
                                   "bar_desc": "", "patterns": [], "context": "", "reasons": []}

    # 4. Master Summary — plain language
    results["master_summary"] = _build_master_summary(results, buy_price)

    return results


def _build_master_summary(systems: dict, buy_price: float) -> dict:
    """
    Combine all system verdicts into one clear, plain-language recommendation.
    Does NOT override the BB-based recommendation — this is an additional perspective.
    """
    hybrid = systems.get("hybrid", {})
    triple = systems.get("triple", {})
    pa = systems.get("price_action", {})

    # Count consensus
    votes = {"BUY": 0, "SELL": 0, "HOLD": 0}
    system_opinions = []

    # Hybrid verdict
    hv = hybrid.get("verdict", "N/A")
    if "BUY" in hv:
        votes["BUY"] += 1
        system_opinions.append(("Hybrid (BB+TA)", "BULLISH", hv))
    elif "SELL" in hv:
        votes["SELL"] += 1
        system_opinions.append(("Hybrid (BB+TA)", "BEARISH", hv))
    else:
        votes["HOLD"] += 1
        system_opinions.append(("Hybrid (BB+TA)", "NEUTRAL", hv))

    # Triple verdict
    tv = triple.get("verdict", "N/A")
    if "BUY" in tv:
        votes["BUY"] += 1
        system_opinions.append(("Triple (BB+TA+PA)", "BULLISH", tv))
    elif "SELL" in tv:
        votes["SELL"] += 1
        system_opinions.append(("Triple (BB+TA+PA)", "BEARISH", tv))
    else:
        votes["HOLD"] += 1
        system_opinions.append(("Triple (BB+TA+PA)", "NEUTRAL", tv))

    # PA standalone
    pa_sig = pa.get("signal", "N/A")
    if pa_sig == "BUY":
        votes["BUY"] += 1
        system_opinions.append(("Price Action (Al Brooks)", "BULLISH", f"BUY — {pa.get('setup', 'N/A')}"))
    elif pa_sig == "SELL":
        votes["SELL"] += 1
        system_opinions.append(("Price Action (Al Brooks)", "BEARISH", f"SELL — {pa.get('setup', 'N/A')}"))
    else:
        votes["HOLD"] += 1
        system_opinions.append(("Price Action (Al Brooks)", "NEUTRAL", f"HOLD — {pa.get('always_in', 'N/A')}"))

    # Determine consensus
    total_systems = 3
    dominant = max(votes, key=votes.get)
    dominant_count = votes[dominant]

    if dominant_count == 3:
        consensus = "STRONG"
        agreement = "ALL AGREE"
    elif dominant_count == 2:
        consensus = "MODERATE"
        agreement = "MAJORITY"
    else:
        consensus = "MIXED"
        agreement = "SPLIT"

    # Overall direction
    if dominant == "BUY":
        direction = "BULLISH"
        action_word = "HOLD / ADD"
    elif dominant == "SELL":
        direction = "BEARISH"
        action_word = "SELL / EXIT"
    else:
        direction = "NEUTRAL"
        action_word = "HOLD / WAIT"

    # Confidence average across systems (weighted)
    conf_vals = [hybrid.get("confidence", 0), triple.get("confidence", 0), pa.get("confidence", 0)]
    avg_confidence = round(sum(c for c in conf_vals if c) / max(1, sum(1 for c in conf_vals if c)), 1)

    # Build plain-language explanation
    plain_lines = []

    if consensus == "STRONG" and direction == "BULLISH":
        plain_lines.append("All 3 analysis systems are saying this stock looks good right now.")
        plain_lines.append("The Bollinger Band indicators, Technical Analysis, and Price Action patterns all point upward.")
        plain_lines.append("This is a strong position — you can hold with confidence or consider adding more if you want.")
    elif consensus == "STRONG" and direction == "BEARISH":
        plain_lines.append("All 3 systems are warning that this stock is weakening.")
        plain_lines.append("Bollinger Bands, Technical indicators, and Price Action all point downward.")
        plain_lines.append("Consider reducing your position or setting a tight stop loss to protect your capital.")
    elif consensus == "MODERATE" and direction == "BULLISH":
        plain_lines.append("2 out of 3 systems are positive on this stock.")
        dissenting = [s[0] for s in system_opinions if s[1] != "BULLISH"]
        if dissenting:
            plain_lines.append(f"Only {dissenting[0]} is not fully aligned, but the majority favors holding.")
        plain_lines.append("You can continue holding. Watch for the dissenting system to also turn positive for more confidence.")
    elif consensus == "MODERATE" and direction == "BEARISH":
        plain_lines.append("2 out of 3 systems suggest caution on this stock.")
        supporting = [s[0] for s in system_opinions if s[1] == "BULLISH"]
        if supporting:
            plain_lines.append(f"Only {supporting[0]} is still positive.")
        plain_lines.append("Consider tightening your stop loss. If the last system also turns negative, it may be time to exit.")
    elif consensus == "MODERATE" and direction == "NEUTRAL":
        plain_lines.append("The systems mostly say to wait and watch.")
        plain_lines.append("There is no strong buying or selling pressure right now.")
        plain_lines.append("Hold your position but keep monitoring for any change in signals.")
    else:
        plain_lines.append("The 3 systems are giving different signals — this means the market is undecided about this stock.")
        plain_lines.append("When systems disagree, it's best to hold your current position and avoid adding more money.")
        plain_lines.append("Wait for at least 2 systems to agree before making any move.")

    # Price Action context (always useful)
    always_in = pa.get("always_in", "N/A")
    if always_in in ("BULLISH", "LONG"):
        plain_lines.append("Price Action shows the 'Always-In' direction is LONG — the trend favors buyers.")
    elif always_in in ("BEARISH", "SHORT"):
        plain_lines.append("Price Action shows 'Always-In' direction is SHORT — sellers are in control currently.")
    else:
        plain_lines.append("Price Action shows the market is sideways — no clear trend.")

    # PA patterns
    pa_patterns = pa.get("patterns", [])
    if pa_patterns:
        plain_lines.append(f"Active price patterns: {', '.join(pa_patterns[:3])}.")

    # [WEIS] Wyckoff phase context
    wyckoff = systems.get("wyckoff")
    if wyckoff and wyckoff.get("phase", "UNKNOWN") != "UNKNOWN":
        wk_phase = wyckoff.get("phase", "UNKNOWN")
        wk_hints = wyckoff.get("hints", [])
        if wk_phase == "ACCUMULATION":
            plain_lines.append("📊 Wyckoff Analysis: Smart money appears to be ACCUMULATING (quietly buying). "
                               "This is often a good sign for holders.")
        elif wk_phase == "DISTRIBUTION":
            plain_lines.append("📊 Wyckoff Analysis: Smart money appears to be DISTRIBUTING (quietly selling). "
                               "Be on alert — the smart money may be exiting.")
        elif wk_phase == "MARKUP":
            wk_sub = wyckoff.get("sub_phase", "")
            if wk_sub == "LATE":
                plain_lines.append("📊 Wyckoff Analysis: The stock is in LATE MARKUP — the uptrend has been "
                                   "running for a while and may be getting tired. Like a marathon runner "
                                   "approaching the finish line. Hold your position but tighten stops and "
                                   "watch for exhaustion signals (shorter rallies, declining volume on up-moves).")
            elif wk_sub == "CONFIRMED":
                plain_lines.append("📊 Wyckoff Analysis: The stock is in CONFIRMED MARKUP — this is the sweet spot. "
                                   "Prices are rising with genuine buying volume behind them. Like a river flowing "
                                   "strongly uphill. Small dips on low volume are buying opportunities.")
            elif wk_sub == "MIDDLE":
                plain_lines.append("📊 Wyckoff Analysis: The stock is in MIDDLE MARKUP — the uptrend is real but "
                                   "not yet fully powered by volume. Buyers have shown strength. Hold your "
                                   "position and watch for volume to confirm the next rally.")
            else:  # EARLY
                plain_lines.append("📊 Wyckoff Analysis: The stock is in EARLY MARKUP — the uptrend is just starting. "
                                   "Like a plane gaining speed on the runway. Promising structure, but volume hasn't "
                                   "fully confirmed the move yet. Watch the next rally's volume closely.")
        elif wk_phase == "MARKDOWN":
            wk_sub = wyckoff.get("sub_phase", "")
            if wk_sub == "LATE":
                plain_lines.append("📊 Wyckoff Analysis: The stock is in LATE MARKDOWN — the decline has been "
                                   "running for a while and may be nearing exhaustion. Watch for panic selling "
                                   "with a big volume spike (Selling Climax) — that often marks the bottom.")
            elif wk_sub == "CONFIRMED":
                plain_lines.append("📊 Wyckoff Analysis: The stock is in CONFIRMED MARKDOWN — supply is overwhelming "
                                   "demand and prices are falling steadily. Any small bounces on low volume are "
                                   "NOT buying opportunities — they're the last exit points before more downside.")
            else:
                plain_lines.append("📊 Wyckoff Analysis: The stock is in MARKDOWN phase — "
                                   "supply is overwhelming demand. Consider protecting capital.")
        # Add the first 2 layman hints from Wyckoff
        for hint in wk_hints[:2]:
            plain_lines.append(f"  → {hint}")

    # [DALTON] Market Profile context
    dalton = systems.get("dalton")
    if dalton and dalton.get("day_type", {}).get("type", "UNKNOWN") != "UNKNOWN":
        dt = dalton["day_type"]["type"]
        ms = dalton.get("market_structure", {}).get("type", "UNKNOWN")
        dp_rating = dalton.get("directional_performance", {}).get("rating", "NEUTRAL")
        dp_dir = dalton.get("directional_performance", {}).get("direction", "NEUTRAL")
        ot = dalton.get("open_type", "UNKNOWN")
        otf = dalton.get("one_timeframing", {}).get("direction", "NONE")
        otf_days = dalton.get("one_timeframing", {}).get("days", 0)

        # Market structure context
        if ms == "TRENDING_UP":
            plain_lines.append("📈 Dalton Market Profile: The market structure is TRENDING UP — "
                               "value areas are consistently moving higher day after day.")
        elif ms == "TRENDING_DOWN":
            plain_lines.append("📉 Dalton Market Profile: The market structure is TRENDING DOWN — "
                               "value areas are moving lower. Sellers are in control.")
        elif ms == "BRACKETING":
            bd = dalton.get("market_structure", {}).get("bracket_days", 0)
            plain_lines.append(f"📊 Dalton Market Profile: Market is BRACKETING (sideways) for "
                               f"{bd} days — value areas are overlapping, no clear direction.")
        elif ms == "TRANSITIONING":
            plain_lines.append("🔄 Dalton Market Profile: Market structure is TRANSITIONING — "
                               "a new trend may be forming. Watch closely.")

        # One-timeframing
        if otf in ("UP", "DOWN") and otf_days >= 2:
            otf_word = "upward" if otf == "UP" else "downward"
            plain_lines.append(f"  → One-timeframing {otf_word} for {otf_days} days — "
                               f"strong directional conviction from institutional traders.")

        # High-probability setups
        hp = dalton.get("high_probability", {})
        if hp.get("three_to_i", {}).get("active"):
            ti_dir = hp["three_to_i"].get("direction", "")
            plain_lines.append(f"  → ⚡ 3-to-I Day setup detected ({ti_dir}) — "
                               "this pattern has 94% historical follow-through probability!")
        if hp.get("neutral_extreme", {}).get("active"):
            ne_dir = hp["neutral_extreme"].get("direction", "")
            plain_lines.append(f"  → ⚡ Neutral-Extreme Day ({ne_dir}) — "
                               "92% probability of follow-through tomorrow!")
        if hp.get("balance_breakout", {}).get("active"):
            bb_dir = hp["balance_breakout"].get("direction", "")
            plain_lines.append(f"  → ⚡ Balance-Area Breakout ({bb_dir}) — "
                               "price broke out of a sideways range with conviction.")

    # Score context
    triple_score = triple.get("score", 0)
    triple_max = triple.get("max_score", 360)
    if triple_score is not None and triple_max:
        pct = abs(triple_score) / triple_max * 100
        if triple_score > 0:
            plain_lines.append(f"The combined conviction score is +{triple_score}/{triple_max} — this is {_score_grade(pct)} bullish.")
        elif triple_score < 0:
            plain_lines.append(f"The combined conviction score is {triple_score}/{triple_max} — this is {_score_grade(pct)} bearish.")

    return {
        "consensus":        consensus,
        "agreement":        agreement,
        "direction":        direction,
        "action_word":      action_word,
        "votes":            votes,
        "system_opinions":  system_opinions,
        "avg_confidence":   avg_confidence,
        "plain_text":       plain_lines,
    }


def _score_grade(pct: float) -> str:
    if pct >= 50:
        return "strongly"
    elif pct >= 25:
        return "moderately"
    else:
        return "mildly"


# ═══════════════════════════════════════════════════════════════
#  MAIN ANALYSIS FUNCTION
# ═══════════════════════════════════════════════════════════════

def analyze_position(position: dict) -> dict:
    """
    Full daily analysis for a single portfolio position.

    Args:
        position: dict from portfolio_db with keys:
            ticker, strategy_code, buy_price, buy_date, quantity, status, ...

    Returns:
        dict with: position, indicators, strategy_signals, recommendation,
                   targets, holding_info, error (if any)
    """
    ticker_raw = position["ticker"]
    strategy_code = position["strategy_code"]
    buy_price = float(position["buy_price"])

    ticker = normalise_ticker(ticker_raw)

    # 1. Load & compute indicators
    df = load_stock_data(ticker, csv_dir=CSV_DIR)
    if df is None or len(df) < 50:
        return {
            "position": position,
            "error": f"Insufficient data for {ticker}",
        }

    df = compute_all_indicators(df)
    last = df.iloc[-1]

    # 2. Run Method I
    sig = analyze_signals(ticker, df)

    # 3. Run Methods II, III, IV
    strats = run_all_strategies(df)

    # 4. Compute targets
    targets = _compute_targets(df, buy_price)

    # 5. Generate recommendation
    rec = _generate_recommendation(strategy_code, sig, strats, df, buy_price)

    # 6. Build strategy signal summary (which strategy was used + current status)
    strategy_map = {"M2": strats[0], "M3": strats[1], "M4": strats[2]}
    buying_strategy_current = None
    if strategy_code in strategy_map:
        sr = strategy_map[strategy_code]
        buying_strategy_current = strategy_result_to_dict(sr)
    elif strategy_code == "M1":
        buying_strategy_current = {
            "code": "M1",
            "name": "Volatility Breakout (Squeeze)",
            "signal_type": "SELL" if sig.sell_signal else ("BUY" if sig.buy_signal else ("HOLD" if sig.hold_signal else "WAIT")),
            "strength":    "STRONG" if sig.confidence >= 70 else ("MODERATE" if sig.confidence >= 40 else "WEAK"),
            "confidence":  sig.confidence,
            "reason":      sig.summary,
        }

    # 7. Current indicator snapshot
    indicators = {
        "price":      _safe(float(last["Close"])),
        "bb_upper":   _safe(float(last["BB_Upper"])),
        "bb_mid":     _safe(float(last["BB_Mid"])),
        "bb_lower":   _safe(float(last["BB_Lower"])),
        "bbw":        _safe(float(last["BBW"]), 6),
        "percent_b":  _safe(float(last["Percent_B"]), 4),
        "mfi":        _safe(float(last["MFI"])),
        "cmf":        _safe(float(last["CMF"]), 4),
        "sar":        _safe(float(last["SAR"])),
        "sar_bull":   bool(last["SAR_Bull"]),
        "squeeze_on": bool(last["Squeeze_ON"]),
        "volume":     int(last["Volume"]),
        "vol_sma50":  int(last["Vol_SMA50"]) if not math.isnan(last["Vol_SMA50"]) else 0,
    }

    # 8. Holding info
    days = _holding_days(position["buy_date"])
    current_price = float(last["Close"])

    # 9. Multi-system analysis (Hybrid, Triple, PA)
    # Use the raw data (before BB indicators) for these engines — they compute their own
    df_raw = load_stock_data(ticker, csv_dir=CSV_DIR)
    multi_sys = _run_multi_system(df_raw, ticker, buy_price) if df_raw is not None and len(df_raw) >= 60 else {}

    return {
        "position":                position,
        "indicators":              indicators,
        "buying_strategy_current": buying_strategy_current,
        "all_strategies":          [strategy_result_to_dict(s) for s in strats],
        "method1_summary": {
            "buy":  sig.buy_signal,
            "sell": sig.sell_signal,
            "hold": sig.hold_signal,
            "wait": sig.wait_signal,
            "confidence":  sig.confidence,
            "phase":       sig.phase,
            "head_fake":   sig.head_fake,
            "exit_sar":    sig.exit_sar_flip,
            "exit_lower":  sig.exit_lower_band_tag,
            "exit_double": sig.exit_double_neg,
        },
        "recommendation":  rec,
        "targets":         targets,
        "multi_system":    multi_sys,
        "holding": {
            "days":          days,
            "buy_price":     buy_price,
            "current_price": _safe(current_price),
            "quantity":      int(position["quantity"]),
            "invested":      _safe(buy_price * int(position["quantity"])),
            "current_value": _safe(current_price * int(position["quantity"])),
            "pnl_amount":    _safe((current_price - buy_price) * int(position["quantity"])),
            "pnl_pct":       _safe((current_price - buy_price) / buy_price * 100 if buy_price else 0),
        },
        "error": None,
    }


def analyze_all_open_positions(positions: list[dict]) -> list[dict]:
    """Run analyze_position on each open position."""
    return [analyze_position(p) for p in positions]
