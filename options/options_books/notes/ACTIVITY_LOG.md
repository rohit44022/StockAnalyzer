# Options Books — Reading Activity Log

## Overview

5 options trading books extracted from EPUB → clean text for systematic reading.
Notes saved per-book for use in future sessions building the options module.

| # | Book | Author | Text Size | Status |
|---|------|--------|-----------|--------|
| 1 | Option Volatility & Pricing (2nd ed) | Sheldon Natenberg | 1,124 KB / 10,756 lines | DONE |
| 2 | Option Volatility & Pricing Workbook | Natenberg | 177 KB / 9,550 lines | DONE |
| 3 | The Bible of Options Strategies (2nd ed) | Guy Cohen | 586 KB / 16,377 lines | DONE |
| 4 | Positional Option Trading | Euan Sinclair | 395 KB / 7,571 lines | DONE |
| 5 | Building Winning Algorithmic Trading Systems | Kevin Davey | 454 KB / 5,832 lines | DONE |
| 6 | Zerodha Varsity — Option Theory (Module 5) | Zerodha | ~340 KB / 8,677 lines | DONE |

## Reading Order Rationale

1. **Natenberg** first — the foundational options text. Pricing, Greeks, volatility, spreads.
2. **Workbook** — practice problems reinforcing Natenberg's theory.
3. **Cohen** — complete strategy encyclopedia mapping strategies to market conditions.
4. **Sinclair** — advanced edge calculation, portfolio management, real-world positioning.
5. **Davey** — turning strategies into algo systems, backtesting, deployment.

## Source Files

Extracted text files are in scratchpad (session-local, not persisted):
- `scratchpad/books_text/01_natenberg_volatility_pricing.txt`
- `scratchpad/books_text/02_natenberg_workbook.txt`
- `scratchpad/books_text/03_cohen_bible_strategies.txt`
- `scratchpad/books_text/04_sinclair_positional.txt`
- `scratchpad/books_text/05_davey_algo_systems.txt`

Original EPUBs: `options/options_books/*.epub`

## Session Log

### 2026-10-05 — Session 1

- Extracted all 5 EPUBs to clean text (Python zipfile + HTML stripping)
- Created notes directory structure
- Started reading Book 1: Natenberg — Option Volatility & Pricing
- Reading strategy: parallel forks reading chapter ranges, merging notes

### 2026-10-06 — Session 2

- Completed Book 3: Cohen — Bible of Options Strategies (all 16,377 lines)
- Notes: `03_cohen_bible_strategies.md` — 58 strategies across 7 chapters
- Ch 1-3: Directional (calls/puts, spreads, calendars, diagonals, ladders)
- Ch 4: Volatility (straddle, strangle, strip, strap, guts, short butterflies/condors/irons)
- Ch 5: Rangebound (short straddle/strangle/guts, long butterflies/condors/irons, modified butterflies)
- Ch 6: Leveraged (ratio backspreads good, ratio spreads bad)
- Ch 7: Synthetics (collar★, synthetic call/put, synthetic straddles, synthetic futures, combos, box)
- Key takeaway: Strategy selection matrix by outlook × volatility × income goal
- NSE adaptation notes added for Indian market differences

### 2026-10-06 — Session 2 (continued)

- Completed Book 5: Davey — Building Winning Algorithmic Trading Systems (all 5,832 lines)
- Notes: `05_davey_algo_systems.md` — 25 chapters across 7 parts
- Part I (Ch 1-4): Davey's journey — losing trader to World Cup champion
- Part II (Ch 5-8): Testing framework — BS meter, Monte Carlo, walk-forward, monkey testing
- Part III (Ch 9-16): Strategy development process — SMART goals, limited testing, WFA, incubation, diversification, position sizing
- Part IV (Ch 18-19): Worked example — Euro day/night strategies, combined return/DD ratio 6.7
- Part V (Ch 20-22): Pre-live — quitting criteria, psychology, broker/automation considerations
- Part VI (Ch 23-24): Monitoring — bird's-eye charts, ±σ tracking bands, real-time diary
- Part VII (Ch 25): Cautionary tales — 11 character archetypes of failing traders
- Key takeaways: walk-forward > backtest, Monte Carlo for realistic DD, 100-200 ideas per tradable strategy, discipline is everything
- Applicability table mapping Davey concepts to options system development

### 2026-10-06 — Session 2 (continued)

