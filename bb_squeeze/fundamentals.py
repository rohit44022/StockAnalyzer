"""
fundamentals.py — Intelligent Stock Fundamental Analyser.
Fetches financial metrics via yfinance and runs a multi-factor
scoring engine to produce a clear BUY / HOLD / AVOID verdict.
"""

import yfinance as yf
import pandas as pd
import requests as _requests
import warnings
import logging
import random
import math
import datetime as _dt
from dataclasses import dataclass, field
from typing import Optional, List, Dict
import time

# Suppress yfinance internal JSON/network errors
warnings.filterwarnings("ignore")
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.CRITICAL)

# ── Shared rate-limit state ───────────────────────────────────────
_last_call_time: float = 0.0
_MIN_INTERVAL: float   = 1.2   # minimum seconds between Yahoo API calls


@dataclass
class QuarterlyResult:
    """One quarter of financial results for YoY / QoQ comparison."""
    period:       str   = ""       # e.g. "Q3 FY25"
    revenue:      Optional[float] = None
    net_income:   Optional[float] = None
    eps:          Optional[float] = None
    gross_profit: Optional[float] = None
    ebitda:       Optional[float] = None
    operating_income: Optional[float] = None
    interest_expense: Optional[float] = None
    pretax_income:    Optional[float] = None
    tax_provision:    Optional[float] = None
    gross_margin:     Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin:       Optional[float] = None


@dataclass
class DividendEntry:
    """One dividend payment."""
    date:   str = ""
    amount: float = 0.0


@dataclass
class EarningsDateEntry:
    """One earnings date row (past or upcoming)."""
    date:         str = ""
    eps_estimate: Optional[float] = None
    eps_reported: Optional[float] = None
    surprise_pct: Optional[float] = None


@dataclass
class ShareholdingMonth:
    """Shareholding snapshot for one period (quarter/month)."""
    period:   str   = ""
    promoter: Optional[float] = None
    fii:      Optional[float] = None
    dii:      Optional[float] = None
    public:   Optional[float] = None


@dataclass
class DeliveryDay:
    """One day of historical delivery data from NSE bhavcopy."""
    date:         str   = ""
    close_price:  float = 0.0
    volume:       int   = 0
    delivery_qty: int   = 0
    delivery_pct: float = 0.0


@dataclass
class AnnualFinancial:
    """One fiscal year of financial statement data."""
    year:              str   = ""     # e.g. "FY2024" or "Mar 2024"
    # ── Income Statement ──
    total_revenue:     Optional[float] = None
    cost_of_revenue:   Optional[float] = None
    gross_profit:      Optional[float] = None
    operating_expense: Optional[float] = None
    operating_income:  Optional[float] = None
    ebitda:            Optional[float] = None
    ebit:              Optional[float] = None
    interest_expense:  Optional[float] = None
    pretax_income:     Optional[float] = None
    tax_provision:     Optional[float] = None
    net_income:        Optional[float] = None
    diluted_eps:       Optional[float] = None
    # ── Balance Sheet ──
    total_assets:          Optional[float] = None
    total_current_assets:  Optional[float] = None
    cash_and_equivalents:  Optional[float] = None
    inventory:             Optional[float] = None
    accounts_receivable:   Optional[float] = None
    net_ppe:               Optional[float] = None
    goodwill:              Optional[float] = None
    total_liabilities:     Optional[float] = None
    total_current_liab:    Optional[float] = None
    long_term_debt:        Optional[float] = None
    total_debt:            Optional[float] = None
    stockholders_equity:   Optional[float] = None
    retained_earnings:     Optional[float] = None
    working_capital:       Optional[float] = None
    # ── Cash Flow ──
    operating_cashflow:    Optional[float] = None
    capex:                 Optional[float] = None
    free_cashflow:         Optional[float] = None
    investing_cashflow:    Optional[float] = None
    financing_cashflow:    Optional[float] = None
    dividends_paid:        Optional[float] = None
    debt_repayment:        Optional[float] = None
    debt_issuance:         Optional[float] = None
    depreciation:          Optional[float] = None
    # ── Computed Ratios (per year) ──
    gross_margin:      Optional[float] = None   # %
    operating_margin:  Optional[float] = None   # %
    net_margin:        Optional[float] = None   # %
    roe:               Optional[float] = None   # %
    roa:               Optional[float] = None   # %
    debt_to_equity:    Optional[float] = None
    current_ratio:     Optional[float] = None
    interest_coverage: Optional[float] = None
    fcf_margin:        Optional[float] = None   # %


@dataclass
class BulkBlockDeal:
    """One bulk or block deal entry from NSE."""
    date:        str = ""
    deal_type:   str = ""    # 'BULK' or 'BLOCK'
    client_name: str = ""
    buy_sell:    str = ""    # 'BUY' or 'SELL'
    quantity:    int = 0
    price:       float = 0.0  # weighted avg trade price
    remarks:     str = ""


@dataclass
class InsiderTrade:
    """One insider / PIT (Prohibition of Insider Trading) entry from NSE."""
    person_name:  str = ""
    category:     str = ""    # 'Promoter', 'Promoter Group', 'Director', etc.
    txn_type:     str = ""    # 'Buy' or 'Sell'
    shares:       int = 0
    value:        float = 0.0  # ₹ value of transaction
    date_from:    str = ""
    date_to:      str = ""
    post_shares:  int = 0      # shares held after txn
    mode:         str = ""    # 'Market', 'Off Market', etc.


@dataclass
class FundamentalData:
    """Complete fundamental data for a stock."""
    ticker: str

    # ── Company Info ──
    company_name:   str = "N/A"
    sector:         str = "N/A"
    industry:       str = "N/A"
    market_cap:     float = 0.0
    market_cap_str: str = "N/A"
    enterprise_value: float = 0.0
    enterprise_value_str: str = "N/A"
    exchange:       str = "NSE"
    description:    str = ""
    outstanding_shares: Optional[float] = None   # in millions

    # ── VALUATION ANALYSIS ──
    pe_ratio:         Optional[float] = None   # P/E Ratio (TTM)
    forward_pe:       Optional[float] = None   # Forward P/E
    pb_ratio:         Optional[float] = None   # Price / Book Value
    ps_ratio:         Optional[float] = None   # Price / Sales (TTM)
    ev_ebitda:        Optional[float] = None   # EV / EBITDA
    peg_ratio:        Optional[float] = None   # PEG Ratio (Price/Earnings/Growth)
    price_to_fcf:     Optional[float] = None   # Price / Free Cash Flow
    earning_yield:    Optional[float] = None   # Earnings Yield % (1/PE × 100)
    book_value:       Optional[float] = None   # Book Value per share ₹
    intrinsic_value:  Optional[float] = None   # Graham Number ₹
    price_to_intrinsic: Optional[float] = None # Price / Intrinsic Value ratio
    graham_number:    Optional[float] = None   # √(22.5 × EPS × Book Value)

    # ── PROFITABILITY ANALYSIS ──
    roe:              Optional[float] = None   # Return on Equity %
    roa:              Optional[float] = None   # Return on Assets %
    roce:             Optional[float] = None   # Return on Capital Employed %
    profit_margin:    Optional[float] = None   # Net Profit Margin %
    operating_margin: Optional[float] = None   # Operating Margin %
    gross_margin:     Optional[float] = None   # Gross Margin %
    ebitda_margin:    Optional[float] = None   # EBITDA Margin %
    ebitda:           Optional[float] = None   # EBITDA ₹
    eps_ttm:          Optional[float] = None   # EPS (TTM) ₹
    eps_forward:      Optional[float] = None   # Forward EPS ₹

    # ── GROWTH ANALYSIS ──
    revenue_growth:       Optional[float] = None   # Revenue growth YoY %
    earnings_growth:      Optional[float] = None   # Earnings/EPS growth YoY %
    total_revenue:        Optional[float] = None   # Total Revenue ₹
    gross_profit:         Optional[float] = None   # Gross Profit ₹
    net_income:           Optional[float] = None   # Net Income ₹
    free_cash_flow:       Optional[float] = None   # Free Cash Flow ₹
    total_assets:         Optional[float] = None   # Total Assets ₹
    total_assets_growth:  Optional[float] = None   # Total Assets growth YoY %

    # ── STABILITY ANALYSIS ──
    debt_to_equity:   Optional[float] = None   # Debt/Equity ratio
    debt_to_ebitda:   Optional[float] = None   # Debt/EBITDA ratio (computed)
    current_ratio:    Optional[float] = None   # Current Ratio
    quick_ratio:      Optional[float] = None   # Quick Ratio
    cash_ratio:       Optional[float] = None   # Cash Ratio
    total_debt:       Optional[float] = None   # Total Debt ₹
    total_cash:       Optional[float] = None   # Total Cash ₹
    shareholders_equity: Optional[float] = None  # Shareholders Equity ₹
    altman_z_score:   Optional[float] = None   # Altman Z-Score (stability metric)
    interest_coverage: Optional[float] = None  # EBIT / Interest Expense
    asset_turnover:    Optional[float] = None  # Revenue / Total Assets
    debt_to_assets:    Optional[float] = None  # Total Debt / Total Assets

    # ── DIVIDENDS ──
    dividend_yield:   Optional[float] = None   # Dividend Yield %
    dividend_rate:    Optional[float] = None   # Annual Dividend ₹
    payout_ratio:     Optional[float] = None   # Payout Ratio %
    ex_dividend_date: Optional[str]   = None   # last ex-dividend date
    dividend_history: List[DividendEntry] = field(default_factory=list)  # last 10+ dividends

    # ── PRICE DATA ──
    current_price:    float = 0.0
    week_52_high:     float = 0.0
    week_52_low:      float = 0.0
    week_52_pct:      float = 0.0      # % from 52-week high
    avg_volume:       float = 0.0
    beta:             Optional[float] = None

    # ── SHAREHOLDING (current snapshot) ──
    promoter_holding:   Optional[float] = None   # % promoter holding
    fii_holding:        Optional[float] = None   # % FII / Institutional holding
    dii_holding:        Optional[float] = None   # % DII holding
    public_holding:     Optional[float] = None   # % public / float holding
    float_pct:          Optional[float] = None   # Float / Outstanding shares %

    # ── SHAREHOLDING HISTORY (last ~6 quarters from yfinance) ──
    shareholding_history: List[ShareholdingMonth] = field(default_factory=list)

    # ── QUARTERLY RESULTS (last 4–6 quarters for comparison) ──
    quarterly_results: List[QuarterlyResult] = field(default_factory=list)

    # ── EARNINGS CALENDAR ──
    upcoming_results_date: Optional[str] = None    # next earnings date (if known)
    earnings_estimate_eps: Optional[float] = None  # consensus EPS estimate for next quarter
    earnings_dates_history: List[EarningsDateEntry] = field(default_factory=list)

    # ── DESCRIPTIVE SUMMARIES ──
    quarterly_analysis: str = ""    # brief analysis of recent quarterly results
    shareholding_verdict: str = ""  # textual analysis of shareholding trend
    dividend_summary: str = ""      # textual analysis of dividend history

    # ── SECTION SCORES (0-100 each) ──
    valuation_score:    int = 0
    profitability_score: int = 0
    growth_score:       int = 0
    stability_score:    int = 0
    fundamental_score:  int = 0    # overall 0-100

    # ── TEXT SUMMARIES ──
    valuation_analysis:    str = ""
    profitability_analysis: str = ""
    growth_analysis:       str = ""
    stability_analysis:    str = ""
    fundamental_verdict:   str = "N/A"
    conviction_message:    str = ""

    # ── OVERALL VERDICT ──
    fundamental_signal:   str = ""     # "BUY" / "HOLD" / "AVOID"
    signal_strength:      str = ""     # "STRONG" / "MODERATE" / "WEAK"
    signal_color:         str = ""     # "green" / "yellow" / "red"

    # ── FINANCIAL STATEMENTS (annual, last 4 years) ──
    annual_financials: List[AnnualFinancial] = field(default_factory=list)
    financial_statements_analysis: str = ""

    # ── DELIVERY DATA (from NSE) ──
    delivery_quantity:  Optional[int]   = None   # shares delivered
    traded_quantity:    Optional[int]   = None   # shares traded
    delivery_pct:       Optional[float] = None   # delivery %
    delivery_date:      Optional[str]   = None   # date of data
    delivery_analysis:  str = ""                  # textual description

    # ── HISTORICAL DELIVERY DATA (from NSE bhavcopy) ──
    delivery_history:          List[DeliveryDay] = field(default_factory=list)
    delivery_history_analysis: str = ""

    # ── BULK / BLOCK DEALS & INSIDER TRADING (from NSE) ──
    bulk_block_deals:   List[BulkBlockDeal] = field(default_factory=list)
    insider_trades:     List[InsiderTrade]  = field(default_factory=list)
    deals_analysis:     str = ""    # textual analysis of deals

    # ── Error ──
    fetch_error: str = ""


def _safe_pct(val, already_pct: bool = False) -> Optional[float]:
    """Convert to percentage safely.

    yfinance is inconsistent:
      • Most ratios (ROE, margins, growth) come as decimals (0.42 → 42%)
      • dividendYield can be 0.0267 OR 2.67 depending on version/region
      • heldPercentInsiders/Institutions are decimals (0.72 → 72%)
      • payoutRatio is decimal (0.47 → 47%)

    If *already_pct* is True the value is returned as-is (just rounded).
    Otherwise: values with abs ≤ 1.0 are treated as fractional → × 100.
    """
    if val is None:
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        if already_pct:
            return round(f, 2)
        # Fractional → percentage  (0.42 → 42%)
        if abs(f) <= 1.0:
            return round(f * 100, 2)
        return round(f, 2)
    except (TypeError, ValueError):
        return None


def _safe_float(val) -> Optional[float]:
    """Safe float conversion — returns None for NaN / Inf."""
    if val is None:
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, 2)
    except (TypeError, ValueError):
        return None


def _format_market_cap(val: float) -> str:
    """Format market cap in Indian number system."""
    if val <= 0:
        return "N/A"
    if val >= 1e12:
        return f"₹{val/1e7:.0f} Cr (Large Cap)"
    elif val >= 1e10:
        return f"₹{val/1e7:.0f} Cr (Mid Cap)"
    elif val >= 1e8:
        return f"₹{val/1e7:.1f} Cr (Small Cap)"
    else:
        return f"₹{val/1e7:.2f} Cr (Micro Cap)"


def _throttle():
    """Enforce a minimum gap between Yahoo Finance API calls."""
    global _last_call_time
    elapsed = time.time() - _last_call_time
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed + random.uniform(0.1, 0.4))
    _last_call_time = time.time()


def _fetch_info_with_retry(ticker: str, max_retries: int = 4) -> dict:
    """
    Fetch yfinance .info with exponential backoff on rate-limit errors.
    Tries the NSE ticker first, falls back to BSE (.BO) on failure.
    """
    tickers_to_try = [ticker]
    if ticker.endswith(".NS"):
        tickers_to_try.append(ticker.replace(".NS", ".BO"))

    for sym in tickers_to_try:
        for attempt in range(max_retries):
            try:
                _throttle()
                yf_t = yf.Ticker(sym)
                info  = yf_t.info or {}

                # yfinance returns a 1-key dict {'trailingPegRatio': None} on blocked requests
                # A valid response has many keys (typically 50+)
                if len(info) < 5:
                    raise ValueError("Empty or blocked response")

                # Check at least one price field exists
                price = info.get("currentPrice") or info.get("regularMarketPrice")
                if price is None and len(info) < 10:
                    raise ValueError("No price data in response")

                return info

            except Exception as exc:
                exc_name = type(exc).__name__
                is_rate_limit = (
                    "RateLimit" in exc_name
                    or "429"     in str(exc)
                    or "Too Many" in str(exc)
                )
                if is_rate_limit:
                    wait = (2 ** attempt) * 3 + random.uniform(1, 3)   # 3s, 7s, 15s, 33s
                    time.sleep(wait)
                elif attempt < max_retries - 1:
                    time.sleep(1.5)
                else:
                    break   # try .BO ticker next

    return {}   # all attempts exhausted


def _fetch_nse_delivery(symbol: str, nse_sess=None) -> dict:
    """Fetch current-day delivery data from NSE trade_info API.

    Returns dict with keys: traded_quantity, delivery_quantity,
    delivery_pct, delivery_date.  Empty dict on failure.
    """
    # Strip .NS / .BO suffix for NSE API
    nse_sym = symbol.replace(".NS", "").replace(".BO", "")

    try:
        sess = nse_sess or _create_nse_session()

        url = (
            f"https://www.nseindia.com/api/quote-equity"
            f"?symbol={nse_sym}&section=trade_info"
        )
        resp = sess.get(url, timeout=10)
        if resp.status_code != 200:
            return {}

        data = resp.json()
        dp = data.get("securityWiseDP") or {}
        if not dp:
            return {}

        traded = dp.get("quantityTraded")
        delivered = dp.get("deliveryQuantity")
        pct = dp.get("deliveryToTradedQuantity")
        dt_str = dp.get("secWiseDelPosDate", "")

        if traded is None and delivered is None:
            return {}

        result = {}
        if traded is not None:
            result["traded_quantity"] = int(str(traded).replace(",", ""))
        if delivered is not None:
            result["delivery_quantity"] = int(str(delivered).replace(",", ""))
        if pct is not None:
            result["delivery_pct"] = round(float(pct), 2)
        if dt_str:
            result["delivery_date"] = dt_str.strip()
        return result

    except Exception:
        return {}


def _build_delivery_analysis(fd) -> str:
    """Build textual analysis of delivery data."""
    if fd.delivery_pct is None:
        return ""

    pct = fd.delivery_pct
    parts = []

    # Header statement
    traded_str = f"{fd.traded_quantity:,}" if fd.traded_quantity else "N/A"
    deliv_str = f"{fd.delivery_quantity:,}" if fd.delivery_quantity else "N/A"
    parts.append(
        f"On {fd.delivery_date or 'the latest trading day'}, "
        f"{deliv_str} shares were delivered out of {traded_str} shares traded, "
        f"giving a delivery percentage of {pct:.2f}%."
    )

    # Interpretation
    if pct >= 70:
        parts.append(
            "This is an EXCEPTIONALLY HIGH delivery percentage. "
            "It indicates very strong conviction buying — institutions "
            "and serious investors are taking delivery rather than "
            "squaring off positions. This is a strongly bullish signal."
        )
    elif pct >= 50:
        parts.append(
            "This is a HIGH delivery percentage. "
            "More than half the traded volume resulted in actual delivery, "
            "suggesting genuine buying interest and likely institutional "
            "accumulation. This is considered a positive signal."
        )
    elif pct >= 35:
        parts.append(
            "This is a MODERATE delivery percentage, which is around the "
            "market average. It shows a balanced mix of delivery-based "
            "investing and intraday trading activity."
        )
    elif pct >= 20:
        parts.append(
            "This is a LOW delivery percentage. "
            "Most of the traded volume was intraday speculation rather "
            "than genuine buying for holding. This may indicate "
            "speculative or trader-driven price movement."
        )
    else:
        parts.append(
            "This is a VERY LOW delivery percentage. "
            "The stock is heavily dominated by intraday traders with "
            "minimal genuine delivery-based interest. Price moves on "
            "such days are less reliable as indicators of real demand."
        )

    # Volume context
    if fd.avg_volume and fd.traded_quantity:
        ratio = fd.traded_quantity / fd.avg_volume if fd.avg_volume > 0 else 0
        if ratio > 2.0:
            parts.append(
                f"Today's traded volume ({traded_str}) is {ratio:.1f}x "
                f"the average volume — unusually high activity."
            )
        elif ratio > 1.3:
            parts.append(
                f"Traded volume is {ratio:.1f}x the average — "
                f"moderately above normal."
            )
        elif ratio < 0.5:
            parts.append(
                f"Traded volume is only {ratio:.1f}x the average — "
                f"unusually low activity."
            )

    return " ".join(parts)


def _create_nse_session() -> _requests.Session:
    """Create a requests session with NSE-friendly headers and cookies."""
    sess = _requests.Session()
    sess.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    })
    sess.get("https://www.nseindia.com", timeout=10)
    return sess


