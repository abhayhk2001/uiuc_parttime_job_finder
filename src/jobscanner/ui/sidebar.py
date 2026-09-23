"""Left sidebar: section counters, bulk actions, and the keyword list.

Collapses to a narrow rail that keeps the section counts visible, so the
table and detail pane can have the width when you're reading postings.
"""

from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk

from jobscanner import storage as db
from jobscanner.ui import theme

DEFAULT_WIDTH = db.DEFAULT_LAYOUT["sidebar_width"]
MIN_WIDTH = 180
MAX_WIDTH = 700
COLLAPSED_WIDTH = 58

_MAIN_SECTIONS = (db.SECTION_NEW, db.SECTION_OLD, db.SECTION_REVIEWED)

#: Sections shown as their own single-entry block rather than under SECTIONS.
_STANDALONE_BLOCKS = (
    ("TO APPLY", db.SECTION_TO_APPLY),
    ("FOLLOW UP", db.SECTION_FOLLOW_UP),
    ("ARCHIVED", db.SECTION_ARCHIVED),
)

#: Short labels for the collapsed rail.
_RAIL_LABELS = {
    db.SECTION_NEW: "New",
    db.SECTION_OLD: "Old",
    db.SECTION_REVIEWED: "Rev",
    db.SECTION_TO_APPLY: "App",
    db.SECTION_FOLLOW_UP: "F/U",
    db.SECTION_ARCHIVED: "Arc",
}

