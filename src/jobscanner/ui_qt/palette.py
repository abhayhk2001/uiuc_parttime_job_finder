"""Color tokens for the Qt UI.

Two parallel dicts -- ``LIGHT`` and ``DARK`` -- keyed by semantic role. The
:mod:`jobscanner.ui_qt.theme` module picks one at startup and assembles a
QSS stylesheet from it. Adding a new color means adding it to both dicts;
naming is intentional so a designer can read either file in isolation.
"""

from __future__ import annotations

from typing import TypedDict


class Palette(TypedDict):
    bg: str
    bg_alt: str
    border: str
    text: str
    muted: str
    faint: str
    accent: str
    accent_hover: str
    success: str
    success_hover: str
    warning: str
    warning_hover: str
    match_fg: str
    match_reviewed_fg: str
    reviewed_fg: str
    link: str
    chip_bg: str
    chip_text: str


LIGHT: Palette = {
    "bg": "#f6f7f9",
    "bg_alt": "#ffffff",
    "border": "#d8dbe0",
    "text": "#1c1e22",
    "muted": "#6a707a",
    "faint": "#9aa0a8",
    "accent": "#1f6aa5",
    "accent_hover": "#2680c6",
    "success": "#0d8050",
    "success_hover": "#11965e",
    "warning": "#9b6b00",
    "warning_hover": "#b07a00",
    "match_fg": "#0a6640",
    "match_reviewed_fg": "#4a7c4a",
    "reviewed_fg": "#7a7a7a",
    "link": "#1d4ed8",
    "chip_bg": "#1f6aa5",
    "chip_text": "#ffffff",
}


DARK: Palette = {
    "bg": "#1d1f23",
    "bg_alt": "#26292e",
    "border": "#353941",
    "text": "#e6e8ec",
    "muted": "#9aa0a8",
    "faint": "#6a707a",
    "accent": "#4d9ee0",
    "accent_hover": "#65b0ea",
    "success": "#3ec285",
    "success_hover": "#5fd09c",
    "warning": "#e0b54a",
    "warning_hover": "#ecc25f",
    "match_fg": "#9be29b",
    "match_reviewed_fg": "#7ea67e",
    "reviewed_fg": "#7a7a7a",
    "link": "#7eb6ff",
    "chip_bg": "#4d9ee0",
    "chip_text": "#0f1115",
}


def is_dark(palette: Palette) -> bool:
    """True when the palette is the dark variant. Used to pick QSS rules."""
    return palette is DARK
