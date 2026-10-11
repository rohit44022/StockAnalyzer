# Delta Architecture: Sebastian + Taleb → Autopilot Integration

## Existing System Summary

The autopilot runs as a cron-driven cycle with 4 phases:
1. Ghost/residual cleanup
2. Exit evaluation (_should_exit: 8 checks)
3. Entry evaluation (_should_enter: 10 gates → scorer → builder)
4. Post-cycle (lifecycle, MTM, reconciliation, backup)

Modules: core/ (BSM, IV, vol, payoff, cost), strategies/ (registry, signals, selector, builder, adjustments, regime), risk/ (sizing, scenarios, margin, limits, portfolio, physical_settlement, audit), data/ (chain, chain_store, pipeline, oi_analysis, event_calendar, fii_dii), backtest/, paper/, execution/.

## Gap Analysis: What's Missing

### A. Sebastian Gaps (TOMIC Framework)

| # | Concept | Where It Should Live | Current State | Priority |
|---|---------|---------------------|---------------|----------|
| S1 | 2% per-trade AUM risk cap | risk/sizing.py + autopilot._should_enter | Has Kelly fractional (0.05-0.48×) but no explicit 2% AUM ceiling | HIGH |
| S2 | 6% portfolio aggregate heat | autopilot._should_enter | max_concurrent=2 but no aggregate risk check | HIGH |
| S3 | 5 volatility skew phases | strategies/signals.py | Has VIX regimes (4 bands) but not the 5-phase ATM IV skew model | MEDIUM |
| S4 | % OTM validation (8.5-10% OTM) | strategies/builder.py | Delta-based strike selection only | MEDIUM |
| S5 | Card Game Value exit (short opt ≤ ₹2-5) | autopilot._should_exit | Missing entirely | HIGH |
| S6 | 3-day forward test before adjustments | strategies/adjustments.py | Adjusts immediately on trigger | MEDIUM |
| S7 | Wing price floor (≥ ₹5 per wing) | strategies/builder.py | Has bid-ask/OI filters, no credit floor | HIGH |
| S8 | Over-adjustment tracking | autopilot.run_cycle | No per-trade adjustment counter | LOW |
| S9 | Weekend theta calendar pre-close | autopilot._should_exit | Has Friday pre-close for some categories | LOW |
| S10 | ATR-based stop cross-check | strategies/adjustments.py | BSM-based only | MEDIUM |
| S11 | Third-Third-Third adjustment hierarchy | strategies/adjustments.py | Has adjustment logic but not the structured priority | MEDIUM |

### B. Taleb Gaps (Dynamic Hedging)

| # | Concept | Where It Should Live | Current State | Priority |
|---|---------|---------------------|---------------|----------|
| T1 | Shadow gamma (BSM × 1.3-1.5 for puts) | risk/scenarios.py | Symmetric BSM gamma | HIGH |
| T2 | Gap risk model (stop-loss fails in gaps) | autopilot._should_exit | Fixed multiplier stop-loss | HIGH |
| T3 | DdeltaDvol joint scenarios | risk/scenarios.py | Has spot × IV matrix but may not weight asymmetrically | HIGH |
| T4 | Up/down gamma asymmetry | risk/scenarios.py | Symmetric stress tests | MEDIUM |
| T5 | VaR tail inadequacy warnings | risk/portfolio.py | Has VaR, no tail-risk flag | MEDIUM |
| T6 | Liquidity hole detection | data/chain_store.py + autopilot | Has spread tracking, no alert | MEDIUM |
| T7 | Gamma evolution tracking (The Bleed) | autopilot Phase 2 | Checks P/L, not gamma drift | LOW |
| T8 | Path-dependent P/L tracking | paper_trade.py | Tracks net P/L, not path cost | LOW |
| T9 | BSM fat-tail multiplier | risk/scenarios.py | Uses BSM directly | MEDIUM |
| T10 | Barrier-like stop behavior warning | autopilot._should_exit | No cascade awareness | LOW |
| T11 | Vega term structure (√T scaling) | core/bsm.py | Has vega, no √T bucketing | LOW |
| T12 | VIX halt at 30 (Taleb-aligned BSM breakdown) | autopilot._preflight | Has VIX check in signals but not hard halt | HIGH |

