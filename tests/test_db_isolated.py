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
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from jobscanner import config  # noqa: E402
from jobscanner import storage as db  # noqa: E402


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
# Follow Up / Archived
# ---------------------------------------------------------------------------

def test_mark_applied_records_timestamps() -> None:
    with _TempDB() as p:
        db.init_db(p)
        db.upsert_listing(
            {"job_id": "FA1", "title": "FA", "company": "",
             "date_posted": "", "detail_url": ""},
            path=p,
        )
        db.set_to_apply("FA1", True, p)
        # `now_iso()` truncates to second precision — match that here so the
        # range check is meaningful.
        before = datetime.now(timezone.utc).replace(microsecond=0)
        db.mark_applied("FA1", p)
        after = datetime.now(timezone.utc).replace(microsecond=0)
        row = db.get_job("FA1", p)
        # applied_at must parse as a UTC ISO timestamp between before & after.
        applied_at = datetime.fromisoformat(row["applied_at"])
        _check(before <= applied_at <= after,
               f"applied_at {row['applied_at']} out of range")
        # follow_up_at must be applied_at + FOLLOW_UP_WINDOW_DAYS.
        follow_up_at = datetime.fromisoformat(row["follow_up_at"])
        delta = follow_up_at - applied_at
        _eq(delta.days, config.FOLLOW_UP_WINDOW_DAYS,
            "follow_up_at should be applied_at + window")
        # Flag flags flipped.
        _check(row["to_apply"] == 0, "to_apply should be 0")
        _check(row["reviewed"] == 1, "reviewed should be 1")
        _check(row["archived"] == 0, "archived should be 0")


def test_mark_further_follow_up_resets_clock() -> None:
    with _TempDB() as p:
        db.init_db(p)
        db.upsert_listing(
            {"job_id": "FF1", "title": "FF", "company": "",
             "date_posted": "", "detail_url": ""},
            path=p,
        )
        # Set a known past follow_up_at.
        with sqlite3.connect(p) as conn:
            conn.execute(
                "UPDATE jobs SET reviewed = 1, applied_at = '2025-01-01T00:00:00+00:00', "
                "follow_up_at = '2025-01-08T00:00:00+00:00' WHERE job_id = 'FF1'"
            )
            conn.commit()
        before = datetime.now(timezone.utc).replace(microsecond=0)
        db.mark_further_follow_up("FF1", path=p)
        after = datetime.now(timezone.utc).replace(microsecond=0)
        # follow_up_at should be `before + FOLLOW_UP_WINDOW_DAYS` (truncated to seconds).
        expected_low = (before + timedelta(days=config.FOLLOW_UP_WINDOW_DAYS))
        expected_high = (after + timedelta(days=config.FOLLOW_UP_WINDOW_DAYS))
        new_fu = datetime.fromisoformat(db.get_job("FF1", p)["follow_up_at"])
        _check(expected_low <= new_fu <= expected_high,
               f"follow_up_at {new_fu.isoformat()} not in "
               f"[{expected_low.isoformat()}, {expected_high.isoformat()}]")


def test_archive_and_unarchive_round_trip() -> None:
    with _TempDB() as p:
        db.init_db(p)
        db.upsert_listing(
            {"job_id": "AR1", "title": "AR", "company": "",
             "date_posted": "", "detail_url": ""},
            path=p,
        )
        db.set_reviewed("AR1", True, p)
        db.archive_job("AR1", p)
        row = db.get_job("AR1", p)
        _check(row["archived"] == 1, "archived flag should be set")
        _check(bool(row["archived_at"]), "archived_at should be populated")
        _check(db.get_section_counts(p)["archived"] == 1,
               "AR1 should appear in Archived section")
        # Unarchive.
        db.unarchive_job("AR1", p)
        row = db.get_job("AR1", p)
        _check(row["archived"] == 0, "archived should be cleared")
        _check(row["archived_at"] is None, "archived_at should be NULL")
        _check(db.get_section_counts(p)["reviewed"] == 1,
               "AR1 should return to Reviewed section")


def test_section_predicates_isolate_follow_up_and_archived() -> None:
    with _TempDB() as p:
        db.init_db(p)
        for jid in ("A", "B", "C", "D"):
            db.upsert_listing(
                {"job_id": jid, "title": jid, "company": "",
                 "date_posted": "", "detail_url": ""},
                path=p,
            )
        db.set_reviewed("A", True, p)            # in Reviewed
        db.mark_applied("B", p) if False else None  # marker; mark below
        # B: in To Apply → mark applied → Follow Up
        db.set_to_apply("B", True, p)
        db.mark_applied("B", p)
        # C: archive directly
        db.set_reviewed("C", True, p)
        db.archive_job("C", p)
        # D: stay unreviewed
        # Force cutoff to future so D is in Old.
        db.set_latest_scan_started_at("2099-01-01T00:00:00+00:00", p)

        counts = db.get_section_counts(p)
        _eq(counts["reviewed"], 1, "A should be the only Reviewed row")
        _eq(counts["follow_up"], 1, "B should be in Follow Up")
        _eq(counts["archived"], 1, "C should be in Archived")

        fu_rows = db.get_jobs_by_section(db.SECTION_FOLLOW_UP, path=p)
        _eq([r["job_id"] for r in fu_rows], ["B"],
            "Follow Up should list only B")

        ar_rows = db.get_jobs_by_section(db.SECTION_ARCHIVED, path=p)
        _eq([r["job_id"] for r in ar_rows], ["C"],
            "Archived should list only C")

        # Follow Up orders by follow_up_at ASC (overdue first); B has future
        # follow_up_at so it's the only row.
        _check(fu_rows[0]["job_id"] == "B", "expected B to be in Follow Up")

        # Archived orders by archived_at DESC.
        _check(ar_rows[0]["job_id"] == "C", "expected C to be in Archived")


