"""
Assert-based check for POST /api/data-browser/delete.

Covers the surface that matters:
  - existing files → listed in `deleted`, gone from disk
  - non-existent   → listed in `missing`
  - path traversal → listed in `errors`, file outside csv_dir untouched
  - list cache is busted so next /list reflects reality
  - empty payload → 400

Run:  python _test_data_browser_delete.py
"""
from __future__ import annotations
import os, sys, json, tempfile, shutil
from pathlib import Path


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="dbdel_")
    csv_dir = os.path.join(tmp, "stock_csv")
    os.makedirs(csv_dir, exist_ok=True)
    os.makedirs(os.path.join(tmp, "data"), exist_ok=True)
    os.environ["STOCK_APP_DATA"] = tmp

    # Seed CSVs. Every ticker gets a valid last-row so /list can parse it.
    tickers = ["FOO", "BAR", "BAZ"]
    for t in tickers:
        Path(csv_dir, f"{t}.NS.csv").write_text(
            "Date,Open,High,Low,Close,Volume\n"
            "2026-08-04,100,101,99,100,1000\n"
            "2026-08-05,101,102,100,101,1200\n"
        )
    # Sentinel file OUTSIDE csv_dir. Delete endpoint must never touch it.
    outside = Path(tmp, "SENSITIVE.NS.csv")
    outside.write_text("must not be deleted")

    # Import app AFTER env is set so CSV_DIR points at the temp dir.
    for mod in ("web.app", "bb_squeeze.config", "auth.middleware"):
        sys.modules.pop(mod, None)
    # Bypass auth: middleware calls auth.db.validate_session — force a fake user.
    import auth.db as _authdb
    _authdb.validate_session = lambda _t: {"user_id": 1, "is_admin": True}
    from web.app import app  # noqa: E402
    from bb_squeeze.config import CSV_DIR  # noqa: E402
    assert CSV_DIR == csv_dir, f"CSV_DIR resolved to {CSV_DIR!r}, expected {csv_dir!r}"

    client = app.test_client()
    # A cookie value is required (else middleware short-circuits before validate_session).
    client.set_cookie("hiranya_session", "test-token")

    # ── 1. empty payload → 400 ────────────────────────────────────────
    r = client.post("/api/data-browser/delete", json={})
    assert r.status_code == 400, r.status_code
    print("[ok] empty payload → 400")

    # ── 2. prime list cache (so we can prove it's busted later) ─────
    r = client.get("/api/data-browser/list")
    assert r.status_code == 200
    j = r.get_json()
    assert j["total"] == 3, j
    print(f"[ok] list before delete: {j['total']} tickers")

    # ── 3. delete existing + missing + traversal in one call ─────────
    r = client.post("/api/data-browser/delete", json={"tickers": [
        "FOO",                # exists (normalises → FOO.NS)
        "DOES_NOT_EXIST",     # not on disk → missing
        "../SENSITIVE",       # traversal → error, outside file must survive
    ]})
    assert r.status_code == 200, r.status_code
    j = r.get_json()
    assert j["deleted"] == ["FOO.NS"], j
    assert j["missing"] == ["DOES_NOT_EXIST.NS"], j
    assert len(j["errors"]) == 1, j
    assert "escapes" in j["errors"][0]["error"], j
    print(f"[ok] mixed batch → deleted={j['deleted']}, missing={j['missing']}, errors={len(j['errors'])}")

    # Disk truth
    assert not Path(csv_dir, "FOO.NS.csv").exists(), "FOO.NS.csv still on disk"
    assert Path(csv_dir, "BAR.NS.csv").exists(),     "BAR.NS.csv wrongly deleted"
    assert outside.exists(), "SENSITIVE file outside csv_dir was touched"
    print("[ok] disk matches API response — traversal target survived")

    # ── 4. cache-bust: next /list must reflect the delete ────────────
    r = client.get("/api/data-browser/list")
    j = r.get_json()
    remaining = sorted(it["ticker"] for it in j["items"])
    assert remaining == ["BAR.NS", "BAZ.NS"], remaining
    print(f"[ok] list after delete: {remaining} (cache busted)")

    # ── 5. batch delete of the rest ──────────────────────────────────
    r = client.post("/api/data-browser/delete",
                    json={"tickers": ["BAR.NS", "BAZ.NS"]})
    j = r.get_json()
    assert sorted(j["deleted"]) == ["BAR.NS", "BAZ.NS"], j
    assert j["count"] == 2, j
    assert not any(Path(csv_dir).glob("*.csv")), "csv_dir not empty after full delete"
    print("[ok] batch delete drained csv_dir")

    shutil.rmtree(tmp, ignore_errors=True)
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
