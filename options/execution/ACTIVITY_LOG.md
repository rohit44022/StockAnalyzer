# Live Execution — Activity Log

## 2026-10-07

### Phase 0: Architecture & Planning
- Created `options/execution/` directory
- Wrote comprehensive ARCHITECTURE.md (8 phases, DB schemas, API contracts, book references)
- Research completed: all 5 book notes read, Dhan API audited, existing system audited
- Key finding: Dhan has NO multi-leg orders → buy-first paired spread execution is the design
- Published brainstorming artifact with 4 rounds + Mermaid diagrams

### Phase 1: Order Queue (queue.py)
- Priority queue (P0=EMERGENCY → P3=ADJUSTMENT), token bucket rate limiter (5/sec)
- Pre-send guards: max_lots, max_orders/day, allowed_indices
- SQLite tables: order_queue, order_events, daily_counters
- Retry logic with max_attempts, pluggable executor
- SELFCHECK: PASSED

### Phase 2: Execution Bridge (bridge.py)
- Buy-first paired spread execution for iron condors (Natenberg Ch.12)
- 3-tier LIMIT pricing: mid → aggressive → best bid/ask
- Write-ahead intent logging (trade_intents table) for crash recovery
- Unwind logic: if leg fails, inverse orders to exit filled legs
- Pre-flight checks: bid-ask spread, DTE range, market hours
- SELFCHECK: PASSED

### Phase 3: Fill Tracker (fills.py)
- Dual-path: OrderFeed WS (fast) + PositionPoller REST (truth)
- Maps dhan_order_id → queue_id, inserts events, updates status
- Callbacks: on_fill (TRADED), on_reject (REJECTED)
- SELFCHECK: PASSED

### Phase 4: Reconciler (reconciler.py)
- Phantom detection: position on Dhan not in our DB → alert
- Orphan detection: our pending order not on Dhan → mark FAILED
- Crash recovery: scans trade_intents for PENDING, matches vs Dhan positions
- Reconciliation log persisted to reconciliation_log table
- SELFCHECK: PASSED

### Phase 5: Safety Layer (safety.py)
- 3-consecutive DD breach confirmation before EXIT_ALL (Davey Ch.14)
- Daily loss: FREEZE at 1×, EXIT_ALL at 2×
- Emergency stop, heartbeat, config validation (kelly ≤ 0.5, cash-settled only)
- Safety events audit trail in safety_events table
- SELFCHECK: PASSED

### Phase 6: Live Executor (live.py)
- MANUAL/SEMI/FULL mode support (Davey Ch.14)
- Approval queue for MANUAL mode, auto-enter within limits for SEMI/FULL
- Integrates bridge + safety + reconciler
- SELFCHECK: PASSED

### Phase 7: Shadow Mode (shadow.py)
- Runs LiveExecutor alongside paper trade, compares decisions (Davey Ch.14)
- Logs all comparisons to shadow_log table
- Match rate tracking, ready_for_live gate (≥95% match + 30 days)
- SELFCHECK: PASSED

### Phase 8: Integration Tests (test_execution.py)
- 65 tests covering all 7 phases + full lifecycle scenarios
- Tests: queue ordering, guards, drain, bridge buy-first/unwind/intents
- Tests: fill WS/REST, phantom/orphan detection, crash recovery
- Tests: safety DD/daily-loss/capital/config, executor modes, shadow comparisons
- Tests: end-to-end entry→reconcile→exit, shadow→live transition, safety cascade
- ALL 65 PASSED

### Audit Pass 1: Production-Grade Review
- **FIX** queue.py: NIFTY lot size 75→65 (NSE lot size change)
- **FIX** bridge.py: Unwind changed from MARKET→aggressive LIMIT (NSE options rule: never MARKET)
- **FIX** reconciler.py: Added quantity mismatch detection (was matching security_id only, ignoring qty)
- **FIX** bridge.py: Replaced dead `get_order_by_dhan_id` fallback with direct DB query on order_queue
- All 7 selfchecks + 65 integration tests pass after fixes

