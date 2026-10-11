# The Option Trader's Hedge Fund — Mark Sebastian & Dennis Chen
## Complete Notes

**Core thesis**: Run your options portfolio as a One Man Insurance Company (TOMIC). You are the insurer — you sell premium (insurance policies), manage risk like an actuary, and compound returns through disciplined underwriting, not directional bets.

---

## PART I: BUILDING THE BUSINESS (Ch.1–7)

### Ch.1 — The Insurance Business Model

**Insurance ↔ Options mapping** (Table 1.1):
| Insurance | Options |
|-----------|---------|
| Policy on asset ($20K car) | Short put on $90 stock |
| Premium collected | Option premium collected |
| Policy term 12 months | Option expiry 30 days |
| Loss = claim payout | Loss = ITM assignment |
| 90% policies expire worthless | ~90% OTM options expire worthless |
| Reinsurance (cede tail risk) | Buy OTM wing (cap max loss) |

**TOMIC value chain** (Fig 1.2–1.3):
1. **Trade selection** — pick which "policies" to underwrite
2. **Risk management** — position sizing, diversification, reinsurance (wings)
3. **Infrastructure** — broker, platform, analytics, margin

**Key insight — Reinsurance**: ABC Insurance in San Francisco insures earthquake risk but reinsures the tail through Berkshire. TOMIC equivalent: sell iron condors (collect premium) but the long wings are your reinsurance — they cap catastrophic loss. Never sell naked; always have reinsurance.

**Insurance makes money from**:
1. Risk pricing (actuarial edge, not directional edge)
2. Risk selection (choose WHAT to insure)
3. Volume of policies (diversification)
4. Investment of float (premium income invested)

**AIG lesson**: AIG sold $450B of CDS "insurance" on mortgage-backed bonds without proper risk pricing or reinsurance. Violated every insurance principle. TOMIC must never concentrate risk or underprice it.

---

### Ch.2 — Trade Selection: What, Where, When

**What to trade** — 4 categories:
1. **Broad-based indices**: SPX, NDX, RUT, DJX, OEX (IRC §1256: 60/40 tax treatment)
2. **ETFs**: SPY, QQQ, IWM, OIH, RTH, XLF, GLD, etc.
3. **Single stocks**: AAPL, IBM, MCD, WMT, GS, FCX (need 50K+ avg daily option volume)
4. **ETCs** (exchange-traded commodities)

**§1256 tax advantage**: Broad-based cash-settled index options get 60% long-term / 40% short-term cap gains regardless of holding period. Blended max rate ~23% vs 35% short-term.

**Five trade questions**:
1. What product to trade?
2. What direction?
3. What time frame?
4. Which specific options?
5. What risk/reward?

**Time frame**: TOMIC is NOT a six-month buy-and-hold. Typical cycle is weeks to ~1 month. Use monthly SPX options; avoid LEAPS for premium selling.

**Volatility assessment**: Like hurricane insurance — price depends on location risk. Cayman Islands hurricane frequency ≠ Kansas. High-vol environments = more premium but more risk. Low-vol = less premium but safer. Price accordingly.

---

### Ch.3 — Risk Management

**Position sizing rules**:
- **2% rule**: Max loss on any single trade = 2% of AUM
- **6% rule**: Max portfolio heat (sum of all open-trade risk) = 6%
- Example: $2M portfolio → max $40K per trade loss. If trading RUT 10-point iron condors ($1,000 max loss each), max 40 contracts. But margin is ~$200/contract (PM), so 200 contracts × $200 = $40,000 = 2%.

**If 2% hit three times (6% total)**: Stop trading that month. Period. The percentage can be adjusted (5%, 7%, 10%) but must be predetermined and enforced.

**Diversification**: Don't put all TOMIC capital into one sector. Example bad: Exxon, Chevron, BP, ConocoPhillips, Petrobras — all energy = correlated. Spread across SPX, AAPL, GS, FCX, BP (different sectors).

**Risk taxonomy** (Table 3.1):
| Risk Type | Description | Mitigation |
|-----------|-------------|------------|
| Systemic | Economy-wide (2008, 9/11) | OTM puts on S&P 500 (25%), OTM VIX calls |
| Market | Broad market moves | Delta management |
| Sector | Industry-specific (Enron, BP spill) | Diversification across sectors |
| Idiosyncratic | Single stock events | Position size limits |

