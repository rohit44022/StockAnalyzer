"""
Price Action Scanner — Full Universe Scanner
==============================================
Scans all stocks for Price Action signals and provides
categorized results for the web interface.
"""

from __future__ import annotations

import sys
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from price_action.engine import run_price_action_analysis, pa_result_to_dict, PriceActionResult
from price_action import config as C


def scan_single_stock(
    ticker: str,
    csv_dir: str,
    include_bb: bool = True,
    include_ta: bool = False,
    include_hybrid: bool = False,
) -> Optional[PriceActionResult]:
    """
    Run Price Action analysis on a single stock.

    Parameters
    ----------
    ticker : str
        Stock ticker.
    csv_dir : str
        Path to CSV directory.
    include_bb : bool
        Whether to also run BB analysis for cross-validation.
    include_ta : bool
        Whether to run TA analysis.
    include_hybrid : bool
        Whether to run Hybrid analysis.

    Returns
    -------
    PriceActionResult or None
    """
    try:
        from bb_squeeze.data_loader import load_stock_data
        from bb_squeeze.indicators import compute_all_indicators
        from bb_squeeze.signals import analyze_signals

        df = load_stock_data(ticker, csv_dir=csv_dir, use_live_fallback=False)
        if df is None or len(df) < C.MIN_BARS_REQUIRED:
            return None

        # Compute indicators (needed for BB data)
        df_ind = compute_all_indicators(df)

        # Get BB data for cross-validation
        bb_data = None
        if include_bb:
            try:
                bb_sig = analyze_signals(ticker, df_ind)
                bb_data = {
                    "buy_signal": bb_sig.buy_signal,
                    "sell_signal": bb_sig.sell_signal,
                    "direction_lean": bb_sig.direction_lean,
                    "confidence": bb_sig.confidence,
                    "phase": bb_sig.phase,
                }
            except Exception:
                pass

        # Get TA data
        ta_data = None
        if include_ta:
            try:
                from technical_analysis.engine import run_ta_analysis
                ta_result = run_ta_analysis(df)
                if ta_result:
                    ta_data = ta_result.get("signal", {})
            except Exception:
                pass

        # Get Triple (hybrid) data
        hybrid_data = None
        if include_hybrid:
            try:
                from hybrid_pa_engine import run_triple_analysis
                hybrid_data = run_triple_analysis(df_ind, ticker=ticker)
            except Exception:
                pass

        # Run PA analysis (use original df without BB indicators)
        result = run_price_action_analysis(
            df=df,
            ticker=ticker,
            bb_data=bb_data,
            ta_data=ta_data,
            hybrid_data=hybrid_data,
        )

        return result if result.success else None

    except Exception:
        return None


def scan_all_stocks(
    csv_dir: str,
    max_workers: int = 16,
    include_bb: bool = True,
) -> Dict[str, List[PriceActionResult]]:
    """
    Scan all stocks in the CSV directory for PA signals.

    Returns categorized results:
    - buy_signals: Stocks with BUY signal
    - sell_signals: Stocks with SELL signal
    - strong_buy: Stocks with STRONG BUY
    - strong_sell: Stocks with STRONG SELL
    - breakout_mode: Stocks in breakout mode (ii/iii patterns)
    - spike_active: Stocks currently in a spike
    """
    from bb_squeeze.data_loader import get_all_tickers_from_csv

    tickers = get_all_tickers_from_csv(csv_dir)
    results: Dict[str, List[PriceActionResult]] = {
        "buy_signals": [],
        "sell_signals": [],
        "strong_buy": [],
        "strong_sell": [],
        "breakout_mode": [],
        "spike_active": [],
        "all": [],
    }

    futures = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for ticker in tickers:
            fut = pool.submit(scan_single_stock, ticker, csv_dir, include_bb)
            futures[fut] = ticker

        # Budget the whole scan, not an arbitrary two minutes: 2,900 NSE tickers
        # take roughly 40 minutes, so the old fixed timeout=120 raised
        # TimeoutError with ~870 futures still running and no results at all.
        # A cap is still wanted -- one pathological ticker can hold a worker for
        # half an hour -- so it scales with the work actually submitted.
        for fut in as_completed(futures, timeout=max(120, len(futures) * 2)):
            try:
                r = fut.result(timeout=30)
                if r is None:
                    continue

                results["all"].append(r)

                if r.signal_type == "BUY":
                    results["buy_signals"].append(r)
                    if r.strength == "STRONG" or r.pa_verdict == "STRONG BUY":
                        results["strong_buy"].append(r)
                elif r.signal_type == "SELL":
                    results["sell_signals"].append(r)
                    if r.strength == "STRONG" or r.pa_verdict == "STRONG SELL":
                        results["strong_sell"].append(r)

                if r.breakout_mode:
                    results["breakout_mode"].append(r)

                if r.trend_phase == "SPIKE":
                    results["spike_active"].append(r)

            except Exception:
                continue

    # Sort each category by confidence descending
    for key in results:
        results[key].sort(key=lambda x: x.confidence, reverse=True)

    return results


def scan_results_to_dicts(results: Dict[str, List[PriceActionResult]]) -> Dict[str, list]:
    """Convert scan results to JSON-safe dicts."""
    return {
        key: [pa_result_to_dict(r) for r in items]
        for key, items in results.items()
    }


# ─────────────────────────────────────────────────────────────────
#  DAILY SHORTLIST
# ─────────────────────────────────────────────────────────────────

