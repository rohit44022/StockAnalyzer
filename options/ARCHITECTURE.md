# Options Trading System — Architecture

Production-grade options trading system for Indian equities (NSE).
Designed from: Natenberg, Cohen, Sinclair, Davey + NSE market mechanics.

## Design Principles

1. **Variance premium is THE edge** (Sinclair Ch.4): IV > RV ~68-80% of time. India: ~2.5 pts avg (vs ~4 pts SPX). Smaller but real. System is built around harvesting this, with India-calibrated expectations.
2. **BSM is 93% of industry** (Sinclair App.3): Use BSM as the pricing language. Don't over-model.
3. **Walk-forward or it didn't happen** (Davey Ch.13): No strategy goes live without WFA + Monte Carlo.
4. **Fractional Kelly sizing** (Sinclair Ch.9): 0.05–0.48× Kelly. 25% over-bet kills growth.
5. **Operational risk kills more than market risk** (Sinclair Ch.10): Barings, LTCM, XIV. Guard rails non-negotiable.
6. **Spreads non-negotiable** (Sinclair Ch.8): Naked positions only for index ATM. Everything else is a spread.
7. **Cost model first** (Sinclair Ch.10): STT, brokerage, slippage eat 30–50% of edge. Never backtest without costs.

## NSE-Specific Constraints (verified Oct 2026)

- **Index options** (Nifty, Bank Nifty): European-style, cash-settled
- **Stock options**: European-style (since 2010), **physical settlement** (since 2019) — shares delivered/received
- **Lot sizes (Jan 2026)**: Nifty=**65**, BankNifty=**30**, FinNifty=60, MidcapNifty=120 (SEBI: contract value ₹15-20L)
- **Weekly expiry**: **Nifty only, every Tuesday** (NSE). BankNifty/FinNifty weekly DISCONTINUED Nov 2024
- **Monthly expiry**: **Last Tuesday** of month for all indices + stocks (changed from Thu, Sep 2025)
- **Margins**: SPAN + Exposure + ELM. **+2% extra ELM on short index options on expiry day** (Nov 2024). Calendar spread margin benefit **removed on expiry day** (Feb 2025)
- **Upfront premium**: Option buyers must have **full premium upfront** — cannot use unrealized P&L (Feb 2025)
- **Costs (Apr 2026)**: STT **0.15%** sell-side on premium, brokerage ₹20/order flat, exchange charges **0.035%**, GST 18% on (brokerage+exchange)
- **India VIX**: NSE's fear gauge, long-term average **~14%**, range 9-90, revert-target for vol strategies
- **Trading hours**: 9:15 AM – 3:30 PM IST. No pre/post-market for options
- **Strike intervals**: Nifty=50pts, BankNifty=100pts, stocks vary
- **Settlement price**: Index options settle on **last 30-min VWAP** of underlying (not LTP or close)
- **Physical settlement margins**: Increase E-4→E-day (10%→25%→45%→70%→100% of contract value)
- **Close-to-money OTM**: Even OTM stock options near strike get **25% delivery margin** on expiry day
- **MWPL ban**: OI > 95% MWPL → no fresh positions (delta-based FutEq from Oct 2025)
- **Position limits**: Client-level limits per SEBI (1% of MWPL or ₹500 crore, whichever lower)

## Module Architecture

```
options/
├── ARCHITECTURE.md          ← this file
├── options_books/           ← source books + notes (already exists)
│
├── core/                    ← pricing, Greeks, volatility (pure math, no I/O)
│   ├── __init__.py
│   ├── bsm.py              ← Black-Scholes-Merton pricing + Greeks
│   ├── binomial.py          ← Binomial tree (American options, dividend handling)
│   ├── greeks.py            ← All Greeks: primary (δ,γ,θ,ν,ρ) + higher-order (vanna, charm, volga, speed)
│   ├── iv.py                ← Implied volatility solver (Newton-Raphson + bisection fallback)
│   ├── volatility.py        ← Historical vol estimators (C2C, Parkinson, Garman-Klass, Yang-Zhang)
│   ├── vol_forecast.py      ← EWMA, GARCH(1,1), ensemble forecast, mean-reversion model
│   ├── vol_surface.py       ← IV term structure, skew modeling, sticky-strike vs sticky-delta
│   ├── payoff.py            ← Strategy payoff calculator (any N-leg combo)
│   ├── cost_model.py        ← NSE cost model: STT 0.15%, brokerage, exchange 0.035%, slippage
│   └── dividends.py         ← Dividend-adjusted forward pricing for stock options
│
├── strategies/              ← strategy definitions, selection, signals
│   ├── __init__.py
│   ├── registry.py          ← Strategy catalog (all 58 from Cohen, coded as dataclasses)
│   ├── selector.py          ← Strategy selection engine: outlook × vol_regime × risk_budget → ranked strategies
│   ├── builder.py           ← Construct strategy legs from underlying + chain data
│   ├── signals.py           ← Entry/exit signal generation (variance premium, PCR, max pain, VIX regime)
│   └── adjustments.py       ← Position adjustment rules (roll, widen, close leg)
│
├── data/                    ← data acquisition and storage
│   ├── __init__.py
│   ├── chain.py             ← Option chain fetcher (NSE API / broker API) + MWPL data
│   ├── india_vix.py         ← India VIX historical + live data
│   ├── oi_analysis.py       ← Open Interest analysis, PCR, Max Pain, OI-price regime
│   ├── chain_store.py       ← Historical chain: bhavcopy download + live snapshots (SQLite)
│   ├── pipeline.py          ← EOD batch pipeline + real-time streaming mode
│   ├── rate.py              ← Risk-free rate (RBI repo rate / T-bill yield)
│   ├── event_calendar.py    ← RBI policy, earnings, budget, elections, expiry dates, NSE holidays
│   └── fii_dii.py           ← FII/DII daily derivative positions (NSE-published, sentiment signal)
│
├── risk/                    ← position and portfolio risk management
│   ├── __init__.py
│   ├── position.py          ← Single position Greeks aggregation, P&L scenarios
│   ├── portfolio.py         ← Portfolio-level Greeks, correlation risk, VaR
│   ├── sizing.py            ← Fractional Kelly, fixed-fraction, max-loss sizing
│   ├── margin.py            ← SPAN margin estimator + expiry-day ELM surcharge + physical settlement margins
│   ├── limits.py            ← Hard limits + MWPL/ban period check + client position limits + broker auto-sq-off times
│   ├── scenarios.py         ← Catastrophe scenario tables (Sinclair Ch.8): ±10/20/30% underlying moves
│   ├── physical_settlement.py ← Delivery obligation calc, margin escalation (E-4→E), CTM handling, auto-exit
│   └── audit.py             ← Trade log, SEBI P&L export, post-trade analysis
│
├── backtest/                ← strategy validation (Davey methodology)
│   ├── __init__.py
│   ├── engine.py            ← Walk-forward backtest engine with cost model
│   ├── walk_forward.py      ← Walk-forward analysis: in-sample optimize → out-of-sample validate
│   ├── monte_carlo.py       ← Monte Carlo simulation for drawdown/return distributions
│   ├── metrics.py           ← Performance: Sharpe, Sortino, Calmar, profit factor, return/DD, win rate
│   └── report.py            ← Backtest report generator (HTML/JSON)
│
├── paper/                   ← Paper trading incubation (Phase 6.5)
│   ├── __init__.py
│   └── engine.py            ← Simulated trading against live data, paper vs backtest comparison
│
└── web/                     ← Flask routes + templates (follows existing app pattern)
    ├── __init__.py
    ├── routes.py             ← Blueprint: /options/* endpoints
    └── templates/
        └── options/
            ├── dashboard.html    ← Main options dashboard
            ├── chain.html        ← Option chain viewer with Greeks overlay
            ├── strategy.html     ← Strategy builder + payoff diagram
            ├── volatility.html   ← Vol surface, IV vs RV, term structure
            └── backtest.html     ← Backtest results viewer
```

