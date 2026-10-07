# Natenberg Part 4: Arbitrage, Hedging, Models & Position Analysis (Ch 15-21)

## Chapter 15: Option Arbitrage

### Put-Call Parity — The Core Relationship

The most important pricing relationship in options:

**For European options with the same exercise price and expiration:**

```
C - P = (F - X) / (1 + r × t)
```

Where:
- C = call price, P = put price
- F = forward price of underlying
- X = exercise price
- r = annual interest rate
- t = time to expiration in years

#### Simplified Forms

**Futures options (futures-type settlement, r effectively 0):**
```
C - P = F - X
```

**Futures options (stock-type settlement):**
```
C - P = (F - X) / (1 + r × t)
```

**Stock options (exact):**
```
C - P = S - X/(1 + r × t) - D/(1 + r × t)
```
Where S = stock price, D = dividends before expiration.

**Stock options (quick approximation):**
```
C - P ≈ S - X + X × r × t - D
```
Difference = stock price - exercise price + interest on exercise price - dividends. Accurate for short-term, low-rate options.

### Conversions and Reversals

**Conversion:** Short call + long put + long underlying (at same strike/expiry)
- Profit when synthetic (call-put) is overpriced vs. underlying
- Has negative rho (wants rates to fall) in stock options
- Has positive dividend exposure

**Reverse conversion (reversal):** Long call + short put + short underlying
- Profit when synthetic is underpriced vs. underlying
- Has positive rho (wants rates to rise)
- Has negative dividend exposure

### Arbitrage Risks

1. **Execution risk**: Rarely can execute all legs simultaneously. Must leg in.
2. **Pin risk**: At expiration, if underlying = exercise price, unknown whether short option will be assigned. Can result in unwanted directional exposure. Solution: reduce position size near expiration if underlying is near strike. Cash-settled options have NO pin risk.
3. **Settlement risk**: When options and underlying have different settlement procedures (stock-type vs futures-type). Variation on futures creates cash flow that options don't offset, causing interest gain/loss.
4. **Interest rate risk**: Conversions hurt by rising rates (carrying cost increases). Reversals hurt by falling rates.
5. **Dividend risk**: Conversions helped by rising dividends (own stock). Reversals hurt.

### Boxes

**Box = conversion at one strike + reversal at different strike** (underlying positions cancel)

Example: Long 90/100 box = synthetic long at 90 + synthetic short at 100

```
Box value = (X_high - X_low) / (1 + r × t)     [stock-type settlement]
Box value = X_high - X_low                       [futures-type settlement]
```

A box is also = bull call spread + bear put spread at same strikes.

**Key use:** If you know the call spread price, you can derive the put spread price:
```
Put spread = Box value - Call spread
```

Boxes are essentially lending/borrowing transactions. Selling a box = borrowing money at implied rate.

### Rolls (Jelly Rolls)

**Roll = conversion in one month + reversal in different month** (underlying cancels, same strike)

```
Roll value ≈ X × r × t_between - D_between
```
Where t_between = time between expirations, D_between = dividends between expirations.

Also = long call calendar spread - short put calendar spread. If roll is positive (interest > dividends), call calendar > put calendar.

### Time Boxes (Diagonal Rolls)

Different exercise prices AND different months. Value = difference between discounted exercise prices less dividends.

### Synthetic Strategy Optimization

Before executing any multi-leg strategy, check if doing part synthetically is cheaper. Compare:
1. Outright strategy (e.g., buy straddle: buy call + buy put)
2. Synthetic variants (e.g., buy 2 calls + sell underlying)
3. Iron equivalent (e.g., sell iron butterfly instead of buy butterfly)

Even without arbitrage opportunities, the bid-ask structure often makes one execution path 0.05-0.10 cheaper.

---

## Chapter 16: Early Exercise of American Options

### When American > European

An American option has value ≥ European option. The difference = early exercise premium. If no dividends and no interest advantage, American = European.

### Lower Arbitrage Boundaries

**American option:** Never less than intrinsic value.
```
American call ≥ max[0, S - X]
American put  ≥ max[0, X - S]
```

**European option:** Can be less than intrinsic value.
```
European call ≥ max[0, (F - X)/(1 + r × t)]
European put  ≥ max[0, (X - F)/(1 + r × t)]
```

