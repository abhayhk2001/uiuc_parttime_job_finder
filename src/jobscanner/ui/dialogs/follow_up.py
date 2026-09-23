"""Popup for editing a job's `follow_up_at`."""

from __future__ import annotations

from tkinter import messagebox

import customtkinter as ctk

from jobscanner import config
from jobscanner import storage as db
from jobscanner.timeutils import add_days_iso, now_iso, parse_iso
from jobscanner.ui import theme


class FollowUpDateEditor(ctk.CTkToplevel):
    """Popup for editing a job's `follow_up_at`. Shows preset offset buttons
    and a custom YYYY-MM-DD entry."""

    PRESETS = (
        (1, "in 1 day"),
        (3, "in 3 days"),
        (7, "in 1 week"),
        (14, "in 2 weeks"),
        (30, "in 1 month"),
        (90, "in 3 months"),
    )

    def __init__(self, master, job_id: str, initial_date: str,
                 on_save=None, db_path=None) -> None:
        super().__init__(master)
        self.title("Edit follow-up date")
        self.geometry("420x320")
        self.minsize(360, 280)
        self.transient(master)
        self.after(50, self.grab_set)

        self._job_id = job_id
        self._on_save_cb = on_save
        self._current_iso = initial_date
        self._db_path = db_path or config.DB_PATH

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(99, weight=1)

        ctk.CTkLabel(
            self, text="Pick a follow-up date",
            anchor="w", font=theme.heading_font(),
        ).grid(row=0, column=0, sticky="ew",
               padx=theme.PAD_LARGE, pady=(theme.PAD_LARGE, 6))

        ctk.CTkLabel(
            self, text="Preset offsets:", anchor="w",
            text_color=theme.MUTED_TEXT,
        ).grid(row=1, column=0, sticky="ew", padx=theme.PAD_LARGE, pady=(4, 2))
        for i, (days, label) in enumerate(self.PRESETS):
            r = 2 + i // 3
            c = i % 3
            ctk.CTkButton(
                self, text=label, width=110, height=28,
                command=lambda d=days: self._apply_offset(d),
            ).grid(row=r, column=0, sticky="ew", padx=theme.PAD_LARGE, pady=2)

        custom_row = 2 + (len(self.PRESETS) + 2) // 3 + 1
        ctk.CTkLabel(
            self, text="Or pick a custom date (YYYY-MM-DD):",
            anchor="w", text_color=theme.MUTED_TEXT,
        ).grid(row=custom_row, column=0, sticky="ew",
               padx=theme.PAD_LARGE, pady=(8, 2))
        self.date_var = ctk.StringVar(value=initial_date or "")
        self.date_entry = ctk.CTkEntry(
            self, textvariable=self.date_var, placeholder_text="YYYY-MM-DD",
            width=200,
        )
        self.date_entry.grid(row=custom_row + 1, column=0, sticky="w",
                             padx=theme.PAD_LARGE, pady=(0, 4))
        ctk.CTkButton(
            self, text="Set custom date", width=200, height=28,
            command=self._apply_custom,
        ).grid(row=custom_row + 2, column=0, sticky="w",
               padx=theme.PAD_LARGE, pady=(0, 6))

        ctk.CTkButton(
            self, text="Close", width=120, height=28,
            command=self.destroy,
        ).grid(row=custom_row + 3, column=0, sticky="w",
               padx=theme.PAD_LARGE, pady=(8, theme.PAD_LARGE))

    def _save(self, iso: str) -> None:
        db.set_follow_up(self._job_id, iso, self._db_path)
        self._current_iso = iso
        if self._on_save_cb:
            self._on_save_cb()
        self.destroy()

    def _apply_offset(self, days: int) -> None:
        self._save(add_days_iso(now_iso(), days))

    def _apply_custom(self) -> None:
        raw = (self.date_var.get() or "").strip()
        dt = parse_iso(raw)
        if dt is None:
            messagebox.showerror(
                "Invalid date",
                f"Couldn't parse '{raw}'. Use YYYY-MM-DD format.",
                parent=self,
            )
            return
        self._save(dt.isoformat(timespec="seconds"))
