"""
Brooks ML Scorer — inference using Brooks-trained models only.
No imports from ai_ml/. Completely independent.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

log = logging.getLogger("brooks.ml.scorer")

MODEL_DIR = Path(__file__).parent / "models"

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

SEQ_LEN = 20
XGB_THRESHOLD = 0.50
SEQ_THRESHOLD = 0.50

# Lazy-loaded singletons
_xgb = None
_xgb_medians = None
_lgb = None
_lgb_q25 = None
_lgb_q75 = None
_lgb_medians = None
_downside = None
_lstm = None


def _load_xgb():
    global _xgb, _xgb_medians
    if _xgb is not None:
        return _xgb
    p = MODEL_DIR / "brooks_xgb.joblib"
    if not p.exists():
        return None
    _xgb = joblib.load(p)
    mp = MODEL_DIR / "brooks_xgb_medians.joblib"
    _xgb_medians = joblib.load(mp) if mp.exists() else {}
    return _xgb


def _load_lgb():
    global _lgb, _lgb_q25, _lgb_q75, _lgb_medians
    if _lgb is not None:
        return _lgb
    p = MODEL_DIR / "brooks_lgb.joblib"
    if not p.exists():
        return None
    _lgb = joblib.load(p)
    q25p = MODEL_DIR / "brooks_lgb_q25.joblib"
    q75p = MODEL_DIR / "brooks_lgb_q75.joblib"
    mp = MODEL_DIR / "brooks_lgb_medians.joblib"
    _lgb_q25 = joblib.load(q25p) if q25p.exists() else None
    _lgb_q75 = joblib.load(q75p) if q75p.exists() else None
    _lgb_medians = joblib.load(mp) if mp.exists() else {}
    return _lgb


def _load_downside():
    global _downside
    if _downside is not None:
        return _downside
    p = MODEL_DIR / "brooks_downside.joblib"
    if not p.exists():
        return None
    _downside = joblib.load(p)
    return _downside


def _load_lstm():
    global _lstm
    if _lstm is not None:
        return _lstm
    p = MODEL_DIR / "brooks_lstm.pt"
    if not p.exists():
        return None
    try:
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

        _lstm = BrooksLSTM()
        _lstm.load_state_dict(torch.load(p, weights_only=True, map_location="cpu"))
        _lstm.eval()
        return _lstm
    except Exception as e:
        log.warning("Failed to load Brooks LSTM: %s", e)
        return None


def _extract_features(pick: dict, indicators: dict) -> dict:
    """Map pick + indicators to feature vector."""
    return {
        "confidence": pick.get("confidence", 50),
        "pa_score": pick.get("pa_score", 0),
        "risk_reward": pick.get("risk_reward", 1.0),
        "traders_equation": pick.get("traders_equation", 0),
        "trend_strength_num": STRENGTH_MAP.get(pick.get("strength", "MODERATE"), 1),
        "volume_ratio": indicators.get("volume_ratio", 1.0),
        "rsi14": indicators.get("rsi14", 50),
        "bbw": indicators.get("bbw", 0.05),
        "atr_pct": indicators.get("atr_pct", 2),
        "close_vs_sma20": indicators.get("close_vs_sma20", 0),
        "sma20_slope_5d": indicators.get("sma20_slope_5d", 0),
        "rsi_slope_5d": indicators.get("rsi_slope_5d", 0),
        "bbw_percentile_60d": indicators.get("bbw_percentile_60d", 0.5),
        "momentum_10d": indicators.get("momentum_10d", 0),
        "momentum_20d": indicators.get("momentum_20d", 0),
        "vol_ratio": indicators.get("vol_ratio", 1.0),
        "vol_trend_5d": indicators.get("vol_trend_5d", 0),
        "atr_percentile_60d": indicators.get("atr_percentile_60d", 0.5),
        "setup_encoded": SETUP_MAP.get(pick.get("setup", ""), 3),
        "phase_encoded": PHASE_MAP.get(pick.get("trend_phase", ""), 4),
        "ai_encoded": AI_MAP.get(pick.get("always_in", "FLAT"), 2),
        "eq_encoded": EQ_MAP.get(pick.get("equation_verdict", ""), 1),
        "buying_pressure": pick.get("buying_pressure", 50),
        "selling_pressure": pick.get("selling_pressure", 50),
        "stop_distance_pct": abs(pick.get("entry", pick.get("entry_price", 0)) - pick.get("stop", pick.get("stop_loss", 0))) / max(pick.get("entry", pick.get("entry_price", 1)), 1) * 100,
        "regime_score": pick.get("regime_score", 0),
    }


def _extract_sequence(ticker: str) -> np.ndarray | None:
    """Extract a 20-bar OHLCV sequence for LSTM."""
    from bb_squeeze.config import CSV_DIR
    csv_path = os.path.join(CSV_DIR, f"{ticker}.csv")
    if not os.path.exists(csv_path):
        return None

    try:
        df = pd.read_csv(csv_path, parse_dates=["Date"]).sort_values("Date")
        if len(df) < SEQ_LEN + 60:
            return None

        close = df["Close"].values.astype(float)
        high = df["High"].values.astype(float)
        low = df["Low"].values.astype(float)
        vol = df["Volume"].values.astype(float)

        c = close[-SEQ_LEN:]
        h = high[-SEQ_LEN:]
        l = low[-SEQ_LEN:]
        v = vol[-SEQ_LEN:]

        base = c[0] if c[0] > 0 else 1
        vol_base = v.mean() if v.mean() > 0 else 1

        return np.stack([
            c / base - 1,
            h / base - 1,
            l / base - 1,
            v / vol_base,
        ], axis=1).astype(np.float32)
    except Exception:
        return None


def score_picks(picks: list[dict]) -> None:
    """Score Brooks picks with all Brooks-trained ML models. Modifies in-place."""

    # ── XGBoost ──
    xgb_model = _load_xgb()
    for p in picks:
        indicators = p.get("_brooks_indicators", {})
        if not xgb_model or not indicators:
            p["bml_confidence"] = None
            p["bml_verdict"] = "BML_UNAVAILABLE"
            p["bml_downside"] = None
            continue

        feats = _extract_features(p, indicators)
        try:
            row = pd.DataFrame([feats])[FEATURES]
            if _xgb_medians:
                row = row.fillna(_xgb_medians)
            prob = float(xgb_model.predict_proba(row)[0, 1])
            p["bml_confidence"] = round(prob, 4)
            p["bml_verdict"] = "BML_PASS" if prob >= XGB_THRESHOLD else "BML_CAUTION"

            # SHAP
            try:
                import shap
                raw = xgb_model
                if hasattr(raw, "calibrated_classifiers_"):
                    raw = raw.calibrated_classifiers_[0].estimator
                explainer = shap.TreeExplainer(raw)
                sv = explainer.shap_values(row)
                if isinstance(sv, list):
                    sv = sv[1]
                vals = sv[0]
                top_idx = np.argsort(np.abs(vals))[-5:][::-1]
                p["bml_explanation"] = [
                    {"feature": FEATURES[i],
                     "impact": round(float(vals[i]), 4),
                     "direction": "+" if vals[i] > 0 else "-"}
                    for i in top_idx
                ]
            except Exception:
                p["bml_explanation"] = None

            # Downside
            ds_model = _load_downside()
            if ds_model:
                try:
                    dr_row = row.fillna(0)
                    p["bml_downside"] = round(float(ds_model.predict(dr_row)[0]), 4)
                except Exception:
                    p["bml_downside"] = None
            else:
                p["bml_downside"] = None

        except Exception as e:
            log.warning("Brooks XGBoost failed for %s: %s", p.get("ticker"), e)
            p["bml_confidence"] = None
            p["bml_verdict"] = "BML_UNAVAILABLE"
            p["bml_downside"] = None

    # Percentile within batch
    scored = [(i, p["bml_confidence"]) for i, p in enumerate(picks)
              if p.get("bml_confidence") is not None]
    if scored:
        scored.sort(key=lambda x: x[1])
        for rank, (idx, _) in enumerate(scored):
            picks[idx]["bml_percentile"] = round((rank + 1) / len(scored), 2)

    # ── LSTM ──
    lstm_model = _load_lstm()
    for p in picks:
        if not lstm_model:
            p["bml_seq_confidence"] = None
            p["bml_seq_verdict"] = "BSEQ_UNAVAILABLE"
            p["bml_seq_agreement"] = None
            continue

        seq = _extract_sequence(p.get("ticker", ""))
        if seq is None:
            p["bml_seq_confidence"] = None
            p["bml_seq_verdict"] = "BSEQ_UNAVAILABLE"
            p["bml_seq_agreement"] = None
            continue

        try:
            import torch
            with torch.no_grad():
                x = torch.from_numpy(seq).unsqueeze(0)
                prob = float(lstm_model(x).item())
            p["bml_seq_confidence"] = round(prob, 4)
            p["bml_seq_verdict"] = "BSEQ_PASS" if prob >= SEQ_THRESHOLD else "BSEQ_CAUTION"

            # Agreement with XGBoost
            xgb_v = p.get("bml_verdict")
            if xgb_v and xgb_v != "BML_UNAVAILABLE":
                xgb_pass = xgb_v == "BML_PASS"
                seq_pass = prob >= SEQ_THRESHOLD
                if xgb_pass and seq_pass:
                    p["bml_seq_agreement"] = "BOTH_AGREE"
                elif not xgb_pass and not seq_pass:
                    p["bml_seq_agreement"] = "BOTH_CAUTION"
                else:
                    p["bml_seq_agreement"] = "DISAGREE"
            else:
                p["bml_seq_agreement"] = None
        except Exception as e:
            log.warning("Brooks LSTM failed for %s: %s", p.get("ticker"), e)
            p["bml_seq_confidence"] = None
            p["bml_seq_verdict"] = "BSEQ_UNAVAILABLE"
            p["bml_seq_agreement"] = None

    # ── LightGBM conviction ──
    lgb_model = _load_lgb()
    for p in picks:
        indicators = p.get("_brooks_indicators", {})
        if not lgb_model or not indicators:
            p["bml_conviction"] = None
            p["bml_conviction_label"] = None
            p["bml_conviction_ci"] = None
            continue

        feats = _extract_features(p, indicators)
        try:
            row = pd.DataFrame([feats])[FEATURES]
            if _lgb_medians:
                row = row.fillna(_lgb_medians)

            raw_r = float(lgb_model.predict(row)[0])
            score = max(0, min(100, (raw_r + 1) * 33))  # map r_multiple to 0-100

            if score >= 60:
                label = "HIGH"
            elif score >= 35:
                label = "MODERATE"
            else:
                label = "LOW"

            ci = None
            if _lgb_q25 and _lgb_q75:
                lo = float(_lgb_q25.predict(row)[0])
                hi = float(_lgb_q75.predict(row)[0])
                ci_lo = max(0, min(100, (lo + 1) * 33))
                ci_hi = max(0, min(100, (hi + 1) * 33))
                ci = [round(ci_lo, 1), round(ci_hi, 1)]

            p["bml_conviction"] = round(score, 1)
            p["bml_conviction_label"] = label
            p["bml_conviction_ci"] = ci
        except Exception as e:
            log.warning("Brooks LightGBM failed for %s: %s", p.get("ticker"), e)
            p["bml_conviction"] = None
            p["bml_conviction_label"] = None
            p["bml_conviction_ci"] = None


def is_available() -> bool:
    """Check if Brooks ML models are trained."""
    return (MODEL_DIR / "brooks_xgb.joblib").exists()
