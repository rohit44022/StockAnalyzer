"""
ai_ml/trainer.py — Generate training data and train the ML Signal Filter.

This reads historical CSVs, runs the same indicator math as the backtester,
generates signals, walks forward to determine WIN/LOSS, and captures the
full indicator snapshot at each entry as ML features.

The trained XGBoost model learns which indicator combinations predict wins.

Usage:
    python -m ai_ml.trainer            # train on all stocks, 2011-2026
    python -m ai_ml.trainer --quick    # train on Nifty-50 only (fast test)
"""
from __future__ import annotations

import json
import os
import sys
import time
import logging

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from ai_ml.config import (
    SIGNAL_FILTER_MODEL, METHOD_ROUTER_DATA, TRAINING_DATA_FILE,
    CSV_DIR, ML_FEATURES,
)

logger = logging.getLogger("ai_ml.trainer")

# ─────────────────────────────────────────────────────────────────
#  INDICATOR MATH (mirrors backtester exactly — no dependency on it)
# ─────────────────────────────────────────────────────────────────

def _sma(arr: np.ndarray, period: int) -> np.ndarray:
    out = np.full(len(arr), np.nan)
    for i in range(period - 1, len(arr)):
        out[i] = arr[i - period + 1 : i + 1].mean()
    return out


def _rolling_std(arr: np.ndarray, period: int) -> np.ndarray:
    out = np.full(len(arr), np.nan)
    for i in range(period - 1, len(arr)):
        out[i] = arr[i - period + 1 : i + 1].std(ddof=0)
    return out


def _rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    delta = np.diff(close, prepend=np.nan)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = _sma(gain, period)
    avg_loss = _sma(loss, period)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.where(avg_loss == 0, np.inf, avg_gain / avg_loss)
    return 100.0 - (100.0 / (1.0 + rs))


def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    prev_close = np.concatenate([[np.nan], close[:-1]])
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    return _sma(tr, period)


def _rolling_percentile(arr: np.ndarray, val: np.ndarray, window: int) -> np.ndarray:
    """What percentile is val[i] relative to arr[i-window:i]?"""
    out = np.full(len(arr), np.nan)
    for i in range(window, len(arr)):
        chunk = arr[i - window : i]
        valid = chunk[~np.isnan(chunk)]
        if len(valid) > 5 and not np.isnan(val[i]):
            out[i] = np.searchsorted(np.sort(valid), val[i]) / len(valid)
    return out


# ─────────────────────────────────────────────────────────────────
#  SIGNAL FUNCTIONS (identical to backtester)
# ─────────────────────────────────────────────────────────────────

def _signal_m1(ind, i):
    if i < 5: return False
    return (not np.isnan(ind["bbw"][i]) and ind["bbw"][i] < 0.10
            and ind["close"][i] > ind["upper"][i]
            and ind["volume"][i] > 1.5 * ind["vol_ma"][i])

def _signal_m2(ind, i):
    if i < 6: return False
    return (not np.isnan(ind["sma20"][i])
            and ind["close"][i] > ind["sma20"][i]
            and ind["close"][i] > ind["close"][i-1]
            and not np.isnan(ind["rsi14"][i]) and ind["rsi14"][i] > 50
            and ind["sma20"][i] > ind["sma20"][i-5])

def _signal_m3(ind, i):
    if i < 2: return False
    return (not np.isnan(ind["lower"][i-1])
            and ind["close"][i-1] < ind["lower"][i-1]
            and not np.isnan(ind["rsi14"][i-1]) and ind["rsi14"][i-1] < 35
            and ind["close"][i] > ind["close"][i-1])

def _signal_m4(ind, i):
    if i < 3: return False
    consec = all(ind["close"][j] > ind["upper"][j] for j in range(i-2, i+1))
    vol_rising = ind["volume"][i] > ind["volume"][i-1] > ind["volume"][i-2]
    return consec and vol_rising and not np.isnan(ind["upper"][i])

_SIGNAL_FN = {"M1": _signal_m1, "M2": _signal_m2, "M3": _signal_m3, "M4": _signal_m4}


