"""
Known market events that inflate IV for a reason.
Sell-premium strategies should be suppressed near these dates.
"""

import datetime

# buffer_days: skip sell strategies this many trading days before event
EVENTS = [
    # RBI MPC 2026 (6 meetings, dates approximate — update annually)
    {'date': '2026-02-07', 'name': 'RBI MPC', 'buffer_days': 2},
    {'date': '2026-04-09', 'name': 'RBI MPC', 'buffer_days': 2},
    {'date': '2026-06-06', 'name': 'RBI MPC', 'buffer_days': 2},
    {'date': '2026-08-08', 'name': 'RBI MPC', 'buffer_days': 2},
    {'date': '2026-10-08', 'name': 'RBI MPC', 'buffer_days': 2},
    {'date': '2026-12-05', 'name': 'RBI MPC', 'buffer_days': 2},
    # RBI MPC 2027
    {'date': '2027-02-05', 'name': 'RBI MPC', 'buffer_days': 2},
    {'date': '2027-04-09', 'name': 'RBI MPC', 'buffer_days': 2},
    # Union Budget
    {'date': '2026-02-01', 'name': 'Union Budget', 'buffer_days': 3},
    {'date': '2027-02-01', 'name': 'Union Budget', 'buffer_days': 3},
    # Quarterly expiry (last Thursday of Mar, Jun, Sep, Dec)
    {'date': '2026-03-26', 'name': 'Quarterly Expiry', 'buffer_days': 1},
    {'date': '2026-06-25', 'name': 'Quarterly Expiry', 'buffer_days': 1},
    {'date': '2026-09-24', 'name': 'Quarterly Expiry', 'buffer_days': 1},
    {'date': '2026-12-31', 'name': 'Quarterly Expiry', 'buffer_days': 1},
    {'date': '2027-03-25', 'name': 'Quarterly Expiry', 'buffer_days': 1},
]

_parsed = None


def _load():
    global _parsed
    if _parsed is not None:
        return _parsed
    _parsed = []
    for ev in EVENTS:
        d = datetime.date.fromisoformat(ev['date'])
        _parsed.append((d, ev['buffer_days'], ev['name']))
    return _parsed


def event_near(dt, buffer_override=None):
    """Return event name if a known event is within buffer_days of dt, else None."""
    for ev_date, buf, name in _load():
        b = buffer_override if buffer_override is not None else buf
        diff = (ev_date - dt).days
        if 0 <= diff <= b:
            return name
    return None


def is_sell_suppressed(dt):
    """True if sell-premium strategies should be suppressed on dt."""
    return event_near(dt) is not None
