"""
ai_ml/feedback_loop.py — Outcome Tracker + Self-Learning

Logs each Top 5 pick to SQLite, checks what happened (WIN/LOSS/EXPIRED),
computes performance stats, and can retrain the ML model with new data.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import date, datetime

import pandas as pd

from ai_ml.config import (
    CSV_DIR, FEEDBACK_DB, FEEDBACK_EXPIRY_DAYS,
    FEEDBACK_MIN_RETRAIN, SIGNAL_FILTER_MODEL, TRAINING_DATA_FILE,
)

logger = logging.getLogger("ai_ml.feedback_loop")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS ai_ml_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    method TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    entry_price REAL NOT NULL,
    stop_loss REAL,
    target_price REAL,
    ml_confidence REAL,
    ml_verdict TEXT,
    composite_score REAL,
    market_regime TEXT,
    outcome TEXT DEFAULT 'OPEN',
    exit_price REAL,
    exit_date TEXT,
    actual_return_pct REAL,
    days_held INTEGER,
    max_drawdown_pct REAL,
    max_favorable_pct REAL,
    checked_at TEXT,
    UNIQUE(ticker, entry_date, method)
)
"""


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(FEEDBACK_DB), exist_ok=True)
    conn = sqlite3.connect(FEEDBACK_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_feedback_db():
    with _get_conn() as conn:
        conn.execute(_CREATE_TABLE)


def log_picks(picks: list[dict], method: str = "") -> int:
    """Log picks to feedback DB. Returns count of newly logged entries."""
    init_feedback_db()
    today = date.today().isoformat()
    logged = 0
    with _get_conn() as conn:
        for pick in picks:
            ticker = pick.get("ticker", "")
            price = pick.get("price") or pick.get("current_price")
            if not ticker or not price:
                continue

            stop = pick.get("stop_loss")
            # Try to find target from various sources
            target = pick.get("target_upside")
            if not target:
                targets = pick.get("triple_targets") or {}
                if isinstance(targets, dict):
                    target = targets.get("conservative", {}).get("price")

            regime_data = pick.get("market_regime", {})
            regime = regime_data.get("regime", "") if isinstance(regime_data, dict) else ""

            try:
                conn.execute(
                    """INSERT OR IGNORE INTO ai_ml_feedback
                       (ticker, method, entry_date, entry_price, stop_loss,
                        target_price, ml_confidence, ml_verdict,
                        composite_score, market_regime)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (ticker, method or pick.get("method", ""),
                     today, price, stop, target,
                     pick.get("ml_confidence"),
                     pick.get("ml_verdict"),
                     pick.get("composite_score"),
                     regime),
                )
                if conn.total_changes:
                    logged += 1
            except Exception as e:
                logger.debug("log_picks insert error for %s: %s", ticker, e)
    return logged


def check_outcomes() -> dict:
    """
    Check all OPEN trades against CSV data. Resolve to WIN/LOSS/EXPIRED.
    Returns summary of what was resolved.
    """
    init_feedback_db()
    resolved = {"checked": 0, "wins": 0, "losses": 0, "expired": 0, "still_open": 0}

    with _get_conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM ai_ml_feedback WHERE outcome = 'OPEN'"
        ).fetchall()

    now = datetime.now().isoformat()

    for row in rows:
        resolved["checked"] += 1
        ticker = row["ticker"]
        entry_date_str = row["entry_date"]
        entry_price = row["entry_price"]
        stop = row["stop_loss"]
        target = row["target_price"]

        # Load CSV
        csv_path = os.path.join(CSV_DIR, f"{ticker}.csv")
        if not os.path.exists(csv_path):
            # Try with .NS suffix
            csv_path = os.path.join(CSV_DIR, f"{ticker}.NS.csv")
        if not os.path.exists(csv_path):
            resolved["still_open"] += 1
            continue

        try:
            df = pd.read_csv(csv_path, parse_dates=["Date"])
            df = df.sort_values("Date").reset_index(drop=True)
        except Exception:
            resolved["still_open"] += 1
            continue

        # Find entry date index
        try:
            entry_date = pd.to_datetime(entry_date_str)
        except Exception:
            resolved["still_open"] += 1
            continue

        mask = df["Date"] >= entry_date
        if not mask.any():
            resolved["still_open"] += 1
            continue
        forward = df[mask].copy()

        if len(forward) < 2:
            resolved["still_open"] += 1
            continue

        # Walk forward
        outcome = "OPEN"
        exit_price = None
        exit_date = None
        days_held = 0
        max_dd = 0.0
        max_fav = 0.0

        for i, (_, bar) in enumerate(forward.iterrows()):
            if i == 0:
                continue  # skip entry bar
            days_held = i
            low = float(bar["Low"])
            high = float(bar["High"])
            close = float(bar["Close"])

            # Track extremes
            dd = (entry_price - low) / entry_price * 100 if entry_price else 0
            fav = (high - entry_price) / entry_price * 100 if entry_price else 0
            max_dd = max(max_dd, dd)
            max_fav = max(max_fav, fav)

            # Check stop hit
            if stop and low <= stop:
                outcome = "LOSS"
                exit_price = stop
                exit_date = str(bar["Date"].date()) if hasattr(bar["Date"], "date") else str(bar["Date"])[:10]
                break

            # Check target hit
            if target and high >= target:
                outcome = "WIN"
                exit_price = target
                exit_date = str(bar["Date"].date()) if hasattr(bar["Date"], "date") else str(bar["Date"])[:10]
                break

            # Expiry check
            if i >= FEEDBACK_EXPIRY_DAYS:
                outcome = "EXPIRED"
                exit_price = close
                exit_date = str(bar["Date"].date()) if hasattr(bar["Date"], "date") else str(bar["Date"])[:10]
                break

        if outcome == "OPEN":
            resolved["still_open"] += 1
            continue

        actual_return = (exit_price - entry_price) / entry_price * 100 if entry_price and exit_price else 0

        # Update DB
        with _get_conn() as conn:
            conn.execute(
                """UPDATE ai_ml_feedback SET
                   outcome=?, exit_price=?, exit_date=?, actual_return_pct=?,
                   days_held=?, max_drawdown_pct=?, max_favorable_pct=?,
                   checked_at=?
                   WHERE id=?""",
                (outcome, exit_price, exit_date, round(actual_return, 2),
                 days_held, round(max_dd, 2), round(max_fav, 2),
                 now, row["id"]),
            )

        if outcome == "WIN":
            resolved["wins"] += 1
        elif outcome == "LOSS":
            resolved["losses"] += 1
        elif outcome == "EXPIRED":
            resolved["expired"] += 1

    return resolved


def get_feedback_stats() -> dict:
    """Return performance stats for the AI/ML feedback system."""
    init_feedback_db()

    with _get_conn() as conn:
        conn.row_factory = sqlite3.Row

        total = conn.execute("SELECT COUNT(*) c FROM ai_ml_feedback").fetchone()["c"]
        if total == 0:
            return {
                "total_logged": 0, "total_resolved": 0, "total_open": 0,
                "win_rate_overall": None, "by_method": {}, "by_ml_verdict": {},
                "by_regime": {}, "avg_return_pct": None, "avg_days_held": None,
                "model_last_trained": _model_last_trained(),
                "outcomes_since_training": 0, "retrain_ready": False,
            }

        open_count = conn.execute(
            "SELECT COUNT(*) c FROM ai_ml_feedback WHERE outcome='OPEN'"
        ).fetchone()["c"]

        resolved = conn.execute(
            "SELECT * FROM ai_ml_feedback WHERE outcome != 'OPEN'"
        ).fetchall()

        total_resolved = len(resolved)
        wins = sum(1 for r in resolved if r["outcome"] == "WIN")
        win_rate = round(wins / total_resolved * 100, 1) if total_resolved else None

        # By method
        by_method = {}
        for r in resolved:
            m = r["method"] or "UNKNOWN"
            if m not in by_method:
                by_method[m] = {"trades": 0, "wins": 0}
            by_method[m]["trades"] += 1
            if r["outcome"] == "WIN":
                by_method[m]["wins"] += 1
        for m in by_method:
            t = by_method[m]["trades"]
            w = by_method[m]["wins"]
            by_method[m]["win_rate"] = round(w / t * 100, 1) if t else 0

        # By ML verdict
        by_verdict = {}
        for r in resolved:
            v = r["ml_verdict"] or "UNKNOWN"
            if v not in by_verdict:
                by_verdict[v] = {"trades": 0, "wins": 0}
            by_verdict[v]["trades"] += 1
            if r["outcome"] == "WIN":
                by_verdict[v]["wins"] += 1
        for v in by_verdict:
            t = by_verdict[v]["trades"]
            w = by_verdict[v]["wins"]
            by_verdict[v]["win_rate"] = round(w / t * 100, 1) if t else 0

        # By regime
        by_regime = {}
        for r in resolved:
            rg = r["market_regime"] or "UNKNOWN"
            if rg not in by_regime:
                by_regime[rg] = {"trades": 0, "wins": 0}
            by_regime[rg]["trades"] += 1
            if r["outcome"] == "WIN":
                by_regime[rg]["wins"] += 1
        for rg in by_regime:
            t = by_regime[rg]["trades"]
            w = by_regime[rg]["wins"]
            by_regime[rg]["win_rate"] = round(w / t * 100, 1) if t else 0

        # Averages
        returns = [r["actual_return_pct"] for r in resolved if r["actual_return_pct"] is not None]
        days = [r["days_held"] for r in resolved if r["days_held"] is not None]

        model_date = _model_last_trained()
        outcomes_since = _outcomes_since_training(conn, model_date)

        # Load latest feature importance if available
        feature_importance = None
        fi_path = os.path.join(os.path.dirname(SIGNAL_FILTER_MODEL), "feature_importance.json")
        try:
            if os.path.exists(fi_path):
                import json
                with open(fi_path) as f:
                    fi_history = json.load(f)
                if fi_history:
                    feature_importance = fi_history[-1]
        except Exception:
            pass

        return {
            "total_logged": total,
            "total_resolved": total_resolved,
            "total_open": open_count,
            "win_rate_overall": win_rate,
            "by_method": by_method,
            "by_ml_verdict": by_verdict,
            "by_regime": by_regime,
            "avg_return_pct": round(sum(returns) / len(returns), 2) if returns else None,
            "avg_days_held": round(sum(days) / len(days), 1) if days else None,
            "model_last_trained": model_date,
            "outcomes_since_training": outcomes_since,
            "retrain_ready": outcomes_since >= FEEDBACK_MIN_RETRAIN,
            "feature_importance": feature_importance,
        }


def _model_last_trained() -> str | None:
    model_path = SIGNAL_FILTER_MODEL
    if os.path.exists(model_path):
        mtime = os.path.getmtime(model_path)
        return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
    return None


def _outcomes_since_training(conn, model_date: str | None) -> int:
    if not model_date:
        return 0
    try:
        row = conn.execute(
            "SELECT COUNT(*) c FROM ai_ml_feedback WHERE outcome != 'OPEN' AND checked_at > ?",
            (model_date,),
        ).fetchone()
        return row["c"] if row else 0
    except Exception:
        return 0


def retrain_model() -> dict:
    """
    Retrain the ML signal filter using resolved feedback data merged
    with original training data.
    """
    stats = get_feedback_stats()
    if not stats.get("retrain_ready"):
        return {
            "status": "skipped",
            "reason": f"Need {FEEDBACK_MIN_RETRAIN}+ resolved outcomes, have {stats.get('outcomes_since_training', 0)}",
        }

    try:
        from ai_ml.trainer import train_signal_filter
        metrics = train_signal_filter()
        return {"status": "ok", "metrics": metrics}
    except Exception as e:
        logger.error("Retrain failed: %s", e)
        return {"status": "error", "error": str(e)}


if __name__ == "__main__":
    init_feedback_db()
    fake = [{
        "ticker": "TEST.NS", "method": "M2", "price": 100,
        "stop_loss": 95, "target_upside": 115,
        "ml_confidence": 0.62, "ml_verdict": "ML_PASS",
        "composite_score": 72, "market_regime": {"regime": "BULL"},
    }]
    n = log_picks(fake, method="M2")
    print(f"Logged: {n}")
    stats = get_feedback_stats()
    print(f"Total logged: {stats['total_logged']}")
    print(f"Model last trained: {stats['model_last_trained']}")
    assert stats["total_logged"] >= 1
    print("OK")
