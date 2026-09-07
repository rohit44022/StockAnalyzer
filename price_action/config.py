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
# Brooks defines inside and outside bars exactly, with no tolerance band:
# inside  = "a high that is at or below the high of the prior bar and a low
#            that is at or above the low of the prior bar"
# The old INSIDE_BAR_TOLERANCE let a bar whose high poked ABOVE the prior high
# still count as inside, which is not an inside bar under any reading of the
# book. Comparisons are now exact; the constant is retained only so external
# callers do not break, and is unused.
INSIDE_BAR_TOLERANCE = 0.0          # unused — Brooks' definition is exact

# ─────────────────────────────────────────────────────────────────
#  PATTERN DETECTION
# ─────────────────────────────────────────────────────────────────
# High/Low counting
HL_MAX_LOOKBACK = 30                # Max bars to look back for H1-H4 / L1-L4 counting

# Brooks' with-trend test (glossary, "with trend"): "if most of the past 10 or
# 20 bars are above the moving average, trend setups and trades are likely on
# the buy side." This gates H-counts to the buy side and L-counts to the sell
# side — Brooks: "a low 1 sets up trades in trading ranges and bear trends,
# not strong bull trends."
WITH_TREND_LOOKBACK = 20            # "the past 10 or 20 bars"
WITH_TREND_MIN_BARS = 10            # need at least the shorter window to judge

# Swing points (Brooks, glossary "swing high"/"swing low"): a swing needs only
# ONE bar on each side. A MAJOR swing is not "the highest of N bars" — Brooks
# ties major structure to separation: a major trend line is "typically drawn
# using bars that are at least 10 bars apart".
SWING_LOOKBACK = 1                  # bars each side — Brooks' definition
MAJOR_SWING_MIN_SEPARATION = 10     # Brooks: major trend line bars >= 10 apart

# Double bottom/top flags
# Brooks: "the low of the current bar is about the same as the low of a prior
# swing low. That prior low can be just one bar earlier or 20 or more bars
# earlier." So there is no minimum spacing (a 1-bar gap is a micro double
# bottom, which Brooks trades) and no hard 30-bar ceiling.
DB_PRICE_TOLERANCE = 0.015          # 1.5% — "about the same" (our operationalisation)
DB_MAX_SPACING = 60                 # Brooks: "20 or more bars earlier" — not capped at 30
DB_MIN_SPACING = 1                  # Brooks: "can be just one bar earlier"
# A double bottom is a two-legged flag, so the market must actually rally away
# from the first low and come back. Without a neckline the "formation" is a
# tight trading range (Brooks calls that barbwire), not a double bottom.
# Measured in ATR so it scales across instruments. Our operationalisation —
# Brooks describes the shape but gives no number.
DB_MIN_NECKLINE_ATR = 1.0

# Wedge (3-push) patterns
WEDGE_MAX_LOOKBACK = 40             # Max bars to look back for wedge
WEDGE_MIN_PUSHES = 3                # Minimum pushes required

# ii / iii / ioi patterns — detected by exact bar relationships, no thresholds needed

# ─────────────────────────────────────────────────────────────────
#  TREND ANALYSIS
# ─────────────────────────────────────────────────────────────────
# Always-in direction
# Brooks' always-in is a latching state that flips only on a spike that breaks
# out and is confirmed by follow-through on the next bar. It is not a score,
# so AI_EMA_PERIOD / AI_STRONG_THRESHOLD no longer gate it; they are kept only
# so external callers do not break, and are unused.
AI_LOOKBACK = 20                    # Min bars before an always-in read is meaningful
AI_BREAKOUT_LOOKBACK = 10           # "beyond the trading range" — our operationalisation
AI_BASE_SCORE = 60.0                # A confirmed flip starts here, +2/bar it survives
AI_EMA_PERIOD = 20                  # unused — always-in does not consult the EMA
AI_STRONG_THRESHOLD = 65            # unused — always-in is binary, not scored

# Buying / Selling pressure
PRESSURE_LOOKBACK = 20              # Bars to analyze for pressure
PRESSURE_STRONG = 0.65              # >65% bull bars = strong buying pressure

# Spike detection
SPIKE_MIN_BARS = 2                  # Min consecutive strong trend bars for spike (Al Brooks: "every trend bar is a spike"; 2+ = confirmed spike)
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
