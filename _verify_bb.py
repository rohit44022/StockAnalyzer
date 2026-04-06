"""
Comprehensive Bollinger Band Squeeze Strategy ACCURACY VERIFICATION
Cross-checks every indicator against independent manual calculations
and the `ta` library (Technical Analysis Library in Python).
"""
import pandas as pd
import numpy as np
import yfinance as yf
import sys, warnings
warnings.filterwarnings("ignore")

TICKER = "TCS.NS"
print(f"\n{'='*80}")
print(f"  BOLLINGER SQUEEZE ACCURACY AUDIT — {TICKER}")
print(f"{'='*80}\n")

# ── Step 1: Get raw price data ──────────────────────────────────
tk = yf.Ticker(TICKER)
raw = tk.history(period="2y", auto_adjust=True)
if raw is None or len(raw) < 200:
    print("ERROR: Not enough data"); sys.exit(1)
print(f"  Data points: {len(raw)} rows  ({raw.index[0].date()} → {raw.index[-1].date()})\n")

close  = raw["Close"].astype(float)
high   = raw["High"].astype(float)
low    = raw["Low"].astype(float)
volume = raw["Volume"].astype(float)

# ── Step 2: Import OUR implementation ────────────────────────────
from bb_squeeze.indicators import (
    bollinger_bands, bandwidth, percent_b, is_squeeze,
    parabolic_sar, volume_sma, chaikin_money_flow, money_flow_index,
    compute_all_indicators,
)
from bb_squeeze.config import BB_PERIOD, BB_STD_DEV, BBW_LOOKBACK, BBW_TRIGGER, CMF_PERIOD, MFI_PERIOD

# ── Step 3: Compute OUR indicators ──────────────────────────────
our_mid, our_upper, our_lower = bollinger_bands(close)
our_bbw    = bandwidth(our_mid, our_upper, our_lower)
our_pctb   = percent_b(close, our_upper, our_lower)
our_cmf    = chaikin_money_flow(high, low, close, volume)
our_mfi    = money_flow_index(high, low, close, volume)
our_sar, our_sar_bull = parabolic_sar(high, low)
our_vol_sma = volume_sma(volume)
our_squeeze = is_squeeze(our_bbw)

bugs_found = 0

def check(name, ours, expected, tol=0.01, is_pct=False):
    """Compare two values within tolerance."""
    global bugs_found
    if ours is None or expected is None or np.isnan(ours) or np.isnan(expected):
        print(f"  ⚠  {name:30s}  Ours={ours}  Expected={expected}  (cannot compare)")
        return
    diff = abs(ours - expected)
    reldiff = diff / abs(expected) if expected != 0 else diff
    ok = reldiff < tol
    icon = "✅" if ok else "❌ BUG"
    sfx = "%" if is_pct else ""
    print(f"  {icon}  {name:30s}  Ours={ours:.6f}{sfx}   Expected={expected:.6f}{sfx}   Diff={diff:.8f}  ({reldiff*100:.4f}%)")
    if not ok:
        bugs_found += 1


# ═════════════════════════════════════════════════════════════════
#  TEST 1: BOLLINGER BANDS — Manual calculation
# ═════════════════════════════════════════════════════════════════
print("─" * 80)
print("  TEST 1: BOLLINGER BANDS (SMA-20, 2σ)")
print("─" * 80)

# Manual reference
manual_mid = close.rolling(window=20).mean()
manual_std = close.rolling(window=20).std(ddof=1)  # ddof=1 = sample std
manual_upper = manual_mid + 2.0 * manual_std
manual_lower = manual_mid - 2.0 * manual_std

idx = -1  # latest
check("BB Middle (SMA-20)",   our_mid.iloc[idx],   manual_mid.iloc[idx])
check("BB Upper  (SMA+2σ)",   our_upper.iloc[idx], manual_upper.iloc[idx])
check("BB Lower  (SMA-2σ)",   our_lower.iloc[idx], manual_lower.iloc[idx])

# Check ddof — THIS IS CRITICAL
# John Bollinger uses population std (ddof=0) per his book, but many
# implementations use sample std (ddof=1). Let's check both.
manual_std_pop = close.rolling(window=20).std(ddof=0)
manual_upper_pop = manual_mid + 2.0 * manual_std_pop
manual_lower_pop = manual_mid - 2.0 * manual_std_pop

diff_ddof1 = abs(our_upper.iloc[idx] - manual_upper.iloc[idx])
diff_ddof0 = abs(our_upper.iloc[idx] - manual_upper_pop.iloc[idx])

