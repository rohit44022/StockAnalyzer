# Book 3: The Bible of Options Strategies (2nd ed) — Guy Cohen

## Book Purpose

Complete strategy encyclopedia: 58 options strategies organized by market outlook, with standardized entry/exit rules, risk profiles, margin requirements, and Cohen's proprietary OVI (Options Volatility Indicator) for stock selection. Every strategy follows the same template: Description → Context → Risk Profile → Greeks → Advantages/Disadvantages → Exiting → Margin → Example.

---

## Ch 1–3: Foundations & Directional/Income Strategies (lines 1–5499)

### 1. Options Fundamentals

- **Call** = right to buy; **Put** = right to sell
- **ITM/ATM/OTM** — intrinsic value exists only for ITM
- **Extrinsic (time) value** decays exponentially in final month
- **Greeks**: Delta (direction), Gamma (delta acceleration), Theta (time decay), Vega (volatility sensitivity), Rho (interest rate)
- **OVI** (Options Volatility Indicator): proprietary -1 to +1 indicator measuring options demand/supply; persistent positive = bullish smart money, persistent negative = bearish

### 2. Directional Strategies (Income)

| Strategy | Outlook | Construction | Risk | Reward | Time | Key Rule |
|---|---|---|---|---|---|---|
| **Long Call** | Bullish | Buy ATM/ITM call | Premium | Uncapped | 3+ months | OVI positive, ADV>500K |
| **Short (Naked) Call** | Bearish | Sell OTM call | Uncapped | Premium | ≤1 month | Margin required, high risk |
| **Long Put** | Bearish | Buy ATM/ITM put | Premium | Strike−premium | 3+ months | OVI negative |
| **Short (Naked) Put** | Bullish | Sell OTM put | Strike−premium | Premium | ≤1 month | Cash-secured preferred |
| **Covered Call** | Mildly bullish | Own stock + sell OTM call | Stock−premium | (Strike−stock)+premium | 1–2 months | Income strategy, sell monthly |
| **Covered Put** | Mildly bearish | Short stock + sell OTM put | Uncapped up | (Stock−strike)+premium | ≤1 month | Very risky, not recommended |

### 3. Spread Strategies

| Strategy | Outlook | Construction | Debit/Credit | Max Risk | Max Reward |
|---|---|---|---|---|---|
| **Bull Call Spread** | Bullish | Buy lower call, sell higher call | Debit | Net debit | Diff in strikes − debit |
| **Bull Put Spread** | Bullish | Buy lower put, sell higher put | Credit | Diff in strikes − credit | Net credit |
| **Bear Call Spread** | Bearish | Sell lower call, buy higher call | Credit | Diff in strikes − credit | Net credit |
| **Bear Put Spread** | Bearish | Buy higher put, sell lower put | Debit | Net debit | Diff in strikes − debit |

**Spread rules**: Same expiration, equal number of contracts each leg, bid/ask <4%.

### Calendar & Diagonal Spreads

| Strategy | Construction | Outlook | Key Point |
|---|---|---|---|
| **Calendar Call** | Buy long-term call, sell short-term call (same strike) | Neutral-bullish | Profit from time decay diff |
| **Calendar Put** | Buy long-term put, sell short-term put (same strike) | Neutral-bearish | Same concept with puts |
| **Diagonal Call** | Buy long-term call, sell short-term higher-strike call | Bullish | Calendar + directional bias |
| **Diagonal Put** | Buy long-term put, sell short-term lower-strike put | Bearish | Calendar + directional bias |

**Calendar/Diagonal rules**: NEVER hold short leg into final month. Use 3-month long leg minimum. Pre-earnings in-and-out works well for calendars.

### Covered Combinations

| Strategy | Construction | Risk |
|---|---|---|
| **Covered Short Straddle** | Own stock + sell ATM call + sell ATM put | High — uncapped downside |
| **Covered Short Strangle** | Own stock + sell OTM call + sell OTM put | High — uncapped downside |

