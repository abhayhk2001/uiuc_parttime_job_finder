"""Job rows: reads, writes, and the To Apply / Follow Up / Archive
state transitions."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Optional

from jobscanner import config
from jobscanner.storage.meta import get_latest_scan_started_at
from jobscanner.storage.schema import LEGACY_SOURCE, connect
from jobscanner.storage.sections import (
    SECTION_ALL,
    SECTION_FOLLOW_UP,
    SECTION_TO_APPLY,
    VALID_SECTIONS,
    _follow_up_clause,
    section_clause,
)
from jobscanner.timeutils import add_days_iso, now_iso

# ---------------------------------------------------------------------------
# Scan-time writes
# ---------------------------------------------------------------------------


def _source_of(job_id: str) -> str:
    """Derive the source key from a namespaced job id ("rp:48827" -> "rp")."""
    return job_id.split(":", 1)[0] if ":" in job_id else LEGACY_SOURCE


# For an existing row, how each listing field is merged into the stored one.
# Overwrite: a non-empty incoming value wins. Fill: the stored value wins
# unless it is empty.
_MERGE_OVERWRITE = "{col} = COALESCE(NULLIF(?, ''), {col})"
_MERGE_FILL = "{col} = COALESCE(NULLIF({col}, ''), NULLIF(?, ''), {col})"


def upsert_listing(
    job: dict,
    path: Optional[Path] = None,
    overwrite: bool = True,
) -> bool:
    """Insert new job row (returning True if newly inserted) or update last_seen_at.

    `overwrite=False` keeps the stored title/company/date_posted and only
    fills them in when empty. The scan passes it for sources whose listing
    is less accurate than their detail page: VJB's listing carries only the
    department, so overwriting would replace the real title that
    fetch_detail stored on the previous scan with the department name.

    Seeing a row again restores it if the scanner auto-archived it --
    being listed is proof it is open. A row the user archived stays put.
    """
    now = now_iso()
    merge = _MERGE_OVERWRITE if overwrite else _MERGE_FILL
    with connect(path) as conn:
        exists = conn.execute(
            "SELECT 1 FROM jobs WHERE job_id = ?", (job["job_id"],)
        ).fetchone() is not None
        if exists:
            conn.execute(
                "UPDATE jobs SET last_seen_at = ?, "
                + ", ".join(merge.format(col=c)
                            for c in ("title", "company", "date_posted"))
                + ", archived = CASE WHEN auto_archived = 1 THEN 0 ELSE archived END"
                ", archived_at = CASE WHEN auto_archived = 1 THEN NULL ELSE archived_at END"
                ", auto_archived = 0 "
                "WHERE job_id = ?",
                (now, job.get("title", ""), job.get("company", ""),
                 job.get("date_posted", ""), job["job_id"]),
            )
            conn.commit()
            return False
        conn.execute(
            "INSERT INTO jobs (job_id, title, company, date_posted, detail_url, "
            "first_seen_at, last_seen_at, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job["job_id"],
                job.get("title", ""),
                job.get("company", ""),
                job.get("date_posted", ""),
                job.get("detail_url", ""),
                now,
                now,
                job.get("source") or _source_of(job["job_id"]),
            ),
        )
        conn.commit()
        return True


def update_details(
    job_id: str,
    job_description: str,
    requirements: str,
    skills: str,
    matched_keywords: Iterable[str],
    path: Optional[Path] = None,
) -> None:
    matches = ",".join(sorted({m for m in matched_keywords if m}))
    with connect(path) as conn:
        conn.execute(
            "UPDATE jobs SET job_description = ?, requirements = ?, skills = ?, "
            "matched_keywords = ? WHERE job_id = ?",
            (job_description, requirements, skills, matches, job_id),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def get_existing_job_ids(path: Optional[Path] = None) -> set[str]:
    with connect(path) as conn:
        return {row[0] for row in conn.execute("SELECT job_id FROM jobs").fetchall()}


def get_jobs_missing_details(path: Optional[Path] = None) -> list[str]:
    with connect(path) as conn:
        cur = conn.execute(
            "SELECT job_id FROM jobs WHERE (job_description IS NULL OR job_description = '') "
            "AND (requirements IS NULL OR requirements = '') AND (skills IS NULL OR skills = '')"
        )
        return [row[0] for row in cur.fetchall()]


def get_job(job_id: str, path: Optional[Path] = None) -> dict | None:
    with connect(path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return dict(row) if row else None


def get_all_jobs(path: Optional[Path] = None) -> list[dict]:
    with connect(path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM jobs ORDER BY first_seen_at DESC")
        return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Single-row state transitions
# ---------------------------------------------------------------------------


def set_reviewed(
    job_id: str,
    reviewed: bool,
    path: Optional[Path] = None,
) -> None:
    with connect(path) as conn:
        conn.execute(
            "UPDATE jobs SET reviewed = ? WHERE job_id = ?",
            (1 if reviewed else 0, job_id),
        )
        conn.commit()


def set_to_apply(
    job_id: str,
    to_apply: bool,
    path: Optional[Path] = None,
) -> None:
    """Toggle the To Apply flag. Deliberately leaves `reviewed` untouched —
    the GUI only offers this on rows that aren't reviewed yet."""
    with connect(path) as conn:
        conn.execute(
            "UPDATE jobs SET to_apply = ? WHERE job_id = ?",
            (1 if to_apply else 0, job_id),
        )
        conn.commit()


