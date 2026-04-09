"""
market_profile — Dalton Market Profile Analysis (Mind Over Markets)
===================================================================

Computes Market Profile concepts from daily OHLCV data per
James F. Dalton's "Mind Over Markets" (2012 Updated Edition).

All concepts here originate from Dalton's book. The numeric thresholds
(percentile cutoffs, tail %, etc.) are our CALIBRATION of Dalton's
qualitative descriptions — the book gives conceptual rules, we
translate them into code.

[DALTON] tag = direct book concept
[CALIBRATION] tag = our numeric translation of a qualitative concept
"""

from market_profile.engine import run_market_profile_analysis, MarketProfileResult
