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

    The modifier is spelled ``Ctrl`` on every platform: on macOS Qt maps
    ``Ctrl`` to the Command key and ``Meta`` to the Control key, so
    ``Meta`` here bound every shortcut to Control. The human-readable
    ``Cmd`` from :func:`accel` is only for labels.
    """
    if scoped in {"Return", "Enter", "Escape", "Esc", "Tab", "Backtab",
                  "Space", "Left", "Right", "Up", "Down"}:
        return scoped
    return f"Ctrl+{scoped}"
