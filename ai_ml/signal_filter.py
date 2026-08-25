"""
ai_ml/signal_filter.py — ML Signal Filter (XGBoost)

Loads the trained model and scores picks with ML confidence.
Adds ml_confidence (0-100%) and ml_verdict (ML_PASS / ML_CAUTION)
to each pick dict WITHOUT modifying any existing field.
"""
from __future__ import annotations

import os
import logging

import numpy as np
import pandas as pd

from ai_ml.config import SIGNAL_FILTER_MODEL, ML_FEATURES, ML_CONFIDENCE_THRESHOLD

logger = logging.getLogger("ai_ml.signal_filter")

_model = None
_downside_model = None
_MODEL_PATH = SIGNAL_FILTER_MODEL
_feature_medians = None


def _load_model():
    global _model, _downside_model, _feature_medians
    if _model is not None:
        return _model
    if not os.path.exists(_MODEL_PATH):
        logger.warning("ML model not found at %s — run ai_ml.trainer first", _MODEL_PATH)
        return None
    try:
        import joblib
        _model = joblib.load(_MODEL_PATH)
        model_dir = os.path.dirname(_MODEL_PATH)
        # Load training medians for sklearn fallback NaN handling
        medians_path = os.path.join(model_dir, "feature_medians.json")
        if os.path.exists(medians_path):
            import json
            with open(medians_path) as f:
                _feature_medians = json.load(f)
        # Load downside risk model if available
        downside_path = os.path.join(model_dir, "downside_model.joblib")
        if os.path.exists(downside_path):
            _downside_model = joblib.load(downside_path)
        return _model
    except Exception as e:
        logger.warning("Failed to load ML model: %s", e)
        return None


def _extract_features_from_pick(pick: dict) -> dict | None:
    """
    Extract ML features from a live Top Picks dict.
    Maps existing pick fields to the feature vector the model expects.
    """
    bb = pick.get("bb_data", {})
    ta = pick.get("ta_snapshot", {})

    indicators = bb.get("indicators", {})
    bbw = indicators.get("bbw") or indicators.get("bandwidth")
    rsi = indicators.get("rsi") or indicators.get("rsi14")
    atr = indicators.get("atr") or indicators.get("atr14")
    price = pick.get("price", 0)
    sma20 = indicators.get("sma20") or indicators.get("sma_20")
    upper = indicators.get("upper_band") or indicators.get("upper")
    lower = indicators.get("lower_band") or indicators.get("lower")
    volume = indicators.get("volume", 0)
    vol_avg = indicators.get("vol_avg") or indicators.get("vol_ma") or indicators.get("avg_volume", 1)

    if not all([price, sma20, upper, lower]) or price == 0 or sma20 == 0:
        return None

    atr_pct = (atr / price * 100) if atr and price else None
    vol_ratio = (volume / vol_avg) if vol_avg and vol_avg > 0 else None

    feats = {
        "bbw":               bbw,
        "rsi14":             rsi,
        "atr14_pct":         atr_pct,
        "vol_ratio":         vol_ratio,
        "close_vs_sma20":    (price - sma20) / sma20 * 100,
        "close_vs_upper":    (price - upper) / sma20 * 100,
        "close_vs_lower":    (price - lower) / sma20 * 100,
        "sma20_slope_5d":    indicators.get("sma20_slope"),
        "rsi14_slope_5d":    indicators.get("rsi_slope"),
        "bbw_percentile_60d": indicators.get("bbw_percentile"),
        "vol_trend_5d":      indicators.get("vol_trend"),
        "price_momentum_10d": indicators.get("momentum_10d"),
        "price_momentum_20d": indicators.get("momentum_20d"),
        "atr14_percentile_60d": indicators.get("atr_percentile"),
        "method":            pick.get("method", "M2"),
    }

    return feats


def _get_raw_model(model):
    """Unwrap CalibratedClassifierCV to get the fitted tree model for SHAP/categorical."""
    if hasattr(model, 'calibrated_classifiers_'):
        return model.calibrated_classifiers_[0].estimator
    return getattr(model, 'estimator', model)