## Module Details

### 1. core/bsm.py — Black-Scholes-Merton Engine

The foundation. Every other module depends on this.

```
Inputs: S (spot), X (strike), t (time to expiry in years), r (risk-free rate),
        σ (volatility), q (dividend yield, 0 for indices)

Formulas (Natenberg Ch.18):
  d1 = [ln(S/X) + (r - q + σ²/2)t] / (σ√t)
  d2 = d1 - σ√t

  Call = Se^(-qt)·N(d1) - Xe^(-rt)·N(d2)
  Put  = Xe^(-rt)·N(-d2) - Se^(-qt)·N(-d1)

  Where N(x) = cumulative normal distribution function

Functions:
  price(S, X, t, r, σ, q, option_type) → float
  delta(...)  → float     # ∂C/∂S = e^(-qt)·N(d1) for calls
  gamma(...)  → float     # ∂²C/∂S² = e^(-qt)·n(d1)/(S·σ·√t)
  theta(...)  → float     # ∂C/∂t (per day, divide by 365)
  vega(...)   → float     # ∂C/∂σ = S·e^(-qt)·n(d1)·√t (per 1% vol)
  rho(...)    → float     # ∂C/∂r = X·t·e^(-rt)·N(d2) for calls

  # Higher-order (Natenberg Ch.9)
  vanna(...)  → float     # ∂²C/∂S∂σ  (delta sensitivity to vol)
  charm(...)  → float     # ∂²C/∂S∂t  (delta decay)
  volga(...)  → float     # ∂²C/∂σ²   (vega convexity)
  speed(...)  → float     # ∂³C/∂S³   (gamma sensitivity to spot)

  # Utility
  forward_price(S, r, q, t) → float    # F = S·e^((r-q)t)
  pv(X, r, t) → float                  # X·e^(-rt)

Quick approximation (Natenberg "40% rule"):
  ATM call ≈ 0.4 × S × σ × √t
  ATM put  ≈ same (at-the-forward, call ≈ put)
```

### 2. core/iv.py — Implied Volatility Solver

```
Given market price, solve BSM backwards for σ.

Method: Newton-Raphson (vega as derivative), bisection fallback.

  iv_solve(market_price, S, X, t, r, q, option_type) → float
    1. Initial guess: ATM approximation σ₀ = market_price / (0.4 × S × √t)
    2. Newton: σ_{n+1} = σ_n - (BSM(σ_n) - market_price) / vega(σ_n)
    3. Converge when |BSM(σ_n) - market_price| < 0.01
    4. Fallback to bisection if Newton diverges (σ < 0 or σ > 500%)
    5. Max 100 iterations

  iv_chain(chain_df, S, r, q) → DataFrame
    Compute IV for entire option chain. Skip illiquid strikes (bid=0 or spread>20%).
```

### 3. core/volatility.py — Historical Volatility Estimators

```
Four estimators (Natenberg Ch.20, Sinclair Ch.3):

1. Close-to-Close (standard):
   σ = √[(1/(n-1)) × Σ(ln(Ci/Ci-1))²] × √252
   Most common. Uses closing prices only. Misses intraday info.

2. Parkinson (high-low):
   σ = √[(1/(4n·ln2)) × Σ(ln(Hi/Li))²] × √252
   ~5× more efficient than C2C. Misses overnight gaps.

3. Garman-Klass (OHLC):
   σ = √[(1/n) × Σ(0.5×ln(Hi/Li)² - (2ln2-1)×ln(Ci/Oi)²)] × √252
   Best single-estimator. Uses all OHLC data.

4. Yang-Zhang (open-aware):
   Combines overnight vol + open-to-close vol. Most robust to drift.

Functions:
  realized_vol(prices_df, window=20, method='garman_klass') → Series
  vol_cone(prices_df, windows=[5,10,20,60,120,252]) → DataFrame
    # Percentile cone: min/25th/median/75th/max for each window
```

### 4. core/vol_forecast.py — Volatility Forecasting

```
Ensemble approach (Sinclair Ch.3):

1. EWMA (Exponentially Weighted Moving Average):
   σ²_t = λ·σ²_{t-1} + (1-λ)·r²_t
   λ = 0.94 (RiskMetrics default). Weight decays as λ^i.

2. GARCH(1,1):
   σ²_t = ω + α·r²_{t-1} + β·σ²_{t-1}
   Where ω = long-run variance weight, α = news weight, β = persistence.
   α + β < 1 for stationarity. Long-run vol = √(ω/(1-α-β)).

3. Mean-reversion model:
   Short-term → medium-term: weight recent + long-run average
   Natenberg 5-period weighted: (15%×28% + 25%×22% + 35%×19% + 25%×18%) = 20.85%

4. Ensemble:
   σ_forecast = w1·EWMA + w2·GARCH + w3·mean_reversion
   Default weights: 0.4/0.4/0.2 (Sinclair recommends equal-weighting)

Functions:
  ewma_vol(returns, lambda_=0.94) → float
  garch_vol(returns) → float  # fit GARCH(1,1), return forecast
  ensemble_forecast(prices_df, horizon_days=30) → dict
    # Returns: {forecast_vol, ewma, garch, mean_rev, confidence_interval}

Variance Premium (THE edge):
  variance_premium(iv, rv) → float   # iv - rv; positive = sell premium
  vp_percentile(iv, rv, history) → float  # where current VP sits historically
```

### 5. core/vol_surface.py — Volatility Surface