# ── Historical delivery from NSE bhavcopy CSV ────────────────────
def _fetch_nse_delivery_history(symbol: str, nse_sess=None,
                                days: int = 30) -> List[DeliveryDay]:
    """Fetch ~*days* trading-days of historical delivery data from NSE bhavcopy CSVs.

    Source: https://archives.nseindia.com/products/content/sec_bhavdata_full_{DDMMYYYY}.csv
    One CSV per day, ~350 KB each, contains ALL stocks.

    Returns list of DeliveryDay sorted oldest → newest, empty list on failure.
    """
    nse_sym = symbol.replace(".NS", "").replace(".BO", "")
    # Use a dedicated session – the shared NSE session sets Accept: application/json
    # which can cause issues with CSV downloads from archives.nseindia.com
    sess = _requests.Session()
    sess.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.nseindia.com/",
        "Accept-Language": "en-US,en;q=0.9",
    })
    # Pre-warm with NSE main page to get cookies
    try:
        sess.get("https://www.nseindia.com", timeout=10)
    except Exception:
        pass

    results: List[DeliveryDay] = []
    seen_dates: set = set()   # deduplicate (holiday CSVs can repeat prior day's data)
    d = _dt.date.today()
    attempts = 0
    max_attempts = days * 2  # account for weekends & holidays

    while len(results) < days and attempts < max_attempts:
        attempts += 1
        # Skip weekends
        if d.weekday() >= 5:
            d -= _dt.timedelta(days=1)
            continue

        ddmmyyyy = d.strftime("%d%m%Y")
        url = (
            f"https://archives.nseindia.com/products/content/"
            f"sec_bhavdata_full_{ddmmyyyy}.csv"
        )
        try:
            resp = sess.get(url, timeout=15)
            if resp.status_code != 200:
                d -= _dt.timedelta(days=1)
                continue

            import csv, io
            reader = csv.DictReader(io.StringIO(resp.text))
            for row in reader:
                sym_val = (row.get("SYMBOL") or "").strip()
                series  = (row.get(" SERIES") or row.get("SERIES") or "").strip()
                if sym_val == nse_sym and series == "EQ":
                    close_str = (row.get(" CLOSE_PRICE") or row.get("CLOSE_PRICE") or "0").strip()
                    vol_str   = (row.get(" TTL_TRD_QNTY") or row.get("TTL_TRD_QNTY") or "0").strip()
                    dq_str    = (row.get(" DELIV_QTY") or row.get("DELIV_QTY") or "0").strip()
                    dp_str    = (row.get(" DELIV_PER") or row.get("DELIV_PER") or "0").strip()
                    dt_str    = (row.get(" DATE1") or row.get("DATE1") or "").strip()

                    date_key = dt_str or d.strftime("%d-%b-%Y")
                    if date_key not in seen_dates:
                        seen_dates.add(date_key)
                        results.append(DeliveryDay(
                            date=date_key,
                            close_price=float(close_str) if close_str else 0.0,
                            volume=int(vol_str) if vol_str else 0,
                            delivery_qty=int(dq_str) if dq_str else 0,
                            delivery_pct=float(dp_str) if dp_str else 0.0,
                        ))
                    break  # found the stock row for this date
        except Exception:
            pass

        d -= _dt.timedelta(days=1)
        time.sleep(0.15)  # polite delay between requests

    # oldest first
    results.reverse()
    return results


def _build_delivery_history_analysis(fd) -> str:
    """Build textual analysis of historical delivery % trends."""
    hist = fd.delivery_history
    if not hist or len(hist) < 3:
        return ""

    pcts = [h.delivery_pct for h in hist if h.delivery_pct > 0]
    prices = [h.close_price for h in hist if h.close_price > 0]

    if not pcts:
        return ""

    avg_pct = sum(pcts) / len(pcts)
    max_pct = max(pcts)
    min_pct = min(pcts)
    latest_pct = pcts[-1] if pcts else 0
    n = len(hist)

    parts = []

    # ── Summary
    parts.append(
        f"Over the last {n} trading days, delivery percentage ranged from "
        f"{min_pct:.1f}% to {max_pct:.1f}% with an average of {avg_pct:.1f}%."
    )

    # ── Trend (compare first half vs second half)
    mid = len(pcts) // 2
    first_half_avg = sum(pcts[:mid]) / mid if mid > 0 else avg_pct
    second_half_avg = sum(pcts[mid:]) / (len(pcts) - mid) if (len(pcts) - mid) > 0 else avg_pct
    trend_diff = second_half_avg - first_half_avg

    if trend_diff > 5:
        parts.append(
            f"Delivery % shows a RISING trend — recent average ({second_half_avg:.1f}%) "
            f"is significantly higher than earlier ({first_half_avg:.1f}%). "
            "This suggests increasing conviction and accumulation by serious investors."
        )
    elif trend_diff > 2:
        parts.append(
            f"Delivery % is gradually INCREASING — recent average ({second_half_avg:.1f}%) "
            f"vs earlier ({first_half_avg:.1f}%). Mild build-up of delivery-based interest."
        )
    elif trend_diff < -5:
        parts.append(
            f"Delivery % shows a DECLINING trend — recent average ({second_half_avg:.1f}%) "
            f"is lower than earlier ({first_half_avg:.1f}%). "
            "Traders are increasingly squaring off positions intraday."
        )
    elif trend_diff < -2:
        parts.append(
            f"Delivery % is gradually DECREASING — recent ({second_half_avg:.1f}%) "
            f"vs earlier ({first_half_avg:.1f}%). Slight shift towards speculative activity."
        )
    else:
        parts.append(
            f"Delivery % has been STABLE — recent ({second_half_avg:.1f}%) "
            f"is similar to earlier ({first_half_avg:.1f}%). "
            "No significant shift in delivery patterns."
        )

    # ── Average level interpretation
    if avg_pct >= 55:
        parts.append(
            f"The average delivery percentage of {avg_pct:.1f}% is HIGH, indicating "
            "strong institutional participation and genuine investment interest."
        )
    elif avg_pct >= 35:
        parts.append(
            f"The average delivery percentage of {avg_pct:.1f}% is MODERATE, "
            "indicating a healthy mix of delivery-based and intraday trading."
        )
    else:
        parts.append(
            f"The average delivery percentage of {avg_pct:.1f}% is LOW, "
            "suggesting the stock is dominated by speculative/intraday activity."
        )

    # ── Spikes detection (days > avg + 1.5 std dev)
    if len(pcts) >= 5:
        import statistics
        std_pct = statistics.stdev(pcts)
        spike_threshold = avg_pct + 1.5 * std_pct
        spikes = [(h.date, h.delivery_pct) for h in hist
                  if h.delivery_pct >= spike_threshold and h.delivery_pct > 0]
        if spikes:
            spike_dates = ", ".join(f"{s[0]} ({s[1]:.1f}%)" for s in spikes[:3])
            parts.append(
                f"Notable delivery spikes detected on: {spike_dates}. "
                "Spikes often indicate block/bulk deals or institutional accumulation."
            )

    # ── Price-Delivery correlation
    if len(prices) >= 5 and len(pcts) >= 5:
        min_len = min(len(prices), len(pcts))
        p_slice = prices[-min_len:]
        d_slice = pcts[-min_len:]
        # Simple correlation: compare direction of change
        p_up = sum(1 for i in range(1, min_len) if p_slice[i] > p_slice[i-1])
        d_up = sum(1 for i in range(1, min_len) if d_slice[i] > d_slice[i-1])
        both_up = sum(1 for i in range(1, min_len)
                      if p_slice[i] > p_slice[i-1] and d_slice[i] > d_slice[i-1])
        total_moves = min_len - 1

        if total_moves > 0:
            co_pct = both_up / total_moves * 100
            price_start = p_slice[0]
            price_end = p_slice[-1]
            price_chg = ((price_end - price_start) / price_start * 100) if price_start else 0

            if price_chg > 3 and second_half_avg > first_half_avg + 2:
                parts.append(
                    f"BULLISH SIGNAL: Price rose {price_chg:.1f}% while delivery % increased — "
                    "this combination suggests genuine accumulation and institutional buying."
                )
            elif price_chg < -3 and second_half_avg > first_half_avg + 2:
                parts.append(
                    f"CAUTION: Price fell {abs(price_chg):.1f}% while delivery % increased — "
                    "high delivery on falling prices may indicate informed selling or "
                    "value investors stepping in at lower levels."
                )
            elif price_chg > 3 and second_half_avg < first_half_avg - 2:
                parts.append(
                    f"WARNING: Price rose {price_chg:.1f}% but delivery % declined — "
                    "rising prices with falling delivery suggests speculative rally "
                    "lacking institutional conviction."
                )
            elif price_chg < -3 and second_half_avg < first_half_avg - 2:
                parts.append(
                    f"BEARISH SIGNAL: Price fell {abs(price_chg):.1f}% with declining delivery % — "
                    "suggests waning interest and lack of value buying at lower levels."
                )

    return " ".join(parts)


# ── Financial Statement Fetcher & Analyser ────────────────────────

def _fetch_annual_financials(yf_ticker) -> List[AnnualFinancial]:
    """Extract annual financial statements (Income, Balance Sheet, Cash Flow)
    from a yfinance Ticker object.  Returns up to 4 years, newest-first."""

    results: List[AnnualFinancial] = []

    try:
        _throttle()
        inc = yf_ticker.financials          # annual income statement
        bs  = yf_ticker.balance_sheet       # annual balance sheet
        cf  = yf_ticker.cashflow            # annual cash flow
    except Exception:
        return results

    if inc is None or inc.empty:
        return results

    def _val(df, *names):
        """Get a value from a DataFrame column by row-name lookup."""
        if df is None or df.empty:
            return None
        col = df.columns[0] if hasattr(df, 'columns') else None
        if col is None:
            return None
        for nm in names:
            for idx in df.index:
                if nm.lower() == str(idx).strip().lower():
                    v = df.loc[idx, col]
                    if pd.notna(v):
                        return float(v)
            for idx in df.index:
                if nm.lower() in str(idx).strip().lower():
                    v = df.loc[idx, col]
                    if pd.notna(v):
                        return float(v)
        return None

    # Process up to 4 columns (years)
    n_years = min(4, len(inc.columns))
    for i in range(n_years):
        col_date = inc.columns[i]
        dt = pd.to_datetime(col_date)
        fy_label = f"FY{dt.year + 1}" if dt.month >= 4 else f"FY{dt.year}"
        year_label = f"{fy_label} ({dt.strftime('%b %Y')})"

        # Slice each DF to this column only
        inc_y = inc[[col_date]] if col_date in inc.columns else None
        bs_y  = bs[[col_date]]  if bs is not None and not bs.empty and col_date in bs.columns else None
        cf_y  = cf[[col_date]]  if cf is not None and not cf.empty and col_date in cf.columns else None

        af = AnnualFinancial(year=year_label)

        # ── Income Statement
        af.total_revenue     = _val(inc_y, "Total Revenue", "Operating Revenue")
        af.cost_of_revenue   = _val(inc_y, "Cost Of Revenue", "Reconciled Cost Of Revenue")
        af.gross_profit      = _val(inc_y, "Gross Profit")
        af.operating_expense = _val(inc_y, "Operating Expense", "Total Expenses")
        af.operating_income  = _val(inc_y, "Operating Income")
        af.ebitda            = _val(inc_y, "EBITDA", "Normalized EBITDA")
        af.ebit              = _val(inc_y, "EBIT")
        af.interest_expense  = _val(inc_y, "Interest Expense")
        af.pretax_income     = _val(inc_y, "Pretax Income")
        af.tax_provision     = _val(inc_y, "Tax Provision")
        af.net_income        = _val(inc_y, "Net Income Common Stockholders",
                                    "Net Income", "Net Income Continuous Operations")
        af.diluted_eps       = _val(inc_y, "Diluted EPS", "Basic EPS")

        # ── Balance Sheet
        af.total_assets         = _val(bs_y, "Total Assets")
        af.total_current_assets = _val(bs_y, "Current Assets")
        af.cash_and_equivalents = _val(bs_y, "Cash And Cash Equivalents",
                                       "Cash Cash Equivalents And Short Term Investments")
        af.inventory            = _val(bs_y, "Inventory")
        af.accounts_receivable  = _val(bs_y, "Accounts Receivable", "Other Receivables")
        af.net_ppe              = _val(bs_y, "Net PPE")
        af.goodwill             = _val(bs_y, "Goodwill")
        af.total_liabilities    = _val(bs_y, "Total Liabilities Net Minority Interest",
                                       "Total Non Current Liabilities Net Minority Interest")
        af.total_current_liab   = _val(bs_y, "Current Liabilities")
        af.long_term_debt       = _val(bs_y, "Long Term Debt")
        af.total_debt           = _val(bs_y, "Total Debt")
        af.stockholders_equity  = _val(bs_y, "Stockholders Equity", "Common Stock Equity")
        af.retained_earnings    = _val(bs_y, "Retained Earnings")
        if af.total_current_assets and af.total_current_liab:
            af.working_capital = af.total_current_assets - af.total_current_liab

        # ── Cash Flow
        af.operating_cashflow = _val(cf_y, "Operating Cash Flow")
        af.capex              = _val(cf_y, "Capital Expenditure")
        af.free_cashflow      = _val(cf_y, "Free Cash Flow")
        af.investing_cashflow = _val(cf_y, "Investing Cash Flow")
        af.financing_cashflow = _val(cf_y, "Financing Cash Flow")
        af.dividends_paid     = _val(cf_y, "Cash Dividends Paid", "Common Stock Dividend Paid")
        af.debt_repayment     = _val(cf_y, "Long Term Debt Payments", "Repayment Of Debt")
        af.debt_issuance      = _val(cf_y, "Long Term Debt Issuance", "Issuance Of Debt")
        af.depreciation       = _val(cf_y, "Depreciation And Amortization", "Depreciation")

        # If free cashflow not directly available, compute it
        if af.free_cashflow is None and af.operating_cashflow is not None and af.capex is not None:
            af.free_cashflow = af.operating_cashflow + af.capex  # capex is negative

        # ── Computed Ratios
        if af.total_revenue and af.total_revenue > 0:
            if af.gross_profit is not None:
                af.gross_margin = round(af.gross_profit / af.total_revenue * 100, 2)
            if af.operating_income is not None:
                af.operating_margin = round(af.operating_income / af.total_revenue * 100, 2)
            if af.net_income is not None:
                af.net_margin = round(af.net_income / af.total_revenue * 100, 2)
            if af.free_cashflow is not None:
                af.fcf_margin = round(af.free_cashflow / af.total_revenue * 100, 2)
        if af.stockholders_equity and af.stockholders_equity > 0 and af.net_income is not None:
            af.roe = round(af.net_income / af.stockholders_equity * 100, 2)
        if af.total_assets and af.total_assets > 0 and af.net_income is not None:
            af.roa = round(af.net_income / af.total_assets * 100, 2)
        if af.stockholders_equity and af.stockholders_equity > 0 and af.total_debt is not None:
            af.debt_to_equity = round(af.total_debt / af.stockholders_equity, 3)
        if af.total_current_liab and af.total_current_liab > 0 and af.total_current_assets is not None:
            af.current_ratio = round(af.total_current_assets / af.total_current_liab, 2)
        if af.ebit and af.interest_expense and abs(af.interest_expense) > 0:
            af.interest_coverage = round(abs(af.ebit) / abs(af.interest_expense), 2)

        results.append(af)

    return results


