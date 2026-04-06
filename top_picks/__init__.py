# ─────────────────────────────────────────────────────────────────
# TOP PICKS ENGINE — Isolated "Best 5 Stocks" Recommendation Module
# ─────────────────────────────────────────────────────────────────
#
# PURPOSE:
#   When you scan stocks using any of the 4 Bollinger Band strategies
#   (Method I Squeeze, Method II Trend Following, Method III Reversals,
#    Method IV Walking the Bands), this module goes BEYOND the basic scan.
#
#   Instead of just showing "here's every stock with a BUY signal",
#   it runs a DEEP multi-layer analysis on every matching stock:
#
#     Layer 1 — BB Strategy Score (how well does the stock fit the BB pattern?)
#     Layer 2 — Murphy Technical Analysis (6-category scoring: trend, momentum,
#               volume, patterns, support/resistance, risk)
#     Layer 3 — Hybrid BB+TA Engine (cross-validates both, checks agreement)
#     Layer 4 — Risk/Reward Assessment (target price vs stop-loss distance)
#     Layer 5 — Signal Agreement (do ALL engines agree on direction?)
#     Layer 6 — Data Quality (is the data fresh and reliable?)
#
#   It then combines all 6 layers into one COMPOSITE SCORE (0-100)
#   and picks the TOP 5 stocks that score the highest.
#
# ISOLATION GUARANTEE:
#   This module ONLY READS from existing analysis engines.
#   It does NOT modify any existing file or function.
#   It creates NO side effects in the existing system.
#
# FILES:
#   config.py  — Weight configuration for the composite scoring formula
#   scorer.py  — The composite scoring logic (combines all 6 layers)
#   engine.py  — The main orchestrator (scan → analyze → rank → pick top 5)
# ─────────────────────────────────────────────────────────────────
