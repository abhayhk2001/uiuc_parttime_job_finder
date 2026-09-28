"""The right-hand detail pane.

Shows the selected job: title, clickable URL, meta info, primary + secondary
action buttons, the follow-up date editor trigger, matched keyword chips,
and the body (Description / Requirements / Skills) rendered as HTML inside
a ``QTextBrowser``.

The widget is a ``QScrollArea`` so it remains usable when the window is
short. The body HTML is built once per ``show()`` -- the widgets (chips,
buttons, labels) are reused across selections, so swapping jobs doesn't
recreate the layout and the reader's scroll position is preserved.
"""

from __future__ import annotations

import html
from typing import Optional

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from jobscanner.timeutils import relative_days
from jobscanner.ui_qt import job_actions as ja
from jobscanner.ui_qt import theme
from jobscanner.ui_qt.flow_layout import FlowLayout


_BODY_FIELDS: tuple[tuple[str, str], ...] = (
    ("Description", "job_description"),
    ("Requirements", "requirements"),
    ("Skills", "skills"),
)


def _build_body_html(job: dict, palette) -> str:
    """Build the HTML body for ``QTextBrowser``.

    Each populated section gets its own ``<h3>`` heading and a paragraph.
    Sections with no text are omitted rather than shown as "(empty)": only
    the Virtual Job Board splits its text into Requirements and Skills, so
    every Research Park, Clearinghouse and Library job would otherwise
    carry two empty headings. Description is always rendered, so a job with
    no text at all still shows why the pane looks bare.

    Inline styling is used because QTextBrowser does not inherit QSS from
    the surrounding window reliably.
    """
    parts: list[str] = []
    body_color = palette["text"]
    muted = palette["muted"]
    for heading, field in _BODY_FIELDS:
        value = (job.get(field) or "").strip()
        if not value:
            if field != "job_description":
                continue
            value = "(empty)"
        escaped = html.escape(value).replace("\n", "<br>")
        parts.append(
            f'<h3 style="color:{muted}; margin-top:14px; margin-bottom:4px;">'
            f'{heading}</h3>'
            f'<p style="color:{body_color}; margin:0;">{escaped}</p>'
        )
    return "".join(parts)


class _Chip(QLabel):
    """A small rounded chip for a matched keyword."""

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(text, parent)
        p = theme.current_palette()
        self.setStyleSheet(
            f"background-color: {p['chip_bg']}; color: {p['chip_text']}; "
            f"border-radius: 10px; padding: 2px 10px;"
        )
        self.setMargin(2)


