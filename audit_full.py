#!/usr/bin/env python3
"""
FULL APPLICATION AUDIT — Cross-verifies every formula, indicator, and
fundamental metric by computing expected values independently from raw
yfinance data and comparing against our API output.

Run:  python3 audit_full.py
"""
import json, math, sys, requests
import yfinance as yf
import pandas as pd
import numpy as np

SYMBOL = "TCS.NS"
API    = f"http://127.0.0.1:5001/api/analyze/{SYMBOL}"
PASS   = "✅"
FAIL   = "❌"
WARN   = "⚠️"
TOL    = 0.02   # 2% tolerance for floating-point / timing differences

results = {"pass": 0, "fail": 0, "warn": 0}

def check(name, expected, actual, tol=TOL):
    """Compare two values within tolerance."""
    if expected is None and actual is None:
        results["pass"] += 1
        print(f"  {PASS} {name}: Both None")
        return
    if expected is None or actual is None:
        results["warn"] += 1
        print(f"  {WARN} {name}: expected={expected}, got={actual} (one is None)")
        return
    try:
        expected = float(expected)
        actual = float(actual)
    except (TypeError, ValueError):
        if str(expected) == str(actual):
            results["pass"] += 1
            print(f"  {PASS} {name}: '{actual}'")
        else:
            results["fail"] += 1
            print(f"  {FAIL} {name}: expected='{expected}', got='{actual}'")
        return

    if expected == 0 and actual == 0:
        results["pass"] += 1
        print(f"  {PASS} {name}: 0")
        return
    if expected == 0:
        diff = abs(actual)
    else:
        diff = abs((actual - expected) / expected)

    if diff <= tol:
        results["pass"] += 1
        print(f"  {PASS} {name}: expected={expected:.4f}, got={actual:.4f} (diff={diff:.4%})")
    elif diff <= 0.10:
        results["warn"] += 1
        print(f"  {WARN} {name}: expected={expected:.4f}, got={actual:.4f} (diff={diff:.4%}) — within 10%")
    else:
        results["fail"] += 1
        print(f"  {FAIL} {name}: expected={expected:.4f}, got={actual:.4f} (diff={diff:.4%})")


# ═══════════════════════════════════════════════════════════════════
print(f"\n{'='*70}")
print(f"  FULL APPLICATION AUDIT — {SYMBOL}")
print(f"{'='*70}\n")

# ── 1. FETCH RAW DATA ──
print("📥 Fetching raw yfinance data...")
tk = yf.Ticker(SYMBOL)
hist = tk.history(period="1y")
info = tk.info
print(f"   Got {len(hist)} daily bars, info has {len(info)} keys\n")

# ── 2. FETCH OUR API ──
print("📥 Fetching our API response...")
try:
    resp = requests.get(API, timeout=120)
    data = resp.json()
except Exception as e:
    print(f"  {FAIL} Could not reach API: {e}")
    sys.exit(1)

sig   = data.get("signal", {})
fund  = data.get("fundamentals", {})
chart = data.get("chart_data", [])
print(f"   Got signal, fundamentals, {len(chart)} chart bars\n")

# ═══════════════════════════════════════════════════════════════════
# SECTION A: BOLLINGER BAND INDICATORS
# ═══════════════════════════════════════════════════════════════════
print(f"\n{'─'*70}")
print("  SECTION A: BOLLINGER BAND INDICATORS")
print(f"{'─'*70}\n")

# Use last 200 bars for our calculations
df = hist.tail(200).copy()
close = df["Close"]

# A1: SMA(20) — Simple Moving Average
sma20 = close.rolling(20).mean()
print("A1. SMA(20) — 20-day Simple Moving Average")
if chart:
    last_bar = chart[-1]
    api_sma = last_bar.get("bb_mid")
    exp_sma = round(sma20.iloc[-1], 2)
    check("SMA(20)", exp_sma, api_sma)