print(f"\n  📊 ddof check:")
print(f"     Our Upper Band       : {our_upper.iloc[idx]:.4f}")
print(f"     Manual ddof=1 (sample): {manual_upper.iloc[idx]:.4f}  diff={diff_ddof1:.6f}")
print(f"     Manual ddof=0 (popul.): {manual_upper_pop.iloc[idx]:.4f}  diff={diff_ddof0:.6f}")
if diff_ddof1 < diff_ddof0:
    print(f"     → Code uses ddof=1 (SAMPLE std dev)")
    print(f"     ⚠  NOTE: John Bollinger's original uses POPULATION std (ddof=0)")
    print(f"     ⚠  Most platforms (TradingView, Zerodha) use ddof=0. This matters!")
    band_width_our    = our_upper.iloc[idx] - our_lower.iloc[idx]
    band_width_pop    = manual_upper_pop.iloc[idx] - manual_lower_pop.iloc[idx]
    print(f"     Band width ours (ddof=1): {band_width_our:.4f}")
    print(f"     Band width correct (ddof=0): {band_width_pop:.4f}")
    print(f"     Difference in band width: {abs(band_width_our - band_width_pop):.4f} ({abs(band_width_our - band_width_pop)/band_width_pop*100:.2f}%)")
else:
    print(f"     → Code uses ddof=0 (POPULATION std dev) ✅ Matches Bollinger standard")

print()

# ═════════════════════════════════════════════════════════════════
#  TEST 2: BANDWIDTH (BBW)
# ═════════════════════════════════════════════════════════════════
print("─" * 80)
print("  TEST 2: BANDWIDTH = (Upper - Lower) / Middle")
print("─" * 80)

manual_bbw = (our_upper - our_lower) / our_mid
check("BBW (latest)",     our_bbw.iloc[idx], manual_bbw.iloc[idx])

# Check if BBW matches what TradingView would show (with ddof=0)
tv_bbw = (manual_upper_pop - manual_lower_pop) / manual_mid
print(f"\n  BBW ours (ddof=1):       {our_bbw.iloc[idx]:.6f}")
print(f"  BBW TradingView (ddof=0): {tv_bbw.iloc[idx]:.6f}")
print(f"  Impact on squeeze: BBW trigger = {BBW_TRIGGER}")
print(f"  Our BBW says squeeze = {our_bbw.iloc[idx] <= BBW_TRIGGER}")
print(f"  TV  BBW says squeeze = {tv_bbw.iloc[idx] <= BBW_TRIGGER}")
if (our_bbw.iloc[idx] <= BBW_TRIGGER) != (tv_bbw.iloc[idx] <= BBW_TRIGGER):
    print(f"  ❌ BUG: ddof difference causes DIFFERENT squeeze detection!")
    bugs_found += 1
print()

# ═════════════════════════════════════════════════════════════════
#  TEST 3: %b (Percent B)
# ═════════════════════════════════════════════════════════════════
print("─" * 80)
print("  TEST 3: %b = (Close - Lower) / (Upper - Lower)")
print("─" * 80)

manual_pctb = (close - our_lower) / (our_upper - our_lower)
check("Percent B (latest)",  our_pctb.iloc[idx], manual_pctb.iloc[idx])
print()

# ═════════════════════════════════════════════════════════════════
#  TEST 4: CMF (Chaikin Money Flow)
# ═════════════════════════════════════════════════════════════════
print("─" * 80)
print("  TEST 4: CMF = Σ(MFV, 20) / Σ(Vol, 20)")
print("─" * 80)

# Manual CMF
hl_range = (high - low).replace(0, np.nan)
manual_mfm = ((close - low) - (high - close)) / hl_range
manual_mfv = manual_mfm * volume
manual_cmf = manual_mfv.rolling(20).sum() / volume.rolling(20).sum()

check("CMF (latest)",  our_cmf.iloc[idx], manual_cmf.iloc[idx])

# Cross-check with ta library if available
try:
    from ta.volume import ChaikinMoneyFlowIndicator
    ta_cmf = ChaikinMoneyFlowIndicator(high, low, close, volume, window=20).chaikin_money_flow()
    check("CMF vs ta library", our_cmf.iloc[idx], ta_cmf.iloc[idx])
except ImportError:
    print("  ℹ  `ta` library not installed — skipping cross-check")
print()

