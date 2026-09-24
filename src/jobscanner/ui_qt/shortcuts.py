"""Platform-aware accelerator prefix and tiny shortcut helpers.

Centralised so every QShortcut and QAction sequence in the app agrees on
``Cmd`` (macOS) vs ``Ctrl`` (everything else). Mirrors the
``sys.platform`` check the old CTk UI did inline at
``jobscanner.ui.app:178``.
"""

from __future__ import annotations

import sys


def accel() -> str:
    """Return ``"Cmd"`` on macOS, ``"Ctrl"`` elsewhere."""
    return "Cmd" if sys.platform == "darwin" else "Ctrl"


def sequence(scoped: str) -> str:
    """Build a QKeySequence string, e.g. ``sequence("F")`` -> ``"Ctrl+F"``.

    Pass the bare key name; this helper prepends the platform accelerator.
    ``"Return"`` and ``"Escape"`` stay as-is since they have no
    Cmd/Ctrl meaning.
    """
    if scoped in {"Return", "Enter", "Escape", "Esc", "Tab", "Backtab",
                  "Space", "Left", "Right", "Up", "Down"}:
        return scoped
    return f"{accel()}+{scoped}"
