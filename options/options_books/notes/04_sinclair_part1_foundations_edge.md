# Sinclair — Positional Option Trading: Part 1

## Chapters 1–5: BSM Framework, Market Efficiency, Volatility Forecasting, Variance Premium, Finding Trades

---

## Ch.1 — Options as a Simplified Tool

### BSM Is Not a Predictive Model

BSM is a simplifying framework that converts option prices → implied volatility, making comparison possible across strikes/expiries. It is not a statement that markets follow GBM or that vol is constant. Market-makers know this; they use BSM the way a carpenter uses a tape measure — the tool has known limits but it standardizes communication.

### The Fundamental Equation

**P/L = Vega × (σ_implied − σ_realized)**

- If you sell options at IV 30% and realized vol turns out to be 25%, you pocket 5 vega-points of profit.
- Everything in the book flows from this equation. Every edge is ultimately about predicting the gap between implied and realized.

### Greeks as Language

- Delta: directional exposure. Gamma: convexity / acceleration. Theta: time decay (the "rent" paid for gamma). Vega: volatility exposure.
- For positional traders (hold to near-expiry), delta and vega dominate. Gamma/theta matter more for market-makers who re-hedge intraday.
- BSM Greeks are model-dependent but robust enough for position sizing and risk control.

### Implied vs. Realized — Two Different Things

- Implied vol is the market's consensus price for uncertainty, not a forecast.
- Realized vol is backward-looking measurement of actual moves.
- The persistent gap (implied > realized) is the variance premium — the central edge in options.

---

## Ch.2 — Efficient Markets and Practical Edges

### EMH: Approximately True, Not Perfectly True

- Strong EMH (all information, including private, is priced in) is false — insider trading is profitable.
- Semi-strong EMH (all public info is priced in) is approximately true but has known exceptions.
- Weak EMH (past prices contain no predictive info) is mostly true, but momentum exists.

### Inefficiencies vs. Risk Premia

- A risk premium is compensation for bearing a risk others want to shed. It persists because the risk is real.
- An inefficiency is a market mistake. It gets arbitraged away once discovered.
- Most "anomalies" are risk premia, not inefficiencies. The variance premium is a risk premium — it compensates sellers for left-tail crash risk.

### Alpha Decay

- Once an edge is published, it decays. McLean & Pontiff (2016): academic publication cuts anomaly returns by 32% post-publication, 58% post-sample.
- Capacity matters: a strategy that works for $1M may not work for $100M.
- Crowding kills edge. If too many people sell vol, the variance premium shrinks.

### Behavioral Finance

Key biases that create persistent mispricings:
- **Loss aversion**: people feel losses 2x more than equivalent gains → overpay for puts (protective insurance).
- **Anchoring**: traders anchor to recent vol levels, underreact to regime changes.
- **Availability heuristic**: recent memorable events (crashes) get overweighted.
- **Overconfidence**: traders overestimate their forecasting ability.
- **Disposition effect**: sell winners too early, hold losers too long.

### What This Means for Options

The variance premium likely persists because:
1. Structural demand: portfolio managers must buy puts for insurance.
2. Behavioral: people overweight crash scenarios (availability heuristic).
3. Risk-based: selling vol carries genuine left-tail risk that most can't stomach.
4. Agency: fund managers can't afford to show -40% drawdowns even if long-run EV is positive.

---

## Ch.3 — Volatility Forecasting

### Key Result: Vol Is Forecastable, But Consensus Is Hard to Beat

- Volatility is serially correlated (today's vol predicts tomorrow's vol).
- EWMA (exponentially weighted moving average) and GARCH produce roughly equivalent forecasts.
- Simple models work nearly as well as complex ones. The marginal improvement from GARCH(1,1) over a 20-day EWMA is small.

### Ensemble Averaging

- Combining multiple forecasting methods (EWMA, GARCH, realized vol measures) via simple averaging outperforms any single method.
- This works because individual model errors are partially uncorrelated → averaging reduces noise.

### Forecasting Horizons

- Short-term (1–5 days): high autocorrelation, easiest to forecast. Use recent realized vol.
- Medium-term (1–3 months): moderate predictability. Mean-reversion dominates.
- Long-term (6+ months): vol converges toward long-run average (~15–20% for S&P). Harder to add value.

### Practical Forecasting Rules

1. Start with current realized vol (close-to-close or high-low estimator).
2. Compare to implied vol. If IV >> RV, selling premium has historical edge.
3. Blend with mean-reversion: extreme vol (high or low) tends to revert.
4. Don't try to be clever. Simple models are robust; complex models overfit.

### What NOT to Do

- Don't use ARIMA or similar for vol (it's designed for price levels, not volatility).
- Don't forecast point values — forecast ranges/distributions.
- Don't assume stationarity over long periods. Vol regimes shift.

---

## Ch.4 — The Variance Premium

### The Core Edge in Options

**Implied vol is systematically higher than realized vol.** This is the variance premium.

### S&P 500 Numbers

- Average gap: ~4 percentage points (e.g., IV=20%, RV=16%).
- Positive ~85% of the time (implied > realized).
- The premium exists in both high and low vol regimes.
- Mid-VIX environments (15–25) offer the best risk-adjusted premium.

### The Premium Exists Everywhere

Not just S&P 500. Found in:
- Individual equities (cross-section)
- Commodities (oil, gold, grains)
- Bonds / interest rates
- Currencies (FX options)
- VIX options (vol-of-vol premium)
- International indices

