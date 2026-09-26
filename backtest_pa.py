"""
Price Action System — Historical Backtest Simulation
=====================================================
Walks through historical data for each stock, generating PA signals
using a rolling window, then checks if targets or stops were hit in
subsequent bars. Reports win/loss/accuracy metrics.

Methodology
-----------
For each stock:
  1. Slide a window of WINDOW_SIZE bars across the history.
  2. At each step, run the full PA engine on the window.
  3. If a BUY or SELL signal is generated (confidence >= MIN_CONF):
     - Record entry price, stop loss, target_1, target_2.
     - Walk forward up to MAX_HOLD bars to see outcome.
     - WIN:  if target_1 is reached before stop loss.
     - LOSS: if stop loss is hit before target.
     - TIMEOUT: if neither hit within MAX_HOLD bars (partial credit).
  4. Skip ahead by COOLDOWN bars after a signal to avoid overlap.
"""

from __future__ import annotations

import json
import os
import sys
import time
import glob
from dataclasses import dataclass, field, asdict
from typing import List, Dict

import pandas as pd
import numpy as np

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from brooks.analyzer import run_price_action_analysis
from brooks.engine import MIN_BARS as _MIN_BARS  # was price_action config
from brooks.ml.regime import classify_regime

# ── Brooks ML model (lazy load) ──
_brooks_xgb = None
_brooks_xgb_medians = None
_brooks_ind_cache = {}  # ticker → indicators

def _load_brooks_ml():
    global _brooks_xgb, _brooks_xgb_medians
    if _brooks_xgb is not None:
        return
    try:
        from pathlib import Path
        import joblib
        mdir = Path(__file__).parent / "brooks" / "ml" / "models"
        p = mdir / "brooks_xgb.joblib"
        if p.exists():
            _brooks_xgb = joblib.load(p)
            mp = mdir / "brooks_xgb_medians.joblib"
            _brooks_xgb_medians = joblib.load(mp) if mp.exists() else {}
    except Exception:
        pass

def _score_one_pick(pick: dict, ticker: str, signal_date: str) -> float | None:
    """Score a single pick with Brooks XGBoost. Returns P(WIN) or None."""
    global _brooks_ind_cache
    if _brooks_xgb is None:
        return None
    from brooks.ml.scorer import FEATURES, SETUP_MAP, PHASE_MAP, AI_MAP, EQ_MAP, STRENGTH_MAP
    import pandas as pd

    # Compute indicators (cached per ticker)
    if ticker not in _brooks_ind_cache:
        from brooks.analyzer import _build_bb_indicators
        _brooks_ind_cache[ticker] = _build_bb_indicators(ticker) or {}
    ind = _brooks_ind_cache[ticker]
    if not ind:
        return None

    feats = {
        "confidence": pick.get("confidence", 50),
        "pa_score": pick.get("pa_score", 0),
        "risk_reward": pick.get("risk_reward", 1.0),
        "traders_equation": pick.get("traders_equation", 0),
        "trend_strength_num": STRENGTH_MAP.get(pick.get("strength", "MODERATE"), 1),
        "volume_ratio": ind.get("volume_ratio", 1.0),
        "rsi14": ind.get("rsi14", 50),
        "bbw": ind.get("bbw", 0.05),
        "atr_pct": ind.get("atr_pct", 2),
        "close_vs_sma20": ind.get("close_vs_sma20", 0),
        "sma20_slope_5d": ind.get("sma20_slope_5d", 0),
        "rsi_slope_5d": ind.get("rsi_slope_5d", 0),
        "bbw_percentile_60d": ind.get("bbw_percentile_60d", 0.5),
        "momentum_10d": ind.get("momentum_10d", 0),
        "momentum_20d": ind.get("momentum_20d", 0),
        "vol_ratio": ind.get("vol_ratio", 1.0),
        "vol_trend_5d": ind.get("vol_trend_5d", 0),
        "atr_percentile_60d": ind.get("atr_percentile_60d", 0.5),
        "setup_encoded": SETUP_MAP.get(pick.get("setup", ""), 3),
        "phase_encoded": PHASE_MAP.get(pick.get("trend_phase", ""), 4),
        "ai_encoded": AI_MAP.get(pick.get("always_in", "FLAT"), 2),
        "eq_encoded": EQ_MAP.get(pick.get("equation_verdict", ""), 1),
        "buying_pressure": pick.get("buying_pressure", 50),
        "selling_pressure": pick.get("selling_pressure", 50),
        "stop_distance_pct": abs(pick.get("entry_price", 0) - pick.get("stop_loss", 0)) / max(pick.get("entry_price", 1), 1) * 100,
        "regime_score": pick.get("regime_score", 0),
    }
    try:
        row = pd.DataFrame([feats])[FEATURES]
        if _brooks_xgb_medians:
            row = row.fillna(_brooks_xgb_medians)
        return float(_brooks_xgb.predict_proba(row)[0, 1])
    except Exception:
        return None

# ─────────────────────────────────────────────────────────────────
#  BACKTEST CONFIGURATION
# ─────────────────────────────────────────────────────────────────
WINDOW_SIZE = 250        # Bars fed to PA engine per signal
STEP_SIZE = 5            # Slide window by N bars between signal checks
COOLDOWN = 10            # Skip N bars after a signal to avoid overlaps
TIMEFRAME = "D"          # "D" = daily (original), "W" = weekly
MAX_HOLD = 12 if TIMEFRAME == "W" else 30
MIN_CONF = 30            # Minimum confidence to count as a signal
PCT_TARGETS = None       # Fixed % targets (T1, T2); None = use engine measured moves
PCT_STOP = None          # Fixed % stop; None = use engine ATR stop
TRAIL_BE_PCT = None      # Move stop to breakeven after this % move; None = off
TRAIL_PCT = None         # Continuous trailing stop: X% below peak; None = off
TRAIL_ACTIVATION = 3     # Only start trailing after this % gain

