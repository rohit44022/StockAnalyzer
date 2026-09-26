"""
Intraday Brooks Scanner
=======================
Runs Brooks PA engine on 5-min candles for intraday trading.

Two setup families:
  SHORT_FIRST — sell at resistance, buy back at support (trend-following in bear)
  LONG_FIRST  — buy at support, sell into resistance (counter-trend scalp in bear)

Architecture:
  1. Fetch 5 days of 5-min candles (context)
  2. Isolate TODAY's bars for signal generation (no cross-day contamination)
  3. Use prior days' close for gap detection
  4. Apply time-of-day filters (opening range, lunch deadzone, hard exit)
  5. Override engine's daily-calibrated stop floor with intraday ATR

Universe: daily Brooks engine's SELL/BEAR stocks, or manual watchlist.
Hard exit: 3:15 PM IST (NSE close = 3:30, leave 15 min buffer).
"""

from __future__ import annotations

import sys, os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
from datetime import datetime, time, timedelta

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from brooks.engine import run_brooks_analysis, BrooksResult, MIN_BARS
from intraday.data import fetch_intraday

# ── Intraday constants ────────────────────────────────────────────
INTRADAY_MIN_BARS = 60          # match engine's MIN_BARS requirement
MAX_STOP_PCT = 2.5              # intraday: max 2.5% stop (vs 8% daily)
MIN_STOP_PCT = 0.3              # floor: 5-min ATR is tiny, 0.3% prevents noise stops
MIN_RR = 1.5                    # at least 1.5:1 reward/risk
MAX_WORKERS = 4                 # respect Dhan rate limit (5/sec)
HARD_EXIT = time(15, 15)        # must close by 3:15 PM IST
NO_NEW_ENTRY_AFTER = time(14, 45)  # no new entries after 2:45 PM
LUNCH_START = time(12, 0)       # avoid signals during lunch
LUNCH_END = time(13, 0)
OPENING_RANGE_BARS = 6          # first 30 min = 6 x 5-min bars
MIN_VOLUME_RATIO = 1.0
INTERVAL = "5m"
INTRADAY_ATR_STOP_MULT = 3.0   # 5-min ATR is ~15x smaller than daily; 3.0 gives 0.4-1.2% stops


@dataclass
class IntradaySetup:
    ticker: str
    direction: str          # SHORT_FIRST or LONG_FIRST
    setup_type: str         # from Brooks: BREAKOUT, PULLBACK, etc.
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: float
    stop_pct: float         # distance to stop as %
    risk_reward: float
    confidence: int
    always_in: str          # LONG/SHORT/FLAT on 5-min
    trend_phase: str        # intraday trend phase
    strength: str
    volume_ratio: float
    pa_score: float
    daily_regime: str = ""  # from daily engine: BEAR/CHOPPY etc.
    daily_ai: str = ""      # daily always-in direction
    reasons: List[str] = field(default_factory=list)
    timestamp: str = ""
    time_quality: str = ""  # PRIME / OK / LATE / AVOID
    gap_type: str = ""      # GAP_UP / GAP_DOWN / FLAT_OPEN
    opening_range_breakout: bool = False


# ── Time-of-day quality ───────────────────────────────────────────

def _time_quality(ts: Optional[datetime] = None) -> Tuple[str, int]:
    """Rate the current time for intraday trading. Returns (label, conf_adj)."""
    t = (ts or datetime.now()).time()
    if t < time(9, 15):
        return "PRE_MARKET", -100
    if t <= time(10, 30):
        return "PRIME", +5       # first hour: best setups
    if t <= LUNCH_START:
        return "OK", 0
    if t <= LUNCH_END:
        return "LUNCH", -15      # low volume, choppy
    if t <= time(14, 30):
        return "OK", 0
    if t <= NO_NEW_ENTRY_AFTER:
        return "LATE", -10       # less time for setup to play out
    if t <= time(15, 30):
        return "AVOID", -100     # too close to hard exit
    return "CLOSED", -100


