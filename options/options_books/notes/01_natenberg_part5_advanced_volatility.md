# Natenberg — Part 5: Advanced Volatility, Skews & Volatility Contracts

## Chapters 20-25 + Appendices

---

## Chapter 20: Volatility Revisited

### Core Principle
**The longer an option position is held, the more important realized volatility becomes and the less important implied volatility is.** If held to expiration, realized volatility is the ONLY consideration.

Even if implied volatility rises after you buy options, if time passes and the underlying doesn't move enough, time decay overwhelms the IV benefit. Conversely, if IV falls but the underlying moves significantly, positive gamma profits can overcome the IV decline.

### Historical Volatility Calculation

**Population standard deviation** (for true volatility of a known dataset):
```
σ = sqrt( Σ(xi - μ)² / n )
```

**Sample standard deviation** (estimating future from a sample — most common):
```
σ = sqrt( Σ(xi - μ)² / (n - 1) )
```

Where:
- `xi` = data points (price returns)
- `μ` = mean of all data points
- `n` = number of data points

**Price returns** are typically the logarithmic change:
```
xi = ln(pn / pn-1)
```

**Zero-mean assumption**: Most calculations set μ = 0 regardless of actual mean. Rationale: if a contract goes up 1% every day for 10 days, its volatility should NOT be zero — but using the actual mean would give exactly that.

**Annualization**: Multiply the standard deviation of returns by `sqrt(number_of_periods_per_year)`.
- Using trading days: ~252 days/year → multiply by √252
- Using all calendar days: 365 days/year → multiply by √365
- Both methods yield nearly identical results

**Daily vs. weekly returns**: Daily returns (more data points, ~91 vs. 13 for 3 months) yield a smoother volatility estimate. A contract volatile day-to-day is equally volatile week-to-week.

### Alternative Historical Volatility Estimators

**1. Parkinson (Extreme-Value Method)**
Uses high/low prices during each period:
```
σ = sqrt( (1/n) × Σ [ln(hi/li)]² / (4 × ln(2)) ) / sqrt(t)
```
Where:
- hi = highest price during interval
- li = lowest price during interval  
- t = length of each time interval in years
- n = number of intervals

Better captures intraday movement missed by close-to-close.

**2. Garman-Klass Method**
Extends Parkinson by including open/close prices:
```
σ = sqrt( (1/n) × Σ [0.5 × ln(hi/li)² - (2ln2 - 1) × ln(ci/oi)²] ) / sqrt(t)
```
Where oi = opening price, ci = closing price.

**Important caveat**: Both Parkinson and Garman-Klass assume continuous trading. For markets open only part of the day, they underestimate volatility. Solution: weight the close-to-close estimate against the Parkinson/Garman-Klass estimate, perhaps equally, or proportional to fraction of day the market is open.

### Key Volatility Characteristics

**1. Serial Correlation**
What happened last period is the best predictor of what happens next period (same length). If 4-week volatility was 15%, next 4-week volatility is more likely near 15% than far from it.

**2. Mean Reversion**
Volatility always reverts to a long-term mean. Unlike prices (which can trend indefinitely), volatility always returns to its average range. This is the single most important volatility characteristic for trading.

- Gold: mean ~10-20%
- S&P 500: mean ~15-20%
- Bund: mean ~5%

**3. Term Structure (Volatility Cone)**
Short-term volatility varies wildly; long-term volatility converges to the mean. Conic shape: wider range for short periods, narrower for long.

Counterintuitive implication: long-term volatility is easier to predict (more stable), BUT long-term options have higher vega, so even small errors are magnified. A 2-3% vol error on a long-term option may hurt more than a 5-6% error on a short-term option.

**4. Trending**
Volatility shows trending behavior similar to price charts. Some technical analysis concepts apply but must be adapted — volatility has different dynamics than price.

### Volatility Forecasting Methods

**Weighted Averaging**
Give more weight to data that matches your time horizon:
- For short-term options: weight recent, short-period volatility most heavily
- For long-term options: weight longer-period data (closer to mean)
- Weight by serial correlation: match historical period length to option life

Example for 5-month options with data at 6wk/12wk/26wk/52wk:
```
(15% × 28%) + (25% × 22%) + (35% × 19%) + (25% × 18%) = 20.85%
```
26-week data gets highest weight because 5 months ≈ 26 weeks.

