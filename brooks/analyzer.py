"""
Brooks System — Top-5 BUY & SELL Scanner
=========================================
Standalone scanner using brooks/engine.py (zero price_action/ imports).
"""

from __future__ import annotations

import sys, os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from brooks.engine import (
    run_brooks_analysis, BrooksResult,
    MIN_BARS, SHORTLIST_SETUPS, SHORTLIST_MIN_CONFIDENCE, SHORTLIST_MIN_RR,
)


# ─────────────────────────────────────────────────────────────────
#  SINGLE-STOCK SCAN
# ─────────────────────────────────────────────────────────────────

def _scan_one(ticker: str, csv_dir: str) -> Optional[BrooksResult]:
    try:
        from bb_squeeze.data_loader import load_stock_data
        df = load_stock_data(ticker, csv_dir=csv_dir, use_live_fallback=False)
        if df is None or len(df) < MIN_BARS:
            return None

        # Stale data check — refuse signals on data older than 3 calendar days
        try:
            last_dt = df.index[-1] if hasattr(df.index, 'date') else pd.to_datetime(df.iloc[-1].get("Date", ""))
            age = (pd.Timestamp.now() - pd.Timestamp(last_dt)).days
            if age > 3:
                return None
        except Exception:
            pass

        r = run_brooks_analysis(df=df, ticker=ticker)
        if r.success:
            from brooks.ml.regime import classify_regime
            ri = classify_regime(df)
            r._regime = ri["regime"]
            r._regime_score = ri["score"]
        return r if r.success else None
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────
#  SELL SHORTLIST (mirrors top_buy_shortlist logic from scanner.py)
# ─────────────────────────────────────────────────────────────────

_SELL_SETUPS = ("CHANNEL_REVERSAL",)

_PLAIN_SETUP_SELL = {
    "BREAKOUT": "it has just broken below the range it was stuck in",
    "PULLBACK": "it is in a downtrend and has bounced back to a level sellers "
                "have defended before",
    "SECOND_ENTRY": "it tried to turn down, failed, and is now trying a second "
                    "time — the attempt Brooks rates highest",
    "FAILED_BREAKOUT": "a break to the upside failed and price has snapped "
                       "back down, trapping the buyers",
    "TRAPPED_TRADERS": "traders who entered the wrong way are now trapped and "
                       "being forced to exit, creating momentum in your direction",
}

_PLAIN_PHASE_SELL = {
    "SPIKE": "It is moving fast in a straight line downward right now.",
    "CHANNEL": "It has been grinding lower in an orderly way.",
    "TIGHT_CHANNEL": "It has been grinding lower very steadily, with shallow bounces.",
    "BROAD_CHANNEL": "It has been falling, but in wide swings.",
    "TRADING_RANGE": "It has been going sideways, so the move may stall at the "
                     "bottom of the range.",
}


def _plain_english_sell(r: BrooksResult) -> str:
    risk = r.stop_loss - r.entry_price
    reward = r.entry_price - r.target_1 if r.target_1 < r.entry_price else 0.0
    risk_pct = risk / r.entry_price * 100 if r.entry_price else 0.0

    lines = [
        f"Short near Rs.{r.entry_price:,.2f}. Get out if it rises to "
        f"Rs.{r.stop_loss:,.2f} — that is the whole loss you are accepting, "
        f"about {risk_pct:.1f}% of what you put in."
    ]
    if reward > 0 and risk > 0:
        lines.append(
            f"First place to take money off the table is Rs.{r.target_1:,.2f}, "
            f"so you are risking Rs.{risk:,.2f} a share to make Rs.{reward:,.2f} "
            f"— {reward / risk:.1f} times what you risk."
        )

    lines.append(
        f"Why this one: {_PLAIN_SETUP_SELL.get(r.setup_type, 'it matched a Brooks setup')}."
    )

    phase = _PLAIN_PHASE_SELL.get(r.trend_phase)
    if phase:
        lines.append(phase)

    lines.append(
        "It also passed the one test Brooks insists on — the likely gain is "
        "bigger than the likely loss — and the engine rates it "
        f"{r.confidence}/100, its high band."
    )
    lines.append(
        "Reality check: shortlists like this won about 59 times in 100 in "
        "testing. The edge is real but thin — it came out ahead because the "
        "winners ran further than the losers, which needs you to take the "
        "whole list, not the one you like, and to honour the stop every time."
    )
    return " ".join(lines)


# ─────────────────────────────────────────────────────────────────
#  PLAIN ENGLISH BUY (duplicated here to keep module self-contained)
# ─────────────────────────────────────────────────────────────────

_PLAIN_SETUP_BUY = {
    "BREAKOUT": "it has just broken out of the range it was stuck in",
    "PULLBACK": "it is in an uptrend and has dipped back to a level buyers "
                "have defended before",
    "SECOND_ENTRY": "it tried to turn up, failed, and is now trying a second "
                    "time — the attempt Brooks rates highest",
    "FAILED_BREAKOUT": "a break to the downside failed and price has snapped "
                       "back up, trapping the sellers",
    "TRAPPED_TRADERS": "traders who shorted are now trapped and being forced "
                       "to cover, creating buying momentum",
}

_PLAIN_PHASE_BUY = {
    "SPIKE": "It is moving fast in a straight line right now.",
    "CHANNEL": "It has been grinding upward in an orderly way.",
    "TIGHT_CHANNEL": "It has been grinding upward very steadily, with shallow dips.",
    "BROAD_CHANNEL": "It has been rising, but in wide swings — expect a bumpy ride.",
    "TRADING_RANGE": "It has been going sideways, so the move may stall at the "
                     "top of the range.",
}


def _plain_english_buy(r: BrooksResult) -> str:
    risk = r.entry_price - r.stop_loss
    reward = r.target_1 - r.entry_price if r.target_1 > r.entry_price else 0.0
    risk_pct = risk / r.entry_price * 100 if r.entry_price else 0.0

    lines = [
        f"Buy near Rs.{r.entry_price:,.2f}. Get out if it drops to "
        f"Rs.{r.stop_loss:,.2f} — that is the whole loss you are accepting, "
        f"about {risk_pct:.1f}% of what you put in."
    ]
    if reward > 0 and risk > 0:
        lines.append(
            f"First place to take money off the table is Rs.{r.target_1:,.2f}, "
            f"so you are risking Rs.{risk:,.2f} a share to make Rs.{reward:,.2f} "
            f"— {reward / risk:.1f} times what you risk."
        )

    lines.append(
        f"Why this one: {_PLAIN_SETUP_BUY.get(r.setup_type, 'it matched a Brooks setup')}."
    )

    phase = _PLAIN_PHASE_BUY.get(r.trend_phase)
    if phase:
        lines.append(phase)

    lines.append(
        "It also passed the one test Brooks insists on — the likely gain is "
        "bigger than the likely loss — and the engine rates it "
        f"{r.confidence}/100, its high band."
    )
    lines.append(
        "Reality check: shortlists like this won about 59 times in 100 in "
        "testing. The edge is real but thin — it came out ahead because the "
        "winners ran further than the losers, which needs you to take the "
        "whole list, not the one you like, and to honour the stop every time."
    )
    return " ".join(lines)


