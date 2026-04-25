# Bollinger on Bollinger Bands — Complete Extraction

> Source: *Bollinger on Bollinger Bands* by John Bollinger (2002, McGraw-Hill)
> Extracted from the full text, page by page, with no sections skipped.

---

## Table of Contents

1. [The 15 Basic Rules](#1-the-15-basic-rules)
2. [Formulas and Indicator Calculations](#2-formulas-and-indicator-calculations)
3. [Parameter Values and Defaults](#3-parameter-values-and-defaults)
4. [Trading Methods](#4-trading-methods)
5. [Chart Pattern Definitions](#5-chart-pattern-definitions)
6. [Guidelines and Heuristics by Chapter](#6-guidelines-and-heuristics-by-chapter)
7. [Quotes with Page Numbers](#7-quotes-with-page-numbers)

---

## 1. The 15 Basic Rules

*(Part VI, pp. 183–184)*

1. **Bollinger Bands provide a relative definition of high and low.**
2. **That relative definition can be used to compare price action and indicator action to arrive at rigorous buy and sell decisions.**
3. **Appropriate indicators can be derived from momentum, volume, sentiment, open interest, intermarket data, etc.**
4. **Volatility and trend already have been deployed in the construction of Bollinger Bands, so their use for confirmation of price action is not recommended.**
5. **The indicators used for confirmation should not be directly related to one another. Two indicators from the same category do not increase confirmation. Avoid collinearity.**
6. **Bollinger Bands can be used to clarify pure price patterns such as M-type tops and W-type bottoms, momentum shifts, etc.**
7. **Price can, and does, walk up the upper Bollinger Band and down the lower Bollinger Band.**
8. **Closes outside the Bollinger Bands can be continuation signals, not reversal signals — as is demonstrated by the use of Bollinger Bands in some very successful volatility-breakout systems.**
9. **The default parameter of 20 periods for calculating the moving average and standard deviation and the default parameter of 2 standard deviations for the BandWidth are just that, defaults. The actual parameters needed for any given market or task may be different.**
10. **The average deployed should not be the best one for crossover signals. Rather, it should be descriptive of the intermediate-term trend.**
11. **If the average is lengthened, the number of standard deviations needs to be increased simultaneously — from 2 at 20 periods to 2.1 at 50 periods. Likewise, if the average is shortened, the number of standard deviations should be reduced — from 2 at 20 periods to 1.9 at 10 periods.**
12. **Bollinger Bands are based upon a simple moving average. This is because a simple moving average is used in the standard deviation calculation and we wish to be logically consistent.**
13. **Be careful about making statistical assumptions based on the use of the standard deviation calculation in the construction of the bands. The sample size in most deployments of Bollinger Bands is too small for statistical significance, and the distributions involved are rarely normal.**
14. **Indicators can be normalized with %b, eliminating fixed thresholds in the process.**
15. **Finally, tags of the bands are just that — tags, not signals. A tag of the upper Bollinger Band is not in and of itself a sell signal. A tag of the lower Bollinger Band is not in and of itself a buy signal.**

---

## 2. Formulas and Indicator Calculations

### 2.1 Bollinger Bands Construction (Ch. 7, pp. 50–59)

| Component | Formula |
|-----------|---------|
| **Middle Band** | 20-period simple moving average of closing price |
| **Upper Band** | Middle Band + (2 × standard deviation) |
| **Lower Band** | Middle Band − (2 × standard deviation) |

- **Standard deviation** uses the **population formula** (divisor = *n*, not *n − 1*). (Endnote Ch. 7, p. 190)
- Typical price `(high + low + close) / 3` or `(open + high + low + close) / 4` may substitute for close. (Endnote Ch. 6, p. 189)

### 2.2 %b (Ch. 8, pp. 60–63)

```
%b = (last − lower BB) / (upper BB − lower BB)
```

| Value | Position |
|-------|----------|
| 1.0 | At upper band |
| 0.5 | At middle band |
| 0.0 | At lower band |
| > 1.0 | Above upper band |
| < 0.0 | Below lower band |

Derivation acknowledged from George Lane's stochastics formula: `(last − n-period lowest low) / (n-period highest high − n-period lowest low)`. (Endnote Ch. 8, p. 191)

### 2.3 BandWidth (Ch. 8, pp. 63–67; Ch. 15, p. 120)

```
BandWidth = (upper BB − lower BB) / middle BB
```

Mathematically equals `4 × standard deviation / mean` (four times the coefficient of variation). (Endnote Ch. 8, p. 191; Endnote Ch. 15, p. 194)

### 2.4 Volume Indicator Formulas (Table 18.3, p. 148)

| Indicator | Formula |
|-----------|---------|
| **On Balance Volume (OBV)** | volume × sign of the change |
| **Volume-Price Trend (V-PT)** | volume × percentage change |
| **Negative Volume Index (NVI)** | If volume falls, accumulate price change |
| **Positive Volume Index (PVI)** | If volume rises, accumulate price change |
| **Intraday Intensity (II)** | `(2 × close − high − low) / (high − low) × volume` |
| **Accumulation Distribution (AD)** | `(close − open) / (high − low) × volume` |
| **Money Flow Index (MFI)** | `100 − 100 / (1 + positive price×volume sum / negative price×volume sum)` |
| **Volume-Weighted MACD** | 12-period vol-weighted avg of last − 26-period vol-weighted avg of last |
| **VWMACD Signal Line** | 9-period exponential average of VWMACD |

### 2.5 Normalized Volume Oscillator (Table 18.4, p. 151)

```
10-day sum of [(close − open) / (high − low) × volume] / 10-day sum of volume
```

Normalized versions referred to as percents: 21-day II%, 10-day AD%, etc. (p. 151)

### 2.6 Normalized Indicator Formula (Table 21.2, p. 173)

```
%b(indicator) = (indicator − indicator lower band) / (indicator upper band − indicator lower band)
```

### 2.7 Bollinger Boxes (Ch. 11, pp. 91–92)

```
Box size = 0.17 × last^0.5
```

(17 percent of the square root of the most recent price)

### 2.8 MACD (Endnote Ch. 18, p. 195)

```
MACD = 12-period exponential average of last − 26-period exponential average of last
Signal line = 9-period exponential average of MACD
```

To convert days to EMA percentage: `2 / (n + 1)` (Endnote Ch. 20, p. 196)

### 2.9 Volume-Weighted Moving Average (Endnote Ch. 18, p. 196)

```
n-day VW avg = n-day sum of (last × volume) / n-day sum of volume
```

### 2.10 Arms Index (Endnote Ch. 20, p. 196)

```
Arms Index = (advances / declines) / (up volume / down volume)
```

Neutral at 1.0; long-term average ~0.85 (positive market bias). (p. 196)

### 2.11 Typical Price (Endnote Ch. 6, p. 189)

```
Typical price = (high + low + close) / 3
Extended    = (open + high + low + close) / 4
```

### 2.12 Standard Deviation — Population Formula (Ch. 7, p. 52)

```
σ = √[ Σ(xi − mean)² / n ]
```

Population divisor (*n*) is used, not sample divisor (*n − 1*). (Endnote Ch. 7, p. 190)

---

## 3. Parameter Values and Defaults

### 3.1 Bollinger Band Defaults (Ch. 7)

| Parameter | Default |
|-----------|---------|
| Average length | 20 periods |
| Width multiplier | ±2 standard deviations |
| Moving average type | Simple moving average |

### 3.2 Width–Length Relationship (Rule 11, p. 184)

| Average Length | Standard Deviations |
|----------------|---------------------|
| 10 periods | 1.9 |
| 20 periods | 2.0 |
| 50 periods | 2.1 |

### 3.3 Containment (Ch. 7; Endnote Ch. 7, p. 190)

- At 20 periods / 2 std dev: **~89% of data for stocks** (not the 95.4% expected from normal distribution, due to fat tails / leptokurtosis).
- Bomar Bands originally targeted 85% containment. (Endnote Ch. 7, p. 190)

### 3.4 Time Frames (Ch. 3, pp. 19–25)

| Frame | Approximate Length |
|-------|-------------------|
| Short term | ~10 periods |
| Intermediate term | ~20 periods (default) |
| Long term | ~50 periods |

### 3.5 Indicator Length Rule (Ch. 19, p. 157)

> Indicator length should be approximately **half** the length of the BB calculation period.

### 3.6 Bollinger Bands on Indicators (Table 21.1, p. 171)

| Indicator | BB Length | BB Width |
|-----------|-----------|----------|
| 9-period RSI | 40 | 2.0 |
| 14-period RSI | 50 | 2.1 |
| 10-period MFI | 40 | 2.0 |
| 21-period II | 40 | 2.0 |

Goal: 85–90% of all observations fall within the bands. (p. 171)

### 3.7 MFI Benchmarks (Ch. 18, p. 152)

| Indicator | Overbought | Oversold |
|-----------|-----------|----------|
| RSI | 70 | 30 |
| MFI | 80 | 20 |

### 3.8 Parabolic Stop Parameters (Endnote Ch. 19, p. 196)

| Parameter | Value |
|-----------|-------|
| Initial acceleration factor | 0.02 |
| Terminal acceleration factor | 0.20 |

Larger initial or step values = faster stop increments, quicker exits, more whipsaws. (p. 196)

### 3.9 Volume Normalization (Ch. 2, p. 16)

Standard reference: **50-day moving average of volume**.

### 3.10 Indicator Categories (Table 17.1, p. 140)

| Category | Example Indicators |
|----------|-------------------|
| Momentum | Rate of change, Stochastics |
| Trend | Linear regression, MACD |
| Sentiment | Survey, Put-call ratio |
| Volume (open) | Intraday Intensity, Accumulation Distribution |
| Volume (closed) | Money Flow Index, Volume-Weighted MACD |
| Overbought/oversold | Commodity Channel Index, RSI |

**Rule:** Use only one indicator from each category to avoid multicollinearity. (p. 140)

### 3.11 ChartCraft Box Sizes (Table 11.1, p. 91)

| Price Range | Box Size |
|-------------|----------|
| Below $5 | ¼ point |
| $5–$20 | ½ point |
| $20–$100 | 1 point |
| Above $100 | 2 points |

### 3.12 Bollinger Boxes Sample Reversals (Table 11.2, p. 92)

| Price | Reversal % |
|-------|-----------|
| $4.50 | 8% |
| $8.00 | 6% |
| $18.00 | 4% |
| $69.00 | 2% |

### 3.13 Method III Breadth MACD Parameters (Ch. 20, p. 162)

| MACD Parameter | Value (Days) | Value (%) |
|----------------|-------------|-----------|
| Short-term average | 21 | 9% |
| Long-term average | 100 | 2% |
| Signal line | 9 | 20% |

Data inputs: advances − declines; up volume − down volume. (p. 162)

### 3.14 The Squeeze — Advanced Definition (Endnote Ch. 15, p. 194)

1. Plot 20-day standard deviation of the close (or typical price).
2. Plot 125-day, 1.5-standard-deviation Bollinger Bands on that standard deviation.
3. A Squeeze is triggered when the 20-day standard deviation tags the lower band.

---

## 4. Trading Methods

### 4.1 Method I — Volatility Breakout (Ch. 16, pp. 125–132)

**Philosophy:** Anticipate high volatility by exploiting the cyclical nature of volatility; look for extremely low volatility as a precursor of high volatility.

**Setup:**
- BandWidth drops to its **lowest level in six months** → Squeeze is on.

**Entry:**
- **Buy** when the upper Bollinger Band is exceeded after a Squeeze.
- **Short** when the lower Bollinger Band is broken to the downside after a Squeeze.

**Exit (two options):**
1. **Parabolic trailing stop:** Initial stop just below the range of the breakout formation; incremented upward each day.
2. **Opposite band tag:** In a buy, exit on a tag of the lower band; in a short, exit on a tag of the upper band.

**Head Fake Management:**
- Stocks often feint in the wrong direction before making the real move. (p. 121, 127)
- Strategy: Wait for Squeeze, look for first move away from trading range. Trade half a position the first strong day in the **opposite** direction of the head fake, add to position when breakout occurs, use Parabolic or opposite band tag stop. (p. 128)
- "Once a faker..." — check past Squeezes for head-fake tendency. (p. 128)
- Volume indicators (II, AD, MFI) give hints regarding ultimate resolution. (p. 129)

**Parameters:**
- Standard: 20-day average, 2 standard deviation bands. (p. 129)
- Short-term traders: shorten to 15 periods, tighten to 1.5 std dev. (p. 129)
- Longer Squeeze look-back period = greater compression, more explosive setups, but fewer of them. (p. 129)

---

### 4.2 Method II — Trend Following (Ch. 19, pp. 155–159)

**Philosophy:** Anticipate the birth of trends by looking at strength in price confirmed by indicator strength.

**Buy Rule:**
```
%b > 0.8  AND  MFI(10) > 80  →  BUY
```

**Sell Rule:**
```
%b < 0.2  AND  MFI(10) < 20  →  SELL
```

**Exit:** Modified Parabolic or tag of opposite Bollinger Band. (p. 155)

**Variations (Table 19.1, p. 157):**
- VWMACD can substitute for MFI.
- VWMACD histogram (VWMACD minus its 9-day signal line) for shorter-term, more sensitive signals. (p. 157)
- Strength thresholds for %b and indicator can be varied.
- Parabolic speed can be varied.
- BB length parameter can be adjusted.
- Adjusting %b threshold is equivalent to adjusting BandWidth. (p. 157)
- For very volatile growth stocks: consider %b > 1.0, higher MFI, higher Parabolic. (p. 158)
- Start Parabolic under most recent significant low (not entry day). (p. 158)

**Alert Variation:** Use signals as alerts; trade the first pullback after the alert. Reduces trades and whipsaws. (p. 158)

**Rational Analysis:** Presort universe by fundamental criteria — take buy signals only for fundamentally attractive stocks, sell signals only for fundamentally weak stocks. (p. 158)

---

### 4.3 Method III — Reversals (Ch. 20, pp. 160–165)

**Philosophy:** Anticipate reversals by comparing tags of the bands to indicator action.

**Buy Setup:**
- Lower band tag + positive oscillator reading.
- Systematized: `%b < 0.05 AND II% > 0` → Go long. (p. 165)

**Sell Setup:**
- Upper band tag + negative oscillator reading.
- Systematized: `%b > 0.95 AND AD% < 0` → Go short. (p. 165)

**W Bottom Confirmation (with indicators):**
1. Form a W2 bottom where %b is higher on the retest than on the initial low (relative W4). (p. 163)
2. Check volume oscillator (MFI or VWMACD) for similar pattern.
3. If confirmed → buy the first strong up day. If not → wait for another setup.

**M Top Confirmation (with indicators):**
1. %b lower on each push to a high.
2. Volume indicator (e.g., AD) also lower on each push. (p. 164)
3. After pattern develops → sell on meaningful down days where volume and range are greater than average.

**Breadth Indicator Version (for market timing):**
- Use MACD parameters: 21 / 100 / 9 on advances − declines and up volume − down volume data. (p. 162)
- Substitute Bollinger Bands for fixed-percentage bands. (p. 162)
- Tags of upper band + negative breadth oscillator = sell; tags of lower band + positive breadth oscillator = buy.

**Risk-Reward:** Method III setups deliver good risk-reward ratios because a new low is typically close to the entry point, while the target (opposite band tag) is far away. Example given: ~2.5 pts risk vs. ~10 pts target ≈ 4:1. (p. 165)

---

## 5. Chart Pattern Definitions

### 5.1 W-Type Bottoms (Ch. 12, pp. 96–104)

**Definition:** A low followed by a retest and then an uptrend, forming the shape of a capital W.

**Exact Criteria:**
1. First low at or outside the lower Bollinger Band.
2. Reaction rally carries price back inside the bands, often tagging or exceeding the middle band.
3. Second low (retest) occurs **inside** the lower Bollinger Band.
4. **Key rule:** If first low is outside the band and second low is inside the band, the second low is higher on a **relative** basis even if lower on an **absolute** basis. An absolute W8 may be a relative W10. (p. 100)
5. **Invalid W:** Secondary low occurring at or beneath the lower band and/or making a new relative low. (p. 101)
6. Stock does not have to trade beneath the lower band at first low for a valid W — all that is required is that price be **relatively higher** on the retest. (p. 101)

**Entry:**
- Buy strength: Wait for a rally day with **greater than average range AND greater than average volume**. (p. 102)

**Stop/Risk:**
- Initial stop beneath the most recent low (right side of the W). (p. 102)
- Increment upward: Parabolic-style or by eye beneath the lowest point of the most recent consolidation/pullback. (p. 102)
- Start with relatively wide stops and tighten slowly. (p. 102)

**Psychological Variations:**
- **Right side higher** (W4, W5, W10): Frustration — investors waiting for a proper retest are left behind. (p. 98)
- **Right side equal**: Satisfaction — investors buy into the retest easily. (p. 98)
- **Right side lower** (W2, W3, W8 — "spring" in Wyckoff terms): Fear and discomfort — investors shaken out. Greatest profit potential. (p. 100)

**Fractal nature:** Bottom formations on daily charts often contain smaller confirming formations on hourly charts. (p. 101–102)

### 5.2 M-Type Tops (Ch. 13, pp. 105–111)

**Definition:** A rally, a pullback, a subsequent failed test of resistance near the prior highs, followed by the start of a downtrend.

**Characteristics:**
- Tops are more complex than bottoms; typically take more time.
- Triple top is the most common top formation. (p. 105)
- Double tops (Ms) and head-and-shoulders tops are also common.

**Head-and-Shoulders Exact Criteria:**
1. **Left shoulder:** Rally outside the upper BB; pullback. (p. 107)
2. **Head:** Rally to a new high, tags (but does not exceed) the upper BB; steeper pullback to near the first low (neckline area). Volume does not confirm the new high. (p. 107)
3. **Right shoulder:** Failure rally — unable to make a new high, ideally ending near first peak. Fails to tag upper BB. Volume low, action desultory. (p. 107)
4. **Neckline break:** Decline falls beneath levels of first and second declines. Volume picks up. (p. 106)
5. **Throwback rally:** Carries prices back to neckline neighborhood. Last good chance to exit. (p. 107)
6. **Volume pattern:** Strongest on left shoulder, waning across middle, picking up on decline. (p. 106)
7. **Merrill building blocks:** M14/M15 (left shoulder + head) → M3/M4 or M7/M8 (head + right shoulder) → M1/M3 (right shoulder + throwback). (p. 109)

**Three Pushes to a High:**
1. First push outside the upper band. (p. 108)
2. Second push makes a new high and touches the upper band. (p. 108)
3. Third push may make a marginal new high — more often not — but **fails to tag the band**. (p. 108)
4. Volume diminishes steadily across the pattern. (p. 108)
5. Building blocks: M15s or M16s. (p. 108)

**Entry:**
- Wait for a **sign of weakness**: a day with greater-than-average volume and greater-than-average range. (p. 110)
- **Patience:** Wait for countertrend rally (throwback) for entry — provides a perfect low-risk entry point. (p. 110)
- Set stop just above the top of the pullback for precise risk-reward definition. (p. 110)

**Relativity Rule:** A high made outside the bands followed by a new high made inside the bands is always suspect, especially if the second high fails to tag the upper band. (p. 110)

### 5.3 Walking the Bands (Ch. 14, pp. 112–118)

**Definition:** A series of tags of the upper (or lower) band during a sustained trend.

**Rules:**
- Closes outside the bands during a walk are **continuation signals, not reversal signals.** (p. 113)
- If the average is well suited to the stock, it will provide **support on pullbacks** during a walk — excellent entry, add-on, or reentry points. (p. 116)
- Often consists of **three primary legs** (per Elliott convention), but may be more. (p. 116)
- End signal: Weakening ability to get outside the bands; an unconfirmed peak/trough inside the bands. (p. 113)

**Expansion Rule:**
- When a powerful trend is born, volatility expands so much that the **lower band turns down in an uptrend** or the **upper band turns up in a downtrend** — this is an Expansion. (p. 123)
- When the Expansion reverses, odds are very high the trend is at an end. Does not necessarily mean the entire move is over — another leg could materialize — but the current leg is likely over. (p. 123)
- Strategic implication: Time to sell options against existing positions (high premiums). (p. 123)

**Volume Indicators for Walking:**
- Open forms of II or AD: Plot in same clip as price (separate scale); act as trend descriptors. (p. 113–114)
- Closed forms (II% or AD%): Tags accompanied by opposing indicator readings = end-of-trend action signal. (p. 114)
- Small divergences are warnings; clearer divergences follow later if a top/bottom is forming. (p. 114)

### 5.4 The Squeeze (Ch. 15, pp. 119–124)

**Definition:** A period of dramatically low volatility, as measured by BandWidth dropping to its lowest level in six months. (p. 120)

**Core Principle:** Low volatility begets high volatility; high volatility begets low volatility. (p. 121)

**Head Fake:** Near the end of a Squeeze, price often stages a short fake-out move, then abruptly turns and surges in the direction of the emerging trend. (p. 121)

**Direction Forecasting:** Use indicators — is volume picking up on up days? Is AD turning up? Does the range narrow on down days? What is the relationship of the open to the close? News is often the catalyst. (p. 121)

### 5.5 Five-Point Patterns / Merrill Patterns (Ch. 11, pp. 84–95)

**Structure:** 32 possible patterns — 16 Ms and 16 Ws (4 strokes connecting 5 points = 2^5 patterns). (Endnote Ch. 11, p. 193)

**Percentage filters between 2% and 10%** usually work well for stocks. (p. 85)

**Merrill's Categorization (Table 11.3, p. 95):**

| Technical Pattern | Merrill Codes |
|-------------------|---------------|
| Uptrends | M15, M16, W14, W16 |
| Downtrends | M1, M3, W1, W2 |
| Head and shoulders | W6, W7, W9, W11, W13, W15 |
| Inverted head and shoulders | M2, M4, M6, M8, M10, M11 |
| Triangle | M13, W4 |
| Broadening | M5, W12 |

---

## 6. Guidelines and Heuristics by Chapter

### Chapter 1 — Introduction (pp. 3–8)
- The concept of relativity is central: what is high or low should be defined relative to recent action, not absolute levels.
- "It is not that the facts have changed, but that the framework in which the facts are evaluated has changed." (p. 4)

### Chapter 2 — Raw Materials (pp. 9–18)
- Five basic data points: open, high, low, close, volume. (p. 9)
- Volume should be normalized using a 50-day moving average. (p. 16)
- Line charts can give a false sense of continuity. (Endnote Ch. 2, p. 188)

### Chapter 3 — Time Frames (pp. 19–25)
- Always use three time frames: short, intermediate, long. (p. 19)
- The intermediate time frame is your primary operating time frame. (p. 20)
- Alternative BB length selection: Run a moving-average crossover optimization; double the length of the results. (Endnote Ch. 3, p. 188)
- **Insensitivity to small changes in parameters is a key criterion** in developing trading systems. (Endnote Ch. 3, p. 188)

### Chapter 4 — Continuous Advice (pp. 26–29)
- Prefer continuous systems (always in the market or always have an opinion) over discrete point signals. (p. 26–27)
- Accept that not every pattern is diagnosable; undiagnosable formations should be left alone. (p. 28)

### Chapter 5 — Be Your Own Master (pp. 30–32)
- Do your own thinking. No ironclad rules; the markets constantly evolve. (p. 30–31)
- "Two roads diverged in a wood, and I — I took the one less traveled by, And that has made all the difference." — Robert Frost (p. 31)

### Chapter 6 — History (pp. 35–49)
- Historical precedents: Keltner Channels, Donchian Channels (four-week rule), Hurst Envelopes, Bomar Bands, percentage bands. (pp. 36–46)
- Keltner buy line: `10-day MA of typical price + 10-day MA of daily range`. (p. 38)
- Keltner sell line: `10-day MA of typical price − 10-day MA of daily range`. (p. 38)
- Bomar Bands: Spread above and below an average so 85% of data over past year is contained. (p. 45–46)

### Chapter 7 — Construction (pp. 50–59)
- SMA is used (not EMA) for logical consistency with the standard deviation calculation. (p. 55)
- Multiple bands can be plotted using different widths (e.g., ±1 and ±2 std dev). (p. 55, 57)
- Do not mismatch calculation periods (e.g., 10-period average with 20-period standard deviation). (p. 55)
- At 30 periods, bands hold near 89% of data for stocks, not 95.4%. (Endnote Ch. 7, p. 190)

### Chapter 8 — Bollinger Band Indicators (pp. 60–67)
- %b: Shows where you are within the bands; key for system-building.
- BandWidth: Measures volatility relative to the average; key for The Squeeze.
- BandWidth parallels: Lines drawn at fixed BandWidth levels (e.g., a Squeeze threshold). (p. 67)

### Chapter 9 — Statistics (pp. 68–73)
- Regression to the mean: After extreme deviations, expect return toward the mean. (p. 70)
- Security price distributions have **fat tails** (leptokurtosis); they are more variable than normal. (p. 71)
- The central limit theorem helps — larger samples approach normality — but typical BB samples (20 periods) are small. (p. 69)
- Volatility cycles exist and are forecastable. (p. 71)
- Tags of bands on their own are NOT buy/sell signals. (p. 70)

### Chapter 10 — Pattern Recognition (pp. 77–83)
- Ms and Ws are the most common patterns. (p. 82)
- Patterns are often fractal. (p. 82)
- **Lows outside the bands followed by lows inside the bands are typically reversal patterns** even if a new absolute low/high is made. (p. 82)
- Volume and momentum indicators are very useful for diagnosing tops and bottoms. (p. 82)

### Chapter 11 — Five-Point Patterns (pp. 84–95)
- Price filters clarify patterns by removing noise. (p. 95)
- Percentage filters are best for stocks (comparability from issue to issue). (p. 95)
- All price patterns can be categorized as a series of Ms and Ws. (p. 95)

### Chapter 12 — W-Type Bottoms (pp. 96–104)
- W bottoms and their variations are the most common bottom type. (p. 104)
- Spike (V) bottoms happen but are rare. (p. 104)
- Ws may be transitions to bases rather than reversals. (p. 104)
- Buy strength after completion of a W. (p. 104)
- Set a trailing stop to control risk. (p. 104)
- "Down is faster" — confirmed empirically. (Endnote Ch. 12, p. 193)

### Chapter 13 — M-Type Tops (pp. 105–111)
- Tops are more complex than bottoms; harder to diagnose. (p. 111)
- Best known top: head-and-shoulders. (p. 111)
- Three pushes to a high is very common. (p. 111)
- Classic top shows steadily waning momentum. (p. 111)
- Wait for a sign of weakness. (p. 111)
- Look for countertrend rallies to sell. (p. 111)

### Chapter 14 — Walking the Bands (pp. 112–118)
- Walks up and down are quite common. (p. 118)
- A tag of a band is NOT a buy or sell in and of itself. (p. 118)
- Indicators distinguish confirmed from unconfirmed tags. (p. 118)
- The average may provide support and entry points during a sustained trend. (p. 118)

### Chapter 15 — The Squeeze (pp. 119–124)
- Low volatility begets high volatility. (p. 124)
- High volatility begets low volatility. (p. 124)
- Beware the head fake. (p. 124)
- Use indicators to forecast direction. (p. 124)

### Chapter 16 — Method I: Volatility Breakout (pp. 125–132)
- Use the Squeeze as a setup. (p. 132)
- Go with an expansion in volatility. (p. 132)
- Beware the head fake. (p. 132)
- Use volume indicators for direction clues. (p. 132)
- Adjust parameters to suit yourself. (p. 132)

### Chapter 17 — Bollinger Bands and Indicators (pp. 135–145)
- Use indicators to confirm band tags. (p. 145)
- Volume indicators are preferred. (p. 145)
- Avoid collinearity. (p. 145)
- Choose your indicators **before** the trade. (p. 145)
- Use prebuilt templates for analysis. (p. 145)
- If you must optimize, do so carefully. (p. 145)
- **Confirmation:** Tag of upper band + strong indicator = hold/continue. (p. 135)
- **Nonconfirmation:** Tag of lower band + positive indicator = classic buy signal. (p. 135)
- **Neutral indicator at band tag:** Warning — tighten stops. Negative indicator = outright sell signal. (p. 137)
- Use **Rational Analysis** — the juncture of fundamental and technical analysis. (p. 158)
- Optimization: Use **sectioning** — break history into sections, optimize independently, test for consistency (robustness). (p. 144–145)
- Robust method: change parameters by small amounts; results should be consistent. (p. 145)

### Chapter 18 — Volume Indicators (pp. 146–154)
- Volume is an independent variable. (p. 154)
- Focus on AD, II, MFI, and VWMACD. (p. 154)
- Look at both open and closed forms of AD and II. (p. 154)
- Volume precedes price. (p. 146)
- Four categories: periodic price change, periodic volume change, intraperiod structure, volume weighting. (Table 18.2, p. 147)

### Chapter 19 — Method II: Trend Following (pp. 155–159)
- Buy when %b > 0.8 and MFI > 80. (p. 159)
- Sell when %b < 0.2 and MFI < 20. (p. 159)
- Use a Parabolic stop. (p. 159)
- May anticipate Method I. (p. 159)
- Use Rational Analysis. (p. 159)

### Chapter 20 — Method III: Reversals (pp. 160–165)
- Buy setup: lower band tag and oscillator positive. (p. 165)
- Sell setup: upper band tag and oscillator negative. (p. 165)
- Use MACD to calculate breadth indicators. (p. 165)

### Chapter 21 — Normalizing Indicators (pp. 169–175)
- Use Bollinger Bands to normalize indicator levels. (p. 175)
- Generally, longer average lengths are needed for indicators. (p. 175)
- Try replotting the indicator as %b. (p. 175)
- Treat the upper band as overbought and the lower band as oversold — adaptive, not fixed. (p. 172)

### Chapter 22 — Day Trading (pp. 176–180)
- Choose charts carefully; ensure bars are robust (last price should NOT be at high or low a preponderance of the time). (p. 177)
- Tighten BB parameters for trading breakouts after Squeezes. (p. 180)
- Sell reversals outside the bands. (p. 180)
- Try volume indicators (MFI and VWMACD are more reliable intraday than AD and II). (p. 180)
- Be careful about crossing session boundaries — gaps distort averages, bands, and indicators. (p. 180)
- The Squeeze is a necessary element for breakout logic in day trading. (p. 179)

---

## 7. Quotes with Page Numbers

> "By price I mean any combination of the open, high, low, and close for a given period... By far the most common choice is the close, or last." — p. 9

> "It is not that the facts have changed, but that the framework in which the facts are evaluated has changed." — p. 4

> "Bollinger Bands provide a relative definition of high and low. By definition price is high at the upper band and low at the lower band." — p. 60

> "There is absolutely nothing about a tag of a band that in and of itself is a signal." — p. 112

> "The greatest myth about Bollinger Bands is that you are supposed to sell at the upper band and buy at the lower band." — p. 126

> "Closes outside the bands are continuation signals, not reversal signals." — p. 113

> "Low volatility begets high volatility, and high volatility begets low volatility." — p. 121

> "If it is a quiet day, expect a storm. If it is a stormy day, expect quiet." — p. 121

> "A high made outside the bands followed by a new high made inside the bands is always suspect, especially if the second (new) high fails to tag the upper band." — p. 110

> "If the first low occurs outside the band and the second low occurs inside the band, the second low is higher on a relative basis even if it is lower on an absolute basis." — p. 100

> "Volume precedes price." — p. 146

> "Down is faster." — p. 97

> "Pain is, after all, a more insistent emotion than joy." — p. 97

> "Technical analysis is not a stand-alone science; rather it is a depiction of the actions of investors driven by fundamental and psychological facts — or more properly, driven by anticipation of the facts." — p. 103

> "The use of ancillary data and/or methods to improve confidence is fine. Just be careful about what you use and how you use it." — p. 117

> "If you want a simple approach, take one of the three methods presented here and give it a try. Modify it to suit your needs and proceed." — p. 118

> "Investing is a tough task; take care out there." — p. 186

> "...no matter how specific or declarative a book gets, every reader will walk away from reading it with unique ideas and approaches, and that, as they say, is a good thing." — p. 126

> "Two roads diverged in a wood, and I — I took the one less traveled by, And that has made all the difference." — Robert Frost, cited p. 31

> "It could be said of tenor-saxophonist Albert Ayler whose music advanced from screaming sound explorations to early New Orleans-type marching bands, [that he] went so far ahead that he eventually came in at the beginning!" — Scott Yanow, cited p. 186

> "Buying shortly after a new low is made can be very scary, but the fear can be reduced and confidence increased if the indicator used for confirmation does not go to a new low." — p. 139

> "Setups where the risk and reward parameters can be quantified are the only reasonable way to go." — p. 117

> "Every idea presented in this book can be quantified, and we urge you to do so." — p. 118

> "Pick your indicators and create your analysis templates before you trade!" — p. 142

---

*End of extraction. File generated from complete reading of all 8,413 lines of the source text.*
