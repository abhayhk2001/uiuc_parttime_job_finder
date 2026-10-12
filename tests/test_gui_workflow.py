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
    """Visible job_ids in display order, sections flattened.

    Rows are grouped per source, so proxy().rowCount() counts *sections*;
    the view exposes this walk so tests never do it by hand.
    """
    return app._table.visible_job_ids()


def _job_count(app) -> int:
    return app._table.visible_job_count()


def test_each_section_queries_without_error() -> None:
    with gui_app() as (app, _path, _kw):
        for section in db.VALID_SECTIONS:
            app.select_section(section)
            pump_events()
            eq(app._section, section, "section should be selected")
        app.select_section(db.SECTION_ALL)
        pump_events()
        eq(_job_count(app), 6, "All should list every seeded job")


def test_selecting_a_row_populates_the_detail_pane() -> None:
    with gui_app() as (app, _path, _kw):
        app.select_section(db.SECTION_ALL)
        pump_events()
        eq(_job_count(app), 6, "all seeded rows are in the All section")
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

        check(app.detail.primary_btn.text().endswith("Add to To Apply"),
              "an untouched row offers Add to To Apply as the main action")
        check(app.detail.secondary_btn.text().endswith("Mark Reviewed"),
              "Mark Reviewed is the secondary action on an untouched row")
        app._run_job_op(app.detail._primary_op)     # Add to To Apply
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


def test_sections_are_grouped_by_source_in_registry_order() -> None:
    """Rows are grouped into a collapsible section per board. The source has
    no column of its own -- the board's name is the section heading."""
    from jobscanner.sources import SOURCE_LABELS

    with gui_app() as (app, path, _kw):
        for job_id, source in (("rp:48827", "rp"), ("ach:70", "ach")):
            db.upsert_listing(
                {"job_id": job_id, "title": f"Job {job_id}", "company": "X",
                 "date_posted": "", "detail_url": "https://e.org",
                 "source": source},
                path=path,
            )
        app.select_section(db.SECTION_ALL)
        app.refresh()
        pump_events()

        table = app._table
        # Seeded rows are vjb; plus the rp and ach rows just added.
        eq(table.visible_group_keys(), ["vjb", "rp", "ach"],
           "sections follow registry order, not alphabetical")
        eq(table.proxy().rowCount(), 3, "one section per source present")

        model = table.source_model()
        headings = []
        for i in range(table.proxy().rowCount()):
            src = table.proxy().mapToSource(table.proxy().index(i, 0))
            headings.append(model.group_at(src.row()).heading)
        check(any(SOURCE_LABELS["rp"] in h and "(1)" in h for h in headings),
              f"the Research Park heading carries its count ({headings})")

        check("source" not in [c.key for c in COLUMNS],
              "source must not also be a column")

        # A section heading is not a job.
        group_idx = table.proxy().index(0, 0)
        check(table.proxy().data(group_idx, JobRoles.JobIdRole) is None,
              "a heading has no job id")
        table.setCurrentIndex(group_idx)
        pump_events()
        check(table.selected_id() is None,
              "selecting a heading selects no job")


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

        # Qt's sort indicator is on the model side, not the header.
        eq(app._table.proxy().sortOrder(), Qt.DescendingOrder,
           "proxy reflects the most recent sort direction")

        app.refresh()
        pump_events()
        eq(_row_ids(app), descending,
           "the chosen sort survives a refresh")
        eq(app._table.visible_group_keys(), ["vjb"],
           "sorting must not reshuffle the sections")


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
        parent = proxy.index(0, 0)  # the single seeded section
        counts = [
            int(proxy.data(proxy.index(r, _col("matches"), parent), SORT_ROLE) or 0)
            for r in range(proxy.rowCount(parent))
        ]
        eq(counts, sorted(counts, reverse=True),
           f"rows are ordered by match count on open ({counts})")


