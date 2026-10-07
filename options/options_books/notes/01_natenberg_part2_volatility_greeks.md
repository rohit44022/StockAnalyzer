# Natenberg — Part 2: Volatility, Greeks, Dynamic Hedging & Risk Measurement II

## Chapter 6: Volatility

### Core Concept
Volatility = speed of the market. Low-vol markets move slowly; high-vol markets move quickly. It's the most important and hardest-to-observe input into any option pricing model.

### Random Walks & Normal Distributions
- Price movement modeled as a **random walk** (pinball/Galton board analogy)
- Many random outcomes → **bell-shaped / normal distribution**
- Normal distribution is symmetrical, peak at center, tails extend infinitely
- Fully described by just two numbers: **mean** and **standard deviation**

### Standard Deviation Rules (critical for trading)
- **±1 SD** ≈ **68.3%** of all occurrences (~2/3)
- **±2 SD** ≈ **95.4%** of all occurrences (~19/20)
- **±3 SD** ≈ **99.7%** of all occurrences (~369/370)
- Standard deviations are **additive**: 2 SD = 2 × 1 SD

### Volatility Definition
**Volatility = annualized one standard deviation price change, in percent.**

Example: Contract at 100, volatility 20%:
- 68% chance of being between **80–120** after 1 year (100 ± 20%)
- 95% chance of being between **60–140** (100 ± 2×20%)
- 99.7% chance of being between **40–160** (100 ± 3×20%)

### Forward Price as the Mean
- The distribution is centered around the **forward price**, not the current price
- Forward price = current price adjusted for carry (interest, dividends, storage)
- Black-Scholes variants differ primarily in how they calculate the forward price

### Scaling Volatility for Time
**Volatility is proportional to the SQUARE ROOT of time** (not linear like interest rates).

Key formulas:
```
Daily σ  = Annual σ / √256 = Annual σ / 16
Weekly σ = Annual σ / √52  = Annual σ / 7.2
```

Example: Stock at $45, annual vol 37%:
- Daily 1-SD: 37%/16 = 2.31% → $1.04
- Weekly 1-SD: 37%/7.2 = 5.14% → $2.31
- Expect price change > 1 SD about 1 day in 3
- Expect price change > 2 SD about 1 day in 20 (~once per month)

### Practical Volatility Check
Given observed daily price changes, check if they're consistent with assumed volatility:
- Calculate expected 1-SD daily move
- Count how many days exceed it (should be ~1 in 3)
- If actual moves are consistently smaller/larger → wrong volatility assumption

### Lognormal Distribution (Black-Scholes assumption)
Normal distribution has a flaw: allows negative prices. Solution: **lognormal distribution**.

- Based on continuously compounded returns: `price = S × e^(σ)`
- Upside moves > downside moves in absolute terms (e^+0.12 = 1.1275, e^-0.12 = 0.8869)
- Distribution is **skewed right** — bounded by zero on downside, open-ended on upside
- Mean is to the RIGHT of the peak (mode)
- Consequence: OTM call always worth more than equally-OTM put (e.g., 110 call > 90 put with forward at 100)

### Three Types of Volatility

#### 1. Realized (Historical) Volatility
- Annualized standard deviation of percent price changes over a past period
- Must specify: interval (daily/weekly/monthly) AND lookback window (50-day, 52-week, etc.)
- Different intervals over same period give similar results
- Calculated from **settlement-to-settlement** price changes (not high/low or open/close)
- **Future realized volatility** = what we want to know (impossible)
- **Historical realized volatility** = starting point for estimating future vol

#### 2. Implied Volatility
- Derived from option's market price by running pricing model backwards
- "What volatility makes the model output equal the market price?"
- Represents **market consensus** of future realized vol over option's life
- Depends on the pricing model used AND contemporaneous inputs
- Used to compare relative pricing of options (more useful than absolute price)
- Traders say "bought at 27.51%" meaning the implied vol at trade price

#### 3. Forecast Volatility
- Statistical models attempting to predict future realized vol
- Used as additional input alongside historical data

### Key Volatility–Option Value Relationships
1. **In total points**: vol change affects **ATM options most**
2. **In percent terms**: vol change affects **OTM options most**
3. **Long-term options** are more sensitive to vol changes than short-term options
4. Calls and puts at same strike/expiry have very similar implied vols (put-call parity)
5. In-the-money options are **least sensitive** to vol changes

