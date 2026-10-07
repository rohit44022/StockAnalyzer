# Natenberg — Option Volatility & Pricing: Part 1 (Chapters 1–5)

## Foundational Concepts: Contracts, Pricing, Terminology, P&L, and Theoretical Models

---

## Chapter 1: Financial Contracts

### Core Analogy
Natenberg opens with a parable: Jerry wants to buy land from Farmer Smith for $100,000. This simple transaction introduces all derivative contract types:

- **Immediate exchange** = spot/cash transaction
- **Deferred payment** = forward contract (agree now, settle later)
- **Insurance against loss** = option contract (right, not obligation)

### Buying and Selling
- **Long** = buying / owning / expecting price to rise
- **Short** = selling / not owning / expecting price to fall
- A long position profits when the market rises; a short position profits when the market falls
- Long the underlying: exposed to both upside and downside

### Notional Value
- **Notional value** = quantity × price per unit
  - 1,000 barrels × $75/barrel = $75,000 notional
  - Stock index: index level × multiplier (e.g., 825.00 × $200 = $165,000)

### Settlement Procedures

Two fundamental settlement types:

| Feature | Stock-Type Settlement | Futures-Type Settlement |
|---------|----------------------|------------------------|
| Payment | Full price paid upfront | Only margin deposit required |
| P&L realization | At close of position | Daily (variation/mark-to-market) |
| Cash flow timing | Deferred until sale | Continuous |
| Used for | Stocks, stock indexes, most options | Futures contracts |
| Credit risk | Buyer pays full amount | Margin covers daily swings |

**Stock-type**: Buy 100 shares at $50 → pay $5,000 immediately. If price goes to $60, profit = $1,000, but only realized when you sell.

**Futures-type**: Buy 1,000 units at $75 with $3,000 margin. If price goes to $80, you receive $5,000 variation credit daily. If price drops to $70, you pay $5,000 variation debit.

**Key insight**: Even though futures and stock positions may have the same notional value, the cash-flow timing is fundamentally different. This affects the cost of carry and therefore the forward price.

### Market Integrity
- **Clearinghouse** stands between buyer and seller on all exchange-traded contracts
- Breaks the direct link between counterparties
- Guarantees contract performance (eliminates counterparty risk)
- Parties post **margin** as security
- Individual traders → clearing firms → clearinghouse (layered guarantee structure)

---

## Chapter 2: Forward Pricing

### The Central Question
What is the fair price for delivery of an asset at a future date?

### Forward Price Formula (General)

```
F = S × (1 + r × t) + storage/insurance costs − income from holding
```

Where:
- **F** = forward price
- **S** = current spot price
- **r** = annual interest rate (as decimal)
- **t** = time to maturity (in years, e.g., 8 months = 8/12)

### Asset-Specific Forward Pricing

#### Physical Commodities (Grains, Energy, Metals)
```
F = S × (1 + r × t) + storage + insurance
```
- Storage and insurance are **costs of carry** — they increase the forward price
- Example: Commodity at $67, r=6%, t=8 months, storage=$0.33/month, insurance=$0:
  ```
  F = 67.00 × (1 + 0.06 × 8/12) + (storage costs) = ~69.02
  ```

#### Stocks
```
F = S × (1 + r × t) − D
```
- **D** = expected dividends during the period (reduces forward price because holder gets income)
- Dividends can be adjusted for interest earned if received during the period
- **Ex-dividend date** matters: on that date, stock price drops by approximately the dividend amount
- Example: Stock at $67.50, ex-div coming with $0.40 dividend:
  - Current price $68.25 (cum-dividend)
  - Forward adjustment: 68.25 − 1.15 (carry cost) − 0.40 (ex-div) = $66.70

#### Bonds and Notes
```
F = S × (1 + r × t) − coupon income
```
- Similar to stocks but with coupon payments instead of dividends

#### Foreign Currencies
```
F = S × (1 + r_domestic × t) / (1 + r_foreign × t)
```
- Two interest rates matter: domestic and foreign
- If domestic rate > foreign rate, forward price > spot (forward premium)
- If domestic rate < foreign rate, forward price < spot (forward discount)

### Arbitrage