- Completed Book 4: Sinclair — Positional Option Trading (all 7,571 lines, 10 chapters + 3 appendices)
- Notes split into 3 files:
  - `04_sinclair_part1_foundations_edge.md` (Ch.1-5): BSM as language not law, EMH/behavioral edges, vol forecasting (EWMA/GARCH ensemble), variance premium (IV>RV ~85%, ~4pts on S&P), 11 exploitable edges (smart beta SR 1.44, PEAD, FOMC, VVIX, skew premium)
  - `04_sinclair_part2_trading_hedging_portfolio.md` (Ch.6-8): ATM captures most variance premium, Generalized Sharpe Ratio (adjusts for skew/kurtosis), spread construction (1×2 put spreads, risk reversals), delta hedging, catastrophe scenarios (SPY crash tables), portfolio diversification rules
  - `04_sinclair_part3_sizing_risk_execution.md` (Ch.9-10, App.1-3): Kelly criterion for non-normal distributions, over-betting destroys wealth (25% over-bet → negative growth), fractional Kelly 0.05-0.48×, stop losses as survival insurance, operational risk (Barings/LTCM/Madoff/XIV blow-ups), BSM 93% of industry, execution cost framework (commissions/spread/impact)
- Key takeaways: variance premium is THE edge, size at fractional Kelly, spreads non-negotiable, operational risk kills more than market risk
- NSE adaptation notes in each file

### 2026-10-06 — Session 2 (final)

- Completed Book 2: Natenberg Workbook (all 9,550 lines)
- Notes: `02_natenberg_workbook.md` — 942 lines, 20 chapters + appendix
- All formulas, worked solutions, Greeks tables, spread rules, binomial trees, 12 rules of thumb
- ALL 5 BOOKS COMPLETE

### 2026-10-06 — Session 3

