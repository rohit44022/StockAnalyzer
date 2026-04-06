"""
historical_data.py
──────────────────
Downloads historical OHLCV data for all NSE stocks and saves each
as a CSV file in stock_csv/.

Key features
  • end_date auto-set to TODAY (re-run any day to refresh)
  • Skips already-downloaded files unless --force flag is set
  • Handles yfinance ≥ 1.x multi-level column headers properly
  • Filters out invalid tickers (e.g. bare '.NS')
  • Retries failed downloads once before giving up
  • Prints a clean progress summary at the end
"""

import os
import io
import csv
import json
import time
import warnings
import logging
from datetime import date, datetime

import requests
import yfinance as yf
import pandas as pd

# ── silence yfinance/urllib noise ──────────────────────────────────
warnings.filterwarnings("ignore")
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.CRITICAL)


# ══════════════════════════════════════════════════════════════════
#  CONFIGURATION  — edit only this section if needed
# ══════════════════════════════════════════════════════════════════

START_DATE  = "2020-01-01"
END_DATE    = date.today().strftime("%Y-%m-%d")   # always today's date
SAVE_PATH   = "/Users/rttripathirttripathi/Rohit/coding/StockCode/ historical_data/stock_csv/"
SKIP_EXISTING = True   # set False to re-download everything from scratch
RETRY_ONCE    = True   # retry a failed ticker once before skipping
STALENESS_DAYS = 4     # re-download if last CSV date is older than this many calendar days
                       # (4 covers Mon/Tue when last trade was Fri; holidays/long weekends)

_HD_DATA_DIR = os.environ.get("STOCK_APP_DATA", os.path.dirname(os.path.abspath(__file__)))
TICKERS_CACHE_FILE = os.path.join(_HD_DATA_DIR, "tickers_cache.json")


# ══════════════════════════════════════════════════════════════════
#  LIVE TICKER FETCHING  — pulls EQ-series symbols from NSE
# ══════════════════════════════════════════════════════════════════

NSE_EQUITY_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"


def fetch_nse_tickers(include_sme: bool = False) -> list[str]:
    """
    Fetch the current list of NSE-listed equity symbols from
    the official NSE archives CSV.

    Parameters
    ----------
    include_sme : if True, include BE-series (SME / book-entry) stocks
                  in addition to EQ-series.

    Returns
    -------
    Sorted list of Yahoo Finance-style tickers, e.g. ['RELIANCE.NS', ...]
    """
    hdrs = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    resp = requests.get(NSE_EQUITY_URL, headers=hdrs, timeout=30)
    resp.raise_for_status()

    reader = csv.DictReader(io.StringIO(resp.text))
    allowed_series = {"EQ"}
    if include_sme:
        allowed_series.add("BE")

    symbols = []
    for row in reader:
        series = row.get(" SERIES", "").strip()
        if series in allowed_series:
            sym = row.get("SYMBOL", "").strip()
            if sym:
                symbols.append(f"{sym}.NS")

    return sorted(set(symbols))


def refresh_tickers_cache(include_sme: bool = False) -> dict:
    """
    Fetch live tickers from NSE, save to local JSON cache, and return
    a summary dict with keys: count, fetched_at, tickers.
    """
    tickers = fetch_nse_tickers(include_sme=include_sme)
    payload = {
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "NSE EQUITY_L.csv",
        "include_sme": include_sme,
        "count": len(tickers),
        "tickers": tickers,
    }
    with open(TICKERS_CACHE_FILE, "w") as f:
        json.dump(payload, f, indent=2)
    return payload


def load_tickers() -> list[str]:
    """
    Load tickers with priority:
      1. Cached JSON file (tickers_cache.json)
      2. Live fetch from NSE (creates cache)
      3. Hardcoded fallback list
    """
    # 1. Try cached file
    if os.path.exists(TICKERS_CACHE_FILE):
        try:
            with open(TICKERS_CACHE_FILE) as f:
                data = json.load(f)
            tickers = data.get("tickers", [])
            if tickers:
                return tickers
        except Exception:
            pass

    # 2. Try live fetch
    try:
        result = refresh_tickers_cache()
        return result["tickers"]
    except Exception:
        pass

    # 3. Fallback to hardcoded (minimal Nifty-50 set)
    return list(_HARDCODED_TICKERS)


