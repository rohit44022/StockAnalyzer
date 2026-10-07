# Natenberg — Part 3: Spreads, Arbitrage & Early Exercise (Ch 10–16)

> **Source**: *Option Volatility and Pricing*, Sheldon Natenberg, 2nd ed.
> **Scope**: Chapters 10–16 (lines 2614–5120 of extracted text)
> **Purpose**: Sole reference for building a production-grade options system. Every formula, rule, and decision criterion is here so future sessions never re-read the book.

---

## Chapter 10 — Introduction to Spreading

### What Is a Spread?

A spread is the simultaneous purchase and sale of related instruments where a change in the value of one instrument is at least partially offset by a change in the value of another. The goal is to profit from the **price relationship** between contracts, not from directional moves.

### Why Spread?

1. **Risk reduction**: Offsetting positions reduce exposure to large market moves.
2. **Market neutrality**: A well-constructed spread can isolate a single variable (e.g., volatility) from the others (direction, time).
3. **Profit from mispricing**: If the model says an option is overpriced, selling it naked exposes you to unlimited risk; spreading lets you sell the overpriced option while buying a correctly-priced (or underpriced) one as a hedge.

### Option Spreads

Every option spread involves contracts that differ in at least one of:
- **Exercise price** (vertical spread)
- **Expiration date** (calendar/horizontal spread)
- **Type** (call vs. put)
- **Underlying** (inter-market spread)

A common categorization:
- **Volatility spreads** → profit from volatility being different from what the market implies
- **Directional spreads** → profit from a move in the underlying price
- **Arbitrage spreads** → lock in a riskless (or near-riskless) profit from mispricing

### Spread Mechanics

- A spread requires **two or more legs**, each of which is a buy or sell of an option.
- The **net premium** (debit or credit) is the cash flow at trade initiation.
- Greeks of a spread = sum of Greeks of individual legs (with sign: long = positive, short = negative).

---

## Chapter 11 — Volatility Spreads

### Core Principle

Volatility spreads are designed to **profit from a difference between implied volatility and the trader's forecast of future realized volatility**, while remaining as market-neutral as possible.

- If you think volatility will be **higher** than implied → buy volatility (positive gamma, positive vega)
- If you think volatility will be **lower** than implied → sell volatility (negative gamma, negative vega)

### Strategy Catalog

#### 1. Straddle
- **Construction**: Buy (or sell) a call and put at the same exercise price and expiration.
- **Long straddle**: +call +put → positive gamma, positive vega, negative theta.
- **Short straddle**: −call −put → negative gamma, negative vega, positive theta.
- **Delta**: Approximately delta-neutral when the exercise price equals the forward price.
- **Max loss** (long): total premium paid.
- **Max loss** (short): unlimited.
- **Use case**: You expect a large move (long) or minimal move (short); you don't know direction.

#### 2. Strangle
- **Construction**: Buy (or sell) a call and put at different exercise prices (both OTM).
- **Long strangle**: cheaper than a straddle but needs a bigger move to profit.
- **Short strangle**: lower premium collected, wider breakeven range.
- **Greeks**: Same sign pattern as straddle but smaller magnitude.
- **Use case**: Like a straddle but cheaper entry; you're betting on a very large move or very quiet market.

#### 3. Butterfly
- **Construction**: Buy 1 low-strike option, sell 2 middle-strike options, buy 1 high-strike option. All same expiration. Equal spacing between strikes.
- **Long butterfly**: Profit from low volatility. Max profit at the middle strike at expiration.
- **Short butterfly**: Profit from high volatility. Same payoff as a long strangle (limited risk).
- **Cost**: Always a debit for the long butterfly (credit for short).
- **Gamma**: Long butterfly has negative gamma near the middle strike.
- **Vega**: Long butterfly has negative vega (wants vol to fall).
- **Use case**: Pinning bet — you expect the underlying to stay near a specific price.

#### 4. Condor
- **Construction**: Buy 1 option at strike A, sell 1 at B, sell 1 at C, buy 1 at D (A < B < C < D), all same expiration.
- **Like a butterfly** but with a wider profitable zone (the "body" has two different strikes).
- **Long condor**: Profit from low volatility; wider but shallower profit zone than a butterfly.
- **Short condor**: Profit from high volatility.

