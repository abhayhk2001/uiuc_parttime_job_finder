"""A simple flow layout that wraps widgets when they don't fit a row.

Qt has no built-in ``QFlowLayout`` (the one in QtWidgets is private), and
``QHBoxLayout`` can't wrap, so a job with many matched keywords ends up
squeezing each chip down to a single character. This implementation
matches the standard example in the Qt docs.
"""

from __future__ import annotations

from typing import List

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QSizePolicy, QStyle, QWidget


class FlowLayout(QLayout):
    """Wrap-on-overflow layout. Lays widgets out left-to-right, top-to-bottom."""

    def __init__(self, parent: QWidget | None = None,
                 margin: int = 0, h_spacing: int = 6, v_spacing: int = 6):
        super().__init__(parent)
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)
        self._h_space = h_spacing
        self._v_space = v_spacing
        self._items: List[QLayoutItem] = []

    def __del__(self) -> None:
        # Take all items so Python doesn't see them as leaks.
        while True:
            item = self.takeAt(0)
            if item is None:
                break

    # -- QLayout API ------------------------------------------------------

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802
        self._items.append(item)

    def horizontalSpacing(self) -> int:  # noqa: N802
        if self._h_space >= 0:
            return self._h_space
        return self._smart_spacing(QStyle.PM_LayoutHorizontalSpacing)

    def verticalSpacing(self) -> int:  # noqa: N802
        if self._v_space >= 0:
            return self._v_space
        return self._smart_spacing(QStyle.PM_LayoutVerticalSpacing)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientations:  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(),
                      margins.top() + margins.bottom())
        return size

    # -- helpers ---------------------------------------------------------

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(),
                                 -margins.right(), -margins.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0

        for item in self._items:
            wid = item.widget()
            space_x = self.horizontalSpacing()
            if space_x == -1 and wid is not None:
                space_x = wid.style().layoutSpacing(
                    QSizePolicy.PushButton, QSizePolicy.PushButton,
                    Qt.Horizontal)
            space_y = self.verticalSpacing()
            if space_y == -1 and wid is not None:
                space_y = wid.style().layoutSpacing(
                    QSizePolicy.PushButton, QSizePolicy.PushButton,
                    Qt.Vertical)

            next_x = x + item.sizeHint().width() + space_x
            if next_x - space_x > effective.right() and line_height > 0:
                x = effective.x()
                y = y + line_height + space_y
                next_x = x + item.sizeHint().width() + space_x
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))

            x = next_x
            line_height = max(line_height, item.sizeHint().height())

        return y + line_height - rect.y() + margins.bottom()

    def _smart_spacing(self, pm: QStyle.PixelMetric) -> int:
        parent = self.parent()
        if parent is None:
            return -1
        if parent.isWidgetType():
            return parent.style().pixelMetric(pm, None, parent)
        return parent.spacing()
