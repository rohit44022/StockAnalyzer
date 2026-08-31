"""
sentiment/storage.py — SQLite Persistent Store for Sentiment Data
=================================================================

Accumulates scraped posts over time so we build 3-month depth even
though free APIs only return recent data per request.

All public functions are wrapped in try/except — storage failures
must NEVER break the sentiment pipeline.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

logger = logging.getLogger("sentiment.storage")

_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "logs", "sentiment_store.db",
)

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS posts (
    hash       TEXT PRIMARY KEY,
    ticker     TEXT NOT NULL,
    title      TEXT,
    text       TEXT,
    url        TEXT,
    published  TEXT,
    source_name TEXT,
    platform   TEXT,
    compound   REAL DEFAULT 0,
    label      TEXT DEFAULT 'NEUTRAL',
    scraped_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_posts_ticker ON posts(ticker);
CREATE INDEX IF NOT EXISTS idx_posts_published ON posts(published);
"""

_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        return conn
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.executescript(_CREATE_SQL)
    _local.conn = conn
    return conn


def _post_hash(title: str) -> str:
    return hashlib.md5(title.lower().strip()[:80].encode()).hexdigest()


def save_posts(ticker: str, posts: List[Dict[str, Any]]) -> int:
    """Upsert scored posts into persistent store. Returns count saved."""
    try:
        conn = _get_conn()
        now = datetime.now(timezone.utc).isoformat()
        saved = 0
        for p in posts:
            title = p.get("title", "")
            if not title:
                continue
            h = _post_hash(title)
            s = p.get("sentiment", {})
            conn.execute(
                "INSERT OR IGNORE INTO posts "
                "(hash, ticker, title, text, url, published, source_name, platform, compound, label, scraped_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    h, ticker.upper(), title,
                    (p.get("text") or "")[:500],
                    p.get("url", ""),
                    p.get("published", ""),
                    p.get("source_name", ""),
                    p.get("platform", ""),
                    s.get("compound", 0),
                    s.get("label", "NEUTRAL"),
                    now,
                ),
            )
            saved += 1
        conn.commit()
        _trim_old(conn, months=3)
        return saved
    except Exception as e:
        logger.warning("storage.save_posts failed: %s", e)
        return 0


def load_posts(ticker: str, months: int = 3) -> List[Dict[str, Any]]:
    """Load stored posts for ticker from the last N months."""
    try:
        conn = _get_conn()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=months * 30)).isoformat()
        rows = conn.execute(
            "SELECT * FROM posts WHERE ticker = ? AND scraped_at > ? ORDER BY published DESC",
            (ticker.upper(), cutoff),
        ).fetchall()
        return [
            {
                "title": r["title"],
                "text": r["text"],
                "url": r["url"],
                "published": r["published"],
                "source_name": r["source_name"],
                "platform": r["platform"],
                "sentiment": {
                    "compound": r["compound"],
                    "label": r["label"],
                    "color": _label_color(r["label"]),
                },
                "metadata": {},
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning("storage.load_posts failed: %s", e)
        return []


def merge_with_fresh(
    stored: List[Dict], fresh: List[Dict],
) -> List[Dict]:
    """Combine stored + fresh posts, dedup by title hash."""
    seen = set()
    merged = []
    for p in fresh + stored:
        h = _post_hash(p.get("title", ""))
        if h in seen:
            continue
        seen.add(h)
        merged.append(p)
    return merged


def _trim_old(conn: sqlite3.Connection, months: int = 3):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=months * 30)).isoformat()
    try:
        conn.execute("DELETE FROM posts WHERE scraped_at < ?", (cutoff,))
        conn.commit()
    except Exception as e:
        logger.warning("trim_old failed: %s", e)


def _label_color(label: str) -> str:
    return {
        "STRONG_BULLISH": "#00c853",
        "BULLISH": "#66bb6a",
        "NEUTRAL": "#ffc107",
        "BEARISH": "#ef5350",
        "STRONG_BEARISH": "#ff1744",
    }.get(label, "#ffc107")
