"""
Price Action Analysis Engine — Al Brooks Methodology
=====================================================
A production-ready system implementing Al Brooks' "Trading Price Action: TRENDS"
concepts for bar-by-bar analysis of price charts.

Integrates with existing BB Squeeze, Technical Analysis, and Hybrid engines
to provide a comprehensive price action layer.

Modules
-------
config         : Thresholds, constants, scoring weights
bar_types      : Individual bar classification (trend, doji, signal, outside, inside)
patterns       : Multi-bar pattern detection (ii, iii, ioi, H1-4, L1-4, wedges, flags)
trend_analyzer : Always-in direction, spike/channel, two-leg, buying/selling pressure
channels       : Trend lines, channel lines, micro channels
breakouts      : Breakout detection, failed breakouts, breakout pullbacks
signals        : Final signal generation combining all PA components
engine         : Main orchestrator — integrates PA with BB/TA/Hybrid data
scanner        : Full-universe scanner for web interface
"""

from price_action.engine import run_price_action_analysis

__all__ = ["run_price_action_analysis"]
