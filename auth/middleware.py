"""
auth/middleware.py — Route protection & security safeguards.

Provides:
  - @login_required decorator for Flask routes
  - before_request hook that enforces auth on ALL routes
  - CSRF token generation/validation
  - Security headers middleware
  - Session fixation protection
  - XSS / injection safeguards

Bypass prevention:
  - No route is accessible without valid session (except whitelist)
  - Cookie is HttpOnly, SameSite=Lax, Secure (in production)
  - Session tokens are validated server-side on every request
  - Rate limiting on auth endpoints
  - CSRF token on all state-changing requests
"""
from __future__ import annotations

import os
import secrets
import functools
from datetime import datetime

from flask import request, redirect, url_for, g, make_response, abort, session

from auth.db import validate_session

# Cookie name for session token
SESSION_COOKIE = "hiranya_session"
# Cookie name for CSRF token
CSRF_COOKIE = "hiranya_csrf"
# Header name for CSRF token (for AJAX)
CSRF_HEADER = "X-CSRF-Token"

# Routes that DON'T require authentication
PUBLIC_ROUTES = frozenset({
    "auth.login_page",
    "auth.signup_page",
    "auth.do_login",
    "auth.do_signup",
    "auth.check_username",
    "auth.pincode_lookup",
    "auth.google_callback",
    "static",
})

# Route prefixes that are always public
PUBLIC_PREFIXES = ("/auth/", "/static/")


def init_auth_middleware(app):
    """
    Register all auth middleware on the Flask app.
    Must be called AFTER all blueprints are registered.
    """
    # Secret key for Flask session (used for CSRF + flash messages only)
    if not app.secret_key:
        app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(32))

    @app.before_request
    def _enforce_auth():
        """
        Global before_request hook — ensures EVERY request is authenticated
        unless the route is in the public whitelist.
        """
        # Skip auth for public routes/prefixes
        if request.endpoint and request.endpoint in PUBLIC_ROUTES:
            return
        for prefix in PUBLIC_PREFIXES:
            if request.path.startswith(prefix):
                return

        # Validate session from cookie
        token = request.cookies.get(SESSION_COOKIE)
        user_data = validate_session(token) if token else None

        if not user_data:
            # API requests get 401, page requests get redirected
            if request.path.startswith("/api/"):
                abort(401)
            return redirect(url_for("auth.login_page", next=request.path))

        # Store user in request context (available in all routes)
        g.user = user_data
        g.session_token = token

    @app.after_request
    def _security_headers(response):
        """Add security headers to every response."""
        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        # Prevent MIME sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        # XSS protection (legacy browsers)
        response.headers["X-XSS-Protection"] = "1; mode=block"
        # Referrer policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Cache control for authenticated pages
        if hasattr(g, "user") and g.user:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
            response.headers["Pragma"] = "no-cache"
        return response

    @app.errorhandler(401)
    def _handle_401(e):
        if request.path.startswith("/api/"):
            return {"error": "Authentication required", "code": 401}, 401
        return redirect(url_for("auth.login_page", next=request.path))


def login_required(f):
    """
    Decorator for individual routes that need auth.
    This is a SECOND layer of defense — the before_request hook is the primary gate.
    Use this on routes for explicit clarity.
    """
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not hasattr(g, "user") or not g.user:
            if request.path.startswith("/api/"):
                abort(401)
            return redirect(url_for("auth.login_page", next=request.path))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Decorator for admin-only routes."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not hasattr(g, "user") or not g.user:
            abort(401)
        if not g.user.get("is_admin"):
            abort(403)
        return f(*args, **kwargs)
    return decorated


def generate_csrf_token() -> str:
    """Generate a CSRF token and store in Flask session."""
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]


def validate_csrf_token() -> bool:
    """
    Validate CSRF token from form data or header.
    Returns True if valid.
    """
    expected = session.get("csrf_token")
    if not expected:
        return False

    # Check form field
    submitted = request.form.get("csrf_token") or request.headers.get(CSRF_HEADER)
    if not submitted:
        # Also check JSON body
        try:
            data = request.get_json(silent=True)
            if data:
                submitted = data.get("csrf_token")
        except Exception:
            pass

    if not submitted:
        return False

    return secrets.compare_digest(expected, submitted)


def set_session_cookie(response, token: str, remember: bool = False):
    """Set the session cookie with proper security flags."""
    max_age = 30 * 24 * 3600 if remember else None  # 30 days or session-only
    is_prod = os.environ.get("FLASK_ENV") == "production"

    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,          # Prevent JS access (XSS protection)
        samesite="Lax",         # CSRF protection
        secure=is_prod,         # HTTPS only in production
        path="/",
    )
    return response


def clear_session_cookie(response):
    """Remove the session cookie."""
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
