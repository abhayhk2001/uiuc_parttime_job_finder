"""The collapsible scan-log console and the stdout shim that feeds it."""

from __future__ import annotations

import queue

import customtkinter as ctk

from jobscanner.ui import theme

_END = "end"


class StreamToQueue:
    """File-like shim that mirrors writes into a queue (so the GUI log can
    display them) while still passing through to the original stream so a
    terminal user still sees output."""

    def __init__(self, q: "queue.Queue[str]", orig) -> None:
        self._q = q
        self._orig = orig

    def write(self, s: str) -> int:
        if s:
            self._q.put(s)
        try:
            self._orig.write(s)
            self._orig.flush()
        except Exception:
            pass
        return len(s)

    def flush(self) -> None:
        try:
            self._orig.flush()
        except Exception:
            pass


class LogConsole(ctk.CTkFrame):
    """A read-only textbox that scan output streams into."""

    def __init__(self, master) -> None:
        super().__init__(master)
        self.textbox = ctk.CTkTextbox(
            self, height=160, state="disabled", font=theme.mono_font(11),
        )
        self.textbox.pack(fill="both", expand=True, padx=6, pady=6)

    def append(self, text: str) -> None:
        self.textbox.configure(state="normal")
        self.textbox.insert(_END, text)
        self.textbox.see(_END)
        self.textbox.configure(state="disabled")

    def clear(self) -> None:
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", _END)
        self.textbox.configure(state="disabled")
