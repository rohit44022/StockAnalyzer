"""
Brooks System — Top-5 BUY & SELL Scanner
=========================================
Separate module that reuses price_action/ (which already implements every
Al Brooks rule from all three books) and adds:
  - Top-5 SELL shortlist (mirrors the existing top_buy_shortlist)
  - A single scan_and_rank() entry point for the web route
"""

from __future__ import annotations

import sys, os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from price_action.engine import run_price_action_analysis, PriceActionResult
from price_action import config as C


# ─────────────────────────────────────────────────────────────────
#  SINGLE-STOCK SCAN (lightweight — no BB/TA cross-validation)
# ─────────────────────────────────────────────────────────────────

def _scan_one(ticker: str, csv_dir: str) -> Optional[PriceActionResult]:
    try:
        from bb_squeeze.data_loader import load_stock_data
        df = load_stock_data(ticker, csv_dir=csv_dir, use_live_fallback=False)
        if df is None or len(df) < C.MIN_BARS_REQUIRED:
            return None
        r = run_price_action_analysis(df=df, ticker=ticker)
        return r if r.success else None
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────
#  SELL SHORTLIST (mirrors top_buy_shortlist logic from scanner.py)
# ─────────────────────────────────────────────────────────────────

_SELL_SETUPS = ("BREAKOUT", "PULLBACK", "SECOND_ENTRY", "FAILED_BREAKOUT")

_PLAIN_SETUP_SELL = {
    "BREAKOUT": "it has just broken below the range it was stuck in",
    "PULLBACK": "it is in a downtrend and has bounced back to a level sellers "
                "have defended before",
    "SECOND_ENTRY": "it tried to turn down, failed, and is now trying a second "
                    "time — the attempt Brooks rates highest",
    "FAILED_BREAKOUT": "a break to the upside failed and price has snapped "
                       "back down, trapping the buyers",
}

_PLAIN_PHASE_SELL = {
    "SPIKE": "It is moving fast in a straight line downward right now.",
    "CHANNEL": "It has been grinding lower in an orderly way.",
    "TIGHT_CHANNEL": "It has been grinding lower very steadily, with shallow bounces.",
    "BROAD_CHANNEL": "It has been falling, but in wide swings.",
    "TRADING_RANGE": "It has been going sideways, so the move may stall at the "
                     "bottom of the range.",
}


def _plain_english_sell(r: PriceActionResult) -> str:
    risk = r.stop_loss - r.entry_price
    reward = r.entry_price - r.target_1 if r.target_1 < r.entry_price else 0.0
    risk_pct = risk / r.entry_price * 100 if r.entry_price else 0.0

    lines = [
        f"Short near Rs.{r.entry_price:,.2f}. Get out if it rises to "
        f"Rs.{r.stop_loss:,.2f} — that is the whole loss you are accepting, "
        f"about {risk_pct:.1f}% of what you put in."
    ]
    if reward > 0 and risk > 0:
        lines.append(
            f"First place to take money off the table is Rs.{r.target_1:,.2f}, "
            f"so you are risking Rs.{risk:,.2f} a share to make Rs.{reward:,.2f} "
            f"— {reward / risk:.1f} times what you risk."
        )

    lines.append(
        f"Why this one: {_PLAIN_SETUP_SELL.get(r.setup_type, 'it matched a Brooks setup')}."
    )

    phase = _PLAIN_PHASE_SELL.get(r.trend_phase)
    if phase:
        lines.append(phase)

    lines.append(
        "It also passed the one test Brooks insists on — the likely gain is "
        "bigger than the likely loss — and the engine rates it "
        f"{r.confidence}/100, its high band."
    )
    lines.append(
        "Reality check: shortlists like this won about 40 times in 100 in "
        "testing, so most single picks lose. It came out ahead only because the "
        "winners ran further than the losers — which needs you to take the "
        "whole list, not the one you like, and to honour the stop every time."
    )
    return " ".join(lines)


# ─────────────────────────────────────────────────────────────────
#  PLAIN ENGLISH BUY (duplicated here to keep module self-contained)
# ─────────────────────────────────────────────────────────────────