# ─────────────────────────────────────────────────────────────────
#  PICK BUILDERS
# ─────────────────────────────────────────────────────────────────

def _build_management(r: BrooksResult, direction: str, risk: float) -> dict:
    """Brooks Ch.18 position management plan for a specific trade."""
    entry = r.entry_price
    stop = r.stop_loss
    is_buy = direction == "BUY"

    # Scale-out targets (Ch.18: never take profit until ≥2x risk)
    t1 = round(entry + risk * 1.5, 2) if is_buy else round(entry - risk * 1.5, 2)
    t2 = round(entry + risk * 2.0, 2) if is_buy else round(entry - risk * 2.0, 2)
    t3 = round(entry + risk * 3.0, 2) if is_buy else round(entry - risk * 3.0, 2)

    scale_out = [
        {"price": t1, "pct": 25, "action": f"Book 25% at ₹{t1} (1.5x risk) — reduces risk on the position"},
        {"price": t2, "pct": 25, "action": f"Book another 25% at ₹{t2} (2x risk) — now house money"},
        {"price": t3, "pct": 0, "action": f"Trail remaining 50% — let it run toward ₹{t3} (3x risk) or target"},
    ]

    # Trailing stop rules depend on trend phase
    if r.trend_phase == "SPIKE":
        trail_rule = "Do NOT move stop during a spike. Spikes look scary but produce the best R:R. Wait for the spike to end (first pullback bar), then raise stop to below that pullback's low."
    elif r.trend_phase in ("CHANNEL", "TIGHT_CHANNEL"):
        trail_rule = "After each new swing high, raise stop to 1 tick below the most recent higher low. In a tight channel, pullbacks are shallow — don't tighten to breakeven until you see a new swing high above your entry."
    elif r.trend_phase == "BROAD_CHANNEL":
        trail_rule = "Trail stop below each swing low. Pullbacks will be deeper (50-60% of each leg), so use wider stops. If the pullback exceeds the prior swing low, the channel may be breaking — exit the remaining position."
    else:
        trail_rule = "Trail stop below the most recent swing low. In a trading range, expect the first breakout to be tested — don't panic if price pulls back to the breakout level."

    # Breakeven rule (Ch.18: don't tighten too early)
    be_price = round(entry + risk * 0.5, 2) if is_buy else round(entry - risk * 0.5, 2)
    breakeven_rule = f"Move stop to breakeven (₹{entry}) ONLY after price reaches ₹{be_price} and makes a new swing high. Moving to breakeven too early gets you stopped out by normal pullbacks — trends routinely retest the entry price before continuing."

    # Exit signals (Ch.18-19)
    exit_signals = []
    exit_signals.append("Three consecutive climax bars (unusually large trend bars) — exhaustion, expect 10-bar two-legged correction")
    exit_signals.append("Unusually large trend bar after 20+ bars of trend — often the final exhaustive push")
    if is_buy:
        exit_signals.append("Always-in direction flips from LONG to SHORT — the market structure has changed")
        exit_signals.append("Price breaks below the bull trend line AND fails to make a new high on the retest")
        exit_signals.append("A strong bear bar closes below the 20-day EMA with follow-through")
    else:
        exit_signals.append("Always-in direction flips from SHORT to LONG")
        exit_signals.append("Price breaks above the bear trend line AND fails to make a new low on retest")
        exit_signals.append("A strong bull bar closes above the 20-day EMA with follow-through")

    # Warning signs based on current data
    warnings = []
    if r.selling_pressure > r.buying_pressure + 10:
        warnings.append(f"Selling pressure ({r.selling_pressure:.0f}%) exceeds buying pressure ({r.buying_pressure:.0f}%) — bears are gaining control")
    if r.signs_of_strength_score <= 5:
        warnings.append(f"Signs of strength only {r.signs_of_strength_score}/{r.signs_of_strength_total} — trend conviction is weak")
    if r.recent_climax:
        warnings.append("Recent climax detected — the move may be exhausting itself, tighten stops")
    if r.is_final_flag:
        warnings.append("Final flag pattern — this may be the last push before a correction, take partial profits early")
    if r.ema_gap_bar_count >= 15:
        warnings.append(f"Price has been above EMA for {r.ema_gap_bar_count} bars — extended moves like this often snap back to the EMA")
    if r.reversal_checklist_score >= 5:
        warnings.append(f"Reversal checklist at {r.reversal_checklist_score}/10 — multiple reversal conditions are forming")

    # Max hold days by setup type
    max_hold = {"BREAKOUT": 30, "PULLBACK": 20, "SECOND_ENTRY": 20,
                "BREAKOUT_PULLBACK": 25, "REVERSAL": 15}.get(r.setup_type, 20)

    return {
        "scale_out": scale_out,
        "trailing_stop_rule": trail_rule,
        "breakeven_rule": breakeven_rule,
        "exit_signals": exit_signals,
        "warnings": warnings,
        "max_hold_days": max_hold,
    }


