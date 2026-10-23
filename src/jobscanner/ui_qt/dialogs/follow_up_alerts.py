"""The startup follow-up alerts dialog.

Shown once when the app opens if any applied job needs attention: either its
``follow_up_at`` is due/overdue, or the scanner archived it because it left
the listing. Each entry can jump straight to the job in the right section.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from jobscanner import config
from jobscanner.timeutils import local_date_str, relative_days
from jobscanner.ui_qt import job_actions as ja
from jobscanner.ui_qt import theme


class FollowUpAlertsDialog(QDialog):
    """Lists applied jobs that need follow-up attention."""

    jumpRequested = Signal(str)
    #: ``(job_id, op)`` -- the owner applies the op; the dialog only drops
    #: the row, so it stays free of database access.
    actionRequested = Signal(str, str)

    def __init__(self, parent, jobs: list[dict]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Follow-ups due")
        self.setModal(True)
        self.resize(600, 420)
        self.setMinimumSize(480, 320)
        self._build(jobs)

    def _build(self, jobs: list[dict]) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QLabel("Follow-ups due", self)
        title_font = title.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 1)
        title.setFont(title_font)
        layout.addWidget(title)

        count = len(jobs)
        subtitle = QLabel("", self)
        subtitle.setStyleSheet(f"color: {theme.current_palette()['muted']};")
        layout.addWidget(subtitle)
        self._subtitle = subtitle

        self._list = QListWidget(self)
        self._list.setSelectionMode(QListWidget.SingleSelection)
        for job in jobs:
            item = QListWidgetItem(self._item_text(job))
            item.setData(Qt.UserRole, job.get("job_id"))
            item.setData(Qt.UserRole + 1, job.get("detail_url") or "")
            item.setToolTip(job.get("detail_url") or "")
            self._list.addItem(item)
        self._list.itemDoubleClicked.connect(lambda _item: self._go())
        layout.addWidget(self._list, 1)

        bar = QHBoxLayout()
        self._soon_btn = QPushButton(
            f"Follow up in {config.FOLLOW_UP_SNOOZE_DAYS} days", self)
        self._soon_btn.clicked.connect(
            lambda: self._act(ja.OP_FOLLOW_UP_SOON))
        bar.addWidget(self._soon_btn)
        self._remove_btn = QPushButton("Remove", self)
        self._remove_btn.setToolTip(
            "Take this job off the follow-up list. It stays in Applied.")
        self._remove_btn.clicked.connect(
            lambda: self._act(ja.OP_REMOVE_FOLLOW_UP))
        bar.addWidget(self._remove_btn)
        bar.addStretch(1)
        self._open_btn = QPushButton("Open in Browser", self)
        self._open_btn.clicked.connect(self._open_in_browser)
        bar.addWidget(self._open_btn)
        self._go_btn = QPushButton("Go to job", self)
        self._go_btn.setDefault(True)
        self._go_btn.clicked.connect(self._go)
        bar.addWidget(self._go_btn)
        close_btn = QPushButton("Close", self)
        close_btn.clicked.connect(self.accept)
        bar.addWidget(close_btn)
        layout.addLayout(bar)

        if self._list.count():
            self._list.setCurrentRow(0)
        self._sync_state()

    def _sync_state(self) -> None:
        count = self._list.count()
        self._subtitle.setText(
            f"{count} applied job{'s' if count != 1 else ''} need attention.")
        for btn in (self._soon_btn, self._remove_btn, self._go_btn,
                    self._open_btn):
            btn.setEnabled(count > 0)

    def _act(self, op: str) -> None:
        row = self._list.currentRow()
        item = self._list.item(row)
        if item is None:
            return
        job_id = item.data(Qt.UserRole)
        self._list.takeItem(row)
        self._sync_state()
        self.actionRequested.emit(job_id, op)
        if self._list.count() == 0:
            self.accept()

    @staticmethod
    def _item_text(job: dict) -> str:
        title = (job.get("title") or "").strip() or "(no title)"
        company = (job.get("company") or "").strip()
        if job.get("archived"):
            note = "No longer listed"
        else:
            follow = job.get("follow_up_at") or ""
            rel = relative_days(follow)
            if rel:
                note = f"follow up {rel}"
            else:
                note = f"follow up {local_date_str(follow) or 'due'}"
        text = title
        if company:
            text += f"  \u00b7  {company}"
        text += f"  \u2014  {note}"
        return text

    def _go(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        self.jumpRequested.emit(item.data(Qt.UserRole))
        self.accept()

    def _open_in_browser(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        url = (item.data(Qt.UserRole + 1) or "").strip()
        if url.startswith(("http://", "https://")):
            QDesktopServices.openUrl(QUrl(url))