## Integration Plan: Where Each Fix Goes

### Phase A: Risk Hardening (T1, T2, T3, T12, S1, S2, S5, S7) — CRITICAL

**1. Shadow Gamma in Scenarios** (T1, T4)
File: `risk/scenarios.py`
Current: `_stress_test()` uses BSM gamma symmetrically
Fix: For put-side scenarios (spot down), multiply gamma by `shadow_factor`:
```
shadow_factor = 1.3 if vix < 20 else 1.5  # Taleb Ch.8
```
Apply to all down-move scenarios (-5%, -10%, -20%, -30%).
Also weight down-move P/L by 1.5× in worst-case reporting (T4: down-gamma > up-gamma).

**2. Gap Risk Model** (T2)
File: `autopilot._should_exit`
Current: `total_pnl <= -(max_loss * cfg['stop_loss_multiplier'])`
Fix: Stop-loss is a BEHAVIORAL limit, not a guaranteed exit (Taleb Ch.4). Add:
- If VIX > 25 OR event_near(tomorrow): stop_multiplier × 1.5 (gap-widened)
- Track gap-down history: if NIFTY gapped > 2% in last 30 days, apply widened stop
- Add `_should_exit` comment: "stop-loss is behavioral, not contractual"

**3. DdeltaDvol Joint Scenarios** (T3)
File: `risk/scenarios.py`
Current: Has spot × IV matrix
Fix: Ensure Taleb's specific joint scenarios are tested:
- NIFTY −3%, VIX +5pts
- NIFTY −5%, VIX +10pts (blow-up scenario)
- NIFTY +3%, VIX −3pts
These must be NAMED scenarios (not just matrix cells) so they show up in reports.

**4. VIX Hard Halt** (T12)
File: `autopilot._preflight` or `_should_enter`
Current: signals.py has VIX sweet-spot (14-22), but no hard halt
Fix: If VIX > 30: block ALL new entries. Taleb Ch.15: BSM breaks down above ~30% vol.
Already in config as `vix_halt_above=30` per notes. Wire it into _should_enter.

**5. 2% Per-Trade Risk Cap** (S1)
File: `risk/sizing.py` + `autopilot._should_enter`
Current: Has Kelly/fractional sizing (0.05-0.48×) + max_loss checks
Fix: After sizing, verify: `max_loss_per_trade / current_capital ≤ 0.02`.
Reject if trade risks > 2% AUM. Sebastian Ch.3.

**6. 6% Portfolio Heat** (S2)
File: `autopilot._should_enter`
Current: `max_concurrent_trades` check but no aggregate risk
Fix: Sum `max_loss_per_lot × lots` across ALL open trades.
If total_risk / current_capital > 0.06: block entry. Sebastian Ch.3.

