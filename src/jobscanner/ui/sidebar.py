"""Left sidebar: section counters, bulk actions, and the keyword list."""

from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk

from jobscanner import storage as db
from jobscanner.ui import theme

DEFAULT_WIDTH = 240
MIN_WIDTH = 180
MAX_WIDTH = 700

#: Sections shown as their own single-entry block rather than under SECTIONS.
_STANDALONE_BLOCKS = (
    ("TO APPLY", db.SECTION_TO_APPLY),
    ("FOLLOW UP", db.SECTION_FOLLOW_UP),
    ("ARCHIVED", db.SECTION_ARCHIVED),
)

_MAIN_SECTIONS = (db.SECTION_NEW, db.SECTION_OLD, db.SECTION_REVIEWED)

#: (label, section, callable-name on the app) for the bulk-action buttons.
BULK_SPECS: tuple[tuple[str, str], ...] = (
    (db.SECTION_NEW, "Mark all New reviewed"),
    (db.SECTION_OLD, "Mark all Old reviewed"),
    (db.SECTION_REVIEWED, "Revisit all Reviewed"),
    (db.SECTION_TO_APPLY, "Mark all To Apply Applied"),
    (db.SECTION_TO_APPLY, "Unmark all To Apply"),
    (db.SECTION_FOLLOW_UP, "Mark all Follow Up Further"),
    (db.SECTION_FOLLOW_UP, "Archive all Follow Up"),
)


class SectionsPanel(ctk.CTkFrame):
    """Per-section counters + bulk actions + keyword list."""

    SECTION_KEYS = db.COUNTED_SECTIONS
    SECTION_LABELS = db.SECTION_LABELS

    def __init__(
        self,
        master,
        on_select_section: Callable[[str], None],
        on_bulk_action: Callable[[str, str], None],
        on_edit_keywords: Callable[[], None],
    ) -> None:
        super().__init__(master, width=DEFAULT_WIDTH)
        self._on_select_section = on_select_section
        self._on_bulk_action = on_bulk_action
        self._on_edit_keywords = on_edit_keywords

        self.grid_propagate(False)
        self.grid_columnconfigure(0, weight=1)
        self.current_section: str = db.SECTION_NEW
        self._section_buttons: dict[str, ctk.CTkButton] = {}
        self._bulk_buttons: dict[str, ctk.CTkButton] = {}
        self._kw_count_label: Optional[ctk.CTkLabel] = None
        self._kw_list_frame: Optional[ctk.CTkScrollableFrame] = None
        self._build()

    # -- construction ------------------------------------------------------

    def _header(self, text: str, row: int, pady=(0, 4)) -> None:
        ctk.CTkLabel(
            self, text=text, anchor="w",
            font=theme.heading_font(), text_color=theme.MUTED_TEXT,
        ).grid(row=row, column=0, sticky="ew", padx=10, pady=pady)

    def _divider(self, row: int) -> None:
        ctk.CTkFrame(self, height=1, fg_color=theme.DIVIDER).grid(
            row=row, column=0, sticky="ew", padx=10, pady=(12, 4))

    def _section_button(self, section: str, row: int) -> None:
        btn = ctk.CTkButton(
            self, text="", anchor="w", height=32,
            fg_color="transparent",
            text_color=theme.BODY_TEXT,
            hover_color=theme.HOVER_NEUTRAL,
            command=lambda k=section: self._on_select_section(k),
        )
        btn.grid(row=row, column=0, sticky="ew", padx=6, pady=2)
        self._section_buttons[section] = btn

    def _build(self) -> None:
        row = 0
        self._header("SECTIONS", row, pady=(12, 4))
        row += 1
        for section in _MAIN_SECTIONS:
            self._section_button(section, row)
            row += 1

        for label, section in _STANDALONE_BLOCKS:
            self._divider(row)
            row += 1
            self._header(label, row)
            row += 1
            self._section_button(section, row)
            row += 1

        self._divider(row)
        row += 1
        self._header("BULK ACTIONS", row)
        row += 1
        for section, label in BULK_SPECS:
            btn = ctk.CTkButton(
                self, text=label, anchor="w", height=30,
                command=lambda s=section, l=label: self._on_bulk_action(s, l),
            )
            btn.grid(row=row, column=0, sticky="ew", padx=6, pady=2)
            self._bulk_buttons[label] = btn
            row += 1

        self._divider(row)
        row += 1
        self._header("KEYWORDS", row)
        row += 1

        self._kw_count_label = ctk.CTkLabel(
            self, text="0 loaded", anchor="w", text_color=theme.FAINT_TEXT)
        self._kw_count_label.grid(row=row, column=0, sticky="ew",
                                  padx=10, pady=(0, 4))
        row += 1

        ctk.CTkButton(
            self, text="Edit Keywords…", anchor="w", height=30,
            command=self._on_edit_keywords,
        ).grid(row=row, column=0, sticky="ew", padx=6, pady=(0, 4))
        row += 1

        self._kw_list_frame = ctk.CTkScrollableFrame(self, label_text="")
        self._kw_list_frame.grid(row=row, column=0, sticky="nsew",
                                 padx=6, pady=(4, 6))
        self._kw_list_frame.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(row, weight=1)

    # -- state -------------------------------------------------------------

    def set_section(self, key: str) -> None:
        self.current_section = key

    def refresh(self, counts: dict, keywords: list[str]) -> None:
        for key in self.SECTION_KEYS:
            btn = self._section_buttons[key]
            btn.configure(text=f"  {self.SECTION_LABELS[key]}  ({counts[key]})")
            if key == self.current_section:
                btn.configure(fg_color=theme.ACCENT, text_color=("white", "white"))
            else:
                btn.configure(fg_color="transparent", text_color=theme.BODY_TEXT)

        for section, label in BULK_SPECS:
            self._bulk_buttons[label].configure(
                state="normal" if counts.get(section) else "disabled")

        self.refresh_keywords(keywords)

    def refresh_keywords(self, keywords: list[str]) -> None:
        """Re-populate the keyword list with the given items."""
        if self._kw_count_label is not None:
            self._kw_count_label.configure(text=f"{len(keywords)} loaded")
        if self._kw_list_frame is None:
            return
        for widget in self._kw_list_frame.winfo_children():
            widget.destroy()
        if not keywords:
            ctk.CTkLabel(
                self._kw_list_frame, text="(none — Edit Keywords to add)",
                text_color=theme.FAINT_TEXT, anchor="w",
            ).grid(row=0, column=0, sticky="ew", padx=4, pady=2)
            return
        for i, keyword in enumerate(keywords):
            ctk.CTkLabel(
                self._kw_list_frame, text=keyword, anchor="w",
                text_color=theme.KEYWORD_TEXT, font=theme.body_font(),
            ).grid(row=i, column=0, sticky="ew", padx=4, pady=1)
