#!/usr/bin/env python3
"""Verify Top 5 Picks score components for KRISHANA stock."""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bb_squeeze.data_loader import load_stock_data, get_data_freshness
from bb_squeeze.indicators import compute_all_indicators
from bb_squeeze.signals import analyze_signals
from bb_squeeze.strategies import run_all_strategies, strategy_result_to_dict
from hybrid_engine import run_hybrid_analysis
from price_action.engine import run_price_action_analysis, pa_result_to_dict
from top_picks.scorer import compute_composite_score, _score_bb_strategy, _score_technical_analysis, _score_hybrid, _score_risk_reward, _score_signal_agreement, _score_data_quality, _score_price_action

ticker = "KRISHANA.NS"
df = load_stock_data(ticker, use_live_fallback=False)
print(f"Data loaded: {len(df)} rows")

# Run hybrid (runs everything internally)
hybrid = run_hybrid_analysis(df, ticker=ticker)
if "error" in hybrid:
    print(f"ERROR: {hybrid['error']}")
    sys.exit(1)

bb_data = hybrid.get("bb_data", {})
ta_signal = hybrid.get("ta_signal", {})
hv = hybrid.get("hybrid_verdict", {})
data_freshness = hybrid.get("data_freshness", {})
target_prices = hybrid.get("target_prices", {})

# BB M2 confidence
df_ind = compute_all_indicators(df)
strats = run_all_strategies(df_ind)
m2_sig = None
for s in strats:
    sd = strategy_result_to_dict(s)
    if sd.get("code") == "M2":
        m2_sig = sd.get("signal", {})
        break

print("\n" + "=" * 70)
print("RAW VALUES FROM EACH ENGINE")
print("=" * 70)

# BB Method I
print(f"\n--- BB Method I ---")
print(f"  buy_signal: {bb_data.get('buy_signal')}")
print(f"  sell_signal: {bb_data.get('sell_signal')}")
print(f"  confidence: {bb_data.get('confidence')}")
print(f"  phase: {bb_data.get('phase')}")

# BB Method II
print(f"\n--- BB Method II ---")
if m2_sig:
    print(f"  type: {m2_sig.get('type')}")
    print(f"  confidence: {m2_sig.get('confidence')}")
    print(f"  strength: {m2_sig.get('strength')}")

# TA
print(f"\n--- Technical Analysis ---")
print(f"  verdict: {ta_signal.get('verdict')}")
print(f"  raw score: {ta_signal.get('score')}")
print(f"  max_score: {ta_signal.get('max_score')}")
cats = ta_signal.get("categories", {})
for cat, data in cats.items():
    if isinstance(data, dict):
        print(f"    {cat}: {data.get('score',0)}/{data.get('max',0)}")

# Hybrid
print(f"\n--- Hybrid Engine ---")
print(f"  verdict: {hv.get('verdict')}")
print(f"  combined_score: {hv.get('score')}")
print(f"  confidence: {hv.get('confidence')}")
print(f"  bb_total: {hybrid.get('bb_score', {}).get('total')}")
print(f"  ta_total: {hybrid.get('ta_score', {}).get('total')}")
cv = hybrid.get("cross_validation", {})
print(f"  agreement_score: {cv.get('agreement_score')}")

# Risk/Reward
print(f"\n--- Risk/Reward ---")
rr = target_prices.get("risk_reward_ratio") if target_prices else None
print(f"  R:R ratio: {rr}")

# Data quality
print(f"\n--- Data Quality ---")
print(f"  trading_days_stale: {data_freshness.get('trading_days_stale')}")

