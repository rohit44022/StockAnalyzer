"""
ai_ml/conviction_scorer.py — ML Conviction Score v2 for portfolio positions.

v2: LGBMRegressor on r_multiple + LogisticRegression ensemble, 51 features,
    confidence intervals via quantile regression. Trained on max NSE history.

Usage:
  Training:  python3 -m ai_ml.conviction_scorer
  Inference: from ai_ml.conviction_scorer import score_conviction
             result = score_conviction(df_with_indicators, "M2")
"""
from __future__ import annotations

import json
import logging
import math
import os
from typing import Optional

import joblib
import numpy as np
import pandas as pd

from ai_ml.config import (
    CONVICTION_MODEL, CONVICTION_MEDIANS, TRAINING_DATA_FILE,
)

logger = logging.getLogger(__name__)

_model = None
_lr = None
_iso = None
_q_lo = None
_q_hi = None
_imputer = None
_scaler = None
_medians: dict | None = None

# ─────────────────────────────────────────────────────────────
#  Feature lists (must match training exactly)
# ─────────────────────────────────────────────────────────────

BASE_FEATURES = [
    "bbw", "rsi14", "atr14_pct", "vol_ratio",
    "close_vs_sma20", "close_vs_upper", "close_vs_lower",
    "sma20_slope_5d", "rsi14_slope_5d", "bbw_percentile_60d",
    "vol_trend_5d", "price_momentum_10d", "price_momentum_20d",
    "atr14_percentile_60d", "percent_b", "cmf", "mfi",
    "ii_pct", "ad_pct", "vwmacd_hist", "vwmacd_signal",
    "expansion_end",
    "bbw_roc_5d", "rsi_bb_divergence",
    "kc_squeeze_intensity", "rsi_norm", "mfi_norm",
    # v2: micro lookbacks
    "price_momentum_1d", "price_momentum_3d", "rsi14_slope_3d", "vol_trend_3d",
    # v2: macro lookbacks
    "price_momentum_60d", "price_momentum_90d", "sma20_slope_20d", "bbw_percentile_120d",
    # v2: sector relative strength
    "sector_rs", "stock_vs_sector_rs",
]

# Dropped via SHAP: expansion_up, expansion_down, rsi_oversold, rsi_overbought,
# band_mom_align, bull_count, consensus_strength (all < 0.001 mean |SHAP|)

ENGINEERED_FEATURES = [
    "pctb_x_mfi", "pctb_x_cmf", "pctb_x_rsi",
    "squeeze_intensity", "squeeze_x_vol",
    "vol_mom_div", "mom_accel", "mfi_cmf_div",
    "bbw_vol_expansion",
]

ALL_FEATURES = BASE_FEATURES + ENGINEERED_FEATURES

# Human-readable labels + formatting for driver explanations
# (label, format_fn, higher_is_bullish)
FEATURE_META = {
    "bbw":               ("Band Width",        lambda v: f"{v:.2f}",   False),
    "rsi14":             ("RSI-14",            lambda v: f"{v:.1f}",   True),
    "atr14_pct":         ("ATR %",             lambda v: f"{v:.2f}%",  False),
    "vol_ratio":         ("Volume Ratio",      lambda v: f"{v:.2f}x",  True),
    "close_vs_sma20":    ("Price vs SMA20",    lambda v: f"{v:+.1f}%", True),
    "close_vs_upper":    ("Price vs Upper BB", lambda v: f"{v:+.1f}%", True),
    "close_vs_lower":    ("Price vs Lower BB", lambda v: f"{v:+.1f}%", True),
    "sma20_slope_5d":    ("SMA20 Slope (5d)",  lambda v: f"{v:+.2f}%", True),
    "rsi14_slope_5d":    ("RSI Slope (5d)",    lambda v: f"{v:+.1f}",  True),
    "bbw_percentile_60d":("BBW Percentile",    lambda v: f"{v:.0f}%ile", False),
    "vol_trend_5d":      ("Volume Trend (5d)", lambda v: f"{v:+.0f}%", True),
    "price_momentum_10d":("Momentum (10d)",    lambda v: f"{v*100:+.1f}%", True),
    "price_momentum_20d":("Momentum (20d)",    lambda v: f"{v*100:+.1f}%", True),
    "atr14_percentile_60d":("ATR Percentile",  lambda v: f"{v:.0f}%ile", False),
    "percent_b":         ("%B",                lambda v: f"{v:.2f}",   True),
    "cmf":               ("Chaikin MF",        lambda v: f"{v:+.3f}",  True),
    "mfi":               ("Money Flow",        lambda v: f"{v:.1f}",   True),
    "ii_pct":            ("Intraday Intensity", lambda v: f"{v:+.1f}%", True),
    "ad_pct":            ("A/D Pct",           lambda v: f"{v:+.1f}%", True),
    "vwmacd_hist":       ("VWMACD Hist",       lambda v: f"{v:+.2f}",  True),
    "bbw_roc_5d":        ("BBW Change (5d)",   lambda v: f"{v*100:+.1f}%", False),
    "rsi_bb_divergence": ("RSI-BB Divergence", lambda v: f"{v:+.3f}",  True),
    "pctb_x_mfi":        ("%B × MFI",          lambda v: f"{v:.3f}",   True),
    "pctb_x_cmf":        ("%B × CMF",          lambda v: f"{v:+.3f}",  True),
    "pctb_x_rsi":        ("%B × RSI",          lambda v: f"{v:.3f}",   True),
    "squeeze_intensity": ("Squeeze Intensity", lambda v: f"{v:.2f}",   True),
    "squeeze_x_vol":     ("Squeeze × Vol",     lambda v: f"{v:.2f}",   True),
    "vol_mom_div":       ("Vol-Mom Divergence", lambda v: f"{v:+.2f}", True),
    "mom_accel":         ("Momentum Accel",    lambda v: f"{v*100:+.2f}%", True),
    "mfi_cmf_div":       ("MFI-CMF Divergence",lambda v: f"{v:+.3f}",  True),
    "bbw_vol_expansion": ("BBW-Vol Expansion", lambda v: f"{v:+.3f}",  True),
    # v2 features
    "vwmacd_signal":     ("VWMACD Signal",    lambda v: f"{v:+.2f}",  True),
    "expansion_end":     ("Expansion End",    lambda v: "Yes" if v else "No", False),
    "kc_squeeze_intensity": ("KC Squeeze",    lambda v: f"{v:.2f}",   True),
    "rsi_norm":          ("RSI Normalized",   lambda v: f"{v:+.2f}σ", True),
    "mfi_norm":          ("MFI Normalized",   lambda v: f"{v:+.2f}σ", True),
    "price_momentum_1d": ("Momentum (1d)",    lambda v: f"{v:+.1f}%", True),
    "price_momentum_3d": ("Momentum (3d)",    lambda v: f"{v:+.1f}%", True),
    "rsi14_slope_3d":    ("RSI Slope (3d)",   lambda v: f"{v:+.1f}",  True),
    "vol_trend_3d":      ("Volume Trend (3d)",lambda v: f"{v:+.0f}%", True),
    "price_momentum_60d":("Momentum (60d)",   lambda v: f"{v:+.1f}%", True),
    "price_momentum_90d":("Momentum (90d)",   lambda v: f"{v:+.1f}%", True),
    "sma20_slope_20d":   ("SMA20 Slope (20d)",lambda v: f"{v:+.2f}%", True),
    "bbw_percentile_120d":("BBW %ile (120d)", lambda v: f"{v:.0f}%ile", False),
    "sector_rs":         ("Sector vs Nifty", lambda v: f"{v:+.1f}%",  True),
    "stock_vs_sector_rs":("Stock vs Sector", lambda v: f"{v:+.1f}%",  True),
}


