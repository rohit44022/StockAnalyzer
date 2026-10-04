"""
Intraday data fetcher — pulls 5-min OHLCV candles via Dhan API.
"""

from __future__ import annotations

import io
import json
import os
import threading
import time as _time
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
from typing import Optional, Dict, List

log = logging.getLogger(__name__)

_SCRIP_CACHE: Dict[str, int] = {}
_SCRIP_LOADED = False

_rate_lock = threading.Lock()
_rate_timestamps: list = []
_RATE_LIMIT = 5

_BAD_TICKERS_FILE = os.path.join(os.path.dirname(__file__), ".bad_tickers.json")

def _throttle():
    with _rate_lock:
        now = _time.monotonic()
        _rate_timestamps[:] = [t for t in _rate_timestamps if now - t < 1.0]
        if len(_rate_timestamps) >= _RATE_LIMIT:
            sleep_for = 1.0 - (now - _rate_timestamps[0])
            if sleep_for > 0:
                _time.sleep(sleep_for)
        _rate_timestamps.append(_time.monotonic())


def _load_dhan_context():
    """Load Dhan credentials from .env, return (ctx, ok)."""
    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)
        cid = os.getenv("DHAN_CLIENT_ID")
        tok = os.getenv("DHAN_ACCESS_TOKEN")
        if not cid or not tok:
            return None, False
        from dhanhq import DhanContext
        return DhanContext(cid, tok), True
    except Exception:
        return None, False


def _load_scrip_master() -> Dict[str, int]:
    """Load Dhan scrip master. Caches to disk for 24h to avoid repeated downloads."""
    global _SCRIP_CACHE, _SCRIP_LOADED
    if _SCRIP_LOADED:
        return _SCRIP_CACHE

    cache_path = os.path.join(os.path.dirname(__file__), ".scrip_cache.csv")
    cache_fresh = False
    if os.path.exists(cache_path):
        age = datetime.now().timestamp() - os.path.getmtime(cache_path)
        cache_fresh = age < 86400

    try:
        if cache_fresh:
            df = pd.read_csv(cache_path, low_memory=False)
        else:
            import requests
            resp = requests.get(
                "https://images.dhan.co/api-data/api-scrip-master.csv", timeout=15
            )
            df = pd.read_csv(io.StringIO(resp.text), low_memory=False)
            df.to_csv(cache_path, index=False)

        nse_eq = df[
            (df["SEM_EXM_EXCH_ID"] == "NSE")
            & (df["SEM_SEGMENT"] == "E")
            & (df["SEM_INSTRUMENT_NAME"] == "EQUITY")
        ]
        _SCRIP_CACHE = dict(
            zip(nse_eq["SEM_TRADING_SYMBOL"], nse_eq["SEM_SMST_SECURITY_ID"].astype(int))
        )
        _SCRIP_LOADED = True
    except Exception:
        pass
    return _SCRIP_CACHE


def _ticker_to_sid(ticker: str) -> Optional[int]:
    """Convert 'RELIANCE.NS' → Dhan security_id (e.g. 2885)."""
    scrips = _load_scrip_master()
    sym = ticker.replace(".NS", "").replace(".BO", "").strip().upper()
    return scrips.get(sym)


def validate_tickers(tickers: List[str]) -> List[str]:
    """Drop tickers that have no Dhan security_id (delisted/renamed/corrupt)."""
    scrips = _load_scrip_master()
    valid = []
    dropped = []
    for t in tickers:
        sym = t.replace(".NS", "").replace(".BO", "").strip().upper()
        if sym in scrips:
            valid.append(t)
        else:
            dropped.append(t)
    if dropped:
        log.warning("Dropped %d tickers not in Dhan scrip master: %s",
                     len(dropped), dropped[:10])
    return valid


def _interval_minutes(interval: str) -> int:
    return int(interval.replace("m", ""))


def _fetch_dhan(
    ticker: str, interval: str = "5m", days: int = 5
) -> Optional[pd.DataFrame]:
    """Fetch intraday candles from Dhan API."""
    ctx, ok = _load_dhan_context()
    if not ok:
        return None

    sid = _ticker_to_sid(ticker)
    if sid is None:
        return None

    try:
        from dhanhq import HistoricalData

        hd = HistoricalData(ctx)
        to_date = datetime.now().strftime("%Y-%m-%d")
        from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        _throttle()
        resp = hd.intraday_minute_data(
            security_id=str(sid),
            exchange_segment="NSE_EQ",
            instrument_type="EQUITY",
            from_date=from_date,
            to_date=to_date,
            interval=_interval_minutes(interval),
        )

        if not isinstance(resp, dict) or resp.get("status") != "success":
            return None

        d = resp["data"]
        if not d or not d.get("open"):
            return None

        df = pd.DataFrame({
            "Open": d["open"],
            "High": d["high"],
            "Low": d["low"],
            "Close": d["close"],
            "Volume": d["volume"],
        })
        from zoneinfo import ZoneInfo
        ist = ZoneInfo("Asia/Kolkata")
        df.index = pd.DatetimeIndex(
            [datetime.fromtimestamp(ts, tz=ist) for ts in d["timestamp"]]
        )
        df.index.name = "Datetime"
        df.dropna(inplace=True)

        return df if len(df) >= 20 else None
    except Exception:
        return None


# --- Bad tickers: persisted to disk, auto-expire daily ---

def _load_bad_tickers() -> dict:
    try:
        with open(_BAD_TICKERS_FILE) as f:
            data = json.load(f)
        today = date.today().isoformat()
        return {k: v for k, v in data.items() if v == today}
    except Exception:
        return {}

def _save_bad_tickers(bt: dict):
    try:
        with open(_BAD_TICKERS_FILE, "w") as f:
            json.dump(bt, f)
    except Exception:
        pass

_bad_tickers: dict = _load_bad_tickers()


def fetch_intraday(
    ticker: str,
    interval: str = "5m",
    days: int = 5,
) -> Optional[pd.DataFrame]:
    """Fetch intraday candles from Dhan."""
    today = date.today().isoformat()
    if _bad_tickers.get(ticker) == today:
        return None
    df = _fetch_dhan(ticker, interval, days)
    if df is None:
        _bad_tickers[ticker] = today
        _save_bad_tickers(_bad_tickers)
    return df


def fetch_today_candles(ticker: str, interval: str = "5m") -> Optional[pd.DataFrame]:
    """Fetch only today's intraday candles."""
    df = fetch_intraday(ticker, interval=interval, days=1)
    if df is None:
        return None
    today = datetime.now().date()
    mask = df.index.date == today
    today_df = df[mask]
    return today_df if len(today_df) >= 5 else None
