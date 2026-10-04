"""The sidebar: section counters, bulk actions, and the keyword list.

Implemented as a single ``QDockWidget`` whose contents are a vertical
``QSplitter``:

- Top:    ``SectionsList`` (a ``QListView`` of section names + counts).
- Middle: ``BulkActionBar`` (a vertical column of ``QToolButton``s).
- Bottom: ``KeywordPanel`` (the list of keywords + Edit Keywords button).

The app inserts the dock on the left edge and lets the user float, hide,
or re-dock it via the View menu. Section-click, bulk-action-click, and
edit-keywords signals bubble up to the main window via signals declared
on :class:`SidebarDock`.
"""

from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDockWidget,
    QFrame,
    QLabel,
    QListView,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from jobscanner import storage as db
from jobscanner.ui_qt import palette as palette_mod
from jobscanner.ui_qt import theme
from jobscanner.ui_qt.bulk_actions import BULK_ACTIONS, BulkAction


# ---------------------------------------------------------------------------
# Sections list
# ---------------------------------------------------------------------------


class _SectionsModel(QAbstractListModel):
    """List model of ``(section_key, label, count)`` tuples."""

    KEY_ROLE = Qt.UserRole + 1

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._items: list[tuple[str, str, int]] = []
        self._current: str = db.SECTION_NEW

    def roleNames(self):  # noqa: N802 -- Qt naming
        return {Qt.DisplayRole: b"display", self.KEY_ROLE: b"key"}

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._items)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None
        key, label, count = self._items[index.row()]
        if role == Qt.DisplayRole:
            return f"{label}  ({count})"
        if role == self.KEY_ROLE:
            return key
        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        return None

    def set_sections(self, items: list[tuple[str, str, int]],
                     current: str) -> None:
        self.beginResetModel()
        self._items = list(items)
        self._current = current
        self.endResetModel()

    def set_current(self, current: str) -> None:
        if current == self._current:
            return
        self._current = current
        if self._items:
            top = self.index(0)
            bottom = self.index(len(self._items) - 1)
            self.dataChanged.emit(top, bottom)

    def current_key(self) -> str:
        return self._current


class SectionsList(QWidget):
    """The list of sections with counts."""

    sectionSelected = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._model = _SectionsModel(self)
        self._view = QListView(self)
        self._view.setModel(self._model)
        self._view.setSelectionMode(QListView.SingleSelection)
        self._view.setUniformItemSizes(True)
        self._view.setFrameShape(QFrame.NoFrame)
        self._view.setMinimumWidth(180)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        header = QLabel("SECTIONS", self)
        header.setProperty("role", "section-header")
        layout.addWidget(header)
        layout.addWidget(self._view, 1)

        # Selection is driven by currentChanged alone, which covers clicks
        # and arrow keys. Also listening to clicked/activated emitted
        # sectionSelected two or three times per click, each one a full
        # database query and model reset.
        self._view.selectionModel().currentChanged.connect(
            self._on_current_changed)

    def set_sections(self, items: list[tuple[str, str, int]],
                     current: str) -> None:
        self._model.set_sections(items, current)
        self._select_current()

    def set_current(self, current: str) -> None:
        self._model.set_current(current)
        self._select_current()

    def current_key(self) -> str:
        return self._model.current_key()

    def _select_current(self) -> None:
        for row in range(self._model.rowCount()):
            idx = self._model.index(row, 0)
            if self._model.data(idx, _SectionsModel.KEY_ROLE) == self._model.current_key():
                self._view.setCurrentIndex(idx)
                return

    def _on_current_changed(self, current: QModelIndex, _previous) -> None:
        if not current.isValid():
            return
        key = self._model.data(current, _SectionsModel.KEY_ROLE)
        if key and key != self._model.current_key():
            # Sync the model without re-emitting the user signal.
            self._model.set_current(str(key))
            self.sectionSelected.emit(str(key))


# ---------------------------------------------------------------------------
# Bulk actions
# ---------------------------------------------------------------------------


class BulkActionBar(QWidget):
    """A vertical column of bulk-action buttons. One ``QToolButton`` per action."""

    actionInvoked = Signal(str)  # the BulkAction.id

    def __init__(self, parent=None,
                 actions: Iterable[BulkAction] = BULK_ACTIONS) -> None:
        super().__init__(parent)
        self._actions: dict[str, BulkAction] = {}
        self._buttons: dict[str, QToolButton] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        header = QLabel("BULK ACTIONS", self)
        header.setProperty("role", "section-header")
        layout.addWidget(header)

        for action in actions:
            btn = QToolButton(self)
            btn.setText(action.label)
            btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.clicked.connect(
                lambda _checked=False, aid=action.id: self.actionInvoked.emit(aid))
            layout.addWidget(btn)
            self._actions[action.id] = action
            self._buttons[action.id] = btn
        layout.addStretch(1)

    def set_enabled_by_section(self, counts: dict) -> None:
        """Enable each button only if its target section has rows."""
        for action_id, btn in self._buttons.items():
            action = self._actions[action_id]
            btn.setEnabled(bool(counts.get(action.section)))


