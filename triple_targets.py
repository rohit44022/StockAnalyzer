"""
triple_targets.py — Unified BUY/SELL/Stop targets across the Triple Conviction Engine.
═══════════════════════════════════════════════════════════════════════════════════════

WHY THIS EXISTS:
Each subsystem already produces its own price targets and stops:
  - BB:  bb_signal.stop_loss + band envelopes (upper/mid/lower)
  - TA:  calculate_target_prices() — 7-method consensus (Fib, S/R, ATR, MA, BB, patterns, pivots)
  - PA:  Al Brooks engine — entry_price, stop_loss, target_1/2, measured_move_target
  - Wyckoff: range support/resistance (when in_range)

Without a unifier, the dashboard shows 7+ different prices and the user has to pick which
to trust. This module produces ONE plan that uses ALL THREE dimensions:

  - Entry zone   (current price ± small buffer, with breakout-extended warning)
  - Stop loss    (tightest valid stop across systems, capped at MAX_STOP_PCT)
  - Tier 1       (Conservative — nearest credible profit-take)
  - Tier 2       (Primary — TA consensus, the meat of the move)
  - Tier 3       (Stretch — furthest reasonable extension)
  - Wyckoff modifier (small ±5% nudge based on structural phase)
  - Confidence   (derived from triple verdict + cross-validation alignment)
  - Warnings     (entry-timing, phase mismatch, stale measured moves, etc.)

DESIGN PRINCIPLES:
  • Reuse existing system outputs — don't re-invent target math.
  • Conviction-weighted: a system's targets are weighted by its score in this stock.
  • Sanity checks: stops below entry (BUY) / above entry (SELL); targets ordered;
    reject too-close (<1.5%) or too-far (>40%) targets.
  • Direction-aware: BUY/SELL have mirror logic; HOLD returns range bounds only.
  • Deterministic: same input → same output.
"""

from __future__ import annotations
import math
from typing import Optional


# ─────────────────────────── tunables ───────────────────────────

MAX_STOP_PCT       = 0.08    # never recommend a stop more than 8% away
MIN_STOP_PCT       = 0.015   # reject stops within 1.5% (gets stopped out by noise)
MIN_TARGET_PCT     = 0.015   # reject targets within 1.5% (noise)
MAX_TARGET_PCT     = 0.40    # reject targets beyond 40% (unrealistic short term)
ENTRY_BUFFER_PCT   = 0.005   # ±0.5% entry zone

# Wyckoff phase multipliers applied to T2 (primary target)
WYCKOFF_T2_MULT = {
    ("ACCUMULATION", "LATE"):    1.07,   # smart money loaded — extend target
    ("ACCUMULATION", "MIDDLE"):  1.05,
    ("ACCUMULATION", "EARLY"):   1.02,
    ("MARKUP",       "EARLY"):   1.03,
    ("MARKUP",       "MIDDLE"):  1.05,
    ("MARKUP",       "CONFIRMED"): 1.05,
    ("MARKUP",       "LATE"):    0.95,   # late in trend — cap target
    ("DISTRIBUTION", "EARLY"):   0.95,
    ("DISTRIBUTION", "MIDDLE"):  0.92,
    ("DISTRIBUTION", "LATE"):    0.90,
    ("MARKDOWN",     "EARLY"):   0.95,
    ("MARKDOWN",     "MIDDLE"):  0.92,
    ("MARKDOWN",     "CONFIRMED"): 0.90,
    ("MARKDOWN",     "LATE"):    0.95,
}


# ─────────────────────────── helpers ───────────────────────────

def _safe(v) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pct(price: float, target: float) -> float:
    if not price:
        return 0.0
    return round((target - price) / price * 100.0, 2)


def _is_bullish(verdict: str) -> bool:
    return "BUY" in (verdict or "").upper()


def _is_bearish(verdict: str) -> bool:
    return "SELL" in (verdict or "").upper()


def _direction_from_verdict(verdict: str) -> str:
    if _is_bullish(verdict):
        return "BUY"
    if _is_bearish(verdict):
        return "SELL"
    return "HOLD"


# ─────────────────────────── stop loss ───────────────────────────