**EWMA (Exponentially Weighted Moving Average)**
```
σ² = Σ αi × ri²
```
Where αi weights are determined by decay factor λ (0 < λ < 1):
```
αi = (1-λ) × λ^(n-i)
```
- λ close to 0: heavily weights recent returns, older returns decay fast
- λ close to 1: weights all returns nearly equally
- Common λ in risk management: ~0.94

**GARCH Models**
Three components:
1. Volatility estimate (like EWMA)
2. Correlation component (large returns follow large returns)
3. Mean-reversion component (speed of reversion to long-term mean)

More sophisticated than EWMA but more complex. Beyond scope of this book.

### Implied Volatility as Predictor

Key finding from empirical data:
- **Implied volatility is an imperfect predictor** of future realized volatility
- IV tends to **lag** realized volatility (reactive, not predictive)
- Under normal conditions, **implied volatility tends to be TOO HIGH** — options tend to be overpriced
- Buyers willingly overpay as insurance premium for rare extreme events

Why options may be "overpriced":
1. Insurance premium — buyers pay extra for protection against rare events
2. Cost of dynamic hedging passed through by market makers
3. Model weaknesses in pricing

### Term Structure of Implied Volatility

Mean reversion causes different expiration months to respond differently to the same event:
- Short-term IV changes more than long-term IV
- If March IV rises from 25% to 30%, June might only rise to 27%, September to 26.5%

**Practical implication for vega risk**: A position with zero total vega across months is NOT necessarily vega-neutral, because different months change at different rates.

Example: Position with monthly vegas +15, -36, -21, +42 sums to 0. But adjusting for term structure:
```
June adjustment: 2/3 → -36 × 0.67 = -24.12
Aug adjustment: 1.5/3 → -21 × 0.5 = -10.50
Oct adjustment: 1.1/3 → +42 × 0.37 = +15.54
True vega = +15.00 - 24.12 - 10.50 + 15.54 = -4.08
```

**Term-structure model inputs**:
1. Primary month (usually front month, sometimes not if front month is unstable)
2. Mean volatility
3. "Whippiness" factor (how fast IV changes propagate to other months)

**Seasonal volatility**: In commodities (natural gas, agricultural), certain months carry permanently elevated IV due to seasonal risk (e.g., October natural gas options elevated due to hurricane season August-September).

### Forward Volatility

Given implied volatilities at two expiration times:
```
σf² × (t2 - t1) = σ2² × t2 - σ1² × t1

σf = sqrt( (σ2² × t2 - σ1² × t1) / (t2 - t1) )
```

This is analogous to forward interest rates. Variance (σ²) is proportional to time (not σ itself).

**Calendar spread implied volatility**: Approximation for at-the-money:
```
IV_spread ≈ (O2 - O1) / (V2 - V1)
```
Where O = option price, V = vega. Useful for quick assessment of relative month mispricing.

---

## Chapter 21: Position Analysis

### Analyzing Complex Positions

**Synthetic rewriting technique**: Convert all positions to same type (all calls or all puts) using synthetic equivalents to recognize familiar patterns.

Example: A position with 9 different legs, when rewritten as all calls, turned out to be simply a long 42/84/42 butterfly at 70/75/65 strikes.

### Risk Sensitivities Change as Markets Move

A position with delta=0, gamma=0, theta=0, vega=0 TODAY is NOT risk-free. These are snapshots that shift as the underlying price, time, and volatility change.

Key dynamic effects:
- Gamma is greatest for ATM options → as underlying moves toward/away from a strike, gamma of that strike increases/decreases
- As vol rises, all deltas move toward ±50; as vol falls, deltas move away from 50
- As time passes (like reducing vol), deltas move away from 50

### Position Visualization

- **Negative delta**: Graph slopes upper-left to lower-right
- **Positive delta**: Graph slopes lower-left to upper-right
- **Negative gamma**: Graph curves downward (frown shape) — hurts on movement
- **Positive gamma**: Graph curves upward (smile shape) — benefits from movement
- Gamma and theta always have opposite signs
- Gamma and vega can be same or opposite sign

### Net Contract Position (Extreme Move Analysis)

Always check: what happens if the market makes a DRAMATIC move in either direction?
- **Upside**: All puts → 0, all calls act like underlying. Net position = sum of calls + underlying contracts
- **Downside**: All calls → 0, all puts act like short underlying. Net position = sum of puts + underlying contracts

These "impossible" moves happen more often than models predict. This check prevents catastrophic surprises.

### Breakeven Volatility of a Position

```
Breakeven vol = assumed vol + (theoretical edge / vega)
```

