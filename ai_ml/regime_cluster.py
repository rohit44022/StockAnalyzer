"""
ai_ml/regime_cluster.py — Unsupervised Market State Discovery

Uses UMAP dimensionality reduction + KMeans clustering to discover
hidden market regimes from 8 indicator dimensions. Each pick gets
a cluster_id, human-readable label, and confidence score.

Separate module — if umap-learn is not installed, gracefully returns
None for all fields. Core BB system is never touched.
"""
from __future__ import annotations

import logging
import os

import numpy as np
import pandas as pd

from ai_ml.config import (
    CSV_DIR, REGIME_CLUSTER_MODEL, CLUSTER_FEATURES, MODELS_DIR,
)

logger = logging.getLogger("ai_ml.regime_cluster")

_cluster_bundle = None


def _load_bundle():
    global _cluster_bundle
    if _cluster_bundle is not None:
        return _cluster_bundle
    if not os.path.exists(REGIME_CLUSTER_MODEL):
        logger.info("Regime cluster model not found — run train_regime_clusters() first")
        return None
    try:
        import joblib
        _cluster_bundle = joblib.load(REGIME_CLUSTER_MODEL)
        return _cluster_bundle
    except Exception as e:
        logger.warning("Failed to load regime cluster model: %s", e)
        return None


def train_regime_clusters(csv_dir: str | None = None,
                          n_clusters: int = 6,
                          sample_size: int = 500_000) -> dict:
    """
    Train UMAP + KMeans on sampled bars from all stock CSVs.
    Saves scaler + reducer + clusterer as a single joblib bundle.
    """
    try:
        import umap
    except ImportError:
        return {"status": "error", "error": "umap-learn not installed. pip install umap-learn"}

    from sklearn.preprocessing import StandardScaler
    from sklearn.cluster import KMeans
    import joblib

    csv_dir = csv_dir or CSV_DIR
    csv_files = [os.path.join(csv_dir, f) for f in os.listdir(csv_dir)
                 if f.endswith(".csv")]

    if not csv_files:
        return {"status": "error", "error": f"No CSV files in {csv_dir}"}

    print(f"Regime Cluster: loading features from {len(csv_files)} stocks...", flush=True)

    all_rows = []
    for csv_path in csv_files:
        try:
            df = pd.read_csv(csv_path, parse_dates=["Date"])
            if len(df) < 100:
                continue
            feats = _compute_cluster_features_df(df)
            if feats is not None and len(feats) > 0:
                all_rows.append(feats)
        except Exception:
            continue

    if not all_rows:
        return {"status": "error", "error": "No valid data extracted"}

    data = pd.concat(all_rows, ignore_index=True)
    data = data.dropna()
    print(f"  Total bars with valid features: {len(data)}", flush=True)

    # Sample if too large
    if len(data) > sample_size:
        data = data.sample(n=sample_size, random_state=42)
        print(f"  Sampled down to {sample_size} bars", flush=True)

    X = data[CLUSTER_FEATURES].values

    # Standardize
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # UMAP dimensionality reduction
    print("  Running UMAP (this may take a minute)...", flush=True)
    reducer = umap.UMAP(n_components=3, n_neighbors=30, min_dist=0.1,
                        metric="euclidean", random_state=42, verbose=False)
    X_embedded = reducer.fit_transform(X_scaled)

    # KMeans clustering
    print(f"  Clustering into {n_clusters} regimes...", flush=True)
    km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = km.fit_predict(X_embedded)

    # Auto-label clusters based on median feature values
    cluster_labels = _auto_label_clusters(X, labels, n_clusters)

    # Save bundle
    bundle = {
        "scaler": scaler,
        "reducer": reducer,
        "clusterer": km,
        "cluster_labels": cluster_labels,
        "feature_names": CLUSTER_FEATURES,
        "n_clusters": n_clusters,
    }
    os.makedirs(MODELS_DIR, exist_ok=True)
    joblib.dump(bundle, REGIME_CLUSTER_MODEL)

    # Print cluster summary
    print(f"\n  Regime Clusters Discovered:")
    unique, counts = np.unique(labels, return_counts=True)
    for cid, cnt in zip(unique, counts):
        pct = cnt / len(labels) * 100
        print(f"    Cluster {cid}: {cluster_labels.get(cid, '?')} ({cnt} bars, {pct:.1f}%)")

    global _cluster_bundle
    _cluster_bundle = bundle

    return {
        "status": "ok",
        "n_clusters": n_clusters,
        "total_bars": len(data),
        "cluster_labels": cluster_labels,
        "cluster_sizes": dict(zip(unique.tolist(), counts.tolist())),
    }