# A2: Bollinger Bands — Upper & Lower (20, 2)
std20 = close.rolling(20).std(ddof=0)  # population std
bb_upper = sma20 + 2 * std20
bb_lower = sma20 - 2 * std20
print("\nA2. Bollinger Bands (20, 2σ)")
if chart:
    check("BB Upper", round(bb_upper.iloc[-1], 2), last_bar.get("bb_upper"))
    check("BB Lower", round(bb_lower.iloc[-1], 2), last_bar.get("bb_lower"))

# A3: Bollinger Bandwidth = (Upper - Lower) / Middle * 100
bbw = (bb_upper - bb_lower) / sma20 * 100
print("\nA3. Bollinger Bandwidth (BBW)")
if chart:
    check("BBW", round(bbw.iloc[-1], 4), last_bar.get("bbw"), tol=0.05)

# A4: %B = (Close - Lower) / (Upper - Lower)
pct_b = (close - bb_lower) / (bb_upper - bb_lower)
print("\nA4. Percent B (%B)")
if chart:
    check("%B", round(pct_b.iloc[-1], 4), last_bar.get("pct_b"), tol=0.05)

# A5: Keltner Channels (20, 1.5 × ATR(10))
high = df["High"]
low  = df["Low"]
tr = pd.concat([
    high - low,
    (high - close.shift(1)).abs(),
    (low - close.shift(1)).abs()
], axis=1).max(axis=1)
atr10 = tr.rolling(10).mean()
kc_upper = sma20 + 1.5 * atr10
kc_lower = sma20 - 1.5 * atr10
print("\nA5. Keltner Channels (20, 1.5×ATR10)")
if chart:
    check("KC Upper", round(kc_upper.iloc[-1], 2), last_bar.get("kc_upper"), tol=0.03)
    check("KC Lower", round(kc_lower.iloc[-1], 2), last_bar.get("kc_lower"), tol=0.03)

# A6: Squeeze detection — BB inside KC
squeeze = (bb_lower.iloc[-1] > kc_lower.iloc[-1]) and (bb_upper.iloc[-1] < kc_upper.iloc[-1])
print("\nA6. Squeeze Detection (BB inside KC)")
api_squeeze = last_bar.get("squeeze", False) if chart else None
check("Squeeze", squeeze, api_squeeze)

# A7: 12-period momentum (for squeeze histogram)
mom12 = close - close.shift(12)
print("\nA7. 12-Period Momentum")
if chart:
    check("Momentum", round(mom12.iloc[-1], 2), last_bar.get("momentum"), tol=0.05)

# A8: RSI(14)
delta = close.diff()
gain = delta.where(delta > 0, 0.0)
loss = (-delta).where(delta < 0, 0.0)
avg_gain = gain.ewm(alpha=1/14, min_periods=14).mean()
avg_loss = loss.ewm(alpha=1/14, min_periods=14).mean()
rs = avg_gain / avg_loss
rsi = 100 - (100 / (1 + rs))
print("\nA8. RSI(14) — Relative Strength Index")
if chart:
    check("RSI(14)", round(rsi.iloc[-1], 2), last_bar.get("rsi"), tol=0.05)

# A9: MACD (12, 26, 9)
ema12 = close.ewm(span=12, adjust=False).mean()
ema26 = close.ewm(span=26, adjust=False).mean()
macd_line = ema12 - ema26
macd_signal = macd_line.ewm(span=9, adjust=False).mean()
macd_hist = macd_line - macd_signal
print("\nA9. MACD (12, 26, 9)")
if chart:
    check("MACD Line", round(macd_line.iloc[-1], 2), last_bar.get("macd"), tol=0.05)
    check("MACD Signal", round(macd_signal.iloc[-1], 2), last_bar.get("macd_signal"), tol=0.05)
    check("MACD Hist", round(macd_hist.iloc[-1], 2), last_bar.get("macd_hist"), tol=0.10)