**Definition**: Risk-free profit from price discrepancies between related markets.

**Cash-and-carry arbitrage** — when forward is overpriced:
1. Borrow money at rate r
2. Buy the asset at spot price S
3. Sell the forward contract at price F
4. At maturity: deliver the asset, receive F, repay loan
5. Profit = F − [S × (1 + r × t) + carry costs]

**Reverse cash-and-carry** — when forward is underpriced:
1. Sell/short the asset at spot price S
2. Lend the proceeds at rate r
3. Buy the forward contract at price F
4. At maturity: receive asset via forward, return borrowed asset
5. Profit = [S × (1 + r × t) + carry costs] − F

**Example**: Commodity at $67, 8-month forward should be $69.02. If forward trades at $69.50:
- Cash-and-carry profit = 69.50 − 69.02 = $0.48 per unit (risk-free)

### Short Sales and Borrowing Costs

- **Short selling** = selling stock you don't own (must borrow it first)
- **Short-stock rebate** = interest rate paid to the short seller on proceeds held by the lender
- The rebate is always less than the full lending rate

**Key formula**:
```
r_long − r_short = r_borrowing_cost
```

- This creates a **no-arbitrage band** around the theoretical forward price
- Example: If forward should be $69.02 (using long rate) but short rate gives $68.13:
  - Forward trading between $68.13 and $69.02 → no arbitrage possible
  - Only arbitrage if forward < $68.13 (buy forward, sell stock) or > $69.02 (sell forward, buy stock)

**Options vs. stocks**: Options are contracts, not deliverable securities. You don't need to "borrow" an option to sell it short. Therefore, the **ordinary long rate** always applies to option cash flows.

### Forward Rate Notation
```
1 × 5 forward rate = 4-month rate beginning in 1 month
3 × 9 forward rate = 6-month rate beginning in 3 months
4 × 12 forward rate = 8-month rate beginning in 4 months
```

---

## Chapter 3: Contract Specifications and Option Terminology

### Option Types
- **Call** = right to BUY the underlying at the strike price
- **Put** = right to SELL the underlying at the strike price
- Key difference from futures: options give **rights** to the buyer, **obligations** to the seller

### Underlying Contract
- Stock options: typically 100 shares per contract
- Futures options: one futures contract per option
- **Serial options**: option expirations where no corresponding futures month exists
  - e.g., Jan/Feb options on March futures
- **Midcurve options**: short-term options on long-term futures (1-year, 2-year, 5-year midcurve)

### Expiration
- Stock options: typically 3rd Friday of expiration month
- **AM expiration** (stock indexes): settlement based on opening price → avoids large order imbalances at close
- **PM expiration** (individual stocks): settlement based on closing price
- Futures options on physical commodities: often expire in the month BEFORE the futures month

### Exercise Price (Strike Price)
- Fixed by the exchange, set at equal intervals bracketing current price
- Exchange can add new strikes as price moves
- Example: Crude oil October 90 call on NYMEX = right to buy 1 October crude futures (1,000 barrels) at $90/barrel

### Exercise and Assignment

| Action | Call | Put |
|--------|------|-----|
| Exercise (buyer) | Buy underlying at strike | Sell underlying at strike |
| Assignment (seller) | Sell underlying at strike | Buy underlying at strike |

**Settlement types upon exercise**:

1. **Physical delivery**: Actual shares/commodity change hands
   - Exercise 1 Jan 110 call → pay $11,000, receive 100 shares
   - Assigned on 3 Oct 95 puts → pay $28,500, receive 300 shares

2. **Futures settlement**: Position established at exercise price, subject to margin and daily variation
   - Exercise 1 Feb 80 call (underlying at 85) → long 1 futures at 80, receive $5,000 variation credit
   - Assigned on 6 Sept 75 calls (underlying at 85) → short 6 futures at 75, pay $60,000 variation debit

3. **Cash settlement**: Difference between exercise price and settlement value paid in cash
   - Exercise 3 Mar 300 calls (settlement at 320) → receive (320−300) × $500 × 3 = $30,000
   - No physical delivery of the index

### Exercise Style
- **American**: can exercise any time before expiration
- **European**: can exercise only at expiration

### Option Price Components

