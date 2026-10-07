# Natenberg Workbook — Detailed Notes

Companion workbook to "Option Volatility and Pricing" (2nd Ed).
Structure: exercises + detailed solutions for each chapter of the main text.
This file captures every formula, worked solution pattern, and key insight.

---

## Chapter 1: Financial Contracts

### Settlement Types
- **Stock-type settlement**: Buyer pays full price. Carrying cost = price × rate × time.
  - Interest on $100 at 6.00% for 1 month: `100 × 0.06 × 1/12 = $0.50`
- **Futures-type settlement**: No cash changes hands at trade. Daily mark-to-market via margin.
  - Example: Gold at 625.80, multiplier $200: notional = `625.80 × 200 = $125,160`

### Key Worked Examples
- Stock-type P&L includes interest on purchase price
- Futures-type P&L = pure price change × multiplier (no interest component)
- At 7.80% for 1 week: carrying cost = `price × 0.078 × 1/52`

---

## Chapter 2: Forward Pricing

### Master Formula
```
Forward Price = (Spot + Carrying Costs) × (1 + r × t)
```
Where t is measured as: days/365, weeks/52, or months/12.

### Worked Solution Patterns

**Commodity forward:**
```
F = S × (1 + r × t) + storage + insurance
Example: S=123.15, dividend=2.60, r=5.30%, t=10/12
F = (123.15 - 2.60) × (1 + 0.053 × 10/12) + 2.60 × (1 + 0.053 × 4/12) = 124.32
```
Note: Dividends paid during the period reduce forward price; interest on dividends depends on when received.

**Stock forward:**
```
F = S × (1 + r × t) - FV(dividends)
Example: Stock at 76.60, r=4.25%, 84 days
F = 76.60 × (1 + 0.0425 × 84/365) = 76.95
```

**Implied interest rate from forward:**
```
r = [(F + dividends)/S - 1] / t
Example: F=77.30, S=76.70, div=0.51, t=84/365
r = [(77.30 + 0.51)/76.70 - 1] / (84/365) = 6.29%
```

**Arbitrage check:**
```
If F_market > F_theoretical → sell forward, buy spot (cash-and-carry)
If F_market < F_theoretical → buy forward, sell spot (reverse cash-and-carry)
Profit = |F_market - F_theoretical|
```

**Cross-rate forward (FX):**
```
F_FX = S_FX × (1 + r_foreign × t) / (1 + r_domestic × t)
Example: GBP/EUR 1.24, r_EUR=3.78%, r_GBP=2.32%, 3 months
F = 1.24 × (1 + 0.0232/4) / (1 + 0.0378/4) = 1.2355
```

---

## Chapter 3: Contract Specifications & Terminology

### Moneyness Rules
| Condition | Call | Put |
|-----------|------|-----|
| S > X | In-the-money | Out-of-the-money |
| S = X | At-the-money | At-the-money |
| S < X | Out-of-the-money | In-the-money |

### Intrinsic vs. Time Value
- **Intrinsic value**: max(S - X, 0) for calls; max(X - S, 0) for puts
- **Time value**: Option price - Intrinsic value
- Every option (ITM, ATM, OTM) carries time value

### Exercise Price Intervals
- Example: Strike prices at 45, 50, 55, 60, 65, 70, 75 with stock at 63.50
- At-the-money ≈ closest strike to spot (65)
- ITM calls: 45, 50, 55, 60; OTM calls: 70, 75

### Key Rules
- Exercise price is FIXED at contract inception
- "Parity" = intrinsic value (option trading at parity has zero time value)
- Example: Stock at 101.90, 100 call at 1.90 → at parity (pure intrinsic)

---

## Chapter 4: Expiration Profit and Loss

### Parity Graph Construction
At expiration, option value = intrinsic value only.

**Single leg P&L:**
```
Long call P&L = max(S - X, 0) - premium
Long put P&L = max(X - S, 0) - premium
```

**Multi-leg breakeven formulas (critical for system building):**

