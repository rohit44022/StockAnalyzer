"""
ai_ml/regime_filter.py — Market Regime Detector

Classifies the overall market as STRONG_BULL / BULL / NEUTRAL / BEAR / STRONG_BEAR
using 5 signals: Nifty vs 50-SMA, Nifty vs 200-SMA, Nifty RSI, India VIX, breadth.

Adjusts per-pick ML confidence by a regime-based multiplier so that the AI is
more aggressive in bull markets and more conservative in bear markets.
"""
from __future__ import annotations

import functools
import logging
import os
import random
from datetime import date

import numpy as np
import pandas as pd
import yfinance as yf

from ai_ml.config import (
    CSV_DIR, NIFTY_TICKER, REGIME_BREADTH_SAMPLE,
    REGIME_CONFIDENCE_FACTORS, REGIME_VIX_BULL_THRESHOLD,
)

logger = logging.getLogger("ai_ml.regime_filter")


@functools.lru_cache(maxsize=4)
def _fetch_nifty(as_of: date) -> pd.DataFrame | None:
    try:
        df = yf.download(NIFTY_TICKER, period="1y", interval="1d",
                         progress=False, auto_adjust=True)
        if df is None or df.empty or len(df) < 50:
            return None
        return df
    except Exception as e:
        logger.warning("Failed to fetch Nifty data: %s", e)
        return None


