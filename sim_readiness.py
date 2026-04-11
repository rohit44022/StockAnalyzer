#!/usr/bin/env python3
"""
sim_readiness.py — Triple Conviction Engine & Portfolio Tracker Readiness Simulation.

Deeply validates every data field that flows from the backend engines into the
portfolio UI, including:
  • Triple Conviction Engine (BB + TA + PA scores, verdict, alignment)
  • Wyckoff / Villahermosa Volume Analysis (phase, sub_phase, bias, events, volume)
  • Dalton Market Profile (day_type, activity, market_structure, VA seq, signals, high-prob)
  • Price Action (Al Brooks) (signal, trend, patterns, targets, reasons)
  • Portfolio Analyzer (analyze_position end-to-end with multi_system)
  • Flask API endpoint (/api/portfolio/<pid>/analyze)

Usage:  python3 sim_readiness.py [--tickers N] [--api]
"""

import sys, os, json, time, traceback, math, argparse, random
from datetime import datetime, date, timedelta
from collections import Counter, defaultdict

import pandas as pd
import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from bb_squeeze.data_loader import load_stock_data, get_all_tickers_from_csv, normalise_ticker
from bb_squeeze.indicators import compute_all_indicators
from bb_squeeze.portfolio_analyzer import analyze_position
from bb_squeeze.config import CSV_DIR
from hybrid_pa_engine import run_triple_analysis
from price_action.engine import run_price_action_analysis

# ═══════════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════════
SEPARATOR = "═" * 80
SUBSEP = "─" * 80


class Result:
    """Test result accumulator."""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.warned = 0
        self.errors = []   # (section, ticker, severity, message)
        self.stats = {}    # distribution counters

    def ok(self, section, ticker, msg=""):
        self.passed += 1

    def fail(self, section, ticker, msg):
        self.failed += 1
        self.errors.append((section, ticker, "FAIL", msg))

    def warn(self, section, ticker, msg):
        self.warned += 1
        self.errors.append((section, ticker, "WARN", msg))

    def stat(self, category, value):
        self.stats.setdefault(category, Counter())
        self.stats[category][str(value)] += 1

    @property
    def total(self):
        return self.passed + self.failed

    @property
    def pass_rate(self):
        return self.passed / self.total * 100 if self.total else 0


def _check(r, section, ticker, condition, pass_msg, fail_msg):
    if condition:
        r.ok(section, ticker, pass_msg)
    else:
        r.fail(section, ticker, fail_msg)
    return condition


def _check_range(r, section, ticker, val, name, lo, hi):
    if val is None or (isinstance(val, float) and (math.isnan(val) or math.isinf(val))):
        r.fail(section, ticker, f"{name} is None/NaN/Inf")
        return False
    if not (lo <= val <= hi):
        r.fail(section, ticker, f"{name}={val} out of [{lo}, {hi}]")
        return False
    r.ok(section, ticker, f"{name}={val}")
    return True


def _check_in(r, section, ticker, val, name, valid_set):
    if val in valid_set:
        r.ok(section, ticker, f"{name}={val}")
        return True
    r.fail(section, ticker, f"{name}='{val}' not in {valid_set}")
    return False


