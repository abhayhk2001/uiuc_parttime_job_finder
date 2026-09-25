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
