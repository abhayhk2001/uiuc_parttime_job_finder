"""The main application window.

Run via `python gui.py` (root shim) or invoked automatically by the CLI
after a scan finishes (unless `--no-gui` is passed).

The window owns four children -- toolbar, sidebar, table, detail pane --
plus a collapsible log console. Each lives in its own module; this file is
the wiring and the scan thread.
"""

from __future__ import annotations

import queue
import sys
import threading
from pathlib import Path
from tkinter import messagebox
from typing import Optional

import customtkinter as ctk

from jobscanner import config
from jobscanner import matching
from jobscanner import pipeline
from jobscanner import storage as db
from jobscanner.ui import sidebar as sidebar_mod
from jobscanner.ui import job_actions, theme
from jobscanner.ui.detail_pane import DetailPane
from jobscanner.ui.dialogs.follow_up import FollowUpDateEditor
from jobscanner.ui.dialogs.keywords import KeywordEditor
from jobscanner.ui.jobs_table import JobsTable
from jobscanner.ui.log_console import LogConsole, StreamToQueue
from jobscanner.ui.sash import Sash

_SCAN_DONE = "__SCAN_DONE__"

# Root grid columns.
_COL_SIDEBAR = 0
_COL_SASH = 1
_COL_TABLE = 2
_COL_DETAIL = 3
_COL_COUNT = 4


