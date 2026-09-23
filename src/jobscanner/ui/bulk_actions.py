"""The sidebar's bulk actions, as a registry.

These used to be a tuple of (section, English label) pairs whose label
doubled as the dict key for enable/disable *and* as the dispatch
discriminator -- `bulk_mark_section` branched on `"Unmark" in label` and
`"Archive" in label`. Renaming a button caption silently broke both. Each
action is now an explicit record with its own id, and the label is only
ever displayed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from jobscanner import config
from jobscanner import storage as db


@dataclass(frozen=True)
class BulkAction:
    """One button in the BULK ACTIONS block."""

    id: str
    label: str
    #: Section whose count decides whether the button is enabled.
    section: str
    #: Performs the action; returns the number of rows affected.
    run: Callable[[Path], int]
    #: Builds the result message from that row count.
    message: Callable[[int], str]
    #: Shown in a confirmation dialog first. None means act immediately.
    confirm: Optional[str] = None


BULK_ACTIONS: tuple[BulkAction, ...] = (
    BulkAction(
        id="review_new",
        label="Mark all New reviewed",
        section=db.SECTION_NEW,
        run=lambda path: db.bulk_set_reviewed(db.SECTION_NEW, True, path),
        message=lambda n: f"Marked {n} job(s) in 'New' as reviewed.",
    ),
    BulkAction(
        id="review_old",
        label="Mark all Old reviewed",
        section=db.SECTION_OLD,
        run=lambda path: db.bulk_set_reviewed(db.SECTION_OLD, True, path),
        message=lambda n: f"Marked {n} job(s) in 'Old' as reviewed.",
    ),
    BulkAction(
        id="revisit_reviewed",
        label="Revisit all Reviewed",
        section=db.SECTION_REVIEWED,
        run=lambda path: db.bulk_set_reviewed(db.SECTION_REVIEWED, False, path),
        message=lambda n: (
            f"Revisited {n} job(s) (moved from 'Reviewed' back to Old/New)."),
        confirm=("Clear the reviewed flag on every job in Reviewed?\n\n"
                 "They all move back to New/Old."),
    ),
    BulkAction(
        id="apply_all_to_apply",
        label="Mark all To Apply Applied",
        section=db.SECTION_TO_APPLY,
        run=db.bulk_mark_all_applied,
        message=lambda n: f"Marked {n} job(s) as applied (moved to Follow Up).",
        confirm=("Mark every job in To Apply as applied?\n\n"
                 "They move to Follow Up with today's date recorded."),
    ),
    BulkAction(
        id="clear_to_apply",
        label="Unmark all To Apply",
        section=db.SECTION_TO_APPLY,
        run=db.bulk_clear_to_apply,
        message=lambda n: f"Removed {n} job(s) from To Apply.",
        confirm="Remove every job from To Apply?",
    ),
    BulkAction(
        id="further_follow_up",
        label="Mark all Follow Up Further",
        section=db.SECTION_FOLLOW_UP,
        run=lambda path: db.bulk_mark_further_follow_up(
            db.SECTION_FOLLOW_UP, path=path),
        message=lambda n: (
            f"Reset follow-up date for {n} job(s) to today + "
            f"{config.FOLLOW_UP_WINDOW_DAYS} days."),
    ),
    BulkAction(
        id="archive_follow_up",
        label="Archive all Follow Up",
        section=db.SECTION_FOLLOW_UP,
        run=lambda path: db.bulk_archive_section(db.SECTION_FOLLOW_UP, path),
        message=lambda n: f"Archived {n} job(s) from Follow Up.",
        confirm="Archive every job currently in Follow Up?",
    ),
)

BULK_ACTIONS_BY_ID: dict[str, BulkAction] = {a.id: a for a in BULK_ACTIONS}