**Intrinsic value**:
```
Call intrinsic = max(0, underlying_price − strike_price)
Put intrinsic = max(0, strike_price − underlying_price)
```

**Time value** (extrinsic value):
```
Time value = option_price − intrinsic_value
```
- Always ≥ 0 for American options
- Represents the probability-weighted potential for further favorable movement

**Example**: Stock at $435
- 400 call: intrinsic = $35, if trading at $50, time value = $15
- 400 put: intrinsic = $0 (out-of-the-money), all premium is time value

### Moneyness

| Term | Call Condition | Put Condition |
|------|---------------|---------------|
| **In-the-money (ITM)** | S > X | S < X |
| **At-the-money (ATM)** | S ≈ X | S ≈ X |
| **Out-of-the-money (OTM)** | S < X | S > X |

- ITM options have intrinsic value
- OTM options have zero intrinsic value (all time value)
- ATM options have the most time value (maximum uncertainty about finishing ITM)

### Automatic Exercise
- Most exchanges automatically exercise ITM options at expiration
- Threshold varies: typically if ITM by ≥ $0.05 (exchanges) or ≥ $0.01–$0.02 (customer accounts)
- Traders must submit "do not exercise" notices if they don't want automatic exercise

### Margin/Risk Requirements
- **SPAN** (Standard Portfolio Analysis of Risk): risk-based margin system used by CME Group
- Margin is based on portfolio risk, not individual position
- Clearinghouse analyzes "what-if" scenarios to determine margin

---

## Chapter 4: Expiration Profit and Loss

### Parity Graphs (Payoff Diagrams)

Parity graphs show the value of an option position AT EXPIRATION as a function of the underlying price.

**Basic position slopes**:

| Position | Below Strike | Above Strike |
|----------|-------------|-------------|
| Long call | 0 (worthless) | +1 (gains with price) |
| Short call | 0 | −1 |
| Long put | −1 (gains as price falls) | 0 (worthless) |
| Short put | +1 | 0 |
| Long underlying | +1 everywhere | +1 everywhere |
| Short underlying | −1 everywhere | −1 everywhere |

**Slope notation**: +1 means the position gains $1 for every $1 increase in the underlying. −1 means it loses $1 for every $1 increase.

### Building Complex Positions

For multi-leg positions:
1. List slopes of each component over every price interval (between strikes)
2. Sum the slopes in each interval
3. Calculate P&L at one known point (easiest at a strike price)
4. Use slopes to extend P&L to all other intervals

### Expiration P&L (shifting the parity graph)

```
Expiration P&L = Parity value − net premium paid
```

- Buying options → debit → shifts parity graph DOWN
- Selling options → credit → shifts parity graph UP

**Example**: Long 100 call bought at $3.50
- Below 100: lose $3.50 (option worthless)
- Breakeven: $103.50 (strike + premium)
- Above 103.50: profit = (underlying − 100) − 3.50

**Example**: Short 95 put sold at $2.25
- Above 95: profit = $2.25 (option worthless)
- Breakeven: $92.75 (strike − premium)
- Below 92.75: loss = 95 − underlying − 2.25

### Breakeven Calculation
```
Call breakeven = strike + premium paid
Put breakeven = strike − premium paid
```

For complex positions with known P&L at one point:
```
Breakeven = reference_price + (P&L_at_reference / slope_in_that_interval)
```

Example: P&L = −3.00 at strike 95, slope = +1 between 95 and 105:
- Breakeven = 95.00 + (3.00/1) = 98.00

### Relative Value Observations
- **Calls**: lower strike → higher premium (right to buy cheaper)
- **Puts**: higher strike → higher premium (right to sell at higher price)

---

## Chapter 5: Theoretical Pricing Models

### The Speed Problem

**Critical insight**: Unlike an underlying trader who only needs to be right about direction, an option trader must be right about BOTH direction AND speed.

- If a stock rises from $100 to $115 but takes 4 months instead of 2, a 3-month $110 call expires worthless even though direction was correct
- Time decay works against option buyers: favorable direction alone is insufficient
- Many option strategies depend ONLY on speed (volatility) and NOT on direction

**Implication for system design**: Speed = volatility. This is why volatility is the central concept in options trading.

