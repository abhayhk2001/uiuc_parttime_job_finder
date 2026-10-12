"""Detail-pane rendering and keyboard/mouse interaction.

    python tests/test_gui_interactions.py
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMenu

from support import check, eq, gui_app, gui_available, pump_events, run_module  # noqa: E402

from jobscanner import storage as db  # noqa: E402
from jobscanner.ui_qt import job_actions as ja  # noqa: E402

ACCEL = "Cmd" if sys.platform == "darwin" else "Ctrl"


def test_chip_widgets_are_reused_across_selections() -> None:
    """Regression: the chip frame used to destroy and rebuild every chip on
    each refresh; with Qt's smaller rebuild cost it's less visible but the
    behaviour is preserved -- same row stays selected and chips don't churn
    when the keyword string hasn't changed."""
    with gui_app() as (app, _path, _kw):
        app.select_section(db.SECTION_ALL)
        pump_events()
        app._table.select_id("T0")
        pump_events()
        before_ids = [id(w) for w in app.detail.chips_flow.findChildren(QLabel)]

        # Same keywords (T0 is to_apply, no flip yet)
        app._run_job_op(ja.OP_ADD_TO_APPLY)
        pump_events()
        # After refresh the selection persists, so the chips should be
        # identical objects.
        after_ids = [id(w) for w in app.detail.chips_flow.findChildren(QLabel)]
        eq(before_ids, after_ids,
           "chips are reused across same-keyword refreshes")

        # Different keywords -- the chips_frame rebuilds.
        app._table.select_id("T1")  # T1 has matched_keywords="python"
        pump_events()
        check(0 < len(app.detail.chips_flow.findChildren(QLabel)),
              "chips rebuild for a row with different keywords")


def test_open_button_tracks_whether_there_is_a_url() -> None:
    with gui_app() as (app, _path, _kw):
        app._table.select_id("T0")
        pump_events()
        check(app.detail.open_btn.isEnabled(),
              "enabled for a job with an http URL")

        app.detail.clear()
        pump_events()
        check(not app.detail.open_btn.isEnabled(),
              "disabled with no job selected")


def test_empty_sections_explain_themselves() -> None:
    with gui_app() as (app, _path, _kw):
        app.select_section(db.SECTION_ALL)
        pump_events()
        app._search_edit.setText("zzzz-no-such-job")
        pump_events()
        eq(app._table.visible_job_count(), 0, "nothing matched")
        check(app._table._empty_label.isVisible(),
              "the empty state is shown")
        check("zzzz-no-such-job" in app._table._empty_label.text(),
              "the empty state names the query")

        app._search_edit.clear()
        pump_events()
        check(not app._table._empty_label.isVisible(),
              "the empty state hides once rows come back")

        app.select_section(db.SECTION_ARCHIVED)
        pump_events()
        check("Archived" in app._table._empty_label.text(),
              "an empty section names itself")


def test_selection_moves_between_jobs_across_sections() -> None:
    """Rows live under section headings now, so selection is driven by
    job id rather than a flat row number."""
    with gui_app() as (app, _path, _kw):
        app.select_section(db.SECTION_ALL)
        pump_events()
        ids = app._table.visible_job_ids()
        check(len(ids) >= 2, f"need rows to navigate (got {ids})")

        check(app._table.select_id(ids[0]), "first job selectable")
        pump_events()
        eq(app._table.selected_id(), ids[0], "first job selected")

        check(app._table.select_id(ids[1]), "second job selectable")
        pump_events()
        eq(app._table.selected_id(), ids[1], "selection moved")

        check(app._table.select_id(ids[-1]), "last job selectable")
        pump_events()
        eq(app._table.selected_id(), ids[-1], "selection reaches the last job")

        eq(app._table.select_id("no-such-job"), False,
           "an unknown id selects nothing")