def _explain_feature(feat: str, val, direction: str) -> str:
    """Generate a plain-English sentence explaining what this feature value means."""
    b = direction == "bullish"
    v = val

    if feat == "cmf":
        if v > 0.15:
            return "Strong buying pressure from institutional investors — money is flowing into this stock."
        elif v > 0:
            return "Mild buying pressure — more money flowing in than out, a positive sign."
        elif v > -0.15:
            return "Mild selling pressure — slightly more money flowing out than in."
        else:
            return "Heavy selling pressure — institutions appear to be offloading this stock."
    if feat == "mfi":
        if v > 80:
            return "Money Flow Index is very high — heavy buying activity, but could be overbought."
        elif v > 60:
            return "Strong money flow — buyers are in control, supporting the current price."
        elif v > 40:
            return "Neutral money flow — no strong buying or selling dominance."
        elif v > 20:
            return "Weak money flow — sellers have more control, reducing conviction."
        else:
            return "Very low money flow — extremely weak buying interest."
    if feat == "rsi14":
        if v > 70:
            return f"RSI at {v:.0f} — stock is in overbought territory, which may limit further upside."
        elif v > 55:
            return f"RSI at {v:.0f} — healthy bullish momentum, price has room to run."
        elif v > 45:
            return f"RSI at {v:.0f} — neutral momentum, no strong directional bias."
        elif v > 30:
            return f"RSI at {v:.0f} — weakening momentum, bears are gaining ground."
        else:
            return f"RSI at {v:.0f} — oversold territory, a bounce could be brewing."
    if feat == "vol_ratio":
        if v > 2:
            return f"Volume is {v:.1f}x the average — unusual activity, something is happening."
        elif v > 1.2:
            return f"Volume is above average ({v:.1f}x) — the current move has participation."
        elif v > 0.8:
            return "Volume is near average — no unusual activity to report."
        else:
            return f"Volume is below average ({v:.1f}x) — the current price action lacks conviction."
    if feat == "vol_trend_5d":
        if v > 50:
            return f"Volume surged {v:.0f}% over 5 days — growing interest from traders."
        elif v > 10:
            return f"Volume rising {v:.0f}% over 5 days — increasing participation."
        elif v > -10:
            return "Volume is stable over the past 5 days."
        else:
            return f"Volume dropped {abs(v):.0f}% over 5 days — fading interest."
    if feat == "vwmacd_hist":
        if v > 0:
            return "Volume-weighted MACD is positive — buying momentum confirmed by volume."
        else:
            return "Volume-weighted MACD is negative — selling pressure backed by volume."
    if feat == "percent_b":
        if v > 0.8:
            return f"Price is near the upper Bollinger Band (%B={v:.2f}) — strong upward positioning."
        elif v > 0.5:
            return f"Price is in the upper half of Bollinger Bands (%B={v:.2f}) — bullish positioning."
        elif v > 0.2:
            return f"Price is in the lower half of Bollinger Bands (%B={v:.2f}) — bearish positioning."
        else:
            return f"Price is near the lower Bollinger Band (%B={v:.2f}) — oversold but risky."
    if feat == "close_vs_sma20":
        if v > 3:
            return f"Price is {v:.1f}% above the 20-day average — extended but trending up."
        elif v > 0:
            return f"Price is {v:.1f}% above the 20-day average — in a healthy uptrend."
        elif v > -3:
            return f"Price is {abs(v):.1f}% below the 20-day average — mildly weak."
        else:
            return f"Price is {abs(v):.1f}% below the 20-day average — significant weakness."
    if feat == "sma20_slope_5d":
        if v > 0.5:
            return f"The 20-day moving average is rising ({v:+.2f}%) — the trend is your friend."
        elif v > 0:
            return "The 20-day average is slowly rising — a mild uptrend."
        elif v > -0.5:
            return "The 20-day average is slowly falling — the trend is softening."
        else:
            return f"The 20-day average is falling ({v:.2f}%) — the trend has turned down."
    if feat == "rsi14_slope_5d":
        if v > 5:
            return f"RSI gained {v:.0f} points in 5 days — momentum is accelerating."
        elif v > 0:
            return "RSI is slowly improving — momentum is quietly building."
        elif v > -5:
            return "RSI is slowly declining — momentum is fading."
        else:
            return f"RSI dropped {abs(v):.0f} points in 5 days — momentum is collapsing."
    if feat == "price_momentum_10d":
        pct = v * 100
        if pct > 5:
            return f"Stock is up {pct:.1f}% over 10 days — strong short-term rally."
        elif pct > 0:
            return f"Stock is up {pct:.1f}% over 10 days — mild positive momentum."
        elif pct > -5:
            return f"Stock is down {abs(pct):.1f}% over 10 days — mild negative momentum."
        else:
            return f"Stock is down {abs(pct):.1f}% over 10 days — significant selling pressure."
    if feat == "price_momentum_20d":
        pct = v * 100
        if pct > 5:
            return f"Up {pct:.1f}% over 20 days — sustained uptrend over the medium term."
        elif pct > 0:
            return f"Up {pct:.1f}% over 20 days — gradual appreciation."
        else:
            return f"Down {abs(pct):.1f}% over 20 days — the medium-term trend is negative."
    if feat == "bbw_percentile_60d":
        if v < 20:
            return f"Bollinger Bands are very tight ({v:.0f}th percentile) — a squeeze is building, expect a big move soon."
        elif v < 40:
            return f"Bands are moderately tight ({v:.0f}th percentile) — volatility is compressed."
        elif v < 70:
            return "Band width is average — no unusual volatility compression or expansion."
        else:
            return f"Bands are wide ({v:.0f}th percentile) — high volatility, the move may be exhausting."
    if feat == "atr14_pct":
        if v > 4:
            return f"Daily range is {v:.1f}% of price — very volatile, bigger moves expected."
        elif v > 2:
            return f"Daily range is {v:.1f}% of price — moderate volatility."
        else:
            return f"Daily range is {v:.1f}% of price — calm, low-volatility phase."
    if feat == "atr14_percentile_60d":
        if v < 25:
            return f"Volatility is unusually low ({v:.0f}th percentile) — the stock is coiled for a move."
        elif v > 75:
            return f"Volatility is elevated ({v:.0f}th percentile) — big swings are the norm right now."
        else:
            return "Volatility is in its normal range."
    if feat == "ii_pct":
        if v > 0:
            return "Intraday buying pressure is positive — closes are happening near daily highs."
        else:
            return "Intraday selling pressure — closes are happening near daily lows."
    if feat == "ad_pct":
        if v > 0:
            return "Accumulation is positive — shares are being accumulated over time."
        else:
            return "Distribution is active — shares are being sold down."
    if feat == "squeeze_intensity":
        if v > 0.7:
            return "Bands are extremely tight — the stock is coiled like a spring, ready for a big move."
        elif v > 0.4:
            return "Moderate squeeze — volatility is compressed, a directional move is likely."
        else:
            return "Low squeeze — bands are relatively wide, no compression setup."
    if feat == "pctb_x_mfi":
        if v > 0.5:
            return "Strong alignment between price position and money flow — buyers are in control at the right level."
        elif v > 0.2:
            return "Decent alignment between price and money flow."
        else:
            return "Weak price-flow alignment — price position doesn't match money flow."
    if feat == "pctb_x_cmf":
        if v > 0.1:
            return "Price position is confirmed by Chaikin money flow — smart money agrees with the price level."
        elif v > -0.1:
            return "Neutral alignment between price and Chaikin flow."
        else:
            return "Price position contradicts Chaikin flow — a divergence that reduces conviction."
    if feat == "mom_accel":
        pct = v * 100
        if pct > 1:
            return f"Momentum is accelerating (+{pct:.1f}%) — the move is gaining speed."
        elif pct > -1:
            return "Momentum is steady — neither accelerating nor decelerating."
        else:
            return f"Momentum is decelerating ({pct:.1f}%) — the move is losing steam."
    if feat == "vwmacd_signal":
        if v > 0:
            return "VWMACD signal line is positive — the volume-weighted trend favours buyers."
        else:
            return "VWMACD signal line is negative — the volume-weighted trend favours sellers."
    if feat == "expansion_end":
        if v:
            return "Band expansion just ended — the breakout move may be exhausting, watch for reversal."
        return "No expansion end signal — current trend phase continues."
    if feat == "kc_squeeze_intensity":
        if v > 0.6:
            return f"Keltner squeeze is very tight ({v:.2f}) — extreme compression, big move imminent."
        elif v > 0.3:
            return f"Moderate Keltner squeeze ({v:.2f}) — volatility compressed, directional move likely."
        elif v > 0:
            return "Mild Keltner squeeze — some compression but not extreme."
        else:
            return "No Keltner squeeze — bands are not compressed."
    if feat == "rsi_norm":
        if v > 1.5:
            return f"RSI is {v:.1f}σ above its mean — unusually strong momentum, potentially overextended."
        elif v > 0:
            return f"RSI is {v:.1f}σ above its mean — above-average momentum."
        elif v > -1.5:
            return f"RSI is {abs(v):.1f}σ below its mean — below-average momentum."
        else:
            return f"RSI is {abs(v):.1f}σ below its mean — extremely weak, potential bounce setup."
    if feat == "mfi_norm":
        if v > 1.5:
            return f"Money Flow is {v:.1f}σ above its mean — heavy buying vs recent history."
        elif v > 0:
            return f"Money Flow is above its recent average ({v:+.1f}σ)."
        elif v > -1.5:
            return f"Money Flow is below its recent average ({v:+.1f}σ)."
        else:
            return f"Money Flow is {abs(v):.1f}σ below mean — very weak relative to recent history."
    if feat in ("price_momentum_1d", "price_momentum_3d"):
        days = "1 day" if "1d" in feat else "3 days"
        if v > 2:
            return f"Up {v:.1f}% in {days} — sharp short-term rally."
        elif v > 0:
            return f"Up {v:.1f}% in {days} — mild positive."
        elif v > -2:
            return f"Down {abs(v):.1f}% in {days} — mild pullback."
        else:
            return f"Down {abs(v):.1f}% in {days} — sharp short-term drop."
    if feat in ("price_momentum_60d", "price_momentum_90d"):
        days = "60" if "60d" in feat else "90"
        if v > 15:
            return f"Up {v:.0f}% over {days} days — strong long-term uptrend."
        elif v > 0:
            return f"Up {v:.1f}% over {days} days — gradual appreciation."
        elif v > -15:
            return f"Down {abs(v):.1f}% over {days} days — moderate long-term weakness."
        else:
            return f"Down {abs(v):.0f}% over {days} days — significant long-term decline."
    if feat == "rsi14_slope_3d":
        if v > 5:
            return f"RSI gained {v:.0f} points in 3 days — rapid momentum buildup."
        elif v > 0:
            return "RSI rising over 3 days — short-term momentum improving."
        elif v > -5:
            return "RSI declining over 3 days — short-term momentum fading."
        else:
            return f"RSI dropped {abs(v):.0f} points in 3 days — rapid momentum collapse."
    if feat == "vol_trend_3d":
        if v > 50:
            return f"Volume surged {v:.0f}% in 3 days — very rapid participation increase."
        elif v > 0:
            return f"Volume up {v:.0f}% over 3 days — growing interest."
        else:
            return f"Volume down {abs(v):.0f}% over 3 days — declining interest."
    if feat == "sma20_slope_20d":
        if v > 2:
            return f"SMA20 rose {v:.1f}% over 20 days — strong medium-term uptrend confirmed."
        elif v > 0:
            return f"SMA20 up {v:.1f}% over 20 days — gradual uptrend."
        elif v > -2:
            return f"SMA20 down {abs(v):.1f}% over 20 days — mild medium-term weakness."
        else:
            return f"SMA20 fell {abs(v):.1f}% over 20 days — clear downtrend."
    if feat == "bbw_percentile_120d":
        if v < 20:
            return f"Band width at {v:.0f}th percentile of 120 days — extremely tight, big move ahead."
        elif v > 80:
            return f"Band width at {v:.0f}th percentile of 120 days — very wide, the move may be exhausting."
        else:
            return f"Band width at {v:.0f}th percentile of 120 days — within normal range."
    if feat == "sector_rs":
        if v > 2:
            return f"The sector is outperforming Nifty by {v:.1f}% — sector tailwind supports the trade."
        elif v > -2:
            return "The sector is performing in line with Nifty — neutral sector impact."
        else:
            return f"The sector is underperforming Nifty by {abs(v):.1f}% — sector headwind hurts conviction."
    if feat == "stock_vs_sector_rs":
        if v > 3:
            return f"Stock is outperforming its sector by {v:.1f}% — relative strength leader."
        elif v > -3:
            return "Stock is performing in line with its sector."
        else:
            return f"Stock is underperforming its sector by {abs(v):.1f}% — lagging peers."
    # Fallback
    what = "positive" if b else "negative"
    return f"{FEATURE_META[feat][0]} reading is {what} for the trade outlook."


