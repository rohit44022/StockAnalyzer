"""
analyzer.py — Sentiment regime, money flow, correlations, India impact.
═══════════════════════════════════════════════════════════════════════

This module is the brain. It takes the raw per-instrument summaries from
data_loader and produces:

  1. REGIME — one of:
       Risk-On Growth, Risk-Off / Flight to Safety, Inflation Concern,
       Recession Watch, Mixed / Transitioning
     Each regime has a short rationale rooted in classic inter-market reading
     (Pring, Murphy, Soros' reflexivity).

  2. COMPOSITE SENTIMENT SCORE  (-100 to +100)
     A weighted blend of momentum signals across all instruments, polarity-
     corrected. +100 = risk-on euphoria, -100 = systemic flight to safety.

  3. MONEY FLOW — directional flows between asset classes:
       "Capital flowing FROM bonds INTO equities" etc.
     Computed by comparing 5d % moves between paired classes.

  4. CORRELATIONS — pairwise rolling-30d correlations of % returns for the
     classic macro pairs (Gold↔DXY, USDINR↔Nifty, Brent↔Nifty, US10Y↔Gold,
     BTC↔Nasdaq). Useful to see if relationships are holding or breaking.

  5. INDIA IMPACT — translates global signals into Nifty/INR-specific
     read: FII flow direction, current account pressure, rate-sensitive
     sectors, etc.
"""

from __future__ import annotations
from typing import Optional

import pandas as pd

from global_sentiment.instruments import BY_KEY


# ─────────────────────────── helpers ───────────────────────────

def _get(summaries: dict, key: str, field: str, default=None):
    s = summaries.get(key, {})
    v = s.get(field)
    return default if v is None else v


def _sign(x: float) -> int:
    if x is None:
        return 0
    if x > 0.0001:
        return 1
    if x < -0.0001:
        return -1
    return 0


# ─────────────────────────── regime detection ───────────────────────────

def detect_regime(summaries: dict) -> dict:
    """
    Apply a classic inter-market decision tree to label the current regime.
    Now uses multi-timeframe (1d + 5d + 20d) for stability and includes
    India VIX as a primary fear indicator alongside US VIX.
    """
    sp500_5d    = _get(summaries, "sp500",    "change_5d_pct", 0)
    sp500_20d   = _get(summaries, "sp500",    "change_20d_pct", 0)
    nasdaq_5d   = _get(summaries, "nasdaq",   "change_5d_pct", 0)
    vix_last    = _get(summaries, "vix",      "last", 0)
    vix_5d      = _get(summaries, "vix",      "change_5d_pct", 0)
    indiavix_l  = _get(summaries, "indiavix", "last")
    indiavix_5d = _get(summaries, "indiavix", "change_5d_pct", 0)
    gold_5d     = _get(summaries, "gold",     "change_5d_pct", 0)
    gold_20d    = _get(summaries, "gold",     "change_20d_pct", 0)
    dxy_5d      = _get(summaries, "dxy",      "change_5d_pct", 0)
    brent_5d    = _get(summaries, "brent",    "change_5d_pct", 0)
    brent_20d   = _get(summaries, "brent",    "change_20d_pct", 0)
    copper_5d   = _get(summaries, "copper",   "change_5d_pct", 0)
    us10y_last  = _get(summaries, "us10y",    "last", 0)
    us3m_last   = _get(summaries, "us3m",     "last", 0)
    us10y_5d    = _get(summaries, "us10y",    "change_5d_pct", 0)
    btc_5d      = _get(summaries, "btc",      "change_5d_pct", 0)

    drivers: list = []

    # Yield curve check (10Y - 3M is the NY Fed preferred recession signal)
    yc_inverted = (us10y_last and us3m_last and us10y_last < us3m_last)
    if yc_inverted:
        drivers.append(f"Yield curve INVERTED (US 10Y {us10y_last:.2f}% < 3M {us3m_last:.2f}%) — NY Fed's preferred recession signal")

    # ── 1. RISK-OFF / FLIGHT TO SAFETY ──
    risk_off_score = 0
    if vix_last and vix_last > 25:           risk_off_score += 2
    if indiavix_l and indiavix_l > 20:       risk_off_score += 2     # India fear gauge
    if sp500_5d and sp500_5d < -2:           risk_off_score += 2
    if sp500_20d and sp500_20d < -5:         risk_off_score += 1     # confirmed by 20d
    if gold_5d and gold_5d > 1:              risk_off_score += 1
    if dxy_5d and dxy_5d > 0.8:              risk_off_score += 1
    if vix_5d and vix_5d > 15:               risk_off_score += 1
    if indiavix_5d and indiavix_5d > 15:     risk_off_score += 1

    # ── 2. INFLATION CONCERN ──
    inflation_score = 0
    if brent_5d and brent_5d > 3:            inflation_score += 2
    if brent_20d and brent_20d > 7:          inflation_score += 1     # confirmed trend
    if us10y_5d and us10y_5d > 3:            inflation_score += 1
    if gold_5d and gold_5d > 2:              inflation_score += 1
    if copper_5d and copper_5d > 2:          inflation_score += 1

    # ── 3. RECESSION WATCH ──
    recession_score = 0
    if yc_inverted:                          recession_score += 3
    if copper_5d and copper_5d < -3:         recession_score += 2
    if brent_5d and brent_5d < -5:           recession_score += 1
    if dxy_5d and dxy_5d > 1:                recession_score += 1
    if sp500_20d and sp500_20d < -8:         recession_score += 1     # 20d confirmation

    # ── 4. RISK-ON GROWTH ──
    risk_on_score = 0
    if sp500_5d and sp500_5d > 1.5:          risk_on_score += 2
    if sp500_20d and sp500_20d > 4:          risk_on_score += 1       # confirmed trend
    if nasdaq_5d and nasdaq_5d > 2:          risk_on_score += 1
    if btc_5d and btc_5d > 3:                risk_on_score += 1
    if vix_last and vix_last < 16:           risk_on_score += 1
    if indiavix_l and indiavix_l < 14:       risk_on_score += 1
    if copper_5d and copper_5d > 1:          risk_on_score += 1
    if gold_5d and gold_5d < 0:              risk_on_score += 1

    # Pick highest-scoring regime
    scores = {
        "Risk-Off / Flight to Safety": risk_off_score,
        "Inflation Concern":           inflation_score,
        "Recession Watch":             recession_score,
        "Risk-On Growth":              risk_on_score,
    }
    label = max(scores, key=scores.get)
    top = scores[label]

    if top < 2:
        label = "Mixed / Transitioning"

    # Build rationale + drivers
    if label == "Risk-Off / Flight to Safety":
        emoji, color = "🛡️", "#f85149"
        rationale = (f"Markets defensive: VIX at {vix_last:.1f}, S&P {sp500_5d:+.1f}% over 5d, "
                     f"gold {gold_5d:+.1f}%, DXY {dxy_5d:+.1f}%. Capital fleeing risk into safer assets.")
        drivers.append(f"VIX (fear) at {vix_last:.1f} — {'elevated' if vix_last > 20 else 'normal'}")
        if sp500_5d < 0: drivers.append(f"S&P 500 down {abs(sp500_5d):.1f}% over 5 days")
        if gold_5d > 0:  drivers.append(f"Gold up {gold_5d:+.1f}% — fear bid")
        if dxy_5d > 0:   drivers.append(f"DXY up {dxy_5d:+.1f}% — USD safe-haven demand")

    elif label == "Inflation Concern":
        emoji, color = "🔥", "#ffa500"
        rationale = (f"Inflation pressure building: Brent {brent_5d:+.1f}% in 5d, US10Y yield {us10y_last:.2f}%, "
                     f"copper {copper_5d:+.1f}%. Watch for central bank hawkish pivot.")
        if brent_5d > 0: drivers.append(f"Brent crude up {brent_5d:+.1f}% — energy inflation")
        if us10y_5d > 0: drivers.append(f"US 10Y yield up {us10y_5d:+.1f}% — bond market pricing inflation")
        if gold_5d > 0:  drivers.append(f"Gold up {gold_5d:+.1f}% — inflation hedge bid")

    elif label == "Recession Watch":
        emoji, color = "⚠️", "#d29922"
        rationale = (f"Recession warning lights: " +
                     ("inverted yield curve, " if yc_inverted else "") +
                     f"copper {copper_5d:+.1f}%, oil {brent_5d:+.1f}%. "
                     f"Cyclical assets weakening.")
        if copper_5d < 0: drivers.append(f"Dr. Copper down {copper_5d:+.1f}% — industrial demand softening")

    elif label == "Risk-On Growth":
        emoji, color = "🚀", "#3fb950"
        rationale = (f"Risk appetite strong: S&P {sp500_5d:+.1f}%, Nasdaq {nasdaq_5d:+.1f}%, "
                     f"VIX low at {vix_last:.1f}, BTC {btc_5d:+.1f}%. Capital chasing growth.")
        if nasdaq_5d > 0: drivers.append(f"Nasdaq up {nasdaq_5d:+.1f}% — high-beta tech leading")
        if btc_5d > 0:    drivers.append(f"BTC up {btc_5d:+.1f}% — crypto risk-on")
        if vix_last < 16: drivers.append(f"VIX low at {vix_last:.1f} — complacency / confidence")
        if copper_5d > 0: drivers.append(f"Copper up {copper_5d:+.1f}% — industrial demand healthy")

    else:
        emoji, color = "🔄", "#8b949e"
        rationale = ("No single regime dominates — markets are in transition or directionless. "
                     "Watch the next 3-5 sessions for a clearer signal.")

    return {
        "label": label,
        "emoji": emoji,
        "color": color,
        "rationale": rationale,
        "drivers": drivers[:6],
        "regime_scores": scores,
    }


# ─────────────────────────── composite sentiment score ───────────────────────────