```
IV Term Structure (Natenberg Ch.20):
  Plot IV across expirations for ATM strikes.
  Normal: upward sloping (short-term < long-term)
  Inverted: fear regime (short-term > long-term, high VIX)

IV Skew (Natenberg Ch.24):
  Equity/index: downside skew (OTM puts have higher IV than OTM calls)
  Causes: crash demand, leverage effect, risk aversion

  Sticky-strike model: IV stays with strike as spot moves
  Sticky-delta model: IV stays with delta as spot moves

Skew metrics:
  skew_25d = IV(25δ put) - IV(25δ call)   # typically positive for equity
  skew_ratio = IV(25δ put) / IV(25δ call)  # >1.0 = normal skew
  butterfly_25d = (IV(25δ put) + IV(25δ call))/2 - IV(ATM)  # smile convexity

Functions:
  build_surface(chain_data, expirations) → VolSurface
  term_structure(chain_data) → DataFrame  # ATM IV by expiry
  skew_at_expiry(chain_data, expiry) → DataFrame  # IV by strike/delta
  skew_metrics(chain_data, expiry) → dict  # 25d skew, butterfly, ratio
```

### 6. core/cost_model.py — NSE Transaction Costs (verified Apr 2026)

```
Critical: costs eat 30-50% of edge (Sinclair Ch.10).
With India's 0.15% STT, cost drag is HIGHER than US markets.

Per-trade costs for NSE options (current as of Apr 2026):
  STT (Securities Transaction Tax):
    Options Buy: 0 (no STT on buy)
    Options Sell: 0.15% of premium (on sell side only)
    Options Exercise: 0.15% of intrinsic value
    Futures Sell: 0.05% of price

  Brokerage: ₹20/order (flat, Zerodha/discount broker) or % based

  Exchange charges: 0.035% of turnover (NSE, reduced from 0.0495% in Oct 2024)

  GST: 18% on (brokerage + exchange charges). NOT on STT.

  SEBI charges: ₹10/crore

  Stamp duty: 0.003% on buy side (varies by state)

  Physical settlement (stock options only):
    DP charges: ₹15.93/scrip (Zerodha) for delivery
    Short delivery penalty: auction + 20% higher price

  Slippage estimate:
    Nifty ATM: 0.5-1 tick (₹0.05-₹0.10 per unit)
    Nifty OTM: 1-3 ticks
    BankNifty ATM: 1-2 ticks
    Stock options: 2-10 ticks (many are illiquid)

  Example — Nifty short straddle round-trip cost:
    Sell ATM call ₹200 × 65 lot = ₹13,000 premium
    STT: ₹13,000 × 0.15% = ₹19.50
    Brokerage: ₹20 × 2 legs = ₹40
    Exchange: ₹13,000 × 0.035% = ₹4.55
    GST: (₹40 + ₹4.55) × 18% = ₹8.02
    Per-side total: ~₹72 for one leg
    Full straddle (4 legs: sell call, sell put, buy-to-close both): ~₹290
    As % of premium collected (₹400 × 65 = ₹26,000): ~1.1%

Functions:
  trade_cost(premium, qty, side, instrument_type) → dict
    # Returns: {stt, brokerage, exchange, gst, sebi, stamp, slippage, total}

  round_trip_cost(entry_premium, exit_premium, qty, instrument) → float
    # Total cost for open + close

  cost_as_iv_points(total_cost, vega, qty) → float
    # Express cost in IV terms (to compare with edge)

  # Critical: net_edge = gross_variance_premium - cost_in_iv_points
  # If net_edge < 0.5 IV points → strategy not worth trading
```

### 7. strategies/registry.py — Strategy Catalog

```
All 58 strategies from Cohen, stored as dataclasses.

@dataclass
class OptionStrategy:
    name: str
    category: str          # 'directional', 'income', 'volatility', 'rangebound', 'leveraged', 'synthetic'
    outlook: str           # 'bullish', 'bearish', 'neutral', 'vol_up', 'vol_down'
    legs: list[Leg]        # each leg: {type: call/put, action: buy/sell, strike_offset: ATM/OTM/ITM, expiry: near/far}
    max_profit: str        # formula or 'unlimited'
    max_loss: str          # formula or 'unlimited'
    breakeven: str         # formula(s)
    greeks_profile: dict   # {delta: +/-, gamma: +/-, theta: +/-, vega: +/-}
    margin_required: bool  # True if short naked legs
    nse_compatible: bool   # some strategies need American-style exercise
    min_capital: str       # rough capital needed
    risk_reward_ratio: str # e.g., '1:3' or 'limited:unlimited'

Key strategies for NSE (European, cash-settled index):
  Income/Premium selling:
    - Short straddle, short strangle (ATM, high-margin)
    - Iron condor (defined risk, lower margin)
    - Iron butterfly
    - Credit spreads (bull put, bear call)
    - Covered call (on stock holdings)

  Directional:
    - Bull/bear call/put spreads
    - Diagonal spreads

  Volatility:
    - Long straddle/strangle (pre-event: earnings, RBI, elections)
    - Ratio backspreads (1×2 put spread, Sinclair's favorite)

  Rangebound:
    - Butterfly (long)
    - Condor (long)

Strategy selection matrix (Cohen Ch.7):
  outlook × vol_expectation × risk_tolerance → ranked strategy list
```

### 8. strategies/signals.py — Signal Generation

```
Edge sources (Sinclair Ch.5):

1. Variance Premium (primary):
   Signal: IV - forecast_RV > threshold (e.g., > 1.5 IV points for India)
   India data: avg VP ~2.5 pts, positive ~70% of time (vs ~4 pts / 85% for SPX)
   Action: Sell premium (short straddle, iron condor, credit spread)
   Filter: India VIX regime (best at VIX 14-22, avoid VIX < 11)

2. PCR (Put-Call Ratio):
   PCR = Put OI / Call OI (or Put Volume / Call Volume)
   PCR > 1.3: oversold / fear → contrarian bullish
   PCR < 0.7: complacent → contrarian bearish
   Use as confirmation, not primary signal

3. Max Pain:
   Strike where total option buyer loss is maximized
   Price tends toward max pain near expiry (market maker hedging)
   Useful for short-term range estimation, not directional

4. India VIX Regime (long-term avg ~14, NOT 15-20):
   VIX < 11: complacent, avoid vol-selling (low premium, surprise risk)
   VIX 14-22: sweet spot for vol-selling
   VIX > 25: fear, vol-selling is rich but dangerous; spreads mandatory
   VIX > 35: crisis mode (elections 2024: ~25, COVID 2020: ~90)
   VIX term structure: contango = normal, backwardation = crisis

5. Skew Signal:
   Steep skew (25d skew > 8): OTM puts expensive → sell put spreads
   Flat skew (25d skew < 3): complacent → buy tail protection

6. Event Calendar (→ data/event_calendar.py):
   RBI policy (India's FOMC equivalent): IV crush post-announcement, VIX drops ~3%
   Earnings: IV crush next day, straddle/strangle before if IV < realized
   Union Budget (February): VIX can spike 30-50%
   Elections: VIX 25+ (2024 general election), collapses post-result
   Weekly expiry Tuesday: gamma exposure peaks, pin risk
   Monthly expiry last Tuesday: settlement on VWAP, physical settlement risk for stocks

Functions:
  scan_signals(underlying, chain, vix, rv_history) → list[Signal]
  variance_premium_signal(iv, rv_forecast) → Signal
  pcr_signal(chain) → Signal
  max_pain(chain) → float  # strike with max pain
  vix_regime(vix_value, vix_history) → str  # 'low'/'normal'/'high'/'crisis'
```

