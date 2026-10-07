# Zerodha Varsity — Module 5: Option Theory for Professional Trading

> **Source:** Zerodha Varsity Module 5 (25 chapters, 8,677 lines extracted from PDF)
> **What's unique vs Natenberg/Cohen/Sinclair:** NSE-specific mechanics, India VIX, practical strike selection tables by time-to-expiry, volatility-based stoploss, real Nifty/Bank Nifty examples, author's personal option writing playbook.

---

## Ch 1-8: Basics (already covered in Natenberg notes — key NSE-specific points only)

### NSE Contract Specs
- **Lot sizes** vary by stock; Nifty = 25 (as of 2015 text; now 50)
- **Settlement:** European-style, cash-settled, last Thursday of month
- **Moneyness on NSE:** strikes listed in fixed intervals (50 for Nifty, varies by stock)
- **Option chain:** NSE website shows LTP, volume, OI, IV for every strike
- NSE marks ITM/OTM with color bands; ~2 ITM strikes shown by default

### Intrinsic Value Reminders (CE/PE)
- CE IV = max(0, Spot − Strike); PE IV = max(0, Strike − Spot)
- Premium = Intrinsic Value + Time Value
- OTM options have zero intrinsic value — entire premium is time value
- At expiry: premium converges to intrinsic value only

---

## Ch 9-11: Delta

### Delta Table (CE and PE)
| Moneyness | CE Delta | PE Delta |
|-----------|----------|----------|
| Deep ITM  | 0.8–1.0  | −0.8 to −1.0 |
| Slight ITM| 0.6–1.0  | −0.6 to −1.0 |
| ATM       | ~0.5     | ~−0.5    |
| Slight OTM| 0–0.45   | 0 to −0.45 |
| Deep OTM  | 0–0.3    | 0 to −0.3 |

### Delta as Probability Proxy
- Delta ≈ probability of expiring ITM
- OTM option with delta 0.1 → ~10% chance of expiring ITM
- Useful for option writing: sell strikes with delta < 0.1 for high probability of worthless expiry

### Position Delta (Portfolio Level)
- Sum of (qty × delta) across all positions
- Long puts contribute negative delta; short puts contribute positive
- **Neutral portfolio:** position delta ≈ 0
- Example: long 1 ATM CE (Δ=0.5) + long 1 ATM PE (Δ=−0.5) = position delta 0

### Strike Selection by Delta (% Return Perspective)
The key insight: **OTM options have highest % return when the move is fast, but highest % loss when the move is slow or doesn't happen.**

| Strike | Delta | Premium | 30pt Move | % Gain |
|--------|-------|---------|-----------|--------|
| Deep OTM | 0.05 | Rs.3   | 1.5       | 50%    |
| Slight OTM | 0.3 | Rs.7  | 9         | 129%   |
| ATM    | 0.5   | Rs.12   | 15        | 125%   |
| Slight ITM | 0.7 | Rs.22 | 21        | 95%    |
| Deep ITM | 1.0  | Rs.75  | 30        | 40%    |

**Conclusion:** Slight OTM gives best risk-adjusted % return for moderate moves.

---

## Ch 12-13: Gamma ★

### Gamma as Acceleration
- Delta = speed of premium change; Gamma = acceleration of delta change
- Gamma is always positive for both CE and PE (long positions)
- **Short gamma = directional risk** — the position works against you faster as it moves against you

### Gamma Risk for Option Writers
- Short ATM near expiry = maximum gamma risk
- Short OTM with ample time = low gamma risk (safest writing)
- Gamma stays flat until ~halfway through expiry, then ATM gamma explodes
- ITM and OTM gamma collapse to zero near expiry

### Gamma Behavior Near Expiry (Critical for Writing)
```
Time to expiry:  Far ──────────────────── Near
ATM Gamma:       Low, stable ──────────── SPIKE ↑↑↑
ITM Gamma:       Low, stable ──────────── → 0
OTM Gamma:       Low, stable ──────────── → 0
```
**Rule: Never short ATM options in the last week unless you can handle the gamma spike.**

### DgammaDspot
- Gamma itself changes as spot moves (3rd order effect)
- ATM gamma peaks; OTM/ITM gamma is lower
- When spot crosses a strike, that strike's gamma spikes then falls — this is the "pin risk" zone

---

## Ch 14: Theta ★

### Time Decay Behavior
- Theta is always negative for option buyers (premium erodes daily)
- **Non-linear decay:** slow in first half of series, accelerates dramatically in last week
- Rule of thumb: option loses ~1/3 of remaining time value in last week

### Theta Decay Curve (approximate)
| Days to Expiry | Daily Decay Rate |
|----------------|-----------------|
| 30             | Slow            |
| 20             | Slow            |
| 15             | Moderate        |
| 10             | Accelerating    |
| 5              | Fast            |
| 1              | Maximum         |

