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

def add_position(d: dict, user_id: int = None) -> dict:
    """
    Add a buy. Broker-style behavior:
      - If an OPEN position with the same (user_id, ticker, strategy_code) exists,
        AVERAGE the new buy into it (volume-weighted) instead of creating a duplicate.
        New avg price = (old_qty * old_price + new_qty * new_price) / (old_qty + new_qty).
        Earliest buy_date is preserved. Notes are appended.
      - Otherwise, insert a fresh row.

    Returns a dict:
        {
          "id":            <int>,
          "merged":        <bool>,         # True if averaged into an existing row
          "quantity":      <int>,          # final quantity on the position
          "avg_buy_price": <float>,        # final avg buy price (rounded to 4 dp)
        }
    """
    ticker        = d["ticker"].upper().strip()
    strategy_code = d["strategy_code"].upper().strip()
    add_qty       = int(d.get("quantity", 1))
    add_price     = float(d["buy_price"])
    add_date      = d["buy_date"]
    add_notes     = d.get("notes", "")

    c = _conn()
    existing = c.execute("""
        SELECT id, buy_price, quantity, buy_date, notes
          FROM portfolio_positions
         WHERE status = 'OPEN'
           AND ticker = ?
           AND strategy_code = ?
           AND (user_id IS ? OR user_id = ?)
         ORDER BY id ASC
         LIMIT 1
    """, (ticker, strategy_code, user_id, user_id)).fetchone()

    if existing is not None:
        old_qty   = int(existing["quantity"])
        old_price = float(existing["buy_price"])
        old_date  = existing["buy_date"]
        old_notes = existing["notes"] or ""

        new_qty  = old_qty + add_qty
        new_avg  = (old_qty * old_price + add_qty * add_price) / new_qty
        new_date = min(old_date, add_date) if old_date and add_date else (old_date or add_date)

        merge_tag = f"[+{add_qty} @ ₹{add_price:.2f} on {add_date}]"
        new_notes = (old_notes + " " + merge_tag).strip() if not add_notes \
                    else (old_notes + " " + merge_tag + " " + add_notes).strip()

        c.execute("""
            UPDATE portfolio_positions
               SET quantity = ?, buy_price = ?, buy_date = ?, notes = ?,
                   updated_at = datetime('now')
             WHERE id = ?
        """, (new_qty, round(new_avg, 4), new_date, new_notes, existing["id"]))
        c.commit()
        pid = int(existing["id"])
        c.close()
        return {"id": pid, "merged": True,
                "quantity": new_qty, "avg_buy_price": round(new_avg, 4)}

    cur = c.execute("""
        INSERT INTO portfolio_positions
            (user_id, ticker, strategy_code, buy_price, buy_date, quantity, notes, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN')
    """, (
        user_id, ticker, strategy_code,
        add_price, add_date, add_qty, add_notes,
    ))
    c.commit()
    pid = cur.lastrowid
    c.close()
    return {"id": pid, "merged": False,
            "quantity": add_qty, "avg_buy_price": round(add_price, 4)}


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


def partial_sell_position(pid: int, sell_qty: int, sell_price: float, sell_date: str,
                          sell_reason: str = "",
                          user_id: int = None, is_admin: bool = False) -> dict:
    """
    Sell `sell_qty` shares from an OPEN position. Broker-style behavior:
      - If sell_qty == position.quantity → close the position (status='CLOSED'),
        and record sell_price / sell_date (same as the old close_position path).
      - If sell_qty < position.quantity → reduce the quantity in place; position
        stays OPEN. avg_buy_price is preserved (Zerodha-style average-cost basis).
      - If sell_qty > position.quantity → error.

    Returns a dict:
        {
          "status":          "closed" | "partially_sold" | "error" | "not_found",
          "sold_qty":        <int>,
          "remaining_qty":   <int>,
          "avg_buy_price":   <float>,
          "pnl_per_share":   <float>,
          "total_pnl":       <float>,
          "buy_date":        <str>,
          "ticker":          <str>,
          "strategy_code":   <str>,
        }
    The trade-log row is NOT written here — the caller (HTTP endpoint) does that
    so logging stays a separate concern from DB state.
    """
    c = _conn()
    if is_admin:
        row = c.execute(
            "SELECT * FROM portfolio_positions WHERE id=? AND status='OPEN'", (pid,)
        ).fetchone()
    else:
        row = c.execute(
            "SELECT * FROM portfolio_positions WHERE id=? AND status='OPEN' AND user_id=?",
            (pid, user_id)
        ).fetchone()

    if row is None:
        c.close()
        return {"status": "not_found", "sold_qty": 0, "remaining_qty": 0,
                "avg_buy_price": 0.0, "pnl_per_share": 0.0, "total_pnl": 0.0,
                "buy_date": "", "ticker": "", "strategy_code": ""}

    pos_qty   = int(row["quantity"])
    avg_price = float(row["buy_price"])
    sell_qty  = int(sell_qty)

    if sell_qty <= 0 or sell_qty > pos_qty:
        c.close()
        return {"status": "error", "sold_qty": 0, "remaining_qty": pos_qty,
                "avg_buy_price": avg_price, "pnl_per_share": 0.0, "total_pnl": 0.0,
                "buy_date": row["buy_date"], "ticker": row["ticker"],
                "strategy_code": row["strategy_code"]}

    pnl_per_share = float(sell_price) - avg_price
    total_pnl     = pnl_per_share * sell_qty

    if sell_qty == pos_qty:
        # Full close — same effect as close_position
        c.execute("""
            UPDATE portfolio_positions
               SET status='CLOSED', sell_price=?, sell_date=?, sell_reason=?,
                   updated_at=datetime('now')
             WHERE id=?
        """, (float(sell_price), sell_date, sell_reason, pid))
        c.commit()
        c.close()
        return {"status": "closed",
                "sold_qty": sell_qty, "remaining_qty": 0,
                "avg_buy_price": round(avg_price, 4),
                "pnl_per_share": round(pnl_per_share, 4),
                "total_pnl": round(total_pnl, 2),
                "buy_date": row["buy_date"], "ticker": row["ticker"],
                "strategy_code": row["strategy_code"]}

    # Partial sell — reduce quantity, keep position OPEN, preserve avg_buy_price
    remaining = pos_qty - sell_qty
    old_notes = (row["notes"] or "").strip()
    sell_tag  = f"[-{sell_qty} @ ₹{float(sell_price):.2f} on {sell_date}]"
    new_notes = (old_notes + " " + sell_tag).strip()

    c.execute("""
        UPDATE portfolio_positions
           SET quantity=?, notes=?, updated_at=datetime('now')
         WHERE id=?
    """, (remaining, new_notes, pid))
    c.commit()
    c.close()
    return {"status": "partially_sold",
            "sold_qty": sell_qty, "remaining_qty": remaining,
            "avg_buy_price": round(avg_price, 4),
            "pnl_per_share": round(pnl_per_share, 4),
            "total_pnl": round(total_pnl, 2),
            "buy_date": row["buy_date"], "ticker": row["ticker"],
            "strategy_code": row["strategy_code"]}


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
