# Book 5: Building Winning Algorithmic Trading Systems — Kevin J. Davey

> *A Trader's Journey from Data Mining to Monte Carlo Simulation to Live Trading* (Wiley, 2014)

---

## Overview & Author Context

Kevin Davey is a retail-turned-full-time futures trader who won the World Cup Championship of Futures Trading in 2006 (148% return) and finished second in 2005 (107%) and 2007 (112%), all using algorithmic systems. He has an aerospace engineering background (B.S. Michigan, summa cum laude) and MBA. The book documents his 20+ year journey from losing trader to consistent winner, then walks through his complete system development process with a real worked example (euro day/night strategies) that he traded live.

**Key theme**: Strategy development is a factory — raw ideas go in, most become garbage, a few emerge as tradable gold. The process matters more than any single idea.

---

## PART I: A TRADER'S JOURNEY (Ch. 1–4)

### Chapter 1: The Birth of a Trader

- Started with Ken Roberts' head-and-shoulders course (junk mail) → discovered patterns only look good in hindsight
- Triple moving average crossover on live hogs → lost 30% of $5,000 account
- Tried the "opposite" system (George Costanza approach) → lost another 30%
- **Lesson**: What works in hindsight doesn't work forward. The opposite of a losing system is also a losing system (commissions/slippage must be doubled).

### Chapter 2: Enough Is Enough

