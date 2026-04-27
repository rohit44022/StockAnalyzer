"""
sentiment/collectors.py — Multi-Source News & Social Media Collectors
====================================================================

Each collector function returns a list of dicts with a consistent schema:
    {
        "title":       str,    # Post/article title
        "text":        str,    # Body text (cleaned, truncated)
        "url":         str,    # Link to original
        "published":   str,    # ISO-ish timestamp string
        "source_name": str,    # e.g. "Economic Times", "r/IndianStockMarket"
        "platform":    str,    # "google_news" | "reddit" | "rss_india" | "newsapi"
        "metadata":    dict,   # Extra fields (upvotes, comments, etc.)
    }

Isolation: Every collector has its own try/except. If one source fails,
the others continue. The engine aggregates whatever we get.
"""

from __future__ import annotations
import logging
import re
import time
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import quote_plus
from typing import List, Dict, Any

import requests

from sentiment.config import (
    SOURCES, NEWSAPI_KEY, TWITTER_BEARER_TOKEN,
    REQUEST_TIMEOUT, USER_AGENT,
    INDIAN_RSS_FEEDS, INDIAN_SUBREDDITS,
    get_search_queries, get_company_name,
)

logger = logging.getLogger("sentiment.collectors")

# Type alias
Post = Dict[str, Any]


# ═══════════════════════════════════════════════════════════════
#  UTILITIES
# ═══════════════════════════════════════════════════════════════

def _clean_html(html: str) -> str:
    """Strip HTML tags from text."""
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)
    except ImportError:
        import re
        return re.sub(r"<[^>]+>", " ", html).strip()


def _truncate(text: str, max_len: int = 500) -> str:
    """Truncate text to max_len chars."""
    if not text:
        return ""
    return text[:max_len] + ("..." if len(text) > max_len else "")


def _safe_get(url: str, headers: dict = None, params: dict = None,
              timeout: int = REQUEST_TIMEOUT,
              retries: int = 2) -> requests.Response | None:
    """HTTP GET with timeout, retry on transient failures, and error handling."""
    hdrs = {"User-Agent": USER_AGENT}
    if headers:
        hdrs.update(headers)
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, headers=hdrs, params=params, timeout=timeout)
            if resp.status_code == 200:
                return resp
            # Retry on 429 (rate limit) and 5xx (server error)
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                wait = (attempt + 1) * 1.5
                logger.info("HTTP %d from %s — retry %d in %.1fs",
                            resp.status_code, url[:60], attempt + 1, wait)
                time.sleep(wait)
                continue
            logger.warning("HTTP %d from %s", resp.status_code, url[:80])
            return None
        except requests.RequestException as e:
            if attempt < retries:
                time.sleep((attempt + 1) * 1.0)
                continue
            logger.warning("Request failed for %s: %s", url[:80], e)
            return None
    return None


def _dedup_posts(posts: List[Post]) -> List[Post]:
    """
    Remove duplicate posts based on title similarity.
    Uses normalized title hash to catch near-duplicates from different sources.
    """
    seen = set()
    unique = []
    for p in posts:
        # Normalize: lowercase, strip punctuation, collapse whitespace
        title = p.get("title", "").lower().strip()
        # Simple hash on first 80 chars of normalized title
        key = hashlib.md5(title[:80].encode()).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    return unique


# ═══════════════════════════════════════════════════════════════
#  1. GOOGLE NEWS RSS (free, no API key)
# ═══════════════════════════════════════════════════════════════