def _build_narrative(score: float, label: str, feats: dict,
                     top_drivers: list) -> str:
    """Build a 2-3 sentence layman narrative explaining the ML conviction score."""
    bulls = [d for d in top_drivers if d["direction"] == "bullish"]
    bears = [d for d in top_drivers if d["direction"] == "bearish"]

    # Opening sentence based on score level
    if score >= 80:
        opening = (f"The ML model is highly confident ({score:.0f}%) in this trade. "
                   "Multiple indicators align strongly in favour of this position.")
    elif score >= 60:
        opening = (f"The ML model shows good confidence ({score:.0f}%). "
                   "The majority of signals lean positive, though some caution is warranted.")
    elif score >= 45:
        opening = (f"The ML model is neutral-to-moderate ({score:.0f}%). "
                   "Signals are mixed — some point up, others point down.")
    elif score >= 30:
        opening = (f"The ML model shows weak confidence ({score:.0f}%). "
                   "More signals are leaning negative than positive.")
    else:
        opening = (f"The ML model has low confidence ({score:.0f}%) in this trade. "
                   "The pattern of indicators resembles past losing trades.")

    # Middle: what's driving it
    mid_parts = []
    if bulls:
        bull_explains = [d["explain"] for d in bulls[:2]]
        mid_parts.append("On the positive side: " + " ".join(bull_explains))
    if bears:
        bear_explains = [d["explain"] for d in bears[:2]]
        mid_parts.append("On the negative side: " + " ".join(bear_explains))

    middle = " ".join(mid_parts) if mid_parts else ""

    # Closing advice based on level
    if score >= 70:
        closing = "Overall, the data supports holding this position with conviction."
    elif score >= 40:
        closing = "Monitor closely — the trade could go either way from here."
    else:
        closing = "Consider tightening your stop or reducing position size."

    return f"{opening} {middle} {closing}".strip()


