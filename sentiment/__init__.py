"""
sentiment — Stock-Level Social Media & News Sentiment Engine
═════════════════════════════════════════════════════════════

A standalone module that collects news and social media posts about
a specific stock from multiple sources (Google News, Reddit, Indian
financial RSS, NewsAPI) and uses NLP (VADER + financial lexicon) to
determine whether the overall sentiment is BULLISH, BEARISH, or NEUTRAL.

This module does NOT touch the existing analysis pipeline. It is consumed
only by its own Flask blueprint and rendered as a separate dashboard.

Public API:
    analyze_stock_sentiment(ticker: str, force_refresh: bool = False) -> dict
"""

from sentiment.engine import analyze_stock_sentiment, get_source_status

__all__ = ["analyze_stock_sentiment", "get_source_status"]