- Completed Zerodha Varsity Module 5: Option Theory for Professional Trading (all 8,677 lines, 25 chapters)
- Source: PDF extracted to text at `scratchpad/varsity/module5_text.txt`
- Notes: `06_zerodha_varsity_option_theory.md` — 14 sections covering NSE-unique content
  - Ch 1-8: NSE contract specs, lot sizes, settlement (basics already in Natenberg notes)
  - Ch 9-11: Delta table, position delta, delta as probability proxy
  - Ch 12-13: Gamma as acceleration, gamma risk for writers, DgammaDspot
  - Ch 14: Theta decay curve, non-linear time decay, NSE examples
  - Ch 15-17: Historical vol calculation, normal distribution, SD-based range calculation for Nifty
  - Ch 18: ★★★ Option writing playbook (SD-based strike selection, author's personal rules, vol-based stoploss)
  - Ch 19: Four volatility types, India VIX explained, Vega behavior by DTE
  - Ch 20: ★★ Vol smile, vol cone (with Nifty data), gamma surface plots, delta vs IV
  - Ch 21: B&S calculator with NSE inputs (RBI 91-day T-bill rate, NSE option chain IV)
  - Ch 22: ★★★ Strike selection table by time-to-expiry (the most actionable framework)
  - Ch 23: Case studies — CEAT earnings, RBI policy straddle, Infosys results
  - Aug 24 2015 crash case study: OTM call premiums rose 50-80% on a -5.92% day (Vega > Delta)
- Module 6 (Option Strategies) still blocked — skeleton only in `07_zerodha_varsity_option_strategies.md`

## Notes Directory Map

Total: **6,027 lines / ~285 KB** of distilled notes from ~59K lines / ~3.4 MB of source text.

| File | Book | Lines | Focus |
|------|------|-------|-------|
| `01_natenberg_part1_foundations.md` | Natenberg Ch 1-5 | 538 | Contracts, forwards, pricing models |
| `01_natenberg_part2_volatility_greeks.md` | Natenberg Ch 6-9 | 370 | Volatility types, all Greeks, dynamic hedging |
| `01_natenberg_part3_spreads_arbitrage.md` | Natenberg Ch 10-16 | 879 | Every spread type, synthetics, put-call parity, arbitrage |
| `01_natenberg_part4_models_hedging.md` | Natenberg Ch 17-21 | 704 | Black-Scholes, binomial trees, portfolio hedging, position analysis |
| `01_natenberg_part5_advanced_volatility.md` | Natenberg Ch 22-25 | 640 | Vol skew, VIX, variance swaps, model limitations |
| `02_natenberg_workbook.md` | Workbook | 942 | Formulas, worked examples, rules of thumb |
| `03_cohen_bible_strategies.md` | Cohen | 235 | 58 strategies: construction, Greeks, when-to-use |
| `04_sinclair_part1_foundations_edge.md` | Sinclair Ch 1-5 | 240 | Edge identification, variance premium, vol forecasting |
| `04_sinclair_part2_trading_hedging_portfolio.md` | Sinclair Ch 6-8 | 212 | Trade selection, hedging, portfolio management |
| `04_sinclair_part3_sizing_risk_execution.md` | Sinclair Ch 9-10 | 311 | Kelly sizing, risk management, execution costs |
| `05_davey_algo_systems.md` | Davey | 475 | System dev factory, walk-forward, Monte Carlo, going live |
| `06_zerodha_varsity_option_theory.md` | Varsity Module 5 | 403 | NSE mechanics, strike selection table, vol-based SL, India VIX |
| `07_zerodha_varsity_option_strategies.md` | Varsity Module 6 | 36 | INCOMPLETE — Cloudflare blocked; skeleton only |
| `KNOWN_CEILINGS.md` | All modules | — | 11 open ceilings (C1-C11), 21 closed (X1-X21), fix priorities |

### 2026-10-06 — Session 2 (architecture)

- Read all 11 note files end-to-end to ground the design in book knowledge
- Reviewed existing codebase structure (Flask app, modular per-system)
- Wrote `options/ARCHITECTURE.md` — complete system architecture:
  - 15 modules across 6 packages: core, strategies, data, risk, backtest, web
  - Every module specified with functions, formulas, data structures
  - NSE-specific cost model, margin, settlement, lot sizes
  - 7-phase implementation plan: core → data → strategies → risk → backtest → web → live
  - Key design principles synthesized from all 5 books
  - Data flow diagram showing module dependencies
  - Key numbers table (variance premium, Kelly ranges, cost impact, etc.)
- Zerodha Varsity Module 5 (Option Theory) eventually completed — 403 lines saved
- Module 6 (Option Strategies) remains skeleton — Cloudflare blocked

### 2026-10-06 — Session 2 (architecture audit)

- **Full production audit** of ARCHITECTURE.md against verified SEBI/NSE rules
- Web-searched and verified: SEBI Nov 2024 circular, STT rates, lot sizes, expiry changes
- Wrote `options/ARCHITECTURE_AUDIT.md` — found **6 critical errors, 12 missing modules, 5 grey areas**

**Critical corrections applied to ARCHITECTURE.md:**
1. STT: 0.0625% → **0.15%** (Finance Act 2026, from Apr 1)
2. Lot sizes: Nifty=**65**, BankNifty=**30** (SEBI ₹15-20L contract value mandate)
3. Weekly expiry: **Nifty only, Tuesday** (BankNifty/FinNifty weekly DISCONTINUED Nov 2024)
4. Monthly expiry: **Last Tuesday** (changed from Thursday, Sep 2025)
5. India variance premium: **~2.5 pts, ~70%** (not SPX's 4 pts / 85%)
6. India VIX average: **~14%** (not 15-20%)

**New modules added to architecture:**
- `risk/physical_settlement.py` — margin escalation E-4→E, CTM, delivery obligation
- `risk/limits.py` expanded — MWPL/ban period, client limits, broker auto-sq-off
- `data/event_calendar.py` — RBI policy, earnings, budget, elections, holidays
- `data/fii_dii.py` — FII/DII derivative positions (NSE sentiment signal)
- `core/dividends.py` — dividend-adjusted forward pricing for stock options
- Expiry-day risk: +2% ELM, no calendar margin, VWAP settlement
- Upfront premium collection rule (Feb 2025)
- Liquidity filter in strategy builder
- Rollover management in adjustments

**Architecture now has:** 19 modules across 6 packages, 7-phase plan, India-calibrated numbers

### 2026-10-06 — Session 3 (final 6 gaps)

- Addressed 6 remaining gaps from the second-pass audit:

**4 important additions:**
1. `data/chain_store.py` expanded — 3-tier historical data strategy:
   - Tier 1: NSE bhavcopy (free, back to ~2011, no bid-ask)
   - Tier 2: Live snapshot capture via broker API (START NOW, save going forward)
   - Tier 3: Paid vendor when revenue justifies ₹8-12K/yr
   - Bid-ask spread modeling rules for bhavcopy-based backtests
2. `paper/engine.py` — Paper trading incubation mode (Davey Ch.14: 3-6 months before live)
   - Simulated fills against live data, paper vs backtest comparison within 1σ
   - Added as Phase 6.5 between web dashboard and live integration
3. `risk/audit.py` — Trade log + SEBI P&L export + post-trade analysis
   - Full trade schema with entry/exit context, costs, signals, sizing
   - SEBI turnover calculation (absolute P&L sum), loss carry-forward
4. `data/oi_analysis.py` expanded — 4 OI-price combination rules:
   - Long buildup, short buildup, short covering, long unwinding
   - oi_price_regime() and oi_sentiment_summary() functions

**2 structural clarifications:**
5. `data/pipeline.py` — EOD vs real-time pipeline explicitly separated:
   - EOD: cron-based, bhavcopy + analytics + signals (Phase 2)
   - Real-time: WebSocket/polling via broker API (Phase 7)
6. `backtest/engine.py` expanded — Mandatory bid-ask handling:
   - Fill simulation rules (actual spread or modeled from bhavcopy)
   - Volume-based liquidity check, slippage multiplier
   - VWAP settlement, BHAVCOPY WARNING flag on reports

**Architecture now has:** 24 modules across 7 packages (added paper/), 8-phase plan

### 2026-10-06 — Session 3 (Phase 1 build)

- **Built all 6 Phase 1 core modules** at `options/core/`:
  1. `bsm.py` (195 lines) — BSM pricing + 9 Greeks (delta, gamma, theta, vega, rho, charm, vanna, vomma) + put-call parity
  2. `iv.py` (133 lines) — Newton-Raphson IV solver with bisection fallback + chain-wide IV computation
  3. `volatility.py` (197 lines) — 4 historical vol estimators (close-to-close, Parkinson, Garman-Klass, Yang-Zhang) + vol cone
  4. `payoff.py` (177 lines) — N-leg strategy payoff calculator + max profit/loss/breakeven detection + unlimited risk detection
  5. `cost_model.py` (201 lines) — NSE 2026 cost model (STT 0.15%, exchange 0.035%, GST 18%, stamp duty, DP charges) + round-trip + breakdown
  6. `dividends.py` (164 lines) — Dividend-adjusted forward pricing + BSM with discrete/continuous dividends

- **Cross-checked every formula** against book notes:
  - BSM: C = S·e^(-qt)·N(d1) - K·e^(-rt)·N(d2) — verified against Natenberg Ch.15, Workbook Ch.20
  - All 9 Greeks verified by **finite-difference numerical tests** (not just formula matching)
  - Put-call parity: C - P = S·e^(-qt) - K·e^(-rt) verified across 7 parameter combos
  - Natenberg rule of thumb: ATM ≈ 0.4×S×σ×√t — confirmed within 5% for all S/σ/t combos
  - 4 vol estimators: formulas match Natenberg Ch.20 exactly
  - Cost model: STT verified against SEBI Apr 2026 circular; worked example matches architecture
  - Dividend pricing: S_adj = S - PV(dividends), past dividends correctly filtered

- **Bugs found and fixed during build:**
  1. `dividends.py`: past dividends (negative time) were not filtered → fixed `d_time < t` to `0 < d_time < t`
  2. `volatility.py`: Garman-Klass variance can go negative with noisy OHLC data → added `max(variance, 0)` clamp
  3. `payoff.py`: unused `step` variable in strategy_payoff → removed

- **Wrote 127 unit tests** at `options/core/tests/test_phase1.py`:
  - 21 BSM pricing tests (textbook values, bounds, edge cases, Nifty-realistic)
  - 10 put-call parity tests (7 parametrized configs + recovery tests)
  - 22 Greeks tests (8 finite-difference + 14 property/relationship tests)
  - 14 IV solver tests (12 round-trip configs + 6 edge case NaN tests)
  - 10 volatility estimator tests (4 estimators × GBM data + cone + annualization)
  - 16 payoff tests (8 single-leg + 8 strategies: spread, straddle, IC, butterfly, collar)
  - 14 cost model tests (STT, exchange, GST, brokerage cap, DP, futures, round-trip)
  - 15 dividend tests (forward, call/put effect, past/future filtering, parity)
  - 5 cross-module integration tests (price→IV→Greeks, payoff+costs, gamma-theta)
  - All 127 pass in 1.22 seconds

### 2026-10-06 — Session 3 (Phase 3 build: Strategy Engine)

- **Built 5 Phase 3 modules** at `options/strategies/` (1,099 lines total):
  1. `registry.py` (185 lines) — 16 NSE-practical strategies as frozen dataclasses (LegSpec + Strategy), filtered from Cohen's 58 (European, cash-settled only). Categories: income (8), directional (4), volatility (3), rangebound (1).
  2. `signals.py` (244 lines) — `scan_signals(pipeline_result)` → signal dicts. Primary: variance premium (Sinclair Ch.4-5). Secondary: VIX regime (India mean ~14%), PCR (contrarian), skew, OI regime, events, term structure.
  3. `selector.py` (193 lines) — `select(signals, risk_budget, dte)` → ranked strategies. 8-step scoring: vol-regime, direction, VP boost, ATM preference (Sinclair Ch.6), skew, event caution, risk budget, complexity.
  4. `builder.py` (263 lines) — `build(strategy_key, chain_df, spot)` → position dict. Resolves LegSpec templates to actual strikes. Liquidity: OI ≥ 500, bid-ask < 4% (Cohen). Calendar guard, wing validation, risk-ratio warning.
  5. `adjustments.py` (213 lines) — `check(position, spot, dte)` → adjustment recommendations. BSM repricing for P/L (Sinclair Ch.9). Cohen long-option exit rule. Roll suggestions.

- **5 Grey Area fixes (GA1-GA5):**
  - GA1: risk-ratio warning when `abs(max_loss)/max_profit > 10` (jade_lizard ~500:1)
  - GA2: BSM repricing replaces spot-change heuristic (Sinclair Ch.9: stops on actual P/L)
  - GA3: +0.3 score for ATM sell legs in income strategies (Sinclair Ch.6: ATM > OTM risk-adjusted)
  - GA4: `_validate_wings()` for iron_condor/iron_butterfly/long_butterfly (Cohen: equal spacing)
  - GA5: Cohen long-option exit — DTE ≤ 7 urgency 1 ("close now"), DTE ≤ 21 urgency 2

- **Critical fixes during build:**
  1. `ratio_put_backspread` legs: SELL PE -2 (both OTM, wrong) → SELL PE 0 (ATM, per Cohen Ch.6)
  2. VIX sweet spot upper bound: 18 → 22 (ARCHITECTURE.md says 11-22)
  3. Calendar spread: returns None when only 1 expiry (prevents near=far degeneration)
  4. Bid-ask/OI thresholds: 5%/1000 → 4%/500 (Cohen)
  5. `jade_lizard` registry `max_loss='limited'` → `'unlimited'` (naked short put). Was getting +1.0 crisis bonus and escaping -3.0 conservative penalty. Now correctly rejected in crisis (-5.0) and penalized for conservative (-3.0).

- **Book cross-checks:**
  - Cohen Ch.3-6: all 16 strategy leg definitions, Greeks signs, risk profiles
  - Sinclair Ch.4-5: VP as primary edge signal, India VP ~2.5pts avg
  - Sinclair Ch.6: ATM selling preference in scoring
  - Sinclair Ch.8: conservative = spreads only (unlimited risk -3.0 penalty)
  - Sinclair Ch.9: position-level stops via BSM repricing
  - Natenberg: Greeks sign conventions for all key strategies

- **50 tests** in `options/core/tests/test_phase3.py`:
  - 7 registry (count, categories, greeks, legs, filters, backspread, calendar)
  - 9 signals (VP sell/buy/no-RV, VIX sweet-spot/crisis/low, PCR, event, term)
  - 6 selector (income selection, crisis rejection, low-vol, ATM preference, DTE, jade-lizard-crisis-rejected)
  - 11 builder (all-16-buildable, calendar-reject, credit/debit, butterfly, backspread-strikes, jade-lizard, wing-symmetry×2, spread-warning, cost)
  - 10 adjustments (expiry, roll, Cohen-exit×3, spot-fallback, BSM-theta/adverse/take-profit)
  - 7 book cross-checks (Sinclair VP/ATM/spreads/stops, Cohen credit/threshold, Natenberg greeks)
  - All 50 passing. Phase 1 regression: 127 tests still passing.
  - **No remaining grey areas or critical bugs.**

### 2026-10-06 — Session 3 (Phase 4 build: Risk Management)

- **Built 8 Phase 4 modules** at `options/risk/` (1,620 lines total):
  1. `position.py` (116 lines) — Position-level Greeks aggregation (Natenberg Ch.6-7). `aggregate_greeks()` with sign convention: SELL=-1. BSM P/L repricing (Sinclair Ch.9). Dollar delta for portfolio aggregation.
  2. `sizing.py` (243 lines) — Fractional Kelly criterion (Sinclair Ch.9). Classic Kelly `f*=(pb-q)/b`, non-normal adjustment `f*×[1+(skew/6)×f+((kurt-3)/24)×f²]` (eq.9.37-9.38). Range 0.05-0.48× Kelly, default 0.25×. Hard guardrails: 5% per position, 20% correlated, 50% total deployed, -15% DD → cut 50%.
  3. `scenarios.py` (218 lines) — Catastrophe analysis (Sinclair Ch.8). 3D P/L grid: spot(±30%) × IV(±50%/+100%) × time(0-28d). Named stress presets: 2008_crash(-60%), 2020_covid(-38%), flash_crash, election, rally. Entry gate: worst-case > 2× theta → reject.
  4. `margin.py` (211 lines) — SPAN-like + ELM margin estimator. 18-scenario worst-case scan. ELM: 2% index, 3.5% stock (SEBI 2024). Expiry-day ramp E-4→E-day (SEBI 2025). Spread margin benefit calculation.
  5. `limits.py` (211 lines) — MWPL/ban (60%/95%/80%), client limits (1% MWPL or ₹500cr), ban-period actions, auto-sq-off warnings (3:20/3:00).
  6. `portfolio.py` (185 lines) — Portfolio-level Greeks aggregation, parametric VaR (delta+vega), concentration checks (Sinclair Ch.8: diversify across underlyings).
  7. `physical_settlement.py` (223 lines) — SEBI 2019+ stock option settlement. Delivery margin ramp (E-4:10%→E-day:100%). CTM auto-exercise detection. Cash-settled index exclusion. Obligation tracking (deliver/pay).
  8. `audit.py` (212 lines) — Pre-trade compliance (Davey Ch.5 + SEBI). 5-check audit: MWPL, rationale, margin, position size, exit plan. JSONL trade logging. Daily summary.

- **Book cross-checks (26 points verified):**
  - Natenberg Ch.6-7: Greeks additive, sign convention for SELL
  - Sinclair Ch.8: scenario grid dimensions, stress references (2008/2020), entry gate (2× theta rule), portfolio diversification, correlation kills diversification in crashes
  - Sinclair Ch.9: Kelly formula exact, non-normal adjustment exact (eq.9.37-9.38), fractional range 0.05-0.48×, 25% over-bet rule, position-level stops, -15% DD portfolio stop
  - Sinclair Ch.10: operational risk awareness in audit checks
  - Davey Ch.5: trade logging, entry rationale requirement, exit plan
  - NSE/SEBI: SPAN scan ranges, ELM rates (2%/3.5%), expiry ramp, MWPL thresholds, client limits, physical settlement rules, CTM auto-exercise, auto-sq-off times

- **50 tests** in `options/core/tests/test_phase4.py` (565 lines):
  - 6 position (straddle/IC/long-call greeks, theta-decay P/L, adverse P/L, dollar-delta)
  - 11 sizing (Kelly basic/edge/high-payoff, adjusted-Kelly skew/normal, fractional-clamping, size-cap, negative-edge, deployed-limit, correlated-limit, DD-stop)
  - 7 scenarios (table-shape, symmetry, stress-2020/rally/unknown, entry-gate pass/reject)
  - 4 margin (spread-benefit, ELM-index-vs-stock, expiry-surcharge, utilization)
  - 6 limits (MWPL ok/caution/ban, client-limit, ban-actions, sq-off)
  - 4 portfolio (aggregate, VaR, concentration-single/diversified)
  - 6 physical-settlement (applies-index-vs-stock, delivery-ramp, no-delivery-far, CTM, cash-settled, stock-near-expiry)
  - 5 audit (passes, ban-rejects, oversized-rejects, no-rationale-warns, daily-summary)
  - 1 integration (full risk pipeline: position→sizing→margin→scenario→limits→audit)
  - All 52 passing (50 original + 2 bug-fix tests). Phase 3: 50 passing. Phase 1: 127 passing.

- **Post-build audit — 2 bugs found and fixed:**
  1. `physical_settlement.py`: `delivery_val = strike * lot_size` → `spot * lot_size`. SEBI: delivery margin is on spot value, not strike. RELIANCE spot=₹2,600, strike=₹2,500 → margin must be on ₹6,50,000 (2600×250), not ₹6,25,000. Test: `test_delivery_uses_spot_not_strike`.
  2. `scenarios.py`: `entry_gate()` hardcoded `theta_30d = daily_theta * 30`. A 7-DTE IC got compared against 30 days of theta → 4× too lenient. Fixed: added `dte` param, auto-inferred from legs' `expiry_years`. Test: `test_entry_gate_dte_matters`.

- **3 known ceilings (ponytail-commented):**
  - `margin.py`: ELM floor of 1 lot for any short position; real NSE charges per-leg reduced ELM
  - `portfolio.py`: VaR assumes ρ=0 between spot and IV; in crashes they're highly correlated
  - `limits.py`: FutEq delta-based computation is pass-through (not computed from greeks)
  - **No remaining grey areas or critical bugs.**

### 2026-10-06 — Session 4 (Phase 7: Incubation + Daily Pipeline)

- **Built Phase 7 incubation module** (Davey Ch.14, Ch.23) — all code in existing files, no new modules:

**Phase 7a: metrics.py — 6 new functions (Davey Ch.14/23):**
  1. `t_test_oos(trades, alpha)` — one-sample t-test: H0=mean P/L≤0 (Davey Ch.14)
  2. `t_test_compare(paper, wfa, threshold=0.44)` — Welch's two-sample t-test: paper≈WFA (Davey Ch.14: "56%+ chance not different")
  3. `dd_recovery_days(equity)` — DD episode tracking with mean/std/1σ/2σ recovery
  4. `return_efficiency(actual, expected)` — actual/expected return ratio (Davey Ch.23: target 0.70-1.30)
  5. `dd_efficiency(actual_dd, expected_dd)` — 1-actual/expected DD (Davey Ch.23: want >0)
  6. `equity_bands(n, avg_pnl, std_pnl)` — expected ± 1σ/2σ tracking bands (Davey Ch.23)

**Phase 7b: monte_carlo.py — 1 new function:**
  - `abort_threshold(hist_dd, mc_result)` — Davey Ch.14 quitting point: AVERAGE of 1.5× worst historical DD and 95th percentile MC DD

**Phase 7c: paper_trade.py — lifecycle table + 3 functions + CLI:**
  - `strategy_lifecycle` table (20 columns) in `init_db()`
  - `incubate(strategy_key, wfa_report_path)` — loads WFA report, normalizes trade keys, extracts baseline, computes abort threshold, inserts lifecycle row
  - `check_lifecycle(strategy_key)` — evaluates 11 graduation criteria + 2 abort triggers:
    - **Graduation (ALL):** ≥3 months, ≥30 trades, t-test p>0.44, return efficiency 0.70-1.30, DD efficiency >0, equity above 2σ floor, return/DD >2.0, PF >1.0, DD <40%, MC ruin <10%, DD < abort threshold
    - **Abort (ANY):** DD > abort threshold, or t-test p<0.10 with n≥20
  - `lifecycle_status()` — dashboard printer
  - CLI: `incubate`, `lifecycle`, `abort` subcommands

**Phase 7d: report.py — t-test gate:**
  - `t_test_significance` added to `_davey_gates()` with trades parameter

**Phase 7e: Daily pipeline — 2 new files:**
  1. `options/data/collect_daily.py` — fetches NIFTY/BANKNIFTY chains from Dhan API, stores in chain_store SQLite
  2. `options/daily_run.py` — 5-step orchestrator: chain collect → recommend → enter → check → lifecycle

**Phase 7f: Incubation started:**
  - `long_strangle`: 31 WFA trades, avg ₹3,350, abort DD 3.42%
  - `long_put`: 35 WFA trades, avg ₹1,471, abort DD 3.26%
  - First real chain snapshot: 1,424 rows, 3 expiries, 244 strikes, avg IV 22.4%
  - Cron installed: `45 16 * * 1-5` (daily_run replacing old paper_trade entries)

- **Bugs found and fixed during build (11 total):**

  *Phase 7 audit (7 bugs):*
  1. `monte_carlo.py`: JSON roundtrip turns percentile keys to strings → `.get(95)` misses `"95"`. Fixed: `dd_pctls.get(95, dd_pctls.get('95', 0.0))`
  2. `paper_trade.py`: `equity_from_trades` default 1M vs `DEFAULT_CAPITAL=500K` → DD diluted 2×. Fixed: pass `initial=DEFAULT_CAPITAL`
  3. `paper_trade.py`: `INSERT OR REPLACE` silently resets GRADUATED/ABORTED strategies. Fixed: guard check
  4. `paper_trade.py`: CLI `abort` missing `init_db()`. Fixed.
  5. `paper_trade.py`: CLI `abort` silent on nonexistent key. Fixed: rowcount check
  6. `paper_trade.py`: trades query only fetched `net_pnl`. Fixed: fetch `gross_pnl`, `entry_cost`, `exit_cost`
  7. `paper_trade.py`: vacuously true criteria with 0 trades. Fixed: `n_paper >= 3` guards

  *Pre-existing bugs in recommend() pipeline (4 bugs, never hit before live data):*
  8. `paper_trade.py`: `selector.select(sig_map)` passed dict instead of list. Fixed: pass `sigs`
  9. `paper_trade.py`: `builder.build(key, spot, chain_df=chain_df)` wrong arg order. Fixed: `build(key, chain_df, spot)`
  10. `paper_trade.py`: `sizing.position_size(capital, edge)` missing `max_loss_per_lot`. Fixed: added third arg
  11. `paper_trade.py`: `audit_trade(trade, capital)` missing `margin_available`. Fixed: pass `capital` as margin

  *Pipeline hardening (3 more fixes):*
  12. `paper_trade.py`: `_json_default` didn't handle numpy types. Fixed: added numpy.integer/floating/bool_/ndarray
  13. `paper_trade.py`: WFA report uses `net`/`gross`/`costs` keys, not `net_pnl`/`gross_pnl`/`costs_total`. Fixed: key normalization in `incubate()`
  14. `paper_trade.py`: `edge` passed as `kelly_frac` to `position_size()` — wrong variable (loss ratio ≠ Kelly fraction). Fixed: compute Kelly from WFA baseline trades or conservative 0.10 fallback

  *Data integrity:*
  15. `chain_store.py`: no UNIQUE constraint → re-runs double data. Fixed: expression UNIQUE index on `(date, symbol, expiry, strike, option_type)` + `INSERT OR IGNORE` + dedup migration (removed 10,456 duplicates)

- **30 tests** in `options/core/tests/test_phase7.py`:
  - 4 t_test_oos (profitable/unprofitable/zero/tiny)
  - 3 t_test_compare (same/different/too_few)
  - 3 efficiency (return/DD normal, DD edge)
  - 3 equity_bands (basic/zero_std/zero_n)
  - 4 abort_threshold (both/hist/mc/fallback)
  - 1 incubate real report (long_strangle WFA)
  - 1 JSON roundtrip (string key fix)
  - 9 lifecycle (start/missing/no_trades/not_found/status_empty/status_shows/dd_breach/refuses_graduated/zero_criteria)
  - All 30 passing. Full suite: 345 tests passing.

- **Book cross-checks (Phase 7):**
  - Davey Ch.6: ≥30 trades for significance → graduation gate ✓
  - Davey Ch.7: return/DD >2.0, PF >1.0, DD <40% → graduation gates ✓
  - Davey Ch.9: Kelly 0.05-0.48× fractional → sizing.py + recommend() wiring fixed ✓
  - Davey Ch.13: WFA 70/30 IS/OOS → walk_forward.py ✓
  - Davey Ch.14: MC 10K sims → monte_carlo.py ✓
  - Davey Ch.14: 3-6 month incubation → check_lifecycle ≥3 months gate ✓
  - Davey Ch.14: Abort = avg(1.5×hist, 95th MC) → abort_threshold() ✓
  - Davey Ch.14: t-test OOS edge p<0.05 → t_test_oos + report gate ✓
  - Davey Ch.14: t-test paper≈WFA p>0.44 → t_test_compare + graduation gate ✓
  - Davey Ch.23: Return/DD efficiency → return_efficiency/dd_efficiency ✓
  - Davey Ch.23: ±σ equity bands → equity_bands + graduation gate ✓
  - Sinclair Ch.9: Kelly + fractional sizing → sizing.py (wiring now correct) ✓

- **Architecture alignment:**
  - Phase 6.5 (paper trading + incubation): COMPLETE
  - Phase 7 (live deployment): blocked on C1/C4/C6 as designed
  - Daily pipeline operational: chain collection + paper trading + lifecycle tracking
  - WFA re-validation due: 2027-01-06 (3 months of real chain data)

- **Known ceilings status after Phase 7:**
  - **11 open:** C1-C11 (C1/C4/C6 block live capital)
  - **21 closed:** X1-X21 (X17: chain_snapshot dedup, X18: Kelly wiring, X19: recommend() arg bugs, X20: MC JSON keys, X21: equity capital mismatch)