# Price Action
print(f"\n--- Price Action ---")
bb_cross = {
    "buy_signal": bb_data.get("buy_signal", False),
    "sell_signal": bb_data.get("sell_signal", False),
    "direction_lean": bb_data.get("direction_lean", ""),
    "confidence": bb_data.get("confidence", 0),
    "phase": bb_data.get("phase", ""),
}
pa = run_price_action_analysis(df=df, ticker=ticker, bb_data=bb_cross, ta_data=ta_signal, hybrid_data=hybrid)
pa_flat = None
if pa and pa.success:
    pa_dict = pa_result_to_dict(pa)
    print(f"  pa_score (raw): {pa.pa_score}  (-100 to +100)")
    print(f"  confidence: {pa.confidence}")
    print(f"  signal_type: {pa.signal_type}")
    print(f"  pa_verdict: {pa_dict.get('signal',{}).get('pa_verdict')}")
    print(f"  setup: {pa_dict.get('signal',{}).get('setup')}")
    pa_flat = {
        "success": True,
        "pa_score": pa.pa_score,
        "confidence": pa.confidence,
        "pa_verdict": pa_dict.get("signal", {}).get("pa_verdict", "HOLD"),
        "signal_type": pa.signal_type,
        "setup_type": pa_dict.get("signal", {}).get("setup", ""),
    }
else:
    print("  PA analysis failed")

# Now compute composite score EXACTLY like top_picks does
print("\n" + "=" * 70)
print("COMPOSITE SCORE COMPUTATION (M2, BUY filter)")
print("=" * 70)

bb_conf = m2_sig.get("confidence", 0) if m2_sig else 0
bb_type = m2_sig.get("type", "NONE") if m2_sig else "NONE"
print(f"\nInputs to scorer:")
print(f"  bb_confidence={bb_conf}, bb_signal_type={bb_type}")
print(f"  ta_score raw={ta_signal.get('score')}, ta_verdict={ta_signal.get('verdict')}")
print(f"  hybrid combined_score={hv.get('score')}")
print(f"  data_freshness stale={data_freshness.get('trading_days_stale')}")
if pa_flat:
    print(f"  pa_score raw={pa_flat['pa_score']}, pa_conf={pa_flat['confidence']}")

# Manually compute each component
bb_score = _score_bb_strategy(bb_conf, bb_type, "M2")
ta_comp = _score_technical_analysis(ta_signal, is_sell=False)
hybrid_comp = _score_hybrid(hybrid, is_sell=False)
rr_score, rr_val = _score_risk_reward(hybrid)
agree_score = _score_signal_agreement(bb_type, ta_signal.get("verdict", "HOLD"),
                                       hv.get("verdict", "UNKNOWN"))
dq_score = _score_data_quality(data_freshness)
pa_comp = _score_price_action(pa_flat, is_sell=False)

print(f"\nComponent Scores (what shows in UI):")
print(f"  BB Strategy:   {bb_score:.1f}/100   (weight 20%)")
print(f"  TA Score:      {ta_comp:.1f}/100   (weight 20%)")
print(f"  Hybrid Score:  {hybrid_comp:.1f}/100   (weight 15%)")
print(f"  Price Action:  {pa_comp:.1f}/100   (weight 15%)")
print(f"  Risk/Reward:   {rr_score:.1f}/100   (weight 15%, R:R={rr_val})")
print(f"  Agreement:     {agree_score:.1f}/100   (weight 10%)")
print(f"  Data Quality:  {dq_score:.1f}/100   (weight 5%)")

composite = (
    bb_score * 0.20 +
    ta_comp * 0.20 +
    hybrid_comp * 0.15 +
    pa_comp * 0.15 +
    rr_score * 0.15 +
    agree_score * 0.10 +
    dq_score * 0.05
)
print(f"\n  COMPOSITE SCORE: {composite:.1f}/100")

# Full scorer result for comparison
full = compute_composite_score(
    bb_confidence=bb_conf,
    bb_signal_type=bb_type,
    ta_signal=ta_signal,
    hybrid_result=hybrid,
    data_freshness=data_freshness,
    method="M2",
    signal_filter="BUY",
    pa_result=pa_flat,
)
print(f"  SCORER RESULT:  {full['composite_score']}/100, Grade: {full['grade']}")

# Math verification for each
print("\n" + "=" * 70)
print("DETAILED MATH VERIFICATION")
print("=" * 70)

# BB Strategy
print(f"\n1. BB Strategy Score:")
print(f"   Input: confidence={bb_conf}, signal_type={bb_type}")
if bb_type == "BUY":
    expected = min(100, bb_conf + 10)