_PLAIN_SETUP = {
    "BREAKOUT": "it has just broken out of the range it was stuck in",
    "PULLBACK": "it is in an uptrend and has dipped back to a level buyers "
                "have defended before",
    "SECOND_ENTRY": "it tried to turn up, failed, and is now trying a second "
                    "time -- the attempt Brooks rates highest",
    "FAILED_BREAKOUT": "a break to the downside failed and price has snapped "
                       "back up, trapping the sellers",
}

_PLAIN_PHASE = {
    "SPIKE": "It is moving fast in a straight line right now.",
    "CHANNEL": "It has been grinding upward in an orderly way.",
    "TIGHT_CHANNEL": "It has been grinding upward very steadily, with shallow dips.",
    "BROAD_CHANNEL": "It has been rising, but in wide swings -- expect a bumpy ride.",
    "TRADING_RANGE": "It has been going sideways, so the move may stall at the "
                     "top of the range.",
}


def _plain_english(r: PriceActionResult) -> str:
    """Explain one shortlisted BUY the way you would to someone who has never
    read Brooks: what to do, what it costs if wrong, and why it qualified."""
    risk = r.entry_price - r.stop_loss
    reward = r.target_1 - r.entry_price if r.target_1 > r.entry_price else 0.0
    risk_pct = risk / r.entry_price * 100 if r.entry_price else 0.0

    lines = [
        f"Buy near Rs.{r.entry_price:,.2f}. Get out if it drops to "
        f"Rs.{r.stop_loss:,.2f} -- that is the whole loss you are accepting, "
        f"about {risk_pct:.1f}% of what you put in."
    ]
    if reward > 0 and risk > 0:
        lines.append(
            f"First place to take money off the table is Rs.{r.target_1:,.2f}, "
            f"so you are risking Rs.{risk:,.2f} a share to make Rs.{reward:,.2f} "
            f"-- {reward / risk:.1f} times what you risk."
        )

    lines.append(
        f"Why this one: {_PLAIN_SETUP.get(r.setup_type, 'it matched a Brooks setup')}."
    )

    phase = _PLAIN_PHASE.get(r.trend_phase)
    if phase:
        lines.append(phase)

    lines.append(
        "It also passed the one test Brooks insists on -- the likely gain is "
        "bigger than the likely loss -- and the engine rates it "
        f"{r.confidence}/100, its high band."
    )
    lines.append(
        "Reality check: shortlists like this won about 40 times in 100 in "
        "testing, so most single picks lose. It came out ahead only because the "
        "winners ran further than the losers -- which needs you to take the "
        "whole list, not the one you like, and to honour the stop every time. "
        "Whole years (2018, 2019, 2022, 2025) still lost money."
    )
    return " ".join(lines)


def top_buy_shortlist(
    results: Dict[str, List[PriceActionResult]],
    limit: int = C.SHORTLIST_SIZE,
) -> List[dict]:
    """The day's best BUY candidates, filtered the way the backtest says to.

    Takes the output of scan_all_stocks. Keeps only signals that clear Brooks'
    trader's equation, use a setup that made money out-of-sample, sit in an
    uptrend by the always-in reading, score in the engine's high confidence
    band, and offer at least 1.5 times their risk. Ranked best first.

    Returns fewer than `limit` -- possibly none -- on days when nothing
    qualifies, which is the honest answer on those days rather than padding the
    list with the least-bad leftovers.
    """
    picks = [
        r for r in results.get("buy_signals", [])
        if r.equation_verdict == "EDGE"
        and r.setup_type in C.SHORTLIST_SETUPS
        and r.always_in == "LONG"
        and r.confidence >= C.SHORTLIST_MIN_CONFIDENCE
        and r.risk_reward >= C.SHORTLIST_MIN_RR
        and r.entry_price > r.stop_loss > 0
    ]
    picks.sort(key=lambda r: (r.confidence, r.pa_score), reverse=True)

    return [
        {
            "rank": i,
            "ticker": r.ticker,
            "setup": r.setup_type,
            "confidence": r.confidence,
            "entry": round(r.entry_price, 2),
            "stop": round(r.stop_loss, 2),
            "target_1": round(r.target_1, 2),
            "target_2": round(r.target_2, 2),
            "risk_pct": round((r.entry_price - r.stop_loss) / r.entry_price * 100, 2),
            "risk_reward": round(r.risk_reward, 2),
            "trend_phase": r.trend_phase,
            "explanation": _plain_english(r),
        }
        for i, r in enumerate(picks[:limit], 1)
    ]


if __name__ == "__main__":
    # python -m price_action.scanner [csv_dir]
    import textwrap

    _dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_ROOT, "stock_csv")
    _picks = top_buy_shortlist(scan_all_stocks(_dir, include_bb=False))

    if not _picks:
        print("Nothing qualified today. That is a real answer, not a failure -- "
              "on about 3 days in 100 the market offers no setup worth taking.")
    for _p in _picks:
        print(f"\n{_p['rank']}. {_p['ticker']}   entry Rs.{_p['entry']:,.2f}   "
              f"stop Rs.{_p['stop']:,.2f}   target Rs.{_p['target_1']:,.2f}   "
              f"(risk {_p['risk_pct']}%, {_p['risk_reward']}x reward)")
        print(textwrap.fill(_p["explanation"], 96, initial_indent="   ",
                            subsequent_indent="   "))
