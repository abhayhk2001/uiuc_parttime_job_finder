"""The jobs table view: a ``QTreeView`` over ``JobsFilterProxy``.

Rows are grouped into a collapsible section per source ("Research Park
(15)"), which is why this is a tree rather than a table -- a QTreeView
still shows columns, so it reads as a table with section headings. The
source therefore has no column of its own.

- Sortable headers. Sorting reorders jobs *within* each section; the
  sections themselves keep registry order (see ``JobsFilterProxy.lessThan``).
- Sections collapse, and which ones are collapsed is remembered between
  launches in ``QSettings``.
- ``selected_id()`` returns the ``job_id`` of the selected row, or ``None``
  -- including when a section heading is selected, since a heading is not
  a job.
- ``visible_job_ids()`` / ``visible_job_count()`` flatten the tree for
  callers that want jobs. Note ``proxy().rowCount()`` counts *sections*.
- ``current_job_dict()`` returns the full row dict of the current row.
- ``setContextMenuPolicy(Qt.CustomContextMenu)`` emits ``contextMenuRequested``
  with the row's ``job_id`` and the screen coordinate of the click.

Empty state: when no jobs are visible, an overlay label is shown with a
caller-supplied message (the app builds it from the current section +
search state).
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QModelIndex, QPoint, QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QTreeView,
)

from jobscanner.ui_qt.models import COLUMNS, JobRoles, JobsTreeModel
from jobscanner.ui_qt.proxies import JobsFilterProxy
from jobscanner.ui_qt.settings import app_settings

#: Where collapsed sections are remembered between launches.
_COLLAPSED_KEY = "table/collapsed_sources"

_MATCHES_COLUMN = next(i for i, c in enumerate(COLUMNS) if c.key == "matches")


class JobsTableView(QTreeView):
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

        self._model = JobsTreeModel(self)
        self._proxy = JobsFilterProxy(self)
        self._proxy.setSourceModel(self._model)
        self.setModel(self._proxy)

        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(False)
        self.setSortingEnabled(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.setRootIsDecorated(True)
        self.setUniformRowHeights(True)
        self.setExpandsOnDoubleClick(True)
        self.setAllColumnsShowFocus(True)
        self.setIndentation(14)

        hh = self.header()
        hh.setHighlightSections(False)
        hh.setStretchLastSection(True)
        hh.setSectionsMovable(False)
        for col_idx, col in enumerate(COLUMNS):
            self.setColumnWidth(col_idx, col.width)
        # Open with the most-matching jobs first. Explicit rather than via
        # apply_default_sort: setSortingEnabled() above has already sorted
        # by column 0, which that method would keep as a user's choice.
        self.sortByColumn(_MATCHES_COLUMN, Qt.DescendingOrder)

        self.expanded.connect(self._remember_expansion)
        self.collapsed.connect(self._remember_expansion)
        self.customContextMenuRequested.connect(self._on_context_menu)
        # Filtering and sorting can add, drop or move section rows, and a
        # span is tied to a row index -- so re-apply them whenever the shape
        # of the view changes, not just after set_rows().
        for signal in (self._proxy.layoutChanged, self._proxy.modelReset,
                       self._proxy.rowsInserted, self._proxy.rowsRemoved):
            signal.connect(self._on_shape_changed)
        self.selectionModel().currentRowChanged.connect(self._on_current_row_changed)
        self.selectionModel().selectionChanged.connect(self._on_selection_changed)

        self._sync_empty_state()

    # -- public API ------------------------------------------------------

    def source_model(self) -> JobsTreeModel:
        return self._model

    def proxy(self) -> JobsFilterProxy:
        return self._proxy

    def set_rows(self, rows: list[dict]) -> None:
        """Replace every row in the model. Selection clears; sort persists."""
        self._model.set_rows(rows)
        self._restore_expansion()
        self._span_group_rows()
        self._sync_empty_state()

    # -- grouped-row helpers ---------------------------------------------

    def visible_job_ids(self) -> list[str]:
        """Every job currently shown, in display order, groups flattened.

        Callers want jobs, not sections; `proxy().rowCount()` counts groups.
        """
        out: list[str] = []
        for g in range(self._proxy.rowCount()):
            parent = self._proxy.index(g, 0)
            for r in range(self._proxy.rowCount(parent)):
                job_id = self._proxy.data(self._proxy.index(r, 0, parent),
                                          JobRoles.JobIdRole)
                if job_id:
                    out.append(job_id)
        return out

    def visible_job_count(self) -> int:
        return len(self.visible_job_ids())

    def visible_group_keys(self) -> list[str]:
        """Source keys of the sections currently shown, in display order."""
        keys: list[str] = []
        for g in range(self._proxy.rowCount()):
            src_idx = self._proxy.mapToSource(self._proxy.index(g, 0))
            group = self._model.group_at(src_idx.row())
            if group is not None:
                keys.append(group.key)
        return keys

    def _span_group_rows(self) -> None:
        """Let each group heading run the full width of the view."""
        for g in range(self._proxy.rowCount()):
            self.setFirstColumnSpanned(g, QModelIndex(), True)

    # -- collapse state ---------------------------------------------------

    def _settings(self) -> QSettings:
        return app_settings()

    def collapsed_sources(self) -> set[str]:
        raw = self._settings().value(_COLLAPSED_KEY, "") or ""
        return {k for k in str(raw).split(",") if k}

    def _remember_expansion(self, *_args) -> None:
        collapsed = []
        for g in range(self._proxy.rowCount()):
            proxy_idx = self._proxy.index(g, 0)
            if self.isExpanded(proxy_idx):
                continue
            src_idx = self._proxy.mapToSource(proxy_idx)
            group = self._model.group_at(src_idx.row())
            if group is not None:
                collapsed.append(group.key)
        self._settings().setValue(_COLLAPSED_KEY, ",".join(sorted(collapsed)))

    def _restore_expansion(self) -> None:
        collapsed = self.collapsed_sources()
        for g in range(self._proxy.rowCount()):
            proxy_idx = self._proxy.index(g, 0)
            src_idx = self._proxy.mapToSource(proxy_idx)
            group = self._model.group_at(src_idx.row())
            key = group.key if group else ""
            self.setExpanded(proxy_idx, key not in collapsed)

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
        """Select the row with ``job_id`` if present. Returns True on hit.

        Expands the job's section if it was collapsed -- selecting a row the
        user cannot see would otherwise look like nothing happened.
        """
        if not job_id:
            return False
        for g in range(self._model.rowCount()):
            group_idx = self._model.index(g, 0)
            for r in range(self._model.rowCount(group_idx)):
                idx = self._model.index(r, 0, group_idx)
                if self._model.data(idx, JobRoles.JobIdRole) != job_id:
                    continue
                proxy_idx = self._proxy.mapFromSource(idx)
                if not proxy_idx.isValid():
                    return False
                self.expand(proxy_idx.parent())
                self.setCurrentIndex(proxy_idx)
                self.scrollTo(proxy_idx, QAbstractItemView.PositionAtCenter)
                return True
        return False

    def apply_default_sort(self, keep_db_order: bool) -> None:
        """Pick the sort a section opens with.

        Most sections open with the most-matching jobs first. A section
        whose database order means something (Applied: most overdue
        follow-up first; Archived: most recently archived) opens in that
        order instead -- the Matches sort used to override it. A column the
        user picked is kept when moving between ordinary sections.

        Goes through ``sortByColumn`` so the header's sort indicator always
        shows the sort actually applied; sorting the proxy directly left the
        indicator on a different column.
        """
        if keep_db_order:
            self.sortByColumn(-1, Qt.AscendingOrder)
        elif self._proxy.sortColumn() < 0:
            self.sortByColumn(_MATCHES_COLUMN, Qt.DescendingOrder)

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
        self.setCurrentIndex(idx)
        job_id = self.selected_id()
        if job_id:
            global_pos = self.viewport().mapToGlobal(pos)
            self.contextMenuRequested.emit(job_id, global_pos)

    def _on_shape_changed(self, *_args) -> None:
        self._span_group_rows()
        # A section that a filter hid and then let back in returns as a new
        # row, collapsed -- and the next expand/collapse would have saved it
        # that way. Re-apply the remembered state.
        self._restore_expansion()
        self._sync_empty_state()

    def _sync_empty_state(self, *_args) -> None:
        empty = self.visible_job_count() == 0
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