**7. Card Game Value Exit** (S5)
File: `autopilot._should_exit`
Current: Missing
Fix: For short options in a spread, if BSM price of the short leg ≤ ₹3 (NSE-adjusted Card Game Value — Sebastian's $0.10-$0.25 scaled to NIFTY premium levels), and profit is > 75% of max:
Exit. The remaining ₹3 isn't worth the gamma risk of holding.

**8. Wing Price Floor** (S7)
File: `strategies/builder.py`
Current: Has bid-ask and OI filters
Fix: If collected premium per wing < ₹5 (NSE equivalent of Sebastian's $0.25): reject the wing.
$0.25 on a $10 SPX spread ≈ 2.5% of width. For NIFTY 200-pt spread: ₹5 floor.

### Phase B: Signal Enhancement (S3, S4, S6, S10, S11, T5, T6) — IMPORTANT

**9. 5-Phase Skew Model** (S3)
File: `strategies/signals.py`
Current: VIX 4-band regime
Fix: Add ATM IV vs OTM IV skew phase detection (Sebastian Ch.11):
- Phase 1: Normal/flat (16-18% IV)
- Phase 2: Mild skew (OTM puts bid up)
- Phase 3: Crisis skew (30-40%+ ATM, steep)
- Phase 4: Post-crisis (20-35%, ATM > OTM normalizing)
- Phase 5: Crushed (~6% spread, back to Phase 1)
Use to gate strategy selection: iron condors only in phases 1-2, 5.

**10. % OTM Cross-Check** (S4)
File: `strategies/builder.py`
Current: Delta-based strike selection
Fix: After selecting strikes by delta, verify short strikes are 8.5-10% OTM from spot.
If < 8.5% OTM: too close, reject. If IV surface makes 10-delta strike < 8.5% OTM, the IV is lying (Sebastian Ch.11: IV trap — 10-delta is not the same % OTM across IV regimes).

**11. 3-Day Forward Test** (S6)
File: `strategies/adjustments.py`
Current: Triggers adjustment immediately
Fix: When urgency > 2 (not emergency), require 2 of 3 consecutive days with spot beyond half-σ before adjusting. Sebastian Ch.12: "3-day rule" prevents over-adjustment.
Track in paper_trade.py metadata: `adjustment_signal_day_count`.

**12. ATR Cross-Check** (S10)
File: `strategies/adjustments.py`
Current: BSM-based stop only
Fix: Cross-check BSM adjustment trigger with 14-day ATR:
If spot has moved < 1.5× ATR from entry, don't trigger. Prevents adjusting on normal noise.

**13. Third-Third-Third Adjustment Hierarchy** (S11)
File: `strategies/adjustments.py`
Current: Has adjustment actions but not the priority order
Fix: For iron condor upside breach: 1) kite spread, 2) ratio spread, 3) call spread, 4) add margin.
For downside: 1) ratio put, 2) put spread, 3) add margin.
Only cascade to next if prior is unavailable. Sebastian Ch.9.

**14. VaR Tail Warning** (T5)
File: `risk/portfolio.py`
Current: Has VaR computation
Fix: After computing VaR, check if expected tail loss (CVaR/ES) > 3× VaR.
If so, flag: "VaR misleading — tail risk 3-5× VaR per Taleb Ch.VaR".
Show CVaR alongside VaR in dashboard.

**15. Liquidity Hole Alert** (T6)
File: `autopilot._should_exit` Phase 2 checks
Current: Has spread data from chain_store
Fix: If current bid-ask spread > 2× the 20-day average spread for the same strike:
Flag "liquidity deterioration" with urgency=3.
If > 3×: urgency=2 (consider exit — liquidity hole forming).

### Phase C: Monitoring Enhancement (S8, S9, T7, T8, T9, T10, T11) — NICE-TO-HAVE

**16-22.** Over-adjustment counter, weekend theta, gamma drift, path P/L, fat-tail BSM, barrier cascade warning, vega bucketing.
All LOW priority. Defer until Phase A+B prove stable.

## Proposed Config Additions

```python
# autopilot_config additions
'max_trade_risk_pct': 2.0,       # S1: Sebastian 2% per-trade
'max_portfolio_heat_pct': 6.0,   # S2: Sebastian 6% aggregate
'card_game_exit_threshold': 3.0, # S5: ₹3 NSE-adjusted
'wing_credit_floor': 5.0,        # S7: ₹5 minimum per wing
'shadow_gamma_low': 1.3,         # T1: Taleb shadow gamma (VIX<20)
'shadow_gamma_high': 1.5,        # T1: Taleb shadow gamma (VIX≥20)
'vix_halt_above': 30,            # T12: No entries above VIX 30
'gap_stop_multiplier': 1.5,      # T2: Gap-widened stop
'adjustment_wait_days': 3,       # S6: 3-day forward test
'atr_noise_threshold': 1.5,      # S10: ATR noise filter
'liquidity_deterioration_x': 2.0 # T6: Spread deterioration trigger
```

---

## 10-Round Red/Blue Team Brainstorm

### Round 1: "The Gap-Down Massacre"
**RED**: NIFTY gaps down 5% on RBI surprise rate hike (happened Dec 2022). Your stop-loss at 2× max_loss is meaningless — the position opens at 4× max_loss. Your `max_daily_loss=15000` is behavioral, not contractual (Taleb Ch.4). The ₹15K loss becomes ₹60K because you can't exit at your target price.
**BLUE**: Gap risk model (T2) widens stops when VIX > 25 or events are near. But the REAL defense is sizing: S1's 2% per-trade cap means even a 4× max_loss = 8% AUM = survivable. S2's 6% portfolio heat means max 3 concurrent positions × 8% = 24% worst case, not account-ending. Pre-event calendar (event_calendar.py) already reduces position size before RBI meetings.
**VERDICT**: Sizing IS the defense, not stop-loss. The 2%/6% framework (Sebastian) + position reduction before events is the correct architecture. Stop-loss is a secondary, unreliable safety net.

