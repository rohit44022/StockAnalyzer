"""Quick API output verification."""
from market_profile.engine import run_market_profile_analysis, market_profile_to_dict
import pandas as pd, json

df = pd.read_csv('stock_csv/RELIANCE.NS.csv')
mp = run_market_profile_analysis(df)
d = market_profile_to_dict(mp)

required_keys = ['value_area', 'day_type', 'open_type', 'open_vs_prev', 'activity',
                 'directional_performance', 'market_structure', 'one_timeframing',
                 'poor_extremes', 'profile_shape', 'high_probability', 'gap',
                 'overnight_inventory', 'rotation_factor', 'poc_migration',
                 'va_sequence', 'scoring', 'dalton_signals', 'observations', 'summary']
missing = [k for k in required_keys if k not in d]
print('Missing keys:', missing if missing else 'NONE - all present')
print('Observations:', len(d['observations']))
print('Signals:', len(d['dalton_signals']))
print('Summary:', d['summary'][:150])
print('JSON OK:', bool(json.dumps(d)))