def compute_composite_score(summaries: dict) -> dict:
    """
    Multi-timeframe sentiment score: blend 1d (immediacy), 5d (current regime),
    and 20d (trend) into one -100..+100 number.

    Why three timeframes:
      • 1d alone is too noisy.
      • 5d alone misses the trend context (a -2% day in a strong uptrend ≠ regime change).
      • 20d alone is too lagging.
    Weights: 1d=20%, 5d=50%, 20d=30%.

    Higher = risk-on. Lower = risk-off.
    """
    # Importance weights — sum doesn't need to be 1, we'll normalize afterward.
    # Weights set so each "category" contributes ~roughly equal share of the final score
    # when its polarity engages.
    weights = {
        # Equities (major risk-on indicator)
        "sp500": 1.5, "nasdaq": 1.0, "nifty": 1.5, "dow": 0.5,
        "ftse": 0.3, "dax": 0.3, "nikkei": 0.4, "hangseng": 0.4,
        # Bonds & VIX (polarity -1 means high VIX hurts the risk-on score)
        "vix":      1.2,
        "indiavix": 1.5,   # India fear gauge — most relevant for Nifty
        "us10y":    0.8,   # raised — context-aware polarity now engages
        "us30y":    0.3,
        # Currencies
        "dxy":    1.0,     # raised — DXY is a major macro driver
        "usdinr": 0.7,
        "jpyinr": 0.5,
        # Commodities
        "gold":   1.0,
        "copper": 0.8,
        "brent":  0.8,     # raised — oil is now context-aware
        # Crypto
        "btc": 0.7,
        "eth": 0.3,
    }

    # Multi-timeframe blend
    tf_weights = {"change_1d_pct": 0.20, "change_5d_pct": 0.50, "change_20d_pct": 0.30}

    score = 0.0
    total_w = 0.0
    contributors = []

    for key, w in weights.items():
        inst = BY_KEY.get(key)
        if not inst:
            continue

        # Blend timeframes; if any tf is missing, redistribute weight
        tf_score = 0.0
        tf_used = 0.0
        for field, tw in tf_weights.items():
            v = _get(summaries, key, field)
            if v is None:
                continue
            tf_score += max(-12.0, min(12.0, v)) * tw
            tf_used += tw
        if tf_used == 0:
            continue
        tf_score /= tf_used   # normalize when some tfs missing

        # Polarity correction — context-aware for instruments with polarity=0.
        # Some instruments are bullish or bearish DEPENDING on level, not direction.
        polarity = inst.polarity
        if polarity == 0:
            last = _get(summaries, key, "last")
            if key == "dxy":
                polarity = -1   # Stronger USD = bad for EM/commodities/risk
            elif key == "brent" or key == "wti":
                # Oil rising mildly = growth (+); rising sharply / above $85 = inflation drag (-)
                if last is not None and last > 85:
                    polarity = -1
                elif last is not None and 50 <= last <= 75:
                    polarity = +1
                else:
                    polarity = 0
            elif key in ("us10y", "us30y"):
                # Yields > 4.5% restrictive (bearish for risk); < 3.5% accommodative (bullish)
                if last is not None and last > 4.5:
                    polarity = -1
                elif last is not None and last < 3.5 and last > 0:
                    polarity = +1
                else:
                    polarity = 0
            elif key == "us3m":
                polarity = 0   # short-end alone is ambiguous; curve inversion handled in regime
            elif key == "natgas":
                polarity = 0   # too noisy for direct contribution
            else:
                polarity = 0

        contribution = tf_score * polarity * w
        score += contribution
        total_w += w
        contributors.append({
            "key": key,
            "name": inst.name,
            "change_1d_pct":  _get(summaries, key, "change_1d_pct"),
            "change_5d_pct":  _get(summaries, key, "change_5d_pct"),
            "change_20d_pct": _get(summaries, key, "change_20d_pct"),
            "polarity": polarity,
            "weight": w,
            "contribution": round(contribution, 2),
        })

    if total_w == 0:
        normalized = 0
    else:
        # Map raw score (~ ±10 range) to -100..+100
        normalized = max(-100.0, min(100.0, score / total_w * 14.0))

    if normalized >= 50:
        label = "STRONG RISK-ON"
        color = "#3fb950"
    elif normalized >= 20:
        label = "RISK-ON"
        color = "#56d364"
    elif normalized >= -20:
        label = "NEUTRAL"
        color = "#8b949e"
    elif normalized >= -50:
        label = "RISK-OFF"
        color = "#ff7b72"
    else:
        label = "STRONG RISK-OFF"
        color = "#f85149"

    contributors.sort(key=lambda c: abs(c["contribution"]), reverse=True)

    return {
        "score": round(normalized, 1),
        "label": label,
        "color": color,
        "top_drivers": contributors[:6],
    }


# ─────────────────────────── money flow ───────────────────────────

def detect_money_flow(summaries: dict) -> list:
    """
    Identify the main capital-flow narratives based on 5-day % moves.
    Returns a list of plain-English bullet points.
    """
    flows = []

    sp500_5d  = _get(summaries, "sp500",  "change_5d_pct", 0)
    bonds_5d  = _get(summaries, "us10y",  "change_5d_pct", 0)   # rising yield = falling bond price
    gold_5d   = _get(summaries, "gold",   "change_5d_pct", 0)
    dxy_5d    = _get(summaries, "dxy",    "change_5d_pct", 0)
    btc_5d    = _get(summaries, "btc",    "change_5d_pct", 0)
    nifty_5d  = _get(summaries, "nifty",  "change_5d_pct", 0)
    usdinr_5d = _get(summaries, "usdinr", "change_5d_pct", 0)
    brent_5d  = _get(summaries, "brent",  "change_5d_pct", 0)
    copper_5d = _get(summaries, "copper", "change_5d_pct", 0)

    # Equities up + bonds down (yields up) = rotation INTO equities
    if sp500_5d > 1 and bonds_5d > 0:
        flows.append({
            "icon": "📈",
            "text": f"Capital ROTATING from bonds INTO equities (S&P {sp500_5d:+.1f}%, US10Y yield {bonds_5d:+.1f}% — bond prices falling).",
            "tone": "bullish",
        })
    elif sp500_5d < -1 and bonds_5d < 0:
        flows.append({
            "icon": "🛡️",
            "text": f"FLIGHT to bonds: equities down ({sp500_5d:+.1f}%) while yields fall ({bonds_5d:+.1f}%) — investors buying safe-haven Treasuries.",
            "tone": "bearish",
        })

    # USD strengthening vs rest
    if dxy_5d > 0.5:
        flows.append({
            "icon": "💵",
            "text": f"USD STRENGTHENING (DXY {dxy_5d:+.1f}%): pressures EM currencies and dollar-denominated commodities.",
            "tone": "bearish",
        })
    elif dxy_5d < -0.5:
        flows.append({
            "icon": "🌍",
            "text": f"USD WEAKENING (DXY {dxy_5d:+.1f}%): supports EM, commodities, gold.",
            "tone": "bullish",
        })

    # Gold flows
    if gold_5d > 1.5 and dxy_5d > 0.5:
        flows.append({
            "icon": "🪙",
            "text": f"DOUBLE SAFE-HAVEN: gold AND dollar both rising — extreme risk aversion.",
            "tone": "bearish",
        })
    elif gold_5d > 1.5:
        flows.append({
            "icon": "🪙",
            "text": f"Gold {gold_5d:+.1f}% — defensive bid, watch for fear or inflation hedge demand.",
            "tone": "neutral",
        })

    # Risk-on crypto signal
    if btc_5d > 5 and sp500_5d > 1:
        flows.append({
            "icon": "🚀",
            "text": f"BTC {btc_5d:+.1f}% + equities up — full risk-on; speculative capital active.",
            "tone": "bullish",
        })
    elif btc_5d < -5:
        flows.append({
            "icon": "❄️",
            "text": f"BTC down {btc_5d:+.1f}% — speculative capital retreating, risk-off precursor.",
            "tone": "bearish",
        })

    # Oil regime
    if brent_5d > 4:
        flows.append({
            "icon": "⛽",
            "text": f"Oil up {brent_5d:+.1f}% — inflation pressure + India current-account headwind (oil importer).",
            "tone": "bearish_for_india",
        })
    elif brent_5d < -4:
        flows.append({
            "icon": "📉",
            "text": f"Oil down {brent_5d:+.1f}% — softer inflation, tailwind for India CAD and rupee.",
            "tone": "bullish_for_india",
        })

    # Copper / industrial
    if copper_5d < -3:
        flows.append({
            "icon": "🔻",
            "text": f"Copper down {copper_5d:+.1f}% — Dr. Copper warning of slowing global industrial demand.",
            "tone": "bearish",
        })

    # India-specific
    if usdinr_5d > 0.3 and nifty_5d < -1:
        flows.append({
            "icon": "🇮🇳",
            "text": f"FII OUTFLOW: USD/INR {usdinr_5d:+.1f}% (rupee weak) + Nifty {nifty_5d:+.1f}% — foreign capital exiting India.",
            "tone": "bearish_for_india",
        })
    elif usdinr_5d < -0.3 and nifty_5d > 1:
        flows.append({
            "icon": "🇮🇳",
            "text": f"FII INFLOW: USD/INR {usdinr_5d:+.1f}% (rupee firm) + Nifty {nifty_5d:+.1f}% — foreign capital entering India.",
            "tone": "bullish_for_india",
        })

    return flows


# ─────────────────────────── correlations ───────────────────────────

CORRELATION_PAIRS = [
    ("gold", "dxy",    "Gold vs DXY",       "Classic NEGATIVE — when one rises the other falls"),
    ("usdinr", "nifty","USD/INR vs Nifty",  "Negative — rupee weakness pressures Indian equities"),
    ("brent", "nifty", "Brent vs Nifty",    "Negative — oil pressures India CAD; positive if energy stocks dominate"),
    ("us10y", "gold",  "US 10Y vs Gold",    "Negative — higher real yields hurt non-yielding gold"),
    ("btc",   "nasdaq","BTC vs Nasdaq",     "Positive in risk-on — both speculative growth assets"),
    ("dxy",   "sp500", "DXY vs S&P 500",    "Mildly negative — strong USD weighs on multinational earnings"),
    ("vix",   "sp500", "VIX vs S&P 500",    "Strongly negative by construction"),
    ("copper","sp500", "Copper vs S&P 500", "Positive — both leading indicators of growth"),
]