### 9. strategies/selector.py — Strategy Selection Engine

```
Given: market_outlook, vol_regime, risk_budget, days_to_expiry
Returns: ranked list of suitable strategies with expected edge

Decision tree (synthesized from Cohen Ch.7 + Sinclair):

  if vol_regime == 'high' and variance_premium > 4:
      # Sell premium, but ALWAYS with defined risk
      if outlook == 'neutral':
          → iron_condor, iron_butterfly, short_strangle (with stops)
      elif outlook == 'bullish':
          → bull_put_spread, jade_lizard
      elif outlook == 'bearish':
          → bear_call_spread

  elif vol_regime == 'low':
      # Buy premium or wait
      if pre_event:  # earnings, RBI, election
          → long_straddle, long_strangle (cheap premium)
      else:
          → calendar_spread (sell near, buy far — vol usually mean-reverts up)

  elif vol_regime == 'normal':
      # Balanced approaches
      if outlook == 'bullish':
          → bull_call_spread, diagonal_call
      elif outlook == 'bearish':
          → bear_put_spread, diagonal_put
      elif outlook == 'neutral':
          → iron_condor (wide wings), butterfly

Ranking factors:
  1. Expected edge (variance premium × probability)
  2. Risk/reward ratio
  3. Margin efficiency
  4. Bid-ask cost (illiquid strikes penalized)
  5. Complexity (simpler preferred, Sinclair: BSM is 93%)
```

### 10. risk/sizing.py — Position Sizing

```
Fractional Kelly (Sinclair Ch.9):

Kelly criterion (binary outcome):
  f* = (p × b - q) / b
  Where p = win probability, q = 1-p, b = win/loss ratio

For non-normal returns (options):
  Use log-growth maximization (Sinclair eq. 9.16-9.38)
  Adjust for skewness and kurtosis:
    f*_adjusted = f* × [1 + (skew/6)×f* + ((kurt-3)/24)×f*²]

CRITICAL: Always use FRACTIONAL Kelly
  - 25% over-bet → positive-EV strategy loses money
  - Non-normal distributions make over-betting even worse
  - Practical range: 0.05× to 0.48× Kelly
  - Default: 0.25× Kelly (conservative)
  - Monte Carlo validation: simulate 10,000 paths to verify growth

Position limits (hard guardrails):
  - Max 5% of capital per position (single strategy)
  - Max 20% of capital in correlated positions
  - Max 50% of capital deployed total
  - Position-level stop: 2-3× expected daily theta
  - Portfolio-level stop: -15% drawdown → reduce all by 50%

Functions:
  kelly_fraction(win_prob, win_loss_ratio) → float
  adjusted_kelly(returns_distribution) → float  # non-normal adjustment
  position_size(capital, kelly_frac, max_loss, fractional=0.25) → int  # lots
  validate_size(proposed_lots, capital, margin_per_lot, limits) → bool
```

### 11. risk/scenarios.py — Catastrophe Analysis

```
Before entering ANY position, compute P&L under stress (Sinclair Ch.8):

Scenario table for underlying moves:
  Spot changes: -30%, -20%, -10%, -5%, 0%, +5%, +10%, +20%, +30%
  IV changes: -50%, -25%, 0%, +25%, +50%, +100% (for each spot change)
  Time changes: 0, 7, 14, 21, 28 days elapsed

Output: 3D P&L grid showing worst-case across all combinations.

Key rule: If worst-case loss > 2× expected theta income, don't enter.

For Indian market specifics:
  - Nifty: use 2008 (-60%), 2020 March (-38%) as stress reference
  - Bank Nifty: higher beta, multiply Nifty stress by 1.3-1.5×
  - Use India VIX history: max ~90 (March 2020), min ~9

Functions:
  scenario_table(position_legs, S, r, t, vol) → DataFrame
    # Columns: spot_change, iv_change, days_elapsed, pnl
  max_loss_scenario(position_legs, S, r, t, vol) → dict
  stress_test(position, stress_type='2020_crash') → dict
```

### 12. backtest/engine.py — Walk-Forward Backtest

```
Davey methodology (Ch.13-14):

1. Define strategy with SMART goals:
   - Specific: "sell Nifty iron condor weekly at VIX > 15"
   - Measurable: "target 1.5% weekly, <10% monthly DD"
   - Achievable: consistent with variance premium literature
   - Relevant: to capital base and risk tolerance
   - Time-bound: "evaluate after 6 months"

2. Walk-forward analysis:
   - Split data: 70% in-sample, 30% out-of-sample (rolling windows)
   - In-sample: optimize parameters (strike selection, entry timing)
   - Out-of-sample: validate with zero changes
   - Walk forward: slide window, repeat
   - Pass/fail: out-of-sample return/DD > 2.0

3. Monte Carlo validation:
   - Resample trade returns (bootstrap) 10,000 times
   - Build distribution of: max DD, final return, Sharpe
   - 95th percentile DD = realistic worst case
   - If 95th percentile DD > quit threshold → reject strategy

4. Incubation:
   - Paper trade 3-6 months before live
   - Compare paper vs backtest: within 1σ band?
   - If consistently worse → investigate execution assumptions

5. Cost model ALWAYS on:
   - Every backtest trade charged: STT + brokerage + slippage
   - No strategy accepted if costs > 30% of gross edge

Functions:
  backtest(strategy, chain_history, config) → BacktestResult
  walk_forward(strategy, chain_history, in_pct=0.7, out_pct=0.3) → WFAResult
  monte_carlo(trade_returns, n_sims=10000, n_trades=252) → MCResult
  evaluate(wfa_result, mc_result, goals) → PassFail
```

### 13. backtest/metrics.py — Performance Metrics