# ── Production filters ──
PROD_MODE = True         # Apply production filters (BUY only, conf>=60, no FB/CHREV)
PROD_MIN_CONF = 60
PROD_EXCLUDED_SETUPS = {"FAILED_BREAKOUT", "CHANNEL_REVERSAL", "REVERSAL", "SECOND_ENTRY"}
PROD_EXCLUDED_PHASES = {"CHANNEL"}  # 100% losers in test
MAX_STOP_PCT = 8                    # Skip trades with stop > 8% from entry
MIN_REGIME_SCORE = 0                # 0=off, 7=moderate, 9=aggressive/selective

# ── Brooks ML filter ──
ML_FILTER = False         # AUC 0.53 — adds no value with rule-based filters active
ML_FILTER_THRESHOLD = 0.45  # Skip trades with P(WIN) below this

# ── Volume confirmation ──
MIN_VOLUME_RATIO = 1.0    # Require volume >= 1.0x 20-day avg (50% WR / PF 1.67)

# ── Regime filter & capital management ──
REGIME_FILTER = True          # Skip signals in unfavorable regimes
DD_TOLERANCE = True           # Reduce exposure during drawdowns
CAPITAL_SURVIVAL = True       # Dynamic position sizing during DD

# ── NSE cost model (delivery/swing trading) ──
APPLY_COSTS = True
BROKERAGE_PCT = 0.03     # 0.03% each side (Zerodha-style flat broker)
STT_SELL_PCT = 0.10      # 0.1% on sell side (delivery)
STAMP_BUY_PCT = 0.015    # 0.015% on buy side
EXCHANGE_PCT = 0.00345   # NSE transaction charges per side
SEBI_PCT = 0.0001        # SEBI turnover fee per side
GST_RATE = 0.18          # 18% GST on brokerage+exchange+SEBI
SLIPPAGE_PCT = 0.10      # 0.1% per side (market impact)

# ── Liquidity filter ──
MIN_AVG_VOLUME = 50_000  # Minimum 50K shares/day avg volume over window

# ── Position sizing & equity ──
INITIAL_CAPITAL = 10_00_000  # ₹10 lakh
RISK_PER_TRADE = 0.02        # 2% of capital risked per trade

# ── Train/test split ──
SPLIT_DATE = "2022-01-01"
MIN_BARS_NEEDED = WINDOW_SIZE + MAX_HOLD + 10  # Need enough data


# ─────────────────────────────────────────────────────────────────
#  TRADE RESULT
# ─────────────────────────────────────────────────────────────────
@dataclass
class TradeResult:
    ticker: str = ""
    signal_date: str = ""
    direction: str = ""         # BUY or SELL
    setup_type: str = ""
    strength: str = ""
    confidence: int = 0
    pa_score: float = 0.0
    entry_price: float = 0.0
    stop_loss: float = 0.0
    target_1: float = 0.0
    target_2: float = 0.0
    risk_reward: float = 0.0
    outcome: str = ""           # WIN_T1, WIN_T2, LOSS, BREAKEVEN, TIMEOUT_WIN, TIMEOUT_LOSS
    exit_price: float = 0.0
    exit_date: str = ""
    bars_held: int = 0
    pnl_pct: float = 0.0       # percentage gain/loss
    always_in: str = ""
    trend_phase: str = ""
    # Brooks' trader's equation — the book's own filter on whether a setup
    # is worth taking at all: p(success)*reward vs p(failure)*risk.
    traders_equation: float = 0.0
    equation_verdict: str = "NONE"
    regime: str = ""
    regime_score: int = 0
    volume_ratio: float = 0.0
    ml_prob: float = -1.0


# ─────────────────────────────────────────────────────────────────
#  SINGLE STOCK BACKTEST
# ─────────────────────────────────────────────────────────────────
def _round_trip_cost_pct() -> float:
    """Total round-trip cost as % of trade value."""
    per_side = BROKERAGE_PCT + EXCHANGE_PCT + SEBI_PCT
    gst_per_side = per_side * GST_RATE
    buy_cost = per_side + gst_per_side + STAMP_BUY_PCT + SLIPPAGE_PCT
    sell_cost = per_side + gst_per_side + STT_SELL_PCT + SLIPPAGE_PCT
    return buy_cost + sell_cost

RT_COST = _round_trip_cost_pct() if APPLY_COSTS else 0.0


def _resample_weekly(df: pd.DataFrame) -> pd.DataFrame:
    return df.resample("W").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    ).dropna()


