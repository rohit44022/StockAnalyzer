#!/usr/bin/env python3
"""Quick end-to-end test of the Technical Analysis module."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bb_squeeze.data_loader import load_stock_data
from bb_squeeze.config import CSV_DIR
from technical_analysis.indicators import (
    compute_all_ta_indicators, get_indicator_snapshot,
    detect_ma_crossovers, detect_all_divergences,
    compute_pivot_points, compute_fibonacci,
)
from technical_analysis.candlesticks import scan_candlestick_patterns
from technical_analysis.patterns import (
    detect_support_resistance, identify_trend,
    detect_all_chart_patterns, analyze_volume, analyze_ichimoku,
)
from technical_analysis.signals import generate_signal
from technical_analysis.risk_manager import generate_risk_report

df = load_stock_data("RELIANCE.NS", CSV_DIR)
print(f"Loaded {len(df)} rows")

df = compute_all_ta_indicators(df)
print(f"Computed {len(df.columns)} columns")

snap = get_indicator_snapshot(df)
print(f"Snapshot: price={snap.get('price')}, rsi={snap.get('rsi')}, macd={snap.get('macd')}, adx={snap.get('adx')}")

trend = identify_trend(df)
print(f"Trend: {trend['primary']} | {trend['strength']} | Phase: {trend['phase']}")

sr = detect_support_resistance(df)
print(f"S/R: {len(sr.get('support',[]))} supports, {len(sr.get('resistance',[]))} resistances")

candles = scan_candlestick_patterns(df)
print(f"Candle patterns: {[c['name'] for c in candles]}")

chart_pats = detect_all_chart_patterns(df)
print(f"Chart patterns: {[p['name'] for p in chart_pats]}")

vol = analyze_volume(df)
print(f"Volume: ratio={vol.get('volume_ratio')}, status={vol.get('volume_status')}")

ichi = analyze_ichimoku(df)
print(f"Ichimoku: {ichi.get('verdict')}")

fib = compute_fibonacci(df)
print(f"Fibonacci: low={fib.get('swing_low')}, high={fib.get('swing_high')}")

crossovers = detect_ma_crossovers(df)
divs = detect_all_divergences(df)
signal = generate_signal(snap, trend, vol, chart_pats, candles, divs, sr, fib)
print(f"\nFINAL: {signal['verdict']} | Score: {signal['score']}/{signal['max_score']} | Confidence: {signal['confidence']}%")
print(f"Actions: {signal.get('action_items', [])[:3]}")

risk = generate_risk_report(snap, sr)
ps = risk.get("position_sizing", {})
if ps.get("shares"):
    print(f"Position: {ps['shares']} shares @ ₹{ps['entry']} (₹{ps['position_value']})")

print("\n✅ All tests passed!")
