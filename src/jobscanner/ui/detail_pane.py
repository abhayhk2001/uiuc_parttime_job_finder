"""Right-hand pane: everything about the selected job."""

from __future__ import annotations

import webbrowser
from typing import Callable, Optional

import customtkinter as ctk
from tkinter import messagebox

from jobscanner.timeutils import relative_days
from jobscanner.ui import job_actions, theme

#: Body blocks rendered under the keyword chips, in order.
_BODY_SECTIONS = (
    ("Description", "job_description"),
    ("Requirements", "requirements"),
    ("Skills", "skills"),
)

_WRAP_DEFAULT = 440
#: Horizontal padding to subtract when recomputing wraplength from the
#: pane's real width.
_WRAP_INSET = 44
_MIN_WRAP = 180


class DetailPane(ctk.CTkFrame):
    """Shows the selected job and its two context-aware action buttons."""

    def __init__(
        self,
        master,
        on_action: Callable[[Optional[str]], None],
        on_edit_follow_up: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self._on_action = on_action
        self._on_edit_follow_up = on_edit_follow_up
        self.job_id: Optional[str] = None
        self._url: str = ""
        self._primary_op: Optional[str] = None
        self._secondary_op: Optional[str] = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(8, weight=1)

        self.title_label = ctk.CTkLabel(
            self, text="(select a job)", anchor="w",
            font=theme.title_font(), wraplength=_WRAP_DEFAULT, justify="left")
        self.title_label.grid(row=0, column=0, sticky="ew",
                              padx=10, pady=(10, 2))

        link_row = ctk.CTkFrame(self, fg_color="transparent")
        link_row.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
        link_row.grid_columnconfigure(0, weight=1)

        self.url_label = ctk.CTkLabel(
            link_row, text="", anchor="w", text_color=theme.LINK_TEXT,
            wraplength=_WRAP_DEFAULT, justify="left")
        self.url_label.grid(row=0, column=0, sticky="ew")

        # The clickable label alone was undiscoverable.
        self.open_btn = ctk.CTkButton(
            link_row, text="Open \u2197", width=86, height=26,
            command=self.open_url, **theme.OUTLINE_BUTTON)
        self.open_btn.grid(row=0, column=1, sticky="e", padx=(6, 0))
        self.url_label.bind("<Button-1>", lambda _e: self.open_url())
        self.url_label.bind(
            "<Enter>", lambda _e: self.url_label.configure(cursor="hand2"))
        self.url_label.bind(
            "<Leave>", lambda _e: self.url_label.configure(cursor=""))

        self.meta_label = ctk.CTkLabel(
            self, text="", anchor="w", justify="left",
            text_color=theme.MUTED_TEXT, wraplength=_WRAP_DEFAULT)
        self.meta_label.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 8))

        self.primary_btn = ctk.CTkButton(
            self, text="✓ Mark Reviewed", width=180, height=32,
            command=lambda: self._on_action(self._primary_op))
        self.primary_btn.grid(row=3, column=0, sticky="w", padx=10, pady=(0, 4))

        self.secondary_btn = ctk.CTkButton(
            self, text="☆ Add to To Apply", width=180, height=28,
            command=lambda: self._on_action(self._secondary_op),
            **theme.OUTLINE_BUTTON)
        self.secondary_btn.grid(row=4, column=0, sticky="w",
                                padx=10, pady=(0, 8))

        # Only gridded for Follow Up rows; see _sync_follow_up_button.
        self.follow_up_btn = ctk.CTkButton(
            self, text="", width=240, height=28,
            command=self._on_edit_follow_up, **theme.OUTLINE_BUTTON)

        ctk.CTkLabel(
            self, text="Matched keywords", anchor="w",
            font=theme.heading_font(), text_color=theme.MUTED_TEXT,
        ).grid(row=6, column=0, sticky="ew", padx=10, pady=(4, 0))
        self.chips_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.chips_frame.grid(row=7, column=0, sticky="ew", padx=10, pady=(0, 6))

        body_holder = ctk.CTkFrame(self, fg_color="transparent")
        body_holder.grid(row=8, column=0, sticky="nsew", padx=10, pady=(4, 10))
        body_holder.grid_columnconfigure(0, weight=1)
        body_holder.grid_rowconfigure(0, weight=1)

        self.body = ctk.CTkScrollableFrame(body_holder)
        self.body.grid(row=0, column=0, sticky="nsew")
        self.body.grid_columnconfigure(0, weight=1)

        # Built once and re-filled on every selection. Destroying and
        # recreating these on each refresh made the pane flicker and threw
        # away the reader's scroll position.
        self._body_labels: dict[str, ctk.CTkLabel] = {}
        for index, (label, field) in enumerate(_BODY_SECTIONS):
            ctk.CTkLabel(
                self.body, text=label, anchor="w", font=theme.heading_font(),
            ).grid(row=index * 2, column=0, sticky="ew", padx=2, pady=(8, 2))
            value = ctk.CTkLabel(
                self.body, text="", anchor="w", justify="left",
                wraplength=_WRAP_DEFAULT)
            value.grid(row=index * 2 + 1, column=0, sticky="ew",
                       padx=2, pady=(0, 8))
            self._body_labels[field] = value

        #: Last-rendered keyword string, so chips are only rebuilt on change.
        self._chips_key: Optional[str] = None
        self._wraplength = _WRAP_DEFAULT
        self.bind("<Configure>", self._on_resize)

    # -- content -----------------------------------------------------------

    def clear(self) -> None:
        self.job_id = None
        self._url = ""
        self._primary_op = None
        self._secondary_op = None
        self.title_label.configure(text="(select a job)")
        self.url_label.configure(text="")
        self.open_btn.configure(state="disabled")
        self.meta_label.configure(text="")
        self.follow_up_btn.grid_remove()
        self._render_chips("")
        for label in self._body_labels.values():
            label.configure(text="")
        self._apply_actions(job_actions.JobState())

    def show(self, job: dict) -> None:
        self.job_id = job.get("job_id")
        title = (job.get("title") or "").strip() or "(no title)"
        self.title_label.configure(text=f"{title}  ·  #{job.get('job_id', '')}")

        self._url = (job.get("detail_url") or "").strip()
        self.url_label.configure(text=self._url)
        self.open_btn.configure(
            state="normal" if self._url.startswith(("http://", "https://"))
            else "disabled")

        self.meta_label.configure(text="\n".join(self._meta_lines(job)))

        state = job_actions.JobState.from_row(job)
        self._apply_actions(state)
        self._sync_follow_up_button(state, job.get("follow_up_at") or "")
        self._render_chips(job.get("matched_keywords") or "")
        self._render_body(job)

    @staticmethod
    def _meta_lines(job: dict) -> list[str]:
        lines = []
        company = (job.get("company") or "").strip()
        if company:
            lines.append(f"Company: {company}")
        applied_at = (job.get("applied_at") or "").strip()
        if applied_at:
            lines.append(f"Applied: {applied_at}")
        follow_up_at = (job.get("follow_up_at") or "").strip()
        if follow_up_at:
            lines.append(
                f"Follow up: {follow_up_at}  ({relative_days(follow_up_at)})")
        archived_at = (job.get("archived_at") or "").strip()
        if job.get("archived") and archived_at:
            lines.append(f"Archived: {archived_at}")
        return lines

    def _apply_actions(self, state: job_actions.JobState) -> None:
        primary = job_actions.primary_action(state)
        secondary = job_actions.secondary_action(state)
        self._primary_op = primary.op
        self._secondary_op = secondary.op

        self.primary_btn.configure(
            text=primary.label,
            state="normal" if primary.enabled else "disabled",
            **theme.BUTTON_STYLES.get(primary.style or "", {}),
        )
        self.secondary_btn.configure(
            text=secondary.label,
            state="normal" if secondary.enabled else "disabled",
        )

    def _sync_follow_up_button(
        self, state: job_actions.JobState, follow_up_at: str
    ) -> None:
        """The date editor is only meaningful for Follow Up rows."""
        if state.applied and not state.archived:
            pretty = follow_up_at[:10] if follow_up_at else "—"
            self.follow_up_btn.configure(
                text=f"✎  Edit follow-up date ({pretty})")
            self.follow_up_btn.grid(row=5, column=0, sticky="w",
                                    padx=10, pady=(0, 6))
        else:
            self.follow_up_btn.grid_remove()

    def _render_chips(self, matched_keywords: str) -> None:
        # Only rebuild when the keywords actually changed -- toggling a flag
        # re-renders the pane and used to churn these every time.
        if matched_keywords == self._chips_key:
            return
        self._chips_key = matched_keywords
        for widget in self.chips_frame.winfo_children():
            widget.destroy()
        keywords = [k.strip() for k in matched_keywords.split(",") if k.strip()]
        if not keywords:
            ctk.CTkLabel(
                self.chips_frame, text="(no keyword match)",
                text_color=theme.FAINT_TEXT,
            ).pack(side="left")
            return
        for keyword in keywords:
            ctk.CTkLabel(
                self.chips_frame, text=keyword, fg_color=theme.CHIP_BG,
                corner_radius=10, text_color=theme.CHIP_TEXT,
            ).pack(side="left", padx=(0, 4), pady=2)

    def _render_body(self, job: dict) -> None:
        for field, label in self._body_labels.items():
            label.configure(text=(job.get(field) or "").strip() or "(empty)")

    # -- reflow ------------------------------------------------------------

    def _on_resize(self, event=None) -> None:
        """Keep wraplength in step with the pane's real width, so text
        reflows when the divider is dragged instead of being clipped."""
        wrap = max(_MIN_WRAP, self.winfo_width() - _WRAP_INSET)
        if abs(wrap - self._wraplength) < 8:
            return
        self._wraplength = wrap
        for label in (self.title_label, self.meta_label):
            label.configure(wraplength=wrap)
        # The URL shares its row with the Open button.
        self.url_label.configure(wraplength=max(_MIN_WRAP, wrap - 100))
        for label in self._body_labels.values():
            label.configure(wraplength=wrap)

    # -- url ---------------------------------------------------------------

    def open_url(self) -> None:
        if self._url.startswith(("http://", "https://")):
            try:
                webbrowser.open(self._url)
            except Exception as exc:
                messagebox.showerror("Open URL failed", str(exc), parent=self)
