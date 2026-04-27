"""
auth/db.py — User database & session storage.

SQLite-backed user management with:
  - users table (full profile: name, contact, address, trading experience)
  - sessions table (server-side session tokens)
  - rate_limit table (brute-force protection)
"""
from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timedelta
from contextlib import contextmanager

_DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_DB_PATH = os.path.join(_DB_DIR, "app.db")

# Session lifetime
SESSION_LIFETIME_HOURS = 24
# Max failed login attempts before lockout
MAX_FAILED_ATTEMPTS = 5
# Lockout duration in minutes
LOCKOUT_MINUTES = 15


def _ensure_dir():
    os.makedirs(_DB_DIR, exist_ok=True)


@contextmanager
def _get_conn():
    _ensure_dir()
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_auth_db():
    """Create auth tables if they don't exist."""
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                username            TEXT    UNIQUE NOT NULL,
                password_hash       TEXT    NOT NULL DEFAULT '',
                first_name          TEXT    NOT NULL DEFAULT '',
                last_name           TEXT    NOT NULL DEFAULT '',
                email               TEXT    UNIQUE NOT NULL,
                mobile              TEXT    NOT NULL DEFAULT '',
                alt_mobile          TEXT    DEFAULT '',
                city                TEXT    NOT NULL DEFAULT '',
                state               TEXT    NOT NULL DEFAULT '',
                pincode             TEXT    NOT NULL DEFAULT '',
                trading_experience  TEXT    DEFAULT 'beginner',
                auth_provider       TEXT    DEFAULT 'local',
                google_id           TEXT    DEFAULT '',
                profile_picture     TEXT    DEFAULT '',
                is_active           INTEGER DEFAULT 1,
                is_admin            INTEGER DEFAULT 0,
                created_at          TEXT    DEFAULT (datetime('now')),
                updated_at          TEXT    DEFAULT (datetime('now')),
                last_login          TEXT
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id           TEXT    PRIMARY KEY,
                user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                ip_address   TEXT,
                user_agent   TEXT,
                created_at   TEXT    DEFAULT (datetime('now')),
                expires_at   TEXT    NOT NULL,
                is_valid     INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS rate_limit (
                ip_address     TEXT    NOT NULL,
                target         TEXT    DEFAULT 'login',
                attempts       INTEGER DEFAULT 0,
                first_attempt  TEXT    DEFAULT (datetime('now')),
                locked_until   TEXT,
                PRIMARY KEY (ip_address, target)
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_user   ON sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
            CREATE INDEX IF NOT EXISTS idx_users_email      ON users(email);
            CREATE INDEX IF NOT EXISTS idx_users_mobile     ON users(mobile);
        """)

        # Migration: add columns if they don't exist (for existing DBs)
        _migrate_google_columns(conn)


def _migrate_google_columns(conn):
    """Add Google OAuth columns to existing users table if missing."""
    try:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        migrations = [
            ("auth_provider", "TEXT DEFAULT 'local'"),
            ("google_id", "TEXT DEFAULT ''"),
            ("profile_picture", "TEXT DEFAULT ''"),
        ]
        for col_name, col_def in migrations:
            if col_name not in existing:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}")
        # Index on google_id if not exists
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_google_id ON users(google_id)")
    except Exception:
        pass  # Table doesn't exist yet — init_auth_db will create it


# ═══════════════════════════════════════════════════════════
#  USER CRUD
# ═══════════════════════════════════════════════════════════

def create_user(username: str, email: str, password_hash: str,
                first_name: str = "", last_name: str = "",
                mobile: str = "", alt_mobile: str = "",
                city: str = "", state: str = "", pincode: str = "",
                trading_experience: str = "beginner") -> int | None:
    """Insert a new user. Returns user ID or None on duplicate."""
    try:
        with _get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO users (username, email, password_hash,
                   first_name, last_name, mobile, alt_mobile,
                   city, state, pincode, trading_experience)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (username, email.lower().strip(), password_hash,
                 first_name, last_name, mobile, alt_mobile,
                 city, state, pincode, trading_experience),
            )
            return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def get_user_by_email(email: str) -> dict | None:
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?",
                           (email.lower().strip(),)).fetchone()
        return dict(row) if row else None


def get_user_by_username(username: str) -> dict | None:
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?",
                           (username,)).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict | None:
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?",
                           (user_id,)).fetchone()
        return dict(row) if row else None


def update_last_login(user_id: int):
    with _get_conn() as conn:
        conn.execute("UPDATE users SET last_login = datetime('now') WHERE id = ?",
                     (user_id,))


def email_exists(email: str) -> bool:
    with _get_conn() as conn:
        row = conn.execute("SELECT 1 FROM users WHERE email = ?",
                           (email.lower().strip(),)).fetchone()
        return row is not None


def username_exists(username: str) -> bool:
    with _get_conn() as conn:
        row = conn.execute("SELECT 1 FROM users WHERE username = ?",
                           (username,)).fetchone()
        return row is not None


def mobile_exists(mobile: str) -> bool:
    with _get_conn() as conn:
        row = conn.execute("SELECT 1 FROM users WHERE mobile = ?",
                           (mobile,)).fetchone()
        return row is not None


# ═══════════════════════════════════════════════════════════
#  GOOGLE OAUTH — USER FUNCTIONS
# ═══════════════════════════════════════════════════════════

def get_user_by_google_id(google_id: str) -> dict | None:
    """Find a user by their Google account ID."""
    if not google_id:
        return None
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE google_id = ?",
                           (google_id,)).fetchone()
        return dict(row) if row else None


def create_google_user(
    google_id: str, email: str,
    first_name: str = "", last_name: str = "",
    profile_picture: str = "",
) -> int | None:
    """
    Create a new user via Google Sign-In.
    Auto-generates a unique username from email prefix.
    Password hash is empty (Google-only auth).
    """
    try:
        # Generate username from email (e.g., rohit.tripathi@gmail.com → rohit_tripathi)
        base_username = email.split("@")[0].replace(".", "_").replace("-", "_")[:20]
        # Ensure valid chars only
        import re
        base_username = re.sub(r"[^a-zA-Z0-9_]", "", base_username)
        if len(base_username) < 3:
            base_username = "user_" + base_username

        username = base_username
        suffix = 1
        while username_exists(username):
            username = f"{base_username}_{suffix}"
            suffix += 1

        with _get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO users (
                       username, email, password_hash, first_name, last_name,
                       auth_provider, google_id, profile_picture
                   ) VALUES (?, ?, '', ?, ?, 'google', ?, ?)""",
                (username, email.lower().strip(), first_name, last_name,
                 google_id, profile_picture),
            )
            return cur.lastrowid
    except Exception as e:
        import logging
        logging.getLogger("auth.db").error("Failed to create Google user: %s", e)
        return None


