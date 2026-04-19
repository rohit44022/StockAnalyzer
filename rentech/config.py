"""
RenTech Config — All parameters for the Indian equity quant engine.
═══════════════════════════════════════════════════════════════════

Every magic number lives here. No hard-coded constants in logic modules.
Grouped by sub-system for clarity.

Indian Market Constants:
  - NSE trading hours: 09:15–15:30 IST (375 minutes)
  - ~248 trading days/year
  - STT: 0.1% on sell (delivery), 0.025% on sell (intraday)
  - Stamp Duty: 0.015% on buy
  - Exchange fees: ~0.00345% both sides
  - Tick size: ₹0.05 for most stocks
  - T+1 settlement since Jan 2023
"""

from __future__ import annotations
from pathlib import Path
import os

# ─── Paths ────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent
CSV_DIR = ROOT_DIR / "stock_csv"
CACHE_DIR = ROOT_DIR / "rentech" / "cache"

# ─── Indian Market Constants ──────────────────────────────────
TRADING_DAYS_PER_YEAR = 248
TICK_SIZE = 0.05  # ₹

# Transaction costs (fraction, not percent)
STT_DELIVERY_SELL   = 0.001      # 0.1% on sell side
STT_INTRADAY_SELL   = 0.00025    # 0.025% on sell side (intraday)
STAMP_DUTY_BUY      = 0.00015    # 0.015% on buy
EXCHANGE_FEES       = 0.0000345  # per side
GST_ON_BROKERAGE    = 0.18       # 18% GST on brokerage
SEBI_TURNOVER_FEE   = 0.000001   # ₹10 per crore

# Total round-trip cost estimate (delivery)
# Buy:  stamp_duty + exchange + brokerage + GST_on_brokerage ≈ 0.05%
# Sell: STT + exchange + brokerage + GST_on_brokerage ≈ 0.15%
# Total ≈ 0.20% round trip
ROUND_TRIP_COST = 0.0020

# ─── Data Requirements ────────────────────────────────────────
MIN_BARS_REQUIRED = 252          # 1 year minimum for any analysis
IDEAL_BARS        = 504          # 2 years for robust statistics
MAX_LOOKBACK      = 756          # 3 years max lookback

# ─── Statistical Models ──────────────────────────────────────
# Hurst Exponent
HURST_LOOKBACK       = 252       # 1 year of data for Hurst calculation
HURST_MEAN_REVERT    = 0.40      # H < 0.40 → strong mean reversion
HURST_RANDOM_WALK_LO = 0.40      # 0.40 ≤ H ≤ 0.60 → random walk zone
HURST_RANDOM_WALK_HI = 0.60
HURST_TRENDING       = 0.60      # H > 0.60 → trending / persistent

# Ornstein-Uhlenbeck (mean reversion speed)
OU_LOOKBACK          = 60        # days for OU parameter estimation
OU_HALF_LIFE_MAX     = 30        # max half-life (days) for tradeable MR
OU_HALF_LIFE_MIN     = 2         # min half-life (days), below = noise

# Z-Score
ZSCORE_LOOKBACK      = 20        # rolling window for z-score
ZSCORE_ENTRY         = -2.0      # enter long when z ≤ this
ZSCORE_EXIT          = 0.0       # exit when z returns to mean
ZSCORE_STOP          = -3.5      # stop-loss when z goes further

# ─── Hidden Markov Model ─────────────────────────────────────
HMM_N_STATES         = 3         # Bull, Bear, Sideways
HMM_LOOKBACK         = 252       # training window (1 year)
HMM_MIN_PROB         = 0.60      # minimum state probability to act on

# ─── Signal Generation ────────────────────────────────────────
# Mean Reversion
MR_RSI_PERIOD         = 2        # RSI(2) — Connors RSI, ultra-short
MR_RSI_OVERSOLD       = 10       # RSI(2) < 10 → deeply oversold
MR_RSI_OVERBOUGHT     = 90       # RSI(2) > 90 → deeply overbought
MR_BB_LOOKBACK        = 20       # Bollinger Band period
MR_BB_STD             = 2.0      # standard deviations
MR_ZSCORE_THRESHOLD   = 2.0      # z-score entry threshold

# Momentum
MOM_FAST_LOOKBACK     = 10       # fast momentum (2 weeks)
MOM_MEDIUM_LOOKBACK   = 21       # medium momentum (1 month)
MOM_SLOW_LOOKBACK     = 63       # slow momentum (3 months)
MOM_CROSS_LOOKBACK    = 126      # cross-sectional momentum (6 months)
MOM_VOLUME_CONFIRM    = 1.5      # volume must be 1.5x avg to confirm

# Microstructure
MICRO_VOLUME_LOOKBACK = 20       # rolling volume average window
MICRO_SPREAD_PROXY_LOOKBACK = 20 # (High-Low)/Close as bid-ask proxy
MICRO_OBV_DIVERGE_BARS = 10      # OBV divergence lookback

# Multi-Factor Weights (ensemble)
FACTOR_WEIGHT_MR       = 0.25    # mean reversion
FACTOR_WEIGHT_MOM      = 0.25    # momentum
FACTOR_WEIGHT_MICRO    = 0.15    # microstructure / volume
FACTOR_WEIGHT_STAT     = 0.20    # statistical (Hurst, OU, cointegration)
FACTOR_WEIGHT_REGIME   = 0.15    # regime alignment bonus

# ─── Risk Management ─────────────────────────────────────────
CAPITAL_DEFAULT       = 1_000_000  # ₹10 Lakh default portfolio
MAX_POSITION_PCT      = 0.10       # max 10% of capital in one stock
MAX_PORTFOLIO_STOCKS  = 20         # max concurrent positions
MAX_SECTOR_PCT        = 0.30       # max 30% in one sector
MAX_DRAWDOWN_HALT     = 0.08       # halt trading if portfolio DD > 8%
VOL_TARGET_ANNUAL     = 0.15       # target 15% annualized vol
KELLY_FRACTION        = 0.25       # quarter-Kelly (conservative)
STOP_ATR_MULTIPLE     = 2.0        # stop loss = entry ± 2×ATR
TARGET_ATR_MULTIPLE   = 3.0        # take profit = entry ± 3×ATR
TRAILING_ATR_MULTIPLE = 1.5        # trailing stop = 1.5×ATR from peak

# ─── Regime Detection ────────────────────────────────────────
REGIME_ADX_PERIOD      = 14
REGIME_ADX_TREND       = 25       # ADX > 25 → trending
REGIME_BBW_SQUEEZE_PCT = 15       # BBW below 15th percentile → squeeze
REGIME_VIX_PANIC       = 25       # India VIX > 25 → panic regime
REGIME_VIX_CALM        = 15       # India VIX < 15 → calm
REGIME_BREADTH_LOOKBACK = 20      # A/D ratio lookback

# ─── Scoring & Output ────────────────────────────────────────
SCORE_SCALE      = 100            # all scores normalized to 0–100
CONFIDENCE_MIN   = 30             # below this → "insufficient confidence"
SIGNAL_STRONG    = 75             # score ≥ 75 → STRONG signal
SIGNAL_MODERATE  = 55             # score ≥ 55 → moderate signal
SIGNAL_WEAK      = 40             # score ≥ 40 → weak signal