else:
    expected = bb_conf
print(f"   Expected: min(100, {bb_conf} + 10) = {expected}")
print(f"   Got: {bb_score}")
print(f"   MATCH: {abs(expected - bb_score) < 0.1}")

# TA Score  
print(f"\n2. TA Score:")
ta_raw = ta_signal.get("score", 0)
ta_expected = (ta_raw + 100) / 2.0
print(f"   Input: raw_score={ta_raw}")
print(f"   Formula: ({ta_raw} + 100) / 2 = {ta_expected:.1f}")
print(f"   Got: {ta_comp:.1f}")
print(f"   MATCH: {abs(ta_expected - ta_comp) < 0.1}")

# Hybrid Score
print(f"\n3. Hybrid Score:")
h_combined = hv.get("score", 0)
h_expected = (h_combined + 245) / 490 * 100
print(f"   Input: combined_score={h_combined}")
print(f"   Formula: ({h_combined} + 245) / 490 * 100 = {h_expected:.1f}")
print(f"   Got: {hybrid_comp:.1f}")
print(f"   MATCH: {abs(h_expected - hybrid_comp) < 0.1}")

# PA Score
print(f"\n4. Price Action Score:")
if pa_flat:
    pa_raw = pa_flat["pa_score"]
    pa_conf = pa_flat["confidence"]
    normalized = (pa_raw + 100) / 200 * 100
    blended = normalized * 0.7 + pa_conf * 0.3
    print(f"   Input: pa_score={pa_raw}, confidence={pa_conf}")
    print(f"   Normalized: ({pa_raw} + 100) / 200 * 100 = {normalized:.1f}")
    print(f"   Blended: {normalized:.1f} * 0.7 + {pa_conf} * 0.3 = {blended:.1f}")
    print(f"   Got: {pa_comp:.1f}")
    print(f"   MATCH: {abs(blended - pa_comp) < 0.1}")

# Risk/Reward
print(f"\n5. Risk/Reward Score:")
print(f"   Input: R:R={rr_val}")
print(f"   Got: {rr_score}")

# Agreement
print(f"\n6. Agreement Score:")
print(f"   BB signal: {bb_type}")
print(f"   TA verdict: {ta_signal.get('verdict')}")
print(f"   Hybrid verdict: {hv.get('verdict')}")
print(f"   Got: {agree_score}")

# Data Quality
print(f"\n7. Data Quality:")
print(f"   Days stale: {data_freshness.get('trading_days_stale')}")
print(f"   Got: {dq_score}")

# Cross-check what screenshot shows
print("\n" + "=" * 70)
print("SCREENSHOT vs COMPUTED (from image)")
print("=" * 70)
print(f"  BB Strategy: Screenshot=100, Computed={bb_score:.0f}  {'OK' if abs(bb_score-100)<1 else 'MISMATCH!'}")
print(f"  TA Score:    Screenshot=69,  Computed={ta_comp:.0f}  {'OK' if abs(ta_comp-69)<1 else 'MISMATCH!'}")
print(f"  Hybrid:      Screenshot=74,  Computed={hybrid_comp:.0f}  {'OK' if abs(hybrid_comp-74)<2 else 'MISMATCH!'}")
print(f"  Price Action:Screenshot=74,  Computed={pa_comp:.0f}  {'OK' if abs(pa_comp-74)<2 else 'MISMATCH!'}")
print(f"  Risk/Reward: Screenshot=55,  Computed={rr_score:.0f}  {'OK' if abs(rr_score-55)<1 else 'MISMATCH!'}")
print(f"  Agreement:   Screenshot=100, Computed={agree_score:.0f}  {'OK' if abs(agree_score-100)<1 else 'MISMATCH!'}")
print(f"  Data Quality:Screenshot=85,  Computed={dq_score:.0f}  {'OK' if abs(dq_score-85)<1 else 'MISMATCH!'}")
print(f"  Composite:   Screenshot=78.4 Computed={composite:.1f}  {'OK' if abs(composite-78.4)<1 else 'MISMATCH!'}")