# ─────────────────────────────────────────────────────────────────
#  FEATURE EXTRACTION — the ML-specific part
# ─────────────────────────────────────────────────────────────────

def _extract_features(ind: dict, i: int) -> dict | None:
    """Extract ML feature vector at bar index i. Returns None if data insufficient."""
    if i < 60:
        return None

    close = ind["close"]
    sma20 = ind["sma20"][i]
    upper = ind["upper"][i]
    lower = ind["lower"][i]

    if np.isnan(sma20) or sma20 == 0 or np.isnan(upper) or np.isnan(lower):
        return None

    atr_val = ind["atr14"][i]
    if np.isnan(atr_val) or atr_val == 0:
        return None

    vol_ma = ind["vol_ma"][i]

    return {
        "bbw":               ind["bbw"][i],
        "rsi14":             ind["rsi14"][i],
        "atr14_pct":         atr_val / close[i] * 100 if close[i] > 0 else np.nan,
        "vol_ratio":         ind["volume"][i] / vol_ma if vol_ma > 0 else np.nan,
        "close_vs_sma20":    (close[i] - sma20) / sma20 * 100,
        "close_vs_upper":    (close[i] - upper) / sma20 * 100,
        "close_vs_lower":    (close[i] - lower) / sma20 * 100,
        "sma20_slope_5d":    (sma20 - ind["sma20"][i-5]) / sma20 * 100 if not np.isnan(ind["sma20"][i-5]) and ind["sma20"][i-5] > 0 else np.nan,
        "rsi14_slope_5d":    ind["rsi14"][i] - ind["rsi14"][i-5] if not np.isnan(ind["rsi14"][i-5]) else np.nan,
        "bbw_percentile_60d": ind["bbw_pct60"][i] if "bbw_pct60" in ind else np.nan,
        "vol_trend_5d":      (ind["volume"][i] / ind["volume"][i-5] - 1) * 100 if ind["volume"][i-5] > 0 else np.nan,
        "price_momentum_10d": (close[i] / close[i-10] - 1) * 100 if close[i-10] > 0 else np.nan,
        "price_momentum_20d": (close[i] / close[i-20] - 1) * 100 if close[i-20] > 0 else np.nan,
        "atr14_percentile_60d": ind["atr14_pct60"][i] if "atr14_pct60" in ind else np.nan,
    }


# ─────────────────────────────────────────────────────────────────
#  SINGLE-STOCK DATA GENERATOR
# ─────────────────────────────────────────────────────────────────

def _process_stock(csv_path: str, start_date: str, end_date: str,
                   stop_mult: float = 2.0, target_mult: float = 3.0) -> list[dict]:
    """Generate labeled training samples from one stock CSV."""
    try:
        df = pd.read_csv(csv_path, parse_dates=["Date"], index_col="Date")
    except Exception:
        return []

    if df.empty or "Close" not in df.columns or len(df) < 100:
        return []

    close  = df["Close"].to_numpy(dtype=float)
    high   = df["High"].to_numpy(dtype=float)
    low    = df["Low"].to_numpy(dtype=float)
    volume = df["Volume"].to_numpy(dtype=float)

    sma20  = _sma(close, 20)
    std20  = _rolling_std(close, 20)
    upper  = sma20 + 2.0 * std20
    lower  = sma20 - 2.0 * std20
    bbw    = np.where(sma20 > 0, (upper - lower) / sma20, np.nan)
    rsi14  = _rsi(close, 14)
    atr14  = _atr(high, low, close, 14)
    vol_ma = _sma(volume, 20)

    bbw_pct60  = _rolling_percentile(bbw, bbw, 60)
    atr14_pct60 = _rolling_percentile(atr14, atr14, 60)

    ind = {
        "close": close, "high": high, "low": low, "volume": volume,
        "sma20": sma20, "upper": upper, "lower": lower, "bbw": bbw,
        "rsi14": rsi14, "atr14": atr14, "vol_ma": vol_ma,
        "bbw_pct60": bbw_pct60, "atr14_pct60": atr14_pct60,
    }

    dates = df.index
    start_ts = pd.Timestamp(start_date)
    end_ts   = pd.Timestamp(end_date)
    mask = (dates >= start_ts) & (dates <= end_ts)
    valid = np.where(mask)[0]
    if len(valid) < 60:
        return []

    ticker = os.path.basename(csv_path).replace(".csv", "")
    samples = []
    max_hold = 30

    for method, sig_fn in _SIGNAL_FN.items():
        cooldown = 0
        for i in valid:
            if cooldown > 0:
                cooldown -= 1
                continue

            atr_val = ind["atr14"][i]
            if np.isnan(atr_val) or atr_val <= 0:
                continue

            if not sig_fn(ind, i):
                continue

            feats = _extract_features(ind, i)
            if feats is None:
                continue

            entry_price = close[i]
            stop  = entry_price - stop_mult * atr_val
            target = entry_price + target_mult * atr_val

            # Walk forward
            result = "OPEN"
            r_mult = 0.0
            for j in range(i + 1, min(i + max_hold + 1, len(close))):
                if high[j] >= target:
                    result = "WIN"
                    r_mult = target_mult
                    break
                if low[j] <= stop:
                    result = "LOSS"
                    risk = entry_price - stop
                    r_mult = (stop - entry_price) / risk if risk > 0 else -1.0
                    break

            if result == "OPEN":
                continue

            sample = {
                "ticker": ticker,
                "method": method,
                "date": str(dates[i].date()),
                "result": 1 if result == "WIN" else 0,
                "r_multiple": round(r_mult, 3),
            }
            sample.update(feats)
            samples.append(sample)
            cooldown = 10

    return samples


