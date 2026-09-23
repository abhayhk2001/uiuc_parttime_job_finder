"""Section definitions: the single source of truth for what "New", "Old",
"Reviewed", "To Apply", "Follow Up" and "Archived" mean in SQL.

Before this module the same predicates were written out in five places
(the clause helpers, `get_jobs_by_section`, `get_section_counts`,
`bulk_set_reviewed` and `get_stats`) and had already drifted apart. Every
section query now goes through :func:`section_clause`.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from jobscanner import config
from jobscanner.storage.meta import get_latest_scan_started_at
from jobscanner.storage.schema import connect

SECTION_NEW = "new"
SECTION_OLD = "old"
SECTION_REVIEWED = "reviewed"
SECTION_TO_APPLY = "to_apply"
SECTION_FOLLOW_UP = "follow_up"
SECTION_ARCHIVED = "archived"
SECTION_ALL = "all"

# Rows that are neither triaged nor filed away — the pool New and Old split.
_UNTRIAGED = "reviewed = 0 AND to_apply = 0 AND archived = 0"

_ORDER_BY_DEFAULT = "first_seen_at DESC"
_ORDER_BY_FOLLOW_UP = (
    "CASE WHEN follow_up_at IS NULL THEN 1 ELSE 0 END, "
    "follow_up_at ASC, first_seen_at DESC"
)
_ORDER_BY_ARCHIVED = (
    "CASE WHEN archived_at IS NULL THEN 1 ELSE 0 END, "
    "archived_at DESC, first_seen_at DESC"
)


def _new_clause(cutoff: str = "") -> tuple[str, list]:
    """Unreviewed, un-flagged, unarchived rows discovered in the latest scan.

    With no recorded scan yet, every untriaged row counts as New.
    """
    if not cutoff:
        return (_UNTRIAGED, [])
    return (f"{_UNTRIAGED} AND first_seen_at >= ?", [cutoff])


def _old_clause(cutoff: str = "") -> tuple[str, list]:
    """Untriaged rows that pre-date the latest scan. Empty until one runs."""
    if not cutoff:
        return ("1 = 0", [])
    return (f"{_UNTRIAGED} AND first_seen_at < ?", [cutoff])


def _reviewed_clause(cutoff: str = "") -> tuple[str, list]:
    """Looked at, but not applied to and not archived."""
    return ("reviewed = 1 AND applied_at IS NULL AND archived = 0", [])


def _to_apply_clause(cutoff: str = "") -> tuple[str, list]:
    return ("to_apply = 1 AND archived = 0", [])


def _follow_up_clause(cutoff: str = "") -> tuple[str, list]:
    return ("reviewed = 1 AND applied_at IS NOT NULL AND archived = 0", [])


def _archived_clause(cutoff: str = "") -> tuple[str, list]:
    return ("archived = 1", [])


def _all_clause(cutoff: str = "") -> tuple[str, list]:
    return ("", [])


@dataclass(frozen=True)
class Section:
    """One row-bucket the UI can select."""

    key: str
    label: str
    clause: Callable[[str], tuple[str, list]]
    order_by: str = _ORDER_BY_DEFAULT
    #: Whether this section appears as a counted bucket in the sidebar.
    counted: bool = True


SECTIONS: tuple[Section, ...] = (
    Section(SECTION_NEW, "New", _new_clause),
    Section(SECTION_OLD, "Old", _old_clause),
    Section(SECTION_REVIEWED, "Reviewed", _reviewed_clause),
    Section(SECTION_TO_APPLY, "To Apply", _to_apply_clause),
    Section(SECTION_FOLLOW_UP, "Follow Up", _follow_up_clause,
            order_by=_ORDER_BY_FOLLOW_UP),
    Section(SECTION_ARCHIVED, "Archived", _archived_clause,
            order_by=_ORDER_BY_ARCHIVED),
    Section(SECTION_ALL, "All", _all_clause, counted=False),
)

SECTIONS_BY_KEY: dict[str, Section] = {s.key: s for s in SECTIONS}
VALID_SECTIONS: tuple[str, ...] = tuple(s.key for s in SECTIONS)
#: Sections that get a live count in the sidebar, in display order.
COUNTED_SECTIONS: tuple[str, ...] = tuple(s.key for s in SECTIONS if s.counted)
SECTION_LABELS: dict[str, str] = {s.key: s.label for s in SECTIONS}


def section_clause(section: str, cutoff: str) -> tuple[str, list]:
    """Return ``(sql_predicate, params)`` for `section`.

    The predicate is ``''`` for :data:`SECTION_ALL`, which matches everything.
    """
    try:
        spec = SECTIONS_BY_KEY[section]
    except KeyError:
        raise ValueError(f"Unknown section: {section!r}") from None
    return spec.clause(cutoff)


def get_jobs_by_section(
    section: str,
    query: str = "",
    matches_only: bool = False,
    path: Path = config.DB_PATH,
) -> list[dict]:
    """Return jobs belonging to `section` (one of VALID_SECTIONS),
    optionally narrowed by free-text `query` and/or `matches_only`."""
    spec = SECTIONS_BY_KEY.get(section)
    if spec is None:
        raise ValueError(f"Unknown section: {section!r}")

    clause, params = spec.clause(get_latest_scan_started_at(path))
    clauses = [clause] if clause else []

    if matches_only:
        clauses.append("(matched_keywords IS NOT NULL AND matched_keywords != '')")
    if query.strip():
        like = f"%{query.strip().lower()}%"
        clauses.append(
            "(LOWER(title) LIKE ? OR LOWER(company) LIKE ? "
            "OR LOWER(job_description) LIKE ? OR LOWER(requirements) LIKE ? "
            "OR LOWER(skills) LIKE ? OR LOWER(matched_keywords) LIKE ?)"
        )
        params.extend([like] * 6)

    sql = "SELECT * FROM jobs"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    # Per-section default ordering — overridable via the GUI's column sort.
    sql += f" ORDER BY {spec.order_by}"

    with connect(path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_section_counts(path: Path = config.DB_PATH) -> dict:
    """Row count per counted section, plus ``total``."""
    cutoff = get_latest_scan_started_at(path)
    counts: dict[str, int] = {}
    with connect(path) as conn:
        for key in COUNTED_SECTIONS:
            clause, params = section_clause(key, cutoff)
            sql = "SELECT COUNT(*) FROM jobs"
            if clause:
                sql += f" WHERE {clause}"
            counts[key] = conn.execute(sql, tuple(params)).fetchone()[0]
        counts["total"] = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    return counts


def get_stats(path: Path = config.DB_PATH) -> dict:
    """Whole-database totals for the status bar.

    Note ``reviewed`` and ``to_apply`` here are raw flag counts across the
    entire table, so they intentionally differ from the same-named keys in
    :func:`get_section_counts`, which count *section membership* and
    therefore exclude applied/archived rows. ``follow_up`` and ``archived``
    do come from the section registry and agree with the sidebar.
    """
    fu_clause, _ = _follow_up_clause()
    ar_clause, _ = _archived_clause()
    with connect(path) as conn:
        def _count(where: str) -> int:
            return conn.execute(
                f"SELECT COUNT(*) FROM jobs WHERE {where}"
            ).fetchone()[0]

        total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        matching = _count(
            "matched_keywords IS NOT NULL AND matched_keywords != ''"
        )
        with_details = _count(
            "(job_description IS NOT NULL AND job_description != '')"
            "OR (requirements IS NOT NULL AND requirements != '')"
            "OR (skills IS NOT NULL AND skills != '')"
        )
        reviewed = _count("reviewed = 1")
        to_apply = _count("to_apply = 1")
        follow_up = _count(fu_clause)
        archived = _count(ar_clause)
        last_seen = conn.execute(
            "SELECT MAX(last_seen_at) FROM jobs"
        ).fetchone()[0]
    return {
        "total": total,
        "matching": matching,
        "with_details": with_details,
        "reviewed": reviewed,
        "to_apply": to_apply,
        "follow_up": follow_up,
        "archived": archived,
        "last_seen_at": last_seen or "",
    }