def backtest_stock(df: pd.DataFrame, ticker: str) -> List[TradeResult]:
    """Run PA backtest on a single stock's historical data."""
    if TIMEFRAME == "W":
        df = _resample_weekly(df)

    trades: List[TradeResult] = []
    n = len(df)

    if n < MIN_BARS_NEEDED:
        return trades

    # Liquidity filter: compute rolling avg volume
    if MIN_AVG_VOLUME and "Volume" in df.columns:
        avg_vol = df["Volume"].rolling(WINDOW_SIZE, min_periods=20).mean()
    else:
        avg_vol = None

    highs = df["High"].values
    lows = df["Low"].values
    closes = df["Close"].values
    dates = df.index

    i = WINDOW_SIZE
    while i < n - MAX_HOLD:
        # Extract window
        window_df = df.iloc[i - WINDOW_SIZE:i]

        try:
            result = run_price_action_analysis(window_df, ticker)
        except Exception:
            i += STEP_SIZE
            continue

        if not result.success:
            i += STEP_SIZE
            continue

        # Only process actionable signals
        if result.signal_type not in ("BUY", "SELL") or result.confidence < MIN_CONF:
            i += STEP_SIZE
            continue

        # Production filters
        if PROD_MODE:
            if result.signal_type != "BUY":
                i += STEP_SIZE
                continue
            if result.confidence < PROD_MIN_CONF:
                i += STEP_SIZE
                continue
            if result.setup_type in PROD_EXCLUDED_SETUPS:
                i += STEP_SIZE
                continue

        # Liquidity filter
        if avg_vol is not None and avg_vol.iloc[i] < MIN_AVG_VOLUME:
            i += STEP_SIZE
            continue

        # Validate price levels
        if result.entry_price <= 0 or result.stop_loss <= 0 or result.target_1 <= 0:
            i += STEP_SIZE
            continue

        # Avoid invalid risk (stop == entry)
        risk = abs(result.entry_price - result.stop_loss)
        if risk <= 0 or risk / result.entry_price < 0.001:
            i += STEP_SIZE
            continue

        # Skip wide stops (winners avg 6.4% stop, losers 8.3%)
        if MAX_STOP_PCT and risk / result.entry_price * 100 > MAX_STOP_PCT:
            i += STEP_SIZE
            continue

        # Skip excluded phases (CHANNEL = 100% losers in test)
        if PROD_MODE and PROD_EXCLUDED_PHASES and result.trend_phase in PROD_EXCLUDED_PHASES:
            i += STEP_SIZE
            continue

        # ── Brooks ML score (always compute, filter only if ML_FILTER) ──
        _ml_prob = None
        if _brooks_xgb is not None:
            pick_dict = {
                "ticker": ticker,
                "confidence": result.confidence,
                "pa_score": result.pa_score,
                "risk_reward": result.risk_reward,
                "traders_equation": result.traders_equation,
                "strength": result.strength,
                "setup": result.setup_type,
                "trend_phase": result.trend_phase,
                "always_in": result.always_in,
                "equation_verdict": getattr(result, "equation_verdict", ""),
                "buying_pressure": getattr(result, "buying_pressure", 50),
                "selling_pressure": getattr(result, "selling_pressure", 50),
                "volume_ratio": getattr(result, "volume_ratio", 1.0),
            }
            _ml_prob = _score_one_pick(pick_dict, ticker, str(dates[i - 1].date()) if hasattr(dates[i - 1], "date") else str(dates[i - 1]))
            if ML_FILTER and _ml_prob is not None and _ml_prob < ML_FILTER_THRESHOLD:
                i += STEP_SIZE
                continue

        # ── Walk forward to determine outcome ──
        trade = TradeResult(
            ticker=ticker,
            signal_date=str(dates[i - 1].date()) if hasattr(dates[i - 1], "date") else str(dates[i - 1]),
            direction=result.signal_type,
            setup_type=result.setup_type,
            strength=result.strength,
            confidence=result.confidence,
            pa_score=result.pa_score,
            entry_price=result.entry_price,
            stop_loss=result.stop_loss,
            target_1=result.target_1,
            target_2=result.target_2,
            risk_reward=result.risk_reward,
            always_in=result.always_in,
            trend_phase=result.trend_phase,
            traders_equation=result.traders_equation,
            equation_verdict=result.equation_verdict,
        )

        regime_info = classify_regime(window_df)
        trade.regime = regime_info["regime"]
        trade.regime_score = regime_info["score"]

        # Volume ratio at signal
        if "Volume" in window_df.columns and len(window_df) >= 20:
            vol = window_df["Volume"].values.astype(float)
            v_avg = float(vol[-20:].mean())
            trade.volume_ratio = round(float(vol[-1]) / max(v_avg, 1), 2)

        if _ml_prob is not None:
            trade.ml_prob = round(_ml_prob, 4)

        if MIN_VOLUME_RATIO and trade.volume_ratio < MIN_VOLUME_RATIO:
            i += STEP_SIZE
            continue

        if MIN_REGIME_SCORE and trade.regime_score < MIN_REGIME_SCORE:
            i += STEP_SIZE
            continue

        outcome = _evaluate_trade(
            direction=result.signal_type,
            entry=result.entry_price,
            stop=result.stop_loss,
            target_1=result.target_1,
            target_2=result.target_2,
            highs=highs[i:i + MAX_HOLD],
            lows=lows[i:i + MAX_HOLD],
            closes=closes[i:i + MAX_HOLD],
        )

        trade.outcome = outcome["outcome"]
        trade.exit_price = outcome["exit_price"]
        trade.bars_held = outcome["bars_held"]
        trade.pnl_pct = round(outcome["pnl_pct"] - RT_COST, 2)

        # Skip trades where entry was never triggered
        if trade.outcome == "NO_ENTRY":
            i += STEP_SIZE
            continue

        exit_idx = i + outcome["bars_held"] - 1
        if exit_idx < n:
            trade.exit_date = str(dates[exit_idx].date()) if hasattr(dates[exit_idx], "date") else str(dates[exit_idx])

        trades.append(trade)

        # Skip forward to avoid overlapping trades
        i += max(COOLDOWN, outcome["bars_held"])
        continue

    return trades