def _result_to_pick(r: BrooksResult, rank: int, direction: str) -> dict:
    """Build a detailed pick dict from a BrooksResult."""
    if direction == "BUY":
        risk = r.entry_price - r.stop_loss
        explanation = _plain_english_buy(r)
    else:
        risk = r.stop_loss - r.entry_price
        explanation = _plain_english_sell(r)

    risk_pct = risk / r.entry_price * 100 if r.entry_price else 0.0

    return {
        "rank": rank,
        "ticker": r.ticker,
        "direction": direction,
        "setup": r.setup_type,
        "confidence": r.confidence,
        "pa_score": r.pa_score,
        "pa_verdict": r.pa_verdict,
        "entry": round(r.entry_price, 2),
        "stop": round(r.stop_loss, 2),
        "target_1": round(r.target_1, 2),
        "target_2": round(r.target_2, 2),
        "risk_pct": round(risk_pct, 2),
        "risk_reward": round(r.risk_reward, 2),
        "current_price": round(r.current_price, 2),
        "always_in": r.always_in,
        "trend_direction": r.trend_direction,
        "trend_phase": r.trend_phase,
        "trend_strength": round(r.trend_strength, 1),
        "buying_pressure": round(r.buying_pressure, 1),
        "selling_pressure": round(r.selling_pressure, 1),
        "ema20": round(r.ema20, 2),
        "price_vs_ema": r.price_vs_ema,
        "ema_gap_bars": r.ema_gap_bar_count,
        "in_spike": r.in_spike,
        "spike_direction": r.spike_direction,
        "recent_climax": r.recent_climax,
        "last_bar_type": r.last_bar_type,
        "last_bar_description": r.last_bar_description,
        "active_patterns": r.active_patterns,
        "last_h": r.last_hl_bull,
        "last_l": r.last_hl_bear,
        "breakout_mode": r.breakout_mode,
        "in_breakout": r.in_breakout,
        "two_leg_complete": r.two_leg_complete,
        "measured_move_target": round(r.measured_move_target, 2),
        "equation_verdict": r.equation_verdict,
        "traders_equation": round(r.traders_equation, 2),
        "reasons": r.reasons,
        "al_brooks_context": r.al_brooks_context,
        "explanation": explanation,
        "score_details": r.score_details,
        # v3 fields
        "atr": round(r.atr, 2),
        "volume_ratio": r.volume_ratio,
        "volume_spike": r.volume_spike,
        "trend_line_broken": r.trend_line_broken,
        "signs_of_strength": r.signs_of_strength_score,
        "signs_of_strength_total": r.signs_of_strength_total,
        "reversal_checklist": r.reversal_checklist_score,
        "is_final_flag": r.is_final_flag,
        "is_triangle": r.is_triangle,
        "is_trapped_trade": r.is_trapped_trade,
        "sr_proximity": r.sr_proximity,
        "round_magnet": r.round_magnet_distance,
        "reasons_count": r.reasons_count,
        "quality_score": r.quality_score,
        "outside_bar": r.outside_bar_reversal,
        "ioi_pattern": r.ioi_pattern,
        "regime": getattr(r, '_regime', ''),
        "regime_score": getattr(r, '_regime_score', 0),
        "management": _build_management(r, direction, risk),
    }


# ─────────────────────────────────────────────────────────────────
#  AI/ML ENRICHMENT — replaces template text with data-driven narrative
# ─────────────────────────────────────────────────────────────────

def _build_bb_indicators(ticker: str) -> dict | None:
    """Compute full BB indicator set from CSV for ML model bridge."""
    import numpy as np
    try:
        from bb_squeeze.data_loader import load_stock_data
        from bb_squeeze.config import CSV_DIR
        df = load_stock_data(ticker, csv_dir=CSV_DIR, use_live_fallback=False)
        if df is None or len(df) < 60:
            return None

        close = df["Close"].values.astype(float)
        high = df["High"].values.astype(float)
        low = df["Low"].values.astype(float)
        vol = df["Volume"].values.astype(float)
        n = len(close)

        # SMA20, Bollinger Bands
        sma20 = float(np.mean(close[-20:]))
        std20 = float(np.std(close[-20:], ddof=1))
        upper = sma20 + 2 * std20
        lower = sma20 - 2 * std20
        bbw = (upper - lower) / sma20 if sma20 > 0 else 0

        # RSI 14
        delta = np.diff(close[-15:])
        gain = np.where(delta > 0, delta, 0).mean()
        loss = np.where(delta < 0, -delta, 0).mean()
        rs = gain / max(loss, 1e-10)
        rsi = 100 - 100 / (1 + rs)

        # ATR 14
        tr = np.maximum(high[-14:] - low[-14:],
                        np.maximum(np.abs(high[-14:] - close[-15:-1]),
                                   np.abs(low[-14:] - close[-15:-1])))
        atr = float(tr.mean())

        # Volume
        volume = float(vol[-1])
        vol_avg = float(vol[-20:].mean())

        # SMA20 slope (5-day)
        sma20_5ago = float(np.mean(close[-25:-5])) if n >= 25 else sma20
        sma20_slope = (sma20 - sma20_5ago) / max(sma20_5ago, 1e-10) * 100

        # RSI slope (compute RSI 5 bars ago)
        if n >= 20:
            d2 = np.diff(close[-20:-5])
            g2 = np.where(d2 > 0, d2, 0).mean()
            l2 = np.where(d2 < 0, -d2, 0).mean()
            rsi_5ago = 100 - 100 / (1 + g2 / max(l2, 1e-10))
            rsi_slope = rsi - rsi_5ago
        else:
            rsi_slope = 0

        # BBW percentile (60-day)
        if n >= 60:
            bbws = []
            for i in range(60):
                idx = n - 60 + i
                s = float(np.mean(close[max(0, idx - 19):idx + 1]))
                sd = float(np.std(close[max(0, idx - 19):idx + 1], ddof=1))
                bbws.append((4 * sd / s) if s > 0 else 0)
            bbw_pct = float(np.searchsorted(np.sort(bbws), bbw) / len(bbws))
        else:
            bbw_pct = 0.5

        # Volume trend (5-day)
        vol_trend = 0
        if n >= 25:
            vol_avg_5ago = float(vol[-25:-5].mean())
            vol_trend = (vol_avg - vol_avg_5ago) / max(vol_avg_5ago, 1e-10)

        # Momentum
        mom_10 = (close[-1] - close[-11]) / close[-11] * 100 if n >= 11 else 0
        mom_20 = (close[-1] - close[-21]) / close[-21] * 100 if n >= 21 else 0

        # ATR percentile (60-day)
        if n >= 74:
            atrs = []
            for i in range(60):
                idx = n - 60 + i
                tr_i = np.maximum(high[idx - 13:idx + 1] - low[idx - 13:idx + 1],
                                  np.maximum(np.abs(high[idx - 13:idx + 1] - close[idx - 14:idx]),
                                             np.abs(low[idx - 13:idx + 1] - close[idx - 14:idx])))
                atrs.append(float(tr_i.mean()))
            atr_pct = float(np.searchsorted(np.sort(atrs), atr) / len(atrs))
        else:
            atr_pct = 0.5

        return {
            "bbw": round(bbw, 6), "rsi": round(rsi, 2), "rsi14": round(rsi, 2),
            "atr": round(atr, 2), "atr14": round(atr, 2),
            "sma20": round(sma20, 2), "sma_20": round(sma20, 2),
            "upper_band": round(upper, 2), "lower_band": round(lower, 2),
            "volume": volume, "vol_avg": vol_avg, "avg_volume": vol_avg,
            "sma20_slope": round(sma20_slope, 4),
            "rsi_slope": round(rsi_slope, 2),
            "bbw_percentile": round(bbw_pct, 4),
            "vol_trend": round(vol_trend, 4),
            "momentum_10d": round(mom_10, 4),
            "momentum_20d": round(mom_20, 4),
            "atr_percentile": round(atr_pct, 4),
            "price": float(close[-1]),
        }
    except Exception:
        return None


