"""
Theme support — single dark admin dashboard theme.
Bootswatch removed; plain Bootstrap 5.3 + custom dark theme via theme.css.
"""
from __future__ import annotations

import os

from flask import Blueprint, jsonify, request

BOOTSTRAP_VERSION = "5.3.3"
COOKIE_NAME = "sc_theme"


def _bootstrap_css_url() -> str:
    return f"https://cdn.jsdelivr.net/npm/bootstrap@{BOOTSTRAP_VERSION}/dist/css/bootstrap.min.css"


theme_bp = Blueprint("theme", __name__)


@theme_bp.route("/theme/set", methods=["POST"])
def set_theme():
    return jsonify(ok=True, slug="dark", mode="dark")


@theme_bp.route("/theme/list")
def list_themes():
    return jsonify(themes=[], active={"slug": "dark", "label": "Dark", "mode": "dark"})


_THEME_CSS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "static", "css", "theme.css"
)


def _theme_assets_version() -> str:
    try:
        return str(int(os.path.getmtime(_THEME_CSS_PATH)))
    except OSError:
        return "0"


def inject_theme():
    """Flask context processor — exposes theme info to all templates."""
    return {
        "theme_slug": "dark",
        "theme_mode": "dark",
        "theme_label": "Dark",
        "bootstrap_css_url": _bootstrap_css_url(),
        "bootswatch_themes": [],
        "theme_assets_version": _theme_assets_version(),
    }
