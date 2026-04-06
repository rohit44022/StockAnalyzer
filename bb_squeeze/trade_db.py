"""
SQLite storage layer for the Trade P&L Dashboard.
DB file: <project_root>/trades.db
"""

from __future__ import annotations
import sqlite3, os

_DATA_DIR = os.environ.get(
    "STOCK_APP_DATA",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
DB_PATH = os.path.join(_DATA_DIR, "trades.db")


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
            created_at  TEXT    DEFAULT (datetime('now'))
        )
    """)
    c.commit()
    c.close()


_INSERT = """INSERT INTO trades
    (stock, platform, trade_type, exchange, quantity,
     buy_price, sell_price, buy_date, sell_date, notes)
    VALUES (?,?,?,?,?,?,?,?,?,?)"""


def add_trade(d: dict) -> int:
    c = _conn()
    cur = c.execute(_INSERT, (
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
    ))
    c.commit()
    tid = cur.lastrowid
    c.close()
    return tid


def get_all_trades() -> list[dict]:
    c = _conn()
    rows = c.execute(
        "SELECT * FROM trades ORDER BY sell_date DESC, created_at DESC"
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_trade(tid: int) -> dict | None:
    c = _conn()
    row = c.execute("SELECT * FROM trades WHERE id=?", (tid,)).fetchone()
    c.close()
    return dict(row) if row else None


def delete_trade(tid: int) -> bool:
    c = _conn()
    n = c.execute("DELETE FROM trades WHERE id=?", (tid,)).rowcount
    c.commit()
    c.close()
    return n > 0


def update_trade(tid: int, d: dict) -> bool:
    c = _conn()
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
    c.commit()
    c.close()
    return n > 0