def _enrich_picks_with_ai(picks: list) -> None:
    """Bridge Brooks picks into the full AI/ML pipeline."""
    import logging
    log = logging.getLogger("brooks.analyzer")

    # ── 1. Market regime (once for all picks) ──
    regime = {}
    regime_label = "UNKNOWN"
    try:
        from ai_ml.regime_filter import get_market_regime
        regime = get_market_regime()
        regime_label = regime.get("regime", "UNKNOWN")
    except Exception as e:
        log.warning("Regime filter unavailable: %s", e)

    # ── 2. Build indicator bridge for each pick ──
    for p in picks:
        ind = _build_bb_indicators(p["ticker"])
        if ind:
            p["_brooks_indicators"] = ind
        else:
            p["_brooks_indicators"] = {}

    # ── 3. Brooks ML — informational only, does NOT gate picks ──
    # XGB AUC 0.52 / LGB R² -0.007 = no predictive power.
    # Kept for display so the user can watch if a retrained model improves.
    try:
        from brooks.ml.scorer import score_picks as brooks_ml_score
        brooks_ml_score(picks)
        log.info("Brooks ML scored %d picks (informational only)", len(picks))
    except Exception as e:
        log.debug("Brooks ML scoring unavailable: %s", e)

    # ── 6. Exit intelligence per pick ──
    for p in picks:
        ind = p.get("bb_data", {}).get("indicators", {})
        indicators = {
            "volume": ind.get("volume", 1.0),
            "vol_avg": ind.get("vol_avg", 1.0),
            "sma20": ind.get("sma20", p.get("ema20", 0)),
            "rsi": ind.get("rsi"),
            "bbw": ind.get("bbw"),
        }

        exit_data = {}
        try:
            from ai_ml.exit_intelligence import (
                _score_exit_urgency, _assess_momentum,
                _urgency_label, _build_explanation,
            )
            score, signals = _score_exit_urgency(indicators, p.get("current_price"))
            momentum = _assess_momentum(indicators)
            label = _urgency_label(score)
            exit_text = _build_explanation(label, momentum, signals)
            exit_data = {
                "urgency_score": score,
                "urgency_label": label,
                "momentum_health": momentum,
                "signals": signals,
                "exit_explanation": exit_text,
            }
        except Exception as e:
            log.warning("Exit intelligence failed for %s: %s", p["ticker"], e)

        # ── 7. Regenerate texts with all AI/ML data ──
        p["exit_intelligence"] = exit_data
        p["market_regime"] = regime

        p["explanation"] = _enriched_explanation(p, regime_label, exit_data)

        mgmt = p.get("management", {})
        mgmt["trailing_stop_rule"] = _enriched_trail_rule(p, regime_label, exit_data)
        mgmt["exit_intelligence_text"] = exit_data.get("exit_explanation", "")
        mgmt["momentum_health"] = exit_data.get("momentum_health", "UNKNOWN")
        mgmt["urgency_label"] = exit_data.get("urgency_label", "HOLD")
        mgmt["regime_context"] = _regime_management_note(regime_label, p)
        p["management"] = mgmt

        p["chart_narrative"] = _build_chart_narrative(p, regime_label, exit_data)

    # Clean internal fields
    for p in picks:
        p.pop("_brooks_indicators", None)
        p.pop("bb_data", None)