def _build_financial_statements_analysis(fd) -> str:
    """Build a comprehensive HTML analysis of annual financial statements."""
    fins = fd.annual_financials
    if not fins or len(fins) < 1:
        return ""

    latest = fins[0]   # newest year
    n = len(fins)

    def _cr(v):
        """Format in Crores."""
        if v is None:
            return "N/A"
        cr = v / 1e7
        if abs(cr) >= 1_00_000:
            return f"\u20b9{cr/1_00_000:.2f}L Cr"
        if abs(cr) >= 1_000:
            return f"\u20b9{cr/1_000:.1f}K Cr"
        return f"\u20b9{cr:.1f} Cr"

    def _pct(v):
        if v is None:
            return "N/A"
        return f"{v:.1f}%"

    def _yoy(curr, prev):
        if curr is None or prev is None or prev == 0:
            return None
        return round((curr - prev) / abs(prev) * 100, 1)

    def _badge(text, color):
        return (f'<span style="display:inline-block;padding:1px 7px;border-radius:4px;'
                f'font-size:.72rem;font-weight:600;background:{color}20;color:{color};'
                f'margin-left:4px;">{text}</span>')

    def _good(text):
        return _badge(text, '#3fb950')

    def _warn(text):
        return _badge(text, '#d29922')

    def _bad(text):
        return _badge(text, '#f85149')

    def _neutral(text):
        return _badge(text, '#8b949e')

    sections = []  # list of (title_html, bullet_list)

    # ═══ SECTION 1: Revenue & Profit Overview ═══
    rev_bullets = []
    if latest.total_revenue:
        rev_bullets.append(
            f'The company earned <strong>{_cr(latest.total_revenue)}</strong> in total revenue '
            f'during <strong>{latest.year}</strong>. '
            f'<span style="color:#8b949e;">Think of this as the total sales or money coming in '
            f'before any expenses are deducted.</span>'
        )
        if n >= 2 and fins[1].total_revenue:
            rev_g = _yoy(latest.total_revenue, fins[1].total_revenue)
            if rev_g is not None:
                if rev_g > 0:
                    rev_bullets.append(
                        f'Revenue <strong>grew {abs(rev_g):.1f}%</strong> compared to last year {_good("Growing")}. '
                        f'<span style="color:#8b949e;">This means the company is selling more products/services '
                        f'than before — a positive sign.</span>'
                    )
                else:
                    rev_bullets.append(
                        f'Revenue <strong>declined {abs(rev_g):.1f}%</strong> compared to last year {_bad("Declining")}. '
                        f'<span style="color:#8b949e;">This means the company\'s sales have fallen — could be due '
                        f'to market slowdown, competition, or loss of business.</span>'
                    )
        if n >= 4 and fins[3].total_revenue and fins[3].total_revenue > 0:
            cagr_rev = ((latest.total_revenue / fins[3].total_revenue) ** (1/3) - 1) * 100
            badge = _good(f'{cagr_rev:.1f}%') if cagr_rev > 10 else _warn(f'{cagr_rev:.1f}%') if cagr_rev > 0 else _bad(f'{cagr_rev:.1f}%')
            rev_bullets.append(
                f'3-year revenue CAGR: <strong>{cagr_rev:.1f}%</strong> {badge}. '
                f'<span style="color:#8b949e;">CAGR = Compound Annual Growth Rate. It shows the average '
                f'yearly growth over 3 years, smoothing out yearly ups and downs.</span>'
            )

    if latest.net_income is not None:
        ni_color = '#3fb950' if latest.net_income > 0 else '#f85149'
        rev_bullets.append(
            f'Net income (bottom-line profit): <strong style="color:{ni_color}">{_cr(latest.net_income)}</strong>. '
            f'<span style="color:#8b949e;">This is what\'s left after ALL expenses (costs, taxes, interest) '
            f'are paid — the actual profit shareholders own.</span>'
        )
        if n >= 2 and fins[1].net_income is not None:
            ni_g = _yoy(latest.net_income, fins[1].net_income)
            if ni_g is not None:
                if ni_g > 0:
                    rev_bullets.append(f'Net income <strong>grew {abs(ni_g):.1f}%</strong> YoY {_good("↑ Profit Up")}')
                else:
                    rev_bullets.append(f'Net income <strong>declined {abs(ni_g):.1f}%</strong> YoY {_bad("↓ Profit Down")}')

    if latest.ebitda is not None:
        rev_bullets.append(
            f'EBITDA: <strong>{_cr(latest.ebitda)}</strong>. '
            f'<span style="color:#8b949e;">EBITDA = Earnings Before Interest, Taxes, Depreciation & Amortization. '
            f'It shows the core operating profitability without accounting tricks.</span>'
        )

    if rev_bullets:
        sections.append(('📊 Revenue & Profit Overview', rev_bullets))

    # ═══ SECTION 2: Margin Analysis ═══
    margin_bullets = []
    if latest.gross_margin is not None:
        gm = latest.gross_margin
        gm_badge = _good('Healthy') if gm >= 40 else _warn('Moderate') if gm >= 20 else _bad('Thin')
        margin_bullets.append(
            f'<strong>Gross Margin: {_pct(gm)}</strong> {gm_badge}. '
            f'<span style="color:#8b949e;">For every ₹100 of revenue, the company keeps ₹{gm:.0f} '
            f'after paying for raw materials/direct costs. Higher is better.</span>'
        )
    if latest.operating_margin is not None:
        om = latest.operating_margin
        om_badge = _good('Strong') if om >= 20 else _warn('Fair') if om >= 10 else _bad('Weak') if om >= 0 else _bad('Loss-Making')
        margin_bullets.append(
            f'<strong>Operating Margin: {_pct(om)}</strong> {om_badge}. '
            f'<span style="color:#8b949e;">After paying salaries, rent, and other operating costs, '
            f'₹{max(0,om):.0f} out of every ₹100 revenue remains as operating profit.</span>'
        )
    if latest.net_margin is not None:
        nm = latest.net_margin
        nm_badge = _good('Excellent') if nm >= 15 else _good('Good') if nm >= 10 else _warn('Average') if nm >= 5 else _bad('Low')
        margin_bullets.append(
            f'<strong>Net Margin: {_pct(nm)}</strong> {nm_badge}. '
            f'<span style="color:#8b949e;">The final profit after everything — taxes, interest, all expenses. '
            f'This is the true profitability measure.</span>'
        )

    # Margin trend
    if n >= 2:
        for attr, label in [("gross_margin", "Gross"), ("operating_margin", "Operating"), ("net_margin", "Net")]:
            curr_m = getattr(latest, attr)
            prev_m = getattr(fins[1], attr)
            if curr_m is not None and prev_m is not None:
                diff = curr_m - prev_m
                if abs(diff) >= 1.0:
                    arrow = '↑' if diff > 0 else '↓'
                    color = '#3fb950' if diff > 0 else '#f85149'
                    margin_bullets.append(
                        f'{label} margin changed <strong style="color:{color}">{arrow} {abs(diff):.1f} '
                        f'percentage points</strong> vs last year'
                    )

    if margin_bullets:
        sections.append(('💹 Margin Analysis — How Much Profit Per ₹100 Revenue?', margin_bullets))

    # ═══ SECTION 3: Return Ratios ═══
    ret_bullets = []
    if latest.roe is not None:
        roe = latest.roe
        roe_badge = _good('Excellent') if roe >= 20 else _good('Good') if roe >= 15 else _warn('Moderate') if roe >= 10 else _bad('Low')
        ret_bullets.append(
            f'<strong>Return on Equity (ROE): {_pct(roe)}</strong> {roe_badge}. '
            f'<span style="color:#8b949e;">ROE measures how well the company uses shareholders\' money '
            f'to generate profit. Above 15% is generally considered good. '
            f'Think of it as: "For every ₹100 of shareholder money, the company earns ₹{roe:.0f} profit."</span>'
        )
    if latest.roa is not None:
        roa = latest.roa
        roa_badge = _good('Efficient') if roa >= 10 else _warn('Fair') if roa >= 5 else _bad('Low')
        ret_bullets.append(
            f'<strong>Return on Assets (ROA): {_pct(roa)}</strong> {roa_badge}. '
            f'<span style="color:#8b949e;">ROA shows how efficiently the company uses ALL its assets '
            f'(buildings, machines, cash, etc.) to generate profit.</span>'
        )

    if ret_bullets:
        sections.append(('🎯 Return Ratios — How Efficiently Is Money Being Used?', ret_bullets))

    # ═══ SECTION 4: Balance Sheet Health ═══
    bs_bullets = []
    if latest.total_assets:
        bs_bullets.append(
            f'<strong>Total Assets: {_cr(latest.total_assets)}</strong>. '
            f'<span style="color:#8b949e;">Everything the company owns — cash, buildings, inventory, receivables, etc.</span>'
        )
    if latest.total_debt is not None and latest.stockholders_equity:
        bs_bullets.append(
            f'Total Debt: <strong>{_cr(latest.total_debt)}</strong> vs '
            f'Shareholders\' Equity: <strong>{_cr(latest.stockholders_equity)}</strong>. '
            f'<span style="color:#8b949e;">Debt = money borrowed from banks/lenders. '
            f'Equity = money that belongs to shareholders. Ideally equity should be larger than debt.</span>'
        )
    if latest.cash_and_equivalents:
        bs_bullets.append(
            f'Cash & Equivalents: <strong>{_cr(latest.cash_and_equivalents)}</strong>. '
            f'<span style="color:#8b949e;">Liquid cash available to the company — its financial cushion '
            f'for emergencies or opportunities.</span>'
        )

    if latest.debt_to_equity is not None:
        de = latest.debt_to_equity
        if de < 0.1:
            de_badge = _good('Debt-Free')
            de_explain = 'Virtually no debt! Excellent financial strength — the company runs mostly on its own money.'
        elif de < 0.5:
            de_badge = _good('Low Debt')
            de_explain = 'Conservative borrowing. Healthy balance sheet with manageable debt levels.'
        elif de < 1.0:
            de_badge = _warn('Moderate')
            de_explain = 'Debt is within acceptable limits but worth monitoring if it keeps rising.'
        else:
            de_badge = _bad('High Debt')
            de_explain = 'Company has borrowed more than its net worth. High leverage = higher risk if business slows down.'
        bs_bullets.append(
            f'<strong>Debt-to-Equity Ratio: {de:.2f}</strong> {de_badge}. '
            f'<span style="color:#8b949e;">{de_explain} '
            f'(D/E = Total Debt ÷ Equity. Below 0.5 is safe, above 1.0 is risky)</span>'
        )

    # Debt trend
    if n >= 2:
        d_curr = latest.total_debt
        d_prev = fins[1].total_debt
        if d_curr is not None and d_prev is not None and d_prev > 0:
            d_chg = _yoy(d_curr, d_prev)
            if d_chg is not None and abs(d_chg) >= 5:
                if d_chg > 0:
                    bs_bullets.append(
                        f'⚠️ Total debt <strong style="color:#f85149">increased {d_chg:.1f}%</strong> '
                        f'YoY ({_cr(d_prev)} → {_cr(d_curr)}) {_bad("Debt Rising")}'
                    )
                else:
                    bs_bullets.append(
                        f'✅ Total debt <strong style="color:#3fb950">reduced {abs(d_chg):.1f}%</strong> '
                        f'YoY ({_cr(d_prev)} → {_cr(d_curr)}) {_good("Deleveraging")}'
                    )

    if latest.current_ratio is not None:
        cr = latest.current_ratio
        cr_badge = _good('Strong') if cr >= 2 else _good('Healthy') if cr >= 1.5 else _warn('Adequate') if cr >= 1.0 else _bad('Risky')
        bs_bullets.append(
            f'<strong>Current Ratio: {cr:.2f}</strong> {cr_badge}. '
            f'<span style="color:#8b949e;">Measures if the company can pay its short-term bills. '
            f'Current Assets ÷ Current Liabilities. Above 1.5 is comfortable; below 1.0 means trouble.</span>'
        )

    if latest.working_capital is not None:
        wc = latest.working_capital
        wc_color = '#3fb950' if wc > 0 else '#f85149'
        wc_badge = _good('Positive') if wc > 0 else _bad('Negative')
        bs_bullets.append(
            f'Working Capital: <strong style="color:{wc_color}">{_cr(wc)}</strong> {wc_badge}. '
            f'<span style="color:#8b949e;">Current Assets minus Current Liabilities. '
            f'Positive = company has enough short-term resources. Negative = may struggle to pay bills.</span>'
        )

    if bs_bullets:
        sections.append(('🏦 Balance Sheet — What Does the Company Own vs Owe?', bs_bullets))

    # ═══ SECTION 5: Cash Flow Analysis ═══
    cf_bullets = []
    if latest.operating_cashflow is not None:
        ocf = latest.operating_cashflow
        ocf_color = '#3fb950' if ocf > 0 else '#f85149'
        cf_bullets.append(
            f'<strong style="color:{ocf_color}">Operating Cash Flow: {_cr(ocf)}</strong>. '
            f'<span style="color:#8b949e;">Actual cash generated from day-to-day business operations. '
            f'Unlike profit (which can include non-cash items), this is real money flowing in.</span>'
        )
        if latest.net_income and latest.net_income > 0 and ocf > 0:
            ocf_to_ni = ocf / latest.net_income
            if ocf_to_ni >= 1.2:
                cf_bullets.append(
                    f'Cash Flow vs Profit ratio: <strong>{ocf_to_ni:.2f}x</strong> {_good("Strong Cash Conversion")}. '
                    f'<span style="color:#8b949e;">OCF is well above reported profit — the company\'s earnings '
                    f'are backed by real cash. This is a sign of high-quality earnings.</span>'
                )
            elif ocf_to_ni >= 0.8:
                cf_bullets.append(
                    f'Cash Flow vs Profit ratio: <strong>{ocf_to_ni:.2f}x</strong> {_good("Healthy")}. '
                    f'<span style="color:#8b949e;">Cash flow is in line with reported profits — genuine earnings.</span>'
                )
            else:
                cf_bullets.append(
                    f'Cash Flow vs Profit ratio: <strong>{ocf_to_ni:.2f}x</strong> {_bad("Poor Conversion")}. '
                    f'<span style="color:#8b949e;">⚠️ Profits on paper are much higher than actual cash coming in. '
                    f'This raises questions about earnings quality — money may be stuck in receivables or inventory.</span>'
                )

    if latest.free_cashflow is not None:
        fcf = latest.free_cashflow
        fcf_color = '#3fb950' if fcf > 0 else '#f85149'
        fcf_badge = _good('Positive FCF') if fcf > 0 else _bad('Negative FCF')
        cf_bullets.append(
            f'<strong style="color:{fcf_color}">Free Cash Flow: {_cr(fcf)}</strong> {fcf_badge}. '
            f'<span style="color:#8b949e;">FCF = Operating Cash Flow minus Capital Expenditure. '
            f'This is the cash left over after maintaining/expanding the business — available for '
            f'dividends, buybacks, or debt repayment. Positive FCF is what investors love.</span>'
        )

    if latest.capex is not None:
        cf_bullets.append(
            f'Capital Expenditure (Capex): <strong>{_cr(abs(latest.capex))}</strong>. '
            f'<span style="color:#8b949e;">Money spent on buying/upgrading factories, equipment, '
            f'technology, etc. High capex can mean the company is investing for future growth.</span>'
        )

    if latest.fcf_margin is not None:
        fm = latest.fcf_margin
        if fm >= 15:
            fm_badge = _good('Excellent')
        elif fm >= 5:
            fm_badge = _good('Decent')
        elif fm >= 0:
            fm_badge = _warn('Thin')
        else:
            fm_badge = _bad('Negative')
        cf_bullets.append(
            f'<strong>FCF Margin: {_pct(fm)}</strong> {fm_badge}. '
            f'<span style="color:#8b949e;">What percentage of revenue converts into free cash. '
            f'FCF Margin above 10% is great; above 5% is decent.</span>'
        )

    # FCF trend
    if n >= 2:
        fcf_curr = latest.free_cashflow
        fcf_prev = fins[1].free_cashflow
        if fcf_curr is not None and fcf_prev is not None and fcf_prev != 0:
            fcf_g = _yoy(fcf_curr, fcf_prev)
            if fcf_g is not None and abs(fcf_g) >= 10:
                if fcf_g > 0:
                    cf_bullets.append(
                        f'Free cash flow <strong style="color:#3fb950">grew {fcf_g:.1f}%</strong> '
                        f'YoY {_good("↑ Improving")}'
                    )
                else:
                    cf_bullets.append(
                        f'Free cash flow <strong style="color:#f85149">declined {abs(fcf_g):.1f}%</strong> '
                        f'YoY {_bad("↓ Declining")}'
                    )

    if cf_bullets:
        sections.append(('💰 Cash Flow — Is Real Cash Being Generated?', cf_bullets))

    # ═══ SECTION 6: Debt Servicing ═══
    debt_bullets = []
    if latest.interest_coverage is not None:
        ic = latest.interest_coverage
        if ic >= 10:
            ic_badge = _good('Very Safe')
            ic_explain = 'Company earns 10x+ what it needs to pay interest — zero debt stress.'
        elif ic >= 3:
            ic_badge = _good('Comfortable')
            ic_explain = 'Can comfortably service its debt without strain.'
        elif ic >= 1.5:
            ic_badge = _warn('Tight')
            ic_explain = 'Barely enough to cover interest payments — any revenue drop could cause trouble.'
        else:
            ic_badge = _bad('RED FLAG')
            ic_explain = 'Struggling to cover even interest payments — serious financial distress risk.'
        debt_bullets.append(
            f'<strong>Interest Coverage: {ic:.1f}x</strong> {ic_badge}. '
            f'<span style="color:#8b949e;">{ic_explain} '
            f'(Interest Coverage = Operating Profit ÷ Interest Expense. Above 3x is safe.)</span>'
        )

    if latest.dividends_paid is not None and latest.dividends_paid != 0:
        debt_bullets.append(
            f'Dividends Paid: <strong>{_cr(abs(latest.dividends_paid))}</strong>. '
            f'<span style="color:#8b949e;">Cash returned to shareholders as dividends.</span>'
        )
    if latest.debt_repayment and latest.debt_repayment != 0:
        debt_bullets.append(
            f'Debt Repaid: <strong>{_cr(abs(latest.debt_repayment))}</strong> {_good("Paying Down Debt")}'
        )
    if latest.debt_issuance and latest.debt_issuance > 0:
        debt_bullets.append(
            f'New Debt Raised: <strong>{_cr(latest.debt_issuance)}</strong> {_warn("Borrowing More")}'
        )

    if debt_bullets:
        sections.append(('🔒 Debt Servicing & Capital Allocation', debt_bullets))

    # ═══ SECTION 7: EPS Trend ═══
    eps_bullets = []
    if n >= 2:
        eps_vals = [(f.year, f.diluted_eps) for f in fins if f.diluted_eps is not None]
        if len(eps_vals) >= 2:
            eps_latest = eps_vals[0][1]
            eps_oldest = eps_vals[-1][1]
            eps_color = '#3fb950' if eps_latest > 0 else '#f85149'
            eps_bullets.append(
                f'Latest Diluted EPS: <strong style="color:{eps_color}">\u20b9{eps_latest:.2f}</strong>. '
                f'<span style="color:#8b949e;">EPS = Earnings Per Share. If the company\'s total profit '
                f'is divided equally among all shares, each share earned ₹{eps_latest:.2f}. '
                f'Higher EPS = more profitable per share.</span>'
            )
            if eps_oldest and eps_oldest > 0:
                eps_cagr = ((eps_latest / eps_oldest) ** (1 / max(1, len(eps_vals) - 1)) - 1) * 100
                cagr_badge = _good(f'{eps_cagr:.1f}%') if eps_cagr > 10 else _warn(f'{eps_cagr:.1f}%') if eps_cagr > 0 else _bad(f'{eps_cagr:.1f}%')
                eps_bullets.append(
                    f'{len(eps_vals)-1}-year EPS CAGR: <strong>{eps_cagr:.1f}%</strong> {cagr_badge}. '
                    f'<span style="color:#8b949e;">Shows how fast per-share earnings have grown over the years. '
                    f'Consistent double-digit EPS growth is a hallmark of quality companies.</span>'
                )

    if eps_bullets:
        sections.append(('📈 Earnings Per Share (EPS) Trend', eps_bullets))

    # ═══ SECTION 8: Overall Verdict ═══
    verdict_bullets = []
    strengths = []
    if latest.net_margin is not None and latest.net_margin > 15:
        strengths.append('High profitability (Net Margin > 15%)')
    if latest.roe is not None and latest.roe > 15:
        strengths.append('Strong returns on equity (ROE > 15%)')
    if latest.debt_to_equity is not None and latest.debt_to_equity < 0.5:
        strengths.append('Low leverage / debt-free')
    if latest.free_cashflow is not None and latest.free_cashflow > 0:
        strengths.append('Positive free cash flow')
    if latest.current_ratio is not None and latest.current_ratio >= 1.5:
        strengths.append('Healthy liquidity (Current Ratio ≥ 1.5)')
    if latest.operating_cashflow and latest.net_income and latest.net_income > 0:
        if latest.operating_cashflow / latest.net_income >= 1.0:
            strengths.append('Strong cash conversion')
    if n >= 2 and latest.total_revenue and fins[1].total_revenue:
        rev_g = _yoy(latest.total_revenue, fins[1].total_revenue)
        if rev_g and rev_g > 10:
            strengths.append(f'Strong revenue growth ({rev_g:.0f}% YoY)')

    concerns = []
    if latest.net_margin is not None and latest.net_margin < 5:
        concerns.append('Thin profit margins (< 5%)')
    if latest.debt_to_equity is not None and latest.debt_to_equity > 1.0:
        concerns.append('High leverage (D/E > 1.0)')
    if latest.free_cashflow is not None and latest.free_cashflow < 0:
        concerns.append('Negative free cash flow')
    if latest.interest_coverage is not None and latest.interest_coverage < 2:
        concerns.append('Low interest coverage (< 2x)')
    if latest.current_ratio is not None and latest.current_ratio < 1.0:
        concerns.append('Weak liquidity (Current Ratio < 1.0)')
    if latest.roe is not None and latest.roe < 8:
        concerns.append('Low return on equity (ROE < 8%)')

    if strengths:
        strength_items = ''.join(f'<li style="color:#3fb950;">{s}</li>' for s in strengths)
        verdict_bullets.append(f'<strong style="color:#3fb950;">✅ Key Strengths:</strong><ul style="margin:2px 0 6px 0;padding-left:18px;">{strength_items}</ul>')
    if concerns:
        concern_items = ''.join(f'<li style="color:#f85149;">{c}</li>' for c in concerns)
        verdict_bullets.append(f'<strong style="color:#f85149;">⚠️ Key Concerns:</strong><ul style="margin:2px 0 6px 0;padding-left:18px;">{concern_items}</ul>')

    if not strengths and not concerns:
        verdict_bullets.append('Insufficient data to form a clear verdict.')

    if verdict_bullets:
        sections.append(('🏆 Overall Financial Verdict', verdict_bullets))

    # ── Build final HTML
    html_parts = []
    for title, bullets in sections:
        html_parts.append(
            f'<div style="margin-bottom:14px;">'
            f'<div style="font-weight:700;font-size:.88rem;margin-bottom:6px;'
            f'padding:4px 10px;border-radius:6px;'
            f'background:rgba(88,166,255,0.08);border-left:3px solid #58a6ff;">'
            f'{title}</div>'
            f'<ul style="list-style:none;padding-left:6px;margin:0;">'
        )
        for b in bullets:
            html_parts.append(
                f'<li style="padding:3px 0 3px 14px;position:relative;line-height:1.65;">'
                f'<span style="position:absolute;left:0;color:#58a6ff;">▸</span>{b}</li>'
            )
        html_parts.append('</ul></div>')

    return '\n'.join(html_parts)


def _fetch_nse_bulk_block_deals(symbol: str, nse_sess=None) -> List[BulkBlockDeal]:
    """Fetch today's bulk & block deals for *symbol* from NSE snapshot API.

    Returns list of BulkBlockDeal for this symbol (may be empty).
    """
    nse_sym = symbol.replace(".NS", "").replace(".BO", "")

    try:
        sess = nse_sess or _create_nse_session()
        url = "https://www.nseindia.com/api/snapshot-capital-market-largedeal"
        resp = sess.get(url, timeout=10)
        if resp.status_code != 200:
            return []

        data = resp.json()
        deals: List[BulkBlockDeal] = []

        for dtype, label in [("BULK_DEALS_DATA", "BULK"),
                             ("BLOCK_DEALS_DATA", "BLOCK")]:
            for item in (data.get(dtype) or []):
                if (item.get("symbol") or "").upper() != nse_sym.upper():
                    continue
                qty_raw = item.get("qty", "0")
                price_raw = item.get("watp", "0")
                deals.append(BulkBlockDeal(
                    date=item.get("date", ""),
                    deal_type=label,
                    client_name=item.get("clientName", "") or "",
                    buy_sell=(item.get("buySell") or "").upper(),
                    quantity=int(str(qty_raw).replace(",", "")) if qty_raw else 0,
                    price=round(float(str(price_raw).replace(",", "")), 2) if price_raw else 0.0,
                    remarks=item.get("remarks", "") or "",
                ))

        return deals
    except Exception:
        return []


def _fetch_nse_insider_trades(symbol: str, nse_sess=None) -> List[InsiderTrade]:
    """Fetch recent insider / PIT trades for *symbol* from NSE.

    Covers roughly the last 6 months of filings.
    """
    nse_sym = symbol.replace(".NS", "").replace(".BO", "")

    try:
        sess = nse_sess or _create_nse_session()
        today = _dt.date.today()
        from_dt = today - _dt.timedelta(days=180)
        url = (
            f"https://www.nseindia.com/api/corporates-pit"
            f"?index=equities"
            f"&from_date={from_dt.strftime('%d-%m-%Y')}"
            f"&to_date={today.strftime('%d-%m-%Y')}"
            f"&symbol={nse_sym}"
        )
        resp = sess.get(url, timeout=10)
        if resp.status_code != 200:
            return []

        raw = resp.json()
        items = raw.get("data", raw) if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            return []

        trades: List[InsiderTrade] = []
        for it in items[:20]:  # cap at 20 most recent
            sec_acq = it.get("secAcq", "0")
            sec_val = it.get("secVal", "0")
            post_shares = it.get("afterAcqSharesNo", "0")
            trades.append(InsiderTrade(
                person_name=it.get("acqName", "") or "",
                category=it.get("personCategory", "") or "",
                txn_type=it.get("tdpTransactionType", "") or "",
                shares=int(str(sec_acq).replace(",", "")) if sec_acq else 0,
                value=float(str(sec_val).replace(",", "")) if sec_val else 0.0,
                date_from=it.get("acqfromDt", "") or "",
                date_to=it.get("acqtoDt", "") or "",
                post_shares=int(str(post_shares).replace(",", "")) if post_shares else 0,
                mode=it.get("acqMode", "") or "",
            ))
        return trades
    except Exception:
        return []