### Trading Implications
- **Implied vol > expected future realized vol** → sell options
- **Implied vol < expected future realized vol** → buy options
- Always compare implied vol to historical vol range — if historical range is 10-30%, a guess of 5% or 40% is unreasonable
- Need **margin for error** — strategy that loses on 2% vol miss is too fragile

---

## Chapter 7: Risk Measurement I — The Greeks

### Effect of Market Changes on Option Values (summary table)

| Change | Calls | Puts |
|--------|-------|------|
| Underlying ↑ | ↑ | ↓ |
| Volatility ↑ | ↑ | ↑ |
| Time passes | ↓ | ↓ |
| Interest ↑ (stock opts) | ↑ (call), ↓ (put) | ↓ |
| Dividend ↑ | ↓ | ↑ |

### Delta (Δ) — Directional Risk

**Definition**: Rate of change in option value per unit change in underlying price.

- Calls: delta ranges **0 to +100** (or 0 to +1.00)
- Puts: delta ranges **–100 to 0** (or –1.00 to 0)
- Underlying contract: always delta = **100**

#### Four Interpretations:
1. **Rate of change**: A 40-delta call gains 0.40 for each 1.00 move in underlying
2. **Hedge ratio**: 100/delta = ratio of options to underlying for delta-neutral hedge. Delta-50 call → 2:1 (2 calls per 1 underlying)
3. **Equivalent underlying position**: Each 100 deltas ≈ 1 underlying contract. 500 deltas = long 5 futures or 500 shares
4. **Probability approximation**: |delta| ≈ probability of finishing ITM. Delta-25 ≈ 25% chance ITM. ATM options ≈ delta 50

#### Delta-Neutral Hedging
- Sum of all deltas in position = 0 → **delta neutral**
- Buy 2 calls (delta 50 each) + sell 1 underlying: (2×50) – 100 = 0
- Delta neutral = no directional bias (for small price changes)

### Gamma (Γ) — Curvature / Rate of Delta Change

**Definition**: Change in delta per 1-point move in underlying.

- Always **positive** for both calls and puts (long options = long gamma)
- Buying options → positive gamma; selling options → negative gamma
- For each point up: new delta = old delta + gamma
- For each point down: new delta = old delta – gamma

#### Using Gamma to Estimate New Option Value:
```
New value ≈ C + (ΔS × Δ) + (ΔS² × Γ/2)
```
Where ΔS = price change in underlying.

Example: Call at 3.65, delta 40, gamma 2.5, underlying moves +4.00:
- New delta: 40 + (4 × 2.5) = 50
- Average delta: (40+50)/2 = 45
- New value: 3.65 + (4.00 × 0.45) = **5.45**

### Theta (Θ) — Time Decay

**Definition**: Value lost per day, assuming no other changes.

- Almost always **negative** (options lose value over time)
- Expressed as negative number: theta –0.05 means lose $0.05/day
- **ATM options** have the highest theta
- ATM theta **increases** as expiration approaches (accelerating decay)
- Exception: deeply ITM European options with stock-type settlement can have **positive theta** (negative time value)

### Vega (V or K) — Volatility Sensitivity

**Definition**: Change in theoretical value per 1 percentage point change in volatility.

- Always **positive** for both calls and puts
- If vega = 0.15: +1% vol → +0.15 value, –1% vol → –0.15 value
- "Vega" is trader convention (not actually Greek); academic term is kappa (K)

### Rho (P) — Interest Rate Sensitivity

**Definition**: Change in theoretical value per 1% change in interest rate.

- **Stock options**: calls have positive rho, puts have negative rho
- **Futures options** (stock-type settlement): both calls and puts have negative rho
- **Futures options** (futures-type settlement): rho = 0 (no cash flow)
- Usually the **least important** Greek — most traders ignore it

### Properties of Underlying Contract's Greeks:
- Delta = 100 (always)
- Gamma = 0, Theta = 0, Vega = 0, Rho = 0

### Critical Principle: Gamma and Theta Are Opposite Signs
- **Positive gamma** → negative theta (movement helps, time hurts)
- **Negative gamma** → positive theta (stillness helps, time helps)
- Magnitudes correlate: large gamma ↔ large theta (opposite sign)
- **You cannot have both** — either movement or time works for you, not both

### Risk Interpretation Summary

| Greek | Positive means... | Negative means... |
|-------|-------------------|-------------------|
| Delta | Want market up | Want market down |
| Gamma | Want big/fast moves (any direction) | Want market to sit still / move slowly |
| Theta | Profit from time passing | Lose from time passing |
| Vega | Want implied vol to rise | Want implied vol to fall |