#### 5. Ratio Spread (Ratio Vertical Spread)
- **Construction**: Buy N options at one strike, sell M options at another (N ≠ M).
- **Example call ratio spread**: Buy 1 lower-strike call, sell 2 higher-strike calls (1:2 ratio).
- **Delta**: Can be made delta-neutral by choosing the right ratio.
- **Risk profile**: Typically one-sided unlimited risk (the side with the extra short options).
- **Positive ratio spread** (buy fewer, sell more): Credit spread, negative gamma, negative vega.
- **Negative ratio spread** (buy more, sell fewer): Debit spread, positive gamma, positive vega (backspread).

**Ratio formula (delta-neutral)**:
```
Ratio = Δ(option bought) / Δ(option sold)
```
For a 1:2 call ratio spread to be delta-neutral:
```
1 × Δ(lower call) = 2 × Δ(higher call)
Δ(lower call) / Δ(higher call) = 2
```

#### 6. Christmas Tree (Ladder)
- **Construction**: Buy 1 option at one strike, sell 1 each at two different further-OTM strikes.
- Equivalent to a ratio spread with one of the short options further out.
- Reduces the extreme risk of a ratio spread at the cost of giving up some premium.

#### 7. Calendar Spread (Time Spread / Horizontal Spread)
- **Construction**: Sell a short-term option, buy a longer-term option, same strike and type.
- **Long calendar**: positive theta (short-term option decays faster), positive vega (longer-term option has more vega), approximately delta-neutral.
- **Profit mechanism**: Time decay differential. The short-term option decays faster, so the spread widens as time passes (if spot stays near the strike).
- **Risk**: Large move in the underlying collapses the spread (both options go deep ITM or OTM, time value difference shrinks).
- **Max profit**: At expiration of the short-term option, with spot at the strike.
- **Effect of volatility changes**: Rising implied vol helps (positive vega overall). But **watch for term structure effects**: if near-term vol rises more than far-term vol, the trade can lose even though "vol went up."

**Key formula — calendar spread value approximation**:
```
Calendar spread value ≈ vega_long × IV_long - vega_short × IV_short + theta_short × t_remaining_short
```

#### 8. Time Butterfly
- **Construction**: A butterfly across expirations. Buy 1 short-term, sell 2 medium-term, buy 1 long-term, all same strike.
- Isolates the **curvature of the term structure** of implied volatility.

#### 9. Diagonal Spread
- **Construction**: Options differ in both strike **and** expiration.
- Combines characteristics of vertical and calendar spreads.
- More complex Greeks; can be tailored to a specific view on direction + time decay.

### Choosing a Volatility Spread

Decision factors:
1. **Magnitude of edge**: How far is implied vol from your forecast?
2. **Gamma vs. vega exposure**: Do you want to profit from realized vol (gamma) or from IV changes (vega)?
3. **Risk tolerance**: Unlimited-risk strategies (naked straddles, ratio spreads) vs. limited-risk (butterflies, condors).
4. **Capital requirements**: Debit spreads tie up less margin than naked short positions.

**Rule of thumb**: The more legs in a spread, the narrower the profitable range but the lower the risk.

### Adjustments

When the underlying moves, a volatility spread's delta changes. **Adjustments** bring the position back to delta-neutral:
- **Trade the underlying**: Buy/sell shares or futures to offset delta. Simple, liquid, but converts the spread into a partially directional bet on the adjustment price.
- **Trade options**: Buy/sell additional options to offset delta. Also adjusts gamma and vega, which may or may not be desirable.
- **Do nothing**: Accept temporary delta exposure, trusting the vol view to hold over time.

**Adjustment frequency tradeoff**:
- Frequent adjustments → more transaction costs, but position stays closer to market-neutral.
- Infrequent adjustments → lower costs, but larger directional risk between adjustments.

---

## Chapter 12 — Bull and Bear Spreads

### Directional Strategies

These spreads profit primarily from **directional movement** in the underlying, not from changes in volatility.

### Naked Positions

The simplest directional trade: buy a call (bullish) or buy a put (bearish). Risk is limited to premium paid; reward is theoretically unlimited.

**Choosing which option to buy**:
- Deep ITM options behave like the underlying (delta near 100, low gamma, low vega) → expensive, low leverage, less vol risk.
- ATM options have the highest gamma and vega → most sensitive to short-term moves and IV changes.
- Deep OTM options are cheap but have low delta → need a large move to profit, very sensitive to vol changes.

### Bull and Bear Ratio Spreads

Add a directional bias to a volatility spread:
- **Bull ratio spread**: More long calls than short calls at a higher strike (or equivalently, more short puts than long puts at a lower strike).
- **Bear ratio spread**: The reverse.

These have **both a volatility view AND a directional view**.

### Vertical Spreads (Bull Spread / Bear Spread)

