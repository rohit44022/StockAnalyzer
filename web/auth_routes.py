"""
web/auth_routes.py — Flask blueprint for authentication endpoints.

Routes:
  GET  /auth/login                → Login page
  GET  /auth/signup               → Signup page
  POST /auth/login                → Process login form
  POST /auth/signup               → Process signup form
  GET  /auth/logout               → Logout
  GET  /auth/api/check-username   → Check username availability (AJAX)
  GET  /auth/api/pincode/<pin>    → Pincode → city/state lookup (AJAX)
  GET  /auth/api/me               → Current user info (API)
"""
from __future__ import annotations

import requests as http_requests

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    jsonify, make_response, session, g,
)

from auth.engine import login, signup, logout, TRADING_EXPERIENCE_OPTIONS
from auth.middleware import (
    set_session_cookie, clear_session_cookie, SESSION_COOKIE,
    generate_csrf_token, validate_csrf_token,
)
from auth.db import check_rate_limit, validate_session, username_exists

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


# ═══════════════════════════════════════════════════════════
#  LOGIN PAGE
# ═══════════════════════════════════════════════════════════

@auth_bp.route("/login", methods=["GET"])
def login_page():
    token = request.cookies.get(SESSION_COOKIE)
    if token and validate_session(token):
        return redirect("/")

    error = request.args.get("error", "")
    success = request.args.get("success", "")
    next_url = request.args.get("next", "/")
    csrf = generate_csrf_token()

    return render_template(
        "login.html",
        error=error,
        success=success,
        next_url=next_url,
        csrf_token=csrf,
        show_signup=False,
        experience_options=TRADING_EXPERIENCE_OPTIONS,
    )


@auth_bp.route("/signup", methods=["GET"])
def signup_page():
    token = request.cookies.get(SESSION_COOKIE)
    if token and validate_session(token):
        return redirect("/")

    error = request.args.get("error", "")
    csrf = generate_csrf_token()

    return render_template(
        "login.html",
        error=error,
        success="",
        next_url="/",
        csrf_token=csrf,
        show_signup=True,
        experience_options=TRADING_EXPERIENCE_OPTIONS,
    )


# ═══════════════════════════════════════════════════════════
#  LOGIN HANDLER
# ═══════════════════════════════════════════════════════════

@auth_bp.route("/login", methods=["POST"])
def do_login():
    if not validate_csrf_token():
        return redirect(url_for("auth.login_page", error="Invalid request. Please try again."))

    identifier = request.form.get("identifier", "").strip()
    password = request.form.get("password", "").strip()
    remember = request.form.get("remember") == "on"
    next_url = request.form.get("next", "/")

    if not identifier or not password:
        return redirect(url_for("auth.login_page", error="Please fill in all fields.", next=next_url))

    ip = request.remote_addr or "unknown"
    ua = request.headers.get("User-Agent", "")

    result = login(identifier, password, ip_address=ip, user_agent=ua)

    if not result["success"]:
        return redirect(url_for("auth.login_page", error=result["error"], next=next_url))

    resp = make_response(redirect(next_url or "/"))
    set_session_cookie(resp, result["token"], remember=remember)
    return resp


# ═══════════════════════════════════════════════════════════
#  SIGNUP HANDLER
# ═══════════════════════════════════════════════════════════

@auth_bp.route("/signup", methods=["POST"])
def do_signup():
    if not validate_csrf_token():
        return redirect(url_for("auth.signup_page", error="Invalid request. Please try again."))

    ip = request.remote_addr or "unknown"
    allowed, remaining = check_rate_limit(ip, target="signup")
    if not allowed:
        return redirect(url_for("auth.signup_page",
                                error=f"Too many signup attempts. Try again in {remaining // 60 + 1} minutes."))

    result = signup(
        username=request.form.get("username", "").strip(),
        password=request.form.get("password", ""),
        confirm_password=request.form.get("confirm_password", ""),
        first_name=request.form.get("first_name", "").strip(),
        last_name=request.form.get("last_name", "").strip(),
        email=request.form.get("email", "").strip(),
        mobile=request.form.get("mobile", "").strip(),
        alt_mobile=request.form.get("alt_mobile", "").strip(),
        city=request.form.get("city", "").strip(),
        state=request.form.get("state", "").strip(),
        pincode=request.form.get("pincode", "").strip(),
        trading_experience=request.form.get("trading_experience", "beginner"),
    )

    if not result["success"]:
        return redirect(url_for("auth.signup_page", error=result["error"]))

    return redirect(url_for("auth.login_page",
                            success=f"Account created successfully! Login with username: {result['username']}"))


# ═══════════════════════════════════════════════════════════
#  AJAX: Username availability check
# ═══════════════════════════════════════════════════════════

@auth_bp.route("/api/check-username", methods=["GET"])
def check_username():
    u = request.args.get("username", "").strip()
    if not u or len(u) < 3:
        return jsonify({"available": False, "msg": "Minimum 3 characters"})
    if username_exists(u):
        return jsonify({"available": False, "msg": "Already taken"})
    return jsonify({"available": True, "msg": "Available"})


# ═══════════════════════════════════════════════════════════
#  AJAX: Pincode → City / State lookup (India Post API)
# ═══════════════════════════════════════════════════════════

@auth_bp.route("/api/pincode/<pincode>", methods=["GET"])
def pincode_lookup(pincode):
    """Lookup city and state from Indian pincode using public API."""
    if not pincode or len(pincode) != 6 or not pincode.isdigit():
        return jsonify({"success": False, "error": "Invalid pincode"})

    try:
        resp = http_requests.get(
            f"https://api.postalpincode.in/pincode/{pincode}",
            timeout=5,
        )
        data = resp.json()
        if data and data[0].get("Status") == "Success":
            po = data[0]["PostOffice"][0]
            return jsonify({
                "success": True,
                "city": po.get("District", ""),
                "state": po.get("State", ""),
                "area": po.get("Name", ""),
            })
        return jsonify({"success": False, "error": "Pincode not found"})
    except Exception:
        return jsonify({"success": False, "error": "Lookup service unavailable"})


# ═══════════════════════════════════════════════════════════
#  LOGOUT
# ═══════════════════════════════════════════════════════════

@auth_bp.route("/logout", methods=["GET", "POST"])
def do_logout():
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        logout(token)

    resp = make_response(redirect(url_for("auth.login_page")))
    clear_session_cookie(resp)
    session.clear()
    return resp


# ═══════════════════════════════════════════════════════════
#  API: Current User
# ═══════════════════════════════════════════════════════════

@auth_bp.route("/api/me", methods=["GET"])
def api_me():
    if not hasattr(g, "user") or not g.user:
        return jsonify({"authenticated": False}), 401
    return jsonify({"authenticated": True, "user": g.user})
