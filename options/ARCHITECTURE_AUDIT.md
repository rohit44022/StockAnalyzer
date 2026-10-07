# Architecture Audit — Indian Stock Options System

Audit of `options/ARCHITECTURE.md` against verified NSE/SEBI rules (Oct 2026).
Severity: CRITICAL (breaks production), IMPORTANT (missing feature), GREY (needs validation).

---

## CRITICAL — Wrong Facts (would break production)

### 1. STT Rate is WRONG — costs underestimated 2.4×

**Architecture says:** STT Sell = 0.0625% of premium
**Reality (from April 1, 2026):** STT Sell = **0.15%** of premium

Timeline:
| Period | STT on Options Sell |
|--------|-------------------|
| Before Oct 2024 | 0.0625% |
| Oct 2024 – Mar 2026 | 0.1% |
| **Apr 2026 onward (CURRENT)** | **0.15%** |

**Impact:** At 0.15%, STT alone on a ₹100 premium sell = ₹0.15/unit. For Nifty (65 lot), that's ₹9.75 per lot per side. Round-trip (buy+sell): ₹9.75 since buy-side STT is 0. But this is 2.4× what the architecture models. **Edge calculations will be dangerously over-optimistic with the wrong cost.**

**Fix:** Update `cost_model.py` spec. STT = 0.15% sell-side on premium. Futures STT = 0.05% sell-side.

### 2. Lot Sizes are WRONG

**Architecture says:** "Nifty=75→25 (revised), Bank Nifty=15→15"
**Reality (Jan 2026 onward):**

| Index | Old Lot | Current Lot (2026) |
|-------|---------|-------------------|
| Nifty 50 | 25 | **65** |
| Bank Nifty | 15 | **30** |
| FinNifty | 25 | **60** |
| Midcap Nifty | 50 | **120** |

SEBI mandated contract value ₹15–20 lakh, so lots INCREASED (not decreased as the doc implies). Nifty lot went from 25 → 75 → 65 (adjusted Jan 2026).

**Impact:** Position sizing, margin calculation, cost-per-trade all wrong with old lot sizes. A Nifty lot at ₹24,000 spot × 65 = ₹15.6 lakh notional — this is the minimum position size.

### 3. Weekly Expiry Info is WRONG (3 errors)

**Architecture says:** "Weekly (Thu) for Nifty/BankNifty/FinNifty"
**Reality:**

| What's wrong | Correct |
|-------------|---------|
| "Weekly for BankNifty" | **DISCONTINUED** since Nov 13, 2024. Monthly only. |
| "Weekly for FinNifty" | **DISCONTINUED** since Nov 2024. Monthly only. |
| "Thu" expiry day | **TUESDAY** since Sep 1, 2025 |

Only **Nifty 50** has weekly expiry on NSE, and it's on **Tuesday** (not Thursday).
BSE: Only **Sensex** has weekly, on Thursday.

**Impact:** Any strategy logic based on "weekly BankNifty expiry" will produce zero trades. Calendar spread logic assuming multiple weekly indices will fail. Expiry-day timing calculations off by 2 days.

### 4. Monthly Expiry Day is WRONG

**Architecture says:** (implicitly Thursday)
**Reality:** All NSE monthly expiries moved to **last Tuesday of the month** (from Sep 2025).

Stock F&O also expires on last Tuesday.

### 5. India Variance Premium Numbers are WRONG

**Architecture says (from Sinclair/SPX):** "~4 IV points, 85% of time"
**India reality (verified data):**

| Metric | SPX (Sinclair) | India (Nifty) |
|--------|---------------|---------------|
| Avg VP | ~4 pts | **~2.46 pts** |
| Median VP | — | **~3.25 pts** |
| % positive | ~85% | **~68–80%** |
| Worst VP | — | **-64.5 pts** (COVID Mar 2020) |

India VP is **smaller and less consistent** than US. Architecture over-estimates edge by ~40%.

IV overprices realized vol:
- Nifty: 68% of days, median gap +1.4 pts
- BankNifty: 66% of days, median gap +1.6 pts
- Single stocks (e.g. Reliance): 58% of days, +0.7 pts

**Impact:** Strategy expected returns need India-calibrated VP. VIX sweet spot is also different — India VIX long-term average is **~14** (not 15-20 as doc states).

---

## CRITICAL — Missing Modules (production will fail without these)

### 6. No Physical Settlement Module

Stock options on NSE require **physical delivery of shares** since 2019. This is not just a footnote — it's a separate system.

**What's needed:**
- **Margin escalation tracker:** Margins increase from E-4 to E-day:
  - E-4: 10% of contract value (Qty × Price)
  - E-3: 25%
  - E-2: 45%
  - E-1: 70%
  - E-day: 100%
- **Close-to-money (CTM) OTM handling:** Even OTM options near the strike get blocked with **25% delivery margin** on expiry day because they might flip ITM
- **Delivery obligation calculator:** If holding ITM call at expiry → must pay full contract value to take delivery of shares. If holding ITM put → must have shares in demat to deliver
- **Auto-exit logic:** System must square off stock option positions before expiry if user cannot meet delivery obligation
- **DP charges:** Demat charges for physical settlement