# Minimal fallback — only Nifty-50 constituents.
# The full universe is fetched dynamically from NSE (see fetch_nse_tickers).
_HARDCODED_TICKERS = [
    'ADANIENT.NS', 'ADANIPORTS.NS', 'APOLLOHOSP.NS', 'ASIANPAINT.NS',
    'AXISBANK.NS', 'BAJAJ-AUTO.NS', 'BAJFINANCE.NS', 'BAJAJFINSV.NS',
    'BEL.NS', 'BPCL.NS', 'BHARTIARTL.NS', 'BRITANNIA.NS',
    'CIPLA.NS', 'COALINDIA.NS', 'DRREDDY.NS', 'EICHERMOT.NS',
    'GRASIM.NS', 'HCLTECH.NS', 'HDFCBANK.NS', 'HDFCLIFE.NS',
    'HEROMOTOCO.NS', 'HINDALCO.NS', 'HINDUNILVR.NS', 'ICICIBANK.NS',
    'INDUSINDBK.NS', 'INFY.NS', 'ITC.NS', 'JSWSTEEL.NS',
    'KOTAKBANK.NS', 'LT.NS', 'M&M.NS', 'MARUTI.NS',
    'NESTLEIND.NS', 'NTPC.NS', 'ONGC.NS', 'POWERGRID.NS',
    'RELIANCE.NS', 'SBILIFE.NS', 'SBIN.NS', 'SHRIRAMFIN.NS',
    'SUNPHARMA.NS', 'TCS.NS', 'TATACONSUM.NS', 'TATAMOTORS.NS',
    'TATASTEEL.NS', 'TECHM.NS', 'TITAN.NS', 'TRENT.NS',
    'ULTRACEMCO.NS', 'WIPRO.NS',
]

# ── Build TICKERS dynamically (cached → live NSE → hardcoded fallback) ──
TICKERS = load_tickers()


# ══════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════

def _is_valid_ticker(t: str) -> bool:
    """Filter out blank or stub entries like '.NS'."""
    t = t.strip()
    return bool(t) and not t.startswith(".") and len(t) > 3


def _clean_df(data: pd.DataFrame, ticker: str) -> pd.DataFrame | None:
    """
    Normalise a raw yfinance DataFrame to flat Date-indexed OHLCV CSV.
    Handles both flat and multi-level column headers (yfinance ≥ 1.x).
    """
    if data is None or data.empty:
        return None

    df = data.copy()

    # ── flatten multi-level columns produced by yfinance ≥ 1.x ──
    if isinstance(df.columns, pd.MultiIndex):
        # ('Close', 'RELIANCE.NS') → 'Close'
        df.columns = [col[0] if isinstance(col, tuple) else col
                      for col in df.columns]

    # ── keep only the 6 columns we need ──
    wanted = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
    df = df[[c for c in wanted if c in df.columns]]

    # must have at least Close
    if "Close" not in df.columns:
        return None

    # ── clean index — strip timezone AND time component, keep date only ──
    dt_index = pd.to_datetime(df.index, utc=True).tz_convert("Asia/Kolkata")
    df.index = dt_index.normalize().tz_localize(None).date  # → pure date objects
    df.index = pd.DatetimeIndex(df.index)                   # back to DatetimeIndex
    df.index.name = "Date"
    df = df.sort_index()

    # ── numeric coercion & drop bad rows ──
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["Close"])
    df = df[df["Close"] > 0]

    return df if not df.empty else None


