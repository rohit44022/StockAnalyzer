#!/usr/bin/env python3
"""
Stock Analyzer — macOS Desktop Application
===========================================
Wraps the Flask web dashboard in a native macOS window using pywebview.
All analysis engines (BB Methods I-IV, TA, Hybrid, Quant, Price Action)
run locally — no external server needed.

Usage (development):  python3 desktop_app.py
Usage (built app):    open StockAnalyzer.app
"""

import sys, os, threading, time, shutil

# ── Determine runtime mode (MUST happen before any project imports) ──
FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    # Running inside a PyInstaller .app bundle
    BUNDLE_DIR = sys._MEIPASS
    DATA_DIR = os.path.join(
        os.path.expanduser("~"), "Documents", "StockAnalyzer"
    )
    os.makedirs(DATA_DIR, exist_ok=True)

    # Set env var so bb_squeeze.config / trade_db / portfolio_db / historical_data
    # resolve CSV_DIR, DB paths, cache to the writable data directory.
    os.environ["STOCK_APP_DATA"] = DATA_DIR

    # Ensure bundle root is on sys.path
    if BUNDLE_DIR not in sys.path:
        sys.path.insert(0, BUNDLE_DIR)

    # ── First-launch bootstrap: copy data from bundle → user Documents ──
    csv_src = os.path.join(BUNDLE_DIR, "stock_csv")
    csv_dest = os.path.join(DATA_DIR, "stock_csv")
    if not os.path.exists(csv_dest) and os.path.exists(csv_src):
        shutil.copytree(csv_src, csv_dest)

    cache_src = os.path.join(BUNDLE_DIR, "tickers_cache.json")
    cache_dest = os.path.join(DATA_DIR, "tickers_cache.json")
    if not os.path.exists(cache_dest) and os.path.exists(cache_src):
        shutil.copy2(cache_src, cache_dest)

    # Ensure writable sub-dirs
    os.makedirs(os.path.join(DATA_DIR, "bb_squeeze", "cache"), exist_ok=True)
else:
    # Development mode — everything in project root
    ROOT = os.path.dirname(os.path.abspath(__file__))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)

# ── Now safe to import project modules ───────────────────────────
import webview                       # pywebview — native WebKit window
from web.app import app as flask_app

PORT = 5001
APP_TITLE = "Stock Analyzer — BB Squeeze · TA · Hybrid · Price Action"


def _start_flask():
    """Run Flask in a daemon thread (no reloader, no debug)."""
    flask_app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False)


def main():
    # Start Flask server in background
    server = threading.Thread(target=_start_flask, daemon=True)
    server.start()

    # Give Flask a moment to bind the port
    time.sleep(1.5)

    # Create native macOS window (WebKit-backed)
    webview.create_window(
        APP_TITLE,
        url=f"http://127.0.0.1:{PORT}",
        width=1440,
        height=900,
        min_size=(1024, 768),
    )

    # Blocks until the window is closed, then process exits
    webview.start()


if __name__ == "__main__":
    main()