Example: Vol assumption = 27%, edge = 6.00, vega = -0.759:
```
27.00 + (6.00/0.759) = 34.90%
```
Position breaks even if realized vol stays below ~35%. This is the "implied volatility of the entire position."

### Market Making Principles

Three essential questions for market makers:
1. What does the marketplace think the option is worth? (equilibrium price)
2. What do I think it is worth? (theoretical value)
3. What positions am I currently carrying? (risk management)

Key practices:
- Adjust bid/ask to manage inventory (raise both to attract buys, lower both to attract sells)
- Diversify risk across exercise prices and expiration months
- Concentrated risk at one strike = dangerous, even if total risk measures look fine
- Always consider how risks change under different scenarios

### Stock Splits

For Y-for-X split:
- New stock price = old price × (X/Y)
- New number of options = old × (Y/X)
- New exercise prices = old × (X/Y)
- New delta position = old × (Y/X)
- New gamma position = old × (Y/X)²
- Theta, vega, rho: UNCHANGED
- A stock split has no real economic effect on a position — it's an accounting change

---

## Chapter 22: Stock Index Futures and Options

### Index Types

**Price-weighted** (e.g., Dow Jones): Sum of stock prices. Highest-price stocks dominate.
```
Weighting_i = price_i / Σ prices
```

**Capitalization-weighted** (e.g., S&P 500): Sum of (price × shares outstanding). Largest-cap stocks dominate.
```
Weighting_i = (price_i × shares_i) / Σ(price_j × shares_j)
```

**Equal-weighted**: Each stock contributes equally. Requires periodic rebalancing as stocks outperform/underperform.

### Index Divisor
Used to set initial index value to a round number. Adjusted for stock splits, component changes, and (for total-return indexes) dividend payouts.
```
Divisor = raw_index_value / target_value
```

### Impact of Individual Stock Changes
```
% change in index = % change in stock × stock's weight in index
```
For price-weighted index: each 1-point change in ANY stock = 1/divisor change in index.

### Stock Index Forward Pricing
```
F = S × (1 + r × t) - D       (exact, with discrete dividends)
F = S × [1 + (r - d) × t]     (approximation, d = annualized dividend yield)
```

The approximation works for long-term contracts but can have large errors for short-term contracts because dividend payments come in discrete bundles spread unevenly.

### Index Arbitrage (Program Trading)
Buy/sell futures vs. sell/buy basket of stocks when futures mispriced vs. fair value.

**Delta of futures** relative to cash index: `1 + r × t`
- Must buy/sell more stock than the exact index replication amount
- Adjust as time passes and interest rates change

**Settlement risk**: Futures settle daily (variation), stocks settle at close. The mismatch creates small P&L differences from expected arbitrage profit.

**Bias**: Stock index futures tend to trade below fair value because:
- Portfolio managers (mostly long stocks) sell futures to hedge
- Creates persistent downward pressure
- Short selling stocks is harder/costlier than buying → asymmetric forces

### Index Options

**Options on futures**: Exercise results in a futures position. American-style. Triple witching when futures, futures options, and cash options all expire together.

**Cash index options**: European. Settle in cash. No underlying position from exercise.

**Hedging cash index options**: Use futures as hedging instrument (not the underlying stocks — impractical).

**Serial month pricing**: Use put-call parity to find implied forward price for months without corresponding futures:
```
F = (C - P) × (1 + r × t) + X
```
Then use offset from nearest futures to price serial month options.

---

## Chapter 23: Models and the Real World

### Six Key Assumptions of Traditional Pricing Models

1. **Markets are frictionless** — VIOLATED: transaction costs, borrowing limits, margin, short-sale restrictions, taxes
2. **Interest rates constant** — VIOLATED: rates change, borrow ≠ lend rate, clearing rates vary. Minor risk for short-term options.
3. **Volatility constant** — VIOLATED: volatility clusters, trends, and changes regime. Value of option depends on PATH of volatility, not just average.
4. **Trading is continuous** — VIOLATED: markets close, prices gap on news. Gaps are the single biggest model weakness.
5. **Volatility independent of price** — VIOLATED: stock markets more volatile falling, commodities more volatile rising.
6. **Lognormal distribution** — VIOLATED: real distributions have fat tails (positive kurtosis), more small moves, more big moves, fewer intermediate moves.

### Path Dependency of Option Values

Even with identical 28% realized volatility over 80 days:
- **Rising volatility** (small moves early, big moves late): ATM straddle worth 12.82 (vs. Black-Scholes 10.46)
- **Falling volatility** (big moves early, small moves late): ATM straddle worth 5.94