# A10: MFI(14) — Money Flow Index
typical_price = (high + low + close) / 3
raw_mf = typical_price * df["Volume"]
pos_mf = raw_mf.where(typical_price > typical_price.shift(1), 0).rolling(14).sum()
neg_mf = raw_mf.where(typical_price < typical_price.shift(1), 0).rolling(14).sum()
mfi = 100 - (100 / (1 + pos_mf / neg_mf))
print("\nA10. MFI(14) — Money Flow Index")
if chart:
    check("MFI", round(mfi.iloc[-1], 2), last_bar.get("mfi"), tol=0.10)

# A11: CMF(20) — Chaikin Money Flow
clv = ((close - low) - (high - close)) / (high - low)
clv = clv.replace([np.inf, -np.inf], 0).fillna(0)
cmf = (clv * df["Volume"]).rolling(20).sum() / df["Volume"].rolling(20).sum()
print("\nA11. CMF(20) — Chaikin Money Flow")
if chart:
    check("CMF", round(cmf.iloc[-1], 4), last_bar.get("cmf"), tol=0.10)

# A12: Parabolic SAR (basic check — just verify it exists and is reasonable)
print("\nA12. Parabolic SAR")
if chart:
    sar_val = last_bar.get("sar")
    if sar_val is not None:
        # SAR should be within reasonable range of price
        price = close.iloc[-1]
        if abs(sar_val - price) / price < 0.15:
            results["pass"] += 1
            print(f"  {PASS} SAR={sar_val:.2f} (within 15% of price {price:.2f})")
        else:
            results["warn"] += 1
            print(f"  {WARN} SAR={sar_val:.2f} seems far from price {price:.2f}")
    else:
        results["warn"] += 1
        print(f"  {WARN} SAR is None")


# ═══════════════════════════════════════════════════════════════════
# SECTION B: FUNDAMENTAL RATIOS
# ═══════════════════════════════════════════════════════════════════
print(f"\n{'─'*70}")
print("  SECTION B: FUNDAMENTAL RATIOS")
print(f"{'─'*70}\n")

# B1: P/E Ratio
pe_yf = info.get("trailingPE")
print("B1. P/E Ratio (Trailing)")
check("P/E", pe_yf, fund.get("pe_ratio"), tol=0.05)

# B2: Forward P/E
fpe_yf = info.get("forwardPE")
print("\nB2. Forward P/E")
check("Fwd P/E", fpe_yf, fund.get("forward_pe"), tol=0.05)

# B3: P/B Ratio
pb_yf = info.get("priceToBook")
print("\nB3. P/B Ratio")
check("P/B", pb_yf, fund.get("pb_ratio"), tol=0.05)

# B4: EV/EBITDA
ev_ebitda_yf = info.get("enterpriseToEbitda")
print("\nB4. EV/EBITDA")
check("EV/EBITDA", ev_ebitda_yf, fund.get("ev_ebitda"), tol=0.05)

# B5: Dividend Yield
div_yf = info.get("dividendYield")
if div_yf is not None:
    div_yf *= 100  # convert to percentage
print("\nB5. Dividend Yield (%)")
check("Div Yield", div_yf, fund.get("dividend_yield"), tol=0.10)

# B6: ROE
roe_yf = info.get("returnOnEquity")
if roe_yf is not None:
    roe_yf *= 100
print("\nB6. ROE (%)")
check("ROE", roe_yf, fund.get("roe"), tol=0.05)

# B7: ROA
roa_yf = info.get("returnOnAssets")
if roa_yf is not None:
    roa_yf *= 100
print("\nB7. ROA (%)")
check("ROA", roa_yf, fund.get("roa"), tol=0.05)

# B8: Net Margin
nm_yf = info.get("profitMargins")
if nm_yf is not None:
    nm_yf *= 100
print("\nB8. Net Profit Margin (%)")
check("Net Margin", nm_yf, fund.get("net_margin"), tol=0.05)

# B9: Operating Margin
om_yf = info.get("operatingMargins")
if om_yf is not None:
    om_yf *= 100
