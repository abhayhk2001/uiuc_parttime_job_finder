"""CustomTkinter GUI for the UIUC Part-Time Job Scanner.

Run via `python gui.py` or invoked automatically by `main.py` after a scan
finishes (unless `--no-gui` is passed).
"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Optional

import customtkinter as ctk
from tkinter import messagebox, ttk

import config
import db
import matcher
import main as scanner_main


COLUMNS: tuple[tuple[str, str, int], ...] = (
    ("job_id", "Job ID", 80),
    ("title", "Title", 380),
    ("company", "Company", 200),
    ("matches", "Matches", 70),
    ("reviewed", "Reviewed", 80),
)

_END = "end"


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


class SectionsPanel(ctk.CTkFrame):
    """Left sidebar: per-section counters + bulk actions + keyword list."""

    SECTION_KEYS = (db.SECTION_NEW, db.SECTION_OLD, db.SECTION_REVIEWED)
    SECTION_LABELS = {
        db.SECTION_NEW: "New",
        db.SECTION_OLD: "Old",
        db.SECTION_REVIEWED: "Reviewed",
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
        ctk.CTkLabel(
            self, text="SECTIONS", anchor="w",
            font=ctk.CTkFont(weight="bold"),
            text_color=("gray40", "gray70"),
        ).grid(row=0, column=0, sticky="ew", padx=10, pady=(12, 4))

        for i, key in enumerate(self.SECTION_KEYS, start=1):
            btn = ctk.CTkButton(
                self, text="", anchor="w", height=32,
                fg_color="transparent",
                text_color=("gray10", "gray90"),
                hover_color=("gray70", "gray30"),
                command=lambda k=key: self.app.select_section(k),
            )
            btn.grid(row=i, column=0, sticky="ew", padx=6, pady=2)
            self._section_buttons[key] = btn

        ctk.CTkFrame(self, height=1).grid(
            row=4, column=0, sticky="ew", padx=10, pady=(12, 4))

        ctk.CTkLabel(
            self, text="BULK ACTIONS", anchor="w",
            font=ctk.CTkFont(weight="bold"),
            text_color=("gray40", "gray70"),
        ).grid(row=5, column=0, sticky="ew", padx=10, pady=(0, 4))

        bulk_specs = (
            (db.SECTION_NEW, "Mark all New reviewed"),
            (db.SECTION_OLD, "Mark all Old reviewed"),
            (db.SECTION_REVIEWED, "Revisit all Reviewed"),
        )
        for i, (key, label) in enumerate(bulk_specs, start=6):
            btn = ctk.CTkButton(
                self, text=label, anchor="w", height=30,
                command=lambda k=key: self.app.bulk_mark_section(k),
            )
            btn.grid(row=i, column=0, sticky="ew", padx=6, pady=2)
            self._bulk_buttons[key] = btn

        # KEYWORDS section — header, count, edit button, scrollable list.
        ctk.CTkFrame(self, height=1).grid(
            row=9, column=0, sticky="ew", padx=10, pady=(12, 4))
        ctk.CTkLabel(
            self, text="KEYWORDS", anchor="w",
            font=ctk.CTkFont(weight="bold"),
            text_color=("gray40", "gray70"),
        ).grid(row=10, column=0, sticky="ew", padx=10, pady=(0, 4))

        self._kw_count_label = ctk.CTkLabel(
            self, text="0 loaded", anchor="w",
            text_color=("gray50", "gray70"),
        )
        self._kw_count_label.grid(row=11, column=0, sticky="ew",
                                  padx=10, pady=(0, 4))

        ctk.CTkButton(
            self, text="Edit Keywords\u2026", anchor="w", height=30,
            command=self.app._open_keyword_editor,
        ).grid(row=12, column=0, sticky="ew", padx=6, pady=(0, 4))

        self._kw_list_frame = ctk.CTkScrollableFrame(self, label_text="")
        self._kw_list_frame.grid(row=13, column=0, sticky="nsew",
                                 padx=6, pady=(4, 6))
        self.grid_rowconfigure(13, weight=1)
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

        self._bulk_buttons[db.SECTION_NEW].configure(
            state="normal" if counts[db.SECTION_NEW] else "disabled")
        self._bulk_buttons[db.SECTION_OLD].configure(
            state="normal" if counts[db.SECTION_OLD] else "disabled")
        self._bulk_buttons[db.SECTION_REVIEWED].configure(
            state="normal" if counts[db.SECTION_REVIEWED] else "disabled")

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

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title("UIUC Part-Time Job Scanner")
        self.geometry("1380x860")
        self.minsize(1080, 640)

        self.grid_columnconfigure(0, weight=0)   # sidebar fixed width
        self.grid_columnconfigure(1, weight=2)   # table
        self.grid_columnconfigure(2, weight=2)   # detail
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
        # Sections sidebar
        self._sections_panel = SectionsPanel(self)
        self._sections_panel.grid(row=1, column=0, sticky="nsew",
                                  padx=(8, 4), pady=4)

        # Table area
        table_frame = ctk.CTkFrame(self)
        table_frame.grid(row=1, column=1, sticky="nsew", padx=(0, 4), pady=4)
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

        # Detail pane
        right = ctk.CTkFrame(self)
        right.grid(row=1, column=2, sticky="nsew", padx=(4, 8), pady=4)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(6, weight=1)

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

        # Mark Reviewed / Revisit on its own line.
        btn_row = ctk.CTkFrame(right, fg_color="transparent")
        btn_row.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 6))
        btn_row.grid_columnconfigure(0, weight=0)
        btn_row.grid_columnconfigure(1, weight=1)
        self.reviewed_var = ctk.BooleanVar(value=False)
        self.reviewed_btn = ctk.CTkButton(
            btn_row, text="\u2713 Mark Reviewed", width=160,
            command=self._on_reviewed_toggle,
        )
        self.reviewed_btn.grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            right, text="Matched keywords", anchor="w",
            font=ctk.CTkFont(weight="bold"),
            text_color=("gray50", "gray70"),
        ).grid(row=4, column=0, sticky="ew", padx=10, pady=(4, 0))
        self.chips_frame = ctk.CTkFrame(right, fg_color="transparent")
        self.chips_frame.grid(row=5, column=0, sticky="ew", padx=10, pady=(0, 6))

        # Detail body sits below chips.
        self.detail_body_holder = ctk.CTkFrame(right, fg_color="transparent")
        self.detail_body_holder.grid(row=6, column=0, sticky="nsew",
                                     padx=10, pady=(4, 10))
        self.detail_body_holder.grid_columnconfigure(0, weight=1)
        self.detail_body_holder.grid_rowconfigure(0, weight=1)

        self._detail_scroll = ctk.CTkScrollableFrame(self.detail_body_holder)
        self._detail_scroll.grid(row=0, column=0, sticky="nsew")
        self._detail_scroll.grid_columnconfigure(0, weight=1)
        self.detail_body = self._detail_scroll

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
        for w in self.chips_frame.winfo_children():
            w.destroy()
        for w in self.detail_body.winfo_children():
            w.destroy()
        self._set_reviewed_button(False)

    # -- sections -------------------------------------------------------

    def select_section(self, section: str) -> None:
        if section not in db.VALID_SECTIONS:
            return
        self.section_var = section
        self._sections_panel.set_section(section)
        self._refresh_table()

    def bulk_mark_section(self, section: str) -> None:
        if section not in (db.SECTION_NEW, db.SECTION_OLD, db.SECTION_REVIEWED):
            return
        # The Reviewed-section action is "Revisit" — i.e. un-mark reviewed.
        is_revisit = section == db.SECTION_REVIEWED
        try:
            n = db.bulk_set_reviewed(section, reviewed=not is_revisit)
        except Exception as exc:
            messagebox.showerror("Bulk update failed", str(exc))
            return
        label = self._sections_panel.SECTION_LABELS[section]
        if is_revisit:
            msg = f"Revisited {n} job(s) (moved from '{label}' back to Old/New)."
        else:
            msg = f"Marked {n} job(s) in '{label}' as reviewed."
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

        # Meta block: company only (First/Last seen are internal).
        company = (job.get("company") or "").strip()
        bits = []
        if company:
            bits.append(f"Company: {company}")
        self.detail_meta.configure(text="\n".join(bits))

        # Reviewed/Revisit button reflects the row's reviewed state
        self._set_reviewed_button(bool(job.get("reviewed")))

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

    def _on_reviewed_toggle(self) -> None:
        if not self._detail_job_id:
            return
        # The button toggles the *current* reviewed state.
        new_val = not bool(self.reviewed_var.get())
        try:
            db.set_reviewed(self._detail_job_id, new_val, self.db_path)
        except Exception as exc:
            messagebox.showerror("Update failed", str(exc))
            return
        self._refresh_table()

    def _set_reviewed_button(self, reviewed: bool) -> None:
        self.reviewed_var.set(bool(reviewed))
        if reviewed:
            self.reviewed_btn.configure(
                text="\u21BB Revisit",
                fg_color=("#9b6b00", "#7a5100"),
                hover_color=("#b07a00", "#8a5e00"),
            )
        else:
            self.reviewed_btn.configure(
                text="\u2713 Mark Reviewed",
                fg_color=("#1f6aa5", "#154a78"),
                hover_color=("#2680c6", "#1a5a90"),
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
