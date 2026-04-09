#!/usr/bin/env python3
"""
TRIPLE ENGINE TRUTHFULNESS AUDIT
=================================
Runs every stock through the Triple Conviction Engine and validates:
  1. No crashes / exceptions
  2. JSON-serializable output (no NaN, Inf, numpy objects)
  3. Score ranges respected:
       BB:  [-100, +100]
       TA:  [-100, +100]
       PA:  [-100, +100]
       Agreement: [-60, +60]   (theoretical; documented ±60)
       Combined:  [-360, +360]
  4. Verdict is one of the known categories
  5. Alignment is one of the known categories
  6. Cross-validation direction matches score direction
  7. Component scores don't exceed their documented maximums
"""

import os, sys, json, time, math, traceback
import pandas as pd

# ── Add project root to path ────────────────────────────────
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from hybrid_pa_engine import run_triple_analysis
from bb_squeeze.data_loader import load_from_csv, get_all_tickers_from_csv

CSV_DIR = os.path.join(ROOT, "stock_csv")
VALID_VERDICTS = {
    "SUPER STRONG BUY", "STRONG BUY", "BUY",
    "HOLD / WAIT",
    "SELL", "STRONG SELL", "SUPER STRONG SELL",
}
VALID_ALIGNMENTS = {
    "TRIPLE_ALIGNED", "DOUBLE_ALIGNED", "CONFLICTING",
    "ALL_NEUTRAL", "SINGLE", "MIXED", "PARTIAL",
}
VALID_DIRECTIONS = {"BULLISH", "BEARISH", "NEUTRAL"}

# ── Counters ────────────────────────────────────────────────
total = 0
passed = 0
errors = []           # (ticker, error_msg)
score_violations = [] # (ticker, field, value, expected_range)
verdict_dist = {}
alignment_dist = {}
bb_scores = []
ta_scores = []
pa_scores = []
agreement_scores = []
combined_scores = []
nan_fields = []       # (ticker, field_path)


def check_json_serializable(obj, path="root"):
    """Recursively check every value is JSON-safe (no NaN, Inf, numpy)."""
    issues = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            issues.extend(check_json_serializable(v, f"{path}.{k}"))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            issues.extend(check_json_serializable(v, f"{path}[{i}]"))
    elif isinstance(obj, float):
        if math.isnan(obj):
            issues.append(f"NaN at {path}")
        elif math.isinf(obj):
            issues.append(f"Inf at {path}")
    elif obj is not None and not isinstance(obj, (int, float, str, bool)):
        issues.append(f"Non-JSON type {type(obj).__name__} at {path}")
    return issues


