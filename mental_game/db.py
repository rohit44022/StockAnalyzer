"""
SQLite storage layer for the Mental Game of Trading system.
Based on "The Mental Game of Trading" by Jared Tendler.

Stores: daily sessions, per-trade psychology, weekly reports,
performance map, learning curve snapshots, and pattern alerts.

DB file: <project_root>/data/app.db (shared; mental-game tables)
"""

from __future__ import annotations
import sqlite3, os, json
from datetime import datetime, date

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


def init_mental_game_db() -> None:
    """Create all mental game tables."""
    c = _conn()

    # ── DAILY PRE-SESSION CHECKLIST ──────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS daily_sessions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_date    TEXT    NOT NULL UNIQUE,
            sleep_quality   INTEGER NOT NULL DEFAULT 5,
            stress_level    INTEGER NOT NULL DEFAULT 5,
            physical_state  TEXT    DEFAULT 'OK',
            financial_pressure TEXT DEFAULT 'NONE',
            emotional_state TEXT    DEFAULT 'NEUTRAL',
            mental_score    INTEGER NOT NULL DEFAULT 7,
            go_decision     TEXT    NOT NULL DEFAULT 'GO',
            go_protocol     TEXT    DEFAULT '',
            notes           TEXT    DEFAULT '',
            created_at      TEXT    DEFAULT (datetime('now'))
        )
    """)

    # ── PER-TRADE PSYCHOLOGICAL JOURNAL ──────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS trade_psychology (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id         INTEGER,
            trade_date          TEXT    NOT NULL,
            ticker              TEXT    NOT NULL,
            pre_emotion         TEXT    DEFAULT 'NEUTRAL',
            pre_mental_score    INTEGER DEFAULT 7,
            system_followed     TEXT    DEFAULT 'YES',
            rule_broken         TEXT    DEFAULT '',
            root_cause          TEXT    DEFAULT '',
            in_trade_emotion    TEXT    DEFAULT '',
            post_reflection     TEXT    DEFAULT '',
            pattern_tag         TEXT    DEFAULT '',
            psych_gate_passed   TEXT    DEFAULT 'YES',
            confluence_required INTEGER DEFAULT 4,
            position_size_pct   INTEGER DEFAULT 100,
            created_at          TEXT    DEFAULT (datetime('now'))
        )
    """)

    # ── WEEKLY PSYCHOLOGICAL REPORT ──────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS weekly_reports (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            week_start          TEXT    NOT NULL,
            week_end            TEXT    NOT NULL,
            total_trades        INTEGER DEFAULT 0,
            rules_followed      INTEGER DEFAULT 0,
            rules_broken        INTEGER DEFAULT 0,
            common_emotion      TEXT    DEFAULT '',
            common_rule_break   TEXT    DEFAULT '',
            common_pattern      TEXT    DEFAULT '',
            root_cause_found    TEXT    DEFAULT '',
            correction_used     TEXT    DEFAULT '',
            progress_vs_last    TEXT    DEFAULT 'SAME',
            improvement_goal    TEXT    DEFAULT '',
            notes               TEXT    DEFAULT '',
            created_at          TEXT    DEFAULT (datetime('now'))
        )
    """)

    # ── PERSONAL PERFORMANCE MAP ─────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS performance_map (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            mistake         TEXT    NOT NULL,
            emotion_behind  TEXT    NOT NULL,
            root_cause      TEXT    NOT NULL,
            correction      TEXT    NOT NULL,
            early_warning   TEXT    NOT NULL,
            tendler_problem TEXT    DEFAULT '',
            severity        INTEGER DEFAULT 5,
            is_active       INTEGER DEFAULT 1,
            created_at      TEXT    DEFAULT (datetime('now')),
            updated_at      TEXT    DEFAULT (datetime('now'))
        )
    """)

    # ── LEARNING CURVE / INCHWORM TRACKER ────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS learning_curve (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            month           TEXT    NOT NULL,
            floor_score     REAL    DEFAULT 3.0,
            avg_score       REAL    DEFAULT 5.0,
            ceiling_score   REAL    DEFAULT 8.0,
            inchworm_dir    TEXT    DEFAULT 'STABLE',
            fear_level      TEXT    DEFAULT 'CONSCIOUS_INCOMPETENCE',
            greed_level     TEXT    DEFAULT 'CONSCIOUS_INCOMPETENCE',
            anger_level     TEXT    DEFAULT 'CONSCIOUS_INCOMPETENCE',
            confidence_level TEXT   DEFAULT 'CONSCIOUS_INCOMPETENCE',
            discipline_level TEXT   DEFAULT 'CONSCIOUS_INCOMPETENCE',
            notes           TEXT    DEFAULT '',
            created_at      TEXT    DEFAULT (datetime('now'))
        )
    """)

    # ── EMERGENCY PROTOCOL LOG ───────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS emergency_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            log_date        TEXT    NOT NULL,
            protocol_type   TEXT    NOT NULL,
            trigger_desc    TEXT    DEFAULT '',
            steps_taken     TEXT    DEFAULT '',
            outcome         TEXT    DEFAULT '',
            created_at      TEXT    DEFAULT (datetime('now'))
        )
    """)

    # ── MIGRATIONS ───────────────────────────────────────────
    try:
        c.execute("ALTER TABLE performance_map ADD COLUMN severity INTEGER DEFAULT 5")
    except Exception:
        pass  # column already exists

    c.commit()
    c.close()