def collect_google_news(ticker: str, max_results: int = 20) -> List[Post]:
    """
    Collect news articles from Google News RSS.

    Google News RSS is free, reliable, and provides excellent
    coverage for Indian stocks. We search with the company name
    and ticker for maximum relevance.
    """
    try:
        import feedparser
    except ImportError:
        logger.error("feedparser not installed — run: pip install feedparser")
        return []

    posts = []
    queries = get_search_queries(ticker)
    seen_titles = set()

    # Search ALL query variations for broad coverage (critical for smaller stocks)
    for query in queries:
        if len(posts) >= max_results:
            break

        url = (
            f"https://news.google.com/rss/search?"
            f"q={quote_plus(query)}&hl=en-IN&gl=IN&ceid=IN:en"
        )

        try:
            resp = _safe_get(url, retries=1)
            if resp is None:
                continue
            feed = feedparser.parse(resp.text)

            for entry in feed.entries:
                if len(posts) >= max_results:
                    break
                title = entry.get("title", "").strip()
                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)

                # Extract source from title (Google News format: "Title - Source")
                source_name = "Google News"
                if " - " in title:
                    parts = title.rsplit(" - ", 1)
                    if len(parts) == 2 and len(parts[1]) < 40:
                        source_name = parts[1].strip()
                        title = parts[0].strip()

                desc = _clean_html(entry.get("description", ""))
                published = entry.get("published", "")

                posts.append({
                    "title": title,
                    "text": _truncate(desc),
                    "url": entry.get("link", ""),
                    "published": published,
                    "source_name": source_name,
                    "platform": "google_news",
                    "metadata": {},
                })

        except Exception as e:
            logger.warning("Google News query '%s' failed: %s", query, e)

    return posts


# ═══════════════════════════════════════════════════════════════
#  2. REDDIT JSON API (free, no auth for public search)
# ═══════════════════════════════════════════════════════════════

def _is_relevant(text: str, ticker: str, company_name: str) -> bool:
    """
    Strict relevance check — does this post actually mention the stock?

    Prevents garbage results like 'ISP in Lusaka' or 'Time Off Schedule'
    from polluting sentiment when searching for 'Reliance Industries'.
    """
    text_lower = text.lower()
    clean_ticker = ticker.replace(".NS", "").replace(".BO", "").lower()

    # Must match ticker OR first word of company name (exact word boundary)
    # Ticker match (e.g., "reliance" as a whole word)
    if re.search(r'\b' + re.escape(clean_ticker) + r'\b', text_lower):
        return True
    # Company name first meaningful word (e.g., "reliance", "infosys", "tata")
    first_word = company_name.split()[0].lower() if company_name else ""
    if first_word and len(first_word) > 3:
        if re.search(r'\b' + re.escape(first_word) + r'\b', text_lower):
            return True
    return False


def collect_reddit(ticker: str, max_results: int = 25) -> List[Post]:
    """
    Collect posts from Reddit via public JSON API.

    Strategy: Search Indian stock subreddits FIRST (high signal),
    then fall back to global Reddit with strict relevance filtering.
    Uses quoted exact-match queries to avoid garbage results.
    """
    posts = []
    clean_ticker = ticker.replace(".NS", "").replace(".BO", "")
    company_name = get_company_name(ticker)
    seen = set()

    def _parse_reddit_posts(data, source_label="reddit"):
        """Parse Reddit API response into post dicts."""
        parsed = []
        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            title = d.get("title", "").strip()
            if not title or title in seen:
                continue
            selftext = d.get("selftext", "")
            combined_text = f"{title} {selftext}"

            # STRICT relevance check — reject posts that don't mention the stock
            if not _is_relevant(combined_text, ticker, company_name):
                continue

            seen.add(title)
            created_utc = d.get("created_utc", 0)
            try:
                pub_dt = datetime.fromtimestamp(created_utc, tz=timezone.utc)
                published = pub_dt.isoformat()
            except Exception:
                published = ""

            subreddit = d.get("subreddit", "unknown")
            parsed.append({
                "title": title,
                "text": _truncate(selftext),
                "url": f"https://reddit.com{d.get('permalink', '')}",
                "published": published,
                "source_name": f"r/{subreddit}",
                "platform": "reddit",
                "metadata": {
                    "upvotes": d.get("ups", 0),
                    "comments": d.get("num_comments", 0),
                    "subreddit": subreddit,
                    "score": d.get("score", 0),
                },
            })
        return parsed

    # Strategy 1: Search Indian stock subreddits (high relevance)
    for subreddit in INDIAN_SUBREDDITS:
        if len(posts) >= max_results:
            break
        url = f"https://www.reddit.com/r/{subreddit}/search.json"
        params = {
            "q": clean_ticker,
            "restrict_sr": "on",  # Search within subreddit only
            "sort": "new",
            "limit": 15,
            "t": "month",
        }
        resp = _safe_get(url, params=params)
        if resp:
            try:
                posts.extend(_parse_reddit_posts(resp.json()))
            except Exception as e:
                logger.warning("Reddit r/%s search failed: %s", subreddit, e)

    # Strategy 2: Global Reddit search with EXACT match (quoted query)
    if len(posts) < max_results:
        url = "https://www.reddit.com/search.json"
        # Use quoted query for exact match — prevents garbage
        query = f'"{clean_ticker}" stock'
        params = {
            "q": query,
            "sort": "relevance",
            "limit": min(max_results, 25),
            "t": "month",
        }
        resp = _safe_get(url, params=params)
        if resp:
            try:
                posts.extend(_parse_reddit_posts(resp.json()))
            except Exception as e:
                logger.warning("Reddit global search failed: %s", e)

    return posts[:max_results]