_PLAIN_SETUP_BUY = {
    "BREAKOUT": "it has just broken out of the range it was stuck in",
    "PULLBACK": "it is in an uptrend and has dipped back to a level buyers "
                "have defended before",
    "SECOND_ENTRY": "it tried to turn up, failed, and is now trying a second "
                    "time — the attempt Brooks rates highest",
    "FAILED_BREAKOUT": "a break to the downside failed and price has snapped "
                       "back up, trapping the sellers",
}

_PLAIN_PHASE_BUY = {
    "SPIKE": "It is moving fast in a straight line right now.",
    "CHANNEL": "It has been grinding upward in an orderly way.",
    "TIGHT_CHANNEL": "It has been grinding upward very steadily, with shallow dips.",
    "BROAD_CHANNEL": "It has been rising, but in wide swings — expect a bumpy ride.",
    "TRADING_RANGE": "It has been going sideways, so the move may stall at the "
                     "top of the range.",
}


def _plain_english_buy(r: PriceActionResult) -> str:
    risk = r.entry_price - r.stop_loss
    reward = r.target_1 - r.entry_price if r.target_1 > r.entry_price else 0.0
    risk_pct = risk / r.entry_price * 100 if r.entry_price else 0.0

    lines = [
        f"Buy near Rs.{r.entry_price:,.2f}. Get out if it drops to "
        f"Rs.{r.stop_loss:,.2f} — that is the whole loss you are accepting, "
        f"about {risk_pct:.1f}% of what you put in."
    ]
    if reward > 0 and risk > 0:
        lines.append(
            f"First place to take money off the table is Rs.{r.target_1:,.2f}, "
            f"so you are risking Rs.{risk:,.2f} a share to make Rs.{reward:,.2f} "
            f"— {reward / risk:.1f} times what you risk."
        )

    lines.append(
        f"Why this one: {_PLAIN_SETUP_BUY.get(r.setup_type, 'it matched a Brooks setup')}."
    )

    phase = _PLAIN_PHASE_BUY.get(r.trend_phase)
    if phase:
        lines.append(phase)

    lines.append(
        "It also passed the one test Brooks insists on — the likely gain is "
        "bigger than the likely loss — and the engine rates it "
        f"{r.confidence}/100, its high band."
    )
    lines.append(
        "Reality check: shortlists like this won about 40 times in 100 in "
        "testing, so most single picks lose. It came out ahead only because the "
        "winners ran further than the losers — which needs you to take the "
        "whole list, not the one you like, and to honour the stop every time."
    )
    return " ".join(lines)


# ─────────────────────────────────────────────────────────────────
#  PICK BUILDERS
# ─────────────────────────────────────────────────────────────────

def _result_to_pick(r: PriceActionResult, rank: int, direction: str) -> dict:
    """Build a detailed pick dict from a PriceActionResult."""
    if direction == "BUY":
        risk = r.entry_price - r.stop_loss
        explanation = _plain_english_buy(r)
    else:
        risk = r.stop_loss - r.entry_price
        explanation = _plain_english_sell(r)

    risk_pct = risk / r.entry_price * 100 if r.entry_price else 0.0

    return {
        "rank": rank,
        "ticker": r.ticker,
        "direction": direction,
        "setup": r.setup_type,
        "confidence": r.confidence,
        "pa_score": r.pa_score,
        "pa_verdict": r.pa_verdict,
        "entry": round(r.entry_price, 2),
        "stop": round(r.stop_loss, 2),
        "target_1": round(r.target_1, 2),
        "target_2": round(r.target_2, 2),
        "risk_pct": round(risk_pct, 2),
        "risk_reward": round(r.risk_reward, 2),
        "current_price": round(r.current_price, 2),
        "always_in": r.always_in,
        "trend_direction": r.trend_direction,
        "trend_phase": r.trend_phase,
        "trend_strength": round(r.trend_strength, 1),
        "buying_pressure": round(r.buying_pressure, 1),
        "selling_pressure": round(r.selling_pressure, 1),
        "ema20": round(r.ema20, 2),
        "price_vs_ema": r.price_vs_ema,
        "ema_gap_bars": r.ema_gap_bar_count,
        "in_spike": r.in_spike,
        "spike_direction": r.spike_direction,
        "recent_climax": r.recent_climax,
        "last_bar_type": r.last_bar_type,
        "last_bar_description": r.last_bar_description,
        "active_patterns": r.active_patterns,
        "last_h": r.last_hl_bull,
        "last_l": r.last_hl_bear,
        "breakout_mode": r.breakout_mode,
        "in_breakout": r.in_breakout,
        "two_leg_complete": r.two_leg_complete,
        "measured_move_target": round(r.measured_move_target, 2),
        "equation_verdict": r.equation_verdict,
        "traders_equation": round(r.traders_equation, 2),
        "reasons": r.reasons,
        "al_brooks_context": r.al_brooks_context,
        "explanation": explanation,
        "score_details": r.score_details,
    }


