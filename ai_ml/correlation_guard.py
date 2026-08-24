"""
ai_ml/correlation_guard.py — Correlation-Aware Portfolio Filter

Computes pairwise correlation between Top 5 picks to flag
concentrated risk. If two picks are >70% correlated, the
portfolio is effectively one fewer independent bet.

Adds correlation matrix and risk warnings to the result dict
WITHOUT modifying any existing field.
"""
from __future__ import annotations

import os
import logging

import numpy as np
import pandas as pd

from ai_ml.config import CORRELATION_WINDOW, CORRELATION_THRESHOLD, CSV_DIR

logger = logging.getLogger("ai_ml.correlation_guard")


def _load_close_series(ticker: str, days: int = CORRELATION_WINDOW) -> pd.Series | None:
    """Load last N days of Close prices from CSV."""
    csv_path = os.path.join(CSV_DIR, f"{ticker}.csv")
    if not os.path.exists(csv_path):
        return None
    try:
        df = pd.read_csv(csv_path, parse_dates=["Date"], index_col="Date")
        close = df["Close"].dropna().tail(days)
        if len(close) < days // 2:
            return None
        return close
    except Exception:
        return None


def compute_correlation_matrix(picks: list[dict]) -> dict:
    """
    Compute pairwise correlation for a list of picks.

    Returns dict with:
      - matrix: {ticker_a: {ticker_b: corr_value}}
      - correlated_pairs: [(tickerA, tickerB, corr)] for corr > threshold
      - diversification_score: 0-100 (100 = fully diversified)
      - risk_level: "LOW" | "MEDIUM" | "HIGH"
    """
    tickers = [p["ticker"] for p in picks]
    if len(tickers) < 2:
        return {
            "matrix": {},
            "correlated_pairs": [],
            "diversification_score": 100,
            "risk_level": "LOW",
        }

    series = {}
    for t in tickers:
        s = _load_close_series(t)
        if s is not None:
            series[t] = s.pct_change().dropna()

    if len(series) < 2:
        return {
            "matrix": {},
            "correlated_pairs": [],
            "diversification_score": 100,
            "risk_level": "LOW",
        }

    # Align all series to common dates
    combined = pd.DataFrame(series)
    combined = combined.dropna(how="any")
    if len(combined) < 20:
        return {
            "matrix": {},
            "correlated_pairs": [],
            "diversification_score": 100,
            "risk_level": "LOW",
        }

    corr = combined.corr()

    # Extract correlated pairs
    correlated_pairs = []
    n = len(corr.columns)
    for i in range(n):
        for j in range(i + 1, n):
            val = corr.iloc[i, j]
            if abs(val) > CORRELATION_THRESHOLD:
                correlated_pairs.append({
                    "stock_a": corr.columns[i],
                    "stock_b": corr.columns[j],
                    "correlation": round(float(val), 3),
                })

    # Diversification score: average off-diagonal abs correlation inverted
    off_diag = []
    for i in range(n):
        for j in range(i + 1, n):
            off_diag.append(abs(corr.iloc[i, j]))

    avg_corr = np.mean(off_diag) if off_diag else 0
    div_score = max(0, min(100, int((1 - avg_corr) * 100)))

    if len(correlated_pairs) >= 3 or avg_corr > 0.6:
        risk = "HIGH"
    elif len(correlated_pairs) >= 1 or avg_corr > 0.4:
        risk = "MEDIUM"
    else:
        risk = "LOW"

    matrix_dict = {}
    for t in corr.columns:
        matrix_dict[t] = {t2: round(float(corr.loc[t, t2]), 3) for t2 in corr.columns}

    return {
        "matrix": matrix_dict,
        "correlated_pairs": correlated_pairs,
        "diversification_score": div_score,
        "risk_level": risk,
        "avg_correlation": round(float(avg_corr), 3),
        "stocks_analyzed": list(corr.columns),
    }


def enrich_picks_with_correlation(picks: list[dict]) -> dict:
    """
    Compute correlation analysis for the pick set.
    Returns the correlation result (NOT modifying individual picks — this is
    portfolio-level data that goes on the result object, not per-pick).
    """
    return compute_correlation_matrix(picks)