def _enriched_explanation(p: dict, regime: str, exit_data: dict) -> str:
    """Generate rich, color-coded HTML 'Why this trade' explanation."""
    ticker = p["ticker"]
    entry = p["entry"]
    stop = p["stop"]
    target = p["target_1"]
    risk_pct = p["risk_pct"]
    rr = p["risk_reward"]
    setup = p.get("setup", "UNKNOWN")
    phase = p.get("trend_phase", "UNKNOWN")
    ai = p.get("always_in", "FLAT")
    strength = p.get("trend_strength", 0)
    bp = p.get("buying_pressure", 50)
    sp = p.get("selling_pressure", 50)
    ema20 = p.get("ema20", 0)
    current = p.get("current_price", 0)
    conf = p.get("confidence", 0)
    sos = p.get("signs_of_strength", 0)
    sos_total = p.get("signs_of_strength_total", 18)
    vol_ratio = p.get("volume_ratio", 1.0)
    quality = p.get("quality_score", 0)
    momentum = exit_data.get("momentum_health", "UNKNOWN")
    patterns = p.get("active_patterns", [])
    eq = p.get("equation_verdict", "EDGE")
    mmt = p.get("measured_move_target", 0)

    B = '<span class="c-bull">'   # bull
    R = '<span class="c-bear">'   # bear
    A = '<span class="c-amber">'  # amber
    P = '<span class="c-price">'  # price
    X = '<span class="c-accent">' # accent
    E = '</span>'
    lines = []

    # ── Setup ──
    setup_map = {
        "BREAKOUT": f"{B}{ticker}{E} just {B}broke out{E} of a consolidation pattern",
        "PULLBACK": f"{B}{ticker}{E} is {A}pulling back{E} within an established uptrend",
        "SECOND_ENTRY": f"{B}{ticker}{E} is offering a {B}second entry{E} — the first pullback held, this is the safer re-entry",
        "BREAKOUT_PULLBACK": f"{B}{ticker}{E} {B}broke out{E} and is now {A}pulling back{E} to test the breakout level",
        "REVERSAL": f"{A}{ticker}{E} is showing early {A}reversal signals{E} after a decline",
        "FAILED_BREAKOUT": f"{B}{ticker}{E} had a {R}failed breakout{E} to the downside — {B}bears are trapped{E}, price should reverse up",
        "TRAPPED_TRADERS": f"{B}{ticker}{E} has {B}trapped sellers{E} — they'll need to buy back, pushing price higher",
    }
    lines.append(setup_map.get(setup, f"{X}{ticker}{E} has a {setup.lower().replace('_', ' ')} setup") + ".")

    # ── Trend phase ──
    phase_map = {
        "SPIKE": f"The stock is in a {B}spike phase{E} — strong momentum with almost no pullbacks. This is the {B}most powerful{E} phase of a trend.",
        "CHANNEL": f"It's trending in a {B}steady channel{E} with orderly pullbacks. Trend strength: {B}{strength:.0f}%{E}.",
        "TIGHT_CHANNEL": f"The trend is in a {B}tight channel{E} — very strong, barely any pullbacks. This is a {B}momentum trade{E}.",
        "BROAD_CHANNEL": f"The trend is in a {A}broad channel{E} with wide swings. Expect {A}larger pullbacks{E} but also larger targets.",
        "TRADING_RANGE": f"The stock is in a {A}trading range{E}. This trade bets on the range resolving in the direction of the always-in.",
    }
    t = phase_map.get(phase)
    if t:
        lines.append(t)

    # ── Always-in ──
    if ai == "LONG":
        lines.append(f"Always-in direction is {B}LONG{E} — institutions are positioned for higher prices.")
    elif ai == "SHORT":
        lines.append(f"Always-in direction is {R}SHORT{E} — this is a {R}counter-trend{E} trade, extra risk.")

    # ── Pressure ──
    if bp > sp + 15:
        lines.append(f"{B}Buyers dominate{E}: {B}{bp:.0f}%{E} buying vs {sp:.0f}% selling.")
    elif sp > bp + 15:
        lines.append(f"{R}Sellers are active{E} ({R}{sp:.0f}%{E} vs {bp:.0f}%) — watch for the trade to stall.")
    else:
        lines.append(f"Pressure balanced ({A}{bp:.0f}%{E} vs {A}{sp:.0f}%{E}) — conviction is moderate.")

    # ── EMA position ──
    if current and ema20:
        ema_dist = (current - ema20) / ema20 * 100
        if ema_dist > 5:
            lines.append(f"Price is {A}{ema_dist:.1f}%{E} above the 20-day EMA — strong but {A}potentially extended{E}.")
        elif ema_dist > 0:
            lines.append(f"Price is {B}{ema_dist:.1f}%{E} above the 20-day EMA — {B}healthy bullish positioning{E}.")
        elif ema_dist > -3:
            lines.append(f"Price is near the 20-day EMA ({A}{ema_dist:.1f}%{E}) — at a {A}key support level{E} for pullback entries.")
        else:
            lines.append(f"Price is {R}{abs(ema_dist):.1f}%{E} below the 20-day EMA — a {R}deeper pullback{E} trade.")

    # ── Volume ──
    if vol_ratio > 2.0:
        lines.append(f"Volume {B}surging{E} at {B}{vol_ratio:.1f}x{E} average — strong participation confirms the move.")
    elif vol_ratio > 1.3:
        lines.append(f"Volume {B}{vol_ratio:.1f}x{E} average — above-normal interest supports the setup.")
    elif vol_ratio < 0.6:
        lines.append(f"Volume {R}low{E} at {R}{vol_ratio:.1f}x{E} — thin participation, be cautious.")

    # ── Signs of strength ──
    if sos >= 12:
        lines.append(f"Signs of strength: {B}{sos}/{sos_total}{E} — {B}very strong{E} structural support.")
    elif sos >= 8:
        lines.append(f"Signs of strength: {B}{sos}/{sos_total}{E} — solid structural support.")
    elif sos >= 4:
        lines.append(f"Signs of strength: {A}{sos}/{sos_total}{E} — moderate support.")

    # ── Brooks ML models ──
    ml_conf = p.get("bml_confidence")
    ml_verdict = p.get("bml_verdict", "")
    ml_down = p.get("bml_downside")
    seq_conf = p.get("bml_seq_confidence")
    seq_verdict = p.get("bml_seq_verdict", "")
    seq_agree = p.get("bml_seq_agreement", "")
    conv = p.get("bml_conviction")
    conv_label = p.get("bml_conviction_label", "")
    conv_ci = p.get("bml_conviction_ci")

    if ml_conf is not None:
        mc = B if ml_verdict == "BML_PASS" else R
        pct = f"{ml_conf * 100:.0f}%"
        verd = "PASS" if ml_verdict == "BML_PASS" else "CAUTION"
        lines.append(f"XGBoost win probability: {mc}{pct}{E} ({mc}{verd}{E}).")
        ml_expl = p.get("bml_explanation")
        if ml_expl:
            drivers = ", ".join(f"{d['feature']} ({d['direction']})" for d in ml_expl[:3])
            lines.append(f"Top ML drivers: {X}{drivers}{E}.")

    if ml_down is not None:
        dc = B if ml_down > -2 else A if ml_down > -5 else R
        lines.append(f"Downside risk model: {dc}{ml_down:.1f}%{E} expected worst-case loss.")

    if seq_conf is not None:
        sc = B if seq_verdict == "BSEQ_PASS" else R
        lines.append(f"LSTM sequence score: {sc}{seq_conf * 100:.0f}%{E} ({sc}{'PASS' if seq_verdict == 'BSEQ_PASS' else 'CAUTION'}{E}).")
        if seq_agree == "BOTH_AGREE":
            lines.append(f"{B}Both XGBoost and LSTM agree{E} — higher-conviction setup.")
        elif seq_agree == "DISAGREE":
            lines.append(f"{A}XGBoost and LSTM disagree{E} — mixed signals from ML, size down.")

    if conv is not None:
        cc = B if conv >= 60 else A if conv >= 35 else R
        ci_text = ""
        if conv_ci:
            ci_text = f" (range {A}{conv_ci[0]:.0f}–{conv_ci[1]:.0f}{E})"
        lines.append(f"LightGBM conviction: {cc}{conv:.0f}/100{E} {cc}{conv_label}{E}{ci_text}.")

    # ── AI momentum ──
    mom_html = {
        "STRONG": f"AI momentum: {B}STRONG{E} — buyers in full control, the move has energy.",
        "HEALTHY": f"AI momentum: {B}HEALTHY{E} — good energy behind the setup.",
        "FADING": f"AI momentum: {A}FADING{E} — move is losing steam, {A}consider smaller position{E}.",
        "WEAK": f"AI momentum: {R}WEAK{E} — {R}exhausted{E}, higher-risk entry.",
    }
    if momentum in mom_html:
        lines.append(mom_html[momentum])

    # ── Market regime ──
    regime_html = {
        "BULL": f"Market regime: {B}BULL{E} — the broad market {B}supports{E} long positions.",
        "BEAR": f"Market regime: {R}BEAR{E} — {R}swimming against the tide{E}. The stock's own structure must overcome the headwind.",
        "SIDEWAYS": f"Market regime: {A}SIDEWAYS{E} — no strong directional bias from the broad market.",
    }
    if regime in regime_html:
        lines.append(regime_html[regime])

    # ── Trade mechanics ──
    lines.append(
        f"Trade plan: Buy at {P}₹{entry:,.2f}{E}, stop at {R}₹{stop:,.2f}{E} "
        f"({A}{risk_pct:.1f}%{E} risk), target {B}₹{target:,.2f}{E} — "
        f"{B}{rr:.1f}x{E} reward for the risk."
    )
    if mmt and mmt > 0 and abs(mmt - target) > 1:
        lines.append(f"Measured move projects to {B}₹{mmt:,.2f}{E} — a secondary target from the prior swing's length.")

    # ── Confidence ──
    conf_c = B if conf >= 75 else A if conf >= 50 else R
    qual_c = B if quality >= 80 else A if quality >= 60 else R
    eq_c = B if eq == "STRONG_EDGE" else B if eq == "EDGE" else R
    lines.append(
        f"Engine confidence: {conf_c}{conf}/100{E} (quality {qual_c}{quality}/100{E}). "
        f"Trader's equation: {eq_c}{eq}{E}."
    )

    # ── Patterns ──
    if patterns:
        lines.append(f"Active patterns: {X}{', '.join(patterns)}{E}.")

    body = "".join(f'<div class="e-line">{l}</div>' for l in lines if l)

    # ── Reality check ──
    reality = (
        "Reality check: shortlists like this won about 59 times in 100 in testing. "
        "The edge is real but thin — it came out ahead because the winners ran "
        "further than the losers, which needs you to take the whole list, "
        "not the one you like, and to honour the stop every time."
    )

    return f'<div class="enriched-block">{body}<div class="e-reality">{reality}</div></div>'


