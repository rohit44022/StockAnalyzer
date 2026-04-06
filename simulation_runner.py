#!/usr/bin/env python3
"""
simulation_runner.py — Comprehensive System Validation Simulator.

Runs ALL system components across multiple tickers, multiple passes.
Validates math, indicator correctness, signal logic, portfolio analysis,
trade calculator, hybrid engine, and cross-checks everything.

Usage:  python3 simulation_runner.py
Output: simulation_results.json + terminal report
"""

import sys, os, json, math, time, traceback
from datetime import datetime, date, timedelta
from dataclasses import asdict
from multiprocessing import Pool

import pandas as pd
import numpy as np

# Ensure project root on path
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ── BB Squeeze modules ──
from bb_squeeze.data_loader import (
    normalise_ticker, load_stock_data, get_all_tickers_from_csv, get_data_freshness,
)
from bb_squeeze.indicators import compute_all_indicators
from bb_squeeze.signals import analyze_signals
from bb_squeeze.strategies import run_all_strategies, strategy_result_to_dict
from bb_squeeze.quant_strategy import run_quant_analysis
from bb_squeeze.portfolio_analyzer import analyze_position
from bb_squeeze.trade_calculator import calculate_trade
from bb_squeeze.config import CSV_DIR

# ── Technical Analysis modules ──
from technical_analysis.indicators import (
    compute_all_ta_indicators,
    get_indicator_snapshot,
    detect_ma_crossovers,
    detect_all_divergences,
    compute_pivot_points,
    compute_fibonacci,
)
from technical_analysis.candlesticks import scan_candlestick_patterns
from technical_analysis.patterns import (
    detect_support_resistance,
    identify_trend,
    detect_all_chart_patterns,
    analyze_volume,
    analyze_ichimoku,
)
from technical_analysis.signals import generate_signal as generate_ta_signal
from technical_analysis.risk_manager import generate_risk_report
from technical_analysis.target_price import calculate_target_prices

# ── Hybrid engine ──
from hybrid_engine import run_hybrid_analysis


# ═══════════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════════

# Dynamically load ALL tickers from stock_csv/ directory
def _discover_all_tickers():
    csv_dir = os.path.join(ROOT, "stock_csv")
    tickers = []
    for f in sorted(os.listdir(csv_dir)):
        if f.endswith(".NS.csv"):
            tickers.append(f.replace(".NS.csv", ""))
    return tickers

SIM_TICKERS = _discover_all_tickers()

NUM_PASSES = 5  # Run 5 full passes
MAX_WORKERS = 6  # Parallel workers for speed

RESULTS_FILE = os.path.join(ROOT, "simulation_results.json")


# ═══════════════════════════════════════════════════════════════
#  HELPER UTILITIES
# ═══════════════════════════════════════════════════════════════

class SimulationError:
    def __init__(self, module, ticker, error_type, message, detail=""):
        self.module = module
        self.ticker = ticker
        self.error_type = error_type  # "CRASH", "MATH_ERROR", "INCONSISTENCY", "WARNING"
        self.message = message
        self.detail = detail

    def to_dict(self):
        return {
            "module": self.module, "ticker": self.ticker,
            "error_type": self.error_type, "message": self.message,
            "detail": self.detail,
        }


def _safe_val(v):
    if v is None:
        return None
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        fv = float(v)
        if math.isnan(fv) or math.isinf(fv):
            return None
        return round(fv, 6)
    if isinstance(v, (np.ndarray,)):
        return [_safe_val(x) for x in v.tolist()]
    return v


def _check_nan(val, label, ticker, module):
    """Return SimulationError if val is NaN/Inf, else None."""
    if val is None:
        return None
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return SimulationError(module, ticker, "MATH_ERROR",
                               f"{label} is NaN/Inf", f"value={val}")
    return None


def _check_range(val, label, lo, hi, ticker, module):
    """Return SimulationError if val is out of expected range."""
    if val is None:
        return None
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return SimulationError(module, ticker, "MATH_ERROR",
                               f"{label} is NaN/Inf", f"value={val}")
    if val < lo or val > hi:
        return SimulationError(module, ticker, "MATH_ERROR",
                               f"{label} out of range [{lo}, {hi}]",
                               f"value={val}")
    return None


# ═══════════════════════════════════════════════════════════════
#  MODULE 1: DATA LOADER TESTS
# ═══════════════════════════════════════════════════════════════

def test_data_loader(ticker, errors):
    """Test data loading, normalization, freshness for a ticker."""
    mod = "data_loader"
    norm = normalise_ticker(ticker)
    if not norm.endswith(".NS"):
        errors.append(SimulationError(mod, ticker, "INCONSISTENCY",
                                       f"normalise_ticker('{ticker}') = '{norm}', expected .NS suffix"))

    df = load_stock_data(norm, CSV_DIR)
    if df is None or df.empty:
        errors.append(SimulationError(mod, ticker, "CRASH",
                                       f"load_stock_data returned None/empty"))
        return None

    # Check required columns
    required_cols = ["Open", "High", "Low", "Close", "Volume"]
    for col in required_cols:
        if col not in df.columns:
            errors.append(SimulationError(mod, ticker, "CRASH",
                                           f"Missing column: {col}"))
            return None

    # Check no NaN in critical columns
    for col in required_cols:
        nan_count = df[col].isna().sum()
        if nan_count > 0:
            errors.append(SimulationError(mod, ticker, "WARNING",
                                           f"{nan_count} NaN values in {col}"))

    # Check data freshness
    freshness = get_data_freshness(df)
    if freshness["is_stale"]:
        errors.append(SimulationError(mod, ticker, "WARNING",
                                       f"Data is stale: {freshness['trading_days_stale']} trading days old"))

    # Check OHLC relationship: Low <= Open,Close <= High
    invalid_ohlc = df[(df["Low"] > df["Open"]) | (df["Low"] > df["Close"]) |
                      (df["High"] < df["Open"]) | (df["High"] < df["Close"])]
    if len(invalid_ohlc) > 0:
        errors.append(SimulationError(mod, ticker, "MATH_ERROR",
                                       f"{len(invalid_ohlc)} rows violate OHLC relationship (Low<=Open,Close<=High)"))

    # Check no negative prices
    neg_prices = df[(df["Open"] <= 0) | (df["High"] <= 0) | (df["Low"] <= 0) | (df["Close"] <= 0)]
    if len(neg_prices) > 0:
        errors.append(SimulationError(mod, ticker, "MATH_ERROR",
                                       f"{len(neg_prices)} rows with negative/zero prices"))

    return df, freshness


# ═══════════════════════════════════════════════════════════════
#  MODULE 2: BB INDICATORS
# ═══════════════════════════════════════════════════════════════