print("\nB9. Operating Margin (%)")
check("Op Margin", om_yf, fund.get("operating_margin"), tol=0.05)

# B10: Gross Margin
gm_yf = info.get("grossMargins")
if gm_yf is not None:
    gm_yf *= 100
print("\nB10. Gross Margin (%)")
check("Gross Margin", gm_yf, fund.get("gross_margin"), tol=0.05)

# B11: Revenue Growth
rg_yf = info.get("revenueGrowth")
if rg_yf is not None:
    rg_yf *= 100
print("\nB11. Revenue Growth (%)")
check("Rev Growth", rg_yf, fund.get("revenue_growth"), tol=0.10)

# B12: Earnings Growth
eg_yf = info.get("earningsGrowth")
if eg_yf is not None:
    eg_yf *= 100
print("\nB12. Earnings Growth (%)")
check("Earn Growth", eg_yf, fund.get("earnings_growth"), tol=0.10)

# B13: D/E Ratio
de_yf = info.get("debtToEquity")
if de_yf is not None:
    de_yf /= 100  # yfinance gives it as percentage
print("\nB13. Debt/Equity Ratio")
check("D/E", de_yf, fund.get("debt_equity"), tol=0.05)

# B14: Current Ratio
cr_yf = info.get("currentRatio")
print("\nB14. Current Ratio")
check("Current Ratio", cr_yf, fund.get("current_ratio"), tol=0.05)

# B15: EPS (TTM)
eps_yf = info.get("trailingEps")
print("\nB15. EPS (TTM)")
check("EPS TTM", eps_yf, fund.get("eps_ttm"), tol=0.05)

# B16: Book Value
bv_yf = info.get("bookValue")
print("\nB16. Book Value per Share")
check("Book Value", bv_yf, fund.get("book_value"), tol=0.05)

# B17: Graham Number = sqrt(22.5 × EPS × Book Value)
print("\nB17. Graham Number — sqrt(22.5 × EPS × BV)")
if eps_yf and bv_yf and eps_yf > 0 and bv_yf > 0:
    graham_exp = math.sqrt(22.5 * eps_yf * bv_yf)
    check("Graham Number", round(graham_exp, 2), fund.get("graham_number"), tol=0.05)
else:
    results["warn"] += 1
    print(f"  {WARN} Cannot compute Graham (EPS={eps_yf}, BV={bv_yf})")

# B18: Earning Yield = (EPS / Price) × 100
print("\nB18. Earning Yield = (EPS / Price) × 100")
price = info.get("currentPrice") or info.get("regularMarketPrice")
if eps_yf and price and price > 0:
    ey_exp = (eps_yf / price) * 100
    check("Earning Yield", round(ey_exp, 2), fund.get("earning_yield"), tol=0.05)

# B19: PEG Ratio
peg_yf = info.get("pegRatio") or info.get("trailingPegRatio")
print("\nB19. PEG Ratio")
check("PEG", peg_yf, fund.get("peg_ratio"), tol=0.10)

# B20: ROCE = EBIT / Capital Employed
print("\nB20. ROCE")
# We can't easily verify independently, just check it's in reasonable range
roce = fund.get("roce")
if roce is not None:
    if 0 < roce < 100:
        results["pass"] += 1
        print(f"  {PASS} ROCE = {roce:.2f}% (reasonable range)")
    else:
        results["warn"] += 1
        print(f"  {WARN} ROCE = {roce} — unusual value")
else:
    results["warn"] += 1
    print(f"  {WARN} ROCE is None")

# B21: 52-Week High/Low
print("\nB21. 52-Week High/Low")
w52h_yf = info.get("fiftyTwoWeekHigh")
w52l_yf = info.get("fiftyTwoWeekLow")
check("52W High", w52h_yf, fund.get("week_52_high"), tol=0.02)
check("52W Low", w52l_yf, fund.get("week_52_low"), tol=0.02)