# ═══════════════════════════════════════════════════════════════
#  TEST 1: TRIPLE CONVICTION ENGINE — DEEP VALIDATION
# ═══════════════════════════════════════════════════════════════
def test_triple_engine(ticker, df, r):
    SEC = "triple_engine"
    try:
        result = run_triple_analysis(df.copy(), ticker=normalise_ticker(ticker))
    except Exception as ex:
        r.fail(SEC, ticker, f"CRASH: {ex}")
        return None

    _check(r, SEC, ticker, isinstance(result, dict), "returns dict", "result is not dict")
    if not isinstance(result, dict):
        return None

    _check(r, SEC, ticker, "error" not in result or result["error"] is None,
           "no error", f"error: {result.get('error')}")

    # ── Triple Verdict ──
    tv = result.get("triple_verdict", {})
    _check(r, SEC, ticker, isinstance(tv, dict), "triple_verdict is dict", "triple_verdict missing/not dict")

    VALID_VERDICTS = {"SUPER STRONG BUY", "STRONG BUY", "BUY", "HOLD / WAIT",
                      "WEAK HOLD", "HOLD", "SELL", "STRONG SELL", "SUPER STRONG SELL"}
    verdict = tv.get("verdict", "")
    _check_in(r, SEC, ticker, verdict, "verdict", VALID_VERDICTS)
    r.stat("triple_verdict", verdict)

    _check_range(r, SEC, ticker, tv.get("score", 0), "score", -425, 425)
    _check_range(r, SEC, ticker, tv.get("confidence", -1), "confidence", 0, 100)
    _check(r, SEC, ticker, tv.get("max_score") is not None, "max_score present", "max_score missing")

    VALID_ALIGN = {"TRIPLE_ALIGNED", "DOUBLE_ALIGNED", "CONFLICTING", "ALL_NEUTRAL",
                   "SINGLE", "MIXED", "SINGLE_ALIGNED"}
    alignment = tv.get("alignment", "")
    _check_in(r, SEC, ticker, alignment, "alignment", VALID_ALIGN)
    r.stat("alignment", alignment)

    # ── Component Scores ──
    for comp in ["bb_score", "ta_score", "pa_score"]:
        cs = result.get(comp)
        _check(r, SEC, ticker, isinstance(cs, dict), f"{comp} is dict", f"{comp} missing/not dict")
        if isinstance(cs, dict):
            total = cs.get("total", None)
            _check_range(r, SEC, ticker, total, f"{comp}.total", -100, 100)

    # ── Cross Validation ──
    cv = result.get("cross_validation")
    _check(r, SEC, ticker, isinstance(cv, dict), "cross_validation is dict", "cross_validation missing")
    if isinstance(cv, dict):
        for dir_key in ["bb_direction", "ta_direction", "pa_direction"]:
            _check_in(r, SEC, ticker, cv.get(dir_key, ""), dir_key,
                      {"BULLISH", "BEARISH", "NEUTRAL"})
        _check(r, SEC, ticker, isinstance(cv.get("observations"), list),
               "observations is list", "observations not list")
        wyb = cv.get("wyckoff_bonus", 0)
        _check_range(r, SEC, ticker, wyb, "wyckoff_bonus", -50, 50)
        dab = cv.get("dalton_bonus", 0)
        _check_range(r, SEC, ticker, dab, "dalton_bonus", -50, 50)
        _check_in(r, SEC, ticker, cv.get("alignment", ""), "cv.alignment",
                  {"TRIPLE_ALIGNED", "DOUBLE_ALIGNED", "CONFLICTING", "ALL_NEUTRAL",
                   "SINGLE", "MIXED", "SINGLE_ALIGNED"})
        _check_in(r, SEC, ticker, cv.get("wyckoff_bias", ""), "cv.wyckoff_bias",
                  {"BULLISH", "BEARISH", "NEUTRAL"})
        sys_aligned = cv.get("systems_aligned", 0)
        _check_range(r, SEC, ticker, sys_aligned, "cv.systems_aligned", -3, 3)
        # Dalton signals list
        dsigs = cv.get("dalton_signals")
        _check(r, SEC, ticker, isinstance(dsigs, (list, type(None))),
               f"cv.dalton_signals ({len(dsigs or [])})", "cv.dalton_signals wrong type")

    # ── Data Freshness ──
    df_info = result.get("data_freshness")
    _check(r, SEC, ticker, isinstance(df_info, dict), "data_freshness present", "data_freshness missing")
    if isinstance(df_info, dict):
        _check(r, SEC, ticker, "last_date" in df_info, "last_date present", "last_date missing")
        _check(r, SEC, ticker, "is_stale" in df_info, "is_stale present", "is_stale missing")

    # ── JSON Serializable ──
    try:
        json.dumps(result, default=str)
        r.ok(SEC, ticker, "JSON serializable")
    except Exception as ex:
        r.fail(SEC, ticker, f"NOT JSON serializable: {ex}")

    return result


# ═══════════════════════════════════════════════════════════════
#  TEST 2: WYCKOFF / VILLAHERMOSA — DEEP VALIDATION
# ═══════════════════════════════════════════════════════════════
def test_wyckoff(ticker, triple_result, r):
    SEC = "wyckoff"
    wk = triple_result.get("wyckoff")
    if wk is None:
        r.warn(SEC, ticker, "No wyckoff block in triple result")
        return

    _check(r, SEC, ticker, isinstance(wk, dict), "wyckoff is dict", "wyckoff not dict")

    # Phase block — is a dict with name, sub_phase, confidence, events
    phase_block = wk.get("phase", {})
    _check(r, SEC, ticker, isinstance(phase_block, dict), "phase is dict", "phase not dict")
    if isinstance(phase_block, dict):
        VALID_PHASES = {"ACCUMULATION", "MARKUP", "DISTRIBUTION", "MARKDOWN",
                        "RANGING", "UNKNOWN"}
        phase_name = phase_block.get("name", "")
        _check_in(r, SEC, ticker, phase_name, "phase.name", VALID_PHASES)
        r.stat("wyckoff_phase", phase_name)

        VALID_SUB = {"EARLY", "MIDDLE", "LATE", "CONFIRMED", "DEFAULT", "N/A",
                     "CONSOLIDATION", "TRANSITIONING", "", None}
        sub = phase_block.get("sub_phase", "")
        if sub not in VALID_SUB:
            r.warn(SEC, ticker, f"Unusual sub_phase: '{sub}'")
        else:
            r.ok(SEC, ticker, f"sub_phase={sub}")

        _check_range(r, SEC, ticker, phase_block.get("confidence", -1), "phase.confidence", 0, 100)

        # Events list (inside phase block)
        events = phase_block.get("events")
        _check(r, SEC, ticker, isinstance(events, (list, type(None))),
               f"phase.events ({len(events or [])} items)", "phase.events wrong type")
        if isinstance(events, list):
            r.stat("wk_events_count", len(events))
    else:
        r.stat("wyckoff_phase", "MISSING")

    # Scoring block — has wyckoff_bonus and bias
    scoring = wk.get("scoring", {})
    _check(r, SEC, ticker, isinstance(scoring, dict), "scoring is dict", "scoring missing")
    if isinstance(scoring, dict):
        VALID_BIAS = {"BULLISH", "BEARISH", "NEUTRAL"}
        bias = scoring.get("bias", "")
        _check_in(r, SEC, ticker, bias, "scoring.bias", VALID_BIAS)
        r.stat("wyckoff_bias", bias)

        bonus = scoring.get("wyckoff_bonus", 0)
        _check_range(r, SEC, ticker, bonus, "wyckoff_bonus", -50, 50)

    # Volume story
    vol = wk.get("volume")
    _check(r, SEC, ticker, isinstance(vol, dict), "volume block present", "volume missing")
    if isinstance(vol, dict):
        _check(r, SEC, ticker, vol.get("status") is not None, f"vol.status={vol.get('status')}", "vol.status missing")

    # Wave balance
    wb = wk.get("wave_balance")
    _check(r, SEC, ticker, isinstance(wb, dict), "wave_balance present", "wave_balance missing")

    # Shortening of thrust
    sot = wk.get("shortening")
    _check(r, SEC, ticker, isinstance(sot, dict), "shortening present", "shortening missing")
    if isinstance(sot, dict):
        _check(r, SEC, ticker, isinstance(sot.get("detected"), bool),
               f"shortening.detected={sot.get('detected')}", "shortening.detected not bool")

    # Summary string
    _check(r, SEC, ticker, isinstance(wk.get("summary"), str),
           "summary is string", "summary missing/not string")

    # Hints
    hints = wk.get("hints")
    _check(r, SEC, ticker, isinstance(hints, (list, type(None))),
           f"hints ({len(hints or [])})", "hints wrong type")