def _detect_gap(today_open: float, prev_close: float) -> Tuple[str, float]:
    """Detect gap type and size."""
    if prev_close <= 0:
        return "UNKNOWN", 0.0
    gap_pct = (today_open - prev_close) / prev_close * 100
    if gap_pct > 0.3:
        return "GAP_UP", round(gap_pct, 2)
    if gap_pct < -0.3:
        return "GAP_DOWN", round(gap_pct, 2)
    return "FLAT_OPEN", round(gap_pct, 2)


def _detect_opening_range_breakout(
    df_today: pd.DataFrame, n_bars: int = OPENING_RANGE_BARS
) -> Tuple[bool, str, float, float]:
    """Check if price has broken out of the opening range."""
    if len(df_today) <= n_bars:
        return False, "NONE", 0.0, 0.0

    or_high = df_today["High"].iloc[:n_bars].max()
    or_low = df_today["Low"].iloc[:n_bars].min()
    last_close = df_today["Close"].iloc[-1]

    if last_close > or_high:
        return True, "BULL", or_high, or_low
    if last_close < or_low:
        return True, "BEAR", or_high, or_low
    return False, "NONE", or_high, or_low


def _split_by_day(df: pd.DataFrame) -> List[pd.DataFrame]:
    """Split multi-day 5-min dataframe into per-day frames."""
    if df.index.tz is not None:
        dates = df.index.date
    else:
        dates = df.index.date
    unique_dates = sorted(set(dates))
    return [df[df.index.date == d] for d in unique_dates]