### Expected Value

**Definition**: The probability-weighted average of all possible outcomes.

```
Expected Value = Σ (probability_i × outcome_i)
```

**Die example**: E[V] = (1+2+3+4+5+6)/6 = $3.50
- Pay < $3.50 → positive expected value (edge)
- Pay > $3.50 → negative expected value

**Roulette example**: 38 slots, one winning slot pays $36
- E[V] = $36/38 = $0.9474 ≈ $0.95
- Casino sells bet for $1.00 → casino edge = $0.05 per bet (5.26%)

### Theoretical Value

**Definition**: The price at which you break even in the long run = present value of the expected value.

```
Theoretical Value = Expected Value / (1 + r × t)
```

**Key**: Must discount for time value of money. If you win but get paid in 2 months:
```
TV = $0.95 / (1 + 0.12 × 2/12) ≈ $0.93
```

### From Theory to Option Pricing

**Step-by-step model construction**:

1. **Propose possible prices at expiration** for the underlying
2. **Assign probabilities** to each price such that the expected value = forward price (arbitrage-free condition)
3. **Calculate expected value of the option**: for each possible price, compute intrinsic value, multiply by probability, sum
4. **Discount to present value** (if stock-type settlement)

**Call expected value formula**:
```
E[Call] = Σ max(0, S_i − X) × p_i
```

**Put expected value formula**:
```
E[Put] = Σ max(0, X − S_i) × p_i
```

**Example with 5 equal-probability prices** ($80, $90, $100, $110, $120, each 20%):
- E[underlying] = $100
- E[100 call] = 0.20×0 + 0.20×0 + 0.20×0 + 0.20×10 + 0.20×20 = $6.00

**With realistic probability distribution** (more weight near current price):
- Probabilities: 10%, 20%, 40%, 20%, 10% for $80, $90, $100, $110, $120
- E[100 call] = 0×0 + 0.20×0 + 0×0 + 0.20×10 + 0.10×20 = $4.00

### The Forward Price is the Expected Value

**Critical assumption**: In an arbitrage-free market, the expected value of the underlying at expiration equals the forward price.

```
E[S_T] = F = S × (1 + r × t) − dividends
```

- If it weren't, arbitrageurs would trade until it was
- Probabilities should be centered around the forward price, not the spot price
- The forward price incorporates cost of carry

**Example**: Stock at $100, no dividends, r=12%, t=2 months:
```
F = $100 × (1 + 0.12 × 2/12) = $102
```
Center probabilities around $102, not $100.

### At-the-Money vs. At-the-Forward

- **At-the-money (ATM)**: exercise price = current spot price
- **At-the-forward (ATF)**: exercise price = forward price at expiration
- ATF options are the most actively traded and used as benchmarks
- For European options, the forward price matters more than the spot price

### The Black-Scholes Model

**History**: Published 1973 by Fischer Black & Myron Scholes. Built on Bachelier (1900). Variants:
- **Original B-S**: European options on non-dividend-paying stocks
- **Modified B-S**: Added dividend component
- **Black model** (1976): Options on futures
- **Garman-Kohlhagen** (1983): Options on foreign currencies

All variants are structurally identical — they differ only in how they compute the forward price and handle settlement.

### Five Required Inputs

| Input | Source | Variability |
|-------|--------|-------------|
| 1. Exercise price | Contract spec | Fixed — never changes |
| 2. Time to expiration | Contract spec / calendar | Fixed date, but shrinks daily |
| 3. Underlying price | Market | Observable but ambiguous (bid/ask) |
| 4. Interest rate | Market | Observable, least important input |
| 5. **Volatility** | Estimated | **Most important, most difficult** |

### Input Details

**Exercise Price**: Fixed by contract. Never varies.

**Time to Expiration**: 
- Enter as annualized: days/365
- Business days matter for price movement, calendar days for interest
- The model handles the reconciliation internally
- Close to expiration: model becomes less reliable. Many traders stop using it near expiry.
- Can use finer increments (hours, minutes) near expiration

**Underlying Price**:
- Use bid-ask midpoint for liquid markets
- For hedging decisions: use the price where you can actually execute the hedge
  - Buying calls/selling puts (long market) → hedge by selling → use **bid price**
  - Selling calls/buying puts (short market) → hedge by buying → use **ask price**
