"""The jobs table view: a ``QTableView`` over ``JobsFilterProxy``.

Behaviour parity with the old CTk ``JobsTable``:

- Sortable headers (single click toggles direction on the same column).
- Right-aligned numeric columns.
- Row selection (whole rows, not individual cells).
- ``selected_id()`` returns the ``job_id`` of the selected row, or
  ``None`` if nothing is selected.
- ``current_job_dict()`` returns the full row dict of the current row.
- ``setContextMenuPolicy(Qt.CustomContextMenu)`` emits ``contextMenuRequested``
  with the row's source ``job_id`` and the screen coordinate of the click
  -- the app installs a real native ``QMenu`` here in step 5/9.

Empty state: when the proxy has zero rows, an overlay label is shown with
a caller-supplied message (the app builds it from the current section +
search state).
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QTableView,
)

from jobscanner.ui_qt.models import COLUMNS, JobRoles, JobsTableModel
from jobscanner.ui_qt.proxies import JobsFilterProxy


class JobsTableView(QTableView):
    """The right-hand table widget. Owns model, proxy, selection."""

    #: Emitted whenever the selection changes; payload is the job_id
    #: (or ``None`` if the selection cleared).
    selectionJobIdChanged = Signal(object)

    #: Emitted on right-click; payload is ``(job_id, global_pos)``.
    contextMenuRequested = Signal(str, object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._empty_label = QLabel("", self)
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setStyleSheet("color: palette(mid); font-size: 14px;")
        self._empty_label.hide()

        self._model = JobsTableModel(self)
        self._proxy = JobsFilterProxy(self)
        self._proxy.setSourceModel(self._model)
        self.setModel(self._proxy)

        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(False)
        self.setShowGrid(False)
        self.setSortingEnabled(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)

        # Native-looking vertical header with auto row height.
        vh = self.verticalHeader()
        vh.setVisible(False)
        vh.setDefaultSectionSize(24)

        hh = self.horizontalHeader()
        hh.setHighlightSections(False)
        hh.setStretchLastSection(True)
        hh.setSectionsMovable(False)
        # 'matches' starts descending-first (the user wants the most
        # promising rows at the top), matching the old behaviour.
        for col_idx, col in enumerate(COLUMNS):
            self.setColumnWidth(col_idx, col.width)
            if col.numeric:
                self._proxy.sort(col_idx, Qt.DescendingOrder if col.key == "matches" else Qt.AscendingOrder)
                break

        self.customContextMenuRequested.connect(self._on_context_menu)
        self._proxy.layoutChanged.connect(self._sync_empty_state)
        self._proxy.modelReset.connect(self._sync_empty_state)
        self._proxy.rowsInserted.connect(self._sync_empty_state)
        self._proxy.rowsRemoved.connect(self._sync_empty_state)
        self.selectionModel().currentRowChanged.connect(self._on_current_row_changed)
        self.selectionModel().selectionChanged.connect(self._on_selection_changed)

        self._sync_empty_state()

    # -- public API ------------------------------------------------------

    def source_model(self) -> JobsTableModel:
        return self._model

    def proxy(self) -> JobsFilterProxy:
        return self._proxy

    def set_rows(self, rows: list[dict]) -> None:
        """Replace every row in the model. Selection clears; sort persists."""
        self._model.set_rows(rows)
        self._sync_empty_state()

    def selected_id(self) -> Optional[str]:
        idx = self.selectionModel().currentIndex()
        if not idx.isValid():
            return None
        job_id = self._proxy.data(idx, JobRoles.JobIdRole)
        return job_id or None

    def current_job_dict(self) -> Optional[dict]:
        idx = self.selectionModel().currentIndex()
        if not idx.isValid():
            return None
        return self._proxy.data(idx, JobRoles.JobDictRole)

    def select_id(self, job_id: str) -> bool:
        """Select the row with ``job_id`` if present. Returns True on hit."""
        if not job_id:
            return False
        for source_row in range(self._model.rowCount()):
            idx = self._model.index(source_row, 0)
            if self._model.data(idx, JobRoles.JobIdRole) == job_id:
                proxy_idx = self._proxy.mapFromSource(idx)
                if proxy_idx.isValid():
                    self.selectRow(proxy_idx.row())
                    self.scrollTo(proxy_idx, QAbstractItemView.PositionAtCenter)
                    return True
        return False

    def set_search_text(self, text: str) -> None:
        self._proxy.set_search_text(text)

    def set_matches_only(self, value: bool) -> None:
        self._proxy.set_matches_only(value)

    def set_empty_message(self, text: str) -> None:
        self._empty_label.setText(text or "")
        self._sync_empty_state()

    def refresh_palette(self) -> None:
        self._model.refresh_palette()

    # -- internals -------------------------------------------------------

    def _on_current_row_changed(self, current, _previous) -> None:
        if not current.isValid():
            self.selectionJobIdChanged.emit(None)
            return
        job_id = self._proxy.data(current, JobRoles.JobIdRole)
        self.selectionJobIdChanged.emit(job_id or None)

    def _on_selection_changed(self, *_args) -> None:
        # Some selection events only fire selectionChanged (e.g. clicks that
        # don't move currentRow). Mirror to selectionJobIdChanged so callers
        # always see an update.
        self.selectionJobIdChanged.emit(self.selected_id())

    def _on_context_menu(self, pos: QPoint) -> None:
        idx = self.indexAt(pos)
        if not idx.isValid():
            return
        self.selectRow(idx.row())
        job_id = self.selected_id()
        if job_id:
            global_pos = self.viewport().mapToGlobal(pos)
            self.contextMenuRequested.emit(job_id, global_pos)

    def _sync_empty_state(self, *_args) -> None:
        empty = self._proxy.rowCount() == 0
        if empty and self._empty_label.text():
            self._empty_label.setGeometry(self.viewport().geometry())
            self._empty_label.show()
            self._empty_label.raise_()
        else:
            self._empty_label.hide()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._empty_label.isVisible():
            self._empty_label.setGeometry(self.viewport().geometry())