### Ladders

| Strategy | Construction | Net Position | Risk |
|---|---|---|---|
| **Bull Call Ladder** | Buy 1 lower call, sell 1 middle call, sell 1 higher call | Credit | Uncapped above highest strike |
| **Bull Put Ladder** | Buy 1 lower put, sell 1 middle put, sell 1 higher put | Credit | Uncapped below lowest strike |
| **Bear Call Ladder** | Sell 1 lower call, buy 1 middle call, buy 1 higher call | Debit | Limited to debit paid |
| **Bear Put Ladder** | Sell 1 higher put, buy 1 middle put, buy 1 lower put | Debit | Limited to debit paid |

---

## Ch 4: Volatility Strategies (lines ~5000–6743)

Strategies that profit from large stock moves in either direction. You don't care about direction, only magnitude.

| Strategy | Construction | Cost | Max Risk | Max Reward | BE Points |
|---|---|---|---|---|---|
| **Long Straddle** | Buy ATM call + ATM put | Debit | Premium paid | Uncapped | Strike ± debit |
| **Long Strangle** | Buy OTM call + OTM put | Debit (cheaper) | Premium paid | Uncapped | Lower strike − debit, Higher strike + debit |
| **Strip** | Buy 1 ATM call + 2 ATM puts | Debit | Premium paid | Uncapped | Bearish bias: BE down = strike − (debit/2) |
| **Strap** | Buy 2 ATM calls + 1 ATM put | Debit | Premium paid | Uncapped | Bullish bias: BE up = strike + (debit/2) |
| **Guts** | Buy ITM call + ITM put | Expensive debit | Debit − strike diff | Uncapped | Very wide BEs; rarely traded |

### Volatility Strategy Rules (Cohen's 8 Pointers)

1. Stock price $15–$60 preferred (manageable premiums)
2. Bid/ask spread <4%
3. Check IV hasn't already spiked — want IV low relative to its own history
4. Buy with ≥3 months to expiration (2 months minimum)
5. Straddle cost < half of stock's recent high-low range (40/60/80 day lookback for 2/3/4 month options)
6. If playing earnings: exit within 2 weeks after the event
7. Look for consolidation/reversal chart patterns (compressed volatility)
8. Use dynamic trailing stop once one side is profitable

### Short Volatility Variants (credit strategies, capped reward)

| Strategy | Construction | Credit/Debit | Max Risk | Max Reward |
|---|---|---|---|---|
| **Short Call Butterfly** | Sell ITM call, buy 2 ATM calls, sell OTM call | Credit | Strike diff − credit | Net credit |
| **Short Put Butterfly** | Sell OTM put, buy 2 ATM puts, sell ITM put | Credit | Strike diff − credit | Net credit |
| **Short Call Condor** | Sell ITM call, buy lower-mid call, buy upper-mid call, sell OTM call | Credit | Strike diff − credit | Net credit |
| **Short Put Condor** | Sell OTM put, buy lower-mid put, buy upper-mid put, sell ITM put | Credit | Strike diff − credit | Net credit |
| **Short Iron Butterfly** | Sell OTM put, buy ATM put, buy ATM call, sell OTM call | Debit | Net debit | Strike diff − debit |
| **Short Iron Condor** | Sell OTM put, buy OTM put, buy OTM call, sell OTM call | Debit | Net debit | Strike diff − debit |

**Cohen's verdict on short butterflies/condors**: Not popular — tiny credit reward vs. large potential loss. Straddles and strangles are superior volatility plays.

---

## Ch 5: Rangebound Strategies (lines 6744–8060)

Strategies that profit when stock stays within a price range. **Never trade before earnings or news events.**

### Uncapped Risk (Not Recommended for Non-Experts)

