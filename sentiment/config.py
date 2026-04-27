"""
sentiment/config.py — Social Media Sentiment Configuration
==========================================================

This module provides stock-level social media & news sentiment analysis
by aggregating from multiple free sources (Google News, Reddit, Indian
financial RSS feeds) plus optional paid APIs (NewsAPI, Twitter/X).

TRUTHFULNESS AUDIT
──────────────────
This is a NEW module — not derived from any book. It is a practical
engineering system that collects public news/social-media posts about
a stock and uses NLP (VADER + financial lexicon) to classify sentiment.

Source Design:
  1. Google News RSS  — free, reliable, excellent Indian stock coverage
  2. Reddit JSON API   — free (public endpoint), global + Indian subreddits
  3. Indian Financial RSS — MoneyControl, ET Markets, LiveMint, Biz Standard
  4. StockTwits         — free API, stock-specific social platform, users tag bullish/bearish
  5. NewsAPI (optional) — free tier 100 req/day, needs NEWSAPI_KEY in .env
  6. Twitter/X (optional) — paid API ($100+/month), needs TWITTER_BEARER_TOKEN

All thresholds are [CALIBRATION] — tuned for Indian stock sentiment.
"""

import os

# ─────────────────────────────────────────────────────────────
#  SOURCE CONFIGURATION
# ─────────────────────────────────────────────────────────────

SOURCES = {
    "google_news": {
        "enabled": True,
        "weight": 0.25,
        "max_results": 20,
        "description": "Google News (free, reliable)",
    },
    "reddit": {
        "enabled": True,
        "weight": 0.20,
        "max_results": 25,
        "description": "Reddit (free JSON API)",
    },
    "rss_india": {
        "enabled": True,
        "weight": 0.20,
        "max_results": 15,
        "description": "Indian Financial News (RSS feeds)",
    },
    "bing_news": {
        "enabled": True,
        "weight": 0.15,
        "max_results": 15,
        "description": "Bing News (free, no API key)",
    },
    "stocktwits": {
        "enabled": True,
        "weight": 0.10,
        "max_results": 30,
        "description": "StockTwits (free, stock-specific social)",
    },
    "twitter": {
        "enabled": bool(os.environ.get("TWITTER_BEARER_TOKEN")),
        "weight": 0.15,
        "max_results": 30,
        "description": "X / Twitter (needs Bearer Token)",
    },
    "newsapi": {
        "enabled": bool(os.environ.get("NEWSAPI_KEY")),
        "weight": 0.15,
        "max_results": 20,
        "description": "NewsAPI (needs API key)",
    },
}

# ─────────────────────────────────────────────────────────────
#  API KEYS (from .env — all optional)
# ─────────────────────────────────────────────────────────────

NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "")
TWITTER_BEARER_TOKEN = os.environ.get("TWITTER_BEARER_TOKEN", "")

# ─────────────────────────────────────────────────────────────
#  CACHE
# ─────────────────────────────────────────────────────────────

CACHE_TTL_SECONDS = 1800   # 30 minutes per ticker

# ─────────────────────────────────────────────────────────────
#  SENTIMENT THRESHOLDS [CALIBRATION]
# ─────────────────────────────────────────────────────────────
# VADER compound score ranges from -1 to +1

STRONG_BULLISH_THRESHOLD = 0.35
BULLISH_THRESHOLD = 0.10
BEARISH_THRESHOLD = -0.10
STRONG_BEARISH_THRESHOLD = -0.35

# Minimum posts for confident sentiment
MIN_POSTS_FOR_CONFIDENCE = 5

# ─────────────────────────────────────────────────────────────
#  REQUEST SETTINGS
# ─────────────────────────────────────────────────────────────

REQUEST_TIMEOUT = 10  # seconds per HTTP request
USER_AGENT = "StockAnalyzer/1.0 (Sentiment Module)"

# ─────────────────────────────────────────────────────────────
#  INDIAN FINANCIAL RSS FEEDS
# ─────────────────────────────────────────────────────────────

INDIAN_RSS_FEEDS = {
    "moneycontrol": "https://www.moneycontrol.com/rss/latestnews.xml",
    "economic_times": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "economic_times_stocks": "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "livemint": "https://www.livemint.com/rss/markets",
    "business_standard": "https://www.business-standard.com/rss/markets-106.rss",
}

