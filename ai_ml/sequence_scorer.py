"""
ai_ml/sequence_scorer.py — LSTM Sequence Pattern Scorer

Feeds the last 20 bars as a time series into a small LSTM to learn
temporal patterns (bandwidth tightening, volume ramp-ups) that
XGBoost treats as isolated snapshots.

Separate module — if torch is not installed, gracefully returns
None for all fields. Core BB system is never touched.
"""
from __future__ import annotations

import logging
import os

import numpy as np
import pandas as pd

from ai_ml.config import (
    CSV_DIR, SEQUENCE_MODEL_PATH, SEQ_LOOKBACK, SEQ_FEATURES,
    SEQ_CONFIDENCE_THRESHOLD, MODELS_DIR,
)

logger = logging.getLogger("ai_ml.sequence_scorer")

_seq_model = None


def _load_model():
    global _seq_model
    if _seq_model is not None:
        return _seq_model
    if not os.path.exists(SEQUENCE_MODEL_PATH):
        logger.info("Sequence LSTM not found — run train_sequence_model() first")
        return None
    try:
        import torch
        from ai_ml.sequence_scorer import SequenceLSTM
        device = torch.device("cpu")
        model = SequenceLSTM()
        model.load_state_dict(torch.load(SEQUENCE_MODEL_PATH, map_location=device, weights_only=True))
        model.eval()
        _seq_model = model
        return model
    except Exception as e:
        logger.warning("Failed to load sequence model: %s", e)
        return None


# ── Model Definition ────────────────────────────────────────────

try:
    import torch
    import torch.nn as nn

    class SequenceLSTM(nn.Module):
        def __init__(self, n_features=6, hidden=64, n_layers=2, dropout=0.3):
            super().__init__()
            self.lstm = nn.LSTM(n_features, hidden, n_layers,
                                batch_first=True, dropout=dropout)
            self.head = nn.Sequential(
                nn.Linear(hidden, 32),
                nn.ReLU(),
                nn.Dropout(dropout),
                nn.Linear(32, 1),
                nn.Sigmoid(),
            )

        def forward(self, x):
            _, (h_n, _) = self.lstm(x)
            return self.head(h_n[-1]).squeeze(-1)

except ImportError:
    pass


# ── Training ────────────────────────────────────────────────────