def _compute_drivers(feats: dict, model) -> tuple[list, str, str]:
    """Return (top 4 drivers with explanations, summary, narrative)."""
    importances = model.feature_importances_
    imp_map = dict(zip(ALL_FEATURES, importances))
    total_imp = sum(importances) or 1

    drivers = []
    for feat in ALL_FEATURES:
        val = feats.get(feat)
        if val is None:
            continue
        meta = FEATURE_META.get(feat)
        if not meta:
            continue
        label, fmt_fn, higher_bullish = meta
        median = (_medians or {}).get(feat, 0)
        imp = imp_map.get(feat, 0) / total_imp
        # Binary features: deviation is just 0 or 1
        if feat in ("expansion_end",):
            dev = abs(val - median)
        else:
            dev = abs(val - median) / (abs(median) + 0.01)
        weight = imp * min(dev, 10)

        above_median = val > median
        bullish = above_median if higher_bullish else not above_median
        direction = "bullish" if bullish else "bearish"
        drivers.append({
            "name": label,
            "value": fmt_fn(val),
            "direction": direction,
            "weight": round(weight, 4),
            "explain": _explain_feature(feat, val, direction),
        })

    drivers.sort(key=lambda d: d["weight"], reverse=True)
    top = drivers[:6]

    bulls = [d["name"] for d in top if d["direction"] == "bullish"][:2]
    bears = [d["name"] for d in top if d["direction"] == "bearish"][:2]
    parts = []
    if bulls:
        parts.append(f"{' and '.join(bulls)} {'are' if len(bulls)>1 else 'is'} supporting conviction")
    if bears:
        parts.append(f"{' and '.join(bears)} {'are' if len(bears)>1 else 'is'} weighing against")
    summary = ". ".join(parts) + "." if parts else "No dominant drivers identified."

    top6 = top[:6]
    return top6, summary, ""


