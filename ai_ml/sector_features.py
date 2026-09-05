"""
ai_ml/sector_features.py — Sector-relative features for conviction scoring.

Downloads sector index CSVs once, caches as parquet. Maps tickers to sectors
via yfinance info (cached as JSON). Computes 20-day relative strength at
any historical bar for training, and live for inference.
"""
from __future__ import annotations

import json
import logging
import os

import numpy as np
import pandas as pd

from ai_ml.config import SECTOR_CACHE, TICKER_SECTOR_MAP, CSV_DIR

logger = logging.getLogger(__name__)

SECTOR_INDICES = {
    "Financial Services": "^NSEBANK",
    "Information Technology": "^CNXIT",
    "Automobile and Auto Components": "^CNXAUTO",
    "Healthcare": "^CNXPHARMA",
    "Metals & Mining": "^CNXMETAL",
    "Fast Moving Consumer Goods": "^CNXFMCG",
    "Oil Gas & Consumable Fuels": "^CNXENERGY",
    "Construction": "^CNXREALTY",
    "Real Estate": "^CNXREALTY",
    "Consumer Services": "^CNXFMCG",
    "Capital Goods": "^CNXMETAL",
    "Power": "^CNXENERGY",
    "Telecommunication": "^CNXIT",
    "Chemicals": "^CNXPHARMA",
    "Textiles": "^CNXFMCG",
    "Media Entertainment & Publication": "^CNXIT",
}

_sector_data: dict[str, pd.Series] | None = None
_ticker_sectors: dict[str, str] | None = None


def build_sector_cache() -> None:
    """Download all sector index + Nifty50 historical data, save as parquet."""
    import yfinance as yf

    unique_tickers = list(set(SECTOR_INDICES.values())) + ["^NSEI"]
    frames = {}
    for ticker in unique_tickers:
        print(f"  Downloading {ticker}...", flush=True)
        df = yf.download(ticker, start="1994-01-01", progress=False)
        if df is not None and not df.empty:
            close = df["Close"].dropna()
            if hasattr(close, 'columns'):
                close = close.iloc[:, 0]
            frames[ticker] = close

    combined = pd.DataFrame(frames)
    combined.to_parquet(SECTOR_CACHE)
    print(f"  Sector cache saved: {len(combined)} rows, {len(frames)} indices", flush=True)


def build_ticker_sector_map() -> None:
    """Map each stock ticker to its sector via yfinance info. Cached as JSON."""
    import yfinance as yf
    import glob

    files = sorted(glob.glob(os.path.join(CSV_DIR, "*.csv")))
    mapping = {}

    for i, f in enumerate(files):
        ticker = os.path.basename(f).replace(".csv", "")
        try:
            info = yf.Ticker(ticker).info
            sector = info.get("sector", "")
            if sector and sector in SECTOR_INDICES:
                mapping[ticker] = sector
        except Exception:
            pass
        if (i + 1) % 200 == 0:
            print(f"  [{i+1}/{len(files)}] mapped {len(mapping)} tickers", flush=True)

    with open(TICKER_SECTOR_MAP, "w") as f:
        json.dump(mapping, f)
    print(f"  Ticker-sector map saved: {len(mapping)} tickers", flush=True)


def _load_sector_data():
    """Load cached sector index data."""
    global _sector_data
    if _sector_data is not None:
        return
    if not os.path.exists(SECTOR_CACHE):
        _sector_data = {}
        return
    df = pd.read_parquet(SECTOR_CACHE)
    _sector_data = {col: df[col].dropna() for col in df.columns}


def _load_ticker_sectors():
    """Load cached ticker-to-sector mapping."""
    global _ticker_sectors
    if _ticker_sectors is not None:
        return
    if not os.path.exists(TICKER_SECTOR_MAP):
        _ticker_sectors = {}
        return
    with open(TICKER_SECTOR_MAP) as f:
        _ticker_sectors = json.load(f)


def get_sector_rs_at_bar(ticker: str, bar_date, stock_close_20d: float) -> dict:
    """Compute sector RS features at a historical bar date.

    Returns dict with sector_rs (sector vs nifty) and stock_vs_sector_rs.
    Returns empty dict if data unavailable.
    """
    _load_sector_data()
    _load_ticker_sectors()

    sector = (_ticker_sectors or {}).get(ticker)
    if not sector or not _sector_data:
        return {}

    sector_idx = SECTOR_INDICES.get(sector)
    if not sector_idx:
        return {}

    sector_closes = _sector_data.get(sector_idx)
    nifty_closes = _sector_data.get("^NSEI")
    if sector_closes is None or nifty_closes is None:
        return {}

    try:
        ts = pd.Timestamp(bar_date)
        # Find nearest index position
        sector_loc = sector_closes.index.get_indexer([ts], method="ffill")[0]
        nifty_loc = nifty_closes.index.get_indexer([ts], method="ffill")[0]

        if sector_loc < 20 or nifty_loc < 20:
            return {}

        sector_ret = (float(sector_closes.iloc[sector_loc]) /
                      float(sector_closes.iloc[sector_loc - 20]) - 1) * 100
        nifty_ret = (float(nifty_closes.iloc[nifty_loc]) /
                     float(nifty_closes.iloc[nifty_loc - 20]) - 1) * 100

        sector_rs = sector_ret - nifty_ret
        stock_vs_sector = stock_close_20d - sector_ret

        return {
            "sector_rs": round(sector_rs, 4),
            "stock_vs_sector_rs": round(stock_vs_sector, 4),
        }
    except Exception:
        return {}


def get_sector_rs_live(ticker: str, stock_df: pd.DataFrame) -> dict:
    """Compute sector RS features from live data for inference."""
    _load_ticker_sectors()

    sector = (_ticker_sectors or {}).get(ticker)
    if not sector:
        return {}

    try:
        from bb_squeeze.sector_strength import compute_sector_rs
        result = compute_sector_rs(ticker, stock_df, sector)
        if not result.get("available"):
            return {}
        return {
            "sector_rs": result.get("sector_vs_nifty_rs", 0),
            "stock_vs_sector_rs": result.get("stock_vs_sector_rs", 0),
        }
    except Exception:
        return {}
