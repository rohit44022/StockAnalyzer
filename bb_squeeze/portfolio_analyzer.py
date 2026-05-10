"""
portfolio_analyzer.py — Strategy-aware post-purchase analysis engine.

For each open portfolio position this module:
  1. Loads current daily OHLCV data from the existing data_loader
  2. Computes all technical indicators (reuses indicators.py)
  3. Runs the SAME strategy that was used to buy (M1/M2/M3/M4)
  4. Generates an actionable recommendation: HOLD / SELL / ADD
  5. Computes target prices based on Bollinger Bands + fundamentals
  6. Returns a rich analysis dict ready for the UI

This module NEVER modifies any existing module.  It only reads from them.
"""

from __future__ import annotations

import math
import time as _time
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, date

import pandas as pd
import numpy as np
import yfinance as yf

from bb_squeeze.data_loader import load_stock_data, normalise_ticker
from bb_squeeze.fundamentals import fetch_fundamentals
from bb_squeeze.indicators import compute_all_indicators
from bb_squeeze.signals import analyze_signals
from bb_squeeze.strategies import run_all_strategies, strategy_result_to_dict
from bb_squeeze.config import CSV_DIR
from bb_squeeze.strategy_config import (
    M2_PCT_B_BUY_THRESHOLD, M2_PCT_B_SELL_THRESHOLD,
    M2_MFI_CONFIRM_BUY, M2_MFI_CONFIRM_SELL,
    M4_WALK_PCT_B_UPPER,
)

# Multi-system engines
from hybrid_pa_engine import run_triple_analysis
from price_action.engine import run_price_action_analysis

# Vince Risk Management
from vince.optimal_f import find_optimal_f_empirical, compute_by_products
from vince.risk_metrics import position_sizing, historical_volatility, drawdown_analysis, time_to_goal
from vince.statistics import runs_test, serial_correlation


# ═══════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════

def _safe(v, decimals=2):
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, (float, np.floating)):
        return round(float(v), decimals)
    return v


def _holding_days(buy_date_str: str) -> int:
    try:
        bd = datetime.strptime(buy_date_str, "%Y-%m-%d").date()
        return (date.today() - bd).days
    except Exception:
        return 0


_pa_logger = logging.getLogger(__name__)

# ── Nifty benchmark cache (2y of daily closes) ───────────────
_nifty_closes: pd.Series | None = None
_nifty_fetch_ts: float = 0.0
_NIFTY_CACHE_TTL: float = 4 * 3600.0   # 4 hours


def _get_nifty_closes() -> pd.Series | None:
    """Return Nifty 50 daily Close series (cached 4h)."""
    global _nifty_closes, _nifty_fetch_ts
    if _nifty_closes is not None and _time.time() - _nifty_fetch_ts < _NIFTY_CACHE_TTL:
        return _nifty_closes
    try:
        nifty = yf.download("^NSEI", period="2y", progress=False, timeout=10)
        if nifty is not None and not nifty.empty:
            closes = nifty["Close"].squeeze()
            if isinstance(closes, pd.Series) and len(closes) > 10:
                _nifty_closes = closes
                _nifty_fetch_ts = _time.time()
                return _nifty_closes
    except Exception as e:
        _pa_logger.debug("Nifty fetch failed: %s", e)
    return None


# ═══════════════════════════════════════════════════════════════
#  FUNDAMENTAL HEALTH SNAPSHOT (50-year expert: never trade blind)
# ═══════════════════════════════════════════════════════════════

def _fetch_fundamental_snapshot(ticker: str) -> dict:
    """
    Lightweight fundamental health check for a portfolio position.
    Uses the 4h-cached fetch_fundamentals() — no extra latency.

    A 50-year market veteran never holds a position without knowing:
      1. Is the company making money? (ROE, margins)
      2. Is it growing? (revenue/earnings growth)
      3. Is it overvalued? (PE, PB vs sector)
      4. Can it survive a downturn? (debt, current ratio)
      5. What's the overall fundamental verdict?
    """
    try:
        fd = fetch_fundamentals(ticker)
        if fd.fetch_error:
            return {"available": False, "error": fd.fetch_error}

        # ── Expert health assessment ──
        health_flags = []
        concern_flags = []

        # Profitability check
        if fd.roe is not None:
            if fd.roe > 15:
                health_flags.append(f"Strong ROE ({fd.roe:.1f}%) — company generates good returns on equity")
            elif fd.roe < 5:
                concern_flags.append(f"Weak ROE ({fd.roe:.1f}%) — poor capital efficiency")

        # Debt check
        if fd.debt_to_equity is not None:
            if fd.debt_to_equity < 0.5:
                health_flags.append("Low debt — financially strong balance sheet")
            elif fd.debt_to_equity > 1.5:
                concern_flags.append(f"High debt (D/E: {fd.debt_to_equity:.2f}) — vulnerable in downturns")

        # Growth check
        if fd.revenue_growth is not None:
            if fd.revenue_growth > 15:
                health_flags.append(f"Strong revenue growth ({fd.revenue_growth:.1f}%) — business expanding")
            elif fd.revenue_growth < 0:
                concern_flags.append(f"Revenue declining ({fd.revenue_growth:.1f}%) — business shrinking")

        # Valuation check
        if fd.pe_ratio is not None:
            if fd.pe_ratio < 15:
                health_flags.append(f"Attractively valued (PE: {fd.pe_ratio:.1f})")
            elif fd.pe_ratio > 50:
                concern_flags.append(f"Expensive valuation (PE: {fd.pe_ratio:.1f}) — growth must justify price")

        # Cash flow check
        if fd.free_cash_flow is not None:
            if fd.free_cash_flow > 0:
                health_flags.append("Positive free cash flow — self-funding business")
            else:
                concern_flags.append("Negative free cash flow — burning cash")

        # Expert verdict
        health_count = len(health_flags)
        concern_count = len(concern_flags)
        if health_count >= 3 and concern_count == 0:
            expert_view = "STRONG"
            expert_note = "Fundamentals are rock-solid. Technicals + fundamentals aligned = high conviction hold."
        elif health_count >= 2 and concern_count <= 1:
            expert_view = "GOOD"
            expert_note = "Fundamentals support the position. Minor concerns exist but the business is sound."
        elif concern_count >= 3:
            expert_view = "WEAK"
            expert_note = "Fundamental concerns detected. Even if technicals look good, weak fundamentals can catch up. Tighter stops advised."
        elif concern_count >= 2:
            expert_view = "CAUTION"
            expert_note = "Mixed fundamentals. The business has notable weaknesses. Don't overstay — take profits when technicals weaken."
        else:
            expert_view = "NEUTRAL"
            expert_note = "Fundamentals are average. Let technicals drive your decision."

        return {
            "available": True,
            "company_name": fd.company_name,
            "sector": fd.sector,
            "pe_ratio": _safe(fd.pe_ratio),
            "pb_ratio": _safe(fd.pb_ratio),
            "roe": _safe(fd.roe),
            "roce": _safe(fd.roce),
            "debt_to_equity": _safe(fd.debt_to_equity, 3),
            "profit_margin": _safe(fd.profit_margin),
            "operating_margin": _safe(fd.operating_margin),
            "revenue_growth": _safe(fd.revenue_growth),
            "earnings_growth": _safe(fd.earnings_growth),
            "free_cash_flow": _safe(fd.free_cash_flow),
            "current_ratio": _safe(fd.current_ratio),
            "dividend_yield": _safe(fd.dividend_yield),
            "fundamental_score": fd.fundamental_score,
            "fundamental_signal": fd.fundamental_signal,
            "fundamental_verdict": fd.fundamental_verdict,
            "valuation_score": fd.valuation_score,
            "profitability_score": fd.profitability_score,
            "growth_score": fd.growth_score,
            "stability_score": fd.stability_score,
            # Expert assessment
            "expert_view": expert_view,
            "expert_note": expert_note,
            "health_flags": health_flags[:5],
            "concern_flags": concern_flags[:5],
        }
    except Exception as e:
        _pa_logger.debug("Fundamental snapshot failed for %s: %s", ticker, e)
        return {"available": False, "error": "Could not fetch fundamentals"}


# ═══════════════════════════════════════════════════════════════
#  BENCHMARK ALPHA (50-year expert: always know if you're beating the market)
# ═══════════════════════════════════════════════════════════════

