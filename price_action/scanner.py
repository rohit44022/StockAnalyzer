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

        for fut in as_completed(futures, timeout=120):
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
