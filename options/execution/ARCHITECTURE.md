# Live Trading Execution Architecture

> Reference document for building the order execution bridge.
> Every design decision cites the source book/chapter.
> Code lives in `options/execution/`. Tests in `options/core/tests/test_execution.py`.

---

## Hard Constraints (Dhan API)

| Constraint | Value | Impact |
|---|---|---|
| Orders/sec | 10 | 4-leg strategy = 4 calls, leaves 6/sec headroom |
| Orders/day | 7,000 | ~20 trades/day realistic, well under limit |
| Modifications/order | 25 | 3-tier pricing uses ≤2 mods per order |
| Multi-leg orders | **None** | Each leg is a separate LIMIT order |
| Static IP required | Yes (for order mutations) | Need VPS or static IP from ISP |
| Token refresh | Manual (web login) | No programmatic refresh flow |
| Kill switch | POST /v2/killswitch | Blocks ALL new orders, not selective |
| Emergency exit | DELETE /v2/positions | Exits ALL positions at market |
| P&L exit | POST /v2/pnlExit | Daily loss limit, exchange-level |
| Super Orders | POST /v2/super/orders | Bracket order: entry + target + SL |
| Order slicing | POST /v2/orders/slicing | Auto-split for freeze quantity |

## Allowed Indices (Cash-Settled Only)

NIFTY (sec_id=13, lot=75→65), BANKNIFTY (sec_id=25, lot=30)

No stock options. No FINNIFTY (delisted). Physical settlement risk = zero.

---

## Phase 1: Order Queue (`queue.py`)

### Goal
Single-threaded priority queue that serializes all order mutations to Dhan API,
enforces rate limits, and provides idempotency guarantees.

### Why single-threaded
- Prevents race conditions on position state
- Guarantees ordering (emergency exits before new entries)
- Single-writer SQLite constraint is actually a safety feature (Davey Ch.10)
- We're swing trading (7-30 DTE), not HFT — latency is irrelevant

### Design

```
OrderRequest:
    id: str              # UUID, idempotency key
    priority: int        # 0=EMERGENCY, 1=STOP_LOSS, 2=ENTRY, 3=ADJUSTMENT
    action: str          # PLACE, MODIFY, CANCEL
    dhan_params: dict    # security_id, exchange_segment, transaction_type, quantity,
                         #   order_type, product_type, price, trigger_price, validity
    parent_trade_id: int # FK to trades table
    leg_index: int       # which leg of multi-leg trade
    created_at: str      # ISO timestamp
    attempts: int        # retry count
    max_attempts: int    # default 3
    timeout_sec: float   # per-attempt timeout, default 5.0
```

```
OrderQueue:
    __init__(safety_config: dict, db_path: str)
    submit(request: OrderRequest) -> str           # returns request.id
    process_next() -> OrderResult | None           # pops + executes highest priority
    run(interval_sec=0.2)                          # main loop: process_next every 200ms
    pause() / resume()                             # freeze queue (don't drain)
    emergency_drain()                              # process all P0 immediately
    stats() -> dict                                # queue depth by priority, daily counts
```