**Combined (American is at least as high as European):**
```
American call ≥ max[0, S - X, (F - X)/(1 + r × t)]
American put  ≥ max[0, X - S, (X - F)/(1 + r × t)]
```

### Upper Arbitrage Boundaries

```
American put  ≤ X
European put  ≤ X/(1 + r × t)
American call ≤ S (stock)
European call on stock ≤ S - D (ignoring interest on dividends)
```

### Early Exercise of Calls on Stock

**Call value components:**
```
Call value = intrinsic value + volatility value + interest value - dividend value
```

**Early exercise condition:**
```
Dividend value > volatility value + interest value
```

Where:
- Dividend value = total dividends over option life
- Interest value ≈ X × r × t (cost of carrying exercise price)
- Volatility value ≈ price of companion out-of-the-money put

**Critical rule: Only exercise calls the day BEFORE the ex-dividend date.** No other day is optimal. If no dividend, never exercise a call early.

### Early Exercise of Puts on Stock

**Put value components:**
```
Put value = intrinsic value + volatility value - interest value + dividend value
```

**Early exercise condition:**
```
Interest value > volatility value + dividend value
```

Where:
- Interest value = X × r × t (interest earned on exercise price)
- Volatility value ≈ price of companion out-of-the-money call
- Dividend value = expected dividends

**Unlike calls, puts can be exercised on ANY day** (not just around dividends). Common exercise day is the ex-dividend date itself.

**Blackout period** (never exercise during this window):
```
Blackout days = Dividend / (daily interest on exercise price)
```
Example: Dividend = 0.40, daily interest on X=120 at 6% = 0.02 → blackout = 20 days before dividend.

### Early Exercise of Options on Futures

Only relevant when options have stock-type settlement (US exchanges). Condition:
```
Interest on intrinsic value > volatility value
```

For immediate exercise, one day's interest must exceed one day's theta of the companion OTM option.

**Fugit:** Number of days until an option becomes an immediate early exercise candidate.

### Pricing American Options

**Cox-Ross-Rubinstein (binomial) model:** Loop-based, easy to understand, handles dividends well but slower.

**Barone-Adesi-Whaley (quadratic) model:** Faster convergence but treats all cash flows as continuous interest, so less accurate for discrete dividends.

An American option is optimally exercised when its theoretical value = parity and delta = 100.

### Impact on Synthetics

For American options, call delta + |put delta| > 100 (unlike European where they = 100). This means conversions/reversals/boxes may not be truly delta neutral with American options.

---

## Chapter 17: Hedging with Options

### Protective Calls and Puts

**Protective put (long underlying + long put):** = synthetic long call
- Limited downside (floor at strike), unlimited upside
- Cost = put premium (the "insurance premium")
- Lower strike = less protection, cheaper

**Protective call (short underlying + long call):** = synthetic long put
- Limited upside risk (cap at strike), unlimited downside profit
- Cost = call premium

**Caps and floors:** Interest-rate versions of protective calls/puts.

### Covered Writes

**Covered call (long underlying + short call):** = synthetic short put
- Limited upside (capped at strike), unlimited downside
- Generates immediate credit for partial protection
- In-the-money call = more protection, less upside
- At-the-money call = most time premium, best if market stays flat
- Out-of-the-money call = less protection, more upside

**Covered put (short underlying + short put):** = synthetic short call

**Buy/write:** Simultaneous purchase of stock + sale of call. Quoted as single price (stock price - call price).

**CBOE BXM Index:** Tracks performance of S&P 500 buy-write strategy.

**Cash-secured put:** Selling puts to set target buy price. Requires cash deposit = exercise price (or PV of exercise price for European options).

### Choosing: Protective vs. Covered

- **Implied volatility high** → sell covered options (collect overpriced premium)
- **Implied volatility low** → buy protective options (cheap insurance)

### Collars

**Long collar:** Long underlying + long put (lower strike) + short call (higher strike) = bull vertical spread
**Short collar:** Short underlying + long call (higher strike) + short put (lower strike) = bear vertical spread

**Zero-cost collar:** When put premium = call premium. Limited risk, limited reward, no net cost.

