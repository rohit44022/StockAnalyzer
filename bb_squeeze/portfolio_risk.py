"""
portfolio_risk.py — Portfolio-Level Risk Analysis (Correlation & Concentration)

In plain English, this module answers two questions about your portfolio:

1. ARE YOUR EGGS IN TOO FEW BASKETS?  (Concentration)
   If 60% of your money is in banking stocks and RBI hikes interest rates,
   all of them fall together. That is sector concentration risk. Similarly,
   if one stock is 40% of your portfolio and it crashes, your whole portfolio
   bleeds. This module flags such situations.

2. DO YOUR STOCKS MOVE TOGETHER?  (Correlation)
   Correlation measures how "in sync" two stocks are. A correlation of 1.0
   means they move in lockstep — when one falls 5%, the other falls 5% too.
   Holding 10 stocks that all move together is barely better than holding 1.
   True diversification means your stocks react differently to market events.

The Diversification Score (0–100) combines both checks. Higher is safer.
"""
from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd

from bb_squeeze.config import CSV_DIR
from bb_squeeze.data_loader import load_from_csv

_CORR_WINDOW = 60        # trading days used for correlation
_HIGH_CORR   = 0.75      # threshold above which two stocks are "too similar"
_SECTOR_WARN = 0.30      # >30 % in one sector triggers a warning
_POS_WARN    = 0.20      # >20 % in one stock triggers a warning


# ─────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────

def _returns(ticker: str, csv_dir: str) -> pd.Series | None:
    """Last _CORR_WINDOW daily returns for a ticker, or None if unavailable."""
    df = load_from_csv(ticker, csv_dir)
    if df is None or len(df) < 2:
        return None
    close = df["Close"].tail(_CORR_WINDOW + 1)
    ret = close.pct_change().dropna()
    return ret if len(ret) >= 10 else None  # need at least 10 points


def _pearson(a: pd.Series, b: pd.Series) -> float | None:
    """Pearson correlation on the overlapping date index."""
    combined = pd.concat([a, b], axis=1).dropna()
    if len(combined) < 10:
        return None
    return float(combined.iloc[:, 0].corr(combined.iloc[:, 1]))


# ─────────────────────────────────────────────────────────────────
#  MAIN FUNCTION
# ─────────────────────────────────────────────────────────────────

def analyze_portfolio_risk(
    positions: list[dict],
    csv_dir: str | None = None,
) -> dict:
    """
    Compute correlation & concentration risk for a list of portfolio positions.

    Each position dict must contain at minimum:
        ticker        (str)   e.g. "RELIANCE.NS"
        sector        (str)   e.g. "Energy" or "N/A"
        current_price (float)
        quantity      (int | float)

    Returns a rich dict — see module docstring for full schema.
    """
    csv_dir = csv_dir or CSV_DIR

    # ── guard: need at least 2 positions for meaningful analysis ──
    if not positions or len(positions) < 2:
        return {
            "available": False,
            "reason": "Need at least 2 positions for risk analysis.",
        }

    # ── market values ─────────────────────────────────────────────
    for p in positions:
        p["_mv"] = float(p["current_price"]) * float(p["quantity"])

    total_value = sum(p["_mv"] for p in positions)
    if total_value <= 0:
        return {"available": False, "reason": "Total portfolio value is zero."}

    # ── sector breakdown ──────────────────────────────────────────
    sector_map: dict[str, list[dict]] = {}
    for p in positions:
        s = p.get("sector") or "N/A"
        sector_map.setdefault(s, []).append(p)

    sector_breakdown = []
    for s, ps in sorted(sector_map.items()):
        sv = sum(x["_mv"] for x in ps)
        sector_breakdown.append({
            "sector":     s,
            "count":      len(ps),
            "value":      round(sv, 2),
            "weight_pct": round(sv / total_value * 100, 2),
        })
    sector_breakdown.sort(key=lambda x: x["value"], reverse=True)

    # ── per-position weights ──────────────────────────────────────
    for p in positions:
        p["_wt"] = p["_mv"] / total_value

    max_pos     = max(positions, key=lambda p: p["_wt"])
    max_pos_pct = round(max_pos["_wt"] * 100, 2)

    # ── concentration warnings ────────────────────────────────────
    warnings: list[str] = []
    for sb in sector_breakdown:
        if sb["weight_pct"] > _SECTOR_WARN * 100:
            warnings.append(
                f"{sb['sector']} sector is {sb['weight_pct']:.1f}% of your portfolio "
                f"({sb['count']} stock{'s' if sb['count'] > 1 else ''}) — "
                f"a single sector event (e.g. RBI rate hike for Banking, GST change for FMCG) "
                f"could hurt {sb['weight_pct']:.1f}% of your capital at once."
            )
    if max_pos_pct > _POS_WARN * 100:
        warnings.append(
            f"{max_pos['ticker']} is {max_pos_pct:.1f}% of your portfolio — "
            f"a single stock should ideally not exceed 20% of total capital."
        )

    # ── correlation matrix ────────────────────────────────────────
    tickers = [p["ticker"] for p in positions]
    ret_cache: dict[str, pd.Series | None] = {
        t: _returns(t, csv_dir) for t in tickers
    }

    high_correlations: list[dict] = []
    all_corrs: list[float] = []

    for a, b in combinations(tickers, 2):
        ra, rb = ret_cache[a], ret_cache[b]
        if ra is None or rb is None:
            continue
        c = _pearson(ra, rb)
        if c is None:
            continue
        all_corrs.append(c)
        if c > _HIGH_CORR:
            high_correlations.append({
                "stock_a":     a,
                "stock_b":     b,
                "correlation": round(c, 3),
            })

    high_correlations.sort(key=lambda x: x["correlation"], reverse=True)
    avg_corr = round(float(np.mean(all_corrs)), 3) if all_corrs else 0.0

    # ── diversification score ─────────────────────────────────────
    score = 100

    for sb in sector_breakdown:
        if sb["weight_pct"] > _SECTOR_WARN * 100:
            score -= 20                         # -20 per over-weight sector

    score -= len(high_correlations) * 10        # -10 per highly-correlated pair

    for p in positions:
        if p["_wt"] > _POS_WARN:
            score -= 15                         # -15 per over-weight position

    if len(sector_map) >= 5:
        score += 10                             # bonus for breadth

    score = max(0, min(100, score))

    # ── risk level ────────────────────────────────────────────────
    if score >= 70:
        risk_level = "WELL_DIVERSIFIED"
    elif score >= 40:
        risk_level = "MODERATELY_CONCENTRATED"
    else:
        risk_level = "HIGHLY_CONCENTRATED"

    # ── explanation ───────────────────────────────────────────────
    explanation = _build_explanation(
        risk_level, score, sector_breakdown, high_correlations,
        avg_corr, max_pos, max_pos_pct, total_value, len(sector_map),
    )

    # clean up internal keys before returning
    for p in positions:
        p.pop("_mv", None)
        p.pop("_wt", None)

    return {
        "available":             True,
        "total_positions":       len(positions),
        "total_value":           round(total_value, 2),
        "sector_breakdown":      sector_breakdown,
        "concentration_warnings": warnings,
        "high_correlations":     high_correlations,
        "avg_correlation":       avg_corr,
        "max_position_pct":      max_pos_pct,
        "max_position_ticker":   max_pos["ticker"],
        "diversification_score": score,
        "risk_level":            risk_level,
        "explanation":           explanation,
    }