# ─────────────────────────────────────────────────────────────
#  REDDIT — Indian stock subreddits
# ─────────────────────────────────────────────────────────────

INDIAN_SUBREDDITS = [
    "IndianStockMarket",
    "IndianStreetBets",
    "DalalStreetBets",
    "IndiaInvestments",
]

# ─────────────────────────────────────────────────────────────
#  TICKER → COMPANY NAME MAPPING (Top NSE stocks)
# ─────────────────────────────────────────────────────────────
# Helps search engines find relevant news when only ticker is given.
# Format: "TICKER.NS" → "Company Name Keywords"

TICKER_TO_NAME = {
    "RELIANCE.NS":   "Reliance Industries",
    "TCS.NS":        "TCS Tata Consultancy Services",
    "HDFCBANK.NS":   "HDFC Bank",
    "INFY.NS":       "Infosys",
    "ICICIBANK.NS":  "ICICI Bank",
    "HINDUNILVR.NS": "Hindustan Unilever HUL",
    "ITC.NS":        "ITC Limited",
    "SBIN.NS":       "State Bank of India SBI",
    "BHARTIARTL.NS": "Bharti Airtel",
    "KOTAKBANK.NS":  "Kotak Mahindra Bank",
    "LT.NS":         "Larsen Toubro L&T",
    "BAJFINANCE.NS": "Bajaj Finance",
    "HCLTECH.NS":    "HCL Technologies",
    "MARUTI.NS":     "Maruti Suzuki",
    "ASIANPAINT.NS": "Asian Paints",
    "AXISBANK.NS":   "Axis Bank",
    "TITAN.NS":      "Titan Company",
    "SUNPHARMA.NS":  "Sun Pharma",
    "TATAMOTORS.NS": "Tata Motors",
    "TATASTEEL.NS":  "Tata Steel",
    "WIPRO.NS":      "Wipro",
    "ONGC.NS":       "ONGC Oil Natural Gas",
    "NTPC.NS":       "NTPC Power",
    "POWERGRID.NS":  "Power Grid Corporation",
    "COALINDIA.NS":  "Coal India",
    "ADANIPORTS.NS": "Adani Ports",
    "ADANIENT.NS":   "Adani Enterprises",
    "TECHM.NS":      "Tech Mahindra",
    "ULTRACEMCO.NS": "UltraTech Cement",
    "NESTLEIND.NS":  "Nestle India",
    "DRREDDY.NS":    "Dr Reddys Laboratories",
    "DIVISLAB.NS":   "Divis Laboratories",
    "CIPLA.NS":      "Cipla",
    "BAJAJ-AUTO.NS": "Bajaj Auto",
    "JSWSTEEL.NS":   "JSW Steel",
    "GRASIM.NS":     "Grasim Industries",
    "BRITANNIA.NS":  "Britannia Industries",
    "HEROMOTOCO.NS": "Hero MotoCorp",
    "INDUSINDBK.NS": "IndusInd Bank",
    "EICHERMOT.NS":  "Eicher Motors Royal Enfield",
    "TATACONSUM.NS": "Tata Consumer Products",
    "APOLLOHOSP.NS": "Apollo Hospitals",
    "SBILIFE.NS":    "SBI Life Insurance",
    "HDFCLIFE.NS":   "HDFC Life Insurance",
    "ZOMATO.NS":     "Zomato",
    "PAYTM.NS":      "Paytm One97",
    "NYKAA.NS":      "Nykaa FSN E-Commerce",
    "DMART.NS":      "Avenue Supermarts DMart",
    "IRCTC.NS":      "IRCTC Indian Railway Catering",
    "HAL.NS":        "HAL Hindustan Aeronautics",
    "BEL.NS":        "Bharat Electronics BEL",
    "BHEL.NS":       "Bharat Heavy Electricals BHEL",
}


def get_company_name(ticker: str) -> str:
    """Get company name for a ticker, or derive from ticker itself."""
    # Try direct lookup
    name = TICKER_TO_NAME.get(ticker)
    if name:
        return name
    # Strip .NS / .BO suffix and return clean ticker
    clean = ticker.replace(".NS", "").replace(".BO", "").replace("_", " ")
    return clean


