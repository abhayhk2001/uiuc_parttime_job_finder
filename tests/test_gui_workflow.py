"""End-to-end GUI behaviour: sections, selection, the job state machine,
sorting, filtering and the dialogs.

Ported from the CustomTkinter version -- the test intent is identical,
the API calls are Qt equivalents (see :mod:`tests.support`).

    python tests/test_gui_workflow.py
"""

from __future__ import annotations

import json
import sys

from PySide6.QtCore import Qt

from support import check, eq, gui_app, gui_available, pump_events, run_module  # noqa: E402

from jobscanner import storage as db  # noqa: E402
from jobscanner.ui_qt.models import COLUMNS  # noqa: E402


def _col(key: str) -> int:
    """Index of a column by key -- never hardcode positions."""
    for i, column in enumerate(COLUMNS):
        if column.key == key:
            return i
    raise AssertionError(f"no {key!r} column")
from jobscanner.ui_qt import job_actions as ja  # noqa: E402
from jobscanner.ui_qt.models import SORT_ROLE, JobRoles  # noqa: E402


def _row_ids(app) -> list[str]:
    """Return the visible job_ids in the table in current sort order."""
    proxy = app._table.proxy()
    return [
        proxy.data(proxy.index(r, 0), JobRoles.JobIdRole)
        for r in range(proxy.rowCount())
    ]


def test_each_section_queries_without_error() -> None:
    with gui_app() as (app, _path, _kw):
        for section in db.VALID_SECTIONS:
            app.select_section(section)
            pump_events()
            eq(app._section, section, "section should be selected")
        app.select_section(db.SECTION_ALL)
        pump_events()
        eq(app._table.proxy().rowCount(), 6,
           "All should list every seeded job")


def test_selecting_a_row_populates_the_detail_pane() -> None:
    with gui_app() as (app, _path, _kw):
        app.select_section(db.SECTION_ALL)
        pump_events()
        eq(app._table.proxy().rowCount(), 6,
           "all seeded rows are in the All section")
        app._table.select_id("T0")
        pump_events()
        eq(app.detail.job_id, "T0", "detail should follow the selection")
        check("Job 0" in app.detail.title_label.text(),
              "detail shows the job title")
        check("Dept 0" in app.detail.meta_label.text(),
              "detail shows the company")


def test_state_machine_walk() -> None:
    """New -> To Apply -> Follow Up -> Archived -> back."""
    with gui_app() as (app, path, _kw):
        app.select_section(db.SECTION_ALL)
        pump_events()
        app._table.select_id("T0")
        pump_events()

        check(app.detail.primary_btn.text().endswith("Mark Reviewed"),
              "an untouched row offers Mark Reviewed")
        app._run_job_op(app.detail._secondary_op)   # Add to To Apply
        pump_events()
        check(bool(db.get_job("T0", path)["to_apply"]),
              "row moved to To Apply")

        check(app.detail.primary_btn.text().endswith("Mark Applied"),
              "a To Apply row offers Mark Applied")
        app._run_job_op(app.detail._primary_op)     # Mark Applied
        pump_events()
        row = db.get_job("T0", path)
        check(bool(row["applied_at"]) and bool(row["follow_up_at"]),
              "Mark Applied records applied_at and follow_up_at")

        check(app.detail.primary_btn.text().endswith("Further Follow Up"),
              "a Follow Up row offers Mark Further Follow Up")
        check(app.detail.follow_up_btn.isVisible(),
              "the follow-up date editor is offered for Follow Up rows")
        app._run_job_op(app.detail._secondary_op)   # Archive
        pump_events()
        check(bool(db.get_job("T0", path)["archived"]), "row archived")

        check(app.detail.primary_btn.text().endswith("Unarchive"),
              "an archived row offers Unarchive")
        check(not app.detail.secondary_btn.isEnabled(),
              "an archived row's secondary button is disabled")
        app._run_job_op(app.detail._primary_op)     # Unarchive
        pump_events()
        check(not db.get_job("T0", path)["archived"], "row unarchived")


