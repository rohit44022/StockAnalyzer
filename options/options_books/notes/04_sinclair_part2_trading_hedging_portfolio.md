# Sinclair — Positional Option Trading: Part 2

## Chapters 6–8: How to Trade Specific Strategies, Hedging, Portfolio Construction

---

## Ch.6 — Selling Options: The Core Strategies

### Selling Naked Puts

**Profile**: collect premium, obligated to buy stock if it drops below strike.

- **Win rate**: ~70–85% (most options expire worthless or near-worthless).
- **P/L shape**: many small wins, occasional large losses. Negative skew.
- **Key risk**: tail events. A -30% crash wipes out months of premium income.

### Short Straddles / Strangles

**Short straddle** = sell ATM call + ATM put.  
**Short strangle** = sell OTM call + OTM put.

- Straddles capture more premium but higher gamma risk.
- Strangles have wider profit range but less premium.
- Sinclair's finding: **ATM selling outperforms OTM selling on a risk-adjusted basis** because the variance premium is concentrated at ATM strikes. OTM options carry additional skewness risk that eats into the premium.

### Short-Dated vs. Long-Dated

- **Short-dated (weekly/monthly)**: higher theta decay rate, more trades per year, but more gamma risk per trade.
- **Long-dated (3–12 months)**: smoother P/L, fewer transactions, but capital is locked up longer and vega risk is larger.
- **Sinclair's preference**: 1–3 month expiry balances theta capture with manageable gamma.

### IV Levels at Entry

**When to sell vol:**
- VIX 15–25: best risk/reward zone. Premium is adequate, crashes less likely.
- VIX > 30: premium is rich but the risk of further spike is real. Size down.
- VIX < 12: premium is too thin to justify the risk.

### Skew-Adjusted Positioning

- Sell options where IV is richest relative to expected realized vol.
- **Puts carry more skew premium** than calls → selling put spreads captures skewness premium.
- **OTM put IV / ATM IV ratio**: when steep (>1.3), put-selling edge is largest.
- Risk reversal (sell OTM put, buy OTM call) captures both directional drift and skew premium.

---

## Ch.7 — Beyond BSM: Alternative Models and the GSR

### Generalized Sharpe Ratio (GSR)

Standard Sharpe Ratio (SR) assumes normal returns. Options returns are NOT normal — they're skewed and fat-tailed.

**Adjusted SR formula (Generalized Sharpe Ratio):**

GSR ≈ SR × [1 − (λ₃/6)×SR + ((λ₄−3)/24)×SR²]

Where:
- λ₃ = skewness (negative for short vol → reduces GSR)
- λ₄ = kurtosis (>3 for fat tails → also reduces GSR)

### What This Means

A strategy with SR = 1.0 but skew = -2 and kurtosis = 8 has GSR ≈ 0.6.

The raw Sharpe Ratio **overstates** the attractiveness of short-vol strategies because it ignores:
1. The negative skewness (you lose big when you lose)
2. The fat tails (big losses are more common than normal distribution predicts)

### Practical Impact

- **BXM (CBOE PutWrite Index)**: raw return 8.5% vs. S&P 7.7%, but vol 12.6% vs. 17.3%.
- Looks great on SR. But after skew/kurtosis adjustment, the advantage shrinks.
- BXM's worst drawdowns (2008, 2020) are equity-like, not bond-like.
- Still attractive, but don't expect bond-like risk with equity-like returns.

### Historical Options Strategy Returns

- Covered calls (BXM): ~85% of equity returns with ~75% of equity vol. Modest improvement.
- Cash-secured puts: similar profile to covered calls (put-call parity).
- Iron condors: attractive steady income but occasional 1.4σ+ events cause outsized losses.
- Straddle selling: highest raw premium but hardest to manage risk.

### BSM Alternatives

Sinclair reviews Boness model, generalized BSM, stochastic vol models:
- **None consistently outperform BSM** for practical trading.
- Stochastic vol models (Heston etc.) improve pricing of OTM options and skew, but add parameters that need calibrating.
- Practical verdict: use BSM + skew adjustments, not a complex model.

---

## Ch.8 — Hedging and Portfolio Construction

### Delta Hedging

**When to hedge delta:**
- If your edge is pure vol (you think IV is wrong), hedge delta to isolate the vol bet.
- If your edge is directional + vol, partial hedge or no hedge.

**How often to hedge:**
- Continuous hedging (market-maker style): expensive in transaction costs.
- Daily hedging: reasonable balance for positional traders.
- Discrete hedging: re-hedge when delta moves by threshold (e.g., ±0.10).
- **Key insight**: hedging frequency matters less than you think. Moving from daily to hourly improves P/L marginally while multiplying costs.

### Gamma Scalping

If you're long gamma (long options), you profit when the stock makes large moves by delta-hedging:
- Stock goes up → you're long delta → sell some stock.
- Stock goes down → you're short delta → buy some stock.
- Each round-trip captures a profit if the move is big enough.
- Your cost is theta (time decay).

**Break-even**: realized vol must exceed implied vol. If you bought at 20% IV and stock realizes 25% vol, gamma scalping is profitable.

