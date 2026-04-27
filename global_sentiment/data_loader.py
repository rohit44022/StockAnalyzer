"""
data_loader.py — Production-grade fetcher for macro instruments.
═══════════════════════════════════════════════════════════════════

Production hardening over the v1:
  • Persistent file cache (survives restart) + 15-min in-memory layer
  • Retries with exponential backoff on transient yfinance failures
  • Per-instrument staleness detection (calendar days since last close)
  • Outlier validation — reject prices that move >40% in a single bar
  • Structured logging to global_sentiment.log
  • Health metrics (last successful fetch, # failed instruments, error rate)
  • Multi-timeframe summary: 1d / 5d / 20d / 60d % changes + volatility
"""

from __future__ import annotations
import json
import logging
import math
import os
import pickle
import threading
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Optional

import pandas as pd

from global_sentiment.instruments import ALL_INSTRUMENTS


# ─────────────────────────── logging ───────────────────────────

_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)
_LOG_PATH = os.path.join(_LOG_DIR, "global_sentiment.log")

logger = logging.getLogger("global_sentiment")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    h = RotatingFileHandler(_LOG_PATH, maxBytes=2_000_000, backupCount=3)
    h.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(h)


# ─────────────────────────── config ───────────────────────────

CACHE_TTL_SECONDS  = 15 * 60
LOOKBACK_DAYS      = 1825        # ~5 years — enough for both 1Y and 5Y percentiles + correlation
FETCH_RETRY_MAX    = 3           # total attempts including the first
FETCH_RETRY_DELAY  = 1.5         # seconds, doubles each retry
STALE_WARN_DAYS    = 3           # > 3 calendar days since last close → flag stale
STALE_FAIL_DAYS    = 10          # > 10 days → drop the instrument entirely
OUTLIER_BAR_PCT    = 0.40        # >40% single-bar move → reject as bad print

# Persistent cache file — survives process restarts
_CACHE_FILE = os.path.join(_LOG_DIR, "global_sentiment_cache.pkl")


# ─────────────────────────── memory cache ───────────────────────────

_cache_lock = threading.Lock()
_cache = {
    "ts":    0.0,
    "data":  None,    # dict[key] -> DataFrame
    "health": None,   # dict — populated on each fetch
}


def _is_fresh() -> bool:
    return _cache["data"] is not None and (time.time() - _cache["ts"]) < CACHE_TTL_SECONDS


def cache_age_seconds() -> Optional[int]:
    if _cache["data"] is None:
        return None
    return int(time.time() - _cache["ts"])


def get_health() -> Optional[dict]:
    return _cache.get("health")


# ─────────────────────────── persistent cache ───────────────────────────

def _save_persistent(payload: dict) -> None:
    try:
        with open(_CACHE_FILE, "wb") as f:
            pickle.dump(payload, f)
    except Exception as e:
        logger.warning(f"Persistent cache save failed: {e}")


def _load_persistent() -> Optional[dict]:
    try:
        if not os.path.exists(_CACHE_FILE):
            return None
        with open(_CACHE_FILE, "rb") as f:
            return pickle.load(f)
    except Exception as e:
        logger.warning(f"Persistent cache load failed: {e}")
        return None


# ─────────────────────────── helpers ───────────────────────────

def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _validate_close_series(s: pd.Series) -> tuple[pd.Series, list]:
    """
    Reject implausible bars: any single-bar move >OUTLIER_BAR_PCT is dropped
    (likely a Yahoo bad print). Returns cleaned series + list of reject reasons.
    """
    if s is None or s.empty:
        return s, ["empty series"]
    rejects = []
    s = s.copy()
    pct = s.pct_change()
    bad = pct.abs() > OUTLIER_BAR_PCT
    if bad.any():
        for ts in s.index[bad]:
            rejects.append(f"outlier on {ts}: {pct.loc[ts]*100:+.1f}% move rejected")
        s = s.mask(bad)
        s = s.ffill()
    # Reject obviously bogus values
    bogus = (s <= 0) | (s.abs() > 1e9)
    if bogus.any():
        rejects.append(f"{int(bogus.sum())} bogus values masked")
        s = s.mask(bogus).ffill()
    return s, rejects


# ─────────────────────────── fetch ───────────────────────────

def _fetch_yahoo_once() -> dict:
    """One batched yfinance fetch attempt. Returns dict[key] -> DataFrame."""
    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance not installed")
        return {}

    tickers = [i.yf_ticker for i in ALL_INSTRUMENTS]
    out: dict = {}

    df_all = yf.download(
        tickers=" ".join(tickers),
        period=f"{LOOKBACK_DAYS}d",
        interval="1d",
        group_by="ticker",
        auto_adjust=False,
        progress=False,
        threads=True,
    )
    if df_all is None or df_all.empty:
        logger.warning("yfinance returned empty DataFrame")
        return out

    for inst in ALL_INSTRUMENTS:
        try:
            if isinstance(df_all.columns, pd.MultiIndex):
                if inst.yf_ticker not in df_all.columns.get_level_values(0):
                    continue
                sub = df_all[inst.yf_ticker].copy()
            else:
                sub = df_all.copy()
            sub = sub.dropna(how="all")
            if sub.empty or "Close" not in sub.columns:
                continue
            out[inst.key] = sub
        except Exception as e:
            logger.warning(f"{inst.yf_ticker} parse failed: {e}")
            continue
    return out