### Audit Pass 2: Safety & Edge Cases
- **FIX** live.py: `approve()` now re-checks safety before executing (market may move between queue and approval)
- **FIX** live.py: `_count_open_positions` fail-closed — returns max_concurrent_positions on DB error (was fail-open: returned 0)
- **FIX** shadow.py: mode restore wrapped in try/finally (exception between set_mode calls left executor in FULL)
- **CLEAN** live.py: removed unused imports (json, Optional)
- All 7 selfchecks + 65 integration tests pass after fixes
### Audit Pass 3: Architecture Compliance (books cross-referenced)
- **FIX** queue.py: Idempotency — `submit()` catches IntegrityError on duplicate UUID instead of crashing
- **FIX** bridge.py: VIX halt — `_preflight()` now checks `vix_halt_above` via `vix_fetcher` (Sinclair Ch.4)
- **FIX** bridge.py: Slippage — `_calc_slippage()` computes actual vs theoretical cost (Sinclair Ch.10)
- **FIX** safety.py: Dhan Layer 2 — `setup_dhan_safety()` calls pnlExit on session start (Davey Ch.10)
- **FIX** queue.py: HTTP 401→pause+TOKEN_EXPIRED, 429→backoff (Dhan API contract)
- **FIX** queue.py+reconciler.py: Queue blocks during crash recovery via `_recovering` flag (Architecture spec)
- **FIX** queue.py: `max_capital_at_risk` added to `_check_guards()` pre-send validation
- All 7 selfchecks + 65 integration tests pass after fixes
- **AUDIT 3 COMPLETE**: All architecture promises verified against book references

### Audit Pass 4: Alignment Fixes (spec-vs-code gaps)
- **FIX** queue.py: `capital_deployed` column existed but was never incremented — added `_increment_daily_capital()` so the capital guard actually fires
- **FIX** queue.py: 429 backoff changed from flat 2s to exponential 2s/4s/8s (spec: "exponential backoff"), resets on success
- **FIX** reconciler.py: `recover_from_crash()` wrapped in try/finally — exception no longer leaves queue permanently locked
- **FIX** bridge.py: Slippage rejection enforced — unwinds if slippage > `slippage_reject_pct`% of max_loss (spec: "Reject if > 2% of max_loss")
- **FIX** shadow.py: `ready_for_live` expanded from 2 checks to 6: duration, match_rate≥95%, zero phantoms, zero recon mismatches, preflight pass, has_comparisons
- **FIX** shadow.py: `dry_run=True` by default — shadow mode simulates entries/exits without touching real executor. Pass `dry_run=False` only when wired to mock executor in tests
- All 7 selfchecks + 65 integration tests pass after audit 4 fixes

### Audit Pass 5: Production Safety Deep Pass
- **FIX** bridge.py: Unwind orders had `securityId: ''` — now resolves from original legs or DB (would have failed at Dhan API)
- **FIX** queue.py: TOKEN_EXPIRED event was written on unmanaged connection (never committed/closed) — event silently lost
- **FIX** reconciler.py: Crash recovery logged "cancelling stale order" but never sent cancel to Dhan — now submits EMERGENCY cancel via queue
- **FIX** bridge.py: `_complete_intent` now stores legs_filled/failed, total_cost, slippage, execution_time in result_json (was discarding all)
- **ADD** test: HTTP 401 pauses queue
- **ADD** test: HTTP 429 increments exponential backoff counter
- **ADD** test: `max_capital_at_risk` guard blocks second order over limit
- **ADD** test: VIX halt preflight blocks SELL entries when VIX > threshold
- **ADD** test: Idempotent UUID resubmit (no crash, single row)
- **ADD** test: `recover_from_crash` try/finally unlocks queue even on exception
- All 7 selfchecks + 71 integration tests pass after audit 5 fixes

### Audit Pass 6: Stuck-Order & Connection Leak Review
- **ANALYSIS** bridge.py `_wait_fill` MODIFY race: fill arriving between timeout and MODIFY is inherent to single-leg Dhan API — reconciler catches it as phantom fill, no code fix needed
- **FIX** reconciler.py: `recover_from_crash()` conn leak — if `_position_fetcher()` threw, conn opened at line 154 was never closed; wrapped in inner try/finally
- All 7 selfchecks + 74 integration tests pass after audit 6 fixes

## 2026-10-08

### V5: Autopilot ↔ Execution Bridge (Red Team → Code → Audit)

#### Red Team / Blue Team (3 rounds, 15 disaster scenarios)
- 9 hard failures, 4 partial, 2 passes
- **3 systemic patterns identified:**
  1. "Accepted ≠ Done" — order acceptance != fill confirmation
  2. "In-memory state dies on restart" — safety counters must be DB-persisted
  3. "Cross-module blindness" — modules assumed other modules tracked state they didn't

#### Red Team Patches (8 files)
- **queue.py**: WAL+busy_timeout in `_init_queue_db()`, 429 returns immediately with `backoff_sec` (no blocking sleep), `force_drain_exits()` processes EMERGENCY+STOP_LOSS even when paused
- **bridge.py**: Cancel verification (poll order_events after CANCEL), unwind fill verification (`_wait_fill()` after each unwind order), slippage unwind cost = entry_cost + unwind_cost
- **fills.py**: Direction-aware matching — BUY→positive netQty, SELL→zero/negative netQty
- **reconciler.py**: Net position tracking — BUY adds, SELL subtracts, filters zero-net positions
- **safety.py**: DD breach count restored from `safety_events` table on process restart
- **shadow.py**: `dry_run=False` blocked with ValueError — prevents accidental double execution

