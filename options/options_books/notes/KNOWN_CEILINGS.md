# Known Ceilings — Options Module

Full production audit completed 2026-10-06, updated 2026-10-07 (all ceilings closed).
~38 files, ~8,500 lines, 446 tests all passing.
All C1-C11 ceilings resolved. Zero open issues.

## Status Key

- **OPEN** — known ceiling, no fix needed yet
- **CLOSED** — fixed during earlier audit passes

---

## CLOSED — Risk Module (2026-10-07)

### C1. portfolio.py — VaR with spot-IV correlation ✓

Added ρ term: `combined = √(δ²σ²_s + ν²σ²_iv + 2ρ·δ·σ_s·ν·σ_iv)`.
ρ=0.6 normal, ρ=0.9 stress. Natenberg Ch.8.
- **File:** `options/risk/portfolio.py`

### C2. margin.py — ELM hedged spread reduction ✓

Hedged lots get 50% ELM reduction per NSCCL spread rules.
- **File:** `options/risk/margin.py`

### C3. limits.py — FutEq delta-based computation ✓

Added `compute_futeq()`: Σ|delta × qty × lot_size × spot|. SEBI 2025.
- **File:** `options/risk/limits.py`

### C4. margin.py — Broker margin API with estimator fallback ✓

`broker_margin()` tries Dhan API first, falls back to SPAN estimator.
- **File:** `options/risk/margin.py`, `options/data/dhan_fetch.py`

---

## CLOSED — Core Module (2026-10-07)

### C5. vol_surface.py — 25-delta with drift term ✓

Full moneyness: `offset = 0.674·σ·√t + (r + σ²/2)·t`. Natenberg Ch.4.
- **File:** `options/core/vol_surface.py`

### C6. adjustments.py — Live IV repricing ✓

`_reprice_pnl()` accepts `live_iv` dict `{(strike, otype): iv}`.
Falls back to entry IV when not provided. Sinclair Ch.9.
- **File:** `options/strategies/adjustments.py`

---

## CLOSED — Data Module (2026-10-07)

### C7. chain_store.py — Subquery for latest timestamp ✓

`get_chain_snapshot` uses `SELECT MAX(timestamp)` subquery instead of full scan.
- **File:** `options/data/chain_store.py`

### C8. oi_analysis.py — max_pain numpy vectorized ✓

Replaced O(n²) Python loops with numpy broadcasting. 250 strikes: <0.05s.
- **File:** `options/data/oi_analysis.py`

### C9. pipeline.py — oi_sentiment_summary wired ✓

`run_eod_pipeline()` now calls `oi_sentiment_summary()` when prev_chain available.
- **File:** `options/data/pipeline.py`

### C10. chain_store.py — Spread uses actual bid/ask ✓

`estimate_spread()` uses real bid/ask when available, falls back to heuristic.
- **File:** `options/data/chain_store.py`

### C11. Multi-expiry chain loader ✓

`make_chain_loader` generates near + far expiry chains for calendar/diagonal backtests.
- **File:** `options/backtest/run_pipeline.py`

---

## CLOSED (fixed during earlier audit passes)

| # | Issue | Fix | File |
|---|-------|-----|------|
| X1 | chain_store UNIQUE constraint missing | `CREATE UNIQUE INDEX IF NOT EXISTS` in `init_db` | chain_store.py |
| X2 | No analytics persistence | Added `analytics` table + store/get functions | chain_store.py |
| X3 | PCR crowd vs contrarian ambiguity | `pcr_oi` returns both `signal` and `contrarian` | oi_analysis.py |
| X4 | vol_surface used ITM calls for skew | OTM puts (K < spot) + OTM calls (K >= spot) | vol_surface.py |
| X5 | physical_settlement used strike not spot | Changed to `spot * lot_size` for delivery margin | physical_settlement.py |
| X6 | entry_gate hardcoded 30-day theta | Added `dte` param, auto-infer from legs | scenarios.py |
| X7 | engine BSM reprice used entry IV (C6 partial) | Track last-seen ATM IV on positions, use for BSM fallback | engine.py |
| X8 | engine synthetic spread ignored volume/OI (C10 partial) | Widen spread 2× for vol < 20×lot, 1.5× for OI < 100×lot | engine.py |
| X9 | engine no expiry-week slippage | 2× slippage_mult when DTE ≤ 3 | engine.py |
| X10 | WFA windows covered ~50% of date range | OOS tiles from warmup to end; last window gets remainder | walk_forward.py |
| X11 | multi-lot exit thresholds unscaled | profit_target/stop_loss now scale by `pos['lots']` | engine.py |
| X12 | No regime detection / VP-only filtering | Added `regime.py` (Sinclair VP + Cohen outlook), `signal_mode='regime'` in engine | regime.py, engine.py |
| X13 | regime.py used int outlook (+1/-1/0) vs registry strings | Fixed to match registry's 'bullish'/'bearish'/'neutral' strings | regime.py |
| X14 | run_batch.py had wrong strategy keys | Fixed `ratio_put_spread` → `ratio_put_backspread`, `long_call_butterfly` → `long_butterfly` | run_batch.py |
| X15 | run_batch.py no key validation | Added registry.get() check before running, reports unknown keys | run_batch.py |
| X16 | regime.py had zero pytest coverage | Added 12 tests: trend detection, VP classification, edge cases, engine integration | test_phase5.py |
| X17 | chain_snapshot duplicate rows on re-run | Expression UNIQUE index on `(substr(timestamp,1,10), symbol, expiry, strike, option_type)` + `INSERT OR IGNORE`; dedup migration removed 10,456 dupes | chain_store.py |
| X18 | Kelly fraction wiring in recommend() | `edge` (loss ratio) was passed as `kelly_frac`; now computes real Kelly from WFA baseline trades if incubating, falls back to 0.10 | paper_trade.py |
| X19 | recommend() pipeline arg bugs | 4 bugs: selector.select got dict not list, builder.build wrong arg order, position_size missing max_loss_per_lot, audit_trade missing margin_available | paper_trade.py |
| X20 | JSON roundtrip breaks MC percentile keys | `abort_threshold()` used `.get(95)` but JSON turns int keys to strings; fixed: `get(95, get('95', 0.0))` | monte_carlo.py |
| X21 | equity_from_trades capital mismatch | Defaulted to 1M but DEFAULT_CAPITAL=500K, diluting DD by 2×; fixed: pass `initial=DEFAULT_CAPITAL` | paper_trade.py |

---

## Priority — ALL RESOLVED

All 11 ceilings (C1-C11) closed on 2026-10-07.
No open items remain before live capital deployment.

## Strategy Validation Status (2026-10-06)

16 strategies registered, all 15 single-expiry backtested on 6-month NIFTY data.
WFA + MC validation completed on winners.

| Strategy | Net P/L | Davey Gates | WFA+MC |
|----------|---------|-------------|--------|
| long_strangle | +₹104K | ALL PASS | PASS (R/DD 19.0 OOS) |
| long_put | +₹51K | ALL PASS | PASS (R/DD 20.6 OOS) |
| long_straddle | +₹113K | FAIL (27<30 trades) | Not run |
| ratio_put_backspread | +₹48K | FAIL (27<30 trades) | Not run |
| All 11 others | Negative | FAIL | Not run |

**Note:** Test period was 9.5% NIFTY decline — only long-vol/bearish strategies
viable. Flat-market income strategies need range-bound data to validate.
