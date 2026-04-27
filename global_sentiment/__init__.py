"""
global_sentiment — Macro / Inter-Market Sentiment Engine
═════════════════════════════════════════════════════════

A standalone module that reads currency, commodity, bond, and equity-index
data to produce a unified global-sentiment readout — what regime the world
is in, where money is flowing, and what it means for an Indian trader.

This module does NOT touch the existing analysis pipeline. It is consumed
only by its own Flask blueprint and rendered as a separate panel on the
home page.

Public API:
    get_global_sentiment(force_refresh: bool = False) -> dict
"""

from global_sentiment.engine import get_global_sentiment, get_health_summary

__all__ = ["get_global_sentiment", "get_health_summary"]