def _compute_cluster_features_df(df: pd.DataFrame) -> pd.DataFrame | None:
    """Compute the 8 clustering features from a stock DataFrame."""
    if len(df) < 60:
        return None

    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    volume = df["Volume"].astype(float)

    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    upper = sma20 + 2 * std20
    lower = sma20 - 2 * std20
    bbw = (upper - lower) / sma20

    # RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0/14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi14 = 100.0 - (100.0 / (1.0 + rs))

    # ATR
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean()
    atr14_pct = atr14 / close * 100

    # Volume ratio
    vol_ma = volume.rolling(20).mean()
    vol_ratio = volume / vol_ma

    # Price vs SMA20
    close_vs_sma20 = (close - sma20) / sma20 * 100

    # CMF
    hl_range = (high - low).replace(0, np.nan)
    mfm = ((close - low) - (high - close)) / hl_range
    mfv = (mfm * volume).fillna(0)
    cmf = mfv.rolling(20).sum() / volume.rolling(20).sum()

    # MFI
    tp = (high + low + close) / 3.0
    raw_mf = tp * volume
    pos_mf = raw_mf.where(tp > tp.shift(1), 0.0)
    neg_mf = raw_mf.where(tp < tp.shift(1), 0.0)
    mfr = pos_mf.rolling(10).sum() / neg_mf.rolling(10).sum().replace(0, np.nan)
    mfi = 100 - (100 / (1 + mfr))

    # Momentum
    momentum_20d = (close / close.shift(20) - 1) * 100

    result = pd.DataFrame({
        "bbw": bbw,
        "rsi14": rsi14,
        "atr14_pct": atr14_pct,
        "vol_ratio": vol_ratio,
        "close_vs_sma20": close_vs_sma20,
        "cmf": cmf.fillna(0),
        "mfi": mfi.fillna(50),
        "price_momentum_20d": momentum_20d,
    })

    return result.iloc[60:]  # skip warmup


def _auto_label_clusters(X: np.ndarray, labels: np.ndarray,
                         n_clusters: int) -> dict[int, str]:
    """Generate human-readable names based on median feature values per cluster."""
    feature_names = CLUSTER_FEATURES
    cluster_labels = {}

    for cid in range(n_clusters):
        mask = labels == cid
        if not mask.any():
            cluster_labels[cid] = f"Cluster {cid}"
            continue

        medians = np.median(X[mask], axis=0)
        parts = []

        # BBW characterization
        bbw_med = medians[0]
        if bbw_med < 0.08:
            parts.append("Tight Squeeze")
        elif bbw_med < 0.15:
            parts.append("Moderate BB")
        else:
            parts.append("Wide Bands")

        # RSI characterization
        rsi_med = medians[1]
        if rsi_med > 65:
            parts.append("Overbought")
        elif rsi_med < 35:
            parts.append("Oversold")
        else:
            parts.append("Neutral RSI")

        # Volume characterization
        vol_med = medians[3]
        if vol_med > 1.5:
            parts.append("High Vol")
        elif vol_med < 0.7:
            parts.append("Low Vol")

        # Momentum
        mom_med = medians[7]
        if mom_med > 5:
            parts.append("Bullish")
        elif mom_med < -5:
            parts.append("Bearish")

        cluster_labels[cid] = " + ".join(parts) if parts else f"Cluster {cid}"

    return cluster_labels


def enrich_picks_with_clusters(picks: list[dict]) -> None:
    """Add regime cluster data to each pick. Modifies picks in-place."""
    bundle = _load_bundle()

    for pick in picks:
        if bundle is None:
            pick["regime_cluster_id"] = None
            pick["regime_cluster_label"] = None
            pick["regime_cluster_confidence"] = None
            continue

        try:
            features = _extract_cluster_features_from_pick(pick)
            if features is None:
                pick["regime_cluster_id"] = None
                pick["regime_cluster_label"] = None
                pick["regime_cluster_confidence"] = None
                continue

            X = np.array([features])
            X_scaled = bundle["scaler"].transform(X)
            X_embedded = bundle["reducer"].transform(X_scaled)
            cid = int(bundle["clusterer"].predict(X_embedded)[0])

            # Confidence = inverse distance to centroid (normalized)
            centroid = bundle["clusterer"].cluster_centers_[cid]
            dist = np.linalg.norm(X_embedded[0] - centroid)
            max_dist = max(np.linalg.norm(bundle["clusterer"].cluster_centers_ - centroid, axis=1).max(), 1e-6)
            confidence = max(0, 1.0 - dist / max_dist)

            pick["regime_cluster_id"] = cid
            pick["regime_cluster_label"] = bundle["cluster_labels"].get(cid, f"Cluster {cid}")
            pick["regime_cluster_confidence"] = round(float(confidence), 3)

        except Exception as e:
            logger.warning("Regime cluster failed for %s: %s", pick.get("ticker"), e)
            pick["regime_cluster_id"] = None
            pick["regime_cluster_label"] = None
            pick["regime_cluster_confidence"] = None


def _extract_cluster_features_from_pick(pick: dict) -> list[float] | None:
    """Extract the 8 clustering features from a live pick dict."""
    bb = pick.get("bb_data", {})
    indicators = bb.get("indicators", {})
    price = pick.get("price", 0) or pick.get("current_price", 0)

    bbw = indicators.get("bbw") or indicators.get("bandwidth")
    rsi = indicators.get("rsi") or indicators.get("rsi14")
    atr = indicators.get("atr") or indicators.get("atr14")
    sma20 = indicators.get("sma20") or indicators.get("sma_20")
    volume = indicators.get("volume", 0)
    vol_avg = indicators.get("vol_avg") or indicators.get("vol_ma") or indicators.get("avg_volume", 1)

    if not all([bbw, rsi, atr, sma20, price]):
        return None

    atr_pct = atr / price * 100 if price > 0 else 0
    vol_ratio = volume / vol_avg if vol_avg and vol_avg > 0 else 1.0
    close_vs_sma20 = (price - sma20) / sma20 * 100 if sma20 > 0 else 0

    cmf = indicators.get("CMF") or indicators.get("cmf") or 0
    mfi = indicators.get("MFI") or indicators.get("mfi") or 50
    momentum = indicators.get("momentum_20d") or indicators.get("price_momentum_20d") or 0

    # Order must match CLUSTER_FEATURES
    return [bbw, rsi, atr_pct, vol_ratio, close_vs_sma20, cmf, mfi, momentum]
