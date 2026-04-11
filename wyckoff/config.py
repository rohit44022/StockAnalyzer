"""
wyckoff/config.py — Wyckoff/Villahermosa Analysis Parameters
============================================================

TRUTHFULNESS AUDIT
──────────────────
Source Book: Rubén Villahermosa, "The Wyckoff Methodology in Depth" (2019)

Villahermosa teaches the PRINCIPLES of reading volume-spread relationships
through 3 Laws, 7 Events, 5 Phases (A-E), and 4 Schematics.
He does NOT prescribe specific numeric thresholds (2×, 3×, etc.).
The thresholds below are [INFERRED] from his qualitative teaching
and calibrated to produce reasonable detection on Indian NSE daily data.

Every comment below cites the SOURCE CONCEPT from the book.
If a parameter is purely our calibration, it is marked [CALIBRATION].
"""

# ─────────────────────────────────────────────────────────────
#  VOLUME ANALYSIS PARAMETERS
# ─────────────────────────────────────────────────────────────

# Volume spike: if current volume exceeds N × average volume
# Source: Villahermosa — Part 5 (Laws), volume analysis
#   Villahermosa teaches: look for bars where volume is notably above average.
#   He does NOT specify 2× or 3×. These multipliers are [CALIBRATION].
VOLUME_SPIKE_MULTIPLIER = 2.0          # [CALIBRATION] 2× avg = notable
VOLUME_CLIMAX_MULTIPLIER = 3.0         # [CALIBRATION] 3× avg = climax

# Volume dry-up: below this fraction of average = no interest
# Source: Villahermosa — Part 5 (Laws), concept of "Lack of Interest"
#   Villahermosa teaches: when volume virtually disappears, supply/demand is absent.
#   The 50% threshold is [CALIBRATION].
VOLUME_DRYUP_FRACTION = 0.5            # [CALIBRATION] <50% avg = dry-up

# Lookback for average volume computation
# [CALIBRATION] Villahermosa uses "recent average" without specifying exact period.
VOLUME_AVG_PERIOD = 50                 # [CALIBRATION] 50-day average

# ─────────────────────────────────────────────────────────────
#  WYCKOFF WAVE PARAMETERS
# ─────────────────────────────────────────────────────────────

# Minimum bars for a wave to be counted
# [CALIBRATION] Villahermosa shows waves visually; no minimum bar count specified.
WAVE_MIN_BARS = 2                      # [CALIBRATION] 2 bars minimum

# Number of recent waves to track for analysis
# [CALIBRATION] Villahermosa compares "recent" waves; no specific count given.
WAVE_LOOKBACK = 10                     # [CALIBRATION] last 10 waves

# Shortening of thrust: if latest wave covers < this % of previous
# Source: Villahermosa — Part 5, Law 3 (Effort vs Result)
#   Villahermosa teaches: "each successive push covers less ground." He shows
#   this visually but does NOT give a numeric threshold.
SHORTENING_THRESHOLD = 0.65            # [CALIBRATION] <65% = shortening

# ─────────────────────────────────────────────────────────────
#  EFFORT VS RESULT PARAMETERS
# ─────────────────────────────────────────────────────────────

# Effort-Result Divergence: high volume but small price move
# Source: Villahermosa — Part 5, Law 3 (Effort vs Result)
#   Villahermosa teaches: "When the effort (volume) doesn't match the result
#   (spread), the Composite Man is operating." He uses visual comparison,
#   not percentiles. These are [CALIBRATION].
NARROW_SPREAD_PERCENTILE = 30          # [CALIBRATION] bottom 30%
WIDE_SPREAD_PERCENTILE = 70            # [CALIBRATION] top 30%

# Lookback for spread percentile computation
SPREAD_LOOKBACK = 50                   # [CALIBRATION]

# ─────────────────────────────────────────────────────────────
#  WYCKOFF PHASE DETECTION
# ─────────────────────────────────────────────────────────────

# Trading range: price within this % band over N bars
# Source: Villahermosa — Part 7 (Structures), concept of "trading range" as
#   foundation for Accumulation/Distribution. Villahermosa identifies ranges visually.
#   The 15% band and 40-bar lookback are [CALIBRATION].
RANGE_LOOKBACK = 40                    # [CALIBRATION] 40-bar window
RANGE_THRESHOLD_PCT = 0.15             # [CALIBRATION] 15% band

# Minimum bars to confirm a Wyckoff phase
# [CALIBRATION] Villahermosa implies phases take "time to develop" but
# gives no specific bar count.
PHASE_MIN_BARS = 15                    # [CALIBRATION] 15-bar minimum

# ─────────────────────────────────────────────────────────────
#  SPRING / UPTHRUST DETECTION
# ─────────────────────────────────────────────────────────────

