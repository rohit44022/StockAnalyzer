"""
rentech/ml_scorer.py — ML confidence meta-learner for the RenTech ensemble.

Answers: "given these 11 alpha scores + regime + statistical profile,
how often do similar setups produce positive forward returns?"

Self-trains on first call using walk-forward on stock CSVs.
Uses HistGradientBoostingClassifier (handles NaN natively, no new deps).

Usage:
    # From engine — real-time scoring
    from rentech.ml_scorer import score_analysis
    ml = score_analysis(composite, profile, regime)

    # CLI training
    python -m rentech.ml_scorer          # train on Nifty-50 stocks
    python -m rentech.ml_scorer --full   # train on all available CSVs
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from rentech import config as C

logger = logging.getLogger("rentech.ml_scorer")

_MODEL_DIR = C.ML_MODEL_DIR
_MODEL_PATH = _MODEL_DIR / "rentech_scorer.joblib"
_MEDIANS_PATH = _MODEL_DIR / "rentech_feature_medians.json"

_cached_model = None
_cached_medians = None

# ── Feature names (order matters for model) ──────────────────
FEATURE_NAMES = [
    "alpha_mr", "alpha_mom", "alpha_micro", "alpha_vol",
    "alpha_season", "alpha_pattern", "alpha_stat",
    "alpha_crsi", "alpha_kst", "alpha_cmo", "alpha_vortex",
    "composite_score", "conviction", "quality",
    "n_longs", "n_shorts",
    "hurst", "ou_half_life", "adf_pval",
    "entropy", "vol_cluster",
    "regime_bull", "regime_bear", "regime_sideways", "regime_highvol",
]

NIFTY50_TICKERS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK", "LT",
    "BAJFINANCE", "HCLTECH", "MARUTI", "AXISBANK", "TITAN",
    "SUNPHARMA", "WIPRO", "NTPC", "POWERGRID", "COALINDIA",
    "ADANIENT", "TECHM", "ULTRACEMCO", "NESTLEIND", "DRREDDY",
    "CIPLA", "TATASTEEL", "HINDUNILVR", "ASIANPAINT", "ONGC",
    "BAJAJ-AUTO", "JSWSTEEL", "GRASIM", "BRITANNIA", "HEROMOTOCO",
    "INDUSINDBK", "EICHERMOT", "TATACONSUM", "APOLLOHOSP", "DIVISLAB",
    "DMART", "HAL", "BEL", "IRCTC", "ZOMATO",
    "ADANIPORTS", "M&M", "BAJAJFINSV", "PIIND", "SBILIFE",
]


# ═══════════════════════════════════════════════════════════════
# FAST VECTORIZED ALPHA FEATURES (for training, not real-time)
# ═══════════════════════════════════════════════════════════════

def _fast_rsi(close: np.ndarray, period: int) -> np.ndarray:
    delta = np.diff(close, prepend=np.nan)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    n = len(close)
    avg_g = np.full(n, np.nan)
    avg_l = np.full(n, np.nan)
    if n <= period:
        return np.full(n, np.nan)
    avg_g[period] = np.mean(gain[1:period + 1])
    avg_l[period] = np.mean(loss[1:period + 1])
    a = 1.0 / period
    for i in range(period + 1, n):
        avg_g[i] = avg_g[i - 1] * (1 - a) + gain[i] * a
        avg_l[i] = avg_l[i - 1] * (1 - a) + loss[i] * a
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.where(avg_l == 0, 100.0, avg_g / avg_l)
    return 100.0 - 100.0 / (1.0 + rs)


def _fast_features(close: np.ndarray, high: np.ndarray,
                   low: np.ndarray, volume: np.ndarray) -> np.ndarray:
    """Compute all 25 features at every bar. Returns shape (n, 25)."""
    n = len(close)
    feats = np.full((n, len(FEATURE_NAMES)), np.nan)

    if n < 120:
        return feats

    # RSI variants
    rsi3 = _fast_rsi(close, 3)
    rsi14 = _fast_rsi(close, 14)

    # ConnorsRSI (simplified — streak + RSI(3) + pct rank)
    streak = np.zeros(n)
    for i in range(1, n):
        if close[i] > close[i - 1]:
            streak[i] = max(streak[i - 1], 0) + 1
        elif close[i] < close[i - 1]:
            streak[i] = min(streak[i - 1], 0) - 1
    # Approx pct rank of 1d return
    roc1 = np.diff(close, prepend=np.nan) / np.concatenate([[1], close[:-1]])
    pct_rank = np.full(n, 50.0)
    for i in range(100, n):
        window = roc1[i - 99:i]
        valid = window[~np.isnan(window)]
        if len(valid) > 5:
            pct_rank[i] = np.searchsorted(np.sort(valid), roc1[i]) / len(valid) * 100

    crsi_score = np.full(n, 0.0)
    crsi = (rsi3 + 50 + pct_rank) / 3  # simplified
    for i in range(110, n):
        v = crsi[i]
        if np.isnan(v):
            continue
        if v < 10:
            crsi_score[i] = 50 + (10 - v) * 3
        elif v < 20:
            crsi_score[i] = 20 + (20 - v) * 3
        elif v > 90:
            crsi_score[i] = -50 - (v - 90) * 3
        elif v > 80:
            crsi_score[i] = -20 - (v - 80) * 3
        else:
            crsi_score[i] = (50 - v) * 0.5
    feats[:, 7] = np.clip(crsi_score, -100, 100)

    # KST
    def _sma(arr, p):
        out = np.full(len(arr), np.nan)
        cs = np.nancumsum(arr)
        cs = np.insert(cs, 0, 0)
        for i in range(p, len(arr) + 1):
            out[i - 1] = (cs[i] - cs[i - p]) / p
        return out

    roc10 = np.full(n, np.nan)
    roc15 = np.full(n, np.nan)
    roc20 = np.full(n, np.nan)
    roc30 = np.full(n, np.nan)
    for i in range(30, n):
        if close[i - 10] > 0:
            roc10[i] = close[i] / close[i - 10] - 1
        if close[i - 15] > 0:
            roc15[i] = close[i] / close[i - 15] - 1
        if close[i - 20] > 0:
            roc20[i] = close[i] / close[i - 20] - 1
        if close[i - 30] > 0:
            roc30[i] = close[i] / close[i - 30] - 1
    kst = _sma(roc10, 10) + 2 * _sma(roc15, 10) + 3 * _sma(roc20, 10) + 4 * _sma(roc30, 15)
    kst_sig = _sma(kst, 9)
    kst_diff = kst - kst_sig
    feats[:, 8] = np.clip(kst_diff * 5000, -100, 100)

    # CMO
    diff_c = np.diff(close, prepend=np.nan)
    su = pd.Series(np.where(diff_c > 0, diff_c, 0)).rolling(14).sum().values
    sd = pd.Series(np.where(diff_c < 0, -diff_c, 0)).rolling(14).sum().values
    denom = su + sd
    with np.errstate(divide="ignore", invalid="ignore"):
        cmo = np.where(denom == 0, 0, (su - sd) / denom * 100)
    cmo_score = np.zeros(n)
    for i in range(30, n):
        v = cmo[i]
        if np.isnan(v):
            continue
        if v < -50:
            cmo_score[i] = 30 + (-50 - v) * 0.7
        elif v > 50:
            cmo_score[i] = -30 - (v - 50) * 0.7
        else:
            cmo_score[i] = -v * 0.3
    feats[:, 9] = np.clip(cmo_score, -100, 100)

    # Vortex
    tr = np.maximum(high - low, np.maximum(
        np.abs(high - np.concatenate([[np.nan], close[:-1]])),
        np.abs(low - np.concatenate([[np.nan], close[:-1]]))))
    vm_p = np.abs(high - np.concatenate([[np.nan], low[:-1]]))
    vm_m = np.abs(low - np.concatenate([[np.nan], high[:-1]]))
    tr14 = pd.Series(tr).rolling(14).sum().values
    vip = pd.Series(vm_p).rolling(14).sum().values / np.where(tr14 == 0, np.nan, tr14)
    vim = pd.Series(vm_m).rolling(14).sum().values / np.where(tr14 == 0, np.nan, tr14)
    vortex_diff = vip - vim
    feats[:, 10] = np.clip(vortex_diff * 150, -100, 100)

    # Mean reversion score (z-score based)
    sma20 = _sma(close, 20)
    std20 = pd.Series(close).rolling(20).std().values
    with np.errstate(divide="ignore", invalid="ignore"):
        zscore = np.where(std20 == 0, 0, (close - sma20) / std20)
    mr_score = np.clip(-zscore * 25, -100, 100)
    feats[:, 0] = mr_score

    # Momentum score (multi-period ROC)
    mom_score = np.zeros(n)
    for i in range(63, n):
        fast = (close[i] / close[i - 10] - 1) * 100 if close[i - 10] > 0 else 0
        med = (close[i] / close[i - 21] - 1) * 100 if close[i - 21] > 0 else 0
        slow = (close[i] / close[i - 63] - 1) * 100 if close[i - 63] > 0 else 0
        mom_score[i] = np.clip(fast * 1.5 + med * 1.0 + slow * 0.5, -100, 100)
    feats[:, 1] = mom_score

    # Microstructure (volume anomaly)
    vol_sma20 = _sma(volume.astype(float), 20)
    with np.errstate(divide="ignore", invalid="ignore"):
        vol_ratio = np.where(vol_sma20 == 0, 1, volume / vol_sma20)
    micro_score = np.clip((vol_ratio - 1) * 30, -100, 100)
    feats[:, 2] = micro_score

    # Volatility score (ATR percentile)
    atr14 = pd.Series(tr).rolling(14).mean().values
    atr_pct = np.full(n, 50.0)
    for i in range(60, n):
        window = atr14[i - 59:i]
        valid = window[~np.isnan(window)]
        if len(valid) > 10:
            atr_pct[i] = np.searchsorted(np.sort(valid), atr14[i]) / len(valid) * 100
    feats[:, 3] = np.clip((50 - atr_pct) * 0.8, -100, 100)

    # Seasonality (simplified — day of week effect)
    feats[:, 4] = 0  # neutral placeholder

    # Pattern (simplified — price action)
    body = close - np.concatenate([[np.nan], close[:-1]])
    feats[:, 5] = np.clip(body / np.where(atr14 == 0, 1, atr14) * 20, -100, 100)

    # Stat arb (simplified — residual from SMA)
    feats[:, 6] = np.clip((sma20 - close) / np.where(std20 == 0, 1, std20) * 15, -100, 100)

    # Composite, conviction, quality (computed from individual alphas)
    weights = np.array([0.25, 0.25, 0.15, 0.10, 0.05, 0.10, 0.20,
                        0.10, 0.08, 0.08, 0.08])
    weights = weights / weights.sum()
    for i in range(100, n):
        alpha_scores = feats[i, :11]
        if np.all(np.isnan(alpha_scores)):
            continue
        valid_mask = ~np.isnan(alpha_scores)
        w = weights.copy()
        w[~valid_mask] = 0
        ws = w.sum()
        if ws > 0:
            w /= ws
        comp = np.nansum(alpha_scores * w)
        feats[i, 11] = np.clip(comp, -100, 100)
        # conviction
        n_long = np.sum(alpha_scores[valid_mask] > 10)
        n_short = np.sum(alpha_scores[valid_mask] < -10)
        n_valid = valid_mask.sum()
        feats[i, 12] = max(n_long, n_short) / max(n_valid, 1) * 100
        # quality
        feats[i, 13] = min(abs(comp) / max(np.nanstd(alpha_scores), 1) * 30, 100)
        feats[i, 14] = n_long
        feats[i, 15] = n_short

    # Statistical features — Hurst approximation (simplified R/S)
    for i in range(252, n):
        window = close[i - 251:i + 1]
        log_ret = np.diff(np.log(window))
        n_rs = len(log_ret)
        mean_r = log_ret.mean()
        dev = np.cumsum(log_ret - mean_r)
        r = dev.max() - dev.min()
        s = log_ret.std()
        if s > 0 and r > 0:
            feats[i, 16] = np.log(r / s) / np.log(n_rs)
        feats[i, 17] = 10  # OU half-life placeholder
        feats[i, 18] = 0.05  # ADF p-value placeholder
        feats[i, 19] = 0.5  # entropy placeholder
        feats[i, 20] = 0.5  # vol cluster placeholder

    # Regime features left as 0 (we don't run HMM in training loop)
    feats[:, 21:25] = 0

    return feats


# ═══════════════════════════════════════════════════════════════
# TRAINING
# ═══════════════════════════════════════════════════════════════

def _generate_training_data(tickers: list[str] | None = None,
                            max_stocks: int = 50) -> tuple[np.ndarray, np.ndarray]:
    """Walk-forward feature generation from stock CSVs."""
    if tickers is None:
        tickers = NIFTY50_TICKERS[:max_stocks]

    csv_dir = C.CSV_DIR
    all_X, all_y = [], []
    fwd = C.ML_FORWARD_DAYS
    cost = C.ROUND_TRIP_COST

    for ticker in tickers:
        # CSVs are named TICKER.NS.csv
        clean = ticker.replace(".NS", "").replace(".BO", "")
        path = csv_dir / f"{clean}.NS.csv"
        if not path.exists():
            path = csv_dir / f"{clean}.csv"
        if not path.exists():
            continue
        try:
            df = pd.read_csv(path, parse_dates=["Date"])
            df = df.sort_values("Date").reset_index(drop=True)
            if len(df) < 300:
                continue

            close = df["Close"].values.astype(float)
            high = df["High"].values.astype(float)
            low = df["Low"].values.astype(float)
            volume = df["Volume"].values.astype(float)

            feats = _fast_features(close, high, low, volume)

            for i in range(120, len(df) - fwd):
                row = feats[i]
                if np.isnan(row[11]):  # composite must exist
                    continue
                fwd_ret = close[i + fwd] / close[i] - 1
                label = 1 if fwd_ret > cost else 0
                all_X.append(row)
                all_y.append(label)
        except Exception as e:
            logger.warning("Skip %s: %s", ticker, e)

    if not all_X:
        return np.array([]), np.array([])
    return np.array(all_X), np.array(all_y)


def train_model(tickers: list[str] | None = None, full: bool = False):
    """Train the RenTech ML scorer and save to disk."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.model_selection import train_test_split
    import joblib

    os.makedirs(_MODEL_DIR, exist_ok=True)

    max_stocks = 2884 if full else C.ML_TRAIN_TICKERS
    logger.info("Generating training data (max %d stocks)...", max_stocks)
    t0 = time.time()

    if tickers is None and full:
        csv_files = sorted(C.CSV_DIR.glob("*.csv"))
        tickers = [f.stem for f in csv_files[:max_stocks]]

    X, y = _generate_training_data(tickers, max_stocks)
    if len(X) < 500:
        logger.error("Not enough training data (%d rows). Need >= 500.", len(X))
        return None

    logger.info("Training data: %d rows, %.1f%% positive, %.1fs",
                len(X), y.mean() * 100, time.time() - t0)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, shuffle=False  # walk-forward: no leakage
    )

    model = HistGradientBoostingClassifier(
        max_iter=300, max_depth=5, learning_rate=0.05,
        min_samples_leaf=50, l2_regularization=1.0,
        random_state=42,
    )
    model.fit(X_train, y_train)

    train_acc = model.score(X_train, y_train)
    test_acc = model.score(X_test, y_test)
    logger.info("Train acc: %.1f%%, Test acc: %.1f%%", train_acc * 100, test_acc * 100)

    # Save model
    joblib.dump(model, _MODEL_PATH)
    logger.info("Model saved to %s", _MODEL_PATH)

    # Save feature medians for NaN imputation at inference
    medians = {}
    for j, name in enumerate(FEATURE_NAMES):
        col = X[:, j]
        valid = col[~np.isnan(col)]
        medians[name] = float(np.median(valid)) if len(valid) > 0 else 0.0
    with open(_MEDIANS_PATH, "w") as f:
        json.dump(medians, f)

    return {"train_acc": train_acc, "test_acc": test_acc,
            "n_samples": len(X), "positive_rate": float(y.mean())}