- Illiquid markets: give extra thought to what price is achievable

**Interest Rates**:
- Textbooks say "risk-free rate" (government securities)
- Practice: use LIBOR or Eurocurrency rates
- Least important input for most positions
- Affects both forward price AND present value of the option
- Two roles: (1) forward price calculation, (2) discounting the option value
- Foreign currency options need TWO rates (domestic and foreign)

**Dividends** (stock options only):
- Must estimate amount and ex-dividend date
- Reduces forward price → reduces call value, increases put value
- Companies usually maintain past dividend policy, but no guarantee
- If ex-div date falls just before vs. just after expiration → significant impact

**Volatility**: 
- Most important and most difficult input
- Related to speed of market / probability distribution width
- Detailed treatment in Chapter 6

### The Riskless Hedge Concept

**Core idea**: For every option position, there exists a theoretically equivalent position in the underlying that offsets price risk.

**Hedge ratio** = the proportion of underlying contracts needed to create a riskless hedge.

| Option Position | Market Bias | Hedge Action |
|----------------|-------------|--------------|
| Buy calls | Long | Sell underlying |
| Sell calls | Short | Buy underlying |
| Buy puts | Short | Buy underlying |
| Sell puts | Long | Sell underlying |

**Memory aid**: 
- Calls: always do the OPPOSITE with the underlying (buy calls → sell underlying)
- Puts: always do the SAME with the underlying (buy puts → buy underlying)

**Why hedge?** As the underlying price changes, the probability distribution changes. By continuously adjusting the hedge, you're accounting for these shifting probabilities. This is **dynamic hedging** (covered in detail in Chapter 8).

### Option as a Substitute for the Underlying

- A call is a substitute for a long position
- A put is a substitute for a short position
- Whether the substitute is better depends on theoretical value vs. market price
- Buy calls below theoretical value → better than buying stock (in the long run)
- Sell puts above theoretical value → better than buying stock (in the long run)

### The Model as a Candle (Natenberg's Metaphor)

The pricing model is like a candle in a dark room:
- Better than groping in the dark (no model at all)
- But doesn't illuminate every detail
- Flickering distorts some of what you see
- As position size grows, distortions become more dangerous
- **Use the model, but know its limitations**

---

## Key Formulas Summary

| Formula | Expression |
|---------|-----------|
| Forward price (commodity) | `F = S × (1 + r × t) + storage + insurance` |
| Forward price (stock) | `F = S × (1 + r × t) − dividends` |
| Forward price (FX) | `F = S × (1 + r_d × t) / (1 + r_f × t)` |
| Borrowing cost | `r_long − r_short = r_borrow_cost` |
| Intrinsic value (call) | `max(0, S − X)` |
| Intrinsic value (put) | `max(0, X − S)` |
| Time value | `option_price − intrinsic_value` |
| Call breakeven | `X + premium` |
| Put breakeven | `X − premium` |
| Expected value | `Σ (p_i × outcome_i)` |
| Theoretical value | `PV(expected value) = E[V] / (1 + r × t)` |
| Call expected value | `Σ max(0, S_i − X) × p_i` |
| Put expected value | `Σ max(0, X − S_i) × p_i` |
| Arbitrage-free condition | `E[S_T] = Forward Price` |

---

## Implementation Notes for Trading System

1. **Forward price calculation** is the foundation — get this right first. Need: spot price, interest rate, dividends, time to expiration.

2. **Settlement type matters** for cash-flow modeling: stock-type options tie up capital (full premium); futures-type don't.

3. **The forward price, not spot, should center all probability distributions** when pricing options.

4. **Underlying price for modeling**: use bid for long-market hedges, ask for short-market hedges, midpoint for liquid markets.

5. **Interest rates**: LIBOR/risk-free rate. Least important input but still needed. For Indian markets: use RBI repo rate or MIBOR.

6. **Time to expiration**: can use calendar days/365. Near expiration (< 5 days), model reliability degrades significantly.

7. **Parity graph slope analysis** is a fast way to understand any multi-leg position's risk profile at expiration.
