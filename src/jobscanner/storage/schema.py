"""Schema definition, connection helper, and idempotent migrations."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from jobscanner import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  job_id           TEXT PRIMARY KEY,
  title            TEXT,
  company          TEXT,
  date_posted      TEXT,
  detail_url       TEXT NOT NULL,
  job_description  TEXT,
  requirements     TEXT,
  skills           TEXT,
  first_seen_at    TEXT NOT NULL,
  last_seen_at     TEXT NOT NULL,
  matched_keywords TEXT,
  reviewed         INTEGER NOT NULL DEFAULT 0,
  to_apply         INTEGER NOT NULL DEFAULT 0,
  applied_at       TEXT,
  follow_up_at     TEXT,
  archived         INTEGER NOT NULL DEFAULT 0,
  archived_at      TEXT,
  source           TEXT NOT NULL DEFAULT 'vjb',
  auto_archived    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_first_seen ON jobs(first_seen_at);
"""

# Columns added after the original schema shipped. Older DBs get them via
# ALTER TABLE on the next init_db().
_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("reviewed", "INTEGER NOT NULL DEFAULT 0"),
    ("to_apply", "INTEGER NOT NULL DEFAULT 0"),
    ("applied_at", "TEXT"),
    ("follow_up_at", "TEXT"),
    ("archived", "INTEGER NOT NULL DEFAULT 0"),
    ("archived_at", "TEXT"),
    # Added when the scanner grew beyond the Virtual Job Board. Every row
    # that predates multi-source support came from VJB, hence the default.
    ("source", "TEXT NOT NULL DEFAULT 'vjb'"),
    # 1 when the scanner archived the row because it left its board, so a
    # later scan that lists it again knows it may restore it. Rows the user
    # archived by hand keep 0 and stay archived.
    ("auto_archived", "INTEGER NOT NULL DEFAULT 0"),
)

# Indexes worth having once the backing column exists.
_INDEXES: tuple[tuple[str, str], ...] = (
    ("idx_jobs_first_seen", "first_seen_at"),
    ("idx_jobs_reviewed", "reviewed"),
    ("idx_jobs_to_apply", "to_apply"),
    ("idx_jobs_archived", "archived"),
    ("idx_jobs_source", "source"),
)


#: Prefix applied to job ids that predate multi-source support.
LEGACY_SOURCE = "vjb"


def _namespace_legacy_ids(conn: sqlite3.Connection) -> int:
    """Prefix pre-multi-source job ids with their source.

    Job ids used to be the bare VJB post id ("48447"). Research Park post
    ids live in the same five-digit range (48827 was live when this was
    written), so without a namespace a Research Park posting could collide
    with a real VJB job and silently overwrite it through upsert_listing.

    Guarded on the separator so re-running is a no-op -- this must never
    double-prefix an already-migrated row.
    """
    cur = conn.execute(
        "UPDATE jobs SET job_id = ? || job_id, source = ? "
        "WHERE instr(job_id, ':') = 0",
        (f"{LEGACY_SOURCE}:", LEGACY_SOURCE),
    )
    return cur.rowcount


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def resolve(path: Optional[Path]) -> Path:
    """`path`, or the configured DB when it is None.

    Read at call time rather than bound as a default argument: a default of
    ``config.DB_PATH`` is evaluated once at import, so redirecting
    ``config.DB_PATH`` afterwards (as the test suite does) would silently
    leave every defaulted call pointed at the real database.
    """
    return Path(path) if path else config.DB_PATH


@contextmanager
def connect(path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    """Open a connection for one `with connect(p) as conn:` block.

    Commits on success, rolls back on error, and always closes -- sqlite3's
    own context manager does the first two but leaves the connection open.
    """
    conn = sqlite3.connect(resolve(path))
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db(path: Optional[Path] = None) -> None:
    """Create the schema if needed and run any pending migrations."""
    path = resolve(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()
        cols = _table_columns(conn, "jobs")
        for name, decl in _MIGRATIONS:
            if name not in cols:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {decl}")
        cols = _table_columns(conn, "jobs")
        if "source" in cols:
            _namespace_legacy_ids(conn)
        for index_name, column in _INDEXES:
            if column not in cols:
                continue
            try:
                conn.execute(
                    f"CREATE INDEX IF NOT EXISTS {index_name} ON jobs({column})"
                )
            except Exception:
                # An index is an optimization; never let one block startup.
                pass
        conn.commit()


# Back-compat alias: `_connect` was the historical name.
_connect = connect