def test_archived_to_apply_row_label_matches_its_action() -> None:
    """Regression: the label and the click handler checked the four flags in
    different orders, so an auto-archived To Apply row showed "Unarchive"
    but ran mark_applied when clicked."""
    with gui_app() as (_app, path, _kw):
        db.set_to_apply("T1", True, path)
        db.archive_job("T1", path)
        state = ja.JobState.from_row(db.get_job("T1", path))
        eq(ja.primary_action(state).op, ja.OP_UNARCHIVE,
           "archived wins over to_apply for both label and action")
        check(not ja.secondary_action(state).enabled,
              "archived row has no secondary action")


def test_follow_up_date_editor_saves() -> None:
    from jobscanner.ui_qt.dialogs.follow_up import FollowUpDialog

    with gui_app() as (app, path, _kw):
        db.mark_applied("T2", path)
        dialog = FollowUpDialog(app, "T2", "",
                               on_save=lambda: None, db_path=path)
        pump_events()
        dialog._apply_offset(30)
        pump_events()
        follow_up = db.get_job("T2", path)["follow_up_at"]
        check(bool(follow_up), "preset wrote a follow-up date")
        check(follow_up > db.now_iso(), "the new date is in the future")


def test_follow_up_presets_each_get_their_own_cell() -> None:
    """Regression: all six presets gridded into column 0 across two rows, so
    three landed in each cell and only the last of each trio was visible."""
    from jobscanner.ui_qt.dialogs.follow_up import FollowUpDialog

    with gui_app() as (app, _path, _kw):
        dialog = FollowUpDialog(app, "T0", "",
                                on_save=lambda: None)
        dialog.resize(460, 300)
        pump_events()
        cells = [(b.grid_row, b.grid_col) for b in dialog.preset_buttons]
        eq(len(set(cells)), len(cells),
           f"every preset needs its own grid cell (cells={cells})")
        eq(len({row for row, _ in cells}), 2,
           "presets form 2 rows of 3")
        dialog.close()


def test_source_column_shows_a_readable_label() -> None:
    """Rows are keyed 'rp:48827'; the table shows the board's name and the
    bare id rather than repeating the prefix."""
    from jobscanner.sources import SOURCE_LABELS

    with gui_app() as (app, path, _kw):
        db.upsert_listing(
            {"job_id": "rp:48827", "title": "Hardware Engineer",
             "company": "Philowave", "date_posted": "",
             "detail_url": "https://e.org", "source": "rp"},
            path=path,
        )
        app.select_section(db.SECTION_ALL)
        app.refresh()
        pump_events()

        proxy = app._table.proxy()
        found = False
        for r in range(proxy.rowCount()):
            job_id = proxy.data(proxy.index(r, _col("job_id")))
            source = proxy.data(proxy.index(r, _col("source")))
            if source == SOURCE_LABELS["rp"]:
                eq(job_id, "48827", "the id column drops the source prefix")
                found = True
        check(found, "the Research Park row shows its board label")


def test_sorting_toggles_and_survives_refresh() -> None:
    with gui_app() as (app, _path, _kw):
        app.select_section(db.SECTION_ALL)
        pump_events()

        job_id_col = _col("job_id")
        app._table.sortByColumn(job_id_col, Qt.AscendingOrder)
        pump_events()
        ascending = _row_ids(app)

        app._table.sortByColumn(job_id_col, Qt.DescendingOrder)
        pump_events()
        descending = _row_ids(app)

        eq(ascending, list(reversed(descending)),
           "clicking the same header twice flips direction")

        hh = app._table.horizontalHeader()
        # Qt's sort indicator is on the model side, not the header.
        eq(app._table.proxy().sortOrder(), Qt.DescendingOrder,
           "proxy reflects the most recent sort direction")

        app.refresh()
        pump_events()
        eq(_row_ids(app), descending,
           "the chosen sort survives a refresh")
        del hh  # unused, kept for clarity in the test


