"""
Bootswatch theme support.

Single source of truth for theme metadata + cookie persistence.
Charts and semantic bull/bear colors are intentionally NOT scoped to
this system — they live in template-level CSS vars and JS literals.
"""
from __future__ import annotations

import os

from flask import Blueprint, jsonify, make_response, request

# Pinned Bootswatch + Bootstrap versions. Keep in sync — Bootswatch
# major.minor must match Bootstrap.
BOOTSWATCH_VERSION = "5.3.3"
BOOTSTRAP_VERSION = "5.3.3"

DEFAULT_THEME = "darkly"  # preserves current dark UX
COOKIE_NAME = "sc_theme"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # 1 year

# slug, label, mode (light|dark)
BOOTSWATCH_THEMES: list[dict[str, str]] = [
    {"slug": "default",   "label": "Bootstrap (default)", "mode": "light"},
    # Light themes
    {"slug": "cerulean",  "label": "Cerulean",  "mode": "light"},
    {"slug": "cosmo",     "label": "Cosmo",     "mode": "light"},
    {"slug": "flatly",    "label": "Flatly",    "mode": "light"},
    {"slug": "journal",   "label": "Journal",   "mode": "light"},
    {"slug": "litera",    "label": "Litera",    "mode": "light"},
    {"slug": "lumen",     "label": "Lumen",     "mode": "light"},
    {"slug": "lux",       "label": "Lux",       "mode": "light"},
    {"slug": "materia",   "label": "Materia",   "mode": "light"},
    {"slug": "minty",     "label": "Minty",     "mode": "light"},
    {"slug": "morph",     "label": "Morph",     "mode": "light"},
    {"slug": "pulse",     "label": "Pulse",     "mode": "light"},
    {"slug": "sandstone", "label": "Sandstone", "mode": "light"},
    {"slug": "simplex",   "label": "Simplex",   "mode": "light"},
    {"slug": "sketchy",   "label": "Sketchy",   "mode": "light"},
    {"slug": "spacelab",  "label": "Spacelab",  "mode": "light"},
    {"slug": "united",    "label": "United",    "mode": "light"},
    {"slug": "yeti",      "label": "Yeti",      "mode": "light"},
    {"slug": "zephyr",    "label": "Zephyr",    "mode": "light"},
    # Dark themes
    {"slug": "cyborg",    "label": "Cyborg",    "mode": "dark"},
    {"slug": "darkly",    "label": "Darkly",    "mode": "dark"},
    {"slug": "quartz",    "label": "Quartz",    "mode": "dark"},
    {"slug": "slate",     "label": "Slate",     "mode": "dark"},
    {"slug": "solar",     "label": "Solar",     "mode": "dark"},
    {"slug": "superhero", "label": "Superhero", "mode": "dark"},
    {"slug": "vapor",     "label": "Vapor",     "mode": "dark"},
]

_BY_SLUG = {t["slug"]: t for t in BOOTSWATCH_THEMES}


def _bootstrap_css_url(slug: str) -> str:
    if slug == "default" or slug not in _BY_SLUG:
        return f"https://cdn.jsdelivr.net/npm/bootstrap@{BOOTSTRAP_VERSION}/dist/css/bootstrap.min.css"
    return f"https://cdn.jsdelivr.net/npm/bootswatch@{BOOTSWATCH_VERSION}/dist/{slug}/bootstrap.min.css"


def get_active_theme() -> dict[str, str]:
    """Read the active theme from the request cookie. Falls back to default."""
    slug = request.cookies.get(COOKIE_NAME, DEFAULT_THEME)
    return _BY_SLUG.get(slug, _BY_SLUG[DEFAULT_THEME])


theme_bp = Blueprint("theme", __name__)


@theme_bp.route("/theme/set", methods=["POST"])
def set_theme():
    """Persist theme choice in a cookie. Body: {"slug": "darkly"}."""
    data = request.get_json(silent=True) or {}
    slug = (data.get("slug") or "").strip().lower()
    if slug not in _BY_SLUG:
        return jsonify(ok=False, error="unknown theme"), 400
    resp = make_response(jsonify(ok=True, slug=slug, mode=_BY_SLUG[slug]["mode"]))
    resp.set_cookie(
        COOKIE_NAME, slug,
        max_age=COOKIE_MAX_AGE,
        httponly=False,  # allow JS to read for instant rehydration
        samesite="Lax",
        path="/",
    )
    return resp


@theme_bp.route("/theme/list")
def list_themes():
    return jsonify(themes=BOOTSWATCH_THEMES, active=get_active_theme())


_THEME_CSS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "static", "css", "theme.css"
)


def _theme_assets_version() -> str:
    """Cache-buster for theme.css — file mtime as integer."""
    try:
        return str(int(os.path.getmtime(_THEME_CSS_PATH)))
    except OSError:
        return "0"


def inject_theme():
    """Flask context processor — exposes theme info to all templates."""
    active = get_active_theme()
    return {
        "theme_slug": active["slug"],
        "theme_mode": active["mode"],
        "theme_label": active["label"],
        "bootstrap_css_url": _bootstrap_css_url(active["slug"]),
        "bootswatch_themes": BOOTSWATCH_THEMES,
        "theme_assets_version": _theme_assets_version(),
    }
