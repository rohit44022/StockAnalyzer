"""
sentiment/engine.py — Social Media Sentiment Orchestrator
=========================================================

Main entry point for stock-level social sentiment analysis.

Pipeline:
  1. Check cache → return if fresh
  2. Collect posts from all enabled sources (Google News, Reddit, RSS, etc.)
  3. Score each post with VADER + financial lexicon
  4. Aggregate into overall sentiment with confidence
  5. Extract key themes and build timeline
  6. Cache result and return

Isolation:
  This module is fully isolated — failures here cannot break analyze,
  scan, top picks, or any other analysis pipeline. If all sources fail,
  we return ok=False and the frontend hides the section gracefully.
"""

from __future__ import annotations
import logging
import re
import time
import threading
from typing import Dict, Any, Optional

from sentiment.config import (
    CACHE_TTL_SECONDS, SOURCES,
    get_company_name, get_search_queries,
)
from sentiment.collectors import collect_all, _dedup_posts, Post
from sentiment.analyzer import (
    score_posts, compute_aggregate_sentiment,
    extract_key_themes, classify_sentiment, sentiment_color,
)

logger = logging.getLogger("sentiment.engine")

# ═══════════════════════════════════════════════════════════════
#  CACHE (in-memory, per-ticker)
# ═══════════════════════════════════════════════════════════════

_cache: Dict[str, Dict[str, Any]] = {}
_cache_lock = threading.Lock()


def _cache_get(ticker: str) -> Optional[Dict]:
    """Get cached result if fresh."""
    with _cache_lock:
        entry = _cache.get(ticker)
        if entry is None:
            return None
        age = time.time() - entry.get("timestamp", 0)
        if age > CACHE_TTL_SECONDS:
            return None
        # Return with cache age
        result = entry["data"].copy()
        result["cache_age_seconds"] = int(age)
        result["from_cache"] = True
        return result


def _cache_set(ticker: str, data: Dict):
    """Store result in cache."""
    with _cache_lock:
        _cache[ticker] = {
            "timestamp": time.time(),
            "data": data,
        }


# ═══════════════════════════════════════════════════════════════
#  INPUT VALIDATION
# ═══════════════════════════════════════════════════════════════

_VALID_TICKER = re.compile(r'^[A-Z0-9][A-Z0-9&\-]{0,19}(\.NS|\.BO)?$', re.IGNORECASE)


def _validate_ticker(raw: str) -> str | None:
    """
    Sanitize and validate ticker input.
    Returns normalized ticker or None if invalid.
    Prevents injection and garbage inputs.
    """
    raw = raw.strip().upper()
    if not raw or len(raw) > 25:
        return None
    # Strip common user input noise
    raw = raw.replace('$', '').replace('#', '').replace('NSE:', '').replace('BSE:', '')
    if not _VALID_TICKER.match(raw):
        return None
    return raw


# ═══════════════════════════════════════════════════════════════
#  TIMELINE GENERATION
# ═══════════════════════════════════════════════════════════════