Why: ATM gamma increases as expiration approaches. High vol near expiration = disproportionately bigger profit from dynamic hedging. For OTM options, the effect reverses (gamma highest early in life).

### Gaps and Jump Risk

At-the-money options close to expiration in low-volatility markets = **highest risk options**.

Reasons:
- Gamma peaks for ATM options near expiration
- Gap causes instant delta change with no opportunity to rehedge
- Lower vol = higher gamma = bigger impact
- Models assume continuous hedging, gaps make this impossible

**Expiration straddle strategy**: Buy ATM straddles cheap near expiration. Rationale: models undervalue them because they don't account for gaps. Most of the time you lose (time decay), but occasional gap produces outsized profit. Like buying cheap insurance — lose often, win big.

### Fat Tails — Real-World Distribution

All exchange-traded markets exhibit:
- More small moves than normal distribution predicts
- More very large moves (fat tails)
- Fewer intermediate moves
- Positive kurtosis

S&P 500 (2003-2012): Biggest up move = 8.84 standard deviations (probability under normal: 1 in 2 quintillion). Biggest down move = 6.75 sigma (1 in 350 billion). These "impossible" moves happen regularly.

### Skewness and Kurtosis

**Skewness**: Lopsidedness of distribution.
- Positive: right tail longer (more big up moves)
- Negative: left tail longer (more big down moves)
- Normal distribution: skewness = 0

**Kurtosis**: Peakedness/tail thickness.
- Positive (leptokurtic): tall peak, fat tails — like a normal distribution with midsection squeezed inward
- Negative (platykurtic): flat peak, thin tails
- Normal distribution: kurtosis = 0 (after subtracting 3 from the raw moment)

Real markets: Almost always positive kurtosis (fat tails). S&P 500 kurtosis of 10.415 is extreme.

---

## Chapter 24: Volatility Skews

### What Causes Skews?

**Investment skew** (stock/index markets — "skew to the downside"):
- Lower strikes have higher IV, higher strikes have lower IV
- Cause: Portfolio hedging — buy protective puts at lower strikes, sell covered calls at higher strikes
- Also: stock markets become more volatile when falling

**Demand/commodity skew** (commodities — "skew to the upside"):
- Higher strikes have higher IV, lower strikes have lower IV
- Cause: End users buy protective calls against rising commodity prices

**Balanced skew** (FX markets):
- Symmetric around ATM
- Cause: Equal hedging pressure from both directions (importers vs. exporters)

### Modeling the Skew

**Polynomial fit**: `y = a + bx + cx²`
Where:
- y = implied volatility at exercise price x
- a = base (ATM) volatility
- b = skewness (tilt)
- c = kurtosis (curvature)

### Skew Dynamics

**Sticky-strike**: IV at each strike stays fixed. Not realistic.

**Floating skew**: Entire skew shifts horizontally as price moves, vertically as IV changes.

**Better approaches**:
- Express x-axis as **moneyness**: ln(X/S) or in standard deviations: `ln(X/F) / (σ × √t)`
- Express y-axis as **% of ATM IV**: e.g., 125% means 25% higher than ATM
- This normalizes across prices, times, and volatility levels

### Skewed Risk Measures (Adjusted Greeks)

The skew changes all Greeks. Example: OTM put with delta = -20. If underlying rises 1.00, normally expect -0.20 change. But in an investment skew, as the put goes further OTM, its IV rises (climbing the skew). If vega = 0.10 and IV rises 0.5%, value increases by 0.05. Net change = -0.15, giving an **adjusted delta of -15**.

### Skew Trading Strategies

**Risk Reversal** (trading skewness):
- Buy OTM puts + sell OTM calls (or vice versa) + hedge delta with underlying
- Profits from skew getting steeper or flatter
- Usually match vega (not delta) of the two options for vega-neutrality

**Dragonfly** (trading kurtosis):
- Buy strangles (OTM calls + OTM puts) if expecting kurtosis increase
- Sell strangles if expecting kurtosis decrease
- Offset vega with ATM straddles (2:1 ratio strangle:straddle if strangles have half the vega)

**Cross-month skew trades**: Buy skew in one month, sell in another. Can combine with implied volatility view.

### Implied Distributions from Butterfly Prices

The probability of the underlying being at price X at expiration equals:
```
P(X) = butterfly_price_at_X / total_butterfly_value
```

Where the butterfly is centered at X. Sum of all butterfly prices = distance between strikes.

