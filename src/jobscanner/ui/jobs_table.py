"""The jobs table: a ttk.Treeview plus its row tagging and sorting."""

from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk
from tkinter import ttk

from jobscanner.ui import theme

_END = "end"

#: (key, heading, initial width)
COLUMNS: tuple[tuple[str, str, int], ...] = (
    ("job_id", "Job ID", 80),
    ("title", "Title", 380),
    ("company", "Company", 200),
    ("matches", "Matches", 70),
    ("reviewed", "Reviewed", 80),
)

_RIGHT_ALIGNED = ("job_id", "matches", "reviewed")

#: Columns that read best highest-first on the first click.
_DESCENDING_FIRST = ("matches",)


def _row_tag(reviewed: bool, match_count: int) -> str:
    if reviewed and match_count:
        return "match_reviewed"
    if reviewed:
        return "reviewed"
    if match_count:
        return "match"
    return "default"


def _sort_key(value: str):
    """Numbers sort numerically and ahead of text; text sorts case-insensitively."""
    try:
        return (0, int(value))
    except (ValueError, TypeError):
        return (1, (value or "").lower())


class JobsTable(ctk.CTkFrame):
    def __init__(self, master, on_select: Callable[[Optional[str]], None]) -> None:
        super().__init__(master)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._on_select = on_select
        # Per-column direction for the *next* click. False=ascending.
        self._next_desc: dict[str, bool] = {
            key: key in _DESCENDING_FIRST for key, _, _ in COLUMNS
        }
        self._sort_col: Optional[str] = None
        self._sort_desc: bool = False

        self.tree = ttk.Treeview(
            self, columns=[c[0] for c in COLUMNS], show="headings")
        for key, label, width in COLUMNS:
            self.tree.heading(
                key, text=label, command=lambda k=key: self.sort_by(k))
            self.tree.column(
                key, width=width,
                anchor="e" if key in _RIGHT_ALIGNED else "w", stretch=True)
        for tag, color in theme.TREE_TAG_COLORS.items():
            self.tree.tag_configure(tag, foreground=color)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<<TreeviewSelect>>", self._handle_select)

        scrollbar = ttk.Scrollbar(
            self, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)

        theme.style_treeview(self)

    # -- selection ---------------------------------------------------------

    def _handle_select(self, _event=None) -> None:
        self._on_select(self.selected_id())

    def selected_id(self) -> Optional[str]:
        selection = self.tree.selection()
        return selection[0] if selection else None

    def select(self, job_id: str) -> None:
        if job_id and job_id in self.tree.get_children():
            self.tree.selection_set(job_id)

    # -- contents ----------------------------------------------------------

    def populate(self, rows: list[dict]) -> None:
        """Replace every row, preserving selection and the active sort."""
        previous = self.selected_id()

        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for row in rows:
            reviewed = bool(row.get("reviewed"))
            raw_matches = row.get("matched_keywords") or ""
            match_count = len([k for k in raw_matches.split(",") if k])
            self.tree.insert(
                "", _END, iid=row.get("job_id", ""),
                values=(
                    row.get("job_id", ""),
                    (row.get("title") or "")[:80],
                    (row.get("company") or "")[:35],
                    str(match_count),
                    "✓" if reviewed else "",
                ),
                tags=(_row_tag(reviewed, match_count),),
            )

        # Restore selection if that row is still in the current section
        # (e.g. the user marked a row reviewed from the All section).
        if previous:
            self.select(previous)
        self._apply_sort()

    # -- sorting -----------------------------------------------------------

    def sort_by(self, col: str) -> None:
        """Sort by `col`, flipping direction if it's already the active one."""
        desc = self._next_desc.get(col, False)
        self._sort_col = col
        self._sort_desc = desc
        self._next_desc[col] = not desc
        self._apply_sort()

    def _apply_sort(self) -> None:
        """Re-sort the live tree by the user's chosen column/direction, so
        toggling reviewed/to_apply doesn't silently revert to DB order."""
        col = self._sort_col
        if not col:
            return
        rows = sorted(
            ((self.tree.set(iid, col), iid) for iid in self.tree.get_children("")),
            key=lambda pair: _sort_key(pair[0]),
            reverse=self._sort_desc,
        )
        for index, (_, iid) in enumerate(rows):
            self.tree.move(iid, "", index)
        self._update_headings()

    def _update_headings(self) -> None:
        """Mark the active sort column with a direction arrow."""
        for key, label, _ in COLUMNS:
            if key == self._sort_col:
                arrow = " ▼" if self._sort_desc else " ▲"
                self.tree.heading(key, text=f"{label}{arrow}")
            else:
                self.tree.heading(key, text=label)