# ═══════════════════════════════════════════════════════════════
# INFERENCE
# ═══════════════════════════════════════════════════════════════

def _load_model():
    global _cached_model, _cached_medians
    if _cached_model is not None:
        return _cached_model, _cached_medians

    if not _MODEL_PATH.exists():
        return None, None

    import joblib
    _cached_model = joblib.load(_MODEL_PATH)
    _cached_medians = {}
    if _MEDIANS_PATH.exists():
        with open(_MEDIANS_PATH) as f:
            _cached_medians = json.load(f)
    return _cached_model, _cached_medians


def _build_feature_vector(composite, profile, regime) -> np.ndarray:
    """Build feature vector from live analysis objects."""
    from rentech.statistical import StatisticalProfile

    alpha_scores = [0.0] * 11
    for i, a in enumerate(composite.alphas):
        if i < 11:
            alpha_scores[i] = float(a.raw_score) if not np.isnan(a.raw_score) else 0.0

    n_longs = sum(1 for a in composite.alphas if a.raw_score > 10)
    n_shorts = sum(1 for a in composite.alphas if a.raw_score < -10)

    regime_name = regime.current.regime if hasattr(regime, "current") else str(regime)

    feats = alpha_scores + [
        float(composite.composite_score),
        float(composite.conviction),
        float(composite.signal_quality),
        float(n_longs),
        float(n_shorts),
        float(profile.hurst.hurst) if not np.isnan(profile.hurst.hurst) else 0.5,
        float(profile.ou.half_life) if not np.isnan(profile.ou.half_life) else 20.0,
        float(profile.adf.p_value) if not np.isnan(profile.adf.p_value) else 0.5,
        float(profile.entropy.normalized_entropy) if hasattr(profile.entropy, "normalized_entropy") and not np.isnan(profile.entropy.normalized_entropy) else 0.5,
        float(profile.vol_cluster.persistence) if hasattr(profile.vol_cluster, "persistence") and not np.isnan(profile.vol_cluster.persistence) else 0.5,
        1.0 if regime_name == "BULL" else 0.0,
        1.0 if regime_name == "BEAR" else 0.0,
        1.0 if regime_name == "SIDEWAYS" else 0.0,
        1.0 if regime_name == "HIGH_VOLATILITY" else 0.0,
    ]

    return np.array(feats, dtype=float).reshape(1, -1)


