"""
Event calendar: RBI policy, earnings, budget, expiry, NSE holidays.

Event-driven IV: RBI announcements cause ~3% VIX drop post-event.
Budget: VIX spikes 30-50% in lead-up. Elections: 2024 VIX ~25, ~12 post-result.
"""

import datetime
from collections import namedtuple

Event = namedtuple('Event', ['date', 'type', 'name', 'iv_impact'])

MuhuratSession = namedtuple('MuhuratSession', ['date', 'start', 'end'])

# Muhurat trading: ~1hr evening session on Diwali (times from NSE circular)
_MUHURAT_SESSIONS = [
    MuhuratSession(datetime.date(2026, 11, 10),
                   datetime.time(18, 15), datetime.time(19, 15)),
]

# ---------------------------------------------------------------------------
# Known events (update each year)
# ---------------------------------------------------------------------------

# RBI Monetary Policy dates 2026 (bi-monthly, 6 meetings/year)
_RBI_2026 = [
    datetime.date(2026, 2, 7),
    datetime.date(2026, 4, 9),
    datetime.date(2026, 6, 6),
    datetime.date(2026, 8, 7),
    datetime.date(2026, 10, 8),
    datetime.date(2026, 12, 5),
]

_RBI_2027 = [
    datetime.date(2027, 2, 5),
    datetime.date(2027, 4, 8),
    datetime.date(2027, 6, 4),
    datetime.date(2027, 8, 6),
    datetime.date(2027, 10, 8),
    datetime.date(2027, 12, 3),
]

# Union Budget
_BUDGET = [
    datetime.date(2026, 2, 1),
    datetime.date(2027, 2, 1),
]

# NSE holidays 2026 (approximate — verify with NSE circular each year)
_NSE_HOLIDAYS_2026 = [
    datetime.date(2026, 1, 26),  # Republic Day
    datetime.date(2026, 3, 10),  # Holi
    datetime.date(2026, 3, 30),  # Id-Ul-Fitr
    datetime.date(2026, 4, 2),   # Ram Navami
    datetime.date(2026, 4, 3),   # Good Friday
    datetime.date(2026, 4, 14),  # Dr. Ambedkar Jayanti
    datetime.date(2026, 5, 1),   # Maharashtra Day
    datetime.date(2026, 6, 5),   # Id-Ul-Adha (Bakri Id)
    datetime.date(2026, 7, 6),   # Muharram
    datetime.date(2026, 8, 15),  # Independence Day
    datetime.date(2026, 9, 4),   # Milad-Un-Nabi
    datetime.date(2026, 10, 2),  # Mahatma Gandhi Jayanti
    datetime.date(2026, 10, 21), # Dussehra
    datetime.date(2026, 11, 10), # Diwali (Laxmi Pujan)
    datetime.date(2026, 11, 11), # Diwali (Balipratipada)
    datetime.date(2026, 11, 27), # Guru Nanak Jayanti
    datetime.date(2026, 12, 25), # Christmas
]


def _all_events():
    """Combine all known events into a single list."""
    events = []
    for d in _RBI_2026 + _RBI_2027:
        events.append(Event(d, 'RBI', 'RBI Monetary Policy', 'high'))
    for d in _BUDGET:
        events.append(Event(d, 'BUDGET', 'Union Budget', 'very_high'))
    return sorted(events, key=lambda e: e.date)


def upcoming_events(days_ahead=30, as_of=None):
    """
    Events in the next N calendar days.

    Parameters
    ----------
    days_ahead : int
    as_of : date or None (defaults to today)

    Returns
    -------
    list of Event namedtuples
    """
    if as_of is None:
        as_of = datetime.date.today()
    cutoff = as_of + datetime.timedelta(days=days_ahead)
    return [e for e in _all_events() if as_of <= e.date <= cutoff]


def days_to_next_event(event_type=None, as_of=None):
    """
    Calendar days until the next event of given type (or any event).

    Returns
    -------
    tuple: (days, Event) or (None, None) if no future event found
    """
    if as_of is None:
        as_of = datetime.date.today()
    for e in _all_events():
        if e.date >= as_of:
            if event_type is None or e.type == event_type:
                return (e.date - as_of).days, e
    return None, None


def is_expiry_week(as_of=None):
    """True if as_of is Mon-Tue of a week containing a Tuesday expiry."""
    if as_of is None:
        as_of = datetime.date.today()
    if as_of.weekday() >= 5:  # Sat/Sun
        return False
    # find this week's Tuesday (weekday=1)
    days_to_tue = (1 - as_of.weekday()) % 7
    if days_to_tue > 1:  # Wed-Fri: next Tue is next week
        return False
    return True


def is_nse_holiday(date):
    """Check if a date is an NSE holiday (2026 only; extend as needed)."""
    return date in _NSE_HOLIDAYS_2026