def _enriched_trail_rule(p: dict, regime: str, exit_data: dict) -> str:
    """Generate color-coded HTML trailing stop rule with AI/ML context."""
    phase = p.get("trend_phase", "UNKNOWN")
    momentum = exit_data.get("momentum_health", "UNKNOWN")
    urgency = exit_data.get("urgency_label", "HOLD")
    entry = p["entry"]
    stop = p["stop"]
    risk = abs(entry - stop)

    B = '<span class="c-bull">'
    R = '<span class="c-bear">'
    A = '<span class="c-amber">'
    P = '<span class="c-price">'
    E = '</span>'

    parts = []

    if phase == "SPIKE":
        parts.append(
            f'<div class="e-line">{B}SPIKE PHASE{E}: Do {R}not touch{E} your stop during the spike. '
            f'Spikes look terrifying but produce the {B}best R:R{E}. Wait for the first pullback bar '
            f'(trades below prior bar\'s low), then raise stop to 1 tick below that pullback\'s low.</div>')
    elif phase in ("CHANNEL", "TIGHT_CHANNEL"):
        parts.append(
            f'<div class="e-line">{B}CHANNEL PHASE{E}: After each new swing high, raise stop to 1 tick below '
            f'the most recent higher low. Don\'t move to breakeven until price makes a new swing high above '
            f'{P}₹{entry + risk * 0.5:,.2f}{E}.</div>')
    elif phase == "BROAD_CHANNEL":
        parts.append(
            f'<div class="e-line">{A}BROAD CHANNEL{E}: Trail stop below each swing low. Expect {A}deeper pullbacks{E} '
            f'(50-60% of each leg). If pullback exceeds prior swing low, the channel may be breaking — '
            f'{R}exit remaining position{E}.</div>')
    else:
        parts.append(
            f'<div class="e-line">{A}TRADING RANGE{E}: Trail stop below the most recent swing low. Expect the '
            f'breakout to be tested — don\'t panic if price pulls back to the breakout level.</div>')

    if momentum == "FADING":
        parts.append(
            f'<div class="e-trail-warn">⚠ AI: {A}FADING{E} momentum — tighten faster. Raise stop to '
            f'{P}₹{entry + risk * 0.3:,.2f}{E} on any new swing high.</div>')
    elif momentum == "WEAK":
        parts.append(
            f'<div class="e-trail-danger">⚠ AI: {R}WEAK{E} momentum — move stop to breakeven '
            f'({P}₹{entry:,.2f}{E}) ASAP and consider {R}partial profits early{E}.</div>')
    elif momentum == "STRONG":
        parts.append(
            f'<div class="e-line">AI: {B}STRONG{E} momentum — give the trade room to run. '
            f'Wide stops capture the full move.</div>')

    if urgency == "TIGHTEN_STOP":
        parts.append(
            f'<div class="e-trail-warn">⚠ {A}AI EXIT ADVISORY{E}: Multiple warning signs. '
            f'Move stop to breakeven or take {A}50% partial profits{E} now.</div>')
    elif urgency == "CONSIDER_EXIT":
        parts.append(
            f'<div class="e-trail-danger">🚨 {R}AI EXIT ADVISORY{E}: Structural damage detected. '
            f'Consider {R}exiting most or all{E} at market price.</div>')

    if regime == "BEAR":
        parts.append(
            f'<div class="e-regime-note">{R}BEAR{E} market regime: be quicker to take profits. '
            f'Trail tighter — raise stop after each {A}1x risk{E} move.</div>')
    elif regime == "BULL":
        parts.append(
            f'<div class="e-regime-note">{B}BULL{E} regime supports letting winners run. '
            f'Trail at normal pace using swing structure.</div>')

    return f'<div class="e-trail-rule">{"".join(parts)}</div>'


def _regime_management_note(regime: str, p: dict) -> str:
    """Market regime context for position management."""
    notes = {
        "BULL": "Broad market is in a BULL regime — conditions favour holding longer and trailing wider. Full position size is appropriate.",
        "BEAR": "Broad market is in a BEAR regime — headwinds for long positions. Consider 50-75% of normal position size and take profits earlier than usual.",
        "SIDEWAYS": "Market is SIDEWAYS — no strong tailwind or headwind. Normal position sizing, standard trailing rules.",
    }
    return notes.get(regime, "Market regime not available — use standard rules.")


