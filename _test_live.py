"""Test script for live-readiness fixes."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bb_squeeze.data_loader import load_stock_data, get_data_freshness
from bb_squeeze.config import CSV_DIR

# Test 1: Data loader + freshness
print("=" * 60)
print("TEST 1: Data Loader + Freshness")
df = load_stock_data("RELIANCE.NS", CSV_DIR, use_live_fallback=False)
assert df is not None, "RELIANCE data not found"
fresh = get_data_freshness(df)
print(f"  Last date: {fresh['last_date']}")
print(f"  Trading days stale: {fresh['trading_days_stale']}")
print(f"  Is stale: {fresh['is_stale']}")
print(f"  Warning: {fresh['warning']}")
print("  PASS")

# Test 2: Indicators — RSI never NaN, pivot uses previous bar
print("\nTEST 2: Indicators")
from technical_analysis.indicators import compute_all_ta_indicators, get_indicator_snapshot, compute_pivot_points
df2 = compute_all_ta_indicators(df.copy())
snap = get_indicator_snapshot(df2)
pivot = compute_pivot_points(df2)
assert snap.get("rsi") is not None, "RSI should not be None"
assert pivot.get("PP") is not None, "Pivot PP should exist"
print(f"  RSI: {snap['rsi']:.2f}")
print(f"  Pivot PP: {pivot['PP']}")
print("  PASS")

# Test 3: Signal scoring
print("\nTEST 3: Signal Scoring")
from technical_analysis.patterns import detect_support_resistance, identify_trend, detect_all_chart_patterns, analyze_volume
from technical_analysis.candlesticks import scan_candlestick_patterns
from technical_analysis.signals import generate_signal
from technical_analysis.indicators import detect_all_divergences, compute_fibonacci

trend = identify_trend(df2)
vol = analyze_volume(df2)
chart_p = detect_all_chart_patterns(df2)
candle_p = scan_candlestick_patterns(df2)
divs = detect_all_divergences(df2)
sr = detect_support_resistance(df2)
fib = compute_fibonacci(df2)

signal = generate_signal(snap=snap, trend=trend, vol_analysis=vol,
                         chart_patterns=chart_p, candle_patterns=candle_p,
                         divergences=divs, sr_data=sr, fib_data=fib)
print(f"  Verdict: {signal.get('verdict')}")
print(f"  Score: {signal.get('score')}")
cats = signal.get("categories", {})
for k, v in cats.items():
    print(f"    {k}: {v.get('score')}/{v.get('max')}")
assert -100 <= signal.get("score", 0) <= 100, "Score out of range"
print("  PASS")

# Test 4: Hybrid engine
print("\nTEST 4: Hybrid Engine")
from hybrid_engine import run_hybrid_analysis
result = run_hybrid_analysis(df.copy(), ticker="RELIANCE.NS", capital=500000)
assert "error" not in result, f"Hybrid error: {result.get('error')}"
assert "data_freshness" in result, "Missing data_freshness in hybrid result"
hv = result["hybrid_verdict"]
print(f"  Hybrid verdict: {hv['verdict']}")
print(f"  Score: {hv['score']}/{hv['max_score']}")
print(f"  Confidence: {hv['confidence']}%")
print(f"  Freshness: {result['data_freshness']}")
print("  PASS")

# Test 5: Risk manager — position size capped
print("\nTEST 5: Risk Manager (position cap)")
from technical_analysis.risk_manager import calculate_position_size
pos = calculate_position_size(entry=500, stop_loss=499.90, capital=500000, risk_pct=0.02)
print(f"  Entry: {pos['entry']}, Stop: {pos['stop_loss']}")
print(f"  Shares: {pos['shares']}, Position: {pos['position_value']}")
assert pos["position_value"] <= 500000, f"Position {pos['position_value']} exceeds capital 500000!"
print("  PASS")

# Test 6: Target prices
print("\nTEST 6: Target Prices")
from technical_analysis.target_price import calculate_target_prices
targets = calculate_target_prices(snap=snap, trend=trend, sr_data=sr,
                                   fib_data=fib, pivot=pivot, chart_patterns=chart_p)
count = len(targets.get("targets", []))
consensus = targets.get("consensus", {})
print(f"  Targets computed: {count}")
print(f"  Consensus upside: {consensus.get('upside_target')}")
print(f"  Consensus downside: {consensus.get('downside_target')}")
# Check no absurd targets
for t in targets.get("targets", []):
    val = t.get("target")
    if val is not None:
        assert val > 0, f"Target price can't be zero or negative: {t}"
print("  PASS")

# Test 7: Test with TCS
print("\nTEST 7: Cross-validate with TCS")
df_tcs = load_stock_data("TCS.NS", CSV_DIR, use_live_fallback=False)
if df_tcs is not None:
    result_tcs = run_hybrid_analysis(df_tcs.copy(), ticker="TCS.NS", capital=500000)
    assert "error" not in result_tcs, f"TCS error: {result_tcs.get('error')}"
    print(f"  TCS verdict: {result_tcs['hybrid_verdict']['verdict']}")
    print(f"  TCS freshness: {result_tcs['data_freshness']}")
    print("  PASS")
else:
    print("  SKIP (no TCS data)")

print("\n" + "=" * 60)
print("ALL TESTS PASSED ✓")