Greeks of a collar:
- Always has positive delta (long collar) or negative delta (short collar)
- Gamma/theta/vega depend on which option is closer to ATM
- If underlying closer to protective option: +gamma, -theta, +vega
- If underlying closer to covered option: -gamma, +theta, -vega

### Complex Hedging Strategies

**High implied volatility environment:** Buy few options, sell many → ratio writes, sell ATM options
**Low implied volatility environment:** Buy many options, sell few → buy calendar spreads

**Delta-based hedge sizing:** To hedge X% of directional risk, use options with total delta = X% of underlying.

### Hedging to Reduce Volatility (Sharpe Ratio)

**Critical insight:** Higher average returns don't guarantee better total returns. Volatility drag reduces compounding.

Example over 5 years:
- Portfolio 1: avg +9%, std dev low → total +44.29%
- Portfolio 3: avg +12%, std dev high → total +33.20%

Lower volatility portfolio beats higher-return-but-volatile portfolio due to compounding.

**Sharpe ratio = Average return / Standard deviation of returns**
Higher Sharpe = better risk-adjusted returns.

### Portfolio Insurance (Option Replication)

Replicate a protective put via dynamic hedging when no listed option exists:
1. Calculate desired option's delta using BS model
2. Hold delta% of the underlying position
3. Periodically recalculate delta, buy/sell underlying to match

**Failed spectacularly in 1987 crash** because:
- Volatility input was wrong (realized vol exploded)
- Dynamic hedging assumptions (continuous trading) broke down
- Cascading sales of index futures worsened the crash

---

## Chapter 18: The Black-Scholes Model

### The Black-Scholes Equation

The partial differential equation that all option prices must satisfy:
```
½σ²S² × C_SS + rS × C_S - rC + C_t = 0
```

Where C_S = delta (∂C/∂S), C_SS = gamma (∂²C/∂S²), C_t = theta (∂C/∂t).

**Key insight:** Only S (stock price) and t (time) are variables. σ (volatility) and r (interest rate) are constant inputs.

### The Black-Scholes Model (Solution)

For a European call on non-dividend-paying stock:
```
C = S × N(d1) - X × e^(-rt) × N(d2)
```

For a European put:
```
P = X × e^(-rt) × N(-d2) - S × N(-d1)
```

Where:
```
d1 = [ln(S/X) + (r + σ²/2) × t] / (σ√t)
d2 = d1 - σ√t
```

Variables:
- S = stock price (spot)
- X = exercise price
- t = time to expiration (years)
- σ = annualized volatility (standard deviation)
- r = risk-free interest rate (continuous compounding)
- N(x) = cumulative standard normal distribution function
- ln = natural logarithm
- e = exponential function

### Understanding d1 and d2

**d1** locates the exercise price relative to the MEAN of the lognormal distribution, measured in standard deviations. N(d1) gives the average value of all stock above the exercise price, normalized.

**d2** locates the exercise price relative to the MEDIAN of the lognormal distribution. N(d2) = probability that the option finishes in the money (probability of exercise).

The difference: d1 - d2 = σ√t (the mean-median gap in a lognormal distribution).

### What Each Term Means

```
C = S × N(d1) - X × e^(-rt) × N(d2)
```

- **S × N(d1):** Present value of expected stock receipt. "If exercised, what stock value do I expect to receive?"
- **X × e^(-rt) × N(d2):** Present value of expected payment. "What's the probability I pay X, discounted to today?"

The call value = expected receipt - expected payment.

### Extended Model for Different Underlyings

Adjustment factor b varies by underlying:
- Stock (no dividend): b = r
- Stock (continuous dividend yield q): b = r - q
- Futures (futures-type settlement): b = 0
- Foreign currency: b = r - r_f (domestic - foreign rate)

General form uses Se^((b-r)t) instead of S.

### The 40% Rule (Quick Approximation)

For an exactly at-the-forward European option:
```
Expected value ≈ 0.00399 × X × σ × √t
```
Or equivalently: **≈ 40% of one standard deviation** where 1 std dev = F × σ × √t.

Examples:
- 100 call, σ=20%, t=1 year → value ≈ 20 × 100 × 0.00399 = 7.98
- 65 call, σ=18%, t=3 months → expected value ≈ 18 × 65 × 0.00399 × √0.25 = 2.33

Theoretical value = expected value / (1 + r × t).

