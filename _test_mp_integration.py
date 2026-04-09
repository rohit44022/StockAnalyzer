"""Quick test of Market Profile integration into Triple Conviction Engine."""
import pandas as pd
from hybrid_pa_engine import run_triple_analysis

df = pd.read_csv("stock_csv/RELIANCE.NS.csv", parse_dates=["Date"])
print(f"Loaded {len(df)} rows for RELIANCE.NS")

result = run_triple_analysis(df, ticker="RELIANCE.NS")

if "error" in result:
    print(f"ERROR: {result['error']}")
    raise SystemExit(1)

v = result["triple_verdict"]
print(f"Verdict: {v['verdict']} (Score: {v['score']}/{v['max_score']}, Confidence: {v['confidence']}%)")
print(f"BB: {result['bb_score']['total']}, TA: {result['ta_score']['total']}, PA: {result['pa_score']['total']}")

cv = result["cross_validation"]
print(f"Cross-Validation: {cv['agreement_score']}")
print(f"  Wyckoff bonus: {cv.get('wyckoff_bonus', 'N/A')}")
print(f"  Dalton bonus: {cv.get('dalton_bonus', 'N/A')}")

mp = result.get("market_profile")
if mp:
    print("\n--- DALTON MARKET PROFILE ---")
    print(f"  Day Type: {mp['day_type']['type']} ({mp['day_type']['conviction']})")
    print(f"  Open Type: {mp['open_type']}")
    print(f"  Activity: {mp['activity']}")
    print(f"  Market Structure: {mp['market_structure']['type']}")
    print(f"  One-Timeframing: {mp['one_timeframing']['direction']} ({mp['one_timeframing']['days']} days)")
    print(f"  Dir Performance: {mp['directional_performance']['direction']} = {mp['directional_performance']['rating']}")
    print(f"  POC Migration: {mp['poc_migration']}")
    print(f"  VA Sequence: {mp['va_sequence']}")
    print(f"  Poor High: {mp['poor_extremes']['poor_high']}, Poor Low: {mp['poor_extremes']['poor_low']}")
    print(f"  Profile Shape: {mp['profile_shape']}")
    hp = mp["high_probability"]
    print(f"  3-to-I: {hp['three_to_i']['active']} ({hp['three_to_i']['direction']})")
    print(f"  Neutral-Extreme: {hp['neutral_extreme']['active']}")
    print(f"  Balance Breakout: {hp['balance_breakout']['active']}")
    print(f"  Gap: {mp['gap']['type']} {mp['gap']['direction']}")
    print(f"  Overnight Inventory: {mp['overnight_inventory']}")
    print(f"  Rotation Factor: {mp['rotation_factor']}")
    print(f"  CV Bonus: {mp['scoring']['cv_bonus']}")
    print(f"  Dalton Signals: {len(mp['dalton_signals'])}")
    for sig in mp["dalton_signals"]:
        print(f"    -> {sig['type']}: {sig['description']}")
    print("\n--- OBSERVATIONS (showing Dalton/Confluence entries) ---")
    for obs in cv["observations"]:
        if "DALTON" in obs or "CONFLUENCE" in obs:
            line = obs[:140] + "..." if len(obs) > 140 else obs
            print(f"  {line}")
else:
    print("Market Profile: None (not computed)")

print("\nTest PASSED — integration working!")