# ═══════════════════════════════════════════════════════════════
#  3. INDIAN FINANCIAL RSS FEEDS (free)
# ═══════════════════════════════════════════════════════════════

def collect_indian_rss(ticker: str, max_results: int = 15) -> List[Post]:
    """
    Collect articles from Indian financial news RSS feeds.

    These are general market feeds — we filter for articles that
    mention the specific stock ticker or company name.
    """
    try:
        import feedparser
    except ImportError:
        logger.error("feedparser not installed — run: pip install feedparser")
        return []

    clean_ticker = ticker.replace(".NS", "").replace(".BO", "")
    company_name = get_company_name(ticker)

    posts = []
    seen = set()

    for feed_name, feed_url in INDIAN_RSS_FEEDS.items():
        try:
            # Use requests (not feedparser URL fetch) to avoid SSL cert issues
            resp = _safe_get(feed_url, retries=0, timeout=8)
            if resp is None:
                continue
            feed = feedparser.parse(resp.text)

            for entry in feed.entries:
                title = entry.get("title", "").strip()
                desc = _clean_html(entry.get("description", entry.get("summary", "")))
                combined = f"{title} {desc}"

                # STRICT relevance check — must mention ticker/company name as a word
                if not _is_relevant(combined, ticker, company_name):
                    continue

                if title in seen:
                    continue
                seen.add(title)

                published = entry.get("published", entry.get("updated", ""))

                posts.append({
                    "title": title,
                    "text": _truncate(desc),
                    "url": entry.get("link", ""),
                    "published": published,
                    "source_name": feed_name.replace("_", " ").title(),
                    "platform": "rss_india",
                    "metadata": {"feed": feed_name},
                })

                if len(posts) >= max_results:
                    return posts

        except Exception as e:
            logger.warning("RSS feed %s failed: %s", feed_name, e)
            continue

    return posts[:max_results]


# ═══════════════════════════════════════════════════════════════
#  4. NEWSAPI (optional — needs NEWSAPI_KEY in .env)
# ═══════════════════════════════════════════════════════════════

def collect_newsapi(ticker: str, max_results: int = 20) -> List[Post]:
    """
    Collect articles from NewsAPI.org.

    Requires NEWSAPI_KEY environment variable.
    Free tier: 100 requests/day, articles up to 1 month old.
    """
    if not NEWSAPI_KEY:
        return []

    clean_ticker = ticker.replace(".NS", "").replace(".BO", "")
    company_name = get_company_name(ticker)
    query = f'"{company_name}" OR "{clean_ticker}"'

    url = "https://newsapi.org/v2/everything"
    params = {
        "q": query,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": max_results,
        "apiKey": NEWSAPI_KEY,
    }

    resp = _safe_get(url, params=params)
    if resp is None:
        return []

    posts = []
    try:
        data = resp.json()
        for article in data.get("articles", []):
            title = (article.get("title") or "").strip()
            if not title or title == "[Removed]":
                continue

            posts.append({
                "title": title,
                "text": _truncate(article.get("description") or ""),
                "url": article.get("url", ""),
                "published": article.get("publishedAt", ""),
                "source_name": article.get("source", {}).get("name", "NewsAPI"),
                "platform": "newsapi",
                "metadata": {
                    "author": article.get("author"),
                    "image": article.get("urlToImage"),
                },
            })

    except Exception as e:
        logger.warning("NewsAPI collection failed: %s", e)

    return posts


# ═══════════════════════════════════════════════════════════════
#  5. STOCKTWITS (free — stock-specific social media)
# ═══════════════════════════════════════════════════════════════