```
Davey Ch.6-7 + Sinclair Ch.7:

  sharpe_ratio(returns, rf=0) → float
    # (mean - rf) / std × √252

  sortino_ratio(returns, rf=0) → float
    # (mean - rf) / downside_std × √252

  calmar_ratio(returns) → float
    # annualized_return / max_drawdown

  profit_factor(trades) → float
    # gross_profit / gross_loss (want > 1.5)

  return_to_dd(returns) → float
    # total_return / max_drawdown (Davey: want > 2.0)

  max_drawdown(equity_curve) → float
    # deepest peak-to-trough decline

  win_rate(trades) → float
    # % of profitable trades

  avg_win_loss_ratio(trades) → float
    # avg_winning_trade / avg_losing_trade

  # Sinclair's Generalized Sharpe Ratio (adjusts for skew/kurtosis):
  gsr(returns) → float
    # SR × [1 + (skew/6)×SR - ((kurt-3)/24)×SR²]
    # Lower than SR for short-vol strategies (negatively skewed)

  expectancy(trades) → float
    # (win_rate × avg_win) - (loss_rate × avg_loss) per trade
```

### 14. data/chain.py — Option Chain Data (NSE parser + synthetic)

```
NSE JSON parser + synthetic chain generator for testing.
  parse_nse_chain_json(data) → DataFrame
  generate_synthetic_chain(spot, ...) → DataFrame
  lot_size(symbol) → int
  mwpl_check(oi, mwpl_limit) → dict
```

### 14b. data/dhan_fetch.py — Dhan API Fetcher (PRODUCTION)

```
Live option chain data via Dhan broker API (dhanhq SDK 2.2.0).
API docs: https://dhanhq.co/docs/v2/
Rate limit: 1 unique option chain request per 3 seconds.

Requires: DHAN_CLIENT_ID + DHAN_ACCESS_TOKEN in .env

Security IDs: NIFTY=13, BANKNIFTY=25, FINNIFTY=27
Segment: IDX_I (weekly+monthly), NSE_FNO (monthly only)

Response includes: LTP, bid/ask+qty, OI, volume, IV, greeks
  (delta, gamma, theta, vega) — richer than NSE bhavcopy.

Returns DataFrames in canonical chain schema (same columns as
chain.py output), so all downstream modules work unchanged:
  oi_analysis, vol_surface, pipeline, chain_store

Functions:
  expiry_list(symbol) → list[date]
  fetch_chain(symbol, expiry=None) → (DataFrame, spot)
  fetch_multi_expiry_chain(symbol, n=3) → (DataFrame, spot)
  fetch_spot(symbol) → float
```

### 15. data/oi_analysis.py — Open Interest Analysis

```
PCR (Put-Call Ratio):
  pcr_oi = total_put_OI / total_call_OI
  pcr_volume = total_put_volume / total_call_volume
  Interpretation: > 1.3 bearish/fear, < 0.7 bullish/complacent

Max Pain:
  For each strike K:
    call_pain = Σ max(0, K - strike_i) × call_OI_i  (for all strikes below K)
    put_pain = Σ max(0, strike_i - K) × put_OI_i   (for all strikes above K)
    total_pain = call_pain + put_pain
  max_pain_strike = argmin(total_pain)

OI-based support/resistance:
  High put OI at strike → support (writers defend)
  High call OI at strike → resistance (writers defend)
  OI buildup + price move = trend confirmation
  OI buildup + no price move = range

Functions:
  pcr(chain_df, method='oi') → float
  max_pain(chain_df) → float
  oi_support_resistance(chain_df) → dict  # {supports: [...], resistances: [...]}
  oi_change_analysis(chain_df, prev_chain_df) → DataFrame
```

## Data Flow

```
Market Data (NSE/Broker API)
    │
    ▼
┌──────────┐    ┌──────────────┐    ┌────────────┐
│  chain   │───▶│  iv solver   │───▶│ vol surface │
│  fetcher │    │  (per strike)│    │ (skew/term) │
└──────────┘    └──────────────┘    └────────────┘
    │                                      │
    ▼                                      ▼
┌──────────┐    ┌──────────────┐    ┌────────────┐
│ OI/PCR/  │    │ vol forecast │    │  signals   │
│ max pain │    │ (EWMA/GARCH) │    │ generator  │
└──────────┘    └──────────────┘    └────────────┘
                       │                   │
                       ▼                   ▼
                ┌──────────────┐    ┌────────────┐
                │  strategy    │◀──▶│  strategy  │
                │  selector    │    │  builder   │
                └──────────────┘    └────────────┘
                       │
                       ▼
                ┌──────────────┐    ┌────────────┐
                │    risk      │───▶│  sizing    │
                │  scenarios   │    │  (Kelly)   │
                └──────────────┘    └────────────┘
                       │
                       ▼
                ┌──────────────┐
                │   backtest   │
                │  (WFA + MC)  │
                └──────────────┘
                       │
                       ▼
                ┌──────────────┐
                │  dashboard   │
                │  (Flask web) │
                └──────────────┘
```

### 16. risk/physical_settlement.py — Physical Settlement (Stock Options)

```
Stock options on NSE require physical delivery of shares since 2019.
This module prevents the #1 retail options disaster: accidental delivery obligation.

Margin escalation schedule (SEBI):
  E-4 (4 days before expiry): 10% of contract value (Qty × spot price)
  E-3: 25%
  E-2: 45%
  E-1: 70%
  E-day: 100%

  Where contract value = lot_size × spot_price (NOT premium)
  Example: RELIANCE 2500CE, lot=250, spot=₹2,600
  E-day margin = 250 × ₹2,600 = ₹6,50,000 (full share value)

Close-to-money (CTM) rule:
  Even OTM options near the strike get blocked with 25% delivery margin
  on expiry day. Broker defines "near" (typically within 1-2 strikes).
  This catches traders who think their OTM position is "safe."

Delivery obligations:
  Long ITM call at expiry → must PAY full contract value, receive shares
  Short ITM call at expiry → must DELIVER shares from demat
  Long ITM put at expiry → must DELIVER shares from demat
  Short ITM put at expiry → must PAY full contract value, receive shares

Functions:
  margin_escalation(position, days_to_expiry, spot_price) → float
    # Returns margin required at current E-minus day

  is_physical_settlement(symbol) → bool
    # True for stock options, False for index options

  delivery_obligation(position, spot_price, is_itm) → dict
    # {direction: 'take'/'give', shares: int, value: float}

  should_auto_exit(position, days_to_expiry, available_margin, has_shares) → bool
    # True if can't meet delivery — must exit before expiry

  ctm_margin_check(position, spot_price, strike) → float
    # Extra margin for close-to-money OTM positions on expiry day
```

### 17. risk/limits.py — Position Limits, MWPL, Ban Period