def test_action_shortcuts_are_bound() -> None:
    """Each menu action has its accelerator set; the dock toggle has its
    own toggleViewAction."""
    with gui_app() as (app, _path, _kw):
        a = app.actions
        for key, action in (
            ("quit", a.quit),
            ("find", a.find),
            ("toggle_sidebar", a.toggle_sidebar),
            ("toggle_log", a.toggle_log),
            ("open_in_browser", a.open_in_browser),
            ("run_scan", a.run_scan),
            ("refresh", a.refresh),
        ):
            shortcut = action.shortcut().toString()
            check(shortcut, f"{key} has a shortcut ({shortcut!r})")


def test_sidebar_toggle_action_hides_and_shows() -> None:
    """The dock widget's built-in toggleViewAction hides/shows the dock."""
    with gui_app() as (app, _path, _kw):
        toggle = app.sidebar.toggleViewAction()
        check(app.sidebar.isVisible(), "the sidebar starts visible")
        toggle.trigger()
        pump_events()
        check(not app.sidebar.isVisible(),
              "the toggle action hides the sidebar")
        toggle.trigger()
        pump_events()
        check(app.sidebar.isVisible(),
              "the toggle action shows it again")


def test_context_menu_signal_carries_the_row_and_position() -> None:
    """Right-clicking a row emits contextMenuRequested with the job_id
    and a screen coordinate; the app's slot builds a real native menu."""
    from jobscanner.ui_qt.models import JobRoles
    from PySide6.QtCore import QPoint

    with gui_app() as (app, _path, _kw):
        app.select_section(db.SECTION_ALL)
        pump_events()

        # T2 sits under its section heading, so walk the one seeded group.
        proxy = app._table.proxy()
        parent = proxy.index(0, 0)
        target = None
        for r in range(proxy.rowCount(parent)):
            idx = proxy.index(r, 0, parent)
            if proxy.data(idx, JobRoles.JobIdRole) == "T2":
                target = idx
                break
        check(target is not None, "T2 is in the visible rows")

        # Ask the view where that row actually is, rather than computing it
        # from a row height -- a tree indents and offsets its children.
        rect = app._table.visualRect(target)
        check(rect.isValid() and rect.height() > 0,
              "the target row has a visible rect")
        click_y = rect.center().y()

        captured: list = []
        app._table.contextMenuRequested.connect(
            lambda job_id, pos: captured.append((job_id, pos)))
        app._table.customContextMenuRequested.emit(
            QPoint(rect.center().x(), click_y))
        pump_events()

        check(captured, "the contextMenuRequested signal fired")
        eq(captured[0][0], "T2",
           "the signal carries the right-clicked row's job_id")


def test_detail_pane_omits_sections_with_no_text() -> None:
    """Only the Virtual Job Board splits its text into Requirements and
    Skills. Every Research Park, Clearinghouse and Library job would
    otherwise carry two "(empty)" headings."""
    from jobscanner.ui_qt.detail_pane import _build_body_html
    from jobscanner.ui_qt import palette

    p = palette.DARK
    listing_only = _build_body_html(
        {"job_description": "Full description text",
         "requirements": "", "skills": ""}, p)
    check("Description" in listing_only, "Description is rendered")
    check("Requirements" not in listing_only,
          "an empty Requirements section is omitted entirely")
    check("Skills" not in listing_only, "so is an empty Skills section")
    check("(empty)" not in listing_only, "and no placeholder is shown")

    full = _build_body_html(
        {"job_description": "d", "requirements": "r", "skills": "s"}, p)
    for heading in ("Description", "Requirements", "Skills"):
        check(heading in full, f"{heading} still renders when populated")

    bare = _build_body_html(
        {"job_description": "", "requirements": "", "skills": ""}, p)
    check("Description" in bare and "(empty)" in bare,
          "a job with no text at all still explains the empty pane")


def test_row_activation_opens_the_url() -> None:
    """Double-clicking (or pressing Return on) a row calls
    _open_selected_in_browser with the selected job."""
    with gui_app() as (app, _path, _kw):
        opened: list = []
        app._open_selected_in_browser = lambda: opened.append(
            app._table.selected_id())

        app.select_section(db.SECTION_ALL)
        pump_events()
        app._table.select_id("T1")
        pump_events()
        app.actions.open_in_browser.trigger()
        pump_events()
        eq(opened, ["T1"], "the action opens the selected job")