### Hedging with Other Options (Spreads)

**Vertical spreads**: cap your risk on a directional bet.
- Bull put spread (sell put, buy lower put): defined risk, lower margin.
- Bear call spread (sell call, buy higher call): same idea, bearish.

**Calendar spreads**: hedge short-dated short with long-dated long.
- Profits from term structure normalization.
- Risk: parallel IV shift (all expiries move together).

**Ratio spreads**: sell 2 OTM, buy 1 ATM.
- Captures skew premium with limited risk in one direction.
- **Dangerous** if stock moves sharply through your short strikes.

### Portfolio Construction: One-by-Two (1×2) Put Spread

Sinclair's detailed example (Ch.8 simulations):

**Setup**: Buy 1 ATM put, sell 2 OTM (20-delta) puts.
- Captures skew premium (OTM puts are overpriced due to skew).
- Net credit or small debit.
- Risk: stock drops through the short strike → losses accelerate.

**Simulation results** (10,000 paths, $100 stock, 20% realized vol, 30% IV):
- **ATM straddle sell**: mean P/L = $422, win rate 78%, but $1,089 worst loss.
- **20-delta strangle sell**: mean P/L = $948, win rate 85%, but tail losses larger.
- **1×2 put spread**: mean P/L = $381, win rate 52%, but worst loss $15,230.

The 1×2 is attractive on average but has catastrophic tail risk. Must be hedged or capped with a further-OTM put.

### Skew Impact on Spreads

**Table 8.11 — Skew sensitivity of 20-delta put:**

As IV of 20-delta put goes from 40.8% to 37.8%:
- Delta drops from 0.43 to -0.09
- Skew-related P/L swings from $0 to $52 per contract.

Key lesson: changes in skew steepness directly affect your P/L even if spot and ATM vol don't move. Track skew, not just ATM IV.

### Catastrophe Scenarios (SPY Example)

SPY at 299, selling far OTM puts (241 strike, 0.04 delta):

| Scenario | SPY move | IV jump | Put P/L |
|----------|----------|---------|---------|
| -10% | 269 | 30% | -$965 |
| -20% | 239 | 80% | -$2,515 |
| -30% | 209 | 120% | -$2,120 |

Vs. 258/266 put spread:

| Scenario | SPY move | IV jump | Spread P/L |
|----------|----------|---------|------------|
| -10% | 269 | 30% | +$410 |
| -20% | 239 | 80% | -$2,556 |
| -30% | 209 | 120% | -$2,050 |

**Lesson**: naked OTM puts look like free money until a -20% crash. Spreads cap the worst case (somewhat) but the protection costs premium.

### Portfolio-Level Rules

1. **Diversify across underlyings**: don't sell all vol on one name.
2. **Diversify across expiries**: stagger maturities so not all positions expire simultaneously.
3. **Correlation kills diversification in crashes**: all stocks fall together. Your portfolio of short puts on 20 stocks acts like one giant short put on the market.
4. **Sector tilts matter**: if all your short vol is in tech, you're making a tech bet, not a vol bet.
5. **Size by worst-case, not average**: the Kelly fraction already accounts for this, but additionally apply a "what if 2008 happens tomorrow" test.

### Premium vs. Spread Strategies

Sinclair's practical hierarchy:
- **Sell ATM/near-ATM premium** for highest per-trade edge (variance premium is ATM-concentrated).
- **Use spreads** to define risk and reduce margin requirements.
- **Avoid far OTM naked** unless you fully understand and accept the tail risk.
- **Ratio spreads** (1×2, 1×3) only when skew is steep enough to justify the tail exposure.

---

## Key Takeaways — Part 2

1. **ATM options capture the most variance premium.** OTM selling looks safer (high win rate) but the risk-adjusted edge is often worse.
2. **The Generalized Sharpe Ratio is essential.** Raw SR overstates short-vol strategies by ignoring skew and kurtosis. Always adjust.
3. **Spreads are non-negotiable for positional traders.** Naked short vol has unbounded risk that wipes out years of premium in one event.
4. **Skew is a tradeable edge**, not just a pricing artifact. Track it and exploit it with risk reversals and ratio spreads.
5. **Crashes correlate everything.** Portfolio diversification across names helps in normal times but fails in crises — size to survive the correlated worst case.
6. **Delta hedging is optional** for positional traders. If your thesis is directional + vol, let it ride. Hedge only to isolate the vol component.

---

## NSE / Indian Market Notes

- Nifty options have steep put skew → 1×2 put spread and risk reversals are viable.
- Margin requirements for naked options are higher on NSE (SPAN + Exposure). Spreads help significantly with margin efficiency.
- Weekly Nifty/BankNifty options: extreme theta decay in 0-2 DTE. Selling these captures variance premium but gamma risk is enormous.
- Correlation breakdown in Indian markets: banking + IT + autos can diverge more than US sectors → diversification across Indian sectors may be more effective.
- Settlement: NSE cash-settled for index options → no assignment risk on Nifty/BankNifty.