#: (section, button label) for the bulk-action buttons.
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
        on_toggle_collapsed: Optional[Callable[[bool], None]] = None,
        width: int = DEFAULT_WIDTH,
        collapsed: bool = False,
    ) -> None:
        super().__init__(master, width=width)
        self._on_select_section = on_select_section
        self._on_bulk_action = on_bulk_action
        self._on_edit_keywords = on_edit_keywords
        self._on_toggle_collapsed = on_toggle_collapsed

        self.grid_propagate(False)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.collapsed = False
        self.expanded_width = max(MIN_WIDTH, min(MAX_WIDTH, width))
        self.current_section: str = db.SECTION_NEW
        self._section_buttons: dict[str, ctk.CTkButton] = {}
        self._rail_buttons: dict[str, ctk.CTkButton] = {}
        self._bulk_buttons: dict[str, ctk.CTkButton] = {}
        self._kw_count_label: Optional[ctk.CTkLabel] = None
        self._kw_list_frame: Optional[ctk.CTkScrollableFrame] = None

        self._build_header()
        self._content = ctk.CTkFrame(self, fg_color="transparent")
        self._content.grid_columnconfigure(0, weight=1)
        self._rail = ctk.CTkFrame(self, fg_color="transparent")
        self._rail.grid_columnconfigure(0, weight=1)
        self._build_content()
        self._build_rail()
        self.set_collapsed(collapsed, notify=False)

    # -- construction ------------------------------------------------------

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=4, pady=(8, 0))
        header.grid_columnconfigure(0, weight=1)
        self._collapse_btn = ctk.CTkButton(
            header, text="«", width=28, height=24,
            fg_color="transparent", text_color=theme.MUTED_TEXT,
            hover_color=theme.HOVER_NEUTRAL,
            command=self.toggle_collapsed,
        )
        self._collapse_btn.grid(row=0, column=1, sticky="e", padx=2)

    def _header_label(self, parent, text: str, row: int, pady=(0, 4)) -> None:
        ctk.CTkLabel(
            parent, text=text, anchor="w",
            font=theme.heading_font(), text_color=theme.MUTED_TEXT,
        ).grid(row=row, column=0, sticky="ew", padx=10, pady=pady)

    def _divider(self, parent, row: int) -> None:
        ctk.CTkFrame(parent, height=1, fg_color=theme.DIVIDER).grid(
            row=row, column=0, sticky="ew", padx=10, pady=(12, 4))

    def _section_button(self, parent, section: str, row: int) -> None:
        btn = ctk.CTkButton(
            parent, text="", anchor="w", height=32,
            fg_color="transparent",
            text_color=theme.BODY_TEXT,
            hover_color=theme.HOVER_NEUTRAL,
            command=lambda k=section: self._on_select_section(k),
        )
        btn.grid(row=row, column=0, sticky="ew", padx=6, pady=2)
        self._section_buttons[section] = btn

    def _build_content(self) -> None:
        parent = self._content
        row = 0
        self._header_label(parent, "SECTIONS", row, pady=(4, 4))
        row += 1
        for section in _MAIN_SECTIONS:
            self._section_button(parent, section, row)
            row += 1

        for label, section in _STANDALONE_BLOCKS:
            self._divider(parent, row)
            row += 1
            self._header_label(parent, label, row)
            row += 1
            self._section_button(parent, section, row)
            row += 1

        self._divider(parent, row)
        row += 1
        self._header_label(parent, "BULK ACTIONS", row)
        row += 1
        for section, label in BULK_SPECS:
            btn = ctk.CTkButton(
                parent, text=label, anchor="w", height=30,
                command=lambda s=section, l=label: self._on_bulk_action(s, l),
            )
            btn.grid(row=row, column=0, sticky="ew", padx=6, pady=2)
            self._bulk_buttons[label] = btn
            row += 1

        self._divider(parent, row)
        row += 1
        self._header_label(parent, "KEYWORDS", row)
        row += 1

        self._kw_count_label = ctk.CTkLabel(
            parent, text="0 loaded", anchor="w", text_color=theme.FAINT_TEXT)
        self._kw_count_label.grid(row=row, column=0, sticky="ew",
                                  padx=10, pady=(0, 4))
        row += 1

        ctk.CTkButton(
            parent, text="Edit Keywords…", anchor="w", height=30,
            command=self._on_edit_keywords,
        ).grid(row=row, column=0, sticky="ew", padx=6, pady=(0, 4))
        row += 1

        self._kw_list_frame = ctk.CTkScrollableFrame(parent, label_text="")
        self._kw_list_frame.grid(row=row, column=0, sticky="nsew",
                                 padx=6, pady=(4, 6))
        self._kw_list_frame.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(row, weight=1)

    def _build_rail(self) -> None:
        """Compact stand-in shown while collapsed: short label + count."""
        for row, section in enumerate(self.SECTION_KEYS):
            btn = ctk.CTkButton(
                self._rail, text=_RAIL_LABELS[section], height=40,
                font=theme.body_font(11),
                fg_color="transparent",
                text_color=theme.BODY_TEXT,
                hover_color=theme.HOVER_NEUTRAL,
                command=lambda k=section: self._on_select_section(k),
            )
            btn.grid(row=row, column=0, sticky="ew", padx=3, pady=2)
            self._rail_buttons[section] = btn

    # -- collapse ----------------------------------------------------------

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self.collapsed)

    def set_collapsed(self, collapsed: bool, notify: bool = True) -> None:
        if collapsed == self.collapsed and notify:
            return
        self.collapsed = collapsed
        if collapsed:
            self._content.grid_remove()
            self._rail.grid(row=1, column=0, sticky="nsew", pady=(4, 6))
            self.configure(width=COLLAPSED_WIDTH)
            self._collapse_btn.configure(text="»")
        else:
            self._rail.grid_remove()
            self._content.grid(row=1, column=0, sticky="nsew")
            self.configure(width=self.expanded_width)
            self._collapse_btn.configure(text="«")
        if notify and self._on_toggle_collapsed is not None:
            self._on_toggle_collapsed(collapsed)

    def set_expanded_width(self, width: int) -> None:
        """Set the width used when expanded (and apply it if expanded now)."""
        self.expanded_width = max(MIN_WIDTH, min(MAX_WIDTH, width))
        if not self.collapsed:
            self.configure(width=self.expanded_width)

    # -- state -------------------------------------------------------------

    def set_section(self, key: str) -> None:
        self.current_section = key

    def refresh(self, counts: dict, keywords: list[str]) -> None:
        for key in self.SECTION_KEYS:
            active = key == self.current_section
            count = counts.get(key, 0)

            btn = self._section_buttons[key]
            btn.configure(text=f"  {self.SECTION_LABELS[key]}  ({count})")
            rail_btn = self._rail_buttons[key]
            rail_btn.configure(text=f"{_RAIL_LABELS[key]}\n{count}")
            for widget in (btn, rail_btn):
                if active:
                    widget.configure(fg_color=theme.ACCENT,
                                     text_color=("white", "white"))
                else:
                    widget.configure(fg_color="transparent",
                                     text_color=theme.BODY_TEXT)

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