# ════════════════════════════════════════════════════════════════
#  DAILY SESSION CRUD
# ════════════════════════════════════════════════════════════════

def save_daily_session(d: dict) -> int:
    c = _conn()
    cur = c.execute("""
        INSERT OR REPLACE INTO daily_sessions
            (session_date, sleep_quality, stress_level, physical_state,
             financial_pressure, emotional_state, mental_score,
             go_decision, go_protocol, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        d["session_date"],
        int(d.get("sleep_quality", 5)),
        int(d.get("stress_level", 5)),
        d.get("physical_state", "OK"),
        d.get("financial_pressure", "NONE"),
        d.get("primary_emotion") or d.get("emotional_state", "NEUTRAL"),
        int(d.get("mental_score", 7)),
        d.get("go_decision", "GO"),
        d.get("go_protocol", ""),
        d.get("warmup_notes") or d.get("notes", ""),
    ))
    c.commit()
    sid = cur.lastrowid
    c.close()
    return sid


def get_daily_session(session_date: str) -> dict | None:
    c = _conn()
    row = c.execute(
        "SELECT * FROM daily_sessions WHERE session_date=?", (session_date,)
    ).fetchone()
    c.close()
    if not row:
        return None
    d = dict(row)
    d["primary_emotion"] = d.get("emotional_state", "")
    d["warmup_notes"] = d.get("notes", "")
    return d


def get_all_sessions(limit: int = 30) -> list[dict]:
    c = _conn()
    rows = c.execute(
        "SELECT * FROM daily_sessions ORDER BY session_date DESC LIMIT ?", (limit,)
    ).fetchall()
    c.close()
    result = []
    for r in rows:
        d = dict(r)
        d["primary_emotion"] = d.get("emotional_state", "")
        d["warmup_notes"] = d.get("notes", "")
        result.append(d)
    return result


# ════════════════════════════════════════════════════════════════
#  TRADE PSYCHOLOGY CRUD
# ════════════════════════════════════════════════════════════════

def save_trade_psychology(d: dict) -> int:
    c = _conn()
    cur = c.execute("""
        INSERT INTO trade_psychology
            (position_id, trade_date, ticker, pre_emotion, pre_mental_score,
             system_followed, rule_broken, root_cause, in_trade_emotion,
             post_reflection, pattern_tag, psych_gate_passed,
             confluence_required, position_size_pct)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        d.get("position_id"),
        d["trade_date"],
        d["ticker"].upper().strip(),
        d.get("pre_emotion", "NEUTRAL"),
        int(d.get("pre_mental_score", 7)),
        d.get("system_followed", "YES"),
        d.get("rule_broken", ""),
        d.get("root_cause", ""),
        d.get("in_trade_emotion", ""),
        d.get("post_reflection", ""),
        d.get("pattern_tag", ""),
        d.get("psych_gate_passed", "YES"),
        int(d.get("confluence_required", 4)),
        int(d.get("position_size_pct", 100)),
    ))
    c.commit()
    tid = cur.lastrowid
    c.close()
    return tid


