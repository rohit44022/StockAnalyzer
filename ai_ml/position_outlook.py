"""
ai_ml/position_outlook.py — Position Outlook Ensemble

Aggregates all existing AI/ML signals into a unified forward-looking
outlook for held positions.  No new model — ensembles XGBoost, LSTM,
exit intelligence, regime, method routing, and KC squeeze into a single
probability-weighted verdict with dynamic explanation.

Adds ai_ml_intel["position_outlook"] dict WITHOUT modifying existing fields.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("ai_ml.position_outlook")

# Per-method historical win rates from 303K-trade training data
_METHOD_BASE_WR = {"M1": 0.483, "M2": 0.457, "M3": 0.439, "M4": 0.438}

# Weight each signal source by reliability (sums to ~1.0)
_W = {
    "ml_xgb":       0.25,   # XGBoost signal filter
    "ml_lstm":      0.15,   # LSTM sequence scorer
    "exit_intel":   0.20,   # Exit intelligence urgency
    "regime":       0.10,   # Market regime filter
    "method_wr":    0.10,   # Method-specific historical WR
    "kc_squeeze":   0.10,   # Keltner squeeze state
    "momentum":     0.10,   # Price vs SMA / band position
}


def compute_position_outlook(ai_ml_intel: dict, holding: dict,
                             indicators: dict, method: str) -> dict:
    """
    Build a Position Outlook from already-computed ai_ml_intel fields.
    Call this AFTER all other AI/ML modules have run.
    """
    signals = {}
    weights_used = {}
    total_w = 0.0
    weighted_score = 0.0

    days = holding.get("days", 0)
    pnl_pct = holding.get("pnl_pct", 0) or 0
    current_price = holding.get("current_price", 0) or 0

    # 1. XGBoost confidence → continuation probability
    ml_conf = ai_ml_intel.get("ml_confidence")
    if ml_conf is not None:
        score = float(ml_conf)
        signals["ml_xgb"] = {"score": score, "source": "XGBoost Signal Filter"}
        weighted_score += score * _W["ml_xgb"]
        total_w += _W["ml_xgb"]
        weights_used["ml_xgb"] = _W["ml_xgb"]

    # 2. LSTM sequence confidence
    seq_conf = ai_ml_intel.get("seq_confidence")
    if seq_conf is not None:
        score = float(seq_conf)
        signals["ml_lstm"] = {"score": score, "source": "LSTM Sequence Scorer"}
        weighted_score += score * _W["ml_lstm"]
        total_w += _W["ml_lstm"]
        weights_used["ml_lstm"] = _W["ml_lstm"]

    # 3. Exit intelligence (inverted: low urgency = high outlook)
    exit_intel = ai_ml_intel.get("exit_intelligence", {})
    if exit_intel.get("available"):
        urgency = exit_intel.get("urgency", 50)
        score = max(0.0, min(1.0, 1.0 - urgency / 100.0))
        signals["exit_intel"] = {
            "score": score,
            "source": f"Exit Intelligence ({exit_intel.get('urgency_label', '?')})",
            "momentum": exit_intel.get("momentum_health"),
        }
        weighted_score += score * _W["exit_intel"]
        total_w += _W["exit_intel"]
        weights_used["exit_intel"] = _W["exit_intel"]

    # 4. Market regime
    regime = ai_ml_intel.get("market_regime") or ai_ml_intel.get("pick_regime")
    if isinstance(regime, dict) and regime.get("regime"):
        r = regime["regime"].upper()
        regime_scores = {"BULLISH": 0.70, "NEUTRAL": 0.50, "BEARISH": 0.25,
                         "RISK_OFF": 0.15, "RISK_ON": 0.65}
        score = regime_scores.get(r, 0.50)
        signals["regime"] = {"score": score, "source": f"Market Regime ({r})"}
        weighted_score += score * _W["regime"]
        total_w += _W["regime"]
        weights_used["regime"] = _W["regime"]

    # 5. Method-specific base win rate
    base_wr = _METHOD_BASE_WR.get(method, 0.45)
    # Adjust by method router if available
    mroute = ai_ml_intel.get("method_routing", {})
    if mroute.get("available") is not False and mroute.get("method_rankings"):
        for mr in mroute["method_rankings"]:
            if mr.get("method") == method:
                base_wr = mr.get("win_rate", base_wr)
                break
    signals["method_wr"] = {"score": base_wr, "source": f"{method} historical WR"}
    weighted_score += base_wr * _W["method_wr"]
    total_w += _W["method_wr"]
    weights_used["method_wr"] = _W["method_wr"]

    # 6. KC Squeeze state
    kc = ai_ml_intel.get("kc_squeeze", {})
    if kc and kc.get("available"):
        if kc.get("kc_t7_pass"):
            score = 0.80
        elif kc.get("kc_squeeze_active"):
            score = 0.65
        elif kc.get("kc_had_squeeze"):
            score = 0.55
        else:
            score = 0.45
        signals["kc_squeeze"] = {
            "score": score,
            "source": f"KC Squeeze ({kc.get('verdict', '?')})",
        }
        weighted_score += score * _W["kc_squeeze"]
        total_w += _W["kc_squeeze"]
        weights_used["kc_squeeze"] = _W["kc_squeeze"]

    # 7. Momentum / band position
    bb_upper = indicators.get("bb_upper", 0)
    bb_lower = indicators.get("bb_lower", 0)
    bb_mid = indicators.get("bb_mid", 0)
    rsi = indicators.get("rsi") or indicators.get("rsi14")
    if current_price and bb_mid and bb_upper > bb_lower:
        band_range = bb_upper - bb_lower
        band_pos = (current_price - bb_lower) / band_range
        # Sweet spot: between mid and upper band (0.5–1.0)
        if 0.5 <= band_pos <= 1.0:
            score = 0.60 + 0.15 * (band_pos - 0.5) / 0.5
        elif band_pos > 1.0:
            score = 0.55  # extended — may pull back
        else:
            score = 0.30 + 0.20 * max(0, band_pos)
        # RSI modifier
        if rsi is not None:
            if rsi > 75:
                score *= 0.85  # overbought drag
            elif rsi < 35:
                score *= 0.80  # oversold in held position = bearish
        signals["momentum"] = {
            "score": max(0.0, min(1.0, score)),
            "source": f"Band position ({band_pos:.0%})",
        }
        weighted_score += signals["momentum"]["score"] * _W["momentum"]
        total_w += _W["momentum"]
        weights_used["momentum"] = _W["momentum"]

    # Normalize
    if total_w > 0:
        outlook_score = weighted_score / total_w
    else:
        outlook_score = base_wr

    outlook_score = max(0.0, min(1.0, outlook_score))

    # P&L context adjustment (held position reality check)
    # Deep loss + weak signals → lower outlook
    if pnl_pct < -10 and outlook_score > 0.5:
        outlook_score = outlook_score * 0.85
    # Deep profit + strong signals → slightly temper (mean reversion)
    elif pnl_pct > 20 and outlook_score > 0.65:
        outlook_score = outlook_score * 0.95

    # Verdict
    if outlook_score >= 0.65:
        verdict = "BULLISH"
        color = "bullish"
    elif outlook_score >= 0.50:
        verdict = "NEUTRAL"
        color = "neutral"
    elif outlook_score >= 0.35:
        verdict = "CAUTIOUS"
        color = "bearish"
    else:
        verdict = "BEARISH"
        color = "bearish"

    # Expected outcome range (using 1:3 risk-reward from training data)
    atr = indicators.get("atr_14") or indicators.get("atr14")
    atr_loss = -(atr / current_price * 100 * 2) if atr and current_price else -6.5
    downside_risk = ai_ml_intel.get("ml_downside_risk")
    if downside_risk is not None and float(downside_risk) < 0:
        expected_loss = float(downside_risk) * 100  # negative fraction → negative pct
    else:
        expected_loss = atr_loss

    expected_gain = abs(expected_loss) * 3  # 1:3 RR from training data
    expected_return = outlook_score * expected_gain + (1 - outlook_score) * expected_loss

    # Time estimate
    time_check = ai_ml_intel.get("time_check", {})
    typical_lo = time_check.get("typical_lo", 15)
    typical_hi = time_check.get("typical_hi", 25)
    remaining_lo = max(0, typical_lo - days)
    remaining_hi = max(0, typical_hi - days)

    # Build explanation
    explanation = _build_outlook_text(
        verdict, outlook_score, signals, pnl_pct, days,
        remaining_lo, remaining_hi, expected_return, method
    )

    return {
        "available": True,
        "outlook_score": round(outlook_score, 3),
        "verdict": verdict,
        "color": color,
        "expected_return_pct": round(expected_return, 1),
        "expected_loss_pct": round(expected_loss, 1),
        "expected_gain_pct": round(expected_gain, 1),
        "remaining_days_lo": remaining_lo,
        "remaining_days_hi": remaining_hi,
        "signals_used": len(signals),
        "signals": {k: {"score": round(v["score"], 3), "source": v["source"]}
                    for k, v in signals.items()},
        "explanation": explanation,
    }


def _build_outlook_text(verdict, score, signals, pnl_pct, days,
                        rem_lo, rem_hi, exp_ret, method):
    parts = []

    pct = round(score * 100)

    if verdict == "BULLISH":
        parts.append(
            f"Ensemble outlook is BULLISH ({pct}% composite score across "
            f"{len(signals)} AI/ML models). The weight of evidence favors "
            f"continued upside from current levels."
        )
    elif verdict == "NEUTRAL":
        parts.append(
            f"Ensemble outlook is NEUTRAL ({pct}% composite score). Signals "
            f"are mixed — some models see upside while others flag caution. "
            f"Hold with tighter risk management."
        )
    elif verdict == "CAUTIOUS":
        parts.append(
            f"Ensemble outlook is CAUTIOUS ({pct}% composite score). More "
            f"models lean bearish than bullish. Consider reducing exposure "
            f"or tightening stops."
        )
    else:
        parts.append(
            f"Ensemble outlook is BEARISH ({pct}% composite score). Multiple "
            f"AI/ML models signal deteriorating conditions. Exit or tight "
            f"stops recommended."
        )

    # Top contributor
    if signals:
        best = max(signals.items(), key=lambda x: x[1]["score"])
        worst = min(signals.items(), key=lambda x: x[1]["score"])
        parts.append(
            f"Strongest signal: {best[1]['source']} ({best[1]['score']:.0%}). "
            f"Weakest: {worst[1]['source']} ({worst[1]['score']:.0%})."
        )

    # P&L context
    if pnl_pct > 10:
        parts.append(
            f"Position is up {pnl_pct:.1f}% — consider trailing stop to "
            f"lock in gains while letting winners run."
        )
    elif pnl_pct < -5:
        parts.append(
            f"Position is down {abs(pnl_pct):.1f}% — monitor stop-loss "
            f"levels closely and validate thesis still holds."
        )

    # Time context
    if rem_hi > 0:
        parts.append(
            f"Based on {method} typical holding period, estimated "
            f"{rem_lo}-{rem_hi} trading days remaining."
        )
    elif days > 0:
        parts.append(
            f"Trade has been held {days} days — past typical {method} "
            f"holding period. Time-based exit pressure is elevated."
        )

    # Expected return
    if exp_ret > 0:
        parts.append(
            f"Expected return from here: +{exp_ret:.1f}% (probability-weighted "
            f"using 1:3 risk-reward from 303K backtested trades)."
        )
    else:
        parts.append(
            f"Expected return from here: {exp_ret:.1f}% (negative expected "
            f"value — risk outweighs potential reward at current signals)."
        )

    return " ".join(parts)
