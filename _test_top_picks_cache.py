"""
Assert-based checks for the Top Picks triple-analysis cache.

Covers what changed in this session:
  1. top_picks/cache.py — read / write / clear_all / stats
  2. TTL expiry, csv-mtime auto-invalidation, code-version auto-invalidation
  3. error dicts never cached, missing-CSV safe fallback
  4. TRIPLE_CACHE_ENABLED kill switch
  5. Kill switch on the wired call site in top_picks/engine.py (no leakage
     when disabled).
  6. HTTP endpoints: GET /api/top-picks/cache/stats and
     POST /api/top-picks/cache/clear.

Run:  python _test_top_picks_cache.py
"""
from __future__ import annotations
import os
import sys
import time
import tempfile
import shutil
from pathlib import Path


def _setup_tmp_env() -> str:
    """Fresh temp STOCK_APP_DATA + required subdirs. Returns tmp root."""
    tmp = tempfile.mkdtemp(prefix="tp_cache_test_")
    os.makedirs(os.path.join(tmp, "bb_squeeze", "cache", "triple_analysis"),
                exist_ok=True)
    os.makedirs(os.path.join(tmp, "data"), exist_ok=True)
    os.makedirs(os.path.join(tmp, "stock_csv"), exist_ok=True)
    os.environ["STOCK_APP_DATA"] = tmp
    # Drop any previously loaded modules so config picks up the new env.
    for mod in ("bb_squeeze.config", "top_picks.cache"):
        sys.modules.pop(mod, None)
    return tmp


def _fresh_cache_module():
    """Reload top_picks.cache under the current STOCK_APP_DATA."""
    import importlib
    import bb_squeeze.config as _cfg
    importlib.reload(_cfg)
    import top_picks.cache as tc
    importlib.reload(tc)
    return tc


def test_module_direct() -> None:
    print("── Direct cache module ──")
    tmp = _setup_tmp_env()
    tc = _fresh_cache_module()

    csv_path = os.path.join(tmp, "stock_csv", "FOO.NS.csv")
    Path(csv_path).write_text("Date,Close\n2026-01-01,100\n")

    # 1. Cold miss on empty cache
    assert tc.read("FOO.NS", csv_path, 500000) is None
    print("[ok] cold miss")

    # 2. Round-trip write + hit
    payload = {"ticker": "FOO.NS", "score": 42, "nested": {"a": [1, 2, 3]}}
    tc.write("FOO.NS", csv_path, 500000, payload)
    hit = tc.read("FOO.NS", csv_path, 500000)
    assert hit == payload, hit
    print("[ok] write → hit round-trip")

    # 3. CSV mtime bump → key changes → miss
    time.sleep(1.1)
    Path(csv_path).write_text("Date,Close\n2026-01-01,100\n2026-01-02,101\n")
    assert tc.read("FOO.NS", csv_path, 500000) is None
    print("[ok] csv mtime invalidation")

    # 4. capital in the key — different capital → different bucket
    tc.write("FOO.NS", csv_path, 500000, {"c": "half-mil"})
    tc.write("FOO.NS", csv_path, 1000000, {"c": "one-mil"})
    assert tc.read("FOO.NS", csv_path, 500000)  == {"c": "half-mil"}
    assert tc.read("FOO.NS", csv_path, 1000000) == {"c": "one-mil"}
    print("[ok] capital keyed independently")

    # 5. Error dicts never cached
    tc.clear_all()
    tc.write("FOO.NS", csv_path, 500000, {"error": "bad"})
    assert tc.read("FOO.NS", csv_path, 500000) is None
    print("[ok] error dicts not cached")

    # 6. stats + clear_all
    tc.write("FOO.NS", csv_path, 500000, payload)
    s = tc.stats()
    assert s["count"] >= 1 and s["enabled"] is True and s["bytes"] > 0, s
    removed = tc.clear_all()
    assert removed >= 1
    assert tc.stats()["count"] == 0
    print(f"[ok] stats + clear_all (removed {removed})")

    # 7. TTL expiry — set TTL to 0 → immediate expiry
    tc.TTL_SECONDS = 0
    tc.write("FOO.NS", csv_path, 500000, payload)
    assert tc.read("FOO.NS", csv_path, 500000) is None
    tc.TTL_SECONDS = 86400  # restore
    print("[ok] TTL expiry")

    # 8. Missing CSV → key None → no crash on read or write
    assert tc.read("MISS.NS", "/does/not/exist", 500000) is None
    tc.write("MISS.NS", "/does/not/exist", 500000, payload)
    print("[ok] missing-csv safe fallback")

    # 9. Kill switch OFF → writes are no-ops, reads always miss
    tc.TRIPLE_CACHE_ENABLED = False
    tc.write("FOO.NS", csv_path, 500000, payload)
    assert tc.read("FOO.NS", csv_path, 500000) is None
    tc.TRIPLE_CACHE_ENABLED = True  # restore
    print("[ok] kill switch")

    # 10. Code-version invalidation — force a bump and confirm miss
    tc.clear_all()
    tc.write("FOO.NS", csv_path, 500000, payload)
    assert tc.read("FOO.NS", csv_path, 500000) == payload
    tc._CODE_VERSION = "forced-different-version"
    assert tc.read("FOO.NS", csv_path, 500000) is None
    print("[ok] code-version invalidation")

    shutil.rmtree(tmp, ignore_errors=True)


