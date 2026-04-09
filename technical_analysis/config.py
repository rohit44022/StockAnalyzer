"""
config.py — Configuration constants for the Technical Analysis module.

All thresholds, periods, and parameters are drawn from:
  "Technical Analysis of the Financial Markets" — John J. Murphy

These are INDUSTRY-STANDARD values used by professionals worldwide.
Tuned for the Indian equity market (NSE/BSE daily timeframe).
"""

# ═══════════════════════════════════════════════════════════════
#  MOVING AVERAGES  (Murphy Ch 9)
# ═══════════════════════════════════════════════════════════════
SMA_PERIODS      = [10, 20, 50, 100, 200]   # Standard SMA lookbacks
EMA_PERIODS      = [9, 12, 21, 26, 50, 200] # Standard EMA lookbacks

# Golden Cross / Death Cross — the two most-watched crossovers
MA_FAST_PERIOD   = 50
MA_SLOW_PERIOD   = 200

# ═══════════════════════════════════════════════════════════════
#  RSI — RELATIVE STRENGTH INDEX  (Murphy Ch 10, Wilder 1978)
# ═══════════════════════════════════════════════════════════════
RSI_PERIOD       = 14
RSI_OVERBOUGHT   = 70    # Above 70 = overbought
RSI_OVERSOLD     = 30    # Below 30 = oversold
RSI_MIDLINE      = 50    # Bull/bear divider

# ═══════════════════════════════════════════════════════════════
#  MACD — MOVING AVERAGE CONVERGENCE DIVERGENCE  (Murphy Ch 10)
# ═══════════════════════════════════════════════════════════════
MACD_FAST        = 12     # Fast EMA period
MACD_SLOW        = 26     # Slow EMA period
MACD_SIGNAL      = 9      # Signal line EMA period

# ═══════════════════════════════════════════════════════════════
#  STOCHASTIC OSCILLATOR  (Murphy Ch 10, George Lane)
# ═══════════════════════════════════════════════════════════════
STOCH_K_PERIOD   = 14     # %K lookback
STOCH_D_PERIOD   = 3      # %D smoothing (SMA of %K)
STOCH_SLOW       = 3      # Slow stochastic smoothing
STOCH_OVERBOUGHT = 80     # Overbought level
STOCH_OVERSOLD   = 20     # Oversold level

# ═══════════════════════════════════════════════════════════════
#  WILLIAMS %R  (Murphy Ch 10)
# ═══════════════════════════════════════════════════════════════
WILLR_PERIOD     = 14
WILLR_OVERBOUGHT = -20    # Near 0 = overbought
WILLR_OVERSOLD   = -80    # Near -100 = oversold

# ═══════════════════════════════════════════════════════════════
#  CCI — COMMODITY CHANNEL INDEX  (Murphy Ch 10, Donald Lambert)
# ═══════════════════════════════════════════════════════════════
CCI_PERIOD       = 20
CCI_OVERBOUGHT   = 100
CCI_OVERSOLD     = -100

# ═══════════════════════════════════════════════════════════════
#  ADX / DMI — AVERAGE DIRECTIONAL INDEX  (Murphy Ch 10, Wilder)
# ═══════════════════════════════════════════════════════════════
ADX_PERIOD       = 14
ADX_STRONG       = 25     # ADX > 25 = strong trend
ADX_VERY_STRONG  = 40     # ADX > 40 = very strong trend
ADX_WEAK         = 20     # ADX < 20 = no clear trend

# ═══════════════════════════════════════════════════════════════
#  ATR — AVERAGE TRUE RANGE  (Wilder 1978)
# ═══════════════════════════════════════════════════════════════
ATR_PERIOD       = 14

# ═══════════════════════════════════════════════════════════════
#  ICHIMOKU CLOUD  (Hosoda)
# ═══════════════════════════════════════════════════════════════
ICHI_TENKAN      = 9      # Conversion line (fast)
ICHI_KIJUN       = 26     # Base line (slow)
ICHI_SENKOU_B    = 52     # Leading Span B lookback
ICHI_DISPLACEMENT = 26    # Cloud displacement (forward shift)

# ═══════════════════════════════════════════════════════════════
#  KELTNER CHANNELS  (Chester Keltner, Linda Raschke variant)
# ═══════════════════════════════════════════════════════════════
KELTNER_PERIOD   = 20     # EMA period
KELTNER_ATR_MULT = 1.5    # ATR multiplier

# ═══════════════════════════════════════════════════════════════
#  SUPERTREND
# ═══════════════════════════════════════════════════════════════
SUPERTREND_PERIOD = 10
SUPERTREND_MULT   = 3.0