| Strategy | Breakeven |
|----------|-----------|
| Long call at X, premium p | X + p |
| Long put at X, premium p | X - p |
| Bull call spread (buy X₁, sell X₂) | X₁ + net debit |
| Bear put spread (buy X₂, sell X₁) | X₂ - net debit |
| Long straddle at X | X ± total premium |
| Long strangle (X₁ put, X₂ call) | X₁ - total premium OR X₂ + total premium |
| Butterfly (buy X₁, sell 2×X₂, buy X₃) | X₁ + net debit AND X₃ - net debit |

### Worked Examples
```
Stock at 72.00:
- Long 70 call at premium → breakeven = 70 + premium
- Short 65 put at premium → breakeven = 65 - premium
- Long 75 call at premium → breakeven = 75 + premium
- Long 80 put at premium → breakeven = 80 - premium

Bull call spread: Buy 70, Sell 80 → 2 breakevens at 70+debit and 80-credit
Straddle at 70: breakevens at 70±total_premium
```

### Slope Rules for Position Analysis
- Slope below lowest strike = sum of all put deltas
- Slope above highest strike = sum of all call deltas
- Slope changes at each strike by the number of contracts at that strike

---

## Chapter 5: Theoretical Pricing Models

### Expected Value Calculation
```
Theoretical Value = Σ(probability_i × outcome_i)
```

### Forward Price as Expected Value
```
Forward = S × (1 + r × t)
Example: Stock at 72.50, r=8%, 6 months
Forward = 72.50 × (1 + 0.08 × 6/12) = 75.40
```

### Option Theoretical Value via Probability Distribution
```
Call TV = Σ[p_i × max(S_i - X, 0)] / (1 + r × t)
```

**Worked example:**
```
S=72.50, X=75, r=8%, t=6 months, Forward=75.40
Possible outcomes with probabilities:
(.08×65.40) + (.18×70.40) + (.34×75.40) + (.26×80.40) + (.14×85.40) = 76.40
Expected stock value = 76.40
Theoretical 75 call = discounted expected payoff
```

### Volatility Input Significance
```
Theoretical value = f(underlying, exercise, time, interest, volatility)
```
- Same formula, different volatility → different price → different trade decision
- Volatility is the ONLY unknown input

### "The Riskless Hedge" Concept
If you buy an undervalued option and hedge with the underlying, you earn the edge regardless of market direction. This is the foundation of all theoretical pricing.

---

## Chapter 6: Volatility

### Annualization Formulas
```
σ_annual = σ_period × √(periods_per_year)
Daily σ → Annual: σ_daily × √256 (trading days) = σ_daily × 16
Weekly σ → Annual: σ_weekly × √52
Monthly σ → Annual: σ_monthly × √12
```

### One Standard Deviation Price Move
```
1σ daily move = Price × (Annual_Vol / √256) = Price × (Annual_Vol / 16)
```

**Worked examples:**
| Underlying | Price | Annual Vol | Daily 1σ Move |
|-----------|-------|-----------|---------------|
| Stock | 78.00 | 23.72% | 78 × 0.2372/16 = 1.16 |
| Index | 1,325.00 | 17.22% | 1325 × 0.1722/16 = 14.26 |
| FX | 1.6270 | 14.27% | 1.627 × 0.1427/16 = 0.0145 |
| Commodity | 669.00 | 31.33% | 669 × 0.3133/16 = 13.10 |

### Historical Volatility Calculation
```
1. Calculate daily returns: r_i = ln(P_i / P_{i-1})
2. Mean return: r̄ = Σr_i / n
3. Variance: σ² = Σ(r_i - r̄)² / (n-1)
4. Daily std dev: σ_daily = √σ²
5. Annualize: σ_annual = σ_daily × √256
```

**Worked example:**
```
Stock at 104.75, 27.42% annual vol
Forward (192 days): 104.75 × (1 + r × 192/365) = 105.88
After 43 days at realized vol: new forward adjusted by √(remaining/original) time
```