# The Applied transition, written once and shared by the single-row and bulk
# entry points so they can't drift apart again.
_APPLIED_ASSIGNMENTS = (
    "to_apply = 0, reviewed = 1, applied_at = ?, follow_up_at = ?, "
    "archived = 0, archived_at = NULL, auto_archived = 0"
)


def _applied_params() -> tuple[str, str]:
    now = now_iso()
    return now, add_days_iso(now, config.FOLLOW_UP_WINDOW_DAYS)


def mark_applied(
    job_id: str,
    path: Optional[Path] = None,
) -> None:
    """Atomic transition for a To Apply job:
    clear `to_apply`, set `reviewed=1`, record `applied_at` and a default
    `follow_up_at` of `applied_at + FOLLOW_UP_WINDOW_DAYS`.
    """
    with connect(path) as conn:
        conn.execute(
            f"UPDATE jobs SET {_APPLIED_ASSIGNMENTS} WHERE job_id = ?",
            (*_applied_params(), job_id),
        )
        conn.commit()


def set_follow_up(
    job_id: str,
    follow_up_iso: str,
    path: Optional[Path] = None,
) -> None:
    """Set `follow_up_at` to an explicit ISO timestamp (e.g. from the date
    editor in the GUI). The job stays in the Follow Up section."""
    with connect(path) as conn:
        conn.execute(
            "UPDATE jobs SET follow_up_at = ? WHERE job_id = ?",
            (follow_up_iso, job_id),
        )
        conn.commit()


def mark_further_follow_up(
    job_id: str,
    days: int = config.FOLLOW_UP_WINDOW_DAYS,
    path: Optional[Path] = None,
) -> None:
    """Reset `follow_up_at` to ``now + days`` — the canonical "I followed
    up today, remind me in a week" action.
    """
    with connect(path) as conn:
        conn.execute(
            "UPDATE jobs SET follow_up_at = ? WHERE job_id = ?",
            (add_days_iso(now_iso(), days), job_id),
        )
        conn.commit()


def archive_job(
    job_id: str,
    path: Optional[Path] = None,
) -> None:
    """Mark a job as archived (sets archived=1, archived_at=now).

    A user archive, so `auto_archived` is cleared: a later scan that still
    lists the job must not bring it back.
    """
    with connect(path) as conn:
        conn.execute(
            "UPDATE jobs SET archived = 1, archived_at = ?, auto_archived = 0 "
            "WHERE job_id = ?",
            (now_iso(), job_id),
        )
        conn.commit()