### Round 2: "The Slow Bleed"
**RED**: You hold an iron condor for 25 days. Spot barely moved. You're at 60% profit. But gamma has tripled as DTE shrinks from 30 to 5. A 2% spot move that was safe at entry now blows through the short strike. Your _should_exit only checks P/L, DTE threshold, and adjustment urgency — it doesn't track HOW MUCH the gamma profile has changed.
**BLUE**: DTE exit threshold (weekly_dte_exit) catches this. If set to 3-5, the position closes before gamma explosion. The Card Game Value exit (S5) also fires: if short option premium has decayed to ₹3, exit — the remaining premium isn't worth the gamma risk. Together, these two rules prevent the slow bleed.
**VERDICT**: DTE threshold + Card Game Value exit are sufficient. Gamma evolution tracking (T7) is nice-to-have but the two simpler rules catch the same risk. Keep DTE exit at ≤5 for weeklies, ≤3 for monthlies.

### Round 3: "The IV Trap"
**RED**: VIX is at 12 (low). Your signals.py says "vol-selling sweet spot." You enter an iron condor. But ATM IV is 12% and OTM put IV is 20% (steep skew, Sebastian Phase 2-3). Your 10-delta put is only 6% OTM (not the usual 10%). A 6% move — normal for NIFTY in a month — hits your short put. The delta-based strike selection was a false sense of security.
**BLUE**: The % OTM cross-check (S4) catches this. After selecting strikes by delta, verify short puts are ≥ 8.5% OTM. If 10-delta = only 6% OTM, reject and either widen or skip. The 5-phase skew model (S3) would also flag: Phase 2-3 skew means iron condors are risky — selector should prefer butterflies or calendars.
**VERDICT**: Both S4 (% OTM check) and S3 (skew phase) are needed. They catch different aspects: S4 is a builder-level gate, S3 is a selector-level signal. Together they prevent the IV trap.

### Round 4: "The Over-Adjustment Death"
**RED**: Trade enters. Day 3: spot moves 1.5%. Adjustment triggers: roll the put spread. Day 7: spot reverses. Another adjustment: roll the call spread. Day 12: spot moves again. Third adjustment. Each adjustment costs ₹1,500 in round-trip transaction costs (₹6,000 for 4 legs). After 3 adjustments = ₹4,500 in costs against ₹2,000 max profit. The adjustment engine destroyed the trade's edge (Sebastian Ch.12: "over-adjustment disease").
**BLUE**: Three defenses: (1) 3-day forward test (S6): don't adjust until spot stays beyond half-σ for 2 of 3 days. (2) ATR noise filter (S10): if move < 1.5× ATR, it's noise, not signal. (3) Over-adjustment counter (S8): warn at 2 adjustments, block at 3 unless urgency=1. Transaction cost model (cost_model.py) should be consulted BEFORE each adjustment: if adjustment cost > remaining profit target, just exit instead.
**VERDICT**: The 3-day rule (S6) is the primary defense. ATR filter (S10) is secondary. Over-adjustment counter (S8) is a hard stop. Cost-vs-profit check before adjusting is elegant — compare adjustment cost to remaining profit. If cost > 50% of remaining profit: exit, don't adjust.

### Round 5: "The VaR Lie"
**RED**: Portfolio VaR says ₹15,000 at 99% confidence. You size to VaR. But your iron condors have short gamma — the tail is NOT normal. The 1% tail event produces ₹50,000 loss, not ₹15,000 (Taleb Ch.VaR: "VaR says nothing about what happens in the 1%"). VaR is also backward-looking: the calm period before the storm shows low VaR precisely when risk is highest (pre-2008 VIX was ~12).
**BLUE**: (1) Always compute CVaR/ES alongside VaR and flag when CVaR > 3× VaR. (2) Use stress scenarios (risk/scenarios.py) as the BINDING constraint, not VaR. The 2008 (-60%) and 2020 (-38%) stress tests with shadow gamma (T1: 1.3-1.5×) are more informative than VaR. (3) Size to stress-test worst-case, not VaR. (4) The 2%/6% Sebastian rules don't depend on VaR at all — they're AUM-based, not model-based.
**VERDICT**: VaR is a reporting metric, NOT a sizing input. Stress scenarios + Sebastian's AUM-based rules are the sizing inputs. Display CVaR alongside VaR in dashboard with a "⚠ tail risk" flag when CVaR > 3× VaR. Never let VaR determine position size.