def _build_deals_analysis(fd) -> str:
    """Build textual analysis of bulk/block deals and insider trades."""
    parts = []
    deals = fd.bulk_block_deals or []
    insiders = fd.insider_trades or []

    # Bulk / Block deals analysis
    if deals:
        buys = [d for d in deals if d.buy_sell == "BUY"]
        sells = [d for d in deals if d.buy_sell == "SELL"]
        bulk_count = sum(1 for d in deals if d.deal_type == "BULK")
        block_count = sum(1 for d in deals if d.deal_type == "BLOCK")

        type_parts = []
        if bulk_count:
            type_parts.append(f"{bulk_count} bulk deal{'s' if bulk_count > 1 else ''}")
        if block_count:
            type_parts.append(f"{block_count} block deal{'s' if block_count > 1 else ''}")
        parts.append(f"Today there {'are' if len(deals) > 1 else 'is'} {' and '.join(type_parts)} for this stock.")

        if buys:
            total_buy_qty = sum(d.quantity for d in buys)
            buyers = ", ".join(d.client_name for d in buys[:3] if d.client_name)
            parts.append(
                f"BUY side: {len(buys)} deal{'s' if len(buys) > 1 else ''} "
                f"totalling {total_buy_qty:,} shares"
                f"{(' by ' + buyers) if buyers else ''}."
            )
        if sells:
            total_sell_qty = sum(d.quantity for d in sells)
            sellers = ", ".join(d.client_name for d in sells[:3] if d.client_name)
            parts.append(
                f"SELL side: {len(sells)} deal{'s' if len(sells) > 1 else ''} "
                f"totalling {total_sell_qty:,} shares"
                f"{(' by ' + sellers) if sellers else ''}."
            )

        buy_qty = sum(d.quantity for d in buys)
        sell_qty = sum(d.quantity for d in sells)
        if buy_qty > sell_qty * 2:
            parts.append("Heavy net buying in bulk/block deals — bullish institutional interest.")
        elif sell_qty > buy_qty * 2:
            parts.append("Heavy net selling in bulk/block deals — institutions may be exiting positions.")
        elif buys and sells:
            parts.append("Both buying and selling in bulk deals — mixed institutional sentiment.")
    else:
        parts.append("No bulk or block deals recorded for this stock today.")

    # Insider trading analysis
    if insiders:
        parts.append("")
        insider_buys = [t for t in insiders if t.txn_type.lower() == "buy"]
        insider_sells = [t for t in insiders if t.txn_type.lower() == "sell"]

        parts.append(
            f"In the last 6 months, {len(insiders)} insider trading "
            f"disclosure{'s' if len(insiders) > 1 else ''} "
            f"{'were' if len(insiders) > 1 else 'was'} filed with the exchange."
        )

        if insider_buys:
            total_buy_val = sum(t.value for t in insider_buys)
            parts.append(
                f"Insiders BOUGHT in {len(insider_buys)} transaction{'s' if len(insider_buys) > 1 else ''}"
                f" worth \u20b9{total_buy_val:,.0f}."
            )
            # Highlight notable promoter/director buys
            notable = [t for t in insider_buys if t.category.lower() in
                       ("promoter", "promoter group", "chairman", "md", "director", "ceo")]
            if notable:
                names = ", ".join(set(t.person_name for t in notable[:3]))
                parts.append(f"Notably, {names} (promoter/director) bought shares — a strong confidence signal.")

        if insider_sells:
            total_sell_val = sum(t.value for t in insider_sells)
            parts.append(
                f"Insiders SOLD in {len(insider_sells)} transaction{'s' if len(insider_sells) > 1 else ''}"
                f" worth \u20b9{total_sell_val:,.0f}."
            )
            notable_sells = [t for t in insider_sells if t.category.lower() in
                             ("promoter", "promoter group", "chairman", "md", "director", "ceo")]
            if notable_sells:
                names = ", ".join(set(t.person_name for t in notable_sells[:3]))
                parts.append(f"Caution: {names} (promoter/director) sold shares — may warrant attention.")

        if insider_buys and not insider_sells:
            parts.append("Only insider buying and no selling in the recent period — positive signal.")
        elif insider_sells and not insider_buys:
            parts.append("Only insider selling in the recent period — may indicate caution warranted.")

    return " ".join(parts)


def fetch_fundamentals(ticker: str) -> FundamentalData:
    """
    Fetch comprehensive fundamental data using yfinance.
    Structured into 4 analysis sections:
      1. Valuation Analysis + Key Ratios
      2. Profitability Analysis + Key Ratios
      3. Growth Key Fields
      4. Stability Analysis + Key Ratios
    """
    fd = FundamentalData(ticker=ticker)

    try:
        info = _fetch_info_with_retry(ticker)

        if not info:
            fd.fetch_error = "Could not fetch data — Yahoo Finance rate limit or ticker not found."
            return fd

        # ── Company Info ──────────────────────────────────────────
        fd.company_name = info.get("longName") or info.get("shortName") or ticker
        fd.sector       = info.get("sector", "N/A")
        fd.industry     = info.get("industry", "N/A")
        fd.exchange     = info.get("exchange", "NSE")
        fd.description  = (info.get("longBusinessSummary") or "")[:400]

        mc = info.get("marketCap") or 0
        fd.market_cap     = float(mc)
        fd.market_cap_str = _format_market_cap(fd.market_cap)

        ev = info.get("enterpriseValue") or 0
        fd.enterprise_value     = float(ev)
        fd.enterprise_value_str = _format_market_cap(fd.enterprise_value).replace("Cap", "").strip()

        fd.outstanding_shares = _safe_float(
            info.get("sharesOutstanding")   # raw share count (e.g. 3.6B for TCS)
        )  # convert to millions

        # ── Price Data ────────────────────────────────────────────
        fd.current_price = _safe_float(
            info.get("currentPrice") or info.get("regularMarketPrice")
        ) or 0.0
        fd.week_52_high  = _safe_float(info.get("fiftyTwoWeekHigh")) or 0.0
        fd.week_52_low   = _safe_float(info.get("fiftyTwoWeekLow")) or 0.0
        fd.avg_volume    = _safe_float(info.get("averageVolume")) or 0.0
        fd.beta          = _safe_float(info.get("beta"))

        if fd.week_52_high > 0 and fd.current_price > 0:
            fd.week_52_pct = round(
                ((fd.current_price - fd.week_52_high) / fd.week_52_high) * 100, 1
            )

        # ── VALUATION KEY RATIOS ──────────────────────────────────
        fd.pe_ratio   = _safe_float(info.get("trailingPE"))
        fd.forward_pe = _safe_float(info.get("forwardPE"))
        fd.pb_ratio   = _safe_float(info.get("priceToBook"))
        fd.ps_ratio   = _safe_float(info.get("priceToSalesTrailing12Months"))
        fd.ev_ebitda  = _safe_float(info.get("enterpriseToEbitda"))
        fd.peg_ratio  = _safe_float(info.get("pegRatio"))
        fd.book_value = _safe_float(info.get("bookValue"))
        fd.eps_ttm    = _safe_float(info.get("trailingEps"))
        fd.eps_forward = _safe_float(info.get("forwardEps"))

        # Computed: Earnings Yield = (1 / PE) × 100
        if fd.pe_ratio and fd.pe_ratio > 0:
            fd.earning_yield = round(100.0 / fd.pe_ratio, 2)

        # Computed: Graham Number = √(22.5 × EPS × Book Value)
        if fd.eps_ttm and fd.book_value and fd.eps_ttm > 0 and fd.book_value > 0:
            fd.graham_number    = round(math.sqrt(22.5 * fd.eps_ttm * fd.book_value), 2)
            fd.intrinsic_value  = fd.graham_number
            if fd.current_price > 0:
                fd.price_to_intrinsic = round(fd.current_price / fd.graham_number, 3)

        # Computed: Price / FCF
        fcf_raw = info.get("freeCashflow")
        shares  = info.get("sharesOutstanding") or 0
        if fcf_raw and shares > 0 and fd.current_price > 0:
            fcf_per_share = float(fcf_raw) / float(shares)
            if fcf_per_share > 0:
                fd.price_to_fcf = round(fd.current_price / fcf_per_share, 2)

        # ──────────────────────────────────────────────────────────
        #  PULL BALANCE SHEET + INCOME STATEMENT for accurate ratios
        #  yfinance .info often returns None for totalAssets,
        #  operatingIncome, totalCurrentLiabilities, etc.
        #  We fill them from financial statements when .info is empty.
        # ──────────────────────────────────────────────────────────
        yf_t = yf.Ticker(ticker)

        def _bs_val(bs_df, *row_names) -> Optional[float]:
            """Get latest quarter value from a balance-sheet DataFrame.
            Uses EXACT case-insensitive match first, falls back to substring."""
            if bs_df is None or bs_df.empty:
                return None
            col = bs_df.columns[0]
            # Pass 1: exact match
            for rn_target in row_names:
                for idx in bs_df.index:
                    if str(idx).strip().lower() == rn_target.strip().lower():
                        v = bs_df.loc[idx, col]
                        if pd.notna(v):
                            return float(v)
            # Pass 2: substring match (only if exact didn't work)
            for rn_target in row_names:
                for idx in bs_df.index:
                    if rn_target.lower() in str(idx).lower():
                        v = bs_df.loc[idx, col]
                        if pd.notna(v):
                            return float(v)
            return None

        def _is_val(is_df, *row_names) -> Optional[float]:
            """Get TTM (sum of 4 quarters) value from income statement.
            Uses EXACT case-insensitive match first, falls back to substring."""
            if is_df is None or is_df.empty:
                return None
            ncols = min(4, len(is_df.columns))
            # Pass 1: exact match
            for rn_target in row_names:
                for idx in is_df.index:
                    if str(idx).strip().lower() == rn_target.strip().lower():
                        vals = [is_df.loc[idx, is_df.columns[c]]
                                for c in range(ncols)]
                        valid = [float(v) for v in vals if pd.notna(v)]
                        if valid:
                            return sum(valid)
            # Pass 2: substring (only if exact didn't work)
            for rn_target in row_names:
                for idx in is_df.index:
                    if str(idx).strip().lower() == rn_target.strip().lower():
                        pass  # already tried
                    elif rn_target.lower() in str(idx).lower():
                        vals = [is_df.loc[idx, is_df.columns[c]]
                                for c in range(ncols)]
                        valid = [float(v) for v in vals if pd.notna(v)]
                        if valid:
                            return sum(valid)
            return None

        def _is_latest(is_df, *row_names) -> Optional[float]:
            """Get latest single quarter value from income statement."""
            if is_df is None or is_df.empty:
                return None
            col = is_df.columns[0]
            for rn_target in row_names:
                for idx in is_df.index:
                    if str(idx).strip().lower() == rn_target.strip().lower():
                        v = is_df.loc[idx, col]
                        if pd.notna(v):
                            return float(v)
            for rn_target in row_names:
                for idx in is_df.index:
                    if rn_target.lower() in str(idx).lower():
                        v = is_df.loc[idx, col]
                        if pd.notna(v):
                            return float(v)
            return None

        try:
            _throttle()
            bs  = yf_t.quarterly_balance_sheet
            qis = yf_t.quarterly_income_stmt
        except Exception:
            bs, qis = None, None

        # ── Fill from balance sheet where .info is blank ──
        _total_assets_bs      = _bs_val(bs, "Total Assets")
        _curr_liab_bs         = _bs_val(bs, "Current Liabilities")
        _curr_assets_bs       = _bs_val(bs, "Current Assets")
        _total_equity_bs      = _bs_val(bs, "Stockholders Equity", "Common Stock Equity",
                                        "Total Equity Gross Minority Interest")
        _total_debt_bs        = _bs_val(bs, "Total Debt")
        _total_cash_bs        = _bs_val(bs, "Cash And Cash Equivalents",
                                        "Cash Cash Equivalents And Short Term Investments")
        _retained_earn_bs     = _bs_val(bs, "Retained Earnings")
        _total_liab_bs        = _bs_val(bs, "Total Liabilities Net Minority Interest")

        # ── Fill from income statement (TTM = sum of 4 quarters) ──
        _ebit_ttm             = _is_val(qis, "EBIT")
        _operating_inc_ttm    = _is_val(qis, "Operating Income")
        _net_income_ttm       = _is_val(qis, "Net Income Common Stockholders",
                                        "Net Income")
        _total_revenue_ttm    = _is_val(qis, "Total Revenue")
        _ebitda_ttm           = _is_val(qis, "EBITDA")

        # Use .info values first; fall back to financial-statement values
        operating_inc = info.get("operatingIncome")  or _operating_inc_ttm
        total_assets  = info.get("totalAssets")       or _total_assets_bs
        curr_liab     = info.get("totalCurrentLiabilities") or _curr_liab_bs
        total_curr_assets = info.get("totalCurrentAssets") or _curr_assets_bs

        # ── PROFITABILITY KEY RATIOS ──────────────────────────────
        fd.roe              = _safe_pct(info.get("returnOnEquity"))
        fd.roa              = _safe_pct(info.get("returnOnAssets"))
        fd.profit_margin    = _safe_pct(info.get("profitMargins"))
        fd.operating_margin = _safe_pct(info.get("operatingMargins"))
        fd.gross_margin     = _safe_pct(info.get("grossMargins"))

        fd.ebitda  = _safe_float(info.get("ebitda"))
        fd.ebitda_margin = None
        total_rev_raw = info.get("totalRevenue")
        if fd.ebitda and total_rev_raw and float(total_rev_raw) > 0:
            fd.ebitda_margin = round((fd.ebitda / float(total_rev_raw)) * 100, 2)

        # Re-compute profit margin from TTM if available (more accurate)
        if _net_income_ttm and _total_revenue_ttm and _total_revenue_ttm > 0:
            fd.profit_margin = round((_net_income_ttm / _total_revenue_ttm) * 100, 2)
        # Re-compute operating margin from TTM if available
        if _operating_inc_ttm and _total_revenue_ttm and _total_revenue_ttm > 0:
            fd.operating_margin = round((_operating_inc_ttm / _total_revenue_ttm) * 100, 2)
        # Re-compute EBITDA margin from TTM
        if _ebitda_ttm and _total_revenue_ttm and _total_revenue_ttm > 0:
            fd.ebitda_margin = round((_ebitda_ttm / _total_revenue_ttm) * 100, 2)

        # Compute ROE from financial statements (more reliable than .info)
        # ROE = Net Profit (TTM) / Shareholders Equity × 100
        if _net_income_ttm and _total_equity_bs and _total_equity_bs > 0:
            roe_computed = round((_net_income_ttm / _total_equity_bs) * 100, 2)
            fd.roe = roe_computed   # prefer BS-computed over .info
        
        # Compute ROA from financial statements if .info is missing
        if fd.roa is None and _net_income_ttm and _total_assets_bs and _total_assets_bs > 0:
            fd.roa = round((_net_income_ttm / _total_assets_bs) * 100, 2)

        # ROCE = EBIT (TTM) / Capital Employed
        # Capital Employed = Total Assets − Current Liabilities
        ebit_for_roce = _ebit_ttm or (operating_inc if operating_inc else None)
        if ebit_for_roce and total_assets and curr_liab:
            cap_employed = float(total_assets) - float(curr_liab)
            if cap_employed > 0:
                fd.roce = round((float(ebit_for_roce) / cap_employed) * 100, 2)

        # ── GROWTH KEY FIELDS ─────────────────────────────────────
        fd.revenue_growth  = _safe_pct(info.get("revenueGrowth"))
        fd.earnings_growth = _safe_pct(info.get("earningsGrowth"))
        fd.total_revenue   = _safe_float(info.get("totalRevenue")) or _safe_float(_total_revenue_ttm)
        fd.gross_profit    = _safe_float(info.get("grossProfits"))
        fd.net_income      = _safe_float(info.get("netIncomeToCommon")) or _safe_float(_net_income_ttm)
        fd.free_cash_flow  = _safe_float(info.get("freeCashflow"))
        fd.total_assets    = _safe_float(total_assets)

        # ── STABILITY KEY RATIOS ──────────────────────────────────
        # yfinance debtToEquity is returned as PERCENTAGE (e.g. 9.44 = 9.44%)
        # To get the actual D/E ratio: divide by 100 → 0.0944
        raw_de = _safe_float(info.get("debtToEquity"))
        if raw_de is not None:
            fd.debt_to_equity = round(raw_de / 100.0, 4)
        else:
            # Compute from balance sheet: Total Debt / Total Equity
            if _total_debt_bs and _total_equity_bs and _total_equity_bs > 0:
                fd.debt_to_equity = round(_total_debt_bs / _total_equity_bs, 4)

        fd.current_ratio      = _safe_float(info.get("currentRatio"))
        fd.quick_ratio        = _safe_float(info.get("quickRatio"))
        fd.total_debt         = _safe_float(info.get("totalDebt")) or _safe_float(_total_debt_bs)
        fd.total_cash         = _safe_float(info.get("totalCash")) or _safe_float(_total_cash_bs)

        # Shareholders Equity = TOTAL equity from balance sheet (not per-share bookValue)
        fd.shareholders_equity = _safe_float(_total_equity_bs)

        # Compute current ratio from balance sheet if .info missing
        if fd.current_ratio is None and _curr_assets_bs and _curr_liab_bs and _curr_liab_bs > 0:
            fd.current_ratio = round(_curr_assets_bs / _curr_liab_bs, 2)

        # Computed: Cash Ratio = Cash & Equivalents / Current Liabilities
        # Use the strictest definition: pure "Cash And Cash Equivalents" from BS
        # (NOT totalCash from .info which includes short-term investments)
        _pure_cash_bs = _bs_val(bs, "Cash And Cash Equivalents")
        cash_for_ratio = _pure_cash_bs or _total_cash_bs or info.get("totalCash")
        cl_for_ratio   = curr_liab
        if cash_for_ratio and cl_for_ratio and float(cl_for_ratio) > 0:
            fd.cash_ratio = round(float(cash_for_ratio) / float(cl_for_ratio), 2)

        # Computed: Debt/EBITDA
        if fd.total_debt and fd.ebitda and fd.ebitda > 0:
            fd.debt_to_ebitda = round(fd.total_debt / fd.ebitda, 3)

        # Computed: Altman Z-Score (modified for service / non-manufacturing)
        # Z′ = 6.56×X1 + 3.26×X2 + 6.72×X3 + 1.05×X4
        # X1 = Working Capital / Total Assets
        # X2 = Retained Earnings / Total Assets
        # X3 = EBIT / Total Assets
        # X4 = Book Value of Equity / Total Liabilities
        ebit_raw  = _ebit_ttm or (operating_inc if operating_inc else None)
        book_eq   = _total_equity_bs
        total_liab = _total_liab_bs
        retained_earn = _retained_earn_bs

        ta_z = float(total_assets) if total_assets else None
        if ta_z and ta_z > 0 and total_curr_assets and curr_liab and ebit_raw and book_eq and total_liab and float(total_liab) > 0:
            wc   = float(total_curr_assets) - float(curr_liab)
            re   = float(retained_earn) if retained_earn else 0.0
            ebit_z = float(ebit_raw)
            bv   = float(book_eq)
            td   = float(total_liab)
            x1 = wc / ta_z
            x2 = re / ta_z
            x3 = ebit_z / ta_z
            x4 = bv / td
            fd.altman_z_score = round(6.56*x1 + 3.26*x2 + 6.72*x3 + 1.05*x4, 2)

        # ── INTEREST COVERAGE = EBIT / Interest Expense ─────────
        _interest_exp_ttm = _is_val(qis, "Interest Expense", "Interest Expense Non Operating")
        ebit_for_ic = _ebit_ttm or (operating_inc if operating_inc else None)
        if ebit_for_ic and _interest_exp_ttm and abs(_interest_exp_ttm) > 0:
            fd.interest_coverage = round(abs(float(ebit_for_ic)) / abs(float(_interest_exp_ttm)), 2)

        # ── ASSET TURNOVER = Revenue / Total Assets ───────────
        if _total_revenue_ttm and total_assets and float(total_assets) > 0:
            fd.asset_turnover = round(float(_total_revenue_ttm) / float(total_assets), 2)

        # ── DEBT-TO-ASSETS = Total Debt / Total Assets ────────
        td_val = fd.total_debt or _total_debt_bs
        if td_val and total_assets and float(total_assets) > 0:
            fd.debt_to_assets = round(float(td_val) / float(total_assets), 4)

        # ── DIVIDENDS ────────────────────────────────────────────
        # dividendYield from yfinance is inconsistent:
        #   sometimes decimal (0.0267) → needs ×100  to get 2.67%
        #   sometimes already % (2.67) → use as-is
        #   sometimes small decimal (0.41) that IS already % (0.41%)
        #
        # Simple heuristic (< 1 → ×100) fails for low-yield stocks (0.41 → 41%!).
        # Solution: cross-validate with dividendRate / currentPrice.
        raw_div_yield = info.get("dividendYield")
        raw_div_rate  = info.get("dividendRate")
        if raw_div_yield is not None:
            dv = float(raw_div_yield)
            # Cross-validate: compute yield from rate/price
            manual_yield = None
            if raw_div_rate and fd.current_price and fd.current_price > 0:
                manual_yield = (float(raw_div_rate) / fd.current_price) * 100  # always %

            if manual_yield is not None:
                # Compare dv (as-is) vs dv*100 — whichever is closer to manual_yield wins
                diff_as_pct  = abs(dv - manual_yield)        # treat dv as already %
                diff_as_frac = abs(dv * 100 - manual_yield)  # treat dv as fractional
                if diff_as_pct <= diff_as_frac:
                    fd.dividend_yield = round(dv, 2)          # already percentage
                else:
                    fd.dividend_yield = round(dv * 100, 2)    # was fractional
            else:
                # No rate available — use conservative threshold
                # Yields > 15% are extremely rare for Indian stocks
                if dv > 0.15:
                    fd.dividend_yield = round(dv, 2)          # likely already %
                else:
                    fd.dividend_yield = round(dv * 100, 2)    # likely fractional
        fd.dividend_rate  = _safe_float(raw_div_rate)
        fd.payout_ratio   = _safe_pct(info.get("payoutRatio"))

        # ── SHAREHOLDING ─────────────────────────────────────────
        # yfinance provides:
        #   heldPercentInsiders      → Promoter / Insider holding (fractional)
        #   heldPercentInstitutions  → ALL institutions = FII + DII combined (fractional)
        # We cannot split FII vs DII from yfinance alone.
        # Label: "Institutional" (FII+DII), not just "FII"
        held_inst    = _safe_pct(info.get("heldPercentInstitutions"))  # FII+DII combined
        held_insider = _safe_pct(info.get("heldPercentInsiders"))      # Promoter/Insider

        fd.promoter_holding = held_insider
        fd.fii_holding      = held_inst      # NOTE: This is FII+DII combined
        fd.dii_holding      = None           # Cannot split from yfinance
        if held_inst is not None and held_insider is not None:
            fd.public_holding = round(max(0.0, 100.0 - held_inst - held_insider), 2)
        # float_pct = floatShares / sharesOutstanding × 100
        float_shares = info.get("floatShares") or 0
        shares_out   = info.get("sharesOutstanding") or 0
        if float_shares and shares_out:
            fd.float_pct = round(float_shares / shares_out * 100, 2)
        else:
            fd.float_pct = None

        # ── QUARTERLY RESULTS (last 4-6 quarters) ─────────────────
        # Reuse yf_t and qis already fetched above for balance-sheet/IS
        try:
            if qis is not None and not qis.empty:
                cols = list(qis.columns[:6])   # up to 6 most recent quarters
                for col in cols:
                    try:
                        dt = pd.to_datetime(col)
                        # Map to Indian fiscal quarter with date range
                        m = dt.month
                        _mo_short = ["Jan","Feb","Mar","Apr","May","Jun",
                                     "Jul","Aug","Sep","Oct","Nov","Dec"]
                        if m in (4, 5, 6):
                            fq = "Q1"; q_start, q_end = "Apr", "Jun"
                        elif m in (7, 8, 9):
                            fq = "Q2"; q_start, q_end = "Jul", "Sep"
                        elif m in (10, 11, 12):
                            fq = "Q3"; q_start, q_end = "Oct", "Dec"
                        else:
                            fq = "Q4"; q_start, q_end = "Jan", "Mar"
                        fy = dt.year if dt.month > 3 else dt.year - 1
                        # Show actual months so users know the real calendar period
                        q_yr = dt.year if fq != "Q4" else dt.year
                        period = f"{fq} FY{str(fy+1)[-2:]} ({q_start}-{q_end} '{str(q_yr)[-2:]})"

                        def _qval(row_name: str) -> Optional[float]:
                            for rn in qis.index:
                                if row_name.lower() in str(rn).lower():
                                    v = qis.loc[rn, col]
                                    if pd.notna(v):
                                        return round(float(v), 2)
                            return None

                        rev   = _qval("Total Revenue")
                        ni    = _qval("Net Income Common Stockholders") or _qval("Net Income")
                        gp    = _qval("Gross Profit")
                        ebit  = _qval("EBITDA") or _qval("Operating Income")
                        oi    = _qval("Operating Income")
                        ie    = _qval("Interest Expense")
                        pti   = _qval("Pretax Income")
                        tp    = _qval("Tax Provision")

                        # Prefer Diluted EPS directly from statement; fall back to computed
                        eps_q = _qval("Diluted EPS") or _qval("Basic EPS")
                        if eps_q is None and ni and shares_out and float(shares_out) > 0:
                            eps_q = round(float(ni) / float(shares_out), 2)

                        # Compute margins
                        gm = round(gp / rev * 100, 2) if gp and rev and rev > 0 else None
                        om = round(oi / rev * 100, 2) if oi and rev and rev > 0 else None
                        nm = round(ni / rev * 100, 2) if ni and rev and rev > 0 else None

                        fd.quarterly_results.append(QuarterlyResult(
                            period=period, revenue=rev, net_income=ni,
                            eps=eps_q, gross_profit=gp, ebitda=ebit,
                            operating_income=oi, interest_expense=ie,
                            pretax_income=pti, tax_provision=tp,
                            gross_margin=gm, operating_margin=om, net_margin=nm
                        ))
                    except Exception:
                        pass
        except Exception:
            pass

        # ── SHAREHOLDING HISTORY ──
        # yfinance does not provide historical quarterly shareholding data.
        # Only the current snapshot is available and shown in the doughnut chart.
        # Historical trend data has been intentionally removed to avoid showing
        # fabricated numbers. When a reliable data source (e.g., NSE APIs) is
        # integrated, real quarterly shareholding history can be populated here.

        # ── DIVIDEND HISTORY ──────────────────────────────────────
        try:
            divs = yf_t.dividends
            if divs is not None and not divs.empty:
                for dt_val, amt in divs.tail(12).items():
                    fd.dividend_history.append(DividendEntry(
                        date=dt_val.strftime("%Y-%m-%d"),
                        amount=round(float(amt), 2),
                    ))
            # ex-dividend date from info
            ex_div_ts = info.get("exDividendDate")
            if ex_div_ts:
                fd.ex_dividend_date = _dt.datetime.fromtimestamp(int(ex_div_ts)).strftime("%Y-%m-%d")
        except Exception:
            pass

        # ── EARNINGS CALENDAR & DATES ─────────────────────────────
        try:
            cal = yf_t.calendar
            if isinstance(cal, dict):
                ed_list = cal.get("Earnings Date", [])
                if ed_list:
                    next_dt = ed_list[0]
                    if hasattr(next_dt, "strftime"):
                        fd.upcoming_results_date = next_dt.strftime("%Y-%m-%d")
                    else:
                        fd.upcoming_results_date = str(next_dt)[:10]
                est_eps = cal.get("Earnings Average")
                if est_eps is not None:
                    fd.earnings_estimate_eps = round(float(est_eps), 2)
        except Exception:
            pass

        try:
            ed_df = yf_t.earnings_dates
            if ed_df is not None and not ed_df.empty:
                for idx_dt, row in ed_df.head(12).iterrows():
                    dt_str = idx_dt.strftime("%Y-%m-%d") if hasattr(idx_dt, "strftime") else str(idx_dt)[:10]
                    est = row.get("EPS Estimate")
                    rep = row.get("Reported EPS")
                    surp = row.get("Surprise(%)")
                    fd.earnings_dates_history.append(EarningsDateEntry(
                        date=dt_str,
                        eps_estimate=round(float(est), 2) if pd.notna(est) else None,
                        eps_reported=round(float(rep), 2) if pd.notna(rep) else None,
                        surprise_pct=round(float(surp), 2) if pd.notna(surp) else None,
                    ))
        except Exception:
            pass

        # ── DELIVERY DATA (from NSE) ─────────────────────────────
        nse_sess = None
        try:
            nse_sess = _create_nse_session()
            nse_del = _fetch_nse_delivery(ticker, nse_sess=nse_sess)
            if nse_del:
                fd.traded_quantity   = nse_del.get("traded_quantity")
                fd.delivery_quantity = nse_del.get("delivery_quantity")
                fd.delivery_pct      = nse_del.get("delivery_pct")
                fd.delivery_date     = nse_del.get("delivery_date")
                fd.delivery_analysis = _build_delivery_analysis(fd)
        except Exception:
            pass

        # ── HISTORICAL DELIVERY DATA (from NSE bhavcopy) ─────────
        try:
            fd.delivery_history = _fetch_nse_delivery_history(
                ticker, nse_sess=nse_sess, days=60
            )
            if fd.delivery_history:
                fd.delivery_history_analysis = _build_delivery_history_analysis(fd)
        except Exception:
            pass

        # ── BULK / BLOCK DEALS & INSIDER TRADING (from NSE) ──────
        try:
            fd.bulk_block_deals = _fetch_nse_bulk_block_deals(ticker, nse_sess=nse_sess)
        except Exception:
            pass
        try:
            fd.insider_trades = _fetch_nse_insider_trades(ticker, nse_sess=nse_sess)
        except Exception:
            pass
        try:
            fd.deals_analysis = _build_deals_analysis(fd)
        except Exception:
            pass

        # ── SECTION SCORES ────────────────────────────────────────
        fd.valuation_score     = _calc_valuation_score(fd)
        fd.profitability_score = _calc_profitability_score(fd)
        fd.growth_score        = _calc_growth_score(fd)
        fd.stability_score     = _calc_stability_score(fd)

        # Overall = weighted average of section scores
        fd.fundamental_score = _calc_overall_score(fd)

        # ── FINAL VERDICT ─────────────────────────────────────────
        _compute_verdict(fd)

        # ── TEXT ANALYSES ─────────────────────────────────────────
        fd.valuation_analysis     = _build_valuation_analysis(fd)
        fd.profitability_analysis = _build_profitability_analysis(fd)
        fd.growth_analysis        = _build_growth_analysis(fd)
        fd.stability_analysis     = _build_stability_analysis(fd)
        fd.conviction_message     = _conviction_message(fd)

        # ── DESCRIPTIVE SUMMARIES ─────────────────────────────────
        fd.quarterly_analysis    = _build_quarterly_analysis(fd)
        fd.shareholding_verdict  = _build_shareholding_verdict(fd)
        fd.dividend_summary      = _build_dividend_summary(fd)

        # ── ANNUAL FINANCIAL STATEMENTS ───────────────────────────
        try:
            fd.annual_financials = _fetch_annual_financials(yf_t)
            if fd.annual_financials:
                fd.financial_statements_analysis = _build_financial_statements_analysis(fd)
        except Exception:
            pass

    except Exception as e:
        fd.fetch_error = str(e)

    return fd