# ═══════════════════════════════════════════════════════════════
#  TEST 3: DALTON MARKET PROFILE — DEEP VALIDATION
# ═══════════════════════════════════════════════════════════════
def test_dalton(ticker, triple_result, r):
    SEC = "dalton"
    mp = triple_result.get("market_profile")
    if mp is None:
        r.warn(SEC, ticker, "No market_profile block in triple result")
        return

    _check(r, SEC, ticker, isinstance(mp, dict), "market_profile is dict", "not dict")

    # Day Type
    dt = mp.get("day_type")
    _check(r, SEC, ticker, isinstance(dt, dict), "day_type is dict", "day_type not dict")
    if isinstance(dt, dict):
        VALID_DAYTYPES = {"NONTREND", "NEUTRAL", "NEUTRAL_EXTREME", "NORMAL",
                          "NORMAL_VARIATION", "TREND", "DOUBLE_DIST"}
        _check_in(r, SEC, ticker, dt.get("type", ""), "day_type.type", VALID_DAYTYPES)
        r.stat("day_type", dt.get("type", ""))

        VALID_CONV = {"LOW", "MODERATE", "HIGH", "VERY_HIGH"}
        _check_in(r, SEC, ticker, dt.get("conviction", ""), "conviction", VALID_CONV)
        r.stat("day_conviction", dt.get("conviction", ""))

    # Open Type
    VALID_OPEN = {"OPEN_DRIVE", "OPEN_TEST_DRIVE", "OPEN_REJECTION_REVERSE",
                  "OPEN_AUCTION", "UNKNOWN"}
    ot = mp.get("open_type", "UNKNOWN")
    _check_in(r, SEC, ticker, ot, "open_type", VALID_OPEN)
    r.stat("open_type", ot)

    # Activity
    VALID_ACT = {"INITIATIVE_BUYING", "INITIATIVE_SELLING",
                 "RESPONSIVE_BUYING", "RESPONSIVE_SELLING", "MIXED"}
    act = mp.get("activity", "MIXED")
    _check_in(r, SEC, ticker, act, "activity", VALID_ACT)
    r.stat("activity", act)

    # Market Structure
    ms = mp.get("market_structure")
    _check(r, SEC, ticker, isinstance(ms, dict), "market_structure is dict", "market_structure not dict")
    if isinstance(ms, dict):
        VALID_MS = {"TRENDING_UP", "TRENDING_DOWN", "BRACKETING", "TRANSITIONING"}
        _check_in(r, SEC, ticker, ms.get("type", ""), "market_structure.type", VALID_MS)
        r.stat("market_structure", ms.get("type", ""))
        bd = ms.get("bracket_days", 0)
        _check(r, SEC, ticker, isinstance(bd, (int, float)) and bd >= 0,
               f"bracket_days={bd}", f"bracket_days invalid: {bd}")

    # One-Timeframing
    otf = mp.get("one_timeframing")
    _check(r, SEC, ticker, isinstance(otf, dict), "OTF is dict", "OTF missing")
    if isinstance(otf, dict):
        VALID_OTF_DIR = {"UP", "DOWN", "NONE"}
        _check_in(r, SEC, ticker, otf.get("direction", "NONE"), "OTF.direction", VALID_OTF_DIR)
        r.stat("otf_direction", otf.get("direction", "NONE"))
        days = otf.get("days", 0)
        _check(r, SEC, ticker, isinstance(days, (int, float)) and days >= 0,
               f"OTF.days={days}", f"OTF.days invalid: {days}")

    # Directional Performance
    dp = mp.get("directional_performance")
    _check(r, SEC, ticker, isinstance(dp, dict), "dir_perf is dict", "dir_perf missing")
    if isinstance(dp, dict):
        VALID_DP_DIR = {"UP", "DOWN", "NEUTRAL"}
        _check_in(r, SEC, ticker, dp.get("direction", ""), "dp.direction", VALID_DP_DIR)
        VALID_DP_RAT = {"VERY_STRONG", "STRONG", "MODERATE", "WEAK", "VERY_WEAK", "NEUTRAL"}
        _check_in(r, SEC, ticker, dp.get("rating", ""), "dp.rating", VALID_DP_RAT)
        r.stat("dp_rating", dp.get("rating", ""))

    # POC Migration
    VALID_POC = {"MIGRATING_UP", "MIGRATING_DOWN", "STATIONARY"}
    poc = mp.get("poc_migration", "STATIONARY")
    _check_in(r, SEC, ticker, poc, "poc_migration", VALID_POC)
    r.stat("poc_migration", poc)

    # VA Sequence
    va_seq = mp.get("va_sequence")
    _check(r, SEC, ticker, isinstance(va_seq, list), "va_sequence is list", "va_sequence not list")
    if isinstance(va_seq, list) and va_seq:
        VALID_VA = {"HIGHER", "LOWER", "OVERLAPPING", "OUTSIDE", "INSIDE"}
        for i, v in enumerate(va_seq):
            if v not in VALID_VA:
                r.fail(SEC, ticker, f"va_sequence[{i}]='{v}' invalid")
                break
        else:
            r.ok(SEC, ticker, f"va_sequence OK ({len(va_seq)} items)")
            # Track the last item
            r.stat("va_last", va_seq[-1] if va_seq else "EMPTY")

    # Profile Shape
    VALID_PS = {"NORMAL", "P_SHAPE", "B_SHAPE", "D_SHAPE", "ELONGATED"}
    ps = mp.get("profile_shape", "NORMAL")
    _check_in(r, SEC, ticker, ps, "profile_shape", VALID_PS)
    r.stat("profile_shape", ps)

    # Overnight Inventory
    VALID_OI = {"LONG", "SHORT", "NEUTRAL"}
    oi = mp.get("overnight_inventory", "NEUTRAL")
    _check_in(r, SEC, ticker, oi, "overnight_inventory", VALID_OI)
    r.stat("overnight_inv", oi)

    # Rotation Factor
    rf = mp.get("rotation_factor", 0)
    _check_range(r, SEC, ticker, rf, "rotation_factor", -30, 30)

    # Poor Extremes
    pe = mp.get("poor_extremes")
    _check(r, SEC, ticker, isinstance(pe, dict), "poor_extremes is dict", "poor_extremes missing")
    if isinstance(pe, dict):
        _check(r, SEC, ticker, isinstance(pe.get("poor_high"), bool),
               f"poor_high={pe.get('poor_high')}", "poor_high not bool")
        _check(r, SEC, ticker, isinstance(pe.get("poor_low"), bool),
               f"poor_low={pe.get('poor_low')}", "poor_low not bool")

    # High Probability Setups
    hp = mp.get("high_probability")
    _check(r, SEC, ticker, isinstance(hp, dict), "high_probability is dict", "high_probability missing")
    if isinstance(hp, dict):
        for setup_name in ["three_to_i", "neutral_extreme", "balance_breakout"]:
            sp = hp.get(setup_name)
            _check(r, SEC, ticker, isinstance(sp, dict),
                   f"{setup_name} is dict", f"{setup_name} missing")
            if isinstance(sp, dict):
                _check(r, SEC, ticker, isinstance(sp.get("active"), bool),
                       f"{setup_name}.active={sp.get('active')}", f"{setup_name}.active not bool")
                if sp.get("active"):
                    r.stat(f"hp_{setup_name}", sp.get("direction", "UNKNOWN"))

    # Gap
    gap = mp.get("gap")
    _check(r, SEC, ticker, isinstance(gap, dict), "gap is dict", "gap missing")
    if isinstance(gap, dict):
        VALID_GAP = {"BREAKAWAY", "ACCELERATION", "EXHAUSTION", "COMMON", "NONE", None}
        gt = gap.get("type", "NONE")
        if gt not in VALID_GAP:
            r.warn(SEC, ticker, f"Unusual gap.type: '{gt}'")
        else:
            r.ok(SEC, ticker, f"gap.type={gt}")
        if gt and gt != "NONE":
            r.stat("gap_type", gt)

    # Dalton Signals
    dsigs = mp.get("dalton_signals")
    _check(r, SEC, ticker, isinstance(dsigs, (list, type(None))),
           f"dalton_signals list ({len(dsigs or [])} items)", "dalton_signals wrong type")
    if isinstance(dsigs, list):
        for sig in dsigs:
            _check(r, SEC, ticker, isinstance(sig, dict) and "type" in sig,
                   f"signal has type: {sig.get('type')}", f"signal missing type: {sig}")
        r.stat("dalton_signals_count", len(dsigs))

    # CV Bonus
    scoring = mp.get("scoring", mp)
    cvb = scoring.get("cv_bonus", 0)
    _check_range(r, SEC, ticker, cvb, "cv_bonus", -50, 50)

    # Value Area
    va = mp.get("value_area")
    if isinstance(va, dict):
        val = va.get("va_low")
        vah = va.get("va_high")
        poc_v = va.get("poc")
        if val and vah:
            _check(r, SEC, ticker, val <= vah, f"VA: {val} <= {vah} ✓",
                   f"VA inverted: val={val} > vah={vah}")
        if poc_v and val and vah:
            _check(r, SEC, ticker, val <= poc_v <= vah,
                   f"POC {poc_v} within VA ✓",
                   f"POC {poc_v} outside VA [{val}, {vah}]")


