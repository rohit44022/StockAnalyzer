"""
auth/engine.py — Core authentication logic.

Handles:
  - Password hashing (bcrypt with PBKDF2 fallback)
  - Signup with user-chosen username + password + full profile
  - Login with username or email + password
  - Input validation & sanitisation
"""
from __future__ import annotations

import re
import secrets
import hashlib
import hmac

try:
    import bcrypt
    _USE_BCRYPT = True
except ImportError:
    _USE_BCRYPT = False

from auth.db import (
    create_user, get_user_by_email, get_user_by_username,
    get_user_by_id, update_last_login,
    create_session, invalidate_session, invalidate_all_sessions,
    email_exists, username_exists, mobile_exists,
    check_rate_limit, record_failed_attempt, reset_rate_limit,
)


# ═══════════════════════════════════════════════════════════
#  PASSWORD HASHING
# ═══════════════════════════════════════════════════════════

def hash_password(password: str) -> str:
    if _USE_BCRYPT:
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(12)).decode("utf-8")
    else:
        salt = secrets.token_hex(16)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 260_000)
        return f"pbkdf2:{salt}:{dk.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    if not hashed or not password:
        return False
    if hashed.startswith("pbkdf2:"):
        parts = hashed.split(":")
        if len(parts) != 3:
            return False
        _, salt, stored_hex = parts
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 260_000)
        return hmac.compare_digest(dk.hex(), stored_hex)
    elif _USE_BCRYPT:
        try:
            return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
        except Exception:
            return False
    return False


# ═══════════════════════════════════════════════════════════
#  INPUT VALIDATION
# ═══════════════════════════════════════════════════════════

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,30}$")
_MOBILE_RE = re.compile(r"^[6-9]\d{9}$")
_PINCODE_RE = re.compile(r"^\d{6}$")

TRADING_EXPERIENCE_OPTIONS = [
    "beginner",         # < 1 year
    "intermediate",     # 1-3 years
    "experienced",      # 3-5 years
    "expert",           # 5+ years
]


def validate_email(email: str) -> str | None:
    if not email:
        return None
    email = email.strip().lower()
    if len(email) > 254:
        return None
    if not _EMAIL_RE.match(email):
        return None
    return email


def validate_username(username: str) -> str | None:
    if not username:
        return None
    username = username.strip()
    if not _USERNAME_RE.match(username):
        return None
    return username


def validate_password_strength(password: str) -> tuple[bool, str]:
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    if not re.search(r"[A-Z]", password):
        return False, "Must contain at least one uppercase letter"
    if not re.search(r"[a-z]", password):
        return False, "Must contain at least one lowercase letter"
    if not re.search(r"[0-9]", password):
        return False, "Must contain at least one digit"
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-+=\[\]\\;'/`~]", password):
        return False, "Must contain at least one special character"
    return True, "OK"


def _sanitize_name(name: str) -> str:
    if not name:
        return ""
    name = re.sub(r"<[^>]*>", "", name)
    name = re.sub(r"[^a-zA-Z\s.\-']", "", name)
    return name.strip()[:50]


def validate_mobile(mobile: str) -> str | None:
    if not mobile:
        return None
    mobile = re.sub(r"[\s\-+]", "", mobile)
    if mobile.startswith("91") and len(mobile) == 12:
        mobile = mobile[2:]
    if not _MOBILE_RE.match(mobile):
        return None
    return mobile


def validate_pincode(pincode: str) -> str | None:
    if not pincode:
        return None
    pincode = pincode.strip()
    if not _PINCODE_RE.match(pincode):
        return None
    return pincode


# ═══════════════════════════════════════════════════════════
#  SIGNUP
# ═══════════════════════════════════════════════════════════

