"""
Brooks System — Flask Routes
==============================
Separate blueprint for the Al Brooks top-5 BUY / SELL scanner.
"""

from __future__ import annotations

import sys, os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from flask import Blueprint, render_template, jsonify, request
from bb_squeeze.config import CSV_DIR

brooks_bp = Blueprint("brooks", __name__)


@brooks_bp.route("/brooks")
def brooks_page():
    return render_template("brooks.html")


@brooks_bp.route("/api/brooks/scan")
def api_brooks_scan():
    """Run full scan and return top-5 BUY + top-5 SELL picks with reasoning."""
    from brooks.analyzer import scan_and_rank

    limit = min(int(request.args.get("limit", "5")), 20)
    workers = min(int(request.args.get("workers", "16")), 20)

    result = scan_and_rank(CSV_DIR, max_workers=workers, limit=limit)
    return jsonify(result)
