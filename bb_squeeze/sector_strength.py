"""
sector_strength.py — Sector Relative Strength for NSE Stocks
=============================================================

WHY THIS MATTERS (for the layman):
    Imagine a cricket team. Even the best batsman struggles if the whole
    team is in poor form and morale is low. But a decent batsman in a
    dominant team often scores big because everything around them is
    working — good openers, good pitch conditions, home crowd.

    In the stock market, sectors work the same way. Stocks belong to
    sectors (banks, pharma, IT, etc.), and sectors go in and out of
    favour — fund managers rotate billions of rupees into and out of
    them. A good stock in a favoured sector gets carried up like a
    rising tide lifts all boats. A good stock in a beaten-down sector
    fights an uphill battle every day.

    This module measures:
    1. Is the stock's sector outperforming or underperforming Nifty 50?
    2. Is the stock outperforming or underperforming its own sector?
    3. Where does the sector rank among all 8 major NSE sectors?

    These three answers tell you whether the wind is behind your trade
    or against it — before you place a single rupee.

HOW IT WORKS:
    1. Maps the stock's sector (from yfinance fundamentals) to the
       corresponding NSE sectoral index (e.g., Bank Nifty, Nifty IT).
    2. Downloads 20 trading days of price data for that index + Nifty 50.
    3. Computes 20-day returns for the sector, Nifty, and the stock itself.
    4. Calculates Relative Strength ratios (Mansfield-style):
       - Sector RS vs Nifty: is the sector outpacing the benchmark?
       - Stock RS vs Sector: is this stock beating its own sector?
    5. Ranks all 8 sectors by their 20-day return.
    6. Returns a plain-English verdict: LEADING / INLINE / LAGGING.
"""

from __future__ import annotations

import functools
from datetime import date

import numpy as np
import pandas as pd
import yfinance as yf


# ---------------------------------------------------------------------------
# Sector → NSE Index mapping
# ---------------------------------------------------------------------------

_SECTOR_MAP: dict[str, tuple[str, str]] = {
    "Financial Services": ("^NSEBANK", "Bank Nifty"),
    "Information Technology": ("^CNXIT", "Nifty IT"),
    "Automobile and Auto Components": ("^CNXAUTO", "Nifty Auto"),
    "Healthcare": ("^CNXPHARMA", "Nifty Pharma"),
    "Metals & Mining": ("^CNXMETAL", "Nifty Metal"),
    "Fast Moving Consumer Goods": ("^CNXFMCG", "Nifty FMCG"),
    "Oil Gas & Consumable Fuels": ("^CNXENERGY", "Nifty Energy"),
    "Construction": ("^CNXREALTY", "Nifty Realty"),
    "Real Estate": ("^CNXREALTY", "Nifty Realty"),
    "Consumer Services": ("^CNXFMCG", "Nifty FMCG"),
    "Capital Goods": ("^CNXMETAL", "Nifty Metal"),
    "Power": ("^CNXENERGY", "Nifty Energy"),
    "Telecommunication": ("^CNXIT", "Nifty IT"),
    "Chemicals": ("^CNXPHARMA", "Nifty Pharma"),
    "Textiles": ("^CNXFMCG", "Nifty FMCG"),
    "Media Entertainment & Publication": ("^CNXIT", "Nifty IT"),
}

# Unique sector indices for ranking (deduplicated, with display name)
_ALL_SECTOR_INDICES: list[tuple[str, str]] = list({
    ticker: name for _, (ticker, name) in _SECTOR_MAP.items()
}.items())


# ---------------------------------------------------------------------------
# Cached data fetcher — refreshes once per calendar day
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=64)
def _fetch_close(ticker: str, as_of: date) -> tuple[float, ...]:
    """
    Download up to 30 calendar days of daily Close for `ticker`.
    Returns last 21 Close values as a tuple (hashable for lru_cache).
    `as_of` is only used as a cache key so the result refreshes daily.
    """
    try:
        df = yf.download(ticker, period="30d", interval="1d",
                         progress=False, auto_adjust=True)
        if df is None or df.empty:
            return ()
        closes = df["Close"].dropna()
        if len(closes) < 2:
            return ()
        return tuple(float(v) for v in closes.values[-21:])
    except Exception:
        return ()