### Key Rules
- **68-95-99.7 rule**: 1σ covers 68.3%, 2σ covers 95.4%, 3σ covers 99.7%
- Volatility SCALES with √time, NOT linearly
- A 10-day realized vol of 20% means: daily moves of `20%/16 = 1.25%`
- Close-to-close method: use ln returns, n-1 divisor

### Converting Period Vol to Annual
```
10-day close-to-close returns with σ_daily = 1.65%
Annual vol = 1.65% × √256 ≈ 26.40%
```

---

## Chapter 7: Risk Measurement I (The Greeks)

### Delta
```
Call delta: 0 to +100 (or 0 to +1.0)
Put delta: -100 to 0 (or -1.0 to 0)
Put delta = Call delta - 100

Position delta = Σ(quantity_i × delta_i × contract_multiplier)
```

### Gamma
```
Gamma = change in delta per unit change in underlying
Always positive for long options (calls and puts)
Highest for ATM options near expiration

Position gamma = Σ(quantity_i × gamma_i)
```

### Theta
```
Theta = daily time decay (usually negative for long options)
Highest (most negative) for ATM options near expiration

Position theta = Σ(quantity_i × theta_i)
```

### Vega
```
Vega = change in option value per 1% change in implied vol
Always positive for long options
Highest for ATM, longer-dated options

Position vega = Σ(quantity_i × vega_i)
```

### Rho
```
Rho = change in option value per 1% change in interest rate
Calls: positive rho; Puts: negative rho
```

### Greeks Relationship (Theta-Gamma Tradeoff)
```
For a delta-neutral position:
Theta + (Gamma × σ²S²) / 2 ≈ r × (option value)

Practical: Theta ≈ -½ × Gamma × S² × σ² / 365
```
This means: if you're long gamma, you bleed theta. If you're short gamma, you collect theta.

### Worked Position Greeks
```
Position: +5 at 79δ, +6 at 52δ, +14 at 26δ, -8 at 21δ, +11 at 48δ, -6 at 74δ, -3 at 100δ
Total delta = (5×79)+(6×52)+(14×26)+(-8×21)+(11×48)+(-6×74)+(-3×100) = +271

Total gamma similarly summed → -148.8
Total theta → +3.50
Total vega → -3.525

Net P&L per day ≈ theta + ½ × gamma × (move²)
```

### The "Tied-To" Concept
When hedging an option with the underlying:
```
Theoretical Edge = ½ × Gamma × (actual_move² - implied_move²)
```
If actual vol > implied vol → long gamma profits
If actual vol < implied vol → short gamma profits

### Market-Maker's Edge
```
Example: ATM option, gamma=48.0, theta=-5.3, vega=56.0
Daily theoretical edge at vol differential:
Edge = ½ × Gamma × (S² × σ²_actual/365) - |Theta|
```

---

## Chapter 8: Dynamic Hedging

### Delta-Neutral Hedging
```
Shares to hedge = -option_delta × number_of_contracts × contract_multiplier
```

**Worked examples:**
```
Long 25 calls at delta 80 → hedge: sell 25 × 80 = 2,000 shares (or 20 contracts of 100)
Long 50 puts at delta -70 → hedge: buy 50 × 70 = 3,500 shares
```

### Rebalancing P&L
```
Each rebalance captures: ½ × Γ × ΔS²
Cumulative hedge P&L over life = realized vol captured

Example:
Start: delta-neutral with +55 gamma
Stock moves from 55 to 70: need to sell (70-55)×55/2 shares = ~412 shares
P&L from rebalancing = ½ × gamma × (price_change)²
```

### Key Insight: Dynamic Hedging Frequency
```
Total P&L = Σ(½ × Γ_i × ΔS_i²) - Total_Theta
         = (Realized Vol captured) - (Time decay paid)

If realized vol > implied vol → net profit
If realized vol < implied vol → net loss
```

This is the fundamental theorem of options trading.

---

## Chapter 9: Risk Measurement II

### Spread Categories by Greek Exposure

