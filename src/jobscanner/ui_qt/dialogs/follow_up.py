"""The follow-up date editor dialog.

Real ``QDialog`` with a row of preset-offset buttons (1d, 3d, 1w, 2w, 1m,
3m) and a ``QDateEdit`` for arbitrary YYYY-MM-DD selection. Saving calls
``db.set_follow_up`` and triggers the caller-supplied ``on_save`` callback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QDateEdit,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from jobscanner import config
from jobscanner import storage as db
from jobscanner.timeutils import add_days_iso, now_iso, parse_iso
from jobscanner.ui_qt import theme


_COLUMNS = 3

PRESETS: tuple[tuple[int, str], ...] = (
    (1, "in 1 day"),
    (3, "in 3 days"),
    (7, "in 1 week"),
    (14, "in 2 weeks"),
    (30, "in 1 month"),
    (90, "in 3 months"),
)


class FollowUpDialog(QDialog):
    """Set a job's ``follow_up_at``."""

    def __init__(self, parent, job_id: str, initial_date: str,
                 on_save: Optional[Callable[[], None]] = None,
                 db_path: Optional[Path] = None) -> None:
        super().__init__(parent)
        self._job_id = job_id
        self._on_save = on_save
        self._db_path = db_path or config.DB_PATH

        self.setWindowTitle("Edit follow-up date")
        self.resize(460, 300)
        self.setMinimumSize(420, 280)

        self._build(initial_date or "")

    def _build(self, initial: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        title = QLabel("Pick a follow-up date", self)
        title_font = title.font()
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        presets_label = QLabel("Preset offsets:", self)
        presets_label.setStyleSheet(
            f"color: {theme.current_palette()['muted']};")
        layout.addWidget(presets_label)

        preset_grid = QGridLayout()
        preset_grid.setSpacing(6)
        # Keep references + their grid cell so the layout can be asserted
        # on by tests and by introspection in the GUI (e.g. tooltips).
        self.preset_buttons: list[QPushButton] = []
        for i, (days, label) in enumerate(PRESETS):
            btn = QPushButton(label, self)
            btn.clicked.connect(lambda _checked=False, d=days: self._apply_offset(d))
            preset_grid.addWidget(btn, i // _COLUMNS, i % _COLUMNS)
            btn.grid_row = i // _COLUMNS
            btn.grid_col = i % _COLUMNS
            self.preset_buttons.append(btn)
        layout.addLayout(preset_grid)

        rows_used = (len(PRESETS) + _COLUMNS - 1) // _COLUMNS
        custom_row = rows_used + 1

        custom_label = QLabel(
            "Or pick a custom date (YYYY-MM-DD):", self)
        custom_label.setStyleSheet(
            f"color: {theme.current_palette()['muted']};")
        layout.addWidget(custom_label)

        date_row = QHBoxLayout()
        self._date_edit = QDateEdit(self)
        self._date_edit.setCalendarPopup(True)
        self._date_edit.setDisplayFormat("yyyy-MM-dd")
        if initial:
            parsed = parse_iso(initial)
            if parsed is not None:
                self._date_edit.setDate(QDate(parsed.year, parsed.month, parsed.day))
            else:
                self._date_edit.setDate(QDate.currentDate())
        else:
            self._date_edit.setDate(QDate.currentDate())
        date_row.addWidget(self._date_edit, 1)
        set_btn = QPushButton("Set date", self)
        set_btn.clicked.connect(self._apply_custom)
        date_row.addWidget(set_btn)
        layout.addLayout(date_row)

        close_btn = QPushButton("Close", self)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignRight)

    def _apply_offset(self, days: int) -> None:
        iso = add_days_iso(now_iso(), days)
        self._save(iso)

    def _apply_custom(self) -> None:
        qdate = self._date_edit.date()
        iso = f"{qdate.year():04d}-{qdate.month():02d}-{qdate.day():02d}"
        self._save(iso)

    def _save(self, iso: str) -> None:
        try:
            db.set_follow_up(self._job_id, iso, self._db_path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        if self._on_save is not None:
            try:
                self._on_save()
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "Refresh failed", str(exc))
                return
        self.accept()