def train_sequence_model(csv_dir: str | None = None,
                         training_parquet: str | None = None,
                         epochs: int = 30,
                         batch_size: int = 256,
                         lr: float = 1e-3) -> dict:
    """
    Train the LSTM on labeled samples. For each sample in the training
    parquet, loads its stock CSV and extracts a 20-bar lookback window.
    """
    try:
        import torch
        import torch.nn as nn
        from torch.utils.data import TensorDataset, DataLoader
    except ImportError:
        return {"status": "error", "error": "torch not installed. pip install torch"}

    from ai_ml.config import TRAINING_DATA_FILE

    parquet_path = training_parquet or TRAINING_DATA_FILE
    if not os.path.exists(parquet_path):
        return {"status": "error", "error": f"Training data not found: {parquet_path}"}

    csv_dir = csv_dir or CSV_DIR

    tdf = pd.read_parquet(parquet_path)
    # Support both column naming conventions
    if "label" not in tdf.columns and "result" in tdf.columns:
        tdf["label"] = tdf["result"]
    required = {"ticker", "date", "label"}
    if not required.issubset(tdf.columns):
        return {"status": "error", "error": f"Training parquet missing columns: {required - set(tdf.columns)}"}

    print(f"Sequence LSTM: building sequences from {len(tdf)} labeled samples...", flush=True)

    csv_cache: dict[str, pd.DataFrame] = {}
    date_index_cache: dict[str, dict] = {}
    sequences = []
    labels = []

    for _, row in tdf.iterrows():
        ticker = row["ticker"]
        label = int(row["label"])
        trade_date = str(row["date"])[:10]

        if ticker not in csv_cache:
            csv_path = os.path.join(csv_dir, f"{ticker}.csv")
            if not os.path.exists(csv_path):
                continue
            try:
                stock_df = pd.read_csv(csv_path, parse_dates=["Date"])
                csv_cache[ticker] = stock_df
                date_index_cache[ticker] = {
                    str(d)[:10]: i for i, d in enumerate(stock_df["Date"])
                }
            except Exception:
                continue

        bar_idx = date_index_cache[ticker].get(trade_date)
        if bar_idx is None or bar_idx < SEQ_LOOKBACK + 60:
            continue

        df = csv_cache[ticker]
        seq = _extract_sequence(df, bar_idx)
        if seq is not None:
            sequences.append(seq)
            labels.append(label)

    if len(sequences) < 100:
        return {"status": "error", "error": f"Only {len(sequences)} valid sequences — need ≥100"}

    X = np.array(sequences, dtype=np.float32)
    y = np.array(labels, dtype=np.float32)
    print(f"  Built {len(X)} sequences ({y.sum():.0f} WIN, {len(y) - y.sum():.0f} LOSS)", flush=True)

    # Temporal split: last 20% for validation
    split = int(len(X) * 0.8)
    X_train, X_val = X[:split], X[split:]
    y_train, y_val = y[:split], y[split:]

    train_ds = TensorDataset(torch.from_numpy(X_train), torch.from_numpy(y_train))
    val_ds = TensorDataset(torch.from_numpy(X_val), torch.from_numpy(y_val))
    train_dl = DataLoader(train_ds, batch_size=batch_size, shuffle=True)
    val_dl = DataLoader(val_ds, batch_size=batch_size)

    model = SequenceLSTM()
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    criterion = nn.BCELoss()
    best_val_loss = float("inf")
    patience_counter = 0

    for epoch in range(epochs):
        model.train()
        train_loss = 0.0
        for xb, yb in train_dl:
            optimizer.zero_grad()
            pred = model(xb)
            loss = criterion(pred, yb)
            loss.backward()
            optimizer.step()
            train_loss += loss.item() * len(xb)
        train_loss /= len(train_ds)

        model.eval()
        val_loss = 0.0
        correct = 0
        with torch.no_grad():
            for xb, yb in val_dl:
                pred = model(xb)
                val_loss += criterion(pred, yb).item() * len(xb)
                correct += ((pred > 0.5).float() == yb).sum().item()
        val_loss /= len(val_ds)
        val_acc = correct / len(val_ds)

        if (epoch + 1) % 5 == 0 or epoch == 0:
            print(f"  Epoch {epoch+1}/{epochs}  train_loss={train_loss:.4f}  "
                  f"val_loss={val_loss:.4f}  val_acc={val_acc:.3f}", flush=True)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            patience_counter = 0
            os.makedirs(MODELS_DIR, exist_ok=True)
            torch.save(model.state_dict(), SEQUENCE_MODEL_PATH)
        else:
            patience_counter += 1
            if patience_counter >= 7:
                print(f"  Early stopping at epoch {epoch+1}", flush=True)
                break

    global _seq_model
    model.load_state_dict(torch.load(SEQUENCE_MODEL_PATH, map_location="cpu", weights_only=True))
    model.eval()
    _seq_model = model

    return {
        "status": "ok",
        "sequences": len(X),
        "val_accuracy": round(val_acc, 4),
        "best_val_loss": round(best_val_loss, 4),
        "epochs_trained": epoch + 1,
    }


