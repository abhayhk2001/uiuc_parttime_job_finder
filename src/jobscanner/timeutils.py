"""UTC ISO-8601 helpers shared by the storage layer and the GUI.

Everything the app persists is `datetime.isoformat(timespec="seconds")` in
UTC, e.g. ``2026-09-23T17:29:55+00:00``. These helpers are the only place
that format is produced or interpreted.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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


def relative_days(iso_ts: str) -> str:
    """Human-friendly relative time: 'in 7 days', 'today', '5 days ago'.

    Returns ``''`` for anything unparseable.
    """
    dt = parse_iso(iso_ts)
    if dt is None:
        return ""
    delta_days = (dt.date() - datetime.now(timezone.utc).date()).days
    if delta_days == 0:
        return "today"
    if delta_days == 1:
        return "in 1 day"
    if delta_days > 0:
        return f"in {delta_days} days"
    if delta_days == -1:
        return "1 day ago"
    return f"{abs(delta_days)} days ago"
