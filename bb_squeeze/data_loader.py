"""
data_loader.py — Handles loading historical data from local CSV files
and live data fetching via yfinance.
Also fixes the historical_data.py issues for proper data download.
"""

import os
import warnings
import logging
import pandas as pd
import numpy as np
import yfinance as yf
from pathlib import Path
from datetime import datetime, timedelta
from bb_squeeze.config import CSV_DIR, HISTORY_START, MIN_DATA_DAYS

# Suppress noisy yfinance warnings ("possibly delisted", etc.)
warnings.filterwarnings("ignore")
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.CRITICAL)

# ─────────────────────────────────────────────────────────────────
#  NSE TRADING CALENDAR AWARENESS
# ─────────────────────────────────────────────────────────────────

# Major NSE holidays (approximate — updated annually)
# This covers fixed holidays; variable ones (Diwali, Holi, Eid) shift each year
_NSE_FIXED_HOLIDAYS_MD = {
    (1, 26),   # Republic Day
    (8, 15),   # Independence Day
    (10, 2),   # Gandhi Jayanti
    (12, 25),  # Christmas
}


def _is_nse_trading_day(dt: datetime) -> bool:
    """Check if a given date is likely an NSE trading day (not weekend, not known holiday)."""
    if dt.weekday() >= 5:  # Saturday / Sunday
        return False
    if (dt.month, dt.day) in _NSE_FIXED_HOLIDAYS_MD:
        return False
    return True


def _last_expected_trading_date() -> datetime:
    """Return the most recent date that should have been a trading day."""
    dt = datetime.now()
    # If before 15:30 IST, the *previous* session is the latest complete one
    if dt.hour < 16:  # Use 16:00 as conservative end-of-day
        dt = dt - timedelta(days=1)
    # Walk backwards to find a trading day
    for _ in range(10):
        if _is_nse_trading_day(dt):
            return dt.replace(hour=0, minute=0, second=0, microsecond=0)
        dt = dt - timedelta(days=1)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def get_data_freshness(df: pd.DataFrame) -> dict:
    """
    Compute data freshness metadata for a DataFrame.
    Returns dict with last_date, days_stale, trading_days_stale, is_stale, warning.
    """
    if df is None or df.empty:
        return {
            "last_date": None,
            "days_stale": 999,
            "trading_days_stale": 999,
            "is_stale": True,
            "warning": "⚠️ NO DATA AVAILABLE",
        }

    last_date = pd.Timestamp(df.index[-1])
    now = pd.Timestamp.now()
    # Handle timezone-aware vs timezone-naive index
    if last_date.tzinfo is not None:
        last_date = last_date.tz_localize(None)
    calendar_days = (now - last_date).days

    # Count approximate trading days stale
    trading_days = 0
    check = last_date + pd.Timedelta(days=1)
    while check.date() <= now.date():
        if _is_nse_trading_day(check.to_pydatetime()):
            trading_days += 1
        check += pd.Timedelta(days=1)

    is_stale = trading_days > 2  # More than 2 trading days old

    warning = None
    if trading_days > 10:
        warning = f"🔴 DATA IS {trading_days} TRADING DAYS OLD — signals UNRELIABLE for live trading"
    elif trading_days > 5:
        warning = f"🟠 DATA IS {trading_days} TRADING DAYS OLD — signals may be outdated"
    elif trading_days > 2:
        warning = f"🟡 DATA IS {trading_days} TRADING DAYS OLD — consider refreshing"

    return {
        "last_date": str(last_date.date()),
        "days_stale": calendar_days,
        "trading_days_stale": trading_days,
        "is_stale": is_stale,
        "warning": warning,
    }


# ─────────────────────────────────────────────────────────────────
#  TICKER NORMALISATION
# ─────────────────────────────────────────────────────────────────

def normalise_ticker(raw: str) -> str:
    """
    Accept any of these formats and return a valid yfinance NSE ticker:
    'RELIANCE', 'RELIANCE.NS', 'RELIANCE.BO', 'reliance'
    """
    raw = raw.strip().upper()
    if raw.endswith(".NS") or raw.endswith(".BO"):
        return raw
    return f"{raw}.NS"   # Default to NSE