def collect_stocktwits(ticker: str, max_results: int = 30) -> List[Post]:
    """
    Collect messages from StockTwits — the stock-specific social platform.

    StockTwits is like Twitter but exclusively for stock traders.
    Users can tag their messages as “Bullish” or “Bearish”, giving us
    pre-labeled sentiment data directly from the trading community.

    API: https://api.stocktwits.com/api/2/streams/symbol/{SYMBOL}.json
    Free, no API key needed for basic access.
    """
    clean_ticker = ticker.replace(".NS", "").replace(".BO", "")

    # StockTwits symbol format for Indian stocks: TICKER or TICKER-IN
    symbols_to_try = [clean_ticker]

    posts = []
    for symbol in symbols_to_try:
        url = f"https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
        resp = _safe_get(url, retries=0)  # No retry — 403 means blocked
        if resp is None:
            continue

        try:
            data = resp.json()
            if data.get("response", {}).get("status") != 200:
                continue

            for msg in data.get("messages", [])[:max_results]:
                body = msg.get("body", "").strip()
                if not body:
                    continue

                # StockTwits provides user-tagged sentiment
                entities = msg.get("entities", {}) or {}
                st_sentiment = entities.get("sentiment", {}) or {}
                user_sentiment = st_sentiment.get("basic", "")  # "Bullish" / "Bearish" / ""

                created = msg.get("created_at", "")
                user = msg.get("user", {}) or {}

                posts.append({
                    "title": body[:120],
                    "text": _truncate(body),
                    "url": f"https://stocktwits.com/message/{msg.get('id', '')}",
                    "published": created,
                    "source_name": f"@{user.get('username', 'anonymous')}",
                    "platform": "stocktwits",
                    "metadata": {
                        "user_sentiment": user_sentiment,  # Pre-labeled by user!
                        "likes": msg.get("likes", {}).get("total", 0) if msg.get("likes") else 0,
                        "username": user.get("username", ""),
                        "followers": user.get("followers", 0),
                    },
                })

            if posts:
                break  # Got results, no need to try alternate symbols

        except Exception as e:
            logger.warning("StockTwits collection failed for %s: %s", symbol, e)

    return posts[:max_results]


# ═══════════════════════════════════════════════════════════════
#  6. TWITTER / X.COM (optional — needs TWITTER_BEARER_TOKEN)
# ═══════════════════════════════════════════════════════════════

def collect_twitter(ticker: str, max_results: int = 30) -> List[Post]:
    """
    Collect recent tweets about a stock from X.com / Twitter.

    Requires TWITTER_BEARER_TOKEN in .env (paid API, $100+/month).
    Uses Twitter API v2 recent search endpoint.
    Searches for cashtag ($TICKER), hashtag (#TICKER), and company name.
    """
    if not TWITTER_BEARER_TOKEN:
        return []

    clean_ticker = ticker.replace(".NS", "").replace(".BO", "")
    company_name = get_company_name(ticker)

    # Build Twitter search query: cashtag OR hashtag OR company name
    query = f"${clean_ticker} OR #{clean_ticker} OR \"{company_name}\" -is:retweet lang:en"

    url = "https://api.twitter.com/2/tweets/search/recent"
    headers = {"Authorization": f"Bearer {TWITTER_BEARER_TOKEN}"}
    params = {
        "query": query,
        "max_results": min(max_results, 100),  # API max is 100
        "tweet.fields": "created_at,public_metrics,author_id,text",
        "sort_order": "recency",
    }

    resp = _safe_get(url, headers=headers, params=params)
    if resp is None:
        return []

    posts = []
    try:
        data = resp.json()

        if "errors" in data:
            logger.warning("Twitter API errors: %s", data["errors"])
            return []

        for tweet in data.get("data", []):
            text = tweet.get("text", "").strip()
            if not text:
                continue

            metrics = tweet.get("public_metrics", {})
            created = tweet.get("created_at", "")

            posts.append({
                "title": text[:120],
                "text": _truncate(text),
                "url": f"https://x.com/i/status/{tweet.get('id', '')}",
                "published": created,
                "source_name": "X.com",
                "platform": "twitter",
                "metadata": {
                    "likes": metrics.get("like_count", 0),
                    "retweets": metrics.get("retweet_count", 0),
                    "replies": metrics.get("reply_count", 0),
                    "impressions": metrics.get("impression_count", 0),
                },
            })

    except Exception as e:
        logger.warning("Twitter collection failed: %s", e)

    return posts[:max_results]