def _build_stop_loss(direction: str, price: float, bb_data: dict,
                     ta_risk: dict, pa_data: dict, wyckoff: dict) -> dict:
    """
    Pick the tightest valid stop across systems, capped at MAX_STOP_PCT.

    For BUY: stop must be BELOW price.
    For SELL: stop must be ABOVE price.
    """
    candidates = {}

    # PA structural stop — already direction-aware
    pa_sl = _safe((pa_data or {}).get("stop_loss"))
    if pa_sl:
        candidates["PA structural"] = pa_sl

    # BB stop_loss — typically below entry for BUY
    bb_sl = _safe((bb_data or {}).get("stop_loss"))
    if bb_sl:
        candidates["BB stop"] = bb_sl

    # BB lower band as a fallback floor (for BUY); upper band for SELL
    bands = (bb_data or {}).get("indicators", {})
    bb_lower = _safe(bands.get("bb_lower"))
    bb_upper = _safe(bands.get("bb_upper"))
    if direction == "BUY" and bb_lower:
        candidates["BB lower band"] = bb_lower
    elif direction == "SELL" and bb_upper:
        candidates["BB upper band"] = bb_upper

    # Wyckoff range bounds
    ph = (wyckoff or {}).get("phase", {}) if wyckoff else {}
    wyckoff_support = _safe(ph.get("support"))
    wyckoff_resistance = _safe(ph.get("resistance"))
    if direction == "BUY" and wyckoff_support and wyckoff_support > 0:
        candidates["Wyckoff support"] = wyckoff_support * 0.99   # 1% buffer below support
    elif direction == "SELL" and wyckoff_resistance and wyckoff_resistance > 0:
        candidates["Wyckoff resistance"] = wyckoff_resistance * 1.01

    # ATR-based stop from TA risk report
    sl_section = (ta_risk or {}).get("stop_losses", {}) if isinstance(ta_risk, dict) else {}
    if isinstance(sl_section, dict):
        for key in ("atr_2x", "recommended"):
            entry = sl_section.get(key)
            if isinstance(entry, dict):
                lvl = _safe(entry.get("level"))
                if lvl:
                    candidates[f"TA {key}"] = lvl

    # Filter to side-correct stops AND minimum distance (noise floor)
    min_dist = price * MIN_STOP_PCT
    if direction == "BUY":
        valid = {k: v for k, v in candidates.items() if v < price and (price - v) >= min_dist}
    elif direction == "SELL":
        valid = {k: v for k, v in candidates.items() if v > price and (v - price) >= min_dist}
    else:
        valid = {}

    if not valid:
        # Fallback: 5% from entry
        if direction == "BUY":
            return {
                "price": round(price * 0.95, 2),
                "pct": -5.0,
                "method": "fallback (no system stop available)",
                "rationale": "No system produced a valid stop. Using 5% default.",
                "alternatives": {},
            }
        elif direction == "SELL":
            return {
                "price": round(price * 1.05, 2),
                "pct": 5.0,
                "method": "fallback (no system stop available)",
                "rationale": "No system produced a valid stop. Using 5% default.",
                "alternatives": {},
            }
        else:
            return {"price": None, "pct": None, "method": "n/a", "rationale": "HOLD — no stop required.", "alternatives": {}}

    # Cap by MAX_STOP_PCT (don't recommend stops too far away)
    if direction == "BUY":
        floor_price = price * (1 - MAX_STOP_PCT)
        valid = {k: max(v, floor_price) for k, v in valid.items()}
        # Tightest = highest stop price (closest to entry)
        chosen_method, chosen_price = max(valid.items(), key=lambda kv: kv[1])
    else:  # SELL
        ceiling_price = price * (1 + MAX_STOP_PCT)
        valid = {k: min(v, ceiling_price) for k, v in valid.items()}
        # Tightest = lowest stop price (closest to entry)
        chosen_method, chosen_price = min(valid.items(), key=lambda kv: kv[1])

    return {
        "price": round(chosen_price, 2),
        "pct": _pct(price, chosen_price),
        "method": chosen_method,
        "rationale": f"Tightest valid stop across systems: {chosen_method} @ ₹{chosen_price:.2f} "
                     f"({_pct(price, chosen_price):+.2f}%). Other levels: " +
                     ", ".join(f"{k} ₹{v:.2f}" for k, v in sorted(valid.items(), key=lambda kv: kv[1], reverse=(direction=='BUY'))),
        "alternatives": {k: round(v, 2) for k, v in valid.items()},
    }


# ─────────────────────────── targets ───────────────────────────