# ─────────────────────────────────────────────────────────────
#  Feature engineering (shared between training and inference)
# ─────────────────────────────────────────────────────────────

def _add_engineered(df: pd.DataFrame) -> pd.DataFrame:
    """Add 9 engineered features to a DataFrame that already has base features."""
    df = df.copy()
    df["pctb_x_mfi"] = df["percent_b"] * df["mfi"] / 100
    df["pctb_x_cmf"] = df["percent_b"] * df["cmf"]
    df["pctb_x_rsi"] = df["percent_b"] * df["rsi14"] / 100
    df["squeeze_intensity"] = 1 - df["bbw_percentile_60d"] / 100
    df["squeeze_x_vol"] = df["squeeze_intensity"] * df["vol_ratio"]
    df["vol_mom_div"] = df["vol_ratio"] * np.sign(df["price_momentum_10d"])
    df["mom_accel"] = df["price_momentum_10d"] - df["price_momentum_20d"]
    df["mfi_cmf_div"] = (df["mfi"] / 100) - ((df["cmf"] + 1) / 2)
    df["bbw_vol_expansion"] = df["bbw_roc_5d"] * df["vol_ratio"]
    return df


# ─────────────────────────────────────────────────────────────
#  Live feature extraction (from compute_all_indicators() df)
# ─────────────────────────────────────────────────────────────

def _safe(v):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return None
    return float(v)