def score_picks(picks: list[dict]) -> list[dict]:
    """
    Score each pick with ML confidence. Adds fields but never modifies existing ones.

    Added fields per pick:
      - ml_confidence:  float 0.0-1.0 (probability of WIN)
      - ml_verdict:     "ML_PASS" | "ML_CAUTION" | "ML_UNAVAILABLE"
      - ml_percentile:  rank within this batch (1.0 = highest confidence)
    """
    model = _load_model()
    if model is None:
        for pick in picks:
            pick["ml_confidence"] = None
            pick["ml_verdict"] = "ML_UNAVAILABLE"
            pick["ml_percentile"] = None
        return picks

    for pick in picks:
        feats = _extract_features_from_pick(pick)
        if feats is None:
            pick["ml_confidence"] = None
            pick["ml_verdict"] = "ML_UNAVAILABLE"
            pick["ml_percentile"] = None
            continue

        try:
            row = pd.DataFrame([feats])
            available = [c for c in ML_FEATURES if c in row.columns]
            row = row[available]
            # Convert categorical columns for XGBoost native handling
            from ai_ml.config import ML_CATEGORICAL_FEATURES
            _inner = _get_raw_model(model)
            _is_xgb = hasattr(_inner, 'get_booster')
            for cat_col in ML_CATEGORICAL_FEATURES:
                if cat_col in row.columns:
                    if _is_xgb:
                        row[cat_col] = row[cat_col].astype("category")
                    else:
                        row = row.drop(columns=[cat_col])
            if not _is_xgb and _feature_medians:
                row = row.fillna(_feature_medians)
            prob = float(model.predict_proba(row)[0, 1])
            pick["ml_confidence"] = round(prob, 4)
            pick["ml_verdict"] = "ML_PASS" if prob >= ML_CONFIDENCE_THRESHOLD else "ML_CAUTION"

            # SHAP explanation — top 5 features driving this prediction
            pick["ml_explanation"] = _explain_row(row, _inner if _is_xgb else model)

            # Downside risk (expectile regression at α=0.25, numeric features only)
            if _downside_model is not None:
                try:
                    dr_row = row.select_dtypes(include="number")
                    dr = float(_downside_model.predict(dr_row)[0])
                    pick["ml_downside_risk"] = round(dr, 4)
                except Exception:
                    pick["ml_downside_risk"] = None
            else:
                pick["ml_downside_risk"] = None
        except Exception as e:
            logger.warning("ML scoring failed for %s: %s", pick.get("ticker"), e)
            pick["ml_confidence"] = None
            pick["ml_verdict"] = "ML_UNAVAILABLE"
            pick["ml_percentile"] = None

    # Compute percentile within batch
    scored = [(i, p["ml_confidence"]) for i, p in enumerate(picks) if p.get("ml_confidence") is not None]
    if scored:
        scored.sort(key=lambda x: x[1])
        for rank, (idx, _) in enumerate(scored):
            picks[idx]["ml_percentile"] = round((rank + 1) / len(scored), 2)

    return picks


def _explain_row(row: pd.DataFrame, raw_model) -> list[dict] | None:
    """SHAP explanation for a single prediction row. Returns top 5 drivers."""
    try:
        import shap
        explainer = shap.TreeExplainer(raw_model)
        sv = explainer.shap_values(row)
        if isinstance(sv, list):
            sv = sv[1]
        vals = sv[0]
        cols = row.columns.tolist()
        # Only report numeric features (skip categorical like 'method')
        pairs = [(f, v) for f, v in zip(cols, vals) if f not in ("method",)]
        pairs = sorted(pairs, key=lambda x: abs(x[1]), reverse=True)[:5]
        return [
            {"feature": f, "impact": round(float(v), 4),
             "direction": "WIN" if v > 0 else "LOSS"}
            for f, v in pairs
        ]
    except Exception:
        return None


def explain_pick(pick: dict) -> dict | None:
    """Standalone SHAP explanation for a single pick dict."""
    model = _load_model()
    if model is None:
        return None
    feats = _extract_features_from_pick(pick)
    if feats is None:
        return None
    try:
        from ai_ml.config import ML_CATEGORICAL_FEATURES
        row = pd.DataFrame([feats])
        available = [c for c in ML_FEATURES if c in row.columns]
        row = row[available]
        _inner = _get_raw_model(model)
        _is_xgb = hasattr(_inner, 'get_booster')
        for cat_col in ML_CATEGORICAL_FEATURES:
            if cat_col in row.columns:
                if _is_xgb:
                    row[cat_col] = row[cat_col].astype("category")
                else:
                    row = row.drop(columns=[cat_col])
        if not _is_xgb and _feature_medians:
            row = row.fillna(_feature_medians)
        prob = float(model.predict_proba(row)[0, 1])
        explanation = _explain_row(row, _inner)
        return {
            "ml_confidence": round(prob, 4),
            "ml_verdict": "ML_PASS" if prob >= ML_CONFIDENCE_THRESHOLD else "ML_CAUTION",
            "explanation": explanation,
        }
    except Exception as e:
        logger.warning("explain_pick failed: %s", e)
        return None