def update_trade_psychology(tid: int, d: dict) -> bool:
    c = _conn()
    n = c.execute("""
        UPDATE trade_psychology SET
            pre_emotion=?, pre_mental_score=?, system_followed=?,
            rule_broken=?, root_cause=?, in_trade_emotion=?,
            post_reflection=?, pattern_tag=?, psych_gate_passed=?,
            confluence_required=?, position_size_pct=?
        WHERE id=?
    """, (
        d.get("pre_emotion", "NEUTRAL"),
        int(d.get("pre_mental_score", 7)),
        d.get("system_followed", "YES"),
        d.get("rule_broken", ""),
        d.get("root_cause", ""),
        d.get("in_trade_emotion", ""),
        d.get("post_reflection", ""),
        d.get("pattern_tag", ""),
        d.get("psych_gate_passed", "YES"),
        int(d.get("confluence_required", 4)),
        int(d.get("position_size_pct", 100)),
        tid,
    )).rowcount
    c.commit()
    c.close()
    return n > 0


def get_trade_psychology(tid: int) -> dict | None:
    c = _conn()
    row = c.execute(
        "SELECT * FROM trade_psychology WHERE id=?", (tid,)
    ).fetchone()
    c.close()
    return dict(row) if row else None


def get_trade_psych_by_position(pid: int) -> dict | None:
    c = _conn()
    row = c.execute(
        "SELECT * FROM trade_psychology WHERE position_id=? ORDER BY id DESC LIMIT 1",
        (pid,)
    ).fetchone()
    c.close()
    return dict(row) if row else None


