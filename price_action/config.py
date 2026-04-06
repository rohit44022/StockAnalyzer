"""
Price Action Configuration — Al Brooks Constants & Thresholds
=============================================================
All tunable parameters for the Price Action analysis engine.
Values calibrated for Indian NSE daily charts (OHLCV data).
"""

# ─────────────────────────────────────────────────────────────────
#  BAR CLASSIFICATION THRESHOLDS
# ─────────────────────────────────────────────────────────────────
# Body as percentage of bar range
STRONG_TREND_BAR_BODY_PCT = 0.60    # Body > 60% of range = strong trend bar
TREND_BAR_BODY_PCT = 0.40           # Body > 40% = trend bar
DOJI_BODY_PCT = 0.20                # Body < 20% = doji (neither side controls)

# Close position within bar (thirds)
CLOSE_UPPER_THIRD = 0.67            # Close in top 1/3 of range
CLOSE_LOWER_THIRD = 0.33            # Close in bottom 1/3 of range

# Tail significance
SIGNIFICANT_TAIL_PCT = 0.33         # Tail > 33% of range = significant rejection
SMALL_TAIL_PCT = 0.10               # Tail < 10% = shaved (strong conviction)

# ─────────────────────────────────────────────────────────────────
#  SIGNAL BAR (REVERSAL BAR) THRESHOLDS
# ─────────────────────────────────────────────────────────────────
REVERSAL_BAR_TAIL_MIN = 0.30        # Min tail pct for reversal bar
REVERSAL_BAR_BODY_MAX = 0.50        # Max body pct (smaller body = more indecision)
MIN_BARS_IN_MOVE = 3                # Min bars in a move before reversal bar counts

# ─────────────────────────────────────────────────────────────────
#  OUTSIDE / INSIDE BAR
# ─────────────────────────────────────────────────────────────────
INSIDE_BAR_TOLERANCE = 0.001        # Allow tiny overshoot for inside bar (fraction of range)

# ─────────────────────────────────────────────────────────────────
#  PATTERN DETECTION
# ─────────────────────────────────────────────────────────────────
# High/Low counting
HL_MAX_LOOKBACK = 30                # Max bars to look back for H1-H4 / L1-L4 counting

# Double bottom/top flags
DB_PRICE_TOLERANCE = 0.015          # 1.5% price tolerance for double bottom/top
DB_MAX_SPACING = 30                 # Max bars between the two lows/highs
DB_MIN_SPACING = 3                  # Min bars between the two lows/highs

# Wedge (3-push) patterns
WEDGE_MAX_LOOKBACK = 40             # Max bars to look back for wedge
WEDGE_MIN_PUSHES = 3                # Minimum pushes required

# ii / iii / ioi patterns — detected by exact bar relationships, no thresholds needed

# ─────────────────────────────────────────────────────────────────
#  TREND ANALYSIS
# ─────────────────────────────────────────────────────────────────
# Always-in direction
AI_LOOKBACK = 20                    # Bars to consider for always-in calculation
AI_EMA_PERIOD = 20                  # EMA for trend bias
AI_STRONG_THRESHOLD = 65            # Score > 65 = strong always-in direction

# Buying / Selling pressure
PRESSURE_LOOKBACK = 20              # Bars to analyze for pressure
PRESSURE_STRONG = 0.65              # >65% bull bars = strong buying pressure

# Spike detection
SPIKE_MIN_BARS = 3                  # Min consecutive strong trend bars for spike (Al Brooks: urgency = 2-5 bars) (Al Brooks: urgency = 2-5 bars) (Al Brooks: urgency = 2-5 bars)
SPIKE_MAX_BARS = 5                  # Typical spike is 1-5 bars
SPIKE_BODY_THRESHOLD = 0.55         # Min body pct to qualify as spike bar

# Two-leg analysis
TWO_LEG_TOLERANCE = 0.02            # 2% tolerance for second leg matching first

