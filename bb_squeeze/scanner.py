"""
scanner.py — Batch scanner that analyzes ALL stocks in the CSV directory
and identifies squeeze opportunities, buy/sell/hold signals.
"""

import os
import time
import warnings
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

# Suppress noisy yfinance / urllib warnings during batch scans
warnings.filterwarnings("ignore")
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.CRITICAL)

from bb_squeeze.config import CSV_DIR
from bb_squeeze.data_loader import load_stock_data, get_all_tickers_from_csv
from bb_squeeze.indicators import compute_all_indicators
from bb_squeeze.signals import analyze_signals, SignalResult
from bb_squeeze.fundamentals import fetch_fundamentals, FundamentalData
from bb_squeeze.display import (
    console, make_progress_bar, print_scan_results,
    print_summary_stats, print_section, print_info
)


# ─────────────────────────────────────────────────────────────────
#  SINGLE STOCK PIPELINE
# ─────────────────────────────────────────────────────────────────

def analyze_single_ticker(ticker: str,
                           csv_dir: str = CSV_DIR,
                           fetch_fundamentals_flag: bool = False
                           ) -> tuple[SignalResult, Optional[FundamentalData]]:
    """
    Full analysis pipeline for one ticker:
    1. Load data  → 2. Calculate indicators  → 3. Generate signals
    Optional: fetch fundamentals
    """
    df = load_stock_data(ticker, csv_dir=csv_dir)

    if df is None:
        sig = SignalResult(ticker=ticker)
        sig.phase   = "INSUFFICIENT_DATA"
        sig.summary = "Data not available."
        return sig, None

    try:
        df  = compute_all_indicators(df)
        sig = analyze_signals(ticker, df)
    except Exception as e:
        sig = SignalResult(ticker=ticker)
        sig.phase   = "ERROR"
        sig.summary = f"Analysis error: {e}"
        return sig, None

    fd = None
    if fetch_fundamentals_flag:
        try:
            fd = fetch_fundamentals(ticker)
        except Exception:
            fd = None

    return sig, fd


# ─────────────────────────────────────────────────────────────────
#  BATCH SCANNER
# ─────────────────────────────────────────────────────────────────

class SqueezeScanner:
    """
    Scans all tickers in the CSV directory for squeeze signals.
    Results are categorised into buy/sell/hold/squeeze/head_fake lists.
    """

    def __init__(self, csv_dir: str = CSV_DIR,
                 max_workers: int = 16,
                 fetch_fundamentals_for_signals: bool = False):
        self.csv_dir   = csv_dir
        self.max_workers = max_workers
        self.fetch_fund = fetch_fundamentals_for_signals

        # Results store
        self.all_results:  list[tuple[SignalResult, Optional[FundamentalData]]] = []
        self.buy_signals:  list[tuple[SignalResult, Optional[FundamentalData]]] = []
        self.sell_signals: list[tuple[SignalResult, Optional[FundamentalData]]] = []
        self.hold_signals: list[tuple[SignalResult, Optional[FundamentalData]]] = []
        self.wait_signals: list[tuple[SignalResult, Optional[FundamentalData]]] = []
        self.head_fakes:   list[tuple[SignalResult, Optional[FundamentalData]]] = []
        self.squeeze_only: list[tuple[SignalResult, Optional[FundamentalData]]] = []

    def _process_one(self, ticker: str) -> tuple[SignalResult, Optional[FundamentalData]]:
        """Worker function for parallel execution."""
        try:
            return analyze_single_ticker(ticker, self.csv_dir, self.fetch_fund)
        except Exception as e:
            sig = SignalResult(ticker=ticker)
            sig.phase = "ERROR"
            return sig, None

    def scan(self, tickers: Optional[list[str]] = None) -> None:
        """
        Run the full scan on all available tickers (or a provided list).
        Uses ThreadPoolExecutor for parallel processing.
        """
        if tickers is None:
            tickers = get_all_tickers_from_csv(self.csv_dir)

        if not tickers:
            print_info("No tickers found. Run data download first.")
            return

        # Reset result stores
        self.all_results.clear()
        self.buy_signals.clear()
        self.sell_signals.clear()
        self.hold_signals.clear()
        self.wait_signals.clear()
        self.head_fakes.clear()
        self.squeeze_only.clear()

        total = len(tickers)
        print_info(f"Starting scan of {total} stocks...")
        start_t = time.time()

        with make_progress_bar() as progress:
            task = progress.add_task("Scanning stocks...", total=total)

            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {executor.submit(self._process_one, t): t for t in tickers}

                for future in as_completed(futures):
                    ticker = futures[future]
                    try:
                        sig, fd = future.result(timeout=30)
                        self._categorise(sig, fd)
                        self.all_results.append((sig, fd))
                    except Exception:
                        pass
                    finally:
                        progress.advance(task)

        elapsed = time.time() - start_t
        print_info(f"Scan completed in {elapsed:.1f}s | {total} stocks")

    def _categorise(self, sig: SignalResult, fd: Optional[FundamentalData]):
        """Sort a signal into the right category bucket."""
        pair = (sig, fd)

        if sig.phase in ("INSUFFICIENT_DATA", "ERROR"):
            return

        if sig.buy_signal:
            self.buy_signals.append(pair)
        elif sig.sell_signal:
            self.sell_signals.append(pair)
        elif sig.hold_signal:
            self.hold_signals.append(pair)
        elif sig.head_fake:
            self.head_fakes.append(pair)
        elif sig.wait_signal:
            self.wait_signals.append(pair)
            self.squeeze_only.append(pair)

        # Also add to squeeze_only if squeeze is on
        if sig.cond1_squeeze_on and not sig.buy_signal:
            if pair not in self.squeeze_only:
                self.squeeze_only.append(pair)

    def print_report(self, mode: str = "ALL") -> None:
        """
        Print the scan report.
        mode: 'BUY' | 'SELL' | 'SQUEEZE' | 'ALL' | 'HOLD'
        """
        if mode == "BUY":
            sorted_buy = sorted(
                self.buy_signals,
                key=lambda x: x[0].confidence, reverse=True
            )
            print_scan_results(sorted_buy, "BUY")

        elif mode == "SELL":
            print_scan_results(self.sell_signals, "SELL")

        elif mode == "HOLD":
            print_scan_results(self.hold_signals, "HOLD")

        elif mode == "SQUEEZE":
            sorted_sqz = sorted(
                self.squeeze_only,
                key=lambda x: x[0].squeeze_days, reverse=True
            )
            print_scan_results(sorted_sqz, "SQUEEZE")

        elif mode == "ALL":
            # Print BUY first (most important), then SELL, then SQUEEZE
            sorted_buy = sorted(
                self.buy_signals,
                key=lambda x: x[0].confidence, reverse=True
            )
            print_scan_results(sorted_buy, "BUY")
            print_scan_results(self.sell_signals, "SELL")

            # Top 30 squeeze stocks by days in squeeze
            sorted_sqz = sorted(
                self.squeeze_only,
                key=lambda x: x[0].squeeze_days, reverse=True
            )[:30]
            print_scan_results(sorted_sqz, "SQUEEZE")

            # Head fake warnings
            if self.head_fakes:
                print_section("⚠️  HEAD FAKE WARNINGS", "dark_orange")
                print_scan_results(self.head_fakes, "HEAD FAKES")

        # Always print summary
        print_summary_stats(
            total     = len(self.all_results),
            buy       = len(self.buy_signals),
            sell      = len(self.sell_signals),
            squeeze   = len(self.squeeze_only),
            hold      = len(self.hold_signals),
            head_fake = len(self.head_fakes),
        )