def test_default_sort_is_applied_on_open() -> None:
    """Regression: 'matches' was declared descending-first but no sort ran
    until the user clicked a header, so the table opened in DB order."""
    with gui_app() as (app, _path, _kw):
        eq(app._table.proxy().sortColumn(), _col("matches"),
           "opens sorted by matches")
        eq(app._table.proxy().sortOrder(), Qt.DescendingOrder,
           "matches sorts descending first")

        app.select_section(db.SECTION_ALL)
        pump_events()
        proxy = app._table.proxy()
        counts = [
            int(proxy.data(proxy.index(r, _col("matches")), SORT_ROLE) or 0)
            for r in range(proxy.rowCount())
        ]
        eq(counts, sorted(counts, reverse=True),
           f"rows are ordered by match count on open ({counts})")


def test_search_and_matches_only_filters() -> None:
    with gui_app() as (app, _path, _kw):
        app.select_section(db.SECTION_ALL)
        pump_events()
        app._search_edit.setText("Job 3")
        pump_events()
        eq(app._table.proxy().rowCount(), 1, "search narrows the table")

        app._search_edit.clear()
        pump_events()
        eq(app._table.proxy().rowCount(), 6, "clearing restores rows")

        app._matches_only.setChecked(True)
        app.refresh()
        pump_events()
        eq(app._table.proxy().rowCount(), 3,
           "matches-only keeps the 3 matching rows")


def test_keyword_editor_round_trip() -> None:
    from jobscanner.ui_qt.dialogs.keywords import KeywordsDialog

    with gui_app() as (app, _path, kw_path):
        editor = KeywordsDialog(app, kw_path, on_save=lambda _k: None)
        pump_events()
        check("python" in editor._editor.toPlainText(),
              "the editor loads the existing keywords")
        editor._editor.setPlainText("alpha\nbeta\nALPHA\n")
        editor._save_and_accept()
        pump_events()

        saved = json.loads(kw_path.read_text())
        eq(saved, ["alpha", "beta"],
           "save de-duplicates case-insensitively and drops blanks")


def test_sidebar_counts_and_keyword_list() -> None:
    with gui_app() as (app, path, _kw):
        app.refresh()
        pump_events()
        counts = db.get_section_counts(path)

        # Walk the sidebar's section model directly and find the New row.
        from jobscanner.ui_qt.models import JobRoles as _JR  # noqa: F401
        from jobscanner.ui_qt.sidebar import _SectionsModel
        sections_model = app.sidebar._sections._model
        new_label = None
        for r in range(sections_model.rowCount()):
            if sections_model.data(sections_model.index(r, 0),
                                   _SectionsModel.KEY_ROLE) == db.SECTION_NEW:
                new_label = sections_model.data(sections_model.index(r, 0),
                                                Qt.DisplayRole)
                break
        check(new_label is not None and f"({counts['new']})" in new_label,
              f"sidebar shows the live New count ({new_label!r})")
        check("2 loaded" in app.sidebar._keywords._count_label.text(),
              "sidebar shows the keyword count")


def test_log_buffers_while_collapsed() -> None:
    """Regression: output logged while the console was hidden was dropped,
    so opening it mid-scan showed an empty box."""
    with gui_app() as (app, _path, _kw):
        # Earlier tests may have left the dock visible via QSettings.
        # Force the hidden state for this test.
        app.log_dock.hide()
        pump_events()
        check(not app.log_dock.isVisible(),
              "the log dock starts hidden")
        # The new design always buffers; output appended while hidden
        # shows up when the dock is opened.
        app.log_dock.append("written while collapsed\n")
        app._toggle_log()
        pump_events()
        check("written while collapsed" in app.log_dock._text.toPlainText(),
              "buffered output is replayed on open")
        app._toggle_log()
        pump_events()


def test_layout_is_persisted() -> None:
    """Splitter sizes round-trip through QSettings."""
    with gui_app() as (app, _path, _kw):
        app.splitter.setSizes([600, 600])
        pump_events()
        # QSplitter clamps sizes to its children's minSizeHint, so
        # persist what Qt actually accepted rather than what we asked for.
        saved = app.splitter.sizes()
        app.close()

    with gui_app() as (app, _path, _kw):
        eq(app.splitter.sizes(), saved,
           "splitter sizes round-trip through QSettings")


if __name__ == "__main__":
    ok, reason = gui_available()
    _, failed, _ = run_module(globals(), "GUI workflow",
                              skip_reason="" if ok else reason)
    sys.exit(1 if failed else 0)
