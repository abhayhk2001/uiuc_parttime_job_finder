"""``QSortFilterProxyModel`` for the jobs table.

Combines two filters:

- ``set_search_text(text)`` -- case-insensitive substring match against
  title, company, description, requirements, skills, and matched keywords
  (same set of fields :func:`jobscanner.storage.get_jobs_by_section`
  searches against).
- ``set_matches_only(bool)`` -- only rows whose ``matched_keywords`` is
  non-empty.

Both filters AND together. ``filterAcceptsRow`` runs once per row
whenever either filter changes; cheap for the row counts this app deals
with (hundreds to low thousands).
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QSortFilterProxyModel, Qt

from jobscanner.ui_qt.models import SORT_ROLE


class JobsFilterProxy(QSortFilterProxyModel):
    """Filter + sort the :class:`JobsTableModel`."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._needle: str = ""
        self._matches_only: bool = False
        self.setSortRole(SORT_ROLE)
        # Rows live one level down, under a group node. Recursive filtering
        # keeps a group whose children match and drops one whose children
        # all fail, so empty sections disappear on their own.
        self.setRecursiveFilteringEnabled(True)

    # -- public API ------------------------------------------------------

    def set_search_text(self, text: str) -> None:
        text = (text or "").strip().lower()
        if text == self._needle:
            return
        self._needle = text
        # ``invalidate()`` is the non-deprecated alias for the
        # row-filter invalidation in PySide6 6.11+; both
        # ``invalidateFilter`` and ``invalidateRowsFilter`` raise
        # DeprecationWarning on this binding.
        self.invalidate()

    def search_text(self) -> str:
        return self._needle

    def set_matches_only(self, value: bool) -> None:
        if bool(value) == self._matches_only:
            return
        self._matches_only = bool(value)
        self.invalidate()

    def matches_only(self) -> bool:
        return self._matches_only

    # -- internals -------------------------------------------------------

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
        from jobscanner.ui_qt.models import JobRoles

        model = self.sourceModel()
        if model is None:
            return True
        idx = model.index(source_row, 0, source_parent)
        row_dict = model.data(idx, JobRoles.JobDictRole)
        if row_dict is None:
            # A group node. Reject it on its own merits; recursive filtering
            # re-admits it if any of its jobs pass.
            return False

        if self._matches_only:
            mk = (row_dict.get("matched_keywords") or "").strip()
            if not mk:
                return False

        if self._needle:
            fields = (
                row_dict.get("title") or "",
                row_dict.get("company") or "",
                row_dict.get("job_description") or "",
                row_dict.get("requirements") or "",
                row_dict.get("skills") or "",
                row_dict.get("matched_keywords") or "",
            )
            if not any(self._needle in (f or "").lower() for f in fields):
                return False

        return True

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:  # noqa: N802
        """Sort jobs within their group, never the groups themselves.

        Without this, sorting by Title would reshuffle the sections too.
        Sections must always read in registry order (VJB, Research Park,
        Clearinghouse, Library) whichever column the user sorts by, and in
        whichever direction.

        Qt reverses the comparison for a descending sort, so to land on the
        same order either way the verdict is inverted when descending.
        """
        model = self.sourceModel()
        is_group = getattr(model, "is_group", None)
        if is_group is not None and is_group(left) and is_group(right):
            if self.sortOrder() == Qt.DescendingOrder:
                return left.row() > right.row()
            return left.row() < right.row()
        return super().lessThan(left, right)