```
MWPL (Market Wide Position Limit):
  Each stock has a maximum total OI limit set by NSE quarterly.
  Based on free-float market cap + average daily turnover.

  Alert: OI > 60% of MWPL → watchlist (system warns)
  Ban:   OI > 95% of MWPL → NO fresh positions, only squaring off
  Unban: OI < 80% of MWPL → fresh positions resume

  New (Oct 2025): Delta-based FutEq framework — actual exposure by delta,
  not just contract count.

Client position limits (SEBI):
  Index: varies by index (higher limits)
  Stock: 1% of MWPL or ₹500 crore (whichever lower)
  Combined across ALL brokers

Broker auto-square-off awareness:
  Zerodha/Angel: auto square-off intraday positions at 3:20 PM
  Margin shortfall: broker RMS can exit ANY position at any time
  Expiry day: some brokers square off as early as 3:00 PM

Functions:
  fetch_mwpl(symbol) → dict  # {mwpl_limit, current_oi, pct_used, is_banned}
  check_ban_status(symbol) → str  # 'clear' / 'alert' / 'banned'
  check_position_limit(symbol, proposed_lots, existing_lots) → bool
  broker_cutoff_time(is_expiry_day=False) → time  # when broker may sq-off
```

### 18. data/event_calendar.py — Event Calendar

```
Options are event-driven instruments. Missing an event = surprise vol.

Event types:
  RBI Monetary Policy: 6 meetings/year (bi-monthly). IV crush post-announcement.
    VIX typically drops ~3% on announcement day.

  Quarterly Earnings: Per stock. IV spikes 2-3 weeks before, crushes day after.
    Nifty50 stocks: earnings clustered in Apr/Jul/Oct/Jan.

  Union Budget: Usually Feb 1. Historically biggest vol event.
    VIX can spike 30-50% in lead-up.

  Elections: General (every 5 years), state (frequent).
    2024 general election: VIX hit ~25, collapsed to ~12 post-result.

  Monthly Expiry: Last Tuesday. Gamma exposure peaks.
    Stock options: physical settlement risk.

  NSE Holidays: ~15 per year. Gap risk = no hedging possible.

Functions:
  upcoming_events(symbol=None, days_ahead=30) → list[Event]
  is_event_window(symbol, date, window_days=5) → bool
  event_iv_impact(event_type) → dict  # historical IV change stats
  nse_holidays(year) → list[date]
  next_expiry(weekly=True) → date
  days_to_expiry(expiry_date) → int
```

### 19. data/fii_dii.py — FII/DII Derivative Positions

```
NSE publishes daily FII (Foreign Institutional Investor) and DII
(Domestic Institutional Investor) positions in derivatives.

Data points:
  - FII/DII long/short in index futures (contracts + value)
  - FII/DII long/short in index options (calls/puts separately)
  - FII/DII long/short in stock futures
  - FII/DII long/short in stock options

Signals:
  FII net long index futures + heavy put writing → strong bullish
  FII unwinding index longs + buying puts → bearish
  FII-DII divergence → regime change signal
  FII put OI at specific strikes → institutional support levels

Functions:
  fetch_fii_dii_data(date=None) → DataFrame
  fii_index_sentiment() → str  # 'bullish' / 'bearish' / 'neutral'
  fii_put_support_levels(index='NIFTY') → list[float]  # strikes with heavy FII put OI
```

### 20. data/chain_store.py — Historical Chain Data Strategy

```
The hardest data problem in Indian options: NSE does not publish historical
option chains with bid-ask spreads. Three tiers, use all three.

Tier 1 — Bhavcopy (FREE, available now):
  NSE publishes daily "bhavcopy" CSV files:
    - fo_bhavcopy: OHLC + settle + volume + OI per contract per day
    - Available back to ~2011 on NSE archives
    - Missing: bid-ask spread, intraday snapshots, greeks
  Use for: backtest entry/exit on LTP or settle price, OI analysis, PCR history

  Download: NSE archives → daily CSV → SQLite
  Schema: (date, symbol, expiry, strike, option_type, open, high, low, close,
           settle, volume, oi, oi_change)

Tier 2 — Live Snapshot Capture (FREE, start now):
  Capture live chain snapshots via broker API (Kite/Angel) every 5-15 min
  during market hours. Save to SQLite with full bid-ask-qty depth.

  Schema: (timestamp, symbol, expiry, strike, option_type, ltp, bid, ask,
           bid_qty, ask_qty, oi, volume, iv, underlying_price)

  START THIS IMMEDIATELY — every day of data not captured is gone forever.
  6 months of snapshots = enough for initial WFA validation.

  Storage: ~50 MB/day for Nifty+BankNifty full chains at 5-min intervals.
  1 year ≈ 12 GB uncompressed, ~3 GB compressed.

Tier 3 — Paid Vendor (when revenue justifies ~₹8-12K/yr):
  Global Data Feeds (~₹8K/yr) or True Data (~₹12K/yr):
    - Tick-level option data with bid-ask
    - 3-5 years of history
    - Intraday snapshots
  Use for: production-grade backtests with realistic fills

Backtest bid-ask modeling (until Tier 3):
  Bhavcopy has no bid-ask. Model spread from LTP + rules:
    Index ATM (Nifty/BankNifty): 1 tick (₹0.05) — extremely liquid
    Index 1 strike OTM: 1-2 ticks
    Index 2+ strikes OTM: 2-3 ticks
    Stock ATM (top 15 liquid): 3-5 ticks
    Stock OTM / illiquid: 5-10+ ticks (or skip entirely)

  Conservative rule: assume 2× modeled spread for slippage.
  Flag all bhavcopy-based backtest results as "LTP-based, spread modeled."

Functions:
  download_bhavcopy(date) → DataFrame        # fetch NSE daily file
  bulk_download(start_date, end_date) → int   # batch download, return count
  store_bhavcopy(df, date) → None             # persist to SQLite
  capture_live_snapshot(symbol) → None         # save current chain to DB
  load_chain(symbol, date, expiry=None) → DataFrame  # retrieve stored chain
  estimate_spread(symbol, strike, option_type, oi, volume) → float  # model bid-ask
  chain_history(symbol, start, end) → DataFrame  # time series of chain data
```

### 21. risk/audit.py — Trade Log and Audit Trail