def audit_one(ticker: str):
    """Run full audit on a single stock."""
    global total, passed
    total += 1
    issues = []

    try:
        df = load_from_csv(ticker, CSV_DIR)
        if df is None or len(df) < 60:
            errors.append((ticker, f"Too few rows ({len(df) if df is not None else 0})"))
            return

        result = run_triple_analysis(df, ticker=ticker)

        if "error" in result:
            errors.append((ticker, f"Engine error: {result['error']}"))
            return

        # ── 1. JSON serializable ──
        json_issues = check_json_serializable(result)
        if json_issues:
            for ji in json_issues:
                nan_fields.append((ticker, ji))

        # Also try actual serialization
        try:
            json.dumps(result)
        except (TypeError, ValueError) as e:
            issues.append(f"JSON serialization failed: {e}")

        # ── 2. Score range checks ──
        bb = result.get("bb_score", {}).get("total", 0)
        ta = result.get("ta_score", {}).get("total", 0)
        pa = result.get("pa_score", {}).get("total", 0)
        agree = result.get("cross_validation", {}).get("agreement_score", 0)
        combined = result.get("triple_verdict", {}).get("score", 0)

        bb_scores.append(bb)
        ta_scores.append(ta)
        pa_scores.append(pa)
        agreement_scores.append(agree)
        combined_scores.append(combined)

        if bb < -100 or bb > 100:
            score_violations.append((ticker, "bb_total", bb, "[-100,100]"))
        if ta < -100 or ta > 100:
            score_violations.append((ticker, "ta_total", ta, "[-100,100]"))
        if pa < -100 or pa > 100:
            score_violations.append((ticker, "pa_total", pa, "[-100,100]"))
        if agree < -60 or agree > 60:
            score_violations.append((ticker, "agreement", agree, "[-60,60]"))
        if combined < -360 or combined > 360:
            score_violations.append((ticker, "combined", combined, "[-360,360]"))

        # ── 3. BB method scores ──
        for m in result.get("bb_score", {}).get("methods", []):
            s = m.get("score", 0)
            mx = m.get("max", 100)
            if abs(s) > mx:
                score_violations.append((ticker, m.get("method", "?"), s, f"[-{mx},{mx}]"))

        # ── 4. PA component scores ──
        for comp_name, comp in result.get("pa_score", {}).get("components", {}).items():
            s = comp.get("score", 0)
            mx = comp.get("max", 100)
            if abs(s) > mx:
                score_violations.append((ticker, f"pa.{comp_name}", s, f"[-{mx},{mx}]"))

        # ── 5. Verdict validity ──
        verdict = result.get("triple_verdict", {}).get("verdict", "")
        if verdict not in VALID_VERDICTS:
            issues.append(f"Invalid verdict: '{verdict}'")
        verdict_dist[verdict] = verdict_dist.get(verdict, 0) + 1

        # ── 6. Alignment validity ──
        alignment = result.get("cross_validation", {}).get("alignment", "")
        if alignment not in VALID_ALIGNMENTS:
            issues.append(f"Invalid alignment: '{alignment}'")
        alignment_dist[alignment] = alignment_dist.get(alignment, 0) + 1

        # ── 7. Direction validity ──
        cross = result.get("cross_validation", {})
        for sys_name in ["bb_direction", "ta_direction", "pa_direction"]:
            d = cross.get(sys_name, "")
            if d not in VALID_DIRECTIONS:
                issues.append(f"Invalid direction {sys_name}='{d}'")

        # ── 8. Score-direction consistency ──
        # BB: >10 should be BULLISH, <-10 BEARISH
        bb_dir = cross.get("bb_direction", "NEUTRAL")
        if bb > 10 and bb_dir != "BULLISH":
            issues.append(f"BB score={bb} but direction={bb_dir}")
        if bb < -10 and bb_dir != "BEARISH":
            issues.append(f"BB score={bb} but direction={bb_dir}")

        # TA: >10 should be BULLISH, <-10 BEARISH
        ta_dir = cross.get("ta_direction", "NEUTRAL")
        if ta > 10 and ta_dir != "BULLISH":
            issues.append(f"TA score={ta} but direction={ta_dir}")
        if ta < -10 and ta_dir != "BEARISH":
            issues.append(f"TA score={ta} but direction={ta_dir}")

        # PA: >15 should be BULLISH, <-15 BEARISH (PA uses threshold=15)
        pa_dir = cross.get("pa_direction", "NEUTRAL")
        if pa > 15 and pa_dir != "BULLISH":
            issues.append(f"PA score={pa} but direction={pa_dir}")
        if pa < -15 and pa_dir != "BEARISH":
            issues.append(f"PA score={pa} but direction={pa_dir}")

        # ── 9. Combined score = sum of parts ──
        expected = round(bb + ta + pa + agree, 1)
        if abs(combined - expected) > 0.2:
            issues.append(f"Combined={combined} != BB({bb})+TA({ta})+PA({pa})+Agree({agree})={expected}")

        # ── 10. Confidence range ──
        conf = result.get("triple_verdict", {}).get("confidence", -1)
        if conf < 0 or conf > 100:
            issues.append(f"Confidence out of range: {conf}")

        if issues:
            for iss in issues:
                errors.append((ticker, iss))
        else:
            passed += 1

    except Exception as e:
        errors.append((ticker, f"CRASH: {traceback.format_exc().split(chr(10))[-2]}"))