def _collect_target_candidates(direction: str, price: float, bb_data: dict,
                               ta_targets: dict, pa_data: dict, wyckoff: dict,
                               bb_score: float, ta_score: float, pa_score: float) -> list:
    """
    Collect all target candidates from all systems with conviction weights.

    Each candidate: {price, source, weight, label}
    Weights are based on system score (capped 0..100 → 0..1 normalized).
    """
    out = []

    def _w(score: float) -> float:
        # System contributes more weight when its absolute score is high
        return max(0.0, min(1.0, abs(score) / 100.0))

    going_up = direction == "BUY"

    # ── BB band-projected targets ──
    bands = (bb_data or {}).get("indicators", {})
    bb_upper = _safe(bands.get("bb_upper"))
    bb_mid = _safe(bands.get("bb_mid"))
    bb_lower = _safe(bands.get("bb_lower"))
    if going_up and bb_upper and bb_upper > price:
        out.append({"price": bb_upper, "source": "BB", "weight": _w(bb_score) * 0.7, "label": "BB upper band"})
    if going_up and bb_mid and bb_mid > price:
        out.append({"price": bb_mid, "source": "BB", "weight": _w(bb_score) * 0.5, "label": "BB middle band"})
    if not going_up and bb_lower and bb_lower < price:
        out.append({"price": bb_lower, "source": "BB", "weight": _w(bb_score) * 0.7, "label": "BB lower band"})
    if not going_up and bb_mid and bb_mid < price:
        out.append({"price": bb_mid, "source": "BB", "weight": _w(bb_score) * 0.5, "label": "BB middle band"})

    # BB-band projection (2× band width above for upside breakout)
    if going_up and bb_upper and bb_lower:
        bb_proj = bb_upper + (bb_upper - bb_lower)
        if bb_proj > price * (1 + MIN_TARGET_PCT):
            out.append({"price": bb_proj, "source": "BB", "weight": _w(bb_score) * 0.4, "label": "BB envelope projection"})

    # ── TA consensus and individual targets ──
    if isinstance(ta_targets, dict):
        if going_up:
            cu = ta_targets.get("consensus_upside")
            if isinstance(cu, dict):
                t = _safe(cu.get("target"))
                if t and t > price:
                    out.append({"price": t, "source": "TA", "weight": _w(ta_score) * 1.0,
                                "label": f"TA consensus ({cu.get('num_methods', 0)} methods, {cu.get('num_targets', 0)} targets)"})
            for tgt in ta_targets.get("upside_targets", []):
                p = _safe(tgt.get("target"))
                conf = _safe(tgt.get("confidence")) or 50
                if p and p > price:
                    out.append({"price": p, "source": "TA", "weight": _w(ta_score) * (conf / 100) * 0.6,
                                "label": f"TA {tgt.get('method', '?')}: {tgt.get('label', '')}"})
        else:
            cd = ta_targets.get("consensus_downside")
            if isinstance(cd, dict):
                t = _safe(cd.get("target"))
                if t and t < price:
                    out.append({"price": t, "source": "TA", "weight": _w(ta_score) * 1.0,
                                "label": f"TA consensus ({cd.get('num_methods', 0)} methods)"})
            for tgt in ta_targets.get("downside_targets", []):
                p = _safe(tgt.get("target"))
                conf = _safe(tgt.get("confidence")) or 50
                if p and p < price:
                    out.append({"price": p, "source": "TA", "weight": _w(ta_score) * (conf / 100) * 0.6,
                                "label": f"TA {tgt.get('method', '?')}: {tgt.get('label', '')}"})

    # ── PA targets (only when PA agrees with direction) ──
    if isinstance(pa_data, dict):
        pa_sig = (pa_data.get("signal_type") or "").upper()
        pa_aligned = (going_up and "BUY" in pa_sig) or (not going_up and "SELL" in pa_sig)
        for key, label, weight_mult in [
            ("target_1", "PA target 1", 0.9),
            ("target_2", "PA target 2", 0.8),
            ("measured_move_target", "PA measured move", 0.6),
        ]:
            p = _safe(pa_data.get(key))
            if not p:
                continue
            # Filter direction
            if going_up and p <= price:
                continue
            if not going_up and p >= price:
                continue
            w = _w(pa_score) * weight_mult
            if not pa_aligned:
                w *= 0.4   # downweight when PA disagrees with verdict
            out.append({"price": p, "source": "PA", "weight": w,
                        "label": label + ("" if pa_aligned else " (PA disagrees with verdict)")})

    # ── Wyckoff range bounds (Wyckoff returns 0 when not in_range — treat as unavailable) ──
    if isinstance(wyckoff, dict):
        ph = wyckoff.get("phase", {}) or {}
        sup = _safe(ph.get("support"))
        res = _safe(ph.get("resistance"))
        if going_up and res and res > 0 and res > price:
            out.append({"price": res, "source": "Wyckoff", "weight": 0.6, "label": "Wyckoff range resistance"})
        if not going_up and sup and sup > 0 and sup < price:
            out.append({"price": sup, "source": "Wyckoff", "weight": 0.6, "label": "Wyckoff range support"})

    # ── Sanity filter ──
    cleaned = []
    for t in out:
        delta = abs(t["price"] - price) / price
        if delta < MIN_TARGET_PCT or delta > MAX_TARGET_PCT:
            continue
        cleaned.append(t)
    return cleaned