def _compute_benchmark_alpha(buy_date_str: str, position_return_pct: float) -> dict:
    """
    Compare your holding-period return vs Nifty 50 over the same dates.

    A 50-year veteran always asks: "Am I generating alpha or just riding
    the market wave?" If Nifty rose 15% and your stock rose 12%, you
    actually LOST value relative to a simple index fund.
    """
    try:
        buy_date = datetime.strptime(buy_date_str, "%Y-%m-%d").date()
        days_held = (date.today() - buy_date).days
        if days_held < 3:
            return {"available": False, "reason": "Too few days to compare"}

        nifty = _get_nifty_closes()
        if nifty is None or nifty.empty:
            return {"available": False, "error": "Nifty data unavailable"}

        # Find closest trading day on or after buy date
        nifty_idx = nifty.index.tz_localize(None) if nifty.index.tz else nifty.index
        mask = nifty_idx >= pd.Timestamp(buy_date)
        if mask.sum() < 2:
            return {"available": False, "error": "Buy date outside Nifty data range"}

        nifty_slice = nifty[mask]
        nifty_start = float(nifty_slice.iloc[0])
        nifty_end = float(nifty_slice.iloc[-1])
        nifty_return = (nifty_end - nifty_start) / nifty_start * 100

        alpha = position_return_pct - nifty_return

        # Annualised returns (CAGR)
        years = days_held / 365.25
        if years >= 0.08:  # ~30 days minimum for annualisation
            ann_pos = ((1 + position_return_pct / 100) ** (1 / years) - 1) * 100
            ann_nifty = ((1 + nifty_return / 100) ** (1 / years) - 1) * 100
            ann_alpha = ann_pos - ann_nifty
        else:
            ann_pos = ann_nifty = ann_alpha = None

        # Expert assessment
        if alpha > 10:
            verdict = "EXCELLENT"
            note = "You're significantly outperforming the market. Strong stock picking."
        elif alpha > 3:
            verdict = "GOOD"
            note = "Beating the market by a healthy margin. Your entry was well-timed."
        elif alpha > -3:
            verdict = "NEUTRAL"
            note = "Roughly matching the market. You're not losing but not gaining edge either."
        elif alpha > -10:
            verdict = "LAGGING"
            note = "Underperforming Nifty. A simple index fund would have done better over this period."
        else:
            verdict = "POOR"
            note = "Significantly trailing the market. Re-evaluate if this position deserves your capital."

        return {
            "available": True,
            "nifty_return_pct": round(nifty_return, 2),
            "position_return_pct": round(position_return_pct, 2),
            "alpha_pct": round(alpha, 2),
            "annualized_position": _safe(ann_pos) if ann_pos else None,
            "annualized_nifty": _safe(ann_nifty) if ann_nifty else None,
            "annualized_alpha": _safe(ann_alpha) if ann_alpha else None,
            "days_held": days_held,
            "beating_market": alpha > 0,
            "nifty_start": round(nifty_start, 2),
            "nifty_end": round(nifty_end, 2),
            "verdict": verdict,
            "note": note,
        }
    except Exception as e:
        _pa_logger.debug("Benchmark alpha failed: %s", e)
        return {"available": False, "error": "Benchmark comparison unavailable"}


# ═══════════════════════════════════════════════════════════════
#  TRAILING STOPS (50-year expert: protect profits with dynamic stops)
# ═══════════════════════════════════════════════════════════════

def _compute_trailing_stops(df: pd.DataFrame, buy_price: float) -> dict:
    """
    ATR-based dynamic trailing stops — the professional way.

    Static stops (fixed %) get you whipsawed in volatile stocks and
    leave money on the table in calm ones. Dynamic stops adapt to
    the stock's actual breathing room (ATR = Average True Range).

    Levels computed:
      • Chandelier Exit:  Highest_High(22) - 3×ATR(22)  [Chuck LeBeau]
      • ATR Trail (tight): Close - 2×ATR(14)             [active traders]
      • ATR Trail (wide):  Close - 3×ATR(14)             [swing traders]
      • SuperTrend-style:  Close - 2×ATR(10)             [Indian market standard]
    """
    if len(df) < 30:
        return {"available": False}

    high = df["High"].values.astype(float)
    low = df["Low"].values.astype(float)
    close = df["Close"].values.astype(float)

    # True Range series
    tr = np.zeros(len(df))
    tr[0] = high[0] - low[0]
    for i in range(1, len(df)):
        tr[i] = max(high[i] - low[i],
                     abs(high[i] - close[i - 1]),
                     abs(low[i] - close[i - 1]))

    # ATR at different lookbacks
    atr_10 = float(np.mean(tr[-10:]))
    atr_14 = float(np.mean(tr[-14:]))
    atr_22 = float(np.mean(tr[-22:]))

    price = close[-1]
    highest_22 = float(np.max(high[-22:]))

    # ── Stop Levels ──
    chandelier   = highest_22 - 3 * atr_22      # LeBeau classic
    atr_tight    = price - 2 * atr_14            # Active traders
    atr_wide     = price - 3 * atr_14            # Swing traders
    supertrend   = price - 2 * atr_10            # Indian market favourite

    # Daily volatility as % of price
    vol_pct = (atr_14 / price) * 100 if price > 0 else 0

    # Pick recommended stop: highest (tightest) that still gives breathing room
    # Rule: never set stop inside 1×ATR of current price (too tight = whipsaw)
    min_stop = price - atr_14
    candidates = [s for s in [chandelier, atr_tight, supertrend]
                  if 0 < s < price and s <= min_stop]
    recommended = max(candidates) if candidates else atr_wide

    # Risk from current price to recommended stop
    risk_pct = (price - recommended) / price * 100 if price > 0 else 0

    # Is recommended stop above buy price? (= profit locked in)
    profit_locked = recommended > buy_price
    locked_pnl_pct = ((recommended - buy_price) / buy_price * 100) if profit_locked and buy_price > 0 else 0

    # Expert note
    if profit_locked and locked_pnl_pct > 10:
        expert_note = f"Excellent — trailing stop locks in {locked_pnl_pct:.1f}% profit even if the stock reverses. Let the winner run."
    elif profit_locked:
        expert_note = f"Good — trailing stop is above your buy price, locking in {locked_pnl_pct:.1f}% profit. Move stop up as the stock rises."
    elif risk_pct < 5:
        expert_note = "Tight risk. The stop is close to current price — you'll exit quickly if the trend turns."
    elif risk_pct < 10:
        expert_note = "Reasonable risk. The stop gives the stock room to breathe while protecting against large drops."
    else:
        expert_note = "Wide risk zone. Consider whether this much downside is acceptable for your position size."

    return {
        "available":         True,
        "atr_14":            round(atr_14, 2),
        "atr_22":            round(atr_22, 2),
        "daily_vol_pct":     round(vol_pct, 2),
        "chandelier_exit":   round(chandelier, 2),
        "atr_trail_tight":   round(atr_tight, 2),
        "atr_trail_wide":    round(atr_wide, 2),
        "supertrend_stop":   round(supertrend, 2),
        "recommended_stop":  round(recommended, 2),
        "risk_pct":          round(risk_pct, 2),
        "profit_locked":     profit_locked,
        "locked_pnl_pct":    round(locked_pnl_pct, 2) if profit_locked else 0,
        "expert_note":       expert_note,
        "highest_22d":       round(highest_22, 2),
    }


# ═══════════════════════════════════════════════════════════════
#  EXPERT DAILY COMMENTARY (60-year market veteran)
# ═══════════════════════════════════════════════════════════════

