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
    c.commit()
    c.close()


# ── CREATE ───────────────────────────────────────────────────

def add_position(d: dict) -> int:
    """Insert a new portfolio position and return its ID."""
    c = _conn()
    cur = c.execute("""
        INSERT INTO portfolio_positions
            (ticker, strategy_code, buy_price, buy_date, quantity, notes, status)
        VALUES (?, ?, ?, ?, ?, ?, 'OPEN')
    """, (
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

def get_all_positions() -> list[dict]:
    """Fetch all positions ordered by status (OPEN first), then date."""
    c = _conn()
    rows = c.execute("""
        SELECT * FROM portfolio_positions
        ORDER BY
            CASE status WHEN 'OPEN' THEN 0 ELSE 1 END,
            buy_date DESC,
            created_at DESC
    """).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_open_positions() -> list[dict]:
    c = _conn()
    rows = c.execute("""
        SELECT * FROM portfolio_positions
        WHERE status = 'OPEN'
        ORDER BY buy_date DESC
    """).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_closed_positions() -> list[dict]:
    c = _conn()
    rows = c.execute("""
        SELECT * FROM portfolio_positions
        WHERE status = 'CLOSED'
        ORDER BY sell_date DESC
    """).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_position(pid: int) -> dict | None:
    c = _conn()
    row = c.execute(
        "SELECT * FROM portfolio_positions WHERE id=?", (pid,)
    ).fetchone()
    c.close()
    return dict(row) if row else None


# ── UPDATE ───────────────────────────────────────────────────

def update_position(pid: int, d: dict) -> bool:
    """Update an existing position (edit fields)."""
    c = _conn()
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
    c.commit()
    c.close()
    return n > 0


def close_position(pid: int, sell_price: float, sell_date: str, sell_reason: str = "") -> bool:
    """Mark a position as CLOSED with sell details."""
    c = _conn()
    n = c.execute("""
        UPDATE portfolio_positions SET
            status='CLOSED', sell_price=?, sell_date=?, sell_reason=?,
            updated_at=datetime('now')
        WHERE id=? AND status='OPEN'
    """, (float(sell_price), sell_date, sell_reason, pid)).rowcount
    c.commit()
    c.close()
    return n > 0


def reopen_position(pid: int) -> bool:
    """Reopen a closed position."""
    c = _conn()
    n = c.execute("""
        UPDATE portfolio_positions SET
            status='OPEN', sell_price=NULL, sell_date=NULL, sell_reason='',
            updated_at=datetime('now')
        WHERE id=? AND status='CLOSED'
    """, (pid,)).rowcount
    c.commit()
    c.close()
    return n > 0


# ── DELETE ───────────────────────────────────────────────────

def delete_position(pid: int) -> bool:
    c = _conn()
    n = c.execute(
        "DELETE FROM portfolio_positions WHERE id=?", (pid,)
    ).rowcount
    c.commit()
    c.close()
    return n > 0