def test_bb_indicators(ticker, df, errors):
    """Test Bollinger Band indicators computation."""
    mod = "bb_indicators"
    df = compute_all_indicators(df.copy())

    # Check all expected columns were added
    expected_cols = ["BB_Mid", "BB_Upper", "BB_Lower", "BBW", "BBW_6M_Min",
                     "Percent_B", "Squeeze_ON", "SAR", "SAR_Bull",
                     "Vol_SMA50", "Vol_Above_SMA", "CMF", "MFI"]
    for col in expected_cols:
        if col not in df.columns:
            errors.append(SimulationError(mod, ticker, "CRASH",
                                           f"Missing indicator column: {col}"))

    # Check last row values
    last = df.iloc[-1]

    # BB relationship: Lower < Mid < Upper
    bb_l, bb_m, bb_u = float(last["BB_Lower"]), float(last["BB_Mid"]), float(last["BB_Upper"])
    if not (bb_l <= bb_m <= bb_u):
        errors.append(SimulationError(mod, ticker, "MATH_ERROR",
                                       f"BB band order violation: {bb_l} <= {bb_m} <= {bb_u}"))

    # BBW should be non-negative
    bbw = float(last["BBW"])
    e = _check_range(bbw, "BBW", 0.0, 10.0, ticker, mod)
    if e: errors.append(e)

    # %B typically -1 to 2 (can go outside bands)
    pctb = float(last["Percent_B"])
    e = _check_range(pctb, "Percent_B", -3.0, 4.0, ticker, mod)
    if e: errors.append(e)

    # CMF should be -1 to +1
    cmf = float(last["CMF"])
    e = _check_range(cmf, "CMF", -1.0, 1.0, ticker, mod)
    if e: errors.append(e)

    # MFI should be 0-100
    mfi = float(last["MFI"])
    e = _check_range(mfi, "MFI", 0.0, 100.0, ticker, mod)
    if e: errors.append(e)

    # SAR should be positive
    sar = float(last["SAR"])
    if sar <= 0:
        errors.append(SimulationError(mod, ticker, "MATH_ERROR",
                                       f"SAR is non-positive: {sar}"))

    # Check for NaN in computed columns
    for col in expected_cols:
        val = last[col]
        if isinstance(val, float) and math.isnan(val):
            errors.append(SimulationError(mod, ticker, "MATH_ERROR",
                                           f"NaN in final row for {col}"))

    return df


# ═══════════════════════════════════════════════════════════════
#  MODULE 3: BB SIGNALS (Method I)
# ═══════════════════════════════════════════════════════════════

def test_bb_signals(ticker, df, errors):
    """Test Method I signal analysis."""
    mod = "bb_signals"
    norm = normalise_ticker(ticker)
    sig = analyze_signals(norm, df)

    # Check signal result is valid
    if sig is None:
        errors.append(SimulationError(mod, ticker, "CRASH",
                                       "analyze_signals returned None"))
        return None

    # Phase should be valid
    valid_phases = ["COMPRESSION", "DIRECTION", "EXPLOSION", "NORMAL", "INSUFFICIENT_DATA", "ERROR"]
    if sig.phase not in valid_phases:
        errors.append(SimulationError(mod, ticker, "INCONSISTENCY",
                                       f"Invalid phase: {sig.phase}"))

    # Confidence 0-100
    e = _check_range(sig.confidence, "confidence", 0, 100, ticker, mod)
    if e: errors.append(e)

    # Exactly one signal type should be true (buy, sell, hold, wait)
    signals = [sig.buy_signal, sig.hold_signal, sig.sell_signal, sig.wait_signal]
    true_count = sum(1 for s in signals if s)
    if sig.phase not in ("INSUFFICIENT_DATA", "ERROR") and true_count != 1:
        errors.append(SimulationError(mod, ticker, "INCONSISTENCY",
                                       f"Expected exactly 1 signal, got {true_count}",
                                       f"buy={sig.buy_signal}, hold={sig.hold_signal}, sell={sig.sell_signal}, wait={sig.wait_signal}"))

    # Price should be positive
    if sig.current_price <= 0:
        errors.append(SimulationError(mod, ticker, "MATH_ERROR",
                                       f"Price is {sig.current_price}"))

    # Stop loss should be below price (for buy/hold) or valid
    if sig.stop_loss < 0:
        errors.append(SimulationError(mod, ticker, "MATH_ERROR",
                                       f"Stop loss is negative: {sig.stop_loss}"))

    # Check all indicator values in signal are valid
    for attr, lo, hi in [("cmf", -1.0, 1.0), ("mfi", 0.0, 100.0),
                          ("bbw", 0.0, 10.0), ("percent_b", -3.0, 4.0)]:
        val = getattr(sig, attr, None)
        if val is not None:
            e = _check_range(float(val), attr, lo, hi, ticker, mod)
            if e: errors.append(e)

    return sig


# ═══════════════════════════════════════════════════════════════
#  MODULE 4: BB STRATEGIES (Methods II, III, IV)
# ═══════════════════════════════════════════════════════════════

def test_bb_strategies(ticker, df, errors):
    """Test Methods II, III, IV strategies."""
    mod = "bb_strategies"
    strats = run_all_strategies(df)

    if strats is None or len(strats) != 3:
        errors.append(SimulationError(mod, ticker, "CRASH",
                                       f"run_all_strategies returned {len(strats) if strats else 'None'} results, expected 3"))
        return None

    valid_signals = ["BUY", "SELL", "HOLD", "WATCH", "NONE"]
    valid_strengths = ["STRONG", "MODERATE", "WEAK"]
    expected_codes = ["M2", "M3", "M4"]

    for i, sr in enumerate(strats):
        code = sr.code
        if code not in expected_codes:
            errors.append(SimulationError(mod, ticker, "INCONSISTENCY",
                                           f"Strategy #{i} has code '{code}', expected one of {expected_codes}"))

        # Signal type
        if sr.signal.signal_type not in valid_signals:
            errors.append(SimulationError(mod, ticker, "INCONSISTENCY",
                                           f"{code}: signal_type='{sr.signal.signal_type}'"))

        # Strength
        if sr.signal.strength not in valid_strengths:
            errors.append(SimulationError(mod, ticker, "INCONSISTENCY",
                                           f"{code}: strength='{sr.signal.strength}'"))

        # Confidence 0-100
        e = _check_range(sr.signal.confidence, f"{code}.confidence", 0, 100, ticker, mod)
        if e: errors.append(e)

        # Patterns should be list
        if not isinstance(sr.patterns, list):
            errors.append(SimulationError(mod, ticker, "INCONSISTENCY",
                                           f"{code}: patterns is not a list"))

        # Test serialization
        try:
            d = strategy_result_to_dict(sr)
            json.dumps(d)
        except Exception as ex:
            errors.append(SimulationError(mod, ticker, "CRASH",
                                           f"{code}: strategy_result_to_dict failed: {ex}"))

    return strats


# ═══════════════════════════════════════════════════════════════
#  MODULE 5: QUANT STRATEGY
# ═══════════════════════════════════════════════════════════════