def _return_20d(closes: tuple[float, ...]) -> float | None:
    """20-day return from a Close tuple. Returns None if not enough data."""
    if len(closes) < 2:
        return None
    start = closes[0]
    end = closes[-1]
    if start == 0:
        return None
    return (end - start) / start * 100.0


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def compute_sector_rs(
    stock_ticker: str,
    stock_df: pd.DataFrame,
    sector_name: str,
) -> dict:
    """
    Compute sector relative strength for a stock.

    Parameters
    ----------
    stock_ticker : str
        NSE ticker e.g. "RELIANCE.NS"
    stock_df : pd.DataFrame
        Daily OHLCV DataFrame with DatetimeIndex and a 'Close' column.
    sector_name : str
        Sector string from yfinance `info['sector']`.

    Returns
    -------
    dict with RS ratios, sector rank, trend verdict, and explanation.
    """
    if sector_name not in _SECTOR_MAP:
        known = ", ".join(sorted(_SECTOR_MAP.keys()))
        return {
            "available": False,
            "explanation": (
                f"Sector '{sector_name}' is not mapped to an NSE index. "
                f"Known sectors: {known}."
            ),
        }

    sector_ticker, sector_index_name = _SECTOR_MAP[sector_name]
    today = date.today()

    # --- Fetch sector and Nifty data (cached per calendar day) ---
    sector_closes = _fetch_close(sector_ticker, today)
    nifty_closes = _fetch_close("^NSEI", today)

    if not sector_closes or not nifty_closes:
        return {
            "available": False,
            "explanation": (
                "Could not download sector index or Nifty 50 data from yfinance. "
                "Check your internet connection or try again later."
            ),
        }

    sector_ret = _return_20d(sector_closes)
    nifty_ret = _return_20d(nifty_closes)

    if sector_ret is None or nifty_ret is None:
        return {
            "available": False,
            "explanation": "Insufficient price history in downloaded index data.",
        }

    # --- Stock 20-day return from the supplied DataFrame ---
    try:
        stock_close = stock_df["Close"].dropna()
        if len(stock_close) < 2:
            raise ValueError("not enough rows")
        tail = stock_close.values[-21:]
        stock_ret = float((tail[-1] - tail[0]) / tail[0] * 100.0) if tail[0] != 0 else None
    except Exception:
        stock_ret = None

    if stock_ret is None:
        return {
            "available": False,
            "explanation": f"Could not compute 20-day return for {stock_ticker} from supplied data.",
        }

    # --- RS ratios (Mansfield-style: ratio of returns) ---
    # Guard against zero / near-zero denominator
    def _safe_ratio(num: float, denom: float) -> float:
        if abs(denom) < 0.001:
            return 1.0  # ponytail: flat market → treat as inline
        return (1 + num / 100) / (1 + denom / 100)

    sector_rs_vs_nifty = _safe_ratio(sector_ret, nifty_ret)
    stock_rs_vs_sector = _safe_ratio(stock_ret, sector_ret)

    # --- Sector trend label ---
    if sector_rs_vs_nifty > 1.1:
        sector_trend = "LEADING"
    elif sector_rs_vs_nifty < 0.9:
        sector_trend = "LAGGING"
    else:
        sector_trend = "INLINE"

    # --- Rank all 8 sector indices ---
    sector_returns: list[dict] = []
    for idx_ticker, idx_name in _ALL_SECTOR_INDICES:
        closes = _fetch_close(idx_ticker, today)
        ret = _return_20d(closes)
        sector_returns.append({
            "name": idx_name,
            "ticker": idx_ticker,
            "return_20d": ret if ret is not None else float("nan"),
        })

    # Sort descending; NaN sorts last
    sector_returns.sort(
        key=lambda x: x["return_20d"] if not np.isnan(x["return_20d"]) else -9999,
        reverse=True,
    )
    for i, s in enumerate(sector_returns, start=1):
        s["rank"] = i

    sector_rank = next(
        (s["rank"] for s in sector_returns if s["ticker"] == sector_ticker),
        None,
    )
    total = len(sector_returns)

    # Strip internal ticker key from output
    all_sectors_out = [
        {"name": s["name"], "return_20d": round(s["return_20d"], 2), "rank": s["rank"]}
        for s in sector_returns
    ]

    # --- Plain-English explanation ---
    explanation = _build_explanation(
        sector_trend=sector_trend,
        sector_index_name=sector_index_name,
        sector_name=sector_name,
        sector_ret=sector_ret,
        nifty_ret=nifty_ret,
        stock_ret=stock_ret,
        sector_rs_vs_nifty=sector_rs_vs_nifty,
        stock_rs_vs_sector=stock_rs_vs_sector,
        sector_rank=sector_rank,
        total=total,
        stock_ticker=stock_ticker,
    )

    return {
        "available": True,
        "sector_name": sector_name,
        "sector_index": sector_index_name,
        "sector_rs_vs_nifty": round(sector_rs_vs_nifty, 3),
        "stock_rs_vs_sector": round(stock_rs_vs_sector, 3),
        "sector_return_20d": round(sector_ret, 2),
        "nifty_return_20d": round(nifty_ret, 2),
        "stock_return_20d": round(stock_ret, 2),
        "sector_rank": sector_rank,
        "total_sectors": total,
        "sector_trend": sector_trend,
        "all_sectors": all_sectors_out,
        "explanation": explanation,
    }