### Practical NSE Examples
- Nifty 8600 CE (OTM, 6 days to expiry): premium Rs.99.4 → Rs.87.9 in 1 day = Rs.11.5 theta decay (no spot move!)
- Nifty 8450 CE (ITM): premium Rs.160 → intrinsic value Rs.64.5 at expiry = Rs.95.5 of time value lost
- **ITM options lose time value too** — just less dramatically than OTM

### Theta + Moneyness
- ATM theta is highest (most time value to lose)
- Deep ITM/OTM theta is low (little time value left to erode)
- OTM options can go to zero; ITM options retain intrinsic value

---

## Ch 15-17: Volatility & Normal Distribution ★★

### Historical Volatility Calculation (Step by Step)
1. Get daily closing prices from NSE
2. Calculate daily returns: LN(today/yesterday)
3. Calculate SD of daily log returns = **daily volatility**
4. Annualize: daily vol × √252 (trading days) = **annual volatility**
5. For N-day vol: daily vol × √N

### NSE Volatility Data
- NSE publishes annualized volatility on its website for each stock/index
- Cross-check your calculation against NSE's published number

### Normal Distribution Applied to Stocks
- Daily stock returns are approximately normally distributed
- Mean and SD fully characterize the distribution
- **68-95-99.7 rule** applied to stock ranges:

### SD-Based Range Calculation (Nifty Example)
```
Given: Nifty = 8337, Daily mean = 0.04%, Daily SD = 1.046%

For 1-year range:
  Annual mean = 0.04% × 252 = 9.66%
  Annual SD = 1.046% × √252 = 16.61%
  
  1SD range (68% confidence):
    Upper = 8337 × e^(9.66% + 16.61%) = 10,841
    Lower = 8337 × e^(9.66% - 16.61%) = 7,777
  
  2SD range (95% confidence):
    Upper = 8337 × e^(9.66% + 2×16.61%) = 12,800
    Lower = 8337 × e^(9.66% - 2×16.61%) = 6,587

For 30-day range:
  30d mean = 0.04% × 30 = 1.15%
  30d SD = 1.046% × √30 = 5.73%
  
  1SD (68%): 7,963 — 8,930
  2SD (95%): 7,520 — 9,457
```
**Black swan = anything beyond 3SD. Non-zero probability, impossible to predict when.**

---

## Ch 18: Volatility Applications ★★★

### Strike Selection for Option Writing (Using SD)
**The core method for safe option writing on NSE:**

1. Calculate daily mean and SD of the underlying
2. Convert to N-day values (N = days to expiry)
3. Calculate 1SD and 2SD ranges
4. Write options **outside** the SD range — they are likely to expire worthless

#### Worked Example
```
Date: 11 Aug 2015, Nifty = 8462, Expiry = 16 days away
Daily mean = 0.04%, Daily SD = 0.89%

16-day SD = 0.89% × √16 = 3.567%
16-day mean = 0.04% × 16 = 0.65%

Upper range (1SD) = 8462 × (1 + 0.65% + 3.567%) = 8818
Lower range (1SD) = 8462 × (1 - 2.920%) = 8214

→ Write CEs above 8818 (e.g., 8850 CE, 8900 CE)
→ Write PEs below 8214
→ 68% probability these expire worthless
```

### Author's Personal Option Writing Playbook
1. **Write calls only, not puts** — panic (down moves) is faster than greed (up moves); a 438-point fall happens faster than a 438-point rise
2. **Timing:** short options only on last Friday before expiry week (~4-5 days left). Theta acceleration is your friend
3. **Strike selection:** 1SD away when 3-4 days to expiry; 2SD away if writing earlier. Never write with >15 days to expiry
4. **Premium target:** ~Rs.5-6 on Nifty per lot = ~1.0-1.5% return on margin (~Rs.12,000) = **~18% annualized**
5. **Capital allocation:**
   - 35% → MF SIP (4 funds)
   - 40% → equity portfolio (12 stocks)
   - 25% → short-term trading
   - Max 35% of trading capital per strategy = **max ~9% of total capital** per trade
   - ≤ 4 lots of Nifty options
6. **Exit rule:** get out when OTM transitions to ATM
7. **Avoid:** writing around events (RBI policy, earnings, elections)
8. **Black swan reality:** "eating like a hen but shitting like an elephant" — 9-10 months of small gains can be wiped by 1 bad month. Track sentiment, exit fast on danger signals
9. **Instruments:** only liquid names — Nifty, Bank Nifty, SBI, Infosys, Reliance, Tata Steel, Tata Motors, TCS

### Volatility-Based Stoploss ★★
**Replace fixed % SL with volatility-based SL:**

1. Calculate daily vol of the stock
2. Convert to holding-period vol: daily_vol × √(holding_days)
3. SL price = entry − (holding_period_vol × entry_price)
4. Recalculate RRR with new SL