class JobScannerApp(ctk.CTk):
    def __init__(self, db_path: Path, keywords_path: Path) -> None:
        super().__init__()
        self.db_path = db_path
        self.keywords_path = keywords_path
        self.scanning = False
        self._log_q: "queue.Queue[str]" = queue.Queue()
        self._log_visible = False
        self.section_var: str = db.SECTION_NEW

        theme.apply_appearance()
        self.title("UIUC Part-Time Job Scanner")
        self.geometry("1380x860")
        self.minsize(1080, 640)

        self.grid_columnconfigure(_COL_SIDEBAR, weight=0)
        self.grid_columnconfigure(_COL_SASH, weight=0)
        self.grid_columnconfigure(_COL_TABLE, weight=2)
        self.grid_columnconfigure(_COL_DETAIL, weight=2)
        self.grid_rowconfigure(1, weight=1)

        self._build_toolbar()
        self._build_body()
        self._build_footer()

        self.refresh()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(60, self._drain_log_queue)

    # -- layout ------------------------------------------------------------

    def _build_toolbar(self) -> None:
        from jobscanner.ui.toolbar import Toolbar

        self.toolbar = Toolbar(
            self,
            on_scan=self._start_scan,
            on_refresh=self.refresh,
            on_filter_change=self.refresh,
        )
        self.toolbar.grid(row=0, column=0, columnspan=_COL_COUNT,
                          sticky="ew", padx=theme.PAD, pady=(theme.PAD, 4))

    def _build_body(self) -> None:
        saved = db.get_sash_widths(self.db_path)
        self._sidebar_width = saved[0] if saved else sidebar_mod.DEFAULT_WIDTH

        self.sections_panel = sidebar_mod.SectionsPanel(
            self,
            on_select_section=self.select_section,
            on_bulk_action=self.bulk_mark_section,
            on_edit_keywords=self._open_keyword_editor,
        )
        self.sections_panel.configure(width=self._sidebar_width)
        self.sections_panel.grid(row=1, column=_COL_SIDEBAR, sticky="nsew",
                                 padx=(theme.PAD, 0), pady=4)

        self._sash = Sash(
            self, on_drag=self._drag_sidebar, on_release=self._save_layout)
        self._sash.grid(row=1, column=_COL_SASH, sticky="ns", pady=4)

        self.jobs_table = JobsTable(self, on_select=self._on_select_row)
        self.jobs_table.grid(row=1, column=_COL_TABLE, sticky="nsew",
                             padx=(0, 4), pady=4)

        self.detail = DetailPane(
            self,
            on_action=self._run_job_op,
            on_edit_follow_up=self._open_follow_up_editor,
        )
        self.detail.grid(row=1, column=_COL_DETAIL, sticky="nsew",
                         padx=(4, theme.PAD), pady=4)

    def _build_footer(self) -> None:
        footer = ctk.CTkFrame(self)
        footer.grid(row=2, column=0, columnspan=_COL_COUNT, sticky="ew",
                    padx=theme.PAD, pady=(4, theme.PAD))
        footer.grid_columnconfigure(0, weight=1)

        self.log_toggle = ctk.CTkButton(
            footer, text="▾ Log", width=80, command=self._toggle_log)
        self.log_toggle.grid(row=0, column=1, padx=6, pady=6)

        self.log_console = LogConsole(self)

    # -- sidebar resize ----------------------------------------------------

    def _drag_sidebar(self, delta: int) -> None:
        width = max(sidebar_mod.MIN_WIDTH,
                    min(sidebar_mod.MAX_WIDTH, self._sidebar_width + delta))
        self.sections_panel.configure(width=width)

    def _save_layout(self) -> None:
        try:
            # The configured (requested) width, not winfo_width(), which can
            # be stale before the widget re-renders.
            self._sidebar_width = int(self.sections_panel.cget("width") or 0)
            # Table and detail fill the remaining space proportionally, so
            # only the sidebar needs persisting.
            db.set_sash_widths([self._sidebar_width, 0, 0], self.db_path)
        except Exception:
            pass

    # -- refresh -----------------------------------------------------------

    def refresh(self) -> None:
        """Re-query the current section and rebuild every dependent view."""
        try:
            rows = db.get_jobs_by_section(
                section=self.section_var,
                query=self.toolbar.query(),
                matches_only=self.toolbar.matches_only(),
                path=self.db_path,
            )
        except Exception as exc:
            messagebox.showerror("DB error", f"Could not query DB:\n{exc}")
            return

        self.jobs_table.populate(rows)
        self.sections_panel.refresh(
            db.get_section_counts(self.db_path),
            matching.load_keywords(self.keywords_path),
        )
        self._refresh_status()
        self._on_select_row(self.jobs_table.selected_id())

    def _refresh_status(self, prefix: str = "") -> None:
        try:
            stats = db.get_stats(self.db_path)
        except Exception:
            self.toolbar.set_status("Ready.")
            return
        self.toolbar.set_status(
            f"{prefix}{stats['total']} jobs  ·  {stats['matching']} matching  "
            f"·  {stats['reviewed']} reviewed"
        )

    # -- sections ----------------------------------------------------------

    def select_section(self, section: str) -> None:
        if section not in db.VALID_SECTIONS:
            return
        self.section_var = section
        self.sections_panel.set_section(section)
        self.refresh()

    def bulk_mark_section(self, section: str, label: str = "") -> None:
        """Bulk action dispatcher.

        For New / Old: mark all as reviewed.
        For Reviewed: clear the reviewed flag (Revisit).
        For To Apply / Follow Up: dispatch by label.
        """
        try:
            if section == db.SECTION_TO_APPLY:
                if "Unmark" in label:
                    n = db.bulk_clear_to_apply(self.db_path)
                    msg = f"Removed {n} job(s) from To Apply."
                else:
                    n = db.bulk_mark_all_applied(self.db_path)
                    msg = f"Marked {n} job(s) as applied (moved to Follow Up)."
            elif section == db.SECTION_FOLLOW_UP:
                if "Archive" in label:
                    n = db.bulk_archive_section(section, self.db_path)
                    msg = f"Archived {n} job(s) from Follow Up."
                else:
                    n = db.bulk_mark_further_follow_up(section,
                                                       path=self.db_path)
                    msg = (f"Reset follow-up date for {n} job(s) to today + "
                           f"{config.FOLLOW_UP_WINDOW_DAYS} days.")
            else:
                is_revisit = section == db.SECTION_REVIEWED
                n = db.bulk_set_reviewed(section, not is_revisit, self.db_path)
                name = db.SECTION_LABELS[section]
                if is_revisit:
                    msg = (f"Revisited {n} job(s) (moved from "
                           f"'{name}' back to Old/New).")
                else:
                    msg = f"Marked {n} job(s) in '{name}' as reviewed."
        except Exception as exc:
            messagebox.showerror("Bulk update failed", str(exc))
            return
        messagebox.showinfo("Done", msg)
        self.refresh()

    # -- detail ------------------------------------------------------------

    def _on_select_row(self, job_id: Optional[str]) -> None:
        job = db.get_job(job_id, self.db_path) if job_id else None
        if job:
            self.detail.show(job)
        else:
            self.detail.clear()

    def _run_job_op(self, op: Optional[str]) -> None:
        """Run a primary/secondary detail-pane action on the selected job."""
        job_id = self.detail.job_id
        if not op or not job_id:
            return
        try:
            job_actions.apply_op(op, job_id, self.db_path)
        except Exception as exc:
            messagebox.showerror("Update failed", str(exc))
            return
        self.refresh()

    def _open_follow_up_editor(self) -> None:
        """Open the date editor. Only reachable for Follow Up rows."""
        job_id = self.detail.job_id
        if not job_id:
            return
        job = db.get_job(job_id, self.db_path) or {}
        if not job.get("applied_at") or job.get("archived"):
            return
        FollowUpDateEditor(
            self, job_id, (job.get("follow_up_at") or "")[:10],
            on_save=self.refresh, db_path=self.db_path,
        )

    def _open_keyword_editor(self) -> None:
        def _on_save(new_keywords: list[str]) -> None:
            try:
                n = matching.rematch_all(new_keywords, self.db_path)
                self._append_log(
                    f"[gui] re-matched {n} job(s) against updated keywords\n")
            except Exception as exc:
                messagebox.showerror("Re-match failed", str(exc))
            self.refresh()

        KeywordEditor(self, self.keywords_path, on_save=_on_save)

    # -- scan --------------------------------------------------------------

    def _start_scan(self) -> None:
        if self.scanning:
            return
        self.scanning = True
        self.toolbar.set_scanning(True)
        self.toolbar.set_status("Scanning…")
        threading.Thread(target=self._run_scan_thread, daemon=True).start()

    def _run_scan_thread(self) -> None:
        orig_out, orig_err = sys.stdout, sys.stderr
        sys.stdout = StreamToQueue(self._log_q, orig_out)
        sys.stderr = StreamToQueue(self._log_q, orig_err)
        try:
            pipeline.run(dry_run=False, verbose=False, fetch_missing=True)
        except Exception as exc:
            print(f"[gui] scan failed: {exc}", file=sys.stderr)
        finally:
            sys.stdout, sys.stderr = orig_out, orig_err
            self._log_q.put(_SCAN_DONE)

    def _drain_log_queue(self) -> None:
        try:
            while True:
                item = self._log_q.get_nowait()
                if item == _SCAN_DONE:
                    self._scan_finished()
                else:
                    self._append_log(item)
        except queue.Empty:
            pass
        self.after(80, self._drain_log_queue)

    def _append_log(self, text: str) -> None:
        if not self._log_visible:
            return
        self.log_console.append(text)

    def _scan_finished(self) -> None:
        self.scanning = False
        self.toolbar.set_scanning(False)
        self.refresh()
        self._refresh_status(prefix="Scan complete · ")

    def _toggle_log(self) -> None:
        self._log_visible = not self._log_visible
        if self._log_visible:
            self.log_console.grid(row=3, column=0, columnspan=_COL_COUNT,
                                  sticky="ew", padx=theme.PAD, pady=(0, 4))
            self.log_toggle.configure(text="▴ Log")
        else:
            self.log_console.grid_forget()
            self.log_toggle.configure(text="▾ Log")

    # -- close -------------------------------------------------------------

    def _on_close(self) -> None:
        self._save_layout()
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