def _recalc_intraday_stop(
    sig: str, entry: float, df_today: pd.DataFrame
) -> float:
    """Recalculate stop using intraday ATR instead of the engine's 2% floor."""
    h = df_today["High"].values.astype(float)
    l = df_today["Low"].values.astype(float)
    c = df_today["Close"].values.astype(float)
    n = len(c)
    if n < 2:
        return entry * (0.985 if sig == "BUY" else 1.015)

    # compute ATR on today's bars
    tr = np.zeros(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    atr = float(np.mean(tr[-min(14, n):]))
    stop_dist = atr * INTRADAY_ATR_STOP_MULT
    min_dist = entry * MIN_STOP_PCT / 100
    stop_dist = max(stop_dist, min_dist)

    if sig == "BUY":
        return round(entry - stop_dist, 2)
    else:
        return round(entry + stop_dist, 2)


def _analyse_one(ticker: str, days: int = 5) -> Optional[IntradaySetup]:
    """Run Brooks on 5-min candles for one ticker, return setup or None."""
    df = fetch_intraday(ticker, interval=INTERVAL, days=days)
    if df is None or len(df) < INTRADAY_MIN_BARS:
        return None

    # ── Split into days ──
    daily_frames = _split_by_day(df)
    if not daily_frames:
        return None

    df_today = daily_frames[-1]
    if len(df_today) < 10:
        return None

    # ── Time-of-day check ──
    tq_label, tq_adj = _time_quality()
    if tq_adj <= -100:
        return None

    # ── Gap detection (compare today's open to previous day's close) ──
    gap_type, gap_pct = "UNKNOWN", 0.0
    if len(daily_frames) >= 2:
        prev_close = daily_frames[-2]["Close"].iloc[-1]
        today_open = df_today["Open"].iloc[0]
        gap_type, gap_pct = _detect_gap(float(today_open), float(prev_close))

    # ── Opening range breakout ──
    orb, orb_dir, or_high, or_low = _detect_opening_range_breakout(df_today)

    # ── Run Brooks engine on TODAY's bars (not multi-day) ──
    # Use last 2 days for enough bars (context from yesterday + today's action)
    if len(daily_frames) >= 2:
        analysis_df = pd.concat([daily_frames[-2], daily_frames[-1]])
    else:
        analysis_df = df_today

    if len(analysis_df) < MIN_BARS:
        return None

    r = run_brooks_analysis(df=analysis_df, ticker=ticker)
    if not r.success or r.signal_type == "HOLD":
        return None

    # ── Recalculate stop using intraday ATR (override engine's 2% floor) ──
    if r.entry_price <= 0:
        return None
    stop = _recalc_intraday_stop(r.signal_type, r.entry_price, df_today)

    # ── Stop distance check ──
    stop_pct = abs(r.entry_price - stop) / r.entry_price * 100
    if stop_pct > MAX_STOP_PCT or stop_pct == 0:
        return None

    # ── Recalculate targets with intraday stop ──
    risk = abs(r.entry_price - stop)
    if risk <= 0:
        return None
    if r.signal_type == "BUY":
        t1 = round(r.entry_price + risk * 1.5, 2)
        t2 = round(r.entry_price + risk * 2.5, 2)
    else:
        t1 = round(r.entry_price - risk * 1.5, 2)
        t2 = round(r.entry_price - risk * 2.5, 2)

    # ── Risk/reward check ──
    rr = 1.5  # targets set at 1.5:1 minimum
    if rr < MIN_RR:
        return None

    # ── Volume check (using today's bars only) ──
    vol = df_today["Volume"].values.astype(float)
    if len(vol) >= 2:
        avg_vol = float(np.mean(vol[:-1])) if len(vol) > 1 else float(vol[0])
        vol_ratio = round(float(vol[-1]) / max(avg_vol, 1), 2)
    else:
        vol_ratio = r.volume_ratio
    if vol_ratio < MIN_VOLUME_RATIO:
        return None

    # ── Apply time-of-day confidence adjustment ──
    adj_confidence = max(0, min(100, r.confidence + tq_adj))

    # ── Opening range breakout bonus ──
    if orb and orb_dir == ("BULL" if r.signal_type == "BUY" else "BEAR"):
        adj_confidence = min(100, adj_confidence + 8)

    # ── Lunch penalty already in tq_adj, but also skip weak lunch signals ──
    if tq_label == "LUNCH" and adj_confidence < 60:
        return None

    # ── Determine direction ──
    if r.signal_type == "SELL":
        direction = "SHORT_FIRST"
    elif r.signal_type == "BUY":
        direction = "LONG_FIRST"
    else:
        return None

    reasons = r.reasons if hasattr(r, "reasons") else []
    if orb:
        reasons = [f"Opening range breakout ({orb_dir})"] + reasons
    if gap_type in ("GAP_UP", "GAP_DOWN"):
        reasons.append(f"{gap_type.replace('_', ' ')} {abs(gap_pct):.1f}%")
    if tq_label == "PRIME":
        reasons.append("First hour — highest probability window")
    elif tq_label == "LUNCH":
        reasons.append("Lunch hour — lower volume, reduce size")

    return IntradaySetup(
        ticker=ticker,
        direction=direction,
        setup_type=r.setup_type,
        entry_price=round(r.entry_price, 2),
        stop_loss=stop,
        target_1=t1,
        target_2=t2,
        stop_pct=round(stop_pct, 2),
        risk_reward=round(rr, 2),
        confidence=adj_confidence,
        always_in=r.always_in,
        trend_phase=r.trend_phase,
        strength=r.strength,
        volume_ratio=vol_ratio,
        pa_score=round(r.pa_score, 1),
        reasons=reasons,
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        time_quality=tq_label,
        gap_type=gap_type,
        opening_range_breakout=orb,
    )


def get_bearish_watchlist(csv_dir: str, limit: int = 50) -> List[str]:
    """Get bearish stocks from the daily Brooks engine as intraday universe.
    Uses cached daily scan when available via the web API."""
    from bb_squeeze.data_loader import get_all_tickers_from_csv, load_stock_data
    from brooks.ml.regime import classify_regime

    tickers = get_all_tickers_from_csv(csv_dir)
    bearish = []

    def _check(t):
        try:
            df = load_stock_data(t, csv_dir=csv_dir, use_live_fallback=False)
            if df is None or len(df) < 60:
                return None
            ri = classify_regime(df)
            if ri["regime"] in ("BEAR", "TRENDING_BEAR", "CHOPPY"):
                r = run_brooks_analysis(df=df, ticker=t)
                if r.success and r.always_in == "SHORT":
                    return (t, ri["regime"])
        except Exception:
            pass
        return None

    with ThreadPoolExecutor(max_workers=16) as pool:
        futs = {pool.submit(_check, t): t for t in tickers}
        for fut in as_completed(futs, timeout=300):
            try:
                res = fut.result(timeout=10)
                if res:
                    bearish.append(res)
                    if len(bearish) >= limit:
                        break
            except Exception:
                pass

    bearish.sort(key=lambda x: x[0])
    return [t for t, _ in bearish[:limit]]


def scan_intraday(
    watchlist: Optional[List[str]] = None,
    csv_dir: str = "stock_csv",
    top_n: int = 10,
) -> Dict:
    """
    Main entry point. Scans watchlist on 5-min candles.

    If no watchlist, auto-builds from daily bearish stocks.
    Returns dict with short_first, long_first picks + stats.
    """
    if not watchlist:
        watchlist = get_bearish_watchlist(csv_dir, limit=50)

    setups: List[IntradaySetup] = []
    scanned = 0
    errors = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futs = {pool.submit(_analyse_one, t): t for t in watchlist}
        for fut in as_completed(futs, timeout=180):
            try:
                s = fut.result(timeout=30)
                scanned += 1
                if s is not None:
                    setups.append(s)
            except Exception:
                errors += 1
                scanned += 1

    # Enrich with daily regime
    if csv_dir:
        _enrich_daily(setups, csv_dir)

    # Split by direction, sort by confidence then RR
    shorts = sorted(
        [s for s in setups if s.direction == "SHORT_FIRST"],
        key=lambda s: (-s.confidence, -s.risk_reward),
    )[:top_n]

    longs = sorted(
        [s for s in setups if s.direction == "LONG_FIRST"],
        key=lambda s: (-s.confidence, -s.risk_reward),
    )[:top_n]

    tq_label, _ = _time_quality()

    return {
        "short_first": [_to_dict(s) for s in shorts],
        "long_first": [_to_dict(s) for s in longs],
        "watchlist_size": len(watchlist),
        "scanned": scanned,
        "errors": errors,
        "total_setups": len(setups),
        "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "market_open": _is_market_open(),
        "time_quality": tq_label,
    }


def _enrich_daily(setups: List[IntradaySetup], csv_dir: str):
    """Add daily regime + AI direction to each setup."""
    from bb_squeeze.data_loader import load_stock_data
    from brooks.ml.regime import classify_regime

    for s in setups:
        try:
            df = load_stock_data(s.ticker, csv_dir=csv_dir, use_live_fallback=False)
            if df is None or len(df) < 60:
                continue
            ri = classify_regime(df)
            s.daily_regime = ri["regime"]
            r = run_brooks_analysis(df=df, ticker=s.ticker)
            if r.success:
                s.daily_ai = r.always_in
        except Exception:
            pass


def _is_market_open() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return time(9, 15) <= t <= time(15, 30)


def _to_dict(s: IntradaySetup) -> Dict:
    return {
        "ticker": s.ticker,
        "direction": s.direction,
        "setup_type": s.setup_type,
        "entry_price": s.entry_price,
        "stop_loss": s.stop_loss,
        "target_1": s.target_1,
        "target_2": s.target_2,
        "stop_pct": s.stop_pct,
        "risk_reward": s.risk_reward,
        "confidence": s.confidence,
        "always_in": s.always_in,
        "trend_phase": s.trend_phase,
        "strength": s.strength,
        "volume_ratio": s.volume_ratio,
        "pa_score": s.pa_score,
        "daily_regime": s.daily_regime,
        "daily_ai": s.daily_ai,
        "reasons": s.reasons,
        "timestamp": s.timestamp,
        "time_quality": s.time_quality,
        "gap_type": s.gap_type,
        "opening_range_breakout": s.opening_range_breakout,
    }