# ─────────────────────────────────────────────────────────────────
#  TRAINING DATA GENERATOR
# ─────────────────────────────────────────────────────────────────

def generate_training_data(
    csv_dir: str = CSV_DIR,
    start_date: str = "2011-08-29",
    end_date: str = "2026-08-21",
    max_stocks: int = 0,
) -> pd.DataFrame:
    """Generate training data from all stock CSVs."""
    import glob

    files = sorted(glob.glob(os.path.join(csv_dir, "*.csv")))
    if max_stocks > 0:
        files = files[:max_stocks]

    print(f"Generating training data from {len(files)} stocks...", flush=True)
    all_samples = []
    t0 = time.time()

    for idx, f in enumerate(files):
        samples = _process_stock(f, start_date, end_date)
        all_samples.extend(samples)
        if (idx + 1) % 500 == 0:
            print(f"  [{idx+1}/{len(files)}] {len(all_samples)} samples so far...", flush=True)

    df = pd.DataFrame(all_samples)
    elapsed = time.time() - t0
    print(f"  Done: {len(df)} samples from {len(files)} stocks in {elapsed:.0f}s", flush=True)

    if not df.empty:
        df.to_parquet(TRAINING_DATA_FILE, index=False)
        print(f"  Saved to {TRAINING_DATA_FILE}")

    return df


# ─────────────────────────────────────────────────────────────────
#  FEEDBACK DATA MERGE — real production outcomes
# ─────────────────────────────────────────────────────────────────