def _build_timeline(all_posts: list) -> list:
    """
    Build a sentiment timeline from posts sorted by publication time.

    Returns list of {time, score, label, title} for chart rendering.
    """
    from datetime import datetime

    timeline = []
    for post in all_posts:
        pub = post.get("published", "")
        compound = post.get("sentiment", {}).get("compound", 0)
        label = post.get("sentiment", {}).get("label", "NEUTRAL")

        # Try to parse various date formats
        dt = None
        for fmt in (
            "%a, %d %b %Y %H:%M:%S %Z",
            "%a, %d %b %Y %H:%M:%S %z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                dt = datetime.strptime(pub.strip(), fmt)
                break
            except (ValueError, AttributeError):
                continue

        timeline.append({
            "time": dt.isoformat() if dt else pub,
            "time_display": dt.strftime("%b %d, %I:%M %p") if dt else pub[:20],
            "score": round(compound, 3),
            "label": label,
            "title": post.get("title", "")[:80],
        })

    # Sort by time (most recent first)
    timeline.sort(key=lambda x: x["time"], reverse=True)
    return timeline[:50]  # Limit to 50 most recent


# ═══════════════════════════════════════════════════════════════
#  TOP POSTS (most impactful — highest absolute sentiment)
# ═══════════════════════════════════════════════════════════════

def _get_top_posts(all_posts: list, top_n: int = 15) -> list:
    """Get the most sentiment-impactful posts."""
    sorted_posts = sorted(
        all_posts,
        key=lambda p: abs(p.get("sentiment", {}).get("compound", 0)),
        reverse=True,
    )

    top = []
    for p in sorted_posts[:top_n]:
        s = p.get("sentiment", {})
        top.append({
            "title": p.get("title", ""),
            "text": p.get("text", "")[:200],
            "url": p.get("url", ""),
            "published": p.get("published", ""),
            "source_name": p.get("source_name", ""),
            "platform": p.get("platform", ""),
            "compound": s.get("compound", 0),
            "label": s.get("label", "NEUTRAL"),
            "color": s.get("color", "#ffc107"),
            "metadata": p.get("metadata", {}),
        })

    return top


# ═══════════════════════════════════════════════════════════════
#  GENERATE HUMAN-READABLE SUMMARY
# ═══════════════════════════════════════════════════════════════

def _generate_summary(
    ticker: str,
    company_name: str,
    aggregate: Dict,
    source_breakdown: list,
    total_posts: int,
    all_posts: list = None,
    themes: list = None,
) -> str:
    """Generate a rich, in-depth analysis summary with per-source details."""
    label = aggregate.get("overall_label", "NEUTRAL")
    score = aggregate.get("overall_score", 0)
    confidence = aggregate.get("confidence", 0)
    dist = aggregate.get("distribution", {})

    label_text = {
        "STRONG_BULLISH": "strongly bullish",
        "BULLISH": "moderately bullish",
        "NEUTRAL": "neutral / mixed",
        "BEARISH": "moderately bearish",
        "STRONG_BEARISH": "strongly bearish",
    }.get(label, "neutral")

    conf_text = "high" if confidence >= 70 else "moderate" if confidence >= 40 else "low"

    # Count bull/bear/neutral
    bull_count = (dist.get("STRONG_BULLISH", 0) + dist.get("BULLISH", 0))
    bear_count = (dist.get("STRONG_BEARISH", 0) + dist.get("BEARISH", 0))
    neut_count = dist.get("NEUTRAL", 0)

    lines = []

    # ── Overall verdict ──
    lines.append(
        f"Overall social media & news sentiment for {company_name} is "
        f"{label_text} with a composite score of {score:+.2f} "
        f"(confidence: {conf_text} at {confidence}%)."
    )

    # ── Distribution breakdown ──
    if total_posts > 0:
        bull_pct = round(bull_count / total_posts * 100)
        bear_pct = round(bear_count / total_posts * 100)
        neut_pct = round(neut_count / total_posts * 100)
        lines.append(
            f"Out of {total_posts} posts analyzed: "
            f"{bull_count} bullish ({bull_pct}%), "
            f"{neut_count} neutral ({neut_pct}%), "
            f"{bear_count} bearish ({bear_pct}%)."
        )

    # ── Per-source details ──
    active_sources = [s for s in source_breakdown if s.get("count", 0) > 0]
    if active_sources:
        src_details = []
        for s in active_sources:
            src_label = s.get("label", "NEUTRAL").replace("_", " ").title()
            src_score = s.get("avg_score", 0)
            src_details.append(
                f"{s['source_display']} ({s['count']} posts, {src_score:+.2f} → {src_label})"
            )
        lines.append("Source-wise breakdown: " + " | ".join(src_details) + ".")

    # ── Directional insight ──
    if label in ("STRONG_BULLISH", "BULLISH"):
        lines.append(
            "The majority of news articles and social discussion is positive — "
            "market participants appear optimistic about this stock. "
            "Positive catalysts dominate the narrative."
        )
    elif label in ("STRONG_BEARISH", "BEARISH"):
        lines.append(
            "The majority of news articles and social discussion is negative — "
            "market participants express concern about this stock. "
            "Negative catalysts and risk factors dominate the narrative."
        )
    else:
        lines.append(
            "Sentiment is mixed — both positive and negative coverage exists. "
            "No clear directional bias from social media. "
            "Watch for developing trends."
        )

    # ── Source agreement ──
    if len(active_sources) > 1:
        source_labels = [s.get("label", "NEUTRAL") for s in active_sources]
        bullish_sources = sum(1 for l in source_labels if "BULLISH" in l)
        bearish_sources = sum(1 for l in source_labels if "BEARISH" in l)
        if bullish_sources == len(source_labels):
            lines.append("All sources agree: uniformly bullish across platforms.")
        elif bearish_sources == len(source_labels):
            lines.append("All sources agree: uniformly bearish across platforms.")
        elif bullish_sources > 0 and bearish_sources > 0:
            lines.append(
                f"Sources are divided: {bullish_sources} bullish vs "
                f"{bearish_sources} bearish — monitor closely for direction."
            )

    # ── Top themes mention ──
    if themes and len(themes) >= 3:
        top_theme_words = [t["word"] for t in themes[:5]]
        lines.append(
            "Key themes being discussed: " + ", ".join(top_theme_words) + "."
        )

    # ── Strongest signal ──
    if all_posts:
        strongest = max(all_posts, key=lambda p: abs(p.get("sentiment", {}).get("compound", 0)))
        s_score = strongest.get("sentiment", {}).get("compound", 0)
        s_title = strongest.get("title", "")[:80]
        s_src = strongest.get("source_name", "")
        if abs(s_score) > 0.3:
            direction = "bullish" if s_score > 0 else "bearish"
            lines.append(
                f"Strongest signal ({s_score:+.2f}, {direction}): "
                f"\"{s_title}\" — {s_src}."
            )

    return "\n\n".join(lines)


# ═══════════════════════════════════════════════════════════════
#  SOURCE STATUS — which sources are available
# ═══════════════════════════════════════════════════════════════

def get_source_status() -> list:
    """Return status of all configured sources."""
    status = []
    for key, cfg in SOURCES.items():
        status.append({
            "source": key,
            "description": cfg.get("description", key),
            "enabled": cfg.get("enabled", False),
            "weight": cfg.get("weight", 0),
        })
    return status


# ═══════════════════════════════════════════════════════════════
#  MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════

def analyze_stock_sentiment(
    ticker: str,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    Run complete social media sentiment analysis for a stock.

    This is the ONLY function external code needs to call.

    Args:
        ticker: Stock ticker (e.g., "RELIANCE.NS" or "RELIANCE")
        force_refresh: Bypass cache and fetch fresh data

    Returns:
        dict with ok, sentiment data, posts, themes, timeline, etc.
    """
    # Validate & normalize ticker
    validated = _validate_ticker(ticker)
    if validated is None:
        return {
            "ok": False,
            "ticker": ticker,
            "company_name": "",
            "error": f"Invalid ticker: '{ticker}'. Use format like RELIANCE, TCS.NS, or INFY.BO",
            "sources": get_source_status(),
            "total_posts": 0,
            "elapsed_seconds": 0,
        }
    ticker = validated
    if not ticker.endswith((".NS", ".BO")):
        ticker = f"{ticker}.NS"

    # Check cache
    if not force_refresh:
        cached = _cache_get(ticker)
        if cached is not None:
            logger.info("Cache hit for %s (age: %ds)", ticker, cached.get("cache_age_seconds", 0))
            return cached

    company_name = get_company_name(ticker)
    t0 = time.time()

    try:
        # Step 1: Collect from all sources
        posts_by_source = collect_all(ticker)

        # Step 2: Score each post
        scored_by_source = {}
        all_posts = []
        for source_key, posts in posts_by_source.items():
            scored = score_posts(posts)
            scored_by_source[source_key] = scored
            all_posts.extend(scored)

        # Step 2b: Cross-source deduplication
        pre_dedup = len(all_posts)
        all_posts = _dedup_posts(all_posts)
        if pre_dedup != len(all_posts):
            logger.info("Deduped %d → %d posts for %s",
                        pre_dedup, len(all_posts), ticker)

        total_posts = len(all_posts)

        if total_posts == 0:
            result = {
                "ok": False,
                "ticker": ticker,
                "company_name": company_name,
                "error": f"No posts found for {company_name}. Try a different stock or check your internet connection.",
                "sources": get_source_status(),
                "total_posts": 0,
                "elapsed_seconds": round(time.time() - t0, 2),
            }
            _cache_set(ticker, result)
            return result

        # Step 3: Aggregate sentiment
        aggregate = compute_aggregate_sentiment(scored_by_source)

        # Step 4: Extract key themes
        themes = extract_key_themes(all_posts, top_n=20)

        # Step 5: Build timeline
        timeline = _build_timeline(all_posts)

        # Step 6: Get top posts
        top_posts = _get_top_posts(all_posts, top_n=15)

        # Step 7: Generate summary
        summary = _generate_summary(
            ticker, company_name, aggregate,
            aggregate.get("source_breakdown", []),
            total_posts,
            all_posts=all_posts,
            themes=themes,
        )

        elapsed = round(time.time() - t0, 2)

        result = {
            "ok": True,
            "ticker": ticker,
            "company_name": company_name,
            "overall_sentiment": {
                "score": aggregate["overall_score"],
                "label": aggregate["overall_label"],
                "color": aggregate["overall_color"],
                "confidence": aggregate["confidence"],
                "summary": summary,
            },
            "total_posts": total_posts,
            "source_breakdown": aggregate["source_breakdown"],
            "distribution": aggregate["distribution"],
            "top_posts": top_posts,
            "themes": themes,
            "timeline": timeline,
            "sources": get_source_status(),
            "elapsed_seconds": elapsed,
            "from_cache": False,
            "cache_age_seconds": 0,
        }

        _cache_set(ticker, result)
        logger.info(
            "Sentiment analysis for %s: %s (%.2f) — %d posts in %.1fs",
            ticker, aggregate["overall_label"],
            aggregate["overall_score"], total_posts, elapsed,
        )
        return result

    except Exception as e:
        logger.error("Sentiment analysis failed for %s: %s", ticker, e, exc_info=True)
        return {
            "ok": False,
            "ticker": ticker,
            "company_name": company_name,
            "error": f"Sentiment analysis failed: {str(e)}",
            "sources": get_source_status(),
            "total_posts": 0,
            "elapsed_seconds": round(time.time() - t0, 2),
        }