# ─────────────────────────────────────────────────────────────────
#  EXPLANATION BUILDER
# ─────────────────────────────────────────────────────────────────

def _build_explanation(
    risk_level: str,
    score: int,
    sector_breakdown: list[dict],
    high_correlations: list[dict],
    avg_corr: float,
    max_pos: dict,
    max_pos_pct: float,
    total_value: float,
    num_sectors: int,
) -> str:
    lines: list[str] = []

    # ── header ───────────────────────────────────────────────────
    if risk_level == "WELL_DIVERSIFIED":
        lines.append(
            f"Your portfolio scores {score}/100 — well diversified. "
            f"You have spread your capital across {num_sectors} sector(s), "
            f"which means no single industry event can wipe out your portfolio."
        )
    elif risk_level == "MODERATELY_CONCENTRATED":
        lines.append(
            f"Your portfolio scores {score}/100 — moderately concentrated. "
            f"There are some risks worth addressing, but you are not in danger zone yet."
        )
    else:
        lines.append(
            f"Your portfolio scores {score}/100 — HIGHLY CONCENTRATED. "
            f"This is a serious risk flag. If one sector or stock goes wrong, "
            f"a large portion of your ₹{total_value:,.0f} portfolio will be hurt."
        )

    # ── sector concentration detail ───────────────────────────────
    lines.append("\n📊 SECTOR BREAKDOWN:")
    for sb in sector_breakdown:
        bar = "█" * int(sb["weight_pct"] / 5)
        flag = " ⚠️  OVER-WEIGHT" if sb["weight_pct"] > 30 else ""
        lines.append(f"  {sb['sector']:<20} {sb['weight_pct']:>5.1f}%  {bar}{flag}")

    heavy = [sb for sb in sector_breakdown if sb["weight_pct"] > 30]
    if heavy:
        lines.append(
            "\n⚠️  SECTOR CONCENTRATION RISK: "
            "When one sector gets bad news, ALL stocks in it tend to fall together. Examples:"
        )
        for sb in heavy:
            s = sb["sector"]
            if "bank" in s.lower() or "financ" in s.lower() or "nbfc" in s.lower():
                example = "RBI hiking rates, NPA concerns, or a credit crisis can crash all banking stocks simultaneously."
            elif "it" in s.lower() or "tech" in s.lower() or "software" in s.lower():
                example = "Rupee appreciation, US slowdown, or visa restrictions hit all IT stocks at once."
            elif "pharma" in s.lower() or "health" in s.lower():
                example = "US FDA import alerts or drug pricing pressure can drag down all pharma stocks together."
            elif "fmcg" in s.lower() or "consumer" in s.lower():
                example = "A GST hike or rural slowdown hurts the entire FMCG basket."
            elif "energy" in s.lower() or "oil" in s.lower():
                example = "A crude oil price shock or government pricing intervention hits all energy stocks."
            elif "metal" in s.lower() or "steel" in s.lower():
                example = "China dumping steel or a global slowdown crashes all metal stocks together."
            else:
                example = f"A sector-specific shock could impact all your {s} positions at once."
            lines.append(
                f"  • {s} ({sb['weight_pct']:.1f}% = ₹{sb['value']:,.0f}): {example}"
            )

    # ── single stock concentration ────────────────────────────────
    if max_pos_pct > 20:
        lines.append(
            f"\n⚠️  SINGLE STOCK RISK: {max_pos['ticker']} is {max_pos_pct:.1f}% of your portfolio. "
            f"If this stock falls 30%, your total portfolio loses {max_pos_pct * 0.3:.1f}%. "
            f"Consider trimming to below 20% of total capital."
        )

    # ── correlation section ───────────────────────────────────────
    lines.append(
        f"\n🔗 CORRELATION ANALYSIS (last {60} trading days):"
    )
    lines.append(
        f"  Average pairwise correlation: {avg_corr:.2f}  "
        + ("(stocks move very similarly — limited diversification benefit)" if avg_corr > 0.6
           else "(reasonable diversity — stocks don't all move in lockstep)")
    )
    lines.append(
        "  Correlation explained: A value of 1.0 means two stocks move in perfect lockstep. "
        "A value of 0 means they move independently. Negative means they move in opposite directions. "
        f"We flag pairs above {_HIGH_CORR} as 'high correlation' — holding both gives little extra safety."
    )

    if high_correlations:
        lines.append(f"\n  High-correlation pairs (correlation > {_HIGH_CORR}):")
        for hc in high_correlations[:8]:  # cap display at 8
            lines.append(
                f"    • {hc['stock_a']}  ↔  {hc['stock_b']}:  {hc['correlation']:.2f} — "
                f"when {hc['stock_a']} falls, {hc['stock_b']} tends to fall too."
            )
        if len(high_correlations) > 8:
            lines.append(f"    … and {len(high_correlations) - 8} more pairs.")
    else:
        lines.append("  No high-correlation pairs found — good sign.")

    # ── closing advice ────────────────────────────────────────────
    lines.append("\n💡 SUGGESTIONS:")
    if risk_level == "WELL_DIVERSIFIED":
        lines.append(
            "  Your portfolio construction is solid. Keep monitoring sector weights "
            "as prices change, and rebalance if any sector drifts above 30%."
        )
    elif risk_level == "MODERATELY_CONCENTRATED":
        if heavy:
            s_names = ", ".join(sb["sector"] for sb in heavy)
            lines.append(f"  • Reduce exposure to: {s_names}. Add 1–2 stocks from different sectors.")
        if high_correlations:
            lines.append(
                "  • Consider replacing one stock from each high-correlation pair with "
                "a stock from a different sector or business model."
            )
        lines.append(
            "  • Indian diversification options: PSU Banks vs Private Banks vs NBFCs are "
            "different; IT large-cap vs mid-cap behave differently; mix cyclical "
            "(metals, energy) with defensive (FMCG, pharma)."
        )
    else:  # HIGHLY_CONCENTRATED
        lines.append(
            "  STRONG ACTION ADVISED:"
        )
        lines.append(
            f"  • Target at least 5 sectors. You currently have {num_sectors}. "
            "Add exposure to sectors you don't hold."
        )
        lines.append(
            "  • No single stock should exceed 20% of portfolio. "
            f"Currently {max_pos['ticker']} is at {max_pos_pct:.1f}%."
        )
        lines.append(
            "  • On NSE, explore: Nifty 50 index fund as a base, then selectively "
            "add sector-specific stocks. Mix Banking + IT + Pharma + FMCG + Auto "
            "as a simple 5-sector framework."
        )
        lines.append(
            "  • If you are concentrated by choice (high-conviction bets), "
            "ensure you have strict stop-losses in place."
        )

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────
#  SELF-CHECK
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Synthetic smoke-test — no real CSV needed
    fake_positions = [
        {"ticker": "FAKE_A.NS", "sector": "Banking", "current_price": 500, "quantity": 100},
        {"ticker": "FAKE_B.NS", "sector": "Banking", "current_price": 300, "quantity": 50},
        {"ticker": "FAKE_C.NS", "sector": "IT",      "current_price": 1000, "quantity": 20},
    ]
    result = analyze_portfolio_risk(fake_positions, csv_dir="/tmp/nonexistent")
    assert result["available"] is True
    assert result["total_value"] == 500 * 100 + 300 * 50 + 1000 * 20
    assert any("Banking" in w for w in result["concentration_warnings"])
    assert result["diversification_score"] <= 80  # Banking over-weight should deduct
    assert result["risk_level"] in {"WELL_DIVERSIFIED", "MODERATELY_CONCENTRATED", "HIGHLY_CONCENTRATED"}
    print("Self-check passed.")
    print(f"  score={result['diversification_score']}  risk={result['risk_level']}")
    print(f"  avg_corr={result['avg_correlation']}  warnings={result['concentration_warnings']}")
