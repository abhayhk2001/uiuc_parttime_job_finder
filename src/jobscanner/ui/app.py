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
import webbrowser
from collections import deque
from pathlib import Path
from tkinter import Menu, messagebox
from typing import Optional

import customtkinter as ctk

from jobscanner import config
from jobscanner import matching
from jobscanner import pipeline
from jobscanner import storage as db
from jobscanner.ui import sidebar as sidebar_mod
from jobscanner.ui import job_actions, theme
from jobscanner.ui.bulk_actions import BULK_ACTIONS_BY_ID
from jobscanner.ui.detail_pane import DetailPane
from jobscanner.ui.dialogs.follow_up import FollowUpDateEditor
from jobscanner.ui.dialogs.keywords import KeywordEditor
from jobscanner.ui.jobs_table import JobsTable
from jobscanner.ui.log_console import LogConsole, StreamToQueue
from jobscanner.ui.sash import Sash

_SCAN_DONE = "__SCAN_DONE__"

#: Write chunks retained for the collapsed log console.
_LOG_BUFFER_CHUNKS = 2000

# Root grid columns. The table is the only weighted one, so it absorbs any
# slack; the sidebar and detail pane keep the widths the sashes give them.
_COL_SIDEBAR = 0
_COL_SIDEBAR_SASH = 1
_COL_TABLE = 2
_COL_DETAIL_SASH = 3
_COL_DETAIL = 4
_COL_COUNT = 5

MIN_TABLE_WIDTH = 420
MIN_DETAIL_WIDTH = 300
MAX_DETAIL_WIDTH = 900