def signup(
    username: str, password: str, confirm_password: str,
    first_name: str, last_name: str, email: str,
    mobile: str, alt_mobile: str = "",
    city: str = "", state: str = "", pincode: str = "",
    trading_experience: str = "beginner",
) -> dict:
    """
    Register a new user with user-chosen username and password.
    Returns {success, user_id, username, error}
    """
    # — Username —
    clean_username = validate_username(username)
    if not clean_username:
        return {"success": False, "error": "Username must be 3-30 characters (letters, digits, underscores only)"}
    if username_exists(clean_username):
        return {"success": False, "error": "This username is already taken. Please choose another."}

    # — Password —
    if not password:
        return {"success": False, "error": "Password is required"}
    if password != confirm_password:
        return {"success": False, "error": "Passwords do not match"}
    pw_ok, pw_msg = validate_password_strength(password)
    if not pw_ok:
        return {"success": False, "error": pw_msg}

    # — First name —
    first_name = _sanitize_name(first_name)
    if not first_name:
        return {"success": False, "error": "First name is required"}

    # — Last name —
    last_name = _sanitize_name(last_name)
    if not last_name:
        return {"success": False, "error": "Last name is required"}

    # — Email —
    clean_email = validate_email(email)
    if not clean_email:
        return {"success": False, "error": "Please enter a valid email address"}
    if email_exists(clean_email):
        return {"success": False, "error": "An account with this email already exists"}

    # — Mobile —
    clean_mobile = validate_mobile(mobile)
    if not clean_mobile:
        return {"success": False, "error": "Please enter a valid 10-digit Indian mobile number"}
    if mobile_exists(clean_mobile):
        return {"success": False, "error": "An account with this mobile number already exists"}

    # — Alt mobile (optional) —
    clean_alt = ""
    if alt_mobile and alt_mobile.strip():
        clean_alt = validate_mobile(alt_mobile) or ""

    # — Pincode —
    clean_pincode = validate_pincode(pincode)
    if not clean_pincode:
        return {"success": False, "error": "Please enter a valid 6-digit pincode"}

    # — City & State —
    city = re.sub(r"<[^>]*>", "", city).strip()[:50]
    state = re.sub(r"<[^>]*>", "", state).strip()[:50]
    if not city:
        return {"success": False, "error": "City is required"}
    if not state:
        return {"success": False, "error": "State is required"}

    # — Trading Experience —
    if trading_experience not in TRADING_EXPERIENCE_OPTIONS:
        trading_experience = "beginner"

    # — Create user —
    pw_hash = hash_password(password)
    user_id = create_user(
        username=clean_username,
        email=clean_email,
        password_hash=pw_hash,
        first_name=first_name,
        last_name=last_name,
        mobile=clean_mobile,
        alt_mobile=clean_alt,
        city=city,
        state=state,
        pincode=clean_pincode,
        trading_experience=trading_experience,
    )
    if user_id is None:
        return {"success": False, "error": "Could not create account. Username or email may already be taken."}

    return {
        "success": True,
        "user_id": user_id,
        "username": clean_username,
    }


# ═══════════════════════════════════════════════════════════
#  LOGIN
# ═══════════════════════════════════════════════════════════

def login(identifier: str, password: str, ip_address: str = "",
          user_agent: str = "") -> dict:
    """
    Login with username or email + password.
    Returns {success, token, user, error, locked_seconds}
    """
    if not identifier or not password:
        return {"success": False, "error": "Username/email and password are required"}

    allowed, remaining = check_rate_limit(ip_address)
    if not allowed:
        return {
            "success": False,
            "error": f"Too many failed attempts. Try again in {remaining // 60 + 1} minutes.",
            "locked_seconds": remaining,
        }

    identifier = identifier.strip()
    if "@" in identifier:
        user = get_user_by_email(identifier)
    else:
        user = get_user_by_username(identifier)

    if not user:
        record_failed_attempt(ip_address)
        return {"success": False, "error": "Invalid credentials"}

    if not user["is_active"]:
        return {"success": False, "error": "Account is deactivated. Contact support."}

    if not verify_password(password, user["password_hash"]):
        record_failed_attempt(ip_address)
        return {"success": False, "error": "Invalid credentials"}

    # Success
    reset_rate_limit(ip_address)
    update_last_login(user["id"])
    token = create_session(user["id"], ip_address, user_agent)

    return {
        "success": True,
        "token": token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "full_name": f"{user['first_name']} {user['last_name']}".strip(),
            "is_admin": bool(user["is_admin"]),
        },
    }


# ═══════════════════════════════════════════════════════════
#  LOGOUT
# ═══════════════════════════════════════════════════════════

def logout(token: str):
    invalidate_session(token)


def logout_all(user_id: int):
    invalidate_all_sessions(user_id)