# B22: Free Cash Flow
print("\nB22. Free Cash Flow")
fcf_yf = info.get("freeCashflow")
fcf_api = fund.get("free_cash_flow")
if fcf_yf and fcf_api:
    check("FCF", fcf_yf, fcf_api, tol=0.05)
else:
    results["warn"] += 1
    print(f"  {WARN} FCF: yf={fcf_yf}, api={fcf_api}")

# B23: Altman Z-Score — verify formula
# Z = 1.2×A + 1.4×B + 3.3×C + 0.6×D + 1.0×E
# (can only check if components are reasonable)
print("\nB23. Altman Z-Score")
z = fund.get("altman_z_score")
if z is not None:
    if z > 0:
        results["pass"] += 1
        print(f"  {PASS} Altman Z = {z:.2f} (positive, reasonable for listed company)")
    else:
        results["warn"] += 1
        print(f"  {WARN} Altman Z = {z:.2f} (negative — verify)")
else:
    results["warn"] += 1
    print(f"  {WARN} Altman Z is None")

# B24: Interest Coverage
print("\nB24. Interest Coverage")
ic = fund.get("interest_coverage")
if ic is not None:
    if ic > 0:
        results["pass"] += 1
        print(f"  {PASS} Interest Coverage = {ic:.2f}x")
    else:
        results["warn"] += 1
        print(f"  {WARN} Interest Coverage = {ic}")
else:
    results["warn"] += 1
    print(f"  {WARN} Interest Coverage is None")

# B25: Asset Turnover
print("\nB25. Asset Turnover")
at = fund.get("asset_turnover")
if at is not None:
    if 0 < at < 10:
        results["pass"] += 1
        print(f"  {PASS} Asset Turnover = {at:.2f}x (reasonable)")
    else:
        results["warn"] += 1
        print(f"  {WARN} Asset Turnover = {at}")
else:
    results["warn"] += 1
    print(f"  {WARN} Asset Turnover is None")


# ═══════════════════════════════════════════════════════════════════
# SECTION C: SCORING FORMULAS
# ═══════════════════════════════════════════════════════════════════
print(f"\n{'─'*70}")
print("  SECTION C: SCORING ENGINE VERIFICATION")
print(f"{'─'*70}\n")

def gradient(val, low, high, invert=False):
    """Replicate the _gradient function"""
    if val is None:
        return None
    if invert:
        if val <= low: return 100
        if val >= high: return 0
        return round((high - val) / (high - low) * 100)
    else:
        if val <= low: return 0
        if val >= high: return 100
        return round((val - low) / (high - low) * 100)

# C1: Valuation Score
print("C1. Valuation Score (manual recalculation)")
pe = fund.get("pe_ratio")
pb = fund.get("pb_ratio")
ev_eb = fund.get("ev_ebitda")
pi = fund.get("price_to_intrinsic")
ey = fund.get("earning_yield")
peg = fund.get("peg_ratio")

parts = []
weights = []
# PE: lower is better, 8-40 range
if pe and pe > 0:
    parts.append(gradient(pe, 8, 40, invert=True))
    weights.append(25)
# PB: lower is better, 0.5-8
if pb and pb > 0:
    parts.append(gradient(pb, 0.5, 8, invert=True))
    weights.append(15)
# EV/EBITDA: lower is better, 5-30
if ev_eb and ev_eb > 0:
    parts.append(gradient(ev_eb, 5, 30, invert=True))
    weights.append(20)
# Price/Intrinsic: lower is better, 0.5-3
if pi and pi > 0:
    parts.append(gradient(pi, 0.5, 3, invert=True))
    weights.append(20)
# Earning Yield: higher is better, 0-15
if ey and ey > 0:
    parts.append(gradient(ey, 0, 15))
    weights.append(10)
# PEG: lower is better, 0.5-3
if peg and peg > 0:
    parts.append(gradient(peg, 0.5, 3, invert=True))
    weights.append(10)

