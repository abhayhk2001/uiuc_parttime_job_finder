"""The job state machine, as plain data.

``to_apply`` / ``applied`` / ``archived`` / ``reviewed`` decide which two
buttons the detail pane shows and what clicking them does. That logic used
to be written out three times in the old GUI -- once to label the primary
button, once to handle a primary click, once to handle a secondary click
-- with three independently-ordered branch chains, so it had already
drifted: the label check tested ``archived`` first while the click
handler tested ``to_apply`` first. An auto-archived To Apply row
therefore rendered "Unarchive" but ran ``mark_applied`` when clicked.
One ordering, used by all three, fixes that.

Framework-agnostic: no Qt imports here. Reused by the Qt detail pane in
:mod:`jobscanner.ui_qt`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from jobscanner import config
from jobscanner import storage as db


# Operation ids. ``None`` means the button is inert.
OP_MARK_REVIEWED = "mark_reviewed"
OP_REVISIT = "revisit"
OP_MARK_APPLIED = "mark_applied"
OP_FURTHER_FOLLOW_UP = "further_follow_up"
OP_UNARCHIVE = "unarchive"
OP_ADD_TO_APPLY = "add_to_apply"
OP_REMOVE_TO_APPLY = "remove_to_apply"
OP_ARCHIVE = "archive"
OP_MARK_NOT_APPLIED = "mark_not_applied"
OP_FOLLOW_UP_SOON = "follow_up_soon"
OP_REMOVE_FOLLOW_UP = "remove_follow_up"


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
    #: Semantic style key -- ``"accent"``, ``"success"``, ``"warning"`` or
    #: ``None`` for an outlined/secondary look. The view layer maps this to
    #: a concrete widget style; the state machine itself stays UI-free.
    style: Optional[str] = None
    enabled: bool = True


_ADD_TO_APPLY_LABEL = "\u2606 Add to To Apply"


def primary_action(state: JobState) -> ActionSpec:
    """The main button: advance the job to its next state."""
    if state.archived:
        return ActionSpec("\u21a9 Unarchive", OP_UNARCHIVE, "accent")
    if state.applied:
        return ActionSpec("\u21bb Mark Further Follow Up",
                          OP_FURTHER_FOLLOW_UP, "success")
    if state.to_apply:
        return ActionSpec("\u2713 Mark Applied", OP_MARK_APPLIED, "success")
    if state.reviewed:
        return ActionSpec("\u21bb Revisit", OP_REVISIT, "warning")
    # An unreviewed job's most common next step is "this looks good, put it
    # in To Apply", so that is the prominent action; Mark Reviewed is the
    # side-step and sits in the secondary slot.
    return ActionSpec(_ADD_TO_APPLY_LABEL, OP_ADD_TO_APPLY, "accent")


def secondary_action(state: JobState) -> ActionSpec:
    """The outlined button: the side-step, where one exists."""
    if state.archived:
        # Nothing to do until it's unarchived.
        return ActionSpec(_ADD_TO_APPLY_LABEL, None, enabled=False)
    if state.applied:
        return ActionSpec("\u2605 Archive", OP_ARCHIVE)
    if state.to_apply:
        return ActionSpec("\u2605 Remove from To Apply", OP_REMOVE_TO_APPLY)
    if state.reviewed:
        # A reviewed job can't be re-added to To Apply; Revisit it first.
        return ActionSpec(_ADD_TO_APPLY_LABEL, None, enabled=False)
    return ActionSpec("\u2713 Mark Reviewed", OP_MARK_REVIEWED)


def apply_op(op: Optional[str], job_id: str, path: Path) -> bool:
    """Run ``op`` against ``job_id``. Returns False for a no-op."""
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
    elif op == OP_MARK_NOT_APPLIED:
        db.mark_not_applied(job_id, path)
    elif op == OP_FOLLOW_UP_SOON:
        db.mark_further_follow_up(
            job_id, days=config.FOLLOW_UP_SNOOZE_DAYS, path=path)
    elif op == OP_REMOVE_FOLLOW_UP:
        db.clear_follow_up(job_id, path)
    else:
        raise ValueError(f"Unknown job operation: {op!r}")
    return True


_OP_TOASTS: dict[str, str] = {
    OP_MARK_REVIEWED: "Marked reviewed",
    OP_REVISIT: "Revisited",
    OP_MARK_APPLIED: "Marked applied",
    OP_FURTHER_FOLLOW_UP: "Follow-up reset",
    OP_UNARCHIVE: "Unarchived",
    OP_ADD_TO_APPLY: "Added to To Apply",
    OP_REMOVE_TO_APPLY: "Removed from To Apply",
    OP_ARCHIVE: "Archived",
    OP_MARK_NOT_APPLIED: "Marked not applied",
    OP_FOLLOW_UP_SOON: f"Follow up in {config.FOLLOW_UP_SNOOZE_DAYS} days",
    OP_REMOVE_FOLLOW_UP: "Removed from follow-up list",
}


def describe_op(op: Optional[str], job: Optional[dict]) -> str:
    """A status-bar toast confirming ``op`` ran against ``job``.

    The row vanishes from its section after most ops; without a toast the
    only proof anything happened is the refreshed table.
    """
    verb = _OP_TOASTS.get(op or "", "Updated")
    title = ((job or {}).get("title") or "").strip() or "job"
    return f"{verb}: {title}"


def op_past_tense(op: str) -> str:
    """The past-tense verb for ``op``, for multi-row summary toasts."""
    return _OP_TOASTS.get(op, "Updated")


def ops_for_job(job: Optional[dict]) -> set[str]:
    """Every op the state machine currently offers for ``job``.

    Powers the multi-select context menu: an op appears enabled when at
    least one selected row supports it, with a per-op count.
    """
    state = JobState.from_row(job)
    ops: set[str] = set()
    for spec in (primary_action(state), secondary_action(state)):
        if spec.op and spec.enabled:
            ops.add(spec.op)
    if state.applied:
        ops.add(OP_MARK_NOT_APPLIED)
        ops.add(OP_FOLLOW_UP_SOON)
        # Nothing to remove once the date is cleared and the job isn't an
        # auto-archive alert.
        if job and (job.get("follow_up_at") or job.get("auto_archived")):
            ops.add(OP_REMOVE_FOLLOW_UP)
    return ops


#: The multi-select context menu's rows, in a stable order.
MULTI_OP_LABELS: tuple[tuple[str, str], ...] = (
    (OP_MARK_REVIEWED, "Mark Reviewed"),
    (OP_REVISIT, "Revisit"),
    (OP_ADD_TO_APPLY, "Add to To Apply"),
    (OP_REMOVE_TO_APPLY, "Remove from To Apply"),
    (OP_MARK_APPLIED, "Mark Applied"),
    (OP_ARCHIVE, "Archive"),
    (OP_UNARCHIVE, "Unarchive"),
    (OP_FURTHER_FOLLOW_UP, "Mark Further Follow Up"),
    (OP_FOLLOW_UP_SOON,
     f"Follow Up in {config.FOLLOW_UP_SNOOZE_DAYS} Days"),
    (OP_REMOVE_FOLLOW_UP, "Remove from Follow-up List"),
    (OP_MARK_NOT_APPLIED, "Mark Not Applied"),
)
