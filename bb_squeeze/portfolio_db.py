"""
SQLite storage layer for the Strategy Portfolio Tracker.
DB file: <project_root>/data/app.db (shared, table: portfolio_positions)
"""

from __future__ import annotations
import sqlite3, os
from datetime import datetime

_PROJECT_ROOT = os.environ.get(
    "STOCK_APP_DATA",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
DB_PATH = os.path.join(_PROJECT_ROOT, "data", "app.db")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init_portfolio_db() -> None:
    """Create the portfolio_positions table if it doesn't exist."""
    c = _conn()
    c.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_positions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER DEFAULT NULL,
            ticker          TEXT    NOT NULL,
            strategy_code   TEXT    NOT NULL,
            buy_price       REAL    NOT NULL,
            buy_date        TEXT    NOT NULL,
            quantity         INTEGER NOT NULL DEFAULT 1,
            notes           TEXT    DEFAULT '',
            status          TEXT    NOT NULL DEFAULT 'OPEN',
            sell_price      REAL,
            sell_date       TEXT,
            sell_reason     TEXT    DEFAULT '',
            created_at      TEXT    DEFAULT (datetime('now')),
            updated_at      TEXT    DEFAULT (datetime('now'))
        )
    """)
    # Migration: add user_id column if missing (existing DBs)
    try:
        existing = {r[1] for r in c.execute("PRAGMA table_info(portfolio_positions)").fetchall()}
        if "user_id" not in existing:
            c.execute("ALTER TABLE portfolio_positions ADD COLUMN user_id INTEGER DEFAULT NULL")
    except Exception:
        pass
    c.execute("CREATE INDEX IF NOT EXISTS idx_portfolio_user_id ON portfolio_positions(user_id)")
    c.commit()
    c.close()


# ── CREATE ───────────────────────────────────────────────────

def add_position(d: dict, user_id: int = None) -> int:
    """Insert a new portfolio position and return its ID."""
    c = _conn()
    cur = c.execute("""
        INSERT INTO portfolio_positions
            (user_id, ticker, strategy_code, buy_price, buy_date, quantity, notes, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN')
    """, (
        user_id,
        d["ticker"].upper().strip(),
        d["strategy_code"].upper().strip(),
        float(d["buy_price"]),
        d["buy_date"],
        int(d.get("quantity", 1)),
        d.get("notes", ""),
    ))
    c.commit()
    pid = cur.lastrowid
    c.close()
    return pid


# ── READ ─────────────────────────────────────────────────────

def get_all_positions(user_id: int = None, is_admin: bool = False) -> list[dict]:
    """Fetch positions. Admin sees all; regular user sees only their own."""
    c = _conn()
    if is_admin:
        rows = c.execute("""
            SELECT * FROM portfolio_positions
            ORDER BY CASE status WHEN 'OPEN' THEN 0 ELSE 1 END, buy_date DESC, created_at DESC
        """).fetchall()
    else:
        rows = c.execute("""
            SELECT * FROM portfolio_positions WHERE user_id = ?
            ORDER BY CASE status WHEN 'OPEN' THEN 0 ELSE 1 END, buy_date DESC, created_at DESC
        """, (user_id,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_open_positions(user_id: int = None, is_admin: bool = False) -> list[dict]:
    c = _conn()
    if is_admin:
        rows = c.execute("""
            SELECT * FROM portfolio_positions WHERE status = 'OPEN' ORDER BY buy_date DESC
        """).fetchall()
    else:
        rows = c.execute("""
            SELECT * FROM portfolio_positions WHERE status = 'OPEN' AND user_id = ? ORDER BY buy_date DESC
        """, (user_id,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_closed_positions(user_id: int = None, is_admin: bool = False) -> list[dict]:
    c = _conn()
    if is_admin:
        rows = c.execute("""
            SELECT * FROM portfolio_positions WHERE status = 'CLOSED' ORDER BY sell_date DESC
        """).fetchall()
    else:
        rows = c.execute("""
            SELECT * FROM portfolio_positions WHERE status = 'CLOSED' AND user_id = ? ORDER BY sell_date DESC
        """, (user_id,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_position(pid: int, user_id: int = None, is_admin: bool = False) -> dict | None:
    c = _conn()
    if is_admin:
        row = c.execute("SELECT * FROM portfolio_positions WHERE id=?", (pid,)).fetchone()
    else:
        row = c.execute("SELECT * FROM portfolio_positions WHERE id=? AND user_id=?", (pid, user_id)).fetchone()
    c.close()
    return dict(row) if row else None


# ── UPDATE ───────────────────────────────────────────────────

def update_position(pid: int, d: dict, user_id: int = None, is_admin: bool = False) -> bool:
    """Update an existing position (edit fields)."""
    c = _conn()
    if is_admin:
        n = c.execute("""
            UPDATE portfolio_positions SET
                ticker=?, strategy_code=?, buy_price=?, buy_date=?,
                quantity=?, notes=?, updated_at=datetime('now')
            WHERE id=?
        """, (
            d["ticker"].upper().strip(),
            d["strategy_code"].upper().strip(),
            float(d["buy_price"]),
            d["buy_date"],
            int(d.get("quantity", 1)),
            d.get("notes", ""),
            pid,
        )).rowcount
    else:
        n = c.execute("""
            UPDATE portfolio_positions SET
                ticker=?, strategy_code=?, buy_price=?, buy_date=?,
                quantity=?, notes=?, updated_at=datetime('now')
            WHERE id=? AND user_id=?
        """, (
            d["ticker"].upper().strip(),
            d["strategy_code"].upper().strip(),
            float(d["buy_price"]),
            d["buy_date"],
            int(d.get("quantity", 1)),
            d.get("notes", ""),
            pid, user_id,
        )).rowcount
    c.commit()
    c.close()
    return n > 0


def close_position(pid: int, sell_price: float, sell_date: str, sell_reason: str = "",
                   user_id: int = None, is_admin: bool = False) -> bool:
    """Mark a position as CLOSED with sell details."""
    c = _conn()
    if is_admin:
        n = c.execute("""
            UPDATE portfolio_positions SET
                status='CLOSED', sell_price=?, sell_date=?, sell_reason=?,
                updated_at=datetime('now')
            WHERE id=? AND status='OPEN'
        """, (float(sell_price), sell_date, sell_reason, pid)).rowcount
    else:
        n = c.execute("""
            UPDATE portfolio_positions SET
                status='CLOSED', sell_price=?, sell_date=?, sell_reason=?,
                updated_at=datetime('now')
            WHERE id=? AND status='OPEN' AND user_id=?
        """, (float(sell_price), sell_date, sell_reason, pid, user_id)).rowcount
    c.commit()
    c.close()
    return n > 0


def reopen_position(pid: int, user_id: int = None, is_admin: bool = False) -> bool:
    """Reopen a closed position."""
    c = _conn()
    if is_admin:
        n = c.execute("""
            UPDATE portfolio_positions SET
                status='OPEN', sell_price=NULL, sell_date=NULL, sell_reason='',
                updated_at=datetime('now')
            WHERE id=? AND status='CLOSED'
        """, (pid,)).rowcount
    else:
        n = c.execute("""
            UPDATE portfolio_positions SET
                status='OPEN', sell_price=NULL, sell_date=NULL, sell_reason='',
                updated_at=datetime('now')
            WHERE id=? AND status='CLOSED' AND user_id=?
        """, (pid, user_id)).rowcount
    c.commit()
    c.close()
    return n > 0


# ── DELETE ───────────────────────────────────────────────────

def delete_position(pid: int, user_id: int = None, is_admin: bool = False) -> bool:
    c = _conn()
    if is_admin:
        n = c.execute("DELETE FROM portfolio_positions WHERE id=?", (pid,)).rowcount
    else:
        n = c.execute("DELETE FROM portfolio_positions WHERE id=? AND user_id=?", (pid, user_id)).rowcount
    c.commit()
    c.close()
    return n > 0


def user_has_positions(user_id: int) -> bool:
    """Check if a user has any portfolio positions (for nav visibility)."""
    if not user_id:
        return False
    c = _conn()
    row = c.execute("SELECT 1 FROM portfolio_positions WHERE user_id=? LIMIT 1", (user_id,)).fetchone()
    c.close()
    return row is not None