### Gamma vs Vega Distinction
- **Gamma** = do you want higher/lower **realized** volatility? (actual underlying movement)
- **Vega** = do you want higher/lower **implied** volatility? (option market pricing)
- These often correlate but NOT always — underlying can be volatile while IV falls, or calm while IV rises

### Position Implied Volatility (Breakeven Vol)
```
Position IV ≈ vol_used + (total_edge / total_vega)
```
Example: Edge +2.20, vega –1.70, vol used 25% → breakeven vol ≈ 25 + 2.20/1.70 = **26.29%**

---

## Chapter 8: Dynamic Hedging

### The Core Process
To capture theoretical mispricing, you must:
1. Take a position in the mispriced option
2. Delta-hedge with the underlying
3. **Continuously readjust** the hedge over the option's life (dynamic hedging)

### Detailed Example — Stock Option
- Stock = $97.70, June 100 call theoretical value = 5.89, market price = 5.00
- Implied vol = 32.40%, true future vol = 37.62%
- Delta = 50 → buy 100 calls, sell 50 shares
- Each week: recalculate delta, buy/sell shares to return to delta-neutral
- At expiration: close everything (exercise ITM options, liquidate shares)

### Why It Works — "Buying Low, Selling High"
When price rises → positive delta → forced to sell underlying (sell high)
When price falls → negative delta → forced to buy underlying (buy low)
The cumulative profit from these adjustments = option's theoretical value

### P&L Components:
1. Original hedge P&L (options + initial underlying)
2. Adjustment P&L (the dynamic rehedging trades)
3. Interest on option position (cost of carrying)
4. Interest on stock/underlying position
5. Interest on adjustment cash flows
6. Dividends (if any)

### Key Principle:
> **Option theoretical value = sum of all small profits from rehedging (the "unhedged amounts" captured at each adjustment)**

### Rehedging Frequency
- Models assume continuous rehedging → impossible in practice
- More frequent adjustments → results closer to theoretical prediction
- Less frequent → more variance but same expected value
- **Two approaches**: (a) rehedge at regular intervals (daily, weekly), or (b) rehedge when delta drifts beyond a threshold (e.g., ±500 deltas)
- Transaction costs limit practical frequency

### Implied Vol as Breakeven Vol
- The implied vol at trade price = the realized vol at which the hedge breaks even
- Above breakeven vol → option buyer profits
- Below breakeven vol → option seller profits

### Early Exit via IV Reevaluation
If implied vol moves to match your vol estimate after trade entry, you can close immediately for the full theoretical profit — no need to hold to expiration. But this isn't guaranteed.

### Adverse IV Moves
If IV moves against you (e.g., you bought calls and IV drops), you show a paper loss. But if your vol estimate is correct, holding and adjusting will still capture the theoretical profit by expiration.

### Frictionless Market Assumptions (violated in reality):
1. Can freely buy/sell underlying (short-selling restrictions exist)
2. Single constant interest rate (borrowing ≠ lending rate)
3. Zero transaction costs (commissions, fees, bid-ask spreads)
4. No tax consequences

### Professional vs. Retail
- Professionals: low transaction costs → adjust frequently → results track theory closely
- Retail: higher costs → adjust less → more variance but same expected value long-term
- Retail occasionally gets bigger wins AND bigger losses than professionals

---

## Chapter 9: Risk Measurement II — Higher-Order Sensitivities

### How Delta Changes

#### Delta vs. Volatility
- As vol ↑: OTM deltas move toward 50, ITM deltas move toward 50
- As vol ↓: deltas move away from 50 (toward 0 or 100)
- ATM delta stays near 50 regardless of vol (slightly above 50 due to lognormal skew)
- **Implied delta**: using implied vol to calculate delta (changes as IV changes)

#### Delta vs. Time
- Same effect as volatility: more time → deltas toward 50; less time → deltas away from 50
- Time and volatility have similar effects on most option sensitivities

### Higher-Order Greeks (Named Sensitivities)

