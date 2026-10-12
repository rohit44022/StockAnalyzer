"""
Configuration file for the Bollinger Band Squeeze Strategy Software.
All parameters are based on John Bollinger's book: Bollinger on Bollinger Bands
Chapters 15 & 16 — Method I: Volatility Breakout
"""

import os

# ─────────────────────────────────────────────────────────────────
#  PATHS
# ─────────────────────────────────────────────────────────────────
BASE_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# In packaged desktop app, writable data lives in ~/Documents/StockAnalyzer
DATA_DIR  = os.environ.get("STOCK_APP_DATA", BASE_DIR)
CSV_DIR   = os.path.join(DATA_DIR, "stock_csv")
CACHE_DIR = os.path.join(DATA_DIR, "bb_squeeze", "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────────
#  BOLLINGER BANDS PARAMETERS (Chapters 15 & 16)
# ─────────────────────────────────────────────────────────────────
BB_PERIOD   = 20      # 20-day intermediate-term period
BB_STD_DEV  = 2.0     # 2 standard deviations → covers 88-89% of price data
BB_MA_TYPE  = "SMA"   # Simple Moving Average — internally consistent

# ─────────────────────────────────────────────────────────────────
#  BANDWIDTH (BBW) — SQUEEZE TRIGGER
# ─────────────────────────────────────────────────────────────────
BBW_PERIOD   = 20
BBW_STD_DEV  = 2.0
BBW_TRIGGER  = 0.08   # 6-month low trigger — squeeze is SET when BBW ≤ 0.08
BBW_LOOKBACK = 126    # ~6 months of trading days

# ─────────────────────────────────────────────────────────────────
#  %b (PERCENT B) LEVELS
# ─────────────────────────────────────────────────────────────────
PERCENT_B_UPPER = 0.8   # Price near top of band (bullish zone)
PERCENT_B_MID   = 0.5   # Midline — above = lean bullish, below = lean bearish
PERCENT_B_LOWER = 0.2   # Price near bottom of band (bearish zone)

# ─────────────────────────────────────────────────────────────────
#  PARABOLIC SAR PARAMETERS
# ─────────────────────────────────────────────────────────────────
SAR_INIT_AF  = 0.02   # Initial acceleration factor
SAR_STEP_AF  = 0.02   # Step / increment
SAR_MAX_AF   = 0.20   # Maximum acceleration factor

# ─────────────────────────────────────────────────────────────────
#  VOLUME PARAMETERS
# ─────────────────────────────────────────────────────────────────
VOLUME_SMA_PERIOD = 50  # 50-period SMA on volume (yellow line reference)
MIN_VOLUME        = 200000  # Minimum 2 lakh shares/day for mid-cap+ stocks

# ─────────────────────────────────────────────────────────────────
#  CMF — CHAIKIN MONEY FLOW
# ─────────────────────────────────────────────────────────────────
CMF_PERIOD        = 20
CMF_UPPER_LINE    = +0.10   # Strong accumulation
CMF_LOWER_LINE    = -0.10   # Strong distribution

# ─────────────────────────────────────────────────────────────────
#  MFI — MONEY FLOW INDEX
# ─────────────────────────────────────────────────────────────────
MFI_PERIOD      = 10    # Half of BB period (as per book)
MFI_OVERBOUGHT  = 80    # NOT 70 — as specified in the strategy
MFI_OVERSOLD    = 20    # NOT 30 — as specified in the strategy
MFI_MID         = 50    # Breakout fuel check midline

# ─────────────────────────────────────────────────────────────────
#  INTRADAY INTENSITY (II) — Book Ch.18 Table 18.3
#  II = (2*Close - High - Low) / (High - Low) * Volume
#  II% = 21-day normalised oscillator (Table 18.4)
# ─────────────────────────────────────────────────────────────────
II_NORM_PERIOD = 21    # Normalisation period for II% oscillator

# ─────────────────────────────────────────────────────────────────
#  ACCUMULATION DISTRIBUTION (AD) — Book Ch.18 Table 18.3
#  AD = (Close - Open) / (High - Low) * Volume
#  AD% = 21-day normalised oscillator (Table 18.4)
# ─────────────────────────────────────────────────────────────────
AD_NORM_PERIOD = 21    # Normalisation period for AD% oscillator

# ─────────────────────────────────────────────────────────────────
#  VOLUME-WEIGHTED MACD (VWMACD) — Book Ch.18 Table 18.3
#  VWMACD = 12-period VW avg − 26-period VW avg
#  Signal = 9-period EMA of VWMACD
# ─────────────────────────────────────────────────────────────────
VWMACD_FAST   = 12
VWMACD_SLOW   = 26
VWMACD_SIGNAL = 9

# ─────────────────────────────────────────────────────────────────
#  EXPANSION DETECTION — Book Ch.15 p.123
#  "When a powerful trend is born, volatility expands so much that
#   the lower band turns down in an uptrend." Reverse = end of trend.
# ─────────────────────────────────────────────────────────────────
EXPANSION_LOOKBACK = 5    # Bars to check band direction

# ─────────────────────────────────────────────────────────────────
#  WIDTH-LENGTH RELATIONSHIP — Rule 11, p.184
#  "10-period→1.9σ, 20-period→2.0σ, 50-period→2.1σ"
#  Piecewise linear through the book's three anchor points.
# ─────────────────────────────────────────────────────────────────
WIDTH_LENGTH_ANCHORS = [(10, 1.9), (20, 2.0), (50, 2.1)]
WIDTH_LENGTH_MIN = 1.5
WIDTH_LENGTH_MAX = 2.5

# ─────────────────────────────────────────────────────────────────
#  TYPICAL PRICE OPTION — Book Ch.7
#  Close is standard; (H+L+C)/3 is an alternative.
# ─────────────────────────────────────────────────────────────────
BB_USE_TYPICAL_PRICE = False

# ─────────────────────────────────────────────────────────────────
#  VOLUME-PRICE TREND — Book Ch.18 (7th of 8 indicators)
# ─────────────────────────────────────────────────────────────────
VPT_SIGNAL_PERIOD = 9

# ─────────────────────────────────────────────────────────────────
#  BOLLINGER BOXES — Book Ch.11
# ─────────────────────────────────────────────────────────────────
BBOX_MIN_SWINGS = 4
BBOX_LOOKBACK = 50

# ─────────────────────────────────────────────────────────────────
#  METHOD II PULLBACK TRADING — Book Ch.19
#  "Use signals as alerts, trade the first pullback"
# ─────────────────────────────────────────────────────────────────
M2_PULLBACK_ENABLED = True
M2_PULLBACK_PCT_B_MIN = 0.4
M2_PULLBACK_PCT_B_MAX = 0.65
M2_PULLBACK_LOOKBACK = 5

# ─────────────────────────────────────────────────────────────────
#  METHOD IV 3-LEG WALK — Elliott convention from book
# ─────────────────────────────────────────────────────────────────
M4_WALK_LEG_MIN_BARS = 3
M4_WALK_EXPECTED_LEGS = 3

# ─────────────────────────────────────────────────────────────────
#  INDICATOR NORMALISATION — Book Ch.21 Table 21.1
#  Apply Bollinger Bands to indicators for adaptive OB/OS levels.
# ─────────────────────────────────────────────────────────────────
NORM_RSI_PERIOD    = 14   # RSI calculation period
NORM_RSI_BB_LEN    = 50   # BB length on 14-period RSI (Table 21.1)
NORM_RSI_BB_STD    = 2.1  # BB width on 14-period RSI (Table 21.1)
NORM_MFI_BB_LEN    = 40   # BB length on 10-period MFI (Table 21.1)
NORM_MFI_BB_STD    = 2.0  # BB width on 10-period MFI (Table 21.1)

# ─────────────────────────────────────────────────────────────────
#  KELTNER CHANNEL — T7 Squeeze Filter
#  BB inside KC = genuine volatility compression (not just low BBW).
#  Backtested: 1,795 trades, 53% WR, 1.72 PF vs baseline 49.8% / 1.49.
# ─────────────────────────────────────────────────────────────────
KC_EMA_PERIOD           = 20    # EMA period for KC midline
KC_ATR_PERIOD           = 14    # ATR period for KC width
KC_ATR_MULT             = 1.5   # ATR multiplier (Linda Raschke standard)
KC_SQUEEZE_LOOKBACK     = 10    # Look back N bars for recent KC squeeze
KC_SQUEEZE_MIN_BARS     = 6     # Min consecutive bars BB inside KC
KC_SQUEEZE_INTENSITY_MIN = 0.30 # BB must be ≥30% narrower than KC

# ─────────────────────────────────────────────────────────────────
#  DATA SETTINGS
# ─────────────────────────────────────────────────────────────────
HISTORY_START  = "2020-01-01"
HISTORY_END    = None   # None → uses today's date (dynamic)
MIN_DATA_DAYS  = 150    # Minimum required data points for reliable calculations

# ─────────────────────────────────────────────────────────────────
#  SIGNAL SCORING WEIGHTS
# ─────────────────────────────────────────────────────────────────
# Each condition contributes to confidence score (total = 100)
# Rule 5 collinearity fix: base weights diversified across indicator categories
SCORE_BBW_SQUEEZE    = 25   # Core squeeze condition — highest weight
SCORE_PRICE_BREAKOUT = 25   # Price closes above upper BB
SCORE_VOLUME_CONFIRM = 20   # Volume above 50 SMA (pure volume category)
SCORE_CMF_POSITIVE   = 5    # CMF demoted to supplementary (same category as MFI)
SCORE_MFI_ABOVE_50   = 15   # MFI primary volume×price indicator
SCORE_II_CONFIRM     = 5    # II% > 0 — independent V×P formula (Book Ch.18)
SCORE_VWMACD_CONFIRM = 5    # VWMACD trend category (Book Ch.18)
# Base total: 25+25+20+5+15+5+5 = 100

# Bonus scores (can exceed 100, clamped later)
SCORE_CMF_ABOVE_10   = 3    # CMF > +0.10 (supplementary)
SCORE_MFI_ABOVE_80   = 5    # MFI > 80 (maximum fuel)
SCORE_KC_T7_BONUS    = 10   # T7 Keltner Channel deep squeeze bonus
SCORE_RALLY_DAY      = 5    # Above-avg range + volume on breakout (Book Ch.20 p.163)
SCORE_EXPANSION_CONFIRM = 3 # Band expansion confirms trend direction (Book Ch.15)
SCORE_VPT_CONFIRM    = 3    # VPT above signal line (Book Ch.18)

# ─────────────────────────────────────────────────────────────────
#  FUNDAMENTAL DATA SOURCES
# ─────────────────────────────────────────────────────────────────
SCREENER_BASE_URL     = "https://www.screener.in/company/"
YFINANCE_TIMEOUT      = 10   # seconds

# ─────────────────────────────────────────────────────────────────
#  DISPLAY SETTINGS
# ─────────────────────────────────────────────────────────────────
TERMINAL_WIDTH = 120