#### Example
```
Long Airtel @ 395, target 417, traditional SL = 385 (2.5%)
Daily vol = 1.8%, holding period = 5 days
5-day vol = 1.8% × √5 = 4.01%
Vol-based SL = 395 × (1 - 4.01%) = 379

→ Set SL at 375 (below the vol range)
→ New risk = 20 points, reward = 22 points, RRR = 1.1
→ Avoids getting stopped out by normal daily noise
```

**Why this matters:** A 2% fixed SL on a stock with 3% daily vol will trigger on noise. The vol-based SL stays outside the expected fluctuation range.

---

## Ch 19: Vega & Volatility Types ★★

### Four Types of Volatility
1. **Historical Volatility** — calculated from past closing prices (what happened)
2. **Forecasted Volatility** — model predictions (GARCH(1,1) or GARCH(1,2) recommended)
3. **Implied Volatility (IV)** — market consensus, embedded in option premiums (most valued)
4. **Realized Volatility** — actual vol that occurred during the expiry period (known only after)

### India VIX (NSE's Implied Volatility Index)
- Computed from Nifty option order book (bid-ask of near & next month)
- Represents market's expectation of volatility over **next 30 calendar days**
- Higher VIX = higher expected volatility = higher option premiums
- Also called "Fear Index" — rises during panic
- **VIX is annualized %**, not daily
- VIX ≠ Nifty direction; VIX measures expected magnitude of moves, not direction

### Vega Behavior
- Vega = change in premium per 1% change in IV
- Always positive for both CE and PE (long positions)
- **Vega is highest when there are more days to expiry:**
  - 30 DTE + vol increase 15%→30%: premium up ~95%
  - 15 DTE + same vol increase: premium up ~50%
  - 5 DTE + same vol increase: premium up ~47%

### Aug 24, 2015 Crash — Greek Interaction Case Study ★★★
**What happened:** Nifty fell 5.92% (~490 points), India VIX shot up 64%.
**Surprising result:** OTM call option premiums INCREASED 50-80%.

**Why:**
- ITM/ATM calls (delta 0.3-0.8) lost value normally from delta effect
- Far OTM calls (delta ~0.05) barely moved from delta — 490 × 0.05 = only 24 points loss
- But Vega effect from 64% VIX spike overwhelmed the tiny delta loss
- Vega impact is highest on OTM options
- Net: OTM call premiums went UP on a massive down day

**Lesson:** Never short far OTM options going into potential high-vol events. The Vega spike can make them profitable for buyers even if spot moves against them.

---

## Ch 20: Greek Interactions ★★

### Volatility Smile (NSE Option Chains)
- IV is lowest for ATM options, increases as you move to OTM/ITM on either side
- Plot strike vs IV → U-shaped "smile" curve
- True across all NSE stocks/indices
- Far OTM options always have inflated IV → inflated premiums

### Volatility Cone (Practical Tool)
**Purpose:** Compare current IV to historical realized vol to identify cheap/expensive options.

Construction:
1. Calculate realized volatility for multiple lookback windows (10, 20, 30, 45, 60, 90 days)
2. For each window, compute: max, +2SD, +1SD, mean, −1SD, −2SD, min
3. Plot → forms a "cone" shape (wider at shorter windows, narrower at longer)
4. Overlay current IV dots on the cone

**Interpretation:**
- Option IV near +2SD line → **expensive, consider selling**
- Option IV near −2SD line → **cheap, consider buying**
- Works across different stocks for relative comparison

#### Nifty Realized Vol Cone Data (Jun 2014 – Aug 2015)
| Window | Max | +2SD | +1SD | Mean | −1SD | −2SD | Min |
|--------|-----|------|------|------|------|------|-----|
| 10d    | 56% | 54%  | 42%  | 30%  | 19%  | 7%   | 13% |
| 20d    | 49% | 46%  | 38%  | 29%  | 21%  | 13%  | 16% |
| 30d    | 41% | 42%  | 36%  | 30%  | 23%  | 17%  | 21% |
| 60d    | 37% | 40%  | 35%  | 30%  | 24%  | 19%  | 21% |
| 90d    | 35% | 38%  | 33%  | 29%  | 24%  | 19%  | 20% |

### Gamma vs Time (Surface Plot Summary)
- Far from expiry: all strikes have low, similar gamma
- Approaching expiry: ATM gamma spikes, OTM/ITM gamma → 0
- **Practical rule:** short options with >15 DTE have stable gamma; short options <5 DTE have explosive ATM gamma

### Delta vs Implied Volatility
- When IV is low: delta curve is steep (S-shaped), OTM delta ≈ 0, ITM delta ≈ 1
- When IV is high: delta curve is flatter, OTM delta maintains non-zero value
- **This is why deep OTM options have non-trivial premiums in high-vol environments** — they retain meaningful delta