- Read dozens of trading books → contradictory advice everywhere (stop-losses are essential / stop-losses are for losers)
- Built homemade backtesting in Excel/VB → created "Holy Grail" systems with 10 variables and 1M iterations. Results were too good to be true — never traded them (lucky!)
- Scale trading (Wiest's "You Can't Lose"): 90% annual return first year, then lost everything. Works only with massive capital and discipline
- Averaging down in wheat (1998): kept adding to losers, wired money to broker weekly, eventually lost $70K
- "Wild man" approach: random discretionary trading based on hunches → treaded water
- Mad cow disease trade (Dec 2003): bought cattle on a whim during emotional distress (son's death, father's death) → $5,400 loss, but this disaster triggered the shift to systematic trading

### Chapter 3: World Cup Championship

- **2005 (2nd place)**: X-day close breakout + RSI filter + ATR stops. 9 markets, daily bars. 40% drawdown mid-year before tripling account. Added to losers near year-end (old habit).
- **2006 (1st place)**: One copper trade from Feb–May = $28,875, >95% of year's profit. Then 7 months of slow decline. Stopped trading in December to protect lead. Later realized he remembered it differently than it happened — **memory distortion is dangerous in trading**.
- **2007 (2nd place)**: 50% drawdown by March, recovered to 100%+ return by year-end via Swiss franc and T-bond trends.
- **Key contest lessons**:
  - Goals and objectives dictate every development decision
  - For contest: accepted 75% max drawdown to target 100%+ return
  - Luck plays a role at the top — set yourself up to be near the top consistently
  - "Don't be impressed with the performance itself. Be impressed with the discipline in seeing a goal, chasing it, and realizing it."

### Chapter 4: Making the Leap to Full Time

Eight requirements for going full-time:

| Requirement | Right | Wrong |
|---|---|---|
| **Confidence** | Had it from contest wins | Had too much — contest ≠ full-time |
| **Capital** | Low six figures | Should have been $2–3M (friend's advice) |
| **Living expenses** | 3–5 years saved, separate from trading | Nothing wrong |
| **Family support** | 100% spousal support | Nothing wrong |
| **Home office** | Dedicated space | Kids touching the computer |
| **Strategies** | 3–5 live strategies | No backup strategies ready |
| **Brokers** | Multiple brokers, multiple clearing firms | Missed warning signs (lost money in Refco, PFG Best) |
| **Free time** | Always working, disciplined | Too one-dimensional, no balance |

---

## PART II: YOUR TRADING SYSTEM (Ch. 5–8)

### Chapter 5: Testing and Evaluating a Trading System

**BS Meter for performance results** (most BS → least BS):
1. Trading system vendors (top BS — never trust)
2. Novice DIY developers
3. Broker-supplied / CTA systems
4. Experienced DIY developers (lowest BS)

**Four ways to produce results**:
1. **Historical back testing**: easiest, most abused. Optimized results are always too good.
2. **Out-of-sample testing**: reserve 10–20% of data. Much better than full optimization.
3. **Walk-forward analysis**: aggregate of many out-of-sample periods stitched together. **Davey's recommended method.** Walk-forward results tend to stay consistent going forward.
4. **Real-time testing**: no hindsight bias, but painfully slow.

### Chapter 6: Preliminary Analysis

**Performance report quick-check numbers**:

| Metric | Threshold |
|---|---|
| Total net profit | ~$10K/year/contract minimum |
| Profit factor | >1.0 OK, >1.5 ideal |
| Total trades | 30–100 per rule in the strategy |
| Avg trade net profit | >$50/contract |
| Tharp Expectancy | >0.10 |
| Slippage & commission | Discard if $0. Use $5 commission + 1.5–2 ticks slippage per round turn |
| Max drawdown | Much smaller than total net profit |

**Equity curve visual checks**: slope (lower-left to upper-right), flat periods (short is good), drawdown depth/duration, fuzziness (less = better), absence of drawdowns (suspicious).

### Chapter 7: Detailed Analysis — Monte Carlo Simulation

Monte Carlo = shuffle historical trades randomly, build thousands of possible equity curves, derive statistics.

**Assumptions**: trades are independent (no serial correlation), historical trade distribution represents future.

**Key Monte Carlo outputs**:

| Metric | Davey's Threshold |
|---|---|
| Risk of ruin | <10% |
| Median max drawdown | <40% |
| Median annual return | >40% |
| Return/drawdown ratio (quasi-Calmar) | >2.0 |

**Critical insight**: "Traders can generally handle half the maximum drawdown they think they can handle." — Davey calls this "half of what you think it is."

### Chapter 8: Designing and Developing Systems

**Davey's Strategy Development Process** (factory metaphor):

1. Goals & Objectives → 2. Trading Idea → 3. Limited Testing → 4. Walk-Forward Analysis → 5. Monte Carlo Analysis → 6. Incubation → 7. Diversification → 8. Position Sizing → LIVE

Each step has a gate. Most strategies are discarded along the way. ~100–200 ideas tested per tradable strategy found.

**Tips for keeping the factory running**:
- Write down every trading idea that intrigues you
- No idea is too silly to test
- Test programming mistakes — some become profitable "serendipitous" systems
- Try the opposite if things go bad
- Swap ideas with other traders
- Target 1–5 strategy tests per week

---

## PART III: DEVELOPING A STRATEGY (Ch. 9–16)

### Chapter 9: Goals (SMART/SMARTER)

- **S**pecific, **M**easurable, **A**ttainable, **R**elevant, **T**ime-bound
- **E**valuate, **R**eevaluate when goals prove unattainable
- Example SMART goal: "Create a euro trading system in 6 months returning 50%/year with 30% max DD, 45%+ win rate, following all development process steps."
- Also create a "wish list" of desired traits (market, time of day, frequency, etc.)

### Chapter 10: Trading Idea

**Entries**:
- Keep simple, limit optimizable parameters to 1–2
- Think differently — moving averages have been tested ad nauseum
- Start with single rule, add conditions only if they significantly improve performance
- Entry importance scales with trade duration: critical for scalping, less so for swing trading

**Exits** (often underappreciated):
- Stop and reverse, technical-based, breakeven stops, stop-losses, profit targets, trailing stops
- Exits have huge impact on profitability
- Breakeven stops typically limit profit potential

**Market selection**:
- "One size fits all" (multi-market): more robust but harder to develop; cherry-picking best performers is hidden optimization
- Single-market: easier to develop, can tailor to market characteristics
- Davey uses both approaches

**Time frame**: shorter = more trades = more costs = harder to find edge. Most of Davey's best strategies are swing (days–weeks), not day-trading. Professionals dominate short time frames.

### Chapter 11: Data Considerations

- Use 5–10 years minimum. More data = more market conditions seen = more confidence.
- **Pit vs electronic**: use consistent sessions throughout history. Create custom "pit session" for electronic data to match historical pit hours.
- **Continuous contracts**: back-adjusted contracts can go negative (OK for testing). **Never divide or multiply prices in back-adjusted contracts** — ratios change at every rollover.
- **Forex data**: decentralized = different data per broker. Use market orders only to avoid phantom fills from bid/ask discrepancy.

### Chapter 12: Limited Testing

**Test on a small chunk of data** (1–2 years from the full 10), not the whole dataset. Testing "burns" data — subsequent tests on same data introduce curve-fitting.

**Entry testing** (three methods):
1. Fixed stop and target → does entry win >50%?
2. Fixed-bar exit → does entry pick direction quickly?
3. Random exit → entry still profitable with random exits?

**Exit testing**: similar-approach entry, random entry.

**Core system test**: entry + exit together. Look for 70%+ of optimization iterations profitable.

**Monkey testing** (dart-throwing monkey benchmark):
- Monkey entry + real exit (8,000 runs)
- Real entry + monkey exit (8,000 runs)  
- Monkey entry + monkey exit (8,000 runs)
- Strategy should beat 90%+ of monkey runs
- **Also run monkey tests periodically on live results** — if strategy no longer beats monkeys, the edge may be gone

### Chapter 13: Walk-Forward Analysis

**Walk-forward primer**: optimize on in-sample period, apply best parameters to adjacent out-of-sample period, repeat. Stitch out-of-sample results together for the equity curve.

**Walk-forward inputs**:
- **In period**: enough trades for meaningful optimization (25–50 trades per input variable)
- **Out period**: 10–50% of in period
- **Fitness function**: net profit (simplest, Davey's most-used), linearity of equity curve (best for position sizing), return on account
- **Anchored vs unanchored**: unanchored preferred (only recent data in optimization window)

**Caution**: selecting the best in/out combination IS optimization. If you must test multiple in/out pairs, hold out the last 3 years as a true out-of-sample check.

**Create a walk-forward history strategy** with parameters changing by date — ensures seamless backtest and catches mid-trade parameter changes.

### Chapter 14: Monte Carlo Analysis and Incubation

**Monte Carlo**: run on walk-forward trade results, not optimized results. Focus on return/drawdown ratio >2.0.

**Incubation** (3–6 months before live trading):
- Watch the strategy perform in real time without trading it
- Removes emotional attachment from development effort
- Catches major development mistakes before real money is at risk
- Reveals if you actually like trading the strategy's style
- Usually done without real money, unless limit orders or exotic bars need live verification

**Avoid in backtesting**:
- Buy fills at bar lows / sell fills at bar highs
- Limit orders filled on touch (reality: price must penetrate)
- Exotic bar types (Renko, Kase)
- Entry and exit on same bar

### Chapter 15: Diversification

"Diversification, done properly, is probably the closest thing I've ever seen to the so-called trading Holy Grail."

**Design for diversification**: vary market, bar size, time session, entry style, exit style between strategies. Different behavior → uncorrelated results → diversification.

**Measuring diversification**:
1. Daily return correlation (R² in Excel) — lower is better
2. Linearity of combined equity curve (R² of linear regression)
3. Maximum drawdown comparison
4. Monte Carlo return/drawdown ratio improvement

**Key finding**: the combined euro day+night system had return/DD of 6.7 vs 5.2 (day) and 2.2 (night) individually.

**Benefit**: individual system goals can be relaxed since diversification improves the portfolio. Many "decent" strategies > one "super-terrific" strategy.

### Chapter 16: Position Sizing and Money Management

**Core principles**:
- No optimum position sizing exists (don't believe claims of "the one best method")
- Risk and reward are a team — more reward always means more risk
- Position sizing CAN be optimized → but then you've optimized on a meta-level
- Losing systems cannot become winners through position sizing
- Winning systems CAN become losers through aggressive position sizing
- "The fantasy of size": trading 100 contracts requires a $1M account, not just "adding zeros"
- Martingale: almost always wins short-term, guaranteed ruin long-term
- No position sizing = wasting a winning system

**Davey's approach — Fixed fractional sizing**:

```
N = int(x × Equity / LargestLoss)
```

Uses Monte Carlo simulation to find the value of x that maximizes return/drawdown ratio, subject to:
- Risk of ruin <10%
- Max drawdown <40–45%

For his euro system: x = 0.175 (aggressive but calculated).

**Portfolio position sizing**: analyze all systems together, find optimal x for each system simultaneously.

**Start with one contract always** — reveals live trading issues (automation bugs, slippage reality) at minimum cost. Let profits fund additional contracts.

### Chapter 17: Documenting the Process

Uses an Excel spreadsheet tracking: SMART goals, strategy name/description/edge, market/bars/dates, entry/exit rules, limited testing results, walk-forward results (in/out period, fitness function, anchored/unanchored), Monte Carlo results (return/DD ratio), incubation pass/fail, diversification check, position sizing check, final notes.

**Strategy naming convention**: `KJD2013-10 BrkOut A` (initials, date, description, version letter). Add "W" for walk-forward code, "H" for historical walk-forward version.

Keep a separate list of entry/exit ideas → never run out of things to test.

---

## PART IV: CREATING A SYSTEM — Worked Example (Ch. 18–19)

### Chapter 18: Goals, Initial and Walk-Forward Testing

**SMART Goal**: "Create intraday euro strategy earning 50% annual return, <25% median max drawdown, return/DD >2.0, 55%+ winning days, two trades/day max, one month development time."

**Two strategies developed**:

| | Euro Night (Strategy 1) | Euro Day (Strategy 2) |
|---|---|---|
| **Bars** | 105-minute | 60-minute |
| **Session** | 6 PM – 7 AM ET | 7 AM – 3 PM ET |
| **Entry** | Mean-reversion limit: avg high of X bars − ATR multiplier | Highest high of Y bars + downward momentum → limit order Z ticks above high |
| **Exit** | Stop $425 (34 ticks), optimized profit target, close at session end | Stop $425, $5,000 profit target (effectively "let it run"), close at session end |
| **Style** | High win%, lots of small wins, occasional big loser | Lower win%, primary profit generator, rides trends |
| **Edge** | "Rubber band" reversal — price stretches until limit fill, then bounces back | Same concept but on medium-term excursions |
| **Data** | Jan 2009 – present (~4 years) | Same |

**Limited testing results**: both strategies passed all tests (entry fixed-stop, fixed-bar exit, exit similar-approach, core system, monkey testing). 76–85% of optimizations profitable.

**Walk-forward testing**: ran unanchored WFA with rolling optimization windows.

### Chapter 19: Monte Carlo Testing and Incubation

**Monte Carlo results (individual, $6,250 start, <10% ruin)**:

| | Euro Day | Euro Night | Combined |
|---|---|---|---|
| Max DD | 23.7% | 25.0% | 25.8% |
| Return | 129% | 52% | 176% |
| Return/DD | 5.45 | 2.0 | **6.7** |
| Prob profit | 94% | 85% | 95% |
| Risk of ruin | 4% | 6% | 5% |

**Combined > individual** — diversification effect. The combined system return goes up while drawdowns don't stack.

**Incubation evaluation** (3 methods):
1. Student's t-test: 56% chance distributions are not different → acceptable
2. Data distribution histogram overlap: good overlap between WFA and incubation
3. Equity curve visual: no visible break between WFA and incubation periods

**Profit consistency** (Monte Carlo):
- 59.6% of weeks profitable
- 74.8% of months profitable
- 86.2% of quarters profitable
- 98.8% of years profitable

**Outlier dependence**: system relies on 4–6 large winning trades per year → **must take every single trade** because the one you miss may be the big winner that comes only once a year.

---

## PART V: CONSIDERATIONS BEFORE GOING LIVE (Ch. 20–22)

### Chapter 20: Account and Position Sizing

**Quitting point**: average of (1) 1.5× worst historical drawdown and (2) 95th percentile Monte Carlo max drawdown → $5,000 single-contract drawdown limit.

Three keys to quitting:
1. Base it on the system you're trading
2. Write it down
3. Follow it

**Minimum account**: exchange margin ($2,750) + quit-point drawdown ($5,000) = $7,750 minimum. Using $8,500 for position sizing headroom.

**Fixed fractional sizing**: x = 0.175, BigLoss = $885.

| Equity | Contracts |
|---|---|
| <$10,114 | 1 |
| $10,114 | 2 |
| $15,171 | 3 |
| $20,229 | 4 |
| $50,571 | 10 |

Tested unequal sizing (2:1 ratio between strategies) → worse results, rejected.

### Chapter 21: Trading Psychology

**Algorithmic trading is NOT emotionless.** Emotions manifest differently:

- **When to begin**: establish a rule (e.g., after 4 months incubation) and stick to it. Don't enter current winning trades (bad reward/risk); do enter current losing trades.
- **When to quit**: pre-define criteria, write it down, tell someone. Options: max drawdown, consecutive losers, amount lost per period, equity moving average break, statistical process control.
- **Taking every trade**: the voice says "skip this one after 5 losers" → following it = gambling, not algo trading. **Trade multiple strategies** to make rule-following easier.
- **Jumping the gun**: entering before signal = creating untested strategy
- **When things go wrong**: sync real position with strategy position immediately using market orders. Don't finesse.

"The key to successful algorithmic trading is discipline."

### Chapter 22: Other Considerations

**Brokers**: use multiple accounts at multiple brokers (one per strategy). PFG Best fraud lesson — spread risk.

**Automation**: automated ≠ unattended. Check positions every few hours.

**VPS**: use for high-frequency or many-trades-per-day strategies.

**Order location**: know whether orders sit on your PC, broker's server, or exchange. Plan for each failure mode.

**Rollover methods** (for swing strategies):
1. Quick roll (two market orders): fastest, most expensive (pay two spreads)
2. Leg in roll (one market + one limit): cheapest if done right, risky if chasing
3. Exchange spread roll: simultaneous fill on both legs, cost between methods 1 and 2
- Never use limit orders on both sides — will leave you half-rolled

---

## PART VI: MONITORING A LIVE STRATEGY (Ch. 23–24)

### Chapter 23: Monitoring Tools

**Bird's-eye equity chart**: WFA + incubation + live on one chart. Updated every few weeks. Quick visual: is live performance consistent with historical?

**Monthly summary spreadsheet**:
- Two key columns:
  - **Return efficiency** = actual return / expected return (target: 70–100%)
  - **Drawdown efficiency** = 1 − (actual DD / expected DD) (target: close to 100%)
- Individual strategy sheets feed summary page
- Track on one-contract basis (no position sizing muddying the view)
- Performance "too good" can be a bad sign → revert to mean likely

**Daily tracking graph**:
- Plot cumulative equity vs n × avg (expected value line)
- Add ±σ bands: `n × avg ± sqrt(n) × σ × X` (X=1 for 68%, X=2 for 95%)
- If equity falls below lower band → system may be broken
- Even winning systems can show negative lower bands for many trades (positive expectancy takes time to dominate)
- Can use Monte Carlo percentile curves instead of normal-distribution bands (avoids normality assumption)

**Using the graph to quit**: if live performance falls below 10th percentile line for extended period, consider stopping.

**Track actual vs predicted performance**: Davey's actual fills usually slightly better than predicted (conservative slippage estimates).

### Chapter 24: Real-Time Diary (Euro System Live Trading)

**Week 4**: Breakeven. Not surprised. Results within expectations.

**Week 7**: Cumulative equity near 10th percentile. Actual performance: −$746 vs expected +$1,441. Not hitting quit point ($5K DD), so keep trading. "Statistics can be manipulated very easily, so be careful making any conclusions based on them."

**Week 8**: Down 5% from start. Four winning weeks, four losing. Fills better than expected. No reason to stop.

**Week 9 — Automation issue**: Unfilled limit order wasn't canceled by software, rested at exchange overnight, filled at wrong time → $550 loss. Response: check statements daily, check platform for uncanceled orders, improve position checking. "I am to blame. I am the caretaker."

**Week 9 — Limit order fills**: Got filled at exact bar low (limit touched, not penetrated). Back-test engine didn't show the trade. Net: ~$400 gain vs backtest. Roughly offset the automation loss.

**Week 12**: Down 10% (strategy-calculated), −4.5% (actual, better fills). Fills $550 better than strategy predicts. Near 10th percentile but within quit criteria.

**Week 13**: Reviewed "next best alternative" — every 6 months, compare current systems to bench candidates. Might swap underperformers. "Most people don't have the patience... They jump from system to system, never giving any system a fair chance."

**Week 15**: Finally profitable. Up 1% (strategy) / 9% (actual). Still underperforming vs expectations. "This approach relies on a handful of big profit trades per year, and so far in live trading there have not been any."

---

## PART VII: CAUTIONARY TALES (Ch. 25)

### Character Archetypes and Lessons

| Character | Flaw | Lesson |
|---|---|---|
| **Don Demo** | Only trades demo, never succeeds live | Demo success ≠ real-money success |
| **Gus the Guru** | Analyzes brilliantly, can't trade, sells advice | Beware gurus who don't trade |
| **Paul the Predictor** | Claims market prediction ability | No one can predict the market |
| **Cal the Complication King** | Obscures simplicity with jargon | KISS — simple concepts work best |
| **Pay Me Peter** | $2,500 system based on 5-day backtest | Inflated self-worth = doom |
| **Frank Five Hundred** | $500 account, refuses advice | Don't start with $500. Listen to free advice. |
| **Billy the Boaster** | Paranoid, delusional, claims $15K→$1B in a year | Live in reality |
| **Connie the Compounder** | Compounding hype, no actual trading, IRS fraud | Compounding isn't everything |
| **Ian vs Illuminati** | Conspiracy theories, banned everywhere | Stay away from fighting vendors |
| **Suki the Spinner** | Brags about non-walk-forward backtest results | Beware of backtests — assume they're garbage |
| **Slick Sam** | Trading room operator, demo account, bans skeptics | Vendors want your money, not your success |

---

## CONCLUSION — Key Takeaways

1. **Trading is exceedingly tough.** Part-time retail traders are up against professionals who are great at taking your money.
2. **No Holy Grail exists.** No magic $100 or $10,000 system.
3. **Where there is reward, there is risk.** It may be hidden in the equity curve.
4. **The best road to profits is finding your own strategy** that meets your goals. The process is not easy.
5. **Strategy is the cake, psychology and position sizing are icing.** Positive thinking won't fix a losing strategy. Position sizing won't make a loser profitable.
6. **You need to test 100–200 ideas** before finding something worth trading. Most people quit before that.
7. **Take every trade.** The one you miss may be the big winner.
8. **Discipline is everything.** Follow the rules. When emotions take over and you don't follow the rules, you're gambling.

---

## Appendices

- **Appendix A**: TradeStation EasyLanguage code for 4 monkey testing strategies (baseline, random entry, random exit, both random)
- **Appendix B**: Euro Night Strategy code — limit entries based on average high/low ± ATR multiplier, limit exits based on true range target, $425 stop, exit on close
- **Appendix C**: Euro Day Strategy code — limit entries based on highest high/lowest low breakout with momentum filter, $425 stop, $5,000 profit target, exit on close
- **Companion website**: Monte Carlo simulator, development worksheet, equity/drawdown builder, monthly summary sheets, daily tracking worksheet

---

## Applicability to Our Options System

| Davey Concept | Application |
|---|---|
| Walk-forward analysis | Validate any ML/pattern-based options strategy on rolling out-of-sample windows |
| Monte Carlo simulation | Stress-test options strategy P&L distribution, estimate realistic drawdowns |
| Monkey testing | Benchmark options entry signals against random timing |
| Incubation (3–6 months paper) | Paper-trade options strategies before live capital |
| Diversification | Combine mean-reversion (theta strategies) with directional (delta strategies) |
| Fixed fractional sizing | Position size options trades based on max loss per trade |
| Quitting criteria | Pre-define when to stop an options strategy (1.5× worst DD) |
| Return/drawdown ratio >2.0 | Use as acceptance gate for any options system |
| Daily tracking bands | Monitor live options equity vs expected ±σ bands |
| Document everything | Track every strategy version, test result, and parameter change |