def _build_chart_narrative(p: dict, regime: str, exit_data: dict) -> str:
    """Server-side color-coded HTML chart narrative."""
    entry = p["entry"]
    stop = p["stop"]
    target = p["target_1"]
    rr = p["risk_reward"]
    risk_pct = p["risk_pct"]
    current = p.get("current_price", 0)
    ema20 = p.get("ema20", 0)
    phase = p.get("trend_phase", "UNKNOWN")
    ai = p.get("always_in", "FLAT")
    momentum = exit_data.get("momentum_health", "UNKNOWN")
    urgency = exit_data.get("urgency_label", "HOLD")
    patterns = p.get("active_patterns", [])

    B = '<span class="c-bull">'
    R = '<span class="c-bear">'
    A = '<span class="c-amber">'
    P = '<span class="c-price">'
    X = '<span class="c-accent">'
    E = '</span>'

    parts = []

    # Price vs EMA
    if current and ema20 and ema20 > 0:
        ema_dist = (current - ema20) / ema20 * 100
        if ema_dist > 0:
            parts.append(f"Price at {P}₹{current:,.2f}{E} is {B}{ema_dist:.1f}%{E} above the 20-day EMA (amber line) — {B}bullish{E}.")
        else:
            parts.append(f"Price at {P}₹{current:,.2f}{E} is {R}{abs(ema_dist):.1f}%{E} below the 20-day EMA (amber line) — {A}pulling back{E}.")

    # Phase
    phase_desc = {
        "SPIKE": f"Chart shows a {B}spike phase{E} — large consecutive bars with almost no overlap. {B}Strongest phase{E}.",
        "CHANNEL": f"Chart shows a {B}channel trend{E} — orderly higher highs/lows. Green trend line connects the lows.",
        "TIGHT_CHANNEL": f"Chart shows a {B}tight channel{E} — almost no pullbacks, bars closely stacked. {B}Very strong{E}.",
        "BROAD_CHANNEL": f"Chart shows a {A}broad channel{E} — wide swings between green support and blue resistance.",
        "TRADING_RANGE": f"Chart shows a {A}trading range{E} — price bouncing between amber S/R zones. Betting on breakout.",
    }
    d = phase_desc.get(phase)
    if d:
        parts.append(d)

    # Always-in
    if ai == "LONG":
        parts.append(f"Swing markers show higher lows — always-in is {B}LONG{E}.")
    elif ai == "SHORT":
        parts.append(f"Swing markers show lower highs — always-in is {R}SHORT{E}. Counter-trend entry.")

    # Trade plan
    parts.append(
        f"On chart: {X}blue line{E} = entry ({P}₹{entry:,.2f}{E}), "
        f"{R}red line{E} = stop ({R}₹{stop:,.2f}{E}, {A}{risk_pct:.1f}%{E} risk), "
        f"{B}green line{E} = target ({B}₹{target:,.2f}{E}, {B}{rr:.1f}x{E} reward)."
    )

    # Momentum + regime
    mom_c = B if momentum in ("STRONG", "HEALTHY") else A if momentum == "FADING" else R
    mom_text = {"STRONG": "strong", "HEALTHY": "healthy", "FADING": "fading", "WEAK": "weak"}.get(momentum)
    reg_c = B if regime == "BULL" else R if regime == "BEAR" else A
    if mom_text:
        parts.append(f"AI momentum: {mom_c}{mom_text}{E}. Market: {reg_c}{regime}{E}.")

    # Urgency
    if urgency == "TIGHTEN_STOP":
        parts.append(f"⚠ {A}AI advisory{E}: warning signs — consider tightening stop.")
    elif urgency == "CONSIDER_EXIT":
        parts.append(f"🚨 {R}AI advisory{E}: structural damage — consider exiting.")

    # Patterns
    if patterns:
        parts.append(f"Active patterns: {X}{', '.join(patterns)}{E}.")

    return " ".join(pt for pt in parts if pt)


# ─────────────────────────────────────────────────────────────────
#  MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────

def scan_and_rank(
    csv_dir: str,
    max_workers: int = 16,
    limit: int = 5,
) -> dict:
    """Scan all stocks and return top-5 BUY and top-5 SELL picks.

    Returns
    -------
    dict with keys: buy_picks, sell_picks, stats
    """
    from bb_squeeze.data_loader import get_all_tickers_from_csv

    tickers = get_all_tickers_from_csv(csv_dir)

    all_results: List[BrooksResult] = []
    scanned = 0
    errors = 0

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_scan_one, t, csv_dir): t for t in tickers}
        for fut in as_completed(futures, timeout=max(120, len(futures) * 2)):
            try:
                r = fut.result(timeout=30)
                scanned += 1
                if r is not None:
                    all_results.append(r)
                else:
                    errors += 1
            except Exception:
                errors += 1
                scanned += 1

    # ── Top BUY picks ──
    # ATR-relative stop filter: stop must be within 3x ATR (not fixed 8%)
    # so volatile small-caps with legitimate wide stops aren't silently dropped
    buy_candidates = [
        r for r in all_results
        if r.signal_type == "BUY"
        and r.equation_verdict == "EDGE"
        and r.setup_type in SHORTLIST_SETUPS
        and r.always_in == "LONG"
        and r.confidence >= SHORTLIST_MIN_CONFIDENCE
        and r.risk_reward >= SHORTLIST_MIN_RR
        and r.entry_price > r.stop_loss > 0
        and getattr(r, '_regime', '') not in ("BEAR", "CHOPPY", "TRENDING_BEAR", "MILD_TREND")
        and (r.atr <= 0 or abs(r.entry_price - r.stop_loss) <= r.atr * 3)
        and r.trend_phase != "CHANNEL"
        and getattr(r, 'volume_ratio', 0) >= 1.0
        and not r.warnings
    ]
    # Rank by equation edge (net of costs), not just confidence
    buy_candidates.sort(key=lambda r: (r.traders_equation, r.confidence), reverse=True)
    buy_picks = [
        _result_to_pick(r, i, "BUY")
        for i, r in enumerate(buy_candidates[:limit], 1)
    ]

    # ── Top SELL picks (symmetric with BUY) ──
    sell_candidates = [
        r for r in all_results
        if r.signal_type == "SELL"
        and r.equation_verdict == "EDGE"
        and r.setup_type in _SELL_SETUPS
        and r.always_in == "SHORT"
        and r.confidence >= SHORTLIST_MIN_CONFIDENCE
        and r.risk_reward >= SHORTLIST_MIN_RR
        and r.entry_price > 0 and r.stop_loss > r.entry_price
        and getattr(r, '_regime', '') not in ("TRENDING_BULL", "CHOPPY", "MILD_TREND")
        and (r.atr <= 0 or abs(r.entry_price - r.stop_loss) <= r.atr * 3)
        and r.trend_phase != "CHANNEL"
        and getattr(r, 'volume_ratio', 0) >= 1.0
        and not r.warnings
    ]
    sell_candidates.sort(key=lambda r: (r.traders_equation, r.confidence), reverse=True)
    sell_picks = [
        _result_to_pick(r, i, "SELL")
        for i, r in enumerate(sell_candidates[:limit], 1)
    ]

    total_buy = sum(1 for r in all_results if r.signal_type == "BUY")
    total_sell = sum(1 for r in all_results if r.signal_type == "SELL")
    total_hold = sum(1 for r in all_results if r.signal_type == "HOLD")

    # AI/ML enrichment — replaces template text with data-driven narratives
    _enrich_picks_with_ai(buy_picks + sell_picks)

    return {
        "buy_picks": buy_picks,
        "sell_picks": sell_picks,
        "stats": {
            "total_tickers": len(tickers),
            "scanned": scanned,
            "analysed": len(all_results),
            "errors": errors,
            "total_buy_signals": total_buy,
            "total_sell_signals": total_sell,
            "total_hold": total_hold,
            "buy_qualified": len(buy_candidates),
            "sell_qualified": len(sell_candidates),
        },
    }


