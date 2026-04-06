#!/usr/bin/env python3
"""
Comprehensive Fundamental Data Verification
============================================
Cross-checks every ratio our fundamentals.py produces
against raw yfinance values and manual calculations.

Tests:
 1. P/E Ratio           → trailingPE (direct)
 2. Forward P/E          → forwardPE (direct)
 3. P/B Ratio            → priceToBook (direct)
 4. P/S Ratio            → priceToSalesTrailing12Months (direct)
 5. EV/EBITDA            → enterpriseToEbitda (direct)
 6. PEG Ratio            → pegRatio (direct)
 7. EPS (TTM)            → trailingEps (direct)
 8. Earnings Yield       → computed 100/PE (verify)
 9. Graham Number        → √(22.5 × EPS × BV) (verify)
10. Price / Graham       → price / graham_number (verify)
11. Price / FCF          → price / (FCF/shares) (verify)
12. ROE                  → NetIncome(TTM) / Equity (BS) (verify vs .info)
13. ROA                  → returnOnAssets (direct, or computed)
14. ROCE                 → EBIT(TTM) / (TotalAssets - CurrLiab) (verify)
15. Profit Margin        → NetIncome(TTM) / Revenue(TTM) (verify)
16. Operating Margin     → OpIncome(TTM) / Revenue(TTM) (verify)
17. Gross Margin         → grossMargins (direct)
18. EBITDA Margin        → EBITDA(TTM) / Revenue(TTM) (verify)
19. D/E Ratio            → debtToEquity/100 (verify vs BS)
20. Current Ratio        → currentRatio (direct, or CA/CL from BS)
21. Quick Ratio          → quickRatio (direct)
22. Cash Ratio           → Cash / CurrLiab (verify)
23. Debt/EBITDA          → TotalDebt / EBITDA (verify)
24. Altman Z-Score       → manual 4-factor (verify)
25. Dividend Yield       → dividendYield heuristic (verify)
26. Payout Ratio         → payoutRatio (verify)
27. Shareholding         → heldPercentInsiders / heldPercentInstitutions (verify)
28. Quarterly Results    → from quarterly_income_stmt (verify EPS)
"""

import sys, os, math
import pandas as pd
import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import yfinance as yf
from bb_squeeze.fundamentals import fetch_fundamentals

# ───────────────────────────────────────────────────
TICKER = "RELIANCE.NS"
TOLERANCE_PCT = 2.0   # allow 2% relative difference
TOLERANCE_ABS = 0.5   # allow 0.5 absolute difference for small values

# ───────────────────────────────────────────────────
MULTI_TICKERS = ["TCS.NS", "RELIANCE.NS", "INFY.NS"]

# ───────────────────────────────────────────────────
def close(a, b, label, tol_pct=TOLERANCE_PCT, tol_abs=TOLERANCE_ABS):
    """Check two values are close; print PASS/FAIL."""
    if a is None and b is None:
        print(f"  ✅ {label:35s}  Both None — SKIP")
        return True
    if a is None or b is None:
        print(f"  ⚠️  {label:35s}  ours={a}  raw={b} — ONE IS NONE")
        return False  # not necessarily wrong, but flagged
    diff = abs(a - b)
    ref  = max(abs(a), abs(b), 1e-9)
    pct  = diff / ref * 100
    ok   = diff <= tol_abs or pct <= tol_pct
    icon = "✅" if ok else "❌"
    print(f"  {icon} {label:35s}  ours={a:>12.4f}  raw={b:>12.4f}  diff={diff:.4f} ({pct:.2f}%)")
    return ok


