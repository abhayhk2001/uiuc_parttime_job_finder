"""Smoke tests for db.py against a temporary SQLite DB.

Each test gets its own temp directory, so they can run in any order
without interfering with each other or with the user's real database.
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import db  # noqa: E402


# ---------------------------------------------------------------------------
# Tiny test helpers (no pytest dependency required)
# ---------------------------------------------------------------------------

class _TestFailed(AssertionError):
    pass


def _check(cond: bool, msg: str) -> None:
    if not cond:
        raise _TestFailed(msg)


def _eq(a, b, msg: str = "") -> None:
    if a != b:
        raise _TestFailed(f"{msg}: expected {b!r}, got {a!r}")


class _TempDB:
    """Context manager that yields a fresh DB path inside a temp dir,
    cleaning up after the test."""

    def __init__(self) -> None:
        self.dir: Path | None = None
        self.path: Path | None = None

    def __enter__(self) -> Path:
        self.dir = Path(tempfile.mkdtemp(prefix="db_isolated_"))
        self.path = self.dir / "jobs.db"
        return self.path

    def __exit__(self, *exc) -> None:
        if self.dir and self.dir.exists():
            shutil.rmtree(self.dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_init_creates_schema_and_indexes() -> None:
    with _TempDB() as p:
        db.init_db(p)
        cols = {row[1] for row in
                sqlite3.connect(p).execute("PRAGMA table_info(jobs)").fetchall()}
        expected = {
            "job_id", "title", "company", "date_posted", "detail_url",
            "job_description", "requirements", "skills",
            "first_seen_at", "last_seen_at", "matched_keywords",
            "reviewed", "to_apply",
        }
        _check(expected.issubset(cols),
               f"missing columns: {sorted(expected - cols)}")
        meta_cols = {row[1] for row in
                     sqlite3.connect(p).execute("PRAGMA table_info(meta)").fetchall()}
        _check({"key", "value"}.issubset(meta_cols),
               f"missing meta columns: {meta_cols}")


def test_init_idempotent() -> None:
    with _TempDB() as p:
        db.init_db(p)
        db.init_db(p)
        db.init_db(p)
        # All three runs should succeed without error.


def test_upsert_listing_inserts_then_updates() -> None:
    with _TempDB() as p:
        db.init_db(p)
        first = db.upsert_listing(
            {"job_id": "A1", "title": "First", "company": "X",
             "date_posted": "", "detail_url": "http://x"},
            path=p,
        )
        _check(first is True, "first upsert should return True")
        time.sleep(1.05)
        second = db.upsert_listing(
            {"job_id": "A1", "title": "First", "company": "X",
             "date_posted": "", "detail_url": "http://x"},
            path=p,
        )
        _check(second is False, "second upsert should return False")
        row = db.get_job("A1", p)
        _check(row is not None, "row should exist")
        # `last_seen_at` should advance; `first_seen_at` should not.
        _check(row["first_seen_at"] != row["last_seen_at"],
               "last_seen_at should advance on re-upsert")


def test_upsert_does_not_touch_reviewed_or_to_apply() -> None:
    with _TempDB() as p:
        db.init_db(p)
        db.upsert_listing(
            {"job_id": "B1", "title": "B", "company": "",
             "date_posted": "", "detail_url": ""},
            path=p,
        )
        db.set_reviewed("B1", True, p)
        db.set_to_apply("B1", True, p)
        time.sleep(1.05)
        db.upsert_listing(
            {"job_id": "B1", "title": "B-updated", "company": "Co",
             "date_posted": "", "detail_url": ""},
            path=p,
        )
        row = db.get_job("B1", p)
        _check(bool(row["reviewed"]), "reviewed flag must survive upsert")
        _check(bool(row["to_apply"]), "to_apply flag must survive upsert")
        _check(row["title"] == "B-updated", "title should have updated")


def test_update_details_does_not_touch_reviewed_or_to_apply() -> None:
    with _TempDB() as p:
        db.init_db(p)
        db.upsert_listing(
            {"job_id": "C1", "title": "C", "company": "",
             "date_posted": "", "detail_url": ""},
            path=p,
        )
        db.set_reviewed("C1", True, p)
        db.set_to_apply("C1", True, p)
        db.update_details("C1", "desc", "reqs", "skills", ["python"], path=p)
        row = db.get_job("C1", p)
        _check(bool(row["reviewed"]), "reviewed flag must survive update_details")
        _check(bool(row["to_apply"]), "to_apply flag must survive update_details")
        _check(row["job_description"] == "desc", "description should be set")
        _check(row["matched_keywords"] == "python", "keywords should be set")


def test_mark_applied_is_atomic() -> None:
    with _TempDB() as p:
        db.init_db(p)
        db.upsert_listing(
            {"job_id": "D1", "title": "D", "company": "",
             "date_posted": "", "detail_url": ""},
            path=p,
        )
        db.set_to_apply("D1", True, p)
        db.mark_applied("D1", p)
        row = db.get_job("D1", p)
        _check(row["to_apply"] == 0, "to_apply should be 0 after mark_applied")
        _check(row["reviewed"] == 1, "reviewed should be 1 after mark_applied")


def test_section_counts_and_queries() -> None:
    with _TempDB() as p:
        db.init_db(p)
        for i in range(3):
            db.upsert_listing(
                {"job_id": f"E{i}", "title": f"E{i}", "company": "",
                 "date_posted": "", "detail_url": ""},
                path=p,
            )
        # Set a scan cutoff so New/Old distinctions work.
        db.set_latest_scan_started_at(
            datetime.now(timezone.utc).isoformat(timespec="seconds"), p,
        )
        _eq(db.get_section_counts(p)["new"], 3,
            "3 unreviewed rows should be in New")
        _eq(db.get_section_counts(p)["old"], 0,
            "Old should be empty with no historical rows")

        # Mark one as reviewed, one as to_apply.
        db.set_reviewed("E0", True, p)
        db.set_to_apply("E1", True, p)
        counts = db.get_section_counts(p)
        _eq(counts["new"], 1, "only E2 should remain in New")
        _eq(counts["reviewed"], 1, "E0 should be Reviewed")
        _eq(counts["to_apply"], 1, "E1 should be To Apply")

        # bulk_mark_all_applied clears to_apply and adds reviewed.
        n = db.bulk_mark_all_applied(p)
        _eq(n, 1, "exactly 1 row should be marked applied")
        _eq(db.get_section_counts(p)["reviewed"], 2, "Reviewed should be 2")
        _eq(db.get_section_counts(p)["to_apply"], 0, "To Apply should be 0")


def test_bulk_actions_are_scoped_to_section() -> None:
    with _TempDB() as p:
        db.init_db(p)
        for i in range(5):
            db.upsert_listing(
                {"job_id": f"F{i}", "title": f"F{i}", "company": "",
                 "date_posted": "", "detail_url": ""},
                path=p,
            )
        # Mark F0..F3 reviewed, leave F4 alone.
        for i in range(4):
            db.set_reviewed(f"F{i}", True, p)
        # Pin the cutoff in the future so no row qualifies as "New".
        # (All rows have first_seen_at < cutoff → all unreviewed are in Old.)
        db.set_latest_scan_started_at("2099-01-01T00:00:00+00:00", p)
        # bulk_set_reviewed(NEW) is a no-op for an empty section.
        _eq(db.bulk_set_reviewed(db.SECTION_NEW, True, p), 0,
            "New is empty; bulk should affect 0 rows")
        # bulk_set_reviewed(REVIEWED, False) clears all 4 reviewed rows.
        n = db.bulk_set_reviewed(db.SECTION_REVIEWED, False, p)
        _eq(n, 4, "should clear all 4 reviewed rows")


def test_backup_and_restore_round_trip() -> None:
    with _TempDB() as p:
        db.init_db(p)
        db.upsert_listing(
            {"job_id": "G1", "title": "Original", "company": "",
             "date_posted": "", "detail_url": ""},
            path=p,
        )
        # backup_db returns None when DB doesn't exist.
        _eq(db.backup_db(p.with_name("nonexistent.db")), None,
            "missing DB should yield None")
        # First real backup.
        b1 = db.backup_db(p)
        _check(b1 is not None and b1.exists(),
               "first backup should exist")
        # Mutate the live DB.
        db.upsert_listing(
            {"job_id": "G1", "title": "Mutated", "company": "",
             "date_posted": "", "detail_url": ""},
            path=p,
        )
        # Restore from backup.
        shutil.copy2(b1, p)
        row = db.get_job("G1", p)
        _eq(row["title"], "Original",
            "restored DB should show the pre-mutation title")


def test_prune_keeps_most_recent_n() -> None:
    with _TempDB() as p:
        db.init_db(p)
        db.upsert_listing(
            {"job_id": "H1", "title": "H", "company": "",
             "date_posted": "", "detail_url": ""},
            path=p,
        )
        # Create 5 backups spaced out in time so the timestamps differ.
        backups = []
        for _ in range(5):
            time.sleep(1.05)
            backups.append(db.backup_db(p))
        _check(all(b and b.exists() for b in backups),
               "all 5 backups should exist")
        deleted = db.prune_old_backups(p, keep=2)
        _eq(deleted, 3, "should delete 3 older backups")
        remaining = sorted(p.parent.glob(p.name + ".bak.*"))
        _eq(len(remaining), 2,
            "exactly 2 backups should remain after prune")


def test_sash_widths_round_trip() -> None:
    with _TempDB() as p:
        db.init_db(p)
        _eq(db.get_sash_widths(p), None, "no sash widths before set")
        db.set_sash_widths([250, 800, 400], p)
        _eq(db.get_sash_widths(p), [250, 800, 400],
            "sash widths round-trip")
        # Invalid JSON is gracefully ignored.
        with sqlite3.connect(p) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                (db.META_KEY_SASH_WIDTHS, "not-valid-json"),
            )
            conn.commit()
        _eq(db.get_sash_widths(p), None,
            "invalid JSON should yield None")


# ---------------------------------------------------------------------------
# Test runner (no pytest required)
# ---------------------------------------------------------------------------

def _run_all() -> tuple[int, int]:
    tests = [
        test_init_creates_schema_and_indexes,
        test_init_idempotent,
        test_upsert_listing_inserts_then_updates,
        test_upsert_does_not_touch_reviewed_or_to_apply,
        test_update_details_does_not_touch_reviewed_or_to_apply,
        test_mark_applied_is_atomic,
        test_section_counts_and_queries,
        test_bulk_actions_are_scoped_to_section,
        test_backup_and_restore_round_trip,
        test_prune_keeps_most_recent_n,
        test_sash_widths_round_trip,
    ]
    passed = 0
    failed = 0
    for fn in tests:
        name = fn.__name__
        try:
            fn()
        except _TestFailed as exc:
            failed += 1
            print(f"  FAIL  {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {name}: {exc!r}")
        else:
            passed += 1
            print(f"  ok    {name}")
    print()
    print(f"{passed} passed, {failed} failed.")
    return passed, failed


if __name__ == "__main__":
    p, f = _run_all()
    sys.exit(0 if f == 0 else 1)
