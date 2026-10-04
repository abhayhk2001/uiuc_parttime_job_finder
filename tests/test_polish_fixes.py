"""Regressions for the medium/low findings of the October 2026 audit.

Each test pins one defect that shipped and is now fixed.

    python tests/test_polish_fixes.py
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import date
from pathlib import Path

import requests
from PySide6.QtCore import Qt

from support import (  # noqa: E402
    TempDB, check, eq, gui_app, pump_events, qt_only, run_module,
)

from jobscanner import config, matching  # noqa: E402
from jobscanner import storage as db  # noqa: E402


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def test_symbol_keywords_match() -> None:
    """`\\b` needs a word character beside it, so these never matched."""
    text = "Experience with C++, C# and .NET required."
    eq(matching.match(["C++", "C#", ".NET"], text), [".net", "c#", "c++"],
       "keywords starting or ending in a symbol match")
    eq(matching.match(["java"], "JavaScript only"), [],
       "still whole-word: java is not JavaScript")


def test_overlapping_keywords_are_each_reported() -> None:
    eq(matching.match(["data", "data science"], "a data science role"),
       ["data", "data science"], "both overlapping keywords are found")


# ---------------------------------------------------------------------------
# HTTP retries
# ---------------------------------------------------------------------------

class _FakeSession:
    def __init__(self, statuses: list) -> None:
        self.statuses = list(statuses)
        self.calls = 0

    def request(self, method, url, **kwargs):
        self.calls += 1
        status = self.statuses.pop(0)
        if isinstance(status, Exception):
            raise status
        resp = requests.Response()
        resp.status_code = status
        resp.url = url
        return resp


def _no_delay():
    original = config.REQUEST_DELAY_SECONDS
    config.REQUEST_DELAY_SECONDS = 0
    return original


def test_transient_failures_are_retried() -> None:
    from jobscanner.scraper import http

    original = _no_delay()
    try:
        s = _FakeSession([requests.ConnectionError("reset"), 503, 200])
        eq(http.request(s, "GET", "https://e.org").status_code, 200,
           "a dropped connection and a 503 are retried until it works")
        eq(s.calls, 3, "three attempts")
    finally:
        config.REQUEST_DELAY_SECONDS = original


def test_a_404_is_not_retried() -> None:
    from jobscanner.scraper import http

    original = _no_delay()
    try:
        s = _FakeSession([404, 200])
        try:
            http.request(s, "GET", "https://e.org/gone")
        except requests.HTTPError:
            pass
        else:
            raise AssertionError("a 404 must raise")
        eq(s.calls, 1, "a page that is gone is not asked for again")
    finally:
        config.REQUEST_DELAY_SECONDS = original


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def test_research_park_long_slugs_do_not_collide() -> None:
    from jobscanner.sources import research_park

    short = "software-engineer-intern"
    eq(research_park._native_id(short), short, "a slug that fits is unchanged")
    stem = "x" * 70
    a = research_park._native_id(stem + "-alpha")
    b = research_park._native_id(stem + "-beta")
    check(a != b, f"slugs sharing 60 characters get distinct ids ({a}, {b})")
    check(len(a) <= 60 and len(b) <= 60, "and still fit the id length")


def test_library_page_without_openings_section_raises() -> None:
    from jobscanner.sources import library
    from jobscanner.sources.base import ListingParseError

    try:
        library.parse_page("<h1>Library</h1><p>Moved.</p>", "k", "Label")
    except ListingParseError:
        pass
    else:
        raise AssertionError("an unrecognised page must not read as empty")


def test_clearinghouse_unrelated_page_raises() -> None:
    from jobscanner.sources import clearinghouse
    from jobscanner.sources.base import ListingParseError

    try:
        clearinghouse.parse_listing("<html><body>Maintenance</body></html>")
    except ListingParseError:
        pass
    else:
        raise AssertionError("a page with no listing container must raise")


def _seed_stale(p: Path, source: str, job_id: str) -> None:
    db.init_db(p)
    db.upsert_listing({"job_id": job_id, "title": "t", "company": "",
                       "date_posted": "", "detail_url": "https://e.org"}, p)
    with sqlite3.connect(p) as conn:
        conn.execute("UPDATE jobs SET last_seen_at = '2020-01-01T00:00:00+00:00'")
        conn.commit()


def test_a_reliably_empty_board_archives_its_old_rows() -> None:
    """Skipping archive on every empty listing kept a board's postings
    forever once it emptied."""
    from jobscanner import pipeline
    from jobscanner.sources.base import Source

    with TempDB() as p:
        _seed_stale(p, "lib", "lib:gone")
        src = Source(key="lib", label="Library", fetch_listing=lambda: [],
                     empty_is_reliable=True)
        result, _ = pipeline._scan_source(src, [], db.now_iso(), dry_run=False,
                                          verbose=False, fetch_missing=False,
                                          path=p)
        eq(result.archived, 1, "the vanished posting is archived")


def test_backfilled_rows_are_not_announced_as_new() -> None:
    from jobscanner import pipeline
    from jobscanner.sources.base import ListingRow, Source

    row = ListingRow(native_id="1", title="Old job", detail_url="https://e.org",
                     teaser="needs python")
    src = Source(key="rp", label="Research Park", fetch_listing=lambda: [row])
    with TempDB() as p:
        db.init_db(p)
        db.upsert_listing({"job_id": "rp:1", "title": "Old job", "company": "",
                           "date_posted": "", "detail_url": "https://e.org"}, p)
        result, alerts = pipeline._scan_source(
            src, ["python"], db.now_iso(), dry_run=False, verbose=False,
            fetch_missing=True, path=p)
        eq(alerts, [], "a backfilled old row is not alerted as new")
        eq(db.get_job("rp:1", p)["matched_keywords"], "python",
           "but its matches are still recorded")


def test_refetch_unknown_source_signals_failure() -> None:
    from jobscanner import pipeline

    eq(pipeline.refetch_details("nope"), -1, "the CLI can exit non-zero")


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

def test_local_days() -> None:
    from jobscanner import timeutils as t

    eq(t.to_local_date("2026-10-10"), date(2026, 10, 10),
       "a bare date is already a local day, not UTC midnight")
    day = date(2026, 12, 31)
    eq(t.to_local_date(t.local_day_iso(day)), day,
       "a picked local day reads back as the same day")
    eq(t.relative_days(t.now_iso()), "today", "now is today, locally")


# ---------------------------------------------------------------------------
# Data directory and import
# ---------------------------------------------------------------------------

def test_data_dir_override() -> None:
    from jobscanner import paths

    with TempDB() as p:
        os.environ[paths.DATA_DIR_ENV] = str(p.parent / "elsewhere")
        try:
            eq(paths.user_db_path(), p.parent / "elsewhere" / "jobs.db",
               "JOBSCANNER_DATA_DIR moves the database")
        finally:
            del os.environ[paths.DATA_DIR_ENV]


def test_import_replaces_an_empty_destination_but_not_a_used_one() -> None:
    """The first launch of the .app creates an empty, newer DB, and the old
    newer-than-source check then refused every migration."""
    from jobscanner import migrate

    with TempDB() as src, TempDB() as dst:
        db.init_db(src)
        db.upsert_listing({"job_id": "vjb:1", "title": "t", "company": "",
                           "date_posted": "", "detail_url": "x"}, src)
        db.init_db(dst)  # what launching the .app leaves behind
        eq(migrate.import_data(src.parent, None, dst.parent, force=False,
                               dry_run=False), 0, "an empty destination is replaced")
        eq(len(db.get_all_jobs(dst)), 1, "with the source's jobs")
        kept = list(dst.parent.glob("jobs.db.pre-import-*"))
        eq(len(kept), 1, "the replaced file is kept under a non-backup name")
        eq(list(dst.parent.glob("jobs.db.bak.*")), [],
           "and not as a .bak that pruning would count")
        eq(migrate.import_data(src.parent, None, dst.parent, force=False,
                               dry_run=False), 2,
           "a destination holding jobs is refused without --force")


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

def test_toast_survives_the_refresh_that_follows_it() -> None:
    with gui_app() as (app, _path, _kw):
        app.status_bar.showMessage("Scan complete.", 5000)
        app.refresh()
        pump_events()
        eq(app.status_bar.currentMessage(), "Scan complete.",
           "refresh no longer overwrites the message")
        check("jobs" in app._stats_label.text(), "totals live in their own label")


def test_one_refresh_per_section_change() -> None:
    with gui_app() as (app, _path, _kw):
        calls = []
        original = app.refresh
        app.refresh = lambda: (calls.append(1), original())
        sections = app.sidebar._sections
        idx = next(sections._model.index(r, 0)
                   for r in range(sections._model.rowCount())
                   if sections._model.data(sections._model.index(r, 0),
                                           sections._model.KEY_ROLE)
                   == db.SECTION_OLD)
        sections._view.setCurrentIndex(idx)
        sections._view.clicked.emit(idx)
        pump_events()
        eq(len(calls), 1, "a click refreshes once, not two or three times")


def test_job_ids_sort_numerically() -> None:
    from jobscanner.ui_qt.models import _job_id_sort_key

    check(_job_id_sort_key("vjb:99") < _job_id_sort_key("vjb:100"),
          "vjb:99 sorts before vjb:100")


def test_group_heading_counts_visible_jobs() -> None:
    with gui_app(count=4) as (app, _path, _kw):
        app._search_edit.setText("python 0")
        pump_events()
        proxy = app._table.proxy()
        heading = proxy.data(proxy.index(0, 0), Qt.DisplayRole)
        check("(1 of 4)" in heading, f"heading counts what is shown ({heading!r})")


def test_applied_section_keeps_its_follow_up_order() -> None:
    with gui_app() as (app, _path, _kw):
        app.select_section(db.SECTION_FOLLOW_UP)
        eq(app._table.proxy().sortColumn(), -1,
           "Applied opens in follow-up order, not sorted by matches")
        eq(app._table.header().sortIndicatorSection(), -1,
           "and the header shows no sort")
        app.select_section(db.SECTION_NEW)
        check(app._table.proxy().sortColumn() >= 0,
              "ordinary sections sort by matches again")


def test_scan_log_is_not_double_spaced() -> None:
    from jobscanner.ui_qt.workers.scan_worker import ScanWorker, _StreamRelay

    with qt_only():
        worker = ScanWorker()
        lines: list[str] = []
        worker.textWritten.connect(lines.append)

        class _Sink:
            def write(self, s): pass
            def flush(self): pass

        relay = _StreamRelay(worker, _Sink())
        relay.write("[scan] one")
        relay.write("\n")
        relay.write("two\nthr")
        relay.write("ee\n")
        relay.write("tail")
        relay.close()
        eq(lines, ["[scan] one", "two", "three", "tail"],
           "one emission per line, and no blank ones")


def test_right_click_opens_a_job_menu() -> None:
    from PySide6.QtWidgets import QMenu

    with gui_app() as (app, _path, _kw):
        app._table.select_id("T0")
        app._show_job_menu("T0", app.mapToGlobal(app.rect().center()))
        pump_events()
        menus = [m for m in app.findChildren(QMenu) if m.isVisible()]
        check(menus, "a menu is shown")
        labels = [a.text() for a in menus[-1].actions() if a.text()]
        check(any("Mark Reviewed" in t for t in labels),
              f"it offers the job's state actions ({labels})")
        check("&Open in Browser" in labels, "and the browser action")
        menus[-1].close()


def test_theme_change_rebuilds_chips() -> None:
    with gui_app() as (app, _path, _kw):
        app._table.select_id("T0")
        pump_events()
        before = [app.detail.chips_layout.itemAt(i).widget()
                  for i in range(app.detail.chips_layout.count())]
        app.detail.refresh_palette()
        pump_events()
        after = [app.detail.chips_layout.itemAt(i).widget()
                 for i in range(app.detail.chips_layout.count())]
        check(before and after and before[0] is not after[0],
              "chips are re-created so they pick up the new palette")


if __name__ == "__main__":
    _, failed, _ = run_module(globals(), "Polish fixes")
    sys.exit(1 if failed else 0)
