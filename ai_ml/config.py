"""
ai_ml/config.py — Configuration for the AI/ML layer.
"""
import os

_ROOT = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(_ROOT, "models")
os.makedirs(MODELS_DIR, exist_ok=True)

SIGNAL_FILTER_MODEL = os.path.join(MODELS_DIR, "signal_filter.joblib")
METHOD_ROUTER_DATA  = os.path.join(MODELS_DIR, "method_router.json")
TRAINING_DATA_FILE  = os.path.join(MODELS_DIR, "training_data.parquet")

CSV_DIR = os.path.join(os.path.dirname(_ROOT), "stock_csv")

# ML Signal Filter
ML_CONFIDENCE_THRESHOLD = 0.55   # minimum ML probability to flag as "ML_PASS"
ML_FEATURES = [
    "bbw", "rsi14", "atr14_pct", "vol_ratio", "close_vs_sma20",
    "close_vs_upper", "close_vs_lower", "sma20_slope_5d",
    "rsi14_slope_5d", "bbw_percentile_60d", "vol_trend_5d",
    "price_momentum_10d", "price_momentum_20d", "atr14_percentile_60d",
    "method",
]
ML_CATEGORICAL_FEATURES = ["method"]

# Correlation Guard
CORRELATION_WINDOW = 60          # trading days for pairwise correlation
CORRELATION_THRESHOLD = 0.70     # above this = "correlated pair"

# Position Sizing (Vince integration)
DEFAULT_CAPITAL = 500_000        # ₹5L default
MAX_SINGLE_POSITION_PCT = 0.25   # never >25% in one stock
MIN_SINGLE_POSITION_PCT = 0.05   # at least 5% if you take a position

# Market Regime Filter
NIFTY_TICKER = "^NSEI"
REGIME_VIX_BULL_THRESHOLD = 18
REGIME_CONFIDENCE_FACTORS = {
    "STRONG_BULL": 1.15, "BULL": 1.05, "NEUTRAL": 1.0,
    "BEAR": 0.85, "STRONG_BEAR": 0.70,
}
REGIME_BREADTH_SAMPLE = 200

# Exit Intelligence
EXIT_URGENCY_THRESHOLDS = {"HOLD": 25, "MONITOR": 45, "TIGHTEN_STOP": 65}

# Feedback Loop
FEEDBACK_DB = os.path.join(os.path.dirname(_ROOT), "data", "app.db")
FEEDBACK_EXPIRY_DAYS = 30
FEEDBACK_MIN_RETRAIN = 50