#### Autopilot Live Integration (autopilot.py + paper_trade.py)
- **Alert system**: `_emit_alert()`, `get_alerts()`, `ack_alert()` with `autopilot_alerts` table (INFO/WARNING/CRITICAL/EMERGENCY)
- **File lock**: `fcntl.LOCK_EX|LOCK_NB` on `.autopilot.lock` for cron anti-overlap
- **`cron_run_cycle()`**: Wraps `run_cycle()` with lock acquire/release
- **`_get_executor(cfg, db)`**: Builds OrderQueue+ExecutionBridge+SafetyMonitor from config, returns None in paper mode
- **`_live_enter()`**: Calls bridge.execute_entry(), handles FILLED/RESIDUAL/FAILED states
- **`_live_exit()`**: Calls bridge.execute_exit(), handles EXITED/EXPIRED/EXIT_FAILED states
- **live_status state machine**: NULL→PENDING→FILLED→EXITED, failure: FAILED/EXIT_FAILED/RESIDUAL/EXPIRED
- **Preflight alert**: CRITICAL with 30-min cooldown when preflight fails + open positions exist
- **Staging**: BURN_IN (₹400 cap), RAMP_UP, FULL_DEPLOY in config
- **paper_trade.py**: `live_status` column migration, `autopilot_alerts` table
- **CLI**: `alerts [-u] [N]`, `alerts ack <id>`, `run` now uses `cron_run_cycle()`

#### V5 Integration Tests (test_v5_integration.py — 24 tests)
- TestAlertSystem: emit, retrieve, ack, severity levels, context JSON
- TestFileLock: acquire/release, reacquire, cron_run_cycle skips when locked
- TestDirectionAwareFills: BUY/SELL matching against positive/negative/zero netQty
- TestNetPositionReconciler: BUY+SELL net-zero, partial sell net tracking
- TestDDBounceRestore: consecutive DD_WARNING count, reset on non-DD event
- TestShadowGuard: dry_run=False raises ValueError, dry_run=True works
- TestRateLimitBackoff: 429 returns immediately
- TestForceDrainExits: emergency orders drain while queue paused
- TestWALMode: queue DB + autopilot conn both use WAL + busy_timeout=10000
- TestLiveStatusMigration: live_status column + autopilot_alerts table exist

#### Audit Pass 7: V5 Production Safety
- **FIX** autopilot.py: `_live_exit` exception handler now updates `live_status='EXIT_FAILED'` in DB (was only logging — trade stayed 'FILLED' after crash)
- **FIX** autopilot.py: Exit path guards on `live_status` — only calls `_live_exit` when `cur_live in ('FILLED', 'EXIT_FAILED')`, skips for FAILED/None (no real position to close)
- **FIX** autopilot.py: When live entry fails, paper trade is now immediately closed via `paper_trade.exit_trade()` and counted as error, not success (was leaving orphaned paper trade that would trigger exit checks against non-existent position)
- All 8 selfchecks + 470 tests (446 existing + 24 v5) pass after audit fixes

#### V5 UI Wiring (options_routes.py + options_autopilot.html)
- **Bug fix**: `/api/options/autopilot/cycle` now calls `cron_run_cycle()` instead of `run_cycle()` (was missing file lock)
- **3 new API routes**:
  - `GET /api/options/autopilot/alerts?limit=N&unacked=1` — fetch alerts with optional unacked filter
  - `POST /api/options/autopilot/alerts/ack` — acknowledge alert by id
  - `GET /api/options/autopilot/execution` — queue stats, recent order events, safety events, reconciliation, shadow match rate
- **Alerts panel**: severity-colored badges (EMERGENCY/CRITICAL/WARNING/INFO), expandable detail, ack button, unacked count badge, auto-refresh during market hours
- **live_status column**: added to open trades table with color-coded badges (PAPER/PENDING/FILLED/EXITED/FAILED/EXIT_FAILED/RESIDUAL/EXPIRED), pulsing animation on RESIDUAL
- **Staging badge**: BURN_IN/RAMP_UP/FULL_DEPLOY shown next to ENABLED/DISABLED status pill
- **Execution Health section**: queue totals (filled/failed/pending), recon clean status, shadow match rate, collapsible recent order events table, collapsible safety events table
- **Config panel**: added Live Mode (paper/live), Staging (BURN_IN/RAMP_UP/FULL_DEPLOY), Max Loss/Trade fields
- **Polling**: alerts + execution stats refresh alongside decision log on every market-hours poll, after cycle/emergency, on tab visibility change