```
Every trade must be logged with full context for SEBI compliance,
tax computation, and post-trade analysis. Not optional for real money.

Trade log schema:
  @dataclass
  class TradeRecord:
      trade_id: str               # UUID
      timestamp: datetime         # entry time (IST)
      symbol: str                 # e.g. 'NIFTY'
      expiry: date
      strategy_name: str          # e.g. 'iron_condor'
      legs: list[LegRecord]       # each leg separately
      entry_signal: str           # what triggered entry
      exit_signal: str            # what triggered exit (filled on close)
      entry_iv: float             # IV at entry
      exit_iv: float              # IV at exit
      entry_underlying: float     # spot at entry
      exit_underlying: float      # spot at exit
      gross_pnl: float            # before costs
      total_costs: float          # STT + brokerage + exchange + GST + slippage
      net_pnl: float              # gross - costs
      holding_period: int         # days
      sizing_kelly_frac: float    # what Kelly fraction was used
      margin_used: float          # margin blocked for this trade

  @dataclass
  class LegRecord:
      leg_id: str
      option_type: str            # 'CE' / 'PE'
      strike: float
      action: str                 # 'BUY' / 'SELL'
      qty: int                    # number of lots × lot_size
      entry_price: float
      exit_price: float
      entry_bid_ask: tuple        # (bid, ask) at entry
      exit_bid_ask: tuple         # (bid, ask) at exit
      slippage: float             # actual fill vs mid

SEBI P&L format:
  F&O turnover = sum of absolute P&L per trade (not notional).
  Tax audit required if turnover > ₹10 crore.
  Losses carry forward 8 years if ITR filed on time.

  generate_sebi_pnl(trades, fiscal_year) → DataFrame
    # Columns: scrip, trade_date, buy_value, sell_value, pnl
    # Grouped by: speculative vs non-speculative business income

Post-trade analysis:
  For each closed trade, compute:
  - Was the entry signal correct? (did IV > RV hold?)
  - Was the exit signal correct? (or stopped out prematurely?)
  - Slippage vs model: how far was actual fill from expected?
  - Edge realized vs expected: net_pnl vs what the model predicted

Functions:
  log_trade(trade: TradeRecord) → None       # persist to SQLite
  close_trade(trade_id, exit_data) → None    # fill exit fields
  trade_history(symbol=None, start=None, end=None) → list[TradeRecord]
  generate_sebi_pnl(fiscal_year) → DataFrame
  trade_analysis(trade_id) → dict            # post-trade decomposition
  export_csv(fiscal_year) → Path             # for CA / tax filing
```

### 22. data/oi_analysis.py — OI-Price Interpretation Rules

```
(Extends the existing oi_analysis.py spec with the 4 OI-price combos)

The 4 OI-price interpretation rules (standard market microstructure):

  | OI Change | Price Change | Interpretation          | Action              |
  |-----------|-------------|-------------------------|---------------------|
  | OI ↑      | Price ↑     | Long buildup (bullish)  | Fresh longs entering|
  | OI ↑      | Price ↓     | Short buildup (bearish) | Fresh shorts entering|
  | OI ↓      | Price ↑     | Short covering (weak bull)| Shorts exiting    |
  | OI ↓      | Price ↓     | Long unwinding (weak bear)| Longs exiting     |

  These apply to the UNDERLYING's OI (futures) or to individual strikes.
  "Buildup" = conviction (new money). "Unwinding/covering" = weak (old money leaving).

Integration with existing oi_analysis.py:
  Add to oi_change_analysis():
    - Classify each strike's OI change into one of the 4 regimes
    - Aggregate across strikes for net market sentiment
    - Weight by OI magnitude (large OI change at key strikes matters more)

Additional function:
  oi_price_regime(oi_change, price_change) → str
    # Returns: 'long_buildup' / 'short_buildup' / 'short_covering' / 'long_unwinding'

  oi_sentiment_summary(chain_df, prev_chain_df, underlying_change) → dict
    # {regime: str, conviction: float, key_strikes: list}
```

### 23. data/pipeline.py — EOD vs Real-Time Data Pipeline

```
Two distinct pipelines. EOD is the foundation; real-time is Phase 7.

EOD Pipeline (build in Phase 2):
  Runs once daily after market close (3:30 PM IST + 30 min buffer).

  Steps:
    1. Download bhavcopy (fo + equity) from NSE archives
    2. Compute: PCR, max pain, OI S/R, OI-price regime for each symbol
    3. Compute: realized vol (all 4 estimators), vol cone update
    4. Compute: IV surface from bhavcopy settle prices
    5. Fetch: India VIX close, FII/DII positions, MWPL data
    6. Fetch: RBI repo rate (changes ~6x/year)
    7. Store all to SQLite (chain_store + analytics tables)
    8. Run: signal scan → update strategy recommendations
    9. Run: margin check on open positions
    10. Generate: daily report (signals, P&L, risk)

  Trigger: cron job or manual. No broker API needed for EOD.
  Data lag: T+0 for bhavcopy (available by ~4:30 PM IST).

Real-Time Pipeline (Phase 7, needs broker API):
  WebSocket or polling via Kite/Angel API during market hours.

  Streams:
    - Underlying price (tick-level)
    - Option chain snapshots (5-min intervals → chain_store)
    - India VIX live
    - Position Greeks (recomputed on each underlying tick)
    - Margin utilization

  Alerts (push notifications):
    - Position stop-loss hit
    - Margin exceeds threshold
    - MWPL approaching ban (>85%)
    - Expiry-day physical settlement warning
    - VIX regime change (crossed threshold)
    - Broker auto-sq-off approaching (3:00-3:20 PM)

Functions:
  run_eod_pipeline(date=None) → dict          # full daily refresh
  eod_report(date=None) → dict                # daily summary
  start_realtime(symbols, broker_api) → None   # Phase 7
  stop_realtime() → None
```

### 24. backtest/engine.py — Bid-Ask Spread Handling in Backtests

```
(Extends the existing backtest engine spec)

The #1 backtest lie: assuming you trade at LTP.
In reality, you cross the spread. This section makes it mandatory.

Fill simulation rules:
  1. If chain_store has bid-ask data (Tier 2/3):
     Buy fill = ask price (you lift the offer)
     Sell fill = bid price (you hit the bid)
     Aggressive: worst of bid/ask. Conservative: mid + half spread.

  2. If bhavcopy only (Tier 1, no bid-ask):
     Use estimated spread from chain_store.estimate_spread()
     Buy fill = LTP + half_spread
     Sell fill = LTP - half_spread

  3. Volume check:
     If strategy lot_size > 20% of that strike's daily volume → SKIP.
     You can't realistically fill in an illiquid strike.

  4. Slippage multiplier:
     Apply 1.5-2× the modeled spread as total execution cost.
     This accounts for: timing, partial fills, adverse selection.

  5. VWAP settlement at expiry:
     Index options: use last-30-min VWAP, not close price.
     If VWAP data unavailable in bhavcopy, use settle price (close proxy).

Every backtest report MUST show:
  - Gross P&L (before all costs)
  - Cost breakdown (STT, brokerage, exchange, GST, spread, slippage)
  - Net P&L (after all costs)
  - Cost as % of gross edge
  - Data tier used (bhavcopy-modeled vs actual bid-ask)
  - "BHAVCOPY WARNING" flag if spread was modeled, not observed

Functions (additions to engine.py):
  simulate_fill(price, spread, side, volume, lot_size) → float
  backtest_cost_report(result: BacktestResult) → dict
  validate_liquidity(strike, volume, lot_size) → bool
```

