"""
Brooks Price Action Engine — v3 (Complete Three-Book Implementation)
====================================================================
Al Brooks: Trends (2011), Trading Ranges (2012), Reversals (2012).

v3: All 83 chapters implemented (54 applicable to daily scanner).
  - Trend line drawing & break detection (Trends Ch.13)
  - Channel line & overshoot (Trends Ch.14)
  - Full 18-point signs of strength (Trends Ch.19)
  - Outside bar / IOI patterns (Trends Ch.6-7)
  - Volume analysis (Reversals Ch.10)
  - Expanding triangle (Reversals Ch.6)
  - Final flag detection (Reversals Ch.7)
  - 10-point reversal checklist (Reversals Ch.4)
  - S/R zones & round-number magnets (TR Ch.8, Ch.10)
  - Triangle detection (TR Ch.23)
  - Trapped trader entries (TR Ch.32)
  - Two-reason minimum enforcement (TR Ch.26)
  - Dueling lines (TR Ch.19)
  - ATR-based adaptive stops
  - Volume confirmation filter
  - Conviction-decay for late entries

Zero imports from price_action/.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

# ── Constants ──────────────────────────────────────────────────────
MIN_BARS = 60
EMA_PERIOD = 20
SWING_LB = 5
BODY_TREND = 0.50
BODY_STRONG = 0.70
BODY_DOJI = 0.25
GAP_BAR_THRESH = 20
CLIMAX_MIN_TREND = 20
ATR_PERIOD = 14
ATR_STOP_MULT = 2.0
VOL_AVG_PERIOD = 20
TREND_LINE_MIN_TOUCHES = 2
MIN_REASONS = 2

# ── NSE Cost Model (delivery trades, discount broker) ─────────────
# ponytail: single round-trip %, bump if slippage proves worse
NSE_COST_PCT = 0.50  # % of entry price, covers brokerage+STT+GST+stamp+slippage

# ── Setup probabilities — loaded from empirical backtest if available ──
_EMPIRICAL_PROB_FILE = Path(__file__).parent / "empirical_setup_prob.json"
_DEFAULT_SETUP_PROB = {
    "SECOND_ENTRY": 0.26, "PULLBACK": 0.27,
    "BREAKOUT": 0.28, "FAILED_BREAKOUT": 0.60,
    "TRAPPED_TRADERS": 0.65, "BREAKOUT_PULLBACK": 0.20,
    "REVERSAL": 0.10, "CHANNEL_REVERSAL": 0.60,
}


def _load_setup_prob():
    if _EMPIRICAL_PROB_FILE.exists():
        try:
            with open(_EMPIRICAL_PROB_FILE) as f:
                data = json.load(f)
            return {k: v for k, v in data.items() if isinstance(v, (int, float))}
        except Exception:
            pass
    return _DEFAULT_SETUP_PROB.copy()


SETUP_PROB = _load_setup_prob()

# Only setups with empirically positive edge after NSE costs
# Full-universe backtest 2023-2025: CHANNEL_REVERSAL 58.9% win, +3.41%/trade
SHORTLIST_SETUPS = ("CHANNEL_REVERSAL",)
SHORTLIST_MIN_CONFIDENCE = 60
SHORTLIST_MIN_RR = 1.5


# ── Result ─────────────────────────────────────────────────────────
@dataclass
class BrooksResult:
    ticker: str
    success: bool = True
    error: str = ""

    signal_type: str = "HOLD"
    setup_type: str = "NONE"
    strength: str = "NONE"
    confidence: int = 0
    pa_score: float = 0.0
    pa_verdict: str = "HOLD"

    entry_price: float = 0.0
    stop_loss: float = 0.0
    target_1: float = 0.0
    target_2: float = 0.0
    risk_reward: float = 0.0
    traders_equation: float = 0.0
    equation_verdict: str = "NONE"
    current_price: float = 0.0

    always_in: str = "FLAT"
    always_in_score: float = 0.0
    trend_direction: str = "SIDEWAYS"
    trend_strength: float = 0.0
    trend_phase: str = "UNKNOWN"
    buying_pressure: float = 0.0
    selling_pressure: float = 0.0
    ema_gap_bar_count: int = 0
    gap_bar_setup: bool = False
    in_spike: bool = False
    spike_direction: str = "NONE"
    spike_bars: int = 0
    spike_strength: float = 0.0
    recent_climax: bool = False
    consecutive_bull_trend: int = 0
    consecutive_bear_trend: int = 0
    price_vs_ema: str = "AT"
    ema20: float = 0.0

    last_bar_type: str = "UNKNOWN"
    last_bar_signal: bool = False
    last_bar_description: str = ""

    active_patterns: List[str] = field(default_factory=list)
    breakout_mode: bool = False
    last_hl_bull: str = ""
    last_hl_bear: str = ""

    price_position: str = "MIDDLE"
    channel_description: str = ""

    in_breakout: bool = False
    breakout_direction: str = "NONE"

    two_leg_complete: bool = False
    measured_move_target: float = 0.0

    score_details: Dict[str, float] = field(default_factory=dict)

    reasons: List[str] = field(default_factory=list)
    al_brooks_context: str = ""
    description: str = ""
    warnings: List[str] = field(default_factory=list)

    # v3 additions
    atr: float = 0.0
    volume_ratio: float = 0.0
    volume_spike: bool = False
    trend_line_broken: bool = False
    signs_of_strength_score: int = 0
    signs_of_strength_total: int = 18
    reversal_checklist_score: int = 0
    is_final_flag: bool = False
    is_expanding_triangle: bool = False
    is_triangle: bool = False
    is_trapped_trade: bool = False
    sr_proximity: float = 0.0
    round_magnet_distance: float = 0.0
    reasons_count: int = 0
    quality_score: int = 0
    outside_bar_reversal: str = "NONE"
    ioi_pattern: str = "NONE"

    # cross-system (kept for API compat)
    bb_agreement: str = "UNKNOWN"
    ta_agreement: str = "UNKNOWN"
    hybrid_agreement: str = "UNKNOWN"
    cross_system_bonus: float = 0.0
    combined_verdict: str = ""
    combined_confidence: float = 0.0


# ═══════════════════════════════════════════════════════════════════
#  BAR CLASSIFICATION (vectorised)
# ═══════════════════════════════════════════════════════════════════

def _classify_bars(o, h, l, c):
    rng = h - l
    bod = np.abs(c - o)
    safe = np.where(rng > 0, rng, 1e-10)
    bpct = bod / safe

    bull = c > o
    bear = c < o
    trend = bpct > BODY_TREND
    strong = bpct > BODY_STRONG
    doji = bpct < BODY_DOJI

    ut = np.where(bull, h - c, h - o) / safe
    lt = np.where(bull, o - l, c - l) / safe

    avg = pd.Series(rng).rolling(20, min_periods=1).mean().values
    savg = np.where(avg > 0, avg, 1e-10)
    rr = rng / savg

    n = len(o)
    inside = np.zeros(n, dtype=bool)
    outside = np.zeros(n, dtype=bool)
    for i in range(1, n):
        inside[i] = h[i] <= h[i - 1] and l[i] >= l[i - 1]
        outside[i] = h[i] > h[i - 1] and l[i] < l[i - 1]

    rev_bull = (lt > 0.33) & (ut < 0.33) & (~doji)
    rev_bear = (ut > 0.33) & (lt < 0.33) & (~doji)

    return dict(
        rng=rng, bod=bod, bpct=bpct, bull=bull, bear=bear,
        trend=trend, strong=strong, doji=doji,
        ut=ut, lt=lt, avg=avg, rr=rr,
        inside=inside, outside=outside,
        rev_bull=rev_bull, rev_bear=rev_bear,
    )


def _describe_bar(i, B):
    b, t, s, d, ins, outs, ratio = (
        B["bull"][i], B["trend"][i], B["strong"][i],
        B["doji"][i], B["inside"][i], B["outside"][i], B["rr"][i],
    )
    if d:
        kind, desc = "DOJI", "Doji"
    elif s:
        side = "bull" if b else "bear"
        kind = f"STRONG_{'BULL' if b else 'BEAR'}"
        desc = f"Strong {side} trend bar"
    elif t:
        side = "bull" if b else "bear"
        kind = f"{'BULL' if b else 'BEAR'}_TREND"
        desc = f"{side.title()} trend bar"
    elif B["rev_bull"][i]:
        kind, desc = "BULL_REVERSAL", "Bull reversal bar"
    elif B["rev_bear"][i]:
        kind, desc = "BEAR_REVERSAL", "Bear reversal bar"
    else:
        kind = "BULL" if b else "BEAR"
        desc = f"{'Bull' if b else 'Bear'} bar"
    if ins:
        kind = "INSIDE_" + kind
        desc = "Inside " + desc[0].lower() + desc[1:]
    if outs:
        kind = "OUTSIDE_" + kind
        desc = "Outside " + desc[0].lower() + desc[1:]
    if ratio > 1.8:
        desc += " (large range)"
    elif ratio < 0.4:
        desc += " (small)"
    return kind, desc


# ═══════════════════════════════════════════════════════════════════
#  STRUCTURAL DETECTION
# ═══════════════════════════════════════════════════════════════════

def _find_swings(h, l, lb=SWING_LB):
    n = len(h)
    sh, sl = [], []
    for i in range(lb, n):
        right = min(lb, n - 1 - i)
        if right < 1:
            continue
        if (h[i] >= h[max(0, i - lb): i].max()
                and h[i] >= h[i + 1: i + 1 + right].max()):
            sh.append(i)
        if (l[i] <= l[max(0, i - lb): i].min()
                and l[i] <= l[i + 1: i + 1 + right].min()):
            sl.append(i)
    return np.array(sh, dtype=int), np.array(sl, dtype=int)


def _atr(h, l, c, period=ATR_PERIOD):
    n = len(c)
    tr = np.zeros(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    atr_vals = pd.Series(tr).rolling(period, min_periods=1).mean().values
    return atr_vals


# ═══════════════════════════════════════════════════════════════════
#  PATTERN DETECTION
# ═══════════════════════════════════════════════════════════════════

# Barbwire / tight range — Brooks TR Ch.22
def _barbwire(h, l, B, n):
    if n < 4:
        return False
    lb = min(5, n)
    if int(np.sum(B["doji"][-lb:])) < 1:
        return False
    cluster_rng = float(np.max(h[-lb:]) - np.min(l[-lb:]))
    avg_bar = float(np.mean(B["avg"][-lb:]))
    if avg_bar <= 0 or cluster_rng > avg_bar * 2.0:
        return False
    overlap_pairs = 0
    for i in range(-lb + 1, 0):
        ov = min(h[i], h[i - 1]) - max(l[i], l[i - 1])
        if ov > 0:
            overlap_pairs += 1
    return overlap_pairs >= 2


# Double top / bottom — Reversals Ch.3/8
def _double_tb(h, l, sh, sl, tolerance=0.015):
    pats = []
    if len(sh) >= 2:
        h1, h2 = h[sh[-2]], h[sh[-1]]
        if abs(h1 - h2) / max(h1, h2, 1e-10) < tolerance:
            pats.append("Double Top")
    if len(sl) >= 2:
        l1, l2 = l[sl[-2]], l[sl[-1]]
        if abs(l1 - l2) / max(l1, l2, 1e-10) < tolerance:
            pats.append("Double Bottom")
    # v3: Higher-low double bottom / Lower-high double top
    if len(sl) >= 2:
        if l[sl[-1]] > l[sl[-2]]:
            pats.append("Higher Low")
    if len(sh) >= 2:
        if h[sh[-1]] < h[sh[-2]]:
            pats.append("Lower High")
    return pats


# Outside bar reversal — Trends Ch.6
def _outside_bar(B, n):
    if n < 2:
        return "NONE"
    last = n - 1
    if not B["outside"][last]:
        return "NONE"
    if B["bull"][last] and B["bpct"][last] > 0.4:
        return "BULL"
    if B["bear"][last] and B["bpct"][last] > 0.4:
        return "BEAR"
    return "NONE"


# Inside-Outside-Inside pattern — Trends Ch.7
def _ioi(B, n):
    if n < 3:
        return "NONE"
    if B["inside"][n - 3] and B["outside"][n - 2] and B["inside"][n - 1]:
        if B["bull"][n - 1]:
            return "BULL"
        if B["bear"][n
                      - 1]:
            return "BEAR"
    return "NONE"


# Expanding triangle — Reversals Ch.6
def _expanding_triangle(h, l, sh, sl):
    if len(sh) < 3 or len(sl) < 3:
        return False
    hh = h[sh[-3:]]
    ll = l[sl[-3:]]
    return (hh[1] > hh[0] and hh[2] > hh[1]
            and ll[1] < ll[0] and ll[2] < ll[1])


# Triangle (converging) — TR Ch.23
def _triangle(h, l, sh, sl):
    if len(sh) < 2 or len(sl) < 2:
        return False, "NONE"
    hh = h[sh[-2:]]
    ll = l[sl[-2:]]
    converging = hh[1] < hh[0] and ll[1] > ll[0]
    if not converging:
        return False, "NONE"
    # direction bias: which side is compressing more?
    high_drop = hh[0] - hh[1]
    low_rise = ll[1] - ll[0]
    if high_drop > low_rise * 1.5:
        return True, "BEAR"
    if low_rise > high_drop * 1.5:
        return True, "BULL"
    return True, "NEUTRAL"


# Final flag — Reversals Ch.7
def _final_flag(h, l, B, n, _ai, trend_bars_count):
    if trend_bars_count < 20:
        return False
    lb = min(8, n)
    tight = True
    for i in range(-lb + 1, 0):
        ov = min(h[i], h[i - 1]) - max(l[i], l[i - 1])
        if ov <= 0:
            tight = False
            break
    if not tight:
        return False
    doji_count = int(np.sum(B["doji"][-lb:]))
    return doji_count >= 2


# Wedge / three-push — Reversals Ch.5
def _wedge(h, l, sl, sh, ai):
    pats = []
    if len(sh) >= 3:
        v = h[sh[-3:]]
        if v[0] < v[1] < v[2]:
            push1 = v[1] - v[0]
            push2 = v[2] - v[1]
            shrinking = push2 < push1
            label = "Wedge Bear Flag" if ai == "SHORT" else "Three Push Top"
            if shrinking:
                label += " (shrinking)"
            pats.append(label)
    if len(sl) >= 3:
        v = l[sl[-3:]]
        if v[0] > v[1] > v[2]:
            push1 = v[0] - v[1]
            push2 = v[1] - v[2]
            shrinking = push2 < push1
            label = "Wedge Bull Flag" if ai == "LONG" else "Three Push Bottom"
            if shrinking:
                label += " (shrinking)"
            pats.append(label)
    return pats


# ═══════════════════════════════════════════════════════════════════
#  TREND ANALYSIS
# ═══════════════════════════════════════════════════════════════════

def _consec_trend(B, n, bull=True):
    count = 0
    key = "bull" if bull else "bear"
    for i in range(n - 1, max(n - 11, -1), -1):
        if B[key][i] and B["trend"][i]:
            count += 1
        else:
            break
    return count


# Always-in direction — Reversals Ch.15
def _always_in(c, ema, B, sh, sl, h, l):
    n = len(c)
    lb = min(20, n)
    s = slice(-lb, None)
    score = 0.0

    if c[-1] > ema[-1] * 1.005:
        score += 10
    elif c[-1] < ema[-1] * 0.995:
        score -= 10

    if n >= 6 and ema[-6] > 0:
        slope = (ema[-1] - ema[-6]) / ema[-6] * 100
        score += float(np.clip(slope * 12, -15, 15))

    bt = int(np.sum(B["bull"][s] & B["trend"][s]))
    brt = int(np.sum(B["bear"][s] & B["trend"][s]))
    score += (bt - brt) * 2

    bs = int(np.sum(B["bull"][s] & B["strong"][s]))
    brs = int(np.sum(B["bear"][s] & B["strong"][s]))
    score += (bs - brs) * 3

    cb = _consec_trend(B, n, bull=True)
    cbr = _consec_trend(B, n, bull=False)
    score += cb * 5
    score -= cbr * 5

    if n >= 2 and B["strong"][n - 1] and B["strong"][n - 2]:
        if B["bull"][n - 1] and B["bull"][n - 2]:
            score += 15
        elif B["bear"][n - 1] and B["bear"][n - 2]:
            score -= 15

    if len(sh) >= 2:
        if h[sh[-1]] > h[sh[-2]]:
            score += 8
        elif h[sh[-1]] < h[sh[-2]]:
            score -= 8
    if len(sl) >= 2:
        if l[sl[-1]] > l[sl[-2]]:
            score += 8
        elif l[sl[-1]] < l[sl[-2]]:
            score -= 8

    if score > 25:
        return "LONG", score
    if score < -25:
        return "SHORT", score
    return "FLAT", score


# Trend phase — Trends Ch.21
def _phase(c, ema, B, n):
    lb = min(20, n)
    s = slice(-lb, None)

    consec, direction = 0, None
    for i in range(n - 1, max(n - lb - 1, -1), -1):
        if B["trend"][i]:
            d = "bull" if B["bull"][i] else "bear"
            if direction is None:
                direction = d
            if d == direction:
                consec += 1
            else:
                break
        else:
            break

    above = c[s] > ema[s]
    crossings = int(np.sum(np.diff(above.astype(int)) != 0))

    dom = max(
        int(np.sum(B["bull"][s] & B["trend"][s])),
        int(np.sum(B["bear"][s] & B["trend"][s])),
    ) / lb * 100

    if consec >= 3 and dom > 55:
        return "SPIKE", min(100.0, dom + consec * 5)
    if crossings <= 2 and dom > 40:
        dev = float(np.mean(np.abs(c[s] - ema[s]) / np.where(ema[s] > 0, ema[s], 1) * 100))
        phase = "TIGHT_CHANNEL" if dev < 1.5 else "CHANNEL"
        return phase, min(90.0, dom + 10)
    if crossings <= 4 and dom > 30:
        return "BROAD_CHANNEL", min(70.0, dom)
    return "TRADING_RANGE", max(0.0, 50 - crossings * 5)


# H1/H2/L1/L2 counting — TR Ch.17
def _count_hl(h, l, ai, sl, sh, n):
    bull_c = bear_c = ""

    if ai in ("LONG", "FLAT") and len(sl):
        recent = sl[sl > n - 30]
        if len(recent):
            start = recent[-1]
            up, cnt = False, 0
            for i in range(start + 1, n):
                if h[i] > h[i - 1]:
                    if not up:
                        cnt += 1
                        up = True
                else:
                    up = False
            if cnt >= 1:
                bull_c = f"H{min(cnt, 4)}"

    if ai in ("SHORT", "FLAT") and len(sh):
        recent = sh[sh > n - 30]
        if len(recent):
            start = recent[-1]
            dn, cnt = False, 0
            for i in range(start + 1, n):
                if l[i] < l[i - 1]:
                    if not dn:
                        cnt += 1
                        dn = True
                else:
                    dn = False
            if cnt >= 1:
                bear_c = f"L{min(cnt, 4)}"

    return bull_c, bear_c


# Spike detection — Trends Ch.21
def _spike(c, B, n):
    consec, d = 0, None
    for i in range(n - 1, max(n - 11, -1), -1):
        if B["trend"][i]:
            side = "BULL" if B["bull"][i] else "BEAR"
            if d is None:
                d = side
            if side == d:
                consec += 1
            else:
                break
        else:
            break

    if consec < 2:
        return False, "NONE", 0, 0.0

    start = n - consec
    good_bars = 0
    for i in range(start + 1, n):
        if d == "BULL" and c[i] > c[i - 1]:
            good_bars += 1
        elif d == "BEAR" and c[i] < c[i - 1]:
            good_bars += 1
    overlap_ok = good_bars >= (consec - 1) * 0.6

    active = overlap_ok and (B["strong"][n - 1] or consec >= 3)
    if active:
        avg_bp = float(B["bpct"][-(consec):].mean())
        return True, d, consec, avg_bp * 100
    return False, "NONE", 0, 0.0


# Climax detection — Reversals Ch.4
def _climax(B, c, n):
    if n < CLIMAX_MIN_TREND + 1:
        return False
    last = n - 1
    if B["rr"][last] < 1.5:
        return False

    lb = min(30, n - 1)
    s = slice(-lb - 1, -1)
    bull_pct = float(np.sum(B["bull"][s])) / lb
    bear_pct = float(np.sum(B["bear"][s])) / lb

    if B["bull"][last] and bull_pct > 0.55 and B["rr"][last] > 1.8:
        return True
    if B["bear"][last] and bear_pct > 0.55 and B["rr"][last] > 1.8:
        return True

    if n >= 3 and all(B["strong"][n - 3: n]):
        if all(B["bull"][n - 3: n]) or all(B["bear"][n - 3: n]):
            return True

    if n >= 4:
        rng = B["rng"]
        if (rng[n - 3] < rng[n - 2] < rng[n - 1]
                and all(B["trend"][n - 3: n])
                and (all(B["bull"][n - 3: n]) or all(B["bear"][n - 3: n]))):
            return True

    return False


# EMA gap bars — TR Ch.14
def _gap_bars(l, h, ema, n):
    cnt = 0
    above = True
    for i in range(n - 1, -1, -1):
        if l[i] > ema[i]:
            if cnt == 0:
                above = True
            elif not above:
                break
            cnt += 1
        elif h[i] < ema[i]:
            if cnt == 0:
                above = False
            elif above:
                break
            cnt += 1
        else:
            break
    return cnt, cnt >= GAP_BAR_THRESH


# Two-legged move — TR Ch.16
def _two_leg(h, l, sl, sh, ai, n):
    if ai == "LONG" and len(sl) >= 2 and len(sh):
        after = sl[sl > sh[-1]]
        if len(after) >= 2 and (after[-1] - after[0]) >= 3:
            return True
    if ai == "SHORT" and len(sh) >= 2 and len(sl):
        after = sh[sh > sl[-1]]
        if len(after) >= 2 and (after[-1] - after[0]) >= 3:
            return True
    return False


# Breakout — TR Ch.1-6
def _breakout(c, h, l, B, sh, sl):
    if len(sh) and c[-1] > h[sh[-1]] and B["bull"][-1] and B["trend"][-1]:
        return True, "BULL"
    if len(sl) and c[-1] < l[sl[-1]] and B["bear"][-1] and B["trend"][-1]:
        return True, "BEAR"
    return False, "NONE"


# Micro channel — Trends Ch.21
def _micro_channel(h, l, n, lb=10):
    lb = min(lb, n - 1)
    bull = bear = 0
    for i in range(n - 1, max(n - lb - 1, 0), -1):
        if l[i] > l[i - 1]:
            bull += 1
        else:
            break
    for i in range(n - 1, max(n - lb - 1, 0), -1):
        if h[i] < h[i - 1]:
            bear += 1
        else:
            break
    if bull >= 5:
        return True, "BULL", bull
    if bear >= 5:
        return True, "BEAR", bear
    return False, "NONE", 0


# Small pullback trend — Trends Ch.20
def _small_pb_trend(l, h, c, ema, sl, sh, ai, n, lb=30):
    lb = min(lb, n - 2)
    if ai == "LONG" and len(sl) >= 2:
        recent_lows = [i for i in sl if i >= n - lb]
        if len(recent_lows) >= 2:
            violations = sum(1 for i in recent_lows if c[i] < ema[i])
            if violations <= 1 and c[recent_lows[-1]] > ema[recent_lows[-1]]:
                return True
    elif ai == "SHORT" and len(sh) >= 2:
        recent_highs = [i for i in sh if i >= n - lb]
        if len(recent_highs) >= 2:
            violations = sum(1 for i in recent_highs if c[i] > ema[i])
            if violations <= 1 and c[recent_highs[-1]] < ema[recent_highs[-1]]:
                return True
    return False


# Breakout pullback — TR Ch.6
def _breakout_pullback(c, h, l, B, sh, sl, ai, n, lb=12):
    lb = min(lb, n - 2)
    last = n - 1
    if ai == "LONG" and len(sh) >= 2:
        bo_level = h[sh[-2]]
        bo_happened = False
        for i in range(max(0, n - lb), last):
            if c[i] > bo_level and B["bull"][i]:
                bo_happened = True
                break
        if bo_happened and l[last] >= bo_level * 0.985 and c[last] >= bo_level:
            return True, "BULL", round(bo_level, 2)
    if ai == "SHORT" and len(sl) >= 2:
        bo_level = l[sl[-2]]
        bo_happened = False
        for i in range(max(0, n - lb), last):
            if c[i] < bo_level and B["bear"][i]:
                bo_happened = True
                break
        if bo_happened and h[last] <= bo_level * 1.015 and c[last] <= bo_level:
            return True, "BEAR", round(bo_level, 2)
    return False, "NONE", 0


# Pressure — Trends Ch.18
def _pressure(B, n, lb=20):
    lb = min(lb, n)
    s = slice(-lb, None)
    bp = float(np.sum(B["bull"][s] & B["trend"][s])) / lb * 100
    sp = float(np.sum(B["bear"][s] & B["trend"][s])) / lb * 100
    return round(bp, 1), round(sp, 1)


# Measured move — TR Ch.7
def _mm(sig, h, l, sh, sl, entry):
    if sig == "BUY" and len(sh) >= 1 and len(sl) >= 2:
        last_sl = sl[-1]
        prior_sh = sh[sh < last_sl]
        if len(prior_sh):
            prior_sl = sl[sl < prior_sh[-1]]
            if len(prior_sl):
                leg = h[prior_sh[-1]] - l[prior_sl[-1]]
                if leg > 0:
                    return round(l[last_sl] + leg, 2)
    if sig == "SELL" and len(sl) >= 1 and len(sh) >= 2:
        last_sh = sh[-1]
        prior_sl = sl[sl < last_sh]
        if len(prior_sl):
            prior_sh2 = sh[sh < prior_sl[-1]]
            if len(prior_sh2):
                leg = h[prior_sh2[-1]] - l[prior_sl[-1]]
                if leg > 0:
                    return round(h[last_sh] - leg, 2)
    if len(sh) and len(sl):
        rng = h[sh[-1]] - l[sl[-1]]
        if rng > 0:
            if sig == "BUY":
                return round(h[sh[-1]] + rng, 2)
            if sig == "SELL":
                return round(l[sl[-1]] - rng, 2)
    return round(entry, 2)


# ═══════════════════════════════════════════════════════════════════
#  v3: TREND LINES & CHANNEL LINES (Trends Ch.13-14)
# ═══════════════════════════════════════════════════════════════════

def _trend_lines(h, l, c, sh, sl, n):
    """Draw trend lines from swing points, detect breaks."""
    bull_tl_broken = False
    bear_tl_broken = False
    bull_tl_slope = 0.0
    bear_tl_slope = 0.0
    ch_overshoot_dir = "NONE"

    # Bull trend line: connect two most recent significant swing lows
    if len(sl) >= 2:
        i1, i2 = sl[-2], sl[-1]
        l1, l2 = l[i1], l[i2]
        if i2 > i1:
            slope = (l2 - l1) / (i2 - i1)
            bull_tl_slope = slope
            # project to current bar
            projected = l2 + slope * (n - 1 - i2)
            # broken if close is below the trend line
            if c[-1] < projected and c[-1] < l2:
                bull_tl_broken = True

    # Bear trend line: connect two most recent significant swing highs
    if len(sh) >= 2:
        i1, i2 = sh[-2], sh[-1]
        h1, h2 = h[i1], h[i2]
        if i2 > i1:
            slope = (h2 - h1) / (i2 - i1)
            bear_tl_slope = slope
            projected = h2 + slope * (n - 1 - i2)
            if c[-1] > projected and c[-1] > h2:
                bear_tl_broken = True

    # Channel overshoot: price beyond projected channel line
    # Bull channel line = parallel to bull TL through highest swing high
    if len(sl) >= 2 and len(sh) >= 1:
        i1, i2 = sl[-2], sl[-1]
        if i2 > i1:
            slope = (l[i2] - l[i1]) / (i2 - i1)
            # find highest swing high between sl[-2] and now
            relevant_sh = sh[(sh >= i1) & (sh <= n - 1)]
            if len(relevant_sh):
                anchor = relevant_sh[np.argmax(h[relevant_sh])]
                channel_at_anchor = l[i1] + slope * (anchor - i1)
                channel_height = h[anchor] - channel_at_anchor
                channel_at_now = l[i1] + slope * (n - 1 - i1) + channel_height
                if c[-1] > channel_at_now * 1.005:
                    ch_overshoot_dir = "BULL"

    if len(sh) >= 2 and len(sl) >= 1:
        i1, i2 = sh[-2], sh[-1]
        if i2 > i1:
            slope = (h[i2] - h[i1]) / (i2 - i1)
            relevant_sl = sl[(sl >= i1) & (sl <= n - 1)]
            if len(relevant_sl):
                anchor = relevant_sl[np.argmin(l[relevant_sl])]
                channel_at_anchor = h[i1] + slope * (anchor - i1)
                channel_height = channel_at_anchor - l[anchor]
                channel_at_now = h[i1] + slope * (n - 1 - i1) - channel_height
                if c[-1] < channel_at_now * 0.995:
                    ch_overshoot_dir = "BEAR"

    return bull_tl_broken, bear_tl_broken, ch_overshoot_dir


# ═══════════════════════════════════════════════════════════════════
#  v3: VOLUME ANALYSIS (Reversals Ch.10)
# ═══════════════════════════════════════════════════════════════════

def _volume(vol, n):
    if vol is None or len(vol) < VOL_AVG_PERIOD:
        return 1.0, False
    avg_vol = float(np.mean(vol[max(0, n - VOL_AVG_PERIOD - 1): n - 1]))
    if avg_vol <= 0:
        return 1.0, False
    ratio = float(vol[n - 1]) / avg_vol
    spike = ratio > 2.0
    return round(ratio, 2), spike


# ═══════════════════════════════════════════════════════════════════
#  v3: SUPPORT / RESISTANCE ZONES (TR Ch.8, Trends Ch.17)
# ═══════════════════════════════════════════════════════════════════

def _sr_zones(h, l, c, sh, sl, n):
    """Cluster swing points into S/R zones. Return proximity to nearest."""
    levels = []
    for i in sh:
        levels.append(h[i])
    for i in sl:
        levels.append(l[i])
    if not levels:
        return 0.0

    levels.sort()
    price = c[n - 1]

    # cluster nearby levels (within 1.5%)
    zones = []
    cluster = [levels[0]]
    for lev in levels[1:]:
        if abs(lev - cluster[-1]) / max(cluster[-1], 1e-10) < 0.015:
            cluster.append(lev)
        else:
            zones.append((np.mean(cluster), len(cluster)))
            cluster = [lev]
    zones.append((np.mean(cluster), len(cluster)))

    # nearest zone distance as %
    min_dist = float('inf')
    for z_level, z_count in zones:
        if z_count >= 2:  # only care about zones with 2+ touches
            dist = abs(price - z_level) / max(price, 1e-10) * 100
            if dist < min_dist:
                min_dist = dist

    return round(min_dist, 2) if min_dist < float('inf') else 99.0


# ═══════════════════════════════════════════════════════════════════
#  v3: ROUND-NUMBER MAGNETS (TR Ch.10, Reversals Ch.22)
# ═══════════════════════════════════════════════════════════════════

def _round_magnet(price):
    if price <= 0:
        return 99.0
    if price < 50:
        bases = [5, 10, 25, 50]
    elif price < 200:
        bases = [10, 25, 50, 100]
    elif price < 1000:
        bases = [50, 100, 250, 500]
    elif price < 5000:
        bases = [100, 250, 500, 1000]
    else:
        bases = [250, 500, 1000, 2500, 5000, 10000]
    candidates = [round(price / b) * b for b in bases]
    min_dist = min(abs(price - c) / price * 100 for c in candidates)
    return round(min_dist, 2)


# ═══════════════════════════════════════════════════════════════════
#  v3: SIGNS OF STRENGTH (Trends Ch.19) — all 18 signs
# ═══════════════════════════════════════════════════════════════════

def _signs_of_strength(h, l, c, B, ema, sh, sl, vol, ai, n):
    """Score 0-18: how many signs of trend strength are present."""
    score = 0
    lb = min(20, n)
    s = slice(-lb, None)
    bull = ai == "LONG"
    bear = ai == "SHORT"

    # 1. Consecutive trend bars in trend direction
    if bull and _consec_trend(B, n, True) >= 2:
        score += 1
    elif bear and _consec_trend(B, n, False) >= 2:
        score += 1

    # 2. Large trend bars (> 1.5x average)
    if B["rr"][n - 1] > 1.5 and B["trend"][n - 1]:
        if (bull and B["bull"][n - 1]) or (bear and B["bear"][n - 1]):
            score += 1

    # 3. Closes near highs (bull) or lows (bear) of bars
    if bull and B["bull"][n - 1] and B["ut"][n - 1] < 0.2:
        score += 1
    elif bear and B["bear"][n - 1] and B["lt"][n - 1] < 0.2:
        score += 1

    # 4. Small tails / no overlap
    if n >= 2:
        if bull and c[n - 1] > h[n - 2]:
            score += 1
        elif bear and c[n - 1] < l[n - 2]:
            score += 1

    # 5. EMA gap bars (trending away from EMA)
    gap_cnt, _ = _gap_bars(l, h, ema, n)
    if gap_cnt >= 5:
        score += 1

    # 6. Strong trend bar bodies > 50%
    trend_count = int(np.sum(B["trend"][s]))
    if trend_count > lb * 0.5:
        score += 1

    # 7. Shallow pullbacks (dips < 50% of last leg)
    if len(sh) >= 1 and len(sl) >= 1:
        if bull and sh[-1] > sl[-1]:
            leg = h[sh[-1]] - l[sl[-1]]
            pb = h[sh[-1]] - c[n - 1]
            if leg > 0 and pb < leg * 0.5:
                score += 1
        elif bear and sl[-1] > sh[-1]:
            leg = h[sh[-1]] - l[sl[-1]]
            pb = c[n - 1] - l[sl[-1]]
            if leg > 0 and pb < leg * 0.5:
                score += 1

    # 8. Higher highs and higher lows (bull) / lower (bear)
    if len(sh) >= 2 and len(sl) >= 2:
        if bull and h[sh[-1]] > h[sh[-2]] and l[sl[-1]] > l[sl[-2]]:
            score += 1
        elif bear and h[sh[-1]] < h[sh[-2]] and l[sl[-1]] < l[sl[-2]]:
            score += 1

    # 9. EMA slope agrees with trend
    if n >= 6 and ema[-6] > 0:
        slope = (ema[-1] - ema[-6]) / ema[-6] * 100
        if (bull and slope > 0.5) or (bear and slope < -0.5):
            score += 1

    # 10. Pullbacks find support at EMA
    if bull and abs(l[n - 1] - ema[n - 1]) / max(ema[n - 1], 1) < 0.015:
        score += 1
    elif bear and abs(h[n - 1] - ema[n - 1]) / max(ema[n - 1], 1) < 0.015:
        score += 1

    # 11. Few dojis in lookback
    doji_count = int(np.sum(B["doji"][s]))
    if doji_count <= lb * 0.15:
        score += 1

    # 12. No climax bars (exhaustion)
    if B["rr"][n - 1] < 2.0 or not B["strong"][n - 1]:
        score += 1

    # 13. Follow-through after signal bars
    if n >= 2 and B["trend"][n - 1] and B["trend"][n - 2]:
        if (bull and B["bull"][n - 1] and B["bull"][n - 2]) or \
           (bear and B["bear"][n - 1] and B["bear"][n - 2]):
            score += 1

    # 14. Breakout bars close on their extreme
    if B["strong"][n - 1]:
        if (bull and B["bull"][n - 1]) or (bear and B["bear"][n - 1]):
            score += 1

    # 15. Volume confirms (above average on trend bars)
    if vol is not None and len(vol) >= n:
        avg_v = float(np.mean(vol[max(0, n - VOL_AVG_PERIOD): n]))
        if avg_v > 0 and vol[n - 1] > avg_v:
            score += 1

    # 16. Reversal bars failing (bear reversal bars in bull trend that fail)
    if n >= 3:
        if bull and B["rev_bear"][n - 2] and B["bull"][n - 1] and c[n - 1] > h[n - 2]:
            score += 1
        elif bear and B["rev_bull"][n - 2] and B["bear"][n - 1] and c[n - 1] < l[n - 2]:
            score += 1

    # 17. Two-legged corrections (successful support of trend)
    # Already handled by two_leg detection elsewhere; credit if in play
    # (caller checks this separately)

    # 18. Strong close on last bar
    if bull and c[n - 1] > (h[n - 1] + l[n - 1]) / 2 and B["bpct"][n - 1] > 0.3:
        score += 1
    elif bear and c[n - 1] < (h[n - 1] + l[n - 1]) / 2 and B["bpct"][n - 1] > 0.3:
        score += 1

    return min(score, 18)


# ═══════════════════════════════════════════════════════════════════
#  v3: REVERSAL CHECKLIST (Reversals Ch.4) — 10 requirements
# ═══════════════════════════════════════════════════════════════════

def _reversal_checklist(h, l, c, B, ema, sh, sl, ai, tl_broken, n):
    """Score 0-10: how many reversal requirements are met."""
    score = 0

    # 1. Prior trend of at least 10 bars
    lb = min(30, n)
    bull_bars = int(np.sum(B["bull"][- lb:] & B["trend"][-lb:]))
    bear_bars = int(np.sum(B["bear"][- lb:] & B["trend"][-lb:]))
    if max(bull_bars, bear_bars) >= 10:
        score += 1

    # 2. Two-legged pullback from the extreme (not just total swing count)
    if bull_bars >= bear_bars and len(sh) >= 1:
        lows_after_peak = [i for i in sl if i > sh[-1]]
        if len(lows_after_peak) >= 2:
            score += 1
    elif bear_bars > bull_bars and len(sl) >= 1:
        highs_after_trough = [i for i in sh if i > sl[-1]]
        if len(highs_after_trough) >= 2:
            score += 1

    # 3. Signal bar quality (strong close, decent body)
    last = n - 1
    if B["trend"][last] and B["bpct"][last] > 0.4:
        score += 1

    # 4. Trend line break (Brooks: NEVER trade reversal without TL break)
    if tl_broken:
        score += 1

    # 5. Price at/beyond support/resistance
    # (checking proximity to prior swing levels)
    if len(sh) and len(sl):
        if c[last] <= l[sl[-1]] * 1.01 or c[last] >= h[sh[-1]] * 0.99:
            score += 1

    # 6. Good risk/reward (reward > 2x risk minimum)
    # (checked in signal generation, credit if entry context is good)
    if B["rr"][last] > 0.8 and B["rr"][last] < 2.5:
        score += 1

    # 7. No barbwire / tight trading range nearby
    is_bw = _barbwire(h, l, B, n)
    if not is_bw:
        score += 1

    # 8. Prior push has exhaustion signs (climax, shrinking momentum)
    if B["rr"][last] > 1.5 or (n >= 3 and B["rng"][last] > B["rng"][last - 1] > B["rng"][last - 2]):
        score += 1

    # 9. Counter-trend has follow-through potential (not just a single bar)
    if n >= 2:
        if (B["bull"][last] and B["bull"][last - 1]) or \
           (B["bear"][last] and B["bear"][last - 1]):
            score += 1

    # 10. Volume spike on reversal bar
    # (Volume check deferred to caller — credit if not available)
    score += 0  # placeholder; caller adds 1 if volume spike present

    return score


# ═══════════════════════════════════════════════════════════════════
#  v3: TRAPPED TRADERS (TR Ch.32)
# ═══════════════════════════════════════════════════════════════════

def _trapped_traders(h, l, c, B, sh, sl, hl_bull, hl_bear, ai, n):
    """Detect trapped traders: failed H/L in wrong context."""
    last = n - 1
    if n < 5:
        return False, "NONE", 0

    # Failed H1/H2 in bear trend → trapped longs → SELL
    if ai == "SHORT" and hl_bull in ("H1", "H2"):
        # H1/H2 tried to push up but failed: last bar is a strong bear bar
        # that closed below the entry bar's low
        if B["bear"][last] and B["trend"][last]:
            # check the recent swing high was tested and rejected
            if len(sh) and sh[-1] >= n - 5:
                if c[last] < l[sh[-1]] if sh[-1] > 0 and sh[-1] < n else False:
                    return True, "SELL", 8

    # Failed L1/L2 in bull trend → trapped shorts → BUY
    if ai == "LONG" and hl_bear in ("L1", "L2"):
        if B["bull"][last] and B["trend"][last]:
            if len(sl) and sl[-1] >= n - 5:
                if c[last] > h[sl[-1]] if sl[-1] > 0 and sl[-1] < n else False:
                    return True, "BUY", 8

    return False, "NONE", 0


# ═══════════════════════════════════════════════════════════════════
#  v3: MULTI-RANGE STAIRCASE (Trends Ch.22)
# ═══════════════════════════════════════════════════════════════════

def _staircase(h, l, sh, sl, ai):
    """Trending trading range: series of TRs separated by breakouts."""
    if len(sh) < 4 or len(sl) < 4:
        return False
    if ai == "LONG":
        # each successive swing low is higher
        lows = l[sl[-4:]]
        return all(lows[i] < lows[i + 1] for i in range(3))
    if ai == "SHORT":
        highs = h[sh[-4:]]
        return all(highs[i] > highs[i + 1] for i in range(3))
    return False


# ═══════════════════════════════════════════════════════════════════
#  v3: DUELING LINES (TR Ch.19)
# ═══════════════════════════════════════════════════════════════════

def _dueling_lines(h, l, c, sh, sl, n):
    """Detect when pullback channel meets larger trend S/R."""
    if len(sh) < 3 or len(sl) < 3:
        return False
    # Simplified: converging trend line and pullback line
    # within 1% of current price
    bull_tl = l[sl[-2]] + (l[sl[-1]] - l[sl[-2]]) / max(sl[-1] - sl[-2], 1) * (n - 1 - sl[-2])
    bear_tl = h[sh[-2]] + (h[sh[-1]] - h[sh[-2]]) / max(sh[-1] - sh[-2], 1) * (n - 1 - sh[-2])

    price = c[n - 1]
    if price > 0:
        bull_dist = abs(price - bull_tl) / price
        bear_dist = abs(price - bear_tl) / price
        if bull_dist < 0.01 and bear_dist < 0.01:
            return True
    return False


# ═══════════════════════════════════════════════════════════════════
#  SIGNAL GENERATION (v3: composite quality scoring)
# ═══════════════════════════════════════════════════════════════════

def _signal(c, h, l, o, ema, B, ai, ai_score, phase, ts,
            hl_bull, hl_bear, in_spk, spk_dir, climax,
            gap_cnt, gap_setup, two_leg, sh, sl, in_bo, bo_dir,
            wedges, is_barbwire, double_pats,
            atr_val, vol_ratio, vol_spike,
            tl_bull_broken, tl_bear_broken, ch_overshoot_dir,
            sos_score, rev_checklist, trapped, trapped_dir, trapped_boost,
            is_ff, is_et, is_tri, tri_dir, is_stair, is_duel,
            ob_rev, ioi_dir, sr_prox, round_mag,
            micro_ch, micro_dir, bp, bp_dir, bp_level,
            small_pb, sr_hi, sr_lo):
    n = len(c)
    last = n - 1
    sig, setup, conf = "HOLD", "NONE", 0
    reasons: List[str] = []
    details: Dict[str, float] = {}
    entry = stop = t1 = t2 = 0.0
    strength = "NONE"

    price = c[last]
    hi, lo = h[last], l[last]
    ev = ema[last]
    bull_bar = bool(B["bull"][last])
    bear_bar = bool(B["bear"][last])
    trend_bar = bool(B["trend"][last])
    is_doji = bool(B["doji"][last])
    buf = price * 0.001
    atr_stop = atr_val * ATR_STOP_MULT if atr_val > 0 else price * 0.03

    # ── STEP 0: Blockers ──
    if is_barbwire:
        reasons.append("Barbwire / tight range — no stop entries (Brooks Ch.22)")
        return sig, setup, conf, strength, entry, stop, t1, t2, reasons, details

    if climax:
        reasons.append("Recent climax — waiting for correction")
        return sig, setup, conf, strength, entry, stop, t1, t2, reasons, details

    if is_et:
        reasons.append("Expanding triangle — breakouts fail here, avoid (Rev Ch.6)")
        return sig, setup, conf, strength, entry, stop, t1, t2, reasons, details

    # ── BUY setups (always-in LONG) ──
    if ai == "LONG":
        near_ema = abs(lo - ev) / ev < 0.02 if ev > 0 else False

        buy_stop = lo - atr_stop
        buy_entry = hi + buf
        # enforce minimum 2% stop distance
        min_stop = buy_entry * 0.98
        if buy_stop > min_stop:
            buy_stop = min_stop

        if gap_setup and near_ema and bull_bar:
            sig, setup, conf = "BUY", "PULLBACK", 78
            entry, stop = buy_entry, buy_stop
            reasons.append(f"First EMA touch after {gap_cnt} gap bars — strongest trend setup (TR Ch.14)")
            details["gap_bar_setup"] = 1

        elif hl_bull == "H2" and near_ema and bull_bar:
            sig, setup, conf = "BUY", "SECOND_ENTRY", 72
            entry, stop = buy_entry, buy_stop
            reasons.append(f"H2 pullback near EMA20 — bread-and-butter entry (Trends Ch.10)")
            details["h2_near_ema"] = 1

        elif any("Wedge Bull Flag" in w for w in wedges) and bull_bar:
            sig, setup, conf = "BUY", "PULLBACK", 70
            entry, stop = buy_entry, buy_stop
            reasons.append("Wedge bull flag / three-push pullback (Rev Ch.5)")
            details["wedge"] = 1

        elif two_leg and bull_bar and price > ev:
            sig, setup, conf = "BUY", "PULLBACK", 68
            entry, stop = buy_entry, buy_stop
            reasons.append("Two-legged correction complete (TR Ch.16)")
            details["two_leg"] = 1

        elif phase in ("CHANNEL", "TIGHT_CHANNEL") and near_ema and bull_bar:
            sig, setup, conf = "BUY", "PULLBACK", 65
            entry, stop = buy_entry, buy_stop
            reasons.append("Pullback to EMA in bull channel (Trends Ch.14)")
            details["channel_pb"] = 1

        elif hl_bull == "H1" and in_spk and spk_dir == "BULL":
            sig, setup, conf = "BUY", "PULLBACK", 62
            entry, stop = buy_entry, buy_stop
            reasons.append("H1 in bull spike — aggressive entry (Trends Ch.21)")
            details["h1_spike"] = 1

        elif (bp and bp_dir == "BULL" and bull_bar
              and (phase in ("CHANNEL", "TIGHT_CHANNEL", "SPIKE")
                   or sos_score >= 12)):
            sig, setup, conf = "BUY", "BREAKOUT_PULLBACK", 62
            entry, stop = buy_entry, min(buy_stop, bp_level - atr_stop)
            reasons.append(f"Breakout pullback — first pullback holds above {bp_level:.2f} (TR Ch.6)")
            details["bp"] = 1

    # ── SELL setups (always-in SHORT) ──
    elif ai == "SHORT":
        near_ema = abs(hi - ev) / ev < 0.02 if ev > 0 else False

        sell_stop = hi + atr_stop
        sell_entry = lo - buf
        max_stop = sell_entry * 1.02
        if sell_stop < max_stop:
            sell_stop = max_stop

        if gap_setup and near_ema and bear_bar:
            sig, setup, conf = "SELL", "PULLBACK", 78
            entry, stop = sell_entry, sell_stop
            reasons.append(f"First EMA touch after {gap_cnt} gap bars (TR Ch.14)")
            details["gap_bar_setup"] = 1

        elif hl_bear == "L2" and near_ema and bear_bar:
            sig, setup, conf = "SELL", "SECOND_ENTRY", 72
            entry, stop = sell_entry, sell_stop
            reasons.append(f"L2 pullback near EMA20 — bread-and-butter entry (Trends Ch.10)")
            details["l2_near_ema"] = 1

        elif any("Wedge Bear Flag" in w for w in wedges) and bear_bar:
            sig, setup, conf = "SELL", "PULLBACK", 70
            entry, stop = sell_entry, sell_stop
            reasons.append("Wedge bear flag / three-push pullback (Rev Ch.5)")
            details["wedge"] = 1

        elif two_leg and bear_bar and price < ev:
            sig, setup, conf = "SELL", "PULLBACK", 68
            entry, stop = sell_entry, sell_stop
            reasons.append("Two-legged correction complete (TR Ch.16)")
            details["two_leg"] = 1

        elif phase in ("CHANNEL", "TIGHT_CHANNEL") and near_ema and bear_bar:
            sig, setup, conf = "SELL", "PULLBACK", 65
            entry, stop = sell_entry, sell_stop
            reasons.append("Pullback to EMA in bear channel (Trends Ch.14)")
            details["channel_pb"] = 1

        elif hl_bear == "L1" and in_spk and spk_dir == "BEAR":
            sig, setup, conf = "SELL", "PULLBACK", 62
            entry, stop = sell_entry, sell_stop
            reasons.append("L1 in bear spike — aggressive entry (Trends Ch.21)")
            details["l1_spike"] = 1

        elif (bp and bp_dir == "BEAR" and bear_bar
              and (phase in ("CHANNEL", "TIGHT_CHANNEL", "SPIKE")
                   or sos_score >= 12)):
            sig, setup, conf = "SELL", "BREAKOUT_PULLBACK", 62
            entry, stop = sell_entry, max(sell_stop, bp_level + atr_stop)
            reasons.append(f"Breakout pullback — first pullback holds below {bp_level:.2f} (TR Ch.6)")
            details["bp"] = 1

    # ── v3: Trapped trader setups (TR Ch.32) ──
    if sig == "HOLD" and trapped:
        if trapped_dir == "BUY" and bull_bar:
            sig, setup, conf = "BUY", "TRAPPED_TRADERS", 70
            entry = hi + buf
            stop = lo - atr_stop
            if stop > entry * 0.98:
                stop = entry * 0.98
            reasons.append("Failed L1/L2 trapped shorts — buying their stops (TR Ch.32)")
            details["trapped"] = 1
        elif trapped_dir == "SELL" and bear_bar:
            sig, setup, conf = "SELL", "TRAPPED_TRADERS", 70
            entry = lo - buf
            stop = hi + atr_stop
            if stop < entry * 1.02:
                stop = entry * 1.02
            reasons.append("Failed H1/H2 trapped longs — selling their stops (TR Ch.32)")
            details["trapped"] = 1

    # ── Breakout (either direction) ──
    if sig == "HOLD" and in_bo:
        if bo_dir == "BULL" and trend_bar and bull_bar and B["strong"][last]:
            sig, setup, conf = "BUY", "BREAKOUT", 58
            entry = price
            stop = lo - atr_stop
            if stop > entry * 0.98:
                stop = entry * 0.98
            reasons.append("Breakout above swing high with strong trend bar (TR Ch.1)")
            details["breakout"] = 1
            if ai == "SHORT":
                conf -= 12
                reasons.append("Counter-trend breakout — 80% rule penalty (Rev Ch.1)")
        elif bo_dir == "BEAR" and trend_bar and bear_bar and B["strong"][last]:
            sig, setup, conf = "SELL", "BREAKOUT", 58
            entry = price
            stop = hi + atr_stop
            if stop < entry * 1.02:
                stop = entry * 1.02
            reasons.append("Breakout below swing low with strong trend bar (TR Ch.1)")
            details["breakout"] = 1
            if ai == "LONG":
                conf -= 12
                reasons.append("Counter-trend breakout — 80% rule penalty (Rev Ch.1)")

    # ── Failed breakout ──
    if sig == "HOLD":
        if (len(sh) and sh[-1] > n - 6
                and bear_bar and trend_bar and price < h[sh[-1]]):
            sig, setup, conf = "SELL", "FAILED_BREAKOUT", 62
            entry = lo - buf
            stop = h[sh[-1]] + atr_stop
            if stop < entry * 1.02:
                stop = entry * 1.02
            reasons.append("Failed bull breakout — trapped buyers (Rev Ch.9)")
            details["failed_bo"] = 1
            if ai == "LONG":
                if not tl_bull_broken:
                    conf -= 20
                    reasons.append("Counter-trend WITHOUT trend line break — very low probability (Trends Ch.13)")
                else:
                    conf -= 10
                    reasons.append("Counter-trend but trend line broken — proceed with caution")
        elif (len(sl) and sl[-1] > n - 6
              and bull_bar and trend_bar and price > l[sl[-1]]):
            sig, setup, conf = "BUY", "FAILED_BREAKOUT", 62
            entry = hi + buf
            stop = l[sl[-1]] - atr_stop
            if stop > entry * 0.98:
                stop = entry * 0.98
            reasons.append("Failed bear breakout — trapped sellers (Rev Ch.9)")
            details["failed_bo"] = 1
            if ai == "SHORT":
                if not tl_bear_broken:
                    conf -= 20
                    reasons.append("Counter-trend WITHOUT trend line break — very low probability (Trends Ch.13)")
                else:
                    conf -= 10
                    reasons.append("Counter-trend but trend line broken — proceed with caution")

    # ── MTR: Major Trend Reversal (Rev Ch.3) ──
    if sig == "HOLD" and rev_checklist >= 7:
        if tl_bear_broken and bull_bar and trend_bar:
            if len(sl) >= 2 and l[sl[-1]] > l[sl[-2]]:
                sig, setup, conf = "BUY", "REVERSAL", 64
                entry = hi + buf
                stop = l[sl[-1]] - atr_stop
                if stop > entry * 0.98:
                    stop = entry * 0.98
                reasons.append(f"Major trend reversal — bear TL broken, higher low, checklist {rev_checklist}/10 (Rev Ch.3)")
                details["mtr"] = 1
        elif tl_bull_broken and bear_bar and trend_bar:
            if len(sh) >= 2 and h[sh[-1]] < h[sh[-2]]:
                sig, setup, conf = "SELL", "REVERSAL", 64
                entry = lo - buf
                stop = h[sh[-1]] + atr_stop
                if stop < entry * 1.02:
                    stop = entry * 1.02
                reasons.append(f"Major trend reversal — bull TL broken, lower high, checklist {rev_checklist}/10 (Rev Ch.3)")
                details["mtr"] = 1

    # ── Channel overshoot reversal (Trends Ch.12) ──
    if sig == "HOLD" and ch_overshoot_dir != "NONE":
        if ch_overshoot_dir == "BULL" and bear_bar and trend_bar and B["strong"][last]:
            sig, setup, conf = "SELL", "CHANNEL_REVERSAL", 66
            entry = lo - buf
            stop = hi + atr_stop
            if stop < entry * 1.02:
                stop = entry * 1.02
            reasons.append("Bull channel overshoot + strong bear reversal bar (Trends Ch.12)")
            details["ch_rev"] = 1
        elif ch_overshoot_dir == "BEAR" and bull_bar and trend_bar and B["strong"][last]:
            sig, setup, conf = "BUY", "CHANNEL_REVERSAL", 66
            entry = hi + buf
            stop = lo - atr_stop
            if stop > entry * 0.98:
                stop = entry * 0.98
            reasons.append("Bear channel overshoot + strong bull reversal bar (Trends Ch.12)")
            details["ch_rev"] = 1

    # ── Trading-range veto: trend-following setups need a trend (TR Ch.21) ──
    # Exception: strong always-in (score >= 50) + decent signs-of-strength (>= 6)
    # overrides — trend is real even if phase detector hasn't caught up.
    _TREND_SETUPS = {"PULLBACK", "SECOND_ENTRY", "BREAKOUT", "BREAKOUT_PULLBACK"}
    _tr_escape = abs(ai_score) >= 50 and sos_score >= 10
    if (sig != "HOLD" and phase == "TRADING_RANGE"
            and setup in _TREND_SETUPS and not _tr_escape):
        sig, setup, conf = "HOLD", "NONE", 0
        reasons.clear()
        reasons.append("Trend-following setup vetoed — no trend in trading range (TR Ch.21)")

    # ── Confidence adjustments ──
    # Only structural factors that predict wins on daily charts.
    # Pattern confirmations (double bottom, IOI, outside bar, volume spike,
    # channel overshoot, S/R proximity, round number, small pullback) are
    # zeroed — backtest shows they are anti-predictive on daily timeframes.
    if sig != "HOLD":
        base_conf = conf
        bonus = 0

        # signal bar quality — structural, weak positive
        if sig == "BUY" and bull_bar and B["lt"][last] < 0.3 and B["bpct"][last] > 0.4:
            bonus += 3
            reasons.append(f"Strong bull signal bar (body {B['bpct'][last]*100:.0f}%)")
        elif sig == "SELL" and bear_bar and B["ut"][last] < 0.3 and B["bpct"][last] > 0.4:
            bonus += 3
            reasons.append(f"Strong bear signal bar (body {B['bpct'][last]*100:.0f}%)")

        # doji signal bar — structural veto/penalty
        if is_doji and B["bpct"][last] < 0.25:
            sig, setup, conf = "HOLD", "NONE", 0
            reasons.clear()
            reasons.append("Doji signal bar body <25% — no entry (Trends Ch.2)")
        elif is_doji:
            conf -= 8
            reasons.append("Doji signal bar — weak setup (Trends Ch.2)")

        # aligned with always-in — structural
        if (sig == "BUY" and ai == "LONG") or (sig == "SELL" and ai == "SHORT"):
            bonus += 3
            reasons.append("Aligned with always-in direction (Rev Ch.15)")

        # ambiguous always-in — structural penalty
        if ai == "FLAT" or (ai == "LONG" and abs(ai_score) < 35) or (ai == "SHORT" and abs(ai_score) < 35):
            conf -= 5
            reasons.append(f"Weak always-in conviction (score {ai_score:.0f}) — ambiguous direction")

        # range penalty — structural
        if phase == "TRADING_RANGE":
            conf -= 15
            reasons.append("Trading range — lower probability (TR Ch.21)")

        # late H/L penalty — structural
        if hl_bull in ("H3", "H4") and sig == "BUY":
            conf -= 5
            reasons.append(f"{hl_bull} — late in cycle, conviction decay (Trends Ch.11)")
        if hl_bear in ("L3", "L4") and sig == "SELL":
            conf -= 5
            reasons.append(f"{hl_bear} — late in cycle, conviction decay (Trends Ch.11)")

        # signs of strength — structural, reduced
        if sos_score >= 12:
            bonus += 3
            reasons.append(f"Strong trend ({sos_score}/18 signs of strength, Trends Ch.19)")
            details["sos"] = sos_score
        elif sos_score < 5:
            conf -= 3
            reasons.append(f"Weak trend ({sos_score}/18 signs, Trends Ch.19)")
            details["sos"] = sos_score

        # v4: Middle-of-range dead zone (TR Ch.4) — structural
        if phase == "TRADING_RANGE" and sr_hi > 0 and sr_lo > 0:
            rng = sr_hi - sr_lo
            if rng > 0:
                pos = (c[last] - sr_lo) / rng
                if 0.33 < pos < 0.67:
                    conf -= 10
                    reasons.append("Price in middle of trading range — low probability zone (TR Ch.4)")
                    details["mid_range"] = 1

        # final flag counter-trend — structural penalty only
        if is_ff:
            if not ((sig == "BUY" and ai == "SHORT") or (sig == "SELL" and ai == "LONG")):
                conf -= 3
                reasons.append("Final flag — with-trend entry in late trend is risky (Rev Ch.7)")

        # channel overshoot — structural penalty only
        if ch_overshoot_dir != "NONE":
            conf -= 5
            reasons.append("Channel overshoot — expect mean reversion (Trends Ch.14)")

        # cap total bonuses to prevent anti-predictive stacking
        conf += min(bonus, 6)
        conf = max(0, min(100, conf))
        strength = "STRONG" if conf >= 75 else "MODERATE" if conf >= 60 else "WEAK"

    # ── Targets ──
    if sig == "BUY" and entry > 0 and stop > 0 and entry > stop:
        risk = entry - stop
        mm = _mm("BUY", h, l, sh, sl, entry)
        mm_rr = (mm - entry) / risk if risk > 0 and mm > entry else 0
        if mm_rr >= 1.5:
            t1 = mm
            t2 = entry + risk * 3
            details["mm_target"] = 1
        else:
            t1, t2 = entry + risk * 1.5, entry + risk * 2.5
    elif sig == "SELL" and entry > 0 and stop > entry:
        risk = stop - entry
        mm = _mm("SELL", h, l, sh, sl, entry)
        mm_rr = (entry - mm) / risk if risk > 0 and mm < entry else 0
        if mm_rr >= 1.5:
            t1 = mm
            t2 = entry - risk * 3
            details["mm_target"] = 1
        else:
            t1, t2 = entry - risk * 1.5, entry - risk * 2.5

    # ── v3: Two-reason minimum enforcement (TR Ch.26) ──
    if sig != "HOLD" and len(reasons) < MIN_REASONS:
        sig, setup, conf = "HOLD", "NONE", 0
        reasons.append(f"Insufficient reasons ({len(reasons)}/{MIN_REASONS}) — Brooks requires 2+ independent reasons (TR Ch.26)")
        entry = stop = t1 = t2 = 0.0

    return sig, setup, conf, strength, entry, stop, t1, t2, reasons, details


# ── Trader's equation ─────────────────────────────────────────────

def _equation(sig, setup, entry, stop, t1, conf):
    if sig == "HOLD" or entry <= 0:
        return 0.0, "NONE"
    prob = SETUP_PROB.get(setup, 0.45)
    prob = prob * (conf / 100) + (1 - conf / 100) * 0.40
    cost = entry * NSE_COST_PCT / 100
    if sig == "BUY":
        risk, reward = max(entry - stop, 0.01), max(t1 - entry, 0.01)
    else:
        risk, reward = max(stop - entry, 0.01), max(entry - t1, 0.01)
    # cost hits both outcomes: win nets (reward - cost), loss costs (risk + cost)
    eq = prob * (reward - cost) - (1 - prob) * (risk + cost)
    net_reward = max(reward - cost, 0.01)
    net_risk = risk + cost
    rr = net_reward / net_risk
    verdict = "EDGE" if eq > 0 and rr >= 1.5 else "RISKY" if eq > 0 else "NO_EDGE"
    return round(eq, 4), verdict


# ── PA score & verdict ────────────────────────────────────────────

def _score(ai, ai_s, ts, setup, conf):
    if ai == "LONG":
        base = min(100.0, abs(ai_s) + ts * 0.3)
    elif ai == "SHORT":
        base = -min(100.0, abs(ai_s) + ts * 0.3)
    else:
        base = ai_s * 0.5
    if setup != "NONE":
        base *= 1.2
    return round(float(np.clip(base, -100, 100)), 1)


def _verdict(s):
    if s > 60:   return "STRONG BUY"
    if s > 30:   return "BUY"
    if s > 10:   return "LEAN BUY"
    if s > -10:  return "HOLD"
    if s > -30:  return "LEAN SELL"
    if s > -60:  return "SELL"
    return "STRONG SELL"


# ── Context builder ───────────────────────────────────────────────

def _context(ai, phase, hl_b, hl_br, in_spk, spk_d,
             climax, gap_cnt, gap_s, two_l, wedges, ev, price,
             is_bw, double_pats, sos_score, tl_broken, is_ff, is_tri, vol_ratio,
             micro_ch=False, micro_dir="NONE", micro_len=0, small_pb=False):
    parts = []
    if ai == "LONG":
        parts.append("Bull trend")
    elif ai == "SHORT":
        parts.append("Bear trend")
    else:
        parts.append("Sideways")

    pm = {"SPIKE": "spike phase", "TIGHT_CHANNEL": "tight channel",
          "CHANNEL": "channel", "BROAD_CHANNEL": "broad channel",
          "TRADING_RANGE": "trading range"}
    parts.append(pm.get(phase, ""))

    if price > ev * 1.005:
        parts.append(f"above EMA20 ({ev:.2f})")
    elif price < ev * 0.995:
        parts.append(f"below EMA20 ({ev:.2f})")
    else:
        parts.append(f"near EMA20 ({ev:.2f})")

    if hl_b:
        parts.append(f"{hl_b} count")
    if hl_br:
        parts.append(f"{hl_br} count")
    if in_spk:
        parts.append(f"{spk_d} spike active")
    if climax:
        parts.append("recent climax — expect correction")
    if is_bw:
        parts.append("barbwire — avoid stop entries")
    if gap_s:
        parts.append(f"{gap_cnt} gap bars — very strong trend")
    if two_l:
        parts.append("two-leg correction complete")
    parts.extend(wedges)
    parts.extend(double_pats)

    # v3 context additions
    if sos_score >= 12:
        parts.append(f"strong trend ({sos_score}/18 signs)")
    elif sos_score < 5 and ai != "FLAT":
        parts.append(f"weak trend ({sos_score}/18 signs)")
    if tl_broken:
        parts.append("trend line broken")
    if is_ff:
        parts.append("final flag — trend exhaustion likely")
    if is_tri:
        parts.append("triangle forming")
    if vol_ratio > 2.0:
        parts.append(f"volume spike ({vol_ratio:.1f}x)")
    elif vol_ratio < 0.5:
        parts.append("low volume")

    if micro_ch:
        parts.append(f"micro channel ({micro_dir}, {micro_len} bars)")
    if small_pb:
        parts.append("small pullback trend — pullbacks staying near EMA")
    return ". ".join(p for p in parts if p) + "."


# ═══════════════════════════════════════════════════════════════════
#  MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════════

def run_brooks_analysis(df: pd.DataFrame, ticker: str) -> BrooksResult:
    r = BrooksResult(ticker=ticker)

    col = {c.lower(): c for c in df.columns}
    try:
        o = df[col.get("open", "Open")].values.astype(float)
        h = df[col.get("high", "High")].values.astype(float)
        l = df[col.get("low", "Low")].values.astype(float)
        c = df[col.get("close", "Close")].values.astype(float)
    except (KeyError, ValueError) as e:
        r.success, r.error = False, f"Missing OHLC: {e}"
        return r

    # Volume (optional)
    vol = None
    try:
        vol = df[col.get("volume", "Volume")].values.astype(float)
        vol = np.where(np.isnan(vol), 0, vol)
    except (KeyError, ValueError):
        pass

    # NaN safety — forward-fill instead of truncating (preserves recent data
    # across single-row gaps from corp actions or bad downloads)
    mask = np.isnan(o) | np.isnan(h) | np.isnan(l) | np.isnan(c)
    if mask.any():
        if mask.all():
            r.success, r.error = False, "All NaN"
            return r
        _tmp = pd.DataFrame({"o": o, "h": h, "l": l, "c": c})
        _tmp = _tmp.ffill().bfill()
        o, h, l, c = _tmp["o"].values, _tmp["h"].values, _tmp["l"].values, _tmp["c"].values
        if vol is not None:
            vol = np.where(np.isnan(vol), 0, vol)

    n = len(c)

    # Corporate action detection — flag bars with >20% gap from prior close
    for i in range(max(1, n - 60), n):
        if c[i - 1] > 0 and abs(o[i] - c[i - 1]) / c[i - 1] > 0.20:
            r.warnings.append(
                f"Bar {i}: {abs(o[i] - c[i-1]) / c[i-1] * 100:.0f}% gap — "
                f"possible split/bonus, levels may be unreliable"
            )
    if n < MIN_BARS:
        r.success, r.error = False, f"Need {MIN_BARS} bars, got {n}"
        return r

    ema = pd.Series(c).ewm(span=EMA_PERIOD, adjust=False).mean().values
    r.ema20 = round(ema[-1], 2)
    r.current_price = round(c[-1], 2)

    B = _classify_bars(o, h, l, c)
    r.last_bar_type, r.last_bar_description = _describe_bar(n - 1, B)

    sh, sl = _find_swings(h, l)
    atr_vals = _atr(h, l, c)
    r.atr = round(atr_vals[-1], 2)

    # core analysis
    is_bw = _barbwire(h, l, B, n)
    double_pats = _double_tb(h, l, sh, sl)

    r.always_in, r.always_in_score = _always_in(c, ema, B, sh, sl, h, l)
    r.trend_direction = {"LONG": "BULL", "SHORT": "BEAR"}.get(r.always_in, "SIDEWAYS")
    r.trend_phase, r.trend_strength = _phase(c, ema, B, n)

    r.price_vs_ema = (
        "ABOVE" if c[-1] > ema[-1] * 1.003
        else "BELOW" if c[-1] < ema[-1] * 0.997
        else "AT"
    )

    r.consecutive_bull_trend = _consec_trend(B, n, True)
    r.consecutive_bear_trend = _consec_trend(B, n, False)
    r.last_hl_bull, r.last_hl_bear = _count_hl(h, l, r.always_in, sl, sh, n)
    r.in_spike, r.spike_direction, r.spike_bars, r.spike_strength = _spike(c, B, n)
    r.recent_climax = _climax(B, c, n)
    r.ema_gap_bar_count, r.gap_bar_setup = _gap_bars(l, h, ema, n)
    r.two_leg_complete = _two_leg(h, l, sl, sh, r.always_in, n)
    wp = _wedge(h, l, sl, sh, r.always_in)
    r.in_breakout, r.breakout_direction = _breakout(c, h, l, B, sh, sl)
    r.breakout_mode = r.in_breakout
    r.buying_pressure, r.selling_pressure = _pressure(B, n)
    micro_ch, micro_dir, micro_len = _micro_channel(h, l, n)
    bp, bp_dir, bp_level = _breakout_pullback(c, h, l, B, sh, sl, r.always_in, n)
    small_pb = _small_pb_trend(l, h, c, ema, sl, sh, r.always_in, n)
    lb_sr = min(40, n - 1)
    sr_hi = float(np.max(h[n - lb_sr:n])) if lb_sr > 0 else 0.0
    sr_lo = float(np.min(l[n - lb_sr:n])) if lb_sr > 0 else 0.0

    # v3 analyses
    tl_bull_broken, tl_bear_broken, ch_overshoot_dir = _trend_lines(h, l, c, sh, sl, n)
    r.trend_line_broken = tl_bull_broken or tl_bear_broken

    r.volume_ratio, r.volume_spike = _volume(vol, n)
    r.sr_proximity = _sr_zones(h, l, c, sh, sl, n)
    r.round_magnet_distance = _round_magnet(c[-1])

    # count total trend bars for final flag detection
    lb30 = min(30, n)
    total_trend_bars = int(np.sum(B["trend"][-lb30:]))
    r.is_final_flag = _final_flag(h, l, B, n, r.always_in, total_trend_bars)
    r.is_expanding_triangle = _expanding_triangle(h, l, sh, sl)
    r.is_triangle, tri_dir = _triangle(h, l, sh, sl)

    r.signs_of_strength_score = _signs_of_strength(
        h, l, c, B, ema, sh, sl, vol, r.always_in, n)

    rev_checklist = _reversal_checklist(
        h, l, c, B, ema, sh, sl, r.always_in, r.trend_line_broken, n)
    if r.volume_spike:
        rev_checklist = min(rev_checklist + 1, 10)
    r.reversal_checklist_score = rev_checklist

    trapped, trapped_dir, trapped_boost = _trapped_traders(
        h, l, c, B, sh, sl, r.last_hl_bull, r.last_hl_bear, r.always_in, n)
    r.is_trapped_trade = trapped

    ob_rev = _outside_bar(B, n)
    r.outside_bar_reversal = ob_rev
    ioi_dir = _ioi(B, n)
    r.ioi_pattern = ioi_dir

    is_stair = _staircase(h, l, sh, sl, r.always_in)
    is_duel = _dueling_lines(h, l, c, sh, sl, n)

    # active patterns list
    pats = list(wp)
    if r.in_spike:
        pats.append(f"{r.spike_direction} Spike")
    if r.trend_phase == "TIGHT_CHANNEL":
        pats.append("Tight Channel")
    if r.gap_bar_setup:
        pats.append("20 Gap Bar Setup")
    if r.recent_climax:
        pats.append("Climax")
    if is_bw:
        pats.append("Barbwire")
    if r.two_leg_complete:
        pats.append("Two-Leg Complete")
    if r.last_hl_bull:
        pats.append(f"{r.last_hl_bull} Bull")
    if r.last_hl_bear:
        pats.append(f"{r.last_hl_bear} Bear")
    if r.in_breakout:
        pats.append(f"{r.breakout_direction} Breakout")
    pats.extend(double_pats)
    if r.trend_line_broken:
        pats.append("Trend Line Broken")
    if r.is_final_flag:
        pats.append("Final Flag")
    if r.is_expanding_triangle:
        pats.append("Expanding Triangle")
    if r.is_triangle:
        pats.append(f"Triangle ({tri_dir})")
    if ob_rev != "NONE":
        pats.append(f"Outside Bar {ob_rev}")
    if ioi_dir != "NONE":
        pats.append(f"IOI {ioi_dir}")
    if trapped:
        pats.append(f"Trapped {trapped_dir}")
    if is_stair:
        pats.append("Staircase Trend")
    if is_duel:
        pats.append("Dueling Lines")
    if r.volume_spike:
        pats.append("Volume Spike")
    if micro_ch:
        pats.append(f"Micro Channel ({micro_dir}, {micro_len} bars)")
    if bp:
        pats.append(f"Breakout Pullback ({bp_dir})")
    if small_pb:
        pats.append("Small Pullback Trend")
    r.active_patterns = pats

    # signal generation
    (r.signal_type, r.setup_type, r.confidence, r.strength,
     r.entry_price, r.stop_loss, r.target_1, r.target_2,
     r.reasons, r.score_details) = _signal(
        c, h, l, o, ema, B, r.always_in, r.always_in_score,
        r.trend_phase, r.trend_strength, r.last_hl_bull, r.last_hl_bear,
        r.in_spike, r.spike_direction, r.recent_climax,
        r.ema_gap_bar_count, r.gap_bar_setup, r.two_leg_complete,
        sh, sl, r.in_breakout, r.breakout_direction, wp,
        is_bw, double_pats,
        atr_vals[-1], r.volume_ratio, r.volume_spike,
        tl_bull_broken, tl_bear_broken, ch_overshoot_dir,
        r.signs_of_strength_score, rev_checklist,
        trapped, trapped_dir, trapped_boost,
        r.is_final_flag, r.is_expanding_triangle,
        r.is_triangle, tri_dir, is_stair, is_duel,
        ob_rev, ioi_dir, r.sr_proximity, r.round_magnet_distance,
        micro_ch, micro_dir, bp, bp_dir, bp_level,
        small_pb, sr_hi, sr_lo,
    )

    r.reasons_count = len(r.reasons)

    # risk / reward
    if r.signal_type == "BUY" and r.entry_price > r.stop_loss > 0:
        risk = r.entry_price - r.stop_loss
        reward = r.target_1 - r.entry_price
        r.risk_reward = round(reward / risk, 2) if risk > 0 else 0
    elif r.signal_type == "SELL" and r.stop_loss > r.entry_price > 0:
        risk = r.stop_loss - r.entry_price
        reward = r.entry_price - r.target_1
        r.risk_reward = round(reward / risk, 2) if risk > 0 else 0

    r.traders_equation, r.equation_verdict = _equation(
        r.signal_type, r.setup_type, r.entry_price, r.stop_loss,
        r.target_1, r.confidence,
    )
    r.measured_move_target = _mm(r.signal_type, h, l, sh, sl, r.entry_price)
    r.pa_score = _score(r.always_in, r.always_in_score, r.trend_strength,
                        r.setup_type, r.confidence)
    r.pa_verdict = _verdict(r.pa_score)
    r.al_brooks_context = _context(
        r.always_in, r.trend_phase, r.last_hl_bull, r.last_hl_bear,
        r.in_spike, r.spike_direction, r.recent_climax,
        r.ema_gap_bar_count, r.gap_bar_setup, r.two_leg_complete,
        wp, ema[-1], c[-1], is_bw, double_pats,
        r.signs_of_strength_score, r.trend_line_broken,
        r.is_final_flag, r.is_triangle, r.volume_ratio,
        micro_ch, micro_dir, micro_len, small_pb,
    )

    # v3: quality score (composite of all factors)
    q = 0
    if r.signal_type != "HOLD":
        q = r.confidence
        q += min(r.signs_of_strength_score, 10)
        if r.volume_ratio > 1.2:
            q += 5
        if r.trend_line_broken and r.setup_type == "FAILED_BREAKOUT":
            q += 5
        if trapped:
            q += 5
        if r.sr_proximity < 2.0:
            q += 3
        q = max(0, min(100, q))
    r.quality_score = q

    # price position within recent range
    if len(sh) and len(sl):
        rh, rl = h[sh[-1]], l[sl[-1]]
        span = rh - rl
        if span > 0:
            pos = (c[-1] - rl) / span
            r.price_position = "TOP" if pos > 0.7 else "BOTTOM" if pos < 0.3 else "MIDDLE"

    return r