- **Bull call spread**: Buy a lower-strike call, sell a higher-strike call (same expiration). Debit spread.
- **Bear call spread**: Sell a lower-strike call, buy a higher-strike call. Credit spread.
- **Bull put spread**: Sell a higher-strike put, buy a lower-strike put. Credit spread.
- **Bear put spread**: Buy a higher-strike put, sell a lower-strike put. Debit spread.

**Key properties**:
- **Limited risk, limited reward** in all cases.
- Max profit = difference between strikes minus net debit (for debit spreads), or net credit (for credit spreads).
- Max loss = net debit (debit spreads), or difference between strikes minus net credit (credit spreads).
- A bull call spread has the **same payoff** as a bull put spread at the same strikes (via put-call parity).

**Delta of a vertical spread**: Always between 0 and 100. A bull spread has positive delta; a bear spread has negative delta.

**Gamma/Theta/Vega of a vertical spread**: Small and depend on whether the spread is ATM, ITM, or OTM. An ATM vertical spread has near-zero gamma, theta, and vega (the bought and sold options roughly offset).

### Implied Volatility and Strike Selection

**Critical rule for vertical spreads**:

When implied volatility is **high**:
- Sell call or put spreads (credit spreads).
- The overpriced premium benefits the seller.
- High IV inflates the sold option more than the bought option (in dollar terms).

When implied volatility is **low**:
- Buy call or put spreads (debit spreads).
- The underpriced premium benefits the buyer.
- Low IV makes the debit cheaper than theoretically fair.

**The reasoning**: A bull spread can be decomposed into a long underlying position + a short ratio spread. If IV is high, the short ratio spread component (which is short vol) adds value. If IV is low, the long ratio spread component (long vol) adds value.

**Practical selection rules**:
- **Bullish + high IV** → sell a bull put spread (credit).
- **Bullish + low IV** → buy a bull call spread (debit).
- **Bearish + high IV** → sell a bear call spread (credit).
- **Bearish + low IV** → buy a bear put spread (debit).

---

## Chapter 13 — Risk Considerations

### Practical Risk Management for Spreads

After constructing a spread, a trader must continuously evaluate risk exposure across multiple dimensions.

### How Much Margin for Error?

The trader's edge comes from the difference between their volatility estimate and implied volatility. But no estimate is perfect.

**Key question**: How wrong can the volatility estimate be before the trade loses money?

For a volatility spread, this is the **breakeven volatility** — the realized volatility at which the spread breaks even after accounting for all costs.

### Volatility Risk

For a spread that's **long gamma, long vega** (e.g., long straddle):
- **Rising realized vol**: Gamma profits from rebalancing exceed theta decay → profit.
- **Falling realized vol**: Theta decay exceeds gamma profits → loss.
- **Rising implied vol**: Vega profit → mark-to-market gain.
- **Falling implied vol**: Vega loss → mark-to-market loss.

For a **short gamma, short vega** spread (e.g., short straddle): the reverse.

### The Gamma/Theta Ratio (Efficiency)

```
Efficiency = Gamma / Theta
```

This measures how much gamma (rebalancing profit potential) you get per unit of theta (time decay cost).

- Higher ratio → more efficient use of capital.
- Compare this ratio across different spread constructions to find the best way to express a volatility view.

**For delta-neutral spreads**:
- A straddle typically has a lower efficiency ratio than a strangle (you pay more theta relative to gamma).
- A butterfly has very high efficiency near the center strike but almost zero everywhere else.

### Practical Considerations

1. **Transaction costs**: More legs = more execution cost. The theoretical edge must exceed round-trip costs.
2. **Bid-ask spread**: Each leg contributes its own bid-ask cost. Total slippage can erode a thin edge.
3. **Liquidity**: Illiquid options may be mispriced, but you can't trade the theoretical value if the market isn't there.
4. **Margin requirements**: Some strategies (naked shorts) require substantial margin that affects return on capital.
5. **Model risk**: All Greeks are model-dependent. If the model is wrong (e.g., assumes lognormal when the actual distribution has fat tails), the Greeks are wrong.

### Adjustment Strategies

When a position drifts from its intended Greeks:

1. **Delta adjustment**: The most common. Trade the underlying or options to bring delta back to target.
2. **Gamma adjustment**: Roll strikes — e.g., if short gamma grew too large, buy some OTM options.
3. **Vega adjustment**: Roll expirations — e.g., if you want less vega exposure, sell some longer-dated options.
4. **Theta adjustment**: Reduce position size if time decay is too costly.

