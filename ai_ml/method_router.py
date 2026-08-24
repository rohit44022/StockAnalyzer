"""
ai_ml/method_router.py — Regime-Adaptive Method Router

Uses pre-computed per-regime win rates to advise which methods are
strongest in the current market regime.

Does NOT block or filter methods — it adds advisory data so the user
(and the UI) can see which method has the highest edge right now.

Adds fields to the result dict (not per-pick) WITHOUT modifying existing fields.
"""
from __future__ import annotations

import json
import os
import logging

from ai_ml.config import METHOD_ROUTER_DATA

logger = logging.getLogger("ai_ml.method_router")


def _load_router_data() -> dict:
    if os.path.exists(METHOD_ROUTER_DATA):
        try:
            with open(METHOD_ROUTER_DATA) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def get_method_recommendation(
    current_rsi: float | None = None,
    current_bbw_pct: float | None = None,
) -> dict:
    """
    Given current market indicators, recommend which methods are
    strongest and weakest.

    Returns:
      - method_rankings: [{method, win_rate, regime_label}] sorted best→worst
      - best_method: str
      - worst_method: str
      - regime_detected: str (e.g. "NEUTRAL + MED_VOL")
    """
    router = _load_router_data()
    if not router:
        return {"available": False, "reason": "No router data — run ai_ml.trainer first"}

    # Detect RSI regime
    if current_rsi is not None:
        if current_rsi < 40:
            rsi_regime = "OVERSOLD"
        elif current_rsi > 60:
            rsi_regime = "OVERBOUGHT"
        else:
            rsi_regime = "NEUTRAL"
    else:
        rsi_regime = None

    # Detect volatility regime
    if current_bbw_pct is not None:
        if current_bbw_pct < 0.33:
            vol_regime = "LOW_VOL"
        elif current_bbw_pct > 0.67:
            vol_regime = "HIGH_VOL"
        else:
            vol_regime = "MED_VOL"
    else:
        vol_regime = None

    rankings = []
    for method in ["M1", "M2", "M3", "M4"]:
        mdata = router.get(method, {})
        # Try regime-specific win rate, fall back to overall
        wr = mdata.get("overall_win_rate", 0.45)
        trades = mdata.get("total_trades", 0)
        source = "overall"

        if rsi_regime and rsi_regime in mdata.get("by_rsi_regime", {}):
            regime_wr = mdata["by_rsi_regime"][rsi_regime]["win_rate"]
            regime_n = mdata["by_rsi_regime"][rsi_regime]["trades"]
            if regime_n > 100:
                wr = regime_wr
                trades = regime_n
                source = f"rsi_{rsi_regime}"

        if vol_regime and vol_regime in mdata.get("by_vol_regime", {}):
            vol_wr = mdata["by_vol_regime"][vol_regime]["win_rate"]
            vol_n = mdata["by_vol_regime"][vol_regime]["trades"]
            if vol_n > 100:
                # Average with RSI-regime rate
                wr = (wr + vol_wr) / 2
                source += f"+vol_{vol_regime}"

        rankings.append({
            "method": method,
            "win_rate": round(wr, 4),
            "trades_in_regime": trades,
            "source": source,
        })

    rankings.sort(key=lambda x: x["win_rate"], reverse=True)

    regime_label = ""
    if rsi_regime:
        regime_label += rsi_regime
    if vol_regime:
        regime_label += f" + {vol_regime}" if regime_label else vol_regime

    return {
        "available": True,
        "method_rankings": rankings,
        "best_method": rankings[0]["method"] if rankings else None,
        "worst_method": rankings[-1]["method"] if rankings else None,
        "regime_detected": regime_label or "UNKNOWN",
    }