def _compute_features(df: pd.DataFrame, method: str,
                      ticker: str | None = None) -> Optional[dict]:
    """Extract features from a DataFrame with indicators computed.
    Returns None if critical data is missing."""
    if df is None or len(df) < 60:
        return None

    try:
        row = df.iloc[-1]
        close = float(row["Close"])
        mid = float(row["BB_Mid"])
        upper = float(row["BB_Upper"])
        lower = float(row["BB_Lower"])
        if close == 0 or mid == 0 or pd.isna(close) or pd.isna(mid):
            return None

        atr = float(row["ATR"]) if "ATR" in df.columns else None
        vol = float(row["Volume"])
        vol_sma = float(row["Vol_SMA50"]) if not pd.isna(row["Vol_SMA50"]) else 1

        recent3 = df.tail(3)
        recent5 = df.tail(5)
        recent60 = df.tail(60)
        recent120 = df.tail(120)

        feats = {
            "bbw": _safe(row["BBW"]),
            "rsi14": _safe(row["RSI"]),
            "atr14_pct": _safe(atr / close * 100) if atr else None,
            "vol_ratio": _safe(vol / vol_sma) if vol_sma > 0 else None,
            "close_vs_sma20": _safe((close - mid) / mid * 100),
            "close_vs_upper": _safe((close - upper) / mid * 100),
            "close_vs_lower": _safe((close - lower) / mid * 100),
            "sma20_slope_5d": _safe(
                (float(recent5["BB_Mid"].iloc[-1]) - float(recent5["BB_Mid"].iloc[0]))
                / float(recent5["BB_Mid"].iloc[0]) * 100
            ) if len(recent5) >= 5 else None,
            "rsi14_slope_5d": _safe(
                float(recent5["RSI"].iloc[-1]) - float(recent5["RSI"].iloc[0])
            ) if len(recent5) >= 5 else None,
            "bbw_percentile_60d": _safe(
                recent60["BBW"].rank(pct=True).iloc[-1] * 100
            ) if len(recent60) >= 10 else None,
            "vol_trend_5d": _safe(
                (float(recent5["Volume"].iloc[-1]) - float(recent5["Volume"].iloc[0]))
                / float(recent5["Volume"].iloc[0]) * 100
            ) if len(recent5) >= 5 and float(recent5["Volume"].iloc[0]) > 0 else None,
            "price_momentum_10d": _safe(
                close / float(df["Close"].iloc[-11]) - 1
            ) if len(df) >= 11 else None,
            "price_momentum_20d": _safe(
                close / float(df["Close"].iloc[-21]) - 1
            ) if len(df) >= 21 else None,
            "atr14_percentile_60d": _safe(
                recent60["ATR"].rank(pct=True).iloc[-1] * 100
            ) if "ATR" in df.columns and len(recent60) >= 10 else None,
            "percent_b": _safe(row["Percent_B"]),
            "cmf": _safe(row["CMF"]),
            "mfi": _safe(row["MFI"]),
            "ii_pct": _safe(row.get("II_Pct")),
            "ad_pct": _safe(row.get("AD_Pct")),
            "vwmacd_hist": _safe(row.get("VWMACD_Hist")),
            "vwmacd_signal": _safe(row.get("VWMACD_Signal")),
            "expansion_up": float(bool(row.get("Expansion_Up", False))),
            "expansion_down": float(bool(row.get("Expansion_Down", False))),
            "expansion_end": float(bool(row.get("Expansion_End", False))),
            "bbw_roc_5d": _safe(
                (float(row["BBW"]) - float(df["BBW"].iloc[-6])) / float(df["BBW"].iloc[-6])
            ) if len(df) >= 6 and float(df["BBW"].iloc[-6]) > 0 else None,
            "rsi_bb_divergence": _safe(
                float(row["RSI"]) / 100 - float(row["Percent_B"])
            ),
            "kc_squeeze_intensity": _safe(row.get("KC_Squeeze_Intensity")),
            "rsi_norm": _safe(row.get("RSI_Norm")),
            "mfi_norm": _safe(row.get("MFI_Norm")),
            # v2: micro lookbacks
            "price_momentum_1d": _safe(
                (close / float(df["Close"].iloc[-2]) - 1) * 100
            ) if len(df) >= 2 else None,
            "price_momentum_3d": _safe(
                (close / float(df["Close"].iloc[-4]) - 1) * 100
            ) if len(df) >= 4 else None,
            "rsi14_slope_3d": _safe(
                float(recent3["RSI"].iloc[-1]) - float(recent3["RSI"].iloc[0])
            ) if len(recent3) >= 3 else None,
            "vol_trend_3d": _safe(
                (float(recent3["Volume"].iloc[-1]) - float(recent3["Volume"].iloc[0]))
                / float(recent3["Volume"].iloc[0]) * 100
            ) if len(recent3) >= 3 and float(recent3["Volume"].iloc[0]) > 0 else None,
            # v2: macro lookbacks
            "price_momentum_60d": _safe(
                (close / float(df["Close"].iloc[-61]) - 1) * 100
            ) if len(df) >= 61 else None,
            "price_momentum_90d": _safe(
                (close / float(df["Close"].iloc[-91]) - 1) * 100
            ) if len(df) >= 91 else None,
            "sma20_slope_20d": _safe(
                (float(df["BB_Mid"].iloc[-1]) - float(df["BB_Mid"].iloc[-21]))
                / float(df["BB_Mid"].iloc[-21]) * 100
            ) if len(df) >= 21 else None,
            "bbw_percentile_120d": _safe(
                recent120["BBW"].rank(pct=True).iloc[-1] * 100
            ) if len(recent120) >= 30 else None,
        }

        # Engineered features from base values
        pb = feats["percent_b"] or 0
        mfi_v = feats["mfi"] or 0
        cmf_v = feats["cmf"] or 0
        rsi_v = feats["rsi14"] or 0
        bbwp = feats["bbw_percentile_60d"] or 50
        vr = feats["vol_ratio"] or 1
        sslope = feats["sma20_slope_5d"] or 0
        mom10 = feats["price_momentum_10d"] or 0
        mom20 = feats["price_momentum_20d"] or 0
        iip = feats["ii_pct"] or 0
        bbw_roc = feats["bbw_roc_5d"] or 0

        feats["pctb_x_mfi"] = pb * mfi_v / 100
        feats["pctb_x_cmf"] = pb * cmf_v
        feats["pctb_x_rsi"] = pb * rsi_v / 100
        feats["squeeze_intensity"] = 1 - bbwp / 100
        feats["squeeze_x_vol"] = feats["squeeze_intensity"] * vr
        feats["vol_mom_div"] = vr * (1 if mom10 > 0 else (-1 if mom10 < 0 else 0))
        feats["mom_accel"] = mom10 - mom20
        feats["mfi_cmf_div"] = (mfi_v / 100) - ((cmf_v + 1) / 2)
        feats["bbw_vol_expansion"] = bbw_roc * vr

        # Sector-relative features (live inference)
        if ticker:
            try:
                from ai_ml.sector_features import get_sector_rs_live
                sector = get_sector_rs_live(ticker, df)
                feats["sector_rs"] = sector.get("sector_rs")
                feats["stock_vs_sector_rs"] = sector.get("stock_vs_sector_rs")
            except Exception:
                pass

        return feats
    except Exception as e:
        logger.debug("conviction feature extraction failed: %s", e)
        return None


# ─────────────────────────────────────────────────────────────
#  Model loading (lazy, cached)
# ─────────────────────────────────────────────────────────────