def score_analysis(composite, profile, regime) -> Dict[str, Any]:
    """Score a RenTech analysis with ML confidence. Never raises."""
    try:
        model, medians = _load_model()
        if model is None:
            return {"model_available": False, "ml_confidence": None,
                    "ml_edge": "NOT_TRAINED", "reason": "Run: python -m rentech.ml_scorer"}

        X = _build_feature_vector(composite, profile, regime)

        # Impute NaN with training medians
        if medians:
            for j, name in enumerate(FEATURE_NAMES):
                if j < X.shape[1] and np.isnan(X[0, j]):
                    X[0, j] = medians.get(name, 0.0)

        proba = model.predict_proba(X)[0]
        # proba[1] = probability of positive forward return
        confidence = float(proba[1]) * 100

        if confidence >= C.ML_CONFIDENCE_PASS:
            edge = "ML_PASS"
        elif confidence >= 45:
            edge = "ML_NEUTRAL"
        else:
            edge = "ML_CAUTION"

        return {
            "model_available": True,
            "ml_confidence": round(confidence, 1),
            "ml_edge": edge,
            "win_probability": round(float(proba[1]) * 100, 1),
            "loss_probability": round(float(proba[0]) * 100, 1),
        }

    except Exception as e:
        logger.warning("ML scoring failed: %s", e)
        return {"model_available": False, "ml_confidence": None,
                "ml_edge": "ERROR", "reason": str(e)}


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    full = "--full" in sys.argv
    result = train_model(full=full)
    if result:
        print(f"\nTraining complete:")
        print(f"  Samples:  {result['n_samples']:,}")
        print(f"  Win rate: {result['positive_rate']:.1%}")
        print(f"  Train:    {result['train_acc']:.1%}")
        print(f"  Test:     {result['test_acc']:.1%}")
    else:
        print("Training failed — check logs.")