# ═══════════════════════════════════════════════════════════════════
#  COMPATIBILITY API (replaces price_action/ package)
# ═══════════════════════════════════════════════════════════════════

PriceActionResult = BrooksResult


def run_price_action_analysis(
    df, ticker: str = "UNKNOWN",
    bb_data=None, ta_data=None, hybrid_data=None,
) -> BrooksResult:
    return run_brooks_analysis(df=df, ticker=ticker)


def pa_result_to_dict(result: BrooksResult) -> dict:
    return {
        "ticker": result.ticker,
        "success": result.success,
        "error": result.error,
        "signal": {
            "type": result.signal_type,
            "setup": result.setup_type,
            "strength": result.strength,
            "confidence": result.confidence,
            "pa_score": result.pa_score,
            "pa_verdict": result.pa_verdict,
        },
        "price_levels": {
            "current": result.current_price,
            "entry": result.entry_price,
            "stop_loss": result.stop_loss,
            "target_1": result.target_1,
            "target_2": result.target_2,
            "risk_reward": result.risk_reward,
            "traders_equation": result.traders_equation,
            "equation_verdict": result.equation_verdict,
        },
        "trend": {
            "always_in": result.always_in,
            "always_in_score": result.always_in_score,
            "direction": result.trend_direction,
            "strength": result.trend_strength,
            "phase": result.trend_phase,
            "buying_pressure": result.buying_pressure,
            "selling_pressure": result.selling_pressure,
            "ema_gap_bar_count": result.ema_gap_bar_count,
            "gap_bar_setup": result.gap_bar_setup,
            "in_spike": result.in_spike,
            "spike_direction": result.spike_direction,
            "spike_bars": result.spike_bars,
            "spike_strength": result.spike_strength,
            "recent_climax": result.recent_climax,
            "consecutive_bull_trend": result.consecutive_bull_trend,
            "consecutive_bear_trend": result.consecutive_bear_trend,
            "price_vs_ema": result.price_vs_ema,
            "ema20": result.ema20,
        },
        "last_bar": {
            "type": result.last_bar_type,
            "is_signal": result.last_bar_signal,
            "description": result.last_bar_description,
        },
        "patterns": {
            "active": result.active_patterns,
            "breakout_mode": result.breakout_mode,
            "last_h": result.last_hl_bull,
            "last_l": result.last_hl_bear,
        },
        "channel": {
            "price_position": result.price_position,
            "description": result.channel_description,
        },
        "breakout": {
            "in_breakout": result.in_breakout,
            "direction": result.breakout_direction,
        },
        "two_leg": {
            "complete": result.two_leg_complete,
            "measured_target": result.measured_move_target,
        },
        "scoring": result.score_details,
        "cross_system": {
            "bb_agreement": result.bb_agreement,
            "ta_agreement": result.ta_agreement,
            "hybrid_agreement": result.hybrid_agreement,
            "cross_bonus": result.cross_system_bonus,
            "combined_confidence": result.combined_confidence,
            "combined_verdict": result.combined_verdict,
        },
        "reasons": result.reasons,
        "al_brooks_context": result.al_brooks_context,
        "description": result.description,
        "v3": {
            "atr": result.atr,
            "quality_score": result.quality_score,
            "signs_of_strength": result.signs_of_strength_score,
            "reversal_checklist": result.reversal_checklist_score,
            "is_trapped_trade": result.is_trapped_trade,
            "outside_bar": result.outside_bar_reversal,
            "ioi_pattern": result.ioi_pattern,
            "volume_ratio": result.volume_ratio,
            "volume_spike": result.volume_spike,
        },
    }


def scan_all_stocks(
    csv_dir: str, max_workers: int = 16, include_bb: bool = True,
) -> dict:
    from bb_squeeze.data_loader import get_all_tickers_from_csv
    tickers = get_all_tickers_from_csv(csv_dir)
    results = {
        "buy_signals": [], "sell_signals": [],
        "strong_buy": [], "strong_sell": [],
        "breakout_mode": [], "spike_active": [], "all": [],
    }
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_scan_one, t, csv_dir): t for t in tickers}
        for fut in as_completed(futures, timeout=max(120, len(futures) * 2)):
            try:
                r = fut.result(timeout=30)
                if r is None:
                    continue
                results["all"].append(r)
                if r.signal_type == "BUY":
                    results["buy_signals"].append(r)
                    if r.strength == "STRONG" or r.pa_verdict == "STRONG BUY":
                        results["strong_buy"].append(r)
                elif r.signal_type == "SELL":
                    results["sell_signals"].append(r)
                    if r.strength == "STRONG" or r.pa_verdict == "STRONG SELL":
                        results["strong_sell"].append(r)
                if r.breakout_mode:
                    results["breakout_mode"].append(r)
                if r.trend_phase == "SPIKE":
                    results["spike_active"].append(r)
            except Exception:
                continue
    for key in results:
        results[key].sort(key=lambda x: x.confidence, reverse=True)
    return results


def scan_results_to_dicts(results: dict) -> dict:
    return {k: [pa_result_to_dict(r) for r in v] for k, v in results.items()}


def top_buy_shortlist(results: dict, limit: int = 5) -> list:
    buys = results.get("buy_signals", [])
    qualified = [
        r for r in buys
        if r.equation_verdict == "EDGE"
        and r.setup_type in SHORTLIST_SETUPS
        and r.always_in == "LONG"
        and r.confidence >= SHORTLIST_MIN_CONFIDENCE
        and r.risk_reward >= SHORTLIST_MIN_RR
        and r.entry_price > r.stop_loss > 0
    ]
    qualified.sort(key=lambda r: (r.confidence, r.pa_score), reverse=True)
    picks = []
    for i, r in enumerate(qualified[:limit], 1):
        pick = _result_to_pick(r, i, "BUY")
        pick["explanation"] = _plain_english_buy(r)
        picks.append(pick)
    return picks