def _evaluate_trade(
    direction: str,
    entry: float,
    stop: float,
    target_1: float,
    target_2: float,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
) -> dict:
    """Walk forward through bars to determine trade outcome."""
    n = len(highs)
    entered = False
    if PCT_TARGETS:
        t1_pct, t2_pct = PCT_TARGETS
        if direction == "BUY":
            target_1 = round(entry * (1 + t1_pct / 100), 2)
            target_2 = round(entry * (1 + t2_pct / 100), 2)
        else:
            target_1 = round(entry * (1 - t1_pct / 100), 2)
            target_2 = round(entry * (1 - t2_pct / 100), 2)

    if PCT_STOP:
        if direction == "BUY":
            stop = round(entry * (1 - PCT_STOP / 100), 2)
        else:
            stop = round(entry * (1 + PCT_STOP / 100), 2)

    cur_stop = stop
    be_level = None
    if TRAIL_BE_PCT:
        be_level = entry * (1 + TRAIL_BE_PCT / 100) if direction == "BUY" else entry * (1 - TRAIL_BE_PCT / 100)

    trail_peak = entry

    for j in range(n):
        if not entered:
            if direction == "BUY" and highs[j] >= entry:
                entered = True
            elif direction == "SELL" and lows[j] <= entry:
                entered = True
            else:
                continue

        if direction == "BUY":
            # Trailing stop: ratchets up as price makes new highs
            if TRAIL_PCT and highs[j] > trail_peak:
                trail_peak = highs[j]
                gain = (trail_peak - entry) / entry * 100
                if gain >= TRAIL_ACTIVATION:
                    trail_stop = trail_peak * (1 - TRAIL_PCT / 100)
                    cur_stop = max(cur_stop, trail_stop)
            if be_level and cur_stop < entry and highs[j] >= be_level:
                cur_stop = entry
            if lows[j] <= cur_stop:
                pnl = (cur_stop - entry) / entry * 100
                outcome = "LOSS" if pnl < 0 else "BREAKEVEN"
                return {"outcome": outcome, "exit_price": cur_stop, "bars_held": j + 1, "pnl_pct": round(pnl, 2)}
            if highs[j] >= target_1:
                if highs[j] >= target_2:
                    pnl = (target_2 - entry) / entry * 100
                    return {"outcome": "WIN_T2", "exit_price": target_2, "bars_held": j + 1, "pnl_pct": round(pnl, 2)}
                pnl = (target_1 - entry) / entry * 100
                return {"outcome": "WIN_T1", "exit_price": target_1, "bars_held": j + 1, "pnl_pct": round(pnl, 2)}
        else:
            # Trailing stop for SELL: ratchets down as price makes new lows
            if TRAIL_PCT and lows[j] < trail_peak:
                trail_peak = lows[j]
                gain = (entry - trail_peak) / entry * 100
                if gain >= TRAIL_ACTIVATION:
                    trail_stop = trail_peak * (1 + TRAIL_PCT / 100)
                    cur_stop = min(cur_stop, trail_stop)
            if be_level and cur_stop > entry and lows[j] <= be_level:
                cur_stop = entry
            if highs[j] >= cur_stop:
                pnl = (entry - cur_stop) / entry * 100
                outcome = "LOSS" if pnl < 0 else "BREAKEVEN"
                return {"outcome": outcome, "exit_price": cur_stop, "bars_held": j + 1, "pnl_pct": round(pnl, 2)}
            if lows[j] <= target_1:
                if lows[j] <= target_2:
                    pnl = (entry - target_2) / entry * 100
                    return {"outcome": "WIN_T2", "exit_price": target_2, "bars_held": j + 1, "pnl_pct": round(pnl, 2)}
                pnl = (entry - target_1) / entry * 100
                return {"outcome": "WIN_T1", "exit_price": target_1, "bars_held": j + 1, "pnl_pct": round(pnl, 2)}

    if not entered:
        return {"outcome": "NO_ENTRY", "exit_price": 0, "bars_held": 0, "pnl_pct": 0}

    last_close = closes[-1] if n > 0 else entry
    if direction == "BUY":
        pnl = (last_close - entry) / entry * 100
    else:
        pnl = (entry - last_close) / entry * 100

    outcome = "TIMEOUT_WIN" if pnl > 0 else "TIMEOUT_LOSS"
    return {"outcome": outcome, "exit_price": float(last_close), "bars_held": n, "pnl_pct": round(pnl, 2)}


# ─────────────────────────────────────────────────────────────────
#  FULL UNIVERSE BACKTEST
# ─────────────────────────────────────────────────────────────────
NIFTY50 = [
    "ADANIENT.NS", "ADANIPORTS.NS", "APOLLOHOSP.NS", "ASIANPAINT.NS",
    "AXISBANK.NS", "BAJAJFINSV.NS", "BAJFINANCE.NS", "BHARTIARTL.NS",
    "BPCL.NS", "BRITANNIA.NS", "CIPLA.NS", "COALINDIA.NS", "DIVISLAB.NS",
    "DRREDDY.NS", "EICHERMOT.NS", "GRASIM.NS", "HCLTECH.NS", "HDFCBANK.NS",
    "HDFCLIFE.NS", "HEROMOTOCO.NS", "HINDALCO.NS", "HINDUNILVR.NS",
    "ICICIBANK.NS", "INDUSINDBK.NS", "INFY.NS", "ITC.NS", "JSWSTEEL.NS",
    "KOTAKBANK.NS", "LT.NS", "M&M.NS", "MARUTI.NS", "NESTLEIND.NS",
    "NTPC.NS", "ONGC.NS", "POWERGRID.NS", "RELIANCE.NS", "SBILIFE.NS",
    "SBIN.NS", "SHRIRAMFIN.NS", "SUNPHARMA.NS", "TATACONSUM.NS",
    "TATAMOTORS.NS", "TATASTEEL.NS", "TCS.NS", "TECHM.NS", "TITAN.NS",
    "ULTRACEMCO.NS", "WIPRO.NS", "LTIM.NS",
]