def _load_model():
    global _model, _lr, _iso, _q_lo, _q_hi, _imputer, _scaler, _medians
    if _model is not None:
        return _model

    if not os.path.exists(CONVICTION_MODEL) or not os.path.exists(CONVICTION_MEDIANS):
        return None

    try:
        bundle = joblib.load(CONVICTION_MODEL)
        with open(CONVICTION_MEDIANS) as f:
            medians = json.load(f)
        _model = bundle["model"]
        _lr = bundle.get("lr")
        _iso = bundle.get("iso")
        _q_lo = bundle.get("q_lo")
        _q_hi = bundle.get("q_hi")
        _imputer = bundle.get("imputer") or (getattr(_lr, '_imputer', None) if _lr else None)
        _scaler = bundle.get("scaler") or (getattr(_lr, '_scaler', None) if _lr else None)
        _medians = medians
        return _model
    except Exception as e:
        logger.warning("Failed to load conviction model: %s", e)
        return None


# ─────────────────────────────────────────────────────────────
#  Public API
# ─────────────────────────────────────────────────────────────

def score_conviction(df: pd.DataFrame, method: str,
                     ticker: str | None = None) -> Optional[dict]:
    """Score a position's ML conviction from its indicator DataFrame.

    Returns dict with ml_conviction (0-100), label, model_available.
    Returns None if model is unavailable or features can't be computed.
    Never raises.
    """
    model = _load_model()
    if model is None:
        return None

    feats = _compute_features(df, method, ticker=ticker)
    if feats is None:
        return None

    try:
        row = {k: feats.get(k) for k in ALL_FEATURES}
        if _medians:
            for k in ALL_FEATURES:
                if row[k] is None:
                    row[k] = _medians.get(k, 0)

        X = pd.DataFrame([row], columns=ALL_FEATURES)
        lr_p = None

        # v2: regressor + ensemble, v1: classifier fallback
        if hasattr(model, "predict_proba"):
            raw_p = float(model.predict_proba(X)[:, 1][0])
            calibrated_p = float(_iso.predict([raw_p])[0]) if _iso else raw_p
            score = max(0, min(100, calibrated_p * 100))
        else:
            raw_r = float(model.predict(X)[0])
            if _lr is not None and _imputer is not None and _scaler is not None:
                X_imp = _imputer.transform(X)
                X_scaled = _scaler.transform(X_imp)
                lr_p = float(_lr.predict_proba(X_scaled)[:, 1][0])
                blended = 0.7 * raw_r + 0.3 * lr_p
            else:
                blended = raw_r
            calibrated = float(_iso.predict([blended])[0]) if _iso else blended
            score = max(0, min(100, calibrated * 100))

        if score >= 70:
            label = "HIGH"
        elif score >= 40:
            label = "MODERATE"
        else:
            label = "LOW"

        # Confidence interval from quantile spread
        ci = None
        if _q_lo is not None and _q_hi is not None:
            lo_r = float(_q_lo.predict(X)[0])
            hi_r = float(_q_hi.predict(X)[0])
            # ponytail: empirical mapping — r_spread to score-space half-width
            # Tight spread = model confident, wide = uncertain
            spread_r = abs(hi_r - lo_r)
            half = max(3, min(18, spread_r * 4.5))
            ci = [round(max(0, score - half), 1),
                  round(min(100, score + half), 1)]

        drivers, summary, _ = _compute_drivers(feats, model)
        narrative = _build_narrative(score, label, feats, drivers)

        result = {
            "ml_conviction": round(score, 1),
            "ml_conviction_label": label,
            "model_available": True,
            "drivers": drivers,
            "summary": summary,
            "narrative": narrative,
            "feature_count": len(ALL_FEATURES),
            "model_version": "v2.1",
            "model_arch": "LightGBM + LR Ensemble",
        }
        if ci:
            result["confidence_range"] = ci
        sr = feats.get("sector_rs")
        svs = feats.get("stock_vs_sector_rs")
        if sr is not None:
            result["sector_rs"] = round(sr, 2)
        if svs is not None:
            result["stock_vs_sector_rs"] = round(svs, 2)
        return result
    except Exception as e:
        logger.debug("conviction scoring failed: %s", e)
        return None


# ─────────────────────────────────────────────────────────────
#  Training
# ─────────────────────────────────────────────────────────────