Works for both calls and puts at-the-forward (they have equal value by put-call parity).

### Delta from Black-Scholes

Delta = N(d1) for calls. This is NOT the same as probability of finishing ITM (which is N(d2)). N(d1) > N(d2) always.

**At-the-forward straddle:** Always has slightly positive delta. Exactly delta-neutral when:
```
S = X × e^(-(r + σ²/2) × t)
```
This price is BELOW the exercise price.

### Theta Components

Theta has three parts:
1. **Volatility decay** (always works against long options): dominant term
2. **Spot-to-forward adjustment**: (b-r) × S × e^((b-r)t) × N(d1)
3. **Present value change**: r × X × e^(-rt) × N(d2)

**Driftless theta** (when r=0 or futures-type settlement): only the volatility decay component.

### Maximum Gamma, Theta, Vega

Not exactly at the exercise price:
- **Max gamma and theta:** occur at slightly ABOVE X (when b=0)
- **Max vega:** occurs at slightly BELOW X
- At b=0, max gamma and max theta occur at the SAME underlying price
- Raising interest rates shifts max gamma/vega lower, max theta higher

**Vega and time:** For stock options with r > 0, vega can DECREASE with more time at certain points. At r=10%, this happens beyond ~33 months to expiration.

---

## Chapter 19: Binomial Option Pricing

### Risk-Neutral Pricing

In a risk-neutral world, investors are indifferent to risk. The probability of an up move p is chosen so the expected value = current price.

**One-period tree:**
```
p = (1 - d) / (u - d)          [no interest]
p = (1 + r×t/n - d) / (u - d)  [with interest, for stock]
```

Where u = up multiplier, d = down multiplier, n = number of periods.

### Building the Tree

Standard recombining tree with u × d = 1:
```
u = e^(σ√(t/n))    (one standard deviation up)
d = 1/u = e^(-σ√(t/n))
```

Terminal prices: S × u^j × d^(n-j) for j = 0, 1, ..., n

Number of paths to each terminal price = binomial coefficient C(n,j).

### Valuing European Options

```
Call = [1/(1+r×t/n)^n] × Σ C(n,j) × p^j × (1-p)^(n-j) × max[S×u^j×d^(n-j) - X, 0]
```

Work backwards through the tree:
```
C(i,j) = [p × C(i+1, j+1) + (1-p) × C(i+1, j)] / (1 + r×t/n)
```

### Greeks from the Binomial Tree

**Delta:** (C_up - C_down) / (S_up - S_down)

**Gamma:** (Δ_up - Δ_down) / (S_up - S_down) — requires going two levels deep.

**Theta:** (C(2,1) - C(0,0)) / (2 × t/n) — change in value over two periods with no price change.

**Vega and Rho:** Cannot be calculated directly from the tree. Must re-run with changed σ or r.

### Three-Period Example

S=100, t=0.75yr, r=4%, u=1.05, d=0.9524 → σ ≈ 9.76%

p = 0.59, (1-p) = 0.41

European 100 call = 5.22, European 100 put = 2.28

Put-call parity check: F = 100 × 1.01^3 = 103.03 → (F-X)/(1+r×t) = 2.94 = C-P ✓

### Gamma Rent

**The breakeven movement = one standard deviation per time period.**

A positive gamma position (long options) loses theta but gains from movement. To break even, the underlying must move by exactly one standard deviation in each time interval. This is the "rent" you pay for gamma.

### Pricing American Options

At each node, compare European value vs. intrinsic value. If intrinsic > European, replace with intrinsic value and work backwards.

**Example:** European 100 put at node P(2,0) = 8.31, but intrinsic = 9.30 → replace with 9.30. This changes the final American put value from 2.28 to 2.64 (+0.36 early exercise premium).

American options have different delta and gamma than European equivalents because early exercise changes the path values.

### Dividends in Binomial Trees

Discrete dividends cause the tree to stop recombining after the dividend date (each branch spawns a new sub-tree). Workaround: reduce all post-dividend stock prices by the dividend amount (approximate but keeps the tree manageable).

### Convergence to Black-Scholes

As periods → ∞, binomial value → Black-Scholes value. Error oscillates between positive and negative, decreasing with more periods. Practical choice: 50-100 periods. Half-step averaging (average of n and n+1 period values) dramatically improves accuracy.