def _extract_sequence(df: pd.DataFrame, bar_idx: int) -> np.ndarray | None:
    """Extract a (SEQ_LOOKBACK, 6) sequence ending at bar_idx."""
    if bar_idx < SEQ_LOOKBACK + 20 or bar_idx >= len(df):
        return None

    try:
        window = df.iloc[bar_idx - SEQ_LOOKBACK:bar_idx]
        if len(window) < SEQ_LOOKBACK:
            return None

        close = window["Close"].astype(float).values
        high = window["High"].astype(float).values
        low = window["Low"].astype(float).values
        volume = window["Volume"].astype(float).values

        sma20_val = df["Close"].astype(float).iloc[max(0, bar_idx-40):bar_idx].rolling(20).mean().iloc[-SEQ_LOOKBACK:]
        if len(sma20_val) < SEQ_LOOKBACK:
            return None
        sma20_arr = sma20_val.values

        # close_norm
        close_norm = close / np.where(sma20_arr > 0, sma20_arr, 1.0)

        # bbw
        std20 = df["Close"].astype(float).iloc[max(0, bar_idx-40):bar_idx].rolling(20).std().iloc[-SEQ_LOOKBACK:].values
        bbw = (4 * std20) / np.where(sma20_arr > 0, sma20_arr, 1.0)

        # rsi_norm (RSI / 100)
        delta = np.diff(close, prepend=close[0])
        gain = np.where(delta > 0, delta, 0.0)
        loss_arr = np.where(delta < 0, -delta, 0.0)
        avg_g = pd.Series(gain).ewm(alpha=1/14, min_periods=1, adjust=False).mean().values
        avg_l = pd.Series(loss_arr).ewm(alpha=1/14, min_periods=1, adjust=False).mean().values
        rs = avg_g / np.where(avg_l > 0, avg_l, 1e-10)
        rsi_norm = (100 - 100 / (1 + rs)) / 100.0

        # atr_norm (ATR% / 10)
        prev_c = np.roll(close, 1)
        prev_c[0] = close[0]
        tr = np.maximum(high - low, np.maximum(np.abs(high - prev_c), np.abs(low - prev_c)))
        atr = pd.Series(tr).rolling(14, min_periods=1).mean().values
        atr_norm = (atr / np.where(close > 0, close, 1.0) * 100) / 10.0

        # vol_ratio
        vol_ma = pd.Series(volume).rolling(20, min_periods=1).mean().values
        vol_ratio = volume / np.where(vol_ma > 0, vol_ma, 1.0)

        # momentum_norm (20d momentum / 10)
        close_full = df["Close"].astype(float).values
        start = bar_idx - SEQ_LOOKBACK
        mom = np.zeros(SEQ_LOOKBACK)
        for j in range(SEQ_LOOKBACK):
            idx = start + j
            idx_20 = idx - 20
            if idx_20 >= 0 and close_full[idx_20] > 0:
                mom[j] = (close_full[idx] / close_full[idx_20] - 1) * 100 / 10.0

        seq = np.column_stack([close_norm, bbw, rsi_norm, atr_norm, vol_ratio, mom])
        seq = np.nan_to_num(seq, nan=0.0, posinf=0.0, neginf=0.0)

        return seq.astype(np.float32)
    except Exception:
        return None


# ── Inference ───────────────────────────────────────────────────

def score_picks_sequence(picks: list[dict]) -> None:
    """Add LSTM sequence scores to each pick. Modifies picks in-place."""
    model = _load_model()

    for pick in picks:
        if model is None:
            pick["seq_confidence"] = None
            pick["seq_verdict"] = "SEQ_UNAVAILABLE"
            pick["seq_agreement"] = None
            continue

        try:
            seq = _extract_sequence_from_pick(pick)
            if seq is None:
                pick["seq_confidence"] = None
                pick["seq_verdict"] = "SEQ_UNAVAILABLE"
                pick["seq_agreement"] = None
                continue

            import torch
            with torch.no_grad():
                x = torch.from_numpy(seq).unsqueeze(0)
                prob = float(model(x).item())

            pick["seq_confidence"] = round(prob, 4)
            pick["seq_verdict"] = "SEQ_PASS" if prob >= SEQ_CONFIDENCE_THRESHOLD else "SEQ_CAUTION"

            # Agreement with XGBoost
            ml_verdict = pick.get("ml_verdict")
            if ml_verdict and ml_verdict != "ML_UNAVAILABLE":
                ml_pass = ml_verdict == "ML_PASS"
                seq_pass = prob >= SEQ_CONFIDENCE_THRESHOLD
                if ml_pass and seq_pass:
                    pick["seq_agreement"] = "BOTH_AGREE"
                elif not ml_pass and not seq_pass:
                    pick["seq_agreement"] = "BOTH_CAUTION"
                else:
                    pick["seq_agreement"] = "DISAGREE"
            else:
                pick["seq_agreement"] = None

        except Exception as e:
            logger.warning("Sequence scoring failed for %s: %s", pick.get("ticker"), e)
            pick["seq_confidence"] = None
            pick["seq_verdict"] = "SEQ_UNAVAILABLE"
            pick["seq_agreement"] = None


def _extract_sequence_from_pick(pick: dict) -> np.ndarray | None:
    """Extract a 20-bar sequence from a pick's stock CSV."""
    ticker = pick.get("ticker")
    if not ticker:
        return None

    csv_path = os.path.join(CSV_DIR, f"{ticker}.csv")
    if not os.path.exists(csv_path):
        return None

    try:
        df = pd.read_csv(csv_path, parse_dates=["Date"])
        if len(df) < SEQ_LOOKBACK + 60:
            return None
        return _extract_sequence(df, len(df) - 1)
    except Exception:
        return None
