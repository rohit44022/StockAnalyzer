"""
top_picks/engine.py — Main Orchestrator for the Top 5 Picks Engine
═══════════════════════════════════════════════════════════════════

WHAT THIS FILE DOES (the whole story in plain English):
───────────────────────────────────────────────────────

Imagine you've scanned 2,000+ stocks with a BB strategy. The scan returns
maybe 50-200 stocks with some kind of signal. But which 5 should you
actually put your money into? That's what this engine answers.

THE 5-STAGE PIPELINE:
─────────────────────

  Stage 1 — RECEIVE SCAN RESULTS
    "Here are 150 stocks that matched the M2 Trend Following scan."
    We receive this list from the existing scan API.

  Stage 2 — PRE-FILTER (fast, eliminates weak candidates)
    "Only 80 of those 150 have BB confidence >= 30%. The other 70 are
     barely matching the pattern — skip them."
    Then: "Of those 80, let's take the top 100 by confidence for deep analysis."

  Stage 3 — DEEP ANALYSIS (the heavy lifting)
    For each of the ~80 qualifying stocks, we run:
      • Full Technical Analysis (Murphy's 6-category scoring)
      • Hybrid BB+TA Engine (cross-validation with agreement scoring)
      • Risk/Reward assessment (target prices, stop losses, R:R ratio)
      • Data quality check (is the CSV data fresh?)
    This is the most time-consuming step — each stock takes ~0.5-2 seconds.

  Stage 4 — COMPOSITE SCORING
    For each stock, combine all the analysis into ONE composite score (0-100)
    using the weighted formula from scorer.py.

  Stage 5 — RANK & SELECT TOP 5
    Sort all stocks by composite score, pick the top 5.
    Attach a detailed explanation card for each pick.

THE OUTPUT:
───────────
  A list of up to 5 stocks, each with:
    - Composite score (0-100) + letter grade
    - 6 component scores with explanations
    - Key reasons WHY this stock was picked
    - Warnings/red flags to watch for
    - TA verdict + categories breakdown
    - Hybrid verdict + BB/TA agreement status
    - Risk report (stop losses, position sizing)
    - Target prices (where the stock could go)
    - Action items (what to actually DO)
"""

from __future__ import annotations
import math
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import pandas as pd

# ── Existing system imports (READ-ONLY — we only consume, never modify) ──
from bb_squeeze.data_loader import (
    load_stock_data, get_data_freshness,
)
from bb_squeeze.indicators import compute_all_indicators as compute_bb_indicators
from bb_squeeze.signals import analyze_signals as generate_bb_signal
from bb_squeeze.strategies import run_all_strategies, strategy_result_to_dict
from bb_squeeze.config import CSV_DIR
from hybrid_engine import run_hybrid_analysis

# ── Our own modules ──
from top_picks.config import (
    MIN_BB_CONFIDENCE, MIN_DATA_BARS, MAX_DEEP_ANALYSIS,
    TOP_N, MIN_COMPOSITE_SCORE, MAX_WORKERS, DEFAULT_CAPITAL,
)
from top_picks.scorer import compute_composite_score
from price_action.engine import run_price_action_analysis, pa_result_to_dict


# ═══════════════════════════════════════════════════════════════
# SAFE VALUE HELPER
# ═══════════════════════════════════════════════════════════════

def _safe(v, default=0):
    """Return a safe numeric value — no NaN, no None, no Infinity."""
    if v is None:
        return default
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return default
    return v


# ═══════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════

