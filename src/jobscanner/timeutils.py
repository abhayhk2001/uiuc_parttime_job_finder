"""UTC ISO-8601 helpers shared by the storage layer and the GUI.

Everything the app persists is `datetime.isoformat(timespec="seconds")` in
UTC, e.g. ``2026-09-23T17:29:55+00:00``. These helpers are the only place
that format is produced or interpreted.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional


def now_iso() -> str:
    """Current UTC time as ISO-8601 with second precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_iso(value: str) -> Optional[datetime]:
    """Parse an ISO-8601 string into a tz-aware UTC datetime.

    Accepts both ``YYYY-MM-DD`` and a full timestamp. Returns ``None`` if
    the value can't be parsed.
    """
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def add_days_iso(iso_ts: str, days: int) -> str:
    """Return ``iso_ts + days`` as a fresh ISO-8601 UTC string.

    Strings that can't be parsed fall back to ``now + days``.
    """
    dt = parse_iso(iso_ts)
    if dt is None:
        dt = datetime.now(timezone.utc)
    return (dt + timedelta(days=days)).isoformat(timespec="seconds")


def to_local_date(value: str) -> Optional[date]:
    """The calendar date `value` falls on for the user, or None.

    Timestamps are stored in UTC, but a person thinks in local days: 8pm
    in Illinois is already tomorrow in UTC. A bare ``YYYY-MM-DD`` (what
    older builds stored from the date picker) already is a local date and
    is taken as-is rather than read as UTC midnight.
    """
    value = (value or "").strip()
    if len(value) == 10:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    dt = parse_iso(value)
    return dt.astimezone().date() if dt is not None else None


def local_date_str(value: str) -> str:
    """``YYYY-MM-DD`` of :func:`to_local_date`, or ``''``."""
    d = to_local_date(value)
    return d.isoformat() if d is not None else ""


def local_day_iso(day: date) -> str:
    """A stored timestamp for a local calendar day: noon local, in UTC.

    Noon rather than midnight so the instant falls on `day` in every
    timezone this app could plausibly be used in.
    """
    local = datetime.combine(day, time(12)).astimezone()
    return local.astimezone(timezone.utc).isoformat(timespec="seconds")


def relative_days(iso_ts: str) -> str:
    """Human-friendly relative time: 'in 7 days', 'today', '5 days ago'.

    Counted in local calendar days. Returns ``''`` for anything unparseable.
    """
    d = to_local_date(iso_ts)
    if d is None:
        return ""
    delta_days = (d - datetime.now().astimezone().date()).days
    if delta_days == 0:
        return "today"
    if delta_days == 1:
        return "in 1 day"
    if delta_days > 0:
        return f"in {delta_days} days"
    if delta_days == -1:
        return "1 day ago"
    return f"{abs(delta_days)} days ago"