def test_auto_archive_removed_jobs_archives_only_active_rows() -> None:
    with _TempDB() as p:
        db.init_db(p)
        for jid in ("A", "B", "C", "D"):
            db.upsert_listing(
                {"job_id": jid, "title": jid, "company": "",
                 "date_posted": "", "detail_url": ""},
                path=p,
            )
        # Pin all rows to an old last_seen_at.
        with sqlite3.connect(p) as conn:
            conn.execute(
                "UPDATE jobs SET last_seen_at = '2020-01-01T00:00:00+00:00'"
            )
            conn.commit()
        # Mark some as active.
        db.set_reviewed("A", True, p)
        db.set_to_apply("B", True, p)
        db.mark_applied("C", p)  # also reviewed=1, applied, in Follow Up
        # D stays unreviewed (in New/Old).

        cutoff = "2026-09-23T00:00:00+00:00"  # newer than last_seen_at
        archived_n = db.auto_archive_removed_jobs(cutoff, p)
        _eq(archived_n, 3, "A, B, C should auto-archive; D stays unreviewed")

        rows = {r["job_id"]: r for r in db.get_all_jobs(p)}
        _check(rows["A"]["archived"] == 1, "A should be archived")
        _check(rows["B"]["archived"] == 1, "B should be archived")
        _check(rows["C"]["archived"] == 1, "C should be archived")
        _check(rows["D"]["archived"] == 0, "D should NOT be archived")

        # No-op when cutoff is empty.
        _eq(db.auto_archive_removed_jobs("", p), 0,
            "empty cutoff should be a no-op")


def test_bulk_follow_up_actions() -> None:
    with _TempDB() as p:
        db.init_db(p)
        for jid in ("F1", "F2", "F3", "RX"):
            db.upsert_listing(
                {"job_id": jid, "title": jid, "company": "",
                 "date_posted": "", "detail_url": ""},
                path=p,
            )
        db.mark_applied("F1", p)
        db.mark_applied("F2", p)
        db.mark_applied("F3", p)
        # RX is reviewed but never applied.
        db.set_reviewed("RX", True, p)
        # Pin F1 follow_up_at to a known value so we can detect the reset.
        with sqlite3.connect(p) as conn:
            conn.execute(
                "UPDATE jobs SET follow_up_at = '2020-01-01T00:00:00+00:00' "
                "WHERE job_id = 'F1'"
            )
            conn.commit()

        before = datetime.now(timezone.utc).replace(microsecond=0)
        n = db.bulk_mark_further_follow_up(db.SECTION_FOLLOW_UP, path=p)
        after = datetime.now(timezone.utc).replace(microsecond=0)
        _eq(n, 3, "all three Follow Up rows should be updated")

        expected_low = (before + timedelta(days=config.FOLLOW_UP_WINDOW_DAYS))
        expected_high = (after + timedelta(days=config.FOLLOW_UP_WINDOW_DAYS))
        new_fu = datetime.fromisoformat(db.get_job("F1", p)["follow_up_at"])
        _check(expected_low <= new_fu <= expected_high,
               f"follow_up_at {new_fu.isoformat()} not in range")

        # Archive all Follow Up.
        n = db.bulk_archive_section(db.SECTION_FOLLOW_UP, p)
        _eq(n, 3, "3 Follow Up rows should be archived")
        _eq(db.get_section_counts(p)["archived"], 3,
            "all 3 should land in Archived")
        _eq(db.get_section_counts(p)["follow_up"], 0,
            "Follow Up section should be empty")


def test_set_follow_up_overrides_default() -> None:
    with _TempDB() as p:
        db.init_db(p)
        db.upsert_listing(
            {"job_id": "SF1", "title": "SF", "company": "",
             "date_posted": "", "detail_url": ""},
            path=p,
        )
        db.mark_applied("SF1", p)
        db.set_follow_up("SF1", "2099-12-31T00:00:00+00:00", p)
        row = db.get_job("SF1", p)
        _eq(row["follow_up_at"], "2099-12-31T00:00:00+00:00",
            "explicit set_follow_up should override default")


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
        test_mark_applied_records_timestamps,
        test_mark_further_follow_up_resets_clock,
        test_archive_and_unarchive_round_trip,
        test_section_predicates_isolate_follow_up_and_archived,
        test_auto_archive_removed_jobs_archives_only_active_rows,
        test_bulk_follow_up_actions,
        test_set_follow_up_overrides_default,
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