def test_search_and_matches_only_filters() -> None:
    with gui_app() as (app, _path, _kw):
        app.select_section(db.SECTION_ALL)
        pump_events()
        app._search_edit.setText("Job 3")
        pump_events()
        eq(_job_count(app), 1, "search narrows the table")

        app._search_edit.clear()
        pump_events()
        eq(_job_count(app), 6, "clearing restores rows")

        app._matches_only.setChecked(True)
        app.refresh()
        pump_events()
        eq(_job_count(app), 3,
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


def test_scan_on_open_toggle_persists() -> None:
    """The Settings → Run scan on open check persists through QSettings."""
    with gui_app() as (app, _path, _kw):
        eq(app.actions.scan_on_open.isChecked(), False,
           "scan-on-open defaults to off")
        # trigger() toggles the checkable action, which emits `toggled`.
        app.actions.scan_on_open.trigger()
        pump_events()
        eq(app._scan_on_open_enabled(), True, "toggle persisted on")
        app.actions.scan_on_open.trigger()
        pump_events()
        eq(app._scan_on_open_enabled(), False, "toggle persisted off")


def test_action_removing_row_advances_selection() -> None:
    """After an action moves the current job out of the section, focus lands
    on the next listing without a click."""
    with gui_app() as (app, path, _kw):
        app.select_section(db.SECTION_NEW)
        pump_events()
        ids = app._table.visible_job_ids()
        eq(len(ids), 6, "all seeded rows start in New")
        first = ids[0]
        app._table.select_id(first)
        pump_events()
        eq(app._table.selected_id(), first, "first row selected")
        # Primary on an unreviewed row is now "Add to To Apply", which moves
        # it out of New.
        app._run_job_op(app.detail._primary_op)
        pump_events()
        check(bool(db.get_job(first, path)["to_apply"]), "row left New")
        check(app._table.selected_id() is not None,
              "a row is still selected after the action")
        check(app._table.selected_id() != first,
              "selection advanced past the removed row")


def test_mark_not_applied_reverts_job() -> None:
    """Applied rows offer Mark Not Applied, which reverts them to Reviewed."""
    with gui_app() as (app, path, _kw):
        db.mark_applied("T2", path)
        app.select_section(db.SECTION_FOLLOW_UP)
        pump_events()
        app._table.select_id("T2")
        pump_events()
        check(app.detail.not_applied_btn.isVisible(),
              "applied rows offer Mark Not Applied")
        app._mark_selected_not_applied()
        pump_events()
        row = db.get_job("T2", path)
        eq(row["applied_at"], None, "applied_at cleared")
        eq(db.get_section_counts(path)["follow_up"], 0, "leaves Applied")


def test_applied_context_menu_offers_mark_not_applied() -> None:
    from PySide6.QtWidgets import QMenu

    with gui_app() as (app, path, _kw):
        db.mark_applied("T2", path)
        app._show_job_menu("T2", app.mapToGlobal(app.rect().center()))
        pump_events()
        menus = [m for m in app.findChildren(QMenu) if m.isVisible()]
        labels = [a.text() for a in menus[-1].actions() if a.text()]
        check("Mark Not Applied" in labels,
              f"menu offers Mark Not Applied ({labels})")
        check(any("Edit Follow-up Date" in t for t in labels),
              "menu offers the follow-up editor for an applied row")
        menus[-1].close()


def test_archived_applied_job_still_offers_follow_up() -> None:
    """A job the user applied to but that left the listing (archived) can
    still be followed up on."""
    with gui_app() as (app, path, _kw):
        db.mark_applied("T3", path)
        db.archive_job("T3", path)
        app.select_section(db.SECTION_ARCHIVED)
        pump_events()
        app._table.select_id("T3")
        pump_events()
        check(app.detail.follow_up_btn.isVisible(),
              "archived applied rows still offer the follow-up editor")
        check(app.detail.not_applied_btn.isVisible(),
              "and Mark Not Applied")


def test_follow_up_alerts_dialog_builds() -> None:
    from jobscanner.ui_qt.dialogs.follow_up_alerts import FollowUpAlertsDialog

    with gui_app() as (app, path, _kw):
        db.mark_applied("T4", path)
        db.set_follow_up("T4", "2020-01-01T00:00:00+00:00", path)
        jobs = db.get_follow_up_alerts(path)
        check(jobs, "the overdue row is picked up by the alert query")
        dialog = FollowUpAlertsDialog(app, jobs)
        pump_events()
        eq(dialog._list.count(), len(jobs), "one list entry per alert")
        check("follow up" in dialog._item_text(jobs[0]).lower(),
              "entry text mentions the follow-up")
        eq(dialog._open_btn.text(), "Open in Browser",
           "the dialog offers Open in Browser")
        dialog.close()


def test_sidebar_keywords_filter_the_table() -> None:
    """Clicking a keyword in the sidebar filters the table by it."""
    from jobscanner.ui_qt.sidebar import _ClickableKeyword

    with gui_app() as (app, _path, _kw):
        app.select_section(db.SECTION_ALL)
        pump_events()
        labels = app.sidebar._keywords._list_holder.findChildren(
            _ClickableKeyword)
        check(labels, "the sidebar lists the loaded keywords")
        first = labels[0]
        first.clicked.emit()
        pump_events()
        eq(app._search_edit.text(), first.text(),
           "clicking a sidebar keyword fills the search box")


def _proxy_index_for(app, job_id: str):
    """The proxy index of ``job_id``'s row, or None if not visible."""
    proxy = app._table.proxy()
    for g in range(proxy.rowCount()):
        parent = proxy.index(g, 0)
        for r in range(proxy.rowCount(parent)):
            idx = proxy.index(r, 0, parent)
            if proxy.data(idx, JobRoles.JobIdRole) == job_id:
                return idx
    return None


def test_multi_select_acts_on_every_selected_row() -> None:
    """Several rows can be selected and triaged in one go."""
    from PySide6.QtCore import QItemSelectionModel

    with gui_app() as (app, path, _kw):
        app.select_section(db.SECTION_NEW)
        pump_events()
        app._table.select_id("T0")
        idx2 = _proxy_index_for(app, "T2")
        check(idx2 is not None, "T2 is visible")
        app._table.selectionModel().select(idx2, QItemSelectionModel.Select)
        pump_events()
        eq(set(app._table.selected_job_ids()), {"T0", "T2"},
           "both rows are selected")

        app._run_op_on_selection(ja.OP_MARK_REVIEWED)
        pump_events()
        check(bool(db.get_job("T0", path)["reviewed"]), "first row reviewed")
        check(bool(db.get_job("T2", path)["reviewed"]), "second row reviewed")
        check(not db.get_job("T1", path)["reviewed"],
              "unselected rows are untouched")
        message = app.status_bar.currentMessage()
        check("Marked reviewed 2 job(s)" in message,
              f"summary toast counts the rows ({message!r})")


def test_multi_select_menu_lists_ops_with_counts() -> None:
    """The multi-select context menu shows each op with a supported count."""
    from PySide6.QtCore import QItemSelectionModel
    from PySide6.QtWidgets import QMenu

    with gui_app() as (app, _path, _kw):
        app.select_section(db.SECTION_NEW)
        pump_events()
        app._table.select_id("T0")
        idx2 = _proxy_index_for(app, "T2")
        app._table.selectionModel().select(idx2, QItemSelectionModel.Select)
        pump_events()
        app._show_job_menu("T0", app.mapToGlobal(app.rect().center()))
        pump_events()
        menus = [m for m in app.findChildren(QMenu) if m.isVisible()]
        check(menus, "the context menu opened")
        labels = [a.text() for a in menus[-1].actions() if a.text()]
        check("2 jobs selected" in labels,
              f"the menu names the selection ({labels})")
        check("Mark Reviewed (2)" in labels,
              f"supported ops carry their counts ({labels})")
        check("Archive (0)" in labels,
              f"unsupported ops count zero ({labels})")
        menus[-1].close()


def test_job_actions_confirm_with_a_status_toast() -> None:
    """The row vanishes from its section after most actions; the status
    bar should say what happened and to which job."""
    with gui_app() as (app, _path, _kw):
        app.select_section(db.SECTION_ALL)
        pump_events()
        app._table.select_id("T0")
        pump_events()
        app._run_job_op(ja.OP_ADD_TO_APPLY)
        pump_events()
        message = app.status_bar.currentMessage()
        check(message and "Added to To Apply" in message
              and "Job 0" in message,
              f"toast confirms the action and the job ({message!r})")


def test_status_bar_shows_current_section_count() -> None:
    """Global totals alone ('80 jobs') don't say what's in this section."""
    with gui_app() as (app, _path, _kw):
        app.select_section(db.SECTION_NEW)
        pump_events()
        check(app._stats_label.text().startswith("New: 6"),
              f"status bar leads with the current section "
              f"({app._stats_label.text()!r})")
        app.select_section(db.SECTION_ARCHIVED)
        pump_events()
        check(app._stats_label.text().startswith("Archived: 0"),
              f"status bar follows the section switch "
              f"({app._stats_label.text()!r})")


def test_scan_ui_toggles_button_progress_and_bulk() -> None:
    """While scanning, the button disables, an indeterminate progress bar
    shows, and the sidebar bulk block locks -- and back again."""
    with gui_app() as (app, _path, _kw):
        app._set_scanning_ui(True)
        pump_events()
        check(not app.actions.run_scan.isEnabled(),
              "Run Scan disables while scanning")
        eq(app.actions.run_scan.text(), "Scanning\u2026",
           "button text changes while scanning")
        check(app._scan_progress.isVisible(),
              "an indeterminate progress bar shows while scanning")
        check(not app.sidebar._bulk.isEnabled(),
              "the sidebar bulk block locks while scanning")

        app._set_scanning_ui(False)
        pump_events()
        check(app.actions.run_scan.isEnabled(),
              "Run Scan re-enables when the scan ends")
        eq(app.actions.run_scan.text(), "&Run Scan",
           "button text restores when the scan ends")
        check(not app._scan_progress.isVisible(),
              "the progress bar hides when the scan ends")
        check(app.sidebar._bulk.isEnabled(),
              "the bulk block unlocks when the scan ends")


if __name__ == "__main__":
    ok, reason = gui_available()
    _, failed, _ = run_module(globals(), "GUI workflow",
                              skip_reason="" if ok else reason)
    sys.exit(1 if failed else 0)