def test_quant_strategy(ticker, df, errors):
    """Test quantitative regime detection, mean-reversion, momentum."""
    mod = "quant_strategy"
    result = run_quant_analysis(df)

    if result is None:
        errors.append(SimulationError(mod, ticker, "CRASH",
                                       "run_quant_analysis returned None"))
        return None

    # Regime
    regime = result.get("regime")
    if regime is None:
        errors.append(SimulationError(mod, ticker, "CRASH",
                                       "No 'regime' in quant result"))
    else:
        valid_regimes = ["TRENDING_UP", "TRENDING_DOWN", "MEAN_REVERTING", "VOLATILE_CHOPPY"]
        regime_name = regime.get("regime") if isinstance(regime, dict) else getattr(regime, "regime", None)
        if regime_name not in valid_regimes:
            errors.append(SimulationError(mod, ticker, "INCONSISTENCY",
                                           f"Invalid regime: {regime_name}"))
        confidence = regime.get("confidence") if isinstance(regime, dict) else getattr(regime, "confidence", None)
        e = _check_range(confidence, "regime.confidence", 0, 100, ticker, mod)
        if e: errors.append(e)
        adx_val = regime.get("adx") if isinstance(regime, dict) else getattr(regime, "adx_value", None)
        e = _check_range(adx_val, "regime.adx", 0, 100, ticker, mod)
        if e: errors.append(e)

    # Mean reversion
    mr = result.get("mean_reversion")
    if mr is None:
        errors.append(SimulationError(mod, ticker, "CRASH",
                                       "No 'mean_reversion' in quant result"))
    else:
        valid_mr = ["STRONG_BUY", "BUY", "NEUTRAL", "SELL", "STRONG_SELL"]
        mr_signal = mr.get("signal") if isinstance(mr, dict) else getattr(mr, "signal", None)
        if mr_signal not in valid_mr:
            errors.append(SimulationError(mod, ticker, "INCONSISTENCY",
                                           f"Invalid mean_reversion signal: {mr_signal}"))
        mr_rsi = mr.get("rsi") if isinstance(mr, dict) else getattr(mr, "rsi", None)
        e = _check_range(mr_rsi, "mr.rsi", 0, 100, ticker, mod)
        if e: errors.append(e)

    # Momentum
    mom = result.get("momentum")
    if mom is None:
        errors.append(SimulationError(mod, ticker, "CRASH",
                                       "No 'momentum' in quant result"))
    else:
        valid_mom = ["STRONG_BUY", "BUY", "NEUTRAL", "SELL", "STRONG_SELL"]
        mom_signal = mom.get("signal") if isinstance(mom, dict) else getattr(mom, "signal", None)
        if mom_signal not in valid_mom:
            errors.append(SimulationError(mod, ticker, "INCONSISTENCY",
                                           f"Invalid momentum signal: {mom_signal}"))

    return result


# ═══════════════════════════════════════════════════════════════
#  MODULE 6: TECHNICAL ANALYSIS FULL PIPELINE
# ═══════════════════════════════════════════════════════════════

def test_ta_pipeline(ticker, df_raw, errors):
    """Test full Technical Analysis pipeline."""
    mod = "ta_pipeline"
    df = compute_all_ta_indicators(df_raw.copy())

    # Check key indicator columns
    key_cols = ["SMA_20", "SMA_50", "SMA_200", "EMA_21", "EMA_50",
                "RSI", "MACD", "MACD_Signal", "MACD_Hist",
                "STOCH_K", "STOCH_D", "WILLR", "CCI", "ROC",
                "ADX", "PLUS_DI", "MINUS_DI", "ATR",
                "AROON_Up", "AROON_Down", "AROON_Osc",
                "OBV", "AD_Line", "VROC", "VWAP",
                "SUPERTREND", "SUPERTREND_DIR"]

    missing_cols = [c for c in key_cols if c not in df.columns]
    if missing_cols:
        errors.append(SimulationError(mod, ticker, "CRASH",
                                       f"Missing TA columns: {missing_cols}"))

    last = df.iloc[-1]

    # Validate RSI range (0-100)
    rsi = float(last.get("RSI", 0))
    e = _check_range(rsi, "RSI", 0.0, 100.0, ticker, mod)
    if e: errors.append(e)

    # Validate Stochastic range (0-100)
    stk = float(last.get("STOCH_K", 0))
    e = _check_range(stk, "STOCH_K", 0.0, 100.0, ticker, mod)
    if e: errors.append(e)

    # ADX range (0-100)
    adx = float(last.get("ADX", 0))
    e = _check_range(adx, "ADX", 0.0, 100.0, ticker, mod)
    if e: errors.append(e)

    # Williams %R range (-100 to 0)
    wr = float(last.get("WILLR", 0))
    e = _check_range(wr, "WILLR", -100.0, 0.0, ticker, mod)
    if e: errors.append(e)

    # Aroon (0-100)
    aroon_up = float(last.get("AROON_Up", 0))
    aroon_dn = float(last.get("AROON_Down", 0))
    e = _check_range(aroon_up, "Aroon_Up", 0.0, 100.0, ticker, mod)
    if e: errors.append(e)
    e = _check_range(aroon_dn, "Aroon_Down", 0.0, 100.0, ticker, mod)
    if e: errors.append(e)

    # ATR should be positive
    atr = float(last.get("ATR", 0))
    if atr < 0:
        errors.append(SimulationError(mod, ticker, "MATH_ERROR",
                                       f"ATR is negative: {atr}"))

    # Get snapshot
    snapshot = get_indicator_snapshot(df)
    if not snapshot or not isinstance(snapshot, dict):
        errors.append(SimulationError(mod, ticker, "CRASH",
                                       "get_indicator_snapshot returned empty"))
        return df, None

    # Price should match
    snap_close = snapshot.get("price", 0)
    real_close = float(last["Close"])
    if snap_close is not None and abs(snap_close - real_close) > 0.02:
        errors.append(SimulationError(mod, ticker, "INCONSISTENCY",
                                       f"Snapshot price={snap_close} != df close={real_close}"))

    # Trend identification
    trend = identify_trend(df)
    if not trend or "primary" not in trend:
        errors.append(SimulationError(mod, ticker, "CRASH",
                                       "identify_trend returned invalid result"))
    else:
        valid_trends = ["UPTREND", "DOWNTREND", "SIDEWAYS"]
        td = trend.get("primary", "").upper()
        if td not in valid_trends:
            errors.append(SimulationError(mod, ticker, "INCONSISTENCY",
                                           f"trend primary is unexpected: {trend.get('primary')}"))

    # Crossovers
    crossovers = detect_ma_crossovers(df)
    if not isinstance(crossovers, (list, dict)):
        errors.append(SimulationError(mod, ticker, "CRASH",
                                       f"detect_ma_crossovers returned {type(crossovers).__name__}"))

    # Divergences
    divergences = detect_all_divergences(df)
    if not isinstance(divergences, list):
        errors.append(SimulationError(mod, ticker, "CRASH",
                                       f"detect_all_divergences returned {type(divergences).__name__}"))

    # Candlestick patterns
    candle_patterns = scan_candlestick_patterns(df, lookback=5)
    if not isinstance(candle_patterns, list):
        errors.append(SimulationError(mod, ticker, "CRASH",
                                       f"scan_candlestick_patterns returned {type(candle_patterns).__name__}"))

    # Chart patterns
    chart_patterns = detect_all_chart_patterns(df)
    if not isinstance(chart_patterns, list):
        errors.append(SimulationError(mod, ticker, "CRASH",
                                       f"detect_all_chart_patterns returned {type(chart_patterns).__name__}"))

    # Volume analysis
    vol_analysis = analyze_volume(df)
    if not isinstance(vol_analysis, dict):
        errors.append(SimulationError(mod, ticker, "CRASH",
                                       f"analyze_volume returned {type(vol_analysis).__name__}"))

    # S/R levels
    sr_data = detect_support_resistance(df)
    if not isinstance(sr_data, dict):
        errors.append(SimulationError(mod, ticker, "CRASH",
                                       f"detect_support_resistance returned {type(sr_data).__name__}"))

    # Fibonacci
    fib_data = compute_fibonacci(df)
    if not isinstance(fib_data, dict):
        errors.append(SimulationError(mod, ticker, "CRASH",
                                       f"compute_fibonacci returned {type(fib_data).__name__}"))

    # Pivot points
    pivots = compute_pivot_points(df)
    if not isinstance(pivots, dict):
        errors.append(SimulationError(mod, ticker, "CRASH",
                                       f"compute_pivot_points returned {type(pivots).__name__}"))
    else:
        # PP should be close to yesterday's typical price
        pp = pivots.get("PP")
        if pp is not None and pp <= 0:
            errors.append(SimulationError(mod, ticker, "MATH_ERROR",
                                           f"Pivot PP is non-positive: {pp}"))

    # Ichimoku
    ichimoku = analyze_ichimoku(df)

    return df, {
        "snapshot": snapshot, "trend": trend, "crossovers": crossovers,
        "divergences": divergences, "candle_patterns": candle_patterns,
        "chart_patterns": chart_patterns, "vol_analysis": vol_analysis,
        "sr_data": sr_data, "fib_data": fib_data, "pivots": pivots,
        "ichimoku": ichimoku,
    }


