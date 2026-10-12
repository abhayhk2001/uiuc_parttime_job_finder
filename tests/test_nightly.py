"""The once-per-slot guard behind the launchd nightly scan.

Exercises :mod:`jobscanner.nightly` purely with injected clocks, so the
suite behaves identically before and after 21:00 local time.

    python tests/test_nightly.py
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from support import check, eq, run_module  # noqa: E402

from jobscanner import paths  # noqa: E402
from jobscanner.nightly import BOUNDARY_HOUR, is_due, mark_run, marker_path  # noqa: E402

_MARKERS = Path(tempfile.mkdtemp(prefix="nightly_test_"))


def _at(hour: int, minute: int, day_offset: int = 0) -> datetime:
    """A naive local-time datetime `day_offset` days from 2026-10-12."""
    return datetime(2026, 10, 12, hour, minute) + timedelta(days=day_offset)


def _marker(name: str) -> Path:
    return _MARKERS / f"{name}.last_nightly_scan"


# ---------------------------------------------------------------------------
# Due-ness
# ---------------------------------------------------------------------------


def test_no_marker_is_due() -> None:
    check(is_due(_marker("none"), now=_at(8, 0)),
          "a slot with no marker at all must be due")


def test_last_nights_run_blocks_morning_rerun() -> None:
    m = _marker("ran-last-night")
    mark_run(m, now=_at(BOUNDARY_HOUR, 5, day_offset=-1))
    check(not is_due(m, now=_at(8, 0)),
          "waking after a successful 21:00 run must not rescan")


def test_missed_slot_makes_morning_catchup_due() -> None:
    m = _marker("missed-last-night")
    mark_run(m, now=_at(15, 0, day_offset=-1))  # before yesterday's 21:00
    check(is_due(m, now=_at(8, 0)),
          "a wake after a missed 21:00 slot must trigger the catch-up scan")


def test_second_wake_is_not_due_again() -> None:
    m = _marker("caught-up")
    mark_run(m, now=_at(3, 0))  # catch-up run earlier today
    check(not is_due(m, now=_at(4, 0)),
          "a second wake in the same day must not rescan")


def test_evening_slot_still_due_after_morning_catchup() -> None:
    m = _marker("catchup-then-evening")
    mark_run(m, now=_at(3, 0))
    check(is_due(m, now=_at(BOUNDARY_HOUR, 0)),
          "the daily 21:00 slot must still fire after a morning catch-up")


def test_evening_run_blocks_same_evening_rerun() -> None:
    m = _marker("ran-at-nine")
    mark_run(m, now=_at(BOUNDARY_HOUR, 0))
    check(not is_due(m, now=_at(22, 30)),
          "a reboot after tonight's 21:00 run must not rescan")


def test_stale_marker_from_two_days_ago_is_due() -> None:
    m = _marker("stale")
    mark_run(m, now=_at(BOUNDARY_HOUR, 5, day_offset=-2))
    check(is_due(m, now=_at(10, 0)),
          "a marker older than the last slot must be due")


def test_corrupt_marker_is_due() -> None:
    m = _marker("corrupt")
    m.write_text("not-a-timestamp\n")
    check(is_due(m, now=_at(10, 0)),
          "an unreadable marker counts as never-run")


def test_marker_path_lives_in_user_data_dir() -> None:
    eq(marker_path(), paths.user_data_dir() / ".last_nightly_scan",
       "the marker must sit next to the database it guards")


# ---------------------------------------------------------------------------
# mark_run
# ---------------------------------------------------------------------------


def test_mark_run_records_a_parseable_timestamp() -> None:
    m = _marker("written")
    mark_run(m, now=_at(23, 59))
    float(m.read_text().strip())  # must not raise
    check(not is_due(m, now=_at(23, 59)),
          "immediately after mark_run the slot is satisfied")


if __name__ == "__main__":
    _, failed, _ = run_module(globals(), "Nightly guard")
    sys.exit(1 if failed else 0)