def unarchive_job(
    job_id: str,
    path: Optional[Path] = None,
) -> None:
    """Restore a job from Archived (clears archived + archived_at). The
    job's other flags determine which section it lands in."""
    with connect(path) as conn:
        conn.execute(
            "UPDATE jobs SET archived = 0, archived_at = NULL, auto_archived = 0 "
            "WHERE job_id = ?",
            (job_id,),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Bulk transitions
# ---------------------------------------------------------------------------


def bulk_set_reviewed(
    section: str,
    reviewed: bool,
    path: Optional[Path] = None,
) -> int:
    """Set the reviewed flag for every job in `section`. Returns rows changed."""
    if section not in VALID_SECTIONS or section == SECTION_ALL:
        raise ValueError(
            f"bulk_set_reviewed cannot operate on {section!r}"
        )
    clause, params = section_clause(section, get_latest_scan_started_at(path))
    with connect(path) as conn:
        cur = conn.execute(
            f"UPDATE jobs SET reviewed = ? WHERE {clause}",
            (1 if reviewed else 0, *params),
        )
        conn.commit()
        return cur.rowcount


def bulk_mark_all_applied(path: Optional[Path] = None) -> int:
    """Apply the full Applied transition to every To Apply job.

    Uses the same assignments as :func:`mark_applied`, so bulk-applied rows
    land in Follow Up with `applied_at` / `follow_up_at` recorded, rather
    than stopping at Reviewed.

    Scoped by the To Apply section predicate, not bare ``to_apply = 1``:
    archived rows keep their flag, and since the assignments un-archive,
    the bare filter dragged them back out of Archived.
    """
    clause, params = section_clause(SECTION_TO_APPLY, "")
    with connect(path) as conn:
        cur = conn.execute(
            f"UPDATE jobs SET {_APPLIED_ASSIGNMENTS} WHERE {clause}",
            (*_applied_params(), *params),
        )
        conn.commit()
        return cur.rowcount


def bulk_clear_to_apply(path: Optional[Path] = None) -> int:
    """Clear `to_apply` for every To Apply job (without marking reviewed)."""
    clause, params = section_clause(SECTION_TO_APPLY, "")
    with connect(path) as conn:
        cur = conn.execute(f"UPDATE jobs SET to_apply = 0 WHERE {clause}", params)
        conn.commit()
        return cur.rowcount


def bulk_archive_section(
    section: str,
    path: Optional[Path] = None,
) -> int:
    """Archive every job in `section` (only Follow Up makes sense today)."""
    if section != SECTION_FOLLOW_UP:
        raise ValueError(
            f"bulk_archive_section only supports {SECTION_FOLLOW_UP!r}"
        )
    clause, params = _follow_up_clause()
    with connect(path) as conn:
        cur = conn.execute(
            f"UPDATE jobs SET archived = 1, archived_at = ?, auto_archived = 0 "
            f"WHERE {clause}",
            (now_iso(), *params),
        )
        conn.commit()
        return cur.rowcount


def bulk_mark_further_follow_up(
    section: str,
    days: int = config.FOLLOW_UP_WINDOW_DAYS,
    path: Optional[Path] = None,
) -> int:
    """Reset `follow_up_at` to ``now + days`` for every job in `section`."""
    if section != SECTION_FOLLOW_UP:
        raise ValueError(
            f"bulk_mark_further_follow_up only supports {SECTION_FOLLOW_UP!r}"
        )
    clause, params = _follow_up_clause()
    with connect(path) as conn:
        cur = conn.execute(
            f"UPDATE jobs SET follow_up_at = ? WHERE {clause}",
            (add_days_iso(now_iso(), days), *params),
        )
        conn.commit()
        return cur.rowcount


def auto_archive_removed_jobs(
    cutoff_iso: str,
    source: str,
    path: Optional[Path] = None,
) -> int:
    """Archive every job of `source` that wasn't re-seen in the scan.

    Cutoff is the ``latest_scan_started_at`` timestamp; rows with
    ``last_seen_at < cutoff`` were not listed in that scan and so are no
    longer open.

    This used to archive only *active* rows (reviewed=1 OR to_apply=1),
    which meant a posting the user had never looked at stayed in Old forever
    once it left the board -- twelve of fifteen Research Park rows were in
    that state when this changed. A job that is gone is gone regardless of
    whether it was reviewed, so the condition is deliberately absent.

    `source` is required and scopes the update. It must never be optional:
    an un-scoped sweep would archive every other source's jobs whenever one
    source failed to fetch, which silently destroys real user state. The
    caller is also responsible for only invoking this for a source whose
    fetch succeeded *and returned rows* -- see pipeline._scan_source, which
    skips archiving on an empty listing so that a parser returning [] can't
    wipe a whole source.

    Rows are flagged ``auto_archived`` so that :func:`upsert_listing` can
    restore them if a later scan lists them again. One flaky scan that
    misses a posting would otherwise bury it -- including jobs already
    applied to -- for good.

    No-op if cutoff_iso is empty (i.e. no scan has completed yet).
    """
    if not cutoff_iso or not source:
        return 0
    with connect(path) as conn:
        cur = conn.execute(
            "UPDATE jobs SET archived = 1, archived_at = ?, auto_archived = 1 "
            "WHERE archived = 0 AND last_seen_at < ? AND source = ?",
            (now_iso(), cutoff_iso, source),
        )
        conn.commit()
        return cur.rowcount