| Name | Definition | Key Behavior |
|------|-----------|--------------|
| **Vanna** | Sensitivity of delta to vol change (= sensitivity of vega to underlying change) | Greatest for deltas ~20 and ~80; near zero for ATM |
| **Charm** (delta decay) | Sensitivity of delta to time passage | Same shape as vanna; increases as expiration nears |
| **Volga** (vomma) | Sensitivity of vega to vol change (volatility gamma) | Near zero for ATM; greatest for deltas ~10 and ~90 |
| **Speed** | Sensitivity of gamma to underlying price change | Greatest for deltas ~15 and ~85 |
| **Color** | Sensitivity of gamma to time passage | Greatest for ATM; gamma of ATM rises as time passes |
| **Zomma** | Sensitivity of gamma to vol change | Same shape as color; greatest for ATM |
| **Vega decay** (DvegaDtime) | Sensitivity of vega to time passage | Vega always falls as time passes |

### Theta Deep Dive
- **ATM theta is greatest** and accelerates toward expiration (approaches infinity at expiry)
- ITM and OTM theta decelerate near expiration
- ATM theta is **directly proportional to volatility** (double vol → double theta)
- ATM theta is **proportional to exercise price** (higher strike → higher theta)
- Theta estimation for ATM option: `theta ≈ TV × (1 - √((t-1)/t))`

### Vega Deep Dive
- Greatest for ATM options
- ATM vega is **proportional to exercise price** (100-strike vega = 2× 50-strike vega)
- ATM vega is **relatively constant** across different vol levels
- ITM and OTM vega **rises** with higher vol (options act more "at-the-money")
- Vega always **rises** with more time to expiry and **falls** as time passes
- Long-term options always more vol-sensitive than short-term options

### Gamma Deep Dive
- **Greatest for ATM** (like theta and vega)
- ATM gamma is **inversely proportional to exercise price** (opposite of theta/vega!)
- ATM gamma **rises** as time passes or vol declines (short-dated ATM = highest gamma risk)
- ITM/OTM gamma rises with higher vol (more "ATM-like")
- **Key danger zone**: ATM options near expiry in low-vol environment = extreme gamma, rapid delta swings

### Lambda (Λ) — Leverage / Elasticity
```
Λ = delta × (underlying_price / option_value)
```
- Measures percentage option change per percentage underlying change
- Greatest for OTM options near expiration in low-vol environment
- Maximum leverage = maximum risk (and highest bid-ask impact)

### Critical Trading Rules from Ch 9
1. **Gamma, theta, and vega are all greatest when ATM** → ATM options are most actively traded
2. **Time and volatility have similar effects** on almost all option sensitivities
3. **ATM near-expiry in low vol = maximum gamma risk** — deltas swing wildly with tiny price moves
4. **Can't determine the effect of time? Think about volatility (and vice versa)** — they're interchangeable in most sensitivity analyses
5. Never assume a position stays delta-neutral — delta changes with vol, time, AND price

---

## Chapter 10: Introduction to Spreading (Bonus)

### Why Spread?
1. **Exploit relative mispricing** between related instruments
2. **Express specific market views** (not just direction — vol views, time views, etc.)
3. **Control risk** — reduce variance while maintaining expected edge

### Casino Analogy (critical insight)
- Casino edge at roulette = 5.26% regardless of bet size or number of bets
- One $2,000 bet: max loss = $70,000 (can bankrupt small casino)
- Two $1,000 bets on different numbers: max loss = $34,000 (half the risk, same edge)
- 38 bets of $1,000 on all numbers: guaranteed profit of $2,000 (perfect spread)
- **Spreading doesn't reduce expected edge — it reduces variance**

### Option Spreads vs. Commodity Spreads
- Commodity spreads: opposing directional positions (cash vs. forward, near month vs. far month)
- Option spreads: can oppose on ANY risk dimension — delta, gamma, vega, theta, rho
- Gamma spread: long gamma in one option, short gamma in another → value depends on realized vol
- Vega spread: long vega vs. short vega → value depends on implied vol changes

### Static vs. Dynamic Spreads
- **Static**: hold to expiration, no adjustments. Works when risk is well-defined and limited.
- **Dynamic**: requires periodic delta adjustments (Ch 8 hedging is a dynamic spread)

### Margin for Error
- Never rely on exact vol estimate being correct
- Spread strategies increase breakeven vol range
- Example: naked call sale breaks even at vol X; spread widens breakeven range to X ± Y
- More spreading → larger margin for error → can trade larger size

### Execution
- Multi-leg spreads often traded as a single package at tighter bid-ask than individual legs
- Execute the **harder leg first** (less liquid market) to reduce execution risk
- Individual leg prices don't matter as long as they sum to the agreed spread price
