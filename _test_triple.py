#!/usr/bin/env python3
"""Quick test of the triple engine."""
from bb_squeeze.data_loader import load_stock_data
from bb_squeeze.config import CSV_DIR
from hybrid_pa_engine import run_triple_analysis
import json

df = load_stock_data('RELIANCE.NS', CSV_DIR)
print(f'Loaded {len(df)} rows for RELIANCE')
result = run_triple_analysis(df, ticker='RELIANCE.NS')
if 'error' in result:
    print('ERROR:', result['error'])
else:
    v = result['triple_verdict']
    c = result['cross_validation']
    print(f"Verdict: {v['verdict']} ({v['emoji']})")
    print(f"Combined Score: {v['score']} / {v['max_score']}")
    print(f"Confidence: {v['confidence']}%")
    print(f"Alignment: {c['alignment']}")
    print(f"BB: {result['bb_score']['total']} | TA: {result['ta_score']['total']} | PA: {result['pa_score']['total']}")
    print(f"Cross-Val Bonus: {c['agreement_score']}")
    print(f"BB Dir: {c['bb_direction']} | TA Dir: {c['ta_direction']} | PA Dir: {c['pa_direction']}")
    # Verify JSON serializable
    json.dumps(result)
    print('✅ JSON serialization OK')
    # Test a second stock
    df2 = load_stock_data('TCS.NS', CSV_DIR)
    r2 = run_triple_analysis(df2, ticker='TCS.NS')
    v2 = r2['triple_verdict']
    c2 = r2['cross_validation']
    print(f"\nTCS: {v2['verdict']} | Score: {v2['score']} | Align: {c2['alignment']}")
    print(f"BB: {r2['bb_score']['total']} | TA: {r2['ta_score']['total']} | PA: {r2['pa_score']['total']}")
    json.dumps(r2)
    print('✅ TCS JSON OK')