def main_for_ticker(TICKER):
    print(f"\n{'='*70}")
    print(f"  FUNDAMENTAL VERIFICATION — {TICKER}")
    print(f"{'='*70}\n")

    # Fetch our data
    print("Fetching via our fundamentals.py ...")
    fd = fetch_fundamentals(TICKER)
    if fd.fetch_error:
        print(f"  ERROR: {fd.fetch_error}")
        return

    # Fetch raw yfinance data
    print("Fetching raw yfinance data ...")
    yf_t = yf.Ticker(TICKER)
    info = yf_t.info or {}
    bs   = yf_t.quarterly_balance_sheet
    qis  = yf_t.quarterly_income_stmt

    passed, failed, warned = 0, 0, 0

    def check(a, b, label, **kw):
        nonlocal passed, failed, warned
        r = close(a, b, label, **kw)
        if r is True:
            passed += 1
        elif r is False:
            if a is None or b is None:
                warned += 1
            else:
                failed += 1

    # ═══════════ SECTION 1: DIRECT .info RATIOS ═══════════
    print("\n── SECTION 1: Direct .info Ratios ──")
    check(fd.pe_ratio,   float(info.get("trailingPE", 0)) if info.get("trailingPE") else None, "P/E Ratio (TTM)")
    check(fd.forward_pe, float(info.get("forwardPE", 0)) if info.get("forwardPE") else None,  "Forward P/E")
    check(fd.pb_ratio,   float(info.get("priceToBook", 0)) if info.get("priceToBook") else None, "P/B Ratio")
    check(fd.ps_ratio,   float(info.get("priceToSalesTrailing12Months", 0)) if info.get("priceToSalesTrailing12Months") else None, "P/S Ratio")
    check(fd.ev_ebitda,  float(info.get("enterpriseToEbitda", 0)) if info.get("enterpriseToEbitda") else None, "EV/EBITDA")
    check(fd.peg_ratio,  float(info.get("pegRatio", 0)) if info.get("pegRatio") else None, "PEG Ratio")
    check(fd.eps_ttm,    float(info.get("trailingEps", 0)) if info.get("trailingEps") else None, "EPS (TTM)")
    check(fd.eps_forward, float(info.get("forwardEps", 0)) if info.get("forwardEps") else None, "EPS (Forward)")
    check(fd.book_value, float(info.get("bookValue", 0)) if info.get("bookValue") else None, "Book Value/Share")
    check(fd.beta,       float(info.get("beta", 0)) if info.get("beta") else None, "Beta", tol_abs=0.1)
    check(fd.current_ratio, float(info.get("currentRatio", 0)) if info.get("currentRatio") else None, "Current Ratio")
    check(fd.quick_ratio,   float(info.get("quickRatio", 0)) if info.get("quickRatio") else None, "Quick Ratio")

    # ═══════════ SECTION 2: COMPUTED RATIOS ═══════════
    print("\n── SECTION 2: Computed Ratios ──")

    # Earnings Yield = 100 / PE
    if fd.pe_ratio and fd.pe_ratio > 0:
        expected_ey = round(100.0 / fd.pe_ratio, 2)
        check(fd.earning_yield, expected_ey, "Earnings Yield = 100/PE")

    # Graham Number = √(22.5 × EPS × BV)
    raw_eps = float(info.get("trailingEps", 0)) if info.get("trailingEps") else None
    raw_bv  = float(info.get("bookValue", 0)) if info.get("bookValue") else None
    if raw_eps and raw_bv and raw_eps > 0 and raw_bv > 0:
        expected_gn = round(math.sqrt(22.5 * raw_eps * raw_bv), 2)
        check(fd.graham_number, expected_gn, "Graham Number")

    # Price / Graham
    if fd.graham_number and fd.graham_number > 0 and fd.current_price > 0:
        expected_ptg = round(fd.current_price / fd.graham_number, 3)
        check(fd.price_to_intrinsic, expected_ptg, "Price / Graham Number")

    # Price / FCF
    raw_fcf    = float(info.get("freeCashflow", 0)) if info.get("freeCashflow") else None
    raw_shares = float(info.get("sharesOutstanding", 0)) if info.get("sharesOutstanding") else None
    raw_price  = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0)
    if raw_fcf and raw_shares and raw_shares > 0 and raw_price > 0:
        fcf_per = raw_fcf / raw_shares
        if fcf_per > 0:
            expected_pfcf = round(raw_price / fcf_per, 2)
            check(fd.price_to_fcf, expected_pfcf, "Price / FCF")

    # ═══════════ SECTION 3: PROFITABILITY (BS/IS computed) ═══════════
    print("\n── SECTION 3: Profitability (Financial Statements) ──")

    # Get raw values from financial statements
    def _bs_get(name):
        if bs is None or bs.empty: return None
        col = bs.columns[0]
        for idx in bs.index:
            if str(idx).strip().lower() == name.lower():
                v = bs.loc[idx, col]
                return float(v) if pd.notna(v) else None
        return None

    def _is_ttm(name):
        if qis is None or qis.empty: return None
        ncols = min(4, len(qis.columns))
        for idx in qis.index:
            if str(idx).strip().lower() == name.lower():
                vals = [qis.loc[idx, qis.columns[c]] for c in range(ncols)]
                valid = [float(v) for v in vals if pd.notna(v)]
                return sum(valid) if valid else None
        return None

    equity_bs     = _bs_get("Stockholders Equity") or _bs_get("Common Stock Equity")
    net_inc_ttm   = _is_ttm("Net Income Common Stockholders") or _is_ttm("Net Income")
    op_inc_ttm    = _is_ttm("Operating Income")
    ebit_ttm      = _is_ttm("EBIT")
    ebitda_ttm    = _is_ttm("EBITDA")
    revenue_ttm   = _is_ttm("Total Revenue")
    total_assets  = _bs_get("Total Assets")
    curr_liab     = _bs_get("Current Liabilities")
    curr_assets   = _bs_get("Current Assets")
    total_debt_bs = _bs_get("Total Debt")
    cash_bs       = _bs_get("Cash And Cash Equivalents") or _bs_get("Cash Cash Equivalents And Short Term Investments")

    # ROE = NetIncome(TTM) / Equity
    if net_inc_ttm and equity_bs and equity_bs > 0:
        expected_roe = round((net_inc_ttm / equity_bs) * 100, 2)
        check(fd.roe, expected_roe, "ROE (BS-computed)")

    # ROCE = EBIT(TTM) / (TotalAssets - CurrLiab)
    ebit_roce = ebit_ttm or op_inc_ttm
    if ebit_roce and total_assets and curr_liab:
        cap_emp = total_assets - curr_liab
        if cap_emp > 0:
            expected_roce = round((ebit_roce / cap_emp) * 100, 2)
            check(fd.roce, expected_roce, "ROCE (BS-computed)")

    # Profit Margin = NetIncome(TTM) / Revenue(TTM)
    if net_inc_ttm and revenue_ttm and revenue_ttm > 0:
        expected_pm = round((net_inc_ttm / revenue_ttm) * 100, 2)
        check(fd.profit_margin, expected_pm, "Net Profit Margin (TTM)")

    # Operating Margin = OpIncome(TTM) / Revenue(TTM)
    if op_inc_ttm and revenue_ttm and revenue_ttm > 0:
        expected_om = round((op_inc_ttm / revenue_ttm) * 100, 2)
        check(fd.operating_margin, expected_om, "Operating Margin (TTM)")

    # EBITDA Margin = EBITDA(TTM) / Revenue(TTM)
    if ebitda_ttm and revenue_ttm and revenue_ttm > 0:
        expected_em = round((ebitda_ttm / revenue_ttm) * 100, 2)
        check(fd.ebitda_margin, expected_em, "EBITDA Margin (TTM)")

    # Gross Margin (from .info — compare)
    raw_gm = info.get("grossMargins")
    if raw_gm:
        expected_gm = round(float(raw_gm) * 100, 2) if abs(float(raw_gm)) <= 1 else round(float(raw_gm), 2)
        check(fd.gross_margin, expected_gm, "Gross Margin (.info)")

    # ROA from .info
    raw_roa = info.get("returnOnAssets")
    if raw_roa:
        expected_roa_info = round(float(raw_roa) * 100, 2) if abs(float(raw_roa)) <= 1 else round(float(raw_roa), 2)
        # Our code uses .info value when available (it only computes from BS if .info is None)
        # Yahoo's ROA uses average total assets, which is more accurate than single-quarter
        check(fd.roa, expected_roa_info, "ROA (.info — Yahoo avg assets)")

    # ═══════════ SECTION 4: STABILITY ═══════════
    print("\n── SECTION 4: Stability Ratios ──")

    # D/E = debtToEquity / 100  (yfinance returns percentage)
    raw_de = info.get("debtToEquity")
    if raw_de is not None:
        expected_de = round(float(raw_de) / 100.0, 4)
        check(fd.debt_to_equity, expected_de, "D/E (debtToEquity/100)")

    # Also verify D/E from balance sheet
    if total_debt_bs and equity_bs and equity_bs > 0:
        expected_de_bs = round(total_debt_bs / equity_bs, 4)
        print(f"  📊 D/E from BS: {expected_de_bs:.4f} (Debt={total_debt_bs/1e7:.0f} Cr / Equity={equity_bs/1e7:.0f} Cr)")
        if fd.debt_to_equity:
            check(fd.debt_to_equity, expected_de_bs, "D/E (vs Balance Sheet)", tol_pct=5.0, tol_abs=0.05)

    # Cash Ratio = Pure Cash & Equivalents / CurrLiab (strictest definition)
    # We prefer "Cash And Cash Equivalents" (pure cash) over totalCash (.info)
    pure_cash_bs = _bs_get("Cash And Cash Equivalents")
    cash_for_cr  = pure_cash_bs or cash_bs
    if cash_for_cr and curr_liab and curr_liab > 0:
        expected_cr = round(cash_for_cr / curr_liab, 2)
        check(fd.cash_ratio, expected_cr, "Cash Ratio (pure cash / CL)")

    # Debt/EBITDA
    raw_debt  = float(info.get("totalDebt", 0)) if info.get("totalDebt") else total_debt_bs
    raw_ebitda = float(info.get("ebitda", 0)) if info.get("ebitda") else None
    if raw_debt and raw_ebitda and raw_ebitda > 0:
        expected_de2 = round(raw_debt / raw_ebitda, 3)
        check(fd.debt_to_ebitda, expected_de2, "Debt/EBITDA")

    # Altman Z-Score (manual computation)
    total_liab = _bs_get("Total Liabilities Net Minority Interest")
    retained   = _bs_get("Retained Earnings")
    if total_assets and total_assets > 0 and curr_assets and curr_liab and ebit_roce and equity_bs and total_liab and total_liab > 0:
        wc = curr_assets - curr_liab
        re = retained if retained else 0
        x1 = wc / total_assets
        x2 = re / total_assets
        x3 = ebit_roce / total_assets
        x4 = equity_bs / total_liab
        expected_z = round(6.56*x1 + 3.26*x2 + 6.72*x3 + 1.05*x4, 2)
        check(fd.altman_z_score, expected_z, "Altman Z-Score (manual)")

    # ═══════════ SECTION 5: DIVIDENDS ═══════════
    print("\n── SECTION 5: Dividends ──")
    raw_dy = info.get("dividendYield")
    raw_dr = info.get("dividendRate")
    raw_price = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0)
    if raw_dy is not None:
        dv = float(raw_dy)
        # Cross-validate: manual yield = rate/price * 100
        if raw_dr and raw_price > 0:
            manual_yield = round((float(raw_dr) / raw_price) * 100, 2)
            diff_as_pct  = abs(dv - manual_yield)
            diff_as_frac = abs(dv * 100 - manual_yield)
            if diff_as_pct <= diff_as_frac:
                expected_dy = round(dv, 2)
            else:
                expected_dy = round(dv * 100, 2)
            print(f"  📊 Raw dividendYield={dv}  rate={raw_dr}  price={raw_price}  manual={manual_yield}%")
            check(fd.dividend_yield, expected_dy, "Dividend Yield (cross-validated)")
        else:
            expected_dy = round(dv * 100, 2) if dv < 1 else round(dv, 2)
            check(fd.dividend_yield, expected_dy, "Dividend Yield")

    raw_pr = info.get("payoutRatio")
    if raw_pr is not None:
        pr = float(raw_pr)
        expected_pr = round(pr * 100, 2) if abs(pr) <= 1 else round(pr, 2)
        check(fd.payout_ratio, expected_pr, "Payout Ratio")

    # ═══════════ SECTION 6: SHAREHOLDING ═══════════
    print("\n── SECTION 6: Shareholding ──")
    raw_ins = info.get("heldPercentInsiders")
    raw_inst = info.get("heldPercentInstitutions")
    if raw_ins is not None:
        pct_ins = round(float(raw_ins) * 100, 2) if abs(float(raw_ins)) <= 1 else round(float(raw_ins), 2)
        check(fd.promoter_holding, pct_ins, "Promoter (Insider) Holding")
    if raw_inst is not None:
        pct_inst = round(float(raw_inst) * 100, 2) if abs(float(raw_inst)) <= 1 else round(float(raw_inst), 2)
        check(fd.fii_holding, pct_inst, "Institutional (FII+DII) Holding")

    # ═══════════ SECTION 7: QUARTERLY RESULTS ═══════════
    print("\n── SECTION 7: Quarterly Results ──")
    if qis is not None and not qis.empty and fd.quarterly_results:
        print(f"  📊 Quarters fetched: {len(fd.quarterly_results)}")
        # Check latest quarter vs raw
        latest = fd.quarterly_results[0]
        col0 = qis.columns[0]
        raw_rev = None
        for idx in qis.index:
            if "total revenue" in str(idx).lower():
                v = qis.loc[idx, col0]
                if pd.notna(v): raw_rev = float(v)
                break
        raw_ni = None
        for idx in qis.index:
            if "net income common stockholders" in str(idx).lower() or "net income" == str(idx).strip().lower():
                v = qis.loc[idx, col0]
                if pd.notna(v): raw_ni = float(v)
                break
        if raw_rev:
            check(latest.revenue, raw_rev, f"Q: {latest.period} Revenue")
        if raw_ni:
            check(latest.net_income, raw_ni, f"Q: {latest.period} Net Income")

        # Check EPS = NI / shares
        shares_out = float(info.get("sharesOutstanding", 0)) if info.get("sharesOutstanding") else None
        if raw_ni and shares_out and shares_out > 0:
            expected_eps = round(raw_ni / shares_out, 2)
            # Our code prefers Diluted EPS from statement, so they may differ slightly
            raw_dil_eps = None
            for idx in qis.index:
                if "diluted eps" in str(idx).lower():
                    v = qis.loc[idx, col0]
                    if pd.notna(v): raw_dil_eps = round(float(v), 2)
                    break
            if raw_dil_eps:
                check(latest.eps, raw_dil_eps, f"Q: {latest.period} EPS (Diluted)")
            else:
                check(latest.eps, expected_eps, f"Q: {latest.period} EPS (computed)")

    # ═══════════ SECTION 8: SCORING SANITY ═══════════
    print("\n── SECTION 8: Score Sanity ──")
    print(f"  Valuation Score:     {fd.valuation_score}/100")
    print(f"  Profitability Score: {fd.profitability_score}/100")
    print(f"  Growth Score:        {fd.growth_score}/100")
    print(f"  Stability Score:     {fd.stability_score}/100")
    print(f"  Overall Score:       {fd.fundamental_score}/100")
    print(f"  Verdict:             {fd.fundamental_verdict}")

    # Verify overall = weighted avg
    expected_overall = int(
        (fd.valuation_score * 25 + fd.profitability_score * 30 +
         fd.growth_score * 25 + fd.stability_score * 20) / 100
    )
    check(float(fd.fundamental_score), float(expected_overall), "Overall Score = weighted avg", tol_abs=1)

    # ═══════════ SUMMARY ═══════════
    print(f"\n{'='*70}")
    print(f"  RESULTS:  ✅ {passed} PASS  |  ❌ {failed} FAIL  |  ⚠️  {warned} WARN")
    print(f"{'='*70}")
    if failed == 0:
        print("  🎉  ALL FUNDAMENTAL VALUES VERIFIED!\n")
    else:
        print(f"  ⚠️  {failed} value(s) need investigation.\n")

    return failed


if __name__ == "__main__":
    total_fails = 0
    for ticker in MULTI_TICKERS:
        # Override module-level TICKER for each run
        import types
        mod = types.SimpleNamespace(TICKER=ticker)
        total_fails += main_for_ticker(ticker) or 0
        print()
    if total_fails == 0:
        print("🎉  ALL STOCKS VERIFIED — ZERO FAILURES!")
    else:
        print(f"⚠️  Total failures across all stocks: {total_fails}")
    sys.exit(total_fails)