# ─────────────────────────────────────────────────────────────────
#  MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────

def scan_and_rank(
    csv_dir: str,
    max_workers: int = 16,
    limit: int = 5,
) -> dict:
    """Scan all stocks and return top-5 BUY and top-5 SELL picks.

    Returns
    -------
    dict with keys: buy_picks, sell_picks, stats
    """
    from bb_squeeze.data_loader import get_all_tickers_from_csv

    tickers = get_all_tickers_from_csv(csv_dir)

    all_results: List[PriceActionResult] = []
    scanned = 0
    errors = 0

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_scan_one, t, csv_dir): t for t in tickers}
        for fut in as_completed(futures, timeout=max(120, len(futures) * 2)):
            try:
                r = fut.result(timeout=30)
                scanned += 1
                if r is not None:
                    all_results.append(r)
                else:
                    errors += 1
            except Exception:
                errors += 1
                scanned += 1

    # ── Top BUY picks ──
    buy_candidates = [
        r for r in all_results
        if r.signal_type == "BUY"
        and r.equation_verdict == "EDGE"
        and r.setup_type in C.SHORTLIST_SETUPS
        and r.always_in == "LONG"
        and r.confidence >= C.SHORTLIST_MIN_CONFIDENCE
        and r.risk_reward >= C.SHORTLIST_MIN_RR
        and r.entry_price > r.stop_loss > 0
    ]
    buy_candidates.sort(key=lambda r: (r.confidence, r.pa_score), reverse=True)
    buy_picks = [
        _result_to_pick(r, i, "BUY")
        for i, r in enumerate(buy_candidates[:limit], 1)
    ]

    # ── Top SELL picks (mirror of BUY logic for SHORT side) ──
    sell_candidates = [
        r for r in all_results
        if r.signal_type == "SELL"
        and r.equation_verdict == "EDGE"
        and r.setup_type in _SELL_SETUPS
        and r.always_in == "SHORT"
        and r.confidence >= C.SHORTLIST_MIN_CONFIDENCE
        and r.risk_reward >= C.SHORTLIST_MIN_RR
        and r.entry_price > 0 and r.stop_loss > r.entry_price
    ]
    sell_candidates.sort(key=lambda r: (r.confidence, abs(r.pa_score)), reverse=True)
    sell_picks = [
        _result_to_pick(r, i, "SELL")
        for i, r in enumerate(sell_candidates[:limit], 1)
    ]

    total_buy = sum(1 for r in all_results if r.signal_type == "BUY")
    total_sell = sum(1 for r in all_results if r.signal_type == "SELL")
    total_hold = sum(1 for r in all_results if r.signal_type == "HOLD")

    return {
        "buy_picks": buy_picks,
        "sell_picks": sell_picks,
        "stats": {
            "total_tickers": len(tickers),
            "scanned": scanned,
            "analysed": len(all_results),
            "errors": errors,
            "total_buy_signals": total_buy,
            "total_sell_signals": total_sell,
            "total_hold": total_hold,
            "buy_qualified": len(buy_candidates),
            "sell_qualified": len(sell_candidates),
        },
    }