def _merge_feedback_outcomes(df: pd.DataFrame) -> pd.DataFrame:
    """Merge resolved feedback outcomes into training data.
    Real production picks override synthetic backtest labels."""
    from ai_ml.config import FEEDBACK_DB
    import sqlite3

    if not os.path.exists(FEEDBACK_DB):
        return df

    try:
        conn = sqlite3.connect(FEEDBACK_DB)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM ai_ml_feedback WHERE outcome IN ('WIN','LOSS','EXPIRED')"
        ).fetchall()
        conn.close()
    except Exception:
        return df

    if not rows:
        return df

    feedback_samples = []
    for row in rows:
        ticker = row["ticker"]
        entry_date = row["entry_date"]
        method = row["method"]
        outcome = row["outcome"]

        # Find CSV for this ticker
        csv_path = os.path.join(CSV_DIR, f"{ticker}.csv")
        if not os.path.exists(csv_path):
            csv_path = os.path.join(CSV_DIR, f"{ticker}.NS.csv")
        if not os.path.exists(csv_path):
            continue

        try:
            stock_df = pd.read_csv(csv_path, parse_dates=["Date"], index_col="Date")
        except Exception:
            continue

        if stock_df.empty or "Close" not in stock_df.columns or len(stock_df) < 100:
            continue

        # Find bar index for entry_date
        try:
            entry_ts = pd.Timestamp(entry_date)
            idx_matches = stock_df.index.get_indexer([entry_ts], method="nearest")
            bar_idx = idx_matches[0]
            if bar_idx < 60:
                continue
        except Exception:
            continue

        # Compute indicators and extract features at that bar
        close  = stock_df["Close"].to_numpy(dtype=float)
        high_  = stock_df["High"].to_numpy(dtype=float)
        low_   = stock_df["Low"].to_numpy(dtype=float)
        volume = stock_df["Volume"].to_numpy(dtype=float)

        sma20  = _sma(close, 20)
        std20  = _rolling_std(close, 20)
        upper  = sma20 + 2.0 * std20
        lower  = sma20 - 2.0 * std20
        bbw    = np.where(sma20 > 0, (upper - lower) / sma20, np.nan)
        rsi14  = _rsi(close, 14)
        atr14  = _atr(high_, low_, close, 14)
        vol_ma = _sma(volume, 20)
        bbw_pct60  = _rolling_percentile(bbw, bbw, 60)
        atr14_pct60 = _rolling_percentile(atr14, atr14, 60)

        ind = {"close": close, "high": high_, "low": low_, "volume": volume,
               "sma20": sma20, "upper": upper, "lower": lower, "bbw": bbw,
               "rsi14": rsi14, "atr14": atr14, "vol_ma": vol_ma,
               "bbw_pct60": bbw_pct60, "atr14_pct60": atr14_pct60}

        feats = _extract_features(ind, bar_idx)
        if feats is None:
            continue

        sample = {
            "ticker": ticker,
            "method": method,
            "date": entry_date,
            "result": 1 if outcome == "WIN" else 0,
            "r_multiple": 0.0,
        }
        sample.update(feats)
        feedback_samples.append(sample)

    if not feedback_samples:
        return df

    fb_df = pd.DataFrame(feedback_samples)
    combined = pd.concat([df, fb_df], ignore_index=True)
    # Feedback rows take precedence over synthetic ones for same trade
    combined = combined.drop_duplicates(
        subset=["ticker", "date", "method"], keep="last"
    )
    print(f"  Merged {len(feedback_samples)} feedback outcomes ({sum(s['result'] for s in feedback_samples)} wins)", flush=True)
    return combined


# ─────────────────────────────────────────────────────────────────
#  XGBoost MODEL TRAINING
# ─────────────────────────────────────────────────────────────────