| Spread Type | Example | Primary Greek |
|------------|---------|---------------|
| Time spread | 1m 75C / -3m 75C | Theta/Vega |
| Ratio spread | -1 75C / +2 80C | Gamma |
| Butterfly | +1 75 / -2 80 / +1 85 | Gamma |
| Straddle | +1 80C / +1 80P | Gamma/Vega |

### Greeks by Moneyness and Time

| | ATM | ITM | OTM |
|---|-----|-----|-----|
| Delta (call) | ~50 | >50 | <50 |
| Gamma | Highest | Lower | Lower |
| Theta | Most negative | Less negative | Less negative |
| Vega | Highest | Lower | Lower |

### Time Effects on Greeks
- **Short-term ATM**: highest gamma, highest theta
- **Long-term ATM**: highest vega, lower gamma
- Near expiration: gamma concentrates at ATM strike (becomes very high ATM, near zero elsewhere)

### Ratio Spread Greeks Analysis
```
Example: Short 1×80C, Long 2×85C
Net delta = -80δ + 2×45δ = +10 (slightly bullish)
Net gamma = -Γ₈₀ + 2×Γ₈₅ > 0 (positive gamma if OTM gamma > ATM)
```

### Zero-Gamma, Zero-Delta Positions
To be delta-neutral AND gamma-neutral:
1. Find ratio that zeroes gamma
2. Hedge remaining delta with underlying

---

## Chapter 10: Introduction to Spreading

### Spread Pricing
```
Spread value = Σ(quantity_i × price_i)
Convention: positive = buy, negative = sell

Examples:
+1 call_A -1 call_B: spread = price_A - price_B
+1 put_A -1 call_B +1 underlying: spread = put_A - call_A + S
```

### Spread Order Rules
- Spreads with same expiration: list by strike
- Spreads with different expirations: list by expiration (nearest first)
- Credit spread: net premium received (negative spread value → you collect)
- Debit spread: net premium paid (positive spread value → you pay)

### Spread Classification by Components

| Spread | Legs | Max Profit | Max Loss |
|--------|------|-----------|----------|
| Vertical (bull call) | +1 low X call, -1 high X call | (X₂-X₁) - debit | Debit paid |
| Vertical (bear put) | +1 high X put, -1 low X put | (X₂-X₁) - debit | Debit paid |
| Straddle | +1 X call, +1 X put | Unlimited | Total premium |
| Strangle | +1 X₁ put, +1 X₂ call | Unlimited | Total premium |
| Butterfly | +1 X₁, -2 X₂, +1 X₃ | X₂-X₁-debit | Debit paid |
| Condor | +1 X₁, -1 X₂, -1 X₃, +1 X₄ | Narrower spread - debit | Debit paid |

---

## Chapter 11: Volatility Spreads

### Straddle Construction & Greeks
```
Long straddle at X: buy call + buy put at same strike
Net delta ≈ 0 (ATM call δ≈50, ATM put δ≈-50)
Net gamma: positive (long both)
Net theta: negative (paying double decay)
Net vega: positive (want vol to rise)
```

### Butterfly as Volatility Play
```
Long butterfly: +1 X₁ call, -2 X₂ call, +1 X₃ call (X₂ = midpoint)
Short vol play: want stock to stay near X₂
Net gamma: negative
Net theta: positive
Net vega: negative
```

### Iron Butterfly / Iron Condor
```
Iron butterfly = short straddle + long strangle
= sell 1 ATM call + sell 1 ATM put + buy 1 OTM call + buy 1 OTM put
```

### Worked Greeks Calculations
```
Position: -1×80C, +2×85C, -1×90C (call butterfly)
Delta: weighted sum
Gamma: negative for short butterfly, positive for long
Theta/Vega: opposite sign to gamma

Christmas tree: -1×80C, +1×85C, +1×85P, -1×90P
Iron condor: sell narrow wings, buy wide wings
```

---

## Chapter 12: Bull and Bear Spreads

### Put-Call Parity (Foundation)
```
Stock-type: C - P = S - X/(1+r×t)
Futures-type: C - P = (F - X)/(1+r×t)
```

