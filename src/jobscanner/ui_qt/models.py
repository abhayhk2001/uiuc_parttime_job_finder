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

from PySide6.QtCore import QAbstractItemModel, QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QFont

from jobscanner.sources import SOURCE_LABELS, SOURCES
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


#: The `source` column deliberately isn't here -- rows are grouped by source
#: and the board's name lives in the group header instead.
COLUMNS: tuple[Column, ...] = (
    Column("job_id", "Job ID", 110, right_aligned=True),
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
        return job_cell_data(self._rows[row], col_idx, role, self._palette)


def _job_id_sort_key(job_id: str) -> str:
    """Make numeric ids sort as numbers: "vjb:99" before "vjb:100".

    Compared as plain text, "vjb:100" sorted first. Digits are zero-padded
    so the key stays a string -- Qt compares it like any other.
    """
    prefix, _, native = job_id.rpartition(":")
    if native.isdigit():
        native = native.zfill(12)
    return f"{prefix}:{native}".lower()


def job_cell_data(row_dict: dict, col_idx: int, role: int, palette):
    """Render one cell of one job row.

    Shared by the flat and grouped models so the two can never drift apart.
    """
    if not (0 <= col_idx < len(COLUMNS)):
        return None
    col = COLUMNS[col_idx]
    reviewed = bool(row_dict.get("reviewed"))
    match_count = _match_count(row_dict.get("matched_keywords") or "")

    if role == JobRoles.JobIdRole:
        return row_dict.get("job_id", "") or ""
    if role == JobRoles.JobDictRole:
        return row_dict
    if role == Qt.ForegroundRole:
        return _row_color(palette, reviewed, match_count)
    if role == Qt.TextAlignmentRole and col.right_aligned:
        return int(Qt.AlignRight | Qt.AlignVCenter)
    if role == Qt.ToolTipRole and col.key == "title":
        return row_dict.get("title") or ""

    if role == SORT_ROLE:
        if col.key == "matches":
            return match_count
        if col.key == "reviewed":
            return 1 if reviewed else 0
        if col.key == "job_id":
            return _job_id_sort_key(row_dict.get("job_id") or "")
        value = row_dict.get(col.key) or ""
        return value.lower() if isinstance(value, str) else value

    if role == Qt.DisplayRole:
        if col.key == "job_id":
            # Ids are namespaced ("rp:48827"); the source is shown in the
            # group header, so don't repeat the prefix on every row.
            job_id = row_dict.get("job_id", "") or ""
            return job_id.split(":", 1)[1] if ":" in job_id else job_id
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


# ---------------------------------------------------------------------------
# Grouped (tree) model
# ---------------------------------------------------------------------------

#: Position of each source key in the canonical ordering, so groups appear in
#: the same order as the registry rather than alphabetically.
_SOURCE_ORDER: dict[str, int] = {s.key: i for i, s in enumerate(SOURCES)}


@dataclass
class Group:
    """One source's block of rows. Held by the model; Qt stores a pointer
    to it in every child index, so these must outlive the indexes."""

    key: str
    label: str
    rows: list[dict]
    position: int

    @property
    def heading(self) -> str:
        return f"{self.label}  ({len(self.rows)})"


class JobsTreeModel(QAbstractItemModel):
    """Two-level model: one node per source, jobs underneath.

    Only sources actually present in the current rows get a group, so an
    empty board contributes nothing rather than an empty heading.

    Group indexes carry ``None`` as their internal pointer and child indexes
    carry their :class:`Group`, which is how :meth:`parent` tells them apart.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._groups: list[Group] = []
        self._palette = theme.current_palette()

    # -- population -------------------------------------------------------

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        buckets: dict[str, list[dict]] = {}
        for row in rows:
            buckets.setdefault(row.get("source") or "", []).append(row)
        ordered = sorted(buckets, key=lambda k: (_SOURCE_ORDER.get(k, 999), k))
        self._groups = [
            Group(key=key,
                  label=SOURCE_LABELS.get(key, key or "Unknown"),
                  rows=buckets[key],
                  position=i)
            for i, key in enumerate(ordered)
        ]
        self.endResetModel()

    def groups(self) -> list[Group]:
        return list(self._groups)

    def rows(self) -> list[dict]:
        """Every job row, in group order."""
        return [r for g in self._groups for r in g.rows]

    def group_at(self, row: int) -> Optional[Group]:
        if 0 <= row < len(self._groups):
            return self._groups[row]
        return None

    def refresh_palette(self) -> None:
        """Re-read palette colours and invalidate every painted cell.

        The job rows are *children* of the section rows, so invalidating the
        top level alone leaves their match/reviewed colours stale after a
        theme switch -- which is exactly what the first version of this did.
        Each group's children need their own dataChanged.
        """
        self._palette = theme.current_palette()
        if not self._groups:
            return
        last_col = len(COLUMNS) - 1
        # The section rows themselves.
        self.dataChanged.emit(
            self.index(0, 0), self.index(len(self._groups) - 1, last_col),
            [Qt.ForegroundRole])
        # And the jobs under each one.
        for position, group in enumerate(self._groups):
            if not group.rows:
                continue
            parent = self.index(position, 0)
            self.dataChanged.emit(
                self.index(0, 0, parent),
                self.index(len(group.rows) - 1, last_col, parent),
                [Qt.ForegroundRole])

    # -- index plumbing ---------------------------------------------------

    def index(self, row: int, column: int,
              parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        if not parent.isValid():
            return self.createIndex(row, column, None)
        group = self.group_at(parent.row())
        if group is None:
            return QModelIndex()
        return self.createIndex(row, column, group)

    def parent(self, index: QModelIndex) -> QModelIndex:  # noqa: A003
        if not index.isValid():
            return QModelIndex()
        group = index.internalPointer()
        if group is None:
            return QModelIndex()
        return self.createIndex(group.position, 0, None)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if not parent.isValid():
            return len(self._groups)
        if parent.internalPointer() is not None:
            return 0  # job rows have no children
        group = self.group_at(parent.row())
        return len(group.rows) if group else 0

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
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

    # -- data -------------------------------------------------------------

    def is_group(self, index: QModelIndex) -> bool:
        return index.isValid() and index.internalPointer() is None

    def job_dict(self, index: QModelIndex) -> Optional[dict]:
        group = index.internalPointer() if index.isValid() else None
        if group is None:
            return None
        if 0 <= index.row() < len(group.rows):
            return group.rows[index.row()]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        group = index.internalPointer()

        if group is None:
            return self._group_data(index, role)

        row_dict = self.job_dict(index)
        if row_dict is None:
            return None
        return job_cell_data(row_dict, index.column(), role, self._palette)

    def _group_data(self, index: QModelIndex, role: int):
        group = self.group_at(index.row())
        if group is None:
            return None
        # Group rows are not jobs: returning None for JobIdRole is what keeps
        # selection handlers and the detail pane from treating one as a job.
        if role in (JobRoles.JobIdRole, JobRoles.JobDictRole):
            return None
        if role == Qt.DisplayRole:
            return group.heading if index.column() == 0 else None
        if role == SORT_ROLE:
            # Groups keep registry order whatever column the user sorts by.
            return group.position
        if role == Qt.FontRole:
            font = QFont()
            font.setBold(True)
            return font
        if role == Qt.ForegroundRole:
            return QColor(self._palette["text"])
        return None
