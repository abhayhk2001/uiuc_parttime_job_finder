"""Once-per-slot guard for the scheduled "scan then open the GUI" run.

The launchd agent fires the app with ``--scan-and-open`` in three
situations: the daily 21:00 slot, right after the Mac wakes when that
slot was missed during sleep, and on every login/reboot (``RunAtLoad``).
Without a guard, a machine that slept through 21:00 and then woke at
03:00, was rebooted at 08:00, and reached 21:00 again would scan three
times in one day.

The guard is a single marker file holding the epoch time of the last
*successful* run. A run is due when that marker is older than the most
recent 21:00 boundary:

- before 21:00, the most recent slot was yesterday's 21:00, so a run at
  03:00 after a missed 21:00 slot is due, while a second wake at 04:00
  is not (the 03:00 run satisfies yesterday's slot);
- at or after 21:00, today's slot is the boundary, so the daily run is
  always due even when a catch-up scan ran earlier in the day.

A failed scan never writes the marker, so it retries at the next
wake/reboot until one succeeds for the current slot.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Optional

from jobscanner import paths

#: Hour (local time) of the daily scan slot.
BOUNDARY_HOUR = 21

#: Marker filename inside the per-user data directory.
MARKER_NAME = ".last_nightly_scan"


def marker_path() -> Path:
    """Where the last-successful-run timestamp lives.

    Resolves through :func:`jobscanner.paths.user_data_dir`, so the
    frozen .app and any source run that sets ``$JOBSCANNER_DATA_DIR``
    share the same marker as the database they write.
    """
    return paths.user_data_dir() / MARKER_NAME


def _boundary(now: datetime, hour: int) -> datetime:
    """The start of the most recent daily slot: today ``hour``:00 if
    already past it, otherwise yesterday's."""
    local = now if now.tzinfo is not None else now.astimezone()
    today = local.date()
    boundary = datetime.combine(today, time(hour)).astimezone()
    if local < boundary:
        boundary -= timedelta(days=1)
    return boundary


def is_due(marker: Optional[Path] = None,
           now: Optional[datetime] = None,
           boundary_hour: int = BOUNDARY_HOUR) -> bool:
    """True when the scheduled slot has not had a successful run yet.

    Missing, unreadable, or empty markers count as never-run.
    """
    marker = Path(marker) if marker else marker_path()
    try:
        last = float(marker.read_text().strip())
    except (OSError, ValueError):
        return True
    now = now or datetime.now().astimezone()
    return last < _boundary(now, boundary_hour).timestamp()


def mark_run(marker: Optional[Path] = None,
             now: Optional[datetime] = None) -> None:
    """Record a successful run at ``now`` (default: right now)."""
    marker = Path(marker) if marker else marker_path()
    now = now or datetime.now().astimezone()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(f"{now.timestamp():.0f}\n")