class JobScannerApp(ctk.CTk):
    def __init__(self, db_path: Path, keywords_path: Path) -> None:
        super().__init__()
        self.db_path = db_path
        self.keywords_path = keywords_path
        self.scanning = False
        self._log_q: "queue.Queue[str]" = queue.Queue()
        self._log_visible = False
        #: Scan output kept so the console can be opened mid-scan and still
        #: show everything from the start. Bounded so a long scan can't grow
        #: it without limit.
        self._log_buffer: "deque[str]" = deque(maxlen=_LOG_BUFFER_CHUNKS)
        self.section_var: str = db.SECTION_NEW

        theme.apply_appearance()
        self.title("UIUC Part-Time Job Scanner")
        self.geometry("1380x860")
        self.minsize(1080, 640)

        self._layout = db.get_layout(self.db_path)
        self._detail_width = int(self._layout["detail_width"])

        self.grid_columnconfigure(_COL_SIDEBAR, weight=0)
        self.grid_columnconfigure(_COL_SIDEBAR_SASH, weight=0)
        self.grid_columnconfigure(_COL_TABLE, weight=1,
                                  minsize=MIN_TABLE_WIDTH)
        self.grid_columnconfigure(_COL_DETAIL_SASH, weight=0)
        # The detail pane is sized explicitly rather than sharing a weight
        # with the table: the Treeview's natural width is wider than its
        # fair share, so a weighted split squeezed the detail pane to ~180px.
        self.grid_columnconfigure(_COL_DETAIL, weight=0,
                                  minsize=self._detail_width)
        self.grid_rowconfigure(1, weight=1)

        self._build_toolbar()
        self._build_body()
        self._build_footer()

        self._build_row_menu()
        self._bind_shortcuts()

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
        self.sections_panel = sidebar_mod.SectionsPanel(
            self,
            on_select_section=self.select_section,
            on_bulk_action=self.bulk_mark_section,
            on_edit_keywords=self._open_keyword_editor,
            on_toggle_collapsed=self._on_sidebar_collapsed,
            width=int(self._layout["sidebar_width"]),
            collapsed=bool(self._layout["sidebar_collapsed"]),
        )
        self.sections_panel.grid(row=1, column=_COL_SIDEBAR, sticky="nsew",
                                 padx=(theme.PAD, 0), pady=4)

        self.sidebar_sash = Sash(
            self,
            on_drag=self._drag_sidebar,
            on_release=self._save_layout,
            on_double_click=self.sections_panel.toggle_collapsed,
        )
        self.sidebar_sash.grid(row=1, column=_COL_SIDEBAR_SASH,
                               sticky="ns", pady=4)

        self.jobs_table = JobsTable(
            self,
            on_select=self._on_select_row,
            on_activate=self._open_job_url,
            on_context_menu=self._show_row_menu,
        )
        self.jobs_table.grid(row=1, column=_COL_TABLE, sticky="nsew",
                             padx=(0, 0), pady=4)

        self.detail_sash = Sash(
            self, on_drag=self._drag_detail, on_release=self._save_layout)
        self.detail_sash.grid(row=1, column=_COL_DETAIL_SASH,
                              sticky="ns", pady=4)

        self.detail = DetailPane(
            self,
            on_action=self._run_job_op,
            on_edit_follow_up=self._open_follow_up_editor,
        )
        self.detail.grid(row=1, column=_COL_DETAIL, sticky="nsew",
                         padx=(0, theme.PAD), pady=4)

    def _build_footer(self) -> None:
        self.footer = ctk.CTkFrame(self)
        self.footer.grid(row=2, column=0, columnspan=_COL_COUNT, sticky="nsew",
                         padx=theme.PAD, pady=(4, theme.PAD))
        self.footer.grid_columnconfigure(0, weight=1)

        self.log_toggle = ctk.CTkButton(
            self.footer, text="▾ Log", width=80, command=self._toggle_log)
        self.log_toggle.grid(row=0, column=1, padx=6, pady=6)

        # The console is a child of the footer so it opens directly beneath
        # its own toggle, rather than in a row below the footer entirely.
        self.log_console = LogConsole(self.footer)

    # -- shortcuts and context menu ----------------------------------------

    def _bind_shortcuts(self) -> None:
        """Keyboard access to everything the toolbar and sidebar offer."""
        accel = "Command" if sys.platform == "darwin" else "Control"
        bindings = {
            f"<{accel}-r>": lambda _e: self.refresh(),
            f"<{accel}-f>": lambda _e: self.toolbar.focus_search(),
            f"<{accel}-l>": lambda _e: self._toggle_log(),
            f"<{accel}-b>": lambda _e: self.sections_panel.toggle_collapsed(),
            f"<{accel}-Return>": lambda _e: self._start_scan(),
            "<Escape>": lambda _e: self.toolbar.clear_search(),
        }
        for sequence, handler in bindings.items():
            self.bind_all(sequence, handler)

        # Digits jump between sections, in sidebar order.
        for index, section in enumerate(db.COUNTED_SECTIONS, start=1):
            if index > 9:
                break
            self.bind_all(f"<{accel}-Key-{index}>",
                          lambda _e, s=section: self.select_section(s))

    def _build_row_menu(self) -> None:
        self._row_menu = Menu(self, tearoff=0)

    def _show_row_menu(self, job_id: str, x_root: int, y_root: int) -> None:
        """Right-click menu offering the same actions as the detail pane."""
        job = db.get_job(job_id, self.db_path)
        if not job:
            return
        state = job_actions.JobState.from_row(job)
        primary = job_actions.primary_action(state)
        secondary = job_actions.secondary_action(state)

        menu = self._row_menu
        menu.delete(0, "end")
        menu.add_command(
            label="Open in browser",
            command=lambda: self._open_job_url(job_id),
            state="normal" if (job.get("detail_url") or "").startswith("http")
            else "disabled",
        )
        menu.add_command(label="Copy Job ID",
                         command=lambda: self._copy_to_clipboard(job_id))
        menu.add_separator()
        for action in (primary, secondary):
            menu.add_command(
                label=action.label,
                command=lambda op=action.op: self._run_job_op_on(job_id, op),
                state="normal" if action.enabled and action.op else "disabled",
            )
        try:
            menu.tk_popup(x_root, y_root)
        finally:
            menu.grab_release()

    def _copy_to_clipboard(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)
        self.toolbar.show_toast(f"Copied {text}", self._refresh_status, ms=2500)

    def _open_job_url(self, job_id: str) -> None:
        job = db.get_job(job_id, self.db_path) or {}
        url = (job.get("detail_url") or "").strip()
        if url.startswith(("http://", "https://")):
            webbrowser.open(url)

    # -- pane resizing -----------------------------------------------------

    def _drag_sidebar(self, delta: int) -> None:
        """Dragging the left sash widens the sidebar; it also un-collapses."""
        if self.sections_panel.collapsed:
            if delta > 20:
                self.sections_panel.set_collapsed(False)
            return
        self.sections_panel.set_expanded_width(
            self.sections_panel.expanded_width + delta)

    def _drag_detail(self, delta: int) -> None:
        """Dragging the right sash left widens the detail pane."""
        width = max(MIN_DETAIL_WIDTH,
                    min(MAX_DETAIL_WIDTH, self._detail_width - delta))
        self.grid_columnconfigure(_COL_DETAIL, minsize=width)

    def _on_sidebar_collapsed(self, collapsed: bool) -> None:
        self._save_layout()

    def _save_layout(self) -> None:
        """Persist the pane layout. Called on every drag release and on
        collapse, so a crash can't lose it the way close-only saving did."""
        try:
            self._detail_width = int(
                self.grid_columnconfigure(_COL_DETAIL)["minsize"])
            self._layout = {
                "sidebar_width": self.sections_panel.expanded_width,
                "sidebar_collapsed": self.sections_panel.collapsed,
                "detail_width": self._detail_width,
            }
            db.set_layout(self._layout, self.db_path)
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

        self.jobs_table.populate(rows, empty_message=self._empty_message())
        self.sections_panel.refresh(
            db.get_section_counts(self.db_path),
            matching.load_keywords(self.keywords_path),
        )
        self._refresh_status()
        self._on_select_row(self.jobs_table.selected_id())

    def _empty_message(self) -> str:
        """Explain an empty table rather than showing a blank grid."""
        if self.toolbar.query().strip():
            return f"No jobs match \u201c{self.toolbar.query().strip()}\u201d here."
        if self.toolbar.matches_only():
            return "No keyword matches in this section."
        return f"Nothing in {db.SECTION_LABELS[self.section_var]}."

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

    def bulk_mark_section(self, action_id: str) -> None:
        """Run the bulk action with this id, confirming first if it says to."""
        action = BULK_ACTIONS_BY_ID.get(action_id)
        if action is None:
            return
        if action.confirm and not messagebox.askokcancel(
            action.label, action.confirm, parent=self, default="cancel"
        ):
            return
        try:
            affected = action.run(self.db_path)
        except Exception as exc:
            messagebox.showerror("Bulk update failed", str(exc))
            return
        self.refresh()
        # A toast instead of a modal the user has to dismiss every time.
        self.toolbar.show_toast(action.message(affected), self._refresh_status)

    # -- detail ------------------------------------------------------------

    def _on_select_row(self, job_id: Optional[str]) -> None:
        job = db.get_job(job_id, self.db_path) if job_id else None
        if job:
            self.detail.show(job)
        else:
            self.detail.clear()

    def _run_job_op(self, op: Optional[str]) -> None:
        """Run a primary/secondary detail-pane action on the selected job."""
        self._run_job_op_on(self.detail.job_id, op)

    def _run_job_op_on(self, job_id: Optional[str], op: Optional[str]) -> None:
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
        # Always buffer: output produced while the console was collapsed used
        # to be dropped, so opening it mid-scan showed an empty box.
        self._log_buffer.append(text)
        if self._log_visible:
            self.log_console.append(text)

    def _scan_finished(self) -> None:
        self.scanning = False
        self.toolbar.set_scanning(False)
        self.refresh()
        self._refresh_status(prefix="Scan complete · ")

    def _toggle_log(self) -> None:
        self._log_visible = not self._log_visible
        if self._log_visible:
            self.log_console.grid(row=1, column=0, columnspan=2,
                                  sticky="nsew", padx=6, pady=(0, 6))
            self.footer.grid_rowconfigure(1, weight=1)
            # Replay whatever was logged while the console was collapsed.
            self.log_console.clear()
            self.log_console.append("".join(self._log_buffer))
            self.log_toggle.configure(text="▴ Log")
        else:
            self.log_console.grid_forget()
            self.footer.grid_rowconfigure(1, weight=0)
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
