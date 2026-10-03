"""Regressions found by auditing the user journeys on mainline.

Each test here pins one defect that was shipped and is now fixed.

    python tests/test_audit_fixes.py
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from PySide6.QtCore import Qt

from support import (  # noqa: E402
    TempDB, check, eq, gui_available, pump_events, qt_only, run_module,
)

from jobscanner import storage as db  # noqa: E402


# ---------------------------------------------------------------------------
# 1. Theme switch left job-row colours stale
# ---------------------------------------------------------------------------

def test_palette_refresh_invalidates_job_rows_not_just_sections() -> None:
    """The grouped model's first refresh_palette only emitted dataChanged for
    the top-level section rows, so the match/reviewed colours on the jobs
    underneath never repainted after a theme switch."""
    with qt_only():
        from jobscanner.ui_qt.models import JobsTreeModel

        model = JobsTreeModel()
        model.set_rows([
            {"job_id": "vjb:1", "source": "vjb", "title": "A", "company": "",
             "matched_keywords": "python", "reviewed": 0},
            {"job_id": "vjb:2", "source": "vjb", "title": "B", "company": "",
             "matched_keywords": "", "reviewed": 1},
            {"job_id": "rp:3", "source": "rp", "title": "C", "company": "",
             "matched_keywords": "ai", "reviewed": 0},
        ])
        seen: list = []
        model.dataChanged.connect(
            lambda tl, br, roles: seen.append(
                ("job" if tl.internalPointer() is not None else "section",
                 tl.row(), br.row())))
        model.refresh_palette()

        check(any(kind == "job" for kind, _, _ in seen),
              f"job rows must be invalidated too (got {seen})")
        check(any(kind == "section" for kind, _, _ in seen),
              "section rows are still invalidated")
        # One signal per populated group, covering that group's whole range.
        job_sigs = [(t, b) for kind, t, b in seen if kind == "job"]
        eq(len(job_sigs), 2, f"one signal per group with rows (got {job_sigs})")


def test_palette_refresh_on_an_empty_model_is_safe() -> None:
    with qt_only():
        from jobscanner.ui_qt.models import JobsTreeModel
        model = JobsTreeModel()
        model.set_rows([])
        model.refresh_palette()   # must not raise or emit nonsense
        eq(model.rowCount(), 0, "no groups, no signals, no crash")


# ---------------------------------------------------------------------------
# 2. Delisted jobs that were never reviewed were never archived
# ---------------------------------------------------------------------------

def _seed(path: Path, ids, stale_ids, source: str = "vjb") -> None:
    db.init_db(path)
    for jid in ids:
        db.upsert_listing({"job_id": f"{source}:{jid}", "title": jid,
                           "company": "", "date_posted": "",
                           "detail_url": "", "source": source}, path=path)
    with sqlite3.connect(path) as conn:
        for jid in stale_ids:
            conn.execute(
                "UPDATE jobs SET last_seen_at = '2020-01-01T00:00:00+00:00' "
                "WHERE job_id = ?", (f"{source}:{jid}",))
        conn.commit()


def test_an_untouched_delisted_job_is_archived() -> None:
    """Twelve of fifteen Research Park rows were in this state: gone from the
    board, never reviewed, and therefore never archived -- they accumulated
    in Old as jobs nobody could apply to."""
    with TempDB() as p:
        _seed(p, ["a", "b"], stale_ids=["a"])
        n = db.auto_archive_removed_jobs("2026-01-01T00:00:00+00:00", "vjb", p)
        eq(n, 1, "the delisted row archives even though it was never reviewed")
        rows = {r["job_id"]: r for r in db.get_all_jobs(p)}
        eq(rows["vjb:a"]["archived"], 1, "delisted row archived")
        eq(rows["vjb:b"]["archived"], 0, "still-listed row untouched")


def test_archiving_stays_scoped_to_one_source() -> None:
    """Widening the predicate must not widen the scope."""
    with TempDB() as p:
        _seed(p, ["x"], stale_ids=["x"], source="vjb")
        _seed(p, ["y"], stale_ids=["y"], source="rp")
        n = db.auto_archive_removed_jobs("2026-01-01T00:00:00+00:00", "vjb", p)
        eq(n, 1, "only the named source is swept")
        rows = {r["job_id"]: r for r in db.get_all_jobs(p)}
        eq(rows["vjb:x"]["archived"], 1, "vjb row archived")
        eq(rows["rp:y"]["archived"], 0, "rp row untouched by a vjb sweep")


def test_an_empty_listing_archives_nothing() -> None:
    """A parser that breaks without raising returns [] -- the Library source
    does exactly that. Archiving on an empty listing would wipe the source,
    so the pipeline skips it."""
    from jobscanner import pipeline
    from jobscanner.sources.base import Source

    with TempDB() as p:
        _seed(p, ["a", "b"], stale_ids=["a", "b"], source="lib")
        empty = Source(key="lib", label="University Library",
                       fetch_listing=lambda: [], supports_detail=False)
        result, _ = pipeline._scan_source(
            empty, [], "2026-01-01T00:00:00+00:00",
            dry_run=False, verbose=False, fetch_missing=False, path=p)

        check(result.ok, "an empty board is a success, not a failure")
        eq(result.listed, 0, "nothing listed")
        eq(result.archived, 0, "and nothing archived")
        rows = db.get_all_jobs(p)
        check(all(not r["archived"] for r in rows),
              "every row survives an empty listing")


def test_a_failed_fetch_archives_nothing() -> None:
    from jobscanner import pipeline
    from jobscanner.sources.base import Source

    def _boom():
        raise RuntimeError("network down")

    with TempDB() as p:
        _seed(p, ["a"], stale_ids=["a"], source="rp")
        broken = Source(key="rp", label="Research Park",
                        fetch_listing=_boom, supports_detail=False)
        result, _ = pipeline._scan_source(
            broken, [], "2026-01-01T00:00:00+00:00",
            dry_run=False, verbose=False, fetch_missing=False, path=p)

        check(not result.ok, "the failure is reported")
        check("network down" in result.error, f"error recorded: {result.error!r}")
        eq(result.archived, 0, "a failed source archives nothing")
        check(not db.get_all_jobs(p)[0]["archived"], "its rows survive")


# ---------------------------------------------------------------------------
# 3. A scan ignored the caller's db_path
# ---------------------------------------------------------------------------

def test_scan_writes_to_the_given_database() -> None:
    """pipeline.run took no path, so a GUI opened against one database would
    have scanned into whichever one config pointed at."""
    from jobscanner import config, pipeline
    from jobscanner.sources.base import ListingRow, Source

    row = ListingRow(native_id="1", title="Fake Job", detail_url="http://e.org",
                     company="Co", teaser="some text")
    fake = Source(key="rp", label="Research Park",
                  fetch_listing=lambda: [row], supports_detail=False)

    with TempDB() as p:
        db.init_db(p)
        before_real = len(db.get_all_jobs(config.DB_PATH)) \
            if config.DB_PATH.exists() else 0
        result, _ = pipeline._scan_source(
            fake, [], db.now_iso(), dry_run=False, verbose=False,
            fetch_missing=False, path=p)
        eq(result.new, 1, "the row was inserted")
        eq([r["job_id"] for r in db.get_all_jobs(p)], ["rp:1"],
           "written to the database we asked for")
        after_real = len(db.get_all_jobs(config.DB_PATH)) \
            if config.DB_PATH.exists() else 0
        eq(after_real, before_real,
           "and the configured database was left alone")


# ---------------------------------------------------------------------------
# 4. Window state leaked into the shared Python preferences file
# ---------------------------------------------------------------------------

def test_settings_scope_is_named_explicitly() -> None:
    """A bare QSettings() only resolves correctly after launch() sets the
    application name. Constructing the window directly -- as the tests and
    any embedding caller do -- wrote window/geometry and the appearance
    override into org.python.python.Python.plist, leaking between runs."""
    with qt_only():
        from jobscanner.ui_qt.settings import APP, ORG, app_settings

        s = app_settings()
        eq(s.organizationName(), ORG, "organisation is named")
        eq(s.applicationName(), APP, "application is named")
        check("python" not in Path(s.fileName()).name.lower(),
              f"must not be the shared Python plist ({s.fileName()})")
        check(APP.lower() in Path(s.fileName()).name.lower(),
              f"settings land in this app's own file ({s.fileName()})")


def test_no_module_constructs_a_bare_qsettings() -> None:
    """The whole point of settings.py -- keep it that way."""
    offenders = []
    for path in Path("src/jobscanner").rglob("*.py"):
        if path.name == "settings.py":
            continue
        for i, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or "``" in line:
                continue
            if "QSettings()" in line:
                offenders.append(f"{path}:{i}")
    eq(offenders, [], f"use app_settings() instead (found {offenders})")


if __name__ == "__main__":
    ok, reason = gui_available()
    _, failed, _ = run_module(globals(), "Audit fixes",
                              skip_reason="" if ok else reason)
    sys.exit(1 if failed else 0)
