"""
nse_bhavcopy.py — NSE Bhavcopy daily EOD updater
=================================================
Downloads the official NSE UDiFF bhavcopy CSV and appends new rows
to existing stock_csv/{SYMBOL}.NS.csv files.

One download covers ALL ~2800 EQ+BE stocks — no per-ticker API calls,
no Yahoo rate limits, no Close=NaN issues.

Usage:
    python nse_bhavcopy.py                    # update with latest trading day
    python nse_bhavcopy.py 2026-08-19         # specific date
    python nse_bhavcopy.py 2026-08-15 2026-08-19  # date range
"""

from __future__ import annotations
import os
import io
import csv
import sys
import zipfile
from datetime import date, datetime, timedelta

import requests
import pandas as pd

# ── config ───────────────────────────────────────────────────────
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAVE_PATH = os.path.join(_BASE_DIR, "stock_csv")

BHAVCOPY_URL = (
    "https://nsearchives.nseindia.com/content/cm/"
    "BhavCopy_NSE_CM_0_0_0_{date}_F_0000.csv.zip"
)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.nseindia.com/",
}
ALLOWED_SERIES = {"EQ", "BE"}


def _last_trading_day() -> date:
    """Most recent weekday (Mon-Fri). Bhavcopy won't exist for today
    until ~6 PM IST, so default to yesterday on weekdays before 18:30."""
    from datetime import timezone
    import zoneinfo
    try:
        ist = zoneinfo.ZoneInfo("Asia/Kolkata")
    except Exception:
        ist = timezone(timedelta(hours=5, minutes=30))

    now = datetime.now(ist)
    d = now.date()
    # if before 6:30 PM IST on a weekday, yesterday's bhavcopy is latest
    if d.weekday() < 5 and now.hour < 18:
        d -= timedelta(days=1)
    # walk back to Friday if weekend
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def fetch_bhavcopy(dt: date) -> list[dict]:
    """Download and parse bhavcopy for a single date.
    Returns list of dicts with keys: Symbol, Date, Open, High, Low, Close, Volume.
    Raises on 404 (holiday/weekend) or network error."""
    url = BHAVCOPY_URL.format(date=dt.strftime("%Y%m%d"))
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        raw = z.read(z.namelist()[0]).decode("utf-8")

    rows = []
    reader = csv.DictReader(raw.strip().split("\n"))
    required_cols = {"TckrSymb", "SctySrs", "OpnPric", "HghPric", "LwPric", "ClsPric", "TtlTradgVol"}
    if reader.fieldnames and not required_cols.issubset(set(reader.fieldnames)):
        missing = required_cols - set(reader.fieldnames)
        raise ValueError(f"Bhavcopy column format changed — missing: {missing}")
    for row in reader:
        series = row.get("SctySrs", "").strip()
        if series not in ALLOWED_SERIES:
            continue
        try:
            rows.append({
                "Symbol": row["TckrSymb"].strip(),
                "Date":   dt.strftime("%Y-%m-%d"),
                "Open":   float(row["OpnPric"]),
                "High":   float(row["HghPric"]),
                "Low":    float(row["LwPric"]),
                "Close":  float(row["ClsPric"]),
                "Volume": int(row["TtlTradgVol"]),
            })
        except (KeyError, ValueError):
            continue
    return rows


def update_csvs(records: list[dict], save_path: str = SAVE_PATH) -> dict:
    """Append bhavcopy records to existing CSV files.
    Returns summary: {new, updated, skipped}."""
    os.makedirs(save_path, exist_ok=True)
    stats = {"new": 0, "updated": 0, "skipped": 0}

    for rec in records:
        fname = f"{rec['Symbol']}.NS.csv"
        fpath = os.path.join(save_path, fname)
        row_date = rec["Date"]

        if os.path.exists(fpath):
            # check if date already present (avoid duplicates)
            try:
                existing = pd.read_csv(fpath)
                dates = existing["Date"].astype(str).values
                if row_date in dates:
                    stats["skipped"] += 1
                    continue
            except Exception:
                pass  # corrupt file — overwrite
            stats["updated"] += 1
        else:
            stats["new"] += 1

        # Adj Close = Close for same-day bhavcopy (no split/dividend adjustment)
        line = (
            f"{row_date},{rec['Open']},{rec['High']},"
            f"{rec['Low']},{rec['Close']},{rec['Close']},{rec['Volume']}\n"
        )

        if not os.path.exists(fpath):
            with open(fpath, "w") as f:
                f.write("Date,Open,High,Low,Close,Adj Close,Volume\n")
                f.write(line)
        else:
            with open(fpath, "a") as f:
                f.write(line)
            # keep CSV date-sorted (matters if back-filling old dates)
            try:
                tmp = pd.read_csv(fpath)
                if not tmp["Date"].is_monotonic_increasing:
                    tmp["Date"] = pd.to_datetime(tmp["Date"])
                    tmp = tmp.sort_values("Date").drop_duplicates("Date", keep="last")
                    tmp["Date"] = tmp["Date"].dt.strftime("%Y-%m-%d")
                    tmp.to_csv(fpath, index=False)
            except Exception:
                pass

    return stats


def run(dates: list[date] | None = None, save_path: str = SAVE_PATH) -> list[dict]:
    """Main entry point. Downloads bhavcopy for given dates and updates CSVs.
    Returns list of per-date summaries."""
    if dates is None:
        dates = [_last_trading_day()]

    results = []
    for dt in dates:
        tag = dt.strftime("%Y-%m-%d")
        print(f"  {tag} ... ", end="", flush=True)
        try:
            records = fetch_bhavcopy(dt)
            stats = update_csvs(records, save_path)
            print(f"OK  ({len(records)} stocks — "
                  f"{stats['updated']} updated, {stats['new']} new, "
                  f"{stats['skipped']} skipped)")
            results.append({"date": tag, "stocks": len(records), **stats})
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                print("SKIP (holiday/no data)")
            else:
                print(f"FAIL ({e})")
            results.append({"date": tag, "stocks": 0, "error": str(e)})
        except Exception as e:
            print(f"FAIL ({e})")
            results.append({"date": tag, "stocks": 0, "error": str(e)})

    return results


def _parse_date(s: str) -> date:
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


if __name__ == "__main__":
    args = sys.argv[1:]
    print(f"\n{'─'*50}")
    print("  NSE Bhavcopy Daily Updater")
    print(f"  Output: {SAVE_PATH}")
    print(f"{'─'*50}\n")

    if len(args) == 0:
        dates = None  # auto-detect latest
    elif len(args) == 1:
        dates = [_parse_date(args[0])]
    elif len(args) == 2:
        start, end = _parse_date(args[0]), _parse_date(args[1])
        dates = []
        d = start
        while d <= end:
            if d.weekday() < 5:  # skip weekends
                dates.append(d)
            d += timedelta(days=1)
    else:
        print("Usage: python nse_bhavcopy.py [date] [end_date]")
        sys.exit(1)

    results = run(dates)

    print(f"\n{'─'*50}")
    total = sum(r.get("updated", 0) + r.get("new", 0) for r in results)
    print(f"  Done — {total} files touched across {len(results)} day(s)")
    print(f"{'─'*50}\n")
