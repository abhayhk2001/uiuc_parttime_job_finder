"""The keyword editor dialog.

Real ``QDialog`` with a ``QPlainTextEdit`` (one keyword per line), Save /
Reload / Cancel. Saving writes atomically to the keywords JSON via a
``.tmp`` + ``os.replace`` so a crash mid-write can't corrupt the file
(matches the old CTk implementation's safety net).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from jobscanner.ui_qt import theme


class KeywordsDialog(QDialog):
    """Edit ``keywords.json``."""

    def __init__(self, parent, keywords_path: Path,
                 on_save: Optional[Callable[[list[str]], None]] = None) -> None:
        super().__init__(parent)
        self._keywords_path = keywords_path
        self._on_save = on_save
        self._keywords: list[str] = []

        self.setWindowTitle("Edit Keywords")
        self.resize(480, 620)
        self.setMinimumSize(360, 420)

        self._build()
        self._load()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        help_label = QLabel("One keyword per line.", self)
        help_label.setStyleSheet(f"color: {theme.current_palette()['muted']};")
        layout.addWidget(help_label)

        self._editor = QPlainTextEdit(self)
        mono_font = QFont("Menlo")
        mono_font.setStyleHint(QFont.Monospace)
        self._editor.setFont(mono_font)
        layout.addWidget(self._editor, 1)

        bar = QHBoxLayout()
        self._path_label = QLabel("", self)
        self._path_label.setStyleSheet(
            f"color: {theme.current_palette()['muted']};"
        )
        bar.addWidget(self._path_label, 1)
        reload_btn = QPushButton("Reload", self)
        reload_btn.clicked.connect(self._reload)
        bar.addWidget(reload_btn)
        save_btn = QPushButton("Save", self)
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save_and_accept)
        bar.addWidget(save_btn)
        cancel_btn = QPushButton("Cancel", self)
        cancel_btn.clicked.connect(self.reject)
        bar.addWidget(cancel_btn)
        layout.addLayout(bar)

    def _load(self) -> None:
        self._keywords = []
        if self._keywords_path.exists():
            try:
                with self._keywords_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:  # noqa: BLE001
                data = []
            if isinstance(data, list):
                self._keywords = [str(k).strip() for k in data if str(k).strip()]
        self._editor.setPlainText("\n".join(self._keywords))
        self._path_label.setText(f"Saves to {self._keywords_path.name}")

    def _reload(self) -> None:
        self._load()

    def _save_and_accept(self) -> None:
        text = self._editor.toPlainText()
        cleaned: list[str] = []
        seen: set[str] = set()
        for line in text.splitlines():
            k = line.strip()
            if not k:
                continue
            kl = k.lower()
            if kl in seen:
                continue
            seen.add(kl)
            cleaned.append(k)

        tmp = self._keywords_path.with_suffix(
            self._keywords_path.suffix + ".tmp")
        try:
            tmp.parent.mkdir(parents=True, exist_ok=True)
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(cleaned, f, indent=2)
            os.replace(tmp, self._keywords_path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Save failed", str(exc))
            return

        self._keywords = cleaned
        if self._on_save is not None:
            try:
                self._on_save(cleaned)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "Re-match failed", str(exc))
                # Saved to disk; surface the error but accept the dialog.
        self.accept()
