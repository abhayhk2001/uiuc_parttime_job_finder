"""Top bar: scan/refresh buttons, the search box, filters, status text."""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from jobscanner.ui import theme


class Toolbar(ctk.CTkFrame):
    """Owns the search/filter variables the table reads from."""

    def __init__(
        self,
        master,
        on_scan: Callable[[], None],
        on_refresh: Callable[[], None],
        on_filter_change: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self._on_filter_change = on_filter_change

        self.search_var = ctk.StringVar()
        self.matches_only_var = ctk.BooleanVar(value=False)
        self.status_var = ctk.StringVar(value="Ready.")
        self._toast_seq = 0

        self.run_btn = ctk.CTkButton(
            self, text="▶ Run Scan", width=130, command=on_scan)
        self.run_btn.grid(row=0, column=0, padx=(4, 6), pady=6)

        self.refresh_btn = ctk.CTkButton(
            self, text="↻ Refresh", width=110, command=on_refresh)
        self.refresh_btn.grid(row=0, column=1, padx=6, pady=6)

        ctk.CTkLabel(self, text="Search:").grid(
            row=0, column=2, padx=(14, 4), pady=6)

        self.search_var.trace_add("write", lambda *_: self._on_filter_change())
        self.search_entry = ctk.CTkEntry(
            self, textvariable=self.search_var, width=240)
        self.search_entry.grid(row=0, column=3, padx=4, pady=6)

        ctk.CTkCheckBox(
            self, text="Matches only", variable=self.matches_only_var,
            command=self._on_filter_change,
        ).grid(row=0, column=4, padx=(14, 6), pady=6)

        self.status_label = ctk.CTkLabel(
            self, textvariable=self.status_var, anchor="e",
            text_color=theme.MUTED_TEXT,
        )
        self.status_label.grid(row=0, column=5, sticky="ew", padx=8, pady=6)
        # The status text takes the slack, pinning it to the right edge.
        self.grid_columnconfigure(5, weight=1)

    # -- accessors used by the app -----------------------------------------

    def query(self) -> str:
        return self.search_var.get()

    def matches_only(self) -> bool:
        return self.matches_only_var.get()

    def set_status(self, text: str) -> None:
        self._toast_seq += 1  # cancel any pending toast revert
        self.status_label.configure(text_color=theme.MUTED_TEXT)
        self.status_var.set(text)

    def show_toast(self, text: str, on_expire=None, ms: int = 5000) -> None:
        """Show `text` in the status area for a few seconds, then revert.

        Bulk actions used to confirm themselves with a modal dialog the user
        had to dismiss every time; this replaces that for the non-destructive
        ones.
        """
        self._toast_seq += 1
        seq = self._toast_seq
        self.status_var.set(text)
        self.status_label.configure(text_color=theme.SUCCESS)

        def _expire() -> None:
            # A newer toast (or a plain set_status) supersedes this one, and
            # the window may be gone by the time this fires.
            if seq != self._toast_seq or not self.winfo_exists():
                return
            self.status_label.configure(text_color=theme.MUTED_TEXT)
            if on_expire is not None:
                on_expire()

        self.after(ms, _expire)

    def set_scanning(self, scanning: bool) -> None:
        self.run_btn.configure(
            state="disabled" if scanning else "normal",
            text="Scanning…" if scanning else "▶ Run Scan",
        )

    def focus_search(self) -> None:
        self.search_entry.focus_set()

    def clear_search(self) -> None:
        self.search_var.set("")
