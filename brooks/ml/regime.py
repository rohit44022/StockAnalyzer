"""
Market regime classifier for Brooks PA — rules-based, no training needed.
Classifies each stock's current state using price structure features.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def classify_regime(df: pd.DataFrame) -> dict:
    """Classify market regime from price window."""
    close = df["Close"].values.astype(float)
    high = df["High"].values.astype(float)
    low = df["Low"].values.astype(float)
    n = len(close)
    if n < 60:
        return {"regime": "UNKNOWN", "score": 0}

    sma20 = float(np.mean(close[-20:]))
    sma50 = float(np.mean(close[-50:]))
    sma20_prev = float(np.mean(close[-30:-10]))
    slope = (sma20 - sma20_prev) / max(sma20_prev, 1e-10) * 100
    cv50 = (close[-1] - sma50) / max(sma50, 1e-10) * 100
    mom = (close[-1] - close[-21]) / max(close[-21], 1e-10) * 100

    tr = np.maximum(high[-14:] - low[-14:],
                    np.maximum(np.abs(high[-14:] - close[-15:-1]),
                               np.abs(low[-14:] - close[-15:-1])))
    atr_pct = float(tr.mean()) / max(close[-1], 1e-10) * 100

    above = int(np.sum(close[-10:] > sma20))

    score = 0
    if abs(slope) > 1.5: score += 3
    elif abs(slope) > 0.8: score += 2
    elif abs(slope) > 0.3: score += 1

    if abs(mom) > 5: score += 2
    elif abs(mom) > 2: score += 1

    if abs(cv50) > 5: score += 2
    elif abs(cv50) > 2: score += 1

    if above >= 8 or above <= 2: score += 2
    elif above >= 7 or above <= 3: score += 1

    if atr_pct < 2.0: score += 1
    elif atr_pct > 3.5: score -= 1

    if cv50 < -5 and mom < -3:
        regime = "BEAR"
    elif score >= 7:
        regime = "TRENDING_BULL" if close[-1] > sma50 else "TRENDING_BEAR"
    elif score >= 4:
        regime = "MILD_TREND"
    else:
        regime = "CHOPPY"

    return {"regime": regime, "score": score}
