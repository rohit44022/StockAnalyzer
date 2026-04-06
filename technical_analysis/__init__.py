"""
technical_analysis — Comprehensive Technical Analysis Module
============================================================

Based on "Technical Analysis of the Financial Markets"
by John J. Murphy (1999, New York Institute of Finance).

This is a STANDALONE module that does NOT modify any existing code.
It imports data from bb_squeeze.data_loader and computes ALL indicators,
patterns, and signals described in the book.

Chapters covered:
  Ch 1-3  : Philosophy, Dow Theory, Chart Construction     → education.py
  Ch 4    : Trend Concepts (support/resistance, Fibonacci)  → trend_analysis.py
  Ch 5-6  : Chart Patterns (reversal + continuation)        → patterns.py
  Ch 7    : Volume (OBV, A/D, volume analysis)              → indicators.py
  Ch 9    : Moving Averages (SMA, EMA, crossovers)          → indicators.py
  Ch 10   : Oscillators (RSI, MACD, Stochastic, CCI, etc.) → indicators.py
  Ch 12   : Japanese Candlesticks                           → candlesticks.py
  Ch 15   : Trading Systems                                 → signals.py
  Ch 16   : Money Management                                → risk_manager.py
  Ch 19   : Pulling It All Together (consensus engine)      → signals.py
"""

__version__ = "1.0.0"