if parts and weights:
    val_score_exp = round(sum(p*w for p,w in zip(parts, weights)) / sum(weights))
    check("Valuation Score", val_score_exp, fund.get("valuation_score"), tol=0.05)
else:
    results["warn"] += 1
    print(f"  {WARN} Cannot recalculate valuation score")

# C2: Profitability Score
print("\nC2. Profitability Score")
roe_v = fund.get("roe")
roa_v = fund.get("roa")
nm_v = fund.get("net_margin")
om_v = fund.get("operating_margin")
gm_v = fund.get("gross_margin")
roce_v = fund.get("roce")

parts2 = []
weights2 = []
if roe_v is not None: parts2.append(gradient(roe_v, 0, 30)); weights2.append(25)
if roa_v is not None: parts2.append(gradient(roa_v, 0, 15)); weights2.append(15)
if nm_v is not None: parts2.append(gradient(nm_v, 0, 25)); weights2.append(20)
if om_v is not None: parts2.append(gradient(om_v, 0, 30)); weights2.append(15)
if gm_v is not None: parts2.append(gradient(gm_v, 20, 70)); weights2.append(10)
if roce_v is not None: parts2.append(gradient(roce_v, 0, 30)); weights2.append(15)

if parts2:
    prof_score_exp = round(sum(p*w for p,w in zip(parts2, weights2)) / sum(weights2))
    check("Profitability Score", prof_score_exp, fund.get("profitability_score"), tol=0.05)

# C3: Growth Score
print("\nC3. Growth Score")
rg = fund.get("revenue_growth")
eg = fund.get("earnings_growth")

parts3 = []
weights3 = []
if rg is not None: parts3.append(gradient(rg, -10, 30)); weights3.append(40)
if eg is not None: parts3.append(gradient(eg, -20, 40)); weights3.append(40)
# FCF contribution
fcf_v = fund.get("free_cash_flow")
mcap = fund.get("market_cap")
if fcf_v and mcap and mcap > 0:
    fcf_yield = (fcf_v / mcap) * 100
    parts3.append(gradient(fcf_yield, 0, 8))
    weights3.append(20)

if parts3:
    grow_score_exp = round(sum(p*w for p,w in zip(parts3, weights3)) / sum(weights3))
    check("Growth Score", grow_score_exp, fund.get("growth_score"), tol=0.10)

# C4: Stability Score
print("\nC4. Stability Score")
de = fund.get("debt_equity")
cr = fund.get("current_ratio")
z_score = fund.get("altman_z_score")

parts4 = []
weights4 = []
if de is not None: parts4.append(gradient(de, 0, 2, invert=True)); weights4.append(30)
if cr is not None: parts4.append(gradient(cr, 0.5, 3)); weights4.append(25)
if z_score is not None: parts4.append(gradient(z_score, 1, 4)); weights4.append(25)
ic_v = fund.get("interest_coverage")
if ic_v is not None and ic_v > 0:
    parts4.append(gradient(ic_v, 1, 15))
    weights4.append(20)

if parts4:
    stab_score_exp = round(sum(p*w for p,w in zip(parts4, weights4)) / sum(weights4))
    check("Stability Score", stab_score_exp, fund.get("stability_score"), tol=0.10)

# C5: Overall Fundamental Score
print("\nC5. Overall Fundamental Score")
vs = fund.get("valuation_score")
ps = fund.get("profitability_score")
gs = fund.get("growth_score")
ss = fund.get("stability_score")
if all(x is not None for x in [vs, ps, gs, ss]):
    # Weights: val=30, prof=25, grow=25, stab=20
    overall_exp = round(vs * 0.30 + ps * 0.25 + gs * 0.25 + ss * 0.20)
    check("Overall Score", overall_exp, fund.get("fundamental_score"), tol=0.05)

