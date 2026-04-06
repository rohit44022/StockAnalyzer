"""Check ALL row labels in quarterly income statement."""
import yfinance as yf
t = yf.Ticker("TCS.NS")
qis = t.quarterly_income_stmt
if qis is not None and not qis.empty:
    print("ALL row labels:")
    for i, idx in enumerate(qis.index):
        col0 = qis.columns[0]
        val = qis.loc[idx, col0]
        print(f"  [{i:2d}] {str(idx):60s} = {val}")