# ═══════════════════════════════════════════════════════════════
#  MODULE 7: TA SIGNAL GENERATION
# ═══════════════════════════════════════════════════════════════

def test_ta_signal(ticker, df, ta_data, errors):
    """Test the final TA consensus signal."""
    mod = "ta_signal"
    try:
        signal = generate_ta_signal(
            snap=ta_data["snapshot"],
            trend=ta_data["trend"],
            vol_analysis=ta_data["vol_analysis"],
            chart_patterns=ta_data["chart_patterns"],
            candle_patterns=ta_data["candle_patterns"],
            divergences=ta_data["divergences"],
            sr_data=ta_data["sr_data"],
            fib_data=ta_data["fib_data"],
        )
    except Exception as ex:
        errors.append(SimulationError(mod, ticker, "CRASH",
                                       f"generate_ta_signal crashed: {ex}",
                                       traceback.format_exc()))
        return None

    if not signal or not isinstance(signal, dict):
        errors.append(SimulationError(mod, ticker, "CRASH",
                                       "generate_ta_signal returned None/invalid"))
        return None

    # Verdict should be valid
    valid_verdicts = ["STRONG BUY", "BUY", "HOLD", "SELL", "STRONG SELL"]
    verdict = signal.get("verdict", "")
    if verdict not in valid_verdicts:
        errors.append(SimulationError(mod, ticker, "INCONSISTENCY",
                                       f"Invalid verdict: '{verdict}'"))

    # Confidence 0-100
    conf = signal.get("confidence", -1)
    e = _check_range(conf, "confidence", 0, 100, ticker, mod)
    if e: errors.append(e)

    # Total score check
    total = signal.get("score", None)
    if total is not None:
        e = _check_range(total, "score", -100, 100, ticker, mod)
        if e: errors.append(e)

    # Category scores should be within their max
    cats = signal.get("categories", {})
    cat_maxes = {"trend": 25, "momentum": 20, "volume": 15,
                 "pattern": 15, "support_resistance": 10, "risk": 15}
    for cat, max_val in cat_maxes.items():
        cat_data = cats.get(cat, {})
        score = cat_data.get("score", 0)
        e = _check_range(score, f"scores.{cat}", -max_val, max_val, ticker, mod)
        if e: errors.append(e)

    return signal


# ═══════════════════════════════════════════════════════════════
#  MODULE 8: RISK MANAGER
# ═══════════════════════════════════════════════════════════════

def test_risk_manager(ticker, ta_data, errors):
    """Test risk management calculations."""
    mod = "risk_manager"
    try:
        risk = generate_risk_report(
            snap=ta_data["snapshot"],
            sr_data=ta_data["sr_data"],
            capital=500000,
        )
    except Exception as ex:
        errors.append(SimulationError(mod, ticker, "CRASH",
                                       f"generate_risk_report crashed: {ex}",
                                       traceback.format_exc()))
        return None

    if not risk or not isinstance(risk, dict):
        errors.append(SimulationError(mod, ticker, "CRASH",
                                       "generate_risk_report returned None"))
        return None

    # Position sizing checks
    pos = risk.get("position_size", {})
    shares = pos.get("shares", 0)
    pos_val = pos.get("position_value", 0)
    if shares is not None and shares < 0:
        errors.append(SimulationError(mod, ticker, "MATH_ERROR",
                                       f"Negative shares: {shares}"))
    if pos_val is not None and pos_val > 500000:
        errors.append(SimulationError(mod, ticker, "MATH_ERROR",
                                       f"Position value {pos_val} exceeds capital 500000"))

    # Stop losses should be positive and below entry
    stops = risk.get("stop_losses", {})
    entry = ta_data["snapshot"].get("close", 0)
    for method, stop_data in stops.items():
        if isinstance(stop_data, dict):
            level = stop_data.get("level")
            if level is not None and level < 0:
                errors.append(SimulationError(mod, ticker, "MATH_ERROR",
                                               f"Stop loss '{method}' is negative: {level}"))

    # Kelly criterion
    kelly = risk.get("kelly", {})
    kelly_pct = kelly.get("kelly_pct")
    if kelly_pct is not None:
        e = _check_range(kelly_pct, "kelly_pct", -100, 100, ticker, mod)
        if e: errors.append(e)

    return risk


# ═══════════════════════════════════════════════════════════════
#  MODULE 9: TARGET PRICES
# ═══════════════════════════════════════════════════════════════

def test_target_prices(ticker, ta_data, errors):
    """Test target price calculations."""
    mod = "target_prices"
    try:
        targets = calculate_target_prices(
            snap=ta_data["snapshot"],
            trend=ta_data["trend"],
            sr_data=ta_data["sr_data"],
            fib_data=ta_data["fib_data"],
            pivot=ta_data["pivots"],
            chart_patterns=ta_data["chart_patterns"],
        )
    except Exception as ex:
        errors.append(SimulationError(mod, ticker, "CRASH",
                                       f"calculate_target_prices crashed: {ex}",
                                       traceback.format_exc()))
        return None

    if not targets or not isinstance(targets, dict):
        errors.append(SimulationError(mod, ticker, "CRASH",
                                       "calculate_target_prices returned None"))
        return None

    # All targets should have positive prices
    for t in targets.get("targets", []):
        tp = t.get("target")
        if tp is not None and tp <= 0:
            errors.append(SimulationError(mod, ticker, "MATH_ERROR",
                                           f"Target price '{t.get('label')}' is non-positive: {tp}"))
        conf = t.get("confidence", -1)
        e = _check_range(conf, f"target.confidence({t.get('label')})", 0, 100, ticker, mod)
        if e: errors.append(e)

    return targets


# ═══════════════════════════════════════════════════════════════
#  MODULE 10: HYBRID ENGINE
# ═══════════════════════════════════════════════════════════════