| Strategy | Construction | Max Risk | Max Reward | Time | Cohen's View |
|---|---|---|---|---|---|
| **Short Straddle** | Sell ATM call + ATM put | Uncapped | Net credit | ≤1 month | "Not worth it" — one gap wipes years of gains |
| **Short Strangle** | Sell OTM call + OTM put | Uncapped | Net credit | ≤1 month | Wider BEs but same fundamental problem |
| **Short Guts** | Sell ITM call + ITM put | Uncapped | Net credit | ≤1 month | Prohibitively expensive, no advantage |

### Capped Risk Rangebound (Recommended)

| Strategy | Construction | Debit/Credit | Max Risk | Max Reward |
|---|---|---|---|---|
| **Long Call Butterfly** | Buy ITM call, sell 2 ATM calls, buy OTM call | Debit | Net debit | Strike diff − debit |
| **Long Put Butterfly** | Buy OTM put, sell 2 ATM puts, buy ITM put | Debit | Net debit | Strike diff − debit |
| **Long Call Condor** | Buy ITM call, sell lower-mid call, sell upper-mid call, buy OTM call | Debit | Net debit | Strike diff − debit |
| **Long Put Condor** | Buy OTM put, sell lower-mid put, sell upper-mid put, buy ITM put | Debit | Net debit | Strike diff − debit |
| **Long Iron Butterfly** | Sell OTM put, buy ATM put, buy ATM call, sell OTM call | Credit | Strike diff − credit | Net credit |
| **Long Iron Condor** | Sell OTM put, buy OTM put, sell OTM call, buy OTM call | Credit | Strike diff − credit | Net credit |

**Key insight**: Long iron butterfly = short straddle + protective wings (long strangle). Converts uncapped risk → capped risk at the cost of reduced max reward. Same logic: iron condor = short strangle + protective wings.

### Modified Butterflies

| Strategy | Adjustment | Effect |
|---|---|---|
| **Modified Call Butterfly** | OTM bought call moved closer to middle strike | Narrows width, creates bullish bias |
| **Modified Put Butterfly** | ITM bought put moved closer to middle strike | Narrows width, creates bullish bias |

---

## Ch 6: Leveraged Strategies — Ratio Spreads & Backspreads (lines 8060–8500)

| Strategy | Construction | Net Position | Risk | Best For |
|---|---|---|---|---|
| **Call Ratio Backspread** | Sell 1 ITM call, buy 2-3 OTM calls (2:1 or 3:2) | Net long options | Limited (to debit paid) | Bullish + volatility |
| **Put Ratio Backspread** | Sell 1 ITM put, buy 2-3 OTM puts (2:1 or 3:2) | Net long options | Limited (to debit paid) | Bearish + volatility |
| **Ratio Call Spread** | Buy 1 ITM call, sell 2-3 OTM calls (1:2 or 2:3) | Net short options | Uncapped upside | Neutral-bearish (NOT recommended) |
| **Ratio Put Spread** | Buy 1 ITM put, sell 2-3 OTM puts (1:2 or 2:3) | Net short options | Uncapped downside | Neutral-bullish (NOT recommended) |

**Cohen's verdict**: Backspreads = good (net long, limited risk). Ratio spreads = bad (net short, uncapped risk — better off trading butterflies).

---

## Ch 7: Synthetic Strategies (lines 8650–10270)

### Collar (★ Key Strategy)

- **Construction**: Buy stock + buy ATM/OTM put (insurance) + sell OTM call (finance the insurance)
- **Outlook**: Conservatively bullish
- **Risk**: Capped at [stock price + put premium − put strike − call premium]. Can be near-zero or even negative (risk-free collar)
- **Reward**: Capped at [call strike − put strike − risk]
- **Time**: 1–2 years. Best collar opportunities found far out in time
- **Key insight**: In high-vol bullish markets, calls are priced > puts → possible to create risk-free collars
- **BE**: Stock price − call premium + put premium
- **Use case**: "Can't afford to lose much but want market participation over 12-18 months"

### Synthetic Equivalents