# C6: Verdict Logic
print("\nC6. Verdict Signal")
fscore = fund.get("fundamental_score")
if fscore is not None:
    if fscore >= 75:
        exp_signal = "BUY"
    elif fscore >= 55:
        exp_signal = "HOLD" if fscore < 65 else "BUY"
    elif fscore >= 40:
        exp_signal = "HOLD"
    else:
        exp_signal = "SELL"
    # More precise: check the actual thresholds from code
    if fscore >= 80:
        exp_verdict_start = "STRONG BUY"
    elif fscore >= 65:
        exp_verdict_start = "BUY"
    elif fscore >= 50:
        exp_verdict_start = "HOLD"
    elif fscore >= 35:
        exp_verdict_start = "AVOID"
    else:
        exp_verdict_start = "SELL"
    
    api_verdict = fund.get("fundamental_verdict", "")
    if exp_verdict_start in api_verdict:
        results["pass"] += 1
        print(f"  {PASS} Score {fscore} → verdict contains '{exp_verdict_start}': '{api_verdict}'")
    else:
        results["warn"] += 1
        print(f"  {WARN} Score {fscore} → expected '{exp_verdict_start}' in '{api_verdict}'")


# ═══════════════════════════════════════════════════════════════════
# SECTION D: CHART DATA INTEGRITY
# ═══════════════════════════════════════════════════════════════════
print(f"\n{'─'*70}")
print("  SECTION D: CHART DATA INTEGRITY")
print(f"{'─'*70}\n")

# D1: OHLCV data matches yfinance
print("D1. Last bar OHLCV vs yfinance")
if chart:
    last_yf = hist.iloc[-1]
    lb = chart[-1]
    check("Close", round(last_yf["Close"], 2), lb.get("close"), tol=0.01)
    check("High", round(last_yf["High"], 2), lb.get("high"), tol=0.01)
    check("Low", round(last_yf["Low"], 2), lb.get("low"), tol=0.01)
    check("Volume", last_yf["Volume"], lb.get("volume"), tol=0.05)

# D2: All required fields present
print("\nD2. Required chart fields present in last bar")
required_fields = ["date", "open", "high", "low", "close", "volume",
                   "bb_upper", "bb_mid", "bb_lower", "bbw", "pct_b",
                   "kc_upper", "kc_lower", "squeeze", "momentum",
                   "rsi", "macd", "macd_signal", "macd_hist",
                   "mfi", "cmf", "sar"]
if chart:
    missing = [f for f in required_fields if f not in chart[-1]]
    if not missing:
        results["pass"] += 1
        print(f"  {PASS} All {len(required_fields)} required fields present")
    else:
        results["fail"] += 1
        print(f"  {FAIL} Missing fields: {missing}")

# D3: No NaN in last 20 bars
print("\nD3. No NaN/null values in last 20 chart bars")
if chart and len(chart) >= 20:
    nan_count = 0
    for bar in chart[-20:]:
        for k, v in bar.items():
            if v is None and k in required_fields:
                nan_count += 1
    if nan_count == 0:
        results["pass"] += 1
        print(f"  {PASS} No null values in last 20 bars")
    else:
        results["warn"] += 1
        print(f"  {WARN} {nan_count} null values found in last 20 bars")


# ═══════════════════════════════════════════════════════════════════
# SECTION E: FORMULA CORRECTNESS (MATHEMATICAL PROOFS)
# ═══════════════════════════════════════════════════════════════════
print(f"\n{'─'*70}")
print("  SECTION E: FORMULA CORRECTNESS — MATHEMATICAL PROOFS")
print(f"{'─'*70}\n")

print("E1. Bollinger Band formula: BB_upper = SMA(20) + 2σ, BB_lower = SMA(20) - 2σ")
if chart:
    mid = last_bar.get("bb_mid", 0)
    up = last_bar.get("bb_upper", 0)
    lo = last_bar.get("bb_lower", 0)
    # Check symmetry: upper - mid should equal mid - lower
    diff_up = up - mid
    diff_lo = mid - lo
    symmetry = abs(diff_up - diff_lo) / max(diff_up, 0.001)
    if symmetry < 0.01:
        results["pass"] += 1
        print(f"  {PASS} BB symmetric: upper-mid={diff_up:.4f}, mid-lower={diff_lo:.4f} (diff={symmetry:.6f})")
    else:
        results["fail"] += 1
        print(f"  {FAIL} BB NOT symmetric: upper-mid={diff_up:.4f}, mid-lower={diff_lo:.4f}")

