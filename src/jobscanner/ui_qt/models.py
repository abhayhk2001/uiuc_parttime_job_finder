"""``QAbstractTableModel`` for the jobs list.

Column order is fixed (mirrors the order the old CTk UI used) and each
column has a key (matches the SQL field name), a display heading, an
initial width in pixels, and whether its values should be right-aligned.

Roles the model exposes:

- ``Qt.DisplayRole``  -- the cell text (truncated where appropriate)
- ``Qt.SortRole``     -- the value used for sort (numeric for the count
                          columns, lowercased string for the text columns)
- ``Qt.ForegroundRole``-- QColor taken from the palette, driven by the
                          (reviewed, matched) state of the row
- ``Qt.TextAlignmentRole`` -- per-column alignment
- ``Qt.ToolTipRole``  -- the full, untruncated title
- ``JobRoles.JobIdRole`` -- the raw ``job_id`` string (used by selection
                            handlers and the detail pane)
- ``JobRoles.JobDictRole`` -- the full row dict (used by the detail pane
                              to avoid a second DB round-trip)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Optional

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

from jobscanner.ui_qt import theme


#: Sort role value. PySide6 6.11 dropped ``Qt.SortRole`` from ``ItemDataRole``
#: in this release -- the historical integer is 14 and the proxy still
#: honours it. Define a single source of truth so callers don't repeat the
#: literal.
SORT_ROLE = 14


class JobRoles(IntEnum):
    """Custom roles layered on top of Qt's standard roles."""

    JobIdRole = Qt.UserRole + 1
    JobDictRole = Qt.UserRole + 2


@dataclass(frozen=True)
class Column:
    key: str
    heading: str
    width: int
    right_aligned: bool = False
    numeric: bool = False


COLUMNS: tuple[Column, ...] = (
    Column("job_id", "Job ID", 80, right_aligned=True),
    Column("title", "Title", 380),
    Column("company", "Company", 200),
    Column("matches", "Matches", 70, right_aligned=True, numeric=True),
    Column("reviewed", "Reviewed", 80, right_aligned=True, numeric=True),
)


def _match_count(matched_keywords: str | None) -> int:
    if not matched_keywords:
        return 0
    return len([k for k in matched_keywords.split(",") if k.strip()])


def _row_color(palette, reviewed: bool, match_count: int) -> QColor:
    """Color the row text based on its (reviewed, matched) state."""
    if reviewed and match_count:
        return QColor(palette["match_reviewed_fg"])
    if reviewed:
        return QColor(palette["reviewed_fg"])
    if match_count:
        return QColor(palette["match_fg"])
    return QColor(palette["text"])


class JobsTableModel(QAbstractTableModel):
    """Backing model for the jobs table. Holds ``list[dict]`` rows.

    Rows come from :func:`jobscanner.storage.get_jobs_by_section` and are
    flat dicts; the model never queries the DB itself. ``set_rows`` is the
    only mutator you need.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[dict] = []
        self._palette = theme.current_palette()

    # -- population -------------------------------------------------------

    def set_rows(self, rows: list[dict]) -> None:
        """Replace every row. Resets selection in the view."""
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def rows(self) -> list[dict]:
        """The raw row list (defensive copy)."""
        return list(self._rows)

    def job_dict_at(self, source_row: int) -> Optional[dict]:
        """Return the row dict at ``source_row`` (or ``None`` if OOB)."""
        if 0 <= source_row < len(self._rows):
            return self._rows[source_row]
        return None

    # -- refresh on theme change -----------------------------------------

    def refresh_palette(self) -> None:
        """Re-read palette colors and emit a dataChanged for visible cells.

        Called by the app after a theme switch so the ForegroundRole
        colors stay in sync.
        """
        self._palette = theme.current_palette()
        if self._rows:
            top = self.index(0, 0)
            bottom = self.index(len(self._rows) - 1, len(COLUMNS) - 1)
            self.dataChanged.emit(top, bottom, [Qt.ForegroundRole])

    # -- Qt model API ----------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if orientation != Qt.Horizontal or not (0 <= section < len(COLUMNS)):
            return None
        col = COLUMNS[section]
        if role == Qt.DisplayRole:
            return col.heading
        if role == Qt.TextAlignmentRole and col.right_aligned:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        col_idx = index.column()
        if not (0 <= row < len(self._rows)) or not (0 <= col_idx < len(COLUMNS)):
            return None
        row_dict = self._rows[row]
        col = COLUMNS[col_idx]
        reviewed = bool(row_dict.get("reviewed"))
        match_count = _match_count(row_dict.get("matched_keywords") or "")

        if role == JobRoles.JobIdRole:
            return row_dict.get("job_id", "") or ""
        if role == JobRoles.JobDictRole:
            return row_dict
        if role == Qt.ForegroundRole:
            return _row_color(self._palette, reviewed, match_count)
        if role == Qt.TextAlignmentRole and col.right_aligned:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.ToolTipRole and col.key == "title":
            return row_dict.get("title") or ""

        if role == SORT_ROLE:
            if col.key == "matches":
                return match_count
            if col.key == "reviewed":
                return 1 if reviewed else 0
            value = row_dict.get(col.key) or ""
            return value.lower() if isinstance(value, str) else value

        if role == Qt.DisplayRole:
            if col.key == "title":
                return (row_dict.get("title") or "")[:80]
            if col.key == "company":
                return (row_dict.get("company") or "")[:35]
            if col.key == "matches":
                return str(match_count) if match_count else ""
            if col.key == "reviewed":
                return "\u2713" if reviewed else ""
            return str(row_dict.get(col.key, "") or "")
        return None