# ═══════════════════════════════════════════════════════════════
#  TEST 4: PRICE ACTION (AL BROOKS) — DEEP VALIDATION
# ═══════════════════════════════════════════════════════════════
def test_price_action(ticker, df, r):
    SEC = "price_action"
    try:
        pa_result = run_price_action_analysis(df.copy(), ticker=normalise_ticker(ticker))
    except Exception as ex:
        r.fail(SEC, ticker, f"CRASH: {ex}")
        return None

    _check(r, SEC, ticker, pa_result is not None, "result not None", "result is None")
    if pa_result is None:
        return None

    # Signal Type
    VALID_SIG = {"BUY", "SELL", "HOLD"}
    sig = getattr(pa_result, "signal_type", None)
    _check_in(r, SEC, ticker, sig, "signal_type", VALID_SIG)
    r.stat("pa_signal", sig)

    # Setup Type
    setup = getattr(pa_result, "setup_type", None)
    _check(r, SEC, ticker, setup is not None, f"setup_type={setup}", "setup_type missing")
    if setup:
        r.stat("pa_setup", setup)

    # PA Verdict
    pa_verdict = getattr(pa_result, "pa_verdict", None)
    _check_in(r, SEC, ticker, pa_verdict, "pa_verdict",
              {"BUY", "SELL", "HOLD", "STRONG BUY", "STRONG SELL", "WEAK BUY", "WEAK SELL"})

    # Trend direction + phase
    VALID_TREND_DIR = {"BULL", "BEAR", "FLAT", "RANGING", "SIDEWAYS", None}
    trend_dir = getattr(pa_result, "trend_direction", None)
    _check(r, SEC, ticker, trend_dir in VALID_TREND_DIR, f"trend_direction={trend_dir}",
           f"trend_direction invalid: {trend_dir}")
    r.stat("pa_trend_dir", trend_dir)

    trend_phase = getattr(pa_result, "trend_phase", None)
    VALID_PHASE = {"CHANNEL", "TIGHT_CHANNEL", "BROAD_CHANNEL", "BREAKOUT",
                   "TRADING_RANGE", "CLIMAX", "PULLBACK", "SPIKE", None}
    if trend_phase and trend_phase not in VALID_PHASE:
        r.warn(SEC, ticker, f"Unusual trend_phase: '{trend_phase}'")
    else:
        r.ok(SEC, ticker, f"trend_phase={trend_phase}")
    r.stat("pa_trend_phase", trend_phase)

    # Strength
    VALID_STR = {"STRONG", "MODERATE", "WEAK", "NONE", None}
    strength = getattr(pa_result, "strength", None)
    _check(r, SEC, ticker, strength in VALID_STR, f"strength={strength}", f"strength invalid: {strength}")

    # Confidence
    conf = getattr(pa_result, "confidence", -1) or 0
    _check_range(r, SEC, ticker, conf, "confidence", 0, 100)

    # Always-In
    VALID_AI = {"LONG", "SHORT", "FLAT", None}
    ai = getattr(pa_result, "always_in", None)
    _check(r, SEC, ticker, ai in VALID_AI, f"always_in={ai}", f"always_in invalid: {ai}")
    r.stat("pa_always_in", ai)

    # Always-In Score
    ai_score = getattr(pa_result, "always_in_score", 0) or 0
    _check_range(r, SEC, ticker, ai_score, "always_in_score", -100, 100)

    # Score
    pa_score = getattr(pa_result, "pa_score", 0) or 0
    _check_range(r, SEC, ticker, pa_score, "pa_score", -100, 100)

    # Pressure
    bp = getattr(pa_result, "buying_pressure", 0) or 0
    sp = getattr(pa_result, "selling_pressure", 0) or 0
    _check_range(r, SEC, ticker, bp, "buying_pressure", 0, 100)
    _check_range(r, SEC, ticker, sp, "selling_pressure", 0, 100)
    total_pressure = bp + sp
    if total_pressure > 0:
        _check(r, SEC, ticker, 95 <= total_pressure <= 105,
               f"pressure sum={total_pressure:.1f}", f"pressure sum far from 100: {total_pressure}")

    # Last Bar
    lbt = getattr(pa_result, "last_bar_type", None)
    _check(r, SEC, ticker, lbt is not None, f"last_bar_type={lbt}", "last_bar_type missing")
    r.stat("pa_bar_type", lbt)

    # Patterns
    patterns = getattr(pa_result, "active_patterns", []) or []
    _check(r, SEC, ticker, isinstance(patterns, list), f"patterns list ({len(patterns)})", "patterns not list")
    r.stat("pa_pattern_count", min(len(patterns), 5))

    # Targets
    sl = getattr(pa_result, "stop_loss", None)
    t1 = getattr(pa_result, "target_1", None)
    t2 = getattr(pa_result, "target_2", None)
    cp = getattr(pa_result, "current_price", None)
    if sl and t1 and cp:
        _check(r, SEC, ticker, sl > 0 and t1 > 0, f"SL={sl:.2f} T1={t1:.2f}", "negative target")
    else:
        r.warn(SEC, ticker, "PA targets not available")

    # Risk Reward
    rr = getattr(pa_result, "risk_reward", 0) or 0
    _check(r, SEC, ticker, rr >= 0, f"risk_reward={rr:.2f}", f"negative risk_reward: {rr}")

    # Reasons
    reasons = getattr(pa_result, "reasons", []) or []
    _check(r, SEC, ticker, isinstance(reasons, list) and len(reasons) > 0,
           f"reasons ({len(reasons)} items)", "reasons empty")

    # Two-leg move
    tlc = getattr(pa_result, "two_leg_complete", None)
    _check(r, SEC, ticker, isinstance(tlc, bool), f"two_leg_complete={tlc}", "two_leg_complete not bool")

    # Score details
    sd = getattr(pa_result, "score_details", None)
    _check(r, SEC, ticker, isinstance(sd, dict), f"score_details ({len(sd or {})} keys)",
           "score_details missing")

    return pa_result