def train_signal_filter(df: pd.DataFrame | None = None) -> dict:
    """
    Train gradient boosting binary classifier: WIN (1) vs LOSS (0).
    Uses sklearn HistGradientBoosting (no native dependencies needed).
    Falls back from XGBoost if libomp is unavailable.
    Returns training metrics dict.
    """
    from sklearn.metrics import accuracy_score, roc_auc_score
    import joblib

    if df is None:
        if os.path.exists(TRAINING_DATA_FILE):
            df = pd.read_parquet(TRAINING_DATA_FILE)
        else:
            raise FileNotFoundError(f"No training data at {TRAINING_DATA_FILE}. Run generate_training_data() first.")

    # Merge real production outcomes from feedback DB
    df = _merge_feedback_outcomes(df)

    feature_cols = [c for c in ML_FEATURES if c in df.columns]
    X = df[feature_cols].copy()
    y = df["result"].astype(int)

    # Convert categorical columns to pandas category dtype for XGBoost native handling
    from ai_ml.config import ML_CATEGORICAL_FEATURES
    for cat_col in ML_CATEGORICAL_FEATURES:
        if cat_col in X.columns:
            X[cat_col] = X[cat_col].astype("category")

    # Save column medians (numeric only) — used at inference for sklearn fallback
    numeric_cols = X.select_dtypes(include="number").columns
    col_medians = X[numeric_cols].median().to_dict()
    X[numeric_cols] = X[numeric_cols].fillna(X[numeric_cols].median())

    # Temporal split: sort by date, oldest 80% train / newest 20% test
    # Eliminates look-ahead bias vs random stratified split
    if "date" in df.columns:
        sort_idx = df["date"].sort_values().index
        split_pt = int(len(sort_idx) * 0.8)
        train_idx, test_idx = sort_idx[:split_pt], sort_idx[split_pt:]
        X_train, X_test = X.loc[train_idx], X.loc[test_idx]
        y_train, y_test = y.loc[train_idx], y.loc[test_idx]
        print(f"  Temporal split: train={len(X_train)} (oldest), test={len(X_test)} (newest)", flush=True)
    else:
        from sklearn.model_selection import train_test_split
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y)

    # Load best hyperparameters if tuning has been run
    best_params_path = os.path.join(os.path.dirname(SIGNAL_FILTER_MODEL), "best_params.json")
    xgb_params = {"n_estimators": 300, "max_depth": 6, "learning_rate": 0.05,
                  "subsample": 0.8, "colsample_bytree": 0.8}
    if os.path.exists(best_params_path):
        try:
            with open(best_params_path) as f:
                xgb_params.update(json.load(f))
            print(f"  Loaded tuned params from {best_params_path}", flush=True)
        except Exception:
            pass

    # Try XGBoost first, fall back to sklearn HistGradientBoosting
    use_xgb = False
    try:
        import xgboost as xgb
        _test_x = X_train.select_dtypes(include="number").iloc[:10]
        xgb.XGBClassifier(n_estimators=1, verbosity=0).fit(
            _test_x, y_train.iloc[:10])
        use_xgb = True
    except Exception:
        pass

    if use_xgb:
        print("  Using XGBoost backend", flush=True)
        scale = y_train.value_counts()
        scale_ratio = scale[0] / scale[1] if scale[1] > 0 else 1.0
        model = xgb.XGBClassifier(
            n_estimators=xgb_params["n_estimators"],
            max_depth=xgb_params["max_depth"],
            learning_rate=xgb_params["learning_rate"],
            subsample=xgb_params["subsample"],
            colsample_bytree=xgb_params["colsample_bytree"],
            min_child_weight=xgb_params.get("min_child_weight", 1),
            gamma=xgb_params.get("gamma", 0),
            scale_pos_weight=scale_ratio, eval_metric="logloss",
            enable_categorical=True,
            random_state=42, verbosity=0,
        )
        model.fit(X_train, y_train, eval_set=[(X_test, y_test)],
                  verbose=False)
    else:
        print("  Using sklearn HistGradientBoosting backend", flush=True)
        from sklearn.ensemble import HistGradientBoostingClassifier
        # sklearn HistGradientBoosting: drop categorical cols, use numeric only
        cat_cols = [c for c in ML_CATEGORICAL_FEATURES if c in X_train.columns]
        X_train_sk = X_train.drop(columns=cat_cols, errors="ignore")
        X_test_sk  = X_test.drop(columns=cat_cols, errors="ignore")
        model = HistGradientBoostingClassifier(
            max_iter=xgb_params["n_estimators"],
            max_depth=xgb_params["max_depth"],
            learning_rate=xgb_params["learning_rate"],
            min_samples_leaf=20, l2_regularization=1.0,
            n_iter_no_change=30, validation_fraction=0.1,
            random_state=42, verbose=0,
        )
        model.fit(X_train_sk, y_train)
        X_train, X_test = X_train_sk, X_test_sk
        feature_cols = [c for c in feature_cols if c not in cat_cols]

    # Save column medians for inference NaN handling (sklearn fallback)
    medians_path = os.path.join(os.path.dirname(SIGNAL_FILTER_MODEL), "feature_medians.json")
    with open(medians_path, "w") as f:
        json.dump(col_medians, f)

    # Probability calibration — makes predict_proba output real probabilities
    try:
        from sklearn.calibration import CalibratedClassifierCV
        calibrated = CalibratedClassifierCV(model, method="isotonic", cv=5)
        calibrated.fit(X_train, y_train)
        raw_model = model
        model = calibrated
        print("  Probability calibration: isotonic (5-fold)", flush=True)
    except Exception as e:
        raw_model = model
        logger.warning("Calibration failed, using raw model: %s", e)

    y_pred = raw_model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1]

    acc = accuracy_score(y_test, y_pred)
    auc = roc_auc_score(y_test, y_prob)

    # Save calibrated model with versioning — keep last 5 versions
    model_path = SIGNAL_FILTER_MODEL
    model_dir = os.path.dirname(model_path)
    version_tag = time.strftime("%Y%m%d_%H%M%S")
    versioned_path = os.path.join(model_dir, f"signal_filter_{version_tag}.joblib")
    joblib.dump(model, versioned_path)
    joblib.dump(model, model_path)

    # Prune old versions — keep last 5
    import glob as _glob
    old_models = sorted(_glob.glob(os.path.join(model_dir, "signal_filter_*.joblib")))
    for stale in old_models[:-5]:
        try:
            os.remove(stale)
        except Exception:
            pass

    # Append to model history
    history_path = os.path.join(model_dir, "model_history.json")
    history_entry = {
        "version": version_tag, "accuracy": round(acc, 4), "auc": round(auc, 4),
        "train_size": len(y_train), "test_size": len(y_test),
        "backend": "xgboost" if use_xgb else "sklearn",
    }
    try:
        history = []
        if os.path.exists(history_path):
            with open(history_path) as f:
                history = json.load(f)
        history.append(history_entry)
        history = history[-10:]
        with open(history_path, "w") as f:
            json.dump(history, f, indent=2)
    except Exception:
        pass

    print(f"\n  Model saved: {versioned_path} (calibrated)")
    print(f"  Accuracy: {acc:.4f} | AUC: {auc:.4f}")
    print(f"  Test set: {len(y_test)} samples")

    # Feature importance (from raw model, before calibration wrapper)
    if hasattr(raw_model, 'feature_importances_'):
        importance = dict(zip(feature_cols, raw_model.feature_importances_))
    else:
        importance = {c: 0 for c in feature_cols}
    top_feats = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:7]
    print(f"  Top features: {', '.join(f'{k}={v:.3f}' for k, v in top_feats)}")

    # Per-method accuracy
    methods_in_test = df.loc[X_test.index, "method"]
    method_metrics = {}
    for m in ["M1", "M2", "M3", "M4"]:
        mask = methods_in_test == m
        if mask.sum() > 0:
            m_acc = accuracy_score(y_test[mask], y_pred[mask])
            m_auc = roc_auc_score(y_test[mask], y_prob[mask]) if y_test[mask].nunique() > 1 else 0
            method_metrics[m] = {"accuracy": round(m_acc, 4), "auc": round(m_auc, 4), "samples": int(mask.sum())}
            print(f"  {m}: acc={m_acc:.4f} auc={m_auc:.4f} ({mask.sum()} samples)")

    # Save feature importance history (last 10 training runs)
    fi_path = os.path.join(os.path.dirname(SIGNAL_FILTER_MODEL), "feature_importance.json")
    fi_entry = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "accuracy": round(acc, 4),
        "auc": round(auc, 4),
        "importance": {k: round(v, 4) for k, v in sorted(importance.items(), key=lambda x: x[1], reverse=True)},
    }
    try:
        fi_history = []
        if os.path.exists(fi_path):
            with open(fi_path) as f:
                fi_history = json.load(f)
        fi_history.append(fi_entry)
        fi_history = fi_history[-10:]
        with open(fi_path, "w") as f:
            json.dump(fi_history, f, indent=2)
    except Exception:
        pass

    # Train expectile regression model for downside risk prediction
    downside_metrics = {}
    if use_xgb and "r_multiple" in df.columns:
        try:
            y_return = df.loc[X_train.index, "r_multiple"].astype(float)
            y_return_test = df.loc[X_test.index, "r_multiple"].astype(float)
            X_train_num = X_train.select_dtypes(include="number")
            X_test_num = X_test.select_dtypes(include="number")
            downside_model = xgb.XGBRegressor(
                objective="reg:expectileerror", expectile_alpha=0.25,
                n_estimators=200, max_depth=5, learning_rate=0.05,
                random_state=42, verbosity=0,
            )
            downside_model.fit(X_train_num, y_return, eval_set=[(X_test_num, y_return_test)],
                               verbose=False)
            downside_path = os.path.join(model_dir, "downside_model.joblib")
            joblib.dump(downside_model, downside_path)
            test_pred = downside_model.predict(X_test_num)
            downside_metrics = {
                "mean_predicted": round(float(test_pred.mean()), 4),
                "saved_to": downside_path,
            }
            print(f"  Downside risk model saved: {downside_path} (expectile α=0.25)")
        except Exception as e:
            logger.warning("Downside model training failed: %s", e)

    metrics = {
        "accuracy": round(acc, 4),
        "auc": round(auc, 4),
        "train_size": len(y_train),
        "test_size": len(y_test),
        "feature_importance": {k: round(v, 4) for k, v in top_feats},
        "per_method": method_metrics,
        "features_used": feature_cols,
        "downside_model": downside_metrics,
    }
    return metrics


