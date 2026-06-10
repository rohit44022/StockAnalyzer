"""
notes_routes.py — Flask Blueprint for the floating Quick Notes widget.

Routes:
  GET  /api/notes        → fetch the authenticated user's notes
  POST /api/notes        → upsert the notes blob (body: {"content": str})
  POST /api/notes/clear  → delete the notes (called on logout)

Auth: all endpoints require an authenticated session. Notes are scoped
to user_id — no cross-user leakage.

Isolation: this blueprint depends only on `notes.db` and the auth context.
It does NOT touch any other module's data.
"""

from __future__ import annotations
import sys
import os
from flask import Blueprint, jsonify, request, g

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from notes.db import get_notes, set_notes, clear_notes


notes_bp = Blueprint("notes", __name__)


def _uid() -> int | None:
    """Resolve the current user id from auth middleware context."""
    if hasattr(g, "user") and g.user:
        return g.user.get("id")
    return None


@notes_bp.route("/api/notes", methods=["GET"])
def api_notes_get():
    uid = _uid()
    if not uid:
        return jsonify({"error": "auth required"}), 401
    return jsonify({"content": get_notes(uid)})


@notes_bp.route("/api/notes", methods=["POST"])
def api_notes_save():
    uid = _uid()
    if not uid:
        return jsonify({"error": "auth required"}), 401
    data = request.get_json(silent=True) or {}
    content = data.get("content", "")
    if not isinstance(content, str):
        return jsonify({"error": "content must be a string"}), 400
    set_notes(uid, content)
    return jsonify({"status": "ok"})


@notes_bp.route("/api/notes/clear", methods=["POST"])
def api_notes_clear():
    uid = _uid()
    if not uid:
        return jsonify({"error": "auth required"}), 401
    clear_notes(uid)
    return jsonify({"status": "ok"})