def get_search_queries(ticker: str) -> list:
    """
    Build search queries for a ticker.
    Returns multiple query variations for better coverage.
    """
    clean_ticker = ticker.replace(".NS", "").replace(".BO", "")
    company_name = get_company_name(ticker)
    queries = []
    # Primary: company name + stock
    queries.append(f"{company_name} stock")
    # Secondary: ticker + NSE
    queries.append(f"{clean_ticker} NSE share")
    # Hashtag style (for social media)
    queries.append(f"#{clean_ticker}")
    return queries


# ─────────────────────────────────────────────────────────────
#  FINANCIAL LEXICON — augments VADER for stock-specific terms
# ─────────────────────────────────────────────────────────────
# VADER is great for general social media but lacks financial terms.
# These additions ensure stock-specific language is scored correctly.
# Values are on VADER's scale: -4 (most negative) to +4 (most positive)

FINANCIAL_LEXICON = {
    # ── Strong Bullish ──
    "bullish": 2.5,
    "breakout": 2.0,
    "outperform": 2.0,
    "upgrade": 2.5,
    "rally": 2.0,
    "surge": 2.5,
    "soaring": 2.5,
    "skyrocket": 3.0,
    "moonshot": 3.0,
    "multibagger": 3.0,
    "all-time high": 2.0,
    "52-week high": 1.5,
    "block deal buy": 2.0,
    "promoter buying": 2.5,
    "fii buying": 2.0,
    "dii buying": 1.5,
    "strong buy": 3.0,
    "accumulate": 1.5,
    "golden cross": 2.0,
    "double bottom": 1.5,
    "inverse head and shoulders": 2.0,

    # ── Mild Bullish ──
    "buy": 1.5,
    "long": 1.0,
    "overweight": 1.5,
    "upside": 1.5,
    "recovery": 1.0,
    "rebound": 1.2,
    "dividend": 1.0,
    "bonus": 1.2,
    "buyback": 1.5,
    "growth": 1.0,
    "expansion": 0.8,
    "beat estimates": 1.5,
    "beat expectations": 1.5,
    "results above": 1.2,
    "strong results": 1.5,
    "record profit": 2.0,
    "record revenue": 1.8,

    # ── Strong Bearish ──
    "bearish": -2.5,
    "crash": -3.0,
    "plunge": -3.0,
    "collapse": -3.0,
    "tank": -2.5,
    "dump": -2.5,
    "fraud": -3.5,
    "scam": -3.5,
    "default": -3.0,
    "bankruptcy": -3.5,
    "insolvency": -3.0,
    "death cross": -2.0,
    "head and shoulders": -1.5,
    "double top": -1.5,
    "52-week low": -1.5,
    "all-time low": -2.0,
    "promoter selling": -2.5,
    "promoter pledge": -2.0,
    "fii selling": -2.0,
    "block deal sell": -2.0,

    # ── Mild Bearish ──
    "sell": -1.5,
    "short": -1.0,
    "underweight": -1.5,
    "downgrade": -2.5,
    "downside": -1.5,
    "correction": -1.0,
    "pullback": -0.8,
    "miss estimates": -1.5,
    "miss expectations": -1.5,
    "below estimates": -1.5,
    "weak results": -1.5,
    "loss": -1.5,
    "debt concern": -1.5,
    "overvalued": -1.2,
    "bubble": -2.0,
    "margin call": -2.0,
    "stop loss": -1.0,
    "target cut": -2.0,
    "target reduced": -1.5,

    # ── Neutral / Context ──
    "hold": 0.0,
    "neutral": 0.0,
    "sideways": -0.3,
    "range-bound": -0.2,
    "consolidation": 0.0,
    "wait": -0.2,
    "volatility": -0.5,
    "uncertainty": -0.8,

    # ── Indian market-specific ──
    "nifty up": 1.5,
    "sensex up": 1.5,
    "nifty down": -1.5,
    "sensex down": -1.5,
    "rbi rate cut": 1.5,
    "rbi rate hike": -1.0,
    "sebi ban": -2.5,
    "sebi warning": -1.5,
    "upper circuit": 2.5,
    "lower circuit": -2.5,
    "operator driven": -2.0,
    "pump and dump": -3.0,
}