# ═══════════════════════════════════════════════════════════════
#  AROON  (Tushar Chande)
# ═══════════════════════════════════════════════════════════════
AROON_PERIOD      = 25

# ═══════════════════════════════════════════════════════════════
#  VOLUME INDICATORS  (Murphy Ch 7)
# ═══════════════════════════════════════════════════════════════
OBV_SMA_PERIOD    = 20     # For OBV trend smoothing
VROC_PERIOD       = 14     # Volume Rate of Change

# ═══════════════════════════════════════════════════════════════
#  VWAP — VOLUME WEIGHTED AVERAGE PRICE
# ═══════════════════════════════════════════════════════════════
VWAP_PERIOD       = 20     # Rolling VWAP lookback

# ═══════════════════════════════════════════════════════════════
#  FIBONACCI & DOW RETRACEMENT LEVELS  (Murphy Ch 4, Ch 19 #8)
# ═══════════════════════════════════════════════════════════════
# Murphy Ch 19 checklist item #8: "33%, 50%, 66% retracements" (Dow Theory)
# Combined with Fibonacci levels for comprehensive coverage.
FIB_RETRACEMENT = [0.0, 0.236, 0.333, 0.382, 0.500, 0.618, 0.667, 0.786, 1.0]
FIB_EXTENSION   = [1.0, 1.272, 1.618, 2.0, 2.618]
# Dow Theory retracements (Murphy): 33%, 50%, 66%
DOW_RETRACEMENT = [0.333, 0.500, 0.667]

# ═══════════════════════════════════════════════════════════════
#  PIVOT POINTS
# ═══════════════════════════════════════════════════════════════
# Classic pivot: PP = (H + L + C) / 3
# S1 = 2*PP - H, R1 = 2*PP - L
# S2 = PP - (H - L), R2 = PP + (H - L)
# S3 = L - 2*(H - PP), R3 = H + 2*(PP - L)

# ═══════════════════════════════════════════════════════════════
#  CANDLESTICK DETECTION  (Murphy Ch 12)
# ═══════════════════════════════════════════════════════════════
CANDLE_DOJI_THRESHOLD     = 0.05    # Body < 5% of range = doji
CANDLE_LONG_BODY_MULT     = 1.5     # Body > 1.5x avg = long body
CANDLE_SMALL_BODY_MULT    = 0.5     # Body < 0.5x avg = small body
CANDLE_SHADOW_RATIO       = 2.0     # Shadow > 2x body for hammer/star
CANDLE_LOOKBACK           = 14      # Periods for average body size

# ═══════════════════════════════════════════════════════════════
#  CHART PATTERNS  (Murphy Ch 5-6)
# ═══════════════════════════════════════════════════════════════
PATTERN_MIN_BARS          = 10      # Minimum bars for a pattern
PATTERN_MAX_BARS          = 120     # Maximum lookback for patterns
SUPPORT_RESISTANCE_WINDOW = 5       # Bars to check for local extremes
SUPPORT_RESISTANCE_CLUSTER = 0.015  # 1.5% tolerance for clustering

# ═══════════════════════════════════════════════════════════════
#  SIGNAL SCORING WEIGHTS  (Murphy Ch 19: Pulling It All Together)
# ═══════════════════════════════════════════════════════════════
WEIGHT_TREND       = 25    # Trend direction (MA, ADX)
WEIGHT_MOMENTUM    = 20    # Oscillators (RSI, MACD, Stochastic)
WEIGHT_VOLUME      = 15    # Volume confirmation (OBV, A/D)
WEIGHT_PATTERN     = 15    # Chart + candlestick patterns
WEIGHT_SUPPORT_RES = 10    # Support/resistance proximity
WEIGHT_RISK        = 15    # Risk/reward setup quality

# ═══════════════════════════════════════════════════════════════
#  RISK MANAGEMENT  (Murphy Ch 16)
# ═══════════════════════════════════════════════════════════════
MAX_RISK_PER_TRADE = 0.02   # 2% of capital per trade (Murphy rule)
MAX_PORTFOLIO_RISK = 0.06   # 6% total portfolio heat
DEFAULT_CAPITAL    = 500000  # ₹5,00,000 default capital (INR)
RISK_FREE_RATE     = 0.065  # 6.5% (Indian 10-year G-Sec yield)

# ═══════════════════════════════════════════════════════════════
#  INDIAN MARKET SPECIFICS
# ═══════════════════════════════════════════════════════════════
MARKET_OPEN_HOUR   = 9
MARKET_OPEN_MIN    = 15
MARKET_CLOSE_HOUR  = 15
MARKET_CLOSE_MIN   = 30
TRADING_DAYS_YEAR  = 252    # Approx trading days per year
LOT_SIZE_DEFAULT   = 1      # Equity lot size (not F&O)