def _fmt_cr(val: Optional[float], decimals: int = 2) -> str:
    """Format large ₹ values in Crores."""
    if val is None:
        return "N/A"
    cr = val / 1e7
    if cr >= 1_00_000:
        return f"₹{cr/1_00_000:.2f}L Cr"
    if cr >= 1_000:
        return f"₹{cr/1_000:.1f}K Cr"
    return f"₹{cr:.{decimals}f} Cr"


def _na(val: Optional[float], decimals: int = 2, suffix: str = "") -> str:
    if val is None:
        return "N/A"
    return f"{val:.{decimals}f}{suffix}"




# ══════════════════════════════════════════════════════════════════
#  INTELLIGENT SCORING ENGINE — Gradient-based, not binary
#
#  Each ratio is scored on a GRADIENT (0-100) rather than pass/fail.
#  This gives partial credit: PE of 18 scores higher than PE of 24,
#  and both score higher than PE of 60.
#
#  The overall score combines 4 section scores with cross-ratio
#  bonuses/penalties. The final output is a clear:
#      ● BUY (STRONG / MODERATE)
#      ● HOLD
#      ● AVOID (MODERATE / STRONG)
# ══════════════════════════════════════════════════════════════════


def _gradient(val: float, best: float, worst: float, invert: bool = False) -> float:
    """
    Score a value on a 0-100 gradient between best and worst.

    If invert=False (default): LOWER is better (PE, PB, D/E, etc.)
       val <= best  → 100;  val >= worst → 0;  linear in between.

    If invert=True: HIGHER is better (ROE, margins, etc.)
       val >= best  → 100;  val <= worst → 0;  linear in between.
    """
    if invert:
        if val >= best:
            return 100.0
        if val <= worst:
            return 0.0
        return max(0.0, min(100.0, (val - worst) / (best - worst) * 100.0))
    else:
        if val <= best:
            return 100.0
        if val >= worst:
            return 0.0
        return max(0.0, min(100.0, (worst - val) / (worst - best) * 100.0))


def _calc_valuation_score(fd) -> int:
    """
    Intelligent valuation scoring — gradient-based.
    Considers PE, PB, EV/EBITDA, PEG, PS, P/Graham, Earning Yield, P/FCF.
    Each metric scored 0-100 on a gradient with appropriate sector-agnostic ranges.
    """
    scores = []
    weights = []

    # P/E Ratio: best=8, worst=60. Negative PE (loss-making) = 0
    if fd.pe_ratio is not None:
        if fd.pe_ratio <= 0:
            scores.append(0)
        else:
            scores.append(_gradient(fd.pe_ratio, 8, 60, invert=False))
        weights.append(20)

    # P/B Ratio: best=0.5, worst=10
    if fd.pb_ratio is not None and fd.pb_ratio > 0:
        scores.append(_gradient(fd.pb_ratio, 0.5, 10, invert=False))
        weights.append(12)

    # EV/EBITDA: best=4, worst=30
    if fd.ev_ebitda is not None and fd.ev_ebitda > 0:
        scores.append(_gradient(fd.ev_ebitda, 4, 30, invert=False))
        weights.append(18)

    # PEG Ratio: best=0.5, worst=3.0
    if fd.peg_ratio is not None and fd.peg_ratio > 0:
        scores.append(_gradient(fd.peg_ratio, 0.5, 3.0, invert=False))
        weights.append(15)

    # P/S Ratio: best=0.5, worst=15
    if fd.ps_ratio is not None and fd.ps_ratio > 0:
        scores.append(_gradient(fd.ps_ratio, 0.5, 15, invert=False))
        weights.append(8)

    # Price / Graham Number: best=0.5, worst=4.0
    if fd.price_to_intrinsic is not None and fd.price_to_intrinsic > 0:
        scores.append(_gradient(fd.price_to_intrinsic, 0.5, 4.0, invert=False))
        weights.append(12)

    # Earning Yield %: best=15, worst=1
    if fd.earning_yield is not None and fd.earning_yield > 0:
        scores.append(_gradient(fd.earning_yield, 15, 1, invert=True))
        weights.append(8)

    # P/FCF: best=5, worst=50
    if fd.price_to_fcf is not None and fd.price_to_fcf > 0:
        scores.append(_gradient(fd.price_to_fcf, 5, 50, invert=False))
        weights.append(7)

    if not weights:
        return 0
    total = sum(s * w for s, w in zip(scores, weights))
    return min(100, max(0, int(total / sum(weights))))


def _calc_profitability_score(fd) -> int:
    """
    Intelligent profitability scoring — gradient-based.
    ROE, ROA, ROCE, Net Margin, Operating Margin, EBITDA Margin, Gross Margin.
    """
    scores = []
    weights = []

    # ROE %: best=30, worst=0
    if fd.roe is not None:
        scores.append(_gradient(max(fd.roe, 0), 30, 0, invert=True))
        weights.append(25)

    # ROA %: best=15, worst=0
    if fd.roa is not None:
        scores.append(_gradient(max(fd.roa, 0), 15, 0, invert=True))
        weights.append(12)

    # ROCE %: best=30, worst=0
    if fd.roce is not None:
        scores.append(_gradient(max(fd.roce, 0), 30, 0, invert=True))
        weights.append(18)

    # Net Profit Margin %: best=25, worst=0
    if fd.profit_margin is not None:
        if fd.profit_margin < 0:
            scores.append(0)
        else:
            scores.append(_gradient(fd.profit_margin, 25, 0, invert=True))
        weights.append(18)

    # Operating Margin %: best=25, worst=0
    if fd.operating_margin is not None:
        if fd.operating_margin < 0:
            scores.append(0)
        else:
            scores.append(_gradient(fd.operating_margin, 25, 0, invert=True))
        weights.append(12)

    # EBITDA Margin %: best=30, worst=0
    if fd.ebitda_margin is not None:
        if fd.ebitda_margin < 0:
            scores.append(0)
        else:
            scores.append(_gradient(fd.ebitda_margin, 30, 0, invert=True))
        weights.append(10)

    # Gross Margin %: best=60, worst=10
    if fd.gross_margin is not None and fd.gross_margin > 0:
        scores.append(_gradient(fd.gross_margin, 60, 10, invert=True))
        weights.append(5)

    if not weights:
        return 0
    total = sum(s * w for s, w in zip(scores, weights))
    return min(100, max(0, int(total / sum(weights))))


def _calc_growth_score(fd) -> int:
    """
    Intelligent growth scoring — gradient-based.
    Revenue growth, earnings growth, positive FCF, and cross-checks.
    """
    scores = []
    weights = []

    # Revenue Growth %: best=25, worst=-10
    if fd.revenue_growth is not None:
        scores.append(_gradient(fd.revenue_growth, 25, -10, invert=True))
        weights.append(30)

    # Earnings Growth %: best=30, worst=-20
    if fd.earnings_growth is not None:
        scores.append(_gradient(fd.earnings_growth, 30, -20, invert=True))
        weights.append(35)

    # Free Cash Flow: positive = good, negative = bad
    if fd.free_cash_flow is not None:
        if fd.free_cash_flow > 0:
            scores.append(80)   # positive FCF is a solid pass
        else:
            scores.append(15)   # negative FCF is weak but not zero (could be investing)
        weights.append(20)

    # Forward PE < Trailing PE = earnings expected to grow
    if fd.pe_ratio is not None and fd.forward_pe is not None:
        if fd.pe_ratio > 0 and fd.forward_pe > 0:
            growth_implied = ((fd.pe_ratio / fd.forward_pe) - 1) * 100
            scores.append(_gradient(growth_implied, 30, -20, invert=True))
            weights.append(15)

    if not weights:
        return 0
    total = sum(s * w for s, w in zip(scores, weights))
    return min(100, max(0, int(total / sum(weights))))


def _calc_stability_score(fd) -> int:
    """
    Intelligent stability scoring — gradient-based.
    D/E, current ratio, quick ratio, cash ratio, Debt/EBITDA, Altman Z.
    """
    scores = []
    weights = []

    # Debt/Equity: best=0, worst=3.0
    if fd.debt_to_equity is not None:
        scores.append(_gradient(max(fd.debt_to_equity, 0), 0, 3.0, invert=False))
        weights.append(25)

    # Current Ratio: best=3.0, worst=0.5
    if fd.current_ratio is not None:
        scores.append(_gradient(fd.current_ratio, 3.0, 0.5, invert=True))
        weights.append(18)

    # Quick Ratio: best=2.0, worst=0.3
    if fd.quick_ratio is not None:
        scores.append(_gradient(fd.quick_ratio, 2.0, 0.3, invert=True))
        weights.append(12)

    # Cash Ratio: best=1.5, worst=0
    if fd.cash_ratio is not None:
        scores.append(_gradient(fd.cash_ratio, 1.5, 0, invert=True))
        weights.append(8)

    # Debt/EBITDA: best=0, worst=6
    if fd.debt_to_ebitda is not None:
        scores.append(_gradient(max(fd.debt_to_ebitda, 0), 0, 6, invert=False))
        weights.append(15)

    # Altman Z-Score: best=5, worst=0.5
    if fd.altman_z_score is not None:
        scores.append(_gradient(fd.altman_z_score, 5, 0.5, invert=True))
        weights.append(22)

    if not weights:
        return 0
    total = sum(s * w for s, w in zip(scores, weights))
    return min(100, max(0, int(total / sum(weights))))


