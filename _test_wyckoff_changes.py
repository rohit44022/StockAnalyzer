"""Quick validation of all Wyckoff code changes."""
from wyckoff.engine import run_wyckoff_analysis, wyckoff_to_dict
from wyckoff.phases import assess_follow_through, detect_absorption, detect_change_in_behavior
from wyckoff.volume_analysis import compute_weis_waves, compare_wave_volumes
import pandas as pd
import os

# Pick a CSV file
csvs = [f for f in os.listdir("stock_csv") if f.endswith(".csv")]
df = pd.read_csv(f"stock_csv/{csvs[0]}")
print(f"Testing with {csvs[0]}, {len(df)} rows")

result = run_wyckoff_analysis(df, "TEST")
d = wyckoff_to_dict(result)

print(f"Phase: {d['phase']['name']} ({d['phase']['sub_phase']})")
print(f"Events: {[e['type'] for e in d['phase']['events']]}")
print(f"Bonus: {d['scoring']['wyckoff_bonus']}, Bias: {d['scoring']['bias']}")
print(f"Follow-through: {d['follow_through']}")
print(f"Duration ratio: {d['wave_balance'].get('duration_ratio', 'N/A')}")
print(f"Duration note: {d['wave_balance'].get('duration_note', 'N/A')}")
print("\nALL IMPORTS AND FUNCTIONS OK")
