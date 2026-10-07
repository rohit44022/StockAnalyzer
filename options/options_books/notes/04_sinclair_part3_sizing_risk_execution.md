# Sinclair — Positional Option Trading: Part 3

## Chapters 9–10, Appendices: Position Sizing, Risk Management, Execution

---

## Ch.9 — Position Sizing: Kelly Criterion and Beyond

### The Kelly Criterion

**Core idea**: there is a mathematically optimal bet size that maximizes long-term growth rate.

**Simple Kelly** (two outcomes, win W with probability p, lose L):

f* = (p × W − (1−p) × L) / (W × L)

Example: 55% chance to win $1, 45% chance to lose $1 → f* = 0.10 (bet 10% of bankroll).

### Non-Normal Distributions (Options Reality)

Kelly assumes two outcomes. Options payoffs are not two-outcome — they have fat tails and skew. Sinclair derives the generalized version:

**Multi-outcome Kelly**: maximize expected log-growth rate across the full distribution of outcomes.

Key equations (9.16–9.38 in text): the optimal fraction accounts for:
- All moments of the return distribution (mean, variance, skewness, kurtosis).
- The full shape of the P/L distribution, not just mean/variance.

### The Over-Betting Problem

**Over-betting is worse than under-betting.** This is the single most important sizing insight.

| Over-bet by | Growth drag (normal) | Growth drag (non-normal) |
|-------------|---------------------|--------------------------|
| 10% | 0.22% | 0.92% |
| 15% | 1.04% | 1.61% |
| 20% | 1.69% | 2.15% |

- **25% over-betting** turns a positive-EV strategy **negative** in growth terms.
- Non-normal distributions (options!) make over-betting even more destructive.
- Under-betting by 25% loses only ~7% of potential growth. The asymmetry is extreme.

### Practical Sizing Rule

**Use 0.05–0.48× Kelly.**

- Full Kelly is theoretically optimal but assumes perfect knowledge of edge and distribution.
- Estimation error in your edge means you're always uncertain about the true Kelly fraction.
- Half-Kelly (0.5× Kelly) sacrifices 25% of growth but reduces variance by 50%.
- Sinclair's numbers: 0.05–0.48× Kelly produces 9.4–9.6% CAGR with massively reduced drawdowns vs. full Kelly.

### Growth Rate Simulations

Simulated $100 portfolio, μ=5%, σ=30%, 10,000 paths:

| Strategy | Mean | Median | 90th pctile | 10th pctile | Max DD |
|----------|------|--------|-------------|-------------|--------|
| No stops | $101.70 | $102.20 | $129.50 | $91.70 | 26% |
| Fixed stop | $102.20 | N/A | $187.60 | $86.30 | 38% |
| Percentage stop | $117.13 | N/A | $305.60 | $89.30 | 30% |

Percentage-based trailing stops improve median and upside while slightly worsening drawdowns — but the real value is behavioral (forces discipline).

### Higher-Order Kelly Adjustments

The standard Kelly uses mean and variance. Sinclair extends to include:

**Adjusted fraction (eq. 9.37–9.38)**:

f_adj = f_kelly × [1 − (skew/6)×f + ((kurt−3)/24)×f²]

Where skew < 0 and kurt > 3 (typical for short vol) → the adjusted fraction is **smaller** than naive Kelly. You should bet less than mean/variance Kelly tells you.

### Variance of Kelly Estimates

Even with 1,000 trades:
- Kelly estimate mean: $0.059
- Kelly estimate std: $1.137
- Kelly estimate has **negative** skew: -6.199

You think you know your edge, but your estimate is noisy and left-skewed. This is why fractional Kelly is mandatory.

---

## Ch.9 (continued) — Stop Losses and Risk Limits

### Stop Losses: The Debate

**Arguments for stops:**
- Prevent catastrophic loss on any single position.
- Enforce discipline (remove emotion from exit decisions).
- Bound worst-case drawdowns.

**Arguments against stops:**
- Mean-reverting underlyings: stop = sell at the worst price, right before it bounces.
- Options: a stop-loss on an option position may force you to crystallize a temporary unrealized loss that theta would have recovered.
- Whipsaw: tight stops in volatile markets get triggered repeatedly.

### Sinclair's View

- **Stop losses have a real cost** — they reduce expected return. The cost comes from selling at temporarily adverse prices.
- **But the tail risk reduction is worth it** for survival.
- Key insight: the value of stops is **not** in improving expected return. It's in ensuring you **survive** to realize the long-term edge.

### Percentage-Based Trailing Stops

Sinclair favors percentage-based trailing stops:
- Set a maximum acceptable loss per position (e.g., 2× premium received).
- Trail the stop upward as the position profits.
- The stop enforces position-level risk control.

### Portfolio Risk vs. Position Risk

