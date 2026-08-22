"""
Earnings Calendar Warning Module
=================================
For a technical trader, earnings season is the single biggest trap.

Here's the problem: your Bollinger Band squeeze, RSI, MACD — all of these
read historical price and volume patterns. But when a company announces its
quarterly results on BSE/NSE, the stock can jump or crash 5-15% overnight,
often before your stop-loss can even trigger (gap risk). No amount of
technical analysis predicts a missed earnings estimate or a surprise management
change. The moment the result drops, the chart "resets" — your entry point,
your support levels, your breakout signal — all of it becomes irrelevant.

This module does one thing: looks at how far we are from the next earnings
date and tells you whether to be cautious. No API calls — it just does date
math on data the fundamentals module already fetched.
"""

from __future__ import annotations

from datetime import date, timedelta


def _trading_days_between(start: date, end: date) -> int:
    """Count approximate trading days (skip Sat/Sun, ignore Indian holidays)."""
    if end <= start:
        return 0
    count = 0
    current = start + timedelta(days=1)
    while current <= end:
        if current.weekday() < 5:  # Mon-Fri
            count += 1
        current += timedelta(days=1)
    return count


def check_earnings_proximity(
    ticker: str,
    upcoming_date_str: str | None,
    earnings_history: list | None = None,  # noqa: ARG001 — reserved for future use
) -> dict:
    """
    Check how close we are to the next earnings date and return a warning dict.

    Parameters
    ----------
    ticker:             e.g. "INFY.NS"
    upcoming_date_str:  fd.upcoming_results_date — e.g. "2026-09-15" or None
    earnings_history:   fd.earnings_dates_history — unused today, kept for callers
    """
    if not upcoming_date_str:
        return {
            "warning": False,
            "days_to_earnings": None,
            "calendar_days": None,
            "earnings_date": None,
            "risk_level": None,
            "confidence_adjustment": 0,
            "explanation": (
                "No upcoming earnings date detected for this stock — your technical "
                "signals carry their normal weight. Do keep an eye on BSE/NSE "
                "announcements manually if the stock has been active recently."
            ),
        }

    try:
        earnings_date = date.fromisoformat(upcoming_date_str)
    except (ValueError, TypeError):
        return {
            "warning": False,
            "days_to_earnings": None,
            "calendar_days": None,
            "earnings_date": upcoming_date_str,
            "risk_level": None,
            "confidence_adjustment": 0,
            "explanation": f"Could not parse earnings date '{upcoming_date_str}' — skipping earnings check.",
        }

    today = date.today()
    calendar_days = (earnings_date - today).days
    trading_days = _trading_days_between(today, earnings_date)

    if trading_days > 15 or calendar_days < 0:
        return {
            "warning": False,
            "days_to_earnings": trading_days,
            "calendar_days": calendar_days,
            "earnings_date": upcoming_date_str,
            "risk_level": None,
            "confidence_adjustment": 0,
            "explanation": (
                f"Earnings on {upcoming_date_str} are {trading_days} trading days away — "
                "far enough that your technical signals are not yet distorted by result-day risk. "
                "Revisit this as the date approaches."
            ),
        }

    # Within 15 trading days — classify
    if trading_days <= 3:
        risk_level = "HIGH"
        color = "red"
        adj = -25
        explanation = (
            f"DANGER ZONE: {ticker} reports quarterly results on {upcoming_date_str} — "
            f"only {trading_days} trading day(s) away. "
            "Indian stocks routinely gap 5-15% at market open after results, before any stop-loss "
            "can fire. Your Bollinger squeeze and momentum signals mean nothing if the stock opens "
            "10% below your entry on result day. "
            "Options: (1) Skip this trade entirely and wait for the post-result chart to settle. "
            "(2) Enter only half your normal position size so a bad gap does not blow your account. "
            "(3) If you must hold, set stops wider than normal AND be prepared to accept the gap. "
            "Do NOT rely on a tight stop to protect you here — gaps bypass stops."
        )
    elif trading_days <= 7:
        risk_level = "MEDIUM"
        color = "amber"
        adj = -15
        explanation = (
            f"CAUTION: {ticker} announces results on {upcoming_date_str} "
            f"({trading_days} trading days away). "
            "As results approach, institutional players start positioning, volumes get choppy, "
            "and the stock can swing sharply on rumours or pre-result activity. "
            "Technical signals become less reliable in this window — a breakout today could reverse "
            "violently on result day. Consider reducing position size and avoid adding to positions "
            "unless the setup is extremely clear. The gap risk is real on BSE/NSE."
        )
    else:  # 8-15 trading days
        risk_level = "LOW"
        color = "yellow"
        adj = -5
        explanation = (
            f"HEADS-UP: {ticker} has quarterly results due {upcoming_date_str} "
            f"({trading_days} trading days away). "
            "Technical signals are mostly valid at this distance, but be aware that gap risk exists. "
            "Proceed normally, but keep the date in mind — if the trade has not worked out by then, "
            "you may want to exit before results rather than hold through them."
        )

    return {
        "warning": True,
        "days_to_earnings": trading_days,
        "calendar_days": calendar_days,
        "earnings_date": upcoming_date_str,
        "risk_level": risk_level,
        "color": color,
        "confidence_adjustment": adj,
        "explanation": explanation,
    }


if __name__ == "__main__":
    from datetime import date, timedelta

    today = date.today()
    cases = [
        ("INFY.NS", None),
        ("INFY.NS", (today + timedelta(days=2)).isoformat()),
        ("INFY.NS", (today + timedelta(days=6)).isoformat()),
        ("INFY.NS", (today + timedelta(days=12)).isoformat()),
        ("INFY.NS", (today + timedelta(days=30)).isoformat()),
        ("INFY.NS", "not-a-date"),
    ]
    for ticker, d in cases:
        r = check_earnings_proximity(ticker, d)
        print(f"{d!r:15} → warning={r['warning']}, risk={r.get('risk_level')}, adj={r['confidence_adjustment']}")