### Synthetic Equivalences
```
Synthetic long stock = long call + short put (same X, same expiration)
Synthetic long call = long stock + long put
Synthetic long put = short stock + long call
```

### Vertical Spread Pricing via Put-Call Parity
```
Bull call spread (buy X₁ call, sell X₂ call) = same P&L as
Bull put spread (sell X₁ put, buy X₂ put) + interest adjustment

For futures-type:
Call vertical = Put vertical = (X₂ - X₁)/(1+r×t) when at parity
```

**Worked examples:**
```
Stock at 61.75:
Bull call: buy 60C at 15.15, sell 70C at 4.85 → debit = 10.30
Equivalent bull put: synthetic gives same P&L
Max profit = (70-60) - 10.30 = -0.30 → this is a credit spread alternative
```

### Time Effects on Vertical Spreads
```
Stock-type settlement, r=8%:
12 months to exp: vertical value discounted by -7.4
9 months: -5.7
6 months: -3.8
3 months: -2.0
At expiration: vertical = intrinsic = X₂ - X₁ (if ITM)
```

### Box Spread (Arbitrage Check)
```
Box = Bull call spread + Bear put spread (same strikes)
Box value = (X₂ - X₁) / (1 + r × t)

If market box ≠ theoretical box → arbitrage opportunity
Implied rate from box: r = [(X₂-X₁)/Box_price - 1] / t

Example: 130-160 box, 73 days
Box = 29.76, implied rate = [(30/29.76)-1]/(73/365) = 4.03%
```

### Ratio Vertical Spreads
```
Ratio spread: buy 1×low strike, sell n×high strike (n > 1)
Backspread: sell 1×low strike, buy n×high strike

Ratio spread: limited upside, unlimited downside
Backspread: limited downside, unlimited upside
```

---

## Chapter 13: Risk Considerations

### Margin of Error (Option Sensitivity)
```
Days until option doubles/halves in value:
Time to halve ≈ (remaining_days × θ) / option_value

For ATM option: value ≈ 0.4 × S × σ × √t
Halving time for ATM ≈ t/4 (option loses half value in last quarter of life)
```

### Probability of Expiring ITM
```
P(ITM at expiration) ≈ |Delta| / 100

For exact calculation:
d₂ = [ln(S/X) + (r - σ²/2)×t] / (σ×√t)
P(call ITM) = N(d₂)
P(put ITM) = N(-d₂)
```

### Theoretical Edge vs. Risk
```
Theoretical edge = TV_model - Market_price (for buys)
                 = Market_price - TV_model (for sells)

Risk = Gamma × expected_move² / 2

Reward/Risk = Edge / (Gamma × σ² × S² × t)
```

### Worked Risk Examples
```
Stock at 60.00, 35 days, r=4%, 15 vol
Delta ≈ 50 at ATM
Gamma per day exposure = ½ × Γ × S² × σ²/365

At 50 strike, 50 delta:
Breakeven vol = implied vol where edge = 0
Time for position to become "safe" (edge > 2σ of risk):
  approximately when √(days_passed/total_days) × edge > 2 × daily_σ × vega
```

### Exercise Boundary (American Options)
```
Early exercise of call is optimal when:
Time_value < Carrying_cost_to_expiration + Dividend_lost

For put:
Time_value < Interest_earned_on_exercise_proceeds

Approximate: Exercise when time value < parity interest
```

---

## Chapter 14: Synthetics

### Complete Synthetic Relationships
```
+C = +S +P (long call = long stock + long put)
-C = -S -P
+P = -S +C (long put = short stock + long call)
-P = +S -C
+S = +C -P (long stock = long call + short put)
-S = -C +P
```

### Put-Call Parity Detailed
```
Stock-type: C - P = S - X×e^(-r×t)   [continuous]
           C - P = S - X/(1+r×t)      [simple]

Futures-type: C - P = (F - X)/(1+r×t)
```

### Conversion/Reversal
```
Conversion: +S -C +P (locked profit if synthetic < actual)
Reversal: -S +C -P (locked profit if synthetic > actual)

Box = Conversion at X₁ + Reversal at X₂
Box value = PV(X₂ - X₁)
```