**Pseudoprobabilities:** p and (1-p) can fall outside [0,1] if interest rate is very high relative to volatility. This means stock can't keep up with risk-free rate. Fix: increase u (higher volatility) so u > 1 + r×t/n.

---

## Chapter 20: Volatility Revisited

### The Fundamental Principle

**The longer a position is held, the more important realized volatility becomes and the less important implied volatility is. At expiration, only realized volatility matters.**

Example: Buy 100 straddle at IV=20% (price=6.25).
- IV rises to 22% immediately → profit +0.62
- IV rises to 22% over 3 weeks → loss -0.82 (theta dominates)
- IV falls to 18%, but underlying moves to 105 → profit +0.84 (gamma wins)

### Historical Volatility Calculation Methods

**1. Close-to-close (standard):**
```
σ = √[(1/(n-1)) × Σ(x_i - μ)²] × √(trading_days_per_year)
```
Where x_i = ln(P_i/P_{i-1}). Most use zero-mean assumption (μ=0). Typically 252 trading days/year.

**2. Parkinson (high-low, extreme value):**
```
σ = √[(1/(4n×ln2)) × Σ(ln(h_i/l_i))²] × √(1/t)
```
More accurate when trading is continuous. Uses intraday range.

**3. Garman-Klass (open-high-low-close):**
```
σ = √[(1/n) × Σ(0.5×(ln(h_i/l_i))² - (2ln2-1)×(ln(c_i/o_i))²)] × √(1/t)
```
Best when market trades continuously. For markets open only part of day, weight Garman-Klass and close-to-close estimates.

### Key Volatility Characteristics

1. **Serial correlation:** Tomorrow's volatility likely resembles today's. Short-term vol is sticky.

2. **Mean reversion:** Volatility always returns to a long-term average. Unlike price, which can trend indefinitely, volatility oscillates around a mean. Examples:
   - S&P 500 mean: ~15-20%
   - Gold mean: ~10-20%
   - Bund mean: ~5%

3. **Term structure convergence:** Over longer measurement periods, min and max realized volatilities converge to the mean. Easier to predict long-term vol than short-term vol (but long-term options have higher vega, amplifying errors).

4. **Trending:** Volatility shows trends within its mean-reverting behavior. Technical analysis principles can apply to vol charts (with modification).

### Volatility Forecasting Methods

**Weighted averaging approach:**
- Weight historical volatilities by relevance to target period
- More recent data gets more weight (unless forecasting long-term)
- For short-term options: weight short-term historical vol highest
- For long-term options: weight long-term vol highest (mean reversion)

Example for 5-month options:
```
(15% × 6wk) + (25% × 12wk) + (35% × 26wk) + (25% × 52wk)
```
Give most weight to 26-week vol (closest to 5 months).

**EWMA (Exponentially Weighted Moving Average):**
```
σ² = Σ α_i × r_i²
```
Where α_i = (1-λ) × λ^(n-i), and λ ≈ 0.94. More recent returns get exponentially more weight.

**GARCH (Generalized Autoregressive Conditional Heteroskedasticity):**
Three components: EWMA + serial correlation + mean reversion. Most sophisticated but beyond scope. Widely used in quantitative finance.

### Implied Volatility as a Predictor

Key finding: **Implied volatility is an imperfect predictor.** Generally:
- IV tends to OVERPREDICT future realized vol (options are usually overpriced)
- In calm markets, IV overpredicts by up to 10 percentage points
- In crises (2008), IV dramatically underpredicts

**Why options tend to be overpriced:**
1. Buyers pay insurance premium for tail risk protection
2. Market makers' replication costs passed to customers
3. Model weaknesses inflate implied values

### Term Structure of Implied Volatility

**Mean reversion drives term structure shape:**
- If current IV > mean → downward sloping (short-term high, long-term closer to mean)
- If current IV < mean → upward sloping (short-term low, long-term closer to mean)
- If current IV = mean → flat

**Implications for multi-month positions:**
Don't assume all months change IV by the same amount. Short-term IV moves more than long-term.

Example: If April IV rises 3%, June rises ~2%, August rises ~1.5%, October rises ~1.1%.