### Round 6: "The Liquidity Mirage"
**RED**: You're holding a NIFTY iron condor. Market drops 3% intraday. You trigger an exit. But OTM put bid-ask spread has blown from ₹1 to ₹8 (liquidity hole — Taleb Ch.4). Your 4-leg exit costs ₹6,000+ in slippage instead of the modeled ₹1,500. The cost model assumed normal spreads. Your actual exit price is 4× worse than modeled.
**BLUE**: (1) Liquidity hole alert (T6): if current spread > 2× 20-day average, flag before attempting exit. If > 3×: wait for spread to normalize unless urgency=1. (2) The cost model should use CURRENT spread, not historical average, for exit cost estimation. (3) For non-emergency exits, use LIMIT orders at mid-price, not market orders. (4) The execution bridge already has `_wait_fill` with timeout — if fill doesn't come at limit, escalate to market only for urgency=1.
**VERDICT**: Two changes: (a) T6 liquidity alert prevents exits into illiquid markets for non-emergency cases, (b) cost_model.py should accept current_spread parameter for exit estimation. The execution bridge's limit → market escalation is correct architecture.

### Round 7: "The Correlated Blow-Up"
**RED**: You have 2 iron condors: NIFTY and BANKNIFTY. Max concurrent = 2, so you're at capacity. But NIFTY and BANKNIFTY have ρ ≈ 0.9 (Taleb Ch.22). A 5% NIFTY drop = 5% BANKNIFTY drop. Your portfolio VaR treats them as independent (portfolio.py uses ρ=0 per KNOWN_CEILINGS). Both positions blow through stops simultaneously. Your 6% portfolio heat is actually 12% in a correlated event.
**BLUE**: (1) For highly correlated underlyings (ρ > 0.7), treat aggregate risk as if fully correlated: 2% + 2% = 4%, not 2% (diversified). (2) With only NIFTY as the current trading symbol (BANKNIFTY lots discontinued), this is moot. (3) If we add more underlyings, the 6% portfolio heat calculation must use MAX(independent_sum, correlated_sum × ρ). (4) Taleb Ch.22: Cholesky decomposition for multi-asset — but for 2 assets, just multiply by ρ.
**VERDICT**: Current system only trades NIFTY, so correlation risk is zero. BUT: if/when BANKNIFTY or stock options are added, the portfolio heat check (S2) must account for correlation. Add a comment/config: `correlation_adjustment=true` for when multi-underlying is enabled. For now, single-underlying makes this a non-issue.

### Round 8: "The ArcSine Delusion"
**RED**: You've incubated for 3 months (Phase 7). The strategy shows 8 wins, 2 losses, PF 2.1. You graduate it to live trading with ₹38K. But ArcSine law (Taleb Ch.3): with only 10 trades, the probability of this record being indistinguishable from a zero-edge strategy is ~57%. Your WFA re-validation at 3 months is statistically meaningless. You're trading live on luck.
**BLUE**: (1) The WFA graduation criteria require: ≥30 trades (not 10), t-test p>0.44, efficiency ratio 0.70-1.30, DD efficiency > 0. These are exactly Taleb/ArcSine-aware thresholds. (2) The t-test explicitly asks "is this distinguishable from zero-edge?" — that's the ArcSine defense made statistical. (3) 3-month re-validation is a CHECK, not graduation — graduation requires ≥30 trades from the full WFA/backtest period, not just 3 months of paper. (4) Phase 7 already has "ABORTED" status for strategies that fail checks.
**VERDICT**: The system is already ArcSine-aware via the ≥30 trade minimum and t-test. The 3-month paper trading period adds trades to the count. The key is: never graduate a strategy with < 30 paper trades regardless of PF. The current system handles this correctly.

