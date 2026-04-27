"""
engine.py — Orchestrator: pulls market data, runs the analyzer, returns one dict.
═══════════════════════════════════════════════════════════════════════════════════

Production hardening:
  • Surfaces health metrics (live vs cached vs failed)
  • Surfaces per-instrument staleness (with warnings list)
  • Includes historical-context (1Y percentile rank) for key indicators
  • Includes sector breakdown for Indian sectoral leaders/laggards
  • Includes regime stability ("how many days has this regime held?")

This module is fully isolated — failures here cannot break analyze, scan,
top picks, etc. If yfinance is down or returns garbage, we return a structured
error and the frontend hides the section gracefully.
"""

from __future__ import annotations
import time
import traceback

from global_sentiment.data_loader import (
    get_market_data, summarize, cache_age_seconds, get_health, logger,
)
from global_sentiment.analyzer import (
    detect_regime, compute_composite_score, detect_money_flow,
    compute_correlations, india_impact, generate_layman_summary,
    compute_regime_stability, analyze_sectors, historical_context,
    compute_section_verdicts,
)
from global_sentiment.calibration import get_calibration, label_score
from global_sentiment.instruments import ALL_INSTRUMENTS, BY_KEY


def _category_view(summaries: dict) -> dict:
    """Group instruments by category for the dashboard panels."""
    out = {"fx": [], "commodity": [], "bond": [], "equity": [], "sector": [], "crypto": []}
    for inst in ALL_INSTRUMENTS:
        s = summaries.get(inst.key)
        if not s:
            continue
        out.setdefault(inst.category, []).append({
            "key":  inst.key,
            "name": inst.name,
            "yf_ticker": inst.yf_ticker,
            "category": inst.category,
            "polarity": inst.polarity,
            "unit": inst.unit,
            "description": inst.description,
            **s,
        })
    return out


def _build_data_quality(summaries: dict, health: dict | None) -> dict:
    """Per-instrument staleness + overall data quality for the user."""
    stale_instruments = []
    rejects_total = 0
    for key, s in summaries.items():
        if s.get("is_stale"):
            inst = BY_KEY.get(key)
            stale_instruments.append({
                "key": key,
                "name": inst.name if inst else key,
                "ts_last": s.get("ts_last"),
                "cal_days_stale": s.get("cal_days_stale"),
            })
        rejects_total += len(s.get("data_rejects", []))

    n_loaded = len(summaries)
    n_total = len(ALL_INSTRUMENTS)
    coverage_pct = round(n_loaded / n_total * 100, 1) if n_total else 0

    if not health or not health.get("ok"):
        quality_label = "DEGRADED"
        quality_color = "#f85149"
    elif coverage_pct < 80:
        quality_label = "PARTIAL"
        quality_color = "#d29922"
    elif stale_instruments:
        quality_label = "OK (some stale)"
        quality_color = "#d29922"
    else:
        quality_label = "OK"
        quality_color = "#3fb950"

    return {
        "label":              quality_label,
        "color":              quality_color,
        "instruments_loaded": n_loaded,
        "instruments_total":  n_total,
        "coverage_pct":       coverage_pct,
        "stale_instruments":  stale_instruments,
        "outlier_rejects":    rejects_total,
        "source":             health.get("source") if health else "unknown",
    }


def get_global_sentiment(force_refresh: bool = False) -> dict:
    """
    Main entry point. Returns the full readout for the dashboard.
    """
    started = time.time()
    try:
        market_data = get_market_data(force_refresh=force_refresh)
        if not market_data:
            return {
                "ok": False,
                "error": "Could not fetch market data (yfinance unavailable + no persistent cache).",
                "fetched_at": int(time.time()),
                "health": get_health(),
            }

        summaries = {}
        for key, df in market_data.items():
            s = summarize(df)
            if s:
                summaries[key] = s

        if not summaries:
            return {
                "ok": False,
                "error": "Market data returned but all instruments failed validation.",
                "fetched_at": int(time.time()),
                "health": get_health(),
            }

        regime    = detect_regime(summaries)
        composite = compute_composite_score(summaries)

        # Calibrated buckets from historical replay (cached 24h)
        calibration = get_calibration(market_data)
        if calibration.get("ok"):
            new_label, new_color = label_score(composite["score"], calibration["buckets"])
            composite["label"] = new_label
            composite["color"] = new_color
            composite["calibration_source"] = calibration["source"]

        flows     = detect_money_flow(summaries)
        correlations = compute_correlations(market_data)
        india     = india_impact(summaries, regime, composite)
        layman    = generate_layman_summary(summaries, regime, composite, india, flows,
                                            calibration=calibration)
        cats      = _category_view(summaries)

        # Production additions
        stability = compute_regime_stability(market_data, regime["label"])
        sectors   = analyze_sectors(summaries)
        hist_ctx  = historical_context(summaries)
        section_verdicts = compute_section_verdicts(summaries, correlations, hist_ctx, sectors)
        health    = get_health()
        dq        = _build_data_quality(summaries, health)

        return {
            "ok": True,
            "fetched_at": int(time.time()),
            "cache_age_seconds": cache_age_seconds(),
            "compute_ms": int((time.time() - started) * 1000),
            "regime": regime,
            "regime_stability": stability,
            "composite": composite,
            "money_flow": flows,
            "correlations": correlations,
            "india_impact": india,
            "layman": layman,
            "sectors": sectors,
            "historical_context": hist_ctx,
            "section_verdicts": section_verdicts,
            "calibration": calibration,
            "instruments": cats,
            "data_quality": dq,
            "health": health,
            "error": None,
        }

    except Exception as ex:
        traceback.print_exc()
        logger.error(f"Engine crashed: {ex}", exc_info=True)
        return {
            "ok": False,
            "error": f"Engine crashed: {ex}",
            "fetched_at": int(time.time()),
            "health": get_health(),
        }


def get_health_summary() -> dict:
    """Cheap health check — used by /api/global-sentiment/health (no fetch)."""
    h = get_health()
    age = cache_age_seconds()
    return {
        "ok": h.get("ok") if h else False,
        "source": h.get("source") if h else "no_cache",
        "instruments_loaded": h.get("instruments_loaded") if h else 0,
        "missing": h.get("missing") if h else [],
        "cache_age_seconds": age,
        "cache_fresh": age is not None and age < 15 * 60,
        "last_error": h.get("last_error") if h else None,
        "checked_at": int(time.time()),
    }
