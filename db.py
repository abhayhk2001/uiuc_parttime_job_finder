import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import config


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
  reviewed         INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_first_seen ON jobs(first_seen_at);
"""


META_KEY_LATEST_SCAN_STARTED_AT = "latest_scan_started_at"


def now_iso() -> str:
    """Public alias: return the current UTC time as ISO-8601 (seconds)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _now() -> str:
    return now_iso()


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def init_db(path: Path = config.DB_PATH) -> None:
    """Create the schema if needed and run any pending migrations."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()
        cols = _table_columns(conn, "jobs")
        if "reviewed" not in cols:
            conn.execute(
                "ALTER TABLE jobs ADD COLUMN reviewed INTEGER NOT NULL DEFAULT 0"
            )
        if "first_seen_at" in cols:
            try:
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_jobs_first_seen "
                    "ON jobs(first_seen_at)"
                )
            except Exception:
                pass
        if "reviewed" in cols:
            try:
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_jobs_reviewed "
                    "ON jobs(reviewed)"
                )
            except Exception:
                pass
        conn.commit()


def _connect(path: Path = config.DB_PATH) -> sqlite3.Connection:
    return sqlite3.connect(path)


def upsert_listing(job: dict, path: Path = config.DB_PATH) -> bool:
    """Insert new job row (returning True if newly inserted) or update last_seen_at."""
    now = _now()
    with _connect(path) as conn:
        cur = conn.execute("SELECT 1 FROM jobs WHERE job_id = ?", (job["job_id"],))
        exists = cur.fetchone() is not None
        if exists:
            conn.execute(
                "UPDATE jobs SET last_seen_at = ?, title = COALESCE(NULLIF(?, ''), title), "
                "company = COALESCE(NULLIF(?, ''), company), date_posted = COALESCE(NULLIF(?, ''), date_posted) "
                "WHERE job_id = ?",
                (now, job.get("title", ""), job.get("company", ""), job.get("date_posted", ""), job["job_id"]),
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
    with _connect(path) as conn:
        conn.execute(
            "UPDATE jobs SET job_description = ?, requirements = ?, skills = ?, "
            "matched_keywords = ? WHERE job_id = ?",
            (job_description, requirements, skills, matches, job_id),
        )
        conn.commit()


def get_existing_job_ids(path: Path = config.DB_PATH) -> set[str]:
    with _connect(path) as conn:
        cur = conn.execute("SELECT job_id FROM jobs")
        return {row[0] for row in cur.fetchall()}


def get_jobs_missing_details(path: Path = config.DB_PATH) -> list[str]:
    with _connect(path) as conn:
        cur = conn.execute(
            "SELECT job_id FROM jobs WHERE (job_description IS NULL OR job_description = '') "
            "AND (requirements IS NULL OR requirements = '') AND (skills IS NULL OR skills = '')"
        )
        return [row[0] for row in cur.fetchall()]


def get_job(job_id: str, path: Path = config.DB_PATH) -> dict | None:
    with _connect(path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_all_jobs(path: Path = config.DB_PATH) -> list[dict]:
    with _connect(path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM jobs ORDER BY first_seen_at DESC")
        return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Sections / reviewed-state
# ---------------------------------------------------------------------------

SECTION_NEW = "new"
SECTION_OLD = "old"
SECTION_REVIEWED = "reviewed"
SECTION_ALL = "all"
VALID_SECTIONS = (SECTION_NEW, SECTION_OLD, SECTION_REVIEWED, SECTION_ALL)


def get_latest_scan_started_at(path: Path = config.DB_PATH) -> str:
    """ISO timestamp of the most recent completed scan, or ``''`` if none."""
    with _connect(path) as conn:
        cur = conn.execute(
            "SELECT value FROM meta WHERE key = ?",
            (META_KEY_LATEST_SCAN_STARTED_AT,),
        )
        row = cur.fetchone()
    return row[0] if row else ""


def set_latest_scan_started_at(
    value: str,
    path: Path = config.DB_PATH,
) -> None:
    with _connect(path) as conn:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (META_KEY_LATEST_SCAN_STARTED_AT, value),
        )
        conn.commit()


def _new_clause(cutoff: str) -> tuple[str, list]:
    """Return (sql_clause, params) for the New section.

    When there's no recorded scan yet, every unreviewed row counts as New
    (they're all newly inserted relative to a non-existent past).
    """
    if not cutoff:
        return ("reviewed = 0", [])
    return ("reviewed = 0 AND first_seen_at >= ?", [cutoff])


def _old_clause(cutoff: str) -> tuple[str, list]:
    """Return (sql_clause, params) for the Old section."""
    if not cutoff:
        return ("1 = 0", [])  # no Old jobs until a scan has happened
    return ("reviewed = 0 AND first_seen_at < ?", [cutoff])


def get_jobs_by_section(
    section: str,
    query: str = "",
    matches_only: bool = False,
    path: Path = config.DB_PATH,
) -> list[dict]:
    """Return jobs belonging to `section` (one of VALID_SECTIONS),
    optionally narrowed by free-text `query` and/or `matches_only`."""
    if section not in VALID_SECTIONS:
        raise ValueError(f"Unknown section: {section!r}")

    cutoff = get_latest_scan_started_at(path)
    clauses: list[str] = []
    params: list = []
    if section == SECTION_NEW:
        clause, extra = _new_clause(cutoff)
        clauses.append(clause)
        params.extend(extra)
    elif section == SECTION_OLD:
        clause, extra = _old_clause(cutoff)
        clauses.append(clause)
        params.extend(extra)
    elif section == SECTION_REVIEWED:
        clauses.append("reviewed = 1")

    if matches_only:
        clauses.append("(matched_keywords IS NOT NULL AND matched_keywords != '')")
    if query.strip():
        like = f"%{query.strip()}%"
        clauses.append(
            "(LOWER(title) LIKE ? OR LOWER(company) LIKE ? "
            "OR LOWER(job_description) LIKE ? OR LOWER(requirements) LIKE ? "
            "OR LOWER(skills) LIKE ? OR LOWER(matched_keywords) LIKE ?)"
        )
        params.extend([like.lower()] * 6)

    sql = "SELECT * FROM jobs"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY first_seen_at DESC"

    with _connect(path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def get_section_counts(path: Path = config.DB_PATH) -> dict:
    cutoff = get_latest_scan_started_at(path)
    with _connect(path) as conn:
        new_clause, new_params = _new_clause(cutoff)
        old_clause, old_params = _old_clause(cutoff)
        new_n = conn.execute(
            f"SELECT COUNT(*) FROM jobs WHERE {new_clause}",
            tuple(new_params),
        ).fetchone()[0]
        old_n = conn.execute(
            f"SELECT COUNT(*) FROM jobs WHERE {old_clause}",
            tuple(old_params),
        ).fetchone()[0]
        reviewed_n = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE reviewed = 1"
        ).fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    return {"new": new_n, "old": old_n, "reviewed": reviewed_n, "total": total}


def set_reviewed(
    job_id: str,
    reviewed: bool,
    path: Path = config.DB_PATH,
) -> None:
    val = 1 if reviewed else 0
    with _connect(path) as conn:
        conn.execute(
            "UPDATE jobs SET reviewed = ? WHERE job_id = ?",
            (val, job_id),
        )
        conn.commit()


def bulk_set_reviewed(
    section: str,
    reviewed: bool,
    path: Path = config.DB_PATH,
) -> int:
    """Set reviewed flag for all jobs in `section`. Returns row count changed."""
    if section not in VALID_SECTIONS or section == SECTION_ALL:
        raise ValueError(f"bulk_set_reviewed only accepts "
                         f"{SECTION_NEW!r}/{SECTION_OLD!r}/{SECTION_REVIEWED!r}")
    val = 1 if reviewed else 0
    cutoff = get_latest_scan_started_at(path)

    if section == SECTION_NEW:
        if not cutoff:
            sql = "UPDATE jobs SET reviewed = ? WHERE reviewed = 0"
            params: tuple = (val,)
        else:
            sql = ("UPDATE jobs SET reviewed = ? "
                   "WHERE reviewed = 0 AND first_seen_at >= ?")
            params = (val, cutoff)
    elif section == SECTION_OLD:
        if not cutoff:
            sql = "UPDATE jobs SET reviewed = ? WHERE 1 = 0"
            params = (val,)
        else:
            sql = ("UPDATE jobs SET reviewed = ? "
                   "WHERE reviewed = 0 AND first_seen_at < ?")
            params = (val, cutoff)
    else:  # SECTION_REVIEWED
        sql = "UPDATE jobs SET reviewed = ? WHERE reviewed = 1"
        params = (val,)

    with _connect(path) as conn:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.rowcount


def get_stats(path: Path = config.DB_PATH) -> dict:
    with _connect(path) as conn:
        total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        matching = conn.execute(
            "SELECT COUNT(*) FROM jobs "
            "WHERE matched_keywords IS NOT NULL AND matched_keywords != ''"
        ).fetchone()[0]
        with_details = conn.execute(
            "SELECT COUNT(*) FROM jobs "
            "WHERE (job_description IS NOT NULL AND job_description != '')"
            "OR (requirements IS NOT NULL AND requirements != '')"
            "OR (skills IS NOT NULL AND skills != '')"
        ).fetchone()[0]
        reviewed = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE reviewed = 1"
        ).fetchone()[0]
        last_seen = conn.execute(
            "SELECT MAX(last_seen_at) FROM jobs"
        ).fetchone()[0]
    return {
        "total": total,
        "matching": matching,
        "with_details": with_details,
        "reviewed": reviewed,
        "last_seen_at": last_seen or "",
    }
