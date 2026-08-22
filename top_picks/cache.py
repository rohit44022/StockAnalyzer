"""
Persistent cache for run_triple_analysis() results, used by Top Picks Stage 4.

Design goals (in priority order):
  1. Correctness — a cache hit MUST equal what run_triple_analysis would
     have returned right now. Any data change or indicator-code change
     invalidates automatically. TTL is a belt-and-braces on top.
  2. Safety — failures never propagate. Read/write errors → cache miss,
     fall through to live compute. Cache is invisible to correctness.
  3. Surgical scope — used only by top_picks.engine. Other callers of
     run_triple_analysis (portfolio, /analyze, backtests, PA scanner)
     are untouched.

Kill switch: set TRIPLE_CACHE_ENABLED = False → every read is a miss, no
writes; instant revert to pre-cache behaviour without a restart-time
migration.
"""
from __future__ import annotations

import hashlib
import os
import pickle
import time
from pathlib import Path
from typing import Optional

from bb_squeeze.config import CACHE_DIR

# ─────────────────────────────────────────────────────────────────────
#  Configuration
# ─────────────────────────────────────────────────────────────────────

TRIPLE_CACHE_ENABLED = True

# 24-hour TTL. User's explicit requirement — "invalidate after 24 hours".
TTL_SECONDS = 24 * 60 * 60

CACHE_SUBDIR = Path(CACHE_DIR) / "triple_analysis"

# Files whose mtime is folded into the cache key. If any of these change,
# every cache entry invalidates automatically — you never have to remember
# to bump a version.
_CODE_FILES = [
    "bb_squeeze/indicators.py",
    "bb_squeeze/signals.py",
    "bb_squeeze/strategies.py",
    "hybrid_pa_engine.py",
    "technical_analysis/indicators.py",
]

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CODE_VERSION: Optional[str] = None  # computed lazily on first key request


# ─────────────────────────────────────────────────────────────────────
#  Internal helpers
# ─────────────────────────────────────────────────────────────────────

def _code_version() -> str:
    """Hash of implementation-file mtimes. Any code edit → new value."""
    global _CODE_VERSION
    if _CODE_VERSION is not None:
        return _CODE_VERSION
    parts = []
    for rel in _CODE_FILES:
        p = _PROJECT_ROOT / rel
        try:
            parts.append(f"{rel}:{int(p.stat().st_mtime)}")
        except OSError:
            parts.append(f"{rel}:missing")
    _CODE_VERSION = hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]
    return _CODE_VERSION


def _make_key(ticker: str, csv_path: str, capital: float) -> Optional[str]:
    """Deterministic cache key. Returns None if the CSV can't be stat'd
    (in which case we skip caching — data fingerprint is required)."""
    try:
        st = os.stat(csv_path)
    except OSError:
        return None
    raw = (
        f"{ticker}|mtime={int(st.st_mtime)}|size={st.st_size}"
        f"|cap={int(capital)}|code={_code_version()}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _path_for(key: str) -> Path:
    return CACHE_SUBDIR / f"{key}.pkl"


def _ensure_dir() -> bool:
    try:
        CACHE_SUBDIR.mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        return False


# ─────────────────────────────────────────────────────────────────────
#  Public API
# ─────────────────────────────────────────────────────────────────────

def read(ticker: str, csv_path: str, capital: float) -> Optional[dict]:
    """Return the cached triple-analysis dict, or None on any miss.

    A miss is returned when: caching disabled, no CSV fingerprint,
    file absent, TTL expired, or unpickle fails. Never raises.
    """
    if not TRIPLE_CACHE_ENABLED:
        return None
    key = _make_key(ticker, csv_path, capital)
    if key is None:
        return None
    fp = _path_for(key)
    try:
        st = fp.stat()
    except OSError:
        return None
    if (time.time() - st.st_mtime) > TTL_SECONDS:
        return None
    try:
        with fp.open("rb") as f:
            return pickle.load(f)
    except Exception:
        # Corrupt or unreadable → treat as miss.
        return None


def write(ticker: str, csv_path: str, capital: float, result: dict) -> None:
    """Persist a triple-analysis result. Silent no-op on any failure.

    Atomic via temp-write + rename. Skips writing errored results.
    """
    if not TRIPLE_CACHE_ENABLED:
        return
    if not isinstance(result, dict) or "error" in result:
        return
    key = _make_key(ticker, csv_path, capital)
    if key is None:
        return
    if not _ensure_dir():
        return
    fp = _path_for(key)
    tmp = fp.with_suffix(f".pkl.tmp.{os.getpid()}.{time.time_ns()}")
    try:
        with tmp.open("wb") as f:
            pickle.dump(result, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, fp)  # atomic on POSIX
    except Exception:
        # Clean up temp on failure; never propagate cache errors.
        try:
            tmp.unlink()
        except OSError:
            pass


def clear_all() -> int:
    """Delete every cache file. Returns count removed. Never raises."""
    if not CACHE_SUBDIR.exists():
        return 0
    removed = 0
    for f in CACHE_SUBDIR.glob("*.pkl"):
        try:
            f.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def stats() -> dict:
    """Snapshot for the UI: entry count, total bytes, oldest age."""
    if not CACHE_SUBDIR.exists():
        return {"count": 0, "bytes": 0, "oldest_age_seconds": 0}
    count = 0
    total = 0
    oldest_mtime = None
    now = time.time()
    for f in CACHE_SUBDIR.glob("*.pkl"):
        try:
            st = f.stat()
            count += 1
            total += st.st_size
            if oldest_mtime is None or st.st_mtime < oldest_mtime:
                oldest_mtime = st.st_mtime
        except OSError:
            continue
    return {
        "count": count,
        "bytes": total,
        "oldest_age_seconds": int(now - oldest_mtime) if oldest_mtime else 0,
        "ttl_seconds": TTL_SECONDS,
        "enabled": TRIPLE_CACHE_ENABLED,
    }