def ticker_to_filename(ticker: str) -> str:
    """Convert ticker to CSV filename as saved by historical_data.py."""
    return f"{ticker}.csv"


# ─────────────────────────────────────────────────────────────────
#  LOCAL CSV LOADING
# ─────────────────────────────────────────────────────────────────

def load_from_csv(ticker: str, csv_dir: str = CSV_DIR) -> pd.DataFrame | None:
    """
    Load historical OHLCV data from a local CSV file.
    Returns a clean DataFrame with proper dtypes, or None if not found/invalid.
    """
    filename = ticker_to_filename(ticker)
    filepath = os.path.join(csv_dir, filename)

    if not os.path.exists(filepath):
        return None

    try:
        df = pd.read_csv(filepath)

        # Handle multi-level headers that yfinance sometimes creates
        if df.columns[0].startswith("Price") or df.columns[0] == "Ticker":
            df = pd.read_csv(filepath, header=[0, 1])
            df.columns = [c[1] if "Unnamed" not in str(c[1]) else c[0] for c in df.columns]

        # Normalise column names
        df.columns = [str(c).strip() for c in df.columns]

        # Find the date column
        date_col = None
        for col in ["Date", "date", "Datetime", "datetime", "index"]:
            if col in df.columns:
                date_col = col
                break

        if date_col is None:
            # Try first column
            df = df.rename(columns={df.columns[0]: "Date"})
            date_col = "Date"

        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col])
        df = df.set_index(date_col)
        df.index.name = "Date"
        df = df.sort_index()

        # Ensure required columns exist
        required = ["Open", "High", "Low", "Close", "Volume"]
        # Handle case-insensitive column names
        col_map = {c.lower(): c for c in df.columns}
        rename_map = {}
        for req in required:
            if req not in df.columns and req.lower() in col_map:
                rename_map[col_map[req.lower()]] = req
        if rename_map:
            df = df.rename(columns=rename_map)

        # Check Close exists at minimum
        if "Close" not in df.columns:
            return None

        # Add missing OHLCV columns if needed (e.g. only Close available)
        for col in ["Open", "High", "Low"]:
            if col not in df.columns:
                df[col] = df["Close"]
        if "Volume" not in df.columns:
            df["Volume"] = 0

        # Convert to numeric
        for col in required:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # Drop rows where Close is NaN
        df = df.dropna(subset=["Close"])

        # Drop rows with zero/negative close prices
        df = df[df["Close"] > 0]

        if len(df) < MIN_DATA_DAYS:
            return None

        return df

    except Exception as e:
        return None


# ─────────────────────────────────────────────────────────────────
#  LIVE DATA FETCH (yfinance)
# ─────────────────────────────────────────────────────────────────

def fetch_live_data(ticker: str, period: str = "2y") -> pd.DataFrame | None:
    """
    Fetch latest OHLCV data directly from Yahoo Finance.
    Used when local CSV is missing or stale (> 1 day old).
    """
    try:
        yf_ticker = yf.Ticker(ticker)
        df = yf_ticker.history(period=period, auto_adjust=True)

        if df is None or len(df) < MIN_DATA_DAYS:
            return None

        df.index = pd.to_datetime(df.index)
        df.index.name = "Date"

        # Keep only OHLCV
        cols_needed = ["Open", "High", "Low", "Close", "Volume"]
        existing = [c for c in cols_needed if c in df.columns]
        df = df[existing]

        for col in cols_needed:
            if col not in df.columns:
                df[col] = df.get("Close", 0)

        df = df.dropna(subset=["Close"])
        df = df[df["Close"] > 0]

        return df if len(df) >= MIN_DATA_DAYS else None

    except Exception:
        return None


def is_csv_stale(ticker: str, csv_dir: str = CSV_DIR, max_age_days: int = 1) -> bool:
    """Check if a local CSV file is older than max_age_days."""
    filename = ticker_to_filename(ticker)
    filepath = os.path.join(csv_dir, filename)
    if not os.path.exists(filepath):
        return True
    mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
    return (datetime.now() - mtime).days > max_age_days


