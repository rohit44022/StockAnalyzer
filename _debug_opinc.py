"""Debug the _is_val function."""
import yfinance as yf
import pandas as pd

t = yf.Ticker("TCS.NS")
qis = t.quarterly_income_stmt

# Check what rows match "operating income"
if qis is not None and not qis.empty:
    for idx in qis.index:
        if "operating" in str(idx).lower():
            vals = [qis.loc[idx, qis.columns[c]] for c in range(min(4, len(qis.columns)))]
            print(f"  {str(idx):55s} = {vals}")
    print()
    # Also check "net non operating"
    for idx in qis.index:
        if "net non operating" in str(idx).lower() or "interest income expense" in str(idx).lower():
            vals = [qis.loc[idx, qis.columns[c]] for c in range(min(4, len(qis.columns)))]
            print(f"  {str(idx):55s} = {vals}")
