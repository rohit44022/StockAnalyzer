"""
Brooks ML Trainer — trains XGBoost, LightGBM, LSTM models on Brooks backtest data.
Completely independent from BB/ai_ml models.

Usage:
  python -m brooks.ml.trainer
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

log = logging.getLogger("brooks.ml.trainer")

MODEL_DIR = Path(__file__).parent / "models"
BACKTEST_FILE = Path(__file__).resolve().parent.parent.parent / "backtest_pa_results.json"
CSV_DIR_DEFAULT = str(Path(__file__).resolve().parent.parent.parent / "stock_csv")

FEATURES = [
    "confidence", "pa_score", "risk_reward", "traders_equation",
    "trend_strength_num", "volume_ratio",
    "rsi14", "bbw", "atr_pct", "close_vs_sma20",
    "sma20_slope_5d", "rsi_slope_5d", "bbw_percentile_60d",
    "momentum_10d", "momentum_20d", "vol_ratio", "vol_trend_5d",
    "atr_percentile_60d",
    "setup_encoded", "phase_encoded", "ai_encoded", "eq_encoded",
    "buying_pressure", "selling_pressure",
    "stop_distance_pct", "regime_score",
]

SETUP_MAP = {"BREAKOUT": 0, "PULLBACK": 1, "SECOND_ENTRY": 2,
             "BREAKOUT_PULLBACK": 3, "REVERSAL": 4}
PHASE_MAP = {"SPIKE": 0, "TIGHT_CHANNEL": 1, "CHANNEL": 2,
             "BROAD_CHANNEL": 3, "TRADING_RANGE": 4}
AI_MAP = {"LONG": 0, "SHORT": 1, "FLAT": 2}
EQ_MAP = {"STRONG_EDGE": 0, "EDGE": 1, "NO_EDGE": 2}
STRENGTH_MAP = {"STRONG": 0, "MODERATE": 1, "WEAK": 2}

TRAIN_SPLIT = "2022-01-01"


def _compute_indicators(ticker: str, signal_date: str, csv_dir: str) -> dict | None:
    """Compute technical indicators at signal_date for a given ticker."""
    csv_path = os.path.join(csv_dir, f"{ticker}.csv")
    if not os.path.exists(csv_path):
        return None

    try:
        df = pd.read_csv(csv_path, parse_dates=["Date"])
        df = df.sort_values("Date").reset_index(drop=True)
        sig_date = pd.Timestamp(signal_date)
        mask = df["Date"] <= sig_date
        if mask.sum() < 60:
            return None
        df = df[mask].tail(80)

        close = df["Close"].values.astype(float)
        high = df["High"].values.astype(float)
        low = df["Low"].values.astype(float)
        vol = df["Volume"].values.astype(float)
        n = len(close)

        if n < 25:
            return None

        sma20 = float(np.mean(close[-20:]))
        std20 = float(np.std(close[-20:], ddof=1))
        upper = sma20 + 2 * std20
        lower = sma20 - 2 * std20
        bbw = (upper - lower) / sma20 if sma20 > 0 else 0

        delta = np.diff(close[-15:])
        gain = np.where(delta > 0, delta, 0).mean()
        loss = np.where(delta < 0, -delta, 0).mean()
        rsi = 100 - 100 / (1 + gain / max(loss, 1e-10))

        tr = np.maximum(high[-14:] - low[-14:],
                        np.maximum(np.abs(high[-14:] - close[-15:-1]),
                                   np.abs(low[-14:] - close[-15:-1])))
        atr = float(tr.mean())
        atr_pct = atr / close[-1] * 100 if close[-1] > 0 else 0

        volume = float(vol[-1])
        vol_avg = float(vol[-20:].mean()) if n >= 20 else 1
        vol_ratio = volume / max(vol_avg, 1)

        sma20_5ago = float(np.mean(close[-25:-5])) if n >= 25 else sma20
        sma20_slope = (sma20 - sma20_5ago) / max(sma20_5ago, 1e-10) * 100

        if n >= 20:
            d2 = np.diff(close[-20:-5])
            g2 = np.where(d2 > 0, d2, 0).mean()
            l2 = np.where(d2 < 0, -d2, 0).mean()
            rsi_5ago = 100 - 100 / (1 + g2 / max(l2, 1e-10))
            rsi_slope = rsi - rsi_5ago
        else:
            rsi_slope = 0

        if n >= 60:
            bbws = []
            for i in range(60):
                idx = n - 60 + i
                s = float(np.mean(close[max(0, idx - 19):idx + 1]))
                sd = float(np.std(close[max(0, idx - 19):idx + 1], ddof=1))
                bbws.append((4 * sd / s) if s > 0 else 0)
            bbw_pct = float(np.searchsorted(np.sort(bbws), bbw) / len(bbws))
        else:
            bbw_pct = 0.5

        vol_trend = 0
        if n >= 25:
            vol_avg_5ago = float(vol[-25:-5].mean())
            vol_trend = (vol_avg - vol_avg_5ago) / max(vol_avg_5ago, 1e-10)

        mom_10 = (close[-1] - close[-11]) / close[-11] * 100 if n >= 11 else 0
        mom_20 = (close[-1] - close[-21]) / close[-21] * 100 if n >= 21 else 0

        if n >= 74:
            atrs = []
            for i in range(60):
                idx = n - 60 + i
                si = max(0, idx - 13)
                if si >= 1 and idx < n:
                    tr_i = np.maximum(high[si:idx + 1] - low[si:idx + 1],
                                      np.maximum(np.abs(high[si:idx + 1] - close[si - 1:idx]),
                                                 np.abs(low[si:idx + 1] - close[si - 1:idx])))
                    atrs.append(float(tr_i.mean()))
            atr_pct_val = float(np.searchsorted(np.sort(atrs), atr) / max(len(atrs), 1))
        else:
            atr_pct_val = 0.5

        return {
            "rsi14": round(rsi, 2),
            "bbw": round(bbw, 6),
            "atr_pct": round(atr_pct, 4),
            "close_vs_sma20": round((close[-1] - sma20) / sma20 * 100, 4),
            "sma20_slope_5d": round(sma20_slope, 4),
            "rsi_slope_5d": round(rsi_slope, 2),
            "bbw_percentile_60d": round(bbw_pct, 4),
            "vol_ratio": round(vol_ratio, 4),
            "vol_trend_5d": round(vol_trend, 4),
            "momentum_10d": round(mom_10, 4),
            "momentum_20d": round(mom_20, 4),
            "atr_percentile_60d": round(atr_pct_val, 4),
            "volume_ratio": round(vol_ratio, 4),
        }
    except Exception:
        return None


def _build_dataset(csv_dir: str | None = None) -> pd.DataFrame:
    """Build training dataset from backtest results + CSV indicators."""
    csv_dir = csv_dir or CSV_DIR_DEFAULT
    from bb_squeeze.config import CSV_DIR as cfg_csv
    csv_dir = csv_dir or cfg_csv

    log.info("Loading backtest results from %s", BACKTEST_FILE)
    with open(BACKTEST_FILE) as f:
        data = json.load(f)
    trades = data["trades"]
    log.info("Total trades: %d", len(trades))

    rows = []
    skipped = 0
    for i, t in enumerate(trades):
        if i % 5000 == 0:
            log.info("Processing trade %d/%d (skipped %d)", i, len(trades), skipped)

        # Target: WIN=1, LOSS=0
        outcome = t["outcome"]
        if outcome in ("WIN_T1", "WIN_T2", "TIMEOUT_WIN"):
            target = 1
        elif outcome in ("LOSS", "TIMEOUT_LOSS"):
            target = 0
        else:
            skipped += 1
            continue

        # r_multiple for conviction
        pnl = t.get("pnl_pct", 0)
        entry = t["entry_price"]
        stop = t["stop_loss"]
        risk = abs(entry - stop) / max(entry, 1e-10) * 100
        r_multiple = pnl / max(risk, 0.1)

        # Technical indicators from CSV
        ind = _compute_indicators(t["ticker"], t["signal_date"], csv_dir)
        if ind is None:
            skipped += 1
            continue

        row = {
            "target": target,
            "r_multiple": r_multiple,
            "pnl_pct": pnl,
            "confidence": t.get("confidence", 50),
            "pa_score": t.get("pa_score", 0),
            "risk_reward": t.get("risk_reward", 1.0),
            "traders_equation": t.get("traders_equation", 0),
            "trend_strength_num": STRENGTH_MAP.get(t.get("strength", "MODERATE"), 1),
            "setup_encoded": SETUP_MAP.get(t.get("setup_type", ""), 3),
            "phase_encoded": PHASE_MAP.get(t.get("trend_phase", ""), 4),
            "ai_encoded": AI_MAP.get(t.get("always_in", "FLAT"), 2),
            "eq_encoded": EQ_MAP.get(t.get("equation_verdict", ""), 1),
            "buying_pressure": 50,  # not in backtest data, default
            "selling_pressure": 50,
            "stop_distance_pct": abs(t.get("entry_price", 0) - t.get("stop_loss", 0)) / max(t.get("entry_price", 1), 1) * 100,
            "regime_score": t.get("regime_score", 0),
            "signal_date": t["signal_date"],
            "ticker": t["ticker"],
            **ind,
        }
        rows.append(row)

    df = pd.DataFrame(rows)
    log.info("Dataset built: %d rows (%d skipped)", len(df), skipped)
    return df


def _train_xgboost(df_train: pd.DataFrame, df_test: pd.DataFrame):
    """Train XGBoost classifier on Brooks data."""
    import xgboost as xgb
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.metrics import classification_report, roc_auc_score

    X_train = df_train[FEATURES].copy()
    y_train = df_train["target"]
    X_test = df_test[FEATURES].copy()
    y_test = df_test["target"]

    # Fill NaN with medians
    medians = X_train.median().to_dict()
    X_train = X_train.fillna(medians)
    X_test = X_test.fillna(medians)

    model = xgb.XGBClassifier(
        n_estimators=300, max_depth=5, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8,
        min_child_weight=10, reg_alpha=0.1, reg_lambda=1.0,
        scale_pos_weight=y_train.value_counts()[0] / max(y_train.value_counts()[1], 1),
        eval_metric="logloss", verbosity=0, n_jobs=-1,
    )
    model.fit(X_train, y_train)

    # Calibrate
    cal_model = CalibratedClassifierCV(model, cv=3, method="isotonic")
    cal_model.fit(X_train, y_train)

    # Evaluate
    y_pred = cal_model.predict(X_test)
    y_prob = cal_model.predict_proba(X_test)[:, 1]
    auc = roc_auc_score(y_test, y_prob)
    report = classification_report(y_test, y_pred, output_dict=True)

    log.info("XGBoost — AUC: %.4f, Accuracy: %.4f", auc, report["accuracy"])

    # Feature importance
    importance = {k: float(v) for k, v in zip(FEATURES, model.feature_importances_)}

    # Save
    joblib.dump(cal_model, MODEL_DIR / "brooks_xgb.joblib")
    joblib.dump(medians, MODEL_DIR / "brooks_xgb_medians.joblib")
    json.dump(importance, open(MODEL_DIR / "brooks_xgb_importance.json", "w"), indent=2)

    return {
        "auc": round(auc, 4),
        "accuracy": round(report["accuracy"], 4),
        "precision_win": round(report.get("1", {}).get("precision", 0), 4),
        "recall_win": round(report.get("1", {}).get("recall", 0), 4),
        "f1_win": round(report.get("1", {}).get("f1-score", 0), 4),
        "train_size": len(df_train),
        "test_size": len(df_test),
    }


def _train_lightgbm(df_train: pd.DataFrame, df_test: pd.DataFrame):
    """Train LightGBM regressor on r_multiple for conviction scoring."""
    import lightgbm as lgb
    from sklearn.metrics import root_mean_squared_error, r2_score

    X_train = df_train[FEATURES].copy()
    y_train = df_train["r_multiple"]
    X_test = df_test[FEATURES].copy()
    y_test = df_test["r_multiple"]

    medians = X_train.median().to_dict()
    X_train = X_train.fillna(medians)
    X_test = X_test.fillna(medians)

    model = lgb.LGBMRegressor(
        n_estimators=300, max_depth=5, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8,
        min_child_samples=20, reg_alpha=0.1, reg_lambda=1.0,
        verbosity=-1, n_jobs=-1,
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    rmse = root_mean_squared_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)

    log.info("LightGBM — RMSE: %.4f, R²: %.4f", rmse, r2)

    # Quantile models for CI
    q_lo = lgb.LGBMRegressor(
        objective="quantile", alpha=0.25,
        n_estimators=200, max_depth=4, learning_rate=0.05,
        verbosity=-1, n_jobs=-1,
    )
    q_hi = lgb.LGBMRegressor(
        objective="quantile", alpha=0.75,
        n_estimators=200, max_depth=4, learning_rate=0.05,
        verbosity=-1, n_jobs=-1,
    )
    q_lo.fit(X_train, y_train)
    q_hi.fit(X_train, y_train)

    joblib.dump(model, MODEL_DIR / "brooks_lgb.joblib")
    joblib.dump(q_lo, MODEL_DIR / "brooks_lgb_q25.joblib")
    joblib.dump(q_hi, MODEL_DIR / "brooks_lgb_q75.joblib")
    joblib.dump(medians, MODEL_DIR / "brooks_lgb_medians.joblib")

    return {
        "rmse": round(rmse, 4),
        "r2": round(r2, 4),
        "train_size": len(df_train),
        "test_size": len(df_test),
    }


def _train_downside(df_train: pd.DataFrame, df_test: pd.DataFrame):
    """Train downside risk model (25th percentile via LightGBM quantile)."""
    import lightgbm as lgb

    X_train = df_train[FEATURES].copy().fillna(0)
    y_train = df_train["pnl_pct"]
    X_test = df_test[FEATURES].copy().fillna(0)
    y_test = df_test["pnl_pct"]

    model = lgb.LGBMRegressor(
        objective="quantile", alpha=0.25,
        n_estimators=200, max_depth=4, learning_rate=0.05,
        verbosity=-1, n_jobs=-1,
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    coverage = (y_test >= y_pred).mean()
    log.info("Downside model — 25th percentile coverage: %.2f%%", coverage * 100)

    joblib.dump(model, MODEL_DIR / "brooks_downside.joblib")

    return {
        "coverage_25pct": round(float(coverage), 4),
        "mean_predicted_floor": round(float(y_pred.mean()), 4),
    }


def _build_sequences(df: pd.DataFrame, csv_dir: str) -> tuple[np.ndarray, np.ndarray]:
    """Build 20-bar OHLCV sequences for LSTM training."""
    SEQ_LEN = 20
    seqs, targets = [], []

    # Sample to cap at 10K sequences for reasonable training time on CPU
    if len(df) > 10000:
        df_seq = df.sample(10000, random_state=42)
    else:
        df_seq = df
    grouped = df_seq.groupby("ticker")
    for ticker, group in grouped:
        csv_path = os.path.join(csv_dir, f"{ticker}.csv")
        if not os.path.exists(csv_path):
            continue
        try:
            stock = pd.read_csv(csv_path, parse_dates=["Date"]).sort_values("Date")
        except Exception:
            continue
        if len(stock) < SEQ_LEN + 60:
            continue

        close = stock["Close"].values.astype(float)
        high = stock["High"].values.astype(float)
        low = stock["Low"].values.astype(float)
        vol = stock["Volume"].values.astype(float)
        dates = stock["Date"].values

        for _, row in group.iterrows():
            sig = pd.Timestamp(row["signal_date"])
            idx = np.searchsorted(dates, sig)
            if idx < SEQ_LEN or idx >= len(close):
                continue

            # Normalize sequence
            window = slice(idx - SEQ_LEN, idx)
            c = close[window]
            h = high[window]
            l = low[window]
            v = vol[window]

            base = c[0] if c[0] > 0 else 1
            vol_base = v.mean() if v.mean() > 0 else 1

            seq = np.stack([
                c / base - 1,
                h / base - 1,
                l / base - 1,
                v / vol_base,
            ], axis=1).astype(np.float32)

            seqs.append(seq)
            targets.append(row["target"])

    if not seqs:
        return np.array([]), np.array([])
    return np.array(seqs, dtype=np.float32), np.array(targets, dtype=np.float32)


def _train_lstm(df_train: pd.DataFrame, df_test: pd.DataFrame, csv_dir: str):
    """Train LSTM sequence model."""
    import torch
    import torch.nn as nn

    class BrooksLSTM(nn.Module):
        def __init__(self, input_size=4, hidden=32, layers=2):
            super().__init__()
            self.lstm = nn.LSTM(input_size, hidden, layers, batch_first=True, dropout=0.2)
            self.fc = nn.Linear(hidden, 1)

        def forward(self, x):
            _, (h, _) = self.lstm(x)
            return torch.sigmoid(self.fc(h[-1])).squeeze(-1)

    log.info("Building LSTM sequences...")
    X_train, y_train = _build_sequences(df_train, csv_dir)
    X_test, y_test = _build_sequences(df_test, csv_dir)

    if len(X_train) < 100:
        log.warning("Too few sequences for LSTM: %d", len(X_train))
        return {"error": "too few sequences"}

    log.info("LSTM train: %d sequences, test: %d", len(X_train), len(X_test))

    X_tr = torch.from_numpy(X_train)
    y_tr = torch.from_numpy(y_train)
    X_te = torch.from_numpy(X_test)
    y_te = torch.from_numpy(y_test)

    model = BrooksLSTM()
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    loss_fn = nn.BCELoss()

    batch_size = 512
    best_loss = float("inf")
    patience = 5
    wait = 0

    for epoch in range(30):
        model.train()
        perm = torch.randperm(len(X_tr))
        epoch_loss = 0
        batches = 0
        for i in range(0, len(X_tr), batch_size):
            idx = perm[i:i + batch_size]
            xb, yb = X_tr[idx], y_tr[idx]
            pred = model(xb)
            loss = loss_fn(pred, yb)
            opt.zero_grad()
            loss.backward()
            opt.step()
            epoch_loss += loss.item()
            batches += 1

        avg_loss = epoch_loss / max(batches, 1)
        if avg_loss < best_loss - 1e-4:
            best_loss = avg_loss
            wait = 0
            torch.save(model.state_dict(), MODEL_DIR / "brooks_lstm.pt")
        else:
            wait += 1
            if wait >= patience:
                log.info("LSTM early stop at epoch %d", epoch)
                break

    # Load best
    model.load_state_dict(torch.load(MODEL_DIR / "brooks_lstm.pt", weights_only=True))
    model.eval()

    with torch.no_grad():
        test_pred = model(X_te).numpy()
    test_labels = y_te.numpy()

    from sklearn.metrics import roc_auc_score, accuracy_score
    threshold = 0.5
    auc = roc_auc_score(test_labels, test_pred) if len(np.unique(test_labels)) > 1 else 0
    acc = accuracy_score(test_labels, (test_pred >= threshold).astype(int))

    log.info("LSTM — AUC: %.4f, Accuracy: %.4f", auc, acc)

    return {
        "auc": round(auc, 4),
        "accuracy": round(acc, 4),
        "train_sequences": len(X_train),
        "test_sequences": len(X_test),
        "epochs": epoch + 1,
    }


def train_all(csv_dir: str | None = None):
    """Train all Brooks ML models."""
    from bb_squeeze.config import CSV_DIR as cfg_csv
    csv_dir = csv_dir or cfg_csv

    t0 = time.time()
    log.info("=== Brooks ML Training ===")

    df = _build_dataset(csv_dir)
    if len(df) < 500:
        log.error("Not enough data: %d rows", len(df))
        return {"error": "insufficient data"}

    # Train/test split
    df_train = df[df["signal_date"] < TRAIN_SPLIT].copy()
    df_test = df[df["signal_date"] >= TRAIN_SPLIT].copy()
    log.info("Train: %d, Test: %d (split: %s)", len(df_train), len(df_test), TRAIN_SPLIT)

    results = {}

    # XGBoost
    log.info("--- Training XGBoost ---")
    results["xgboost"] = _train_xgboost(df_train, df_test)

    # LightGBM
    log.info("--- Training LightGBM ---")
    results["lightgbm"] = _train_lightgbm(df_train, df_test)

    # Downside
    log.info("--- Training Downside model ---")
    results["downside"] = _train_downside(df_train, df_test)

    # LSTM
    log.info("--- Training LSTM ---")
    results["lstm"] = _train_lstm(df_train, df_test, csv_dir)

    elapsed = time.time() - t0
    results["elapsed_seconds"] = round(elapsed, 1)
    results["dataset_size"] = len(df)
    results["train_size"] = len(df_train)
    results["test_size"] = len(df_test)

    # Save results
    json.dump(results, open(MODEL_DIR / "training_results.json", "w"), indent=2)
    log.info("Training complete in %.1fs", elapsed)
    log.info("Results: %s", json.dumps(results, indent=2))

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    train_all()