**Adjusted vega calculation:**
```
Total IV risk = Σ (vega_month × IV_change_factor_month)
```
A position that looks vega-neutral with uniform IV shifts can actually have significant risk under realistic term-structure shifts.

**Whippiness factor:** How fast IV changes in distant months relative to the primary month. Must be estimated from historical behavior.

### Forward Volatility

Analogous to forward interest rates. Given two implied vols at different expirations:
```
σ_f = √[(σ₂² × t₂ - σ₁² × t₁) / (t₂ - t₁)]
```

**Used to identify mispriced calendar spreads.** Calculate forward vol between each pair of months → compare to model's best-fit line → deviations suggest mispriced months.

**Calendar spread implied volatility:** The single volatility that makes the spread value equal to its market price. If it deviates from the forward vol curve, the spread may be mispriced.

Quick estimate: Spread implied vol ≈ spread price / spread vega.

### Seasonal Volatility

Some markets have predictable seasonal vol patterns (e.g., natural gas October options trade at persistently higher IV due to hurricane season). Term-structure models must account for this.

---

## Chapter 21: Position Analysis

### Analyzing Complex Positions

**Step 1:** Use synthetic relationships to rewrite the position in recognizable form (all calls or all puts). Sometimes a complex position is just a butterfly or spread in disguise.

**Step 2:** Calculate initial risk sensitivities (delta, gamma, theta, vega).

**Step 3:** Consider how Greeks change with market moves:
- Gamma is greatest for ATM options → as underlying moves toward an option's strike, that option's gamma increases
- Delta, gamma, theta, vega all change as time passes and volatility shifts
- Rising volatility → all deltas move toward 50
- Falling volatility / time passing → deltas move away from 50

### Net Contract Position

Critical check for extreme moves:
- **Upside contract position:** Sum of all calls + underlying. If market rises dramatically, all calls act like underlying.
- **Downside contract position:** Sum of all puts + underlying (puts count as negative). If market falls dramatically, all puts act like short underlying.

This tells you what you're left with in a crash or melt-up scenario.

### Breakeven Volatility of a Position

```
Breakeven vol ≈ current vol + (theoretical edge / total vega)
```

If you have +6.00 edge, vega = -0.759, current vol = 27%:
```
Breakeven = 27 + 6.00/0.759 = 34.9%
```
Position profitable as long as realized vol < 34.9%. This is the "implied volatility of the entire position."

### Margin for Error

Increase by either: (a) increasing theoretical edge without increasing vega, or (b) reducing vega without reducing edge.

### Position Value Graphs

**Delta interpretation:**
- Negative delta: graph slopes upper-left to lower-right
- Positive delta: graph slopes lower-left to upper-right

**Gamma interpretation:**
- Negative gamma: graph curves downward (frown) — movement hurts
- Positive gamma: graph curves upward (smile) — movement helps

### Optimal Price Target for Negative Gamma Positions

A negative gamma position's profit is maximized when it reaches delta-neutral:
```
Optimal underlying ≈ current price - (current delta / gamma)
```
Approximate because gamma changes as price moves.

### Risk Analysis Framework

Three questions every trader must answer:
1. **What if conditions move against me?** (Plan defensive action)
2. **What if conditions move in my favor?** (Plan to capture gains)
3. **What can I do NOW to prevent future adverse scenarios?**

### Market Making

**Three questions for a market maker:**
1. What does the marketplace think the option is worth? (equilibrium price for bid-ask trading)
2. What do I think it's worth? (theoretical value for edge capture)
3. What positions am I carrying? (risk management)

**Adjusting quotes based on risk:**
- Want to buy options (reduce negative gamma)? Raise both bid and offer.
- Want to sell options (reduce positive gamma)? Lower both bid and offer.

**Key principle:** Diversify risk across exercise prices and expirations. Concentrated gamma at one strike is dangerous — it amplifies as underlying approaches that strike.

### Stock Splits

For Y-for-X split:
- New stock price = old price × X/Y
- Exercise prices = old strike × X/Y
- Number of contracts = old contracts × Y/X
- New delta position = old delta × Y/X
- New gamma position = old gamma × (Y/X)²
- Theta, vega, rho: UNCHANGED

If Y is not a whole number (e.g., 3-for-2), underlying contract size adjusts: new size = old size × Y/X.