def load_stock_data(ticker: str, csv_dir: str = CSV_DIR,
                    use_live_fallback: bool = True) -> pd.DataFrame | None:
    """
    Smart data loader:
    1. Try local CSV first (fast)
    2. If stale or missing → fetch live from yfinance
    3. Returns None if data is unavailable or insufficient
    """
    df = load_from_csv(ticker, csv_dir)

    if df is not None:
        # Check data freshness using trading calendar
        freshness = get_data_freshness(df)

        if freshness["trading_days_stale"] > 1 and use_live_fallback:
            live_df = fetch_live_data(ticker)
            if live_df is not None and len(live_df) > len(df):
                return live_df
        # Always return local CSV even if stale (offline / delisted stocks still valid for analysis)
        return df

    # No local CSV — try live fetch
    if use_live_fallback:
        return fetch_live_data(ticker)

    return None


# ─────────────────────────────────────────────────────────────────
#  SCAN ALL AVAILABLE TICKERS FROM CSV DIRECTORY
# ─────────────────────────────────────────────────────────────────

def get_all_tickers_from_csv(csv_dir: str = CSV_DIR) -> list[str]:
    """
    Return list of all valid tickers found in the CSV directory.
    Skips files with invalid names (e.g., '.NS.csv').
    """
    tickers = []
    csv_path = Path(csv_dir)
    if not csv_path.exists():
        return tickers

    for f in sorted(csv_path.glob("*.csv")):
        stem = f.stem  # e.g., 'RELIANCE.NS'
        # Skip invalid entries like '.NS'
        if stem.startswith(".") or len(stem) < 4:
            continue
        tickers.append(stem)

    return tickers


# ─────────────────────────────────────────────────────────────────
#  DOWNLOAD / UPDATE HISTORICAL DATA  (Fixed version of historical_data.py)
# ─────────────────────────────────────────────────────────────────

def download_all_historical_data(tickers: list[str], save_path: str,
                                  start_date: str = HISTORY_START,
                                  end_date: str = None,
                                  skip_existing: bool = True) -> dict:
    """
    Fixed & improved version of get_historical_data().
    Key fixes from original:
    1. Removed '.NS' invalid ticker
    2. Added error handling per ticker
    3. Added skip_existing to avoid re-downloading
    4. Handles yfinance multi-level column headers
    5. Validates data before saving
    """
    os.makedirs(save_path, exist_ok=True)

    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")

    results = {"success": [], "failed": [], "skipped": []}

    # Filter out invalid tickers
    valid_tickers = [t for t in tickers if t and not t.startswith(".") and len(t) > 3]

    print(f"  Downloading {len(valid_tickers)} tickers from {start_date} to {end_date}")

    for idx, ticker in enumerate(valid_tickers, 1):
        file_path = os.path.join(save_path, f"{ticker}.csv")

        if skip_existing and os.path.exists(file_path):
            results["skipped"].append(ticker)
            if idx % 100 == 0:
                print(f"  Progress: {idx}/{len(valid_tickers)} (skipping existing)")
            continue

        try:
            data = yf.download(
                ticker,
                start=start_date,
                end=end_date,
                auto_adjust=True,
                progress=False
            )

            if data is None or len(data) < 30:
                results["failed"].append(ticker)
                continue

            # Flatten multi-level columns if present
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = [col[0] for col in data.columns]

            data.to_csv(file_path)
            results["success"].append(ticker)

        except Exception as e:
            results["failed"].append(ticker)

        if idx % 50 == 0:
            print(f"  Progress: {idx}/{len(valid_tickers)} | "
                  f"OK: {len(results['success'])} | "
                  f"Failed: {len(results['failed'])}")

    print(f"\n  Download complete — "
          f"Success: {len(results['success'])} | "
          f"Failed: {len(results['failed'])} | "
          f"Skipped: {len(results['skipped'])}")
    return results