### Round 9: "The Model Wrong-Side"
**RED**: You price iron condor legs using BSM. Taleb Ch.15: real markets have fat tails. Your OTM put at 5% OTM is priced at ₹15 by BSM. Real-world probability of hitting is 3-8× higher than BSM predicts (empirical: 2,703 SP500 data points showed multiple 5σ+ events, BSM predicts ~0). You're systematically UNDERPRICING the risk of your short puts. Your entry gate (risk ratio) uses BSM-derived max_loss which is too low.
**BLUE**: (1) Shadow gamma (T1) addresses this for scenarios: multiply put-side gamma by 1.3-1.5. (2) The entry gate already uses scenario-based risk ratio, not just BSM. (3) For PRICING the short put, BSM is fine — we're selling at market price, not BSM theoretical. The market already embeds the skew/fat-tail premium via the volatility smile. (4) Where BSM wrongness matters is in RISK estimation, and that's where shadow gamma + stress scenarios apply. (5) The cost model uses ACTUAL market premiums for entry/exit.
**VERDICT**: BSM wrongness matters for RISK, not for PRICING (since we trade at market prices, not BSM prices). Shadow gamma (T1) + stress scenarios correctly inflate the risk estimates. No change needed to pricing — only to risk assessment. The key insight: BSM is the wrong model for risk but the right model for Greeks direction.

### Round 10: "The Weekend Theta Trap"
**RED**: You hold a calendar spread over Friday. You expect to collect 2.5 days of weekend theta. But Sebastian Ch.12: weekend theta is largely priced in by Friday morning. The front-month short leg's theta is already discounted. You're not actually earning extra theta — the market has already taken it. Worse: Monday opens with potential gap risk but no extra theta earned to compensate.
**BLUE**: (1) Friday pre-close is already in _should_exit for certain categories. (2) For calendars specifically: if we hold over weekend, the earned theta is net zero (front-month theta ≈ back-month theta since both discount weekend). The advantage is only if front-month decays MORE than back-month — which it does by √T scaling (Taleb Ch.9). (3) But the gap risk of Monday open is real. (4) Resolution: for calendars, exit Friday if profit > 50% of target. For iron condors, the theta earned over weekend slightly exceeds the gap risk IF VIX is normal and no events.
**VERDICT**: Calendar-specific: exit Friday at 50% profit. Iron condor: hold through weekend IF no Monday event AND VIX < 22. Add to _should_exit: `if strategy.category == 'calendar' and is_friday and profit_pct > 50: exit`. Current system's weekend pre-close check needs calendar-specific logic.

---

## Architecture Summary: 15 Must-Implement Changes

### CRITICAL (Phase A — before next live deployment):
1. **S1**: 2% per-trade AUM cap in _should_enter
2. **S2**: 6% portfolio heat in _should_enter
3. **S5**: Card Game Value exit (≤₹3) in _should_exit
4. **S7**: Wing credit floor (≥₹5) in builder.py
5. **T1**: Shadow gamma 1.3-1.5× in scenarios.py
6. **T2**: Gap-widened stop when VIX > 25 or event near
7. **T3**: Named DdeltaDvol joint scenarios
8. **T12**: VIX > 30 hard entry halt

### IMPORTANT (Phase B — within 2 weeks):
9. **S3**: 5-phase skew model in signals.py
10. **S4**: % OTM cross-check (≥8.5%) in builder.py
11. **S6**: 3-day forward test in adjustments.py
12. **S10**: ATR noise filter in adjustments.py
13. **T5**: CVaR alongside VaR + tail warning
14. **T6**: Liquidity deterioration alert

### NICE-TO-HAVE (Phase C — when stable):
15. **S8, S9, S11, T7, T8, T9, T10, T11**: defer

## Decision: VaR is Reporting, Not Sizing

Taleb's 5 VaR flaws + Sebastian's AUM-based rules converge:
- SIZE by: 2% per-trade, 6% aggregate, stress-test worst-case
- REPORT by: VaR + CVaR (with tail warning)
- HALT by: VIX > 30, consecutive losses, margin usage

VaR never determines position size. Stress scenarios + AUM caps do.