### Worked Conversion Example
```
Stock at 71.60, 75 strike, 86 days, r=5.45%, vol=29.30%
Step 1: Calculate forward = 71.60 × (1 + 0.0545 × 86/365)
Step 2: Call_TV - Put_TV = Forward - X/(1+r×t)
Step 3: If market prices deviate → conversion or reversal arbitrage
```

### The "40% Rule"
```
For ATM options (at-the-forward):
Call ≈ Put ≈ 0.4 × S × σ × √t

Example: S=1200, σ=20%, t=3 months
ATM option ≈ 0.4 × 1200 × 0.20 × √0.25 = 0.4 × 1200 × 0.10 = 48.0
```

---

## Chapter 15: Binomial Option Pricing

### Risk-Neutral Pricing Framework
```
Up factor: u = e^(σ×√Δt)
Down factor: d = 1/u = e^(-σ×√Δt)
Risk-neutral probability: p = (e^(r×Δt) - d) / (u - d)

Option value = [p × C_up + (1-p) × C_down] / e^(r×Δt)
```

### Worked 1-Period Example
```
S=82.50, X=80, r=6%, t=2 months
u=1.15, d=0.90
S_up = 82.50 × 1.15 = 94.875
S_down = 82.50 × 0.90 = 74.25

p = (e^(0.06×2/12) - 0.90) / (1.15 - 0.90) = 0.44

Call payoffs: max(94.875-80, 0) = 14.875; max(74.25-80, 0) = 0
Call = [0.44×14.875 + 0.56×0] / e^(0.06×2/12) = 6.48

Put payoffs: max(80-94.875, 0) = 0; max(80-74.25, 0) = 5.75
Put = [0.44×0 + 0.56×5.75] / e^(0.06×2/12) = 3.19

Verify put-call parity: 6.48 - 3.19 = 3.29 ≈ S - PV(X) = 82.50 - 80/(1.01) = 3.29 ✓
```

### Delta from Binomial Tree
```
Δ = (C_up - C_down) / (S_up - S_down)
Example: (14.875 - 0) / (94.875 - 74.25) = 0.721 (72.1 delta)
```

### Hedging with Binomial Delta
```
Long 1 call, short Δ shares:
At S_up: 14.875 - 0.721 × 94.875 = payoff
At S_down: 0 - 0.721 × 74.25 = same payoff (riskless!)
```

### 3-Period Tree (American Options)
```
S₀ = 1,278.00, X=1300, t=30 weeks, r=4%, σ=27%
Δt = 10/52 per period

u = e^(0.27×√(10/52)) = 1.1253
d = 1/u = 0.8887
p = (e^(0.04×10/52) - 0.8887) / (1.1253 - 0.8887) = 0.5029

Tree nodes (S × u^j × d^(n-j)):
S₃,₃ = 1823.04  S₃,₂ = 1438.64  S₃,₁ = 1135.30  S₃,₀ = 895.91

Put payoffs at t=3:
1823.04: 0   1438.64: 0   1135.30: 164.70   895.91: 404.09

European put = discounted expected value through tree
= [(164.70 × 3 × 0.1243) + (404.09 × 1 × 0.1228)] / 1.0233^3 = 108.51

American put: at each node, compare continuation value vs. immediate exercise
If immediate exercise > continuation → exercise early
```

### Key Insight: American vs. European
```
American premium = max(European value, immediate exercise value) at each node
The American premium ≥ European premium always
For American put: early exercise optimal when deeply ITM with little time value
```

---

## Chapter 16: Early Exercise of American Options

### When to Exercise American Calls
```
Exercise call early when:
1. Deep ITM (time value ≈ 0)
2. Dividend > time value remaining
3. Just before ex-dividend date

Never exercise American call early on non-dividend-paying stock
(because time value is always positive → selling > exercising)
```