def find_top_picks(
    scan_results: list[dict],
    method: str,
    signal_filter: str = "BUY",
    capital: float = DEFAULT_CAPITAL,
    progress_callback=None,
) -> dict:
    """
    The main function — Find the Top 5 Best Picks from a scan.

    ┌──────────────────────────────────────────────────────────────┐
    │  PARAMETERS:                                                  │
    │                                                               │
    │  scan_results — The raw scan data from `/api/scan` or         │
    │                 `/api/scan/strategies`. Each item has:         │
    │                   - ticker, price, confidence, signal_type     │
    │                                                               │
    │  method       — Which BB method: "M1", "M2", "M3", "M4"      │
    │                                                               │
    │  signal_filter — "BUY" or "SELL" — which direction to rank    │
    │                  (usually "BUY" — we want the best buys)      │
    │                                                               │
    │  capital      — Trading capital in ₹ (default ₹5,00,000)     │
    │                                                               │
    │  progress_callback — Optional function called during analysis │
    │                      Signature: callback(done, total, ticker) │
    │                      Used by the API to stream live progress   │
    │                                                               │
    │  RETURNS:                                                     │
    │  {                                                            │
    │    "method": "M2",                                            │
    │    "signal_filter": "BUY",                                    │
    │    "total_scanned": 2263,        # Total stocks in universe   │
    │    "total_signals": 150,         # Stocks with signals        │
    │    "total_qualified": 80,        # Passed pre-filter          │
    │    "total_analyzed": 80,         # Deep analysis completed    │
    │    "picks": [                    # Top 5 (or fewer)           │
    │      { ... detailed pick data ... },                          │
    │      ...                                                      │
    │    ]                                                          │
    │  }                                                            │
    └──────────────────────────────────────────────────────────────┘
    """

    # ── Stage 1: Extract candidates from scan results ───────────
    candidates = _extract_candidates(scan_results, method, signal_filter)
    total_signals = len(candidates)

    # ── Stage 2: Pre-filter (remove weak candidates) ────────────
    qualified = _prefilter(candidates)
    total_qualified = len(qualified)

    if total_qualified == 0:
        return {
            "method": method,
            "signal_filter": signal_filter,
            "total_scanned": len(scan_results),
            "total_signals": total_signals,
            "total_qualified": 0,
            "total_analyzed": 0,
            "picks": [],
            "message": "No stocks passed the pre-filtering stage. "
                       "This means no scanned stocks had sufficient "
                       "BB confidence and data quality to analyze.",
        }

    # ── Stage 3 + 4: Deep analysis + composite scoring ─────────
    scored = _analyze_and_score_all(
        qualified, method, signal_filter, capital, progress_callback
    )

    # ── Stage 5: Rank and select top N ──────────────────────────
    scored.sort(key=lambda x: x["composite_score"], reverse=True)

    # Apply minimum score threshold
    good_picks = [
        p for p in scored if p["composite_score"] >= MIN_COMPOSITE_SCORE
    ]

    # Take top N
    top = good_picks[:TOP_N]

    # Add rank numbers (1st, 2nd, 3rd, etc.)
    for i, pick in enumerate(top):
        pick["rank"] = i + 1

    return {
        "method": method,
        "signal_filter": signal_filter,
        "total_scanned": len(scan_results),
        "total_signals": total_signals,
        "total_qualified": total_qualified,
        "total_analyzed": len(scored),
        "picks": top,
    }


# ═══════════════════════════════════════════════════════════════
# STAGE 1: EXTRACT CANDIDATES
# ═══════════════════════════════════════════════════════════════

def _extract_candidates(
    scan_results: list[dict], method: str, signal_filter: str
) -> list[dict]:
    """
    Extract relevant candidates from the raw scan data.

    The scan data has two different formats:

    FORMAT A — Method I scan (/api/scan):
      Each item is a flat dict with: ticker, confidence, buy_signal, sell_signal, etc.

    FORMAT B — Strategy scan (/api/scan/strategies):
      Each item has: ticker, price, m1 (Method I data), strategies (list of M2/M3/M4)

    We normalize both formats into a simple list of:
      { ticker, price, confidence, signal_type }
    """
    candidates = []

    for item in scan_results:
        try:
            if method == "M1":
                # Format A: direct M1 signal data
                ticker = item.get("ticker", "")
                confidence = _safe(item.get("confidence", 0))
                sig_type = _get_m1_signal_type(item)
                price = _safe(item.get("current_price", 0))
            else:
                # Format B: strategy scan data
                ticker = item.get("ticker", "")
                price = _safe(item.get("price", 0))
                strat = _find_strategy(item, method)
                if not strat:
                    continue
                sig = strat.get("signal", {})
                confidence = _safe(sig.get("confidence", 0))
                sig_type = sig.get("type", "NONE")

            # Apply signal filter
            if signal_filter == "BUY" and sig_type != "BUY":
                continue
            if signal_filter == "SELL" and sig_type != "SELL":
                continue

            candidates.append({
                "ticker": ticker,
                "price": price,
                "confidence": confidence,
                "signal_type": sig_type,
            })
        except Exception:
            continue

    return candidates