- Individual position stops prevent single-name blow-ups.
- Portfolio risk is about correlated losses across positions.
- In a crash, all your short-vol positions lose simultaneously. Position-level stops don't help if every position hits its stop at once.
- Need portfolio-level risk limits: maximum total vega exposure, maximum total delta, VaR limit.

### Key Level and Game Theory

- Round numbers (50, 100, etc.) act as floors/ceilings in markets.
- Stop placement near round numbers creates predictable order flow.
- Market-makers know where stops cluster and can gun them.
- **Don't place stops at obvious levels** (just below round numbers, just below support).

### Kelly + Stops Together

Optimal approach:
1. Size each position using fractional Kelly (0.25–0.5× Kelly).
2. Apply a position-level stop (2–3× premium).
3. Apply a portfolio-level drawdown limit (e.g., -15% → reduce all positions by 50%).
4. The combination gives both optimal growth and survival assurance.

---

## Ch.10 — Operational Risk and Market Horror Stories

### Non-Market Risk Is the Killer

Most traders who blow up don't lose to the market — they lose to operational failures:
- Counterparty default (your broker/exchange goes down).
- Fraud (Madoff, FTX-style).
- Model error (using wrong inputs, coding bugs).
- Execution failures (fat-finger trades, system outages).
- Regulatory/legal changes.

### Inflation Risk

- Options are priced in nominal terms. Inflation erodes real returns.
- In hyperinflationary environments (Zimbabwe 1993, Venezuela 2018), options become worthless as the underlying currency collapses.
- Moderate inflation (5–10%) subtly erodes option premium income. Real returns = nominal returns − inflation.

### Counterparty Risk

**The QuadrigaCX lesson**: Canadian crypto exchange CEO died in 2019 with sole custody of US$190 million in crypto. All lost.

**Rules:**
1. Use regulated exchanges with clearinghouse guarantees.
2. Never concentrate assets with a single counterparty.
3. Third-party custody is non-negotiable.
4. If returns look too consistent (12% annual, no down months like Madoff), it's probably fraud.
5. Due diligence: audited financials, independent verification, check regulatory filings.

### Specific Blow-Ups Analyzed

**Barings Bank (1995)**: Nick Leeson, unauthorized Nikkei futures positions, hidden in error account 88888. Loss: £827 million. Bank collapsed after 233 years. Lesson: risk controls and auditing are not optional.

**Long-Term Capital Management (1998)**: Nobel laureates running leveraged convergence trades. Worked until Russian debt crisis caused all correlations → 1. Loss: $4.6 billion. Lesson: leverage + correlation = death. "Markets can remain irrational longer than you can remain solvent."

**Madoff (2008)**: $50 billion Ponzi scheme. Claimed consistent 12%/year through "split-strike conversion" strategy. Red flags were obvious to quantitative analysis (Markopolos flagged it to SEC five times starting in 2000). Lesson: if you can't explain the source of returns with arithmetic, it's not real.

**XIV/VIX ETN Blow-Up (Feb 2018)**: Inverse-VIX ETNs designed to short VIX futures. VIX spiked 100%+ intraday. XIV lost 96% in one day, was liquidated. Prospectus warned of this possibility, most holders didn't read it.

### Operational Checklist

1. **Custody**: where are your assets held? By whom? Audited?
2. **Counterparty**: who is on the other side? What happens if they fail?
3. **Margin**: understand your margin requirements under stress (not just normal conditions).
4. **Technology**: backup systems for order entry. What if your platform goes down mid-trade?
5. **Legal/regulatory**: understand tax treatment, reporting requirements, position limits.
6. **Model risk**: validate your models with out-of-sample data. Don't trust a backtest that hasn't been stressed.

---

## Appendix 1 — BSM Assumptions (What Actually Matters)

### Assumptions That Don't Matter Much

1. **Risk-free rate**: getting the rate wrong by 1% changes a 1-year option price by ~$0.23 on a $100 stock. Trivial.
2. **Dividends**: BSM assumes continuous dividend yield. Discrete dividends matter for deep ITM options near ex-date, otherwise minor.

### Assumptions That Matter a Lot

1. **Lognormal distribution**: real returns have fat tails and skew. BSM underprices OTM puts and overprices OTM calls. This is why the skew exists.
2. **Constant volatility**: vol is not constant (GARCH, regime changes). BSM can't handle vol-of-vol.
3. **Continuous trading**: markets close, gap, and jump. BSM assumes you can delta-hedge continuously, but you can't.
4. **Traded underlying**: BSM requires the underlying to be freely tradeable for replication. Works for stocks/indices. Fails for non-traded assets (weather, real estate, private companies).

### Why BSM Survives

Despite its wrong assumptions:
- It standardizes communication (everything → IV).
- Model risk is reduced by fitting to market prices (calibration).
- Ad-hoc adjustments (skew, term structure) patch the worst failures.
- No alternative model is consistently better in practice.
- As of 2019, BSM variants account for ~93% of all options pricing.

**93% of options pricing uses BSM or close variants.** The model's flaws are known and priced in via skew and term structure adjustments.