def _calc_overall_score(fd) -> int:
    """
    Weighted average of 4 section scores with cross-ratio bonuses.

    Base weights: Profitability 30%, Valuation 25%, Growth 25%, Stability 20%

    Cross-ratio adjustments:
      • If cheap (valuation ≥ 60) AND profitable (≥ 60) → bonus +5
      • If cheap AND growing → bonus +5
      • If profitable AND growing AND stable → bonus +3
      • If expensive AND shrinking → penalty -5
      • If high debt AND shrinking → penalty -5
    """
    weights = {
        'val': 25, 'prof': 30, 'growth': 25, 'stab': 20
    }
    base = (
        fd.valuation_score * weights['val']
        + fd.profitability_score * weights['prof']
        + fd.growth_score * weights['growth']
        + fd.stability_score * weights['stab']
    )
    score = base / 100  # now 0-100

    # Cross-ratio bonuses
    if fd.valuation_score >= 60 and fd.profitability_score >= 60:
        score += 5  # cheap + profitable = value gem
    if fd.valuation_score >= 60 and fd.growth_score >= 60:
        score += 5  # cheap + growing = GARP (Growth At Reasonable Price)
    if fd.profitability_score >= 60 and fd.growth_score >= 60 and fd.stability_score >= 60:
        score += 3  # profitable + growing + stable = quality compounder

    # Cross-ratio penalties
    if fd.valuation_score < 30 and fd.growth_score < 30:
        score -= 5  # expensive + shrinking = danger
    if fd.stability_score < 30 and fd.growth_score < 30:
        score -= 5  # stressed + shrinking = distress

    return min(100, max(0, int(score)))


def _compute_verdict(fd) -> None:
    """
    Compute the final BUY / HOLD / AVOID verdict based on overall score,
    section scores, and critical red-flag checks.

    This is the most important function — it produces a clear,
    actionable recommendation for stock selection.
    """
    score = fd.fundamental_score
    v_s = fd.valuation_score
    p_s = fd.profitability_score
    g_s = fd.growth_score
    s_s = fd.stability_score

    # ── Red flags that force AVOID regardless of score ──
    red_flags = []
    if fd.altman_z_score is not None and fd.altman_z_score < 1.1:
        red_flags.append("Altman Z-Score in Distress Zone")
    if fd.debt_to_equity is not None and fd.debt_to_equity > 3.0:
        red_flags.append("Dangerously high debt")
    if fd.pe_ratio is not None and fd.pe_ratio < 0:
        red_flags.append("Company is loss-making")
    if fd.profit_margin is not None and fd.profit_margin < -10:
        red_flags.append("Deep negative margins")
    if fd.earnings_growth is not None and fd.earnings_growth < -30:
        red_flags.append("Earnings collapsing (>30% decline)")

    # ── Green flags that boost conviction ──
    green_flags = []
    if fd.roe is not None and fd.roe > 20:
        green_flags.append("High ROE (>20%)")
    if fd.debt_to_equity is not None and fd.debt_to_equity < 0.3:
        green_flags.append("Virtually debt-free")
    if fd.altman_z_score is not None and fd.altman_z_score > 3.0:
        green_flags.append("Excellent financial health (Z>3)")
    if fd.free_cash_flow is not None and fd.free_cash_flow > 0:
        green_flags.append("Positive free cash flow")
    if fd.price_to_intrinsic is not None and fd.price_to_intrinsic < 1.0:
        green_flags.append("Below Graham Number (undervalued)")
    if fd.revenue_growth is not None and fd.revenue_growth > 15:
        green_flags.append("Strong revenue growth (>15%)")
    if fd.earnings_growth is not None and fd.earnings_growth > 20:
        green_flags.append("Strong earnings growth (>20%)")

    # ── Compute verdict ──
    if red_flags and score < 50:
        fd.fundamental_signal = "AVOID"
        fd.signal_strength = "STRONG"
        fd.signal_color = "red"
        fd.fundamental_verdict = f"🔴 AVOID — {'; '.join(red_flags[:2])}"
    elif score >= 75:
        if len(green_flags) >= 3:
            fd.fundamental_signal = "BUY"
            fd.signal_strength = "STRONG"
            fd.signal_color = "green"
            fd.fundamental_verdict = "🟢 STRONG BUY — Excellent fundamentals across all parameters"
        else:
            fd.fundamental_signal = "BUY"
            fd.signal_strength = "MODERATE"
            fd.signal_color = "green"
            fd.fundamental_verdict = "🟢 BUY — Strong fundamentals support investment"
    elif score >= 60:
        if p_s >= 65 and s_s >= 60:
            fd.fundamental_signal = "BUY"
            fd.signal_strength = "MODERATE"
            fd.signal_color = "green"
            fd.fundamental_verdict = "🟢 BUY — Profitable & stable company at reasonable price"
        else:
            fd.fundamental_signal = "HOLD"
            fd.signal_strength = "MODERATE"
            fd.signal_color = "yellow"
            fd.fundamental_verdict = "🟡 HOLD — Decent fundamentals, wait for better entry or growth"
    elif score >= 45:
        if red_flags:
            fd.fundamental_signal = "AVOID"
            fd.signal_strength = "MODERATE"
            fd.signal_color = "red"
            fd.fundamental_verdict = f"🔴 AVOID — {red_flags[0]}"
        else:
            fd.fundamental_signal = "HOLD"
            fd.signal_strength = "WEAK"
            fd.signal_color = "yellow"
            fd.fundamental_verdict = "🟡 HOLD — Mixed signals, use alongside technical analysis"
    elif score >= 30:
        fd.fundamental_signal = "AVOID"
        fd.signal_strength = "MODERATE"
        fd.signal_color = "red"
        reason = red_flags[0] if red_flags else "Weak fundamentals across multiple parameters"
        fd.fundamental_verdict = f"🔴 AVOID — {reason}"
    else:
        fd.fundamental_signal = "AVOID"
        fd.signal_strength = "STRONG"
        fd.signal_color = "red"
        reason = red_flags[0] if red_flags else "Poor fundamentals — high risk"
        fd.fundamental_verdict = f"🔴 STRONG AVOID — {reason}"


# ══════════════════════════════════════════════════════════════════
#  SECTION TEXT ANALYSES — Plain-English, no jargon
# ══════════════════════════════════════════════════════════════════

def _build_valuation_analysis(fd) -> str:
    """Comprehensive valuation narrative — answers 'Is this stock expensive or cheap?'"""
    pts = []
    s = fd.valuation_score

    # ── HEADLINE VERDICT ──
    if s >= 70:
        pts.append(f"● Valuation Score: {s}/100 — Stock appears UNDERVALUED")
        pts.append("  Multiple metrics suggest you're getting this stock at a bargain price relative to what the company earns and owns.")
    elif s >= 45:
        pts.append(f"● Valuation Score: {s}/100 — Stock appears FAIRLY VALUED")
        pts.append("  The price is neither a steal nor overpriced. Worth buying if profitability and growth are strong.")
    else:
        pts.append(f"● Valuation Score: {s}/100 — Stock appears OVERVALUED")
        pts.append("  The market is demanding a premium for this stock. You're paying more than the fundamentals currently justify.")

    # ── IS THE STOCK EXPENSIVE? — The money answer ──
    cheap_reasons: list[str] = []
    expensive_reasons: list[str] = []
    fair_reasons: list[str] = []          # NEW — capture mid-range signals
    metrics_evaluated = 0

    if fd.pe_ratio is not None:
        metrics_evaluated += 1
        if fd.pe_ratio <= 0:
            expensive_reasons.append("Company is loss-making (no P/E)")
        elif fd.pe_ratio < 12:
            cheap_reasons.append(f"Very low P/E of {fd.pe_ratio:.1f}x (you pay only ₹{fd.pe_ratio:.0f} for every ₹1 of annual profit — real bargain)")
        elif fd.pe_ratio < 18:
            cheap_reasons.append(f"Reasonable P/E of {fd.pe_ratio:.1f}x (you pay ₹{fd.pe_ratio:.0f} for every ₹1 of annual profit — below the Indian market average of ~22)")
        elif fd.pe_ratio < 25:
            fair_reasons.append(f"P/E of {fd.pe_ratio:.1f}x — in line with the market. Neither cheap nor expensive on an earnings basis")
        elif fd.pe_ratio < 40:
            expensive_reasons.append(f"Elevated P/E of {fd.pe_ratio:.1f}x (paying a premium — market expects high growth)")
        else:
            expensive_reasons.append(f"Very high P/E of {fd.pe_ratio:.1f}x (you pay ₹{fd.pe_ratio:.0f} for every ₹1 of annual profit — that's very expensive)")

    if fd.pb_ratio is not None:
        metrics_evaluated += 1
        if fd.pb_ratio < 1.0:
            cheap_reasons.append(f"P/B of {fd.pb_ratio:.2f} — trading BELOW book value (like buying ₹100 of assets for ₹{fd.pb_ratio*100:.0f})")
        elif fd.pb_ratio < 2.5:
            cheap_reasons.append(f"Reasonable P/B of {fd.pb_ratio:.2f} — paying a modest premium over net assets")
        elif fd.pb_ratio < 5:
            fair_reasons.append(f"P/B of {fd.pb_ratio:.1f} — the market values intangibles (brand, moat) at {fd.pb_ratio:.0f}x net assets. Typical for quality companies")
        elif fd.pb_ratio < 8:
            expensive_reasons.append(f"P/B of {fd.pb_ratio:.1f} — paying {fd.pb_ratio:.0f}x the net asset value. Premium pricing")
        else:
            expensive_reasons.append(f"Very high P/B of {fd.pb_ratio:.1f} — paying {fd.pb_ratio:.0f}x net assets. Extremely high expectations baked in")

    if fd.price_to_intrinsic is not None:
        metrics_evaluated += 1
        if fd.price_to_intrinsic < 0.8:
            cheap_reasons.append(f"Price is well BELOW Graham Number (₹{fd.current_price:.0f} vs ₹{fd.graham_number:.0f}) — undervalued by {((1-fd.price_to_intrinsic)*100):.0f}%")
        elif fd.price_to_intrinsic < 1.0:
            cheap_reasons.append(f"Price is below Graham Number (₹{fd.current_price:.0f} vs ₹{fd.graham_number:.0f} intrinsic value)")
        elif fd.price_to_intrinsic < 1.5:
            fair_reasons.append(f"Price is {fd.price_to_intrinsic:.1f}x Graham Number (₹{fd.current_price:.0f} vs ₹{fd.graham_number:.0f}) — modest premium, market pricing in growth")
        elif fd.price_to_intrinsic < 2.5:
            expensive_reasons.append(f"Price is {fd.price_to_intrinsic:.1f}x above Graham Number (₹{fd.current_price:.0f} vs ₹{fd.graham_number:.0f}) — significant premium over intrinsic value")
        else:
            expensive_reasons.append(f"Price is {fd.price_to_intrinsic:.1f}x above Graham Number (₹{fd.current_price:.0f} vs ₹{fd.graham_number:.0f}) — heavy premium")

    if fd.ev_ebitda is not None:
        metrics_evaluated += 1
        if fd.ev_ebitda < 8:
            cheap_reasons.append(f"Low EV/EBITDA of {fd.ev_ebitda:.1f} — cheap on enterprise basis")
        elif fd.ev_ebitda < 14:
            fair_reasons.append(f"EV/EBITDA of {fd.ev_ebitda:.1f} — reasonable enterprise valuation")
        elif fd.ev_ebitda < 22:
            expensive_reasons.append(f"EV/EBITDA of {fd.ev_ebitda:.1f} — on the expensive side for enterprise valuation")
        else:
            expensive_reasons.append(f"High EV/EBITDA of {fd.ev_ebitda:.1f} — expensive on enterprise basis")

    if fd.earning_yield is not None:
        metrics_evaluated += 1
        if fd.earning_yield > 8:
            cheap_reasons.append(f"High earnings yield of {fd.earning_yield:.1f}% — better return than bank FDs (~7%)")
        elif fd.earning_yield >= 5:
            fair_reasons.append(f"Earnings yield of {fd.earning_yield:.1f}% — reasonable, roughly in line with risk-free rate")
        elif fd.earning_yield >= 3:
            expensive_reasons.append(f"Earnings yield of {fd.earning_yield:.1f}% — on the low side, you're paying a lot for each rupee of earnings")
        elif fd.earning_yield > 0:
            expensive_reasons.append(f"Low earnings yield of {fd.earning_yield:.1f}% — worse than bank FDs (~7%)")

    if fd.peg_ratio is not None and fd.peg_ratio > 0:
        metrics_evaluated += 1
        if fd.peg_ratio < 0.8:
            cheap_reasons.append(f"PEG of {fd.peg_ratio:.2f} — stock is clearly underpriced relative to its growth rate (Peter Lynch's golden rule: PEG < 1 = undervalued)")
        elif fd.peg_ratio < 1.2:
            cheap_reasons.append(f"PEG of {fd.peg_ratio:.2f} — roughly fairly priced for its growth. Close to the ideal zone")
        elif fd.peg_ratio < 2.0:
            fair_reasons.append(f"PEG of {fd.peg_ratio:.2f} — slightly rich relative to growth, but not unreasonable")
        else:
            expensive_reasons.append(f"PEG of {fd.peg_ratio:.2f} — growth doesn't justify the premium price")

    # ── Write the verdict using counts + valuation score as tiebreaker ──
    n_cheap = len(cheap_reasons)
    n_exp = len(expensive_reasons)
    n_fair = len(fair_reasons)

    if n_cheap > 0 and n_exp == 0:
        pts.append(f"● 💰 VERDICT: Stock looks CHEAP / UNDERVALUED. {n_cheap} metric(s) lean towards undervaluation:")
        for r in cheap_reasons:
            pts.append(f"  ✅ {r}")
        if n_fair:
            pts.append(f"  ({n_fair} metric(s) in fair-value zone)")
    elif n_exp > 0 and n_cheap == 0:
        pts.append(f"● 🔴 VERDICT: Stock looks EXPENSIVE / OVERVALUED. {n_exp} metric(s) lean towards overvaluation:")
        for r in expensive_reasons:
            pts.append(f"  🚨 {r}")
        if n_fair:
            pts.append(f"  ({n_fair} metric(s) in fair-value zone)")
    elif n_cheap > 0 and n_exp > 0:
        pts.append(f"● ⚖️ MIXED SIGNALS: {n_cheap} metric(s) lean cheap, {n_exp} lean expensive:")
        for r in cheap_reasons:
            pts.append(f"  ✅ Cheap: {r}")
        for r in expensive_reasons:
            pts.append(f"  ⚠️ Expensive: {r}")
        if n_fair:
            for r in fair_reasons:
                pts.append(f"  ➖ Neutral: {r}")
        # Use valuation score as tiebreaker
        if s >= 60:
            pts.append(f"  📊 On balance, the valuation score of {s}/100 tilts towards REASONABLY VALUED given the fundamentals.")
        elif s >= 40:
            pts.append(f"  📊 On balance, the valuation score of {s}/100 suggests FAIR but not cheap pricing.")
        else:
            pts.append(f"  📊 On balance, the valuation score of {s}/100 tilts towards EXPENSIVE relative to fundamentals.")
    elif n_fair > 0:
        # All metrics in the fair-value zone
        pts.append(f"● ⚖️ VERDICT: Stock is FAIRLY VALUED. All {n_fair} metric(s) fall in the mid-range:")
        for r in fair_reasons:
            pts.append(f"  ➖ {r}")
        if s >= 65:
            pts.append(f"  📊 However, the overall valuation score of {s}/100 is solid — not a screaming bargain, but good value for what you get.")
        elif s >= 45:
            pts.append(f"  📊 Valuation score of {s}/100 confirms fair pricing — neither a bargain nor a rip-off.")
        else:
            pts.append(f"  📊 Valuation score of {s}/100 is low — even though individual metrics look middling, the overall picture tilts slightly expensive.")
    elif metrics_evaluated == 0:
        pts.append("● Insufficient valuation data to determine if stock is cheap or expensive.")
    else:
        # Metrics were evaluated but none triggered any list (shouldn't happen with tighter thresholds, but just in case)
        pts.append(f"● ⚖️ VERDICT: Stock appears FAIRLY VALUED based on {metrics_evaluated} metrics analysed. Valuation score: {s}/100.")

    # ── 52-WEEK PRICE CONTEXT ──
    if fd.week_52_pct is not None and fd.week_52_high > 0:
        pct_from_low = 0
        if fd.week_52_low > 0:
            pct_from_low = round(((fd.current_price - fd.week_52_low) / fd.week_52_low) * 100, 1)
        if fd.week_52_pct < -30:
            pts.append(f"● 📉 Price Context: Trading at ₹{fd.current_price:.0f} — down {abs(fd.week_52_pct):.1f}% from 52-week high of ₹{fd.week_52_high:.0f}. If fundamentals are intact, this correction could be a buying opportunity.")
        elif fd.week_52_pct > -5:
            pts.append(f"● 📈 Price Context: Trading at ₹{fd.current_price:.0f} — near 52-week high of ₹{fd.week_52_high:.0f} (only {abs(fd.week_52_pct):.1f}% below). Strong momentum, but less margin of safety.")
        else:
            pts.append(f"● 📊 Price Context: ₹{fd.current_price:.0f} (52W: ₹{fd.week_52_low:.0f} — ₹{fd.week_52_high:.0f}). Currently {abs(fd.week_52_pct):.1f}% below 52-week high, {pct_from_low:.1f}% above 52-week low.")

    # ── INDIVIDUAL METRIC DETAILS (always show) ──
    # Graham Number
    if fd.price_to_intrinsic is not None:
        gn = fd.graham_number
        if fd.price_to_intrinsic < 0.8:
            pts.append(f"● Deep Value — Price/Graham = {fd.price_to_intrinsic:.3f} (Graham No. = ₹{gn:.0f}). Large margin of safety. Benjamin Graham would approve.")
        elif fd.price_to_intrinsic < 1.0:
            pts.append(f"● Below Intrinsic Value — Price/Graham = {fd.price_to_intrinsic:.3f} (₹{gn:.0f}). Trading below calculated fair value.")
        elif fd.price_to_intrinsic < 2.0:
            pts.append(f"● Above Intrinsic Value — Price/Graham = {fd.price_to_intrinsic:.3f} (₹{gn:.0f}). Market has priced in growth expectations.")
        else:
            pts.append(f"● Significantly Above Intrinsic Value — Price/Graham = {fd.price_to_intrinsic:.3f} (₹{gn:.0f}). Heavy premium — needs exceptional growth to justify.")

    # P/E detail
    if fd.pe_ratio is not None:
        if fd.pe_ratio <= 0:
            pts.append(f"● P/E: LOSS-MAKING — Negative P/E means the company lost money over the past 12 months.")
        elif fd.pe_ratio < 12:
            pts.append(f"● P/E of {fd.pe_ratio:.1f}x — Very cheap. You pay ₹{fd.pe_ratio:.1f} for every ₹1 of annual profit. At this rate, your investment pays itself back in ~{fd.pe_ratio:.0f} years from earnings alone.")
        elif fd.pe_ratio < 22:
            pts.append(f"● P/E of {fd.pe_ratio:.1f}x — Reasonable. Fair value for established companies. Your investment would take ~{fd.pe_ratio:.0f} years to 'earn back' from profits.")
        elif fd.pe_ratio < 40:
            pts.append(f"● P/E of {fd.pe_ratio:.1f}x — Moderately expensive. Market expects earnings growth of 15-25% annually to justify this premium.")
        else:
            pts.append(f"● P/E of {fd.pe_ratio:.1f}x — Very expensive. At this level, even a small earnings miss can cause a sharp price correction.")

    # Forward P/E comparison
    if fd.pe_ratio is not None and fd.forward_pe is not None and fd.pe_ratio > 0 and fd.forward_pe > 0:
        if fd.forward_pe < fd.pe_ratio:
            growth_implied = round(((fd.pe_ratio / fd.forward_pe) - 1) * 100, 1)
            pts.append(f"● Forward P/E ({fd.forward_pe:.1f}x) < Trailing P/E ({fd.pe_ratio:.1f}x) — Analysts expect earnings to grow ~{growth_implied:.0f}%. Positive sign.")
        else:
            pts.append(f"● Forward P/E ({fd.forward_pe:.1f}x) > Trailing P/E ({fd.pe_ratio:.1f}x) — Analysts expect earnings to SHRINK. Concerning.")

    # EV/EBITDA
    if fd.ev_ebitda is not None:
        if fd.ev_ebitda < 8:
            pts.append(f"● EV/EBITDA of {fd.ev_ebitda:.1f} — Cheap. Enterprise is valued at only {fd.ev_ebitda:.0f}x its operating cash profits.")
        elif fd.ev_ebitda < 16:
            pts.append(f"● EV/EBITDA of {fd.ev_ebitda:.1f} — Fairly priced on an enterprise basis.")
        else:
            pts.append(f"● EV/EBITDA of {fd.ev_ebitda:.1f} — Expensive. Premium valuation needs strong growth to justify.")

    # Price/FCF
    if fd.price_to_fcf is not None:
        if fd.price_to_fcf < 12:
            pts.append(f"● Price/FCF of {fd.price_to_fcf:.1f} — Cheap on cash-flow basis. Stock generates strong free cash relative to its price.")
        elif fd.price_to_fcf < 25:
            pts.append(f"● Price/FCF of {fd.price_to_fcf:.1f} — Reasonable cash flow valuation.")
        else:
            pts.append(f"● Price/FCF of {fd.price_to_fcf:.1f} — Expensive relative to cash generation.")

    # Earning Yield
    if fd.earning_yield is not None:
        if fd.earning_yield > 8:
            pts.append(f"● Earning Yield of {fd.earning_yield:.1f}% — Better return than most bank FDs (~7%). Attractive entry point.")
        elif fd.earning_yield > 4:
            pts.append(f"● Earning Yield of {fd.earning_yield:.1f}% — Decent. Compare with risk-free rate (RBI bonds ~7%).")
        elif fd.earning_yield > 0:
            pts.append(f"● Earning Yield of {fd.earning_yield:.1f}% — Low. A bank FD may give better returns with zero risk.")

    # Dividend context
    if fd.dividend_yield and fd.dividend_yield > 1:
        pts.append(f"● Dividend Yield: {fd.dividend_yield:.1f}%{' — Good passive income while you wait for price appreciation.' if fd.dividend_yield > 2.5 else ' — Some income, but mainly a growth play.'}")

    return "\n  ".join(pts)


