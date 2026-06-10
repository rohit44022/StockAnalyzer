"""
SQLite storage for per-user quick notes — one TEXT blob per user.

Stored in the shared app DB but in its own isolated `session_notes` table.
No foreign-key relationship to other tables (notes are ephemeral and unrelated
to portfolio/trades/etc.) — the only key is user_id.
"""

from __future__ import annotations
import os
import sqlite3

_PROJECT_ROOT = os.environ.get(
    "STOCK_APP_DATA",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
DB_PATH = os.path.join(_PROJECT_ROOT, "data", "app.db")

# Hard cap on note size — keeps the DB bounded and rejects accidental
# huge pastes. Plenty of room for a stock watchlist + free-form notes.
MAX_NOTE_BYTES = 50_000


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_notes_db() -> None:
    """Create the session_notes table if it does not exist."""
    c = _conn()
    c.execute("""
        CREATE TABLE IF NOT EXISTS session_notes (
            user_id     INTEGER PRIMARY KEY,
            content     TEXT    NOT NULL DEFAULT '',
            updated_at  TEXT    DEFAULT (datetime('now'))
        )
    """)
    c.commit()
    c.close()


def get_notes(user_id: int) -> str:
    """Return the user's current notes (empty string if none)."""
    if not user_id:
        return ""
    c = _conn()
    row = c.execute(
        "SELECT content FROM session_notes WHERE user_id=?", (user_id,)
    ).fetchone()
    c.close()
    return (row["content"] if row else "") or ""


def set_notes(user_id: int, content: str) -> bool:
    """Upsert the user's notes. Returns True on success."""
    if not user_id:
        return False
    content = content or ""
    # Hard cap on size
    if len(content.encode("utf-8")) > MAX_NOTE_BYTES:
        content = content[:MAX_NOTE_BYTES]
    c = _conn()
    c.execute("""
        INSERT INTO session_notes (user_id, content, updated_at)
        VALUES (?, ?, datetime('now'))
        ON CONFLICT(user_id) DO UPDATE SET
            content=excluded.content,
            updated_at=datetime('now')
    """, (user_id, content))
    c.commit()
    c.close()
    return True


def clear_notes(user_id: int) -> bool:
    """Delete the user's notes entirely (called on logout)."""
    if not user_id:
        return False
    c = _conn()
    c.execute("DELETE FROM session_notes WHERE user_id=?", (user_id,))
    c.commit()
    c.close()
    return True