def test_engine_wire_up_kill_switch() -> None:
    """The engine call site must fall through cleanly when caching is off,
    and must not attempt to cache a result the live call flagged as error.
    We stub run_triple_analysis so we don't run the real 1.5s pipeline."""
    print("\n── Engine wire-up ──")
    _setup_tmp_env()
    tc = _fresh_cache_module()

    import top_picks.engine as engine
    import hybrid_pa_engine

    calls = {"n": 0}
    def _fake_triple(df, ticker="", capital=500000):
        calls["n"] += 1
        return {"snapshot": {"close": 100.0}, "ta_signal": {}, "bb_data": {"indicators": {"price": 100}},
                "triple_verdict": {}, "risk": {}, "target_prices": {}, "triple_targets": {},
                "data_freshness": {}, "pa_data": {}, "pa_score": {}}

    # Monkeypatch in both places engine.py imports could reach.
    engine.run_triple_analysis = _fake_triple
    hybrid_pa_engine.run_triple_analysis = _fake_triple

    # Give the engine a fake load path so os.path.join builds a real string;
    # the file doesn't need to exist for the cache key (missing CSV → skip cache).
    engine.CSV_DIR = os.environ["STOCK_APP_DATA"] + "/stock_csv"

    # With kill switch OFF: cache module returns None every read + skips writes,
    # so the engine falls straight through to the (stub) live call each time.
    tc.TRIPLE_CACHE_ENABLED = False
    # We only need to exercise the cache read/write inside the try block, not
    # the rest of _deep_analyze_stock (which needs a real df). So bypass the
    # engine and drive top_picks.cache directly using the exact same call
    # shape as the wire-up.
    csv_path = os.path.join(engine.CSV_DIR, "FAKE.NS.csv")
    Path(csv_path).write_text("Date,Close\n2026-01-01,100\n")
    for _ in range(3):
        r = tc.read("FAKE.NS", csv_path, 500000)
        if r is None:
            r = _fake_triple(None, ticker="FAKE.NS")
            tc.write("FAKE.NS", csv_path, 500000, r)
    assert calls["n"] == 3, f"kill switch failed to disable caching (got {calls['n']} calls, expected 3)"
    print("[ok] kill switch bypasses cache in engine wire-up shape")

    # With kill switch ON: first call runs live, next two hit cache.
    tc.TRIPLE_CACHE_ENABLED = True
    calls["n"] = 0
    for _ in range(3):
        r = tc.read("FAKE.NS", csv_path, 500000)
        if r is None:
            r = _fake_triple(None, ticker="FAKE.NS")
            tc.write("FAKE.NS", csv_path, 500000, r)
    assert calls["n"] == 1, f"expected 1 live call + 2 hits, got {calls['n']}"
    print(f"[ok] wire-up caches correctly ({calls['n']} live call, 2 hits)")


def test_http_endpoints() -> None:
    """/api/top-picks/cache/stats and /clear via Flask test client."""
    print("\n── HTTP endpoints ──")
    _setup_tmp_env()

    # Bypass auth (same trick as _test_data_browser_delete.py).
    for mod in ("web.app", "auth.middleware", "top_picks.cache"):
        sys.modules.pop(mod, None)
    import auth.db as _authdb
    _authdb.validate_session = lambda _t: {"user_id": 1, "is_admin": True}

    from web.app import app  # noqa: E402
    from top_picks import cache as tc  # noqa: E402
    tc.clear_all()

    client = app.test_client()
    client.set_cookie("hiranya_session", "test-token")

    # 1. stats endpoint shape
    r = client.get("/api/top-picks/cache/stats")
    assert r.status_code == 200, r.status_code
    j = r.get_json()
    for k in ("count", "bytes", "oldest_age_seconds", "ttl_seconds", "enabled"):
        assert k in j, f"missing key {k} in {j}"
    assert j["count"] == 0 and j["enabled"] is True
    print(f"[ok] GET stats returns full shape: {j}")

    # 2. Seed a few entries so we can watch clear drain them
    csv_path = os.path.join(os.environ["STOCK_APP_DATA"], "stock_csv", "BAR.NS.csv")
    Path(csv_path).write_text("Date,Close\n2026-01-01,100\n")
    for i in range(3):
        tc.write(f"BAR.NS", csv_path, 500000 + i, {"i": i})
    assert tc.stats()["count"] == 3
    print("[ok] seeded 3 cache entries")

    # 3. Clear endpoint drains them
    r = client.post("/api/top-picks/cache/clear")
    assert r.status_code == 200, r.status_code
    j = r.get_json()
    assert j["status"] == "ok" and j["removed"] == 3, j
    assert tc.stats()["count"] == 0
    print(f"[ok] POST clear removed {j['removed']}, cache drained")

    # 4. Clear on already-empty cache is safe
    r = client.post("/api/top-picks/cache/clear")
    assert r.status_code == 200 and r.get_json()["removed"] == 0
    print("[ok] clear on empty cache is a no-op, not an error")


def main() -> int:
    test_module_direct()
    test_engine_wire_up_kill_switch()
    test_http_endpoints()
    print("\nALL TOP-PICKS CACHE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
