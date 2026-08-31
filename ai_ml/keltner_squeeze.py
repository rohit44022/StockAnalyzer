"""
ai_ml/keltner_squeeze.py — T7 Keltner Channel Squeeze Intelligence

Reads KC squeeze data from pick's bb_data.indicators and produces
human-readable insights + confidence data. Purely additive, stateless.
"""
from __future__ import annotations
import logging

logger = logging.getLogger("ai_ml.keltner_squeeze")


def enrich_picks_with_keltner(picks: list[dict]) -> None:
    for pick in picks:
        try:
            pick["kc_squeeze_data"] = _analyze(pick)
        except Exception as e:
            logger.warning("KC squeeze failed for %s: %s", pick.get("ticker"), e)
            pick["kc_squeeze_data"] = {"available": False}


def _analyze(pick: dict) -> dict:
    ind = pick.get("bb_data", {}).get("indicators", {})

    kc_sq = bool(ind.get("kc_squeeze", False))
    had_sq = bool(ind.get("kc_had_squeeze", False))
    dur = int(ind.get("kc_squeeze_duration") or 0)
    raw_intensity = ind.get("kc_squeeze_intensity") or 0
    intensity = round(float(raw_intensity) * 100, 1)
    t7 = bool(ind.get("kc_t7_pass", False))
    cmf = float(ind.get("cmf") or ind.get("CMF") or 0)

    if not kc_sq and not had_sq and intensity == 0:
        return {"available": False}

    # Verdict
    if t7:
        verdict, color = "T7_PASS", "bullish"
    elif had_sq and cmf > 0:
        verdict, color = "PARTIAL", "neutral"
    elif kc_sq:
        verdict, color = "BUILDING", "building"
    else:
        verdict, color = "NO_SQUEEZE", "inactive"

    # Dynamic insight text
    parts = []

    if kc_sq and dur >= 6:
        parts.append(
            f"Bollinger Bands are sitting inside Keltner Channels for "
            f"{dur} consecutive bars — this is a genuine volatility "
            f"compression, not just low bandwidth. The market is coiling "
            f"energy for a directional release."
        )
    elif kc_sq:
        parts.append(
            f"BB bands are currently inside KC ({dur} bars) — compression "
            f"is active but has not yet reached the 6-bar minimum duration "
            f"that historically separates noise from genuine squeeze setups."
        )
    elif had_sq:
        parts.append(
            f"A {dur}-bar KC squeeze was recently active — the bands have "
            f"begun expanding. If this coincides with a breakout above the "
            f"upper Bollinger Band, it signals the coiled energy is releasing."
        )

    if intensity >= 50:
        parts.append(
            f"Squeeze depth is extreme at {intensity:.0f}% — the BB bands "
            f"are {intensity:.0f}% narrower than KC, indicating one of the "
            f"tightest compressions in recent history. These deep squeezes "
            f"historically produce the most explosive breakout moves."
        )
    elif intensity >= 30:
        parts.append(
            f"Squeeze depth at {intensity:.0f}% passes the T7 threshold "
            f"(≥30%) — statistical volatility has meaningfully contracted "
            f"below range-based volatility. This level of compression shows "
            f"genuine energy storage, not just market quietness."
        )
    elif intensity > 0:
        parts.append(
            f"Squeeze depth at {intensity:.0f}% is below the T7 threshold "
            f"of 30% — BB bands are inside KC but the compression is shallow. "
            f"The stock is mildly compressed but not deeply coiled."
        )

    if t7:
        parts.append(
            f"All T7 conditions are met: deep KC squeeze (≥6 bars), "
            f"intensity ≥30%, and CMF positive (institutional buying "
            f"confirmed). This is the highest-conviction squeeze setup — "
            f"backtested across 2,183 NSE stocks over 15 years, it achieved "
            f"53.0% win rate and 1.72 profit factor vs the baseline 49.8% / "
            f"1.49. Max consecutive losing streak was 8 trades (vs 13 for "
            f"the baseline). The average winning trade returned +9.89% "
            f"against an average loser of -6.47%."
        )
    elif had_sq and cmf <= 0:
        parts.append(
            f"KC squeeze was present but CMF is negative ({cmf:.3f}) — "
            f"the compression exists but institutional money is flowing out, "
            f"not in. A breakout without CMF confirmation carries higher "
            f"head-fake risk. Wait for CMF to turn positive."
        )
    elif had_sq and intensity < 30:
        parts.append(
            f"KC squeeze detected but intensity ({intensity:.0f}%) is below "
            f"the 30% threshold. The compression is real but shallow — "
            f"breakout energy may be insufficient for a strong directional "
            f"move. Consider this a lower-conviction setup."
        )

    # Backtest stats only when T7 passes
    bt = None
    if t7:
        bt = {
            "trades": 1795,
            "win_rate": 53.0,
            "profit_factor": 1.72,
            "expectancy_r": 0.291,
            "avg_winner_pct": 9.89,
            "avg_loser_pct": -6.47,
            "max_consec_losses": 8,
            "baseline_win_rate": 49.8,
            "baseline_pf": 1.49,
        }

    return {
        "available": True,
        "kc_squeeze_active": kc_sq,
        "kc_had_squeeze": had_sq,
        "kc_duration": dur,
        "kc_intensity_pct": intensity,
        "kc_t7_pass": t7,
        "verdict": verdict,
        "color": color,
        "insight": " ".join(parts),
        "backtest_stats": bt,
    }