# ─────────────────────────────────────────────────────────────────
#  HYPERPARAMETER TUNING
# ─────────────────────────────────────────────────────────────────

def tune_hyperparameters(df: pd.DataFrame | None = None, n_iter: int = 30) -> dict:
    """
    Run RandomizedSearchCV with TimeSeriesSplit to find best XGBoost params.
    Saves best_params.json — loaded automatically by train_signal_filter().
    """
    from sklearn.model_selection import RandomizedSearchCV, TimeSeriesSplit
    from scipy.stats import uniform, randint
    import joblib

    if df is None:
        if os.path.exists(TRAINING_DATA_FILE):
            df = pd.read_parquet(TRAINING_DATA_FILE)
        else:
            raise FileNotFoundError("No training data.")

    df = _merge_feedback_outcomes(df)

    feature_cols = [c for c in ML_FEATURES if c in df.columns]
    X = df[feature_cols].copy()
    y = df["result"].astype(int)

    from ai_ml.config import ML_CATEGORICAL_FEATURES
    for cat_col in ML_CATEGORICAL_FEATURES:
        if cat_col in X.columns:
            X[cat_col] = X[cat_col].astype("category")

    numeric_cols = X.select_dtypes(include="number").columns
    X[numeric_cols] = X[numeric_cols].fillna(X[numeric_cols].median())

    if "date" in df.columns:
        sort_order = df["date"].sort_values().index
        X = X.loc[sort_order]
        y = y.loc[sort_order]

    try:
        import xgboost as xgb
    except ImportError:
        print("XGBoost not installed — cannot tune.", flush=True)
        return {}

    scale = y.value_counts()
    scale_ratio = scale[0] / scale[1] if scale[1] > 0 else 1.0

    param_dist = {
        "n_estimators": randint(100, 500),
        "max_depth": randint(3, 9),
        "learning_rate": uniform(0.01, 0.14),
        "subsample": uniform(0.6, 0.4),
        "colsample_bytree": uniform(0.6, 0.4),
        "min_child_weight": randint(1, 10),
        "gamma": uniform(0, 0.3),
    }

    base = xgb.XGBClassifier(
        scale_pos_weight=scale_ratio, eval_metric="logloss",
        enable_categorical=True, random_state=42, verbosity=0,
    )

    tscv = TimeSeriesSplit(n_splits=5)
    search = RandomizedSearchCV(
        base, param_dist, n_iter=n_iter, cv=tscv,
        scoring="roc_auc", random_state=42, n_jobs=-1, verbose=1,
    )
    print(f"  Tuning {n_iter} combinations with 5-fold TimeSeriesSplit...", flush=True)
    search.fit(X, y)

    best = {k: (int(v) if isinstance(v, (np.integer,)) else
                round(float(v), 6) if isinstance(v, (float, np.floating)) else v)
            for k, v in search.best_params_.items()}

    params_path = os.path.join(os.path.dirname(SIGNAL_FILTER_MODEL), "best_params.json")
    with open(params_path, "w") as f:
        json.dump(best, f, indent=2)

    print(f"  Best AUC: {search.best_score_:.4f}")
    print(f"  Best params: {best}")
    print(f"  Saved to {params_path}")

    return {"best_auc": round(search.best_score_, 4), "best_params": best}