# Spring: price breaks below support (Ice) by up to this % then reverses
# Source: Villahermosa — Part 6 (Events), Event 5: Shaking
#   Villahermosa teaches: The Spring is a penetration of the support level (Ice)
#   that quickly reverses. It should be a brief penetration.
#   The 3% max penetration and 0.5% reversal are [CALIBRATION].
SPRING_MAX_PENETRATION_PCT = 0.03      # [CALIBRATION] 3% max below
SPRING_MIN_REVERSAL_PCT = 0.005        # [CALIBRATION] 0.5% min bounce

# Upthrust: mirror of Spring (price breaks above resistance / Creek)
# Source: Villahermosa — Part 6 (Events), Event 5: Shaking (UTAD variant)
#   Same principle as Spring but for resistance (Creek).
UPTHRUST_MAX_PENETRATION_PCT = 0.03    # [CALIBRATION] 3% max above
UPTHRUST_MIN_REVERSAL_PCT = 0.005      # [CALIBRATION] 0.5% min drop

# Volume on spring/upthrust should be below average (trap on low volume)
# Source: Villahermosa — Part 6 (Events), Event 5: Shaking
#   Villahermosa teaches: Springs on LOW volume are the strongest signal because
#   low volume proves "there is no real supply pushing through."
#   He classifies as Spring Type #1 (most reliable) on low volume.
#   The 1.2× threshold is [CALIBRATION].
SPRING_VOLUME_MAX_RATIO = 1.2          # [CALIBRATION] < 1.2× avg

# ─────────────────────────────────────────────────────────────
#  CLIMAX DETECTION
# ─────────────────────────────────────────────────────────────

# Selling Climax: wide spread down + very high volume + close near high
# Source: Villahermosa — Part 6 (Events), Event 2: Climax
#   Villahermosa teaches: Climaxes have wide spread, heavy volume, and the close
#   position tells who won. He uses visual bar-by-bar reading.
#   All numeric thresholds below are [CALIBRATION].
SC_MIN_SPREAD_PERCENTILE = 80          # [CALIBRATION] top 20% spread
SC_MIN_VOLUME_MULTIPLIER = 2.0         # [CALIBRATION] 2× avg vol
SC_CLOSE_POSITION_THRESHOLD = 0.4      # [CALIBRATION] close in upper 40%

# Buying Climax: wide spread up + very high volume + close near low
BC_MIN_SPREAD_PERCENTILE = 80          # [CALIBRATION] top 20% spread
BC_MIN_VOLUME_MULTIPLIER = 2.0         # [CALIBRATION] 2× avg vol
BC_CLOSE_POSITION_THRESHOLD = 0.4      # [CALIBRATION] close in lower 40%

# ─────────────────────────────────────────────────────────────
#  SIGN OF STRENGTH / WEAKNESS
# ─────────────────────────────────────────────────────────────

# Source: Villahermosa covers SOS (Sign of Strength) and SOW (Sign of Weakness)
#   as key events in Phase D. He describes the bar behavior (wide spread, heavy
#   volume, strong close) as part of Events 6 (Breakout) and 7 (Confirmation).
#   The detection logic captures the behavior Villahermosa teaches. [CALIBRATION].
SOS_MIN_SPREAD_PERCENTILE = 60         # [CALIBRATION]
SOS_MIN_VOLUME_RATIO = 1.3             # [CALIBRATION]

# SOW: wide spread down bar closing on low, above-average volume
SOW_MIN_SPREAD_PERCENTILE = 60         # [CALIBRATION]
SOW_MIN_VOLUME_RATIO = 1.3             # [CALIBRATION]

# ─────────────────────────────────────────────────────────────
#  TEST DETECTION
# ─────────────────────────────────────────────────────────────

# Source: Villahermosa — Part 6 (Events), Event 4: Test
#   Villahermosa teaches: After a climax or spring, price "comes back to test
#   that area" and the volume on the test should be LESS than the
#   original event. He does not specify exact ratios.
TEST_VOLUME_RATIO_MAX = 0.75           # [CALIBRATION] vol < 75% of ref
TEST_PRICE_PROXIMITY_PCT = 0.02        # [CALIBRATION] within 2%

# ─────────────────────────────────────────────────────────────
#  SCORING
# ─────────────────────────────────────────────────────────────

# Maximum Wyckoff confirmation bonus added to triple engine
# [CALIBRATION] Villahermosa does not prescribe a scoring system.
# This ±30 bonus is our integration design decision to blend
# Wyckoff analysis into the existing BB+TA+PA scoring framework.
WYCKOFF_MAX_BONUS = 30                 # [CALIBRATION] ±30 pts max