**Key principle**: Every adjustment changes multiple Greeks simultaneously. You can't fix one without affecting others. Prioritize the Greek that poses the greatest immediate risk.

### When to Adjust vs. When to Close

- **Adjust** when the edge (vol view) still holds but the Greeks have drifted.
- **Close** when the edge is gone (vol reverted to your forecast, or you were wrong).
- **Do nothing** when the Greeks are within acceptable bounds and costs of adjustment exceed the risk reduction.

---

## Chapter 14 — Synthetics

### The Synthetic Triangle

Any two of the three instruments {Call, Put, Underlying} can replicate the third:

```
Call = Put + Underlying
Put = Call − Underlying
Underlying = Call − Put
```

More precisely (using forward prices):

```
Synthetic long underlying  = Long call + Short put (same strike, same expiration)
Synthetic short underlying = Short call + Long put
Synthetic long call        = Long put + Long underlying
Synthetic short call       = Short put + Short underlying
Synthetic long put         = Long call + Short underlying
Synthetic short put        = Short call + Long underlying
```

### Put-Call Parity

The fundamental pricing relationship that links calls, puts, and the underlying:

**For futures options**:
```
C − P = (F − X) / (1 + r × t)
```

**For stock options**:
```
C − P = S − X / (1 + r × t) + D
```
Or equivalently:
```
C − P = S − PV(X) − PV(dividends)
```

Where:
- C = call price, P = put price
- F = futures price, S = stock price
- X = exercise price
- r = risk-free interest rate
- t = time to expiration (in years)
- D = present value of dividends

**Implications**:
- If put-call parity is violated, an arbitrage opportunity exists.
- The forward price F implied by options (the strike where C = P) tells you the market's cost-of-carry assumptions.

### Synthetic Equivalences for Complex Strategies

Any spread has a synthetic equivalent. Replace any leg with its synthetic and simplify:

**Iron Butterfly** = Short straddle + Long strangle (same as long butterfly via synthetics):
```
Sell ATM call + Sell ATM put + Buy OTM call + Buy OTM put
= Long butterfly (same strikes)
```

**Iron Condor** = Short strangle + Long wider strangle (same as long condor via synthetics).

**Key identity**:
```
Iron butterfly value + Butterfly value = PV(distance between strikes)
```

### Three Ways to Execute Any Spread

Because every contract has a synthetic equivalent, any N-leg spread can be executed in at least three ways. Example — buying a straddle:

1. Buy call + Buy put (standard)
2. Buy 2 calls + Sell underlying (synthetic put replaces the put)
3. Buy 2 puts + Buy underlying (synthetic call replaces the call)

**Why this matters**: One execution method may be cheaper due to bid-ask spread differences. Always check synthetic alternatives for better pricing.

### Using Synthetics in Spreading

When considering a volatility spread, check whether executing some legs synthetically gives a better price. The savings come from exploiting small discrepancies in bid-ask spreads across the synthetic triangle.

**Example from the text**: Buying a 50 straddle outright costs 6.60, but buying 2 puts + stock (synthetic call + real put) costs 6.55 — a savings of 0.05.

**Important**: This is NOT an arbitrage. The bid-ask spreads prevent riskless profit from conversions/reversals. But the small inefficiency can make a volatility spread slightly cheaper via the synthetic route.

---

## Chapter 15 — Option Arbitrage

### Conversions and Reversals

**Conversion**: Sell call + Buy put + Buy underlying (at the same strike and expiration).
- Locks in a riskless position: the synthetic short underlying (−call +put) exactly offsets the long underlying.
- Profit/loss determined entirely by the pricing of the synthetic vs. the actual underlying.

**Reversal** (Reverse Conversion): Buy call + Sell put + Sell underlying.
- The opposite of a conversion.

**Pricing relationships**:

For futures options (stock-type settlement):
```
Conversion/Reversal value = (F − X) / (1 + r × t)
= Call price − Put price
```

For futures options (futures-type settlement):
```
Conversion/Reversal value = F − X
= Call price − Put price
```

For stock options:
```
Conversion/Reversal value = S − X / (1 + r × t) − D
= Call price − Put price
```

Where D = present value of expected dividends.

**Practical note**: In most markets, conversions/reversals trade at very tight margins. Only professional traders with low transaction costs can profit from them. The edge is typically a few cents.

### Risks in Seemingly Riskless Positions

Even "riskless" arbitrage strategies carry risks:

#### 1. Pin Risk
- At expiration, if the underlying is **exactly at the strike price**, the trader doesn't know whether the short option will be exercised.
- If assigned, the trader has an unhedged position. If not assigned, the position also becomes unhedged.
- Most dangerous with stock options where exercise decisions are made overnight.

#### 2. Settlement Risk
- Futures options that are subject to stock-type settlement may settle at different times for the option vs. the underlying.
- A conversion/reversal that should be riskless can generate unexpected cash flows if settlement timing differs.

#### 3. Interest Rate Risk
- Cash flows from the arbitrage (premium received/paid, margin requirements) earn or cost interest.
- If interest rates change during the life of the position, the actual profit may differ from the expected profit.
- Especially relevant for stock options where the exercise price (carried as cash) earns interest.

#### 4. Dividend Risk (Stock Options)
- The conversion/reversal value depends on expected dividends.
- If the company changes its dividend (increases, decreases, omits), the position gains or loses.
- **This is a real risk**: dividend announcements are uncertain, and the market's expectation may differ from reality.

### Boxes

A box is a combination of a bull spread and a bear spread (or equivalently, a conversion at one strike and a reversal at another strike).

**Construction**:
```
Long X₁/X₂ box = Long X₁ call + Short X₂ call + Short X₁ put + Long X₂ put
```
(where X₁ < X₂)

**Value** (European options):
```
Box value = (X₂ − X₁) / (1 + r × t)
```
The box is worth the present value of the difference between strikes, regardless of where the underlying trades. It's essentially a loan/bond.

**Arbitrage**: If the box trades at a price different from PV(X₂ − X₁), there's an arbitrage. Buy the box if it's cheap; sell if it's expensive.

**Practical use**: Boxes are useful for:
- Checking market consistency (are option prices internally consistent?).
- Financing positions (a long box is like lending money; a short box is like borrowing).

### Rolls (Jelly Rolls)

A roll (or jelly roll) is the combination of a long calendar spread (calls) and a short calendar spread (puts) at the same strike:

**Construction**:
```
Long roll = Long call calendar (sell near, buy far) + Short put calendar (buy near, sell far)
```
At the same strike.

Equivalently: a conversion in one expiration + a reversal in another expiration at the same strike.

**Value** (stock options):
```
Roll value = (r₂t₂ − r₁t₁) × X − (D₂ − D₁)
```
Where subscripts 1 and 2 refer to near and far expirations, and D is dividends between now and each expiration.

For futures options (stock-type settlement):
```
Roll value = [(F₂ − X) / (1 + r₂t₂)] − [(F₁ − X) / (1 + r₁t₁)]
```

**Practical use**:
- Rolls capture the **cost of carry differential** between two expirations.
- If a roll is mispriced, it implies a disagreement about dividends or interest rates.

### Time Boxes

A time box combines options at **different strikes AND different expirations**:
```
Time box = Box + Roll (or equivalently, conversion at one strike/expiration + reversal at different strike/expiration)
```

**Value**:
```
Time box = Long-term box value − Roll value
```
or equivalently:
```
Time box = Short-term box value − Roll value (at the other strike)
```

### Three-Way Arbitrage

When an option at one exchange can be arbitraged against options at another exchange or against the underlying at yet another venue. This is a more complex multi-leg arbitrage that requires simultaneous execution across markets.

### Summary of Arbitrage Relationships

| Strategy | Construction | Value (European) |
|----------|-------------|------------------|
| Conversion | −C + P + U | (F − X)/(1+rt) |
| Reversal | +C − P − U | −(F − X)/(1+rt) |
| Box (X₁/X₂) | Bull spread + Bear spread | (X₂ − X₁)/(1+rt) |
| Roll (t₁/t₂) | Call calendar − Put calendar | carry differential |
| Time Box | Box + Roll | composite |

---

## Chapter 16 — Early Exercise of American Options

### Three Key Questions

1. **When** might a trader exercise an American option before expiration?
2. **Is there an optimal time** to exercise early?
3. **How much more** is an American option worth compared to a European option?

### Fundamental Principle

For early exercise to be desirable, there must be an advantage to **holding the underlying** rather than the option. This advantage comes from:
- **Dividends** that stock owners receive but option holders do not.
- **Interest** that can be earned on the cash from exercising.

**If there are no dividend or interest considerations**:
```
Value of American option = Value of European option
```

This is the case for options on futures with futures-type settlement (no cash flows on either side).

### Arbitrage Boundaries

**Lower arbitrage boundary (American options)**:
```
American call ≥ max[0, S − X]  (at least intrinsic value)
American put  ≥ max[0, X − S]  (at least intrinsic value)
```