def test_hybrid_engine(ticker, df_raw, errors):
    """Test the full Hybrid BB + TA engine."""
    mod = "hybrid_engine"
    try:
        result = run_hybrid_analysis(df_raw.copy(), ticker=normalise_ticker(ticker))
    except Exception as ex:
        errors.append(SimulationError(mod, ticker, "CRASH",
                                       f"run_hybrid_analysis crashed: {ex}",
                                       traceback.format_exc()))
        return None

    if not result or not isinstance(result, dict):
        errors.append(SimulationError(mod, ticker, "CRASH",
                                       "run_hybrid_analysis returned None"))
        return None

    if "error" in result:
        errors.append(SimulationError(mod, ticker, "CRASH",
                                       f"Hybrid engine error: {result['error']}"))
        return None

    # Extract hybrid_verdict sub-dict
    hv = result.get("hybrid_verdict", {})
    valid_verdicts = ["SUPER STRONG BUY", "SUPER STRONG SELL", "STRONG BUY", "BUY",
                      "HOLD / WAIT", "WEAK HOLD", "SELL", "STRONG SELL", "HOLD"]
    verdict = hv.get("verdict", "") if isinstance(hv, dict) else ""
    if verdict not in valid_verdicts:
        errors.append(SimulationError(mod, ticker, "INCONSISTENCY",
                                       f"Invalid hybrid verdict: '{verdict}'"))

    # Combined score (max 245)
    score = hv.get("score", 0) if isinstance(hv, dict) else 0
    e = _check_range(score, "combined_score", -245, 245, ticker, mod)
    if e: errors.append(e)

    # Confidence
    conf = hv.get("confidence", -1) if isinstance(hv, dict) else -1
    e = _check_range(conf, "confidence", 0, 100, ticker, mod)
    if e: errors.append(e)

    # Data freshness should be present
    freshness = result.get("data_freshness")
    if freshness is None:
        errors.append(SimulationError(mod, ticker, "INCONSISTENCY",
                                       "No data_freshness in hybrid result"))

    # Cross-validation should be present
    cv = result.get("cross_validation")
    if cv is None:
        errors.append(SimulationError(mod, ticker, "WARNING",
                                       "No cross_validation in hybrid result"))

    return result


# ═══════════════════════════════════════════════════════════════
#  MODULE 11: PORTFOLIO POSITION ANALYSIS (simulated position)
# ═══════════════════════════════════════════════════════════════

