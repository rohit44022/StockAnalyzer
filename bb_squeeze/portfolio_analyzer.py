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
