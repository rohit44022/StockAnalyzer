"""
sentiment_routes.py — Flask blueprint for Stock Social Media Sentiment.
══════════════════════════════════════════════════════════════════════════

Routes:
    GET /sentiment                          — Dashboard page
    GET /api/sentiment/analyze?ticker=X     — JSON analysis
    GET /api/sentiment/analyze?ticker=X&refresh=1  — bypass cache
    GET /api/sentiment/sources              — available sources status
    GET /api/sentiment/health               — source health check

Production hardening:
  - Rate limiting: 10 requests/minute per IP on the analyze endpoint
  - Input validation: ticker is sanitized in the engine layer
  - All responses are JSON-safe (no NaN/Inf)
  - Non-blocking: analysis runs in the request thread (cached = instant)

Isolation:
  This blueprint is purely read-only and never touches existing routes,
  databases, or analysis pipelines. If the engine fails, the response
  carries ok=False and the frontend shows an appropriate message.
"""

import sys, os, math, time, threading
import numpy as np
from flask import Blueprint, jsonify, request, render_template

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sentiment.engine import analyze_stock_sentiment, get_source_status
from bb_squeeze.data_loader import get_all_tickers_from_csv
from bb_squeeze.config import CSV_DIR


sentiment_bp = Blueprint("sentiment", __name__, template_folder="templates")


# ─────────────────────────────────────────────────────────────
#  RATE LIMITER — 10 requests/minute per IP for analyze endpoint
# ─────────────────────────────────────────────────────────────

_rate_store: dict = {}   # IP → list of timestamps
_rate_lock = threading.Lock()
_RATE_LIMIT = 10         # requests per window
_RATE_WINDOW = 60        # seconds


def _check_rate_limit(ip: str) -> bool:
    """Return True if request is allowed, False if rate-limited."""
    now = time.time()
    with _rate_lock:
        if ip not in _rate_store:
            _rate_store[ip] = []
        # Prune old entries
        _rate_store[ip] = [t for t in _rate_store[ip] if now - t < _RATE_WINDOW]
        if len(_rate_store[ip]) >= _RATE_LIMIT:
            return False
        _rate_store[ip].append(now)
        return True


def _safe_json(obj):
    """Make every value JSON-safe (no NaN/Inf, convert numpy types)."""
    if isinstance(obj, dict):
        return {k: _safe_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_safe_json(v) for v in obj]
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    if isinstance(obj, np.ndarray):
        return _safe_json(obj.tolist())
    return obj


@sentiment_bp.route("/sentiment")
def sentiment_dashboard():
    """Serve the Social Media Sentiment dashboard."""
    tickers = sorted(get_all_tickers_from_csv(CSV_DIR))
    return render_template("sentiment_dashboard.html", tickers=tickers)


@sentiment_bp.route("/api/sentiment/analyze")
def api_sentiment_analyze():
    """Analyze social media sentiment for a given stock ticker."""
    # Rate limiting
    client_ip = request.remote_addr or "unknown"
    if not _check_rate_limit(client_ip):
        return jsonify({
            "ok": False,
            "error": "Rate limited — max 10 requests per minute. Please wait.",
        }), 429

    raw = request.args.get("ticker", "").strip()
    if not raw:
        return jsonify({"ok": False, "error": "ticker parameter required"}), 400
    if len(raw) > 30:
        return jsonify({"ok": False, "error": "ticker too long"}), 400

    refresh = request.args.get("refresh", "0").lower() in ("1", "true", "yes")

    result = analyze_stock_sentiment(raw, force_refresh=refresh)
    return jsonify(_safe_json(result))


@sentiment_bp.route("/api/sentiment/sources")
def api_sentiment_sources():
    """Return status of all configured sentiment sources."""
    return jsonify({"sources": get_source_status()})


@sentiment_bp.route("/api/sentiment/health")
def api_sentiment_health():
    """
    Health check — quickly test if each source is reachable.
    Returns source name + reachable boolean + latency.
    Used for monitoring and debugging.
    """
    import requests as req_lib

    checks = []
    test_urls = {
        "google_news": "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en",
        "reddit": "https://www.reddit.com/r/IndianStockMarket.json?limit=1",
        "rss_india": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "stocktwits": "https://api.stocktwits.com/api/2/streams/trending.json",
        "newsapi": "https://newsapi.org/v2/top-headlines?country=in&pageSize=1&apiKey=test",
        "twitter": "https://api.twitter.com/2/tweets/search/recent?query=test",
    }

    for source, url in test_urls.items():
        t0 = time.time()
        try:
            r = req_lib.get(url, timeout=5, headers={"User-Agent": "StockAnalyzer/1.0"})
            latency = round(time.time() - t0, 2)
            # 200 or 401 (auth required) both mean the service is UP
            reachable = r.status_code in (200, 401, 403)
            checks.append({
                "source": source,
                "reachable": reachable,
                "status_code": r.status_code,
                "latency_seconds": latency,
            })
        except Exception:
            checks.append({
                "source": source,
                "reachable": False,
                "status_code": 0,
                "latency_seconds": round(time.time() - t0, 2),
            })

    return jsonify({"health": checks})
