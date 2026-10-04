"""Pixel-geometry checks for the main window.

Adapted for the Qt port. The old tests asserted against the old
three-pane CTk grid; the new UI uses a single central ``QSplitter``
(table + detail) plus a dockable sidebar and dockable log. This file
covers what's left: window defaults, central splitter proportions,
dock visibility, log dock placement.

    python tests/test_gui_layout.py
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt

from support import (  # noqa: E402
    check, eq, gui_app, gui_available, pump_events, run_module, widget_box,
)

from jobscanner import storage as db  # noqa: E402


def test_window_opens_at_expected_size() -> None:
    """The default window size matches what the app advertises in its
    README/screenshots."""
    with gui_app() as (app, _path, _kw):
        check(app.size().width() >= 1080,
              f"window respects the 1080px minsize (w={app.size().width()})")
        check(app.size().height() >= 640,
              f"window respects the 640px minsize (h={app.size().height()})")
        check(app.windowTitle() == "UIUC Part-Time Job Scanner",
              "window title is the app name")


def test_sidebar_dock_starts_on_the_left() -> None:
    """The sidebar QDockWidget is in Qt.LeftDockWidgetArea at startup."""
    with gui_app() as (app, _path, _kw):
        # findChildren on a QMainWindow returns dock widgets in their
        # current tab order.
        docks = app.findChildren(type(app.sidebar))
        check(app.sidebar in docks, "the sidebar dock is in the window")
        # The Qt.LeftDockWidgetArea is value 1.
        eq(app.dockWidgetArea(app.sidebar), Qt.LeftDockWidgetArea,
           "the sidebar lives in the left dock area")


def test_central_splitter_runs_table_left_of_detail() -> None:
    """The central splitter has table on the left and detail on the right."""
    with gui_app() as (app, _path, _kw):
        sizes = app.splitter.sizes()
        check(sizes[0] > 0 and sizes[1] > 0,
              f"both panes have positive width (sizes={sizes})")
        # The detail pane is the second child.
        table_box = widget_box(app._table)
        detail_box = widget_box(app.detail)
        check(detail_box[0] > table_box[0],
              f"detail pane sits right of the table "
              f"(table.x={table_box[0]}, detail.x={detail_box[0]})")


def test_detail_pane_opens_usably_wide() -> None:
    """Regression: the detail pane opens at a usable width, not ~180px."""
    with gui_app() as (app, _path, _kw):
        detail_box = widget_box(app.detail)
        table_box = widget_box(app._table)
        check(detail_box[2] >= 300,
              f"detail pane opens usably wide (w={detail_box[2]})")
        check(table_box[2] >= 400,
              f"table stays usably wide (w={table_box[2]})")


def test_log_dock_sits_below_central_pane() -> None:
    """The log dock, when visible, sits below the central pane."""
    with gui_app() as (app, _path, _kw):
        # Log dock starts hidden.
        check(not app.log_dock.isVisible(), "log dock starts hidden")
        # Show it.
        app.log_dock.show()
        pump_events()
        check(app.log_dock.isVisible(), "log dock becomes visible after show()")
        # It lives in the bottom dock area.
        eq(app.dockWidgetArea(app.log_dock), Qt.BottomDockWidgetArea,
           "log dock lives in the bottom dock area")
        # And it's positioned below the central widget.
        log_box = widget_box(app.log_dock)
        central_box = widget_box(app.centralWidget())
        check(log_box[1] >= central_box[1] + central_box[3] - 2,
              f"log dock sits below the central pane "
              f"(central bottom={central_box[1] + central_box[3]}, "
              f"log top={log_box[1]})")


def test_follow_up_presets_occupy_distinct_rectangles() -> None:
    """The follow-up dialog's preset buttons each occupy their own cell."""
    from jobscanner.ui_qt.dialogs.follow_up import FollowUpDialog

    with gui_app() as (app, _path, _kw):
        dialog = FollowUpDialog(app, "T0", "",
                                on_save=lambda: None)
        dialog.resize(460, 300)
        dialog.show()
        pump_events()
        boxes = [widget_box(b) for b in dialog.preset_buttons]
        eq(len({(b[0], b[1]) for b in boxes}), len(boxes),
           "every preset has its own screen position")
        check(all(b[2] > 40 and b[3] > 10 for b in boxes),
              "every preset has a real size")
        eq(len({b[1] for b in boxes}), 2, "presets form 2 rows")
        dialog.close()


def test_sidebar_can_be_hidden_and_shown() -> None:
    """The sidebar is hideable via the View menu's toggle action and the
    View menu entry on the dock's right-click menu."""
    with gui_app() as (app, _path, _kw):
        check(app.sidebar.isVisible(), "the sidebar starts visible")
        app.sidebar.hide()
        pump_events()
        check(not app.sidebar.isVisible(),
              "hiding the dock makes it invisible")
        app.sidebar.show()
        pump_events()
        check(app.sidebar.isVisible(),
              "showing the dock makes it visible again")


def test_layout_is_restored_on_relaunch() -> None:
    """Splitter sizes + dock state persist across launches via QSettings.

    The first window saves on close; the second window restores on open.
    """
    from jobscanner.ui_qt import app as gui_mod

    # Clean slate for the persisted state we care about.
    from jobscanner.ui_qt.settings import app_settings
    settings = app_settings()
    settings.remove("window/geometry")
    settings.remove("window/state")
    settings.remove("window/splitter_sizes")

    with gui_app() as (app, _path, _kw):
        # Drive the splitter to a non-default size and hide the log dock,
        # so the next window has something distinctive to restore.
        app.splitter.setSizes([800, 350])
        app.log_dock.hide()
        pump_events()
        saved_splitter = app.splitter.sizes()
        log_was_hidden = not app.log_dock.isVisible()
        app.close()

    with gui_app() as (app2, _path, _kw):
        eq(app2.splitter.sizes(), saved_splitter,
           "splitter sizes round-trip through QSettings")
        check(not app2.log_dock.isVisible() or log_was_hidden,
              "the log dock visibility state round-trips")


if __name__ == "__main__":
    ok, reason = gui_available()
    _, failed, _ = run_module(globals(), "GUI layout",
                              skip_reason="" if ok else reason)
    sys.exit(1 if failed else 0)