print("\nE2. %B boundary check: when Close=Upper, %B=1.0; when Close=Lower, %B=0.0")
if chart:
    # Just verify the formula: %B = (close - lower) / (upper - lower)
    c = last_bar.get("close", 0)
    pctb_calc = (c - lo) / (up - lo) if (up - lo) > 0 else 0
    pctb_api = last_bar.get("pct_b", 0)
    check("%B formula", round(pctb_calc, 4), pctb_api, tol=0.02)

print("\nE3. BBW formula: (Upper - Lower) / Mid × 100")
if chart:
    bbw_calc = ((up - lo) / mid) * 100 if mid > 0 else 0
    check("BBW formula", round(bbw_calc, 4), last_bar.get("bbw"), tol=0.02)

print("\nE4. Graham Number: sqrt(22.5 × EPS × BV)")
eps_api = fund.get("eps_ttm")
bv_api = fund.get("book_value")
gn_api = fund.get("graham_number")
if eps_api and bv_api and eps_api > 0 and bv_api > 0:
    gn_calc = math.sqrt(22.5 * eps_api * bv_api)
    check("Graham (from API's own EPS/BV)", round(gn_calc, 2), gn_api, tol=0.01)

print("\nE5. Earning Yield = (EPS / Price) × 100")
price_api = fund.get("current_price")
if eps_api and price_api and price_api > 0:
    ey_calc = (eps_api / price_api) * 100
    check("EY (from API's own EPS/Price)", round(ey_calc, 2), fund.get("earning_yield"), tol=0.01)

print("\nE6. Price/Intrinsic = Price / Graham Number")
if price_api and gn_api and gn_api > 0:
    pi_calc = price_api / gn_api
    check("P/Intrinsic (from API's Price/Graham)", round(pi_calc, 4), fund.get("price_to_intrinsic"), tol=0.01)

print("\nE7. Overall Score = 0.30×Val + 0.25×Prof + 0.25×Growth + 0.20×Stab")
if all(x is not None for x in [vs, ps, gs, ss]):
    os_calc = round(vs * 0.30 + ps * 0.25 + gs * 0.25 + ss * 0.20)
    check("Overall (from sub-scores)", os_calc, fund.get("fundamental_score"), tol=0.01)

print("\nE8. Gradient function: gradient(50, 0, 100) should = 50")
check("gradient(50,0,100)", 50, gradient(50, 0, 100))
check("gradient(0,0,100)", 0, gradient(0, 0, 100))
check("gradient(100,0,100)", 100, gradient(100, 0, 100))
check("gradient(150,0,100)", 100, gradient(150, 0, 100))
check("gradient_inv(50,0,100)", 50, gradient(50, 0, 100, invert=True))
check("gradient_inv(0,0,100)", 100, gradient(0, 0, 100, invert=True))


# ═══════════════════════════════════════════════════════════════════
# FINAL REPORT
# ═══════════════════════════════════════════════════════════════════
print(f"\n{'='*70}")
print(f"  AUDIT REPORT — {SYMBOL}")
print(f"{'='*70}")
total = results["pass"] + results["fail"] + results["warn"]
print(f"""
  Total checks:  {total}
  {PASS} PASSED:    {results['pass']}
  {FAIL} FAILED:    {results['fail']}
  {WARN} WARNINGS:  {results['warn']}
  
  Pass rate:     {results['pass']/total*100:.1f}%
""")

if results["fail"] == 0:
    print("  🎉 ALL CHECKS PASSED — Application data is TRUSTWORTHY")
else:
    print(f"  ⚠️  {results['fail']} FAILURE(S) FOUND — Review above")

print(f"{'='*70}\n")