def get_all_trade_psychology(limit: int = 100) -> list[dict]:
    c = _conn()
    rows = c.execute(
        "SELECT * FROM trade_psychology ORDER BY trade_date DESC, id DESC LIMIT ?",
        (limit,)
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_trade_psych_for_week(start: str, end: str) -> list[dict]:
    c = _conn()
    rows = c.execute(
        "SELECT * FROM trade_psychology WHERE trade_date >= ? AND trade_date <= ? ORDER BY trade_date",
        (start, end)
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


# ════════════════════════════════════════════════════════════════
#  WEEKLY REPORT CRUD
# ════════════════════════════════════════════════════════════════

def save_weekly_report(d: dict) -> int:
    c = _conn()
    cur = c.execute("""
        INSERT INTO weekly_reports
            (week_start, week_end, total_trades, rules_followed, rules_broken,
             common_emotion, common_rule_break, common_pattern,
             root_cause_found, correction_used, progress_vs_last,
             improvement_goal, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        d["week_start"], d["week_end"],
        int(d.get("total_trades", 0)),
        int(d.get("rules_followed", 0)),
        int(d.get("rules_broken", 0)),
        d.get("common_emotion", ""),
        d.get("common_rule_break", ""),
        d.get("common_pattern", ""),
        d.get("root_cause_found", ""),
        d.get("correction_used", ""),
        d.get("progress_vs_last", "SAME"),
        d.get("improvement_goal", ""),
        d.get("notes", ""),
    ))
    c.commit()
    wid = cur.lastrowid
    c.close()
    return wid


def get_all_weekly_reports(limit: int = 52) -> list[dict]:
    c = _conn()
    rows = c.execute(
        "SELECT * FROM weekly_reports ORDER BY week_end DESC LIMIT ?", (limit,)
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


# ════════════════════════════════════════════════════════════════
#  PERFORMANCE MAP CRUD
# ════════════════════════════════════════════════════════════════

def save_perf_map_entry(d: dict) -> int:
    c = _conn()
    cur = c.execute("""
        INSERT INTO performance_map
            (mistake, emotion_behind, root_cause, correction,
             early_warning, tendler_problem, severity)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        d["mistake"], d["emotion_behind"], d["root_cause"],
        d["correction"], d["early_warning"],
        d.get("tendler_problem", ""), d.get("severity", 5),
    ))
    c.commit()
    mid = cur.lastrowid
    c.close()
    return mid


def update_perf_map_entry(mid: int, d: dict) -> bool:
    c = _conn()
    n = c.execute("""
        UPDATE performance_map SET
            mistake=?, emotion_behind=?, root_cause=?, correction=?,
            early_warning=?, tendler_problem=?, severity=?,
            updated_at=datetime('now')
        WHERE id=?
    """, (
        d["mistake"], d["emotion_behind"], d["root_cause"],
        d["correction"], d["early_warning"],
        d.get("tendler_problem", ""), d.get("severity", 5), mid,
    )).rowcount
    c.commit()
    c.close()
    return n > 0


def delete_perf_map_entry(mid: int) -> bool:
    c = _conn()
    n = c.execute("DELETE FROM performance_map WHERE id=?", (mid,)).rowcount
    c.commit()
    c.close()
    return n > 0


def get_all_perf_map() -> list[dict]:
    c = _conn()
    rows = c.execute(
        "SELECT * FROM performance_map WHERE is_active=1 ORDER BY id"
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


# ════════════════════════════════════════════════════════════════
#  LEARNING CURVE / INCHWORM CRUD
# ════════════════════════════════════════════════════════════════

def save_learning_curve(d: dict) -> int:
    c = _conn()
    cur = c.execute("""
        INSERT OR REPLACE INTO learning_curve
            (month, floor_score, avg_score, ceiling_score, inchworm_dir,
             fear_level, greed_level, anger_level,
             confidence_level, discipline_level, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        d["month"],
        float(d.get("floor_score", 3)),
        float(d.get("avg_score", 5)),
        float(d.get("ceiling_score", 8)),
        d.get("inchworm_dir", "STABLE"),
        d.get("fear") or d.get("fear_level", "CI"),
        d.get("greed") or d.get("greed_level", "CI"),
        d.get("anger") or d.get("anger_level", "CI"),
        d.get("confidence") or d.get("confidence_level", "CI"),
        d.get("discipline") or d.get("discipline_level", "CI"),
        d.get("notes", ""),
    ))
    c.commit()
    lid = cur.lastrowid
    c.close()
    return lid


def get_all_learning_curve() -> list[dict]:
    c = _conn()
    rows = c.execute(
        "SELECT * FROM learning_curve ORDER BY month DESC"
    ).fetchall()
    c.close()
    result = []
    for r in rows:
        d = dict(r)
        # Expose short keys for frontend compatibility
        d["fear"] = d.get("fear_level", "CI")
        d["greed"] = d.get("greed_level", "CI")
        d["anger"] = d.get("anger_level", "CI")
        d["confidence"] = d.get("confidence_level", "CI")
        d["discipline"] = d.get("discipline_level", "CI")
        result.append(d)
    return result


# ════════════════════════════════════════════════════════════════
#  EMERGENCY LOG CRUD
# ════════════════════════════════════════════════════════════════

def save_emergency_log(d: dict) -> int:
    c = _conn()
    cur = c.execute("""
        INSERT INTO emergency_log
            (log_date, protocol_type, trigger_desc, steps_taken, outcome)
        VALUES (?, ?, ?, ?, ?)
    """, (
        d["log_date"], d["protocol_type"],
        d.get("trigger_desc", ""),
        d.get("steps_taken", ""),
        d.get("outcome", "") + ((' | Score After: ' + str(d['score_after'])) if d.get('score_after') else '') + ((' | ' + d['notes']) if d.get('notes') else ''),
    ))
    c.commit()
    eid = cur.lastrowid
    c.close()
    return eid


def get_all_emergency_logs(limit: int = 50) -> list[dict]:
    c = _conn()
    rows = c.execute(
        "SELECT * FROM emergency_log ORDER BY log_date DESC, id DESC LIMIT ?",
        (limit,)
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]