def _download_one(ticker: str, start: str, end: str,
                   save_path: str, skip_existing: bool,
                   retry: bool) -> str:
    """
    Download one ticker and save CSV.
    Returns one of: 'skipped' | 'saved' | 'no_data' | 'error'
    """
    file_path = os.path.join(save_path, f"{ticker}.csv")

    # ── skip only if CSV exists AND is already up-to-date ──
    if skip_existing and os.path.exists(file_path):
        try:
            existing = pd.read_csv(file_path)
            # valid file must have 'Date' column and meaningful data
            if existing.columns[0] == "Date" and len(existing) > 10:
                last_date = pd.to_datetime(existing["Date"].iloc[-1])
                today = pd.Timestamp.today().normalize()
                # consider the file up-to-date if last row is within STALENESS_DAYS
                # of today (accounts for weekends / holidays)
                days_old = (today - last_date).days
                if days_old <= STALENESS_DAYS:
                    return "skipped"
                # else: stale file → fall through and re-download
        except Exception:
            pass  # corrupt file → re-download

    attempts = 2 if retry else 1
    for attempt in range(attempts):
        try:
            t = yf.Ticker(ticker)
            raw = t.history(start=start, end=end, auto_adjust=False)

            df = _clean_df(raw, ticker)
            if df is None or df.empty:
                if attempt == 0 and retry:
                    time.sleep(1)
                    continue
                return "no_data"

            df.to_csv(file_path)
            return "saved"

        except Exception:
            if attempt == 0 and retry:
                time.sleep(2)
            else:
                return "error"

    return "error"


# ══════════════════════════════════════════════════════════════════
#  MAIN DOWNLOAD FUNCTION
# ══════════════════════════════════════════════════════════════════

def get_historical_data(tickers: list[str],
                         start_date: str,
                         end_date: str,
                         save_path: str,
                         skip_existing: bool = SKIP_EXISTING,
                         retry_once: bool = RETRY_ONCE) -> None:
    """
    Download historical OHLCV data for each ticker and save as CSV.

    Parameters
    ----------
    tickers       : list of NSE ticker strings (e.g. 'RELIANCE.NS')
    start_date    : 'YYYY-MM-DD'
    end_date      : 'YYYY-MM-DD'  — use date.today().strftime(...) for live
    save_path     : directory to write CSV files
    skip_existing : if True, skip tickers that already have a valid CSV
    retry_once    : if True, retry failed downloads once
    """
    os.makedirs(save_path, exist_ok=True)

    # Filter out invalid tickers (e.g. bare '.NS' entry)
    valid = [t for t in tickers if _is_valid_ticker(t)]
    skipped_invalid = len(tickers) - len(valid)

    total   = len(valid)
    saved   = 0
    skipped = 0
    no_data = 0
    errors  = 0

    print(f"\n{'─'*60}")
    print(f"  NSE Historical Data Downloader")
    print(f"  Period  : {start_date}  →  {end_date}")
    print(f"  Tickers : {total}  (skipped {skipped_invalid} invalid)")
    print(f"  Output  : {save_path}")
    print(f"{'─'*60}\n")

    for i, ticker in enumerate(valid, 1):
        status = _download_one(ticker, start_date, end_date,
                                save_path, skip_existing, retry_once)

        if status == "saved":
            saved += 1
            tag = "✓ saved"
        elif status == "skipped":
            skipped += 1
            tag = "– skipped (already up-to-date)"
        elif status == "no_data":
            no_data += 1
            tag = "✗ no data"
        else:
            errors += 1
            tag = "✗ error"

        # print every ticker so user sees live progress
        print(f"  [{i:>4}/{total}]  {ticker:<22}  {tag}")

    print(f"\n{'─'*60}")
    print(f"  DONE  |  saved={saved}  skipped={skipped}  "
          f"no_data={no_data}  errors={errors}")
    print(f"{'─'*60}\n")


# ══════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    get_historical_data(
        tickers      = TICKERS,
        start_date   = START_DATE,
        end_date     = END_DATE,
        save_path    = SAVE_PATH,
        skip_existing= SKIP_EXISTING,
        retry_once   = RETRY_ONCE,
    )