def next_expiry(index='NIFTY', as_of=None, monthly=False):
    """
    Next expiry date.

    All NSE F&O expiries moved to Tuesday (Sep 2025 onward).
    Nifty: weekly Tuesday. BankNifty/FinNifty: monthly only (last Tuesday)
    since SEBI discontinued BankNifty/FinNifty weekly expiry Nov 2024.

    Parameters
    ----------
    index : str – 'NIFTY' or 'BANKNIFTY'
    as_of : date
    monthly : bool – force monthly expiry (last Tuesday of month)

    Returns
    -------
    datetime.date – next expiry
    """
    if as_of is None:
        as_of = datetime.date.today()

    # All NSE expiries are Tuesday (weekday=1) since Sep 2025
    target_weekday = 1

    # BankNifty/FinNifty: monthly only since Nov 2024
    force_monthly = monthly or index.upper() in ('BANKNIFTY', 'FINNIFTY')

    if force_monthly:
        return _last_weekday_of_month(as_of, target_weekday)

    # weekly expiry: find next target_weekday
    d = as_of
    for _ in range(10):
        days_ahead = (target_weekday - d.weekday()) % 7
        if days_ahead == 0 and d == as_of:
            candidate = d
        else:
            if days_ahead == 0:
                days_ahead = 7
            candidate = d + datetime.timedelta(days=days_ahead)

        if not is_nse_holiday(candidate):
            return candidate
        candidate -= datetime.timedelta(days=1)
        while is_nse_holiday(candidate) or candidate.weekday() >= 5:
            candidate -= datetime.timedelta(days=1)
        return candidate
    return as_of


def _last_weekday_of_month(as_of, target_weekday):
    """Last occurrence of target_weekday in the current or next month."""
    import calendar
    year, month = as_of.year, as_of.month

    last_day = calendar.monthrange(year, month)[1]
    d = datetime.date(year, month, last_day)
    while d.weekday() != target_weekday:
        d -= datetime.timedelta(days=1)

    if d >= as_of:
        candidate = d
    else:
        # move to next month
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
        last_day = calendar.monthrange(year, month)[1]
        d = datetime.date(year, month, last_day)
        while d.weekday() != target_weekday:
            d -= datetime.timedelta(days=1)
        candidate = d

    # shift for holidays
    while is_nse_holiday(candidate) or candidate.weekday() >= 5:
        candidate -= datetime.timedelta(days=1)
    return candidate


def is_muhurat_session(dt=None):
    """Check if datetime falls within a Muhurat trading session.
    Returns MuhuratSession or None."""
    if dt is None:
        dt = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
    d = dt.date() if hasattr(dt, 'date') else dt
    t = dt.time() if hasattr(dt, 'time') else None
    for ms in _MUHURAT_SESSIONS:
        if d == ms.date:
            if t is None:
                return ms
            if ms.start <= t <= ms.end:
                return ms
    return None


def event_iv_window(as_of=None, window_days=5):
    """
    Check if we're within an IV event window.

    Returns
    -------
    dict or None:
        event – the Event
        days_to – calendar days until event
        regime – 'pre_event' or 'event_day'
        guidance – brief strategy note
    """
    if as_of is None:
        as_of = datetime.date.today()

    for e in _all_events():
        if e.date < as_of:
            continue
        days = (e.date - as_of).days
        if days <= window_days:
            regime = 'event_day' if days == 0 else 'pre_event'
            if regime == 'pre_event':
                guidance = f"IV elevated {days}d before {e.name}; straddle/strangle premium rich"
            else:
                guidance = f"{e.name} today; expect IV crush post-announcement"
            return {
                'event': e,
                'days_to': days,
                'regime': regime,
                'guidance': guidance,
            }
    return None


def _self_check():
    oct1 = datetime.date(2026, 10, 1)
    events = upcoming_events(30, as_of=oct1)
    rbi_dates = [e for e in events if e.type == 'RBI']
    assert len(rbi_dates) >= 1, "Should find Oct 8 RBI meeting"

    days, evt = days_to_next_event('RBI', as_of=oct1)
    assert days == 7, f"Oct 8 is 7 days from Oct 1, got {days}"

    assert is_expiry_week(datetime.date(2026, 10, 5))  # Monday — expiry week (Tue expiry)

    exp = next_expiry('NIFTY', as_of=datetime.date(2026, 10, 5))
    assert exp.weekday() == 1 or not is_nse_holiday(exp), "Expiry should be Tuesday or shifted"

    window = event_iv_window(as_of=datetime.date(2026, 10, 5), window_days=5)
    assert window is not None, "Should detect RBI Oct 8 within 5-day window"
    assert window['regime'] == 'pre_event'

    # Muhurat session checks
    _ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    inside = datetime.datetime(2026, 11, 10, 18, 30, tzinfo=_ist)
    assert is_muhurat_session(inside) is not None, "18:30 on Diwali is Muhurat"
    outside = datetime.datetime(2026, 11, 10, 12, 0, tzinfo=_ist)
    assert is_muhurat_session(outside) is None, "12:00 on Diwali is not Muhurat"
    date_only = is_muhurat_session(datetime.date(2026, 11, 10))
    assert date_only is not None, "Date-only check should find Muhurat day"
    assert is_muhurat_session(datetime.date(2026, 10, 5)) is None

    print("event_calendar.py: all checks passed")


if __name__ == '__main__':
    _self_check()
