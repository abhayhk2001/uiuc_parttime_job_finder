"""The main application window.

Builds the QMainWindow with a real native menu bar, toolbar, status bar,
sidebar dock, and the jobs table. Step 4 wiring:

- Menu / toolbar / shortcuts come from :mod:`jobscanner.ui_qt.actions`
  (one source of truth -- no duplication).
- The sidebar is a real :class:`QDockWidget` (hide via View menu, float,
  re-dock).
- Section clicks populate the table via
  :func:`db.get_jobs_by_section`.
- Bulk actions and the keyword editor open dialogs that land in step 7.
- Theme switch is live: re-fetches row colors on the table model.

Steps still to come: detail pane (step 5), scan worker + log dock
(step 6), the rest of the dialogs (step 7), full QSettings layout
persistence (step 8).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QCoreApplication, QSettings, Qt, QThread
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from jobscanner import config
from jobscanner import matching
from jobscanner import storage as db
from jobscanner.ui_qt import actions as actions_mod
from jobscanner.ui_qt import job_actions as ja
from jobscanner.ui_qt import theme
from jobscanner.ui_qt.detail_pane import DetailPane
from jobscanner.ui_qt.dialogs.follow_up import FollowUpDialog
from jobscanner.ui_qt.dialogs.keywords import KeywordsDialog
from jobscanner.ui_qt.dialogs.preferences import PreferencesDialog
from jobscanner.ui_qt.jobs_table import JobsTableView
from jobscanner.ui_qt.log_dock import LogDock
from jobscanner.ui_qt.shortcuts import accel, sequence
from jobscanner.ui_qt.sidebar import SidebarDock, build_sections_list
from jobscanner.ui_qt.workers.scan_worker import ScanWorker


APP_ORG = "UIUC"
APP_NAME = "PartTimeJobScanner"
APP_TITLE = "UIUC Part-Time Job Scanner"

DEFAULT_GEOMETRY = (1380, 860)
MIN_SIZE = (1080, 640)

# Placeholder detail text shown until step 5 ships.
_DETAIL_PLACEHOLDER = "Detail pane\n(step 5 ships the real one)"


def _placeholder(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("placeholder")
    label.setAlignment(Qt.AlignCenter)
    label.setMinimumWidth(120)
    return label


class JobScannerApp(QMainWindow):
    """The application window. One instance per process."""

    def __init__(self, db_path: Path, keywords_path: Path) -> None:
        super().__init__()
        self.db_path = db_path
        self.keywords_path = keywords_path
        self._section = db.SECTION_NEW

        self.setWindowTitle(APP_TITLE)
        self.resize(*DEFAULT_GEOMETRY)
        self.setMinimumSize(*MIN_SIZE)

        # Actions, menus, toolbar come from a single factory.
        self.actions = actions_mod.build_actions(self)
        actions_mod.build_menus(self, self.actions)
        self.toolbar = actions_mod.build_toolbar(self, self.actions)

        # Sidebar dock on the left.
        self.sidebar = SidebarDock(self)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.sidebar)

        # Log dock on the bottom; hidden until the user toggles it.
        self.log_dock = LogDock(self)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.log_dock)
        self.log_dock.hide()

        # Scan state.
        self._scanning = False
        self._scan_thread: QThread | None = None
        self._scan_worker: ScanWorker | None = None

        # Central widget: search row on top of the jobs table, then the
        # table itself. Step 5 will replace the placeholder detail pane.
        central = QWidget(self)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        search_row = QWidget(central)
        search_layout = QHBoxLayout(search_row)
        search_layout.setContentsMargins(8, 8, 8, 8)
        search_layout.setSpacing(8)
        search_layout.addWidget(QLabel("Search:", search_row))
        self._search_edit = QLineEdit(search_row)
        self._search_edit.setPlaceholderText("Filter visible jobs")
        self._search_edit.setClearButtonEnabled(True)
        search_layout.addWidget(self._search_edit, 1)
        self._matches_only = QCheckBox("Matches only", search_row)
        search_layout.addWidget(self._matches_only)
        outer.addWidget(search_row)

        self.splitter = QSplitter(Qt.Horizontal, self)
        self.splitter.addWidget(central)
        self.detail = DetailPane(self)
        self.splitter.addWidget(self.detail)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([920, 400])
        self.splitter.setChildrenCollapsible(False)
        self.setCentralWidget(self.splitter)

        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready.")

        # Wire the actions.
        self._wire_actions()

        # Wire the search bar to the table.
        self._table = JobsTableView(central)
        self._table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        outer.addWidget(self._table, 1)
        # The search box and matches-only toggle also drive the empty-state
        # message -- wire through a single slot that updates both.
        self._search_edit.textChanged.connect(self._on_filter_changed)
        self._matches_only.toggled.connect(self._on_filter_changed)
        self._table.selectionJobIdChanged.connect(self._on_table_selection)

        # Sidebar signals.
        self.sidebar.sectionSelected.connect(self.select_section)
        self.sidebar.bulkActionInvoked.connect(self.bulk_mark_section)
        self.sidebar.editKeywordsRequested.connect(self._open_keyword_editor)

        # Detail pane signals.
        self.detail.actionInvoked.connect(self._run_job_op)
        self.detail.editFollowUpRequested.connect(self._open_follow_up_editor)

        # Re-fetch row colors when the OS flips light/dark.
        QGuiApplication.styleHints().colorSchemeChanged.connect(
            self._on_color_scheme_changed)

        # Restore window geometry, dock state, and splitter sizes.
        settings = QSettings()
        geometry = settings.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        state = settings.value("window/state")
        if state is not None:
            self.restoreState(state)
        splitter_sizes = settings.value("window/splitter_sizes")
        if splitter_sizes is not None:
            try:
                self.splitter.setSizes([int(s) for s in splitter_sizes])
            except (TypeError, ValueError):
                pass

        # Cmd-1 .. Cmd-9 jump between sections (the old UI's behavior).
        self._install_section_shortcuts()

        self.refresh()

    # -- actions wiring -------------------------------------------------

    def _wire_actions(self) -> None:
        a = self.actions
        a.quit.triggered.connect(self.close)
        a.find.triggered.connect(self._focus_search)
        a.toggle_sidebar.triggered.connect(self._toggle_sidebar)
        a.toggle_log.triggered.connect(self._toggle_log)
        a.appearance.triggered.connect(self._open_preferences)
        a.open_in_browser.triggered.connect(self._open_selected_in_browser)
        a.copy_job_id.triggered.connect(self._copy_selected_job_id)
        a.copy_url.triggered.connect(self._copy_selected_url)
        a.run_scan.triggered.connect(self._start_scan)
        a.refresh.triggered.connect(self.refresh)
        a.about.triggered.connect(self._show_about)

    # -- refresh ---------------------------------------------------------

    def refresh(self) -> None:
        try:
            rows = db.get_jobs_by_section(
                section=self._section,
                query=self._table.proxy().search_text(),
                matches_only=self._table.proxy().matches_only(),
                path=self.db_path,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Database error",
                                 f"Could not query DB:\n{exc}")
            return

        # `set_rows` calls beginResetModel/endResetModel, which clears the
        # selection. Preserve it so the detail pane keeps showing the
        # same row after the refresh (with its new state).
        prev_selected = self._table.selected_id()
        self._table.set_empty_message(self._empty_message())
        self._table.set_rows(rows)
        if prev_selected:
            self._table.select_id(prev_selected)
        self._refresh_status()
        self._on_table_selection(self._table.selected_id())

        # Refresh sidebar section counts.
        try:
            counts = db.get_section_counts(self.db_path)
        except Exception:  # noqa: BLE001
            counts = {}
        sections_with_counts = [(k, label, counts.get(k, 0))
                                for k, label, _ in build_sections_list()]
        self.sidebar.refresh_sections(sections_with_counts, counts, self._section)
        try:
            self.sidebar.set_keywords(matching.load_keywords(self.keywords_path))
        except Exception:  # noqa: BLE001
            self.sidebar.set_keywords([])

    def _refresh_status(self) -> None:
        try:
            stats = db.get_stats(self.db_path)
        except Exception:  # noqa: BLE001
            self.status_bar.showMessage("Ready.")
            return
        self.status_bar.showMessage(
            f"{stats['total']} jobs · {stats['matching']} matching · "
            f"{stats['reviewed']} reviewed"
        )

    def _empty_message(self) -> str:
        """Message to show in the table's overlay when no rows are visible."""
        if self._table.proxy().search_text():
            return f"No jobs match \u201c{self._table.proxy().search_text()}\u201d here."
        if self._table.proxy().matches_only():
            return "No keyword matches in this section."
        return f"Nothing in {db.SECTION_LABELS.get(self._section, self._section)}."

    # -- selection -------------------------------------------------------

    def select_section(self, section: str) -> None:
        if section not in db.VALID_SECTIONS:
            return
        self._section = section
        self.sidebar.set_current_section(section)
        self.refresh()

    # -- bulk actions ----------------------------------------------------

    def bulk_mark_section(self, action_id: str) -> None:
        from jobscanner.ui_qt.bulk_actions import BULK_ACTIONS_BY_ID

        action = BULK_ACTIONS_BY_ID.get(action_id)
        if action is None:
            return
        if action.confirm and QMessageBox.question(
            self, action.label, action.confirm,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        try:
            affected = action.run(self.db_path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Bulk update failed", str(exc))
            return
        self.refresh()
        self.status_bar.showMessage(action.message(affected), 5000)

    def _open_keyword_editor(self) -> None:
        def _on_save(new_keywords: list[str]) -> None:
            try:
                n = matching.rematch_all(new_keywords, self.db_path)
                self.status_bar.showMessage(
                    f"Re-matched {n} job(s) against the new keywords.", 5000)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "Re-match failed", str(exc))
            self.refresh()

        KeywordsDialog(self, self.keywords_path, on_save=_on_save)

    def _open_preferences(self) -> None:
        PreferencesDialog(self)

    # -- detail pane actions -------------------------------------------

    def _run_job_op(self, op) -> None:
        if not op:
            return
        job_id = self.detail.job_id
        if not job_id:
            return
        try:
            ja.apply_op(op, job_id, self.db_path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Update failed", str(exc))
            return
        self.refresh()

    def _open_follow_up_editor(self) -> None:
        job_id = self.detail.job_id
        if not job_id:
            return
        try:
            job = db.get_job(job_id, self.db_path) or {}
        except Exception:  # noqa: BLE001
            return
        if not job.get("applied_at") or job.get("archived"):
            return
        FollowUpDialog(
            self, job_id, (job.get("follow_up_at") or "")[:10],
            on_save=self.refresh, db_path=self.db_path,
        )

    # -- table selection handlers --------------------------------------

    def _on_table_selection(self, job_id) -> None:
        if job_id is None:
            self.detail.clear()
            self.status_bar.showMessage("Ready.", 0)
            return
        # The view already exposes the full row dict via its model role,
        # so no DB round-trip is needed to populate the pane.
        job = self._table.current_job_dict() if job_id == self._table.selected_id() else None
        if job:
            self.detail.show_job(job)
        else:
            job = db.get_job(job_id, self.db_path)
            if job:
                self.detail.show_job(job)
            else:
                self.detail.clear()
        self.status_bar.showMessage(f"Selected job #{job_id}", 0)

    def _on_filter_changed(self, *_args) -> None:
        """Search text or matches-only changed: reapply both filters and
        update the empty-state message to explain why nothing is visible."""
        self._table.set_search_text(self._search_edit.text())
        self._table.set_matches_only(self._matches_only.isChecked())
        self._table.set_empty_message(self._empty_message())

    def _open_selected_in_browser(self) -> None:
        job = self._table.current_job_dict()
        if not job:
            self.status_bar.showMessage("No job selected", 3000)
            return
        url = (job.get("detail_url") or "").strip()
        if not url.startswith(("http://", "https://")):
            self.status_bar.showMessage("No URL for this job", 3000)
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(url))

    def _copy_selected_job_id(self) -> None:
        job_id = self._table.selected_id()
        if not job_id:
            return
        QGuiApplication.clipboard().setText(job_id)
        self.status_bar.showMessage(f"Copied job ID {job_id}", 3000)

    def _copy_selected_url(self) -> None:
        job = self._table.current_job_dict()
        if not job:
            return
        url = (job.get("detail_url") or "").strip()
        if not url:
            return
        QGuiApplication.clipboard().setText(url)
        self.status_bar.showMessage("Copied URL", 3000)

    # -- misc handlers -------------------------------------------------

    def _focus_search(self) -> None:
        self._search_edit.setFocus()
        self._search_edit.selectAll()

    def _toggle_sidebar(self) -> None:
        self.sidebar.toggleViewAction().trigger()

    def _toggle_log(self) -> None:
        if self.log_dock.isVisible():
            self.log_dock.hide()
        else:
            self.log_dock.show()
            self.log_dock.raise_()

    # -- scan -----------------------------------------------------------

    def _start_scan(self) -> None:
        if self._scanning:
            return
        self._scanning = True
        self.actions.run_scan.setEnabled(False)
        self.actions.run_scan.setText("Scanning\u2026")
        self.status_bar.showMessage("Scanning\u2026")

        # Show the log dock while scanning so the user sees progress.
        if not self.log_dock.isVisible():
            self.log_dock.show()
            self.log_dock.raise_()
        self.log_dock.clear()

        self._scan_thread = QThread(self)
        self._scan_worker = ScanWorker(dry_run=False, fetch_missing=True)
        self._scan_worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.textWritten.connect(self.log_dock.append)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_worker.finished.connect(self._scan_thread.quit)
        self._scan_thread.finished.connect(self._scan_worker.deleteLater)
        self._scan_thread.finished.connect(self._scan_thread.deleteLater)
        self._scan_thread.start()

    def _on_scan_finished(self, success: bool) -> None:
        self._scanning = False
        self.actions.run_scan.setEnabled(True)
        self.actions.run_scan.setText("&Run Scan")
        if success:
            self.status_bar.showMessage("Scan complete.", 5000)
        else:
            self.status_bar.showMessage("Scan finished with errors.", 8000)
        self.refresh()
        self._scan_worker = None
        self._scan_thread = None

    def _on_color_scheme_changed(self, _scheme) -> None:
        self._table.refresh_palette()
        self.detail.refresh_palette()
        self.sidebar.refresh_palette()

    def _install_section_shortcuts(self) -> None:
        from PySide6.QtGui import QShortcut, QKeySequence

        prefix = "Meta" if accel() == "Cmd" else "Ctrl"
        for i, section in enumerate(db.COUNTED_SECTIONS[:9], start=1):
            QShortcut(QKeySequence(f"{prefix}+{i}"), self,
                      activated=lambda s=section: self.select_section(s))

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            f"About {APP_TITLE}",
            f"<b>{APP_TITLE}</b><br>"
            "Scans the UIUC Virtual Job Board and tracks postings.<br><br>"
            f"Accelerator: {accel()} · Qt {QT_VERSION_STR if (QT_VERSION_STR := self._qt_version()) else ''}",
        )

    @staticmethod
    def _qt_version() -> str:
        from PySide6 import __version__ as pyside_version
        return f"{pyside_version} / Qt {QT_VERSION}" if (QT_VERSION := _qt_runtime_version()) else pyside_version

    def _not_implemented(self, name: str):
        def _handler() -> None:
            self.status_bar.showMessage(f"{name}: not wired up yet", 4000)
        return _handler

    # -- close ---------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802
        settings = QSettings()
        settings.setValue("window/geometry", self.saveGeometry())
        settings.setValue("window/state", self.saveState())
        settings.setValue("window/splitter_sizes", self.splitter.sizes())
        super().closeEvent(event)


def launch(db_path: Optional[Path] = None,
           keywords_path: Optional[Path] = None) -> None:
    """Build the QApplication + main window and enter the event loop."""
    QCoreApplication.setOrganizationName(APP_ORG)
    QCoreApplication.setApplicationName(APP_NAME)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationDisplayName(APP_TITLE)

    theme.apply_app(app)

    db_path = Path(db_path) if db_path else config.DB_PATH
    keywords_path = Path(keywords_path) if keywords_path else config.KEYWORDS_PATH
    try:
        db.init_db(db_path)
    except Exception as exc:  # noqa: BLE001
        print(f"[gui] could not init db at {db_path}: {exc}", file=sys.stderr)

    window = JobScannerApp(db_path, keywords_path)
    window.show()
    app.exec()


if __name__ == "__main__":
    launch()
