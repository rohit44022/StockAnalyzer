"""
top_picks/config.py — Configuration for the Top 5 Picks Ranking Engine
═══════════════════════════════════════════════════════════════════════

HOW THE COMPOSITE SCORE WORKS (for non-technical readers):
──────────────────────────────────────────────────────────

Imagine you're hiring someone. You wouldn't hire based on just ONE quality.
You'd look at: skills, experience, references, culture fit, salary expectations.

That's exactly what this system does for stocks. Instead of picking a stock
just because the Bollinger Band said "BUY" (one signal), we check:

  1. BB Strategy Score (20%)  — Does the Bollinger Band pattern look strong?
     Think of this as: "Does this stock have a good resume?"

  2. TA Score (20%)           — Does Murphy's Technical Analysis agree?
     Think of this as: "Did the reference check go well?"

  3. Triple Score (15%)       — When we combine BB + TA + PA, is there agreement?
     Think of this as: "Do all the interviewers agree on this candidate?"

  4. Price Action Score (15%) — Does Al Brooks' bar-by-bar analysis agree?
     Think of this as: "Does the on-site interview confirm the resume?"

  5. Risk/Reward (15%)        — Is the potential profit much bigger than the risk?
     Think of this as: "Is the salary reasonable for the value they bring?"

  6. Signal Agreement (10%)   — Do ALL systems point the same direction?
     Think of this as: "Does everyone's gut feel align?"

  7. Data Quality (5%)        — Is our information fresh and reliable?
     Think of this as: "Are we using a recent, verified resume?"

Each component is scored 0-100, then multiplied by its weight.
Final Composite Score = sum of all weighted components = 0 to 100.

A stock scoring 85+ is an EXCELLENT pick. 70-85 is GOOD. Below 50 is WEAK.
"""

# ═══════════════════════════════════════════════════════════════
# COMPOSITE SCORE WEIGHTS
# ═══════════════════════════════════════════════════════════════
# These weights MUST sum to 1.0 (i.e. 100%).
# Changing these lets you emphasise different aspects.
# For example, if you trust BB more than TA, increase BB_STRATEGY_WEIGHT.

WEIGHTS = {
    "bb_strategy":      0.20,   # 20% — How strong is the BB pattern?
    "ta_score":         0.20,   # 20% — Murphy's technical analysis verdict
    "triple_score":     0.15,   # 15% — Combined BB+TA+PA cross-validation score
    "pa_score":         0.15,   # 15% — Al Brooks Price Action analysis
    "risk_reward":      0.15,   # 15% — Potential profit vs potential loss
    "signal_agreement": 0.10,   # 10% — Do ALL engines agree on direction?
    "data_quality":     0.05,   # 5%  — Is the data fresh and reliable?
}

# Maximum PA score (from -100 to +100, so range = 200)
PA_MAX_SCORE = 100

# ═══════════════════════════════════════════════════════════════
# FILTERING THRESHOLDS
# ═══════════════════════════════════════════════════════════════
# Before running deep analysis, we pre-filter stocks to save time.
# Stocks below these thresholds are SKIPPED (not worth analyzing deeply).

# Minimum BB confidence to qualify for deep analysis.
# A stock with 20% BB confidence is barely matching the pattern — skip it.
# A stock with 40%+ is at least moderately fitting the pattern — analyze it.
MIN_BB_CONFIDENCE = 30

# Minimum number of data bars required (about 50 trading days = ~2.5 months).
# Stocks with less data can't produce reliable technical analysis.
MIN_DATA_BARS = 50

# Maximum number of stocks to deeply analyze (prevents system from
# running for 30+ minutes if 500 stocks pass the initial scan).
# The system will take the top N by BB confidence and analyze those.
MAX_DEEP_ANALYSIS = 100

# ═══════════════════════════════════════════════════════════════
# OUTPUT SETTINGS
# ═══════════════════════════════════════════════════════════════

# How many top picks to return (the "Top N").
TOP_N = 5

# Minimum composite score for a stock to be included in the top picks.
# Even if only 3 stocks score above this threshold, we return just 3.
# We never recommend a stock we're not confident about.
MIN_COMPOSITE_SCORE = 30.0

# ═══════════════════════════════════════════════════════════════
# RISK/REWARD SCORING THRESHOLDS
# ═══════════════════════════════════════════════════════════════
# These translate the raw risk:reward ratio into a 0-100 score.
#
# THE IDEA: Professional traders require at LEAST a 1:2 risk:reward ratio.
# That means: "For every ₹1 I might lose, I should potentially gain ₹2."
# Anything below 1:1 means you could lose MORE than you gain — very bad.
#
# Scoring:
#   R:R >= 4.0  →  100 (excellent — you could gain 4x what you risk)
#   R:R >= 3.0  →  90
#   R:R >= 2.5  →  80
#   R:R >= 2.0  →  70  (professional standard — minimum acceptable)
#   R:R >= 1.5  →  55
#   R:R >= 1.0  →  35  (break-even territory — not great)
#   R:R <  1.0  →  15  (danger — possible loss exceeds possible gain)

RR_SCORE_MAP = [
    (4.0, 100),
    (3.0,  90),
    (2.5,  80),
    (2.0,  70),
    (1.5,  55),
    (1.0,  35),
    (0.0,  15),
]

# ═══════════════════════════════════════════════════════════════
# DATA QUALITY SCORING
# ═══════════════════════════════════════════════════════════════
# How many trading days old the data can be before we penalize it.
#
# Fresh data (0-1 days old)  →  100 (we trust this completely)
# 2 days old                 →  85
# 3-5 days old               →  60  (getting stale, signals less reliable)
# 6-10 days old              →  30  (signals are UNRELIABLE for live trading)
# 10+ days old               →  10  (almost useless — pure gamble)

FRESHNESS_SCORE_MAP = [
    (1,  100),
    (2,   85),
    (5,   60),
    (10,  30),
    (999, 10),
]

# ═══════════════════════════════════════════════════════════════
# TRIPLE ENGINE SCORING NORMALIZATION
# ═══════════════════════════════════════════════════════════════
# The triple engine returns scores from -425 to +425.
# Positive max = bb:100 + ta:100 + pa:100 + cross-validation:125 = 425
# Negative min = bb:-100 + ta:-100 + pa:-100 + cross-validation:-125 = -425
# Cross-validation includes Wyckoff (±30) + Dalton Market Profile (±35).

TRIPLE_MAX_SCORE = 425
TRIPLE_MIN_SCORE = -425

# ═══════════════════════════════════════════════════════════════
# PARALLEL PROCESSING
# ═══════════════════════════════════════════════════════════════
# Number of worker threads for analyzing stocks in parallel.
# More threads = faster analysis but more CPU/memory usage.
# 4-6 is a good balance for most machines.

MAX_WORKERS = 6

# ═══════════════════════════════════════════════════════════════
# TRADING CAPITAL (default)
# ═══════════════════════════════════════════════════════════════
# Used for position sizing and risk calculations.
# Users can override this in the API request.

DEFAULT_CAPITAL = 500000  # ₹5,00,000 (~$6,000 USD)
