"""
5-min OHLCV data store for intraday backtest.

Downloads from yfinance (~60 days of 5-min data) and stores as CSV.
The backtest uses these for bar-by-bar simulation when available.

Usage:
    .venv/bin/python -m intraday.datastore            # download all watchlist
    .venv/bin/python -m intraday.datastore --tickers RELIANCE TCS
"""
from __future__ import annotations

import os, sys, argparse
from datetime import datetime, timedelta
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

STORE_DIR = os.path.join(os.path.dirname(__file__), "5min_store")

DEFAULT_WATCHLIST = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS",
    "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "LT.NS", "KOTAKBANK.NS",
    "HINDUNILVR.NS", "BAJFINANCE.NS", "AXISBANK.NS", "MARUTI.NS",
    "SUNPHARMA.NS", "TITAN.NS", "WIPRO.NS", "ULTRACEMCO.NS",
    "TATAMOTORS.NS", "ADANIENT.NS",
]


def _ticker_path(ticker: str) -> str:
    safe = ticker.replace(".", "_")
    return os.path.join(STORE_DIR, f"{safe}_5min.csv")


def download_5min(ticker: str, days: int = 59) -> pd.DataFrame:
    """Download 5-min data from yfinance (max ~60 days)."""
    import yfinance as yf
    end = datetime.now()
    start = end - timedelta(days=days)
    df = yf.download(ticker, start=start, end=end, interval="5m",
                     progress=False, auto_adjust=True)
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index.name = "Datetime"
    return df[["Open", "High", "Low", "Close", "Volume"]]


def save_5min(ticker: str, df: pd.DataFrame):
    """Save/append 5-min data, deduplicating by datetime."""
    os.makedirs(STORE_DIR, exist_ok=True)
    path = _ticker_path(ticker)

    if os.path.exists(path):
        existing = pd.read_csv(path, parse_dates=["Datetime"], index_col="Datetime")
        df = pd.concat([existing, df])
        df = df[~df.index.duplicated(keep="last")]
        df.sort_index(inplace=True)

    df.to_csv(path)


def load_5min(ticker: str, date: str = None) -> pd.DataFrame:
    """Load stored 5-min data. If date given, return only that day's bars."""
    path = _ticker_path(ticker)
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path, parse_dates=["Datetime"], index_col="Datetime")
    if date:
        day = pd.Timestamp(date).date()
        df = df[df.index.date == day]
    return df


def has_5min(ticker: str, date: str) -> bool:
    """Check if we have 5-min data for a specific date."""
    path = _ticker_path(ticker)
    if not os.path.exists(path):
        return False
    df = pd.read_csv(path, parse_dates=["Datetime"], index_col="Datetime")
    day = pd.Timestamp(date).date()
    return (df.index.date == day).any()


def download_all(tickers: list = None, days: int = 59):
    """Download 5-min data for all tickers."""
    tickers = tickers or DEFAULT_WATCHLIST
    print(f"Downloading 5-min data for {len(tickers)} tickers ({days} days)...")
    for t in tickers:
        try:
            df = download_5min(t, days)
            if df.empty:
                print(f"  {t}: no data")
                continue
            save_5min(t, df)
            dates = df.index.date
            unique_days = len(set(dates))
            print(f"  {t}: {len(df)} bars, {unique_days} days")
        except Exception as e:
            print(f"  {t}: error — {e}")
    print("Done.")


def main():
    parser = argparse.ArgumentParser(description="5-min data store")
    parser.add_argument("--tickers", nargs="*", help="Tickers to download")
    parser.add_argument("--days", type=int, default=59, help="Days to fetch (max ~60)")
    args = parser.parse_args()

    tl = None
    if args.tickers:
        tl = [t if t.endswith(".NS") else t + ".NS" for t in args.tickers]
    download_all(tl, args.days)


if __name__ == "__main__":
    main()