If an American option trades below intrinsic value, buy it, hedge with the underlying, and exercise immediately for a riskless profit.

**Lower arbitrage boundary (European options)**:

For futures options (stock-type settlement):
```
European call ≥ max[0, (F − X) / (1 + r × t)]
European put  ≥ max[0, (X − F) / (1 + r × t)]
```
The present value of intrinsic value — always less than intrinsic value.

For stock options:
```
European call ≥ max[0, S − X/(1+rt) − D]
European put  ≥ max[0, X/(1+rt) + D − S]
```
Where D = present value of dividends.

**Combined (American = at least as much as European)**:
```
American call ≥ max[0, S − X, (F − X)/(1 + r × t)]
American put  ≥ max[0, X − S, (X − F)/(1 + r × t)]
```

**Upper arbitrage boundaries**:
```
American put  ≤ X
European put  ≤ X / (1 + r × t)
American call ≤ S
European call ≤ S − D  (stock options)
European call ≤ F / (1 + r × t)  (futures options, stock-type settlement)
```

### Early Exercise of Calls on Stock

**Component breakdown**:
```
Call value = intrinsic value + volatility value + interest value − dividend value
```

- **Volatility value**: The protective value of the call (limited downside). Estimated by the price of the companion put at the same strike.
- **Interest value**: Interest saved by holding the call instead of buying stock. ≈ X × r × t (interest on the exercise price).
- **Dividend value**: Total dividends the stock pays over the option's life.

**Early exercise condition (calls on stock)**:
```
Dividend value > Volatility value + Interest value
```

When this holds, the European option would trade below intrinsic value, but the American option holder can capture intrinsic value by exercising.

**Optimal exercise timing for calls on stock**:

**Exercise ONLY on the day before the ex-dividend date.** On any other day, exercising early gives up volatility value and interest value for no benefit (you don't collect a dividend). Since you always lose volatility value and interest value by exercising, the only time the trade is worthwhile is when you capture a dividend that exceeds those losses.

**Corollary**: If a stock pays NO dividend during the option's life, there is NEVER a reason to exercise an American call early.

**Worked example from text**:
```
Stock = 100, Time = 1 month, Rate = 6%, Dividend = 0.75 (in 15 days)
90 put trading at 0.20

Interest cost = 90 × 0.06 × 1/12 = 0.45
Dividend (0.75) > Volatility value (0.20) + Interest (0.45) = 0.65
→ 90 call IS an early exercise candidate (gain = 0.10)
```

### Early Exercise of Puts on Stock

**Component breakdown**:
```
Put value = intrinsic value + volatility value − interest value + dividend value
```

- **Volatility value**: Estimated by the companion OTM call price.
- **Interest value**: Interest earned on the exercise price if exercised. ≈ X × r × t.
- **Dividend value**: Total dividends over the option's life.

**Early exercise condition (puts on stock)**:
```
Interest value > Volatility value + Dividend value
```

**Optimal exercise timing for puts on stock**:

Unlike calls, a put can potentially be exercised on **any day**, not just around dividend dates. Early exercise is optimal when the daily interest earned exceeds the daily volatility value lost.

**However**, there is a **blackout period** around dividend payments. A trader should NOT exercise a put if the dividend will be paid within:
```
Blackout days = Dividend / (X × r / 365)
```
During this period, the dividend the trader would forfeit (by being short stock after exercising the put) exceeds the interest earned.

**Optimal exercise day for puts**: The day the stock pays the dividend (to collect the dividend first, then exercise). After the dividend, interest accrual without upcoming dividend loss makes exercise attractive.

**Worked example from text**:
```
Stock = 100, Time = 2 months, Rate = 6%, Dividend = 0.40
120 call trading at 0.55

Interest earned = 120 × 0.06 × 1/6 = 1.20
Interest (1.20) > Volatility value (0.55) + Dividend (0.40) = 0.95
→ 120 put IS an early exercise candidate (gain = 0.25)

Daily interest = 120 × 0.06 / 365 = 0.02
Blackout = 0.40 / 0.02 = 20 days
→ Do NOT exercise within 20 days of the dividend payment
```

### Impact of Short Stock on Early Exercise

- **Short stock** reduces the effective interest rate (due to borrowing costs).
- Lower rate → **calls MORE likely** to be exercised early (less interest is lost).
- Lower rate → **puts LESS likely** to be exercised early (less interest is earned).

**General rule**: Whenever possible, avoid a short stock position. Exercise of a call reduces short stock (good); exercise of a put creates short stock (bad).

### Early Exercise of Options on Futures

For futures options to have early exercise value, they must be subject to **stock-type settlement** (as in the US). Under futures-type settlement, no cash flows occur, so there's no early exercise value.

**Early exercise condition (futures options, stock-type settlement)**:
```
Interest on intrinsic value > Volatility value
```

Interest on intrinsic value:
- Call: (F − X) × r × t
- Put: (X − F) × r × t

**Optimal timing**: Exercise when daily interest > daily theta of the companion OTM option.

**Worked example**:
```
Futures = 100, Time = 3 months, Rate = 8%
80 put price = 0.15

Interest on intrinsic = (100 − 80) × 0.08 × 3/12 = 0.40
Interest (0.40) > Vol value (0.15) → candidate (gain = 0.25)

Daily interest = 20 × 0.08/365 = 0.0044
80 put theta = −0.0046 (from Black-Scholes at IV 24.68%)
→ Daily theta (0.0046) > Daily interest (0.0044)
→ NOT an immediate exercise candidate; wait ~4 days until theta < 0.0044
```

**The term "fugit"**: The expected number of days until an American option becomes an immediate early exercise candidate.

### Protective Value and Early Exercise

Exercising an option = giving up its protective value = synthetically selling the companion OTM option.

**Example**: Exercising a 90 call is equivalent to selling the 90 put. If the early exercise gain is 0.10, you're effectively selling the 90 put at its market price + 0.10.

**Hedge**: A trader who exercises early can simultaneously buy the companion OTM option to retain protection. If IV is low, this is cheap and worthwhile. If IV is high, it's expensive and the trader may skip it.

### Pricing American Options

**Black-Scholes** is a European model — it cannot value American options.

**Approximation methods** (historical):
- For calls on dividend-paying stock: Compare Black-Scholes value assuming (a) the option expires the day before ex-dividend and (b) the option expires normally but stock price is reduced by the dividend. Take the higher value.
- For ITM puts and futures options: Set the theoretical value to at least parity (intrinsic value).

**True American pricing models**:

1. **Cox-Ross-Rubinstein (Binomial) Model** (1979):
   - Iterative (loop-based), not closed-form.
   - Easy to understand; builds a tree of possible prices.
   - More iterations → closer to true American value.
   - **Preferred for dividend-paying stocks** because it handles lump-sum dividends naturally.
   - Also specifies optimal early exercise points.

2. **Barone-Adesi-Whaley (Quadratic) Model** (1987):
   - More complex math but converges faster than binomial.
   - **Limitation**: Treats all cash flows as continuous interest payments (not lump-sum dividends).
   - Better for futures options and non-dividend stocks.

**American vs. European value difference**:
- Difference increases as the option goes **deeper ITM** (more likely to be exercised).
- Difference decreases with **higher volatility** (more valuable to keep the option alive).
- For stock options: the maximum difference approaches `Dividend − Interest on X × remaining time`.
- For futures options: difference increases continuously with depth in the money (interest on intrinsic value grows linearly).

### American Option Deltas

For European options: call delta + |put delta| = 100 (at the same strike).

For American options: call delta + |put delta| **can exceed 100** because deeply ITM American options reach delta 100 faster than European options, while the companion OTM option still has residual delta.

**Impact on arbitrage**: Conversions, reversals, and boxes that are delta-neutral with European options may **not** be delta-neutral with American options. For large positions, this delta discrepancy can create material risk.

### American Box Values

An American box can have a value different from PV(X₂ − X₁) depending on which options are early exercise candidates.

**Five cases for a 100/110 box (stock, dividend = 0.60 in 9 days, rate = 6%, 24 days to expiry)**:

| Case | Exercised Options | Approx Box Value |
|------|------------------|-----------------|
| Both puts exercised | 100P, 110P | 9.985 |
| Both calls exercised | 100C, 110C | 9.986 |
| Only 110 put exercised | 110P | 10.231 |
| Only 100 call exercised | 100C | 10.297 |
| 100 call + 110 put exercised | 100C, 110P | 10.568 |

The max box value occurs when both the lower-strike call and higher-strike put are exercised early (stock price near 105, low vol).

### Early Exercise Strategies (Trading Tactics)

#### Dividend Play
1. Sell deeply ITM calls + Buy stock before ex-dividend date.
2. If assigned (expected): break even.
3. If NOT assigned (someone failed to exercise): profit ≈ the dividend amount.
4. Works best in large open interest, less sophisticated markets.
5. Can also be executed via ITM call spreads: market-maker buys/sells at parity (both sides create the dividend play).

#### Interest Play
1. Sell stock + Sell deeply ITM puts.
2. If exercised (expected): break even.
3. If NOT exercised: earn interest on exercise price proceeds.
4. Also executable in futures markets via selling deeply ITM calls/puts + hedging with futures.

### Early Exercise Risk Management

**Key rule**: Early assignment should never be a surprise. Ask: "If I owned this option, would I logically exercise it now?" If yes, expect assignment.

- If assigned unexpectedly on an option that **should** have been exercised → someone made an error, and the assignment is actually a gift (you received value the other side threw away).
- **Cash squeeze risk**: Deep ITM short options getting assigned can generate large cash requirements. Maintain sufficient capital to handle assignment.

---

## Cross-Chapter Reference: Key Formulas

### Put-Call Parity
```
Futures:  C − P = (F − X) / (1 + r × t)          [stock-type settlement]
Futures:  C − P = F − X                            [futures-type settlement]
Stock:    C − P = S − X/(1+rt) − PV(D)
```

### Synthetic Positions
```
Synthetic Long Stock  = +Call −Put  (same strike)
Synthetic Long Call   = +Put  +Stock
Synthetic Long Put    = +Call −Stock
```

### Box Value
```
European Box = (X₂ − X₁) / (1 + r × t)
```

### Roll Value (Stock Options)
```
Roll = (r₂t₂ − r₁t₁) × X − (D₂ − D₁)
```

### Early Exercise Conditions
```
Call on stock:    Dividend > Put_companion + X × r × t
Put on stock:     X × r × t > Call_companion + Dividend
Futures option:   Intrinsic × r × t > Companion_OTM_price
```

### Arbitrage Boundaries (American)
```
Call ≥ max[0, S − X, (F − X)/(1+rt)]
Put  ≥ max[0, X − S, (X − F)/(1+rt)]
```

### Delta-Neutral Ratio
```
Ratio = Δ(bought option) / Δ(sold option)
```

### Efficiency Ratio
```
Efficiency = Gamma / Theta
```

---

## Cross-Chapter Reference: Decision Rules for System Building

### Spread Selection Decision Tree

```
1. What is your PRIMARY view?
   ├─ Volatility (no directional view) → Chapter 11 strategies
   │   ├─ Vol going UP   → Long straddle/strangle/backspread
   │   └─ Vol going DOWN → Short straddle/strangle, long butterfly/condor
   ├─ Direction (no vol view) → Chapter 12 strategies
   │   ├─ Bullish + High IV → Sell bull put spread (credit)
   │   ├─ Bullish + Low IV  → Buy bull call spread (debit)
   │   ├─ Bearish + High IV → Sell bear call spread (credit)
   │   └─ Bearish + Low IV  → Buy bear put spread (debit)
   └─ Both vol AND direction → Ratio spreads (Ch 11 + 12)
       ├─ Bullish + Vol UP   → Call backspread
       ├─ Bullish + Vol DOWN → Call ratio spread
       ├─ Bearish + Vol UP   → Put backspread
       └─ Bearish + Vol DOWN → Put ratio spread

2. Risk tolerance?
   ├─ Limited risk only → Verticals, butterflies, condors, backspreads
   └─ Can accept unlimited risk → Naked options, ratio spreads, straddles

3. Capital efficiency?
   ├─ Low capital → Credit spreads, iron condors, iron butterflies
   └─ Capital not constrained → Any strategy

4. Check synthetics (Ch 14):
   └─ Can any leg be executed synthetically for a better price?

5. Check arbitrage consistency (Ch 15):
   └─ Are put-call parity, box values, and roll values consistent?
```

### Early Exercise Monitoring (for American Options in Production)

```
For each short American option in the portfolio:
1. Calculate: Is it an early exercise candidate?
   - Calls on stock: Check dividend > put_price + interest_on_X
   - Puts on stock:  Check interest_on_X > call_price + dividend
   - Futures options: Check interest_on_intrinsic > companion_OTM_price

2. If yes: Is it an IMMEDIATE exercise candidate?
   - Calls: Is the ex-dividend date tomorrow?
   - Puts: Is daily interest > daily theta of companion call?
     AND are we outside the dividend blackout period?
   - Futures: Is daily interest > daily theta of companion option?

3. If assigned: Expect it. Maintain cash reserves for exercise price.
4. If NOT assigned when it should have been: You received a gift.
```

---

*Notes compiled from Natenberg Ch 10–16. All formulas, rules, and examples taken directly from the source text.*