### Rate Limiting
- Token bucket: 5 tokens/sec (50% of Dhan's 10/sec limit, leaves room for manual)
- Burst: max 5 tokens (can send 5 at once, then wait 1s)
- Per-day counter: hard stop at 200 orders/day (well under 7000 limit)

### Pre-Send Guards (checked before every Dhan call)
1. `max_lots_per_trade` — reject if quantity > config limit
2. `max_orders_per_day` — reject if daily count exceeded
3. `max_capital_at_risk` — reject if total exposure would exceed limit
4. `max_concurrent_positions` — reject if open positions at limit
5. `allowed_indices` — reject if security not NIFTY/BANKNIFTY

### Idempotency
- Each OrderRequest has a UUID
- Before sending to Dhan, check `order_events` table for this UUID
- If already sent + got response, return cached result
- Prevents double-orders on retry after timeout

### Error Handling
- Dhan 401 → token expired, pause queue, emit TOKEN_EXPIRED event
- Dhan 429 → rate limited, exponential backoff (2s, 4s, 8s)
- Dhan 5xx → retry up to max_attempts with backoff
- Dhan timeout → retry once, then mark FAILED
- Network error → retry with backoff, max 3 attempts

### DB Tables

```sql
CREATE TABLE IF NOT EXISTS order_queue (
    id TEXT PRIMARY KEY,
    priority INTEGER NOT NULL,
    action TEXT NOT NULL,
    dhan_params TEXT NOT NULL,  -- JSON
    parent_trade_id INTEGER,
    leg_index INTEGER,
    status TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING, PROCESSING, SENT, DONE, FAILED
    created_at TEXT NOT NULL,
    sent_at TEXT,
    completed_at TEXT,
    attempts INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 3,
    timeout_sec REAL DEFAULT 5.0,
    dhan_order_id TEXT,
    dhan_response TEXT,  -- JSON
    error TEXT
);

CREATE TABLE IF NOT EXISTS order_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_id TEXT NOT NULL,
    event_type TEXT NOT NULL,  -- SUBMITTED, SENT, FILLED, PARTIAL, REJECTED, CANCELLED, EXPIRED, MODIFIED, ERROR
    timestamp TEXT NOT NULL,
    dhan_order_id TEXT,
    dhan_status TEXT,
    filled_qty INTEGER,
    price REAL,
    raw_response TEXT,  -- JSON
    FOREIGN KEY (queue_id) REFERENCES order_queue(id)
);

CREATE TABLE IF NOT EXISTS daily_counters (
    date TEXT PRIMARY KEY,
    orders_sent INTEGER DEFAULT 0,
    orders_filled INTEGER DEFAULT 0,
    orders_failed INTEGER DEFAULT 0,
    capital_deployed REAL DEFAULT 0
);
```

### Self-Check
- Create in-memory DB, submit 5 orders with different priorities
- Verify drain order: P0 first, then P1, P2, P3
- Verify rate limiter blocks >5/sec
- Verify idempotency: same UUID returns cached result
- Verify pre-send guards reject oversized orders

---

## Phase 2: Execution Bridge (`bridge.py`)

### Goal
Convert a multi-leg strategy recommendation into a sequence of OrderRequests,
manage partial fills, and handle the complete entry/exit lifecycle.

### Leg Execution Order (THE CRITICAL RULE)

**BUY legs first, then SELL legs.** Always. No exceptions.

Why: If SELL fills but BUY doesn't → naked short option → unlimited risk.
If BUY fills but SELL doesn't → long option → defined risk (premium paid).
Worst case with buy-first: we own a protective leg we need to exit. Cost = premium + round-trip costs.
Worst case with sell-first: margin call, potentially catastrophic loss.

Reference: Natenberg Ch.12 (risk management), Sinclair Ch.10 (non-market risks)

### Paired Spread Execution

For a 4-leg iron condor (BUY PE, SELL PE, SELL CE, BUY CE):

```
Phase A — Put Spread:
  1. BUY lower PE (protective) → wait fill ≤30s
  2. If filled: SELL higher PE → wait fill ≤30s
  3. If BUY fails: cancel, no harm done
  4. If SELL fails after BUY fills: hold long put, schedule exit

Phase B — Call Spread:
  5. BUY higher CE (protective) → wait fill ≤30s
  6. If filled: SELL lower CE → wait fill ≤30s
  7. Same failure logic as put spread

Phase C — Confirm:
  8. Reconcile all 4 legs against Dhan positions
  9. Update trade DB with actual fill prices + costs
  10. Calculate actual vs theoretical slippage
```

If Phase A fails completely → don't attempt Phase B.
If Phase A succeeds but Phase B fails → we hold a put spread (defined risk, manageable).

### 3-Tier Pricing

For each LIMIT order:

```
Tier 1 (0-10s):   mid = (bid + ask) / 2, rounded to tick
Tier 2 (10-20s):  aggressive = mid + 1 tick toward market (buy: +tick, sell: -tick)
Tier 3 (20-30s):  best = best_ask (for buys) or best_bid (for sells)
After 30s:        CANCEL → trigger unwind logic
```

Never use MARKET order type. NSE MARKET on options has no price protection.
Tick size: ₹0.05 for options.

Reference: Sinclair Ch.10 (execution), Cohen Ch.2 (liquidity checks)

### Pre-Flight Checks (before any execution)

1. Fetch live chain via DepthFeed WS or REST fallback
2. Compute actual entry cost using bid/ask (not theoretical mid)
3. Re-run risk audit with real prices
4. Check bid-ask spread < 4% of mid (Cohen rule)
5. Check VIX < 30 for sell-vol strategies (Sinclair Ch.4)
6. Check time: no entries in last 15 min of session (3:15-3:30 PM)
7. Check DTE: min_dte_entry ≤ DTE ≤ max_dte_entry
8. Reject if slippage > 2% of max_loss

### Write-Ahead Intent

Before placing any order:
```sql
INSERT INTO trade_intents (trade_id, strategy, legs_json, status, created_at)
VALUES (?, ?, ?, 'PENDING', ?);
```

On completion or failure, update intent status. On crash recovery (Phase 4),
scan for PENDING intents and reconcile.

### API Contract

```
ExecutionBridge:
    __init__(queue: OrderQueue, safety: SafetyConfig, db_path: str)
    execute_entry(trade_id: int, legs: list[dict], symbol: str) -> EntryResult
    execute_exit(trade_id: int, legs: list[dict], symbol: str, reason: str) -> ExitResult
    execute_adjustment(trade_id: int, close_legs: list, open_legs: list) -> AdjustResult
    unwind_partial(trade_id: int, filled_legs: list) -> UnwindResult
    get_execution_status(trade_id: int) -> dict

EntryResult:
    success: bool
    trade_id: int
    legs_filled: list[dict]     # each: {leg_index, dhan_order_id, fill_price, fill_qty, timestamp}
    legs_failed: list[dict]     # each: {leg_index, reason}
    total_cost: float           # actual round-trip cost estimate
    slippage: float             # theoretical vs actual entry cost
    execution_time_sec: float
```

### Exit Execution

Same buy-first rule applies to exits, but inverted:
- To close a SELL leg → BUY it back (this is the protective action)
- To close a BUY leg → SELL it
- Close SELL legs first (buy them back), then close BUY legs (sell them)

### Self-Check
- Mock Dhan API, create synthetic 4-leg iron condor
- Execute entry, verify buy-first ordering
- Simulate partial fill (leg 2 timeout), verify unwind of leg 1
- Verify pre-flight rejects bad bid-ask spread
- Verify slippage calculation

---

## Phase 3: Fill Tracker (`fills.py`)

### Goal
Consume OrderFeed WebSocket events and REST position polls to track every
fill, partial fill, rejection, and cancellation. Update order_events table
in real-time.

### Design

Two input channels:
1. **OrderFeed WS** (fast, ~100ms): Real-time order status updates
2. **PositionPoller REST** (reliable, 30s): Periodic position snapshot

OrderFeed is the speed path. PositionPoller is the truth path.
If they disagree, PositionPoller wins.

### Event Processing

```
on_order_update(event):
    1. Parse event: order_id, status, filled_qty, price
    2. Map to our queue_id via dhan_order_id lookup
    3. Insert into order_events table
    4. If status == TRADED:
        - Update order_queue.status = DONE
        - Update trade DB with fill price
        - Notify bridge that leg is filled
    5. If status == REJECTED:
        - Update order_queue.status = FAILED
        - Log rejection reason
        - Notify bridge to trigger unwind
    6. If status == CANCELLED:
        - Update order_queue.status = CANCELLED
    7. If status == PENDING/TRANSIT:
        - Update order_queue.status = PROCESSING
```

### Dhan Order Statuses
TRANSIT → PENDING → TRADED (success)
TRANSIT → PENDING → REJECTED (failure)
TRANSIT → PENDING → CANCELLED (by us or exchange)
TRANSIT → PENDING → EXPIRED (validity expired)

### API Contract

```
FillTracker:
    __init__(db_path: str, on_fill: Callable, on_reject: Callable)
    process_ws_event(event: dict)     # from OrderFeed WS
    process_position_snapshot(positions: list[dict])  # from PositionPoller
    get_fills(trade_id: int) -> list[dict]
    get_pending_orders() -> list[dict]
    reconcile() -> ReconcileResult    # compare our DB vs Dhan
```

### Self-Check
- Simulate sequence: TRANSIT → PENDING → TRADED
- Verify order_events table populated
- Simulate REJECTED, verify bridge notified
- Simulate disagreement between WS and REST, verify REST wins

---

## Phase 4: Reconciler (`reconciler.py`)

### Goal
Continuously verify our position state matches Dhan's. Detect phantoms
(positions on Dhan we don't know about) and orphans (orders in our DB
that Dhan doesn't have). Recover from crashes.

### Reconciliation Loop (every 30s during market hours)

```
1. Fetch Dhan positions: GET /v2/positions
2. Fetch Dhan orders (today): GET /v2/orders
3. Load our DB state: open trades + pending orders
4. Compare:
   a. For each Dhan position:
      - Match to our trade by security_id + transaction_type + quantity
      - If matched: verify quantities agree
      - If NOT matched: PHANTOM → alert + auto-exit if config allows
   b. For each our pending order:
      - Find in Dhan orders by dhan_order_id
      - If not found: ORPHAN → update our DB to FAILED
      - If found with different status: sync our DB
5. Log reconciliation result
6. If any mismatch: emit RECONCILE_MISMATCH event → safety layer decides
```

### Crash Recovery (on startup)

```
1. Check trade_intents table for status='PENDING'
2. For each pending intent:
   a. Query Dhan positions + orders
   b. Determine what actually happened:
      - All legs filled → update trade DB, mark intent COMPLETED
      - Some legs filled → unwind orphaned legs, mark intent PARTIAL_RECOVERED
      - No legs filled → mark intent EXPIRED
      - Orders still pending → cancel them, mark intent CANCELLED
3. Log recovery actions
4. Only after recovery complete: allow new orders
```

### Phantom Detection

A phantom = position on Dhan that our system didn't create.
Causes: manual trade via Dhan web, another system, or our crash recovery missed it.

Action: Log + alert. Do NOT auto-exit phantoms by default (might be manual trade).
Config option: `auto_exit_phantoms: false` (default safe).

### API Contract

```
Reconciler:
    __init__(db_path: str, safety: SafetyConfig)
    reconcile() -> ReconcileResult
    recover_from_crash() -> RecoveryResult
    detect_phantoms(dhan_positions: list) -> list[dict]
    detect_orphans(our_orders: list, dhan_orders: list) -> list[dict]

ReconcileResult:
    matched: int
    phantoms: list[dict]
    orphans: list[dict]
    quantity_mismatches: list[dict]
    timestamp: str
    clean: bool  # True if no issues found
```

### Self-Check
- Create known DB state, mock Dhan positions with one phantom
- Verify phantom detected
- Create pending intent, mock Dhan showing fills
- Verify crash recovery updates DB correctly

---

## Phase 5: Safety Layer (`safety.py`)

### Goal
Three independent kill-switch layers. Any single layer can halt trading.
The system must be safe even if two of three layers fail simultaneously.

### Layer 1: Application-Level (our code)

```
SafetyMonitor:
    __init__(config: SafetyConfig, db_path: str)
    check_portfolio_dd() -> SafetyAction     # every 30s
    check_daily_loss() -> SafetyAction        # every tick
    check_trade_sl(trade_id) -> SafetyAction  # per-trade
    emergency_stop() -> dict                  # halt everything
    heartbeat() -> None                       # Telegram ping

SafetyAction: CONTINUE | WARN | FREEZE_ENTRIES | EXIT_ALL | KILL_SWITCH
```

**Portfolio DD Monitor** (Davey Ch.14, Ch.23):
- Fast DD: LTP-based, every tick, noisy
- Slow DD: BSM reprice with live IV, every 5 min, accurate
- Abort trigger: slow DD > abort_threshold for 3 consecutive checks
- abort_threshold = avg(1.5 × historical_max_dd, 95th_percentile_MC_dd)

**Daily Loss Limit** (Sinclair Ch.9):
- Track realized + unrealized P/L across all positions
- If daily loss > daily_loss_limit_pct of capital: FREEZE_ENTRIES
- If daily loss > 2 × daily_loss_limit_pct: EXIT_ALL

**Per-Trade Stop-Loss** (Sinclair Ch.9):
- SL = 2-3× worst-case premium paid (position-level)
- Implemented via Super Orders on SELL legs (server-side)
- Application monitors as backup

### Layer 2: Dhan Server-Side

Set up at system startup each day:

```
1. POST /v2/pnlExit:
   - loss_limit = abort_dd_pct × capital
   - This is exchange-level: survives our crash

2. Super Orders on every SELL leg:
   - SL trigger = entry_premium × 2.5 (buy-back price)
   - These survive our crash + Dhan API outage

3. Kill switch (manual or auto):
   - POST /v2/killswitch ACTIVATE
   - Blocks ALL new orders on this account
   - Does NOT close existing positions
```

### Layer 3: Exchange-Level (NSE)

We don't control this, but we design around it:
- SPAN margin call: if margin insufficient, broker squares off
- RMS square-off: 3:20 PM for intraday positions
- Our guard: exit all positions by 3:00 PM on expiry day (limits.py)

### Heartbeat & Alerts

```
Every 15 min during market hours (9:15 AM - 3:30 PM):
  - Telegram message: "♥ ALIVE | 2 positions | DD: -1.2% | Feed: LIVE"
  - If heartbeat missed for 30 min: something crashed

On events:
  - TRADE_ENTERED: "📈 Entered iron_condor NIFTY 2L @24000"
  - TRADE_EXITED: "📉 Exited iron_condor: net ₹1,018"
  - DD_WARNING: "⚠️ DD at -8.5%, threshold -15%"
  - KILL_SWITCH: "🛑 KILL SWITCH ACTIVATED: daily loss -2.1%"
  - TOKEN_EXPIRED: "🔑 Dhan token expired, no new orders"
  - PHANTOM_DETECTED: "👻 Unknown position found on Dhan"
  - RECONCILE_MISMATCH: "❌ Position mismatch: our DB vs Dhan"
```

### Safety Config

```python
DEFAULT_SAFETY = {
    'mode': 'MANUAL',                # MANUAL, SEMI, FULL
    'max_lots_per_trade': 5,
    'max_orders_per_day': 20,
    'max_capital_at_risk': 100000,    # ₹1L
    'max_concurrent_positions': 4,
    'daily_loss_limit_pct': 2.0,
    'abort_dd_pct': 15.0,
    'kelly_fraction': 0.25,          # quarter-Kelly (Sinclair Ch.9)
    'allowed_indices': ['NIFTY', 'BANKNIFTY'],
    'min_dte_entry': 7,
    'max_dte_entry': 45,
    'exit_before_expiry_days': 2,
    'slippage_reject_pct': 2.0,
    'bid_ask_max_pct': 4.0,
    'vix_halt_above': 30,
    'order_timeout_sec': 30,
    'heartbeat_interval_sec': 900,
    'auto_exit_phantoms': False,
    'telegram_enabled': False,       # off until configured
    'telegram_bot_token': '',
    'telegram_chat_id': '',
}
```

### Self-Check
- Simulate portfolio DD crossing threshold
- Verify FREEZE_ENTRIES action at 1× limit
- Verify EXIT_ALL action at 2× limit
- Verify heartbeat fires at correct interval
- Verify safety config validation rejects bad values

---

## Phase 6: Live Executor (`live.py`)

### Goal
Drop-in replacement for paper trade execution path. When autopilot calls
`paper_trade.enter()`, the live executor intercepts and routes through
the execution bridge instead of instant DB writes.

### Design

```
LiveExecutor:
    __init__(bridge: ExecutionBridge, safety: SafetyMonitor,
             reconciler: Reconciler, config: SafetyConfig)
    enter(recommendation: dict) -> dict     # replaces paper_trade.enter()
    exit(trade_id: int, reason: str) -> dict  # replaces paper_trade.exit_trade()
    check(trade_id: int, spot: float) -> dict  # replaces daily_check item
    adjust(trade_id: int, adjustments: list) -> dict
```

### Mode Behavior

| Mode | Entry | Exit | Check | Adjustment |
|---|---|---|---|---|
| MANUAL | Queue → wait for human approval via web UI | Queue → wait for approval | Auto | Queue → wait for approval |
| SEMI | Auto if risk < daily_auto_limit, else queue | Auto | Auto | Auto if urgency=1, else queue |
| FULL | Auto within all safety limits | Auto | Auto | Auto |

### Integration with Autopilot

```python
# In autopilot.py cycle:
if config['live_mode']:
    executor = LiveExecutor(bridge, safety, reconciler, config)
    result = executor.enter(recommendation)
else:
    result = paper_trade.enter(rec_id, db=db)
```

### Self-Check
- Mock all dependencies
- Verify MANUAL mode queues and waits
- Verify SEMI mode auto-enters small trades, queues large ones
- Verify exit routes through bridge
- Verify safety checks run before every action

---

## Phase 7: Shadow Mode (`shadow.py`)

### Goal
Run live executor alongside paper executor. Compare every decision.
Log discrepancies. Never place real orders.

### Design

For every autopilot cycle:
1. Run paper executor (as today)
2. Run live executor in dry-run mode (everything except Dhan API call)
3. Compare: same legs? same pricing? same risk assessment?
4. Log divergences to `shadow_log` table
5. After 30 days with 0 critical divergences → ready for MANUAL mode

### What Shadow Mode Validates
- Pre-flight checks work with real chain data
- Bid/ask spreads are within tolerance at actual execution time
- Slippage estimates match (theoretical vs what we'd actually pay)
- Order sequencing logic is correct
- Rate limiter doesn't starve legitimate orders
- Reconciliation finds no false positives

### Graduation from Shadow to MANUAL
All of these for 30 consecutive trading days:
- 0 reconciliation mismatches
- 0 phantom detections
- Slippage estimate error < 1% of trade value
- All pre-flight checks pass when paper trade enters
- Heartbeat never missed
- Token refresh handled gracefully at least once

---

## Phase 8: Integration Tests (`test_execution.py`)

### Test Categories

**Unit tests** (mock Dhan API):
- OrderQueue: priority ordering, rate limiting, idempotency, pre-send guards
- ExecutionBridge: buy-first ordering, 3-tier pricing, partial fill unwind, pre-flight rejection
- FillTracker: event processing, status transitions, WS vs REST disagreement
- Reconciler: phantom detection, orphan cleanup, crash recovery
- SafetyMonitor: DD triggers, daily loss limits, config validation

**Integration tests** (mock Dhan API, real SQLite):
- Full entry lifecycle: recommend → enter → fill → confirm
- Partial fill recovery: leg 2 timeout → unwind leg 1
- Crash recovery: create pending intent → "crash" → restart → reconcile
- Kill switch cascade: DD threshold → freeze → exit all
- Token expiry: mid-execution token death → graceful degradation

**Failure mode tests**:
- Dhan 401 (token expired) during entry → freeze, don't lose partial fills
- Dhan 429 (rate limit) → backoff, retry
- Dhan 5xx → retry with backoff, mark FAILED after max attempts
- Network timeout → retry once, then FAILED
- WebSocket disconnect → fallback to REST
- Simultaneous entry + exit on same underlying → queue serializes correctly

### Test Counts Target
- Phase 1 (queue): ~15 tests
- Phase 2 (bridge): ~20 tests
- Phase 3 (fills): ~10 tests
- Phase 4 (reconciler): ~12 tests
- Phase 5 (safety): ~15 tests
- Phase 6 (live executor): ~10 tests
- Phase 7 (shadow): ~8 tests
- Total: ~90 tests

---

## Book References

| Topic | Source | Key Rule |
|---|---|---|
| Position sizing | Sinclair Ch.9 | 0.25× Kelly, never full Kelly |
| Stop-loss | Sinclair Ch.9 | 2-3× worst-case, position-level |
| Portfolio DD | Sinclair Ch.9 | -15% hard stop, 50% capital reduction |
| Abort threshold | Davey Ch.14 | avg(1.5× hist DD, 95th MC DD) |
| Incubation | Davey Ch.14 | ≥3 months, ≥30 trades, t-test p>0.44 |
| Trade count minimum | Davey Ch.6 | ≥30 for statistical significance |
| Return/DD ratio | Davey Ch.7 | >2.0 |
| Risk of ruin | Davey Ch.14 | <10% (MC simulation) |
| WFA efficiency | Davey Ch.13 | >50% OOS windows profitable |
| Non-market risk | Davey Ch.10, Sinclair Ch.10 | VPS OK for non-HFT, 12% of risk budget |
| Bid/ask liquidity | Cohen Ch.2 | <4% of mid-price |
| Execution | Sinclair Ch.10 | LIMIT only, never MARKET on options |
| BSM accuracy | Sinclair Ch.10 | ~93%, 7% gap is where retail dies |
| Vol regime | Sinclair Ch.4 | VIX 15-25 = sell-vol sweet spot |
| Buy-first rule | Natenberg Ch.12 | Never hold naked short, even transiently |
| Greeks monitoring | Natenberg Ch.7-9 | Delta-neutral target, gamma/vega limits |
| NSE costs | Zerodha Varsity | ₹20/order + STT 0.0625% sell-side |
| SPAN margin | Zerodha Varsity | Portfolio-based, multi-leg hedge benefit |
