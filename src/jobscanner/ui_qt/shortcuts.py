"""Platform-aware accelerator prefix and tiny shortcut helpers.

Centralised so every QShortcut and QAction sequence in the app agrees on
``Cmd`` (macOS) vs ``Ctrl`` (everything else). Mirrors the
``sys.platform`` check the old CTk UI did inline at
``jobscanner.ui.app:178``.
"""

from __future__ import annotations

import sys


def accel() -> str:
    """Human-readable accelerator for menus and labels (``"Cmd"`` or ``"Ctrl"``)."""
    return "Cmd" if sys.platform == "darwin" else "Ctrl"


def sequence(scoped: str) -> str:
    """Build a ``QKeySequence``-parseable string.

    Pass the bare key name (``"F"``, ``"Q"``, ``"Return"``, ...); this
    helper prepends the platform accelerator.

    On macOS Qt expects the modifier name ``Meta``, not ``Cmd``. The
    human-readable ``Cmd`` is reserved for menu labels, where the OS
    rewrites it at draw time.
    """
    if scoped in {"Return", "Enter", "Escape", "Esc", "Tab", "Backtab",
                  "Space", "Left", "Right", "Up", "Down"}:
        return scoped
    modifier = "Meta" if sys.platform == "darwin" else "Ctrl"
    return f"{modifier}+{scoped}"