def _pair_corr(df1, df2, n: int) -> float:
    """Return rolling-N pairwise correlation of % returns; None if insufficient overlap."""
    try:
        r1 = df1["Close"].pct_change().dropna().tail(n)
        r2 = df2["Close"].pct_change().dropna().tail(n)
        joined = pd.concat([r1, r2], axis=1, join="inner").dropna()
        if len(joined) < max(10, n // 3):
            return None
        c = float(joined.iloc[:, 0].corr(joined.iloc[:, 1]))
        if pd.isna(c):
            return None
        return c
    except Exception:
        return None


def compute_correlations(market_data: dict) -> list:
    """
    Pairwise rolling correlations across THREE windows (30d / 60d / 90d) for the
    classic macro pairs. The headline `correlation` field is 30d (recent regime).
    The multi-window view exposes whether the relationship has shifted recently.

    Stability flag:
      - 'stable'    : all three windows have the same sign AND magnitude > 0.2
      - 'shifting'  : windows disagree on sign OR one is much weaker
      - 'weak'      : all three are noise (|corr| < 0.2)
    """
    out = []
    for k1, k2, name, expectation in CORRELATION_PAIRS:
        df1 = market_data.get(k1)
        df2 = market_data.get(k2)
        if df1 is None or df2 is None or df1.empty or df2.empty:
            continue

        c30 = _pair_corr(df1, df2, 30)
        c60 = _pair_corr(df1, df2, 60)
        c90 = _pair_corr(df1, df2, 90)
        if c30 is None:
            continue

        exp_lower = expectation.lower()
        expected_sign = -1 if "negative" in exp_lower else (1 if "positive" in exp_lower else 0)
        sign_match = (c30 > 0 and expected_sign > 0) or (c30 < 0 and expected_sign < 0)
        holding = sign_match and abs(c30) > 0.2

        # Stability
        windows = [w for w in (c30, c60, c90) if w is not None]
        if len(windows) >= 2:
            signs_match = all((w > 0) == (windows[0] > 0) for w in windows)
            magn_strong = all(abs(w) > 0.2 for w in windows)
            magn_weak = all(abs(w) < 0.2 for w in windows)
            if magn_weak:
                stability = "weak"
            elif signs_match and magn_strong:
                stability = "stable"
            else:
                stability = "shifting"
        else:
            stability = "unknown"

        # Detect recent reversal: if 30d sign differs from 90d sign with both > 0.2
        regime_shift = (
            c30 is not None and c90 is not None
            and abs(c30) > 0.2 and abs(c90) > 0.2
            and (c30 > 0) != (c90 > 0)
        )

        out.append({
            "pair": name,
            "key1": k1, "key2": k2,
            "correlation": round(c30, 3),         # headline = 30d
            "corr_30d":   round(c30, 3) if c30 is not None else None,
            "corr_60d":   round(c60, 3) if c60 is not None else None,
            "corr_90d":   round(c90, 3) if c90 is not None else None,
            "expectation": expectation,
            "expected_sign": expected_sign,
            "holding": holding,
            "stability": stability,
            "regime_shift": regime_shift,
            "magnitude": "strong" if abs(c30) > 0.6 else ("moderate" if abs(c30) > 0.3 else "weak"),
        })
    return out


# ─────────────────────────── India impact translator ───────────────────────────

def india_impact(summaries: dict, regime: dict, score: dict) -> dict:
    """
    Translate global signals into India-specific implications.
    """
    points = []

    usdinr_5d = _get(summaries, "usdinr", "change_5d_pct", 0)
    usdinr_last = _get(summaries, "usdinr", "last", 0)
    us10y_last = _get(summaries, "us10y", "last", 0)
    brent_last = _get(summaries, "brent", "last", 0)
    brent_5d   = _get(summaries, "brent", "change_5d_pct", 0)
    nifty_5d   = _get(summaries, "nifty", "change_5d_pct", 0)
    nifty_20d  = _get(summaries, "nifty", "change_20d_pct", 0)
    sp500_5d   = _get(summaries, "sp500", "change_5d_pct", 0)
    dxy_5d     = _get(summaries, "dxy", "change_5d_pct", 0)

    # Rupee impact
    if usdinr_5d > 0.3:
        points.append({
            "tone": "bearish",
            "icon": "📉",
            "text": f"USD/INR at ₹{usdinr_last:.2f} (5d {usdinr_5d:+.1f}%) — FII outflow risk, import cost rising. Watch IT/exporters benefit, banks/financials pressured.",
        })
    elif usdinr_5d < -0.3:
        points.append({
            "tone": "bullish",
            "icon": "📈",
            "text": f"USD/INR at ₹{usdinr_last:.2f} (5d {usdinr_5d:+.1f}%) — rupee firming, suggests FII INFLOW; supportive for banks, autos, consumption.",
        })

    # US 10Y impact
    if us10y_last > 4.5:
        points.append({
            "tone": "bearish",
            "icon": "🇺🇸",
            "text": f"US 10Y yield {us10y_last:.2f}% — at restrictive levels. Capital pulling back to US bonds; valuation pressure on Indian growth/tech stocks.",
        })
    elif us10y_last < 3.5:
        points.append({
            "tone": "bullish",
            "icon": "🇺🇸",
            "text": f"US 10Y yield {us10y_last:.2f}% — accommodative. Supportive backdrop for EM equities including India.",
        })

    # Oil impact
    if brent_last and brent_last > 90:
        points.append({
            "tone": "bearish",
            "icon": "⛽",
            "text": f"Brent at ${brent_last:.1f}/bbl — elevated. India imports ~85% of oil; current-account pressure, inflation risk, fiscal stress on subsidies.",
        })
    elif brent_last and brent_last < 70:
        points.append({
            "tone": "bullish",
            "icon": "⛽",
            "text": f"Brent at ${brent_last:.1f}/bbl — favorable. Positive for India CAD, OMCs, paint/aviation/chemicals downstream of oil.",
        })

    # Nifty divergence from S&P
    if abs(nifty_5d - sp500_5d) > 2.5:
        if nifty_5d > sp500_5d:
            points.append({
                "tone": "bullish",
                "icon": "🇮🇳",
                "text": f"Nifty ({nifty_5d:+.1f}% / 5d) OUTPERFORMING S&P ({sp500_5d:+.1f}%) — India-specific story; domestic flows or sector rotation working.",
            })
        else:
            points.append({
                "tone": "bearish",
                "icon": "🇮🇳",
                "text": f"Nifty ({nifty_5d:+.1f}% / 5d) UNDERPERFORMING S&P ({sp500_5d:+.1f}%) — India-specific drag; FII selling or domestic risk premium rising.",
            })

    # DXY pressure
    if dxy_5d > 0.8:
        points.append({
            "tone": "bearish",
            "icon": "💵",
            "text": f"DXY {dxy_5d:+.1f}% (5d) — strong dollar regime; structurally bearish for EM including India until DXY peaks.",
        })

    # Overall summary
    summary_tone = "bearish" if score["score"] < -20 else ("bullish" if score["score"] > 20 else "neutral")
    if summary_tone == "bullish":
        summary = (f"Global tape is RISK-ON ({score['label']}, {score['score']:+.0f}). "
                   f"Backdrop favors Indian equities; opportunistic longs in cyclicals, financials, autos.")
    elif summary_tone == "bearish":
        summary = (f"Global tape is RISK-OFF ({score['label']}, {score['score']:+.0f}). "
                   f"Defensive posture warranted; reduce gross exposure, prefer staples/IT/pharma over high-beta names.")
    else:
        summary = (f"Global tape is NEUTRAL ({score['label']}, {score['score']:+.0f}). "
                   f"Stock-specific approach; let inter-market correlations clarify before sizing up.")

    return {
        "summary": summary,
        "summary_tone": summary_tone,
        "points": points,
    }


# ─────────────────────────── regime stability ───────────────────────────

def compute_regime_stability(market_data: dict, current_regime_label: str) -> dict:
    """
    How stable is today's regime? We replay the last N trading days, compute
    each day's regime via the simplified rule below, and count consecutive
    days the same regime has held. A regime that just flipped today gets
    confidence "low"; one that's held 10+ days gets "high".

    This avoids users acting on a regime that may flip back tomorrow.
    """
    days_held = 1
    flips_30d = 0
    history = []

    # Build a simple per-day regime history using sp500/vix/oil as the
    # decisive triad (full detect_regime needs many series; we shortcut for speed)
    try:
        sp500 = market_data.get("sp500")
        vix   = market_data.get("vix")
        brent = market_data.get("brent")
        if sp500 is None or vix is None:
            return {"days_held": None, "flips_30d": None, "confidence": "unknown"}

        sp_close = sp500["Close"].dropna()
        vix_close = vix["Close"].dropna()
        brent_close = brent["Close"].dropna() if brent is not None else None

        common = sp_close.index.intersection(vix_close.index)
        if brent_close is not None:
            common = common.intersection(brent_close.index)
        common = common[-35:]  # last 35 trading days

        prev_label = None
        for i in range(5, len(common)):
            d_now = common[i]
            d_5ago = common[i - 5]
            sp_5d = (sp_close.loc[d_now] - sp_close.loc[d_5ago]) / sp_close.loc[d_5ago] * 100
            vix_now = float(vix_close.loc[d_now])
            br_5d = 0
            if brent_close is not None:
                br_5d = (brent_close.loc[d_now] - brent_close.loc[d_5ago]) / brent_close.loc[d_5ago] * 100

            if vix_now > 25 or sp_5d < -3:
                lbl = "Risk-Off / Flight to Safety"
            elif br_5d > 4:
                lbl = "Inflation Concern"
            elif sp_5d > 1.5 and vix_now < 17:
                lbl = "Risk-On Growth"
            else:
                lbl = "Mixed / Transitioning"
            history.append((str(d_now.date()) if hasattr(d_now, "date") else str(d_now), lbl))
            if prev_label and prev_label != lbl:
                flips_30d += 1
            prev_label = lbl

        # Count consecutive days at the end matching current_regime_label
        if history:
            for ts, lbl in reversed(history):
                if lbl == current_regime_label:
                    days_held = max(days_held, days_held + 0)  # noop, see next
            # Simpler: walk backwards from end while matching
            days_held = 0
            for _, lbl in reversed(history):
                if lbl == current_regime_label:
                    days_held += 1
                else:
                    break

        if days_held >= 10:
            confidence = "high"
        elif days_held >= 4:
            confidence = "medium"
        else:
            confidence = "low"

        return {
            "days_held": days_held,
            "flips_30d": flips_30d,
            "confidence": confidence,
            "recent_history": history[-7:],
        }
    except Exception:
        return {"days_held": None, "flips_30d": None, "confidence": "unknown"}


# ─────────────────────────── sector breakdown ───────────────────────────

def analyze_sectors(summaries: dict) -> dict:
    """
    Read the Indian sector indices and compute leadership.
    Identifies which sectors are leading vs lagging on multi-timeframe basis.
    """
    sector_keys = ["banknifty", "niftyit", "niftyauto", "niftypharma",
                   "niftymetal", "niftyfmcg", "niftyenergy", "niftyrealty"]
    sector_data = []

    for k in sector_keys:
        s = summaries.get(k)
        if not s:
            continue
        inst = BY_KEY.get(k)
        if not inst:
            continue
        # Composite sector score: blend 5d and 20d
        c5 = s.get("change_5d_pct") or 0
        c20 = s.get("change_20d_pct") or 0
        composite = c5 * 0.6 + c20 * 0.4
        sector_data.append({
            "key": k,
            "name": inst.name,
            "last": s.get("last"),
            "change_1d_pct":  s.get("change_1d_pct"),
            "change_5d_pct":  c5,
            "change_20d_pct": c20,
            "pct_rank_1y":    s.get("pct_rank_1y"),
            "composite":      round(composite, 2),
        })

    if not sector_data:
        return {"leaders": [], "laggards": [], "summary": "No sector data available."}

    sector_data.sort(key=lambda x: x["composite"], reverse=True)
    leaders  = sector_data[:3]
    laggards = sector_data[-3:][::-1]

    avg = sum(s["composite"] for s in sector_data) / len(sector_data)

    if avg > 2:
        rotation = "BROAD STRENGTH — most sectors participating in rally"
    elif avg < -2:
        rotation = "BROAD WEAKNESS — most sectors selling off (risk-off)"
    elif leaders[0]["composite"] - laggards[0]["composite"] > 6:
        rotation = "ROTATION — wide dispersion across sectors; defensive vs cyclical divergence"
    else:
        rotation = "MIXED — no clear sector leadership"

    return {
        "leaders": leaders,
        "laggards": laggards,
        "all": sector_data,
        "avg_composite": round(avg, 2),
        "rotation": rotation,
    }


# ─────────────────────────── historical context ───────────────────────────

def historical_context(summaries: dict) -> dict:
    """
    For headline indicators, return where today's value sits in BOTH the 1-year
    and 5-year history. Multi-year context prevents over-reaction to "1Y high"
    when in fact the level is normal in a 5Y view (or vice-versa).
    """
    keys = ["us10y", "vix", "indiavix", "dxy", "usdinr", "brent", "gold", "nifty"]
    out = []
    for k in keys:
        s = summaries.get(k)
        if not s:
            continue
        inst = BY_KEY.get(k)
        if not inst:
            continue
        rank = s.get("pct_rank_1y")
        rank5y = s.get("pct_rank_5y")
        last = s.get("last")
        if rank is None or last is None:
            continue
        if rank >= 90:
            label = "1-year HIGH zone"
            tone = "extreme"
        elif rank >= 70:
            label = "elevated vs 1Y range"
            tone = "high"
        elif rank <= 10:
            label = "1-year LOW zone"
            tone = "extreme"
        elif rank <= 30:
            label = "depressed vs 1Y range"
            tone = "low"
        else:
            label = "normal range"
            tone = "neutral"

        # Discrepancy hint: 1Y vs 5Y context
        ctx_note = ""
        if rank5y is not None and rank is not None:
            if rank >= 80 and rank5y < 50:
                ctx_note = "high vs last year, but average vs 5Y — limited multi-year signal"
            elif rank <= 20 and rank5y > 50:
                ctx_note = "low vs last year, but elevated vs 5Y — short-term cool-off"
            elif rank >= 80 and rank5y >= 80:
                ctx_note = "elevated in BOTH 1Y AND 5Y — multi-year extreme"
            elif rank <= 20 and rank5y <= 20:
                ctx_note = "depressed in BOTH 1Y AND 5Y — multi-year low"

        out.append({
            "key": k,
            "name": inst.name,
            "last": last,
            "unit": inst.unit,
            "pct_rank_1y": rank,
            "pct_rank_5y": rank5y,
            "label": label,
            "tone": tone,
            "context_note": ctx_note,
        })
    return out


# ─────────────────────────── per-section verdicts ───────────────────────────

def _verdict(tone: str, headline: str, body: str, observations: list = None) -> dict:
    return {
        "tone": tone,           # bullish | bearish | cautious | neutral | extreme | mixed
        "headline": headline,
        "body": body,
        "observations": observations or [],
    }


def _tone_from_score(score: float, *, bull_strong=2.5, bull=1.0, bear=-1.0,
                     bear_strong=-2.5, neutral_band=0.5) -> str:
    """
    Continuous score → tone with explicit neutral band to prevent single-step flips.

    Defaults give 4 buckets with hysteresis-friendly margins:
      score >= bull_strong  → 'bullish'
      score >= bull         → 'bullish'  (same bucket; gradient handled in headline)
      neutral_band <= score < bull → 'neutral' (cushion)
      bear < score < neutral_band → 'neutral' (cushion)
      bear_strong < score <= bear → 'cautious'
      score <= bear_strong  → 'bearish'

    The 'neutral_band' creates a cushion so values hovering near 1.0 don't oscillate.
    """
    if score is None:
        return "neutral"
    if score >= bull_strong:
        return "bullish"
    if score >= bull:
        return "bullish"
    if score <= bear_strong:
        return "bearish"
    if score <= bear:
        return "cautious"
    return "neutral"


def compute_section_verdicts(summaries: dict, correlations: list,
                             historical: list, sectors: dict) -> dict:
    """
    Produce a data-driven verdict for each section. Each verdict reads the
    actual numbers and translates them into a one-liner + explanation +
    bullet observations.
    """

    # ────── 1. FX VERDICT ──────
    usdinr_5d   = _get(summaries, "usdinr",  "change_5d_pct", 0) or 0
    usdinr_last = _get(summaries, "usdinr",  "last")
    usdinr_rank = _get(summaries, "usdinr",  "pct_rank_1y")
    dxy_5d      = _get(summaries, "dxy",     "change_5d_pct", 0) or 0
    dxy_last    = _get(summaries, "dxy",     "last")
    jpyinr_5d   = _get(summaries, "jpyinr",  "change_5d_pct", 0) or 0
    cny_5d      = _get(summaries, "usdcny",  "change_5d_pct", 0) or 0
    nifty_5d    = _get(summaries, "nifty",   "change_5d_pct", 0) or 0

    fx_obs = []
    fx_score = 0   # +bullish / -bearish from FX lens (for Indian equities)

    if usdinr_5d > 0.5:
        fx_score -= 2
        fx_obs.append(f"Rupee weakening fast ({usdinr_5d:+.2f}% in 5d) — capital exiting India 🔴")
    elif usdinr_5d > 0.2:
        fx_score -= 1
        fx_obs.append(f"Rupee mildly weakening ({usdinr_5d:+.2f}% in 5d) 🟡")
    elif usdinr_5d < -0.3:
        fx_score += 2
        fx_obs.append(f"Rupee strengthening ({usdinr_5d:+.2f}% in 5d) — FII capital flowing in 🟢")
    if usdinr_rank is not None:
        if usdinr_rank >= 90:
            fx_score -= 1
            fx_obs.append(f"USD/INR at {usdinr_rank}th percentile — near 1-year HIGH; rupee at extreme weakness ⚠️")
        elif usdinr_rank <= 10:
            fx_score += 1
            fx_obs.append(f"USD/INR at {usdinr_rank}th percentile — near 1-year LOW; rupee at extreme strength ✅")

    if dxy_5d > 0.7:
        fx_score -= 2
        fx_obs.append(f"DXY (USD index) {dxy_5d:+.2f}% in 5d — strong dollar pressuring all EM 🔴")
    elif dxy_5d < -0.5:
        fx_score += 1
        fx_obs.append(f"DXY {dxy_5d:+.2f}% in 5d — dollar weakening, supportive for EM/commodities 🟢")

    if jpyinr_5d > 1:
        fx_score -= 1
        fx_obs.append(f"JPY/INR up {jpyinr_5d:+.2f}% — yen strength is a classic risk-OFF signal 🔴")
    if cny_5d > 0.5:
        fx_score -= 1
        fx_obs.append(f"USD/CNY {cny_5d:+.2f}% — China currency stress, watch for spillover 🟡")

    # FII inferred flow
    if usdinr_5d > 0.3 and nifty_5d < -1:
        fx_obs.append(f"Combination: rupee weak + Nifty {nifty_5d:+.1f}% = clear FII OUTFLOW signal 🔴")
    elif usdinr_5d < -0.3 and nifty_5d > 1:
        fx_obs.append(f"Combination: rupee firm + Nifty {nifty_5d:+.1f}% = clear FII INFLOW signal 🟢")

    # Hysteresis: neutral band widened by 1 step on each side to prevent single-step tone flips
    if fx_score >= 3:
        fx_v = _verdict("bullish",
                        "Currencies are TAILWIND for Indian equities",
                        f"USD/INR is steady-to-firmer and DXY is not threatening. Capital flow looks supportive — foreign investors aren't fleeing.",
                        fx_obs)
    elif fx_score <= -4:
        usdinr_str = f"₹{usdinr_last:.2f}" if usdinr_last else "—"
        fx_v = _verdict("bearish",
                        "Currencies are HEADWIND — capital is fleeing EM",
                        f"Rupee at {usdinr_str} is weakening and DXY is rising. Foreign investors are converting back to dollars — bearish for Nifty until the rupee stabilizes.",
                        fx_obs)
    elif fx_score <= -2:
        fx_v = _verdict("cautious",
                        "Currencies showing MILD STRESS",
                        f"Rupee is weakening but not in panic. Watch USD/INR — if it accelerates higher, FII outflow risk rises.",
                        fx_obs)
    else:
        usdinr_str = f"₹{usdinr_last:.2f}" if usdinr_last else "—"
        fx_v = _verdict("neutral",
                        "Currencies are RANGE-BOUND",
                        f"No strong directional flow. Currency lens is neutral on Indian equities right now.",
                        fx_obs or [f"USD/INR at {usdinr_str} (5d {usdinr_5d:+.2f}%)"])

    # ────── 2. COMMODITIES VERDICT ──────
    brent_last = _get(summaries, "brent", "last")
    brent_5d   = _get(summaries, "brent", "change_5d_pct", 0) or 0
    brent_20d  = _get(summaries, "brent", "change_20d_pct", 0) or 0
    gold_5d    = _get(summaries, "gold",  "change_5d_pct", 0) or 0
    gold_20d   = _get(summaries, "gold",  "change_20d_pct", 0) or 0
    gold_rank  = _get(summaries, "gold",  "pct_rank_1y")
    copper_5d  = _get(summaries, "copper","change_5d_pct", 0) or 0
    copper_20d = _get(summaries, "copper","change_20d_pct", 0) or 0

    cm_obs = []
    cm_score = 0

    # Oil regime
    if brent_last:
        if brent_last > 95:
            cm_score -= 2
            cm_obs.append(f"Brent at ${brent_last:.0f}/bbl — ELEVATED. India CAD pressure, inflation risk 🔴")
        elif brent_last > 85:
            cm_score -= 1
            cm_obs.append(f"Brent at ${brent_last:.0f}/bbl — above comfortable range for India 🟡")
        elif brent_last < 70:
            cm_score += 2
            cm_obs.append(f"Brent at ${brent_last:.0f}/bbl — favorable for India CAD and rupee 🟢")
    if brent_5d > 4:
        cm_score -= 2
        cm_obs.append(f"Oil spike: {brent_5d:+.1f}% in 5 days — inflation pressure building 🔴")
    elif brent_5d < -4:
        cm_score += 1
        cm_obs.append(f"Oil falling: {brent_5d:+.1f}% in 5d — inflation cooling 🟢")

    # Gold (fear vs inflation)
    if gold_5d > 2 and brent_5d > 2:
        cm_obs.append(f"Gold {gold_5d:+.1f}% + Oil {brent_5d:+.1f}% — INFLATION REGIME 🔥")
    elif gold_5d > 2 and dxy_5d > 0.5:
        cm_score -= 1
        cm_obs.append(f"Gold {gold_5d:+.1f}% + strong dollar — DOUBLE SAFE-HAVEN bid (extreme fear) 🛡️")
    elif gold_5d < -2:
        cm_score += 1
        cm_obs.append(f"Gold {gold_5d:+.1f}% — risk appetite healthy, no flight to safety 🟢")
    if gold_rank is not None and gold_rank >= 90:
        cm_obs.append(f"Gold at {gold_rank}th percentile of 1Y — near record highs ⚠️")

    # Copper (Dr. Copper)
    if copper_5d > 2:
        cm_score += 1
        cm_obs.append(f"Dr. Copper {copper_5d:+.1f}% — global growth signal POSITIVE 🟢")
    elif copper_5d < -3:
        cm_score -= 2
        cm_obs.append(f"Copper {copper_5d:+.1f}% — Dr. Copper warning of slowing growth/recession 🔴")

    if cm_score >= 3:
        cm_v = _verdict("bullish", "Commodities supportive (growth-friendly)",
                        "Oil is benign, copper is firm, gold isn't on a fear bid. Conditions support risk-taking.", cm_obs)
    elif cm_score <= -4:
        cm_v = _verdict("bearish", "Commodities sending STAGFLATION signals",
                        "High oil + soft copper + gold strong = inflation + slowing growth = stagflation regime. Worst combination for stocks.", cm_obs)
    elif cm_score <= -2:
        cm_v = _verdict("cautious", "Commodities mixed-to-negative",
                        "Some inflationary pressure or growth concerns showing. Not a clear regime yet — watch for confirmation.", cm_obs)
    else:
        cm_v = _verdict("neutral", "Commodities are quiet",
                        "No strong inflation or recession signal from commodities. Neutral backdrop.", cm_obs)

    # ────── 3. BONDS & VOLATILITY VERDICT ──────
    us10y_last  = _get(summaries, "us10y",    "last", 0) or 0
    us10y_rank  = _get(summaries, "us10y",    "pct_rank_1y")
    us10y_5d    = _get(summaries, "us10y",    "change_5d_pct", 0) or 0
    us3m_last   = _get(summaries, "us3m",     "last", 0) or 0
    vix_last    = _get(summaries, "vix",      "last", 0) or 0
    vix_5d      = _get(summaries, "vix",      "change_5d_pct", 0) or 0
    indiavix_l  = _get(summaries, "indiavix", "last")
    indiavix_r  = _get(summaries, "indiavix", "pct_rank_1y")

    bd_obs = []
    bd_score = 0
    yc_inverted = us10y_last and us3m_last and us10y_last < us3m_last

    if us10y_last > 4.5:
        bd_score -= 2
        bd_obs.append(f"US 10Y at {us10y_last:.2f}% — RESTRICTIVE; capital pulling to US bonds 🔴")
    elif us10y_last > 4.0:
        bd_score -= 1
        bd_obs.append(f"US 10Y at {us10y_last:.2f}% — elevated; some pressure on EM 🟡")
    elif us10y_last < 3.5 and us10y_last > 0:
        bd_score += 1
        bd_obs.append(f"US 10Y at {us10y_last:.2f}% — accommodative; supportive for EM 🟢")

    if us10y_rank is not None and us10y_rank >= 80:
        bd_obs.append(f"US 10Y at {us10y_rank}th percentile of 1Y — near year highs ⚠️")

    if yc_inverted:
        bd_score -= 1
        bd_obs.append(f"Yield curve INVERTED (10Y {us10y_last:.2f}% < 3M {us3m_last:.2f}%) — recession warning 12-18m forward ⚠️")

    if vix_last > 25:
        bd_score -= 2
        bd_obs.append(f"US VIX at {vix_last:.1f} — REAL FEAR (>25) 🔴")
    elif vix_last > 20:
        bd_score -= 1
        bd_obs.append(f"US VIX at {vix_last:.1f} — elevated, not panic 🟡")
    elif vix_last < 14:
        bd_obs.append(f"US VIX at {vix_last:.1f} — complacency (often precedes sell-offs) 🟡")
    else:
        bd_obs.append(f"US VIX at {vix_last:.1f} — normal range")

    if indiavix_l:
        if indiavix_l > 25:
            bd_score -= 2
            bd_obs.append(f"India VIX at {indiavix_l:.1f} — REAL FEAR in Nifty 🔴")
        elif indiavix_l > 20:
            bd_score -= 1
            bd_obs.append(f"India VIX at {indiavix_l:.1f} — elevated 🟡")
        elif indiavix_l < 13:
            bd_obs.append(f"India VIX at {indiavix_l:.1f} — complacent 🟡")
        if indiavix_r is not None and indiavix_r >= 90:
            bd_obs.append(f"India VIX at {indiavix_r}th percentile of 1Y — near peak fear ⚠️ (often a contrarian signal)")

    if vix_5d > 15:
        bd_score -= 1
        bd_obs.append(f"VIX up {vix_5d:+.1f}% in 5d — fear rising")

    if bd_score >= 2:
        bd_v = _verdict("bullish", "Rates accommodative, fear muted",
                        "Yields are not restrictive and volatility is contained. Backdrop supports risk-taking.", bd_obs)
    elif bd_score <= -4:
        bd_v = _verdict("bearish", "Tight financial conditions + elevated fear",
                        "Yields are restrictive AND fear is rising. This is the textbook risk-off setup — defensive posture.", bd_obs)
    elif bd_score <= -2:
        bd_v = _verdict("cautious", "Rates/volatility creating pressure",
                        "Conditions are not extreme but unfriendly. Watch for either a yield retreat or VIX cool-down before sizing up.", bd_obs)
    else:
        bd_v = _verdict("neutral", "Rates and fear in normal ranges",
                        "Nothing alarming from bonds or volatility. Markets can move on other catalysts.", bd_obs)

    # ────── 4. EQUITY INDICES VERDICT ──────
    sp500_5d   = _get(summaries, "sp500",   "change_5d_pct", 0) or 0
    sp500_20d  = _get(summaries, "sp500",   "change_20d_pct", 0) or 0
    nasdaq_5d  = _get(summaries, "nasdaq",  "change_5d_pct", 0) or 0
    dow_5d     = _get(summaries, "dow",     "change_5d_pct", 0) or 0
    nifty_20d  = _get(summaries, "nifty",   "change_20d_pct", 0) or 0
    hang_5d    = _get(summaries, "hangseng","change_5d_pct", 0) or 0
    nikkei_5d  = _get(summaries, "nikkei",  "change_5d_pct", 0) or 0

    eq_obs = []
    # Synchronization check
    region_5d = [sp500_5d, nasdaq_5d, hang_5d, nikkei_5d, nifty_5d]
    n_pos = sum(1 for x in region_5d if x > 0.5)
    n_neg = sum(1 for x in region_5d if x < -0.5)

    if n_pos >= 4:
        eq_score = 2
        eq_obs.append(f"{n_pos}/5 major regions UP — synchronized risk-on 🟢")
    elif n_neg >= 4:
        eq_score = -2
        eq_obs.append(f"{n_neg}/5 major regions DOWN — synchronized risk-off 🔴")
    elif n_pos >= 3:
        eq_score = 1
        eq_obs.append(f"{n_pos}/5 regions positive — leaning risk-on 🟢")
    elif n_neg >= 3:
        eq_score = -1
        eq_obs.append(f"{n_neg}/5 regions negative — leaning risk-off 🔴")
    else:
        eq_score = 0
        eq_obs.append(f"Mixed: {n_pos} up / {n_neg} down — divergent regions 🟡")

    # Nifty vs S&P
    diff = nifty_5d - sp500_5d
    if diff > 2.5:
        eq_obs.append(f"Nifty {nifty_5d:+.1f}% OUTPERFORMING S&P {sp500_5d:+.1f}% — India-specific bullish 🟢")
        eq_score += 1
    elif diff < -2.5:
        eq_obs.append(f"Nifty {nifty_5d:+.1f}% UNDERPERFORMING S&P {sp500_5d:+.1f}% — India-specific drag 🔴")
        eq_score -= 1
    else:
        eq_obs.append(f"Nifty tracking S&P (Δ {diff:+.1f}%) — no India-specific story right now")

    # 20d trend confirmation
    if sp500_20d > 4 and nifty_20d > 4:
        eq_obs.append(f"20d trend: S&P {sp500_20d:+.1f}%, Nifty {nifty_20d:+.1f}% — uptrends intact 🟢")
    elif sp500_20d < -4 and nifty_20d < -4:
        eq_obs.append(f"20d trend: S&P {sp500_20d:+.1f}%, Nifty {nifty_20d:+.1f}% — both in downtrends 🔴")
        eq_score -= 1

    if eq_score >= 3:
        eq_v = _verdict("bullish", "Equities in a synchronized RISK-ON",
                        "Most major indices are rising together. Trend is your friend — pull-backs are buyable in this regime.", eq_obs)
    elif eq_score <= -3:
        eq_v = _verdict("bearish", "Equities in a synchronized RISK-OFF",
                        "Most major indices are falling together. This is when capital protection matters most — don't try to catch the bottom.", eq_obs)
    elif eq_score <= -2:
        eq_v = _verdict("cautious", "Equities under MODERATE pressure",
                        "Some indices weak, others holding. Selective downside, not a full risk-off — but trim leveraged longs.", eq_obs)
    elif eq_score >= 2:
        eq_v = _verdict("bullish", "Equities tilting POSITIVE",
                        "More green than red across regions. Risk-on bias intact, though not euphoric.", eq_obs)
    else:
        eq_v = _verdict("neutral", "Equities are MIXED",
                        "No clear global direction. Stock-specific approach better than directional bets right now.", eq_obs)

    # ────── 5. SECTOR VERDICT (Indian sectors) ──────
    sec_obs = []
    sec_score = 0
    if sectors and sectors.get("leaders"):
        avg = sectors.get("avg_composite", 0) or 0
        leaders = sectors.get("leaders", [])
        laggards = sectors.get("laggards", [])
        leader_names = [l["name"].replace("Nifty ", "") for l in leaders]
        laggard_names = [l["name"].replace("Nifty ", "") for l in laggards]

        # Cyclical vs defensive read
        cyclicals = {"Bank Nifty", "Auto", "Metal", "Realty", "Energy"}
        defensives = {"FMCG", "Pharma", "IT"}
        leader_set = set(l["name"].replace("Nifty ", "").replace(" Nifty", "") for l in leaders)
        leader_set.update({l["name"] for l in leaders})
        cyc_count = sum(1 for l in leaders if l["name"] in cyclicals or l["name"].replace("Nifty ", "") in cyclicals)
        def_count = sum(1 for l in leaders if l["name"] in defensives or l["name"].replace("Nifty ", "") in defensives)

        sec_obs.append(f"Top 3 leaders: {', '.join(leader_names)} 🟢")
        sec_obs.append(f"Top 3 laggards: {', '.join(laggard_names)} 🔴")
        sec_obs.append(f"Average sector composite: {avg:+.2f}")

        if cyc_count >= 2:
            sec_score += 1
            sec_obs.append(f"Cyclical sectors leading ({cyc_count}/3) — growth/risk-on rotation 🟢")
        if def_count >= 2:
            sec_score -= 1
            sec_obs.append(f"Defensive sectors leading ({def_count}/3) — caution / risk-off rotation 🟡")

        if avg > 3:
            sec_score += 2
            sec_obs.append("Broad participation — most sectors green 🟢")
        elif avg < -3:
            sec_score -= 2
            sec_obs.append("Broad weakness — most sectors red 🔴")

        # Spotlight unusual moves
        for s in leaders[:2]:
            if s["composite"] > 8:
                sec_obs.append(f"⚡ {s['name']} composite {s['composite']:+.2f} — strong outperformance, but check 1Y rank for overheating")
        for s in laggards[:2]:
            if s["composite"] < -7:
                sec_obs.append(f"⚠️ {s['name']} composite {s['composite']:+.2f} — sharp underperformance; capitulation or value?")

    if sec_score >= 3:
        sec_v = _verdict("bullish", "Sector rotation favors RISK-ON",
                        "Cyclicals leading, broad participation. This is the textbook 'growth' regime in Indian sectors.", sec_obs)
    elif sec_score <= -3:
        sec_v = _verdict("bearish", "Sector rotation favors DEFENSIVE",
                        "Defensives leading and/or broad weakness. Stick to FMCG/Pharma; avoid metals, banks unless you have very high conviction.", sec_obs)
    elif sec_score >= 2:
        sec_v = _verdict("bullish", "Sectors tilting POSITIVE",
                        "Decent leadership from growth-sensitive sectors. Selective opportunities in leaders.", sec_obs)
    elif sec_score <= -2:
        sec_v = _verdict("cautious", "Sectors showing CAUTION signals",
                        "Defensive leadership or weak averages. Trim exposure to cyclicals.", sec_obs)
    else:
        sec_v = _verdict("neutral", "No clear sector leadership",
                        "Choppy, no theme. Stock-specific picks rather than sector bets.", sec_obs)

    # ────── 6. CRYPTO VERDICT ──────
    btc_5d  = _get(summaries, "btc",  "change_5d_pct", 0) or 0
    btc_20d = _get(summaries, "btc",  "change_20d_pct", 0) or 0
    eth_5d  = _get(summaries, "eth",  "change_5d_pct", 0) or 0

    cr_obs = []
    cr_score = 0
    if btc_5d > 5:
        cr_score += 2
        cr_obs.append(f"BTC {btc_5d:+.1f}% in 5d — speculative capital flowing aggressively 🟢")
    elif btc_5d > 2:
        cr_score += 1
        cr_obs.append(f"BTC {btc_5d:+.1f}% — modest risk-on signal 🟢")
    elif btc_5d < -7:
        cr_score -= 2
        cr_obs.append(f"BTC {btc_5d:+.1f}% — speculative capital fleeing; early risk-off precursor 🔴")
    elif btc_5d < -3:
        cr_score -= 1
        cr_obs.append(f"BTC {btc_5d:+.1f}% — softening; watch for spillover to tech")

    if eth_5d and abs(eth_5d) > 5:
        cr_obs.append(f"ETH {eth_5d:+.1f}% — high-beta crypto confirming direction")

    if abs(btc_5d - nasdaq_5d) > 5:
        cr_obs.append(f"BTC and Nasdaq DIVERGING (BTC {btc_5d:+.1f}% vs Nasdaq {nasdaq_5d:+.1f}%) — regime shift signal ⚠️")

    if cr_score >= 3:
        cr_v = _verdict("bullish", "Crypto signals RISK-ON",
                        "Speculative capital is active. Consistent with risk-on regimes — but crypto can flip fast.", cr_obs)
    elif cr_score <= -3:
        cr_v = _verdict("bearish", "Crypto signals RISK-OFF",
                        "Speculative capital is retreating. Often a forward indicator for tech/Nasdaq weakness.", cr_obs)
    elif cr_score <= -2:
        cr_v = _verdict("cautious", "Crypto softening",
                        "Modest weakness; not a panic signal yet. Watch BTC level and Nasdaq alignment.", cr_obs)
    else:
        cr_v = _verdict("neutral", "Crypto quiet",
                        "No strong directional signal from crypto. Won't move the macro view either way today.", cr_obs)

    # ────── 7. CORRELATIONS VERDICT ──────
    corr_obs = []
    if correlations:
        holding = sum(1 for c in correlations if c.get("holding"))
        broken = len(correlations) - holding
        broken_pairs = [c["pair"] for c in correlations if not c.get("holding")]
        corr_obs.append(f"{holding}/{len(correlations)} textbook relationships HOLDING ({broken} broken)")
        if broken_pairs:
            corr_obs.append(f"Broken pairs: {', '.join(broken_pairs[:4])}")

        # Specific notable patterns
        for c in correlations:
            if c["key1"] == "gold" and c["key2"] == "dxy" and not c["holding"]:
                corr_obs.append("Gold ↔ DXY broken: both may be rising together — DOUBLE SAFE-HAVEN bid (extreme fear)")
            if c["key1"] == "vix" and c["key2"] == "sp500" and not c["holding"]:
                corr_obs.append("VIX ↔ S&P broken: unusual — investigate")
            if c["key1"] == "btc" and c["key2"] == "nasdaq" and not c["holding"]:
                corr_obs.append("BTC ↔ Nasdaq broken: regime change in speculative flows possible")

        if broken == 0:
            cor_v = _verdict("bullish", "All correlations HOLDING — markets behaving normally",
                            "Textbook inter-market relationships are intact. Regime is stable; signals are reliable.", corr_obs)
        elif broken <= 2:
            cor_v = _verdict("neutral", "Most correlations holding, minor breakdowns",
                            "A couple of relationships are off-pattern but not enough to suggest a regime shift.", corr_obs)
        elif broken <= 4:
            cor_v = _verdict("cautious", "Several correlations BROKEN — regime in flux",
                            "Multiple textbook relationships are not behaving normally. Markets may be transitioning between regimes.", corr_obs)
        else:
            cor_v = _verdict("bearish", "Correlation chaos — REGIME SHIFT in progress",
                            "More than half of relationships broken. Something structural is changing — be very careful with directional bets.", corr_obs)
    else:
        cor_v = _verdict("neutral", "Correlation data unavailable",
                        "Could not compute pair-wise correlations.", [])

    # ────── 8. HISTORICAL CONTEXT VERDICT ──────
    hist_obs = []
    extremes = []
    elevated = []
    depressed = []
    for h in (historical or []):
        if h["tone"] == "extreme":
            extremes.append(h)
        elif h["tone"] == "high":
            elevated.append(h)
        elif h["tone"] == "low":
            depressed.append(h)

    for h in extremes:
        side = "1Y HIGH" if h["pct_rank_1y"] >= 90 else "1Y LOW"
        hist_obs.append(f"{h['name']} {h['unit']}{h['last']:.2f} → {side} ({h['pct_rank_1y']}th %ile) ⚠️")
    for h in elevated[:3]:
        hist_obs.append(f"{h['name']} elevated ({h['pct_rank_1y']}th %ile)")
    for h in depressed[:3]:
        hist_obs.append(f"{h['name']} depressed ({h['pct_rank_1y']}th %ile)")

    n_extremes = len(extremes)
    if n_extremes == 0:
        hist_v = _verdict("neutral", "No indicators at extremes",
                        "All key macro indicators are within their normal 1-year ranges. No mean-reversion or breakout setup signaled.", hist_obs)
    elif n_extremes == 1:
        h = extremes[0]
        hist_v = _verdict("cautious", f"{h['name']} at 1-year extreme",
                        f"{h['name']} is at the {h['pct_rank_1y']}th percentile — extreme zone. Such readings tend to mean-revert OR mark regime change. Monitor.", hist_obs)
    else:
        # Multiple extremes — could be coordinated stress
        names = ", ".join(h["name"] for h in extremes[:3])
        hist_v = _verdict("bearish", f"{n_extremes} indicators at 1-year extremes",
                        f"{names} all at extreme levels simultaneously. Coordinated extremes often signal a regime in stress — historically, such setups precede sharp reversals or breakouts.", hist_obs)

    return {
        "fx":            fx_v,
        "commodity":     cm_v,
        "bond":          bd_v,
        "equity":        eq_v,
        "sector":        sec_v,
        "crypto":        cr_v,
        "correlations":  cor_v,
        "historical":    hist_v,
    }


# ─────────────────────────── layman narrative ───────────────────────────

def generate_layman_summary(summaries: dict, regime: dict, composite: dict,
                            india: dict, flows: list, calibration: dict = None) -> dict:
    """
    Build a plain-English multi-section narrative for non-experts.
    Every section has a tone (bullish/bearish/neutral/cautious) for color coding.

    Returns:
      {
        "headline": str,
        "headline_tone": "bullish" | "bearish" | "neutral" | "cautious",
        "sections": [
          {"title": str, "icon": str, "tone": str, "body": str}, ...
        ],
        "verdict": {"action": str, "tone": str, "explanation": str}
      }
    """
    # Pull common values
    sp500_5d   = _get(summaries, "sp500",   "change_5d_pct", 0) or 0
    nasdaq_5d  = _get(summaries, "nasdaq",  "change_5d_pct", 0) or 0
    nifty_5d   = _get(summaries, "nifty",   "change_5d_pct", 0) or 0
    nifty_last = _get(summaries, "nifty",   "last")
    vix_last   = _get(summaries, "vix",     "last") or 0
    gold_5d    = _get(summaries, "gold",    "change_5d_pct", 0) or 0
    gold_last  = _get(summaries, "gold",    "last")
    dxy_last   = _get(summaries, "dxy",     "last")
    dxy_5d     = _get(summaries, "dxy",     "change_5d_pct", 0) or 0
    brent_last = _get(summaries, "brent",   "last")
    brent_5d   = _get(summaries, "brent",   "change_5d_pct", 0) or 0
    us10y_last = _get(summaries, "us10y",   "last")
    usdinr_last= _get(summaries, "usdinr",  "last")
    usdinr_5d  = _get(summaries, "usdinr",  "change_5d_pct", 0) or 0
    btc_5d     = _get(summaries, "btc",     "change_5d_pct", 0) or 0
    copper_5d  = _get(summaries, "copper",  "change_5d_pct", 0) or 0

    score = composite.get("score", 0)
    regime_label = regime.get("label", "")

    # Most-recent close date across the panel — used to stamp the headline so users
    # know the readout reflects PRIOR-SESSION closes, not live intraday.
    most_recent_ts = None
    for s in summaries.values():
        ts = s.get("ts_last")
        if ts and (most_recent_ts is None or ts > most_recent_ts):
            most_recent_ts = ts
    as_of_text = f" — as of {most_recent_ts} close" if most_recent_ts else ""

    # ── HEADLINE ── (uses calibrated buckets when available, else hardcoded fallback)
    cal_buckets = (calibration or {}).get("buckets") if calibration else None
    cal_source  = (calibration or {}).get("source") if calibration else "default"
    if cal_buckets:
        b_strong_on  = cal_buckets["strong_risk_on"]
        b_on         = cal_buckets["risk_on"]
        b_off        = cal_buckets["risk_off"]
        b_strong_off = cal_buckets["strong_risk_off"]
    else:
        b_strong_on, b_on, b_off, b_strong_off = 50, 20, -20, -50

    cal_tag = f" (calibrated: {cal_source})" if cal_source == "replay" else ""
    if score >= b_strong_on:
        headline_tone = "bullish"
        headline = f"🟢 STRONG RISK-ON over last 5 days{as_of_text} — money chasing growth. Score: +{score:.0f}/100{cal_tag}."
    elif score >= b_on:
        headline_tone = "bullish"
        headline = f"🟢 Markets RISK-ON over last 5 days{as_of_text}, not euphoric. Score: +{score:.0f}/100{cal_tag}."
    elif score > b_off:
        headline_tone = "neutral"
        headline = f"🟡 Markets NEUTRAL over last 5 days{as_of_text} — no clear direction. Score: {score:+.0f}/100{cal_tag}. Wait and watch."
    elif score > b_strong_off:
        headline_tone = "cautious"
        headline = f"🟠 Markets SLIGHTLY DEFENSIVE over last 5 days{as_of_text} — be cautious. Score: {score:.0f}/100{cal_tag}."
    else:
        headline_tone = "bearish"
        headline = f"🔴 STRONG RISK-OFF over last 5 days{as_of_text} — capital fleeing. Score: {score:.0f}/100{cal_tag}. Defensive posture."

    sections = []

    # ── SECTION 0: DATA-AS-OF STAMP (so user knows freshness) ──
    if most_recent_ts:
        sections.append({
            "title": "Data as-of",
            "icon": "🕐",
            "tone": "neutral",
            "body": (
                f"All numbers below reflect closing prices from <b>{most_recent_ts}</b>. "
                f"Markets close at different times across regions — Indian markets close at 15:30 IST, "
                f"US at 02:00 IST next day. So 'last 5 days' means the 5 most recent trading sessions of each instrument. "
                f"<b>If you're checking pre-market in India, US data is from a few hours ago; India data is yesterday's close.</b>"
            ),
            "is_html": True,
        })

    # ── SECTION 1: WHAT'S HAPPENING IN THE WORLD ──
    world_parts = []
    if abs(sp500_5d) > 0.5:
        emoji = "📈" if sp500_5d > 0 else "📉"
        world_parts.append(f"{emoji} <b>US stocks</b> (S&P 500) are <b>{('UP' if sp500_5d > 0 else 'DOWN')} {abs(sp500_5d):.1f}%</b> over the past 5 days.")
    if vix_last:
        if vix_last > 25:
            world_parts.append(f"😨 <b>VIX (fear gauge)</b> is at <b>{vix_last:.1f}</b> — investors are nervous. Above 20 means real worry.")
        elif vix_last < 15:
            world_parts.append(f"😌 <b>VIX (fear gauge)</b> is low at <b>{vix_last:.1f}</b> — calm/complacent. Below 15 means traders feel safe (sometimes too safe).")
        else:
            world_parts.append(f"😐 <b>VIX (fear gauge)</b> is at <b>{vix_last:.1f}</b> — normal range, no panic and no euphoria.")
    if abs(gold_5d) > 1 and gold_last:
        emoji = "🪙" if gold_5d > 0 else "💸"
        meaning = "Gold rises when investors are scared — flight to safety" if gold_5d > 0 else "Gold falling means risk appetite is healthy — investors don't need a safe haven"
        world_parts.append(f"{emoji} <b>Gold</b> at <b>${gold_last:.0f}</b> ({gold_5d:+.1f}% in 5d). {meaning}.")
    if abs(dxy_5d) > 0.5 and dxy_last:
        if dxy_5d > 0:
            world_parts.append(f"💵 <b>US Dollar (DXY)</b> at <b>{dxy_last:.1f}</b> ({dxy_5d:+.1f}% in 5d) — dollar strengthening. Bad for emerging markets like India.")
        else:
            world_parts.append(f"🌍 <b>US Dollar (DXY)</b> at <b>{dxy_last:.1f}</b> ({dxy_5d:+.1f}% in 5d) — dollar weakening. Good for emerging markets and commodities.")
    if abs(brent_5d) > 2 and brent_last:
        if brent_5d > 0:
            world_parts.append(f"⛽ <b>Brent oil</b> at <b>${brent_last:.0f}/barrel</b> ({brent_5d:+.1f}% in 5d) — rising. Inflation pressure builds, and bad news for India which imports ~85% of its oil.")
        else:
            world_parts.append(f"⛽ <b>Brent oil</b> at <b>${brent_last:.0f}/barrel</b> ({brent_5d:+.1f}% in 5d) — falling. Inflation pressure cools, good for India.")
    if us10y_last:
        if us10y_last > 4.5:
            world_parts.append(f"🇺🇸 <b>US 10-year bond yield</b> at <b>{us10y_last:.2f}%</b> — high. Money is flowing into safe US bonds instead of risky stocks worldwide.")
        elif us10y_last < 3.5:
            world_parts.append(f"🇺🇸 <b>US 10-year bond yield</b> at <b>{us10y_last:.2f}%</b> — low. Cheap money supports stock markets globally.")
        else:
            world_parts.append(f"🇺🇸 <b>US 10-year bond yield</b> at <b>{us10y_last:.2f}%</b> — moderate range, neither tight nor easy.")
    if abs(btc_5d) > 5:
        if btc_5d > 0:
            world_parts.append(f"₿ <b>Bitcoin</b> {btc_5d:+.1f}% in 5d — speculative money is flowing freely (risk-on signal).")
        else:
            world_parts.append(f"❄️ <b>Bitcoin</b> {btc_5d:.1f}% in 5d — speculative money is retreating (risk-off precursor).")

    if world_parts:
        sections.append({
            "title": "What's happening in the world",
            "icon": "🌍",
            "tone": headline_tone,
            "body": " ".join(world_parts),
        })

    # ── SECTION 2: WHY IT'S HAPPENING (REGIME EXPLANATION) ──
    regime_explanations = {
        "Risk-On Growth": (
            "When stocks are rising, bond yields are climbing (because investors are SELLING safe bonds to BUY stocks), "
            "the dollar is steady or weak, and the fear gauge (VIX) is low — that's the textbook 'risk-on' regime. "
            "Investors believe the economy is healthy and growing. They're willing to bet on growth."
        ),
        "Risk-Off / Flight to Safety": (
            "When stocks fall AND gold rises AND the dollar strengthens AND the fear gauge spikes — investors are scared. "
            "They're pulling money out of risky assets (stocks, emerging markets, crypto) and parking it in safe places "
            "(US bonds, gold, US dollar cash). This is 'flight to safety'. It usually doesn't end until the fear subsides."
        ),
        "Inflation Concern": (
            "When oil and commodities are spiking, bond yields are rising fast, and gold is also rising — markets are "
            "worried about inflation. Central banks may need to raise interest rates, which makes borrowing expensive "
            "and slows growth. This is bad for high-growth stocks and good for hard assets like gold and energy companies."
        ),
        "Recession Watch": (
            "When the yield curve is inverted (short-term US bonds yield MORE than long-term ones), copper is falling, "
            "and oil is dropping — markets fear a recession is coming. Historically, every US recession in the last 60 years "
            "has been preceded by a yield-curve inversion. It's not a guarantee, but it's a serious warning."
        ),
        "Mixed / Transitioning": (
            "No single regime is dominating right now — some indicators point one way, others point the other. "
            "Markets are usually 'transitioning' between regimes during these phases. Best to wait for clearer signals "
            "before making big bets."
        ),
    }
    sections.append({
        "title": f"Why we're in '{regime_label}'",
        "icon": "🧭",
        "tone": headline_tone,
        "body": regime_explanations.get(regime_label, "Conditions are mixed and don't fit a clear historical pattern."),
    })

    # ── SECTION 3: MONEY FLOW IN PLAIN ENGLISH ──
    if flows:
        flow_text_parts = []
        for f in flows[:4]:
            flow_text_parts.append(f"<div class='gs-flow-item gs-{f['tone']}'>{f['icon']} {f['text']}</div>")
        sections.append({
            "title": "Where money is flowing",
            "icon": "💸",
            "tone": "neutral",
            "body": "".join(flow_text_parts),
            "is_html": True,
        })

    # ── SECTION 4: WHAT THIS MEANS FOR INDIA ──
    india_text_parts = []
    if usdinr_last:
        if usdinr_5d > 0.3:
            india_text_parts.append(
                f"💱 <b>Rupee at ₹{usdinr_last:.2f}/$ (weakening {usdinr_5d:+.1f}% in 5d).</b> "
                f"When rupee weakens, foreign investors (FIIs) lose money on their Indian stock holdings when converting back to dollars. "
                f"They tend to SELL Indian stocks during such periods. This is bearish for Nifty in the short term."
            )
        elif usdinr_5d < -0.3:
            india_text_parts.append(
                f"💱 <b>Rupee at ₹{usdinr_last:.2f}/$ (strengthening {usdinr_5d:+.1f}% in 5d).</b> "
                f"A firming rupee usually means foreign investors are BUYING Indian stocks — they need rupees to buy, which pushes the rupee up. "
                f"This is supportive for Nifty."
            )
        else:
            india_text_parts.append(
                f"💱 <b>Rupee at ₹{usdinr_last:.2f}/$ (stable).</b> No strong directional flow signal from currency."
            )

    if brent_last:
        if brent_last > 90:
            india_text_parts.append(
                f"⛽ <b>Crude oil at ${brent_last:.0f}/barrel — elevated.</b> "
                f"India imports about 85% of its oil. High oil prices mean: (1) rupee under pressure, (2) inflation rises, "
                f"(3) fiscal deficit widens. <b>Sectors hurt:</b> paint, aviation, tyres, plastics, OMCs (oil marketing). "
                f"<b>Sectors that benefit:</b> upstream oil producers (ONGC), some chemicals."
            )
        elif brent_last < 70:
            india_text_parts.append(
                f"⛽ <b>Crude oil at ${brent_last:.0f}/barrel — favorable.</b> "
                f"Cheaper oil is great news for India: (1) rupee gets support, (2) inflation cools, (3) fiscal pressure eases. "
                f"<b>Sectors that benefit:</b> paint companies (Asian Paints), tyres (MRF, Apollo), aviation (IndiGo), OMCs (HPCL, BPCL), "
                f"plastics/chemicals."
            )

    if us10y_last and us10y_last > 4.5:
        india_text_parts.append(
            f"🇺🇸 <b>US 10Y yield at {us10y_last:.2f}% — restrictive.</b> "
            f"When US bonds offer 4.5%+ risk-free, why would foreign investors take risk in Indian stocks? "
            f"They typically rotate capital BACK to US bonds. This pressures Nifty until US yields cool down."
        )

    if abs(nifty_5d - sp500_5d) > 2.5 and nifty_last:
        if nifty_5d > sp500_5d:
            india_text_parts.append(
                f"🇮🇳 <b>Nifty ({nifty_5d:+.1f}%) is OUTPERFORMING S&P 500 ({sp500_5d:+.1f}%) over 5 days.</b> "
                f"Something India-specific is working — could be domestic flows (DII buying), positive earnings, "
                f"government policy, or sector rotation. Decoupling is a positive sign of relative strength."
            )
        else:
            india_text_parts.append(
                f"🇮🇳 <b>Nifty ({nifty_5d:+.1f}%) is UNDERPERFORMING S&P 500 ({sp500_5d:+.1f}%) over 5 days.</b> "
                f"India-specific drag — could be FII selling, earnings disappointments, or election/policy uncertainty. "
                f"Underperformance means foreign investors are picking other markets over India."
            )

    if not india_text_parts:
        india_text_parts.append(
            "Conditions are largely neutral for India right now. Watch for changes in USD/INR, oil, or US yields "
            "as the next directional cues."
        )

    sections.append({
        "title": "What this means for India 🇮🇳",
        "icon": "🇮🇳",
        "tone": india.get("summary_tone", "neutral"),
        "body": "<br><br>".join(india_text_parts),
        "is_html": True,
    })

    # ── SECTION 5: ACTION GUIDANCE ── (uses calibrated thresholds)
    if score >= b_strong_on:
        action = "ADD risk gradually"
        action_tone = "bullish"
        action_text = (
            "Conditions favor risk-taking. If you're sitting in cash, this is a reasonable environment to deploy. "
            "<b>Prefer:</b> cyclicals (auto, banks, metals), high-beta names, mid/small-caps. "
            "<b>Avoid:</b> over-exposure to defensives — they'll lag in a risk-on tape. "
            "<b>Stop discipline:</b> still keep stops; even strong tapes have pullbacks."
        )
    elif score >= b_on:
        action = "SELECTIVE buying"
        action_tone = "bullish"
        action_text = (
            "Constructive but not euphoric. Pick spots carefully — don't chase already-extended names. "
            "<b>Prefer:</b> stocks pulling back to support in healthy uptrends. "
            "<b>Stop discipline:</b> tight stops; the regime can flip if oil spikes or VIX rises."
        )
    elif score > b_off:
        action = "WAIT and watch"
        action_tone = "neutral"
        action_text = (
            "No clear edge right now. <b>This is when traders lose money</b> — by forcing trades when there isn't a setup. "
            "Use this time to build watchlists, study companies, or just sit in cash. "
            "Re-engage when (a) score crosses +20 (risk-on confirmed) or (b) a high-conviction stock-specific setup appears."
        )
    elif score > b_strong_off:
        action = "REDUCE exposure"
        action_tone = "cautious"
        action_text = (
            "Defensive posture warranted. <b>Trim:</b> high-beta longs, leveraged positions. "
            "<b>Prefer if you must be long:</b> defensive sectors (FMCG, pharma, IT — IT especially benefits from weak rupee). "
            "<b>Cash is a position</b> — sitting out is a perfectly valid trade in this environment."
        )
    else:
        action = "PROTECT capital"
        action_tone = "bearish"
        action_text = (
            "Risk-off in force. <b>Top priority:</b> protect what you have. Cut leverage, reduce gross exposure, "
            "honor stops aggressively. <b>Avoid:</b> 'buying the dip' until VIX cools, gold tops out, or DXY peaks. "
            "Markets in flight-to-safety regimes can fall further than you think — never average down here."
        )

    return {
        "headline": headline,
        "headline_tone": headline_tone,
        "sections": sections,
        "verdict": {
            "action": action,
            "tone": action_tone,
            "explanation": action_text,
        },
    }
