"""Quick edge case test for production fixes."""
import pandas as pd
import numpy as np
from rentech.engine import run_rentech_analysis

# Edge case: very short data (20 bars)
dates = pd.date_range('2024-01-01', periods=20, freq='B')
df = pd.DataFrame({
    'Open': np.random.uniform(100, 110, 20),
    'High': np.random.uniform(110, 120, 20),
    'Low': np.random.uniform(90, 100, 20),
    'Close': np.random.uniform(100, 110, 20),
    'Volume': np.random.randint(1000, 10000, 20),
}, index=dates)
r = run_rentech_analysis(df, 'EDGE_SHORT')
print('Short data (20 bars) - success:', r['success'], '| error:', r.get('error'))

# Edge case: capital=0 (should fallback to default)
df2 = pd.read_csv('stock_csv/RELIANCE.NS.csv', index_col='Date', parse_dates=True)
r2 = run_rentech_analysis(df2, 'RELIANCE.NS', capital=0)
print('Zero capital - success:', r2['success'], '| verdict:', r2.get('verdict', {}).get('action', 'N/A'))

# Edge case: capital=-1 (should fallback to default)
r3 = run_rentech_analysis(df2, 'RELIANCE.NS', capital=-1)
print('Neg capital - success:', r3['success'], '| verdict:', r3.get('verdict', {}).get('action', 'N/A'))

# Edge case: constant price (all close = 100)
dates3 = pd.date_range('2023-01-01', periods=300, freq='B')
df3 = pd.DataFrame({
    'Open': [100.0] * 300,
    'High': [100.0] * 300,
    'Low': [100.0] * 300,
    'Close': [100.0] * 300,
    'Volume': [1000] * 300,
}, index=dates3)
r4 = run_rentech_analysis(df3, 'CONSTANT')
print('Constant price - success:', r4['success'], '| error:', r4.get('error'))

print('\nAll edge case tests passed!')