def link_google_account(
    user_id: int, google_id: str, profile_picture: str = "",
):
    """Link a Google account to an existing user (email matched)."""
    with _get_conn() as conn:
        conn.execute(
            """UPDATE users SET google_id = ?, profile_picture = ?,
                   auth_provider = CASE WHEN auth_provider = 'local' THEN 'both' ELSE auth_provider END,
                   updated_at = datetime('now')
               WHERE id = ?""",
            (google_id, profile_picture, user_id),
        )


# ═══════════════════════════════════════════════════════════
#  SESSION MANAGEMENT
# ═══════════════════════════════════════════════════════════

def create_session(user_id: int, ip_address: str = "", user_agent: str = "") -> str:
    """Create a new session token. Returns the token UUID."""
    token = str(uuid.uuid4())
    expires = (datetime.utcnow() + timedelta(hours=SESSION_LIFETIME_HOURS)).isoformat()
    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO sessions (id, user_id, ip_address, user_agent, expires_at)
               VALUES (?, ?, ?, ?, ?)""",
            (token, user_id, ip_address, user_agent[:500], expires),
        )
    return token


def validate_session(token: str) -> dict | None:
    """
    Returns user dict if session is valid and not expired. Otherwise None.
    Also invalidates expired sessions opportunistically.
    """
    if not token:
        return None
    with _get_conn() as conn:
        conn.execute(
            "UPDATE sessions SET is_valid = 0 WHERE expires_at < datetime('now')"
        )
        row = conn.execute(
            """SELECT s.*, u.id as uid, u.username, u.email,
                      u.first_name, u.last_name,
                      u.is_active, u.is_admin
               FROM sessions s
               JOIN users u ON s.user_id = u.id
               WHERE s.id = ? AND s.is_valid = 1
                 AND s.expires_at > datetime('now')
                 AND u.is_active = 1""",
            (token,),
        ).fetchone()
        if row:
            return {
                "user_id": row["uid"],
                "username": row["username"],
                "email": row["email"],
                "full_name": f"{row['first_name']} {row['last_name']}".strip(),
                "first_name": row["first_name"],
                "last_name": row["last_name"],
                "is_admin": bool(row["is_admin"]),
                "session_id": token,
            }
    return None


def invalidate_session(token: str):
    """Logout — mark session as invalid."""
    with _get_conn() as conn:
        conn.execute("UPDATE sessions SET is_valid = 0 WHERE id = ?", (token,))


def invalidate_all_sessions(user_id: int):
    """Force-logout from all devices."""
    with _get_conn() as conn:
        conn.execute("UPDATE sessions SET is_valid = 0 WHERE user_id = ?", (user_id,))


# ═══════════════════════════════════════════════════════════
#  RATE LIMITING (brute-force protection)
# ═══════════════════════════════════════════════════════════

def check_rate_limit(ip_address: str, target: str = "login") -> tuple[bool, int]:
    """Returns (is_allowed, seconds_remaining_if_locked)."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM rate_limit WHERE ip_address = ? AND target = ?",
            (ip_address, target),
        ).fetchone()

        if not row:
            return True, 0

        row = dict(row)

        if row["locked_until"]:
            locked_until = datetime.fromisoformat(row["locked_until"])
            if datetime.utcnow() < locked_until:
                remaining = int((locked_until - datetime.utcnow()).total_seconds())
                return False, max(remaining, 0)
            else:
                conn.execute(
                    """UPDATE rate_limit SET attempts = 0, locked_until = NULL,
                       first_attempt = datetime('now')
                       WHERE ip_address = ? AND target = ?""",
                    (ip_address, target),
                )
                return True, 0

        if row["attempts"] >= MAX_FAILED_ATTEMPTS:
            first = datetime.fromisoformat(row["first_attempt"])
            if (datetime.utcnow() - first).total_seconds() < LOCKOUT_MINUTES * 60:
                lock_time = (datetime.utcnow() + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
                conn.execute(
                    "UPDATE rate_limit SET locked_until = ? WHERE ip_address = ? AND target = ?",
                    (lock_time, ip_address, target),
                )
                return False, LOCKOUT_MINUTES * 60
            else:
                conn.execute(
                    """UPDATE rate_limit SET attempts = 0, locked_until = NULL,
                       first_attempt = datetime('now')
                       WHERE ip_address = ? AND target = ?""",
                    (ip_address, target),
                )
                return True, 0

        return True, 0


def record_failed_attempt(ip_address: str, target: str = "login"):
    with _get_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM rate_limit WHERE ip_address = ? AND target = ?",
            (ip_address, target),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE rate_limit SET attempts = attempts + 1
                   WHERE ip_address = ? AND target = ?""",
                (ip_address, target),
            )
        else:
            conn.execute(
                "INSERT INTO rate_limit (ip_address, target, attempts) VALUES (?, ?, 1)",
                (ip_address, target),
            )


def reset_rate_limit(ip_address: str, target: str = "login"):
    with _get_conn() as conn:
        conn.execute(
            "DELETE FROM rate_limit WHERE ip_address = ? AND target = ?",
            (ip_address, target),
        )