def _generate_expert_commentary(df: pd.DataFrame, sig, multi_sys: dict, buy_price: float) -> dict:
    """
    Generate natural-language expert commentary for today's price action.
    Synthesises OHLCV, Bollinger Bands, volume, Price Action, Triple
    system, and holding context into a daily briefing paragraph.
    Written as if by a market expert with 60 years of experience.
    """
    try:
        if df is None or len(df) < 5:
            return {"available": False}

        last = df.iloc[-1]
        prev = df.iloc[-2]
        prev2 = df.iloc[-3] if len(df) >= 3 else prev

        # ── Price Data ──
        o = float(last["Open"])
        h = float(last["High"])
        l = float(last["Low"])
        c = float(last["Close"])
        v = int(last["Volume"])
        prev_c = float(prev["Close"])
        prev_h = float(prev["High"])
        prev_l = float(prev["Low"])

        # Day change
        day_change = c - prev_c
        day_change_pct = (day_change / prev_c * 100) if prev_c else 0
        intraday_range = h - l
        intraday_range_pct = (intraday_range / l * 100) if l else 0

        # Body vs wick analysis (candle character)
        body = abs(c - o)
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        total_range = h - l if h != l else 0.01
        body_ratio = body / total_range

        # ── Volume Context ──
        vol_sma = float(last.get("Vol_SMA50", v))
        vol_ratio = v / vol_sma if vol_sma > 0 else 1.0
        vol_desc = "extremely heavy" if vol_ratio > 2.5 else "heavy" if vol_ratio > 1.5 else "above average" if vol_ratio > 1.1 else "average" if vol_ratio > 0.7 else "below average" if vol_ratio > 0.4 else "very thin"

        # ── Bollinger Band Context ──
        bb_upper = float(last.get("BB_Upper", c))
        bb_mid = float(last.get("BB_Mid", c))
        bb_lower = float(last.get("BB_Lower", c))
        pct_b = float(last.get("Percent_B", 0.5))
        bbw = float(last.get("BBW", 0))
        squeeze = bool(last.get("Squeeze_ON", False))
        sar_bull = bool(last.get("SAR_Bull", False))
        mfi = float(last.get("MFI", 50))
        cmf = float(last.get("CMF", 0))
        rsi = float(last.get("RSI", 50))

        # Position relative to bands
        if pct_b > 1.0:
            bb_position = "trading ABOVE the upper Bollinger Band — strong bullish momentum but potentially overextended"
        elif pct_b > 0.8:
            bb_position = "hugging the upper band — strong bullish pressure"
        elif pct_b > 0.6:
            bb_position = "in the upper half of the bands — mild bullish bias"
        elif pct_b > 0.4:
            bb_position = "near the middle band — neutral territory, waiting for direction"
        elif pct_b > 0.2:
            bb_position = "in the lower half of the bands — under selling pressure"
        elif pct_b > 0.0:
            bb_position = "near the lower band — weak and potentially oversold"
        else:
            bb_position = "BELOW the lower Bollinger Band — extreme weakness, but bounce probability rises"

        # ── Candle Interpretation ──
        is_green = c > o
        is_doji = body_ratio < 0.15
        is_hammer = lower_wick > body * 2 and upper_wick < body * 0.5 and not is_green
        is_shooting_star = upper_wick > body * 2 and lower_wick < body * 0.5 and is_green
        is_marubozu = body_ratio > 0.85

        if is_doji:
            candle_desc = "a Doji candle (indecision — neither bulls nor bears won today)"
        elif is_hammer:
            candle_desc = "a Hammer pattern (sellers tried hard but buyers reclaimed ground — potential reversal)"
        elif is_shooting_star:
            candle_desc = "a Shooting Star (buyers pushed up but sellers slammed it back — potential reversal warning)"
        elif is_marubozu and is_green:
            candle_desc = "a bullish Marubozu (strong conviction buying from open to close, no wicks)"
        elif is_marubozu and not is_green:
            candle_desc = "a bearish Marubozu (relentless selling from open to close — strong bearish conviction)"
        elif is_green and body_ratio > 0.6:
            candle_desc = "a solid green candle with good body — buyers in control"
        elif not is_green and body_ratio > 0.6:
            candle_desc = "a solid red candle — sellers dominated today's session"
        elif is_green:
            candle_desc = "a green candle with notable wicks — buyers edged out but faced resistance"
        else:
            candle_desc = "a red candle with wicks — selling pressure but some support below"

        # ── Multi-System Verdicts ──
        pa = multi_sys.get("price_action", {})
        triple = multi_sys.get("triple", {})
        hybrid = multi_sys.get("hybrid", {})

        pa_signal = pa.get("signal", "N/A")
        pa_trend = pa.get("trend", "N/A")
        pa_bar = pa.get("bar_desc", "")
        pa_patterns = pa.get("patterns", [])
        triple_verdict = triple.get("verdict", "N/A")
        triple_conf = triple.get("confidence", 0)
        hybrid_verdict = hybrid.get("verdict", "N/A")

        # ── Holding Context ──
        pnl_pct = (c - buy_price) / buy_price * 100 if buy_price else 0
        pnl_dir = "profit" if pnl_pct > 0 else "loss"
        from_buy = f"{'up' if pnl_pct > 0 else 'down'} {abs(pnl_pct):.1f}% from your entry"

        # ── Squeeze Commentary ──
        squeeze_note = ""
        if squeeze:
            # Check BBW percentile
            bbw_min_6m = float(last.get("BBW_6M_Min", bbw))
            squeeze_note = "The Bollinger Squeeze is currently ON — volatility is compressed to 6-month lows. A major directional move is brewing. "
        else:
            expansion_up = bool(last.get("Expansion_Up", False))
            expansion_down = bool(last.get("Expansion_Down", False))
            if expansion_up:
                squeeze_note = "The squeeze has FIRED UPWARD — momentum is expanding bullishly. "
            elif expansion_down:
                squeeze_note = "The squeeze has FIRED DOWNWARD — bearish expansion underway. "

        # ── Volume-Price Divergence ──
        vol_price_note = ""
        if day_change_pct > 1 and vol_ratio < 0.7:
            vol_price_note = "⚠ CAUTION: Price rose on thin volume — this rally lacks conviction and may not sustain. "
        elif day_change_pct < -1 and vol_ratio < 0.7:
            vol_price_note = "The decline happened on low volume — selling pressure is mild, likely not a panic move. "
        elif day_change_pct > 1 and vol_ratio > 1.5:
            vol_price_note = "Price rose on heavy volume — institutional participation likely. This move has conviction. "
        elif day_change_pct < -1 and vol_ratio > 1.5:
            vol_price_note = "⚠ ALERT: Price fell on heavy volume — significant distribution happening. Smart money may be exiting. "

        # ── MFI/CMF Money Flow ──
        mf_note = ""
        if mfi > 80 and cmf > 0.2:
            mf_note = "Money flow is extremely strong (MFI overbought) — buyers are aggressive but watch for exhaustion. "
        elif mfi < 20 and cmf < -0.2:
            mf_note = "Money flow has dried up (MFI oversold, negative CMF) — extreme pessimism often precedes a bounce. "
        elif mfi > 60 and cmf > 0.1:
            mf_note = "Positive money flow — funds are flowing INTO this stock. "
        elif mfi < 40 and cmf < -0.1:
            mf_note = "Negative money flow — capital is draining out. "

        # ── Build the Commentary Paragraphs ──
        # Paragraph 1: Price Action Summary
        direction = "gained" if day_change > 0 else "lost" if day_change < 0 else "closed flat"
        para1 = (
            f"Today the stock {direction} ₹{abs(day_change):.2f} ({day_change_pct:+.2f}%), "
            f"opening at ₹{o:.2f}, reaching a high of ₹{h:.2f} and a low of ₹{l:.2f}, "
            f"before closing at ₹{c:.2f}. The intraday range was ₹{intraday_range:.2f} "
            f"({intraday_range_pct:.1f}% of the low). "
            f"The candle formed is {candle_desc}."
        )

        # Paragraph 2: Volume & Money Flow
        para2 = (
            f"Volume came in at {v:,} shares — {vol_desc} "
            f"({vol_ratio:.1f}x the 50-day average of {int(vol_sma):,}). "
            f"{vol_price_note}{mf_note}"
        )

        # Paragraph 3: Bollinger Band & Squeeze
        para3 = (
            f"On the Bollinger Band framework, the stock is {bb_position} "
            f"(%%B = {pct_b:.2f}). "
            f"Bands: Upper ₹{bb_upper:.2f} | Mid ₹{bb_mid:.2f} | Lower ₹{bb_lower:.2f}. "
            f"Band width is {bbw:.4f}. "
            f"{squeeze_note}"
            f"SAR is {'bullish (below price — uptrend intact)' if sar_bull else 'bearish (above price — trend is down)'}."
        )

        # Paragraph 4: Multi-System Verdict
        systems_parts = []
        if triple_verdict and triple_verdict != "N/A" and triple_verdict != "ERROR":
            systems_parts.append(f"Triple Engine (BB+TA+PA) verdict: {triple_verdict} ({triple_conf:.0f}% confidence)")
        if pa_signal and pa_signal != "N/A" and pa_signal != "ERROR":
            pa_str = f"Price Action: {pa_signal} signal"
            if pa_trend and pa_trend != "N/A":
                pa_str += f", trend is {pa_trend}"
            if pa_bar:
                pa_str += f" — last bar: {pa_bar}"
            systems_parts.append(pa_str)
        if pa_patterns:
            systems_parts.append(f"Active patterns: {', '.join(pa_patterns[:3])}")

        para4 = ""
        if systems_parts:
            para4 = "From a multi-system perspective: " + ". ".join(systems_parts) + "."

        # Paragraph 5: Expert Synthesis (the 60-year veteran speaks)
        # Determine overall tone
        bull_signals = sum([
            day_change_pct > 0.5,
            vol_ratio > 1.2 and day_change > 0,
            pct_b > 0.6,
            sar_bull,
            mfi > 55,
            cmf > 0.05,
            rsi > 50 and rsi < 70,
            pa_signal in ("BUY", "STRONG_BUY"),
            triple_verdict in ("STRONG_BUY", "BUY", "BULLISH"),
        ])
        bear_signals = sum([
            day_change_pct < -0.5,
            vol_ratio > 1.2 and day_change < 0,
            pct_b < 0.4,
            not sar_bull,
            mfi < 45,
            cmf < -0.05,
            rsi > 70,  # overbought = potential reversal
            pa_signal in ("SELL", "STRONG_SELL"),
            triple_verdict in ("STRONG_SELL", "SELL", "BEARISH"),
        ])

        if bull_signals >= 6:
            tone = "STRONGLY BULLISH"
            expert_synth = (
                f"As a 60-year market veteran, I see a textbook bullish day. Multiple systems confirm upward momentum. "
                f"You are {from_buy}. "
                f"The tape reads healthy — let your winner run but keep your trailing stop active."
            )
        elif bull_signals >= 4:
            tone = "MILDLY BULLISH"
            expert_synth = (
                f"A constructive session — more positive signals than negative. "
                f"You are {from_buy}. "
                f"The stock is holding well but hasn't broken out decisively yet. "
                f"Patience is the veteran's greatest weapon."
            )
        elif bear_signals >= 6:
            tone = "STRONGLY BEARISH"
            expert_synth = (
                f"Multiple warning signs today — I'd be very cautious. "
                f"You are {from_buy}. "
                f"When the tape speaks this loudly, a veteran listens. "
                f"Check your stops and don't average down into weakness."
            )
        elif bear_signals >= 4:
            tone = "MILDLY BEARISH"
            expert_synth = (
                f"A cautionary session — selling pressure outweighs buying today. "
                f"You are {from_buy}. "
                f"Not panic-worthy, but watch for follow-through selling tomorrow. "
                f"The market tells you early if a stock is in trouble — respect the message."
            )
        else:
            tone = "NEUTRAL"
            expert_synth = (
                f"A balanced day with mixed signals — the market hasn't decided on direction yet. "
                f"You are {from_buy}. "
                f"In 60 years of trading, I've learned: when the market doesn't tell you anything, "
                f"the best trade is no trade. Hold your position, respect your stops, wait for clarity."
            )

        # ── Combine all paragraphs ──
        full_commentary = f"{para1}\n\n{para2}\n\n{para3}"
        if para4:
            full_commentary += f"\n\n{para4}"
        full_commentary += f"\n\n💡 **Expert Take ({tone}):** {expert_synth}"

        # ── Key Stats for Frontend Cards ──
        return {
            "available": True,
            "tone": tone,
            "day_change": round(day_change, 2),
            "day_change_pct": round(day_change_pct, 2),
            "open": round(o, 2),
            "high": round(h, 2),
            "low": round(l, 2),
            "close": round(c, 2),
            "volume": v,
            "vol_ratio": round(vol_ratio, 2),
            "vol_desc": vol_desc,
            "intraday_range": round(intraday_range, 2),
            "intraday_range_pct": round(intraday_range_pct, 2),
            "candle_type": candle_desc.split("(")[0].strip() if "(" in candle_desc else candle_desc,
            "bb_position_text": bb_position,
            "pct_b": round(pct_b, 3),
            "squeeze_on": squeeze,
            "sar_bullish": sar_bull,
            "rsi": round(rsi, 1),
            "mfi": round(mfi, 1),
            "cmf": round(cmf, 4),
            "bull_signals": bull_signals,
            "bear_signals": bear_signals,
            "commentary": full_commentary,
            "para_price": para1,
            "para_volume": para2,
            "para_bollinger": para3,
            "para_systems": para4,
            "expert_synthesis": expert_synth,
            "pnl_from_buy": from_buy,
        }
    except Exception as e:
        logger.warning(f"Expert commentary generation failed: {e}")
        return {"available": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════
#  TARGET PRICE COMPUTATION
# ═══════════════════════════════════════════════════════════════

def _compute_targets(df: pd.DataFrame, buy_price: float) -> dict:
    """
    Generate target price levels based on Bollinger Bands and price action.

    Targets:
      - BB Upper:    Current upper band (resistance)
      - BB Mid:      Current middle band (support/resistance pivot)
      - BB Lower:    Current lower band (support)
      - 1-Sigma:     Mid + 1*sigma (intermediate target)
      - 2-Sigma:     Mid + 2*sigma (= BB Upper)
      - 3-Sigma:     Mid + 3*sigma (extended target if breaking upper)
      - Stop Loss:   SAR value or BB Lower, whichever is tighter
      - Risk:Reward  based on stop loss vs upper band target
    """
    row = df.iloc[-1]
    mid   = float(row["BB_Mid"])
    upper = float(row["BB_Upper"])
    lower = float(row["BB_Lower"])
    sigma = (upper - mid) / 2.0 if upper != mid else 0
    sar   = float(row["SAR"])
    price = float(row["Close"])

    # Stop loss = tighter of SAR and lower band (for long positions)
    stop_loss = max(sar, lower) if bool(row["SAR_Bull"]) else min(sar, lower)
    # For long positions stop is below price
    if stop_loss > price:
        stop_loss = lower

    # Targets
    t1_sigma = mid + sigma        # +1 sigma
    t2_sigma = upper               # +2 sigma = upper band
    t3_sigma = mid + 3 * sigma     # +3 sigma (extended)

    # 52-week high from available data
    lookback_252 = df.tail(252)
    high_52w = float(lookback_252["High"].max())
    low_52w  = float(lookback_252["Low"].min())

    # Risk:Reward ratio
    risk = buy_price - stop_loss
    reward_upper = upper - buy_price if upper > buy_price else 0
    if risk > 0 and reward_upper > 0:
        rr_ratio = round(reward_upper / risk, 2)
    elif risk <= 0:
        # Stock already above stop loss relative to buy — risk is effectively covered
        rr_ratio = 0  # N/A (already in profit relative to stop)
    else:
        rr_ratio = 0

    # Percentage distances from current price
    def pct_from(target):
        if price == 0:
            return 0
        return round((target - price) / price * 100, 2)

    return {
        "current_price":    _safe(price),
        "buy_price":        _safe(buy_price),
        "pnl_amount":       _safe(price - buy_price),
        "pnl_pct":          _safe((price - buy_price) / buy_price * 100 if buy_price else 0),
        "bb_upper":         _safe(upper),
        "bb_mid":           _safe(mid),
        "bb_lower":         _safe(lower),
        "sigma":            _safe(sigma),
        "target_1_sigma":   _safe(t1_sigma),
        "target_2_sigma":   _safe(t2_sigma),
        "target_3_sigma":   _safe(t3_sigma),
        "stop_loss":        _safe(stop_loss),
        "risk_reward":      rr_ratio,
        "high_52w":         _safe(high_52w),
        "low_52w":          _safe(low_52w),
        "pct_to_upper":     pct_from(upper),
        "pct_to_mid":       pct_from(mid),
        "pct_to_lower":     pct_from(lower),
        "pct_to_3sigma":    pct_from(t3_sigma),
        "pct_to_52w_high":  pct_from(high_52w),
    }


# ═══════════════════════════════════════════════════════════════
#  POST-PURCHASE RECOMMENDATION ENGINE
# ═══════════════════════════════════════════════════════════════

def _generate_recommendation(
    strategy_code: str,
    sig,          # Method I SignalResult
    strategies,   # [M2, M3, M4] StrategyResult list
    df: pd.DataFrame,
    buy_price: float,
) -> dict:
    """
    Generate HOLD / SELL / ADD recommendation based on the BUYING strategy
    plus confirming signals from other strategies.

    Returns dict with:
      action, strength, reasons[], warnings[], strategy_status, confirms[],
      action_triggers[], entry_quality{}, momentum{}
    """
    row = df.iloc[-1]
    price    = float(row["Close"])
    pct_b    = float(row["Percent_B"])
    mfi      = float(row["MFI"])
    cmf      = float(row["CMF"])
    sar_bull = bool(row["SAR_Bull"])
    bbw      = float(row["BBW"])
    upper    = float(row["BB_Upper"])
    mid      = float(row["BB_Mid"])
    lower    = float(row["BB_Lower"])
    sar      = float(row["SAR"])
    volume   = float(row["Volume"])
    vol_sma  = float(row["Vol_SMA50"]) if not math.isnan(row["Vol_SMA50"]) else 0

    m2 = strategies[0]
    m3 = strategies[1]
    m4 = strategies[2]

    reasons  = []
    warnings = []
    confirms = []
    action_triggers = []
    action   = "HOLD"
    strength = "MODERATE"

    # ── Entry Quality Assessment ──
    pnl_pct = (price - buy_price) / buy_price * 100 if buy_price else 0
    if buy_price <= lower:
        entry_zone = "EXCELLENT"
        entry_note = "Bought at or below lower band — textbook entry"
    elif buy_price <= mid:
        entry_zone = "GOOD"
        entry_note = "Bought between lower and mid band — favorable entry"
    elif buy_price <= upper:
        entry_zone = "FAIR"
        entry_note = "Bought between mid and upper band — average entry"
    else:
        entry_zone = "LATE"
        entry_note = "Bought above upper band — potentially chasing"

    entry_quality = {
        "zone": entry_zone,
        "note": entry_note,
        "buy_vs_mid_pct": _safe((buy_price - mid) / mid * 100 if mid else 0),
        "current_vs_buy_pct": _safe(pnl_pct),
    }

    # ── Momentum Assessment (last 5 bars) ──
    recent = df.tail(5)
    pct_b_slope = float(recent["Percent_B"].iloc[-1] - recent["Percent_B"].iloc[0])
    mfi_slope = float(recent["MFI"].iloc[-1] - recent["MFI"].iloc[0])
    vol_trend = "RISING" if volume > vol_sma * 1.1 else ("FADING" if volume < vol_sma * 0.8 else "NORMAL")
    bbw_expanding = float(df.tail(10)["BBW"].iloc[-1]) > float(df.tail(10)["BBW"].iloc[0])

    if pct_b_slope > 0.1 and mfi_slope > 5:
        momentum_label = "STRONG BULLISH"
    elif pct_b_slope > 0 and mfi_slope > 0:
        momentum_label = "BULLISH"
    elif pct_b_slope < -0.1 and mfi_slope < -5:
        momentum_label = "STRONG BEARISH"
    elif pct_b_slope < 0 and mfi_slope < 0:
        momentum_label = "BEARISH"
    else:
        momentum_label = "NEUTRAL"

    momentum = {
        "label": momentum_label,
        "pct_b_slope": _safe(pct_b_slope, 3),
        "mfi_slope": _safe(mfi_slope, 1),
        "volume_trend": vol_trend,
        "bbw_expanding": bbw_expanding,
    }

    # ── Strategy-specific primary signal ──
    if strategy_code == "M1":
        # Bought on squeeze breakout — check if breakout is still valid
        if sig.sell_signal:
            action = "SELL"
            strength = "STRONG"
            if sig.exit_sar_flip:
                reasons.append("SAR has flipped bearish — trend reversal confirmed")
            if sig.exit_lower_band_tag:
                reasons.append("Price tagged the lower Bollinger Band")
            if sig.exit_double_neg:
                reasons.append("Both CMF and MFI are negative — money outflow")
            action_triggers.append(f"EXIT NOW: SAR at ₹{sar:.2f} is above price — bearish confirmation")
        elif sig.hold_signal:
            action = "HOLD"
            reasons.append(f"SAR bullish, price above mid band, CMF & MFI supportive")
            if pct_b > 0.8 and mfi > 60:
                strength = "STRONG"
                reasons.append("Strong uptrend: %b > 0.8 with MFI confirmation")
            action_triggers.append(f"SELL if SAR flips bearish (SAR crosses above ₹{price:.2f})")
            action_triggers.append(f"SELL if price closes below ₹{lower:.2f} (lower band)")
            action_triggers.append(f"BOOK PARTIAL if price reaches ₹{upper:.2f} (upper band)")
        elif sig.buy_signal:
            action = "ADD"
            strength = "STRONG"
            reasons.append("Fresh squeeze breakout signal — consider adding to position")
            action_triggers.append(f"ADD on volume confirmation (current vol vs SMA50: {volume/vol_sma:.1f}x)" if vol_sma > 0 else "ADD on volume confirmation")
        else:
            # Squeeze ON but no buy/sell
            action = "HOLD"
            strength = "WEAK"
            reasons.append("Squeeze is active — waiting for directional breakout")
            if sig.direction_lean == "BULLISH":
                reasons.append("Direction lean is BULLISH — breakout likely upward")
            elif sig.direction_lean == "BEARISH":
                reasons.append("Direction lean is BEARISH — downside risk")
                warnings.append("Squeeze may resolve downward — tighten stop loss")
            action_triggers.append(f"BUY/ADD if price breaks above ₹{upper:.2f} with volume")
            action_triggers.append(f"SELL if price breaks below ₹{lower:.2f}")

    elif strategy_code == "M2":
        sig_type = m2.signal.signal_type
        if sig_type == "BUY":
            action = "ADD"
            strength = m2.signal.strength
            reasons.append(f"Method II confirms trend: %b={pct_b:.2f}, MFI={mfi:.0f}")
            action_triggers.append(f"ADD while %b stays above {M2_PCT_B_BUY_THRESHOLD} with MFI > {M2_MFI_CONFIRM_BUY}")
            action_triggers.append(f"SELL if %b drops below 0.5 (currently {pct_b:.2f})")
        elif sig_type == "SELL":
            action = "SELL"
            strength = m2.signal.strength
            reasons.append(f"Method II sell: %b={pct_b:.2f}, MFI={mfi:.0f} — both weak")
            action_triggers.append(f"EXIT: %b is below {M2_PCT_B_SELL_THRESHOLD} with MFI < {M2_MFI_CONFIRM_SELL}")
        elif sig_type == "HOLD":
            action = "HOLD"
            strength = "MODERATE"
            reasons.append(f"Trend intact: %b={pct_b:.2f}, MFI={mfi:.0f}")
            action_triggers.append(f"SELL if %b drops below {M2_PCT_B_SELL_THRESHOLD} (currently {pct_b:.2f})")
            action_triggers.append(f"ADD if %b rises above {M2_PCT_B_BUY_THRESHOLD} with MFI > {M2_MFI_CONFIRM_BUY}")
        elif sig_type == "WATCH":
            action = "HOLD"
            strength = "WEAK"
            reasons.append(f"Divergence detected — {m2.signal.reason}")
            warnings.append("Divergence between %b and MFI — trend may weaken")
            action_triggers.append("WATCH: Divergence may lead to reversal — tighten stop to mid band")
        else:
            action = "HOLD"
            strength = "WEAK"
            reasons.append("No clear Method II signal — hold and monitor")

    elif strategy_code == "M3":
        sig_type = m3.signal.signal_type
        if sig_type == "BUY":
            action = "ADD"
            strength = m3.signal.strength
            reasons.append(f"W-Bottom confirmed — reversal pattern active")
            if m3.patterns:
                p = m3.patterns[-1]
                reasons.append(f"Pattern: {p.description}")
            action_triggers.append(f"HOLD for rally toward mid band ₹{mid:.2f} then upper band ₹{upper:.2f}")
            action_triggers.append(f"SELL if price breaks below ₹{lower:.2f} (pattern failure)")
        elif sig_type == "SELL":
            action = "SELL"
            strength = m3.signal.strength
            reasons.append(f"M-Top detected — reversal to downside expected")
            if m3.patterns:
                p = m3.patterns[-1]
                reasons.append(f"Pattern: {p.description}")
            action_triggers.append(f"EXIT: M-Top confirms head at upper band — expect drop to ₹{mid:.2f}")
        else:
            action = "HOLD"
            strength = "MODERATE"
            reasons.append("No reversal pattern currently — hold position")
            action_triggers.append(f"WATCH for W-Bottom if price retests ₹{lower:.2f}")
            action_triggers.append(f"WATCH for M-Top if price retests ₹{upper:.2f}")

    elif strategy_code == "M4":
        sig_type = m4.signal.signal_type
        if sig_type == "HOLD":
            action = "HOLD"
            strength = m4.signal.strength
            reasons.append("Walking the upper band — strong uptrend continues")
            action_triggers.append(f"HOLD while price stays above mid band ₹{mid:.2f}")
            action_triggers.append(f"SELL if price closes below mid band (band walk break)")
        elif sig_type == "SELL":
            action = "SELL"
            strength = m4.signal.strength
            reasons.append(f"Band walk breaking: {m4.signal.reason}")
            action_triggers.append(f"EXIT: Band walk broken — expect mean reversion to ₹{mid:.2f}")
        elif sig_type == "BUY":
            action = "ADD"
            strength = m4.signal.strength
            reasons.append("Lower band walk breaking — reversal opportunity")
            action_triggers.append(f"ADD if reversal confirmed with MFI > 50 (currently {mfi:.0f})")
        else:
            action = "HOLD"
            strength = "WEAK"
            reasons.append("No active band walk — hold and monitor")
            action_triggers.append(f"WATCH for upper band walk if %b sustains > {M4_WALK_PCT_B_UPPER}")

    # ── Cross-strategy confirmation ──
    if m2.signal.signal_type == "BUY":
        confirms.append("M2 Trend Following: BUY confirmed (%b + MFI aligned)")
    elif m2.signal.signal_type == "SELL":
        confirms.append("M2 Trend Following: SELL — trend weakening")
    elif m2.signal.signal_type == "HOLD":
        confirms.append("M2 Trend Following: HOLD — trend intact")

    if m3.signal.signal_type == "BUY":
        confirms.append("M3 Reversals: W-Bottom pattern detected")
    elif m3.signal.signal_type == "SELL":
        confirms.append("M3 Reversals: M-Top pattern — potential reversal")

    if m4.signal.signal_type == "HOLD":
        confirms.append("M4 Band Walking: Upper band walk active — strong trend")
    elif m4.signal.signal_type == "SELL":
        confirms.append("M4 Band Walking: Walk breaking — momentum fading")

    if sig.sell_signal:
        confirms.append("M1 Squeeze: EXIT signals triggered")
    elif sig.hold_signal:
        confirms.append("M1 Squeeze: HOLD — technicals supportive")

    # ── Universal warnings ──
    if cmf < 0 and action != "SELL":
        warnings.append(f"CMF is negative ({cmf:.3f}) — money outflow detected")
    if mfi < 40 and action != "SELL":
        warnings.append(f"MFI is low ({mfi:.0f}) — buying pressure weak")
    if not sar_bull and action != "SELL":
        warnings.append("SAR is bearish (dots above price) — caution")
    if price < buy_price:
        loss_pct = (buy_price - price) / buy_price * 100
        if loss_pct > 10:
            warnings.append(f"Position is down {loss_pct:.1f}% — review stop loss")
        elif loss_pct > 5:
            warnings.append(f"Position is down {loss_pct:.1f}% — monitor closely")

    # ── Momentum-based refinements ──
    if "BEARISH" in momentum_label and action == "HOLD":
        strength = "WEAK"
        warnings.append(f"Momentum turning bearish (%b slope: {pct_b_slope:+.3f}, MFI slope: {mfi_slope:+.1f})")
    if vol_trend == "FADING" and action == "HOLD":
        warnings.append("Volume fading below 50-day average — conviction thinning")

    # ── If multiple strategies say SELL, upgrade strength ──
    sell_count = sum(1 for s in [m2, m3, m4] if s.signal.signal_type == "SELL")
    if sell_count >= 2 and action != "SELL":
        action = "SELL"
        strength = "STRONG"
        reasons.append("Multiple strategies confirm sell signal")

    return {
        "action":          action,
        "strength":        strength,
        "reasons":         reasons,
        "warnings":        warnings,
        "confirms":        confirms,
        "action_triggers": action_triggers,
        "entry_quality":   entry_quality,
        "momentum":        momentum,
        "strategy_code":   strategy_code,
    }


# ═══════════════════════════════════════════════════════════════
#  MULTI-SYSTEM ANALYSIS (Hybrid + Triple + PA)
# ═══════════════════════════════════════════════════════════════

def _run_multi_system(df_raw: pd.DataFrame, ticker: str, buy_price: float) -> dict:
    """
    Run Hybrid (BB+TA), Triple (BB+TA+PA), and standalone PA engines.
    Returns condensed results for each system + a master summary.
    """
    results = {}

    # 1. Triple Engine (BB + TA + PA) — replaces old hybrid engine
    try:
        triple = run_triple_analysis(df_raw, ticker=ticker)
        tv = triple.get("triple_verdict", {})
        pa_d = triple.get("pa_data", {})
        pa_s = triple.get("pa_score", {})
        cv = triple.get("cross_validation", {})
        # Provide backward-compatible "hybrid" key with triple data
        results["hybrid"] = {
            "verdict":    tv.get("verdict", "N/A"),
            "score":      _safe(tv.get("score", 0)),
            "max_score":  tv.get("max_score", 390),
            "confidence": _safe(tv.get("confidence", 0)),
            "alignment":  cv.get("alignment", "N/A"),
            "bb_score":   _safe(triple.get("bb_score", {}).get("total", 0)),
            "ta_score":   _safe(triple.get("ta_score", {}).get("total", 0)),
            "ta_verdict": triple.get("ta_signal", {}).get("verdict", "N/A"),
        }
        results["triple"] = {
            "verdict":     tv.get("verdict", "N/A"),
            "score":       _safe(tv.get("score", 0)),
            "max_score":   tv.get("max_score", 390),
            "confidence":  _safe(tv.get("confidence", 0)),
            "alignment":   cv.get("alignment", "N/A"),
            "bb_score":    _safe(triple.get("bb_score", {}).get("total", 0)),
            "ta_score":    _safe(triple.get("ta_score", {}).get("total", 0)),
            "pa_score":    _safe(pa_s.get("total", 0)),
        }
        # [VILLAHERMOSA] Extract Wyckoff data from triple engine
        wyckoff_raw = triple.get("wyckoff")
        if wyckoff_raw:
            wk_phase = wyckoff_raw.get("phase", {})
            results["wyckoff"] = {
                "phase":       wk_phase.get("name", "UNKNOWN"),
                "sub_phase":   wk_phase.get("sub_phase", "UNKNOWN"),
                "confidence":  wk_phase.get("confidence", 0),
                "bias":        wyckoff_raw.get("scoring", {}).get("bias", "NEUTRAL"),
                "bonus":       wyckoff_raw.get("scoring", {}).get("wyckoff_bonus", 0),
                "volume":      wyckoff_raw.get("volume", {}),
                "wave_balance": wyckoff_raw.get("wave_balance", {}),
                "shortening":  wyckoff_raw.get("shortening", {}),
                "events":      wk_phase.get("events", []),
                "hints":       wyckoff_raw.get("hints", []),
                "summary":     wyckoff_raw.get("summary", ""),
            }
        else:
            results["wyckoff"] = None

        # [DALTON] Extract Market Profile data from triple engine
        mp_raw = triple.get("market_profile")
        if mp_raw:
            results["dalton"] = {
                "value_area":     mp_raw.get("value_area", {}),
                "day_type":       mp_raw.get("day_type", {}),
                "open_type":      mp_raw.get("open_type", "UNKNOWN"),
                "open_vs_prev":   mp_raw.get("open_vs_prev", {}),
                "activity":       mp_raw.get("activity", "UNKNOWN"),
                "directional_performance": mp_raw.get("directional_performance", {}),
                "market_structure": mp_raw.get("market_structure", {}),
                "one_timeframing": mp_raw.get("one_timeframing", {}),
                "poor_extremes":  mp_raw.get("poor_extremes", {}),
                "profile_shape":  mp_raw.get("profile_shape", "NORMAL"),
                "high_probability": mp_raw.get("high_probability", {}),
                "gap":            mp_raw.get("gap", {}),
                "overnight_inventory": mp_raw.get("overnight_inventory", "NEUTRAL"),
                "rotation_factor": mp_raw.get("rotation_factor", 0),
                "poc_migration":  mp_raw.get("poc_migration", "STATIONARY"),
                "va_sequence":    mp_raw.get("va_sequence", []),
                "scoring":        mp_raw.get("scoring", {}),
                "dalton_signals": mp_raw.get("dalton_signals", []),
                "observations":   mp_raw.get("observations", []),
                "summary":        mp_raw.get("summary", ""),
            }
        else:
            results["dalton"] = None
    except Exception:
        results["hybrid"] = {"verdict": "ERROR", "score": 0, "max_score": 390,
                             "confidence": 0, "alignment": "N/A", "bb_score": 0, "ta_score": 0, "ta_verdict": "N/A"}
        results["triple"] = {"verdict": "ERROR", "score": 0, "max_score": 390,
                             "confidence": 0, "alignment": "N/A", "bb_score": 0, "ta_score": 0, "pa_score": 0}
        results["wyckoff"] = None
        results["dalton"] = None
    try:
        pa_result = run_price_action_analysis(df_raw, ticker=ticker)
        results["price_action"] = {
            "signal":        pa_result.signal_type,
            "setup":         pa_result.setup_type,
            "strength":      pa_result.strength,
            "confidence":    pa_result.confidence,
            "pa_score":      _safe(pa_result.pa_score),
            "always_in":     pa_result.always_in,
            "trend":         pa_result.trend_direction,
            "stop_loss":     _safe(pa_result.stop_loss),
            "target_1":      _safe(pa_result.target_1),
            "target_2":      _safe(pa_result.target_2),
            "risk_reward":   _safe(pa_result.risk_reward),
            "bar_type":      pa_result.last_bar_type,
            "bar_desc":      pa_result.last_bar_description,
            "patterns":      pa_result.active_patterns[:5] if pa_result.active_patterns else [],
            "context":       pa_result.al_brooks_context,
            "reasons":       pa_result.reasons[:5] if pa_result.reasons else [],
        }
    except Exception:
        results["price_action"] = {"signal": "ERROR", "setup": "N/A", "strength": "N/A",
                                   "confidence": 0, "pa_score": 0, "always_in": "N/A",
                                   "trend": "N/A", "stop_loss": None, "target_1": None,
                                   "target_2": None, "risk_reward": None, "bar_type": "N/A",
                                   "bar_desc": "", "patterns": [], "context": "", "reasons": []}

    # 4. Master Summary — plain language
    results["master_summary"] = _build_master_summary(results, buy_price)

    return results


def _build_master_summary(systems: dict, buy_price: float) -> dict:
    """
    Combine all system verdicts into one clear, plain-language recommendation.
    Does NOT override the BB-based recommendation — this is an additional perspective.
    """
    hybrid = systems.get("hybrid", {})
    triple = systems.get("triple", {})
    pa = systems.get("price_action", {})

    # Count consensus
    votes = {"BUY": 0, "SELL": 0, "HOLD": 0}
    system_opinions = []

    # Hybrid verdict
    hv = hybrid.get("verdict", "N/A")
    if "BUY" in hv:
        votes["BUY"] += 1
        system_opinions.append(("Hybrid (BB+TA)", "BULLISH", hv))
    elif "SELL" in hv:
        votes["SELL"] += 1
        system_opinions.append(("Hybrid (BB+TA)", "BEARISH", hv))
    else:
        votes["HOLD"] += 1
        system_opinions.append(("Hybrid (BB+TA)", "NEUTRAL", hv))

    # Triple verdict
    tv = triple.get("verdict", "N/A")
    if "BUY" in tv:
        votes["BUY"] += 1
        system_opinions.append(("Triple (BB+TA+PA)", "BULLISH", tv))
    elif "SELL" in tv:
        votes["SELL"] += 1
        system_opinions.append(("Triple (BB+TA+PA)", "BEARISH", tv))
    else:
        votes["HOLD"] += 1
        system_opinions.append(("Triple (BB+TA+PA)", "NEUTRAL", tv))

    # PA standalone
    pa_sig = pa.get("signal", "N/A")
    if pa_sig == "BUY":
        votes["BUY"] += 1
        system_opinions.append(("Price Action (Al Brooks)", "BULLISH", f"BUY — {pa.get('setup', 'N/A')}"))
    elif pa_sig == "SELL":
        votes["SELL"] += 1
        system_opinions.append(("Price Action (Al Brooks)", "BEARISH", f"SELL — {pa.get('setup', 'N/A')}"))
    else:
        votes["HOLD"] += 1
        system_opinions.append(("Price Action (Al Brooks)", "NEUTRAL", f"HOLD — {pa.get('always_in', 'N/A')}"))

    # Determine consensus
    total_systems = 3
    dominant = max(votes, key=votes.get)
    dominant_count = votes[dominant]

    if dominant_count == 3:
        consensus = "STRONG"
        agreement = "ALL AGREE"
    elif dominant_count == 2:
        consensus = "MODERATE"
        agreement = "MAJORITY"
    else:
        consensus = "MIXED"
        agreement = "SPLIT"

    # Overall direction
    if dominant == "BUY":
        direction = "BULLISH"
        action_word = "HOLD / ADD"
    elif dominant == "SELL":
        direction = "BEARISH"
        action_word = "SELL / EXIT"
    else:
        direction = "NEUTRAL"
        action_word = "HOLD / WAIT"

    # Confidence average across systems (weighted)
    conf_vals = [hybrid.get("confidence", 0), triple.get("confidence", 0), pa.get("confidence", 0)]
    avg_confidence = round(sum(c for c in conf_vals if c) / max(1, sum(1 for c in conf_vals if c)), 1)

    # Build plain-language explanation
    plain_lines = []

    if consensus == "STRONG" and direction == "BULLISH":
        plain_lines.append("All 3 analysis systems are saying this stock looks good right now.")
        plain_lines.append("The Bollinger Band indicators, Technical Analysis, and Price Action patterns all point upward.")
        plain_lines.append("This is a strong position — you can hold with confidence or consider adding more if you want.")
    elif consensus == "STRONG" and direction == "BEARISH":
        plain_lines.append("All 3 systems are warning that this stock is weakening.")
        plain_lines.append("Bollinger Bands, Technical indicators, and Price Action all point downward.")
        plain_lines.append("Consider reducing your position or setting a tight stop loss to protect your capital.")
    elif consensus == "MODERATE" and direction == "BULLISH":
        plain_lines.append("2 out of 3 systems are positive on this stock.")
        dissenting = [s[0] for s in system_opinions if s[1] != "BULLISH"]
        if dissenting:
            plain_lines.append(f"Only {dissenting[0]} is not fully aligned, but the majority favors holding.")
        plain_lines.append("You can continue holding. Watch for the dissenting system to also turn positive for more confidence.")
    elif consensus == "MODERATE" and direction == "BEARISH":
        plain_lines.append("2 out of 3 systems suggest caution on this stock.")
        supporting = [s[0] for s in system_opinions if s[1] == "BULLISH"]
        if supporting:
            plain_lines.append(f"Only {supporting[0]} is still positive.")
        plain_lines.append("Consider tightening your stop loss. If the last system also turns negative, it may be time to exit.")
    elif consensus == "MODERATE" and direction == "NEUTRAL":
        plain_lines.append("The systems mostly say to wait and watch.")
        plain_lines.append("There is no strong buying or selling pressure right now.")
        plain_lines.append("Hold your position but keep monitoring for any change in signals.")
    else:
        plain_lines.append("The 3 systems are giving different signals — this means the market is undecided about this stock.")
        plain_lines.append("When systems disagree, it's best to hold your current position and avoid adding more money.")
        plain_lines.append("Wait for at least 2 systems to agree before making any move.")

    # Price Action context (always useful)
    always_in = pa.get("always_in", "N/A")
    if always_in in ("BULLISH", "LONG"):
        plain_lines.append("Price Action shows the 'Always-In' direction is LONG — the trend favors buyers.")
    elif always_in in ("BEARISH", "SHORT"):
        plain_lines.append("Price Action shows 'Always-In' direction is SHORT — sellers are in control currently.")
    else:
        plain_lines.append("Price Action shows the market is sideways — no clear trend.")

    # PA patterns
    pa_patterns = pa.get("patterns", [])
    if pa_patterns:
        plain_lines.append(f"Active price patterns: {', '.join(pa_patterns[:3])}.")

    # [VILLAHERMOSA] Wyckoff phase context
    wyckoff = systems.get("wyckoff")
    if wyckoff and wyckoff.get("phase", "UNKNOWN") != "UNKNOWN":
        wk_phase = wyckoff.get("phase", "UNKNOWN")
        wk_hints = wyckoff.get("hints", [])
        if wk_phase == "ACCUMULATION":
            plain_lines.append("📊 Wyckoff Analysis: Smart money appears to be ACCUMULATING (quietly buying). "
                               "This is often a good sign for holders.")
        elif wk_phase == "DISTRIBUTION":
            plain_lines.append("📊 Wyckoff Analysis: Smart money appears to be DISTRIBUTING (quietly selling). "
                               "Be on alert — the smart money may be exiting.")
        elif wk_phase == "MARKUP":
            wk_sub = wyckoff.get("sub_phase", "")
            if wk_sub == "LATE":
                plain_lines.append("📊 Wyckoff Analysis: The stock is in LATE MARKUP — the uptrend has been "
                                   "running for a while and may be getting tired. Like a marathon runner "
                                   "approaching the finish line. Hold your position but tighten stops and "
                                   "watch for exhaustion signals (shorter rallies, declining volume on up-moves).")
            elif wk_sub == "CONFIRMED":
                plain_lines.append("📊 Wyckoff Analysis: The stock is in CONFIRMED MARKUP — this is the sweet spot. "
                                   "Prices are rising with genuine buying volume behind them. Like a river flowing "
                                   "strongly uphill. Small dips on low volume are buying opportunities.")
            elif wk_sub == "MIDDLE":
                plain_lines.append("📊 Wyckoff Analysis: The stock is in MIDDLE MARKUP — the uptrend is real but "
                                   "not yet fully powered by volume. Buyers have shown strength. Hold your "
                                   "position and watch for volume to confirm the next rally.")
            else:  # EARLY
                plain_lines.append("📊 Wyckoff Analysis: The stock is in EARLY MARKUP — the uptrend is just starting. "
                                   "Like a plane gaining speed on the runway. Promising structure, but volume hasn't "
                                   "fully confirmed the move yet. Watch the next rally's volume closely.")
        elif wk_phase == "MARKDOWN":
            wk_sub = wyckoff.get("sub_phase", "")
            if wk_sub == "LATE":
                plain_lines.append("📊 Wyckoff Analysis: The stock is in LATE MARKDOWN — the decline has been "
                                   "running for a while and may be nearing exhaustion. Watch for panic selling "
                                   "with a big volume spike (Selling Climax) — that often marks the bottom.")
            elif wk_sub == "CONFIRMED":
                plain_lines.append("📊 Wyckoff Analysis: The stock is in CONFIRMED MARKDOWN — supply is overwhelming "
                                   "demand and prices are falling steadily. Any small bounces on low volume are "
                                   "NOT buying opportunities — they're the last exit points before more downside.")
            else:
                plain_lines.append("📊 Wyckoff Analysis: The stock is in MARKDOWN phase — "
                                   "supply is overwhelming demand. Consider protecting capital.")
        # Add the first 2 layman hints from Wyckoff
        for hint in wk_hints[:2]:
            plain_lines.append(f"  → {hint}")

    # [DALTON] Market Profile context
    dalton = systems.get("dalton")
    if dalton and dalton.get("day_type", {}).get("type", "UNKNOWN") != "UNKNOWN":
        dt = dalton["day_type"]["type"]
        ms = dalton.get("market_structure", {}).get("type", "UNKNOWN")
        dp_rating = dalton.get("directional_performance", {}).get("rating", "NEUTRAL")
        dp_dir = dalton.get("directional_performance", {}).get("direction", "NEUTRAL")
        ot = dalton.get("open_type", "UNKNOWN")
        otf = dalton.get("one_timeframing", {}).get("direction", "NONE")
        otf_days = dalton.get("one_timeframing", {}).get("days", 0)

        # Market structure context
        if ms == "TRENDING_UP":
            plain_lines.append("📈 Dalton Market Profile: The market structure is TRENDING UP — "
                               "value areas are consistently moving higher day after day.")
        elif ms == "TRENDING_DOWN":
            plain_lines.append("📉 Dalton Market Profile: The market structure is TRENDING DOWN — "
                               "value areas are moving lower. Sellers are in control.")
        elif ms == "BRACKETING":
            bd = dalton.get("market_structure", {}).get("bracket_days", 0)
            plain_lines.append(f"📊 Dalton Market Profile: Market is BRACKETING (sideways) for "
                               f"{bd} days — value areas are overlapping, no clear direction.")
        elif ms == "TRANSITIONING":
            plain_lines.append("🔄 Dalton Market Profile: Market structure is TRANSITIONING — "
                               "a new trend may be forming. Watch closely.")

        # One-timeframing
        if otf in ("UP", "DOWN") and otf_days >= 2:
            otf_word = "upward" if otf == "UP" else "downward"
            plain_lines.append(f"  → One-timeframing {otf_word} for {otf_days} days — "
                               f"strong directional conviction from institutional traders.")

        # High-probability setups
        hp = dalton.get("high_probability", {})
        if hp.get("three_to_i", {}).get("active"):
            ti_dir = hp["three_to_i"].get("direction", "")
            plain_lines.append(f"  → ⚡ 3-to-I Day setup detected ({ti_dir}) — "
                               "this pattern has 94% historical follow-through probability!")
        if hp.get("neutral_extreme", {}).get("active"):
            ne_dir = hp["neutral_extreme"].get("direction", "")
            plain_lines.append(f"  → ⚡ Neutral-Extreme Day ({ne_dir}) — "
                               "92% probability of follow-through tomorrow!")
        if hp.get("balance_breakout", {}).get("active"):
            bb_dir = hp["balance_breakout"].get("direction", "")
            plain_lines.append(f"  → ⚡ Balance-Area Breakout ({bb_dir}) — "
                               "price broke out of a sideways range with conviction.")

    # Score context
    triple_score = triple.get("score", 0)
    triple_max = triple.get("max_score", 360)
    if triple_score is not None and triple_max:
        pct = abs(triple_score) / triple_max * 100
        if triple_score > 0:
            plain_lines.append(f"The combined conviction score is +{triple_score}/{triple_max} — this is {_score_grade(pct)} bullish.")
        elif triple_score < 0:
            plain_lines.append(f"The combined conviction score is {triple_score}/{triple_max} — this is {_score_grade(pct)} bearish.")

    return {
        "consensus":        consensus,
        "agreement":        agreement,
        "direction":        direction,
        "action_word":      action_word,
        "votes":            votes,
        "system_opinions":  system_opinions,
        "avg_confidence":   avg_confidence,
        "plain_text":       plain_lines,
    }


def _score_grade(pct: float) -> str:
    if pct >= 50:
        return "strongly"
    elif pct >= 25:
        return "moderately"
    else:
        return "mildly"


# ═══════════════════════════════════════════════════════════════
#  VINCE RISK & MONEY MANAGEMENT PER POSITION
# ═══════════════════════════════════════════════════════════════

def _compute_vince_risk(
    ticker: str,
    buy_price: float,
    quantity: int,
    account_equity: float = 100000,
    period: int = 252,
) -> dict:
    """
    Compute Vince risk metrics for a single portfolio position.

    Combines optimal f, position sizing, drawdown, volatility,
    and dependency tests into a single risk profile dict.

    Returns dict with keys:
      optimal_f, biggest_loss, geometric_mean, twr, ahpr, sd_hpr,
      position_sizing (at 50% f), drawdown, volatility,
      sizing_status, risk_grade, dependency (runs + serial corr),
      time_to_double, kelly_f
    """
    df = load_stock_data(ticker, csv_dir=CSV_DIR)
    if df is None or len(df) < 50:
        return {"error": f"Insufficient data for Vince analysis on {ticker}"}

    closes = df["Close"].tail(period + 1).values.astype(float)
    if len(closes) < 20:
        return {"error": "Not enough price history"}

    daily_changes = list(np.diff(closes))
    last_price = float(closes[-1])

    result = {}

    # ── Optimal f ──
    opt = find_optimal_f_empirical(daily_changes)
    result["optimal_f"] = opt["optimal_f"]
    result["biggest_loss"] = opt["biggest_loss"]

    if opt["optimal_f"] <= 0:
        result["error"] = "Could not compute optimal f"
        return result

    # ── By-products ──
    bp = compute_by_products(daily_changes, opt["optimal_f"])
    result["geometric_mean"] = bp.get("geometric_mean")
    result["twr"] = bp.get("twr")
    result["ahpr"] = bp.get("ahpr")
    result["sd_hpr"] = bp.get("sd_hpr")

    # ── Position sizing at 50% f (conservative) ──
    ps = position_sizing(account_equity, opt["optimal_f"],
                         opt["biggest_loss"], last_price, 0.5)
    result["position_sizing"] = ps
    recommended = ps.get("shares_to_buy", 0)
    result["recommended_shares"] = recommended
    result["risk_per_trade"] = ps.get("risk_per_trade")
    result["f_dollar"] = ps.get("f_dollar")

    # ── Sizing status ──
    if quantity > 0 and recommended > 0:
        ratio = quantity / recommended
        if ratio > 1.3:
            result["sizing_status"] = "OVERSIZED"
        elif ratio < 0.7:
            result["sizing_status"] = "UNDERSIZED"
        else:
            result["sizing_status"] = "OPTIMAL"
        result["sizing_ratio"] = round(ratio, 2)
    else:
        result["sizing_status"] = "N/A"
        result["sizing_ratio"] = 0

    # ── Drawdown ──
    eq = [account_equity]
    for t in daily_changes:
        eq.append(eq[-1] + t)
    dd = drawdown_analysis(eq)
    result["max_drawdown_pct"] = dd.get("max_drawdown_pct")
    result["current_drawdown_pct"] = dd.get("current_drawdown_pct", 0)
    result["avg_drawdown_pct"] = dd.get("avg_drawdown_pct")

    # ── Volatility ──
    if len(closes) > 21:
        vol = historical_volatility(list(closes))
        result["volatility_pct"] = vol.get("current_volatility_pct")
        result["avg_volatility_pct"] = vol.get("average_volatility_pct")
        result["volatility_label"] = (
            "HIGH" if vol.get("current_volatility_pct", 0) > vol.get("average_volatility_pct", 999) * 1.5
            else "LOW" if vol.get("current_volatility_pct", 0) < vol.get("average_volatility_pct", 0) * 0.5
            else "NORMAL"
        )

    # ── Time to double ──
    gm = bp.get("geometric_mean", 0)
    if gm and gm > 1:
        ttd = time_to_goal(gm, 2.0)
        result["time_to_double"] = ttd.get("trades_needed")

    # ── Kelly fraction ──
    wins = [t for t in daily_changes if t > 0]
    losses = [t for t in daily_changes if t < 0]
    if wins and losses:
        wp = len(wins) / len(daily_changes)
        wlr = (sum(wins) / len(wins)) / abs(sum(losses) / len(losses))
        kelly = wp - (1 - wp) / wlr if wlr > 0 else 0
        result["kelly_f"] = round(kelly, 4)

    # ── Dependency tests (runs + serial corr) ──
    rt = runs_test(daily_changes)
    sc = serial_correlation(daily_changes)
    result["dependency"] = {
        "runs_independent": rt.get("is_random"),
        "serial_corr": sc.get("correlation"),
        "serial_significant": sc.get("is_dependent"),
    }

    # ── Overall risk grade (mathematical composite) ──
    # Grade = f(max_drawdown, volatility, sizing_status, optimal_f)
    score = 0
    # Drawdown contribution (0-30): lower drawdown = safer
    max_dd = abs(result.get("max_drawdown_pct", 0))
    if max_dd < 5:
        score += 30
    elif max_dd < 15:
        score += 20
    elif max_dd < 30:
        score += 10

    # Volatility contribution (0-25)
    vol_pct = result.get("volatility_pct", 0)
    if vol_pct and vol_pct < 20:
        score += 25
    elif vol_pct and vol_pct < 35:
        score += 15
    elif vol_pct and vol_pct < 50:
        score += 5

    # Sizing contribution (0-25)
    if result.get("sizing_status") == "OPTIMAL":
        score += 25
    elif result.get("sizing_status") == "UNDERSIZED":
        score += 15
    # OVERSIZED gets 0

    # Geometric mean contribution (0-20): > 1 means profitable system
    if gm and gm > 1.001:
        score += 20
    elif gm and gm > 1.0:
        score += 10

    if score >= 75:
        result["risk_grade"] = "LOW RISK"
    elif score >= 50:
        result["risk_grade"] = "MODERATE RISK"
    elif score >= 25:
        result["risk_grade"] = "HIGH RISK"
    else:
        result["risk_grade"] = "VERY HIGH RISK"
    result["risk_score"] = score

    return result


# ═══════════════════════════════════════════════════════════════
#  MAIN ANALYSIS FUNCTION
# ═══════════════════════════════════════════════════════════════

def analyze_position(position: dict, light: bool = False) -> dict:
    """
    Full daily analysis for a single portfolio position.

    Args:
        position: dict from portfolio_db with keys:
            ticker, strategy_code, buy_price, buy_date, quantity, status, ...
        light: if True, skip the slow network-bound work (fundamentals snapshot,
            multi-system Triple/Wyckoff/Dalton, benchmark alpha, expert
            commentary). Used for the portfolio table where we only need
            recommendation + risk badges. Cuts ~5–10s per position.

    Returns:
        dict with: position, indicators, strategy_signals, recommendation,
                   targets, holding_info, error (if any)
    """
    ticker_raw = position["ticker"]
    strategy_code = position["strategy_code"]
    buy_price = float(position["buy_price"])

    ticker = normalise_ticker(ticker_raw)

    # 1. Load & compute indicators
    df = load_stock_data(ticker, csv_dir=CSV_DIR)
    if df is None or len(df) < 50:
        return {
            "position": position,
            "error": f"Insufficient data for {ticker}",
        }

    df_with_ind = compute_all_indicators(df)
    last = df_with_ind.iloc[-1]

    # 2. Run Method I
    sig = analyze_signals(ticker, df_with_ind)

    # 3. Run Methods II, III, IV
    strats = run_all_strategies(df_with_ind)

    # 4. Compute targets
    targets = _compute_targets(df_with_ind, buy_price)

    # 5. Generate recommendation
    rec = _generate_recommendation(strategy_code, sig, strats, df_with_ind, buy_price)

    # 6. Build strategy signal summary (which strategy was used + current status)
    strategy_map = {"M2": strats[0], "M3": strats[1], "M4": strats[2]}
    buying_strategy_current = None
    if strategy_code in strategy_map:
        sr = strategy_map[strategy_code]
        buying_strategy_current = strategy_result_to_dict(sr)
    elif strategy_code == "M1":
        buying_strategy_current = {
            "code": "M1",
            "name": "Volatility Breakout (Squeeze)",
            "signal_type": "SELL" if sig.sell_signal else ("BUY" if sig.buy_signal else ("HOLD" if sig.hold_signal else "WAIT")),
            "strength":    "STRONG" if sig.confidence >= 70 else ("MODERATE" if sig.confidence >= 40 else "WEAK"),
            "confidence":  sig.confidence,
            "reason":      sig.summary,
        }

    # 7. Current indicator snapshot
    indicators = {
        "price":      _safe(float(last["Close"])),
        "bb_upper":   _safe(float(last["BB_Upper"])),
        "bb_mid":     _safe(float(last["BB_Mid"])),
        "bb_lower":   _safe(float(last["BB_Lower"])),
        "bbw":        _safe(float(last["BBW"]), 6),
        "percent_b":  _safe(float(last["Percent_B"]), 4),
        "mfi":        _safe(float(last["MFI"])),
        "cmf":        _safe(float(last["CMF"]), 4),
        "sar":        _safe(float(last["SAR"])),
        "sar_bull":   bool(last["SAR_Bull"]),
        "squeeze_on": bool(last["Squeeze_ON"]),
        "volume":     int(last["Volume"]),
        "vol_sma50":  int(last["Vol_SMA50"]) if not math.isnan(last["Vol_SMA50"]) else 0,
    }

    # 8. Holding info
    days = _holding_days(position["buy_date"])
    current_price = float(last["Close"])
    pnl_pct = (current_price - buy_price) / buy_price * 100 if buy_price else 0

    # 9–14. Heavy / network-bound work — runs concurrently in non-light mode,
    # is skipped entirely in light mode (table view).
    multi_sys = {}
    fund_snapshot = {"available": False}
    benchmark = {}
    trailing_stops = _compute_trailing_stops(df_with_ind, buy_price)
    expert_commentary = {}

    # Vince risk is needed for the table (risk_grade + sizing_status), so it
    # runs in both modes. It's local-only (no network).
    vince_risk = _compute_vince_risk(
        ticker, buy_price, int(position["quantity"]),
    )

    if not light:
        # Multi-system engines compute their own indicators, so they need raw
        # OHLCV (compute_all_indicators above mutated `df` in place).
        df_raw = load_stock_data(ticker, csv_dir=CSV_DIR)
        # Fan out the slow, independent calls so the user-facing latency is
        # the max of any single call, not the sum.
        with ThreadPoolExecutor(max_workers=3) as ex:
            f_multi = ex.submit(
                _run_multi_system, df_raw, ticker, buy_price
            ) if df_raw is not None and len(df_raw) >= 60 else None
            f_fund = ex.submit(_fetch_fundamental_snapshot, ticker)
            f_bench = ex.submit(
                _compute_benchmark_alpha, position["buy_date"], pnl_pct
            )

            if f_multi is not None:
                try:
                    multi_sys = f_multi.result()
                except Exception as e:
                    _pa_logger.debug("multi_system failed for %s: %s", ticker, e)
            try:
                fund_snapshot = f_fund.result()
            except Exception as e:
                _pa_logger.debug("fundamentals failed for %s: %s", ticker, e)
                fund_snapshot = {"available": False, "error": "Fetch failed"}
            try:
                benchmark = f_bench.result()
            except Exception as e:
                _pa_logger.debug("benchmark failed for %s: %s", ticker, e)

        expert_commentary = _generate_expert_commentary(df_with_ind, sig, multi_sys, buy_price)

    return {
        "position":                position,
        "indicators":              indicators,
        "buying_strategy_current": buying_strategy_current,
        "all_strategies":          [strategy_result_to_dict(s) for s in strats],
        "method1_summary": {
            "buy":  sig.buy_signal,
            "sell": sig.sell_signal,
            "hold": sig.hold_signal,
            "wait": sig.wait_signal,
            "confidence":  sig.confidence,
            "phase":       sig.phase,
            "head_fake":   sig.head_fake,
            "exit_sar":    sig.exit_sar_flip,
            "exit_lower":  sig.exit_lower_band_tag,
            "exit_double": sig.exit_double_neg,
        },
        "recommendation":  rec,
        "targets":         targets,
        "multi_system":    multi_sys,
        "vince_risk":      vince_risk,
        "fundamental_snapshot": fund_snapshot,
        "benchmark":       benchmark,
        "trailing_stops":  trailing_stops,
        "expert_commentary": expert_commentary,
        "holding": {
            "days":          days,
            "buy_price":     buy_price,
            "current_price": _safe(current_price),
            "quantity":      int(position["quantity"]),
            "invested":      _safe(buy_price * int(position["quantity"])),
            "current_value": _safe(current_price * int(position["quantity"])),
            "pnl_amount":    _safe((current_price - buy_price) * int(position["quantity"])),
            "pnl_pct":       _safe(pnl_pct),
        },
        "light": light,
        "error": None,
    }


def analyze_all_open_positions(positions: list[dict], light: bool = True) -> list[dict]:
    """Run analyze_position for each open position.

    Defaults to light=True because this is used to populate the portfolio
    table and only needs recommendation + vince_risk. Runs positions in
    parallel — local indicator/strategy work is CPU-bound but quick, and
    light mode means no yfinance round-trips."""
    if not positions:
        return []
    max_workers = min(8, len(positions))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        return list(ex.map(lambda p: analyze_position(p, light=light), positions))
