"""CustomTkinter GUI for the UIUC Part-Time Job Scanner.

Run via `python gui.py` (root shim) or invoked automatically by the CLI
after a scan finishes (unless `--no-gui` is passed).
"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import customtkinter as ctk
from tkinter import messagebox, ttk

from jobscanner import config
from jobscanner import matching as matcher
from jobscanner import pipeline as scanner_main
from jobscanner import storage as db


COLUMNS: tuple[tuple[str, str, int], ...] = (
    ("job_id", "Job ID", 80),
    ("title", "Title", 380),
    ("company", "Company", 200),
    ("matches", "Matches", 70),
    ("reviewed", "Reviewed", 80),
)

_END = "end"


def _relative_days(iso_ts: str) -> str:
    """Human-friendly relative time, e.g. 'in 7 days', 'today', '5 days ago'."""
    try:
        dt = datetime.fromisoformat(iso_ts)
    except (ValueError, TypeError):
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    delta_days = (dt.date() - now.date()).days
    if delta_days == 0:
        return "today"
    if delta_days == 1:
        return "in 1 day"
    if delta_days > 0:
        return f"in {delta_days} days"
    if delta_days == -1:
        return "1 day ago"
    return f"{abs(delta_days)} days ago"


def _parse_iso_date(s: str) -> Optional[datetime]:
    """Parse a YYYY-MM-DD string into a UTC datetime. Returns None on failure."""
    try:
        # Accept "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM:SS+00:00".
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

class _StreamToQueue:
    """File-like shim that mirrors writes into a queue (so the GUI log can
    display them) while still passing through to the original stream so a
    terminal user still sees output."""

    def __init__(self, q: "queue.Queue[str]", orig) -> None:
        self._q = q
        self._orig = orig

    def write(self, s: str) -> int:
        if s:
            self._q.put(s)
        try:
            self._orig.write(s)
            self._orig.flush()
        except Exception:
            pass
        return len(s)

    def flush(self) -> None:
        try:
            self._orig.flush()
        except Exception:
            pass


class KeywordEditor(ctk.CTkToplevel):
    """Popup window for editing `keywords.json`. Save also triggers a
    re-match pass against the existing DB."""

    def __init__(self, master: "JobScannerApp", keywords_path: Path,
                 on_save=None) -> None:
        super().__init__(master)
        self.title("Edit Keywords")
        self.geometry("480x620")
        self.minsize(360, 420)
        self.keywords_path = keywords_path
        self.on_save = on_save
        self.transient(master)
        self.after(50, self.grab_set)

        self.keywords: list[str] = []
        self._load_from_disk()
        self._build()

    def _load_from_disk(self) -> None:
        if self.keywords_path.exists():
            try:
                with self.keywords_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self.keywords = [str(k).strip() for k in data if str(k).strip()]
                else:
                    self.keywords = []
            except Exception:
                self.keywords = []
        else:
            self.keywords = []

    def _persist(self) -> bool:
        clean: list[str] = []
        seen: set[str] = set()
        for k in self.keywords:
            k = k.strip()
            if not k:
                continue
            kl = k.lower()
            if kl in seen:
                continue
            seen.add(kl)
            clean.append(k)
        tmp = self.keywords_path.with_suffix(self.keywords_path.suffix + ".tmp")
        try:
            tmp.parent.mkdir(parents=True, exist_ok=True)
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(clean, f, indent=2)
            os.replace(tmp, self.keywords_path)
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc), parent=self)
            return False
        self.keywords = clean
        return True

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        body = ctk.CTkFrame(self)
        body.grid(row=0, column=0, sticky="nsew", padx=12, pady=(12, 6))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            body, text="One keyword per line.",
            anchor="w", text_color=("gray40", "gray70"),
        ).grid(row=0, column=0, sticky="ew", padx=4, pady=(0, 4))

        self.textbox = ctk.CTkTextbox(body, activate_scrollbars=True,
                                      font=ctk.CTkFont(family="Menlo", size=12))
        self.textbox.grid(row=1, column=0, sticky="nsew")
        self.textbox.delete("1.0", _END)
        self.textbox.insert("1.0", "\n".join(self.keywords))

        bar = ctk.CTkFrame(self)
        bar.grid(row=1, column=0, sticky="ew", padx=12, pady=(6, 12))
        bar.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(bar, text="Reload", width=100,
                      command=self._reload).grid(row=0, column=1, padx=4)
        ctk.CTkButton(bar, text="Save", width=100,
                      command=self._handle_save).grid(row=0, column=2, padx=4)
        ctk.CTkButton(bar, text="Cancel", width=100,
                      command=self.destroy).grid(row=0, column=3, padx=4)

        hint = ctk.CTkLabel(
            bar, text=f"Saves to {self.keywords_path.name}",
            anchor="w", text_color=("gray40", "gray70"),
        )
        hint.grid(row=0, column=0, sticky="ew", padx=4)

    def _reload(self) -> None:
        self._load_from_disk()
        self.textbox.delete("1.0", _END)
        self.textbox.insert("1.0", "\n".join(self.keywords))

    def _handle_save(self) -> None:
        text = self.textbox.get("1.0", _END)
        self.keywords = [line.strip() for line in text.splitlines() if line.strip()]
        if not self._persist():
            return
        cb = self.on_save
        self.destroy()
        if cb:
            cb(self.keywords)


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

    def __init__(
        self,
        master: "JobScannerApp",
        job_id: str,
        initial_date: str,
        on_save=None,
    ) -> None:
        super().__init__(master)
        self.title("Edit follow-up date")
        self.geometry("420x320")
        self.minsize(360, 280)
        self.transient(master)
        self.after(50, self.grab_set)

        self._job_id = job_id
        self._on_save_cb = on_save
        self._current_iso = initial_date

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(99, weight=1)

        ctk.CTkLabel(
            self, text="Pick a follow-up date",
            anchor="w", font=ctk.CTkFont(weight="bold"),
        ).grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))

        # Preset offset buttons
        ctk.CTkLabel(
            self, text="Preset offsets:", anchor="w",
            text_color=("gray40", "gray70"),
        ).grid(row=1, column=0, sticky="ew", padx=12, pady=(4, 2))
        for i, (days, label) in enumerate(self.PRESETS):
            r = 2 + i // 3
            c = i % 3
            ctk.CTkButton(
                self, text=label, width=110, height=28,
                command=lambda d=days: self._apply_offset(d),
            ).grid(row=r, column=0, sticky="ew", padx=12, pady=2)
            # grid_columnconfigure(0, weight=1) above already; layout fills column

        # Custom date row
        custom_row = 2 + (len(self.PRESETS) + 2) // 3 + 1
        ctk.CTkLabel(
            self, text="Or pick a custom date (YYYY-MM-DD):",
            anchor="w", text_color=("gray40", "gray70"),
        ).grid(row=custom_row, column=0, sticky="ew", padx=12, pady=(8, 2))
        self.date_var = ctk.StringVar(value=initial_date or "")
        self.date_entry = ctk.CTkEntry(
            self, textvariable=self.date_var, placeholder_text="YYYY-MM-DD",
            width=200,
        )
        self.date_entry.grid(row=custom_row + 1, column=0, sticky="w",
                             padx=12, pady=(0, 4))
        ctk.CTkButton(
            self, text="Set custom date", width=200, height=28,
            command=self._apply_custom,
        ).grid(row=custom_row + 2, column=0, sticky="w",
               padx=12, pady=(0, 6))

        # Close
        ctk.CTkButton(
            self, text="Close", width=120, height=28,
            command=self.destroy,
        ).grid(row=custom_row + 3, column=0, sticky="w",
               padx=12, pady=(8, 12))

    def _apply_offset(self, days: int) -> None:
        new_iso = db._add_days_iso(db.now_iso(), days)
        db.set_follow_up(self._job_id, new_iso)
        self._current_iso = new_iso
        self.date_var.set(new_iso[:10])
        if self._on_save_cb:
            self._on_save_cb()
        self.destroy()

    def _apply_custom(self) -> None:
        raw = (self.date_var.get() or "").strip()
        dt = _parse_iso_date(raw)
        if dt is None:
            messagebox.showerror(
                "Invalid date",
                f"Couldn't parse '{raw}'. Use YYYY-MM-DD format.",
                parent=self,
            )
            return
        iso = dt.isoformat(timespec="seconds")
        db.set_follow_up(self._job_id, iso)
        self._current_iso = iso
        if self._on_save_cb:
            self._on_save_cb()
        self.destroy()


class SectionsPanel(ctk.CTkFrame):
    """Left sidebar: per-section counters + bulk actions + keyword list."""

    SECTION_KEYS = (
        db.SECTION_NEW,
        db.SECTION_OLD,
        db.SECTION_REVIEWED,
        db.SECTION_TO_APPLY,
        db.SECTION_FOLLOW_UP,
        db.SECTION_ARCHIVED,
    )
    SECTION_LABELS = {
        db.SECTION_NEW: "New",
        db.SECTION_OLD: "Old",
        db.SECTION_REVIEWED: "Reviewed",
        db.SECTION_TO_APPLY: "To Apply",
        db.SECTION_FOLLOW_UP: "Follow Up",
        db.SECTION_ARCHIVED: "Archived",
    }

    def __init__(self, master: "JobScannerApp") -> None:
        super().__init__(master, width=220)
        self.app = master
        self.grid_propagate(False)
        self.grid_columnconfigure(0, weight=1)
        self.current_section: str = db.SECTION_NEW
        self._section_buttons: dict[str, ctk.CTkButton] = {}
        self._bulk_buttons: dict[str, ctk.CTkButton] = {}
        self._keyword_labels: list[ctk.CTkLabel] = []
        self._kw_count_label: Optional[ctk.CTkLabel] = None
        self._kw_list_frame: Optional[ctk.CTkScrollableFrame] = None
        self._build()

    def _build(self) -> None:
        # SECTIONS block (New / Old / Reviewed — the main three).
        ctk.CTkLabel(
            self, text="SECTIONS", anchor="w",
            font=ctk.CTkFont(weight="bold"),
            text_color=("gray40", "gray70"),
        ).grid(row=0, column=0, sticky="ew", padx=10, pady=(12, 4))

        main_section_keys = (db.SECTION_NEW, db.SECTION_OLD,
                             db.SECTION_REVIEWED)
        for i, key in enumerate(main_section_keys, start=1):
            btn = ctk.CTkButton(
                self, text="", anchor="w", height=32,
                fg_color="transparent",
                text_color=("gray10", "gray90"),
                hover_color=("gray70", "gray30"),
                command=lambda k=key: self.app.select_section(k),
            )
            btn.grid(row=i, column=0, sticky="ew", padx=6, pady=2)
            self._section_buttons[key] = btn

        # Helper to build a "single-selector" block (TO APPLY / FOLLOW UP / ARCHIVED).
        row_cursor = [4]

        def _add_single_block(label: str, section_key: str) -> None:
            r = row_cursor[0]
            ctk.CTkFrame(self, height=1).grid(
                row=r, column=0, sticky="ew", padx=10, pady=(12, 4))
            r += 1
            ctk.CTkLabel(
                self, text=label, anchor="w",
                font=ctk.CTkFont(weight="bold"),
                text_color=("gray40", "gray70"),
            ).grid(row=r, column=0, sticky="ew", padx=10, pady=(0, 4))
            r += 1
            btn = ctk.CTkButton(
                self, text="", anchor="w", height=32,
                fg_color="transparent",
                text_color=("gray10", "gray90"),
                hover_color=("gray70", "gray30"),
                command=lambda k=section_key: self.app.select_section(k),
            )
            btn.grid(row=r, column=0, sticky="ew", padx=6, pady=2)
            self._section_buttons[section_key] = btn
            r += 1
            row_cursor[0] = r

        _add_single_block("TO APPLY", db.SECTION_TO_APPLY)
        _add_single_block("FOLLOW UP", db.SECTION_FOLLOW_UP)
        _add_single_block("ARCHIVED", db.SECTION_ARCHIVED)

        # BULK ACTIONS block.
        r = row_cursor[0]
        ctk.CTkFrame(self, height=1).grid(
            row=r, column=0, sticky="ew", padx=10, pady=(12, 4))
        r += 1
        ctk.CTkLabel(
            self, text="BULK ACTIONS", anchor="w",
            font=ctk.CTkFont(weight="bold"),
            text_color=("gray40", "gray70"),
        ).grid(row=r, column=0, sticky="ew", padx=10, pady=(0, 4))
        r += 1

        bulk_specs = (
            (db.SECTION_NEW, "Mark all New reviewed"),
            (db.SECTION_OLD, "Mark all Old reviewed"),
            (db.SECTION_REVIEWED, "Revisit all Reviewed"),
            (db.SECTION_TO_APPLY, "Mark all To Apply Applied"),
            (db.SECTION_TO_APPLY, "Unmark all To Apply"),
            (db.SECTION_FOLLOW_UP, "Mark all Follow Up Further"),
            (db.SECTION_FOLLOW_UP, "Archive all Follow Up"),
        )
        for key, label in bulk_specs:
            btn = ctk.CTkButton(
                self, text=label, anchor="w", height=30,
                command=lambda k=key, l=label: self.app.bulk_mark_section(k, l),
            )
            btn.grid(row=r, column=0, sticky="ew", padx=6, pady=2)
            self._bulk_buttons[label] = btn
            r += 1

        # KEYWORDS section — header, count, edit button, scrollable list.
        ctk.CTkFrame(self, height=1).grid(
            row=r, column=0, sticky="ew", padx=10, pady=(12, 4))
        r += 1
        ctk.CTkLabel(
            self, text="KEYWORDS", anchor="w",
            font=ctk.CTkFont(weight="bold"),
            text_color=("gray40", "gray70"),
        ).grid(row=r, column=0, sticky="ew", padx=10, pady=(0, 4))
        r += 1

        self._kw_count_label = ctk.CTkLabel(
            self, text="0 loaded", anchor="w",
            text_color=("gray50", "gray70"),
        )
        self._kw_count_label.grid(row=r, column=0, sticky="ew",
                                  padx=10, pady=(0, 4))
        r += 1

        ctk.CTkButton(
            self, text="Edit Keywords\u2026", anchor="w", height=30,
            command=self.app._open_keyword_editor,
        ).grid(row=r, column=0, sticky="ew", padx=6, pady=(0, 4))
        r += 1

        kw_list_row = r
        self._kw_list_frame = ctk.CTkScrollableFrame(self, label_text="")
        self._kw_list_frame.grid(row=kw_list_row, column=0, sticky="nsew",
                                 padx=6, pady=(4, 6))
        self.grid_rowconfigure(kw_list_row, weight=1)
        self._kw_list_frame.grid_columnconfigure(0, weight=1)

    def set_section(self, key: str) -> None:
        self.current_section = key

    def refresh(self) -> None:
        counts = db.get_section_counts(self.app.db_path)
        for key in self.SECTION_KEYS:
            label = self.SECTION_LABELS[key]
            n = counts[key]
            btn = self._section_buttons[key]
            btn.configure(text=f"  {label}  ({n})")
            if key == self.current_section:
                btn.configure(fg_color=("#1f6aa5", "#154a78"))
                btn.configure(text_color=("white", "white"))
            else:
                btn.configure(fg_color="transparent")
                btn.configure(text_color=("gray10", "gray90"))

        self._bulk_buttons["Mark all New reviewed"].configure(
            state="normal" if counts[db.SECTION_NEW] else "disabled")
        self._bulk_buttons["Mark all Old reviewed"].configure(
            state="normal" if counts[db.SECTION_OLD] else "disabled")
        self._bulk_buttons["Revisit all Reviewed"].configure(
            state="normal" if counts[db.SECTION_REVIEWED] else "disabled")
        self._bulk_buttons["Mark all To Apply Applied"].configure(
            state="normal" if counts[db.SECTION_TO_APPLY] else "disabled")
        self._bulk_buttons["Unmark all To Apply"].configure(
            state="normal" if counts[db.SECTION_TO_APPLY] else "disabled")
        self._bulk_buttons["Mark all Follow Up Further"].configure(
            state="normal" if counts[db.SECTION_FOLLOW_UP] else "disabled")
        self._bulk_buttons["Archive all Follow Up"].configure(
            state="normal" if counts[db.SECTION_FOLLOW_UP] else "disabled")

        self.refresh_keywords(matcher.load_keywords(self.app.keywords_path))

    def refresh_keywords(self, keywords: list[str]) -> None:
        """Re-populate the keyword list with the given items."""
        if self._kw_count_label is not None:
            self._kw_count_label.configure(
                text=f"{len(keywords)} loaded")
        if self._kw_list_frame is None:
            return
        for w in self._kw_list_frame.winfo_children():
            w.destroy()
        self._keyword_labels.clear()
        if not keywords:
            ctk.CTkLabel(
                self._kw_list_frame, text="(none — Edit Keywords to add)",
                text_color=("gray50", "gray60"), anchor="w",
            ).grid(row=0, column=0, sticky="ew", padx=4, pady=2)
            return
        for i, kw in enumerate(keywords):
            lbl = ctk.CTkLabel(
                self._kw_list_frame, text=kw, anchor="w",
                text_color=("gray20", "gray85"),
                font=ctk.CTkFont(size=12),
            )
            lbl.grid(row=i, column=0, sticky="ew", padx=4, pady=1)
            self._keyword_labels.append(lbl)


class JobScannerApp(ctk.CTk):

    def __init__(self, db_path: Path, keywords_path: Path) -> None:
        super().__init__()
        self.db_path = db_path
        self.keywords_path = keywords_path
        self.scanning = False
        self._log_q: queue.Queue[str] = queue.Queue()
        self._log_visible = False
        self.section_var: str = db.SECTION_NEW
        self._detail_job_id: Optional[str] = None
        self._current_url: str = ""
        # Per-column sort direction. False=ascending, True=descending.
        # `matches` defaults to descending; everything else is ascending.
        self._sort_state: dict[str, bool] = {key: False for key, _, _ in COLUMNS}
        self._sort_state["matches"] = True
        # Active sort — the column/direction the user most recently chose.
        # Used by _refresh_table to re-apply the sort after rebuilding rows.
        self._active_sort_col: Optional[str] = None
        self._active_sort_desc: bool = False

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title("UIUC Part-Time Job Scanner")
        self.geometry("1380x860")
        self.minsize(1080, 640)

        # Sidebar / sash / table / detail.
        self.grid_columnconfigure(0, weight=0)   # sidebar
        self.grid_columnconfigure(1, weight=0)   # sash
        self.grid_columnconfigure(2, weight=2)   # table
        self.grid_columnconfigure(3, weight=2)   # detail
        self.grid_rowconfigure(1, weight=1)

        self._build_toolbar()
        self._build_body()
        self._build_footer()
        self._style_tree()

        self._refresh_table()
        self._refresh_status()
        self._sections_panel.refresh()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(60, self._drain_log_queue)

    # -- layout ---------------------------------------------------------

    def _build_toolbar(self) -> None:
        bar = ctk.CTkFrame(self)
        bar.grid(row=0, column=0, columnspan=3, sticky="ew",
                 padx=8, pady=(8, 4))
        bar.grid_columnconfigure(4, weight=1)

        self.run_btn = ctk.CTkButton(
            bar, text="\u25B6 Run Scan", width=130, command=self._start_scan)
        self.run_btn.grid(row=0, column=0, padx=(4, 6), pady=6)

        self.refresh_btn = ctk.CTkButton(
            bar, text="\u21BB Refresh", width=110, command=self._refresh_table)
        self.refresh_btn.grid(row=0, column=1, padx=6, pady=6)

        ctk.CTkLabel(bar, text="Search:").grid(row=0, column=2,
                                               padx=(14, 4), pady=6)
        self.search_var = ctk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._refresh_table())
        ctk.CTkEntry(bar, textvariable=self.search_var, width=240).grid(
            row=0, column=3, padx=4, pady=6)

        self.matches_only_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            bar, text="Matches only", variable=self.matches_only_var,
            command=self._refresh_table).grid(row=0, column=5, padx=(14, 6),
                                              pady=6)

        self.status_var = ctk.StringVar(value="Ready.")
        ctk.CTkLabel(
            bar, textvariable=self.status_var, anchor="e",
            text_color=("gray40", "gray70"),
        ).grid(row=0, column=4, sticky="ew", padx=8, pady=6)

    def _build_body(self) -> None:
        # Load persisted sidebar width if any.
        saved = db.get_sash_widths(self.db_path)
        initial_sidebar_width = saved[0] if saved else 240
        self._sidebar_min_width = 180
        self._sidebar_max_width = 700

        # Sections sidebar (resizable).
        self._sections_panel = SectionsPanel(self)
        self._sections_panel.configure(width=initial_sidebar_width)
        self._sections_panel.grid(row=1, column=0, sticky="nsew",
                                  padx=(8, 0), pady=4)

        # Sash column — drag to resize sidebar.
        self._sash = ctk.CTkFrame(
            self, width=4, cursor="sb_h_double_arrow",
            fg_color=("#2a2a2a", "#2a2a2a"),
        )
        self._sash.grid(row=1, column=1, sticky="ns", padx=0, pady=4)
        self._sash.bind("<ButtonPress-1>", self._sash_press)
        self._sash.bind("<B1-Motion>", self._sash_drag)
        self._sash.bind("<Enter>",
                         lambda _e: self._sash.configure(
                             cursor="sb_h_double_arrow"))
        self._sash.bind("<Leave>",
                         lambda _e: self._sash.configure(cursor=""))

        # Table area.
        table_frame = ctk.CTkFrame(self)
        table_frame.grid(row=1, column=2, sticky="nsew", padx=(0, 4), pady=4)
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        cols = [c[0] for c in COLUMNS]
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings")
        for key, label, width in COLUMNS:
            self.tree.heading(
                key, text=label,
                command=lambda k=key: self._sort_by(k),
            )
            anchor = "e" if key in ("job_id", "matches", "reviewed") else "w"
            self.tree.column(key, width=width, anchor=anchor, stretch=True)

        self.tree.tag_configure("match", foreground="#9be29b")
        self.tree.tag_configure("match_reviewed", foreground="#7ea67e")
        self.tree.tag_configure("reviewed", foreground="#7a7a7a")
        self.tree.tag_configure("default", foreground="#d0d0d0")
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<<TreeviewSelect>>", self._on_select_row)

        sb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)

        # Detail pane.
        right = ctk.CTkFrame(self)
        right.grid(row=1, column=3, sticky="nsew", padx=(4, 8), pady=4)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(8, weight=1)

        self.detail_title = ctk.CTkLabel(
            right, text="(select a job)", anchor="w",
            font=ctk.CTkFont(weight="bold", size=15),
            wraplength=440, justify="left",
        )
        self.detail_title.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 2))

        # URL — clickable, on its own line.
        self.detail_url_label = ctk.CTkLabel(
            right, text="", anchor="w",
            text_color=("#7eb6ff", "#7eb6ff"),
            cursor="",
            wraplength=440, justify="left",
        )
        self.detail_url_label.grid(row=1, column=0, sticky="ew",
                                   padx=10, pady=(0, 6))
        self.detail_url_label.bind("<Button-1>", self._open_url)
        self.detail_url_label.bind("<Enter>",
                                   lambda _e: self.detail_url_label.configure(
                                       cursor="hand2"))
        self.detail_url_label.bind("<Leave>",
                                   lambda _e: self.detail_url_label.configure(
                                       cursor=""))

        self.detail_meta = ctk.CTkLabel(
            right, text="", anchor="w", justify="left",
            text_color=("gray30", "gray70"), wraplength=440,
        )
        self.detail_meta.grid(row=2, column=0, sticky="ew",
                              padx=10, pady=(0, 8))

        # Primary action button (context-aware across 5 sections).
        self.reviewed_var = ctk.BooleanVar(value=False)
        self.reviewed_btn = ctk.CTkButton(
            right, text="\u2713 Mark Reviewed", width=180, height=32,
            command=self._on_primary_toggle,
        )
        self.reviewed_btn.grid(row=3, column=0, sticky="w", padx=10, pady=(0, 4))

        # Secondary context-aware button
        # (Add/Remove To Apply | Archive | hidden in Archived).
        self.to_apply_btn = ctk.CTkButton(
            right, text="\u2606 Add to To Apply", width=180, height=28,
            fg_color="transparent",
            text_color=("gray30", "gray85"),
            border_width=1,
            border_color=("gray60", "gray40"),
            hover_color=("gray80", "gray25"),
            command=self._on_secondary_toggle,
        )
        self.to_apply_btn.grid(row=4, column=0, sticky="w",
                               padx=10, pady=(0, 8))

        # Follow-up edit row — only visible for Follow Up section.
        self.follow_up_edit_btn = ctk.CTkButton(
            right, text="", width=240, height=28,
            fg_color="transparent",
            text_color=("gray30", "gray85"),
            border_width=1,
            border_color=("gray60", "gray40"),
            hover_color=("gray80", "gray25"),
            command=self._open_follow_up_editor,
        )
        # Not gridded initially — _populate_detail grid/grid_remove's it.

        ctk.CTkLabel(
            right, text="Matched keywords", anchor="w",
            font=ctk.CTkFont(weight="bold"),
            text_color=("gray50", "gray70"),
        ).grid(row=6, column=0, sticky="ew", padx=10, pady=(4, 0))
        self.chips_frame = ctk.CTkFrame(right, fg_color="transparent")
        self.chips_frame.grid(row=7, column=0, sticky="ew", padx=10, pady=(0, 6))

        # Detail body sits below chips.
        self.detail_body_holder = ctk.CTkFrame(right, fg_color="transparent")
        self.detail_body_holder.grid(row=8, column=0, sticky="nsew",
                                     padx=10, pady=(4, 10))
        self.detail_body_holder.grid_columnconfigure(0, weight=1)
        self.detail_body_holder.grid_rowconfigure(0, weight=1)

        self._detail_scroll = ctk.CTkScrollableFrame(self.detail_body_holder)
        self._detail_scroll.grid(row=0, column=0, sticky="nsew")
        self._detail_scroll.grid_columnconfigure(0, weight=1)
        self.detail_body = self._detail_scroll

    # -- sash (sidebar resize) ------------------------------------------

    def _sash_press(self, event):
        self._drag_start_x = event.x_root
        self._initial_sidebar_width = self._sections_panel.winfo_width()

    def _sash_drag(self, event):
        delta = event.x_root - self._drag_start_x
        new_width = max(
            self._sidebar_min_width,
            min(self._sidebar_max_width,
                self._initial_sidebar_width + delta),
        )
        self._sections_panel.configure(width=new_width)

    def _save_sash_widths(self) -> None:
        try:
            # Use the configured (requested) width rather than winfo_width(),
            # which can be stale before the widget re-renders.
            sidebar_w = self._sections_panel.cget("width") or 0
            sidebar_w = int(sidebar_w)
            # Persist as [sidebar]. Table and detail fill remaining space
            # proportionally — no separate persistence needed.
            db.set_sash_widths([sidebar_w, 0, 0], self.db_path)
        except Exception:
            pass

    def _build_footer(self) -> None:
        footer = ctk.CTkFrame(self)
        footer.grid(row=2, column=0, columnspan=3, sticky="ew",
                    padx=8, pady=(4, 8))
        footer.grid_columnconfigure(0, weight=1)

        self.log_toggle = ctk.CTkButton(
            footer, text="\u25BE Log", width=80, command=self._toggle_log)
        self.log_toggle.grid(row=0, column=1, padx=6, pady=6)

        self.log_frame = ctk.CTkFrame(self)
        self.log = ctk.CTkTextbox(
            self.log_frame, height=160, state="disabled",
            font=ctk.CTkFont(family="Menlo", size=11),
        )
        self.log.pack(fill="both", expand=True, padx=6, pady=6)

    def _style_tree(self) -> None:
        style = ttk.Style(self)
        for theme in ("clam", "alt", "default"):
            try:
                style.theme_use(theme)
                break
            except Exception:
                continue
        bg = "#2b2b2b"
        fg = "#e6e6e6"
        head = "#3a3a3a"
        style.configure(
            "Treeview",
            background=bg,
            fieldbackground=bg,
            foreground=fg,
            bordercolor=bg,
            rowheight=24,
        )
        style.configure(
            "Treeview.Heading",
            background=head,
            foreground=fg,
            relief="flat",
        )
        style.map(
            "Treeview.Heading",
            background=[("active", "#4a4a4a")],
        )
        style.map(
            "Treeview",
            background=[("selected", "#1f6aa5")],
            foreground=[("selected", "#ffffff")],
        )

    # -- table / status -------------------------------------------------

    def _refresh_table(self) -> None:
        try:
            rows = db.get_jobs_by_section(
                section=self.section_var,
                query=self.search_var.get(),
                matches_only=self.matches_only_var.get(),
                path=self.db_path,
            )
        except Exception as exc:
            messagebox.showerror("DB error", f"Could not query DB:\n{exc}")
            return

        # Remember the current selection so we can restore it after rebuild.
        prev_selection = self.tree.selection()

        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for r in rows:
            reviewed = bool(r.get("reviewed"))
            mk = r.get("matched_keywords") or ""
            n = len([k for k in mk.split(",") if k]) if mk else 0

            if reviewed and n:
                tag = "match_reviewed"
            elif reviewed:
                tag = "reviewed"
            elif n:
                tag = "match"
            else:
                tag = "default"

            values = (
                r.get("job_id", ""),
                (r.get("title") or "")[:80],
                (r.get("company") or "")[:35],
                str(n),
                "\u2713" if reviewed else "",
            )
            self.tree.insert("", _END, iid=r.get("job_id", ""),
                             values=values, tags=(tag,))

        # Restore selection if the row is still in the current section
        # (e.g., user marked a row reviewed from the ALL section).
        if prev_selection and prev_selection[0] in self.tree.get_children():
            self.tree.selection_set(prev_selection[0])

        # Re-apply the user's chosen sort so toggling reviewed/to_apply
        # doesn't silently re-sort to DB order.
        self._apply_active_sort()

        self._sections_panel.refresh()
        self._refresh_status()
        self._refresh_detail_for_current_selection()

    def _refresh_status(self) -> None:
        try:
            stats = db.get_stats(self.db_path)
        except Exception:
            self.status_var.set("Ready.")
            return
        self.status_var.set(
            f"{stats['total']} jobs  \u00B7  {stats['matching']} matching  "
            f"\u00B7  {stats['reviewed']} reviewed"
        )

    def _refresh_detail_for_current_selection(self) -> None:
        sel = self.tree.selection()
        if not sel:
            self._clear_detail()
            return
        job = db.get_job(sel[0], self.db_path)
        if job:
            self._populate_detail(job)
        else:
            self._clear_detail()

    def _clear_detail(self) -> None:
        self._detail_job_id = None
        self._current_url = ""
        self.detail_title.configure(text="(select a job)")
        self.detail_url_label.configure(text="")
        self.detail_meta.configure(text="")
        self.follow_up_edit_btn.grid_remove()
        for w in self.chips_frame.winfo_children():
            w.destroy()
        for w in self.detail_body.winfo_children():
            w.destroy()
        self._set_primary_button(to_apply=False, reviewed=False)

    # -- sections -------------------------------------------------------

    def select_section(self, section: str) -> None:
        if section not in db.VALID_SECTIONS:
            return
        self.section_var = section
        self._sections_panel.set_section(section)
        self._refresh_table()

    def bulk_mark_section(self, section: str, label: str = "") -> None:
        """Bulk action dispatcher.

        For New / Old: mark all as reviewed.
        For Reviewed: clear the reviewed flag (Revisit).
        For To Apply: dispatch by label ("Mark all To Apply Applied" /
            "Unmark all To Apply").
        For Follow Up: dispatch by label ("Mark all Follow Up Further" /
            "Archive all Follow Up").
        """
        try:
            if section == db.SECTION_TO_APPLY:
                if "Unmark" in label:
                    n = db.bulk_clear_to_apply()
                    msg = f"Removed {n} job(s) from To Apply."
                else:
                    n = db.bulk_mark_all_applied()
                    msg = (f"Marked {n} job(s) as applied "
                           f"(moved to Follow Up).")
            elif section == db.SECTION_FOLLOW_UP:
                if "Archive" in label:
                    n = db.bulk_archive_section(section)
                    msg = f"Archived {n} job(s) from Follow Up."
                else:
                    n = db.bulk_mark_further_follow_up(section)
                    msg = (f"Reset follow-up date for {n} job(s) "
                           f"to today + "
                           f"{config.FOLLOW_UP_WINDOW_DAYS} days.")
            else:
                is_revisit = section == db.SECTION_REVIEWED
                n = db.bulk_set_reviewed(section, reviewed=not is_revisit)
                section_name = self._sections_panel.SECTION_LABELS[section]
                if is_revisit:
                    msg = (f"Revisited {n} job(s) (moved from "
                           f"'{section_name}' back to Old/New).")
                else:
                    msg = f"Marked {n} job(s) in '{section_name}' as reviewed."
        except Exception as exc:
            messagebox.showerror("Bulk update failed", str(exc))
            return
        messagebox.showinfo("Done", msg)
        self._refresh_table()

    # -- detail panel ---------------------------------------------------

    def _on_select_row(self, _event=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        job = db.get_job(sel[0], self.db_path)
        if job:
            self._populate_detail(job)

    def _populate_detail(self, job: dict) -> None:
        self._detail_job_id = job.get("job_id")
        title = (job.get("title") or job.get("job_title") or "").strip() \
            or "(no title)"
        self.detail_title.configure(
            text=f"{title}  \u00B7  #{job.get('job_id', '')}"
        )

        # URL on its own line; clickable.
        url = (job.get("detail_url") or "").strip()
        self._current_url = url
        self.detail_url_label.configure(text=url)

        # Meta block: company + applied / follow-up / archived info.
        company = (job.get("company") or "").strip()
        bits = []
        if company:
            bits.append(f"Company: {company}")
        applied_at = (job.get("applied_at") or "").strip()
        follow_up_at = (job.get("follow_up_at") or "").strip()
        archived = bool(job.get("archived"))
        archived_at = (job.get("archived_at") or "").strip()

        if applied_at:
            bits.append(f"Applied: {applied_at}")
        if follow_up_at:
            rel = _relative_days(follow_up_at)
            bits.append(f"Follow up: {follow_up_at}  ({rel})")
        if archived and archived_at:
            bits.append(f"Archived: {archived_at}")
        self.detail_meta.configure(text="\n".join(bits))

        # Context-aware buttons across New / Old / Reviewed / To Apply / Follow Up / Archived.
        self._set_primary_button(
            to_apply=bool(job.get("to_apply")),
            reviewed=bool(job.get("reviewed")),
            applied=bool(applied_at),
            archived=archived,
        )

        # Show the follow-up date edit button only for Follow Up rows.
        if applied_at and not archived:
            pretty = follow_up_at[:10] if follow_up_at else "—"
            self.follow_up_edit_btn.configure(
                text=f"\u270E  Edit follow-up date ({pretty})"
            )
            self.follow_up_edit_btn.grid(
                row=5, column=0, sticky="w",
                padx=10, pady=(0, 6),
            )
        else:
            self.follow_up_edit_btn.grid_remove()

        # Matched-keyword chips
        for w in self.chips_frame.winfo_children():
            w.destroy()
        mk = (job.get("matched_keywords") or "").strip()
        if mk:
            for kw in [k.strip() for k in mk.split(",") if k.strip()]:
                ctk.CTkLabel(
                    self.chips_frame, text=kw,
                    fg_color="#1f6aa5", corner_radius=10, text_color="white",
                ).pack(side="left", padx=(0, 4), pady=2)
        else:
            ctk.CTkLabel(
                self.chips_frame, text="(no keyword match)",
                text_color=("gray50", "gray60"),
            ).pack(side="left")

        # Description / Requirements / Skills body
        for w in self.detail_body.winfo_children():
            w.destroy()
        sections = [
            ("Description", job.get("job_description", "")),
            ("Requirements", job.get("requirements", "")),
            ("Skills", job.get("skills", "")),
        ]
        for label, content in sections:
            ctk.CTkLabel(
                self.detail_body, text=label, anchor="w",
                font=ctk.CTkFont(weight="bold"),
            ).pack(fill="x", padx=2, pady=(8, 2))
            text = (content or "").strip() or "(empty)"
            ctk.CTkLabel(
                self.detail_body, text=text, anchor="w", justify="left",
                wraplength=380,
            ).pack(fill="x", padx=2, pady=(0, 8))

    def _open_url(self, _event=None) -> None:
        url = self._current_url
        if url.startswith(("http://", "https://")):
            try:
                webbrowser.open(url)
            except Exception as exc:
                messagebox.showerror("Open URL failed", str(exc),
                                     parent=self)

    def _open_follow_up_editor(self) -> None:
        """Open the date-edit Toplevel for the currently selected job.

        Shown only for Follow Up rows (i.e. ``applied_at IS NOT NULL AND NOT archived``).
        """
        if not self._detail_job_id:
            return
        current = db.get_job(self._detail_job_id, self.db_path) or {}
        if not current.get("applied_at") or current.get("archived"):
            return
        initial = (current.get("follow_up_at") or "")[:10]  # YYYY-MM-DD
        FollowUpDateEditor(self, self._detail_job_id, initial,
                           on_save=self._refresh_table)

    def _on_primary_toggle(self) -> None:
        if not self._detail_job_id:
            return
        try:
            current = db.get_job(self._detail_job_id, self.db_path) or {}
            applied = bool(current.get("applied_at"))
            archived = bool(current.get("archived"))
            to_apply = bool(current.get("to_apply"))
            reviewed = bool(current.get("reviewed"))

            if to_apply:
                db.mark_applied(self._detail_job_id, self.db_path)
            elif applied and not archived:
                # Follow Up section.
                db.mark_further_follow_up(self._detail_job_id,
                                           path=self.db_path)
            elif archived:
                # Archived section.
                db.unarchive_job(self._detail_job_id, self.db_path)
            else:
                # New / Old / Reviewed.
                db.set_reviewed(
                    self._detail_job_id,
                    not reviewed,
                    self.db_path,
                )
        except Exception as exc:
            messagebox.showerror("Update failed", str(exc))
            return
        self._refresh_table()

    def _on_secondary_toggle(self) -> None:
        """Context-aware secondary button:
          - To Apply job → remove from To Apply
          - Follow Up job → archive
          - Archived job → hidden / disabled
          - Reviewed job → disabled (can't re-add reviewed to To Apply)
          - New / Old job → toggle To Apply
        """
        if not self._detail_job_id:
            return
        try:
            current = db.get_job(self._detail_job_id, self.db_path) or {}
            applied = bool(current.get("applied_at"))
            archived = bool(current.get("archived"))
            to_apply = bool(current.get("to_apply"))
            reviewed = bool(current.get("reviewed"))

            if to_apply:
                db.set_to_apply(self._detail_job_id, False, self.db_path)
            elif applied and not archived:
                db.archive_job(self._detail_job_id, self.db_path)
            elif archived:
                return  # disabled
            elif reviewed:
                return  # disabled
            else:
                db.set_to_apply(
                    self._detail_job_id,
                    not to_apply,
                    self.db_path,
                )
        except Exception as exc:
            messagebox.showerror("Update failed", str(exc))
            return
        self._refresh_table()

    def _set_primary_button(
        self,
        to_apply: bool,
        reviewed: bool,
        applied: bool = False,
        archived: bool = False,
    ) -> None:
        self.reviewed_var.set(bool(reviewed))
        if archived:
            self.reviewed_btn.configure(
                text="\u21A9 Unarchive",
                fg_color=("#1f6aa5", "#154a78"),
                hover_color=("#2680c6", "#1a5a90"),
                state="normal",
            )
            self.to_apply_btn.configure(state="disabled")
        elif applied:
            self.reviewed_btn.configure(
                text="\u21BB Mark Further Follow Up",
                fg_color=("#0d8050", "#0a6640"),
                hover_color=("#11965e", "#0d7a4a"),
                state="normal",
            )
            self.to_apply_btn.configure(
                text="\u2605 Archive",
                state="normal",
            )
        elif to_apply:
            self.reviewed_btn.configure(
                text="\u2713 Mark Applied",
                fg_color=("#0d8050", "#0a6640"),
                hover_color=("#11965e", "#0d7a4a"),
                state="normal",
            )
            self.to_apply_btn.configure(
                text="\u2605 Remove from To Apply",
                state="normal",
            )
        elif reviewed:
            self.reviewed_btn.configure(
                text="\u21BB Revisit",
                fg_color=("#9b6b00", "#7a5100"),
                hover_color=("#b07a00", "#8a5e00"),
                state="normal",
            )
            self.to_apply_btn.configure(
                text="\u2606 Add to To Apply",
                state="disabled",
            )
        else:
            self.reviewed_btn.configure(
                text="\u2713 Mark Reviewed",
                fg_color=("#1f6aa5", "#154a78"),
                hover_color=("#2680c6", "#1a5a90"),
                state="normal",
            )
            self.to_apply_btn.configure(
                text="\u2606 Add to To Apply",
                state="normal",
            )

    def _sort_by(self, col: str) -> None:
        rows = [(self.tree.set(iid, col), iid)
                for iid in self.tree.get_children("")]

        def _key(t):
            try:
                return (0, int(t[0]))
            except (ValueError, TypeError):
                return (1, (t[0] or "").lower())

        reverse = self._sort_state.get(col, False)
        rows.sort(key=_key, reverse=reverse)
        for i, (_, iid) in enumerate(rows):
            self.tree.move(iid, "", i)
        # Toggle for the next click of the same column.
        self._sort_state[col] = not reverse
        # Track active sort so _refresh_table can re-apply it after rebuild.
        self._active_sort_col = col
        self._active_sort_desc = reverse

    def _apply_active_sort(self) -> None:
        """Re-sort the live tree by the user's last-chosen column/direction.

        Used by `_refresh_table` so toggling reviewed/to_apply preserves
        the sort the user explicitly picked.
        """
        col = self._active_sort_col
        if not col:
            return
        rows = [(self.tree.set(iid, col), iid)
                for iid in self.tree.get_children("")]

        def _key(t):
            try:
                return (0, int(t[0]))
            except (ValueError, TypeError):
                return (1, (t[0] or "").lower())

        rows.sort(key=_key, reverse=self._active_sort_desc)
        for i, (_, iid) in enumerate(rows):
            self.tree.move(iid, "", i)

    # -- scan -----------------------------------------------------------

    def _start_scan(self) -> None:
        if self.scanning:
            return
        self.scanning = True
        self.run_btn.configure(state="disabled", text="Scanning\u2026")
        self.status_var.set("Scanning\u2026")
        threading.Thread(target=self._run_scan_thread, daemon=True).start()

    def _run_scan_thread(self) -> None:
        orig_out, orig_err = sys.stdout, sys.stderr
        sys.stdout = _StreamToQueue(self._log_q, orig_out)
        sys.stderr = _StreamToQueue(self._log_q, orig_err)
        try:
            scanner_main.run(dry_run=False, verbose=False, fetch_missing=True)
        except Exception as exc:
            print(f"[gui] scan failed: {exc}", file=sys.stderr)
        finally:
            sys.stdout, sys.stderr = orig_out, orig_err
            self._log_q.put("__SCAN_DONE__")

    def _drain_log_queue(self) -> None:
        try:
            while True:
                item = self._log_q.get_nowait()
                if item == "__SCAN_DONE__":
                    self._scan_finished()
                else:
                    self._append_log(item)
        except queue.Empty:
            pass
        self.after(80, self._drain_log_queue)

    def _append_log(self, text: str) -> None:
        if not self._log_visible:
            return
        self.log.configure(state="normal")
        self.log.insert(_END, text)
        self.log.see(_END)
        self.log.configure(state="disabled")

    def _scan_finished(self) -> None:
        self.scanning = False
        self.run_btn.configure(state="normal", text="\u25B6 Run Scan")
        self._refresh_table()
        self._refresh_status()
        self._sections_panel.refresh()
        try:
            stats = db.get_stats(self.db_path)
            self.status_var.set(
                f"Scan complete \u00B7 {stats['total']} jobs "
                f"\u00B7 {stats['matching']} matching "
                f"\u00B7 {stats['reviewed']} reviewed"
            )
        except Exception:
            pass

    # -- log toggle -----------------------------------------------------

    def _toggle_log(self) -> None:
        self._log_visible = not self._log_visible
        if self._log_visible:
            self.log_frame.grid(row=3, column=0, columnspan=3, sticky="ew",
                                 padx=8, pady=(0, 4))
            self.log_toggle.configure(text="\u25B4 Log")
        else:
            self.log_frame.grid_forget()
            self.log_toggle.configure(text="\u25BE Log")

    # -- keyword editor -------------------------------------------------

    def _open_keyword_editor(self) -> None:
        def _on_save(new_keywords: list[str]) -> None:
            try:
                n = matcher.rematch_all(new_keywords)
                self._append_log(
                    f"[gui] re-matched {n} job(s) against updated keywords\n"
                )
            except Exception as exc:
                messagebox.showerror("Re-match failed", str(exc))
            self._refresh_table()

        KeywordEditor(self, self.keywords_path, on_save=_on_save)

    # -- close ----------------------------------------------------------

    def _on_close(self) -> None:
        self._save_sash_widths()
        self.destroy()


def launch(db_path: Optional[Path] = None,
           keywords_path: Optional[Path] = None) -> None:
    """Build the app and run its mainloop. Safe to call from anywhere."""
    db_path = Path(db_path) if db_path else config.DB_PATH
    keywords_path = Path(keywords_path) if keywords_path else config.KEYWORDS_PATH
    try:
        db.init_db(db_path)
    except Exception as exc:
        print(f"[gui] could not init db at {db_path}: {exc}", file=sys.stderr)
    JobScannerApp(db_path, keywords_path).mainloop()


if __name__ == "__main__":
    launch()
