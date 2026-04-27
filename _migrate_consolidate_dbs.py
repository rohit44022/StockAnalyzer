"""
One-shot migration: consolidate mental_game.db, trades.db, portfolio.db,
data/auth.db into a single data/app.db.

Preserves: schema, indexes, primary keys, AUTOINCREMENT counters
(via sqlite_sequence), all rows.

Verifies: per-table row count in target == source after copy.
"""
from __future__ import annotations

import os
import sqlite3
import sys

PROJECT = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(PROJECT, "data", "app.db")
SOURCES = [
    os.path.join(PROJECT, "mental_game.db"),
    os.path.join(PROJECT, "trades.db"),
    os.path.join(PROJECT, "portfolio.db"),
    os.path.join(PROJECT, "data", "auth.db"),
]


def _list_user_objects(conn: sqlite3.Connection, db_alias: str = "main"):
    """Return (tables, indexes) where each is list of (name, sql).
    Excludes sqlite_* internal objects (sqlite_sequence handled separately)."""
    cur = conn.execute(
        f"SELECT type, name, sql FROM {db_alias}.sqlite_master "
        f"WHERE type IN ('table', 'index') AND name NOT LIKE 'sqlite_%' "
        f"ORDER BY type DESC, name"
    )
    tables, indexes = [], []
    for typ, name, sql in cur.fetchall():
        if sql is None:
            continue  # auto-created indexes (UNIQUE, PRIMARY KEY) skipped
        if typ == "table":
            tables.append((name, sql))
        else:
            indexes.append((name, sql))
    return tables, indexes


def _src_row_counts(src_path: str) -> dict[str, int]:
    s = sqlite3.connect(src_path)
    s.row_factory = sqlite3.Row
    counts: dict[str, int] = {}
    for (name,) in s.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall():
        counts[name] = s.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
    s.close()
    return counts


def main() -> int:
    if os.path.exists(TARGET):
        print(f"ERROR: target already exists, aborting: {TARGET}", file=sys.stderr)
        return 1

    os.makedirs(os.path.dirname(TARGET), exist_ok=True)

    expected_counts: dict[str, dict[str, int]] = {}
    for src in SOURCES:
        if not os.path.exists(src):
            print(f"ERROR: missing source: {src}", file=sys.stderr)
            return 2
        expected_counts[src] = _src_row_counts(src)

    target = sqlite3.connect(TARGET)
    target.execute("PRAGMA journal_mode=WAL")
    target.execute("PRAGMA foreign_keys=OFF")  # off during bulk copy

    seen_tables: dict[str, str] = {}  # name -> source path (to detect collisions)

    for src in SOURCES:
        alias = "src"
        target.execute(f"ATTACH DATABASE ? AS {alias}", (src,))
        tables, indexes = _list_user_objects(target, alias)

        for name, sql in tables:
            if name in seen_tables:
                print(
                    f"ERROR: table name collision '{name}' between "
                    f"{seen_tables[name]} and {src}",
                    file=sys.stderr,
                )
                return 3
            seen_tables[name] = src
            target.execute(sql)
            target.execute(
                f"INSERT INTO main.{name} SELECT * FROM {alias}.{name}"
            )

        for name, sql in indexes:
            target.execute(sql)

        # Carry forward AUTOINCREMENT counters. sqlite_sequence has no
        # UNIQUE constraint, so emulate upsert: take MAX of existing/new.
        for (seq_name, seq_val) in target.execute(
            f"SELECT name, seq FROM {alias}.sqlite_sequence"
        ).fetchall():
            row = target.execute(
                "SELECT seq FROM main.sqlite_sequence WHERE name = ?",
                (seq_name,),
            ).fetchone()
            if row is None:
                target.execute(
                    "INSERT INTO main.sqlite_sequence(name, seq) VALUES (?, ?)",
                    (seq_name, seq_val),
                )
            else:
                target.execute(
                    "UPDATE main.sqlite_sequence SET seq = ? WHERE name = ?",
                    (max(row[0], seq_val), seq_name),
                )

        target.commit()
        target.execute(f"DETACH DATABASE {alias}")

    target.commit()

    # Verify
    print("\n=== Verification ===")
    ok = True
    for src, counts in expected_counts.items():
        for name, expected in counts.items():
            actual = target.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            mark = "OK" if actual == expected else "MISMATCH"
            if actual != expected:
                ok = False
            print(f"  [{mark}] {os.path.basename(src):20s} {name:25s} "
                  f"expected={expected}  actual={actual}")

    target.execute("PRAGMA foreign_keys=ON")
    target.close()

    if not ok:
        print("VERIFICATION FAILED", file=sys.stderr)
        return 4
    print(f"\nConsolidated DB: {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