### When to Exercise American Puts
```
Exercise put early when:
1. Deep ITM
2. Interest on exercise proceeds > remaining time value
3. Condition: X × r × Δt > time_value
```

### Exercise Boundary Relationships
```
For calls with dividend D:
Exercise if: C - intrinsic < D × e^(-r×t_to_ex)
i.e., time value < PV of dividend

For puts:
Exercise if: P - intrinsic < X × r × Δt
i.e., time value < interest on strike until expiration
```

### Synthetic Equivalences and Exercise
```
If long synthetic stock (+C -P) and put becomes deeply ITM:
The put holder may exercise against you
Your position changes from synthetic to actual stock
Need to re-hedge using delta
```

---

## Chapter 17: Volatility Skew

### Skew Patterns
- **Equity index options**: Puts more expensive (negative skew / "smirk")
  - Lower strikes → higher IV
  - Reason: crash risk, demand for downside protection
- **Commodity options**: Calls can be more expensive (positive skew)
  - Supply disruption → price spikes
- **FX options**: Symmetric or varies by pair

### Jump-Diffusion Impact
- Adds fat tails to the distribution
- OTM options worth more than B-S predicts
- Justifies the skew

### Exchange-Traded vs. OTC
- Exchange-traded: standardized strikes and expirations
- OTC: custom strikes, barriers, exotics
- Skew affects exotic option pricing significantly

### Volatility Surface
```
IV = f(strike, expiration)
Term structure: IV across expirations (same delta or moneyness)
Smile/skew: IV across strikes (same expiration)
```

### Trading the Skew
- If skew too steep: sell OTM puts, buy ATM (or reverse)
- If skew too flat: buy wings, sell body
- Key: compare skew to historical realized distribution

---

## Chapter 18: Models and the Real World

### B-S Assumptions vs. Reality
1. **Constant volatility**: False — vol is stochastic
2. **Lognormal distribution**: False — real distributions have fat tails
3. **Continuous trading**: False — gaps and jumps occur
4. **No transaction costs**: False — bid-ask, commissions, slippage
5. **Constant interest rate**: False — rates change
6. **No dividends**: Modified B-S handles this

### Model Risk
- Using wrong vol → mispriced options → losing trades
- Model gives theoretical value, market gives real price
- The spread between model and market is your edge OR your error

### Practical Adjustments
- Use implied vol from market, not just historical
- Adjust for skew when pricing non-ATM options
- Use binomial for American options (B-S only for European)
- Account for discrete dividends in stock options

---

## Chapter 19: Stock Index Futures and Options

### Index Weighting Methods

| Method | Formula | Split Effect | Stock Replacement |
|--------|---------|-------------|-------------------|
| Price-weighted | Σ(prices) / divisor | Divisor changes | Divisor changes |
| Cap-weighted | Σ(price × shares) / divisor | No change (cap same) | Divisor changes |
| Equal-weighted | Σ(price_i/base_i) / divisor | No change | No change |

### Worked Index Calculations
```
3 stocks: X=$25.30/9000shares, Y=$81.70/5000shares, Z=$46.55/3000shares
Starting index = 250

Price-weighted divisor: (25.30+81.70+46.55)/250 = 0.6142
Cap-weighted divisor: (227,700+408,500+139,650)/250 = 3,103.40
Equal-weighted divisor: 3.00/250 = 0.012

After Y splits 2:1 (new price 40.85, new shares 10,000):
Price-weighted divisor changes: (25.30+40.85+46.55)/250 = 0.4508
Cap-weighted: NO CHANGE (cap = 40.85×10,000 = 408,500 same)
Equal-weighted: NO CHANGE (40.85/40.85 = 81.70/81.70 = 1.00)
```

### Index Futures Fair Value
```
F = I × (1 + r × t) - PV(dividends)
Example: Index at 2,520.37, dividends = 9.94, r=5.33%, 72 days
F = (2520.37 + 9.94) / (1 + 0.0533 × 72/365) = 2,503.98
```

