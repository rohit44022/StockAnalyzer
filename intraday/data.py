"""
Intraday data fetcher — pulls 5-min OHLCV candles.
Primary: Dhan API (₹499/mo, 5yr history, reliable).
Fallback: yfinance (free, 60 days, occasionally drops candles).
"""

from __future__ import annotations

import io
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, Dict

_SCRIP_CACHE: Dict[str, int] = {}
_SCRIP_LOADED = False


def _load_dhan_context():
    """Load Dhan credentials from .env, return (ctx, ok)."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
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
        cache_fresh = age < 86400  # 24 hours

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
        # Convert epoch timestamps to IST datetime index
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


def _fetch_yfinance(
    ticker: str, interval: str = "5m", days: int = 5
) -> Optional[pd.DataFrame]:
    """Fallback: fetch from yfinance."""
    try:
        import yfinance as yf

        t = yf.Ticker(ticker)
        df = t.history(period=f"{days}d", interval=interval)
        if df is None or df.empty or len(df) < 20:
            return None
        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.dropna(inplace=True)
        return df
    except Exception:
        return None


def fetch_intraday(
    ticker: str,
    interval: str = "5m",
    days: int = 5,
) -> Optional[pd.DataFrame]:
    """Fetch intraday candles. Tries Dhan first, falls back to yfinance."""
    df = _fetch_dhan(ticker, interval, days)
    if df is not None:
        return df
    return _fetch_yfinance(ticker, interval, days)


def fetch_today_candles(ticker: str, interval: str = "5m") -> Optional[pd.DataFrame]:
    """Fetch only today's intraday candles."""
    df = fetch_intraday(ticker, interval=interval, days=1)
    if df is None:
        return None
    today = datetime.now().date()
    mask = df.index.date == today
    today_df = df[mask]
    return today_df if len(today_df) >= 5 else None