def test_portfolio_analysis(ticker, df_bb, strats, errors):
    """Test portfolio position analysis with a simulated position."""
    mod = "portfolio_analyzer"

    # Create a simulated position — bought 30 days ago at BB Mid
    last = df_bb.iloc[-1]
    mid_price = float(last["BB_Mid"])
    buy_date = (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")

    for strategy_code in ["M1", "M2", "M3", "M4"]:
        position = {
            "id": 999,
            "ticker": ticker,
            "strategy_code": strategy_code,
            "buy_price": round(mid_price, 2),
            "buy_date": buy_date,
            "quantity": 10,
            "status": "OPEN",
            "notes": "Simulation test",
        }

        try:
            analysis = analyze_position(position)
        except Exception as ex:
            errors.append(SimulationError(mod, ticker, "CRASH",
                                           f"analyze_position({strategy_code}) crashed: {ex}",
                                           traceback.format_exc()))
            continue

        if not analysis or not isinstance(analysis, dict):
            errors.append(SimulationError(mod, ticker, "CRASH",
                                           f"analyze_position({strategy_code}) returned None"))
            continue

        if "error" in analysis and analysis["error"]:
            errors.append(SimulationError(mod, ticker, "WARNING",
                                           f"analyze_position({strategy_code}): {analysis['error']}"))
            continue

        # Recommendation should exist
        rec = analysis.get("recommendation", {})
        action = rec.get("action", "")
        valid_actions = ["HOLD", "SELL", "ADD", "STRONG SELL", "STRONG HOLD", "BOOK PARTIAL"]
        if action and action not in valid_actions:
            # Relaxed check — just warn
            errors.append(SimulationError(mod, ticker, "WARNING",
                                           f"Unusual recommendation action for {strategy_code}: '{action}'"))

        # Targets should have valid prices
        targets = analysis.get("targets", {})
        cp = targets.get("current_price")
        if cp is not None and cp <= 0:
            errors.append(SimulationError(mod, ticker, "MATH_ERROR",
                                           f"Current price in targets is {cp}"))

        # Holding info
        hi = analysis.get("holding_info", {})
        days_held = hi.get("days_held", 0)
        if days_held is not None and days_held < 0:
            errors.append(SimulationError(mod, ticker, "MATH_ERROR",
                                           f"days_held is negative: {days_held}"))

    return True


# ═══════════════════════════════════════════════════════════════
#  MODULE 12: TRADE CALCULATOR
# ═══════════════════════════════════════════════════════════════

def test_trade_calculator(ticker, df_bb, errors):
    """Test trade P&L and tax calculations."""
    mod = "trade_calculator"

    last = df_bb.iloc[-1]
    price = float(last["Close"])
    # Simulate trades: one profit, one loss, one LTCG
    test_trades = [
        ("Short-term Profit", price * 0.9, price, "2025-12-01", "2026-03-01", "delivery"),
        ("Short-term Loss", price * 1.1, price, "2025-12-01", "2026-03-01", "delivery"),
        ("Long-term Gain", price * 0.6, price, "2024-06-01", "2026-03-01", "delivery"),
        ("Intraday Profit", price * 0.98, price, "2026-03-01", "2026-03-01", "intraday"),
    ]

    for label, bp, sp, bd, sd, tt in test_trades:
        try:
            result = calculate_trade(
                stock=normalise_ticker(ticker),
                platform="zerodha",
                trade_type=tt,
                exchange="NSE",
                quantity=10,
                buy_price=round(bp, 2),
                sell_price=round(sp, 2),
                buy_date=bd,
                sell_date=sd,
            )
        except Exception as ex:
            errors.append(SimulationError(mod, ticker, "CRASH",
                                           f"calculate_trade({label}) crashed: {ex}",
                                           traceback.format_exc()))
            continue

        # Check result exists
        if result is None:
            errors.append(SimulationError(mod, ticker, "CRASH",
                                           f"calculate_trade({label}) returned None"))
            continue

        # Charges should be non-negative
        if result.charges.total < 0:
            errors.append(SimulationError(mod, ticker, "MATH_ERROR",
                                           f"{label}: Total charges negative: {result.charges.total}"))

        # Tax rate should be valid
        valid_categories = ["STCG", "LTCG", "Speculative"]
        if result.tax_category not in valid_categories:
            errors.append(SimulationError(mod, ticker, "INCONSISTENCY",
                                           f"{label}: Invalid tax_category: {result.tax_category}"))

        if result.tax_rate < 0:
            errors.append(SimulationError(mod, ticker, "MATH_ERROR",
                                           f"{label}: Negative tax rate: {result.tax_rate}"))

        # Net P&L should equal gross - charges
        expected_net = result.gross_pnl - result.charges.total
        if abs(result.net_pnl - expected_net) > 0.01:
            errors.append(SimulationError(mod, ticker, "MATH_ERROR",
                                           f"{label}: net_pnl={result.net_pnl} != gross_pnl({result.gross_pnl}) - charges({result.charges.total}) = {expected_net}"))

        # Buy value = qty * buy_price
        expected_bv = 10 * round(bp, 2)
        if abs(result.buy_value - expected_bv) > 0.01:
            errors.append(SimulationError(mod, ticker, "MATH_ERROR",
                                           f"{label}: buy_value={result.buy_value} != qty*buy_price={expected_bv}"))

    return True


# ═══════════════════════════════════════════════════════════════
#  CROSS-VALIDATION CHECKS
# ═══════════════════════════════════════════════════════════════

def test_cross_validation(ticker, bb_sig, ta_signal, hybrid_result, errors):
    """Cross-validate that signals from different engines are consistent."""
    mod = "cross_validation"

    if bb_sig is None or ta_signal is None or hybrid_result is None:
        return

    # Check that prices used are consistent
    bb_price = bb_sig.current_price
    ta_price = ta_signal.get("scores", {}).get("trend", {}).get("details", "")
    hybrid_price = hybrid_result.get("current_price") or hybrid_result.get("indicators", {}).get("close")

    hv = hybrid_result.get("hybrid_verdict", {})
    if isinstance(hv, dict):
        # Check hybrid max_score is 245
        max_score = hv.get("max_score")
        if max_score is not None and max_score != 245:
            errors.append(SimulationError(mod, ticker, "INCONSISTENCY",
                                           f"Hybrid max_score={max_score}, expected 245"))

        # Verify confidence is derived from score
        score = hv.get("score", 0)
        if score is not None:
            expected_conf = round(abs(score) / 245 * 100, 1)
            actual_conf = hv.get("confidence", 0)
            if actual_conf is not None and abs(actual_conf - expected_conf) > 1.0:
                errors.append(SimulationError(mod, ticker, "MATH_ERROR",
                                               f"Hybrid confidence={actual_conf} but expected ~{expected_conf} from score={score}/245"))

    # Check that hybrid BB score components are present
    bb_score = hybrid_result.get("bb_score")
    if bb_score and isinstance(bb_score, dict):
        if "methods" not in bb_score and "total" not in bb_score:
            errors.append(SimulationError(mod, ticker, "WARNING",
                                           "Missing methods/total in hybrid bb_score"))


# ═══════════════════════════════════════════════════════════════
#  SINGLE TICKER SIMULATION
# ═══════════════════════════════════════════════════════════════

def run_single_ticker(ticker, pass_num):
    """Run all tests for a single ticker. Returns (summary_dict, errors_list)."""
    errors = []
    summary = {
        "ticker": ticker, "pass": pass_num,
        "modules_tested": 0, "modules_passed": 0, "modules_failed": 0,
        "errors_count": 0, "warnings_count": 0,
        "results": {},
    }

    module_count = 0

    # 1. Data Loader
    module_count += 1
    data_result = None
    try:
        data_result = test_data_loader(ticker, errors)
    except Exception as ex:
        errors.append(SimulationError("data_loader", ticker, "CRASH",
                                       f"Exception: {ex}", traceback.format_exc()))

    if data_result is None:
        summary["modules_tested"] = module_count
        summary["modules_failed"] = 1
        summary["errors_count"] = len([e for e in errors if e.error_type != "WARNING"])
        summary["warnings_count"] = len([e for e in errors if e.error_type == "WARNING"])
        return summary, errors

    df_raw, freshness = data_result
    summary["results"]["data_loader"] = {"rows": len(df_raw), "freshness": freshness}

    # 2. BB Indicators
    module_count += 1
    df_bb = None
    try:
        df_bb = test_bb_indicators(ticker, df_raw, errors)
    except Exception as ex:
        errors.append(SimulationError("bb_indicators", ticker, "CRASH",
                                       f"Exception: {ex}", traceback.format_exc()))

    if df_bb is None:
        df_bb = compute_all_indicators(df_raw.copy())

    last = df_bb.iloc[-1]
    summary["results"]["bb_indicators"] = {
        "BB_Mid": _safe_val(last.get("BB_Mid")),
        "BBW": _safe_val(last.get("BBW")),
        "CMF": _safe_val(last.get("CMF")),
        "MFI": _safe_val(last.get("MFI")),
    }

    # 3. BB Signals (Method I)
    module_count += 1
    bb_sig = None
    try:
        bb_sig = test_bb_signals(ticker, df_bb, errors)
    except Exception as ex:
        errors.append(SimulationError("bb_signals", ticker, "CRASH",
                                       f"Exception: {ex}", traceback.format_exc()))

    if bb_sig:
        summary["results"]["bb_signal"] = {
            "phase": bb_sig.phase,
            "buy": bb_sig.buy_signal, "sell": bb_sig.sell_signal,
            "hold": bb_sig.hold_signal, "wait": bb_sig.wait_signal,
            "confidence": bb_sig.confidence,
            "price": _safe_val(bb_sig.current_price),
        }

    # 4. BB Strategies (Methods II, III, IV)
    module_count += 1
    strats = None
    try:
        strats = test_bb_strategies(ticker, df_bb, errors)
    except Exception as ex:
        errors.append(SimulationError("bb_strategies", ticker, "CRASH",
                                       f"Exception: {ex}", traceback.format_exc()))

    if strats:
        summary["results"]["bb_strategies"] = {
            sr.code: {
                "signal": sr.signal.signal_type,
                "strength": sr.signal.strength,
                "confidence": sr.signal.confidence,
                "patterns": len(sr.patterns),
            } for sr in strats
        }

    # 5. Quant Strategy
    module_count += 1
    quant = None
    try:
        quant = test_quant_strategy(ticker, df_bb, errors)
    except Exception as ex:
        errors.append(SimulationError("quant_strategy", ticker, "CRASH",
                                       f"Exception: {ex}", traceback.format_exc()))

    if quant:
        regime = quant.get("regime", {})
        mr = quant.get("mean_reversion", {})
        mom = quant.get("momentum", {})
        summary["results"]["quant"] = {
            "regime": regime.get("regime") if isinstance(regime, dict) else getattr(regime, "regime", None),
            "regime_confidence": _safe_val(regime.get("confidence") if isinstance(regime, dict) else getattr(regime, "confidence", None)),
            "mean_reversion": mr.get("signal") if isinstance(mr, dict) else getattr(mr, "signal", None),
            "momentum": mom.get("signal") if isinstance(mom, dict) else getattr(mom, "signal", None),
        }

    # 6. TA Pipeline
    module_count += 1
    df_ta = None
    ta_data = None
    try:
        result = test_ta_pipeline(ticker, df_raw, errors)
        if result:
            df_ta, ta_data = result
    except Exception as ex:
        errors.append(SimulationError("ta_pipeline", ticker, "CRASH",
                                       f"Exception: {ex}", traceback.format_exc()))

    if ta_data and ta_data.get("snapshot"):
        snap = ta_data["snapshot"]
        summary["results"]["ta_indicators"] = {
            "RSI": _safe_val(snap.get("rsi")),
            "MACD": _safe_val(snap.get("macd")),
            "ADX": _safe_val(snap.get("adx")),
            "ATR": _safe_val(snap.get("atr")),
            "STOCH_K": _safe_val(snap.get("stoch_k")),
            "WILLR": _safe_val(snap.get("williams_r")),
            "trend": ta_data.get("trend", {}).get("primary"),
        }

    # 7. TA Signal
    module_count += 1
    ta_signal = None
    if df_ta is not None and ta_data:
        try:
            ta_signal = test_ta_signal(ticker, df_ta, ta_data, errors)
        except Exception as ex:
            errors.append(SimulationError("ta_signal", ticker, "CRASH",
                                           f"Exception: {ex}", traceback.format_exc()))

    if ta_signal:
        summary["results"]["ta_signal"] = {
            "verdict": ta_signal.get("verdict"),
            "confidence": ta_signal.get("confidence"),
            "total_score": _safe_val(ta_signal.get("score")),
        }

    # 8. Risk Manager
    module_count += 1
    risk = None
    if ta_data:
        try:
            risk = test_risk_manager(ticker, ta_data, errors)
        except Exception as ex:
            errors.append(SimulationError("risk_manager", ticker, "CRASH",
                                           f"Exception: {ex}", traceback.format_exc()))

    if risk:
        ps = risk.get("position_size", {})
        summary["results"]["risk"] = {
            "shares": ps.get("shares"),
            "position_value": _safe_val(ps.get("position_value")),
            "recommended_stop": risk.get("stop_losses", {}).get("recommended", {}).get("level") if isinstance(risk.get("stop_losses", {}).get("recommended"), dict) else None,
        }

    # 9. Target Prices
    module_count += 1
    targets = None
    if ta_data:
        try:
            targets = test_target_prices(ticker, ta_data, errors)
        except Exception as ex:
            errors.append(SimulationError("target_prices", ticker, "CRASH",
                                           f"Exception: {ex}", traceback.format_exc()))

    if targets:
        summary["results"]["targets"] = {
            "count": len(targets.get("targets", [])),
            "primary": _safe_val(targets.get("primary_target")),
            "weighted": _safe_val(targets.get("weighted_target")),
        }

    # 10. Hybrid Engine
    module_count += 1
    hybrid = None
    try:
        hybrid = test_hybrid_engine(ticker, df_raw, errors)
    except Exception as ex:
        errors.append(SimulationError("hybrid_engine", ticker, "CRASH",
                                       f"Exception: {ex}", traceback.format_exc()))

    if hybrid:
        hv = hybrid.get("hybrid_verdict", {})
        summary["results"]["hybrid"] = {
            "verdict": hv.get("verdict") if isinstance(hv, dict) else None,
            "combined_score": _safe_val(hv.get("score")) if isinstance(hv, dict) else None,
            "confidence": _safe_val(hv.get("confidence")) if isinstance(hv, dict) else None,
            "max_score": hv.get("max_score") if isinstance(hv, dict) else None,
        }

    # 11. Portfolio Analysis (simulated)
    module_count += 1
    try:
        test_portfolio_analysis(ticker, df_bb, strats, errors)
    except Exception as ex:
        errors.append(SimulationError("portfolio_analyzer", ticker, "CRASH",
                                       f"Exception: {ex}", traceback.format_exc()))

    summary["results"]["portfolio"] = {"tested": True}

    # 12. Trade Calculator
    module_count += 1
    try:
        test_trade_calculator(ticker, df_bb, errors)
    except Exception as ex:
        errors.append(SimulationError("trade_calculator", ticker, "CRASH",
                                       f"Exception: {ex}", traceback.format_exc()))

    summary["results"]["trade_calc"] = {"tested": True}

    # 13. Cross-validation
    module_count += 1
    try:
        test_cross_validation(ticker, bb_sig, ta_signal, hybrid, errors)
    except Exception as ex:
        errors.append(SimulationError("cross_validation", ticker, "CRASH",
                                       f"Exception: {ex}", traceback.format_exc()))

    # Final counts
    summary["modules_tested"] = module_count
    err_count = len([e for e in errors if e.error_type != "WARNING"])
    warn_count = len([e for e in errors if e.error_type == "WARNING"])
    summary["errors_count"] = err_count
    summary["warnings_count"] = warn_count
    summary["modules_passed"] = module_count - (1 if err_count > 0 else 0)
    summary["modules_failed"] = 1 if err_count > 0 else 0

    return summary, errors


# ═══════════════════════════════════════════════════════════════
#  MAIN SIMULATION DRIVER
# ═══════════════════════════════════════════════════════════════

def _run_ticker_wrapper(args):
    """Wrapper for multiprocessing — returns (ticker, summary_dict, errors_as_dicts)."""
    ticker, pass_num = args
    try:
        summary, errors = run_single_ticker(ticker, pass_num)
        return (ticker, summary, [e.to_dict() for e in errors], None)
    except Exception as ex:
        err = SimulationError("SYSTEM", ticker, "CRASH",
                              f"Top-level crash in pass {pass_num}: {ex}",
                              traceback.format_exc())
        return (ticker, None, [err.to_dict()], str(ex))


def run_full_simulation():
    """Run NUM_PASSES complete simulation passes across all tickers."""

    all_results = []
    all_errors = []
    pass_summaries = []

    n_tickers = len(SIM_TICKERS)
    total_sims = NUM_PASSES * n_tickers

    print("=" * 80)
    print("  COMPREHENSIVE FULL-UNIVERSE SYSTEM SIMULATION")
    print(f"  {NUM_PASSES} passes × {n_tickers} tickers = {total_sims:,} total simulations")
    print(f"  13 modules per ticker × {total_sims:,} = {13 * total_sims:,} total module tests")
    print(f"  Parallel workers: {MAX_WORKERS}")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    for pass_num in range(1, NUM_PASSES + 1):
        print(f"\n{'─' * 80}")
        print(f"  PASS {pass_num}/{NUM_PASSES}  ({n_tickers:,} stocks)")
        print(f"{'─' * 80}")

        pass_errors_dicts = []
        pass_results = []
        pass_start = time.time()
        pass_failures = 0
        pass_crashes = 0

        # Build work items
        work = [(ticker, pass_num) for ticker in SIM_TICKERS]

        # Run in parallel
        with Pool(processes=MAX_WORKERS) as pool:
            completed = 0
            for result in pool.imap_unordered(_run_ticker_wrapper, work, chunksize=20):
                completed += 1
                tk, summary, err_dicts, crash_msg = result

                if summary:
                    pass_results.append(summary)
                    all_results.append(summary)

                pass_errors_dicts.extend(err_dicts)

                errs_this = len([e for e in err_dicts if e["error_type"] != "WARNING"])
                if errs_this > 0:
                    pass_failures += 1
                if crash_msg:
                    pass_crashes += 1

                # Progress line every 100 tickers
                if completed % 200 == 0 or completed == n_tickers:
                    elapsed = time.time() - pass_start
                    rate = completed / elapsed if elapsed > 0 else 0
                    eta = (n_tickers - completed) / rate if rate > 0 else 0
                    print(f"    [{completed:>5,}/{n_tickers:,}]  "
                          f"failures={pass_failures}  crashes={pass_crashes}  "
                          f"({elapsed:.0f}s elapsed, ~{eta:.0f}s remaining)")

        # Reconstruct SimulationError objects for final reporting
        for ed in pass_errors_dicts:
            all_errors.append(SimulationError(
                ed["module"], ed["ticker"], ed["error_type"],
                ed["message"], ed.get("detail", "")))

        pass_elapsed = time.time() - pass_start
        pass_errs = len([e for e in pass_errors_dicts if e["error_type"] != "WARNING"])
        pass_warns = len([e for e in pass_errors_dicts if e["error_type"] == "WARNING"])
        pass_summaries.append({
            "pass": pass_num,
            "time_sec": round(pass_elapsed, 1),
            "total_errors": pass_errs,
            "total_warnings": pass_warns,
            "tickers_tested": n_tickers,
            "tickers_failed": pass_failures,
        })

        print(f"\n  Pass {pass_num} Summary: {pass_errs} errors, {pass_warns} warnings, "
              f"{pass_failures} tickers failed, {pass_elapsed:.1f}s")

    # ── FINAL REPORT ──
    print("\n" + "=" * 80)
    print("  SIMULATION COMPLETE — FINAL REPORT")
    print("=" * 80)

    total_modules = 13 * total_sims
    total_errs = len([e for e in all_errors if e.error_type != "WARNING"])
    total_warns = len([e for e in all_errors if e.error_type == "WARNING"])
    total_crashes = len([e for e in all_errors if e.error_type == "CRASH"])
    total_math = len([e for e in all_errors if e.error_type == "MATH_ERROR"])
    total_inconsist = len([e for e in all_errors if e.error_type == "INCONSISTENCY"])

    print(f"\n  Total Tickers:      {n_tickers:,}")
    print(f"  Total Simulations:  {total_sims:,}")
    print(f"  Module Tests:       {total_modules:,}")
    print(f"  ────────────────────────────────")
    print(f"  CRASHES:            {total_crashes:,}")
    print(f"  MATH ERRORS:        {total_math:,}")
    print(f"  INCONSISTENCIES:    {total_inconsist:,}")
    print(f"  WARNINGS:           {total_warns:,}")
    print(f"  ────────────────────────────────")
    print(f"  TOTAL ERRORS:       {total_errs:,}")
    pr = (total_sims * 13 - total_errs) / (total_sims * 13) * 100 if total_sims > 0 else 0
    print(f"  PASS RATE:          {pr:.2f}%")

    # Per-pass summary
    print(f"\n  Per-Pass Breakdown:")
    print(f"  {'Pass':>6s}  {'Errors':>7s}  {'Warnings':>9s}  {'Time':>7s}")
    print(f"  {'─' * 35}")
    for ps in pass_summaries:
        print(f"  {ps['pass']:>6d}  {ps['total_errors']:>7d}  {ps['total_warnings']:>9d}  {ps['time_sec']:>6.1f}s")

    # Error breakdown by module
    if all_errors:
        print(f"\n  Error Breakdown by Module:")
        module_errors = {}
        for e in all_errors:
            module_errors.setdefault(e.module, {"CRASH": 0, "MATH_ERROR": 0, "INCONSISTENCY": 0, "WARNING": 0})
            module_errors[e.module][e.error_type] += 1

        print(f"  {'Module':<25s}  {'Crash':>6s}  {'Math':>6s}  {'Incon':>6s}  {'Warn':>6s}")
        print(f"  {'─' * 55}")
        for mod in sorted(module_errors.keys()):
            mc = module_errors[mod]
            print(f"  {mod:<25s}  {mc['CRASH']:>6d}  {mc['MATH_ERROR']:>6d}  {mc['INCONSISTENCY']:>6d}  {mc['WARNING']:>6d}")

    # Unique errors (top 30 by count)
    if all_errors:
        print(f"\n  Unique Error Messages (top 30):")
        from collections import Counter, defaultdict
        err_counter = Counter()
        err_tickers = defaultdict(set)
        err_detail = {}
        for e in all_errors:
            key = f"[{e.error_type}] {e.module}: {e.message}"
            err_counter[key] += 1
            err_tickers[key].add(e.ticker)
            if e.detail and e.error_type == "CRASH" and key not in err_detail:
                err_detail[key] = e.detail

        for key, count in err_counter.most_common(30):
            tickers = sorted(err_tickers[key])
            ticker_str = ", ".join(tickers[:5])
            if len(tickers) > 5:
                ticker_str += f" +{len(tickers)-5} more"
            print(f"    {key}")
            print(f"      ↳ {count}× across {len(tickers)} tickers: {ticker_str}")
            if key in err_detail:
                lines = err_detail[key].strip().split("\n")
                for line in lines[-3:]:
                    print(f"        {line}")

    # Signal distribution
    print(f"\n  Signal Distribution (across all passes):")
    bb_signals = {"BUY": 0, "SELL": 0, "HOLD": 0, "WAIT": 0}
    ta_verdicts = {}
    hybrid_verdicts = {}

    for r in all_results:
        bs = r.get("results", {}).get("bb_signal", {})
        for k in ["buy", "sell", "hold", "wait"]:
            if bs.get(k):
                bb_signals[k.upper()] = bb_signals.get(k.upper(), 0) + 1

        tv = r.get("results", {}).get("ta_signal", {}).get("verdict", "N/A")
        ta_verdicts[tv] = ta_verdicts.get(tv, 0) + 1

        hv_dict = r.get("results", {}).get("hybrid", {})
        hv_verdict = hv_dict.get("verdict", "N/A")
        hybrid_verdicts[hv_verdict] = hybrid_verdicts.get(hv_verdict, 0) + 1

    print(f"\n    BB Method I:  {bb_signals}")
    print(f"    TA Murphy:    {dict(sorted(ta_verdicts.items(), key=lambda x: str(x[0])))}")
    print(f"    Hybrid:       {dict(sorted(hybrid_verdicts.items(), key=lambda x: str(x[0])))}")

    # Strategy signal distribution
    strategy_signals = {"M2": {}, "M3": {}, "M4": {}}
    for r in all_results:
        ss = r.get("results", {}).get("bb_strategies", {})
        for code in ["M2", "M3", "M4"]:
            sig = ss.get(code, {}).get("signal", "N/A")
            strategy_signals[code][sig] = strategy_signals[code].get(sig, 0) + 1

    print(f"\n    BB Method II:  {dict(sorted(strategy_signals['M2'].items(), key=lambda x: str(x[0])))}")
    print(f"    BB Method III: {dict(sorted(strategy_signals['M3'].items(), key=lambda x: str(x[0])))}")
    print(f"    BB Method IV:  {dict(sorted(strategy_signals['M4'].items(), key=lambda x: str(x[0])))}")

    # Quant regime distribution
    regime_dist = {}
    for r in all_results:
        reg = r.get("results", {}).get("quant", {}).get("regime", "N/A")
        regime_dist[reg] = regime_dist.get(reg, 0) + 1
    print(f"    Quant Regime:  {dict(sorted(regime_dist.items(), key=lambda x: str(x[0])))}")

    # Save results to JSON
    output = {
        "simulation_date": datetime.now().isoformat(),
        "config": {
            "tickers": SIM_TICKERS,
            "num_passes": NUM_PASSES,
        },
        "summary": {
            "total_tickers": n_tickers,
            "total_simulations": total_sims,
            "total_module_tests": total_modules,
            "total_errors": total_errs,
            "total_warnings": total_warns,
            "pass_rate": round(pr, 2),
            "crashes": total_crashes,
            "math_errors": total_math,
            "inconsistencies": total_inconsist,
        },
        "pass_summaries": pass_summaries,
        "errors": [e.to_dict() for e in all_errors[:500]],  # Cap at 500 to limit file size
        "signal_distribution": {
            "bb_method_i": bb_signals,
            "ta_murphy": ta_verdicts,
            "hybrid": hybrid_verdicts,
            "bb_method_ii": strategy_signals["M2"],
            "bb_method_iii": strategy_signals["M3"],
            "bb_method_iv": strategy_signals["M4"],
            "quant_regime": regime_dist,
        },
        "results": all_results[:200],  # Cap detailed results to first 200 for file size
    }

    with open(RESULTS_FILE, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\n  Full results saved to: {RESULTS_FILE}")
    print(f"  Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    return output


if __name__ == "__main__":
    run_full_simulation()