**Tail hedge (systemic risk)**: TOMIC allocates up to 25% of portfolio to OTM S&P 500 puts and OTM VIX calls as catastrophic insurance.

**Fulcrum concept**: Options are a lever. The fulcrum position determines how much wood is on each side. ATM puts = fulcrum in middle. Moving the fulcrum (changing strikes) changes your risk/reward dramatically.

**OEX example**: OEX 505 calls at $1.20 went to $14.50 in one day (1,200% gain). A 5–10% move in the underlying can cause 20%, 100%, even 1000%+ move in option prices. This is why risk management is existential.

---

### Ch.4 — Assessing Market Conditions

**Pre-trade checklist**:
1. Current market conditions (trending/range-bound)
2. Potential volatility events (FDA, earnings, elections)
3. Historical vs implied volatility comparison
4. Skew shape and term structure

**IV vs HV**: If IV >> HV, premium is overpriced → good to sell. If IV << HV, premium is underpriced → bad to sell, consider buying.

**VIX behavior**: VIX is mean-reverting. After a spike to 40%+, the VIX futures term structure and options tell you where the market thinks vol is heading. VIX futures at 29.20 when cash VIX is 47.5 = market expects reversion (Fig 4.1).

**Skew assessment**: The vol curve across strikes matters enormously. Flat skew + low IV = normal. Steep skew + high IV = fear. Assess both before entering.

**Term structure**: Compare front-month IV to back-month IV. If front >> back (backwardation), market is panicking. If front << back (contango), normal conditions.

**Product selection process**: Walk through insurance analogy — assess the "neighborhood" (product), the "property" (specific trade), then price the policy (premium vs risk).

**Trade sizing**: TOMIC runs 15–30 "policies" at a time, each for $1,000–$10,000 in premium per month.

---

### Ch.5 — Discipline and the Trading Mindset

**Casino analogy**: Casino has edge on roulette (17/37 red numbers). They don't need to win every spin — they need to play enough spins with their edge. TOMIC is the casino, not the gambler.

**Lucky vs Good**: Blackjack — you have 18, dealer shows 6, hits 16, draws 3, gets 21. You lost. Was your play wrong? No. Hitting on 16 has high bust probability. The dealer got lucky. In TOMIC, process > outcome on any single trade. Evaluate decisions, not results.

**Checklist discipline** (Pronovost ICU study): A five-item catheter checklist reduced ICU infections by 66% and saved $200M over 18 months. Simple checklists enforced consistently produce extraordinary results. TOMIC needs the same rigor for every trade.

