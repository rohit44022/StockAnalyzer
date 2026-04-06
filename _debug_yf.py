"""Debug script — verify fundamental data matches screener.in"""
import sys
sys.path.insert(0, ".")
from bb_squeeze.fundamentals import fetch_fundamentals

fd = fetch_fundamentals("TCS.NS")

if fd.fetch_error:
    print(f"ERROR: {fd.fetch_error}")
    sys.exit(1)

print("=" * 70)
print(f"  Company: {fd.company_name}")
print(f"  Ticker:  {fd.ticker}")
print("=" * 70)

# Format large value in Crores
def cr(v):
    if v is None: return "N/A"
    return f"{v/1e7:,.0f} Cr"

print("\n=== VALUATION (compare with screener.in) ===")
print(f"  P/E Ratio (TTM)     : {fd.pe_ratio}       (screener ~17.2)")
print(f"  Forward P/E          : {fd.forward_pe}")
print(f"  P/B Ratio            : {fd.pb_ratio}       (screener ~8.37)")
print(f"  Book Value/share     : {fd.book_value}")
print(f"  EPS (TTM)            : {fd.eps_ttm}       (screener ~131.88)")
print(f"  Graham Number        : {fd.graham_number}")
print(f"  Price/Graham         : {fd.price_to_intrinsic}")
print(f"  EV/EBITDA            : {fd.ev_ebitda}")
print(f"  Earning Yield        : {fd.earning_yield}%")

print("\n=== PROFITABILITY ===")
print(f"  ROE %                : {fd.roe}%           (screener ~52.4%)")
print(f"  ROA %                : {fd.roa}%")
print(f"  ROCE %               : {fd.roce}%          (screener ~64.6%)")
print(f"  Net Margin %         : {fd.profit_margin}%")
print(f"  Operating Margin %   : {fd.operating_margin}%")
print(f"  Gross Margin %       : {fd.gross_margin}%")
print(f"  EBITDA Margin %      : {fd.ebitda_margin}%")

print("\n=== GROWTH ===")
print(f"  Revenue Growth YoY   : {fd.revenue_growth}%")
print(f"  Earnings Growth YoY  : {fd.earnings_growth}%")
print(f"  Total Revenue        : {cr(fd.total_revenue)}")
print(f"  Net Income           : {cr(fd.net_income)}")
print(f"  Free Cash Flow       : {cr(fd.free_cash_flow)}")
print(f"  Total Assets         : {cr(fd.total_assets)}")

print("\n=== STABILITY ===")
print(f"  Debt/Equity RATIO    : {fd.debt_to_equity}  (should be ~0.09 for TCS)")
print(f"  Current Ratio        : {fd.current_ratio}")
print(f"  Quick Ratio          : {fd.quick_ratio}")
print(f"  Cash Ratio           : {fd.cash_ratio}")
print(f"  Debt/EBITDA          : {fd.debt_to_ebitda}")
print(f"  Altman Z-Score       : {fd.altman_z_score}")
print(f"  Total Debt           : {cr(fd.total_debt)}")
print(f"  Total Cash           : {cr(fd.total_cash)}")
print(f"  Shareholders Equity  : {cr(fd.shareholders_equity)}  (should be ~1,06,415 Cr)")

print("\n=== DIVIDENDS ===")
print(f"  Dividend Yield       : {fd.dividend_yield}%  (screener ~2.47%)")
print(f"  Dividend Rate        : {fd.dividend_rate}")
print(f"  Payout Ratio         : {fd.payout_ratio}%")

print("\n=== SHAREHOLDING ===")
print(f"  Promoter             : {fd.promoter_holding}%  (screener ~71.77%)")
print(f"  Institutional FII+DII: {fd.fii_holding}%    (screener FII=10.37%, DII=12.81%)")
print(f"  DII separate         : {fd.dii_holding}      (yfinance cannot split)")
print(f"  Public               : {fd.public_holding}%")
print(f"  Float %              : {fd.float_pct}%")

print("\n=== SCORES ===")
print(f"  Valuation Score      : {fd.valuation_score}")
print(f"  Profitability Score  : {fd.profitability_score}")
print(f"  Growth Score         : {fd.growth_score}")
print(f"  Stability Score      : {fd.stability_score}")
print(f"  Overall Score        : {fd.fundamental_score}")
print(f"  Verdict              : {fd.fundamental_verdict}")

print("\n=== QUARTERLY RESULTS ===")
for q in fd.quarterly_results:
    rev_cr = f"{q.revenue/1e7:,.0f} Cr" if q.revenue else "N/A"
    ni_cr = f"{q.net_income/1e7:,.0f} Cr" if q.net_income else "N/A"
    print(f"  {q.period:10s}  Rev={rev_cr:>15s}  NI={ni_cr:>12s}  EPS={q.eps}")

