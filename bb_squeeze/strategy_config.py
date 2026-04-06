"""
strategy_config.py — Configuration for additional Bollinger Band strategies.
All parameters sourced from: "Bollinger on Bollinger Bands" by John Bollinger
  Method II  — Trend Following   (Chapters 15-16)
  Method III — Reversals          (Chapter 17)
  Method IV  — Walking the Bands  (Chapter 18)
"""

# ─────────────────────────────────────────────────────────────────
#  METHOD II — TREND FOLLOWING  (%b + MFI confirmation)
#  Book ref: "Use %b to clarify patterns and use MFI to confirm."
# ─────────────────────────────────────────────────────────────────

# %b thresholds for Method II signals
M2_PCT_B_BUY_THRESHOLD  = 0.8     # %b > 0.8 → price in upper zone
M2_PCT_B_SELL_THRESHOLD = 0.2     # %b < 0.2 → price in lower zone
M2_MFI_CONFIRM_BUY      = 60      # MFI must confirm with > 60
M2_MFI_CONFIRM_SELL      = 40      # MFI must confirm with < 40
M2_MFI_DIVERGE_LOOKBACK  = 10     # Bars to look back for divergence

# Volume confirmation
M2_VOL_CONFIRM = True   # Require volume above SMA for confirmation

# ─────────────────────────────────────────────────────────────────
#  METHOD III — REVERSALS (W-BOTTOMS / M-TOPS with divergence)
#  Book ref: "W bottoms — Arthur Merrill's 16 W variations"
#            "M tops — look for %b divergence at the second peak"
# ─────────────────────────────────────────────────────────────────

# W-Bottom detection
M3_W_LOOKBACK       = 30    # Days to look back for W/M pattern
M3_W_MIN_SEPARATION = 5     # Minimum days between two lows/highs
M3_W_MAX_SEPARATION = 25    # Maximum days between two lows/highs
M3_W_FIRST_LOW_PCT_B  = 0.0   # First low should tag lower band (%b ≤ 0)
M3_W_SECOND_LOW_PCT_B = 0.2   # Second low must be ABOVE lower band (%b > 0.2)
M3_W_PRICE_TOLERANCE   = 0.03  # Second low within 3% of first low (or higher)

# M-Top detection
M3_M_FIRST_HIGH_PCT_B  = 1.0   # First high should tag upper band (%b ≥ 1)
M3_M_SECOND_HIGH_PCT_B = 0.8   # Second high %b LOWER than first (%b < 0.8)
M3_M_PRICE_TOLERANCE    = 0.03  # Second high within 3% of first high (or higher)

# MFI divergence thresholds
M3_MFI_DIVERGE_THRESHOLD = 5   # MFI must differ by at least 5 points

# ─────────────────────────────────────────────────────────────────
#  METHOD IV — WALKING THE BANDS (strong trend continuation)
#  Book ref: "Tags of the band are just that — tags, not signals.
#             When walking, each tag confirms the trend."
# ─────────────────────────────────────────────────────────────────

M4_WALK_MIN_TOUCHES     = 3     # Min consecutive upper/lower band touches
M4_WALK_LOOKBACK        = 10    # Bars to check for walk pattern
M4_WALK_TOUCH_TOLERANCE = 0.005  # Price within 0.5% of band = "touch"
M4_WALK_PCT_B_UPPER     = 0.85   # Walking upper: %b consistently > 0.85
M4_WALK_PCT_B_LOWER     = 0.15   # Walking lower: %b consistently < 0.15
M4_WALK_BB_MID_PULLBACK = True   # Allow pullback to middle band during walk

# ─────────────────────────────────────────────────────────────────
#  DISPLAY
# ─────────────────────────────────────────────────────────────────

STRATEGY_NAMES = {
    "M1": "Method I — Volatility Breakout (Squeeze)",
    "M2": "Method II — Trend Following",
    "M3": "Method III — Reversals (W-Bottoms / M-Tops)",
    "M4": "Method IV — Walking the Bands",
}

STRATEGY_DESCRIPTIONS = {
    "M1": (
        "The squeeze play — wait for Bollinger Bands to narrow to their tightest point "
        "(BandWidth at 6-month low), then buy when price explodes above the upper band "
        "with volume and money flow confirmation. This is the 'loaded spring' approach."
    ),
    "M2": (
        "Uses %b (where price sits within the bands) combined with MFI (Money Flow Index) "
        "to identify trend continuations. When %b is high AND MFI confirms, the trend is "
        "strong. When they diverge, the trend is weakening. Based on Chapter 16 of the book."
    ),
    "M3": (
        "Identifies classic reversal patterns: W-Bottoms (double bottom where the second low "
        "holds above the lower band — a buy signal) and M-Tops (double top where the second "
        "high fails to reach the upper band — a sell signal). The key insight from the book: "
        "the first touch can be outside the band, but the second touch MUST be inside."
    ),
    "M4": (
        "During very strong trends, price 'walks' along the upper or lower Bollinger Band, "
        "repeatedly tagging it. The book emphasises: tags are NOT signals to sell — they CONFIRM "
        "the trend. A walk along the upper band is bullish; along the lower band is bearish. "
        "Exit only when price pulls back to the middle band and fails to resume the walk."
    ),
}