| Strategy | Construction | Replicates | Net Cost |
|---|---|---|---|
| **Synthetic Call (Married Put)** | Buy stock + buy ATM put | Long call profile | Debit (expensive) |
| **Synthetic Put** | Short stock + buy ATM call | Long put profile | Credit |
| **Long Call Synthetic Straddle** | Short 50 shares per contract + buy 2 ATM calls | Long straddle | Credit |
| **Long Put Synthetic Straddle** | Buy 50 shares per contract + buy 2 ATM puts | Long straddle | Debit (expensive) |
| **Short Call Synthetic Straddle** | Buy 50 shares per contract + sell 2 ATM calls | Short straddle | Debit |
| **Short Put Synthetic Straddle** | Short 50 shares per contract + sell 2 ATM puts | Short straddle | Credit |
| **Long Synthetic Future** | Sell ATM put + buy ATM call (same strike/expiry) | Long stock | Near zero |
| **Short Synthetic Future** | Buy ATM put + sell ATM call (same strike/expiry) | Short stock | Near zero |
| **Long Combo** | Sell OTM put + buy OTM call | Long stock (with gap) | Near zero |
| **Short Combo** | Buy OTM put + sell OTM call | Short stock (with gap) | Near zero/credit |
| **Long Box** | Long synthetic future (lower strike) + short synthetic future (higher strike) | Arbitrage/tax play | Debit |

**Key insight on synthetics**: Main value is flexibility — you can morph an existing position by adding/removing legs. E.g., long stock → add 2 puts = synthetic straddle. Understanding synthetics lets you adapt without closing and reopening.

---

## Cross-Cutting Rules (Apply to ALL Strategies)

### Stock Selection
- **ADV** > 500,000 (liquidity)
- **OVI**: Positive = bullish bias; Negative = bearish bias; Indecisive = volatility play
- Support/resistance must be identifiable on chart
- Avoid stocks with imminent news (for rangebound); seek news catalysts (for volatility)

### Option Selection
- **Open interest** ≥ 100, preferably ≥ 500
- **Bid/ask spread** < 4% of mid-price
- Trade inside the spread, not at the ask
- Equal strikes spacing for butterflies/condors

### Time Management
- **Long options**: ≥ 3 months expiration, exit before final month (time decay accelerates exponentially)
- **Short options**: ≤ 1 month (time decay works for you)
- **Calendars/diagonals**: Long leg ≥ 3 months, short leg ≤ 1 month
- **Collars**: 1–2 years for best risk/reward

### Exit Rules
- Pre-define stop losses before entering
- Dynamic trailing stop for trending winners
- If one side of a straddle/strangle profits, can sell the winner and keep the loser hoping for reversal
- Unravel multi-leg trades in logical chunks (e.g., iron butterfly = put spread + call spread)
- Never hold OTM/ATM options into final month

---

## Strategy Selection Matrix (Cohen's Framework)

| Your Outlook | Low Volatility Expected | High Volatility Expected | Income Goal |
|---|---|---|---|
| **Bullish** | Bull call/put spread, collar | Long call, call ratio backspread, strap | Covered call, short put |
| **Bearish** | Bear call/put spread | Long put, put ratio backspread, strip | Covered put, short call |
| **Neutral** | Iron butterfly/condor, calendar | Long straddle/strangle | Short straddle/strangle (risky) |

---

## NSE/India Adaptation Notes

- NSE options are European-style (no early exercise) — simplifies butterfly/condor exit timing
- Lot sizes are fixed (not 100-share contracts) — adjust ratio calculations
- OVI concept maps to PCR (Put-Call Ratio) + OI change analysis on NSE
- Bid/ask spreads on illiquid NSE strikes can be very wide — Cohen's 4% rule is often violated on far OTM options
- Calendar spreads limited by available expiry months (weekly + monthly + quarterly on NSE)
- Short selling stock for synthetics requires F&O margin, not naked shorting — affects synthetic straddle/future construction
- Cohen's $15-$60 stock price range → for NSE, focus on high-liquidity F&O stocks (NIFTY 50 constituents)