# ─────────────────────────────────────────────────────────────────
#  METHOD ROUTER DATA — per-regime win rates
# ─────────────────────────────────────────────────────────────────

def build_method_router_data(df: pd.DataFrame | None = None) -> dict:
    """
    Compute per-method win rates segmented by market regime proxies
    (momentum, volatility percentile). Saves to JSON for runtime use.
    """
    if df is None:
        if os.path.exists(TRAINING_DATA_FILE):
            df = pd.read_parquet(TRAINING_DATA_FILE)
        else:
            raise FileNotFoundError("No training data.")

    router = {}

    for method in ["M1", "M2", "M3", "M4"]:
        mdf = df[df["method"] == method]
        if mdf.empty:
            continue

        total = len(mdf)
        wins = mdf["result"].sum()
        overall_wr = wins / total if total > 0 else 0

        # Segment by RSI regime (proxy for bull/bear)
        regime_data = {}
        for regime, lo, hi in [("OVERSOLD", 0, 40), ("NEUTRAL", 40, 60), ("OVERBOUGHT", 60, 100)]:
            rmask = (mdf["rsi14"] >= lo) & (mdf["rsi14"] < hi)
            rdf = mdf[rmask]
            if len(rdf) > 50:
                regime_data[regime] = {
                    "win_rate": round(rdf["result"].mean(), 4),
                    "trades": len(rdf),
                }

        # Segment by volatility regime (BBW percentile)
        vol_data = {}
        for vr, lo, hi in [("LOW_VOL", 0, 0.33), ("MED_VOL", 0.33, 0.67), ("HIGH_VOL", 0.67, 1.01)]:
            vmask = (mdf["bbw_percentile_60d"] >= lo) & (mdf["bbw_percentile_60d"] < hi)
            vdf = mdf[vmask]
            if len(vdf) > 50:
                vol_data[vr] = {
                    "win_rate": round(vdf["result"].mean(), 4),
                    "trades": len(vdf),
                }

        router[method] = {
            "overall_win_rate": round(overall_wr, 4),
            "total_trades": total,
            "by_rsi_regime": regime_data,
            "by_vol_regime": vol_data,
        }

    with open(METHOD_ROUTER_DATA, "w") as f:
        json.dump(router, f, indent=2)
    print(f"  Method router data saved: {METHOD_ROUTER_DATA}")

    return router