**Add module:** `risk/physical_settlement.py`

### 7. No MWPL / Ban Period Handling

When a stock's OI exceeds 95% of Market Wide Position Limit → **ban period**. No fresh positions allowed, only squaring off.

**Thresholds:**
- Alert: OI > 60% MWPL (watchlist)
- Ban entry: OI > 95% MWPL (no new positions)
- Ban exit: OI < 80% MWPL (fresh positions resume)

**New (Oct 2025):** Delta-based FutEq framework — exposure measured by delta, not contract count.

**Impact without this:** System could generate signals for banned stocks → orders rejected → stuck in unhedgeable positions.

**Add to:** `data/chain.py` (fetch MWPL data) + `risk/limits.py` (check before order)

### 8. No Expiry Day Risk Module

SEBI Nov 2024 added **2% additional ELM** (Extreme Loss Margin) on short index options on expiry day. Calendar spread margin benefit **removed** on expiry day (Feb 2025).

**What's needed:**
- Expiry day margin spike calculator
- Auto-reduce position logic if margin exceeds threshold
- Broker auto-square-off time awareness (typically 3:15-3:20 PM)
- Settlement price = **last 30-min VWAP** of underlying (not LTP)

### 9. No Upfront Premium Collection Rule

Since **Feb 1, 2025**: Option buyers must have full premium amount upfront. Cannot use unrealized P&L from existing positions to fund new option purchases.

**Impact:** Affects position sizing for multi-leg strategies. Can't bootstrap premium from intraday gains.

---

## IMPORTANT — Missing Features

### 10. No Event Calendar Module

