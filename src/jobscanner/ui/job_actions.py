"""The job state machine, as plain data.

`to_apply` / `applied` / `archived` / `reviewed` decide which two buttons
the detail pane shows and what clicking them does. That logic used to be
written out three times in gui.py -- once to label the primary button, once
to handle a primary click, once to handle a secondary click -- with three
independently-ordered branch chains, so it had already drifted: the label
check tested `archived` first while the click handler tested `to_apply`
first. An auto-archived To Apply row therefore rendered "Unarchive" but ran
mark_applied when clicked. One ordering, used by all three, fixes that.

No Tk imports here on purpose -- this module is readable and testable on
its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from jobscanner import storage as db

# Operation ids. `None` means the button is inert.
OP_MARK_REVIEWED = "mark_reviewed"
OP_REVISIT = "revisit"
OP_MARK_APPLIED = "mark_applied"
OP_FURTHER_FOLLOW_UP = "further_follow_up"
OP_UNARCHIVE = "unarchive"
OP_ADD_TO_APPLY = "add_to_apply"
OP_REMOVE_TO_APPLY = "remove_to_apply"
OP_ARCHIVE = "archive"


@dataclass(frozen=True)
class JobState:
    """The four flags that decide a job's section and available actions."""

    reviewed: bool = False
    to_apply: bool = False
    applied: bool = False
    archived: bool = False

    @classmethod
    def from_row(cls, job: Optional[dict]) -> "JobState":
        job = job or {}
        return cls(
            reviewed=bool(job.get("reviewed")),
            to_apply=bool(job.get("to_apply")),
            applied=bool((job.get("applied_at") or "").strip()),
            archived=bool(job.get("archived")),
        )


@dataclass(frozen=True)
class ActionSpec:
    """What a detail-pane button should say and do."""

    label: str
    op: Optional[str] = None
    #: Key into theme.BUTTON_STYLES, or None to leave the widget's own look.
    style: Optional[str] = None
    enabled: bool = True


_ADD_TO_APPLY_LABEL = "☆ Add to To Apply"


def primary_action(state: JobState) -> ActionSpec:
    """The main button: advance the job to its next state."""
    if state.archived:
        return ActionSpec("↩ Unarchive", OP_UNARCHIVE, "accent")
    if state.applied:
        return ActionSpec("↻ Mark Further Follow Up",
                          OP_FURTHER_FOLLOW_UP, "success")
    if state.to_apply:
        return ActionSpec("✓ Mark Applied", OP_MARK_APPLIED, "success")
    if state.reviewed:
        return ActionSpec("↻ Revisit", OP_REVISIT, "warning")
    return ActionSpec("✓ Mark Reviewed", OP_MARK_REVIEWED, "accent")


def secondary_action(state: JobState) -> ActionSpec:
    """The outlined button: the side-step, where one exists."""
    if state.archived:
        # Nothing to do until it's unarchived.
        return ActionSpec(_ADD_TO_APPLY_LABEL, None, enabled=False)
    if state.applied:
        return ActionSpec("★ Archive", OP_ARCHIVE)
    if state.to_apply:
        return ActionSpec("★ Remove from To Apply", OP_REMOVE_TO_APPLY)
    if state.reviewed:
        # A reviewed job can't be re-added to To Apply; Revisit it first.
        return ActionSpec(_ADD_TO_APPLY_LABEL, None, enabled=False)
    return ActionSpec(_ADD_TO_APPLY_LABEL, OP_ADD_TO_APPLY)


def apply_op(op: Optional[str], job_id: str, path: Path) -> bool:
    """Run `op` against `job_id`. Returns False for a no-op."""
    if not op or not job_id:
        return False
    if op == OP_MARK_REVIEWED:
        db.set_reviewed(job_id, True, path)
    elif op == OP_REVISIT:
        db.set_reviewed(job_id, False, path)
    elif op == OP_MARK_APPLIED:
        db.mark_applied(job_id, path)
    elif op == OP_FURTHER_FOLLOW_UP:
        db.mark_further_follow_up(job_id, path=path)
    elif op == OP_UNARCHIVE:
        db.unarchive_job(job_id, path)
    elif op == OP_ADD_TO_APPLY:
        db.set_to_apply(job_id, True, path)
    elif op == OP_REMOVE_TO_APPLY:
        db.set_to_apply(job_id, False, path)
    elif op == OP_ARCHIVE:
        db.archive_job(job_id, path)
    else:
        raise ValueError(f"Unknown job operation: {op!r}")
    return True
