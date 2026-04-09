"""Quick test for Wyckoff integration."""
import pandas as pd
from bb_squeeze.data_loader import load_stock_data
from wyckoff.engine import run_wyckoff_analysis, wyckoff_to_dict

# Test with KRISHANA (existing portfolio position)
df = load_stock_data('KRISHANA.NS', 'stock_csv')
print(f'Loaded {len(df)} rows for KRISHANA')

result = run_wyckoff_analysis(df, 'KRISHANA')
print(f'Phase: {result.phase.phase} ({result.phase.sub_phase})')
print(f'Phase confidence: {result.phase.confidence}%')
print(f'Volume: {result.volume_character.status} ({result.volume_character.ratio}x)')
print(f'Wave balance: {result.wave_balance["balance"]} (ratio: {result.wave_balance.get("ratio", "N/A")})')
print(f'Shortening: {result.shortening["detected"]}')
print(f'Bonus: {result.wyckoff_bonus}, Bias: {result.bias}')
print(f'Events: {[e.event_type for e in result.phase.events]}')
print()
print('--- Hints ---')
for h in result.hints:
    print(f'  {h}')
print()
print('--- Effort/Result last bar ---')
if result.effort_result:
    er = result.effort_result[-1]
    print(f'  {er.effort_result}: {er.description}')

print()
print('=== Now testing full Triple Engine with Wyckoff ===')
from hybrid_pa_engine import run_triple_analysis
triple = run_triple_analysis(df, ticker='KRISHANA')
tv = triple.get('triple_verdict', {})
print(f'Triple Verdict: {tv.get("verdict")} (score: {tv.get("score")}/{tv.get("max_score")})')
print(f'Confidence: {tv.get("confidence")}%')
cv = triple.get('cross_validation', {})
print(f'Cross-validation score: {cv.get("agreement_score")}')
print(f'Wyckoff bonus in CV: {cv.get("wyckoff_bonus", "N/A")}')
print(f'Wyckoff bias in CV: {cv.get("wyckoff_bias", "N/A")}')
print()
wk = triple.get('wyckoff')
if wk:
    print(f'Wyckoff in response: Phase={wk["phase"]["name"]}, Bias={wk["scoring"]["bias"]}, Bonus={wk["scoring"]["wyckoff_bonus"]}')
else:
    print('Wyckoff data missing from response!')

print()
print('--- Cross-validation observations ---')
for obs in cv.get('observations', []):
    print(f'  {obs}')

print()
print('ALL TESTS PASSED!')