def test_copy_job_id_action_uses_clipboard() -> None:
    """The Copy Job ID action puts the selected id on the clipboard."""
    from PySide6.QtGui import QGuiApplication

    with gui_app() as (app, _path, _kw):
        app.select_section(db.SECTION_ALL)
        pump_events()
        app._table.select_id("T0")
        pump_events()
        app.actions.copy_job_id.trigger()
        pump_events()
        eq(QGuiApplication.clipboard().text(), "T0",
           "Copy Job ID copies the selected id to the clipboard")


def test_esc_clears_the_search_box() -> None:
    """README: 'Esc -- Clear the search'. For a while it did nothing."""
    from PySide6.QtGui import QShortcut

    with gui_app() as (app, _path, _kw):
        app._search_edit.setText("python")
        pump_events()
        eq(app._search_edit.text(), "python", "search text set")

        esc = next(
            (s for s in app.findChildren(QShortcut)
             if s.key().toString() == "Esc"),
            None)
        check(esc is not None, "an Esc shortcut is registered on the window")
        esc.activated.emit()
        pump_events()
        eq(app._search_edit.text(), "", "Esc clears the search box")


def test_saved_state_cannot_resurrect_the_log_dock() -> None:
    """Regression: a session that closed with the log dock open (a scan
    ran) saved it that way, and restoreState() brought it back empty on
    the next launch, eating a quarter of the window."""
    from jobscanner.ui_qt.settings import app_settings

    with gui_app() as (app, _path, _kw):
        app.log_dock.show()
        pump_events()
        saved = app.saveState()
    check(saved, "captured a saved window state")

    settings = app_settings()
    previous = settings.value("window/state")
    settings.setValue("window/state", saved)
    try:
        with gui_app() as (app2, _path2, _kw2):
            check(not app2.log_dock.isVisible(),
                  "the log dock stays hidden even though the saved state "
                  "had it open")
    finally:
        if previous is None:
            settings.remove("window/state")
        else:
            settings.setValue("window/state", previous)


def test_detail_meta_shows_source_and_posted_age() -> None:
    """The board and the posting's age matter when triaging; both are in
    the DB but used to be invisible in the GUI."""
    from jobscanner.sources import SOURCE_LABELS

    with gui_app() as (app, _path, _kw):
        app.select_section(db.SECTION_ALL)
        pump_events()
        app._table.select_id("T0")
        pump_events()
        meta = app.detail.meta_label.text()
        check(f"Source: {SOURCE_LABELS['vjb']}" in meta,
              f"meta names the source board ({meta!r})")
        check("Posted:" in meta and "today" in meta,
              f"meta shows the posting date with its relative age ({meta!r})")


def test_overdue_follow_up_button_warns() -> None:
    """An overdue follow-up date should not need mental date arithmetic."""
    with gui_app() as (app, path, _kw):
        db.mark_applied("T2", path)
        db.set_follow_up("T2", "2020-01-01T00:00:00+00:00", path)
        app.select_section(db.SECTION_FOLLOW_UP)
        pump_events()
        app._table.select_id("T2")
        pump_events()
        check(app.detail.follow_up_btn.isVisible(),
              "the follow-up button shows for an applied row")
        check("overdue" in app.detail.follow_up_btn.text().lower(),
              f"the button says the date is overdue "
              f"({app.detail.follow_up_btn.text()!r})")
        from jobscanner.ui_qt import theme
        check(theme.current_palette()["warning"] in
              app.detail.follow_up_btn.styleSheet(),
              "the overdue button carries the warning color")


if __name__ == "__main__":
    ok, reason = gui_available()
    _, failed, _ = run_module(globals(), "GUI interactions",
                              skip_reason="" if ok else reason)
    sys.exit(1 if failed else 0)
