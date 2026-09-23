"""Pixel-geometry checks for the main window.

The GUI's layout bugs were all "this widget is in the wrong rectangle"
bugs, which no amount of state inspection catches — so these assert real
on-screen positions and sizes.

    python tests/test_gui_layout.py
"""

from __future__ import annotations

import sys

from support import (  # noqa: E402
    _teardown, check, eq, gui_app, gui_available, run_module, widget_box,
)

from jobscanner import storage as db  # noqa: E402


def test_panes_run_left_to_right_without_overlapping() -> None:
    with gui_app() as (app, _path, _kw):
        sidebar = widget_box(app.sections_panel)
        table = widget_box(app.jobs_table)
        detail = widget_box(app.detail)

        check(sidebar[0] < table[0] < detail[0],
              "sidebar | table | detail run left to right")
        check(sidebar[0] + sidebar[2] <= table[0],
              "the sidebar does not overlap the table")
        check(table[0] + table[2] <= detail[0],
              "the table does not overlap the detail pane")


def test_toolbar_and_footer_span_the_full_window() -> None:
    """Regression: both used columnspan=3 on a 4-column grid, so they
    stopped short of the detail pane."""
    with gui_app() as (app, _path, _kw):
        detail_right = widget_box(app.detail)[0] + widget_box(app.detail)[2]
        for name, widget in (("toolbar", app.toolbar), ("footer", app.footer)):
            box = widget_box(widget)
            check(box[0] + box[2] >= detail_right - 2,
                  f"the {name} reaches the detail pane's right edge")

        toolbar = widget_box(app.toolbar)
        sidebar = widget_box(app.sections_panel)
        footer = widget_box(app.footer)
        check(toolbar[1] + toolbar[3] <= sidebar[1], "toolbar sits above the panes")
        check(sidebar[1] + sidebar[3] <= footer[1], "footer sits below the panes")


def test_detail_pane_opens_usably_wide() -> None:
    """Regression: table and detail both had weight=2, but the Treeview's
    natural width exceeds its fair share, so the detail pane opened at
    ~180px — narrower than the wraplength its own labels used."""
    with gui_app() as (app, _path, _kw):
        detail = widget_box(app.detail)
        table = widget_box(app.jobs_table)
        check(detail[2] >= 300, f"detail pane opens usably wide (w={detail[2]})")
        check(table[2] >= 400, f"table stays usably wide (w={table[2]})")


def test_log_console_opens_inside_the_footer() -> None:
    """Regression: it gridded into the root row *below* the footer that
    holds its own toggle button."""
    with gui_app() as (app, _path, _kw):
        app._toggle_log()
        app.update()
        console = widget_box(app.log_console)
        toggle = widget_box(app.log_toggle)
        footer = widget_box(app.footer)

        check(console[1] >= toggle[1] + toggle[3] - 2,
              "the console opens below its own toggle")
        check(console[1] >= footer[1]
              and console[1] + console[3] <= footer[1] + footer[3] + 2,
              "the console sits inside the footer's rectangle")
        check(console[2] > 400, f"the console is full width (w={console[2]})")


def test_follow_up_presets_occupy_distinct_rectangles() -> None:
    from jobscanner.ui.dialogs.follow_up import FollowUpDateEditor

    with gui_app() as (app, path, _kw):
        dialog = FollowUpDateEditor(app, "T0", "", on_save=lambda: None,
                                    db_path=path)
        dialog.geometry("460x300")
        dialog.update()
        boxes = [widget_box(b) for b in dialog.preset_buttons]
        eq(len({(b[0], b[1]) for b in boxes}), len(boxes),
           "every preset has its own screen position")
        check(all(b[2] > 40 and b[3] > 10 for b in boxes),
              "every preset has a real size")
        eq(len({b[1] for b in boxes}), 2, "presets form 2 rows")
        dialog.destroy()


def test_sidebar_collapses_and_expands() -> None:
    with gui_app() as (app, _path, _kw):
        table_before = widget_box(app.jobs_table)[2]
        expanded = app.sections_panel.winfo_width()

        app.sections_panel.toggle_collapsed()
        app.update()
        collapsed = app.sections_panel.winfo_width()
        check(collapsed < expanded / 2,
              f"collapsing shrinks the sidebar ({expanded} -> {collapsed})")
        check(app.sections_panel._rail.winfo_ismapped(),
              "the collapsed sidebar shows the rail")
        check(not app.sections_panel._content.winfo_ismapped(),
              "the collapsed sidebar hides the full content")

        rail_btn = app.sections_panel._rail_buttons[db.SECTION_OLD]
        check("\n" in rail_btn.cget("text"),
              f"the rail keeps counts visible ({rail_btn.cget('text')!r})")
        check(widget_box(app.jobs_table)[2] > table_before,
              "the table gains the width the sidebar gave up")

        app.sections_panel.toggle_collapsed()
        app.update()
        check(abs(app.sections_panel.winfo_width() - expanded) <= 2,
              "expanding restores the previous width")
        check(app.sections_panel._content.winfo_ismapped(),
              "the expanded sidebar shows its content again")


def test_detail_sash_resizes_the_pane() -> None:
    with gui_app() as (app, _path, _kw):
        before = widget_box(app.detail)[2]
        app._drag_detail(-120)
        app.update()
        after = widget_box(app.detail)[2]
        check(after > before,
              f"dragging the right sash left widens detail ({before} -> {after})")


def test_layout_is_restored_on_relaunch() -> None:
    from jobscanner.ui import app as gui

    with gui_app() as (app, path, kw_path):
        app._drag_detail(-120)
        app.update()
        app.sections_panel.set_expanded_width(305)
        app.sections_panel.set_collapsed(True)
        app._save_layout()
        # Compare widget widths, not widget-vs-minsize: the stored column
        # minsize includes the pane's padding, so the two differ by a constant.
        detail_before = widget_box(app.detail)[2]

        relaunched = gui.JobScannerApp(path, kw_path)
        relaunched.geometry("1380x860")
        relaunched.update()
        try:
            check(relaunched.sections_panel.collapsed,
                  "relaunch reopens collapsed")
            eq(relaunched.sections_panel.expanded_width, 305,
               "relaunch remembers the expanded width")
            check(abs(widget_box(relaunched.detail)[2] - detail_before) <= 2,
                  "relaunch restores the detail width")
        finally:
            _teardown(relaunched)


if __name__ == "__main__":
    ok, reason = gui_available()
    _, failed, _ = run_module(globals(), "GUI layout",
                              skip_reason="" if ok else reason)
    sys.exit(1 if failed else 0)