# ═════════════════════════════════════════════════════════════════
#  TEST 5: MFI (Money Flow Index)
# ═════════════════════════════════════════════════════════════════
print("─" * 80)
print("  TEST 5: MFI (Money Flow Index, period=10)")
print("─" * 80)

# Manual MFI
tp = (high + low + close) / 3.0
raw_mf = tp * volume
pos_mf = raw_mf.where(tp > tp.shift(1), 0.0)
neg_mf = raw_mf.where(tp < tp.shift(1), 0.0)
pos_sum = pos_mf.rolling(10).sum()
neg_sum = neg_mf.rolling(10).sum()
neg_sum_safe = neg_sum.replace(0, np.nan)
manual_mfr = pos_sum / neg_sum_safe
manual_mfi = 100 - (100 / (1 + manual_mfr))

check("MFI (latest)",  our_mfi.iloc[idx], manual_mfi.iloc[idx])

# Cross-check with ta library
try:
    from ta.volume import MFIIndicator
    ta_mfi = MFIIndicator(high, low, close, volume, window=10).money_flow_index()
    check("MFI vs ta library", our_mfi.iloc[idx], ta_mfi.iloc[idx])
except ImportError:
    print("  ℹ  `ta` library not installed — skipping cross-check")
print()

# ═════════════════════════════════════════════════════════════════
#  TEST 6: PARABOLIC SAR
# ═════════════════════════════════════════════════════════════════
print("─" * 80)
print("  TEST 6: PARABOLIC SAR (AF=0.02, max=0.20)")
print("─" * 80)

# Check latest value
print(f"  Our SAR value:     {our_sar.iloc[idx]:.4f}")
print(f"  Our SAR direction: {'BULL (dots below)' if our_sar_bull.iloc[idx] else 'BEAR (dots above)'}")
print(f"  Current Price:     {close.iloc[idx]:.4f}")

# Basic sanity: in bull mode, SAR should be below price
if our_sar_bull.iloc[idx]:
    if our_sar.iloc[idx] >= close.iloc[idx]:
        print(f"  ❌ BUG: SAR is BULL mode but SAR ({our_sar.iloc[idx]:.2f}) >= Price ({close.iloc[idx]:.2f})")
        bugs_found += 1
    else:
        print(f"  ✅ SAR < Price in bull mode — correct")
else:
    if our_sar.iloc[idx] <= close.iloc[idx]:
        print(f"  ❌ BUG: SAR is BEAR mode but SAR ({our_sar.iloc[idx]:.2f}) <= Price ({close.iloc[idx]:.2f})")
        bugs_found += 1
    else:
        print(f"  ✅ SAR > Price in bear mode — correct")

# Cross-check with ta library
try:
    from ta.trend import PSARIndicator
    psar = PSARIndicator(high, low, close, step=0.02, max_step=0.20)
    ta_sar_up   = psar.psar_up()   # SAR when bullish (below candles)
    ta_sar_down = psar.psar_down() # SAR when bearish (above candles)
    # ta library returns NaN for the inactive direction
    ta_sar_latest = ta_sar_up.iloc[idx] if not np.isnan(ta_sar_up.iloc[idx]) else ta_sar_down.iloc[idx]
    check("SAR vs ta library", our_sar.iloc[idx], ta_sar_latest, tol=0.02)  # 2% tolerance for SAR
except ImportError:
    print("  ℹ  `ta` library not installed — skipping cross-check")
print()

# ═════════════════════════════════════════════════════════════════
#  TEST 7: VOLUME SMA
# ═════════════════════════════════════════════════════════════════
print("─" * 80)
print("  TEST 7: VOLUME 50-SMA")
print("─" * 80)

manual_vol_sma = volume.rolling(50).mean()
check("Volume SMA-50", our_vol_sma.iloc[idx], manual_vol_sma.iloc[idx])
print()

# ═════════════════════════════════════════════════════════════════
#  TEST 8: SQUEEZE DETECTION LOGIC
# ═════════════════════════════════════════════════════════════════
print("─" * 80)
print("  TEST 8: SQUEEZE DETECTION")
print("─" * 80)

rolling_min = our_bbw.rolling(window=BBW_LOOKBACK, min_periods=60).min()
dynamic_test = our_bbw.iloc[idx] <= (rolling_min.iloc[idx] * 1.05)
absolute_test = our_bbw.iloc[idx] <= BBW_TRIGGER