def run_full_backtest(max_stocks: int = 0, verbose: bool = True,
                      nifty50: bool = False) -> dict:
    """Run backtest across all stocks in stock_csv/."""
    csv_dir = os.path.join(_ROOT, "stock_csv")
    csv_files = sorted(glob.glob(os.path.join(csv_dir, "*.csv")))

    if nifty50:
        nifty_set = set(NIFTY50)
        csv_files = [f for f in csv_files
                     if os.path.basename(f).replace(".csv", "") in nifty_set]

    if max_stocks > 0:
        csv_files = csv_files[:max_stocks]

    # Load Brooks ML model if filter is enabled
    if ML_FILTER:
        _load_brooks_ml()
        if _brooks_xgb is not None:
            print(f"  Brooks ML filter: ON (threshold={ML_FILTER_THRESHOLD})")
        else:
            print("  Brooks ML filter: models not trained, running without filter")

    all_trades: List[TradeResult] = []
    stocks_processed = 0
    stocks_with_signals = 0
    stocks_skipped = 0
    errors = 0

    total = len(csv_files)
    t0 = time.time()

    if verbose:
        print(f"PA BACKTEST — Processing {total} stocks")
        print("=" * 60)

    for idx, csv_path in enumerate(csv_files):
        ticker = os.path.basename(csv_path).replace(".csv", "")

        try:
            df = pd.read_csv(csv_path, parse_dates=["Date"], index_col="Date")
        except Exception:
            errors += 1
            continue

        if len(df) < MIN_BARS_NEEDED:
            stocks_skipped += 1
            continue

        try:
            trades = backtest_stock(df, ticker)
            stocks_processed += 1
            if trades:
                stocks_with_signals += 1
                all_trades.extend(trades)
        except Exception as e:
            errors += 1
            if verbose and errors <= 5:
                print(f"  ERROR {ticker}: {e}")

        if verbose and (idx + 1) % 100 == 0:
            elapsed = time.time() - t0
            rate = (idx + 1) / elapsed
            print(f"  [{idx + 1}/{total}] {rate:.0f} stocks/sec, "
                  f"{len(all_trades)} trades so far")

    elapsed = time.time() - t0

    # ── Compute metrics ──
    metrics = _compute_metrics(all_trades)
    metrics["meta"] = {
        "total_csv": total,
        "stocks_processed": stocks_processed,
        "stocks_with_signals": stocks_with_signals,
        "stocks_skipped": stocks_skipped,
        "errors": errors,
        "elapsed_sec": round(elapsed, 1),
        "config": {
            "window_size": WINDOW_SIZE,
            "step_size": STEP_SIZE,
            "cooldown": COOLDOWN,
            "max_hold": MAX_HOLD,
            "min_confidence": MIN_CONF,
        },
    }

    if verbose:
        _print_report(metrics)

    # Save results
    output = {
        "metrics": metrics,
        "trades": [asdict(t) for t in all_trades],
    }
    out_path = os.path.join(_ROOT, "backtest_pa_results.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    if verbose:
        print(f"\nResults saved to {out_path}")

    return metrics


def _compute_metrics(trades: List[TradeResult]) -> dict:
    """Compute comprehensive backtest metrics."""
    if not trades:
        return {"total_trades": 0}

    total = len(trades)
    wins = [t for t in trades if t.outcome.startswith("WIN")]
    losses = [t for t in trades if t.outcome == "LOSS"]
    breakevens = [t for t in trades if t.outcome == "BREAKEVEN"]
    timeout_wins = [t for t in trades if t.outcome == "TIMEOUT_WIN"]
    timeout_losses = [t for t in trades if t.outcome == "TIMEOUT_LOSS"]

    win_count = len(wins)
    loss_count = len(losses)
    be_count = len(breakevens)
    tw_count = len(timeout_wins)
    tl_count = len(timeout_losses)

    win_rate = win_count / total * 100 if total else 0
    # Count timeout wins as half-wins for adjusted rate
    adjusted_win_rate = (win_count + tw_count * 0.5) / total * 100 if total else 0

    # P&L
    all_pnl = [t.pnl_pct for t in trades]
    avg_pnl = np.mean(all_pnl) if all_pnl else 0
    total_pnl = sum(all_pnl)

    avg_win_pnl = np.mean([t.pnl_pct for t in wins]) if wins else 0
    avg_loss_pnl = np.mean([t.pnl_pct for t in losses]) if losses else 0

    # Profit factor
    gross_profit = sum(t.pnl_pct for t in trades if t.pnl_pct > 0)
    gross_loss = abs(sum(t.pnl_pct for t in trades if t.pnl_pct < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Average bars held
    avg_bars = np.mean([t.bars_held for t in trades])

    # By direction
    buys = [t for t in trades if t.direction == "BUY"]
    sells = [t for t in trades if t.direction == "SELL"]
    buy_wr = sum(1 for t in buys if t.outcome.startswith("WIN")) / len(buys) * 100 if buys else 0
    sell_wr = sum(1 for t in sells if t.outcome.startswith("WIN")) / len(sells) * 100 if sells else 0

    # By setup type (dynamic — captures all setups found)
    setup_metrics = {}
    all_setups = set(t.setup_type for t in trades if t.setup_type and t.setup_type != "NONE")
    for stype in sorted(all_setups):
        st_trades = [t for t in trades if t.setup_type == stype]
        if st_trades:
            st_wins = sum(1 for t in st_trades if t.outcome.startswith("WIN"))
            setup_metrics[stype] = {
                "trades": len(st_trades),
                "wins": st_wins,
                "win_rate": round(st_wins / len(st_trades) * 100, 1),
                "avg_pnl": round(np.mean([t.pnl_pct for t in st_trades]), 2),
            }

    # By strength
    strength_metrics = {}
    for s in ["STRONG", "MODERATE", "WEAK"]:
        s_trades = [t for t in trades if t.strength == s]
        if s_trades:
            s_wins = sum(1 for t in s_trades if t.outcome.startswith("WIN"))
            strength_metrics[s] = {
                "trades": len(s_trades),
                "wins": s_wins,
                "win_rate": round(s_wins / len(s_trades) * 100, 1),
                "avg_pnl": round(np.mean([t.pnl_pct for t in s_trades]), 2),
            }

    # By confidence tier
    conf_metrics = {}
    for label, lo, hi in [("HIGH (75+)", 75, 101), ("MODERATE (50-74)", 50, 75), ("WEAK (30-49)", 30, 50)]:
        c_trades = [t for t in trades if lo <= t.confidence < hi]
        if c_trades:
            c_wins = sum(1 for t in c_trades if t.outcome.startswith("WIN"))
            conf_metrics[label] = {
                "trades": len(c_trades),
                "wins": c_wins,
                "win_rate": round(c_wins / len(c_trades) * 100, 1),
                "avg_pnl": round(np.mean([t.pnl_pct for t in c_trades]), 2),
            }

    # By trend phase
    phase_metrics = {}
    for phase in ["SPIKE", "TIGHT_CHANNEL", "CHANNEL", "BROAD_CHANNEL", "TRADING_RANGE"]:
        p_trades = [t for t in trades if t.trend_phase == phase]
        if p_trades:
            p_wins = sum(1 for t in p_trades if t.outcome.startswith("WIN"))
            phase_metrics[phase] = {
                "trades": len(p_trades),
                "wins": p_wins,
                "win_rate": round(p_wins / len(p_trades) * 100, 1),
                "avg_pnl": round(np.mean([t.pnl_pct for t in p_trades]), 2),
            }

    # Grade the system
    if win_rate >= 65 and profit_factor >= 1.5:
        grade = "A"
    elif win_rate >= 55 and profit_factor >= 1.2:
        grade = "B"
    elif win_rate >= 45 and profit_factor >= 1.0:
        grade = "C"
    elif win_rate >= 35:
        grade = "D"
    else:
        grade = "F"

    # ── Equity curve with survival features ──
    MAX_POSITIONS = 5
    sorted_trades = sorted(trades, key=lambda t: str(t.signal_date))
    first_date = str(sorted_trades[0].signal_date) if sorted_trades else ""
    last_date = str(sorted_trades[-1].signal_date) if sorted_trades else ""

    capital = float(INITIAL_CAPITAL)
    peak = capital
    max_dd_pct = 0.0
    dd_start_date = None
    max_dd_days = 0
    trades_taken = 0
    skipped_regime = 0
    skipped_bear = 0
    skipped_choppy = 0
    skipped_trending_bear = 0
    dd_reduced_trades = 0

    for t in sorted_trades:
        # Regime filter: skip unfavorable regimes for trend-following BUY
        if REGIME_FILTER and t.regime in ("BEAR", "CHOPPY", "TRENDING_BEAR", "MILD_TREND"):
            skipped_regime += 1
            if t.regime == "BEAR":
                skipped_bear += 1
            elif t.regime == "CHOPPY":
                skipped_choppy += 1
            else:
                skipped_trending_bear += 1
            continue

        # Current drawdown
        dd = (peak - capital) / peak * 100 if peak > 0 else 0

        # DD tolerance + capital survival: combined exposure multiplier
        if DD_TOLERANCE or CAPITAL_SURVIVAL:
            if dd > 30:
                exposure_mult = 0.05    # 1 pos × 25% risk
            elif dd > 20:
                exposure_mult = 0.20    # 2 pos × 50% risk
            elif dd > 10:
                exposure_mult = 0.45    # 3 pos × 75% risk
            else:
                exposure_mult = 1.0
            if exposure_mult < 1.0:
                dd_reduced_trades += 1
        else:
            exposure_mult = 1.0

        per_position = capital / MAX_POSITIONS if capital > 0 else 0
        fixed_risk = per_position * RISK_PER_TRADE * exposure_mult
        risk_pct = abs(t.entry_price - t.stop_loss) / t.entry_price * 100 if t.entry_price > 0 and t.stop_loss > 0 else 5.0
        position_size = min(fixed_risk / (risk_pct / 100), per_position * exposure_mult) if risk_pct > 0 else 0
        trade_pnl = position_size * (t.pnl_pct / 100)
        capital += trade_pnl
        capital = max(capital, 0)
        trades_taken += 1

        if capital > peak:
            peak = capital
            if dd_start_date is not None:
                dd_dur = (pd.Timestamp(str(t.signal_date)) - pd.Timestamp(str(dd_start_date))).days
                max_dd_days = max(max_dd_days, dd_dur)
            dd_start_date = None
        elif peak > 0:
            cur_dd = (peak - capital) / peak * 100
            max_dd_pct = max(max_dd_pct, cur_dd)
            if dd_start_date is None:
                dd_start_date = t.signal_date

    years = max(1, (pd.Timestamp(last_date) - pd.Timestamp(first_date)).days / 365.25) if first_date and last_date else 1
    total_ret = (capital - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    cagr = ((capital / INITIAL_CAPITAL) ** (1 / years) - 1) * 100 if capital > 0 else -100

    taken_pnls = [t.pnl_pct for t in sorted_trades
                  if not (REGIME_FILTER and t.regime in ("BEAR", "CHOPPY", "TRENDING_BEAR", "MILD_TREND"))]
    sharpe = 0.0
    if len(taken_pnls) > 1:
        mean_r = np.mean(taken_pnls)
        std_r = np.std(taken_pnls, ddof=1)
        if std_r > 0:
            trades_per_year = trades_taken / years if trades_taken > 0 else 1
            sharpe = (mean_r / std_r) * np.sqrt(min(trades_per_year, 250))
    calmar = cagr / max_dd_pct if max_dd_pct > 0 else 0

    equity_data = {
        "start_capital": INITIAL_CAPITAL,
        "final_capital": round(capital, 0),
        "total_return_pct": round(total_ret, 1),
        "cagr_pct": round(cagr, 1),
        "max_drawdown_pct": round(max_dd_pct, 1),
        "max_dd_days": max_dd_days,
        "sharpe": round(sharpe, 2),
        "calmar": round(calmar, 2),
        "years": round(years, 1),
        "max_positions": MAX_POSITIONS,
        "per_position": round(INITIAL_CAPITAL / MAX_POSITIONS, 0),
        "trades_taken": trades_taken,
        "skipped_regime": skipped_regime,
        "skipped_bear": skipped_bear,
        "skipped_choppy": skipped_choppy,
        "skipped_trending_bear": skipped_trending_bear,
        "dd_reduced_trades": dd_reduced_trades,
    }

    # ── By regime ──
    regime_metrics = {}
    for regime in ["TRENDING_BULL", "MILD_TREND", "CHOPPY", "BEAR", "TRENDING_BEAR"]:
        r_trades = [t for t in trades if t.regime == regime]
        if r_trades:
            r_wins = sum(1 for t in r_trades if t.outcome.startswith("WIN"))
            regime_metrics[regime] = {
                "trades": len(r_trades),
                "wins": r_wins,
                "win_rate": round(r_wins / len(r_trades) * 100, 1),
                "avg_pnl": round(float(np.mean([t.pnl_pct for t in r_trades])), 2),
            }

    # ── Train / Test split ──
    train_test = {}
    split_ts = pd.Timestamp(SPLIT_DATE)
    for label, subset in [
        ("train", [t for t in trades if pd.Timestamp(str(t.signal_date)) < split_ts]),
        ("test", [t for t in trades if pd.Timestamp(str(t.signal_date)) >= split_ts]),
    ]:
        if not subset:
            train_test[label] = {"trades": 0, "wins": 0, "timeout_wins": 0,
                                  "win_rate": 0, "profit_factor": 0, "avg_pnl": 0}
            continue
        n_sub = len(subset)
        w = sum(1 for t in subset if t.outcome.startswith("WIN"))
        tw_sub = sum(1 for t in subset if t.outcome == "TIMEOUT_WIN")
        pnl_list = [t.pnl_pct for t in subset]
        gp = sum(p for p in pnl_list if p > 0)
        gl_sub = abs(sum(p for p in pnl_list if p < 0))
        train_test[label] = {
            "trades": n_sub,
            "wins": w,
            "timeout_wins": tw_sub,
            "win_rate": round(w / n_sub * 100, 1),
            "profit_factor": round(gp / gl_sub, 2) if gl_sub > 0 else 999,
            "avg_pnl": round(np.mean(pnl_list), 2),
        }

    return {
        "total_trades": total,
        "wins": win_count,
        "losses": loss_count,
        "breakevens": be_count,
        "timeout_wins": tw_count,
        "timeout_losses": tl_count,
        "win_rate": round(win_rate, 1),
        "adjusted_win_rate": round(adjusted_win_rate, 1),
        "avg_pnl_pct": round(avg_pnl, 2),
        "total_pnl_pct": round(total_pnl, 2),
        "avg_win_pnl": round(avg_win_pnl, 2),
        "avg_loss_pnl": round(avg_loss_pnl, 2),
        "profit_factor": round(profit_factor, 2),
        "avg_bars_held": round(avg_bars, 1),
        "buy_trades": len(buys),
        "sell_trades": len(sells),
        "buy_win_rate": round(buy_wr, 1),
        "sell_win_rate": round(sell_wr, 1),
        "by_setup": setup_metrics,
        "by_strength": strength_metrics,
        "by_confidence": conf_metrics,
        "by_phase": phase_metrics,
        "by_regime": regime_metrics,
        "grade": grade,
        "equity": equity_data,
        "train_test": train_test,
    }


def _print_report(m: dict) -> None:
    """Print formatted backtest report."""
    print("\n" + "=" * 60)
    print("   AL BROOKS PRICE ACTION — BACKTEST REPORT")
    print("=" * 60)

    if m.get("total_trades", 0) == 0:
        print("No trades generated.")
        return

    print(f"\n{'OVERALL RESULTS':^60}")
    print("-" * 60)
    print(f"  Total Trades     : {m['total_trades']}")
    print(f"  Wins (target hit): {m['wins']}")
    print(f"  Losses (stop hit): {m['losses']}")
    print(f"  Timeout Win      : {m['timeout_wins']}")
    print(f"  Timeout Loss     : {m['timeout_losses']}")
    print(f"  Win Rate         : {m['win_rate']:.1f}%")
    print(f"  Adjusted Win Rate: {m['adjusted_win_rate']:.1f}% (timeout wins = half credit)")
    print(f"  Profit Factor    : {m['profit_factor']:.2f}")
    print(f"  Avg P&L per Trade: {m['avg_pnl_pct']:+.2f}%")
    print(f"  Avg Win P&L      : {m['avg_win_pnl']:+.2f}%")
    print(f"  Avg Loss P&L     : {m['avg_loss_pnl']:+.2f}%")
    print(f"  Avg Bars Held    : {m['avg_bars_held']:.1f}")
    print(f"  GRADE            : {m['grade']}")

    print(f"\n{'DIRECTION SPLIT':^60}")
    print("-" * 60)
    print(f"  BUY  trades: {m['buy_trades']}  win rate: {m['buy_win_rate']:.1f}%")
    print(f"  SELL trades: {m['sell_trades']}  win rate: {m['sell_win_rate']:.1f}%")

    if m.get("by_setup"):
        print(f"\n{'BY SETUP TYPE':^60}")
        print("-" * 60)
        for stype, data in sorted(m["by_setup"].items(), key=lambda x: -x[1]["win_rate"]):
            print(f"  {stype:20s}  trades: {data['trades']:5d}  "
                  f"WR: {data['win_rate']:5.1f}%  avg P&L: {data['avg_pnl']:+.2f}%")

    if m.get("by_strength"):
        print(f"\n{'BY SIGNAL STRENGTH':^60}")
        print("-" * 60)
        for s, data in m["by_strength"].items():
            print(f"  {s:10s}  trades: {data['trades']:5d}  "
                  f"WR: {data['win_rate']:5.1f}%  avg P&L: {data['avg_pnl']:+.2f}%")

    if m.get("by_confidence"):
        print(f"\n{'BY CONFIDENCE TIER':^60}")
        print("-" * 60)
        for label, data in m["by_confidence"].items():
            print(f"  {label:18s}  trades: {data['trades']:5d}  "
                  f"WR: {data['win_rate']:5.1f}%  avg P&L: {data['avg_pnl']:+.2f}%")

    if m.get("by_phase"):
        print(f"\n{'BY TREND PHASE':^60}")
        print("-" * 60)
        for phase, data in sorted(m["by_phase"].items(), key=lambda x: -x[1]["win_rate"]):
            print(f"  {phase:18s}  trades: {data['trades']:5d}  "
                  f"WR: {data['win_rate']:5.1f}%  avg P&L: {data['avg_pnl']:+.2f}%")

    if m.get("by_regime"):
        print(f"\n{'BY MARKET REGIME':^60}")
        print("-" * 60)
        for regime, data in sorted(m["by_regime"].items(), key=lambda x: -x[1]["trades"]):
            tag = " [FILTERED]" if regime in ("BEAR", "CHOPPY", "TRENDING_BEAR", "MILD_TREND") and REGIME_FILTER else ""
            print(f"  {regime:18s}  trades: {data['trades']:5d}  "
                  f"WR: {data['win_rate']:5.1f}%  avg P&L: {data['avg_pnl']:+.2f}%{tag}")

    meta = m.get("meta", {})
    if meta:
        print(f"\n{'PROCESSING':^60}")
        print("-" * 60)
        print(f"  Stocks processed : {meta.get('stocks_processed', 0)}")
        print(f"  With signals     : {meta.get('stocks_with_signals', 0)}")
        print(f"  Skipped (data)   : {meta.get('stocks_skipped', 0)}")
        print(f"  Errors           : {meta.get('errors', 0)}")
        print(f"  Elapsed          : {meta.get('elapsed_sec', 0):.1f}s")

    # ── Equity curve & drawdown ──
    if m.get("equity"):
        eq = m["equity"]
        print(f"\n{'EQUITY CURVE & RISK':^60}")
        print("-" * 60)
        print(f"  Starting Capital : ₹{eq['start_capital']:,.0f}")
        print(f"  Final Capital    : ₹{eq['final_capital']:,.0f}")
        print(f"  Total Return     : {eq['total_return_pct']:+.1f}%")
        print(f"  CAGR             : {eq['cagr_pct']:.1f}%")
        print(f"  Max Drawdown     : {eq['max_drawdown_pct']:.1f}%")
        print(f"  Max DD Duration  : {eq['max_dd_days']} days")
        print(f"  Sharpe Ratio     : {eq['sharpe']:.2f}")
        print(f"  Calmar Ratio     : {eq['calmar']:.2f}")
        print(f"  Max Positions    : {eq.get('max_positions', 5)}")
        print(f"  Per Position     : ₹{eq.get('per_position', 0):,.0f}")
        print(f"  Risk per Trade   : {RISK_PER_TRADE*100:.0f}%")

        if eq.get("skipped_regime", 0) > 0 or eq.get("dd_reduced_trades", 0) > 0:
            print(f"\n{'SURVIVAL FEATURES':^60}")
            print("-" * 60)
            print(f"  Regime filter    : {'ON' if REGIME_FILTER else 'OFF'}")
            print(f"  DD tolerance     : {'ON' if DD_TOLERANCE else 'OFF'}")
            print(f"  Capital survival : {'ON' if CAPITAL_SURVIVAL else 'OFF'}")
            print(f"  Trades taken     : {eq.get('trades_taken', 0)} of {m['total_trades']}")
            print(f"  Skipped (regime) : {eq.get('skipped_regime', 0)}")
            if eq.get('skipped_bear', 0):
                print(f"    - BEAR         : {eq['skipped_bear']}")
            if eq.get('skipped_choppy', 0):
                print(f"    - CHOPPY       : {eq['skipped_choppy']}")
            if eq.get('skipped_trending_bear', 0):
                print(f"    - TRENDING_BEAR: {eq['skipped_trending_bear']}")
            print(f"  DD-reduced size  : {eq.get('dd_reduced_trades', 0)} trades")

    # ── NSE cost summary ──
    if APPLY_COSTS:
        print(f"\n{'NSE COST MODEL':^60}")
        print("-" * 60)
        print(f"  Round-trip cost  : {RT_COST:.3f}%")
        print(f"  Brokerage        : {BROKERAGE_PCT*2:.3f}% (both sides)")
        print(f"  STT (sell)       : {STT_SELL_PCT:.3f}%")
        print(f"  Stamp duty (buy) : {STAMP_BUY_PCT:.3f}%")
        print(f"  Slippage         : {SLIPPAGE_PCT*2:.3f}% (both sides)")
        total_cost_paid = RT_COST * m.get("total_trades", 0)
        print(f"  Total cost drag  : {total_cost_paid:.1f}% across all trades")

    # ── Train/Test split ──
    if m.get("train_test"):
        tt = m["train_test"]
        print(f"\n{'TRAIN / TEST SPLIT (split: ' + SPLIT_DATE + ')':^60}")
        print("-" * 60)
        for label, d in tt.items():
            prof = (d['wins']+d['timeout_wins'])/d['trades']*100 if d['trades'] else 0
            print(f"  {label.upper():6s}  trades:{d['trades']:6d}  "
                  f"WR:{d['win_rate']:.1f}%  profitable:{prof:.1f}%  "
                  f"PF:{d['profit_factor']:.2f}  avg:{d['avg_pnl']:+.2f}%")

    print("=" * 60)


# ─────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="PA Backtest")
    parser.add_argument("--max", type=int, default=0, help="Max stocks (0=all)")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--nifty50", action="store_true", help="Nifty 50 only")
    args = parser.parse_args()

    run_full_backtest(max_stocks=args.max, verbose=not args.quiet,
                      nifty50=args.nifty50)
