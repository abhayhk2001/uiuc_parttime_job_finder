"""Job rows: reads, writes, and the To Apply / Follow Up / Archive
state transitions."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from jobscanner import config
from jobscanner.storage.meta import get_latest_scan_started_at
from jobscanner.storage.schema import connect
from jobscanner.storage.sections import (
    SECTION_ALL,
    SECTION_FOLLOW_UP,
    VALID_SECTIONS,
    _follow_up_clause,
    section_clause,
)
from jobscanner.timeutils import add_days_iso, now_iso

# ---------------------------------------------------------------------------
# Scan-time writes
# ---------------------------------------------------------------------------


def upsert_listing(job: dict, path: Path = config.DB_PATH) -> bool:
    """Insert new job row (returning True if newly inserted) or update last_seen_at."""
    now = now_iso()
    with connect(path) as conn:
        exists = conn.execute(
            "SELECT 1 FROM jobs WHERE job_id = ?", (job["job_id"],)
        ).fetchone() is not None
        if exists:
            conn.execute(
                "UPDATE jobs SET last_seen_at = ?, title = COALESCE(NULLIF(?, ''), title), "
                "company = COALESCE(NULLIF(?, ''), company), date_posted = COALESCE(NULLIF(?, ''), date_posted) "
                "WHERE job_id = ?",
                (now, job.get("title", ""), job.get("company", ""),
                 job.get("date_posted", ""), job["job_id"]),
            )
            conn.commit()
            return False
        conn.execute(
            "INSERT INTO jobs (job_id, title, company, date_posted, detail_url, "
            "first_seen_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                job["job_id"],
                job.get("title", ""),
                job.get("company", ""),
                job.get("date_posted", ""),
                job.get("detail_url", ""),
                now,
                now,
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
    path: Path = config.DB_PATH,
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


def get_existing_job_ids(path: Path = config.DB_PATH) -> set[str]:
    with connect(path) as conn:
        return {row[0] for row in conn.execute("SELECT job_id FROM jobs").fetchall()}


def get_jobs_missing_details(path: Path = config.DB_PATH) -> list[str]:
    with connect(path) as conn:
        cur = conn.execute(
            "SELECT job_id FROM jobs WHERE (job_description IS NULL OR job_description = '') "
            "AND (requirements IS NULL OR requirements = '') AND (skills IS NULL OR skills = '')"
        )
        return [row[0] for row in cur.fetchall()]


def get_job(job_id: str, path: Path = config.DB_PATH) -> dict | None:
    with connect(path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return dict(row) if row else None


def get_all_jobs(path: Path = config.DB_PATH) -> list[dict]:
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
    path: Path = config.DB_PATH,
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
    path: Path = config.DB_PATH,
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
    "archived = 0, archived_at = NULL"
)


def _applied_params() -> tuple[str, str]:
    now = now_iso()
    return now, add_days_iso(now, config.FOLLOW_UP_WINDOW_DAYS)


def mark_applied(
    job_id: str,
    path: Path = config.DB_PATH,
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
    path: Path = config.DB_PATH,
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
    path: Path = config.DB_PATH,
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
    path: Path = config.DB_PATH,
) -> None:
    """Mark a job as archived (sets archived=1, archived_at=now)."""
    with connect(path) as conn:
        conn.execute(
            "UPDATE jobs SET archived = 1, archived_at = ? WHERE job_id = ?",
            (now_iso(), job_id),
        )
        conn.commit()


def unarchive_job(
    job_id: str,
    path: Path = config.DB_PATH,
) -> None:
    """Restore a job from Archived (clears archived + archived_at). The
    job's other flags determine which section it lands in."""
    with connect(path) as conn:
        conn.execute(
            "UPDATE jobs SET archived = 0, archived_at = NULL WHERE job_id = ?",
            (job_id,),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Bulk transitions
# ---------------------------------------------------------------------------


def bulk_set_reviewed(
    section: str,
    reviewed: bool,
    path: Path = config.DB_PATH,
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


def bulk_mark_all_applied(path: Path = config.DB_PATH) -> int:
    """Apply the full Applied transition to every To Apply job.

    Uses the same assignments as :func:`mark_applied`, so bulk-applied rows
    land in Follow Up with `applied_at` / `follow_up_at` recorded, rather
    than stopping at Reviewed.
    """
    with connect(path) as conn:
        cur = conn.execute(
            f"UPDATE jobs SET {_APPLIED_ASSIGNMENTS} WHERE to_apply = 1",
            _applied_params(),
        )
        conn.commit()
        return cur.rowcount


def bulk_clear_to_apply(path: Path = config.DB_PATH) -> int:
    """Clear `to_apply` for every To Apply job (without marking reviewed)."""
    with connect(path) as conn:
        cur = conn.execute("UPDATE jobs SET to_apply = 0 WHERE to_apply = 1")
        conn.commit()
        return cur.rowcount


def bulk_archive_section(
    section: str,
    path: Path = config.DB_PATH,
) -> int:
    """Archive every job in `section` (only Follow Up makes sense today)."""
    if section != SECTION_FOLLOW_UP:
        raise ValueError(
            f"bulk_archive_section only supports {SECTION_FOLLOW_UP!r}"
        )
    clause, params = _follow_up_clause()
    with connect(path) as conn:
        cur = conn.execute(
            f"UPDATE jobs SET archived = 1, archived_at = ? WHERE {clause}",
            (now_iso(), *params),
        )
        conn.commit()
        return cur.rowcount


def bulk_mark_further_follow_up(
    section: str,
    days: int = config.FOLLOW_UP_WINDOW_DAYS,
    path: Path = config.DB_PATH,
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
    path: Path = config.DB_PATH,
) -> int:
    """Archive any *active* job that wasn't re-seen in the latest scan.

    Active = reviewed=1 OR to_apply=1 (Follow Up rows have reviewed=1 too,
    so they're included).  Cutoff is the ``latest_scan_started_at``
    timestamp; rows with ``last_seen_at < cutoff`` were not seen in that
    scan and are therefore no longer listed on VJB.

    No-op if cutoff_iso is empty (i.e. no scan has completed yet).
    """
    if not cutoff_iso:
        return 0
    with connect(path) as conn:
        cur = conn.execute(
            "UPDATE jobs SET archived = 1, archived_at = ? "
            "WHERE archived = 0 AND (reviewed = 1 OR to_apply = 1) "
            "AND last_seen_at < ?",
            (now_iso(), cutoff_iso),
        )
        conn.commit()
        return cur.rowcount