print(f"  Current BBW:            {our_bbw.iloc[idx]:.6f}")
print(f"  6M Rolling Min BBW:     {rolling_min.iloc[idx]:.6f}")
print(f"  Dynamic threshold (×1.05): {rolling_min.iloc[idx] * 1.05:.6f}")
print(f"  Absolute trigger:       {BBW_TRIGGER}")
print(f"  Dynamic squeeze?        {dynamic_test}")
print(f"  Absolute squeeze?       {absolute_test}")
print(f"  Our squeeze result:     {our_squeeze.iloc[idx]}")
manual_squeeze = dynamic_test or absolute_test
if our_squeeze.iloc[idx] == manual_squeeze:
    print(f"  ✅ Squeeze detection matches manual calculation")
else:
    print(f"  ❌ BUG: Squeeze detection MISMATCH!")
    bugs_found += 1
print()

# ═════════════════════════════════════════════════════════════════
#  TEST 9: SIGNAL ENGINE — compute_all_indicators pipeline
# ═════════════════════════════════════════════════════════════════
print("─" * 80)
print("  TEST 9: FULL PIPELINE — compute_all_indicators()")
print("─" * 80)

df = raw.copy()
df = compute_all_indicators(df)

# Check that the pipeline results match the individual calculations
check("Pipeline BB_Mid",     df["BB_Mid"].iloc[idx],     our_mid.iloc[idx])
check("Pipeline BB_Upper",   df["BB_Upper"].iloc[idx],   our_upper.iloc[idx])
check("Pipeline BB_Lower",   df["BB_Lower"].iloc[idx],   our_lower.iloc[idx])
check("Pipeline BBW",        df["BBW"].iloc[idx],        our_bbw.iloc[idx])
check("Pipeline Percent_B",  df["Percent_B"].iloc[idx],  our_pctb.iloc[idx])
check("Pipeline CMF",        df["CMF"].iloc[idx],        our_cmf.iloc[idx])
check("Pipeline MFI",        df["MFI"].iloc[idx],        our_mfi.iloc[idx])
check("Pipeline SAR",        df["SAR"].iloc[idx],        our_sar.iloc[idx])
check("Pipeline Vol_SMA50",  df["Vol_SMA50"].iloc[idx],  our_vol_sma.iloc[idx])
print()

# ═════════════════════════════════════════════════════════════════
#  TEST 10: SIGNAL CONDITIONS CHECK
# ═════════════════════════════════════════════════════════════════
print("─" * 80)
print("  TEST 10: SIGNAL CONDITIONS — analyze_signals()")
print("─" * 80)

from bb_squeeze.signals import analyze_signals
sig = analyze_signals(TICKER, df)

print(f"  Price:            ₹{sig.current_price:.2f}")
print(f"  BB Upper:         ₹{sig.bb_upper:.2f}")
print(f"  BB Mid:           ₹{sig.bb_mid:.2f}")
print(f"  BB Lower:         ₹{sig.bb_lower:.2f}")
print(f"  BBW:              {sig.bbw:.6f}")
print(f"  %b:               {sig.percent_b:.4f}")
print(f"  SAR:              ₹{sig.sar:.2f}  ({'Bull' if sig.sar_bull else 'Bear'})")
print(f"  CMF:              {sig.cmf:+.4f}")
print(f"  MFI:              {sig.mfi:.2f}")
print(f"  Volume:           {int(sig.volume):,}")
print(f"  Vol SMA50:        {int(sig.vol_sma50):,}")
print()
print(f"  Cond1 Squeeze:    {sig.cond1_squeeze_on}")
print(f"  Cond2 Price>UBB:  {sig.cond2_price_above}")
print(f"  Cond3 Vol OK:     {sig.cond3_volume_ok}")
print(f"  Cond4 CMF>0:      {sig.cond4_cmf_positive}")
print(f"  Cond5 MFI>50:     {sig.cond5_mfi_above_50}")
print(f"  Buy Signal:       {sig.buy_signal}")
print(f"  Sell Signal:      {sig.sell_signal}")
print(f"  Head Fake:        {sig.head_fake}")
print(f"  Confidence:       {sig.confidence}/100")
print(f"  Phase:            {sig.phase}")
print(f"  Direction Lean:   {sig.direction_lean}")
print(f"  Squeeze Days:     {sig.squeeze_days}")

# Verify condition logic
manual_cond2 = sig.current_price > sig.bb_upper
if sig.cond2_price_above != manual_cond2:
    print(f"  ❌ BUG: Cond2 mismatch! Price={sig.current_price} Upper={sig.bb_upper}")
    bugs_found += 1