This builds an implied probability distribution from market prices. Compare with theoretical lognormal to find disagreements → potential trading opportunities.

For stock indexes (typical findings):
- Greater probability of small-to-intermediate up moves
- Greater probability of large down moves
- Smaller probability of small-to-intermediate down moves
- Smaller probability of large up moves

---

## Chapter 25: Volatility Contracts

### Realized Volatility Contracts (Variance Swaps)

Settlement value = annualized standard deviation of log returns over contract life:
```
σ = sqrt( (252/n) × Σ [ln(pi/pi-1)]² )
```

Key conventions:
- **Population** standard deviation (divide by n, not n-1) — it's the true value, not an estimate
- **Zero mean** — uses ln(xi), not ln(xi) - μ — independent of price trend
- 252 trading days per year (exchange-specific)

**Variance swap mechanics**:
- Quoted in volatility points with notional vega
- Settled in VARIANCE points (σ²), not volatility points
- Each variance point = notional_vega / (2 × volatility_price)
- Example: Buy at vol 20, $10k vega → each variance point = $10,000/(2×20) = $250
- If realized vol = 23: profit = $250 × (23² - 20²) = $250 × 129 = $32,250

**Why variance, not volatility?**
1. Variance is proportional to time (additive across consecutive periods)
2. A position with constant variance exposure can be replicated with options
3. Variance of combined periods: σ²_total = (σ₁²×t₁ + σ₂²×t₂) / (t₁+t₂)

**Variance caps**: Limit maximum settlement value. Common for single-stock swaps where one event can cause extreme vol. Less common for broad indexes.

### Implied Volatility Contracts (VIX)

**VIX**: 30-day implied volatility of S&P 500 options, calculated by CBOE.

**Calculation methodology (post-2003)**:
- Uses prices of ALL out-of-the-money SPX options (not just ATM)
- No pricing model needed — purely derived from option prices
- Forward price determined via put-call parity
- Each option weighted by 1/X² to achieve constant variance exposure
- Two nearest expiration months bracketing 30 days, interpolated
- Uses mid (bid+ask)/2 as option price
- Only input beyond option prices: risk-free rate (T-bill)

**Original VIX (pre-2003)**: Used only ATM options on OEX, required pricing model, calculated IV from 2 nearest strikes — abandoned because it required model inputs and missed the skew.

**VIX Settlement**: Opening trade prices on expiration Wednesday (special rotation), not bid-ask mid. Can cause jumps if all options get buy or sell prints.

### VIX Characteristics

**Inverse correlation with S&P 500**: Correlation ≈ -0.74. When index falls, VIX rises; when index rises, VIX falls. The VIX changes ~5.7x faster (in percent) than the S&P 500, but in opposite direction.

**VIX as predictor**: Despite the correlation, VIX changes do NOT predict future realized volatility changes (correlation only +0.16). The VIX is driven by DEMAND for protection (fear), not by rational volatility forecasting. Hence "fear index."

**But**: Falling stock markets DO tend to be more volatile (inverse correlation -0.39 between S&P direction and realized vol).

### VIX Futures

Key characteristics:
1. **Term structure**: Usually contango (upward sloping). Occasionally backwardation (downward, during crises).
2. **Futures lag the index**: VIX futures change LESS than the index. If VIX jumps 4 points, front-month futures might move only 2.
3. **Convergence at expiration**: Futures and index must converge on expiration day.
4. **No easy index replication**: Unlike stock index futures (arbitrage via component stocks), VIX cannot be cheaply replicated → futures can persistently diverge from "fair value."

**In contango**: As time passes with no market change, futures lose value (roll down the term structure). This is the "VIX roll cost."

**Trading implications**:
- Don't expect futures to move point-for-point with the index
- Near-expiration futures respond more to index changes than far-dated
- Spreads: In contango, short-term futures decay faster than long-term (curved term structure)
- Contango → backward transition = very profitable for long VIX positions (but rare)

### VIX Options

- European, cash settled
- Each vol point = $100
- Implied volatilities reflect VIX FUTURES volatility, not VIX index volatility (because you hedge with futures)
- VIX futures are LESS volatile than the index → VIX option IVs are lower than you'd expect from index vol