def train_conviction_model():
    """Train v2: LGBMRegressor on r_multiple + LR ensemble + quantile CI."""
    from lightgbm import LGBMRegressor, LGBMClassifier
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score

    print("Loading training data...", flush=True)
    df = pd.read_parquet(TRAINING_DATA_FILE)
    df = _add_engineered(df)

    # Drop rows where r_multiple is missing (shouldn't happen but guard)
    if "r_multiple" not in df.columns:
        print("WARN: r_multiple missing, falling back to binary target", flush=True)
        df["r_multiple"] = df["result"].astype(float)

    # Temporal split
    split_idx = int(len(df) * 0.80)
    df_train = df.iloc[:split_idx]
    df_test = df.iloc[split_idx:]
    y_train_cls = df_train["result"].values
    y_test_cls = df_test["result"].values
    y_train_r = df_train["r_multiple"].values
    y_test_r = df_test["r_multiple"].values

    X_train = df_train[ALL_FEATURES]
    X_test = df_test[ALL_FEATURES]

    print(f"Train: {len(df_train):,} | Test: {len(df_test):,} | "
          f"Baseline WR: {y_test_cls.mean():.1%} | Features: {len(ALL_FEATURES)}", flush=True)

    # 1. LightGBM Regressor on r_multiple
    print("Training LGBMRegressor (1000 trees, depth 8)...", flush=True)
    lgb = LGBMRegressor(
        n_estimators=1000, max_depth=8, learning_rate=0.01,
        num_leaves=63, subsample=0.7, colsample_bytree=0.6,
        min_child_samples=30, reg_alpha=0.5, reg_lambda=2.0,
        random_state=42, verbose=-1,
    )
    lgb.fit(X_train, y_train_r)

    # 2. LogisticRegression ensemble partner (on binary target)
    print("Training LogisticRegression ensemble...", flush=True)
    from sklearn.preprocessing import StandardScaler
    from sklearn.impute import SimpleImputer
    imputer = SimpleImputer(strategy="median")
    X_train_imputed = imputer.fit_transform(X_train)
    X_test_imputed = imputer.transform(X_test)
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train_imputed)
    X_test_scaled = scaler.transform(X_test_imputed)
    lr = LogisticRegression(C=1.0, max_iter=500, random_state=42)
    lr.fit(X_train_scaled, y_train_cls)

    # 3. Blend: 0.7 * lgb_pred + 0.3 * lr_prob
    lgb_test_pred = lgb.predict(X_test)
    lr_test_prob = lr.predict_proba(X_test_scaled)[:, 1]
    blended_test = 0.7 * lgb_test_pred + 0.3 * lr_test_prob

    # 4. Isotonic calibration on last 20% of train
    cal_split = int(len(df_train) * 0.80)
    cal_X = df_train.iloc[cal_split:]
    cal_y = y_train_cls[cal_split:]
    cal_lgb = lgb.predict(cal_X[ALL_FEATURES])
    cal_lr = lr.predict_proba(scaler.transform(imputer.transform(cal_X[ALL_FEATURES])))[:, 1]
    cal_blend = 0.7 * cal_lgb + 0.3 * cal_lr

    iso = IsotonicRegression(out_of_bounds="clip")
    iso.fit(cal_blend, cal_y)

    calibrated_test = iso.predict(blended_test)
    auc = roc_auc_score(y_test_cls, calibrated_test)

    # 5. Quantile models for confidence intervals
    print("Training quantile models (10th/90th)...", flush=True)
    q_lo = LGBMRegressor(
        n_estimators=500, max_depth=6, learning_rate=0.02,
        objective="quantile", alpha=0.1, random_state=42, verbose=-1,
    )
    q_hi = LGBMRegressor(
        n_estimators=500, max_depth=6, learning_rate=0.02,
        objective="quantile", alpha=0.9, random_state=42, verbose=-1,
    )
    q_lo.fit(X_train, y_train_r)
    q_hi.fit(X_train, y_train_r)

    # Bucket analysis
    scores = calibrated_test * 100
    print(f"\nAUC: {auc:.4f}")
    print(f"\n{'Bucket':<15} {'Count':>8} {'Win Rate':>10} {'Avg R':>8}")
    print("─" * 43)
    for label, lo, hi in [("0-30", 0, 30), ("30-50", 30, 50), ("50-70", 50, 70), ("70-90", 70, 90), ("90-100", 90, 101)]:
        mask = (scores >= lo) & (scores < hi)
        sub = df_test[mask]
        if len(sub) < 5:
            continue
        wr = sub["result"].mean()
        avg_r = sub["r_multiple"].mean()
        print(f"{label:<15} {len(sub):>8,} {wr:>9.1%} {avg_r:>+7.2f}")

    hi_wr = df_test[scores >= 60]["result"].mean() if (scores >= 60).sum() > 0 else 0
    lo_wr = df_test[scores < 40]["result"].mean() if (scores < 40).sum() > 0 else 0
    print(f"\nSpread (>60 vs <40): {hi_wr - lo_wr:+.1%}")

    # Save bundle
    bundle = {"model": lgb, "lr": lr, "imputer": imputer, "scaler": scaler,
              "iso": iso, "q_lo": q_lo, "q_hi": q_hi,
              "version": 2, "features": ALL_FEATURES}
    joblib.dump(bundle, CONVICTION_MODEL)
    print(f"Model saved to {CONVICTION_MODEL}")

    # Save feature medians
    medians = {}
    for col in ALL_FEATURES:
        if col in df_train.columns:
            v = df_train[col].median()
            medians[col] = float(v) if not pd.isna(v) else 0
    with open(CONVICTION_MEDIANS, "w") as f:
        json.dump(medians, f, indent=2)
    print(f"Medians saved to {CONVICTION_MEDIANS}")

    return {"auc": auc, "spread": hi_wr - lo_wr, "n_train": len(df_train), "n_test": len(df_test)}


def analyze_features():
    """Print SHAP-based feature importance ranking. Run after training."""
    try:
        import shap
    except ImportError:
        print("pip install shap first")
        return

    bundle = joblib.load(CONVICTION_MODEL)
    model = bundle["model"]
    df = pd.read_parquet(TRAINING_DATA_FILE)
    df = _add_engineered(df)
    X = df[ALL_FEATURES].tail(5000)

    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X)
    mean_abs = np.abs(shap_values).mean(axis=0)
    ranked = sorted(zip(ALL_FEATURES, mean_abs), key=lambda x: x[1], reverse=True)

    print(f"\n{'Feature':<30} {'Mean |SHAP|':>12} {'Status':>10}")
    print("─" * 54)
    for feat, imp in ranked:
        status = "KEEP" if imp >= 0.001 else "DROP?"
        print(f"{feat:<30} {imp:>12.5f} {status:>10}")


if __name__ == "__main__":
    train_conviction_model()