def _build_target_tiers(direction: str, price: float, candidates: list) -> list:
    """
    Bucket candidates into 3 tiers (Conservative / Primary / Stretch).
    Sort by distance, then split.
    """
    if not candidates:
        return []

    going_up = direction == "BUY"
    sorted_c = sorted(candidates, key=lambda c: c["price"], reverse=not going_up)
    # ascending for BUY (nearest first), descending for SELL

    # Bucket into tertiles by absolute distance
    distances = [(c, abs(c["price"] - price)) for c in sorted_c]

    n = len(distances)
    if n == 1:
        groups = [distances]
    elif n == 2:
        groups = [[distances[0]], [distances[1]]]
    else:
        third = n / 3.0
        groups = [
            distances[:max(1, int(round(third)))],
            distances[max(1, int(round(third))):max(2, int(round(2 * third)))],
            distances[max(2, int(round(2 * third))):],
        ]
        groups = [g for g in groups if g]

    tier_names = ["Conservative", "Primary", "Stretch"]
    tiers = []
    for i, group in enumerate(groups[:3]):
        # Weighted centroid within group
        total_w = sum(c["weight"] for c, _ in group)
        if total_w <= 0:
            avg_price = sum(c["price"] for c, _ in group) / len(group)
            avg_conf = 50
        else:
            avg_price = sum(c["price"] * c["weight"] for c, _ in group) / total_w
            avg_conf = round(min(100.0, total_w / len(group) * 100))
        sources = sorted(set(c["source"] for c, _ in group))
        labels = [c["label"] for c, _ in group]
        tiers.append({
            "tier": tier_names[i] if i < len(tier_names) else f"Tier {i+1}",
            "price": round(avg_price, 2),
            "pct": _pct(price, avg_price),
            "sources": sources,
            "contributors": labels[:5],
            "n_methods": len(set(c["label"].split(":")[0] for c, _ in group)),
            "confidence": avg_conf,
        })
    return tiers


def _apply_wyckoff_modifier(tiers: list, direction: str, wyckoff: dict, price: float) -> tuple:
    """
    Apply Wyckoff phase multiplier to T2 (Primary) target only.
    Returns (modified_tiers, mod_info_dict).
    """
    if not wyckoff or len(tiers) < 2:
        return tiers, {"phase": "n/a", "multiplier": 1.0, "note": "insufficient phase data"}

    ph = wyckoff.get("phase", {}) or {}
    name = ph.get("name") or ph.get("phase")
    sub = ph.get("sub_phase")
    mult = WYCKOFF_T2_MULT.get((name, sub), 1.0)

    if mult == 1.0:
        return tiers, {
            "phase": f"{name}/{sub}" if name else "unknown",
            "multiplier": 1.0,
            "note": "phase neutral — targets unmodified",
        }

    # Adjust the Primary tier (index 1 if present).
    # WYCKOFF_T2_MULT is encoded as a "bullish bias" multiplier:
    #   mult > 1.0 → favors UP (extends BUY target / trims SELL target)
    #   mult < 1.0 → favors DOWN (trims BUY target / extends SELL target)
    primary_idx = 1 if len(tiers) >= 2 else 0
    orig = tiers[primary_idx]["price"]
    if direction == "BUY":
        # Distance from entry is scaled by mult.
        new = price + (orig - price) * mult
    else:
        # SELL: invert the bias so that bullish-phase mult shrinks the down-distance.
        new = price + (orig - price) * (2 - mult)

    tiers[primary_idx] = {
        **tiers[primary_idx],
        "price": round(new, 2),
        "pct": _pct(price, new),
        "wyckoff_adjusted": True,
        "wyckoff_orig": round(orig, 2),
    }

    if direction == "BUY":
        direction_word = "extended" if mult > 1 else "trimmed"
    else:
        direction_word = "trimmed" if mult > 1 else "extended"
    return tiers, {
        "phase": f"{name}/{sub}" if name else "unknown",
        "multiplier": mult,
        "note": f"Primary {direction} target {direction_word} due to {name}/{sub} phase",
    }


