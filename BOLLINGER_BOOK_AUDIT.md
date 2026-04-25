# Bollinger on Bollinger Bands — System Audit Report

> Audit of the codebase against every concept, formula, strategy, and rule
> in *Bollinger on Bollinger Bands* (John Bollinger, 2002).
>
> **Scope:** `bb_squeeze/`, `technical_analysis/`, `bollinger_squeeze_strategy.py`
>
> **Verdict key:** ✅ = Correctly implemented | ⚠️ = Partially implemented / deviation | ❌ = Missing entirely

---

## Table of Contents

1. [Core Bollinger Band Construction](#1-core-bollinger-band-construction)
2. [Derived Indicators (%b, BandWidth)](#2-derived-indicators-b-bandwidth)
3. [The 15 Basic Rules — Compliance Check](#3-the-15-basic-rules--compliance-check)
4. [Volume Indicators from the Book](#4-volume-indicators-from-the-book)
5. [Method I — Volatility Breakout (The Squeeze)](#5-method-i--volatility-breakout-the-squeeze)
6. [Method II — Trend Following](#6-method-ii--trend-following)
7. [Method III — Reversals (W-Bottoms / M-Tops)](#7-method-iii--reversals-w-bottoms--m-tops)
8. [Walking the Bands](#8-walking-the-bands)
9. [Head Fake Detection](#9-head-fake-detection)
10. [Normalizing Indicators with Bollinger Bands](#10-normalizing-indicators-with-bollinger-bands)
11. [Pattern Recognition — Five-Point Patterns](#11-pattern-recognition--five-point-patterns)
12. [Multicollinearity / Indicator Selection](#12-multicollinearity--indicator-selection)
13. [Width–Length Relationship](#13-widthlength-relationship)
14. [The Expansion (Reverse Squeeze)](#14-the-expansion-reverse-squeeze)
15. [Day Trading Adaptations](#15-day-trading-adaptations)
16. [Parameter Configuration Audit](#16-parameter-configuration-audit)
17. [Summary Matrix](#17-summary-matrix)
18. [Recommendations (Priority Order)](#18-recommendations-priority-order)

---

## 1. Core Bollinger Band Construction

### Book Reference (Ch. 7, pp. 50–59)

| Requirement | Book Value | Your Code | File | Verdict |
|-------------|-----------|-----------|------|---------|
| Moving average type | **SMA** (Rule 12) | `close.rolling(window=period).mean()` | `bb_squeeze/indicators.py:34` | ✅ |
| Standard deviation | **Population** (ddof=0) | `close.rolling(window=period).std(ddof=0)` | `bb_squeeze/indicators.py:35` | ✅ |
| Default period | **20** | `BB_PERIOD = 20` | `bb_squeeze/config.py:22` | ✅ |
| Default width | **2 std dev** | `BB_STD_DEV = 2.0` | `bb_squeeze/config.py:23` | ✅ |
| Containment note | ~89% for stocks, not 95.4% | Documented in config comment | `bb_squeeze/config.py:23` | ✅ |
| Typical price option | `(H+L+C)/3` alternative | **Not implemented** | — | ⚠️ Not critical but book suggests it |

**Assessment:** Core construction is **correct and faithful to the book**.

---

## 2. Derived Indicators (%b, BandWidth)

### Book Reference (Ch. 8, pp. 60–67)

| Requirement | Book Formula | Your Code | File | Verdict |
|-------------|-------------|-----------|------|---------|
| %b formula | `(close − lower) / (upper − lower)` | Exact match | `bb_squeeze/indicators.py:50-58` | ✅ |
| %b values | 1.0 at upper, 0.5 at mid, 0.0 at lower | Correct, with div-by-zero guard | `indicators.py:57` | ✅ |
| BandWidth formula | `(upper − lower) / middle` | Exact match | `bb_squeeze/indicators.py:47` | ✅ |
| Squeeze detection | BBW at 6-month low | Rolling 126-day min + 0.08 trigger | `bb_squeeze/indicators.py:61-71` | ✅ |
| BBW lookback | ~6 months (126 trading days) | `BBW_LOOKBACK = 126` | `bb_squeeze/config.py:32` | ✅ |

**Assessment:** %b and BandWidth are **perfectly implemented**.

---

## 3. The 15 Basic Rules — Compliance Check

| # | Rule (Paraphrased) | Implementation Status | Notes |
|---|--------------------|-----------------------|-------|
| 1 | Relative definition of high/low | ✅ | Core of the %b / band structure |
| 2 | Compare price & indicator for decisions | ✅ | Methods I–IV all do this |
| 3 | Use indicators from momentum, volume, sentiment, etc. | ⚠️ | MFI and CMF used; missing II, AD, VWMACD from book |
| 4 | Don't use volatility/trend indicators to confirm BB | ✅ | System avoids using BBW to confirm BB signals |
| 5 | Avoid collinearity — one indicator per category | ⚠️ | CMF and MFI are both volume indicators — **same category** |
| 6 | BB clarifies M/W patterns | ✅ | Method III detects W-Bottoms and M-Tops |
| 7 | Price can walk the bands | ✅ | Method IV explicitly implements walking |
| 8 | Closes outside bands = continuation, not reversal | ✅ | Walking logic treats tags as confirmation |
| 9 | Defaults are just defaults; adjust per market | ⚠️ | System only uses fixed 20/2 defaults — no adaptive parameter selection |
| 10 | Average should describe intermediate-term trend | ✅ | 20-period SMA is descriptive, not crossover-optimized |
| 11 | Width–length relationship (10→1.9, 20→2, 50→2.1) | ❌ | Not implemented — see Section 13 |
| 12 | Use SMA for logical consistency | ✅ | SMA used throughout |
| 13 | Don't make statistical assumptions — samples too small | ✅ | No z-score or normal-distribution claims on BB |
| 14 | Normalize indicators with %b | ❌ | Not implemented — see Section 10 |
| 15 | Tags are tags, not signals | ✅ | Walking logic + head fake + confirmation required |

---

## 4. Volume Indicators from the Book

### Book Reference (Ch. 18, Table 18.3, pp. 146–154)

The book defines **8 specific volume indicators** and emphasizes four as primary:

| Indicator | Book Formula | Implemented? | File | Verdict |
|-----------|-------------|-------------|------|---------|
| **Intraday Intensity (II)** | `(2×close − high − low) / (high − low) × volume` | ❌ | — | **Missing** |
| II% (21-day oscillator) | 21-day normalized sum | ❌ | — | **Missing** |
| **Accumulation Distribution (AD)** | `(close − open) / (high − low) × volume` | ❌ | — | **Missing** |
| AD% (21-day oscillator) | 21-day normalized sum | ❌ | — | **Missing** |
| **Money Flow Index (MFI)** | `100 − 100/(1 + pos_mf_sum / neg_mf_sum)` | ✅ | `bb_squeeze/indicators.py:196-218` | ✅ |
| **Volume-Weighted MACD** | VW-EMA(12) − VW-EMA(26), signal = EMA(9) | ❌ | — | **Missing** |
| On Balance Volume (OBV) | `volume × sign(change)` | ✅ | `technical_analysis/indicators.py:229-233` | ✅ (in TA module) |
| Volume-Price Trend | `volume × pct_change` | ❌ | — | Missing |
| Chaikin Money Flow (CMF) | Not in book — Chaikin variant | ✅ | `bb_squeeze/indicators.py:177-189` | ⚠️ Substitute |

### Critical Finding

The book's **primary volume indicators for Bollinger Band methods** are **II, AD, MFI, and VWMACD**. Your system uses:
- **MFI** ✅ (correct formula, correct 10-period per book's half-BB-period rule)
- **CMF** ⚠️ (a Chaikin variant — NOT one of the book's four primary indicators)

**Missing entirely:** Intraday Intensity (II), Accumulation Distribution (AD), and Volume-Weighted MACD (VWMACD).

These matter because:
- **Method I** (Ch. 16): Book says "use volume indicators for directional clues" — specifically II and AD.
- **Method III** (Ch. 20): Book's systematized rules use `II% > 0` for buys and `AD% < 0` for sells.
- **Walking the Bands** (Ch. 14): Book uses II and AD in open form for trend confirmation.

---

## 5. Method I — Volatility Breakout (The Squeeze)

### Book Reference (Ch. 15–16, pp. 119–132)

| Requirement | Book | Your Code | Verdict |
|-------------|------|-----------|---------|
| Setup: BBW at 6-month low | Lowest BBW in ~126 days | `is_squeeze()` uses rolling 126-day min + 0.08 trigger | ✅ |
| Entry: Price closes above upper BB | After Squeeze | `cond2_price_above = close > bb_upper` | ✅ |
| Exit Option 1: Parabolic SAR | Wilder's SAR | Full SAR implementation with init=0.02, max=0.20 | ✅ |
| Exit Option 2: Opposite band tag | Tag of lower band | `exit_lower_band_tag = close <= bb_lower` | ✅ |
| Volume confirmation | Above-average volume | `cond3_volume_ok` checks green candle + vol > 50-SMA | ✅ |
| Volume indicator for direction | II, AD, MFI for direction clues | MFI used; CMF substituted for II/AD | ⚠️ |
| Head fake awareness | Book warns extensively | Dedicated `_head_fake_check()` with 5 filters | ✅ |
| Squeeze phase tracking | Compression → Direction → Explosion | `_phase_detection()` with all 3 phases | ✅ |
| Squeeze consecutive days | Not in book but useful | `_count_squeeze_days()` | ✅ (Enhancement) |

### Deviations

1. **Buy requires ALL 5 conditions simultaneously** — book says enter when price exceeds upper band after Squeeze, with volume indicator for direction. Your system is **stricter** than the book (requiring CMF > 0 + MFI > 50 + MFI rising + volume above SMA + green candle), which may cause **missed entries**. Book's Method I is simpler: Squeeze + breakout above band + direction clue from volume indicator.

2. **Short/sell side of Method I is incomplete.** Book says "a short sale signal is triggered by falling below the lower band after a Squeeze." Your `signals.py` only generates bullish buy signals from the Squeeze — **bearish breakout signals from Method I are not generated as primary buy-equivalent signals.** The sell signals are only exit signals for existing positions.

3. **Absolute BBW trigger (0.08)** — the book does NOT define an absolute trigger. It only says "BandWidth at its lowest level in six months." Your `is_squeeze()` uses `bbw <= trigger` (0.08) as an OR condition with the rolling min. This absolute threshold is not from the book.

---

## 6. Method II — Trend Following

### Book Reference (Ch. 19, pp. 155–159)

| Requirement | Book Value | Your Code | Verdict |
|-------------|-----------|-----------|---------|
| Buy: %b > 0.8 AND MFI > 80 | Exact thresholds | `M2_PCT_B_BUY_THRESHOLD = 0.8` ✅, `M2_MFI_CONFIRM_BUY = 60` ⚠️ | ⚠️ |
| Sell: %b < 0.2 AND MFI < 20 | Exact thresholds | `M2_PCT_B_SELL_THRESHOLD = 0.2` ✅, `M2_MFI_CONFIRM_SELL = 40` ⚠️ | ⚠️ |
| MFI period = half BB period | MFI(10) for BB(20) | `MFI_PERIOD = 10` | ✅ |
| Exit: Parabolic or opposite band | From the book | Not explicitly wired into Method II exits | ⚠️ |
| VWMACD as alternative | Book suggests | Not implemented | ❌ |
| Indicator length = half BB | Book rule | `MFI_PERIOD = 10` for `BB_PERIOD = 20` | ✅ |
| Use signals as alerts, trade first pullback | Book variation | Not implemented | ❌ |
| Rational Analysis (fundamental filter) | Book Ch. 19 | Not in Method II code | ❌ |

### Critical Deviation: MFI Thresholds

The book says **MFI > 80** for buy and **MFI < 20** for sell. Your config uses:
- `M2_MFI_CONFIRM_BUY = 60` (book says 80)
- `M2_MFI_CONFIRM_SELL = 40` (book says 20)

These relaxed thresholds will generate **significantly more signals** than the book intends. The book's strict 80/20 thresholds are deliberate — they capture only the strongest trends.

---

## 7. Method III — Reversals (W-Bottoms / M-Tops)

### Book Reference (Ch. 12–13, Ch. 20, pp. 96–111, 160–165)

| Requirement | Book | Your Code | Verdict |
|-------------|------|-----------|---------|
| W-Bottom: 1st low at/below lower band | %b ≤ 0 | `M3_W_FIRST_LOW_PCT_B = 0.0` + tolerance 0.05 | ✅ |
| W-Bottom: 2nd low ABOVE lower band | %b > 0 (relative higher) | `M3_W_SECOND_LOW_PCT_B = 0.2` | ✅ |
| M-Top: 1st high at/above upper band | %b ≥ 1 | `M3_M_FIRST_HIGH_PCT_B = 1.0` − tolerance 0.05 | ✅ |
| M-Top: 2nd high BELOW upper band | %b < 1 (relative lower) | `M3_M_SECOND_HIGH_PCT_B = 0.8` | ✅ |
| MFI divergence on W retest | MFI higher on 2nd low | `mfi_diverges = mfi2 > mfi1 + threshold` | ✅ |
| MFI divergence on M retest | MFI lower on 2nd high | `mfi_diverges = mfi2 < mfi1 − threshold` | ✅ |
| Buy on strength after W | Rally day with > avg range + > avg volume | Not checked in code | ❌ |
| Stop beneath right side of W | Book says clearly | Not explicitly computed for Method III | ❌ |
| Three pushes to a high | Ch. 13, p. 108 | **Not implemented** | ❌ |
| Head-and-shoulders decomposition | Ch. 13, pp. 105–110 | **Not implemented** | ❌ |
| Book's systematized Method III buy | `%b < 0.05 AND II% > 0` | Uses `%b < first_low tolerance AND MFI divergence` instead | ⚠️ |
| Book's systematized Method III sell | `%b > 0.95 AND AD% < 0` | Uses M-Top pattern + MFI divergence instead | ⚠️ |

### Critical Findings

1. **The book's exact Method III systematized rules** (pp. 163–165) are:
   - Buy: `%b < 0.05 AND II% > 0`
   - Sell: `%b > 0.95 AND AD% < 0`

   Your system uses a pattern-matching approach (local-minima pairs with %b checks) rather than the book's simple threshold rules. The approach is **conceptually aligned** but **not the exact formulation**.

2. **Three pushes to a high** (p. 108) — a very common and important pattern where each successive push has lower %b and declining volume — is not detected.

3. **Entry/exit discipline for Method III** — the book says buy on a "rally day with greater-than-average range AND greater-than-average volume" and set stop beneath the most recent low. Neither of these specific entry/exit rules is implemented.

---

## 8. Walking the Bands

### Book Reference (Ch. 14, pp. 112–118)

| Requirement | Book | Your Code | Verdict |
|-------------|------|-----------|---------|
| Tags during trends = continuation | Core concept | Correctly treated as HOLD/confirmation | ✅ |
| 3+ touches needed for walk | Implied by book | `M4_WALK_MIN_TOUCHES = 3` in 10 bars | ✅ |
| Middle band as support in uptrend | Book says "excellent entry" | Walk-break detection at %b < 0.5 | ✅ |
| Exit when price pulls to middle band | Book says "trend has changed" | Sell when upper walk breaks + %b < 0.5 | ✅ |
| Volume indicators for walk confirmation | II, AD open-form | **Not used** — only MFI, CMF | ⚠️ |
| Three primary legs (Elliott convention) | Book mentions | Not tracked | ⚠️ |
| Expansion rule (lower band turns down in uptrend) | Ch. 15, p. 123 | **Not implemented** | ❌ |

---

## 9. Head Fake Detection

### Book Reference (Ch. 15–16, pp. 121–123, 127–129)

| Requirement | Book | Your Code | Verdict |
|-------------|------|-----------|---------|
| Head fake awareness | Core concept | Dedicated function | ✅ |
| Volume below average = fake | Book says key clue | Filter #1: `volume < vol_sma` | ✅ |
| CMF negative on upside break | Direction mismatch | Filter #2: `close > bb_upper and cmf < 0` | ✅ |
| MFI below 50 on upside break | Weak fuel | Filter #3: `close > bb_upper and mfi < 50` | ✅ |
| BBW not expanding | Bands not widening | Filter #4: `bbw < bbw_6m * 1.02` | ✅ |
| Long upper wick rejection | Price action | Filter #5: wick > 60% of range | ✅ (Enhancement) |
| "Trade half opposite then add" | Book's head-fake strategy | Not implemented as a position-sizing rule | ⚠️ |
| "Once a faker..." — check history | Book's heuristic | Not tracked | ❌ |

**Assessment:** Head fake detection is **well-implemented with creative enhancements** beyond the book. The wick-rejection filter (#5) is not in the book but is a sensible addition.

---

## 10. Normalizing Indicators with Bollinger Bands

### Book Reference (Ch. 21, pp. 169–175)

**Status: ❌ Not implemented**

The book dedicates an entire chapter to this concept. Key rules:
- Apply Bollinger Bands to indicators (RSI, MFI, etc.) to define adaptive overbought/oversold levels instead of fixed thresholds.
- 14-period RSI: Use 50-period, 2.1-std-dev Bollinger Bands.
- 10-period MFI: Use 40-period, 2.0-std-dev Bollinger Bands.
- Plot `%b(indicator)` as a normalized version of the indicator.

Your system uses **fixed thresholds** (MFI > 80, MFI < 20, etc.) throughout. The book argues these fixed levels fail during different market regimes and that BB-normalized levels adapt automatically.

---

## 11. Pattern Recognition — Five-Point Patterns

### Book Reference (Ch. 11, pp. 84–95, Merrill's 32 patterns)

**Status: ❌ Not implemented**

The book categorizes all price patterns into 16 Ms and 16 Ws using Arthur Merrill's five-point system with percentage filters (or Bollinger Boxes). Your system detects W-Bottoms and M-Tops using local-minima pairing, but does not:
- Classify patterns into the 32 Merrill categories.
- Use percentage filters or Bollinger Boxes for pattern filtering.
- Map patterns to the Merrill taxonomy (Table 11.3).

This is an **advanced feature** — the W/M detection you have covers the most important patterns.

---

## 12. Multicollinearity / Indicator Selection

### Book Reference (Ch. 17, pp. 140–141; Rule 5)

**Status: ⚠️ Potential violation**

The book's Rule 5 says: *"Two indicators from the same category do not increase confirmation. Avoid collinearity."*

Your system uses **both CMF and MFI** as confirmation indicators:
- **CMF** — Chaikin Money Flow — volume indicator (closed-form oscillator)
- **MFI** — Money Flow Index — volume indicator (closed-form oscillator)

Both are from the **same category** (volume indicators, closed-form). The book would say they don't provide independent confirmation. The book recommends using one volume indicator + one from another category (momentum, sentiment, etc.).

**However:** CMF and MFI are computed differently (CMF uses close-vs-range positioning × volume; MFI uses typical-price direction × volume), so in practice they can give different signals. But by the book's strict category rules, this is a collinearity issue.

---

## 13. Width–Length Relationship

### Book Reference (Rule 11, p. 184)

**Status: ❌ Not implemented**

The book states:
> "If the average is lengthened, the number of standard deviations needs to be increased simultaneously — from 2 at 20 periods to 2.1 at 50 periods. Likewise, if the average is shortened, the number of standard deviations should be reduced — from 2 at 20 periods to 1.9 at 10 periods."

Your system uses fixed `BB_PERIOD = 20` and `BB_STD_DEV = 2.0` everywhere. If users were to change the period, the system would **not** auto-adjust the standard deviation width. This matters for:
- Day trading (shorter periods → need 1.9 std dev)
- Long-term analysis (longer periods → need 2.1 std dev)

---

## 14. The Expansion (Reverse Squeeze)

### Book Reference (Ch. 15, p. 123)

**Status: ❌ Not implemented**

The Expansion is the reverse of The Squeeze:
> "When a powerful trend is born, volatility expands so much that the lower band turns down in an uptrend or the upper band turns up in a downtrend."
> "When the Expansion reverses, odds are very high the trend is at an end."

Your system does not track the Expansion. Specifically:
- No detection of lower-band-turning-down during uptrends.
- No detection of Expansion reversal as an end-of-trend signal.

---

## 15. Day Trading Adaptations

### Book Reference (Ch. 22, pp. 176–180)

**Status: ❌ Not implemented (not applicable if system is daily-only)**

The book suggests:
- Tighten BB parameters (15 periods, 1.5 std dev) for day trading.
- MFI and VWMACD are more reliable intraday than AD and II.
- Squeeze is mandatory for intraday breakout logic.

If your system is daily-timeframe only, this is not a gap. But if intraday is planned, these adaptations are needed.

---

## 16. Parameter Configuration Audit

### `bb_squeeze/config.py`

| Parameter | Book Value | Your Value | Match? |
|-----------|-----------|-----------|--------|
| BB_PERIOD | 20 | 20 | ✅ |
| BB_STD_DEV | 2.0 | 2.0 | ✅ |
| BB_MA_TYPE | SMA | SMA | ✅ |
| BBW_LOOKBACK | ~126 (6 months) | 126 | ✅ |
| BBW_TRIGGER | N/A (book uses rolling min only) | 0.08 | ⚠️ Extra |
| SAR_INIT_AF | 0.02 | 0.02 | ✅ |
| SAR_MAX_AF | 0.20 | 0.20 | ✅ |
| MFI_PERIOD | 10 (half BB) | 10 | ✅ |
| MFI_OVERBOUGHT | 80 | 80 | ✅ |
| MFI_OVERSOLD | 20 | 20 | ✅ |
| VOLUME_SMA_PERIOD | 50 | 50 | ✅ |

### `bb_squeeze/strategy_config.py`

| Parameter | Book Value | Your Value | Match? |
|-----------|-----------|-----------|--------|
| M2_PCT_B_BUY_THRESHOLD | 0.8 | 0.8 | ✅ |
| M2_PCT_B_SELL_THRESHOLD | 0.2 | 0.2 | ✅ |
| M2_MFI_CONFIRM_BUY | **80** | **60** | ❌ Relaxed |
| M2_MFI_CONFIRM_SELL | **20** | **40** | ❌ Relaxed |
| M3_W_FIRST_LOW_PCT_B | 0.0 | 0.0 | ✅ |
| M3_W_SECOND_LOW_PCT_B | >0 (book says "above lower band") | 0.2 | ✅ (conservative) |
| M3_M_FIRST_HIGH_PCT_B | 1.0 | 1.0 | ✅ |
| M3_M_SECOND_HIGH_PCT_B | <1.0 (book says "below upper band") | 0.8 | ✅ (conservative) |

---

## 17. Summary Matrix

| Concept from Book | Status | Severity |
|-------------------|--------|----------|
| BB Construction (SMA, ddof=0, 20/2) | ✅ Correct | — |
| %b formula | ✅ Correct | — |
| BandWidth formula | ✅ Correct | — |
| Squeeze detection (BBW 6-month low) | ✅ Correct | — |
| Parabolic SAR (exit) | ✅ Correct | — |
| MFI formula + 10-period | ✅ Correct | — |
| Volume SMA (50-day) | ✅ Correct | — |
| Head fake detection | ✅ Correct + enhanced | — |
| Walking the Bands | ✅ Correct | — |
| Method I (Volatility Breakout) | ✅ Core correct, stricter than book | Low |
| W-Bottoms detection | ✅ Pattern logic correct | — |
| M-Tops detection | ✅ Pattern logic correct | — |
| Phase detection (Compression→Direction→Explosion) | ✅ Enhancement | — |
| Method II MFI thresholds | ❌ **60/40 vs book's 80/20** | **HIGH** |
| Method III systematized rules (%b < 0.05 + II%) | ⚠️ Conceptually close, different formulation | Medium |
| Intraday Intensity (II) indicator | ❌ Missing | **HIGH** |
| Accumulation Distribution (AD) indicator | ❌ Missing | **HIGH** |
| Volume-Weighted MACD (VWMACD) | ❌ Missing | Medium |
| Indicator normalization with BB (Ch. 21) | ❌ Missing | Medium |
| Three pushes to a high | ❌ Missing | Medium |
| Head-and-shoulders decomposition | ❌ Missing | Low |
| Width–length relationship (Rule 11) | ❌ Missing | Low |
| The Expansion (reverse Squeeze) | ❌ Missing | Medium |
| Five-point Merrill patterns | ❌ Missing | Low |
| Collinearity: CMF + MFI both volume | ⚠️ Same category | Medium |
| Bollinger Boxes | ❌ Missing | Low |
| Short-side Method I signals | ❌ Missing | Medium |
| Entry discipline (avg range + avg vol day) | ❌ Missing from Method III | Medium |
| Method III stops (beneath right side of W) | ❌ Missing | Medium |

---

## 18. Recommendations (Priority Order)

### HIGH Priority — Deviations from the Book

1. **Fix Method II MFI thresholds** — Change `M2_MFI_CONFIRM_BUY` from 60 → **80** and `M2_MFI_CONFIRM_SELL` from 40 → **20** in `strategy_config.py:17-18`. The book is explicit: `%b > 0.8 AND MFI > 80` for buy, `%b < 0.2 AND MFI < 20` for sell.

2. **Implement Intraday Intensity (II)** — Formula: `(2×close − high − low) / (high − low) × volume`. Add both open-form (cumulative) and closed-form (21-day normalized oscillator II%). This is the book's preferred indicator for Method I direction and Method III reversals.

3. **Implement Accumulation Distribution (AD)** — Formula: `(close − open) / (high − low) × volume`. Add both forms. This is specifically called for in Method III sell rules (`AD% < 0`).

### MEDIUM Priority — Missing Concepts

4. **Implement VWMACD** — Formula: 12-period volume-weighted average minus 26-period volume-weighted average; signal = 9-period EMA. The book suggests it as an alternative to MFI in Method II.

5. **Add The Expansion detection** — Track when the lower band turns down during an uptrend (or upper band turns up during a downtrend). When this reverses, signal end-of-trend.

6. **Implement three-pushes-to-a-high** — Detect three successive highs where %b decreases on each push and volume diminishes. This is described as "very common" by the book.

7. **Implement indicator normalization** — Apply BB to RSI and MFI to create adaptive overbought/oversold levels instead of fixed thresholds. Plot %b(indicator) as the normalized version.

8. **Add short-side Squeeze signals** — Method I explicitly includes short selling when price breaks below the lower band after a Squeeze.

9. **Add Method III entry/exit discipline** — Buy on rally day with above-average range + above-average volume. Stop beneath right side of W.

10. **Address CMF+MFI collinearity** — Consider replacing CMF with a non-volume indicator (e.g., RSI from a different category) to satisfy Rule 5. Alternatively, keep CMF but use it as a supplementary confirmation only, not as a primary buy condition.

### LOW Priority — Nice-to-Have

11. **Width–length auto-adjustment** — If different BB periods are ever offered, auto-scale std dev (10→1.9, 50→2.1).

12. **Head-and-shoulders decomposition** — Break complex tops into M-building-blocks per the Merrill taxonomy.

13. **Five-point Merrill pattern classification** — Classify all patterns into the 32-pattern taxonomy.

14. **Typical price option** — Allow BB computation on `(H+L+C)/3` as an alternative to close.

---

*Audit complete. The system's core Bollinger Band mathematics (construction, %b, BandWidth, Squeeze, Parabolic SAR) are faithfully implemented. The main gaps are: (a) missing book-specific volume indicators (II, AD, VWMACD), (b) relaxed Method II MFI thresholds, and (c) missing advanced concepts (normalization, Expansion, three-pushes). No code was modified during this audit.*