## Implementation Phases

### Phase 1: Core Engine (foundation — must be rock-solid)
- `core/bsm.py` — BSM pricing + all Greeks
- `core/iv.py` — IV solver
- `core/volatility.py` — Historical vol estimators
- `core/payoff.py` — N-leg payoff calculator
- `core/cost_model.py` — NSE costs (**0.15% STT**, exchange 0.035%, full cost stack)
- `core/dividends.py` — Dividend-adjusted forward pricing
- Tests for all of the above (assert-based self-checks)

### Phase 2: Data + Volatility Analysis
- `data/chain.py` — Option chain fetcher + MWPL data
- `data/chain_store.py` — Bhavcopy bulk download + live snapshot capture (START IMMEDIATELY)
- `data/pipeline.py` — EOD batch pipeline (cron after market close)
- `data/india_vix.py` — VIX data (long-term avg ~14%)
- `data/oi_analysis.py` — PCR, Max Pain, OI S/R, **OI-price regime (4 combos)**
- `data/event_calendar.py` — RBI, earnings, budget, elections, holidays
- `data/fii_dii.py` — FII/DII derivative positions
- `data/rate.py` — RBI repo rate
- `core/vol_forecast.py` — EWMA/GARCH ensemble (validate on Nifty data)
- `core/vol_surface.py` — Skew and term structure

### Phase 3: Strategy Engine
- `strategies/registry.py` — Strategy catalog (liquid strategies for NSE only)
- `strategies/selector.py` — Selection engine (India VIX regime: 14-22 sweet spot)
- `strategies/builder.py` — Leg construction + **liquidity filter** (bid-ask < 5%, OI > 1000)
- `strategies/signals.py` — Entry/exit signals (India VP: ~2.5 pts threshold)
- `strategies/adjustments.py` — Adjustments + **rollover management**

### Phase 4: Risk + Sizing
- `risk/position.py` — Position-level Greeks
- `risk/portfolio.py` — Portfolio risk
- `risk/sizing.py` — Kelly sizing (**0.05-0.25× for India**, costs higher)
- `risk/scenarios.py` — Stress testing (use 2008 -60%, 2020 -38% as stress)
- `risk/margin.py` — SPAN margin + **expiry-day 2% ELM** + no calendar margin on expiry
- `risk/limits.py` — MWPL/ban period + client limits + broker auto-sq-off times
- `risk/physical_settlement.py` — Margin escalation E-4→E, CTM, delivery obligation, auto-exit
- `risk/audit.py` — Trade log + SEBI P&L export + post-trade analysis (use from day one)

### Phase 5: Backtesting
- `backtest/engine.py` — Core backtest loop (**settlement on VWAP**, not close)
- `backtest/walk_forward.py` — WFA
- `backtest/monte_carlo.py` — MC simulation
- `backtest/metrics.py` — Performance metrics + **GSR** (Generalized Sharpe for short-vol)
- `backtest/report.py` — Report generator
- **Validate: is net edge positive after Indian costs?** (gross VP 2.5 minus costs)

### Phase 6: Web Dashboard
- `web/routes.py` — Flask blueprint
- Templates: chain viewer, strategy builder, vol surface, backtest viewer
- FII/DII sentiment panel
- Event calendar widget
- MWPL ban status indicators

### Phase 6.5: Paper Trading (Incubation — Davey Ch.14)
- `paper/engine.py` — Paper trading engine against live market data
- Simulated order book: fills at bid/ask with modeled slippage
- Track paper P&L in same schema as `risk/audit.py` trade log
- Compare paper results to backtest expectations: within 1σ band?
- If paper P&L consistently < backtest P&L by >2σ → investigate execution assumptions
- **Minimum 3 months paper before Phase 7** (Davey: 3-6 months incubation)
- Dashboard panel showing paper vs backtest equity curves
- No real orders — uses live price feed only (Dhan API available)

### Phase 7: Live Integration
- Broker API connection (Dhan — already configured, dhanhq SDK 2.2.0)
- Order management + spread order support
- Position monitoring + margin alerts
- Physical settlement auto-exit before expiry
- **Upfront premium check** (Feb 2025 rule)
- Alert system (margin, stop-loss, MWPL, expiry)
- `risk/audit.py` — Full trade logging from day one
- Real-time pipeline (`data/pipeline.py` real-time mode)

## Key Numbers to Remember

| Metric | Value | Source |
|--------|-------|-------|
| **India variance premium** | **~2.5 IV pts, ~70% of time** | NSE empirical data |
| SPX variance premium (reference) | ~4 IV pts, ~85% of time | Sinclair Ch.4 |
| Nifty IV overprices RV | 68% of days, median gap +1.4 pts | NSE option chain study |
| BankNifty IV overprices RV | 66% of days, median gap +1.6 pts | NSE option chain study |
| Stock options VP (e.g. Reliance) | 58% of days, +0.7 pts | NSE option chain study |
| Fractional Kelly range | 0.05–0.25× for India (costs higher) | Sinclair Ch.9 + cost adj |
| 25% over-bet penalty | positive-EV → negative growth | Sinclair Ch.9 |
| **India STT (options sell)** | **0.15%** of premium | Finance Act 2026 |
| Exchange charges | 0.035% of turnover | NSE Oct 2024 |
| Costs eat edge | 30–50% of gross (HIGHER in India) | Sinclair Ch.10 + India STT |
| BSM market share | 93% of derivatives industry | Sinclair App.3 |
| Walk-forward pass | return/DD > 2.0 | Davey Ch.13 |
| Ideas per strategy | 100–200 tested per 1 tradable | Davey Ch.8 |
| **India VIX long-term avg** | **~14%** (not 15-20%) | NSE historical data |
| India VIX normal range | 11–18% | NSE historical data |
| India VIX max | ~90 (March 2020) | NSE data |
| India VIX election spike | ~25 (2024 general election) | NSE data |
| **Nifty lot size** | **65 units** (contract ~₹15-16L) | NSE Jan 2026 |
| **BankNifty lot size** | **30 units** | NSE Jan 2026 |
| **Weekly expiry** | **Nifty only, Tuesday** | SEBI Nov 2024 + Sep 2025 |
| Physical settlement margin E-day | 100% of contract value | SEBI/NSE |
| MWPL ban threshold | OI > 95% → no fresh positions | SEBI |
| Expiry day extra ELM | +2% on short index options | SEBI Nov 2024 |
