"""
top_picks/config.py — Configuration for the Top 5 Picks Ranking Engine
═══════════════════════════════════════════════════════════════════════

SCORING: 5 components — BB Strategy, TA, Triple Conviction, Brooks PA, Fundamentals.
"""

# ═══════════════════════════════════════════════════════════════
# COMPOSITE SCORE WEIGHTS (must sum to 1.0)
# ═══════════════════════════════════════════════════════════════

WEIGHTS = {
    "bb_strategy":      0.30,   # 30% — BB pattern confidence
    "ta_score":         0.20,   # 20% — Murphy's 6-category TA
    "triple_score":     0.15,   # 15% — BB+TA+PA cross-validation
    "brooks_pa":        0.20,   # 20% — Brooks PA engine (v3)
    "fundamental":      0.15,   # 15% — Company quality (valuation+profitability+growth+stability)
}

# Maximum PA score range for normalisation
PA_MAX_SCORE = 100

# ═══════════════════════════════════════════════════════════════
# FILTERING THRESHOLDS
# ═══════════════════════════════════════════════════════════════

MIN_BB_CONFIDENCE = 30
MIN_DATA_BARS = 50
MAX_DEEP_ANALYSIS = 1500
MIN_COMPOSITE_SCORE = 30.0

# ═══════════════════════════════════════════════════════════════
# OUTPUT
# ═══════════════════════════════════════════════════════════════

TOP_N = 5

# ═══════════════════════════════════════════════════════════════
# TRIPLE ENGINE NORMALISATION
# ═══════════════════════════════════════════════════════════════

TRIPLE_MAX_SCORE = 425
TRIPLE_MIN_SCORE = -425

# ═══════════════════════════════════════════════════════════════
# PARALLEL PROCESSING
# ═══════════════════════════════════════════════════════════════

MAX_WORKERS = 16

# ═══════════════════════════════════════════════════════════════
# CAPITAL
# ═══════════════════════════════════════════════════════════════

DEFAULT_CAPITAL = 500000

# ═══════════════════════════════════════════════════════════════
# VIX REGIME
# ═══════════════════════════════════════════════════════════════

VIX_CAUTION_THRESHOLD   = 15.0
VIX_DEFENSIVE_THRESHOLD = 22.0
VIX_CAUTION_MIN_SCORE   = 45.0
VIX_DEFENSIVE_METHODS   = ["M2"]

# ═══════════════════════════════════════════════════════════════
# FUNDAMENTAL FLOOR GATE
# ═══════════════════════════════════════════════════════════════

FUNDAMENTAL_FLOOR_SCORE  = 35
FUNDAMENTAL_FLOOR_SIGNAL = "AVOID"

# ═══════════════════════════════════════════════════════════════
# HOLD PERIOD GUIDANCE (display only)
# ═══════════════════════════════════════════════════════════════

HOLD_PERIOD_MAP = {
    "M1": {"days": "15-20", "stop": "SAR"},
    "M2": {"days": "20+",   "stop": "Lower BB"},
    "M3": {"days": "10-15", "stop": "Lower BB"},
    "M4": {"days": "20+",   "stop": "20-day SMA"},
}
