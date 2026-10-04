"""``QAction`` factory: every menu / toolbar / shortcut action in one place.

The legacy CTk UI registered each action inline three times -- once for
the menu, once for the toolbar, once as a keyboard binding -- and they
drifted apart. This module defines each action once on a single
``Actions`` container; the menu, toolbar, and ``View`` shortcuts read
from the same object.

The actual handlers are attached later (in :mod:`jobscanner.ui_qt.app`)
when the rest of the app's signals are wired up. For step 4 the actions
are constructed but most slots are still placeholders.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMainWindow

from jobscanner.ui_qt.shortcuts import accel, sequence


@dataclass
class Actions:
    """Bundle of every action the app exposes.

    All actions are children of ``owner`` so the lifetime is bound to the
    main window. ``None`` slots are filled in by the app after
    construction.
    """

    # File
    quit: QAction

    # Edit
    find: QAction

    # View
    toggle_sidebar: QAction
    toggle_log: QAction
    appearance: QAction

    # Job
    open_in_browser: QAction
    copy_job_id: QAction
    copy_url: QAction

    # Scan
    run_scan: QAction
    refresh: QAction

    # Help
    about: QAction

    # Numeric shortcuts (Cmd-1..Cmd-9) are added separately so the
    # section list doesn't need to exist at action-construction time.


def build_actions(owner: QMainWindow) -> Actions:
    """Create every action and parent it to ``owner``. Menu bar, toolbar,
    and shortcut wiring all read from the returned object."""

    # File ----------------------------------------------------------------
    quit_act = QAction("&Quit", owner)
    quit_act.setShortcut(QKeySequence(sequence("Q")))
    quit_act.setMenuRole(QAction.QuitRole)
    quit_act.setStatusTip("Quit the application")

    # Edit ----------------------------------------------------------------
    find_act = QAction("&Find", owner)
    find_act.setShortcut(QKeySequence(sequence("F")))
    find_act.setStatusTip("Focus the search box")

    # View ----------------------------------------------------------------
    toggle_sidebar = QAction("Toggle &Sidebar", owner)
    toggle_sidebar.setShortcut(QKeySequence(sequence("B")))
    toggle_sidebar.setCheckable(False)

    toggle_log = QAction("Toggle &Log Dock", owner)
    toggle_log.setShortcut(QKeySequence(sequence("L")))

    appearance = QAction("&Appearance\u2026", owner)
    appearance.setStatusTip("Light / Dark / Follow system")

    # Job -----------------------------------------------------------------
    open_in_browser = QAction("&Open in Browser", owner)
    open_in_browser.setShortcut(QKeySequence(sequence("O")))

    copy_job_id = QAction("Copy &Job ID", owner)
    copy_job_id.setShortcut(QKeySequence(sequence("Shift+C")))

    copy_url = QAction("Copy &URL", owner)

    # Scan ----------------------------------------------------------------
    run_scan = QAction("&Run Scan", owner)
    # Cmd+Return, not a bare Return: Return alone fired a network scan
    # from anywhere in the window, e.g. after typing in the search box.
    run_scan.setShortcut(QKeySequence("Ctrl+Return"))
    run_scan.setStatusTip("Scan the UIUC Virtual Job Board")

    refresh = QAction("&Refresh", owner)
    refresh.setShortcut(QKeySequence(sequence("R")))
    refresh.setStatusTip("Reload the current section from the database")

    # Help ----------------------------------------------------------------
    about = QAction("&About", owner)
    about.setMenuRole(QAction.AboutRole)

    return Actions(
        quit=quit_act,
        find=find_act,
        toggle_sidebar=toggle_sidebar,
        toggle_log=toggle_log,
        appearance=appearance,
        open_in_browser=open_in_browser,
        copy_job_id=copy_job_id,
        copy_url=copy_url,
        run_scan=run_scan,
        refresh=refresh,
        about=about,
    )


def build_menus(owner: QMainWindow, a: Actions) -> dict[str, object]:
    """Attach ``a`` to ``owner.menuBar()`` and return the menu handles.

    The dict lets the app grab a menu by name (used by the About-role
    override that Qt does automatically).
    """
    bar = owner.menuBar()
    bar.setNativeMenuBar(True)

    m_file = bar.addMenu("&File")
    m_file.addAction(a.quit)

    m_edit = bar.addMenu("&Edit")
    m_edit.addAction(a.find)

    m_view = bar.addMenu("&View")
    m_view.addAction(a.toggle_sidebar)
    m_view.addAction(a.toggle_log)
    m_view.addSeparator()
    m_view.addAction(a.appearance)

    m_job = bar.addMenu("&Job")
    m_job.addAction(a.open_in_browser)
    m_job.addSeparator()
    m_job.addAction(a.copy_job_id)
    m_job.addAction(a.copy_url)

    m_scan = bar.addMenu("&Scan")
    m_scan.addAction(a.run_scan)
    m_scan.addAction(a.refresh)

    m_help = bar.addMenu("&Help")
    m_help.addAction(a.about)

    return {
        "file": m_file, "edit": m_edit, "view": m_view,
        "job": m_job, "scan": m_scan, "help": m_help,
    }


def build_toolbar(owner: QMainWindow, a: Actions) -> object:
    """Attach ``a`` to ``owner.addToolBar`` and return the toolbar."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QToolBar

    tb = QToolBar("Main", owner)
    tb.setObjectName("main-toolbar")
    tb.setMovable(False)
    tb.setFloatable(False)
    owner.addToolBar(Qt.TopToolBarArea, tb)
    tb.addAction(a.run_scan)
    tb.addAction(a.refresh)
    tb.addSeparator()
    tb.addAction(a.find)
    return tb