# ─────────────────────────── main entrypoint ───────────────────────────

def compute_triple_targets(
    triple_verdict: dict,
    bb_data: dict,
    bb_score: dict,
    ta_signal: dict,
    ta_score: dict,
    ta_risk: dict,
    ta_targets: dict,
    pa_data: dict,
    pa_score: dict,
    wyckoff: dict,
    cross: dict,
) -> dict:
    """
    Build the unified BUY/SELL/HOLD plan using all three dimensions.
    Returns the dict embedded under `triple_targets` in the engine response.

    All inputs come straight out of run_triple_analysis() — no transformation needed.
    """
    verdict = (triple_verdict or {}).get("verdict", "HOLD")
    direction = _direction_from_verdict(verdict)

    # Current price — try multiple sources
    bands = (bb_data or {}).get("indicators", {})
    price = _safe(bands.get("price"))
    if not price and isinstance(ta_targets, dict):
        price = _safe(ta_targets.get("current_price"))
    if not price:
        return {
            "direction": direction,
            "error": "No current price available — cannot compute targets",
        }

    bb_total = _safe((bb_score or {}).get("total")) or 0
    ta_total = _safe((ta_score or {}).get("total")) or 0
    pa_total = _safe((pa_score or {}).get("total")) or 0

    # ── HOLD: just expose range bounds, no entry plan ──
    if direction == "HOLD":
        ph = (wyckoff or {}).get("phase", {}) if wyckoff else {}
        # Wyckoff returns 0 (falsy) for support/resistance when not in_range — treat as unavailable
        sup = _safe(ph.get("support"))
        res = _safe(ph.get("resistance"))
        if sup == 0: sup = None
        if res == 0: res = None
        range_text = (f"Range: ₹{sup} ↔ ₹{res}" if (sup or res)
                      else "Wyckoff range not detected (price not in a defined trading range)")
        return {
            "direction": "HOLD",
            "verdict": verdict,
            "current_price": round(price, 2),
            "support": sup,
            "resistance": res,
            "summary": (f"HOLD — no actionable trade. Current price ₹{price:.2f}. "
                        f"{range_text}. "
                        f"Wait for {verdict} → BUY/SELL transition before entering."),
            "warnings": ["Triple verdict is HOLD — no high-conviction direction yet."],
        }

    # ── Entry zone ──
    entry_zone = [
        round(price * (1 - ENTRY_BUFFER_PCT), 2),
        round(price * (1 + ENTRY_BUFFER_PCT), 2),
    ]

    # ── Stop loss ──
    stop = _build_stop_loss(direction, price, bb_data, ta_risk, pa_data, wyckoff)

    # ── Targets ──
    candidates = _collect_target_candidates(
        direction, price, bb_data, ta_targets, pa_data, wyckoff,
        bb_total, ta_total, pa_total,
    )
    tiers = _build_target_tiers(direction, price, candidates)
    tiers, wyckoff_mod = _apply_wyckoff_modifier(tiers, direction, wyckoff, price)

    # ── R:R per tier ──
    if stop.get("price") and tiers:
        risk_amount = abs(price - stop["price"])
        for t in tiers:
            reward = abs(t["price"] - price)
            t["rr"] = round(reward / risk_amount, 2) if risk_amount > 0 else None

    # ── Confidence: triple verdict confidence + agreement bonus ──
    base_conf = _safe((triple_verdict or {}).get("confidence")) or 50
    align = (cross or {}).get("alignment", "")
    conf_adj = {"TRIPLE_ALIGNED": 15, "DOUBLE_ALIGNED": 5, "CONFLICTING": -10, "MIXED": -15}.get(align, 0)
    confidence = max(0, min(100, round(base_conf + conf_adj)))

    # ── Warnings ──
    warnings = []
    bb_upper = _safe(bands.get("bb_upper"))
    bb_lower = _safe(bands.get("bb_lower"))
    if direction == "BUY" and bb_upper and price > bb_upper:
        warnings.append(
            f"Price (₹{price:.2f}) is already above BB upper band (₹{bb_upper:.2f}). "
            f"Entry timing risk — consider waiting for pullback toward BB middle "
            f"(₹{_safe(bands.get('bb_mid')) or 0:.2f})."
        )
    if direction == "SELL" and bb_lower and price < bb_lower:
        warnings.append(
            f"Price (₹{price:.2f}) is already below BB lower band (₹{bb_lower:.2f}). "
            f"Entry timing risk — consider waiting for bounce toward BB middle."
        )

    # PA disagreement warning
    pa_sig = ((pa_data or {}).get("signal_type") or "").upper()
    if direction == "BUY" and "SELL" in pa_sig:
        warnings.append(f"Price Action signal is {pa_sig} — disagrees with triple BUY verdict.")
    elif direction == "SELL" and "BUY" in pa_sig:
        warnings.append(f"Price Action signal is {pa_sig} — disagrees with triple SELL verdict.")

    # Wyckoff phase warnings
    ph = (wyckoff or {}).get("phase", {}) if wyckoff else {}
    if direction == "BUY" and ph.get("name") in ("DISTRIBUTION", "MARKDOWN"):
        warnings.append(
            f"Wyckoff phase is {ph.get('name')}/{ph.get('sub_phase')} — "
            f"smart-money structure favors selling. BUY entry contradicts the structural phase."
        )
    elif direction == "SELL" and ph.get("name") in ("ACCUMULATION", "MARKUP"):
        warnings.append(
            f"Wyckoff phase is {ph.get('name')}/{ph.get('sub_phase')} — "
            f"smart-money structure favors buying. SELL entry contradicts the structural phase."
        )

    # R:R warning
    if tiers and tiers[0].get("rr") and tiers[0]["rr"] < 1.0:
        warnings.append(f"Conservative target R:R is only {tiers[0]['rr']:.2f}:1 — "
                        f"reward smaller than risk. Wait for better entry.")

    # ── Summary ──
    if tiers:
        t1 = tiers[0]
        primary = tiers[1] if len(tiers) > 1 else t1
        summary = (
            f"{direction} @ ₹{price:.2f} "
            f"(zone ₹{entry_zone[0]}–₹{entry_zone[1]}). "
            f"Stop ₹{stop['price']} ({stop['pct']:+.1f}%). "
            f"T1 ₹{t1['price']} ({t1['pct']:+.1f}%, RR {t1.get('rr', '?')}:1) → "
            f"T2 ₹{primary['price']} ({primary['pct']:+.1f}%, RR {primary.get('rr', '?')}:1)"
            + (f" → T3 ₹{tiers[2]['price']} ({tiers[2]['pct']:+.1f}%, RR {tiers[2].get('rr', '?')}:1)" if len(tiers) > 2 else "")
            + f". Confidence {confidence}%."
        )
    else:
        summary = f"{direction} @ ₹{price:.2f}. No reliable targets across systems."

    # ── System-by-system snapshot (transparency) ──
    system_view = {
        "bb": {
            "score": round(bb_total, 1),
            "stop": _safe((bb_data or {}).get("stop_loss")),
            "upper_band": _safe(bands.get("bb_upper")),
            "mid_band": _safe(bands.get("bb_mid")),
            "lower_band": _safe(bands.get("bb_lower")),
        },
        "ta": {
            "score": round(ta_total, 1),
            "consensus_upside": (ta_targets or {}).get("consensus_upside") if isinstance(ta_targets, dict) else None,
            "consensus_downside": (ta_targets or {}).get("consensus_downside") if isinstance(ta_targets, dict) else None,
        },
        "pa": {
            "score": round(pa_total, 1),
            "signal": (pa_data or {}).get("signal_type"),
            "entry": _safe((pa_data or {}).get("entry_price")),
            "stop": _safe((pa_data or {}).get("stop_loss")),
            "t1": _safe((pa_data or {}).get("target_1")),
            "t2": _safe((pa_data or {}).get("target_2")),
        },
        "wyckoff": {
            "phase": f"{ph.get('name', '?')}/{ph.get('sub_phase', '?')}" if ph else "n/a",
            "support": _safe(ph.get("support")) if ph else None,
            "resistance": _safe(ph.get("resistance")) if ph else None,
            "bias": (wyckoff or {}).get("scoring", {}).get("bias") if isinstance(wyckoff, dict) else None,
        },
    }

    return {
        "direction": direction,
        "verdict": verdict,
        "current_price": round(price, 2),
        "entry": {
            "price": round(price, 2),
            "zone": entry_zone,
            "rationale": "Current market price ± 0.5% buffer",
        },
        "stop_loss": stop,
        "targets": tiers,
        "wyckoff_modifier": wyckoff_mod,
        "confidence": confidence,
        "warnings": warnings,
        "summary": summary,
        "system_targets": system_view,
        "n_candidates_collected": len(candidates),
    }