manual_cond4 = sig.cmf > 0
if sig.cond4_cmf_positive != manual_cond4:
    print(f"  ❌ BUG: Cond4 mismatch! CMF={sig.cmf}")
    bugs_found += 1

print()

# ═════════════════════════════════════════════════════════════════
#  TEST 11: HISTORICAL SQUEEZE EVENTS — Sanity check
# ═════════════════════════════════════════════════════════════════
print("─" * 80)
print("  TEST 11: HISTORICAL SQUEEZE EVENTS CHECK")
print("─" * 80)

squeeze_periods = df[df["Squeeze_ON"] == True]
total_days = len(df)
squeeze_days = len(squeeze_periods)
print(f"  Total trading days:  {total_days}")
print(f"  Days in squeeze:     {squeeze_days} ({squeeze_days/total_days*100:.1f}%)")

# Squeezes should NOT be constantly on — that would be a bug
if squeeze_days / total_days > 0.70:
    print(f"  ❌ BUG: Squeeze ON > 70% of the time — trigger too loose!")
    bugs_found += 1
elif squeeze_days / total_days < 0.01:
    print(f"  ⚠  Squeeze ON < 1% of the time — trigger may be too tight")
else:
    print(f"  ✅ Squeeze frequency looks reasonable")

# Count distinct squeeze episodes
squeeze_bool = df["Squeeze_ON"].astype(bool)
starts = squeeze_bool & ~squeeze_bool.shift(1, fill_value=False)
num_episodes = starts.sum()
print(f"  Distinct squeeze episodes: {num_episodes}")

# Check that BBW is actually low during detected squeezes
avg_bbw_squeeze = df.loc[df["Squeeze_ON"] == True, "BBW"].mean()
avg_bbw_normal  = df.loc[df["Squeeze_ON"] == False, "BBW"].mean()
print(f"  Avg BBW during squeeze:  {avg_bbw_squeeze:.6f}")
print(f"  Avg BBW during normal:   {avg_bbw_normal:.6f}")
if avg_bbw_squeeze >= avg_bbw_normal:
    print(f"  ❌ BUG: BBW during squeeze is NOT lower than normal — logic error!")
    bugs_found += 1
else:
    print(f"  ✅ BBW is lower during detected squeeze periods — correct")

print()

# ═════════════════════════════════════════════════════════════════
#  TEST 12: TradingView CROSS-CHECK (ddof=0 standard)
# ═════════════════════════════════════════════════════════════════
print("─" * 80)
print("  TEST 12: TradingView STANDARD (ddof=0 population std)")
print("─" * 80)
print(f"  NOTE: TradingView, Zerodha Kite, Screener, and most platforms")
print(f"  use POPULATION std dev (ddof=0) for Bollinger Bands.")
print(f"  John Bollinger himself has not explicitly specified, but the")
print(f"  industry standard is ddof=0.\n")

latest_close = close.iloc[idx]
print(f"  Latest Close:             ₹{latest_close:.2f}")
print(f"  Our BB Upper (ddof=1):    ₹{our_upper.iloc[idx]:.2f}")
print(f"  TV  BB Upper (ddof=0):    ₹{manual_upper_pop.iloc[idx]:.2f}")
print(f"  Our BB Lower (ddof=1):    ₹{our_lower.iloc[idx]:.2f}")
print(f"  TV  BB Lower (ddof=0):    ₹{manual_lower_pop.iloc[idx]:.2f}")
diff_upper = abs(our_upper.iloc[idx] - manual_upper_pop.iloc[idx])
diff_lower = abs(our_lower.iloc[idx] - manual_lower_pop.iloc[idx])
print(f"  Difference Upper:         ₹{diff_upper:.2f}")
print(f"  Difference Lower:         ₹{diff_lower:.2f}")
print(f"  This can cause false/missed breakout signals near band edges!")
print()

# ═════════════════════════════════════════════════════════════════
#  FINAL REPORT
# ═════════════════════════════════════════════════════════════════
print("=" * 80)
if bugs_found == 0:
    print(f"  ✅  ALL TESTS PASSED — NO BUGS FOUND")
    print(f"  ⚠  HOWEVER: ddof=1 vs ddof=0 difference may cause mismatches")
    print(f"     with TradingView/Zerodha. Recommend switching to ddof=0.")
else:
    print(f"  ❌  {bugs_found} BUG(S) FOUND — SEE DETAILS ABOVE")
print("=" * 80)