def _get_m1_signal_type(item: dict) -> str:
    """Determine the M1 signal type from a scan result item."""
    if item.get("buy_signal"):
        return "BUY"
    if item.get("sell_signal"):
        return "SELL"
    if item.get("hold_signal"):
        return "HOLD"
    if item.get("wait_signal"):
        return "WAIT"
    return "NONE"


def _find_strategy(item: dict, method: str) -> Optional[dict]:
    """Find the specific strategy result (M2/M3/M4) from a combined scan item."""
    strategies = item.get("strategies", [])
    for s in strategies:
        if s.get("code") == method:
            return s
    return None


# ═══════════════════════════════════════════════════════════════
# STAGE 2: PRE-FILTER
# ═══════════════════════════════════════════════════════════════

def _prefilter(candidates: list[dict]) -> list[dict]:
    """
    Remove weak candidates before the expensive deep analysis.

    WHY PRE-FILTER? (plain English)
      Deep analysis (full TA + Hybrid) takes ~1-2 seconds per stock.
      If 500 stocks matched the scan, that's 8-15 minutes of processing!
      But most of those 500 have very low BB confidence (10-30%),
      meaning they barely match the pattern. No point analyzing them.

    RULES:
      1. BB confidence >= MIN_BB_CONFIDENCE (default: 30%)
      2. Sort by confidence descending
      3. Take top MAX_DEEP_ANALYSIS (default: 100) candidates
    """
    # Filter by minimum confidence
    filtered = [
        c for c in candidates
        if c["confidence"] >= MIN_BB_CONFIDENCE
    ]

    # Sort by confidence (best first) and cap at MAX_DEEP_ANALYSIS
    filtered.sort(key=lambda x: x["confidence"], reverse=True)
    return filtered[:MAX_DEEP_ANALYSIS]


# ═══════════════════════════════════════════════════════════════
# STAGE 3 + 4: DEEP ANALYSIS + SCORING (parallelized)
# ═══════════════════════════════════════════════════════════════

def _analyze_and_score_all(
    candidates: list[dict],
    method: str,
    signal_filter: str,
    capital: float,
    progress_callback=None,
) -> list[dict]:
    """
    Run deep analysis on all qualified candidates, then score each one.

    HOW IT WORKS:
      - Each candidate stock gets the FULL treatment:
          1. Load CSV data → compute BB indicators
          2. Run Hybrid Engine (which internally runs BB + full TA + cross-validation)
          3. Extract TA signal, risk report, target prices from hybrid result
          4. Run composite scoring (6 weighted components)
      - We use ThreadPoolExecutor for parallel processing (default: 6 threads)
      - Progress callback fires after each stock for live UI updates

    WHY PARALLEL?
      Serial: 80 stocks × 1.5s each = 2 minutes
      Parallel (6 threads): 80 stocks ÷ 6 = ~14 batches × 1.5s = 21 seconds
      That's a 6× speedup — much better UX.
    """
    results = []
    done_count = 0
    total = len(candidates)

    def _analyze_one(candidate: dict) -> Optional[dict]:
        """Analyze a single stock. Returns scored result or None on failure."""
        return _deep_analyze_stock(
            candidate["ticker"],
            candidate["confidence"],
            candidate["signal_type"],
            method,
            signal_filter,
            capital,
        )

    # Use thread pool for parallel analysis
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        future_map = {
            pool.submit(_analyze_one, c): c for c in candidates
        }

        for future in as_completed(future_map):
            done_count += 1
            candidate = future_map[future]
            try:
                result = future.result()
                if result is not None:
                    results.append(result)
            except Exception:
                pass  # Skip stocks that fail analysis

            if progress_callback:
                progress_callback(done_count, total, candidate["ticker"])

    return results


