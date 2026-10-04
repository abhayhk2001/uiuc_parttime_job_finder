"""The scan log dock.

A ``QDockWidget`` containing a ``QPlainTextEdit``. Hidden by default,
toggleable via the View menu (``Cmd+L``). Stays usable across dock
zones (bottom, top, can float) -- standard QDockWidget behaviour.
"""

from __future__ import annotations

from collections import deque

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QDockWidget,
    QPlainTextEdit,
    QWidget,
)

from jobscanner.ui_qt import theme


_MAX_BLOCKS = 5000


class LogDock(QDockWidget):
    """Bottom-docked log console that streams text from a worker."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Log", parent)
        self.setObjectName("log-dock")
        self.setAllowedAreas(
            Qt.TopDockWidgetArea
            | Qt.BottomDockWidgetArea
            | Qt.LeftDockWidgetArea
            | Qt.RightDockWidgetArea
        )
        self.setFeatures(
            QDockWidget.DockWidgetClosable
            | QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
        )

        self._text = QPlainTextEdit(self)
        self._text.setReadOnly(True)
        self._text.setMaximumBlockCount(_MAX_BLOCKS)
        self._text.setLineWrapMode(QPlainTextEdit.NoWrap)
        font = QFont(theme.MONO_FAMILY if hasattr(theme, "MONO_FAMILY") else "Menlo")
        font.setStyleHint(QFont.Monospace)
        self._text.setFont(font)
        self.setWidget(self._text)

    def append(self, text: str) -> None:
        """Append one line (or a block of lines) and scroll to the end.

        An empty string is a deliberate blank line -- e.g. ``print()`` --
        so it is kept.
        """
        if text is None:
            return
        self._text.appendPlainText(text.rstrip("\n"))
        cursor = self._text.textCursor()
        cursor.movePosition(QTextCursor.End)
        self._text.setTextCursor(cursor)

    def clear(self) -> None:
        self._text.clear()
