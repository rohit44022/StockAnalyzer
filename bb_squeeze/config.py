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
#  INDICATOR NORMALISATION — Book Ch.21 Table 21.1
#  Apply Bollinger Bands to indicators for adaptive OB/OS levels.
# ─────────────────────────────────────────────────────────────────
NORM_RSI_PERIOD    = 14   # RSI calculation period
NORM_RSI_BB_LEN    = 50   # BB length on 14-period RSI (Table 21.1)
NORM_RSI_BB_STD    = 2.1  # BB width on 14-period RSI (Table 21.1)
NORM_MFI_BB_LEN    = 40   # BB length on 10-period MFI (Table 21.1)
NORM_MFI_BB_STD    = 2.0  # BB width on 10-period MFI (Table 21.1)

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
SCORE_BBW_SQUEEZE    = 25   # Core squeeze condition — highest weight
SCORE_PRICE_BREAKOUT = 25   # Price closes above upper BB
SCORE_VOLUME_CONFIRM = 20   # Volume above 50 SMA
SCORE_CMF_POSITIVE   = 15   # CMF above zero
SCORE_MFI_ABOVE_50   = 15   # MFI above 50

# Bonus scores
SCORE_CMF_ABOVE_10   = 5    # CMF > +0.10 (strong accumulation)
SCORE_MFI_ABOVE_80   = 5    # MFI > 80 (maximum fuel)

# ─────────────────────────────────────────────────────────────────
#  FUNDAMENTAL DATA SOURCES
# ─────────────────────────────────────────────────────────────────
SCREENER_BASE_URL     = "https://www.screener.in/company/"
YFINANCE_TIMEOUT      = 10   # seconds

# ─────────────────────────────────────────────────────────────────
#  DISPLAY SETTINGS
# ─────────────────────────────────────────────────────────────────
TERMINAL_WIDTH = 120