### Implied Rate from Index Futures
```
r = [(F + divs)/I - 1] / t
Example: F=2509.80, I=2520.37, divs=9.94, 72 days
r = [(2509.80 + 9.94)/2520.37 - 1] / (72/365) = 4.14%
```

### Index Dividend Stream
```
If F < I×(1+r×t), implied dividends > 0
Dividend yield = [I×(1+r×t) - F] / I / t
```

---

## Chapter 20: Risk Analysis (Position Analysis)

### Using Synthetics to Simplify Positions
```
Convert all puts to synthetic equivalent calls (or vice versa):
Put at X = Call at X - Underlying + PV(X)

Then combine same-strike options to find net position
Example:
+12 Oct 45C, -87 Oct 45P, -46 Oct 50C, +46 Oct 50P, +59 Oct 55C, +16 Oct 55P
Convert puts to calls using synthetic:
-87 Oct 45P = -87 Oct 45C + 87 shares
Net Oct 45: +12-87 = -75 Oct 45 calls + 87 shares
Similarly simplify all strikes → reveals it's a bear spread
```

### Position Greeks After Stock Split
```
Y-for-X split:
New contracts = Old × (Y/X)
New strike = Old / (Y/X)
New delta position = Old × (Y/X)
New gamma position = Old × (Y/X)²
New theta = SAME
New vega = SAME
New rho = SAME
New option price = Old / (Y/X)
```

**Worked example (3:1 split):**
```
Old: +68 Nov 120 puts, +37 Nov 135 calls, +1200 shares. Stock = 122.82
New: +204 Nov 40 puts, +111 Nov 45 calls, +3600 shares. Stock = 40.94
Delta: old × 3 (from -228.7 to -686.1)
Gamma: old × 9 (from 244.17 to 2197.53)
Theta: unchanged (-2.2176)
Vega: unchanged (+26.832)
```

### Breakeven Volatility
```
Breakeven vol = evaluation vol + (edge / vega)
Example: edge=78, vega=15.7, eval_vol=22%
Breakeven = 22% + 78/15.7 ≈ 22% + 5% = 27%
```

### Adjusted Vega (Term Structure)
```
If Month 2 vol changes by 75% of Month 1 vol change:
Adjusted vega = vega_M1 + 0.75 × vega_M2

Example: vega_M1=+4.5, vega_M2=-20.2
Adjusted = 4.5 + 0.75×(-20.2) = 4.5 - 15.15 = -10.65
Positive raw vega becomes NEGATIVE adjusted → short vol exposure!
```

### Extreme Position Analysis
```
On large downward move:
- All calls → delta 0 (worthless)
- All puts → delta -100 (act like short stock)
- "Downside contract position" = short stock + long puts acting as stock

On large upward move:
- All puts → delta 0 (worthless)
- All calls → delta +100 (act like long stock)
- "Upside contract position" = short stock + long calls acting as stock

As vol → ∞: all deltas → 50 (calls) or -50 (puts)
```

### Dividend Impact on Multi-Month Positions
```
Dividend increase lowers forward price for later months
Effect = -dividend_change × delta_of_later_month / 100
Example: +$2 dividend, Month 2 delta = -3484
P&L impact = -2.00 × (-34.84) = +69.68
```

---

## Key Rules of Thumb (Summary)

1. **40% Rule**: ATM option ≈ 0.4 × S × σ × √t
2. **Delta ≈ P(ITM)**: Rough probability of finishing in-the-money
3. **Gamma-Theta tradeoff**: Long gamma = short theta, always
4. **Volatility scales √t**: 1-week vol to annual = multiply by √52
5. **Daily 1σ move** = S × σ_annual / 16
6. **Breakeven vol** = implied + edge/vega
7. **Box value** = PV(strike_difference) — deviation = arbitrage
8. **American call**: never exercise early without dividends
9. **American put**: exercise when interest on proceeds > time value
10. **Stock split**: delta×Y/X, gamma×(Y/X)², theta/vega/rho unchanged
11. **Adjusted vega**: accounts for term structure — raw vega can mislead
12. **Conversion value** = S - PV(X) = C - P (put-call parity)
