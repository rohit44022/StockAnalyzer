# StockAnalyzer — Full Development Chat History
**Date:** 8 April 2026  
**Project Root:** `/Users/rttripathirttripathi/Rohit/coding/StockCode/ historical_data`  
**GitHub Repo:** `rohit44022/StockAnalyzer` (branch: `main`)

---

## Table of Contents
1. [Project Overview](#1-project-overview)
2. [Technical Foundation](#2-technical-foundation)
3. [Development Sessions Summary](#3-development-sessions-summary)
4. [Codebase Structure](#4-codebase-structure)
5. [Backtest Results History](#5-backtest-results-history)
6. [Triple Engine Reliability Scorecard](#6-triple-engine-reliability-scorecard)
7. [Portfolio Tracker Enhancement](#7-portfolio-tracker-enhancement)
8. [Key Commands Reference](#8-key-commands-reference)
9. [User Decisions & Constraints](#9-user-decisions--constraints)

---

## 1. Project Overview

A full-stack Indian stock market analysis system built from scratch using Python + Flask. The system combines multiple sophisticated trading engines:

| Engine | Description | Score Range |
|--------|-------------|-------------|
| **BB Squeeze (M1–M4)** | Bollinger Band methods from John Bollinger's book | N/A (signal-based) |
| **Technical Analysis** | RSI, MACD, StochRSI, volume, divergence, patterns | -100 to +100 |
| **Hybrid (BB+TA)** | Combined Bollinger + Technical Analysis | -245 to +245 |
| **Price Action (Al Brooks)** | Bar-by-bar analysis, market structure, always-in | -100 to +100 |
| **Triple Conviction (BB+TA+PA)** | All three + cross-validation | -360 to +360 |
| **Quant Strategy** | Quantitative scoring and ranking | Custom |

---

## 2. Technical Foundation

- **Python:** 3.12 at `/usr/local/bin/python3`
- **Web Framework:** Flask on **port 5001**
- **Database:** SQLite (`portfolio.db`) in project root
- **Data Source:** 1,662 ticker CSVs in `stock_csv/` directory (1,568 analyzable)
- **Data Loading:** Must use `load_from_csv(ticker, CSV_DIR)` from `bb_squeeze.data_loader`

### Server Start/Restart Command
```bash
lsof -ti:5001 | xargs kill -9 2>/dev/null; sleep 1
cd "/Users/rttripathirttripathi/Rohit/coding/StockCode/ historical_data"
nohup python3 web/app.py > /tmp/flask_out.log 2>&1 &
```

### Verify Server
```bash
curl -s http://127.0.0.1:5001/ | head -5
```

---

## 3. Development Sessions Summary

### Session 1–5 (All Completed)
- ✅ **BB Squeeze Methods I–IV** — Implemented all 4 methods from John Bollinger's book with strict rules
- ✅ **Technical Analysis Engine** — RSI, MACD, StochRSI, Bollinger, volume analysis, divergences, chart patterns
- ✅ **Hybrid Engine** (`hybrid_engine.py`) — BB(100pts) + TA(100pts) + Cross-Validation = 245 max
- ✅ **Quant Strategy** (`bb_squeeze/quant_strategy.py`) — Quantitative scoring
- ✅ **Price Action Engine** (`price_action/`) — Full Al Brooks methodology implementation
- ✅ **Top 5 Picks System** (`top_picks/`) — Daily ranked picks from all engines
- ✅ **Portfolio Tracker** — Position tracking with BB Methods I–IV analysis
- ✅ **Trade P&L Calculator** — `bb_squeeze/trade_calculator.py`
- ✅ **Flask Web Dashboard** (`web/app.py`) — Full UI on port 5001
- ✅ **macOS Desktop App** — 366MB app built with PyInstaller (`build_macos.sh`)
- ✅ **GitHub Push** — `rohit44022/StockAnalyzer` on branch `main`
- ✅ **EOD Data Indicator** — End-of-day data freshness detection

### Session 6 — Triple Conviction Engine
- ✅ Built `hybrid_pa_engine.py` combining:
  - BB Score: up to 100 pts
  - TA Score: up to 100 pts
  - PA Score: up to 100 pts
  - Cross-Validation bonus/penalty: ±60 pts
  - **Total: 360 max**

### Session 7 — Truthfulness Audit
- Tested 1,568 stocks, 0 crashes, 0 violations
- Fixed 4 issues found during audit

### Session 8 — Backtest v1-v2
```
v1 ALL:  64,501 trades | WR 27.6% | PF 1.05 | Reliability 28/100
v1 BUY:  33,724 trades | WR 30.7% | PF 1.28 | Reliability 53/100
v2 ALL:  45,908 trades | WR 44.0% | PF 1.19 | Reliability 49/100
v2 BUY:  34,082 trades | WR 44.5% | PF 1.31 | Reliability 58/100
```

### Session 9 — Backtest v3 (Reliability Improvements)
Added to `backtest_triple.py`:
1. Trailing breakeven stop
2. Score ≥ 80 quality filter
3. 2+ system agreement filter
4. Rolling drawdown calculation
5. R-normalized drawdown (DD_raw / avg_loss)
6. 3-component Agreement Quality metric

**Result:** `v3 BUY-only = 19,220 trades | WR 49.9% | PF 1.37 | Reliability 68.0/100`

### Session 10 — Portfolio Tracker Enhancement
- ✅ Integrated all 4 engines into the portfolio position analysis
- ✅ Added plain-language "What This Means For You" section
- ✅ Built multi-system verdict panel with score bars
- ✅ Added Price Action (Al Brooks) detail section
- ✅ Added Triple Engine score breakdown

---

## 4. Codebase Structure

```
StockCode/historical_data/
├── main.py                          # CLI entry point
├── desktop_app.py                   # macOS desktop app
├── hybrid_engine.py                 # Hybrid BB+TA engine
├── hybrid_pa_engine.py              # Triple BB+TA+PA engine
├── historical_data.py               # Data download utilities
├── simulation_runner.py             # Monte Carlo simulation
├── backtest_triple.py               # Triple engine backtest (v3)
├── backtest_full.py                 # Full system backtest
├── backtest_pa.py                   # Price Action backtest
├── backtest_deep.py                 # Deep analysis backtest
│
├── bb_squeeze/
│   ├── config.py                    # CSV_DIR and global config
│   ├── data_loader.py               # load_stock_data(), normalise_ticker()
│   ├── indicators.py                # compute_all_indicators()
│   ├── signals.py                   # analyze_signals() — Method I
│   ├── strategies.py                # run_all_strategies() — M1–M4
│   ├── strategy_config.py           # Thresholds for each method
│   ├── fundamentals.py              # Fundamental data fetching
│   ├── scanner.py                   # Full market scanner
│   ├── display.py                   # Terminal display formatting
│   ├── exporter.py                  # CSV/Excel export
│   ├── quant_strategy.py            # Quant scoring engine
│   ├── portfolio_analyzer.py        # Position analysis (ENHANCED)
│   ├── portfolio_db.py              # SQLite portfolio CRUD
│   └── trade_calculator.py          # Trade R:R and P&L
│
├── price_action/
│   ├── engine.py                    # run_price_action_analysis()
│   ├── bar_types.py                 # Bull/bear bar classification
│   ├── breakouts.py                 # Breakout detection
│   ├── channels.py                  # Channel/wedge detection
│   ├── patterns.py                  # Multi-bar pattern detection
│   ├── scanner.py                   # PA market scanner
│   ├── signals.py                   # PA signal generation
│   ├── trend_analyzer.py            # Trend and market structure
│   └── config.py                    # PA configuration
│
├── technical_analysis/
│   ├── signals.py                   # generate_signal()
│   └── ...
│
├── top_picks/
│   └── ...
│
├── web/
│   ├── app.py                       # Flask routes (port 5001)
│   └── templates/
│       ├── portfolio.html           # Portfolio tracker UI (ENHANCED)
│       └── ...
│
└── stock_csv/                       # 1,662 .NS.csv files
```

---

## 5. Backtest Results History

### Triple Engine Backtest (`backtest_triple.py`)

| Version | Filter | Trades | Win Rate | Profit Factor | Avg P&L | Reliability |
|---------|--------|--------|----------|---------------|---------|-------------|
| v1 | ALL | 64,501 | 27.6% | 1.05 | +0.09% | 28/100 |
| v1 | BUY only | 33,724 | 30.7% | 1.28 | +0.50% | 53/100 |
| v2 | ALL | 45,908 | 44.0% | 1.19 | +0.50% | 49/100 |
| v2 | BUY only | 34,082 | 44.5% | 1.31 | +0.80% | 58/100 |
| v3 | BUY (trail+filters) | 19,220 | 49.9% | 1.37 | +0.78% | 50.2/100 |
| **v3 (fixed scorecard)** | **BUY only** | **19,220** | **49.9%** | **1.37** | **+0.78%** | **68.0/100** |

### v3 BUY-Only Details
- **Total Trades:** 19,220
- **Win Rate:** 49.9%
- **Profit Factor:** 1.37
- **Average P&L per trade:** +0.78%
- **Total P&L:** +15,071%
- **Breakeven trades (trailing stop):** 1,783 (9.3%)
- **Reliability:** 68.0/100 — *"GOOD — Reliable with known edge"*

---

## 6. Triple Engine Reliability Scorecard

### Full Scorecard (68.0/100)

| Metric | Score | Max | Notes |
|--------|-------|-----|-------|
| Win Rate | 12.4 | 20 | 49.9% WR |
| Profit Factor | 12.8 | 20 | PF 1.37 |
| Avg P&L | 10.2 | 15 | +0.78% |
| Score Alignment | 11.2 | 15 | BB+TA+PA correlation |
| Agreement Quality | 12.0 | 15 | 3-component metric |
| Drawdown (R-norm) | 9.4 | 15 | 34.6R normalized |

### Scorecard Fixes Applied (measurement layer only — no core changes)

**1. Agreement Quality** (was "Agreement Ladder"):
- 3 components: Floor WR (0–5) + Profitability Consistency (0–5) + Ladder/Concentration (0–5) = 12/15

**2. R-Normalized Drawdown**:
- Was: Raw % drawdown → 161% → 1.6/15 pts (misleading)
- Fixed: DD_raw / avg_loss = 34.6R → 9.4/15 pts (accurate)

### User Decision
> *"All core functionality is exactly taken by books with all strict set of rule and regulations and code metrics i dont want to change that at all."*

User accepted 68/100 as final reliability score.

---

## 7. Portfolio Tracker Enhancement

### User Request
> *"I want to take leverage of all these system and use them in strategy Portfolio Tracker so that it will tell exact more clear price to me about stock which i purchased. analyse it thoroughly and provide me best information along with hints and descriptive text which will tell me in layman terms or in plain non complex language"*

### What Was Built

#### Backend — `bb_squeeze/portfolio_analyzer.py`

**New imports added:**
```python
from hybrid_engine import run_hybrid_analysis
from hybrid_pa_engine import run_triple_analysis
from price_action.engine import run_price_action_analysis
```

**New functions added:**
- `_run_multi_system(df_raw, ticker, buy_price)` — Runs all 3 engines, returns condensed results
- `_build_master_summary(systems, buy_price)` — Counts votes, determines consensus, generates plain-language advice
- `_score_grade(pct)` — Returns "strongly"/"moderately"/"mildly" based on score percentage

**New `multi_system` key in `analyze_position()` return:**
```json
{
  "hybrid": { "verdict", "score", "max_score", "confidence", "alignment", "bb_score", "ta_score", "ta_verdict" },
  "triple": { "verdict", "score", "max_score", "confidence", "alignment", "bb_score", "ta_score", "pa_score" },
  "price_action": { "signal", "setup", "strength", "confidence", "pa_score", "always_in", "trend",
                    "stop_loss", "target_1", "target_2", "risk_reward", "bar_type", "bar_desc",
                    "patterns", "context", "reasons" },
  "master_summary": { "consensus", "agreement", "direction", "action_word", "votes",
                      "system_opinions", "avg_confidence", "plain_text" }
}
```

#### Frontend — `web/templates/portfolio.html`

**New HTML sections added** (below existing BB analysis):

1. **"What This Means For You"** panel (blue border)
   - Consensus badge (STRONG/MODERATE/MIXED)
   - Direction + Action Word + Avg Confidence + Agreement
   - Plain-language paragraphs in simple English

2. **Multi-System Verdicts** cards
   - Hybrid (BB+TA): score bar, verdict, confidence
   - Triple (BB+TA+PA): score bar, verdict, confidence
   - Price Action: score bar, signal, confidence

3. **Price Action Levels** table
   - PA Stop Loss, Target 1, Target 2
   - Always-In direction, PA Risk:Reward

4. **Price Action Analysis** (Al Brooks Method)
   - Signal/setup/strength/bar/trend badges
   - Al Brooks context text
   - Last bar description
   - Active patterns
   - Reasons list

5. **Triple Conviction Score Breakdown**
   - BB component bar
   - TA component bar
   - PA component bar
   - Total score + verdict + alignment + confidence

**New JS function:** `renderMultiSystem(ms)` at bottom of `renderAnalysis()`

### Test Result for KRISHANA Position (Apr 2026)
```
HYBRID:         SUPER STRONG BUY  +123.7/245   Conf: 50.5%
TRIPLE:         SUPER STRONG BUY  +184.7/360   Conf: 51.3%
PRICE ACTION:   BUY (BREAKOUT)    +51.0/100    Conf: 71.0%

CONSENSUS: STRONG — ALL AGREE → BULLISH
Action: HOLD / ADD

Plain language:
→ All 3 analysis systems are saying this stock looks good right now.
→ The Bollinger Band indicators, Technical Analysis, and Price Action patterns all point upward.
→ This is a strong position — you can hold with confidence or consider adding more if you want.
→ Price Action shows the 'Always-In' direction is LONG — the trend favors buyers.
→ Active price patterns: MICRO_DB, L4, DB_BULL_FLAG.
→ The combined conviction score is +184.7/360 — this is strongly bullish.

PA Stop: ₹562.41 | PA Target 1: ₹605.89 | PA Target 2: ₹623.28
```

---

## 8. Key Commands Reference

### Start Flask Server
```bash
lsof -ti:5001 | xargs kill -9 2>/dev/null; sleep 1
cd "/Users/rttripathirttripathi/Rohit/coding/StockCode/ historical_data"
nohup python3 web/app.py > /tmp/flask_out.log 2>&1 &
```

### Run Triple Backtest (BUY only, all stocks)
```bash
cd "/Users/rttripathirttripathi/Rohit/coding/StockCode/ historical_data"
python3 backtest_triple.py --max 0 --workers 8 --direction BUY 2>&1
```

### Run Full System Backtest
```bash
cd "/Users/rttripathirttripathi/Rohit/coding/StockCode/ historical_data"
python3 backtest_full.py --max 0 --workers 8 2>&1
```

### Test Multi-System Portfolio Analysis
```bash
cd "/Users/rttripathirttripathi/Rohit/coding/StockCode/ historical_data"
python3 _test_multisys.py
```

### Test Specific Position via API
```bash
curl http://127.0.0.1:5001/api/portfolio/6/analyze
```

### View Flask Logs
```bash
tail -f /tmp/flask_out.log
```

### Git Push
```bash
cd "/Users/rttripathirttripathi/Rohit/coding/StockCode/ historical_data"
git add -A && git commit -m "feat: enhance portfolio tracker with multi-system analysis" && git push origin main
```

---

## 9. User Decisions & Constraints

1. **Core trading rules are NOT to be modified** — All BB Methods I–IV logic is directly from John Bollinger's book. Same for PA (Al Brooks) and TA rules.

2. **Accepted reliability of 68/100** — User does not want to add more filters or change scoring to chase 90+. The 68/100 score is accepted.

3. **BUY-only backtests preferred** — User focuses on long trades only (NSE Indian stocks).

4. **Plain language for portfolio** — User wants guidance in simple non-technical language for portfolio decisions.

5. **All engines must be leveraged** — Portfolio tracker should show analysis from ALL systems (BB, TA, Hybrid, PA, Triple).

---

## 10. Files Modified in Final Session

| File | Change |
|------|--------|
| `bb_squeeze/portfolio_analyzer.py` | Added multi-system engine calls + plain-language summary generator |
| `web/templates/portfolio.html` | Added 5 new analysis sections + `renderMultiSystem()` JS function |
| `_test_multisys.py` | New test script for verifying multi-system API output |

---

*End of chat history — Last updated: 8 April 2026*

---

## 11. Senior Frontend Interview Bank (Angular, Node, TypeScript, UI Architecture)

### A. 40 Tricky Conceptual Questions With Answers

1. **Why can an Angular OnPush component still re-render even if input references do not change?**  
   **Answer:** OnPush also re-checks on template events, async pipe emissions, manual `markForCheck`, and ancestor change detection runs.

2. **When should you prefer Signals vs RxJS in Angular?**  
   **Answer:** Signals for local synchronous UI state and fine-grained updates; RxJS for async streams, cancellation, multicasting, and orchestration.

3. **What is a common production issue with `shareReplay(1)`?**  
   **Answer:** Stale cache and retained subscriptions if refCount/reset strategy is wrong; can also cache errors permanently.

4. **`switchMap` vs `exhaustMap` for login submit: which is safer and why?**  
   **Answer:** Usually `exhaustMap` to ignore repeated submits during in-flight request; `switchMap` cancels previous request.

5. **Why is async pipe often better than manual subscribe/unsubscribe?**  
   **Answer:** It handles lifecycle automatically, reduces leaks, and keeps template data flow declarative.

6. **How can NgRx selectors still become slow despite memoization?**  
   **Answer:** Frequent recreation of arrays/objects breaks memoization stability and causes recomputation.

7. **Normalized vs denormalized frontend state: core tradeoff?**  
   **Answer:** Normalized improves consistency and updates; denormalized is simpler to read but harder to maintain at scale.

8. **Why is putting all state in global store an anti-pattern?**  
   **Answer:** It over-couples features and bloats reducers; transient local UI state should stay local.

9. **Smart vs dumb components: why useful, and where can it fail?**  
   **Answer:** Good for separation of concerns, but rigid use can create unnecessary indirection and boilerplate.

10. **How do zombie subscriptions happen in Angular apps?**  
   **Answer:** Subscriptions outlive components due to missing teardown; avoid with async pipe and lifecycle-aware operators.

11. **What is the hidden risk of sharing Angular as singleton in micro-frontends?**  
   **Answer:** Version mismatch/runtime coupling can break host-remote compatibility.

12. **When should micro-frontends avoid shared dependencies?**  
   **Answer:** When independent deployability and team autonomy outweigh bundle-size optimization.

13. **Iframe MFEs vs Module Federation MFEs: practical tradeoff?**  
   **Answer:** Iframes give strong isolation but weaker UX integration; federation improves UX but increases runtime coupling.

14. **How do you keep design consistency across MFEs without hard coupling?**  
   **Answer:** Use versioned design tokens and contract rules, not direct shared UI internals.

15. **Why are contract tests critical in MFE architecture?**  
   **Answer:** They validate host-remote interface compatibility before runtime integration.

16. **How does CSS bleed happen across MFEs?**  
   **Answer:** Global resets and broad selectors leak styles; enforce scoping and naming discipline.

17. **Why can SSR hydration fail silently?**  
   **Answer:** Server/client markup mismatch from non-deterministic rendering or browser-only logic.

18. **Beyond performance, what does route-level code splitting improve?**  
   **Answer:** Better bounded-context ownership and smaller cognitive surface per feature.

19. **How can preload strategies hurt performance?**  
   **Answer:** Over-preloading consumes bandwidth needed for critical path resources.

20. **What value does a facade layer provide over direct store usage?**  
   **Answer:** Decouples components from store implementation and simplifies testing/migration.

21. **Why can async/await-heavy Node code still block requests?**  
   **Answer:** CPU-bound synchronous work blocks event loop regardless of async syntax.

22. **What is backpressure and why should UI architects care?**  
   **Answer:** Producer-consumer flow control; without it, Node streams can cause memory/latency failures that impact UI.

23. **Why does idempotency matter for frontend-triggered writes?**  
   **Answer:** Retries and duplicate submits can create duplicate writes without idempotency keys.

24. **Why is `unknown` safer than `any`?**  
   **Answer:** `unknown` requires narrowing before use; `any` disables type safety.

25. **What is a discriminated union and why useful in UI state?**  
   **Answer:** Models finite states with exhaustive checks, preventing impossible transitions.

26. **Why can `Partial<T>` be dangerous for API contracts?**  
   **Answer:** It may allow invalid business combinations not meant to be optional.

27. **How does structural typing create hidden domain bugs?**  
   **Answer:** Different domain models with same shape become assignable unintentionally.

28. **Why does variance matter for callback types?**  
   **Answer:** Incorrect variance assumptions lead to unsafe function assignments and runtime failures.

29. **What does exhaustiveness checking prevent in reducers?**  
   **Answer:** Missing action handling during evolution of union types.

30. **Why is using `div` instead of `button` a serious quality issue?**  
   **Answer:** Loses built-in semantics, keyboard behavior, and accessibility defaults.

31. **ARIA: enhancement tool or markup replacement?**  
   **Answer:** Enhancement tool; semantic HTML should remain the primary structure.

32. **Why does heading hierarchy matter beyond SEO?**  
   **Answer:** It is core for screen-reader navigation and information architecture.

33. **Why is overusing `!important` a long-term defect generator?**  
   **Answer:** It breaks cascade strategy and forces escalating specificity wars.

34. **What causes stacking contexts and z-index confusion?**  
   **Answer:** Properties like transform/opacity/position create isolated contexts; z-index is local to each context.

35. **When are container queries better than media queries?**  
   **Answer:** When component behavior depends on parent container size, not viewport.

36. **Why should design systems use CSS logical properties?**  
   **Answer:** They support RTL and non-LTR writing modes cleanly.

37. **Why is Sass `@use` preferred over `@import`?**  
   **Answer:** Namespacing and module safety; avoids global namespace collisions.

38. **Design tokens vs SCSS variables: architecture difference?**  
   **Answer:** Tokens are cross-platform design contracts; SCSS variables are preprocessor implementation details.

39. **What is a major RxJS error-handling anti-pattern in production UIs?**  
   **Answer:** Swallowing errors (`EMPTY`) without user-state transition or telemetry.

40. **How do you test architecture maturity in one discussion?**  
   **Answer:** Ask for end-to-end platform design tradeoffs: MFE, SSR, state, observability, deployment governance, and failure mitigation.

### B. 25 Tricky Coding Questions With Answers

1. **TypeScript utility type for mandatory id and optional others?**

```ts
type WithRequiredId<T extends { id?: string }> = Omit<T, 'id'> & { id: string };
```

**Answer:** Uses `Omit` plus explicit override to force `id` required while preserving other fields.

2. **Type-safe reducer exhaustiveness guard?**

```ts
function assertNever(x: never): never {
  throw new Error('Unhandled case: ' + JSON.stringify(x));
}
```

**Answer:** Use in `default` branch so compiler fails when union adds a new action not handled.

3. **Fix memory leak in Angular subscription setup**

```ts
this.userService.user$
  .pipe(takeUntilDestroyed(this.destroyRef))
  .subscribe(user => this.user = user);
```

**Answer:** Lifecycle-safe teardown prevents stale listeners after component destroy.

4. **Cancelable search API calls in RxJS?**

```ts
searchTerms$.pipe(
  debounceTime(250),
  distinctUntilChanged(),
  switchMap(term => this.http.get(`/api/search?q=${term}`))
)
```

**Answer:** `switchMap` cancels prior request when new term arrives.

5. **Prevent double submit for payment endpoint**

```ts
submitClicks$.pipe(
  exhaustMap(() => this.http.post('/api/pay', payload))
)
```

**Answer:** Ignores repeated clicks while first request is in-flight.

6. **Safe runtime decode for unknown API payload (without full libs)**

```ts
function isUser(v: unknown): v is { id: string; name: string } {
  return typeof v === 'object' && v !== null
   && typeof (v as any).id === 'string'
   && typeof (v as any).name === 'string';
}
```

**Answer:** Narrow from `unknown` before use; never trust raw JSON shape.

7. **Angular trackBy for large list performance**

```ts
trackById(_: number, item: { id: string }) { return item.id; }
```

**Answer:** Stable key prevents unnecessary DOM recreation on list updates.

8. **Node event loop blocking snippet and fix**

```js
// bad: CPU loop in request handler
app.get('/hash', (req, res) => {
  const out = heavySyncHash(req.query.text);
  res.send(out);
});
```

**Answer:** Move heavy work to worker threads/background service; avoid sync CPU in request path.

9. **Express idempotency key handling (conceptual skeleton)**

```js
app.post('/orders', async (req, res) => {
  const key = req.header('Idempotency-Key');
  // 1) check key in store
  // 2) return stored response if exists
  // 3) process once, persist response against key
});
```

**Answer:** Prevents duplicate resource creation on retries.

10. **CSS stacking issue fix when modal appears below header**

```css
.app-root { position: relative; }
.modal-layer { position: fixed; inset: 0; z-index: 9999; }
```

**Answer:** Render modal in top-level layer; avoid parent transform/opacity creating lower stacking context.

11. **Sass module usage**

```scss
@use 'tokens/colors' as c;
.btn { background: c.$primary; }
```

**Answer:** `@use` avoids global symbol collisions and clarifies ownership.

12. **Type-safe API response discriminated union**

```ts
type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: string };
```

**Answer:** Consumers must branch on `ok`, reducing unchecked null/error paths.

13. **RxJS retry with exponential backoff (simplified)**

```ts
source$.pipe(
  retry({ count: 3, delay: (_, i) => timer(2 ** i * 200) })
)
```

**Answer:** Controlled retries reduce transient failures without immediate storming.

14. **Avoid stale closure in callback-heavy TS code**

```ts
let current = 0;
function next() { current += 1; return current; }
```

**Answer:** Prefer explicit state transition points over capturing outdated values across async boundaries.

15. **Angular resolver caching pitfall**

```ts
resolve() {
  return this.api.getData().pipe(shareReplay({ bufferSize: 1, refCount: true }));
}
```

**Answer:** Configure replay carefully and define invalidation policy; otherwise stale data is likely.

16. **State immutability bug spot**

```ts
// bad
state.items.push(newItem);
return state;
```

**Answer:** Mutates existing state and can break memoization; return new references.

17. **Fixed immutable update**

```ts
return { ...state, items: [...state.items, newItem] };
```

**Answer:** Creates new object/array references enabling predictable change detection.

18. **HTML accessibility code trap**

```html
<div role="button" tabindex="0" (click)="save()">Save</div>
```

**Answer:** Prefer `<button>` unless forced otherwise; native semantics are superior.

19. **Safe map over possibly undefined API array**

```ts
const rows = (resp.items ?? []).map(x => x.name);
```

**Answer:** Nullish coalescing avoids runtime crashes on missing data.

20. **Micro-frontend shared event contract pattern**

```ts
type CartEvents =
  | { type: 'cart:item-added'; sku: string }
  | { type: 'cart:cleared' };
```

**Answer:** Typed event contracts reduce host-remote integration regressions.

21. **Node stream backpressure-safe piping**

```js
readable.pipe(transform).pipe(writable);
```

**Answer:** Native stream piping handles flow control better than manual buffering loops.

22. **Debounced form validation stream**

```ts
this.form.valueChanges.pipe(
  debounceTime(200),
  distinctUntilChanged()
)
```

**Answer:** Reduces noisy validations and API chatter.

23. **Prevent duplicate HTTP calls from multiple subscribers**

```ts
const users$ = this.http.get('/api/users').pipe(
  shareReplay({ bufferSize: 1, refCount: true })
);
```

**Answer:** Shared cold observable execution avoids N duplicate requests.

24. **Typed route param parsing guard**

```ts
const id = Number(route.snapshot.paramMap.get('id'));
if (!Number.isFinite(id)) throw new Error('Invalid id');
```

**Answer:** Prevents invalid param assumptions and downstream faults.

25. **Promise.all failure trap and robust variant**

```ts
const results = await Promise.allSettled([a(), b(), c()]);
```

**Answer:** `allSettled` captures partial failures explicitly, useful for composite dashboards.

### C. Interview Usage Tip

- For 13+ years candidates, ask 8-10 conceptual and 4-5 coding questions, then do one architecture case study.
- Evaluate depth on tradeoffs, failure modes, and operational concerns, not only syntax correctness.

---

## 12. Simple but Tricky TypeScript Coding Questions With Answers

1. **What is the output?**

```ts
type User = { name: string };
const u: User = { name: 'A' } as const;
u.name = 'B';
console.log(u.name);
```

**Answer:** `B`  
`as const` applied to the literal expression, but `u` is typed as mutable `User`.

2. **What is the type of `result`?**

```ts
const arr = [1, 2, 3];
const result = arr.map(n => n.toString());
```

**Answer:** `string[]`

3. **What prints?**

```ts
let x: any = '10';
let y: number = x;
console.log(y + 1);
```

**Answer:** `101`  
`any` bypasses safety; runtime value remains string.

4. **Why does this fail?**

```ts
let v: unknown = 'hello';
console.log(v.toUpperCase());
```

**Answer:** `unknown` must be narrowed first.

```ts
if (typeof v === 'string') {
   console.log(v.toUpperCase());
}
```

5. **What is the output?**

```ts
const a = 0 || 10;
const b = 0 ?? 10;
console.log(a, b);
```

**Answer:** `10 0`  
`||` treats `0` as falsy, `??` only falls back for `null`/`undefined`.

6. **What is the type of `K`?**

```ts
const obj = { a: 1, b: 2 };
type K = keyof typeof obj;
```

**Answer:** `'a' | 'b'`

7. **What is wrong here?**

```ts
type Person = { name: string; age: number };
const p: Partial<Person> = { name: 'R' };
console.log(p.age + 1);
```

**Answer:** `p.age` can be `undefined`.

8. **What prints?**

```ts
function fn() {
   return;
   { ok: true };
}
console.log(fn());
```

**Answer:** `undefined`  
Automatic semicolon insertion ends `return` early.

9. **What happens here?**

```ts
const nums = [1, 2, 3] as const;
// nums.push(4)
```

**Answer:** `push` is not allowed; tuple is readonly.

10. **What is the type of `T`?**

```ts
const t = ['x', 1];
type T = typeof t;
```

**Answer:** `(string | number)[]`  
Without `as const`, tuple widens to union array.

11. **What prints?**

```ts
type A = 'x' | 'y';
type B = A extends 'x' ? 1 : 2;
let v: B = 2;
console.log(v);
```

**Answer:** `2`  
No distributive behavior in this form; many candidates expect `1 | 2`.

12. **What prints?**

```ts
const data = { count: 0 };
if (data.count) {
   console.log('has count');
} else {
   console.log('no count');
}
```

**Answer:** `no count`  
`0` is a valid value but falsy.

13. **Why does this fail outside the if block?**

```ts
function f(x: string | number) {
   if (typeof x === 'string') {
      x.toUpperCase();
   }
   x.toUpperCase();
}
```

**Answer:** Narrowing only applies inside the guarded block.

14. **What prints?**

```ts
enum Color { Red, Blue }
console.log(Color[0], Color.Red);
```

**Answer:** `Red 0`

15. **Find the bug.**

```ts
type State =
   | { kind: 'loading' }
   | { kind: 'success'; data: string }
   | { kind: 'error'; message: string };

function render(s: State) {
   if (s.kind === 'success') return s.data;
   if (s.kind === 'error') return s.message;
   return s.data;
}
```

**Answer:** `loading` has no `data`; exhaustive handling is missing.

16. **What prints?**

```ts
const x = NaN;
console.log(x === NaN);
```

**Answer:** `false`  
Use `Number.isNaN(x)`.

17. **Readonly trap: allowed or error?**

```ts
type Box = { user: { name: string } };
const b: Readonly<Box> = { user: { name: 'A' } };
b.user.name = 'B';
```

**Answer:** Allowed. `Readonly<T>` is shallow, not deep.

18. **What prints?**

```ts
const p1 = Promise.resolve(1);
const p2 = Promise.resolve('x');

Promise.all([p1, p2]).then(r => {
   console.log(r[0] + 1, r[1].toUpperCase());
});
```

**Answer:** `2 X`

19. **Literal widening trap:**

```ts
function id<T>(x: T) { return x; }
const v = id('hello');
```

**Answer:** `v` is usually inferred as `string` in many usage contexts, not always preserved as literal `'hello'`.

20. **What does `satisfies` do here?**

```ts
const cfg = {
   mode: 'prod',
   retries: 3
} satisfies { mode: 'prod' | 'dev'; retries: number };
```

**Answer:** Checks compatibility with the target shape while keeping useful inferred literal precision for `cfg`.
