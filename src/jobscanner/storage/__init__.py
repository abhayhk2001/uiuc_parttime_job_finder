"""SQLite persistence layer.

Split across four focused modules; this package re-exports the whole public
surface so callers can keep saying ``from jobscanner import storage as db``
and reach everything as ``db.<name>``.

    schema    table definitions, connection helper, migrations
    meta      the key/value meta table (scan cutoff, UI layout)
    sections  what each row-bucket means, in one place
    jobs      row reads/writes and the state transitions
    backup    pre-scan snapshots of the DB file
"""

from jobscanner.timeutils import add_days_iso, now_iso

from jobscanner.storage.backup import (
    _backup_basename,
    backup_db,
    prune_old_backups,
)
from jobscanner.storage.jobs import (
    archive_job,
    auto_archive_removed_jobs,
    bulk_archive_section,
    bulk_clear_to_apply,
    bulk_mark_all_applied,
    bulk_mark_further_follow_up,
    bulk_set_reviewed,
    get_all_jobs,
    get_existing_job_ids,
    get_job,
    get_jobs_missing_details,
    mark_applied,
    mark_further_follow_up,
    set_follow_up,
    set_reviewed,
    set_to_apply,
    unarchive_job,
    update_details,
    upsert_listing,
)
from jobscanner.storage.meta import (
    DEFAULT_LAYOUT,
    META_KEY_LATEST_SCAN_STARTED_AT,
    META_KEY_LAYOUT,
    META_KEY_SASH_WIDTHS,
    get_layout,
    get_latest_scan_started_at,
    get_meta,
    get_sash_widths,
    set_latest_scan_started_at,
    set_layout,
    set_meta,
    set_sash_widths,
)
from jobscanner.storage.schema import SCHEMA, _connect, connect, init_db
from jobscanner.storage.sections import (
    COUNTED_SECTIONS,
    SECTION_ALL,
    SECTION_ARCHIVED,
    SECTION_FOLLOW_UP,
    SECTION_LABELS,
    SECTION_NEW,
    SECTION_OLD,
    SECTION_REVIEWED,
    SECTION_TO_APPLY,
    SECTIONS,
    SECTIONS_BY_KEY,
    VALID_SECTIONS,
    Section,
    get_jobs_by_section,
    get_section_counts,
    get_stats,
    section_clause,
)

#: Historical private alias; use :func:`jobscanner.timeutils.add_days_iso`.
_add_days_iso = add_days_iso

__all__ = [
    # schema
    "SCHEMA", "init_db", "connect", "_connect",
    # time
    "now_iso", "add_days_iso",
    # meta
    "META_KEY_LATEST_SCAN_STARTED_AT", "META_KEY_SASH_WIDTHS",
    "META_KEY_LAYOUT", "DEFAULT_LAYOUT", "get_layout", "set_layout",
    "get_meta", "set_meta",
    "get_latest_scan_started_at", "set_latest_scan_started_at",
    "get_sash_widths", "set_sash_widths",
    # sections
    "Section", "SECTIONS", "SECTIONS_BY_KEY", "SECTION_LABELS",
    "VALID_SECTIONS", "COUNTED_SECTIONS", "section_clause",
    "SECTION_NEW", "SECTION_OLD", "SECTION_REVIEWED", "SECTION_TO_APPLY",
    "SECTION_FOLLOW_UP", "SECTION_ARCHIVED", "SECTION_ALL",
    "get_jobs_by_section", "get_section_counts", "get_stats",
    # jobs
    "upsert_listing", "update_details", "get_job", "get_all_jobs",
    "get_existing_job_ids", "get_jobs_missing_details",
    "set_reviewed", "set_to_apply", "mark_applied",
    "set_follow_up", "mark_further_follow_up",
    "archive_job", "unarchive_job", "auto_archive_removed_jobs",
    "bulk_set_reviewed", "bulk_mark_all_applied", "bulk_clear_to_apply",
    "bulk_archive_section", "bulk_mark_further_follow_up",
    # backup
    "backup_db", "prune_old_backups",
]