### Why It Persists

Multiple reinforcing reasons:
1. **Insurance demand**: portfolio managers must buy puts. Structural demand inflates IV.
2. **Leverage constraints**: investors who can't lever up use options as synthetic leverage, paying a premium.
3. **Behavioral**: crash fears (availability heuristic) → overpriced tails.
4. **Jump risk**: BSM assumes continuous paths. Real markets jump. Sellers demand compensation for jump risk.
5. **Agency problems**: fund managers can't survive -40% even if EV positive over 10 years.
6. **Parameter uncertainty**: even if you forecast vol correctly on average, the uncertainty around your forecast makes selling cheaper than the risk warrants.

### Selling Vol ≠ Free Money

- The 15% of the time implied < realized includes the worst months (crashes, crises).
- Selling vol has *negative skewness* — you collect small premiums consistently, then occasionally suffer large losses.
- This is exactly why the premium exists. If it felt safe, everyone would do it and the premium would vanish.

### VIX Term Structure

- VIX futures in contango (front month < back months) 81% of the time.
- Selling front-month VIX futures is profitable when in contango. The steeper the contango, the better the edge.
- Backwardation signals fear/crisis. Don't sell vol into backwardation.

---

## Ch.5 — Finding Trades: 11 Exploitable Edges

Sinclair rates each edge 1–3 stars for strength and practical usability.

### 1. Term Structure (★★)
- Sell short-dated, buy long-dated when term structure is steep (contango).
- Calendar spreads capture the differential decay rate.
- Edge: front-month IV decays faster than back-month.

### 2. Smart Beta Factors (★★★)
- **Value stocks** (low P/E, low P/CF, high cap, high RoE, high RoA, high D/E) → long vol. Their options are underpriced.
- **Growth stocks** → short vol. Their options are overpriced.
- Combined factor-sorted portfolio: **Sharpe ratio 1.44**.
- This works because analysts herd more on glamour stocks; value stocks are neglected.

### 3. PEAD — Post-Earnings Announcement Drift (★★★)
- Stocks continue drifting in the direction of the earnings surprise for weeks/months after the announcement.
- Fama called it the only anomaly "above suspicion."
- Usable with options: buy calls after positive surprise, buy puts after negative.
- Strongest for small-cap, less-covered stocks.

### 4. Earnings Volatility Premium (★★)
- IV spikes before earnings announcements (predictable event risk).
- The spike is typically excessive: realized earnings-day moves are smaller than IV implies.
- Sell straddles/strangles before earnings, buy back after.
- Caveat: occasional blow-ups when earnings surprise hugely.

### 5. Overnight Effect (★★)
- For indices: the entire variance premium is realized overnight.
- Overnight returns: -1% annualized. Intraday returns: +0.3%.
- Options decay more overnight than during the day.
- Practical: sell vol at close, buy back at open (difficult to execute cleanly).

### 6. FOMC Effect (★★)
- VIX drops ~3% after FOMC announcements.
- Stocks rally 30x more on announcement days than non-announcement days.
- Rally happens mostly in the 2 hours *before* the release.
- Sell VIX futures or buy SPX calls before FOMC.

### 7. Weekend Effect (★)
- Options should decay more over weekends (2 non-trading days).
- But market-makers don't fully adjust Friday IVs downward.
- Result: selling options Friday and buying Monday captures excess decay.
- Edge is small but consistent.

### 8. VVIX (Vol of Vol) (★★)
- Extreme high VVIX predicts VIX decline.
- Vol-of-vol risk premium exists cross-sectionally: stocks with high vol-of-vol have more expensive options.
- Use VVIX as a timing signal for vol-selling strategies.

### 9. Earnings Reversals (★)
- Extreme earnings-day moves partially reverse in subsequent days.
- Fade the move with options after big earnings surprises.
- Small edge, works better for overreactions than underreactions.

### 10. Pre-Earnings Drift (★)
- Stocks tend to drift upward in the days before earnings announcements.
- Buy calls 1–2 weeks before earnings.
- Edge partially explained by risk premium for holding through uncertainty.

### 11. Skewness Premium (★★)
- OTM puts are persistently overpriced relative to OTM calls (implied skew > realized skew).
- Selling put spreads captures the skewness premium.
- Risk reversals (sell put, buy call) exploit this on both sides.

---

## Key Takeaways — Part 1

1. **BSM is a language, not a law.** Use it to standardize, not to predict.
2. **The variance premium is the primary edge** in options. It exists because selling vol is genuinely risky and structurally demanded.
3. **Mid-VIX is the sweet spot** for selling premium. Don't sell into panics, don't bother in ultra-low VIX.
4. **Smart beta + options** (Sharpe 1.44) is the strongest systematic edge Sinclair identifies.
5. **PEAD is robust** — use options to express earnings-drift views.
6. **Vol forecasting is possible but modest** — simple ensemble beats complex models. Don't try to outsmart the consensus by much.
7. **Everything decays** — published edges lose ~30–60% of their power. Size conservatively.

---

## NSE / Indian Market Notes

- Variance premium exists in Nifty options (well-documented).
- PEAD works in NSE but with less research coverage → potentially stronger for mid/small caps.
- No FOMC equivalent for RBI policy, but similar IV crush around RBI announcements.
- Nifty options have steep OTM put skew → skewness premium is available.
- Weekend effect may differ due to different settlement cycles.
- Smart beta factors need Indian-specific factor definitions (different accounting standards, D/E norms).