def _deep_analyze_stock(
    ticker: str,
    bb_confidence: float,
    bb_signal_type: str,
    method: str,
    signal_filter: str,
    capital: float,
) -> Optional[dict]:
    """
    Run the full deep analysis pipeline for a single stock.

    THIS IS THE CORE OF THE ENGINE. For each stock, we:

    Step 1 — Load the stock's CSV data
    Step 2 — Run the Hybrid Engine (which runs BB + TA + cross-validation internally)
    Step 3 — Extract all the individual results from the hybrid output
    Step 4 — Run the composite scorer (6 weighted components → 0-100)
    Step 5 — Package everything into a detailed result card

    If any step fails, we return None (this stock is skipped).
    """
    try:
        # Step 1: Load data
        df = load_stock_data(ticker, csv_dir=CSV_DIR, use_live_fallback=False)
        if df is None or len(df) < MIN_DATA_BARS:
            return None

        # Step 2: Run Hybrid Engine
        # This is the HEAVY call — internally it runs:
        #   - compute_bb_indicators() → BB bands, %b, BBW, CMF, MFI, SAR, etc.
        #   - analyze_signals() → M1 squeeze detection
        #   - run_all_strategies() → M2/M3/M4 pattern detection
        #   - compute_all_ta_indicators() → 40+ TA indicators
        #   - generate_ta_signal() → 6-category TA scoring
        #   - cross_validate() → BB vs TA agreement check
        #   - risk report + target prices
        hybrid = run_hybrid_analysis(df, ticker=ticker, capital=capital)

        if "error" in hybrid:
            return None

        # Step 2b: Run Price Action (Al Brooks) Analysis
        pa_flat = None
        try:
            bb_cross = None
            bb_data_raw = hybrid.get("bb_data", {})
            if bb_data_raw:
                bb_cross = {
                    "buy_signal": bb_data_raw.get("buy_signal", False),
                    "sell_signal": bb_data_raw.get("sell_signal", False),
                    "direction_lean": bb_data_raw.get("direction_lean", ""),
                    "confidence": bb_data_raw.get("confidence", 0),
                    "phase": bb_data_raw.get("phase", ""),
                }
            ta_cross = hybrid.get("ta_signal")
            pa_result_obj = run_price_action_analysis(
                df=df, ticker=ticker,
                bb_data=bb_cross, ta_data=ta_cross, hybrid_data=hybrid,
            )
            if pa_result_obj and pa_result_obj.success:
                pa_dict = pa_result_to_dict(pa_result_obj)
                # Flatten key fields for scorer and frontend
                pa_flat = {
                    "success": True,
                    "pa_score": pa_result_obj.pa_score,
                    "confidence": pa_result_obj.confidence,
                    "pa_verdict": pa_dict.get("signal", {}).get("pa_verdict", "HOLD"),
                    "signal_type": pa_result_obj.signal_type,
                    "signal_strength": pa_dict.get("signal", {}).get("strength", ""),
                    "setup_type": pa_dict.get("signal", {}).get("setup", ""),
                    "always_in": pa_dict.get("trend", {}).get("always_in", ""),
                    "trend_direction": pa_dict.get("trend", {}).get("direction", ""),
                    "trend_phase": pa_dict.get("trend", {}).get("phase", ""),
                    "patterns": pa_dict.get("patterns", {}).get("active", []),
                    "al_brooks_context": pa_dict.get("al_brooks_context", ""),
                    "last_bar": pa_dict.get("last_bar", {}),
                    "breakout": pa_dict.get("breakout", {}),
                    "channel": pa_dict.get("channel", {}),
                    "scoring": pa_dict.get("scoring", {}),
                    "two_leg": pa_dict.get("two_leg", {}),
                    "reasons": pa_dict.get("reasons", []),
                    "price_levels": pa_dict.get("price_levels", {}),
                    "cross_system": pa_dict.get("cross_system", {}),
                }
        except Exception:
            pass

        # Step 3: Extract individual components from hybrid output
        ta_signal = hybrid.get("ta_signal", {})
        data_freshness = hybrid.get("data_freshness", {})
        hybrid_verdict = hybrid.get("hybrid_verdict", {})
        bb_data = hybrid.get("bb_data", {})
        risk = hybrid.get("risk", {})
        target_prices = hybrid.get("target_prices", {})
        ta_categories = ta_signal.get("categories", {})

        # Step 4: Compute composite score (this calls scorer.py)
        scoring = compute_composite_score(
            bb_confidence=bb_confidence,
            bb_signal_type=bb_signal_type,
            ta_signal=ta_signal,
            hybrid_result=hybrid,
            data_freshness=data_freshness,
            method=method,
            signal_filter=signal_filter,
            pa_result=pa_flat,
        )

        # Step 5: Package the result card
        # Get the current price from hybrid data
        current_price = _safe(
            bb_data.get("indicators", {}).get("price") or
            hybrid.get("snapshot", {}).get("close"),
            0
        )

        # Extract action items from TA
        action_items = ta_signal.get("action_items", [])

        # Extract stop loss
        stop_loss = _safe(bb_data.get("stop_loss"), 0)

        # Extract target price consensus
        consensus_up = target_prices.get("consensus_upside", {}) if target_prices else {}
        consensus_down = target_prices.get("consensus_downside", {}) if target_prices else {}

        # Build summary of key TA categories
        category_summary = {}
        for cat_name, cat_data in ta_categories.items():
            if isinstance(cat_data, dict):
                category_summary[cat_name] = {
                    "score": _safe(cat_data.get("score", 0)),
                    "max": _safe(cat_data.get("max", 0)),
                }

        # Hybrid verdict details
        hv = hybrid_verdict if isinstance(hybrid_verdict, dict) else {}

        return {
            # ── Identification ──
            "ticker": ticker,
            "ticker_display": ticker.replace(".NS", ""),
            "current_price": current_price,

            # ── Composite Score (the main ranking number) ──
            "composite_score": scoring["composite_score"],
            "grade": scoring["grade"],
            "components": scoring["components"],
            "reasons": scoring["reasons"],
            "warnings": scoring["warnings"],

            # ── BB Strategy Data ──
            "bb_signal_type": bb_signal_type,
            "bb_confidence": bb_confidence,
            "bb_phase": bb_data.get("phase", ""),
            "bb_squeeze_on": bb_data.get("squeeze_on", False),
            "bb_squeeze_days": bb_data.get("squeeze_days", 0),
            "bb_direction_lean": bb_data.get("direction_lean", ""),

            # ── TA Data ──
            "ta_verdict": ta_signal.get("verdict", "HOLD"),
            "ta_score": _safe(ta_signal.get("score", 0)),
            "ta_categories": category_summary,
            "ta_action_items": action_items[:5],  # Top 5 action items

            # ── Hybrid Data ──
            "hybrid_verdict": hv.get("verdict", "UNKNOWN"),
            "hybrid_combined_score": _safe(hv.get("score", 0)),
            "hybrid_confidence": _safe(hv.get("confidence", 0)),
            "hybrid_bb_total": _safe(hybrid.get("bb_score", {}).get("total", 0)),
            "hybrid_ta_total": _safe(hybrid.get("ta_score", {}).get("total", 0)),
            "hybrid_agreement": _safe(
                hybrid.get("cross_validation", {}).get("agreement_score", 0)
            ),

            # ── Risk/Reward Data ──
            "stop_loss": stop_loss,
            "target_upside": _safe(consensus_up.get("target")) if consensus_up else None,
            "target_upside_pct": _safe(consensus_up.get("pct")) if consensus_up else None,
            "target_downside": _safe(consensus_down.get("target")) if consensus_down else None,
            "rr_ratio": _safe(
                target_prices.get("risk_reward_ratio")
            ) if target_prices else None,

            # ── Data Quality ──
            "data_freshness": data_freshness,

            # ── Price Action (Al Brooks) Data ──
            "pa_data": pa_flat,
        }

    except Exception:
        # If anything goes wrong, skip this stock entirely.
        # We never want a broken stock to crash the entire engine.
        traceback.print_exc()
        return None