def _build_profitability_analysis(fd) -> str:
    """Comprehensive profitability narrative — answers 'Is this company making money efficiently?'"""
    pts = []
    s = fd.profitability_score

    if s >= 70:
        pts.append(f"● Profitability Score: {s}/100 — HIGHLY PROFITABLE Company")
        pts.append("  This company excels at converting sales into profits. Strong margins indicate pricing power and a competitive moat that protects from competition.")
    elif s >= 45:
        pts.append(f"● Profitability Score: {s}/100 — MODERATELY Profitable")
        pts.append("  Company makes money but faces cost or competitive pressures that squeeze margins. Room for improvement.")
    else:
        pts.append(f"● Profitability Score: {s}/100 — WEAK Profitability")
        pts.append("  Struggles to convert revenue into profits. This could be structural (low-margin business) or temporary (investment phase). Watch for margin improvement before investing.")

    # ── ROE — The most important metric for shareholders ──
    if fd.roe is not None:
        if fd.roe > 25:
            pts.append(f"● Exceptional ROE of {fd.roe:.1f}% — For every ₹100 you invest as a shareholder, the company generates ₹{fd.roe:.0f} in profit. This is World-class. Companies like TCS, HDFC Bank, and ITC have ROEs in this range.")
        elif fd.roe > 15:
            pts.append(f"● Good ROE of {fd.roe:.1f}% — Management is efficiently using shareholder capital. Every ₹100 invested generates ₹{fd.roe:.0f} in profit. Above the 15% benchmark.")
        elif fd.roe > 8:
            pts.append(f"● Average ROE of {fd.roe:.1f}% — Acceptable for capital-heavy sectors like banking, infrastructure, or utilities. Below 15% benchmark though.")
        elif fd.roe >= 0:
            pts.append(f"● Weak ROE of {fd.roe:.1f}% — Poor capital utilisation. Every ₹100 invested generates only ₹{fd.roe:.0f} in profit. Not creating enough value for shareholders.")
        else:
            pts.append(f"● NEGATIVE ROE of {fd.roe:.1f}% — Company is destroying shareholder value. Accumulated losses are eating into equity.")

    # ── ROCE — Return on ALL capital (equity + debt) ──
    if fd.roce is not None:
        if fd.roce > 20:
            pts.append(f"● Excellent ROCE of {fd.roce:.1f}% — Outstanding return on ALL capital employed (both equity and debt). The business is highly efficient.")
        elif fd.roce > 12:
            pts.append(f"● Good ROCE of {fd.roce:.1f}% — Healthy returns on total capital base. Above cost of capital for most companies.")
        elif fd.roce > 0:
            pts.append(f"● Below-average ROCE of {fd.roce:.1f}% — Returns may not justify the risk. Look for catalysts that could improve this.")

    # ── ROA — How efficiently ALL assets are used ──
    if fd.roa is not None:
        if fd.roa > 10:
            pts.append(f"● Strong ROA of {fd.roa:.1f}% — Excellent asset utilisation. Company doesn't need a lot of assets to generate profit (asset-light model).")
        elif fd.roa > 5:
            pts.append(f"● Decent ROA of {fd.roa:.1f}% — Reasonable for most sectors.")
        elif fd.roa >= 0:
            pts.append(f"● Low ROA of {fd.roa:.1f}% — Needs lots of assets to generate modest returns. Typical for banking, real estate, or heavy industry.")

    # ── MARGIN WATERFALL: Gross → Operating → EBITDA → Net ──
    margin_pts = []
    if fd.gross_margin is not None:
        margin_pts.append(f"Gross {fd.gross_margin:.1f}%")
    if fd.operating_margin is not None:
        margin_pts.append(f"Operating {fd.operating_margin:.1f}%")
    if fd.ebitda_margin is not None:
        margin_pts.append(f"EBITDA {fd.ebitda_margin:.1f}%")
    if fd.profit_margin is not None:
        margin_pts.append(f"Net {fd.profit_margin:.1f}%")

    if len(margin_pts) >= 2:
        pts.append(f"● Margin Waterfall: {' → '.join(margin_pts)}")
        pts.append("  (Shows how much of each ₹100 of sales remains as profit at each stage)")

    # ── Net Margin detail ──
    if fd.profit_margin is not None:
        if fd.profit_margin > 20:
            pts.append(f"● High Net Margin of {fd.profit_margin:.1f}% — For every ₹100 of sales, ₹{fd.profit_margin:.0f} is pure profit after ALL expenses. Premium business with pricing power.")
        elif fd.profit_margin > 10:
            pts.append(f"● Healthy Net Margin of {fd.profit_margin:.1f}% — Good for most sectors. Company retains ₹{fd.profit_margin:.0f} from every ₹100 of sales.")
        elif fd.profit_margin > 5:
            pts.append(f"● Thin Net Margin of {fd.profit_margin:.1f}% — Low but may be industry-normal (e.g., trading, retail). Vulnerable if costs rise.")
        elif fd.profit_margin > 0:
            pts.append(f"● Very thin Net Margin of {fd.profit_margin:.1f}% — Razor-thin profits. A small cost increase could wipe out profitability.")
        else:
            pts.append(f"● NEGATIVE Margins of {fd.profit_margin:.1f}% — Company is LOSS-MAKING. Losing ₹{abs(fd.profit_margin):.0f} on every ₹100 of revenue.")

    # ── EBITDA Margin ──
    if fd.ebitda_margin is not None:
        if fd.ebitda_margin > 25:
            pts.append(f"● Strong EBITDA Margin of {fd.ebitda_margin:.1f}% — Excellent operating cash profitability before accounting adjustments.")
        elif fd.ebitda_margin > 15:
            pts.append(f"● Decent EBITDA Margin of {fd.ebitda_margin:.1f}% — Healthy operating business.")
        elif fd.ebitda_margin > 0:
            pts.append(f"● Modest EBITDA Margin of {fd.ebitda_margin:.1f}% — Limited pricing power or high operating costs.")

    # ── Asset Turnover ──
    if fd.asset_turnover is not None:
        if fd.asset_turnover > 1.5:
            pts.append(f"● High Asset Turnover of {fd.asset_turnover:.2f}x — Company generates ₹{fd.asset_turnover:.1f} of revenue for every ₹1 of assets. Very efficient use of resources.")
        elif fd.asset_turnover > 0.5:
            pts.append(f"● Moderate Asset Turnover of {fd.asset_turnover:.2f}x — Normal efficiency for the sector.")
        elif fd.asset_turnover > 0:
            pts.append(f"● Low Asset Turnover of {fd.asset_turnover:.2f}x — Capital-intensive business with heavy asset base.")

    # ── EPS context ──
    if fd.eps_ttm is not None and fd.eps_forward is not None:
        if fd.eps_forward > fd.eps_ttm:
            growth = round(((fd.eps_forward - fd.eps_ttm) / abs(fd.eps_ttm)) * 100, 1) if fd.eps_ttm != 0 else 0
            pts.append(f"● EPS Growth Outlook: Current ₹{fd.eps_ttm:.2f} → Estimated ₹{fd.eps_forward:.2f} (+{growth:.0f}%). Analysts expect profit per share to grow.")
        elif fd.eps_forward < fd.eps_ttm and fd.eps_ttm > 0:
            decline = round(((fd.eps_ttm - fd.eps_forward) / fd.eps_ttm) * 100, 1)
            pts.append(f"● EPS Declining: Current ₹{fd.eps_ttm:.2f} → Estimated ₹{fd.eps_forward:.2f} (−{decline:.0f}%). Analysts expect profit per share to shrink. ⚠️")

    return "\n  ".join(pts)


def _build_growth_analysis(fd) -> str:
    """Comprehensive growth narrative — answers 'Is this company growing?'"""
    pts = []
    s = fd.growth_score

    if s >= 70:
        pts.append(f"● Growth Score: {s}/100 — STRONG Growth Mode")
        pts.append("  Both revenue and earnings are growing well above average. This is a high-growth company — stock prices tend to follow earnings growth over time.")
    elif s >= 45:
        pts.append(f"● Growth Score: {s}/100 — MODERATE Growth")
        pts.append("  Company is growing, but at a modest pace. Not a high-flyer, but steady. Look for catalysts that could accelerate growth.")
    else:
        pts.append(f"● Growth Score: {s}/100 — SLOW or Declining Growth")
        pts.append("  Growth has stalled or reversed. This is a red flag — be careful this isn't a value trap (looks cheap but keeps declining).")

    # ── REVENUE GROWTH — Top line expansion ──
    if fd.revenue_growth is not None:
        if fd.revenue_growth > 20:
            pts.append(f"● Revenue grew {fd.revenue_growth:.1f}% YoY — Exceptional top-line expansion. Company is rapidly capturing market share or entering new markets.")
        elif fd.revenue_growth > 10:
            pts.append(f"● Revenue grew {fd.revenue_growth:.1f}% YoY — Solid double-digit growth. Healthy business momentum.")
        elif fd.revenue_growth > 0:
            pts.append(f"● Revenue grew {fd.revenue_growth:.1f}% YoY — Modest but positive. Better than inflation-adjusted GDP growth (~5-6%).")
        else:
            pts.append(f"● Revenue DECLINED {abs(fd.revenue_growth):.1f}% YoY — Shrinking top line. This is a serious concern — the company is selling less than before. Check if it's industry-wide or company-specific.")
    else:
        pts.append("● Revenue growth data not available — cannot assess top-line momentum.")

    # ── EARNINGS GROWTH — Bottom line (what really drives stock price) ──
    if fd.earnings_growth is not None:
        if fd.earnings_growth > 25:
            pts.append(f"● Earnings grew {fd.earnings_growth:.1f}% YoY — Outstanding profit growth. This is the #1 driver of stock price appreciation.")
        elif fd.earnings_growth > 10:
            pts.append(f"● Earnings grew {fd.earnings_growth:.1f}% YoY — Healthy profit expansion. Indicates operating leverage and efficiency gains.")
        elif fd.earnings_growth > 0:
            pts.append(f"● Earnings grew {fd.earnings_growth:.1f}% YoY — Slow but positive improvement. Need consistency over multiple quarters.")
        else:
            pts.append(f"● Earnings DECLINED {abs(fd.earnings_growth):.1f}% YoY — Profit compression. Check whether it's due to one-time items, higher costs, or structural decline.")
    else:
        pts.append("● Earnings growth data not available — cannot assess profit momentum.")

    # ── REVENUE vs EARNINGS — Quality of growth ──
    if fd.revenue_growth is not None and fd.earnings_growth is not None:
        if fd.earnings_growth > fd.revenue_growth and fd.revenue_growth > 0:
            pts.append(f"● 💡 Earnings growing faster than revenue ({fd.earnings_growth:.1f}% vs {fd.revenue_growth:.1f}%) — Margins are EXPANDING. This is the best kind of growth — higher efficiency.")
        elif fd.revenue_growth > 0 and fd.earnings_growth < 0:
            pts.append(f"● ⚠️ Revenue growing but earnings declining ({fd.revenue_growth:.1f}% vs {fd.earnings_growth:.1f}%) — Margins are COMPRESSING. Company is growing but less profitably. Watch costs.")
        elif fd.revenue_growth < 0 and fd.earnings_growth < 0:
            pts.append(f"● 🚨 Both revenue ({fd.revenue_growth:.1f}%) and earnings ({fd.earnings_growth:.1f}%) declining — Double decline is a serious red flag.")

    # ── FREE CASH FLOW — Real cash, not accounting profit ──
    if fd.free_cash_flow is not None:
        if fd.free_cash_flow > 0:
            pts.append(f"● Positive Free Cash Flow of {_fmt_cr(fd.free_cash_flow)} — This is REAL CASH the company generated after all expenses and capital investments. Can fund dividends, buybacks, or growth without borrowing.")
        else:
            pts.append(f"● Negative Free Cash Flow of {_fmt_cr(fd.free_cash_flow)} — Company is BURNING CASH. May need to borrow or raise equity. Not always bad (could be investing in growth), but needs monitoring.")
            if fd.revenue_growth is not None and fd.revenue_growth > 15:
                pts.append("  Note: High-growth companies often have negative FCF during heavy investment phases — this can be acceptable if revenue growth is strong.")
    else:
        pts.append("● Free cash flow data not available.")

    # ── FORWARD OUTLOOK — What analysts expect ──
    if fd.pe_ratio and fd.forward_pe and fd.pe_ratio > 0 and fd.forward_pe > 0:
        if fd.forward_pe < fd.pe_ratio * 0.85:
            implied_growth = round(((fd.pe_ratio / fd.forward_pe) - 1) * 100, 1)
            pts.append(f"● 📈 Analyst Outlook POSITIVE — Forward P/E ({fd.forward_pe:.1f}x) much lower than trailing ({fd.pe_ratio:.1f}x), implying ~{implied_growth:.0f}% earnings growth expected next year.")
        elif fd.forward_pe > fd.pe_ratio * 1.1:
            pts.append(f"● 📉 Analyst Outlook NEGATIVE — Forward P/E ({fd.forward_pe:.1f}x) higher than trailing ({fd.pe_ratio:.1f}x). Analysts expect earnings to decline next year.")

    # ── TOTAL REVENUE SIZE CONTEXT ──
    if fd.total_revenue is not None:
        pts.append(f"● Total Revenue: {_fmt_cr(fd.total_revenue)} — {'Large-scale operation' if fd.total_revenue > 1e12 else 'Mid-size operation' if fd.total_revenue > 1e10 else 'Small-scale operation'}. Size matters for stability and bargaining power.")

    return "\n  ".join(pts)


def _build_stability_analysis(fd) -> str:
    """Comprehensive stability narrative — answers 'Is this company financially safe?'"""
    pts = []
    s = fd.stability_score

    if s >= 70:
        pts.append(f"● Stability Score: {s}/100 — Financially ROCK-SOLID")
        pts.append("  Low debt, strong cash reserves, and excellent financial health. This company can weather economic storms. Minimal risk of bankruptcy or financial distress.")
    elif s >= 45:
        pts.append(f"● Stability Score: {s}/100 — MODERATE Stability")
        pts.append("  Reasonably stable but has some debt or liquidity concerns that need monitoring. Check quarterly results for trend direction.")
    else:
        pts.append(f"● Stability Score: {s}/100 — Financial STRESS Detected")
        pts.append("  High debt, weak liquidity, or poor financial health indicators. This company could face serious trouble if business slows down or interest rates rise.")

    # ── ALTMAN Z-SCORE — Bankruptcy predictor ──
    if fd.altman_z_score is not None:
        if fd.altman_z_score > 5:
            pts.append(f"● Altman Z-Score: {fd.altman_z_score:.2f} — Extremely healthy. Virtually zero bankruptcy risk. This is fortress-level financial strength.")
        elif fd.altman_z_score > 2.6:
            pts.append(f"● Altman Z-Score: {fd.altman_z_score:.2f} — Safe Zone (above 2.6 threshold). Low probability of financial distress. Company is financially sound.")
        elif fd.altman_z_score > 1.8:
            pts.append(f"● Altman Z-Score: {fd.altman_z_score:.2f} — Grey Zone (1.8–2.6). Some financial stress indicators. Not immediately dangerous but warrants caution. ⚠️")
        elif fd.altman_z_score > 1.1:
            pts.append(f"● Altman Z-Score: {fd.altman_z_score:.2f} — Warning Zone (1.1–1.8). Elevated risk of financial difficulties. Monitor debt repayment capacity closely. ⚠️")
        else:
            pts.append(f"● Altman Z-Score: {fd.altman_z_score:.2f} — DISTRESS Zone (below 1.1). High probability of financial distress or bankruptcy. Avoid unless there's a clear turnaround plan. 🚨")
    else:
        pts.append("● Altman Z-Score: Not computable — insufficient balance sheet data to assess bankruptcy risk.")

    # ── DEBT/EQUITY — Leverage ──
    if fd.debt_to_equity is not None:
        if fd.debt_to_equity < 0.1:
            pts.append(f"● Virtually Debt-Free — D/E of {fd.debt_to_equity:.3f}. Company runs almost entirely on its own money. No interest burden. Maximum financial flexibility.")
        elif fd.debt_to_equity < 0.5:
            pts.append(f"● Low Debt — D/E of {fd.debt_to_equity:.2f}. Conservative balance sheet. Borrows little relative to equity. Safe and self-sufficient.")
        elif fd.debt_to_equity < 1.0:
            pts.append(f"● Moderate Debt — D/E of {fd.debt_to_equity:.2f}. Manageable leverage. Debt is within the safety zone for most industries.")
        elif fd.debt_to_equity < 2.0:
            pts.append(f"● Elevated Debt — D/E of {fd.debt_to_equity:.2f}. Leveraged more than average. Less room for error if profits fall.")
        else:
            pts.append(f"● HIGH Debt Risk — D/E of {fd.debt_to_equity:.2f}. Heavily leveraged. For every ₹1 of equity, the company owes ₹{fd.debt_to_equity:.1f} in debt. Very risky in downturns or rising rate environments.")

    # ── DEBT-TO-ASSETS ──
    if fd.debt_to_assets is not None:
        pct = round(fd.debt_to_assets * 100, 1)
        if pct < 20:
            pts.append(f"● Debt/Assets: {pct:.1f}% — Only {pct:.0f}% of the company's assets are financed by debt. Conservative financing.")
        elif pct < 50:
            pts.append(f"● Debt/Assets: {pct:.1f}% — Moderate. About half of assets are debt-financed.")
        else:
            pts.append(f"● Debt/Assets: {pct:.1f}% — Over half the company's assets are debt-funded. High financial risk.")

    # ── INTEREST COVERAGE ──
    if fd.interest_coverage is not None:
        if fd.interest_coverage > 10:
            pts.append(f"● Interest Coverage: {fd.interest_coverage:.1f}x — Company earns {fd.interest_coverage:.0f} times its interest payments. Zero risk of missing interest payments.")
        elif fd.interest_coverage > 3:
            pts.append(f"● Interest Coverage: {fd.interest_coverage:.1f}x — Comfortable. Earns {fd.interest_coverage:.1f}x its interest obligations.")
        elif fd.interest_coverage > 1.5:
            pts.append(f"● Interest Coverage: {fd.interest_coverage:.1f}x — Tight. Only {fd.interest_coverage:.1f}x earnings vs interest. A profit decline could make debt servicing difficult. ⚠️")
        elif fd.interest_coverage > 0:
            pts.append(f"● Interest Coverage: {fd.interest_coverage:.1f}x — DANGEROUSLY LOW. Barely covering interest payments. One bad quarter and debt obligations may be missed. 🚨")

    # ── CURRENT RATIO — Short-term bill-paying ability ──
    if fd.current_ratio is not None:
        if fd.current_ratio > 2.5:
            pts.append(f"● Strong Liquidity — Current Ratio {fd.current_ratio:.2f}. For every ₹1 due within a year, the company has ₹{fd.current_ratio:.1f} in current assets. Extremely comfortable.")
        elif fd.current_ratio > 1.5:
            pts.append(f"● Good Liquidity — Current Ratio {fd.current_ratio:.2f}. Can comfortably pay all bills due within 1 year. Healthy buffer.")
        elif fd.current_ratio > 1.0:
            pts.append(f"● Adequate Liquidity — Current Ratio {fd.current_ratio:.2f}. Short-term obligations are just about covered. Thin margin.")
        elif fd.current_ratio > 0:
            pts.append(f"● Liquidity Risk — Current Ratio {fd.current_ratio:.2f}. Current liabilities EXCEED current assets. May struggle to pay upcoming bills. ⚠️")

    # ── QUICK RATIO ──
    if fd.quick_ratio is not None:
        if fd.quick_ratio > 1.5:
            pts.append(f"● Quick Ratio: {fd.quick_ratio:.2f} — Can pay short-term debts WITHOUT selling inventory. Very strong position.")
        elif fd.quick_ratio > 1.0:
            pts.append(f"● Quick Ratio: {fd.quick_ratio:.2f} — Adequate. Enough liquid assets to cover immediate obligations.")
        elif fd.quick_ratio > 0:
            pts.append(f"● Quick Ratio: {fd.quick_ratio:.2f} — Below 1.0 means company depends on selling inventory to meet short-term obligations. Risky if demand slows.")

    # ── DEBT/EBITDA — Years to repay all debt ──
    if fd.debt_to_ebitda is not None:
        if fd.debt_to_ebitda < 1.5:
            pts.append(f"● Debt/EBITDA of {fd.debt_to_ebitda:.1f} — Can repay ALL debt in ~{fd.debt_to_ebitda:.1f} years from operating cash. Excellent.")
        elif fd.debt_to_ebitda < 3.0:
            pts.append(f"● Debt/EBITDA of {fd.debt_to_ebitda:.1f} — Would take ~{fd.debt_to_ebitda:.0f} years to repay debt from cash profits. Manageable.")
        elif fd.debt_to_ebitda < 5.0:
            pts.append(f"● Debt/EBITDA of {fd.debt_to_ebitda:.1f} — Would take ~{fd.debt_to_ebitda:.0f} years to repay. Getting stretched.")
        else:
            pts.append(f"● Debt/EBITDA of {fd.debt_to_ebitda:.1f} — Over {fd.debt_to_ebitda:.0f} years to repay. This is a heavy debt burden. Risky. 🚨")

    # ── CASH POSITION ──
    if fd.total_cash is not None and fd.total_debt is not None:
        net_cash = fd.total_cash - fd.total_debt
        if net_cash > 0:
            pts.append(f"● Net Cash Position: {_fmt_cr(net_cash)} — Company has MORE cash than debt. Very healthy. Can survive even without borrowing.")
        else:
            pts.append(f"● Net Debt Position: {_fmt_cr(abs(net_cash))} — Debt exceeds cash reserves. Company needs ongoing cash generation to service debt.")

    return "\n  ".join(pts)