# Consecutive trend bars
CONSECUTIVE_TREND_STRONG = 3        # 3+ consecutive trend bars = strong signal

# Climax detection
CLIMAX_ATR_MULTIPLE = 2.0           # Bar range > 2x ATR = potential climax
CLIMAX_LOOKBACK = 50                # ATR lookback for climax detection
CLIMAX_MIN_BARS_IN_TREND = 10       # Must be in trend for 10+ bars before climax

# ─────────────────────────────────────────────────────────────────
#  TREND LINES & CHANNELS
# ─────────────────────────────────────────────────────────────────
TRENDLINE_MIN_TOUCHES = 2           # Min pivot touches for valid trend line
TRENDLINE_MAX_LOOKBACK = 60         # Max bars back for trend line detection
CHANNEL_LINE_TOLERANCE = 0.005      # 0.5% tolerance for channel line touch

# Micro channel
MICRO_CHANNEL_MAX_BARS = 15         # Micro channel is very tight, max 15 bars
MICRO_CHANNEL_MIN_BARS = 5          # Min bars for micro channel
MICRO_CHANNEL_TOUCH_PCT = 0.80      # 80%+ of bars must touch the trend line

# ─────────────────────────────────────────────────────────────────
#  BREAKOUT DETECTION
# ─────────────────────────────────────────────────────────────────
BREAKOUT_STRENGTH_MIN_BODY = 0.50   # Breakout bar body > 50% of range
BREAKOUT_CLOSE_BEYOND = True        # Close must be beyond the breakout level
BREAKOUT_PULLBACK_MAX_BARS = 5      # Max bars for breakout pullback (quick test)
BREAKOUT_PULLBACK_DEEP_MAX = 10     # Extended breakout pullback (up to 10 bars)
FAILED_BREAKOUT_BARS = 3            # Failed within 3 bars = definite failure

# ─────────────────────────────────────────────────────────────────
#  SIGNAL GENERATION / SCORING
# ─────────────────────────────────────────────────────────────────
# PA Score weights (total 100)
W_TREND_DIRECTION = 25              # Always-in direction alignment
W_BAR_QUALITY = 15                  # Signal bar quality
W_PATTERN_MATCH = 15                # Multi-bar pattern found
W_PRESSURE = 15                     # Buying/selling pressure alignment
W_BREAKOUT = 10                     # Breakout status
W_CHANNEL_POSITION = 10             # Position in channel
W_TWO_LEG = 5                       # Two-leg completion
W_FOLLOW_THROUGH = 5                # Follow-through on prior signal

# Cross-system bonus (PA + BB/TA/Hybrid agreement)
CROSS_AGREE_BONUS = 15              # All systems agree
CROSS_PARTIAL_BONUS = 5             # Partial agreement
CROSS_CONFLICT_PENALTY = -10        # Systems conflict

# Confidence thresholds
CONF_STRONG_SIGNAL = 75             # 75+ = strong signal
CONF_MODERATE_SIGNAL = 50           # 50-74 = moderate
CONF_WEAK_SIGNAL = 30               # 30-49 = weak
CONF_MIN_ACTIONABLE = 30            # Below 30 = not actionable

# ─────────────────────────────────────────────────────────────────
#  FINAL VERDICT THRESHOLDS
# ─────────────────────────────────────────────────────────────────
VERDICT_STRONG_BUY = 75
VERDICT_BUY = 50
VERDICT_WEAK_BUY = 30
VERDICT_HOLD = -30                  # -30 to +30 = HOLD
VERDICT_WEAK_SELL = -30
VERDICT_SELL = -50
VERDICT_STRONG_SELL = -75

# ─────────────────────────────────────────────────────────────────
#  DATA REQUIREMENTS
# ─────────────────────────────────────────────────────────────────
MIN_BARS_REQUIRED = 60              # Minimum bars needed for meaningful PA analysis
ATR_PERIOD = 14                     # ATR period for volatility normalization
EMA_PERIOD = 20                     # Default EMA for trend reference