# ═══════════════════════════════════════════════════════════════
#  7. BING NEWS RSS (free, no API key, good Indian stock coverage)
# ═══════════════════════════════════════════════════════════════

def collect_bing_news(ticker: str, max_results: int = 15) -> List[Post]:
    """
    Collect news from Bing News RSS — free, no API key.

    Bing News RSS provides good coverage for Indian stocks and
    acts as a complement to Google News with different article ranking.
    """
    try:
        import feedparser
    except ImportError:
        logger.error("feedparser not installed — run: pip install feedparser")
        return []

    clean_ticker = ticker.replace(".NS", "").replace(".BO", "")
    company_name = get_company_name(ticker)
    query = f"{company_name} stock NSE"

    url = f"https://www.bing.com/news/search?q={quote_plus(query)}&format=rss"

    posts = []
    try:
        resp = _safe_get(url, retries=1)
        if resp is None:
            return posts
        feed = feedparser.parse(resp.text)
        seen = set()

        for entry in feed.entries:
            if len(posts) >= max_results:
                break
            title = entry.get("title", "").strip()
            if not title or title in seen:
                continue

            # Relevance check
            combined = f"{title} {entry.get('description', '')}"
            if not _is_relevant(combined, ticker, company_name):
                continue

            seen.add(title)
            source_name = "Bing News"
            if " - " in title:
                parts = title.rsplit(" - ", 1)
                if len(parts) == 2 and len(parts[1]) < 40:
                    source_name = parts[1].strip()
                    title = parts[0].strip()

            desc = _clean_html(entry.get("description", ""))
            published = entry.get("published", "")

            posts.append({
                "title": title,
                "text": _truncate(desc),
                "url": entry.get("link", ""),
                "published": published,
                "source_name": source_name,
                "platform": "bing_news",
                "metadata": {},
            })

    except Exception as e:
        logger.warning("Bing News collection failed: %s", e)

    return posts


# ═══════════════════════════════════════════════════════════════
#  MASTER COLLECTOR — runs all enabled sources
# ═══════════════════════════════════════════════════════════════

_COLLECTOR_MAP = {
    "google_news": collect_google_news,
    "reddit":      collect_reddit,
    "rss_india":   collect_indian_rss,
    "bing_news":   collect_bing_news,
    "stocktwits":  collect_stocktwits,
    "twitter":     collect_twitter,
    "newsapi":     collect_newsapi,
}


def collect_all(ticker: str) -> Dict[str, List[Post]]:
    """
    Collect posts from all enabled sources for a given ticker — IN PARALLEL.

    Uses ThreadPoolExecutor to fetch all sources simultaneously, cutting
    wall-clock time from O(n * timeout) to O(max_single_timeout).
    Each source is independently isolated — one failure cannot affect others.

    Returns:
        dict mapping source name → list of deduplicated posts.
        e.g. {"google_news": [...], "reddit": [...], ...}
    """
    tasks = {}
    for source_key, config in SOURCES.items():
        if not config.get("enabled"):
            continue
        collector_fn = _COLLECTOR_MAP.get(source_key)
        if not collector_fn:
            continue
        tasks[source_key] = (collector_fn, config.get("max_results", 20))

    if not tasks:
        return {}

    results = {}
    t0_all = time.time()

    def _run_collector(key, fn, max_res):
        t0 = time.time()
        try:
            posts = fn(ticker, max_results=max_res)
            elapsed = time.time() - t0
            logger.info("Collected %d posts from %s for %s (%.1fs)",
                        len(posts), key, ticker, elapsed)
            return key, posts
        except Exception as e:
            logger.error("Collector %s crashed for %s: %s", key, ticker, e)
            return key, []

    with ThreadPoolExecutor(max_workers=len(tasks), thread_name_prefix="sent") as pool:
        futures = {
            pool.submit(_run_collector, key, fn, max_res): key
            for key, (fn, max_res) in tasks.items()
        }
        for future in as_completed(futures):
            key, posts = future.result()
            # Deduplicate within each source
            results[key] = _dedup_posts(posts)

    logger.info("All collectors done for %s in %.1fs (%d sources)",
                ticker, time.time() - t0_all, len(results))
    return results