---

## Appendix 2 — Volatility Estimation Techniques

### Three-Point Estimator

Use expert judgment to set three volatility scenarios (low, mid, high), weight them:

Estimate = (low + 4×mid + high) / 6

Example: vol likely 20%, could be as low as 15% or high as 30%:
Estimate = (15 + 4×20 + 30) / 6 = 21.7%

### Confidence Intervals

93% of the time, realized vol falls between 60% and 140% of current vol estimate.

For a 30-day estimate: 95% CI requires ~30 observations → error bound ≈ ±10%.

### Practical Rules

- Short lookback periods (10 days) are noisy but responsive.
- Long lookback periods (60+ days) are stable but lag.
- Sweet spot: 20–30 day lookback, updated daily.
- Weighting recent observations more heavily (EWMA) improves responsiveness without adding complexity.

---

## Appendix 3 — Execution: Transaction Cost Framework

### Three Components of Transaction Costs

1. **Commissions**: fixed per-contract fee. Smallest component for most liquid options.
2. **Bid-ask spread**: the price of liquidity. Market-makers provide immediacy, you pay the spread.
3. **Market impact**: your order moves the price against you. Invisible but often the largest cost for size.

### Bid-Ask Spread Reality

UVXY example (Table A3.1):
- Bid-ask: $20.64–$20.65 (1¢ wide, 200 shares bid, 800 offered).
- 5,000 shares at market: average fill $20.669 (buy) or $20.608 (sell).
- Effective spread for 5,000 shares: $0.061 (6× the quoted spread).

**Lesson**: quoted spread is the minimum cost. Actual cost scales with order size.

### Market Impact: Permanent vs. Temporary

- **Temporary impact**: your order temporarily pushes the price. It reverts after your order fills.
- **Permanent impact**: your order reveals information. The price doesn't fully revert.
- Rule of thumb: ~50% of impact is permanent.
- For options: market-makers adjust their quotes after filling your order based on what they infer about your information.

### VWAP as Benchmark

- VWAP (Volume-Weighted Average Price) = average price weighted by volume throughout the day.
- Executing at VWAP means you didn't beat the market but you didn't get ripped off.
- Modern brokerages provide VWAP algos — use them for orders >10% of daily volume.

### Timing Cost

- Moving quickly (aggressive execution): higher market impact, but you get the price you want now.
- Moving slowly (patient execution): lower impact, but the price might move against you while you wait.
- The trade-off depends on whether the trade is information-driven (act fast) or decay-driven (be patient).

### Practical Example

Straddle trade:
- Market: 2.1 bid / 2.5 ask. Mid-market: 2.3.
- You want to sell at 2.3. Market-maker offers 2.1.
- You try limit at 2.2. Get filled at 2.1 (1 contract) and 2.2 (rest). Average: ~1.1 above intrinsic.
- Your theoretical edge was 0.2 (IV premium). After execution costs of 0.1, net edge: 0.1.
- **Half your edge went to transaction costs.**

### Execution Rules

1. Never use market orders for options. Always use limits.
2. Start at mid-price, walk toward the natural side in small increments.
3. For multi-leg trades, use the exchange's combo/spread order types.
4. Don't trade illiquid options (wide spreads eat your entire edge).
5. Monitor fill quality over time. Track slippage per strategy.

---

## Key Takeaways — Part 3

1. **Use fractional Kelly (0.25–0.5×).** Full Kelly is theoretically optimal but practically suicidal due to estimation error. Non-normal distributions make this even more critical.
2. **Over-betting destroys wealth.** 25% over-bet turns positive EV negative. Always err toward under-sizing.
3. **Stops are insurance, not alpha.** They reduce expected return but ensure survival. Percentage-based trailing stops are the least-bad option.
4. **Operational risk kills more traders than market risk.** Counterparty failure, fraud, technology failures — non-market risks are non-recoverable.
5. **Transaction costs eat 30–50% of edge** for many strategies. Track and minimize them religiously.
6. **BSM is ~93% of the industry.** Its flaws are well-known and compensated for. Don't waste time on exotic models unless you're a quant researcher.

---

## NSE / Indian Market Notes

- NSE commissions are low (₹20/order flat at discount brokers) but STT (Securities Transaction Tax) on option selling is significant: 0.0625% of premium on sell-side. This is a fixed cost that cannot be reduced.
- Bid-ask spreads: tight for Nifty/BankNifty ATM options, very wide for OTM and stock options. Stick to liquid strikes.
- Market impact on NSE: significant for stock options (low volume). Index options have better depth.
- SPAN margins on NSE: higher than US → Kelly fractions should account for margin lockup reducing capital efficiency.
- Counterparty risk on NSE: clearing corporation (NSCCL) guarantees all trades. Individual broker risk remains (use brokers with strong SEBI compliance).
- Execution: NSE provides limit orders, bracket orders, cover orders. No native VWAP algo for retail — manual execution required.
