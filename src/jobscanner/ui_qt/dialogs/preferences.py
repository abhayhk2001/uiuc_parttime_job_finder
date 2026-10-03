"""The appearance preferences dialog.

Lets the user override the OS theme detection: Light / Dark / Auto.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings

from jobscanner.ui_qt.settings import app_settings
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QRadioButton,
    QVBoxLayout,
)

from jobscanner.ui_qt import palette as palette_mod
from jobscanner.ui_qt import theme


class PreferencesDialog(QDialog):
    """Appearance preferences: light / dark / follow OS."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Appearance")
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        layout.addWidget(QLabel("Theme:", self))

        self._group = QButtonGroup(self)
        self._auto = QRadioButton("Follow system", self)
        self._light = QRadioButton("Light", self)
        self._dark = QRadioButton("Dark", self)
        self._group.addButton(self._auto)
        self._group.addButton(self._light)
        self._group.addButton(self._dark)

        current = app_settings().value("appearance/override", "auto", type=str)
        if current == "light":
            self._light.setChecked(True)
        elif current == "dark":
            self._dark.setChecked(True)
        else:
            self._auto.setChecked(True)
        layout.addWidget(self._auto)
        layout.addWidget(self._light)
        layout.addWidget(self._dark)

        layout.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._apply_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _apply_and_accept(self) -> None:
        if self._light.isChecked():
            override = "light"
        elif self._dark.isChecked():
            override = "dark"
        else:
            override = "auto"
        app_settings().setValue("appearance/override", override)
        # Reapply immediately so the user sees the change before the dialog
        # closes.
        app = QApplication.instance()
        if override == "light":
            theme._set_palette_and_qss(app, palette_mod.LIGHT)
        elif override == "dark":
            theme._set_palette_and_qss(app, palette_mod.DARK)
        else:
            theme._set_palette_and_qss(app, theme._detect_palette())
        self.accept()