def main():
    tickers = get_all_tickers_from_csv(CSV_DIR)
    print(f"═══ TRIPLE ENGINE TRUTHFULNESS AUDIT ═══")
    print(f"Scanning {len(tickers)} stocks...\n")

    t0 = time.time()
    for i, ticker in enumerate(tickers):
        audit_one(ticker)
        if (i + 1) % 100 == 0:
            print(f"  [{i+1}/{len(tickers)}] processed...")

    elapsed = time.time() - t0
    print(f"\n{'═' * 60}")
    print(f"  AUDIT COMPLETE — {elapsed:.1f}s")
    print(f"{'═' * 60}")
    print(f"  Total stocks:      {total}")
    print(f"  Passed cleanly:    {passed}")
    print(f"  With issues:       {total - passed}")
    print(f"  Crash/error:       {len([e for e in errors if 'CRASH' in e[1]])}")

    # ── Score Statistics ──
    print(f"\n{'─' * 60}")
    print(f"  SCORE RANGES (actual vs expected)")
    print(f"{'─' * 60}")
    for name, scores, expected in [
        ("BB", bb_scores, "[-100, +100]"),
        ("TA", ta_scores, "[-100, +100]"),
        ("PA", pa_scores, "[-100, +100]"),
        ("Agreement", agreement_scores, "[-60, +60]"),
        ("Combined", combined_scores, "[-360, +360]"),
    ]:
        if scores:
            mn, mx, avg = min(scores), max(scores), sum(scores)/len(scores)
            print(f"  {name:12s}: [{mn:+8.1f}, {mx:+8.1f}]  avg={avg:+7.1f}  expected={expected}")
        else:
            print(f"  {name:12s}: NO DATA")

    # ── Score Violations ──
    if score_violations:
        print(f"\n  🔴 SCORE RANGE VIOLATIONS ({len(score_violations)}):")
        for ticker, field, val, expected in score_violations[:20]:
            print(f"    {ticker}: {field} = {val} (expected {expected})")
    else:
        print(f"\n  ✅ NO SCORE RANGE VIOLATIONS")

    # ── NaN/Inf Fields ──
    if nan_fields:
        print(f"\n  🔴 NaN/Inf FOUND ({len(nan_fields)}):")
        # group by field path
        from collections import Counter
        field_counts = Counter(f for _, f in nan_fields)
        for field, count in field_counts.most_common(15):
            print(f"    {field}: {count} stocks")
    else:
        print(f"\n  ✅ NO NaN/Inf VALUES")

    # ── Verdict Distribution ──
    print(f"\n{'─' * 60}")
    print(f"  VERDICT DISTRIBUTION")
    print(f"{'─' * 60}")
    for v in ["SUPER STRONG BUY", "STRONG BUY", "BUY", "HOLD / WAIT",
              "SELL", "STRONG SELL", "SUPER STRONG SELL"]:
        count = verdict_dist.get(v, 0)
        pct = count / max(passed + len(errors) - len([e for e in errors if 'CRASH' in e[1]]), 1) * 100
        bar = "█" * int(pct / 2)
        print(f"  {v:20s}: {count:5d} ({pct:5.1f}%) {bar}")

    # ── Alignment Distribution ──
    print(f"\n{'─' * 60}")
    print(f"  ALIGNMENT DISTRIBUTION")
    print(f"{'─' * 60}")
    for a in ["TRIPLE_ALIGNED", "DOUBLE_ALIGNED", "CONFLICTING",
              "ALL_NEUTRAL", "SINGLE", "MIXED"]:
        count = alignment_dist.get(a, 0)
        total_analyzed = sum(alignment_dist.values()) or 1
        pct = count / total_analyzed * 100
        print(f"  {a:20s}: {count:5d} ({pct:5.1f}%)")

    # ── Errors (sample) ──
    crashes = [e for e in errors if "CRASH" in e[1]]
    logic_errors = [e for e in errors if "CRASH" not in e[1] and "Too few rows" not in e[1]]
    small_data = [e for e in errors if "Too few rows" in e[1]]

    if crashes:
        print(f"\n  🔴 CRASHES ({len(crashes)}):")
        for ticker, msg in crashes[:10]:
            print(f"    {ticker}: {msg}")
        if len(crashes) > 10:
            print(f"    ... and {len(crashes) - 10} more")

    if logic_errors:
        print(f"\n  ⚠️  LOGIC ISSUES ({len(logic_errors)}):")
        for ticker, msg in logic_errors[:15]:
            print(f"    {ticker}: {msg}")
        if len(logic_errors) > 15:
            print(f"    ... and {len(logic_errors) - 15} more")

    if small_data:
        print(f"\n  ℹ️  Insufficient data (< 60 bars): {len(small_data)} stocks")

    # ── Final Verdict ──
    print(f"\n{'═' * 60}")
    if not crashes and not logic_errors and not score_violations and not nan_fields:
        print(f"  ✅ SYSTEM IS TRUTHFUL AND PRODUCTION-GRADE")
    else:
        issue_count = len(crashes) + len(logic_errors) + len(score_violations) + len(nan_fields)
        print(f"  ⚠️  {issue_count} ISSUES NEED FIXING")
    print(f"{'═' * 60}")


if __name__ == "__main__":
    main()