def _fetch_with_retry() -> dict:
    """Retry yfinance with exponential backoff."""
    last_err = None
    for attempt in range(1, FETCH_RETRY_MAX + 1):
        try:
            data = _fetch_yahoo_once()
            if data:
                logger.info(f"yfinance fetch OK on attempt {attempt}: {len(data)} instruments")
                return data
            logger.warning(f"yfinance fetch returned empty on attempt {attempt}")
        except Exception as e:
            last_err = e
            logger.warning(f"yfinance fetch attempt {attempt} crashed: {e}")
        if attempt < FETCH_RETRY_MAX:
            time.sleep(FETCH_RETRY_DELAY * (2 ** (attempt - 1)))
    logger.error(f"yfinance fetch failed after {FETCH_RETRY_MAX} attempts; last error: {last_err}")
    return {}


# ─────────────────────────── public API ───────────────────────────

def get_market_data(force_refresh: bool = False) -> dict:
    """
    Returns dict[key] -> DataFrame. Layered cache:
      1. memory cache (15-min TTL) → return immediately
      2. fetch yfinance with retries
      3. fall back to persistent cache if fetch fails
    """
    with _cache_lock:
        if not force_refresh and _is_fresh():
            return _cache["data"]

        # Try fresh fetch
        data = _fetch_with_retry()

        if not data:
            # Fall back to persistent cache so the page still renders
            disk = _load_persistent()
            if disk and disk.get("data"):
                age_min = int((time.time() - disk.get("ts", 0)) / 60)
                logger.warning(f"Using persistent cache (age: {age_min}m)")
                _cache["data"] = disk["data"]
                _cache["ts"]   = disk["ts"]
                _cache["health"] = {
                    "ok": False,
                    "source": "persistent_cache_fallback",
                    "fetch_age_minutes": age_min,
                    "instruments_loaded": len(disk["data"]),
                    "last_error": "yfinance fetch failed; serving cached data from disk",
                }
                return disk["data"]
            # No disk cache either — return empty
            _cache["data"] = {}
            _cache["ts"] = time.time()
            _cache["health"] = {
                "ok": False,
                "source": "fetch_failed",
                "instruments_loaded": 0,
                "last_error": "yfinance fetch failed, no persistent cache available",
            }
            return {}

        # Save to memory + disk
        _cache["data"] = data
        _cache["ts"]   = time.time()
        _save_persistent({"data": data, "ts": _cache["ts"]})
        _cache["health"] = {
            "ok": True,
            "source": "live_fetch",
            "instruments_requested": len(ALL_INSTRUMENTS),
            "instruments_loaded": len(data),
            "missing": sorted(set(i.key for i in ALL_INSTRUMENTS) - set(data.keys())),
        }
        return data


# ─────────────────────────── per-instrument summary ───────────────────────────

def summarize(df: pd.DataFrame) -> dict:
    """
    Reduce a DataFrame to all the metrics the analyzer needs:
      • last, prev_close, change_1d/5d/20d/60d
      • 60-day high/low
      • 1-year percentile of last close
      • staleness (calendar days since last close)
      • realized vol (20-day annualized)
      • data quality flags (rejects, stale)
    """
    if df is None or df.empty:
        return {}
    if "Close" not in df.columns:
        return {}

    closes_raw = df["Close"].dropna()
    closes, rejects = _validate_close_series(closes_raw)
    if closes is None or closes.empty:
        return {}

    last = _safe_float(closes.iloc[-1])
    prev = _safe_float(closes.iloc[-2]) if len(closes) >= 2 else None

    def _pct_change(periods: int) -> Optional[float]:
        if len(closes) <= periods:
            return None
        ref = _safe_float(closes.iloc[-1 - periods])
        if not ref or not last:
            return None
        return round((last - ref) / ref * 100, 2)

    # 1-year percentile of last close
    one_year = closes.tail(252)
    pct_rank = None
    if len(one_year) >= 30 and last is not None:
        rank = (one_year < last).sum()
        pct_rank = round(rank / len(one_year) * 100)

    # 5-year percentile of last close (multi-year context)
    five_year = closes.tail(252 * 5)
    pct_rank_5y = None
    if len(five_year) >= 252 and last is not None:
        rank5 = (five_year < last).sum()
        pct_rank_5y = round(rank5 / len(five_year) * 100)

    # Realized 20-day annualized vol (for confidence/regime stability)
    realized_vol = None
    rets = closes.pct_change().dropna().tail(20)
    if len(rets) >= 10:
        vol = float(rets.std() * (252 ** 0.5) * 100)
        if not (math.isnan(vol) or math.isinf(vol)):
            realized_vol = round(vol, 2)

    # Staleness check
    last_ts = closes.index[-1]
    if hasattr(last_ts, "to_pydatetime"):
        last_dt = last_ts.to_pydatetime()
    elif hasattr(last_ts, "date"):
        last_dt = last_ts
    else:
        last_dt = datetime.now()
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    cal_days_stale = max(0, int((now - last_dt).total_seconds() / 86400))

    if cal_days_stale > STALE_FAIL_DAYS:
        return {}   # caller drops this instrument

    is_stale = cal_days_stale > STALE_WARN_DAYS

    return {
        "last":           last,
        "prev_close":     prev,
        "change_1d_pct":  _pct_change(1),
        "change_5d_pct":  _pct_change(5),
        "change_20d_pct": _pct_change(20),
        "change_60d_pct": _pct_change(60),
        "high_60d":       _safe_float(closes.tail(60).max()) if not closes.empty else None,
        "low_60d":        _safe_float(closes.tail(60).min()) if not closes.empty else None,
        "pct_rank_1y":    pct_rank,           # 0-100; 100 = at 1-year high
        "pct_rank_5y":    pct_rank_5y,        # 0-100; 100 = at 5-year high (multi-year context)
        "realized_vol_pct": realized_vol,     # annualized, %
        "ts_last":        str(last_ts.date()) if hasattr(last_ts, "date") else str(last_ts),
        "cal_days_stale": cal_days_stale,
        "is_stale":       is_stale,
        "n_bars":         int(len(closes)),
        "data_rejects":   rejects,
    }