class DetailPane(QWidget):
    """The right-hand detail panel."""

    actionInvoked = Signal(object)       # the ActionSpec.op string (or None)
    editFollowUpRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.job_id: Optional[str] = None
        self._primary_op: Optional[str] = None
        self._secondary_op: Optional[str] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_body())

    def _build_body(self) -> QWidget:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        inner = QWidget(scroll)
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        self.title_label = QLabel("(select a job)", inner)
        title_font = self.title_label.font()
        title_font.setPointSize(title_font.pointSize() + 2)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        # URL row: a clickable label + a small "Open" button.
        url_row = QWidget(inner)
        url_layout = QHBoxLayout(url_row)
        url_layout.setContentsMargins(0, 0, 0, 0)
        url_layout.setSpacing(6)
        self.url_label = QLabel("", url_row)
        p = theme.current_palette()
        self.url_label.setStyleSheet(f"color: {p['link']};")
        self.url_label.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
        self.url_label.linkActivated.connect(self._open_url)
        self.url_label.setWordWrap(True)
        url_layout.addWidget(self.url_label, 1)
        self.open_btn = QToolButton(url_row)
        self.open_btn.setText("Open \u2197")
        self.open_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.open_btn.setFixedHeight(26)
        self.open_btn.clicked.connect(self._open_current_url)
        url_layout.addWidget(self.open_btn)
        layout.addWidget(url_row)

        self.meta_label = QLabel("", inner)
        self.meta_label.setWordWrap(True)
        self.meta_label.setStyleSheet(f"color: {p['muted']};")
        layout.addWidget(self.meta_label)

        # Primary + secondary action buttons (and follow-up editor).
        self.primary_btn = QPushButton("", inner)
        self.primary_btn.setMinimumHeight(32)
        self.primary_btn.clicked.connect(
            lambda: self.actionInvoked.emit(self._primary_op))
        layout.addWidget(self.primary_btn)

        self.secondary_btn = QPushButton("", inner)
        self.secondary_btn.setMinimumHeight(28)
        self.secondary_btn.clicked.connect(
            lambda: self.actionInvoked.emit(self._secondary_op))
        layout.addWidget(self.secondary_btn)

        self.follow_up_btn = QPushButton("", inner)
        self.follow_up_btn.setMinimumHeight(28)
        self.follow_up_btn.clicked.connect(self.editFollowUpRequested)
        layout.addWidget(self.follow_up_btn)

        # Matched keyword chips header.
        chips_header = QLabel("Matched keywords", inner)
        chips_header.setStyleSheet(
            f"color: {p['muted']}; font-weight: bold;"
        )
        layout.addWidget(chips_header)

        self.chips_flow = QWidget(inner)
        # Use a wrap-on-overflow flow layout so a job with many matched
        # keywords (or a long keyword like "machine learning") doesn't
        # squeeze every chip down to a single character.
        self.chips_layout = FlowLayout(self.chips_flow, margin=0,
                                       h_spacing=6, v_spacing=6)
        layout.addWidget(self.chips_flow)

        # Body text in a QTextBrowser. Anchors are clickable (we wire
        # the only anchor we emit, which is the URL, above).
        self.body = QTextBrowser(inner)
        self.body.setOpenExternalLinks(False)
        self.body.setOpenLinks(False)
        self.body.anchorClicked.connect(self._on_anchor_clicked)
        body_font = QFont()
        body_font.setPointSize(body_font.pointSize())
        self.body.setFont(body_font)
        self.body.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.body, 1)

        scroll.setWidget(inner)
        return scroll

    # -- public API ------------------------------------------------------

    def clear(self) -> None:
        self.job_id = None
        self._primary_op = None
        self._secondary_op = None
        self.title_label.setText("(select a job)")
        self.url_label.setText("")
        self.url_label.setProperty("href", "")
        self.open_btn.setEnabled(False)
        self.meta_label.setText("")
        self._render_actions(ja.primary_action(ja.JobState()),
                             ja.secondary_action(ja.JobState()))
        self.follow_up_btn.hide()
        self._render_chips("")
        self.body.setHtml(_build_body_html({}, theme.current_palette()))

    def show_job(self, job: dict) -> None:
        """Render the job dict into the pane."""
        self.job_id = job.get("job_id")
        self._last_job = dict(job)  # cache for palette refresh
        title = (job.get("title") or "").strip() or "(no title)"
        self.title_label.setText(f"{title}  \u00b7  #{self.job_id}")

        url = (job.get("detail_url") or "").strip()
        self.url_label.setText(url)
        self.url_label.setProperty("href", url)
        self.open_btn.setEnabled(url.startswith(("http://", "https://")))

        meta = self._meta_lines(job)
        self.meta_label.setText("\n".join(meta))

        state = ja.JobState.from_row(job)
        self._render_actions(ja.primary_action(state), ja.secondary_action(state))
        self._render_follow_up(state, job.get("follow_up_at") or "")
        self._render_chips(job.get("matched_keywords") or "")
        self.body.setHtml(_build_body_html(job, theme.current_palette()))

    def refresh_palette(self) -> None:
        """Re-paint chips and labels after a theme switch."""
        p = theme.current_palette()
        self.url_label.setStyleSheet(f"color: {p['link']};")
        self.meta_label.setStyleSheet(f"color: {p['muted']};")
        # Re-render chips with the same keyword string, since their
        # stylesheet is built from the palette.
        last = getattr(self, "_last_keywords", "")
        self._render_chips(last)
        # The body HTML embeds colors too -- re-render with the same job.
        last_job = getattr(self, "_last_job", None)
        if last_job is not None:
            self.body.setHtml(_build_body_html(last_job, p))

    # -- internals -------------------------------------------------------

    def _meta_lines(self, job: dict) -> list[str]:
        lines: list[str] = []
        company = (job.get("company") or "").strip()
        if company:
            lines.append(f"Company: {company}")
        applied = (job.get("applied_at") or "").strip()
        if applied:
            lines.append(f"Applied: {applied[:10]}")
        follow = (job.get("follow_up_at") or "").strip()
        if follow:
            lines.append(
                f"Follow up: {follow[:10]}  ({relative_days(follow)})")
        if job.get("archived") and (job.get("archived_at") or "").strip():
            lines.append(f"Archived: {job['archived_at'][:10]}")
        return lines

    def _render_actions(self, primary: ja.ActionSpec,
                        secondary: ja.ActionSpec) -> None:
        self._primary_op = primary.op
        self._secondary_op = secondary.op
        self._style_button(self.primary_btn, primary)
        self._style_button(self.secondary_btn, secondary)
        self.primary_btn.setVisible(bool(primary.label))
        self.secondary_btn.setVisible(bool(secondary.label))

    def _style_button(self, btn: QPushButton, spec: ja.ActionSpec) -> None:
        btn.setText(spec.label)
        btn.setEnabled(spec.enabled and bool(spec.op))
        p = theme.current_palette()
        style = spec.style
        if style == "accent":
            css = (f"QPushButton {{ background: {p['accent']}; color: white; "
                   f"border: none; padding: 4px 12px; border-radius: 4px; }} "
                   f"QPushButton:hover {{ background: {p['accent_hover']}; }} "
                   f"QPushButton:disabled {{ background: {p['border']}; "
                   f"color: {p['faint']}; }}")
        elif style == "success":
            css = (f"QPushButton {{ background: {p['success']}; color: white; "
                   f"border: none; padding: 4px 12px; border-radius: 4px; }} "
                   f"QPushButton:hover {{ background: {p['success_hover']}; }} "
                   f"QPushButton:disabled {{ background: {p['border']}; "
                   f"color: {p['faint']}; }}")
        elif style == "warning":
            css = (f"QPushButton {{ background: {p['warning']}; color: white; "
                   f"border: none; padding: 4px 12px; border-radius: 4px; }} "
                   f"QPushButton:hover {{ background: {p['warning_hover']}; }} "
                   f"QPushButton:disabled {{ background: {p['border']}; "
                   f"color: {p['faint']}; }}")
        else:
            css = (f"QPushButton {{ background: transparent; "
                   f"color: {p['text']}; border: 1px solid {p['border']}; "
                   f"padding: 4px 12px; border-radius: 4px; }} "
                   f"QPushButton:hover {{ background: {p['bg']}; }} "
                   f"QPushButton:disabled {{ color: {p['faint']}; "
                   f"border-color: {p['border']}; }}")
        btn.setStyleSheet(css)

    def _render_follow_up(self, state: ja.JobState, follow_up_at: str) -> None:
        if state.applied and not state.archived:
            pretty = follow_up_at[:10] if follow_up_at else "\u2014"
            self.follow_up_btn.setText(
                f"\u270e  Edit follow-up date ({pretty})")
            self.follow_up_btn.show()
        else:
            self.follow_up_btn.hide()

    def _render_chips(self, matched_keywords: str) -> None:
        # Keep a copy so palette refreshes can rebuild chips.
        self._last_keywords = matched_keywords
        # Same keywords as last time -> nothing to do. The chip widgets
        # are reused, which avoids visible flicker and preserves any
        # in-progress interaction.
        if matched_keywords == getattr(self, "_chips_key", None):
            return
        self._chips_key = matched_keywords
        # Clear the existing chips.
        while self.chips_layout.count():
            item = self.chips_layout.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        keywords = [k.strip() for k in matched_keywords.split(",") if k.strip()]
        if not keywords:
            empty = QLabel("(no keyword match)", self.chips_flow)
            p = theme.current_palette()
            empty.setStyleSheet(f"color: {p['faint']};")
            self.chips_layout.addWidget(empty)
            return
        for kw in keywords:
            chip = _Chip(kw, self.chips_flow)
            self.chips_layout.addWidget(chip)

    def _on_anchor_clicked(self, url: QUrl) -> None:
        if url.scheme() in ("http", "https"):
            QDesktopServices.openUrl(url)

    def _open_url(self) -> None:
        href = self.url_label.property("href") or ""
        if href.startswith(("http://", "https://")):
            QDesktopServices.openUrl(QUrl(href))

    def _open_current_url(self) -> None:
        self._open_url()
