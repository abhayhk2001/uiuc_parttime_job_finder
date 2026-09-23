"""A thin draggable divider between two grid columns."""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from jobscanner.ui import theme

WIDTH = 5


class Sash(ctk.CTkFrame):
    """Drag-to-resize handle.

    `on_drag` receives the horizontal pixel delta since the drag started;
    the owner decides what to resize. `on_release` fires once when the drag
    ends, which is where layout should be persisted.
    """

    def __init__(
        self,
        master,
        on_drag: Callable[[int], None],
        on_release: Callable[[], None] | None = None,
        on_double_click: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master, width=WIDTH, fg_color=theme.SASH,
                         cursor="sb_h_double_arrow")
        self._on_drag = on_drag
        self._on_release = on_release
        self._on_double_click = on_double_click
        self._start_x = 0
        self._dragging = False

        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        if on_double_click is not None:
            self.bind("<Double-Button-1>", self._double_click)

    def _press(self, event) -> None:
        self._start_x = event.x_root
        self._dragging = True

    def _drag(self, event) -> None:
        if self._dragging:
            self._on_drag(event.x_root - self._start_x)

    def _release(self, _event=None) -> None:
        if not self._dragging:
            return
        self._dragging = False
        if self._on_release is not None:
            self._on_release()

    def _double_click(self, _event=None) -> None:
        # A double-click also fires press/release; make sure the drag state
        # is cleared before the toggle runs.
        self._dragging = False
        if self._on_double_click is not None:
            self._on_double_click()

    def _enter(self, _event=None) -> None:
        self.configure(fg_color=theme.SASH_ACTIVE, cursor="sb_h_double_arrow")

    def _leave(self, _event=None) -> None:
        if not self._dragging:
            self.configure(fg_color=theme.SASH)