**VIX option skew is unique**: "Half frown" shape.
- Lower strikes: IV drops off sharply (limited downside for VIX — can't go below ~5-10%)
- Higher strikes: IV rises then flattens (limited but non-zero chance of extreme VIX spike)
- NOT a typical smile/smirk

**Implied distribution**: Bounded on the left (VIX can't go to 0), moderately bounded on right (extreme VIX spikes are possible but unlikely to sustain).

### Replicating a Variance/VIX Position

**Variance replication**: Buy options across ALL strikes in proportion 1/X² each, then delta-hedge to expiration.
- Constant variance exposure regardless of underlying price
- But NOT constant volatility exposure (because vol = √variance)
- This is why contracts settle in variance, not volatility

**VIX replication**: Buy one strip (near-term), sell another (next-term), weighted for 30-day target. Gamma approximately offsets between strips, so minimal rehedging needed. But:
- Strips may not expire simultaneously → naked risk
- ITM options must be converted to OTM via synthetic underlying
- Practical only for professional firms

### Volatility Contract Applications

1. **Speculation**: Direct bet on realized vol (variance swap) or implied vol (VIX)
2. **Hedging gamma**: Variance swap hedges realized vol risk
3. **Hedging vega**: VIX contracts hedge implied vol risk
4. **Portfolio hedge**: VIX rises when stocks fall → long VIX offsets portfolio losses
5. **Indirect hedging**: Market makers hedge volume risk (higher vol → higher volume → higher profits) by shorting VIX
6. **Covered call hedging**: Covered call writers have short vol position → buy VIX to hedge

---

## Appendix A: Key Glossary Terms (Selected)

| Term | Definition |
|------|-----------|
| **Backspread** | Delta-neutral spread: buy more options than sold, same type/expiry |
| **Charm** | Sensitivity of delta to time passage |
| **Color** | Sensitivity of gamma to time passage |
| **Dragonfly** | Long straddle + 2 short strangles (or vice versa), same expiry |
| **Fugit** | Expected time to optimal early exercise of American option |
| **Iron Butterfly** | Long straddle + short strangle (or vice versa), straddle at midpoint |
| **Iron Condor** | Long narrow strangle + short wide strangle |
| **Pin Risk** | Risk that option expires exactly ATM — exercise unknown |
| **Speed** | Sensitivity of gamma to underlying price change |
| **Vanna** | Sensitivity of delta to volatility change |
| **Volga (Vomma)** | Sensitivity of vega to volatility change |
| **Zomma** | Sensitivity of gamma to volatility change |

---

## Appendix B: Essential Math

### Rate-of-Return Calculations

**Simple interest**: `FV = PV × (1 + r × t)`

**Compound interest**: `FV = PV × (1 + r/n)^(n×t)`

**Continuous interest**: `FV = PV × e^(r×t)`

### Volatility-Related Calculations

**Price range of n standard deviations**:
```
F × e^(±n×σ×√t)
```
Where F = forward price, σ = annual volatility, t = time in years.

**Number of standard deviations to reach exercise price X**:
```
n = ln(X/F) / (σ × √t)
```

### Normal Distribution

The standard normal distribution curve:
```
n(x) = (1/√(2π)) × e^(-x²/2)
```

In a standard normal distribution: μ = 0, σ = 1.

### Moments of a Distribution

jth moment about the mean:
```
mj = (1/n) × Σ(xi - μ)^j
```

From moments 2, 3, 4:
```
Skewness = m3 / (m2)^(3/2)
Kurtosis = m4 / (m2)² - 3     (excess kurtosis, normal = 0)
```

### Historical Volatility Formula

Annualized, zero-mean, sample standard deviation:
```
σ = sqrt( (1/(n-1)) × Σ [ln(pn/pn-1)]² ) / √t
```
Where t = time interval between observations in years.

Population vs. sample gives nearly identical results. Zero-mean vs. actual-mean also nearly identical.

---

## Key Takeaways for System Building

1. **Realized vol dominates** for positions held to expiration — track and forecast it carefully
2. **Mean reversion** is the most exploitable volatility property — build detection for vol extremes
3. **Term structure** matters: adjust vega across expirations using a whippiness model
4. **Forward volatility** = bridge between term structure and calendar spread pricing
5. **EWMA/GARCH** for volatility forecasting — EWMA is simpler, λ ≈ 0.94 standard
6. **IV tends to overstate** future realized vol — selling premium has a statistical edge under normal conditions
7. **Fat tails** are real — never assume normal distribution for risk management. Build in kurtosis awareness.
8. **Skew modeling** (polynomial fit) is essential for accurate Greeks and strategy selection
9. **VIX mechanics** matter if trading index vol: futures lag index, contango bleeds long positions
10. **Variance swaps** are the cleanest vol instrument — settle in variance because it's additive over time and replicable with options
