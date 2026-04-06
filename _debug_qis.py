"""Check quarterly income statement columns."""
import yfinance as yf
t = yf.Ticker("TCS.NS")
qis = t.quarterly_income_stmt
if qis is not None and not qis.empty:
    print("Quarterly Income Statement columns (dates):")
    for i, col in enumerate(qis.columns[:8]):
        print(f"  [{i}] {col}")
    print(f"\nTotal columns: {len(qis.columns)}")
    print(f"\nRow labels: {list(qis.index[:20])}")
