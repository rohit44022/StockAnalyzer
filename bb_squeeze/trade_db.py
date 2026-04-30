"""
SQLite storage layer for the Trade P&L Dashboard.
DB file: <project_root>/data/app.db (shared, table: trades)
"""

from __future__ import annotations
import sqlite3, os

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


def init_db() -> None:
    c = _conn()
    c.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER DEFAULT NULL,
            stock       TEXT    NOT NULL,
            platform    TEXT    NOT NULL DEFAULT 'zerodha',
            trade_type  TEXT    NOT NULL DEFAULT 'delivery',
            exchange    TEXT    NOT NULL DEFAULT 'NSE',
            quantity    INTEGER NOT NULL,
            buy_price   REAL    NOT NULL,
            sell_price  REAL    NOT NULL,
            buy_date    TEXT    NOT NULL,
            sell_date   TEXT    NOT NULL,
            notes       TEXT    DEFAULT '',
            position_id INTEGER DEFAULT NULL,
            created_at  TEXT    DEFAULT (datetime('now'))
        )
    """)
    # Migration: add user_id column if missing (existing DBs)
    try:
        existing = {r[1] for r in c.execute("PRAGMA table_info(trades)").fetchall()}
        if "user_id" not in existing:
            c.execute("ALTER TABLE trades ADD COLUMN user_id INTEGER DEFAULT NULL")
        if "position_id" not in existing:
            c.execute("ALTER TABLE trades ADD COLUMN position_id INTEGER DEFAULT NULL")
    except Exception:
        pass
    c.execute("CREATE INDEX IF NOT EXISTS idx_trades_user_id ON trades(user_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_trades_position_id ON trades(position_id)")
    c.commit()
    c.close()


_INSERT = """INSERT INTO trades
    (user_id, stock, platform, trade_type, exchange, quantity,
     buy_price, sell_price, buy_date, sell_date, notes, position_id)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"""


def add_trade(d: dict, user_id: int = None) -> int:
    c = _conn()
    pos_id = d.get("position_id")
    cur = c.execute(_INSERT, (
        user_id,
        d["stock"].upper().strip(),
        d.get("platform", "zerodha"),
        d.get("trade_type", "delivery"),
        d.get("exchange", "NSE"),
        int(d["quantity"]),
        float(d["buy_price"]),
        float(d["sell_price"]),
        d["buy_date"],
        d["sell_date"],
        d.get("notes", ""),
        int(pos_id) if pos_id else None,
    ))
    c.commit()
    tid = cur.lastrowid
    c.close()
    return tid


def delete_trades_by_position(position_id: int, user_id: int = None, is_admin: bool = False) -> int:
    """Delete trade rows linked to a portfolio position. Returns rows deleted."""
    if not position_id:
        return 0
    c = _conn()
    if is_admin:
        n = c.execute("DELETE FROM trades WHERE position_id=?", (position_id,)).rowcount
    else:
        n = c.execute("DELETE FROM trades WHERE position_id=? AND user_id=?", (position_id, user_id)).rowcount
    c.commit()
    c.close()
    return n


def get_all_trades(user_id: int = None, is_admin: bool = False) -> list[dict]:
    """Get trades. Admin sees all; regular user sees only their own."""
    c = _conn()
    if is_admin:
        rows = c.execute(
            "SELECT * FROM trades ORDER BY sell_date DESC, created_at DESC"
        ).fetchall()
    else:
        rows = c.execute(
            "SELECT * FROM trades WHERE user_id = ? ORDER BY sell_date DESC, created_at DESC",
            (user_id,),
        ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_trade(tid: int, user_id: int = None, is_admin: bool = False) -> dict | None:
    c = _conn()
    if is_admin:
        row = c.execute("SELECT * FROM trades WHERE id=?", (tid,)).fetchone()
    else:
        row = c.execute("SELECT * FROM trades WHERE id=? AND user_id=?", (tid, user_id)).fetchone()
    c.close()
    return dict(row) if row else None


def delete_trade(tid: int, user_id: int = None, is_admin: bool = False) -> bool:
    c = _conn()
    if is_admin:
        n = c.execute("DELETE FROM trades WHERE id=?", (tid,)).rowcount
    else:
        n = c.execute("DELETE FROM trades WHERE id=? AND user_id=?", (tid, user_id)).rowcount
    c.commit()
    c.close()
    return n > 0


def update_trade(tid: int, d: dict, user_id: int = None, is_admin: bool = False) -> bool:
    c = _conn()
    if is_admin:
        n = c.execute("""
            UPDATE trades SET
                stock=?, platform=?, trade_type=?, exchange=?,
                quantity=?, buy_price=?, sell_price=?,
                buy_date=?, sell_date=?, notes=?
            WHERE id=?
        """, (
            d["stock"].upper().strip(),
            d.get("platform", "zerodha"),
            d.get("trade_type", "delivery"),
            d.get("exchange", "NSE"),
            int(d["quantity"]),
            float(d["buy_price"]),
            float(d["sell_price"]),
            d["buy_date"],
            d["sell_date"],
            d.get("notes", ""),
            tid,
        )).rowcount
    else:
        n = c.execute("""
            UPDATE trades SET
                stock=?, platform=?, trade_type=?, exchange=?,
                quantity=?, buy_price=?, sell_price=?,
                buy_date=?, sell_date=?, notes=?
            WHERE id=? AND user_id=?
        """, (
            d["stock"].upper().strip(),
            d.get("platform", "zerodha"),
            d.get("trade_type", "delivery"),
            d.get("exchange", "NSE"),
            int(d["quantity"]),
            float(d["buy_price"]),
            float(d["sell_price"]),
            d["buy_date"],
            d["sell_date"],
            d.get("notes", ""),
            tid, user_id,
        )).rowcount
    c.commit()
    c.close()
    return n > 0


def user_has_trades(user_id: int) -> bool:
    """Check if a user has any trades (for nav visibility)."""
    if not user_id:
        return False
    c = _conn()
    row = c.execute("SELECT 1 FROM trades WHERE user_id=? LIMIT 1", (user_id,)).fetchone()
    c.close()
    return row is not None