def _compute_rsi(closes: pd.Series, period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    last_gain = gain.iloc[-1]
    last_loss = loss.iloc[-1]
    if last_loss == 0:
        return 100.0
    rs = last_gain / last_loss
    return float(100 - 100 / (1 + rs))


def _compute_breadth(csv_dir: str) -> float | None:
    """Sample random CSVs and compute advance/decline ratio from last trading day."""
    try:
        files = [f for f in os.listdir(csv_dir) if f.endswith(".csv")]
        if not files:
            return None
        sample = random.sample(files, min(REGIME_BREADTH_SAMPLE, len(files)))
        advances = 0
        declines = 0
        for fname in sample:
            try:
                path = os.path.join(csv_dir, fname)
                df = pd.read_csv(path, usecols=["Close"], nrows=3000)
                if len(df) < 2:
                    continue
                last = float(df["Close"].iloc[-1])
                prev = float(df["Close"].iloc[-2])
                if last > prev:
                    advances += 1
                elif last < prev:
                    declines += 1
            except Exception:
                continue
        if declines == 0:
            return float(advances) if advances > 0 else None
        return advances / declines
    except Exception as e:
        logger.warning("Breadth computation failed: %s", e)
        return None


def get_market_regime() -> dict:
    """
    Compute market regime from 5 signals.

    Returns dict with:
      regime, score, signals, nifty_price, confidence_factor, explanation
    """
    signals = {}
    score = 0

    # ── 1 & 2: Nifty vs 50-SMA and 200-SMA ──
    nifty_df = _fetch_nifty(date.today())
    nifty_price = None
    if nifty_df is not None and len(nifty_df) >= 200:
        close = nifty_df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        nifty_price = float(close.iloc[-1])
        sma50 = float(close.rolling(50).mean().iloc[-1])
        sma200 = float(close.rolling(200).mean().iloc[-1])

        signals["nifty_above_50sma"] = nifty_price > sma50
        signals["nifty_above_200sma"] = nifty_price > sma200
        if nifty_price > sma50:
            score += 1
        if nifty_price > sma200:
            score += 1

        # ── 3: Nifty RSI ──
        rsi = _compute_rsi(close)
        signals["nifty_rsi"] = round(rsi, 1) if rsi else None
        signals["nifty_rsi_bullish"] = rsi is not None and rsi > 50
        if rsi and rsi > 50:
            score += 1
    elif nifty_df is not None:
        close = nifty_df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        nifty_price = float(close.iloc[-1])
        sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
        signals["nifty_above_50sma"] = sma50 is not None and nifty_price > sma50
        signals["nifty_above_200sma"] = None
        if signals["nifty_above_50sma"]:
            score += 1
        rsi = _compute_rsi(close)
        signals["nifty_rsi"] = round(rsi, 1) if rsi else None
        signals["nifty_rsi_bullish"] = rsi is not None and rsi > 50
        if rsi and rsi > 50:
            score += 1

    # ── 4: India VIX ──
    try:
        from bb_squeeze.vix_regime import _fetch_vix
        vix = _fetch_vix(date.today())
        signals["vix_value"] = round(vix, 2) if vix else None
        signals["vix_bullish"] = vix is not None and vix < REGIME_VIX_BULL_THRESHOLD
        if vix and vix < REGIME_VIX_BULL_THRESHOLD:
            score += 1
    except Exception:
        signals["vix_value"] = None
        signals["vix_bullish"] = None

    # ── 5: Market breadth ──
    ad_ratio = _compute_breadth(CSV_DIR)
    signals["breadth_ad_ratio"] = round(ad_ratio, 2) if ad_ratio else None
    signals["breadth_bullish"] = ad_ratio is not None and ad_ratio > 1.0
    if ad_ratio and ad_ratio > 1.0:
        score += 1

    # ── Classify ──
    if score >= 4:
        regime = "STRONG_BULL"
    elif score == 3:
        regime = "BULL"
    elif score == 2:
        regime = "NEUTRAL"
    elif score == 1:
        regime = "BEAR"
    else:
        regime = "STRONG_BEAR"

    factor = REGIME_CONFIDENCE_FACTORS.get(regime, 1.0)

    explains = {
        "STRONG_BULL": f"Market is in a STRONG BULL regime ({score}/5 signals bullish). Nifty is above both its 50-day and 200-day moving averages, RSI shows strength, VIX is low, and most stocks are advancing. This is the best environment for breakout trades — the tide is strongly in your favour.",
        "BULL": f"Market is in a BULL regime ({score}/5 signals bullish). Most indicators point up. Good conditions for trading — the broader market supports upward moves.",
        "NEUTRAL": f"Market is NEUTRAL ({score}/5 signals bullish). Mixed signals — some indicators are bullish, others bearish. Be selective and stick to high-quality setups only.",
        "BEAR": f"Market is in a BEAR regime ({score}/5 signals bullish). Most indicators point down. Consider smaller positions or waiting for the market to stabilise before entering new trades.",
        "STRONG_BEAR": f"Market is in a STRONG BEAR regime ({score}/5 signals bullish). Nearly all indicators are bearish. This is a dangerous environment for long trades — most breakouts will fail because the market is falling. Consider staying in cash or trading only the strongest setups with tight stops.",
    }

    return {
        "available": True,
        "regime": regime,
        "score": score,
        "max_score": 5,
        "signals": signals,
        "nifty_price": nifty_price,
        "confidence_factor": factor,
        "explanation": explains.get(regime, ""),
    }


def enrich_picks_with_regime(picks: list[dict], regime: dict) -> None:
    """Add market_regime dict to each pick. Adjust ml_confidence if available."""
    factor = regime.get("confidence_factor", 1.0)
    for pick in picks:
        original_ml = pick.get("ml_confidence")
        adjusted = None
        if original_ml is not None:
            adjusted = round(min(original_ml * factor, 1.0), 4)

        pick["market_regime"] = {
            "regime": regime.get("regime", "UNKNOWN"),
            "score": regime.get("score"),
            "max_score": regime.get("max_score", 5),
            "confidence_factor": factor,
            "original_ml_confidence": original_ml,
            "adjusted_ml_confidence": adjusted,
            "explanation": regime.get("explanation", ""),
        }


if __name__ == "__main__":
    regime = get_market_regime()
    print(f"Regime: {regime['regime']} ({regime['score']}/5)")
    print(f"Signals: {regime['signals']}")
    print(f"Factor: {regime['confidence_factor']}")
    assert regime["regime"] in ("STRONG_BULL", "BULL", "NEUTRAL", "BEAR", "STRONG_BEAR")
    assert 0 <= regime["score"] <= 5
    print("OK")