# ─────────────────────────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    quick = "--quick" in sys.argv

    if quick:
        # Nifty-50 only for fast testing
        from historical_data import _HARDCODED_TICKERS
        import glob
        all_files = sorted(glob.glob(os.path.join(CSV_DIR, "*.csv")))
        nifty_syms = {t.replace(".NS", "") for t in _HARDCODED_TICKERS}
        files = [f for f in all_files if os.path.basename(f).replace(".NS.csv", "") in nifty_syms]
        print(f"Quick mode: {len(files)} Nifty-50 stocks")
        df = generate_training_data(max_stocks=0)
    else:
        df = generate_training_data()

    if df.empty:
        print("No training data generated!")
        sys.exit(1)

    print(f"\nTraining data: {len(df)} samples")
    print(f"  WIN: {df['result'].sum()} ({df['result'].mean():.1%})")
    print(f"  LOSS: {(1-df['result']).sum():.0f} ({1-df['result'].mean():.1%})")
    for m in ["M1","M2","M3","M4"]:
        mdf = df[df["method"]==m]
        print(f"  {m}: {len(mdf)} trades, {mdf['result'].mean():.1%} win rate")

    print("\n── Training XGBoost Signal Filter ──")
    metrics = train_signal_filter(df)

    print("\n── Building Method Router Data ──")
    router = build_method_router_data(df)

    print("\nTraining complete.")