# ═══════════════════════════════════════════════════════════════
#  TEST 5: PORTFOLIO ANALYZER — END-TO-END WITH MULTI_SYSTEM
# ═══════════════════════════════════════════════════════════════
def test_portfolio_analyzer(ticker, df_bb, r):
    SEC = "portfolio_analyzer"

    last = df_bb.iloc[-1]
    mid_price = float(last.get("BB_Mid", last["Close"]))
    buy_date = (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")

    for strat in ["M1", "M2"]:
        position = {
            "id": 9999, "ticker": ticker, "strategy_code": strat,
            "buy_price": round(mid_price, 2), "buy_date": buy_date,
            "quantity": 10, "status": "OPEN", "notes": "readiness_sim",
        }

        try:
            analysis = analyze_position(position)
        except Exception as ex:
            r.fail(SEC, ticker, f"CRASH ({strat}): {ex}")
            continue

        if not isinstance(analysis, dict):
            r.fail(SEC, ticker, f"not dict ({strat})")
            continue

        if analysis.get("error"):
            r.fail(SEC, ticker, f"error ({strat}): {analysis['error']}")
            continue

        r.ok(SEC, ticker, f"analyze_position({strat}) OK")

        # Recommendation
        rec = analysis.get("recommendation", {})
        action = rec.get("action", "")
        VALID_ACT = {"HOLD", "SELL", "ADD", "STRONG SELL", "STRONG HOLD", "BOOK PARTIAL", "EXIT"}
        if action:
            _check_in(r, SEC, ticker, action, f"rec.action({strat})", VALID_ACT)
            r.stat("rec_action", action)
        strength = rec.get("strength")
        if strength:
            _check_in(r, SEC, ticker, strength, f"rec.strength({strat})",
                      {"STRONG", "MODERATE", "WEAK"})

        # Targets
        tgts = analysis.get("targets", {})
        cp = tgts.get("current_price")
        if cp:
            _check(r, SEC, ticker, cp > 0, f"current_price={cp:.2f}", f"current_price invalid: {cp}")

        # Holding info
        hold = analysis.get("holding", analysis.get("holding_info", {}))
        if isinstance(hold, dict):
            days = hold.get("days", hold.get("days_held"))
            if days is not None:
                _check(r, SEC, ticker, days >= 0, f"days_held={days}", f"days_held negative: {days}")

        # ── MULTI-SYSTEM BLOCK (crucial for UI) ──
        ms = analysis.get("multi_system")
        _check(r, SEC, ticker, isinstance(ms, dict),
               "multi_system present", "multi_system MISSING — UI will break!")
        if not isinstance(ms, dict):
            continue

        # Triple within multi_system
        triple = ms.get("triple", {})
        _check(r, SEC, ticker, triple.get("verdict") is not None,
               f"triple.verdict={triple.get('verdict')}", "triple.verdict missing in multi_system")
        _check(r, SEC, ticker, triple.get("score") is not None,
               f"triple.score={triple.get('score')}", "triple.score missing in multi_system")
        tb = triple.get("bb_score")
        tt = triple.get("ta_score")
        tp = triple.get("pa_score")
        _check(r, SEC, ticker, tb is not None, f"triple.bb_score={tb}", "bb_score missing")
        _check(r, SEC, ticker, tt is not None, f"triple.ta_score={tt}", "ta_score missing")
        _check(r, SEC, ticker, tp is not None, f"triple.pa_score={tp}", "pa_score missing")

        # Price Action within multi_system
        pa = ms.get("price_action", {})
        _check(r, SEC, ticker, pa.get("signal") is not None,
               f"pa.signal={pa.get('signal')}", "pa.signal missing in multi_system")
        _check(r, SEC, ticker, pa.get("trend") is not None,
               f"pa.trend={pa.get('trend')}", "pa.trend missing in multi_system")

        # Wyckoff within multi_system
        wk = ms.get("wyckoff", {})
        _check(r, SEC, ticker, wk.get("phase") is not None,
               f"wyckoff.phase={wk.get('phase')}", "wyckoff.phase missing in multi_system")

        # Dalton within multi_system
        dal = ms.get("dalton", {})
        _check(r, SEC, ticker, isinstance(dal, dict) and len(dal) > 0,
               f"dalton present ({len(dal)} keys)", "dalton MISSING in multi_system — Dalton UI panel will break!")

        if isinstance(dal, dict) and dal:
            # Validate critical Dalton UI fields
            for field in ["day_type", "open_type", "activity", "market_structure",
                          "one_timeframing", "directional_performance",
                          "poc_migration", "va_sequence", "poor_extremes",
                          "profile_shape", "overnight_inventory", "observations"]:
                _check(r, SEC, ticker, dal.get(field) is not None,
                       f"dalton.{field} ✓", f"dalton.{field} MISSING")

            # Master summary
            _check(r, SEC, ticker, ms.get("master_summary") is not None,
                   "master_summary present", "master_summary MISSING — main summary panel will break!")

            ms_sum = ms.get("master_summary", {})
            if isinstance(ms_sum, dict):
                for mfield in ["consensus", "direction", "action_word", "avg_confidence",
                               "agreement", "plain_text"]:
                    _check(r, SEC, ticker,  ms_sum.get(mfield) is not None,
                           f"master_summary.{mfield} ✓", f"master_summary.{mfield} MISSING")

        # JSON check
        try:
            json.dumps(analysis, default=str)
            r.ok(SEC, ticker, "analysis JSON serializable")
        except Exception as ex:
            r.fail(SEC, ticker, f"analysis NOT JSON serializable: {ex}")

    return True


# ═══════════════════════════════════════════════════════════════
#  TEST 6: FLASK API ENDPOINT (optional — only if server is running)
# ═══════════════════════════════════════════════════════════════
def test_api_endpoint(r):
    SEC = "api_endpoint"
    ticker = "API"
    try:
        import urllib.request
        url = "http://127.0.0.1:5001/api/portfolio?filter=open"
        resp = urllib.request.urlopen(url, timeout=10)
        data = json.loads(resp.read())
        positions = data if isinstance(data, list) else data.get("positions", [])
        _check(r, SEC, ticker, len(positions) >= 0, f"API lists {len(positions)} positions", "API error")

        if not positions:
            r.warn(SEC, ticker, "No open positions to test — skipping analyze endpoint")
            return

        # Test analyze endpoint for first position
        pid = positions[0].get("id")
        url2 = f"http://127.0.0.1:5001/api/portfolio/{pid}/analyze"
        resp2 = urllib.request.urlopen(url2, timeout=120)
        analysis = json.loads(resp2.read())

        _check(r, SEC, ticker, isinstance(analysis, dict), "analyze returns dict", "analyze not dict")
        _check(r, SEC, ticker, "error" not in analysis or analysis.get("error") is None,
               "analyze no error", f"analyze error: {analysis.get('error')}")

        ms = analysis.get("multi_system")
        _check(r, SEC, ticker, isinstance(ms, dict), "multi_system in API", "multi_system MISSING from API!")

        if isinstance(ms, dict):
            triple = ms.get("triple", {})
            _check(r, SEC, ticker, triple.get("score") is not None,
                   f"API triple.score={triple.get('score')}", "API triple.score=None (import bug?)")
            _check(r, SEC, ticker, triple.get("bb_score") is not None,
                   f"API triple.bb_score={triple.get('bb_score')}", "API bb_score=None")

            pa = ms.get("price_action", {})
            _check(r, SEC, ticker, pa.get("signal") is not None,
                   f"API pa.signal={pa.get('signal')}", "API pa.signal=None")

            wk = ms.get("wyckoff", {})
            _check(r, SEC, ticker, wk.get("phase") is not None,
                   f"API wyckoff.phase={wk.get('phase')}", "API wyckoff.phase=None")

            dal = ms.get("dalton", {})
            _check(r, SEC, ticker, isinstance(dal, dict) and len(dal) > 3,
                   f"API dalton has {len(dal)} keys", "API dalton MISSING or empty!")

            # Check that values aren't all zeros (the import bug symptom)
            score = triple.get("score", 0)
            bb_s = triple.get("bb_score", 0)
            ta_s = triple.get("ta_score", 0)
            pa_s = triple.get("pa_score", 0)
            all_zero = (score == 0 and bb_s == 0 and ta_s == 0 and pa_s == 0)
            _check(r, SEC, ticker, not all_zero,
                   f"API scores are non-zero (score={score})",
                   "⚠️ API ALL SCORES ARE ZERO — likely import bug still active!")

            # Master summary
            _check(r, SEC, ticker, ms.get("master_summary") is not None,
                   "API master_summary present", "API master_summary MISSING")

    except ConnectionRefusedError:
        r.warn(SEC, ticker, "Flask server not running on port 5001 — skipping API test")
    except Exception as ex:
        r.fail(SEC, ticker, f"API test error: {ex}")


# ═══════════════════════════════════════════════════════════════
#  MAIN SIMULATION DRIVER
# ═══════════════════════════════════════════════════════════════
def run_readiness_simulation(max_tickers=20, test_api=True):
    print(SEPARATOR)
    print("  TRIPLE CONVICTION ENGINE & PORTFOLIO TRACKER — READINESS SIMULATION")
    print(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(SEPARATOR)

    r = Result()
    start = time.time()

    # Discover tickers
    all_tickers = get_all_tickers_from_csv(CSV_DIR)
    if max_tickers < len(all_tickers):
        # Always include RELIANCE and TCS, then random sample
        must_have = [t for t in all_tickers if t in ("RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "SBIN.NS")]
        remaining = [t for t in all_tickers if t not in must_have]
        random.seed(42)
        sample = must_have + random.sample(remaining, min(max_tickers - len(must_have), len(remaining)))
        tickers = sample[:max_tickers]
    else:
        tickers = all_tickers

    print(f"\n  Testing {len(tickers)} tickers across 6 test suites")
    print(f"  Suites: triple_engine | wyckoff | dalton | price_action | portfolio_analyzer | api_endpoint\n")

    # ── PER-TICKER TESTS ──
    for idx, ticker in enumerate(tickers, 1):
        elapsed = time.time() - start
        print(f"  [{idx:>3}/{len(tickers)}] {ticker:<25s}", end="", flush=True)
        ticker_start = time.time()
        fails_before = r.failed

        try:
            df = load_stock_data(ticker, CSV_DIR, use_live_fallback=False)
        except Exception:
            df = None

        if df is None or len(df) < 30:
            r.warn("data", ticker, f"Insufficient data ({len(df) if df is not None else 0} rows)")
            print(f"  ⚠ SKIP (no data)")
            continue

        # Compute indicators for portfolio test
        try:
            df_bb = compute_all_indicators(df.copy())
        except Exception as ex:
            r.fail("indicators", ticker, f"compute_all_indicators CRASH: {ex}")
            print(f"  ✗ INDICATOR CRASH")
            continue

        # Test 1: Triple Engine
        triple_result = test_triple_engine(ticker, df, r)

        # Test 2: Wyckoff (from triple result)
        if triple_result:
            test_wyckoff(ticker, triple_result, r)

        # Test 3: Dalton (from triple result)
        if triple_result:
            test_dalton(ticker, triple_result, r)

        # Test 4: Price Action
        test_price_action(ticker, df, r)

        # Test 5: Portfolio Analyzer (end-to-end)
        test_portfolio_analyzer(ticker, df_bb, r)

        ticker_time = time.time() - ticker_start
        new_fails = r.failed - fails_before
        status = "✓" if new_fails == 0 else f"✗ ({new_fails} failures)"
        print(f"  {status}  ({ticker_time:.1f}s)")

    # ── API ENDPOINT TEST ──
    if test_api:
        print(f"\n{SUBSEP}")
        print("  Testing Flask API endpoint...")
        test_api_endpoint(r)

    total_time = time.time() - start

    # ═══════════════════════════════════════════════════════════════
    #  FINAL REPORT
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{SEPARATOR}")
    print("  READINESS SIMULATION — FINAL REPORT")
    print(SEPARATOR)

    print(f"\n  Tickers Tested:  {len(tickers)}")
    print(f"  Total Checks:    {r.total:,}")
    print(f"  ✓ Passed:        {r.passed:,}")
    print(f"  ✗ Failed:        {r.failed:,}")
    print(f"  ⚠ Warnings:      {r.warned:,}")
    print(f"  Pass Rate:       {r.pass_rate:.1f}%")
    print(f"  Time:            {total_time:.1f}s")

    # Readiness verdict
    print(f"\n  {'─' * 50}")
    if r.failed == 0:
        print(f"  ✅ SYSTEM IS READY — All {r.total:,} checks passed!")
    elif r.failed <= 5:
        print(f"  ⚠️  MOSTLY READY — {r.failed} minor failures out of {r.total:,} checks")
    else:
        print(f"  ❌ NOT READY — {r.failed} failures need fixing")
    print(f"  {'─' * 50}")

    # Failure details
    if r.errors:
        fails = [(s, t, sev, m) for s, t, sev, m in r.errors if sev == "FAIL"]
        warns = [(s, t, sev, m) for s, t, sev, m in r.errors if sev == "WARN"]

        if fails:
            print(f"\n  ✗ FAILURES ({len(fails)}):")
            # Group by section
            by_section = defaultdict(list)
            for s, t, _, m in fails:
                by_section[s].append((t, m))
            for sec in sorted(by_section):
                print(f"\n    [{sec}]")
                for t, m in by_section[sec][:10]:
                    print(f"      {t}: {m}")
                if len(by_section[sec]) > 10:
                    print(f"      ... +{len(by_section[sec])-10} more")

        if warns:
            print(f"\n  ⚠ WARNINGS ({len(warns)}):")
            by_section = defaultdict(list)
            for s, t, _, m in warns:
                by_section[s].append((t, m))
            for sec in sorted(by_section):
                print(f"    [{sec}]")
                for t, m in by_section[sec][:5]:
                    print(f"      {t}: {m}")
                if len(by_section[sec]) > 5:
                    print(f"      ... +{len(by_section[sec])-5} more")

    # Signal distributions
    if r.stats:
        print(f"\n{SUBSEP}")
        print("  SIGNAL & STATE DISTRIBUTIONS")
        print(SUBSEP)
        for cat in sorted(r.stats):
            dist = r.stats[cat]
            total = sum(dist.values())
            print(f"\n  {cat}:")
            for val, cnt in dist.most_common():
                pct = cnt / total * 100 if total else 0
                bar = "█" * int(pct / 2)
                print(f"    {val:<25s} {cnt:>4d} ({pct:5.1f}%) {bar}")

    # Save results
    output = {
        "simulation_date": datetime.now().isoformat(),
        "tickers_tested": len(tickers),
        "total_checks": r.total,
        "passed": r.passed,
        "failed": r.failed,
        "warnings": r.warned,
        "pass_rate": round(r.pass_rate, 2),
        "time_sec": round(total_time, 1),
        "ready": r.failed == 0,
        "errors": [{"section": s, "ticker": t, "severity": sev, "message": m}
                   for s, t, sev, m in r.errors],
        "distributions": {cat: dict(dist) for cat, dist in r.stats.items()},
    }

    results_file = os.path.join(ROOT, "readiness_results.json")
    with open(results_file, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Results saved to: {results_file}")
    print(SEPARATOR)

    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Triple Engine & Portfolio Tracker Readiness Simulation")
    parser.add_argument("--tickers", type=int, default=20, help="Number of tickers to test (default: 20)")
    parser.add_argument("--api", action="store_true", default=True, help="Test Flask API endpoint")
    parser.add_argument("--no-api", action="store_true", help="Skip Flask API endpoint test")
    args = parser.parse_args()

    run_readiness_simulation(
        max_tickers=args.tickers,
        test_api=not args.no_api,
    )