Options pricing is event-driven. Missing:
- **RBI Monetary Policy dates** (India's equivalent of FOMC) — IV crush post-announcement
- **Quarterly earnings dates** per stock — IV spike before, crush after
- **Union Budget date** (February) — massive vol event
- **General/state election dates** — VIX can spike to 25+
- **Monthly expiry dates** — gamma exposure peaks
- **NSE holidays** — no trading, gap risk

**Add module:** `data/event_calendar.py`
Integration: `signals.py` should check for events within N days.

### 11. No Rollover Management

How to roll expiring positions to next month. Missing:
- Roll cost calculator (cost of closing near-month + opening far-month)
- Optimal roll timing (avoid last-day illiquidity)
- Auto-roll rules for defined strategies
- Rollover OI data (market's rollover percentage as sentiment)

**Add to:** `strategies/adjustments.py` (expand scope)

### 12. No Liquidity Filter

Many NSE stock options are **illiquid**. System must filter:
- Bid-ask spread > 5% of mid → skip (Cohen rule: < 4%)
- Volume < 100 contracts → skip
- OI < 1000 contracts → skip
- Only trade: Nifty, BankNifty, and top 10-15 liquid stocks

**Add to:** `strategies/builder.py` (pre-filter before leg construction)

### 13. No FII/DII Position Data

NSE publishes daily FII/DII derivative positions (long/short in futures, calls, puts). This is a **strong sentiment signal** unique to India:
- FII net long in index futures → bullish
- FII heavy put writing → support levels
- DII vs FII positioning divergence → regime signal

**Add to:** `data/` as `fii_dii.py`

### 14. No Tax Module

F&O income tax changed in India:
- F&O profits treated as **business income** (non-speculative, if regular trader)
- STCG on F&O: effectively at slab rate (not flat 15% anymore for traders)
- Tax audit required if turnover > ₹10 crore (turnover = sum of absolute P&L per trade)
- Losses can be carried forward 8 years (if return filed on time)
- Wash sale rules don't exist in India (unlike US)

Not needed in MVP but important for portfolio-level return calculations.

### 15. No Position Limits Tracking

SEBI mandates client-level position limits:
- Index: higher limits (varies by index)
- Stock: depends on MWPL — client limit is typically 1% of MWPL or ₹500 crore (whichever lower)
- Combined across all brokers

System should warn before hitting limits.

### 16. No Broker Auto-Square-Off Handling

Discount brokers (Zerodha, Angel, etc.) auto-square-off:
- Intraday positions at 3:20 PM if not squared
- Margin shortfall → RMS can square off anytime
- Expiry day: broker may exit positions as early as 3:00 PM

System needs awareness of these timelines.

### 17. No Dividend Handling for Stock Options

Even though NSE stock options are European (no early exercise), dividends still affect pricing:
- Forward price: F = S - PV(dividends) × e^(rt)
- Ex-dividend date → option price adjusts
- Extraordinary dividends → NSE adjusts strike price and lot size
- Ordinary dividends → NO adjustment (unlike some exchanges)

Need: `core/dividends.py` or add to `core/bsm.py` as dividend-adjusted pricing.

---

## GREY AREAS — Needs Validation

### 18. Binomial Model — Is It Needed?

Architecture includes `core/binomial.py` for "American options pricing." But **all NSE options are European** (both index and stock, since 2010). Binomial is dead code for production.

**Keep if:** Educational/analytical tool, or for modeling early-exercise value of dividend-paying stocks (theoretical).
**Remove if:** Strictly production-only scope. BSM handles all NSE pricing.

### 19. India VIX Long-Term Average

**Architecture says:** "15-20% normal"
**Data says:** Long-term average ≈ **14%**. Range: 9 (calm) to 90 (COVID crash). Normal band: 11-18.

Fix: Use India-specific VIX history, not SPX-derived estimates.

### 20. GARCH for Indian Markets

Standard GARCH(1,1) may not capture India's event-driven vol spikes well (RBI, elections, budget). Consider:
- Regime-switching GARCH (RS-GARCH)
- Or simpler: ensemble with higher weight on recent realized vol during event windows
- Validate GARCH fit on Nifty data before production use

### 21. Kelly Criterion with Indian Costs

With STT now at 0.15% (was 0.0625% when Sinclair wrote), Indian costs are **significantly higher** than US. Effect:
- Gross edge (2.46 VP) minus costs could net to <1 VP
- Fractional Kelly fractions should be even smaller (0.05-0.20×, not 0.05-0.48×)
- Must validate: is the net edge still positive after all costs?

### 22. Settlement Price for Index Options

Index options final settlement = **closing VWAP of underlying** (last 30 minutes weighted average). Not the last traded price, not the 3:30 PM close. This affects:
- Payoff calculation at expiry
- Backtest accuracy (must use VWAP, not close)
- Pin risk assessment

### 23. Exchange Transaction Charges

Architecture mentions "~₹50/lakh." Post Oct 2024, NSE reduced exchange charges to **0.035%** (from 0.0495%) when STT was increased. Current rate should be verified and kept updated.

---

## Summary — Fix Priority

### Must Fix Before Any Code (Critical)
1. ✗ STT: 0.0625% → **0.15%**
2. ✗ Lot sizes: Nifty **65**, BankNifty **30**
3. ✗ Weekly expiry: **Nifty only, Tuesday**
4. ✗ Monthly expiry: **Last Tuesday**
5. ✗ Variance premium: India-calibrated (**~2.5 pts, ~70%**)
6. ✗ India VIX average: **~14%** (not 15-20%)

### Must Add Modules (Production fails without)
7. ✗ Physical settlement module (margin escalation, CTM, delivery)
8. ✗ MWPL / ban period tracking
9. ✗ Expiry day risk (extra ELM, no calendar margin, VWAP settlement)
10. ✗ Upfront premium collection rule

### Should Add (Important for real trading)
11. ○ Event calendar (RBI, earnings, budget, elections)
12. ○ Rollover management
13. ○ Liquidity filter
14. ○ FII/DII positioning data
15. ○ Position limits tracking
16. ○ Broker auto-square-off awareness
17. ○ Dividend-adjusted pricing for stocks

### Validate (Grey areas)
18. ? Remove binomial.py or keep as analytical tool
19. ? GARCH validation on Nifty data
20. ? Net edge after Indian costs — is it still positive?
21. ? Settlement VWAP in backtest engine

---

## Sources

- [SEBI F&O Circular Oct 2024 — Zerodha](https://zerodha.com/z-connect/business-updates/sebis-new-rules-for-index-derivatives-heres-whats-changing)
- [STT Revision Oct 2024 — Zerodha](https://zerodha.com/z-connect/business-updates/revision-in-exchange-transaction-charges-and-securities-transaction-tax-from-october-1-2024)
- [SEBI New F&O Rules — ICICI Direct](https://www.icicidirect.com/research/equity/finace/sebi-introduces-new-rules-for-restricted-entry-in-futures-and-options-trading)
- [NSE Lot Size Revision Jan 2026](https://stocko.in/bulletins/nse-revises-market-lot-sizes-for-major-index-derivatives-effective-january-2026/)
- [Physical Settlement — Zerodha Varsity](https://zerodha.com/varsity/chapter/quick-note-on-physical-settlement-2/)
- [Physical Settlement Policy — Zerodha](https://support.zerodha.com/category/trading-and-markets/trading-faqs/f-otrading/articles/policy-on-physical-settlement)
- [MWPL Ban Period — 5paisa](https://www.5paisa.com/nse-ban-list)
- [MWPL Delta Framework — Mastertrust](https://mastertrust.co.in/blog/mwpl-open-position-limit-ban-period)
- [India Variance Risk Premium — GitHub Study](https://github.com/RajolKumar2003/volatility-risk-premium-india)
- [Nifty Weekly Expiry Moved to Tuesday — PL India](https://www.plindia.com/blogs/nifty-weekly-options-strategy-tuesday-expiry-guide/)
- [F&O Lot Sizes 2026 — Algotest](https://algotest.in/blog/nifty-lot-size/)
- [STT Rates History — Bajaj Broking](https://www.bajajbroking.in/blog/securities-transaction-tax)
