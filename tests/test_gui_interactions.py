"""Detail-pane rendering and keyboard/mouse interaction.

    python tests/test_gui_interactions.py
"""

from __future__ import annotations

import sys

from support import check, eq, gui_app, gui_available, run_module  # noqa: E402

from jobscanner import storage as db  # noqa: E402

ACCEL = "Command" if sys.platform == "darwin" else "Control"


def test_body_labels_are_reused_across_selections() -> None:
    """Regression: the pane destroyed and rebuilt every body label on each
    refresh, so it flickered and lost the reader's scroll position."""
    with gui_app() as (app, _path, _kw):
        app.select_section(db.SECTION_ALL)
        app.update()
        app.jobs_table.select("T0")
        app.update()
        before = [id(w) for w in app.detail._body_labels.values()]

        app.jobs_table.select("T1")
        app.update()
        eq([id(w) for w in app.detail._body_labels.values()], before,
           "body labels are reused, not recreated")
        eq(len(app.detail.body.winfo_children()), 6,
           "the body holds exactly 6 widgets, not a growing pile")
        check(app.detail._body_labels["job_description"].cget("text"),
              "body text was filled in")


def test_chips_only_rebuild_when_the_keywords_change() -> None:
    with gui_app() as (app, _path, _kw):
        # Use All, so flipping a flag doesn't move the row out of view.
        app.select_section(db.SECTION_ALL)
        app.update()
        app.jobs_table.select("T0")
        app.update()
        eq(len(app.detail.chips_frame.winfo_children()), 1,
           "a matching job shows one chip")
        before = [id(w) for w in app.detail.chips_frame.winfo_children()]

        app._run_job_op(app.detail._secondary_op)   # same keywords
        app.update()
        eq(app.detail.job_id, "T0", "the row stayed selected")
        eq([id(w) for w in app.detail.chips_frame.winfo_children()], before,
           "chips survive a flag toggle without churning")

        app.jobs_table.select("T1")                 # different keywords
        app.update()
        check([id(w) for w in app.detail.chips_frame.winfo_children()] != before,
              "chips do rebuild when the keywords differ")


def test_text_reflows_with_the_pane_width() -> None:
    """Regression: wraplength was hardcoded at 440/380, so text was clipped
    rather than reflowed when the divider moved."""
    with gui_app() as (app, _path, _kw):
        app.jobs_table.select("T0")
        app.update()
        before = app.detail._wraplength

        app._drag_detail(-200)
        app.update()
        check(app.detail._wraplength > before,
              f"wraplength tracks the pane ({before} -> {app.detail._wraplength})")
        eq(app.detail._body_labels["job_description"].cget("wraplength"),
           app.detail._wraplength, "body labels picked up the new wraplength")


def test_open_button_tracks_whether_there_is_a_url() -> None:
    with gui_app() as (app, _path, _kw):
        app.jobs_table.select("T0")
        app.update()
        eq(str(app.detail.open_btn.cget("state")), "normal",
           "enabled for a job with an http URL")

        app.detail.clear()
        app.update()
        eq(str(app.detail.open_btn.cget("state")), "disabled",
           "disabled with no job selected")


def test_empty_sections_explain_themselves() -> None:
    with gui_app() as (app, _path, _kw):
        app.select_section(db.SECTION_ALL)
        app.update()
        app.toolbar.search_var.set("zzzz-no-such-job")
        app.update()
        eq(len(app.jobs_table.tree.get_children()), 0, "nothing matched")
        check(app.jobs_table._empty_label.winfo_ismapped(),
              "the empty state is shown")
        check("zzzz-no-such-job" in app.jobs_table._empty_label.cget("text"),
              "the empty state names the query")

        app.toolbar.clear_search()
        app.update()
        check(not app.jobs_table._empty_label.winfo_ismapped(),
              "the empty state hides once rows come back")

        app.select_section(db.SECTION_ARCHIVED)
        app.update()
        check("Archived" in app.jobs_table._empty_label.cget("text"),
              "an empty section names itself")


def test_keyboard_navigation_moves_and_clamps() -> None:
    with gui_app() as (app, _path, _kw):
        app.select_section(db.SECTION_ALL)
        app.update()
        rows = app.jobs_table.tree.get_children()
        app.jobs_table.select(rows[0])
        app.update()

        app.jobs_table.move_selection(1)
        app.update()
        eq(app.jobs_table.selected_id(), rows[1], "down moves one row")

        app.jobs_table.move_selection(-99)
        app.update()
        eq(app.jobs_table.selected_id(), rows[0], "navigation clamps at the top")

        app.jobs_table.move_selection(99)
        app.update()
        eq(app.jobs_table.selected_id(), rows[-1],
           "navigation clamps at the bottom")


def test_shortcuts_are_bound() -> None:
    with gui_app() as (app, _path, _kw):
        for sequence in (f"<{ACCEL}-r>", f"<{ACCEL}-f>", f"<{ACCEL}-l>",
                         f"<{ACCEL}-b>", f"<{ACCEL}-Return>", "<Escape>",
                         f"<{ACCEL}-Key-1>"):
            check(bool(app.bind_all(sequence)), f"{sequence} is bound")


def test_collapse_shortcut_fires() -> None:
    with gui_app() as (app, _path, _kw):
        was = app.sections_panel.collapsed
        app.focus_force()
        app.update()
        app.event_generate(f"<{ACCEL}-b>", when="now")
        app.update()
        check(app.sections_panel.collapsed != was,
              f"the collapse shortcut toggles the sidebar (was {was})")


def test_context_menu_offers_the_rows_actions() -> None:
    with gui_app() as (app, path, _kw):
        app.select_section(db.SECTION_ALL)
        app.update()
        app.jobs_table.select("T2")
        app.update()

        posted: list = []
        app._row_menu.tk_popup = lambda x, y: posted.append((x, y))
        app._show_row_menu("T2", 100, 100)

        menu = app._row_menu
        labels = [menu.entrycget(i, "label")
                  for i in range(menu.index("end") + 1)
                  if menu.type(i) != "separator"]
        check("Open in browser" in labels, "offers Open in browser")
        check("Copy Job ID" in labels, "offers Copy Job ID")
        check(any("Mark Reviewed" in label for label in labels),
              f"offers the row's primary action (labels={labels})")
        check(posted, "the menu was actually posted")

        app._run_job_op_on("T2", "mark_reviewed")
        app.update()
        check(bool(db.get_job("T2", path)["reviewed"]),
              "acting from the menu mutates that row")


def test_row_activation_is_wired_to_opening_the_url() -> None:
    with gui_app() as (app, _path, _kw):
        opened: list = []
        app._open_job_url = lambda job_id: opened.append(job_id)
        app.jobs_table._on_activate = app._open_job_url

        app.select_section(db.SECTION_ALL)
        app.update()
        app.jobs_table.select("T1")
        app.update()
        app.jobs_table._handle_activate()
        eq(opened, ["T1"], "activating a row opens that job")


if __name__ == "__main__":
    ok, reason = gui_available()
    _, failed, _ = run_module(globals(), "GUI interactions",
                              skip_reason="" if ok else reason)
    sys.exit(1 if failed else 0)