# ---------------------------------------------------------------------------
# Keyword panel
# ---------------------------------------------------------------------------


class KeywordPanel(QWidget):
    """A small scrollable list of loaded keywords + Edit Keywords button."""

    editRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        header = QLabel("KEYWORDS", self)
        header.setProperty("role", "section-header")
        layout.addWidget(header)

        self._count_label = QLabel("0 loaded", self)
        layout.addWidget(self._count_label)

        edit_btn = QPushButton("Edit Keywords\u2026", self)
        edit_btn.clicked.connect(self.editRequested)
        layout.addWidget(edit_btn)

        self._list_holder = QWidget(self)
        self._list_layout = QVBoxLayout(self._list_holder)
        self._list_layout.setContentsMargins(0, 4, 0, 0)
        self._list_layout.setSpacing(1)
        self._list_layout.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self._list_holder)
        layout.addWidget(scroll, 1)

    def set_keywords(self, keywords: list[str]) -> None:
        # Clear existing labels
        while self._list_layout.count() > 1:  # keep the trailing stretch
            item = self._list_layout.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.deleteLater()
        self._count_label.setText(f"{len(keywords)} loaded")
        if not keywords:
            empty = QLabel("(none \u2014 Edit Keywords to add)", self._list_holder)
            empty.setProperty("role", "faint")
            self._list_layout.insertWidget(0, empty)
            return
        for i, kw in enumerate(keywords):
            label = QLabel(kw, self._list_holder)
            label.setWordWrap(False)
            self._list_layout.insertWidget(i, label)


# ---------------------------------------------------------------------------
# Sidebar dock
# ---------------------------------------------------------------------------


class SidebarDock(QDockWidget):
    """The whole sidebar as a single dockable, hideable panel."""

    sectionSelected = Signal(str)
    bulkActionInvoked = Signal(str)
    editKeywordsRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__("Sidebar", parent)
        self.setObjectName("sidebar-dock")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setFeatures(
            QDockWidget.DockWidgetClosable
            | QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
        )

        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._sections = SectionsList(container)
        self._bulk = BulkActionBar(container)
        self._keywords = KeywordPanel(container)

        splitter = QSplitter(Qt.Vertical, container)
        splitter.addWidget(self._sections)
        splitter.addWidget(self._bulk)
        splitter.addWidget(self._keywords)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 2)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)

        self.setWidget(container)

        self._sections.sectionSelected.connect(self.sectionSelected)
        self._bulk.actionInvoked.connect(self.bulkActionInvoked)
        self._keywords.editRequested.connect(self.editKeywordsRequested)

    # -- public API ---------------------------------------------------

    def refresh_sections(self, sections: list[tuple[str, str, int]],
                         counts: dict, current: str) -> None:
        self._sections.set_sections(sections, current)
        self._bulk.set_enabled_by_section(counts)

    def set_bulk_enabled(self, enabled: bool) -> None:
        """Enable or disable the whole bulk block (e.g. while scanning).
        Each button keeps its own count-based state underneath."""
        self._bulk.setEnabled(enabled)

    def set_current_section(self, current: str) -> None:
        self._sections.set_current(current)

    def set_keywords(self, keywords: list[str]) -> None:
        self._keywords.set_keywords(keywords)

    def refresh_palette(self) -> None:
        """Re-apply theme-derived styles when the user toggles appearance."""
        p = theme.current_palette()
        style = (
            f"QLabel[role='section-header'] {{ "
            f"color: {p['muted']}; font-weight: bold; padding: 2px 4px; "
            f"}} "
            f"QLabel[role='faint'] {{ color: {p['faint']}; }}"
        )
        # Apply to all labels under the dock; QSS doesn't traverse widget
        # properties without explicit selectors, so we set the style on the
        # container and let cascade cover descendants.
        self.widget().setStyleSheet(style)


# ---------------------------------------------------------------------------
# Helpers used by the app to build the section list
# ---------------------------------------------------------------------------


def build_sections_list() -> list[tuple[str, str, int]]:
    """Return the sidebar's section list as ``(key, label, count=0)`` tuples.

    The counts are placeholders; the app calls
    :func:`SidebarDock.refresh_sections` with real counts from the DB.
    """
    return [(s.key, s.label, 0) for s in db.SECTIONS]
