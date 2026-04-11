"""Quick check of what yfinance returns for data freshness."""
import yfinance as yf
import pandas as pd

t = yf.Ticker('RELIANCE.NS')

# Check annual financials
inc = t.financials
if inc is not None and not inc.empty:
    print('=== ANNUAL INCOME STMT COLUMNS (years) ===')
    for c in inc.columns:
        print(f'  {c}')
    print(f'  Total columns: {len(inc.columns)}')

print()

# Check quarterly income stmt
qis = t.quarterly_income_stmt
if qis is not None and not qis.empty:
    print('=== QUARTERLY INCOME STMT COLUMNS ===')
    for c in qis.columns:
        print(f'  {c}')
    print(f'  Total columns: {len(qis.columns)}')
    # Show some row names
    print('  Row names:', list(qis.index[:10]))

print()

# Check quarterly balance sheet
qbs = t.quarterly_balance_sheet
if qbs is not None and not qbs.empty:
    print('=== QUARTERLY BALANCE SHEET COLUMNS ===')
    for c in qbs.columns[:6]:
        print(f'  {c}')

# Check quarterly cashflow
qcf = t.quarterly_cashflow
if qcf is not None and not qcf.empty:
    print('=== QUARTERLY CASHFLOW COLUMNS ===')
    for c in qcf.columns[:6]:
        print(f'  {c}')

print()

# Also check what annual BS and CF have
bs = t.balance_sheet
if bs is not None and not bs.empty:
    print('=== ANNUAL BALANCE SHEET COLUMNS ===')
    for c in bs.columns:
        print(f'  {c}')

cf = t.cashflow
if cf is not None and not cf.empty:
    print('=== ANNUAL CASHFLOW COLUMNS ===')
    for c in cf.columns:
        print(f'  {c}')