---

## Ch 21: Black-Scholes Calculator (NSE Practical) ★

### B&S Inputs for NSE
| Input | Where to Get It |
|-------|----------------|
| Spot price | NSE website / terminal (use spot, not futures, for equity options) |
| Strike price | Option chain |
| Interest rate | **RBI 91-day Treasury bill rate** (from RBI homepage) — ~7.5% as of 2015 |
| Dividend | Only if stock goes ex-dividend before expiry; per-share amount |
| Days to expiry | Calendar days to expiry Thursday |
| Implied volatility | NSE option chain (IV column for each strike) |

### Put-Call Parity (PCP)
```
Put + Spot = PV(Strike) + Call

Or equivalently:
P + S = K × e^(-rt) + C

At expiry (simplified):
Put + Spot = Strike + Call
```
- Holds for European ATM options (NSE stock options are European)
- If PCP is violated → arbitrage opportunity (rare on NSE due to transaction costs)
- PCP can be used to derive synthetic positions

---

## Ch 22: Strike Selection by Time-to-Expiry ★★★

### The Strike Selection Table
**This is the most actionable framework in the module. Memorize it.**

Given: you have a directional view (bullish/bearish) and want to buy options.

| When Initiated | Target Achieved In | Best Strike |
|---------------|-------------------|-------------|
| 1st half of series (>15 DTE) | 5 days | Far OTM (2-3 strikes from ATM) |
| 1st half of series | 15 days | ATM or slightly OTM (1 strike from ATM) |
| 1st half of series | 25 days | Slightly ITM |
| 1st half of series | At expiry | ITM |
| 2nd half of series (<15 DTE) | Same day | Far OTM (2-3 strikes from ATM) |
| 2nd half of series | 5 days | Slightly OTM (1 strike from ATM) |
| 2nd half of series | 10 days | ATM or slightly ITM |
| 2nd half of series | At expiry | ITM |

### Key Principles Behind the Table
1. **Fast moves + ample time = OTM** (highest % return, gamma works for you)
2. **Slow moves or near expiry = ITM** (theta kills OTM; ITM retains intrinsic value)
3. **Never buy far OTM in 2nd half unless expecting same-day move** — theta eats it alive
4. **The cheap premium illusion:** OTM options look cheap but have very high probability of total loss. "Low premium" ≠ "low risk"
5. **Applies equally to puts** — same table, mirror the direction

---

## Ch 23: Case Studies (NSE-Specific)

### Case 1: CEAT Ltd — Earnings Trade
- Bearish on CEAT @ Rs.1260, bought 1220 PE (OTM) for Rs.45.75
- **Mistake:** bought OTM with only 2 days to expiry
- Key learning: even if direction is right, theta + wrong strike = loss

### Case 2: RBI Monetary Policy — Straddle
- Nifty @ 7780, bought 7800 CE (Rs.203) + 7800 PE (Rs.176) = total cost Rs.379
- **Strategy:** buy both ATM options before RBI announcement, exit within minutes
- **Timing:** enter 10-15 min before announcement, exit quickly after
- **Risk:** premium paid is the max loss; both options can lose if market doesn't move enough
- Post-announcement: CE = 191, PE = 369 → profit on the straddle

### Case 3: Infosys Earnings — Directional
- Infy @ Rs.1142, bought 1140 CE (Rs.48) + 1140 PE (Rs.47) = Rs.95 straddle
- Results were good: stock moved, CE went to Rs.55, PE dropped to Rs.20
- **Warning on straddles:** need the move to exceed total premium paid (both legs)

### Case 4: Infosys — OTM Buy on Strong View
- Strong bullish view post-results, bought 1100 CE (OTM) for Rs.18.9
- Already ITM at entry (Infy had gapped up), so actual risk was manageable
- **Lesson:** buying OTM that becomes ITM intraday due to gap = the ideal OTM buy scenario

---

## NSE-Specific Takeaways (Not in Western Textbooks)

1. **RBI 91-day T-bill rate** for risk-free rate in B&S (not LIBOR/Fed Funds)
2. **India VIX** is the fear gauge — track it before writing options
3. **NSE lot sizes** vary by stock and change periodically
4. **SPAN margin** for option writing — check via Zerodha margin calculator
5. **European settlement** on all equity options (no early exercise)
6. **Expiry = last Thursday** of the month
7. **Option chain on NSE website** gives IV for each strike — no need to calculate
8. **Liquidity matters:** only trade options on liquid names (Nifty, Bank Nifty, top ~10 stocks)
9. **Transaction costs:** brokerage + STT + stamp duty + GST + exchange charges. Per-lot costs matter more for premium collection strategies
10. **Panic asymmetry on NSE:** down moves are faster than up moves (same as global markets, but amplified by FII flow dynamics)