**Mindset requirements**:
- Discipline (follow the plan, especially in losses)
- Decisiveness (act on opportunities, don't freeze)
- Flexibility (adapt to changing markets)
- Humility (accept losses as cost of business; even Buffett has losing years)
- Emergency calm (Sullenberger on the Hudson — don't panic)

**TOMIC operating questions**:
- What markets will TOMIC trade?
- What strategies for which conditions?
- What are the risk limits?
- Do I keep a trading journal?

---

### Ch.6 — Infrastructure

**Skill levels**:
- Level 0 (Beginner): Paper trade, learn platform, no real money
- Level 1 (Intermediate): Calendars, diagonals, multi-leg strategies
- Level 2 (Semi-pro): Full risk/reward analysis, part-time TOMIC
- Level 3 (Professional): TOMIC is primary income source

**Broker requirements**:
1. Portfolio margin (PM) — critical for capital efficiency
2. Good execution routing (not just cheapest commissions)
3. Multi-exchange routing capability
4. Real-time analytics and Greeks
5. Reliable platform and customer service

**Portfolio Margin example**:
- 100 shares AAPL at $330 + long 1 AAPL OCT 320 put at $18
- Reg-T margin: $17,300
- PM margin: $1,000
- **PM saves $16,300** in margin per position — transformative for TOMIC capital efficiency

**Essential information sources**: Bloomberg, Yahoo Finance, SeekingAlpha, StockTwits, LiveVol (volatility data), CBOE, iVolatility

**Analytics tools**: LiveVolPro and iVolatility for vol surface analysis. ThinkorSwim for strategy modeling.

---

### Ch.7 — Performance Monitoring

**War Room metrics** (Table 7.1–7.2):
1. Annual return
2. Number of profitable vs unprofitable trades
3. Win rate
4. Average win vs average loss
5. Profit per trade
6. Max winning trade
7. Max losing trade
8. Average DIT (days in trade)
9. Return on margin

**TOMIC 1.0 sample results** (Table 7.2): Win rate 94%, profit ratio 3.2:1, nine losing trades averaging -$1,716, total profit $1,833,878, average DIT 26 days, 3.6% return per trade, 63.8% annualized.

**Comparison** (Table 7.3 vs 7.4): Even dropping win rate from 94% to 90% and profit ratio from 3.2 to 1.0 still shows positive expectancy — IF risk management holds. The margin of safety comes from position sizing, not win rate.

**Coaching**: Get a trading coach or join a mentoring group. Having accountability and feedback loops is essential, same as any professional discipline.

---

## PART II: THE STRATEGIES (Ch.8–10)

### Ch.8 — Understanding Volatility (Three-Dimensional Thinking)

**IV is supply/demand, NOT market-maker-set**: Customer paper flow determines IV. MMs lower bid as selling arrives → overshoot → bids appear on other side → MMs raise offer → IV rises. Smart fund sells when others buy, buys when others sell.

**Market makers think in 3D**: Not just price direction, but volatility level AND term structure simultaneously.

**ATM IV is the anchor ("vomma")**: ATM front-month options have greatest sensitivity to IV changes. All other strikes' IVs derive from ATM. ATM IV = the "speed" of the market. OTM IV inflated by skew.

**Equity skew exists because**:
1. 401(k)/pension funds systematically buy OTM puts for protection
2. Downside moves are sharper than upside (leverage effect)
3. OTM put demand > OTM call demand

**OTM options — the .10 trap (3 Rules)**:
1. NEVER short options ≤ .10
2. If already short and option falls below .10, buy to close (even with commission cost)
3. A hedge fund selling premium should ALWAYS be net long these "units"
- Invest 5–10% of fund in option insurance (units). Long-term, this pays out.

**Term structure**: Front month options have more gamma (day-to-day movement sensitivity). Back month options have more vega (volatility sensitivity). Calendar spreads exploit the difference.

**Events to watch**: Earnings, FDA decisions, dividends — these create discrete volatility that must be priced separately from continuous vol.

**Volatility analysis checklist**:
1. ATM IV level (vs historical range)
2. Skew shape (steep, flat, inverted)
3. Three-month term structure (contango vs backwardation)
4. IV of specific strikes you'll trade
5. Profit/loss under IV changes of ±5%, ±10%, ±25%

---

### Ch.9 — Core TOMIC Strategies

#### Iron Condor
- **Structure**: Sell OTM put spread + sell OTM call spread
- **When**: Low-to-moderate IV, normal skew, range-bound expectation
- **Strike selection**: 10–15 delta, wings 10–12 points wide (SPX). NOT just any credit ≥ $0.60 — check % OTM
- **Risk/reward**: Target ~$2.00 credit on 10-point spread = 25% of max risk. Need 85%+ probability but also 70%+ chance of profit after adjustments
- **Profit target**: Exit at 50–55% of premium collected, within 30 days
- **Stop loss: Third-Third-Third Rule**: Set max loss = credit received. 1st adjust at 1/3 of max loss, 2nd at 2/3, exit at 3/3. If 1.5σ move would breach absolute max loss, exit preemptively even before triggers.
- **Cone of feasibility**: OTM options lose bulk of value exiting the zone where they could logically end ITM — this is WHY 60 DTE optimal for 10-15Δ condors. If 25% of credit captured in <5 trading days → edge was huge, exit immediately.
- **Adjustment hierarchy (upside)**: Kite spread (primary, cheap gamma reduction), back ratio (low IV only), call spread (last resort, expensive), time call spread (PM only).
- **Adjustment hierarchy (downside)**: Ratio 1×2 (primary, flattens curve), put spread (secondary, cheap due to skew), 1×2 front spread (PM, profits on reversal). **NEVER** roll out or add size to fix.
- **ATR filter**: Don't enter if ATR suggests the underlying will breach your short strikes
- **Skew warning**: Steep skew + low IV = wings get pulled in (closer to ATM). Iron condor MORE vulnerable. Flat skew + high IV = wider wings, better risk/reward
- **Reinsurance**: When IV in lower 25% of range, spend up to 10% of credit on OTM unit puts. When IV high and declining, insurance likely unnecessary.

#### Butterfly (Iron Butterfly & Long Butterfly)
- **Structure**: Sell ATM straddle + buy OTM wings (or: buy wing, sell 2× body, buy wing)
- **When**: ATM IV > OTM IV (positive skew conditions), 15–30 DTE, ATR suggests underlying stays near center
- **Wing calculation**: 1σ for max holding period: ATM_IV × √(DIT/365) × strike_price. Example: 0.185 × √(17/365) × 1270 = 51 → round to 50.
- **Width**: Set wings so the long options are worth > $0.25 each. Wings under $0.25 hedge NOTHING
- **Risk/reward**: Target at least 1:1 risk:reward. Well-constructed fly risks 5–10% on a 10% underlying move (Fig 9.7)
- **Skew rule**: Want FLAT put curve + STEEP call curve. When 10Δ put trades at ≤6% discount to ATM IV → favorable; ≤10% discount → excellent. Flat skew = short profitable trade.
- **Strangle-tightening**: At 10% profit, sell far wings & buy inside wings (= buy iron condor inside the fly). Flattens P&L curve, locks profits. If P&L then breaks the tightened tent → close.
- **Exit**: At 10% profit, tighten or close. If trade breaks outside the tent → scratch (≈ wash). Never add more butterflies to adjust ("tranching flies" causes all big fly losses).
- **Key insight**: IV explosion hurts iron condors but helps butterfly structure (OTM wings gain more than ATM loses in gamma terms at extreme IV levels)

#### Calendar Spread
- **Structure**: Sell front month, buy back month (same strike)
- **Long calendar**: Sell front month when IV trades ≥10% premium to normal relationship with back month. IV should be mid-range and stable (NOT bottom 15%). Goal: IV term structure collapses.
- **Short calendar**: Buy front month when IV trades ≥10% discount to normal. Works best when IV is ultra-low OR ultra-high. Long gamma protects.
- **Warning signs**: If front month premium > 25% of front month IV → investigate why (event, earnings). If spread looks too good → it probably is.
- **Goals**: 5–10% return, get in and get out. If 5% in <1 day → gift, kill it. Never hold for theta decay — trade volatility, not time.
- **Risk**: Never lose > 10% of original margin. Almost never pays to add to a losing calendar. If adding, conditions must be ≥ original trade quality.
- **Gamma danger**: Calendars are short front-month gamma. A one-day 10% move in underlying can wipe out the trade. Final few days = straddle price, not IV trade.
- **"Pay the decay"**: Scalp gamma only in small incremental moves (<1-day σ). Gamma scalping defends against decay, it doesn't make money.

#### Ratio Spread (Back Spread: 1×2)
- **Structure**: Sell 1 ATM option, buy 2 OTM options (net credit or zero cost)
- **When**: IV in lower 40% of historical range AND skew flat (OTM options cheap). NEVER enter if IV above 40th percentile.
- **Skew**: Flatter = better. Buy the curve at extra-cheap price. Pop in IV + skew normalization can profit without underlying moving.
- **Goals**: 10% return, never more. Credit or zero cost required — this way, wrong on direction still wins from volatility.
- **Risk**: If losing but conditions improved → add. If losing and conditions worsened → close. No other adjustments.
- **1×2 Front spread (PM only)**: Sell 2 OTM, buy 1 ATM. Conditions awful for back ratio = great for front spread. MUST generate credit. Close when credit can be bought back for a credit (underlying moved away from shorts + skew flattened).

#### Straddle/Strangle (Short)
- **Structure**: Sell ATM put + call (straddle) or sell OTM put + call (strangle)
- **When**: IV elevated, range-bound expectation, willing to manage actively
- **Risk**: Unlimited on both sides. Requires constant monitoring and gamma scalping

**Strategy selection by IV regime**:
| IV Level | Preferred Strategy |
|----------|-------------------|
| Low (VIX 12–16) | Long butterfly, calendar spreads |
| Medium (VIX 16–22) | Iron condors, iron butterflies |
| High (VIX 22–30) | Short strangles, ratio spreads, calendars |
| Crisis (VIX 30+) | Cash, or carefully placed butterflies |

---

### Ch.10 — TOMIC 1.0: Putting It All Together

**TOMIC 1.0 specifications**:
- Starting capital: $100,000
- Max single trade loss: 2% ($2,000)
- Max portfolio loss: 6%
- Portfolio allocation: 20% invested max, 90-day rolling basis
- Target return: 1% per month (12% annual)
- Products: 10 diversified underlyings (SPX, RUT, NDX, RTH, OIH, AAPL, CAT, EXC, MCD, WMT)

**Trade example** (Table 10.1): AAPL position margin = $9,010. TOMIC 1.0 max loss = 150% × $990 = $1,485. That's 1.49% of $100K — within the 2% limit. ✓

**Monthly P&L** (Table 10.2–10.3): Across 10 positions with $2,000 max loss each, net monthly return of ~$3,530 (3.5% on invested capital, ~4% AUM annualized basis). Over 25–30 trades per month.

---

## PART III: BLOG POSTS & FLOOR LESSONS (Ch.11–15)

### Ch.11 — Volatility Case Studies (Blog Posts)

**SPX calendar neutralizer**: When 30-day IV >> 90-day IV, sell the front/buy the back. The vega spread nets a floor for gamma risk. But front-month gamma movements are "dangerous game" — one big move kills the trade.

**Vomma**: ATM front-month options have greatest sensitivity to changes in IV ("vomma"). Watching ATM front month tells you how IV on ANY option will move.

**Skew tracking method**: Chart 5 delta-based options daily: 5Δ put, 20Δ put, 50Δ call, 25Δ call, 10Δ call. Track IV spreads between them. Switch to next month at 15 DTE (rule: "when you hit the 1st of the month, stop using that month for skew").

**Skew relativity**: Skew is a % of ATM IV. 140% × 19% ATM = 26.6% vs 135% × 25% ATM = 33.75%. Higher ATM IV compensates for flatter skew. Not all $0.60 credits are equal: at low IV, 10Δ is 8.5% OTM; at higher IV, same 10Δ is 10% OTM (15 extra points of cushion).

**Skew analysis for condors**: ATM IV falling doesn't mean your condor is safer. If skew steepens (OTM puts get relatively more expensive), the wings of your condor get pulled closer to ATM even as headline IV drops.

**5 Phases of Volatility Skew** (Sebastian's framework):

| Phase | VIX Level | Skew | Market State |
|-------|-----------|------|-------------|
| 1: Calm | 16–18% | Normal/flat | No fear, steady markets |
| 2: Calm Before Storm | Slightly elevated | Steepening | Protection buying begins, OTM puts bid |
| 3: Typhoon | 30–40%+ | Flattens (ATM catches up) | Panic, borderline crisis |
| 4: Calming Storm | 20–35%, falling | Very steep | ATM sold off but OTM still bid; most expensive unit protection |
| 5: Recovery | Normalizing | Slightly elevated | Wounds licking; takes ~6 months to fully return to Phase 1 |

**Iron condor IV trap** (Fig 11.1–11.2): Collecting $0.60 credit on a 10-delta spread is NOT equivalent across different IV regimes. In Nov (higher IV), the 10-delta put was 10% OTM. In Dec (lower IV), the 10-delta put was only 8.5% OTM — 15 points closer to the money in absolute terms. Same credit, very different risk.

---

### Ch.12 — Lessons on Risk Management

**Cash is a position**: Two scenarios with same iron condor strategy — one trades every month, one skips September. Skipping September (a bad month) turned 7% annual return into 13%. Not trading when conditions are unfavorable is the highest-edge trade.

**Card Game Value**: 100 cards, 99 worth $0, one worth $1,000. Theoretical value = $10. But in a single-play game, the seller should charge far more than $11. This is why cheap options (.10–.25) maintain value longer than models predict — the payout asymmetry keeps a floor under their price. **Implication**: Exit credit spreads when the short option reaches Card Game Value territory (.10–.25). Don't wait for zero. Free up capital for new trades.

**Over-adjustment disease**: The most common mistake. A position near trouble ≠ a position in trouble. Every adjustment costs commissions and extends time in the trade (more exposure to tail events).

**3-day rule**: If trade moves within half a standard deviation of trouble for 2 out of 3 consecutive days → adjust. NOT before. NO adjustments in first 2.5 days of any trade — let it settle.

**Weekend theta**: Friday 4pm → Monday 9:30am = 2.5 calendar days. BUT platforms start decaying from Sunday 4pm only (wake-up decay = Sunday 4pm → Monday 9:30am). So the "free weekend premium" is only ~0.5 days, not 2.5. If your spread is on the cusp of exit on Friday, get out — the remaining weekend decay is thin.

**De-risk triggers**:
1. Portfolio volatility prevents sleep
2. Market regime has changed and you can't read it
3. Hit portfolio loss limits
4. Model not working in current environment
5. Positions hit profit targets
6. Rebalancing needed

**Vacation rule**: Go flat. Don't leave trades on. If you must, they should be long-term positions only, and have a trading partner monitoring.

---

### Ch.13 — Lessons on Trading & Execution

**Payment for Order Flow (PFOF)**: Brokers route your orders to market makers who pay for the flow. This means:
- Non-marketable limit orders get sent to the exchange that pays the broker most, NOT the exchange with the most liquidity
- Result: your limit order sits on a low-volume exchange while that price trades freely on CBOE
- **Takeaway**: Always check where your order is routed. Consider using direct routing when available.

**When to worry about assignment**:
- **Put-call parity**: C - P = S - X + (I - D)
- **Short puts**: Only assigned when the corresponding call's value < cost of carry. With near-zero interest rates, assignment is extremely rare
- **Short calls**: Only at risk near ex-dividend dates when dividend > value of the put opposite your short call
- **Rule of thumb**: If it's not near a dividend date, don't worry about assignment

**Short SPX calendar trade example**: Sep-Oct 1085 call spread sold for 13.25, bought back at 11.75 next day = 11.3% return in one day. This trade works when front-month IV is ≥ 2 points above back-month IV.

**Butterfly trading checklist**:
1. IV in 25th–75th percentile of 90-day mean? (Middle = best for flies)
2. Inter-month skew not too wide? (Compare VIX to VXV)
3. Intra-month skew not too steep? (Steep skew = hard fly trade)
→ All three checked? Safe to enter butterfly.

**Wing width rules**:
1. Never buy wings worth < $0.25 — they hedge nothing
2. Target at least 1:1 risk/reward on the butterfly
3. Always check the next-closest strike — if tightening wings costs < $1 per $5 of margin saved, tighten them
4. When long wings decay to < $0.25, either exit the trade or roll the wings closer

**Exit discipline**:
- Two exits per trade: one for loss, one for profit
- Loss exit: e.g., 20% of margin. Hit it = exit without hesitation
- Profit exit: e.g., 15% of margin. Hit it = take profits
- Scaling: Can exit in portions (sell 1/3 at 10%, 1/3 at 15%, 1/3 at 20%)
- The best loss is the FIRST loss

**Capital needed to trade for a living**:
- Know your annual expenses (e.g., $60K)
- Save 2 years of expenses ($120K)
- If earning 2%/month on trades, need $250K capital to generate $5K/month
- But only 50% invested on average → need $500K working capital
- Total: $120K savings + $500K capital = **$620K minimum**

---

### Ch.14 — The Other Greeks (Floor Lessons)

**Gamma behavior with IV changes** (OTM options):
- Small IV increase → OTM options GAIN gamma (become more ATM-like)
- Large IV increase → OTM options LOSE gamma (they've effectively become ATM, so they start behaving like ATM options with decreasing gamma)
- **For condor traders**: Initial IV spike makes your condor delta-sensitive faster than models predict. Only at extreme IV levels does gamma start falling.

**Portfolio weighting**: Delta is per $1 move in the underlying. A $1 move in IBM (0.5%) ≠ $1 move in Ford (6%). Must weight deltas by underlying price:
- SPY delta 30 × 10 contracts = SPX delta 30 × 1 contract (ratio ~10:1)
- Always weight delta and gamma by underlying price
- Vega and theta need minimal weighting adjustment

**Gamma Scalping — Two Methods**:

**Method 1: Pay the Decay** (active traders)
- Formula: X = √(2.8 × Theta / Gamma)
- X = price move needed to pay one day's decay
- Set scalps at 50% of X, round-trip twice per day
- Zero out deltas at end of day
- If underlying gaps past X, sell 75%+ of deltas immediately
- On the floor, Sebastian would scalp 10–30 times per day in active stocks

**Method 2: Delta/Gamma Ratio** (less active)
- Calculate delta/gamma ratio for the position
- When ratio exceeds a threshold (position-specific), hedge
- Simpler but less precise
- Suitable for part-time traders

**Key gamma insight**: "Volatility predicts price movement, not direction." Scalping at closer intervals captures more round-trips than waiting for the full theoretical move.

**SPY vs SPX gamma comparison**:
- SPY moves $3 → 2.5% move. Gamma × 3 = 5 × 3 = 15
- SPX moves $3 → 0.25% move. Gamma × 3 = 0.5 × 3 = 1.5 (irrelevant)
- SPX needs a 30-point move to match SPY's $3 gamma impact: 0.5 × 30 = 15
- Weight accordingly when combining positions

---

### Ch.15 — Conclusion: The Business Framework

**TOMIC framework summary** (Fig 15.1):
1. Insurance model (premium selling with reinsurance)
2. Risk management (2%/6% rules, diversification, tail hedges)
3. Infrastructure (broker, platform, analytics)
4. Core strategies (condors, butterflies, calendars, ratios)
5. 80% of success = discipline. 20% = strategy selection

---

## KEY FORMULAS

| Formula | Use |
|---------|-----|
| Max trade loss = 2% × AUM | Position sizing |
| Max portfolio heat = 6% × AUM | Portfolio risk limit |
| X = √(2.8 × θ / γ) | Gamma scalp distance (pay-the-decay) |
| C - P = S - X + (I - D) | Put-call parity (assignment check) |
| σ(K) = σ_ATM × (1 + b·x + c·x²) | Parabolic skew model |
| 1-day expected move = IV × √(1/365) × Spot | Expected move from IV |
| Annualized return = (1 + yield)^(365.25/DIT) - 1 | Annualizing trade returns |

---

## RECOMMENDED READING (from Appendix)

**Tier 1 (Beginner)**: Wolfinger's *The Rookie's Guide*, Bittman's works
**Tier 2 (Intermediate)**: Natenberg's *Option Volatility & Pricing*
**Tier 3 (Advanced)**: McMillan's *Options as a Strategic Investment*
**Tier 4 (Quant)**: Taleb's *Dynamic Hedging*, Augen's works

---

## ACTIONABLE RULES FOR OUR SYSTEM

1. **Iron condor entry**: Check % OTM (not just delta or credit). Same $0.60 credit can be 8.5% OTM (bad) or 10% OTM (acceptable) depending on IV regime
2. **ATR filter before entry**: If ATR suggests underlying will breach short strikes, don't enter
3. **Skew phase assessment**: Classify current market into Phase 1–5 before trade selection
4. **Card Game exit**: Close credit spreads when short option hits $0.10–$0.25. Don't wait for expiry
5. **Weekend theta**: Don't hold calendar spreads over weekend expecting free decay — it's already priced out by Friday
6. **Wing pricing**: Never buy protective wings worth < $0.25. They are decoration, not hedge
7. **3-day forward test**: Before adjusting, simulate +3 days at current, +1σ, -1σ. Adjust only if losing in 2/3 scenarios
8. **Gamma scalp formula**: X = √(2.8 × θ / γ), scalp at 50% intervals for more round-trips