# ══════════════════════════════════════════════════════════════════
#  CONVICTION MESSAGE — The clear picture for stock selection
# ══════════════════════════════════════════════════════════════════

def _conviction_message(fd) -> str:
    """
    Build a clear, actionable investor conviction summary.
    Combines all 4 sections into a plain-English recommendation
    with specific green flags ✅, warnings ⚠️, and red flags 🚨.
    """
    pts = []

    # ── HEADLINE VERDICT ──
    score = fd.fundamental_score
    sig = fd.fundamental_signal or "N/A"
    verdict = fd.fundamental_verdict or ""

    pts.append(f"{'═' * 50}")
    pts.append(f"FUNDAMENTAL VERDICT: {verdict}")
    pts.append(f"Overall Score: {score}/100")
    pts.append(f"{'═' * 50}")
    pts.append("")

    # ── SECTION BREAKDOWN ──
    def _sec(name, sc):
        if sc >= 70:
            return f"✅ {name}: {sc}/100 — Strong"
        elif sc >= 45:
            return f"⚠️  {name}: {sc}/100 — Average"
        else:
            return f"🚨 {name}: {sc}/100 — Weak"

    pts.append(_sec("Valuation", fd.valuation_score))
    pts.append(_sec("Profitability", fd.profitability_score))
    pts.append(_sec("Growth", fd.growth_score))
    pts.append(_sec("Stability", fd.stability_score))
    pts.append("")

    # ── KEY STRENGTHS (Green Flags) ──
    strengths = []
    if fd.roe is not None and fd.roe > 20:
        strengths.append(f"ROE of {fd.roe:.1f}% — Management generates strong return on your money")
    if fd.roce is not None and fd.roce > 20:
        strengths.append(f"ROCE of {fd.roce:.1f}% — Excellent return on ALL capital employed")
    if fd.pe_ratio is not None and 0 < fd.pe_ratio < 15:
        strengths.append(f"Very cheap valuation — P/E of {fd.pe_ratio:.1f}x")
    elif fd.pe_ratio is not None and 0 < fd.pe_ratio < 22:
        strengths.append(f"Fair valuation — P/E of {fd.pe_ratio:.1f}x")
    if fd.price_to_intrinsic is not None and fd.price_to_intrinsic < 1.0:
        strengths.append(f"Below Graham Number ({fd.price_to_intrinsic:.2f}x) — Margin of safety")
    if fd.debt_to_equity is not None and fd.debt_to_equity < 0.3:
        strengths.append(f"Virtually debt-free (D/E = {fd.debt_to_equity:.2f})")
    if fd.altman_z_score is not None and fd.altman_z_score > 3.0:
        strengths.append(f"Excellent financial health (Z-Score = {fd.altman_z_score:.2f})")
    if fd.free_cash_flow is not None and fd.free_cash_flow > 0:
        strengths.append(f"Positive FCF ({_fmt_cr(fd.free_cash_flow)}) — Real cash generation")
    if fd.revenue_growth is not None and fd.revenue_growth > 15:
        strengths.append(f"Strong revenue growth ({fd.revenue_growth:.1f}% YoY)")
    if fd.earnings_growth is not None and fd.earnings_growth > 20:
        strengths.append(f"Excellent earnings growth ({fd.earnings_growth:.1f}% YoY)")
    if fd.profit_margin is not None and fd.profit_margin > 20:
        strengths.append(f"High net margin ({fd.profit_margin:.1f}%) — Premium business")
    if fd.dividend_yield and fd.dividend_yield > 2.5:
        strengths.append(f"Good dividend yield ({fd.dividend_yield:.1f}%) — Income while you wait")
    if fd.current_ratio is not None and fd.current_ratio > 2:
        strengths.append(f"Strong liquidity (CR = {fd.current_ratio:.2f})")

    if strengths:
        pts.append("✅ KEY STRENGTHS:")
        for s in strengths[:6]:
            pts.append(f"  ✅ {s}")
        pts.append("")

    # ── KEY CONCERNS (Warnings & Red Flags) ──
    concerns = []
    if fd.pe_ratio is not None and fd.pe_ratio > 40:
        concerns.append(f"🚨 Very expensive P/E of {fd.pe_ratio:.1f}x — high expectations priced in")
    elif fd.pe_ratio is not None and fd.pe_ratio > 25:
        concerns.append(f"⚠️  Elevated P/E of {fd.pe_ratio:.1f}x — not cheap")
    if fd.pe_ratio is not None and fd.pe_ratio <= 0:
        concerns.append("🚨 Company is LOSS-MAKING — no P/E ratio")
    if fd.debt_to_equity is not None and fd.debt_to_equity > 2.0:
        concerns.append(f"🚨 Heavy debt burden (D/E = {fd.debt_to_equity:.2f})")
    elif fd.debt_to_equity is not None and fd.debt_to_equity > 1.0:
        concerns.append(f"⚠️  Moderate debt level (D/E = {fd.debt_to_equity:.2f})")
    if fd.altman_z_score is not None and fd.altman_z_score < 1.1:
        concerns.append(f"🚨 Altman Z-Score {fd.altman_z_score:.2f} — DISTRESS zone")
    elif fd.altman_z_score is not None and fd.altman_z_score < 2.6:
        concerns.append(f"⚠️  Altman Z-Score {fd.altman_z_score:.2f} — Grey zone")
    if fd.earnings_growth is not None and fd.earnings_growth < -10:
        concerns.append(f"🚨 Earnings declining {abs(fd.earnings_growth):.1f}% YoY")
    if fd.revenue_growth is not None and fd.revenue_growth < 0:
        concerns.append(f"⚠️  Revenue shrinking {abs(fd.revenue_growth):.1f}% YoY")
    if fd.free_cash_flow is not None and fd.free_cash_flow < 0:
        concerns.append(f"⚠️  Negative FCF ({_fmt_cr(fd.free_cash_flow)}) — cash burn")
    if fd.roe is not None and fd.roe < 8:
        concerns.append(f"⚠️  Low ROE of {fd.roe:.1f}% — poor capital utilisation")
    if fd.profit_margin is not None and fd.profit_margin < 5:
        concerns.append(f"⚠️  Thin margins ({fd.profit_margin:.1f}%) — vulnerable to cost pressures")
    if fd.price_to_intrinsic is not None and fd.price_to_intrinsic > 3.0:
        concerns.append(f"⚠️  Trading at {fd.price_to_intrinsic:.1f}x Graham Number — very expensive")

    if concerns:
        pts.append("⚠️  KEY CONCERNS:")
        for c in concerns[:6]:
            pts.append(f"  {c}")
        pts.append("")

    # ── ACTIONABLE RECOMMENDATION ──
    pts.append("─" * 50)
    if sig == "BUY":
        if fd.signal_strength == "STRONG":
            pts.append("📈 RECOMMENDATION: STRONG BUY for long-term portfolio")
            pts.append("  This stock has strong fundamentals across valuation, profitability,")
            pts.append("  growth and stability. Suitable for core portfolio holding.")
        else:
            pts.append("📈 RECOMMENDATION: BUY on dips / at support levels")
            pts.append("  Fundamentals are solid. Combine with technical entry for best results.")
    elif sig == "HOLD":
        pts.append("⏸️  RECOMMENDATION: HOLD if already invested / WAIT if looking to enter")
        pts.append("  Fundamentals are mixed. Some strengths, some concerns.")
        pts.append("  Use Bollinger Band technical signals for timing entry/exit.")
    elif sig == "AVOID":
        if fd.signal_strength == "STRONG":
            pts.append("🛑 RECOMMENDATION: STRONG AVOID — Do not invest")
            pts.append("  Serious fundamental weaknesses detected. Capital at risk.")
        else:
            pts.append("⛔ RECOMMENDATION: AVOID for now — Wait for improvement")
            pts.append("  Fundamental concerns outweigh positives. Re-evaluate after next quarterly results.")
    else:
        pts.append("📊 RECOMMENDATION: Insufficient data for clear recommendation")
        pts.append("  Check latest quarterly results and combine with technical analysis.")

    # 52-week context
    if fd.week_52_pct is not None:
        if fd.week_52_pct < -30:
            pts.append(f"\n📉 Price is {abs(fd.week_52_pct):.1f}% below 52-week high — If fundamentals are sound, this could be a deep-value opportunity.")
        elif fd.week_52_pct > -10:
            pts.append(f"\n📈 Near 52-week high (only {abs(fd.week_52_pct):.1f}% below) — Strong momentum. Buy on pullbacks to BB lower band.")

    return "\n   ".join(pts)


# ══════════════════════════════════════════════════════════════════
#  DESCRIPTIVE SUMMARIES — Shareholding / Dividends / Quarterly
# ══════════════════════════════════════════════════════════════════

def _build_quarterly_analysis(fd) -> str:
    """Build a brief descriptive analysis of recent quarterly results."""
    qrs = fd.quarterly_results
    if not qrs or len(qrs) < 2:
        return ""
    parts = []
    latest = qrs[0]
    prev = qrs[1]

    parts.append(f"Latest Quarter: {latest.period}")

    # Revenue
    if latest.revenue and prev.revenue and prev.revenue > 0:
        rev_chg = (latest.revenue - prev.revenue) / abs(prev.revenue) * 100
        direction = "grew" if rev_chg > 0 else "declined"
        parts.append(f"Revenue {direction} {abs(rev_chg):.1f}% QoQ to {_fmt_cr(latest.revenue)}.")
    elif latest.revenue:
        parts.append(f"Revenue at {_fmt_cr(latest.revenue)}.")

    # Net Income
    if latest.net_income and prev.net_income and prev.net_income > 0:
        ni_chg = (latest.net_income - prev.net_income) / abs(prev.net_income) * 100
        direction = "improved" if ni_chg > 0 else "declined"
        parts.append(f"Net profit {direction} {abs(ni_chg):.1f}% QoQ to {_fmt_cr(latest.net_income)}.")
    elif latest.net_income:
        parts.append(f"Net profit at {_fmt_cr(latest.net_income)}.")

    # EPS trend
    if latest.eps and prev.eps and prev.eps > 0:
        eps_chg = (latest.eps - prev.eps) / abs(prev.eps) * 100
        parts.append(f"EPS moved from ₹{prev.eps:.2f} to ₹{latest.eps:.2f} ({eps_chg:+.1f}%).")

    # YoY comparison if 4+ quarters available
    if len(qrs) >= 4:
        yoy = qrs[3]  # same quarter last year (roughly)
        if latest.revenue and yoy.revenue and yoy.revenue > 0:
            yoy_rev = (latest.revenue - yoy.revenue) / abs(yoy.revenue) * 100
            parts.append(f"YoY revenue growth: {yoy_rev:+.1f}% vs {yoy.period}.")
        if latest.net_income and yoy.net_income and yoy.net_income > 0:
            yoy_ni = (latest.net_income - yoy.net_income) / abs(yoy.net_income) * 100
            parts.append(f"YoY profit growth: {yoy_ni:+.1f}%.")

    # EBITDA margin trend
    if latest.revenue and latest.ebitda and latest.revenue > 0:
        margin = latest.ebitda / latest.revenue * 100
        parts.append(f"EBITDA margin: {margin:.1f}%.")
        if prev.revenue and prev.ebitda and prev.revenue > 0:
            prev_margin = prev.ebitda / prev.revenue * 100
            if margin > prev_margin + 1:
                parts.append("Margin expansion — positive for profitability.")
            elif margin < prev_margin - 1:
                parts.append("Margin compression — watch for cost pressures.")

    # Overall assessment
    improvements = 0
    if latest.revenue and prev.revenue and latest.revenue > prev.revenue:
        improvements += 1
    if latest.net_income and prev.net_income and latest.net_income > prev.net_income:
        improvements += 1
    if latest.eps and prev.eps and latest.eps > prev.eps:
        improvements += 1

    if improvements >= 2:
        parts.append("Overall: Quarterly performance looks healthy with improving trend.")
    elif improvements == 1:
        parts.append("Overall: Mixed quarter — some metrics improved, others softened.")
    else:
        parts.append("Overall: Weak quarter — key metrics declined. Monitor next quarter closely.")

    return " ".join(parts)


def _build_shareholding_verdict(fd) -> str:
    """Build textual analysis of the shareholding pattern."""
    parts = []
    prom = fd.promoter_holding
    inst = fd.fii_holding
    pub = fd.public_holding

    if prom is None and inst is None:
        return "Shareholding data not available."

    # Current holding assessment
    if prom is not None:
        if prom > 70:
            parts.append(f"Promoter holding is very high at {prom:.1f}% — strong founder/family control and alignment with shareholders.")
        elif prom > 50:
            parts.append(f"Promoter holding at {prom:.1f}% — majority ownership by promoters, healthy sign of management confidence.")
        elif prom > 30:
            parts.append(f"Promoter holding at {prom:.1f}% — moderate. Watch for any pledging of shares.")
        else:
            parts.append(f"Promoter holding is low at {prom:.1f}% — could be widely held or promoters may have diluted stake.")

    if inst is not None:
        if inst > 40:
            parts.append(f"Institutional holding is strong at {inst:.1f}% — significant smart money backing.")
        elif inst > 20:
            parts.append(f"Institutional holding at {inst:.1f}% — decent institutional interest.")
        else:
            parts.append(f"Institutional holding at {inst:.1f}% — relatively low institutional interest.")

    if pub is not None:
        if pub > 50:
            parts.append(f"Public holding at {pub:.1f}% is high — stock is widely held by retail investors.")
        elif pub > 25:
            parts.append(f"Public holding at {pub:.1f}% — balanced retail participation.")

    # Shareholding history trend (only if real historical data is available)
    sh = fd.shareholding_history
    if sh and len(sh) >= 2:
        newest = sh[0]
        oldest = sh[-1]
        if newest.promoter is not None and oldest.promoter is not None:
            prom_delta = newest.promoter - oldest.promoter
            if prom_delta > 0.5:
                parts.append(f"Promoter holding INCREASED by {prom_delta:+.1f}pp over recent quarters — bullish signal, management is buying more.")
            elif prom_delta < -0.5:
                parts.append(f"Promoter holding DECREASED by {prom_delta:.1f}pp over recent quarters — could indicate dilution or profit-taking.")
            else:
                parts.append("Promoter holding has remained stable — no significant change.")

        if newest.fii is not None and oldest.fii is not None:
            fii_delta = newest.fii - oldest.fii
            if fii_delta > 0.5:
                parts.append(f"Institutional holding INCREASED by {fii_delta:+.1f}pp — smart money is accumulating.")
            elif fii_delta < -0.5:
                parts.append(f"Institutional holding DECREASED by {fii_delta:.1f}pp — institutions may be reducing exposure.")
            else:
                parts.append("Institutional holding stable.")
    else:
        parts.append("Historical shareholding trend data is not available — only the current snapshot is shown.")

    return " ".join(parts)


def _build_dividend_summary(fd) -> str:
    """Build textual analysis of dividend history."""
    parts = []
    divs = fd.dividend_history

    if not divs:
        if fd.dividend_yield and fd.dividend_yield > 0:
            parts.append(f"Dividend yield: {fd.dividend_yield:.2f}%.")
        else:
            return "No dividend history available. This company may not pay regular dividends."

    if divs:
        total_recent = sum(d.amount for d in divs)
        parts.append(f"The company has paid {len(divs)} dividends in recent history, totalling ₹{total_recent:.2f} per share.")

        # Annual grouping
        year_totals = {}
        for d in divs:
            yr = d.date[:4]
            year_totals[yr] = year_totals.get(yr, 0) + d.amount
        if len(year_totals) >= 2:
            years_sorted = sorted(year_totals.keys())
            latest_yr = years_sorted[-1]
            prev_yr = years_sorted[-2]
            parts.append(f"Total dividend in {latest_yr}: ₹{year_totals[latest_yr]:.2f}, in {prev_yr}: ₹{year_totals[prev_yr]:.2f}.")
            if year_totals[latest_yr] > year_totals[prev_yr]:
                parts.append("Dividend payout is INCREASING year-over-year — positive for income investors.")
            elif year_totals[latest_yr] < year_totals[prev_yr]:
                parts.append("Dividend payout has DECREASED year-over-year.")
            else:
                parts.append("Dividend payout is stable.")

        # Most recent dividend
        last_div = divs[-1]
        parts.append(f"Last dividend: ₹{last_div.amount} on {last_div.date}.")

    if fd.dividend_yield:
        parts.append(f"Current dividend yield: {fd.dividend_yield:.2f}%.")
    if fd.payout_ratio:
        if fd.payout_ratio < 30:
            parts.append(f"Payout ratio of {fd.payout_ratio:.1f}% is conservative — company retains most earnings for growth.")
        elif fd.payout_ratio < 60:
            parts.append(f"Payout ratio of {fd.payout_ratio:.1f}% is balanced — good mix of dividends and reinvestment.")
        else:
            parts.append(f"Payout ratio of {fd.payout_ratio:.1f}% is high — company distributes most earnings as dividends.")

    if fd.ex_dividend_date:
        parts.append(f"Last ex-dividend date: {fd.ex_dividend_date}.")

    return " ".join(parts)


# ══════════════════════════════════════════════════════════════════
#  LEGACY COMPAT
# ══════════════════════════════════════════════════════════════════

def _calc_fundamental_score(fd) -> int:
    return _calc_overall_score(fd)