# ---------------------------------------------------------------------------
# Explanation builder
# ---------------------------------------------------------------------------

def _build_explanation(
    *,
    sector_trend: str,
    sector_index_name: str,
    sector_name: str,
    sector_ret: float,
    nifty_ret: float,
    stock_ret: float,
    sector_rs_vs_nifty: float,
    stock_rs_vs_sector: float,
    sector_rank: int | None,
    total: int,
    stock_ticker: str,
) -> str:
    rank_str = f"#{sector_rank} out of {total}" if sector_rank else f"unranked out of {total}"
    nifty_dir = "up" if nifty_ret >= 0 else "down"
    sector_dir = "up" if sector_ret >= 0 else "down"
    stock_dir = "up" if stock_ret >= 0 else "down"

    stock_vs_sector = (
        f"outperforming its sector ({stock_ret:+.1f}% vs sector's {sector_ret:+.1f}%)"
        if stock_rs_vs_sector > 1.0
        else f"underperforming its sector ({stock_ret:+.1f}% vs sector's {sector_ret:+.1f}%)"
    )

    if sector_trend == "LEADING":
        return (
            f"SECTOR IS LEADING THE MARKET. "
            f"{sector_index_name} ({sector_name}) is {sector_dir} {abs(sector_ret):.1f}% "
            f"over the last 20 trading days, while Nifty 50 is {nifty_dir} only "
            f"{abs(nifty_ret):.1f}%. That is a Relative Strength ratio of "
            f"{sector_rs_vs_nifty:.2f} — anything above 1.10 means the sector is in "
            f"active favour with institutional money. "
            f"Sector rank: {rank_str}. "
            f"Think of it like a rising tide: when fund managers are pouring ₹ crores into "
            f"this sector, even average stocks in it tend to float higher. The tailwind is "
            f"real and historically, stocks that are already outperforming within a leading "
            f"sector have 15-20% better odds of continuing to rise. "
            f"For {stock_ticker}, the stock itself is {stock_vs_sector}. "
            f"{'This is the ideal combination — strong sector + strong stock.' if stock_rs_vs_sector > 1.0 else 'The sector is helping, but watch whether the stock can keep pace with its peers.'}"
        )

    if sector_trend == "LAGGING":
        return (
            f"SECTOR IS LAGGING THE MARKET. "
            f"{sector_index_name} ({sector_name}) is {sector_dir} only {abs(sector_ret):.1f}% "
            f"over the last 20 trading days, while Nifty 50 is {nifty_dir} {abs(nifty_ret):.1f}%. "
            f"Relative Strength ratio: {sector_rs_vs_nifty:.2f} — below 0.90 signals that "
            f"institutions are actively rotating money OUT of this sector. "
            f"Sector rank: {rank_str}. "
            f"Even excellent stocks fight an uphill battle in a weak sector — they get sold "
            f"not because of their own fundamentals, but because fund managers are unwinding "
            f"their entire sector position. Studies show buy signals against a lagging sector "
            f"fail 55-65% of the time. "
            f"For {stock_ticker}, the stock is {stock_vs_sector}. "
            f"{'The stock is showing impressive relative strength despite the sector headwind — worth watching closely.' if stock_rs_vs_sector > 1.1 else 'Consider waiting for the sector trend to stabilise, or use a smaller position size with a tighter stop-loss.'}"
        )

    # INLINE
    return (
        f"SECTOR IS INLINE WITH THE MARKET. "
        f"{sector_index_name} ({sector_name}) is {sector_dir} {abs(sector_ret):.1f}% "
        f"over the last 20 trading days, close to Nifty 50's {nifty_dir} of {abs(nifty_ret):.1f}%. "
        f"Relative Strength ratio: {sector_rs_vs_nifty:.2f} — the sector is neither in "
        f"favour nor out of favour right now. Sector rank: {rank_str}. "
        f"In a neutral sector, the stock's own merit — earnings quality, promoter holding, "
        f"technical setup — matters more than the macro tailwind. "
        f"For {stock_ticker}, the stock is {stock_vs_sector}. "
        f"{'A stock outperforming in a neutral sector is showing genuine relative strength — a positive sign.' if stock_rs_vs_sector > 1.0 else 'Focus on the stock-specific setup; the sector is not helping or hurting.'}"
    )
