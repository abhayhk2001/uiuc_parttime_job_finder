"""One place for every color, font and spacing decision in the GUI.

Colors are CustomTkinter ``(light, dark)`` pairs. The ttk Treeview -- the
only non-ctk widget in the app -- is styled from these same tokens so the
table can't drift away from the rest of the window.

Fonts are functions, not constants: ``CTkFont`` needs a live Tk root, so
they must be built after the window exists.
"""

from __future__ import annotations

import customtkinter as ctk
from tkinter import ttk

APPEARANCE_MODE = "dark"
COLOR_THEME = "blue"

# -- palette ---------------------------------------------------------------

ACCENT = ("#1f6aa5", "#154a78")
ACCENT_HOVER = ("#2680c6", "#1a5a90")
SUCCESS = ("#0d8050", "#0a6640")
SUCCESS_HOVER = ("#11965e", "#0d7a4a")
WARNING = ("#9b6b00", "#7a5100")
WARNING_HOVER = ("#b07a00", "#8a5e00")

BODY_TEXT = ("gray10", "gray90")
MUTED_TEXT = ("gray40", "gray70")
FAINT_TEXT = ("gray50", "gray60")
KEYWORD_TEXT = ("gray20", "gray85")
LINK_TEXT = ("#1d4ed8", "#7eb6ff")

OUTLINE_BORDER = ("gray60", "gray40")
OUTLINE_HOVER = ("gray80", "gray25")
OUTLINE_TEXT = ("gray30", "gray85")

HOVER_NEUTRAL = ("gray70", "gray30")
DIVIDER = ("gray75", "gray25")
SASH = ("gray70", "#2a2a2a")
SASH_ACTIVE = ACCENT

CHIP_BG = ACCENT
CHIP_TEXT = "white"

#: Button styles referenced by name from `job_actions`, so the state
#: machine never has to know a hex value.
BUTTON_STYLES: dict[str, dict] = {
    "accent": {"fg_color": ACCENT, "hover_color": ACCENT_HOVER},
    "success": {"fg_color": SUCCESS, "hover_color": SUCCESS_HOVER},
    "warning": {"fg_color": WARNING, "hover_color": WARNING_HOVER},
}

#: Transparent/bordered look used for secondary buttons.
OUTLINE_BUTTON: dict = {
    "fg_color": "transparent",
    "text_color": OUTLINE_TEXT,
    "border_width": 1,
    "border_color": OUTLINE_BORDER,
    "hover_color": OUTLINE_HOVER,
}

# -- treeview --------------------------------------------------------------

TREE_BG = "#2b2b2b"
TREE_FG = "#e6e6e6"
TREE_HEADING_BG = "#3a3a3a"
TREE_HEADING_ACTIVE = "#4a4a4a"
TREE_SELECTED_BG = "#1f6aa5"
TREE_SELECTED_FG = "#ffffff"
TREE_ROW_HEIGHT = 24

#: Row tag -> foreground. Bright green = matched and unreviewed; dim green =
#: matched but reviewed; gray = reviewed, no match; default = neither.
TREE_TAG_COLORS: dict[str, str] = {
    "match": "#9be29b",
    "match_reviewed": "#7ea67e",
    "reviewed": "#7a7a7a",
    "default": "#d0d0d0",
}

# -- spacing ---------------------------------------------------------------

PAD = 8
PAD_SMALL = 4
PAD_LARGE = 12

MONO_FAMILY = "Menlo"


def apply_appearance() -> None:
    """Set the process-wide CustomTkinter appearance. Call once, early."""
    ctk.set_appearance_mode(APPEARANCE_MODE)
    ctk.set_default_color_theme(COLOR_THEME)


def heading_font(size: int = 13) -> ctk.CTkFont:
    return ctk.CTkFont(size=size, weight="bold")


def title_font(size: int = 15) -> ctk.CTkFont:
    return ctk.CTkFont(size=size, weight="bold")


def body_font(size: int = 12) -> ctk.CTkFont:
    return ctk.CTkFont(size=size)


def mono_font(size: int = 12) -> ctk.CTkFont:
    return ctk.CTkFont(family=MONO_FAMILY, size=size)


def style_treeview(widget) -> None:
    """Apply the table styling to the ttk theme backing `widget`."""
    style = ttk.Style(widget)
    for name in ("clam", "alt", "default"):
        try:
            style.theme_use(name)
            break
        except Exception:
            continue
    style.configure(
        "Treeview",
        background=TREE_BG,
        fieldbackground=TREE_BG,
        foreground=TREE_FG,
        bordercolor=TREE_BG,
        rowheight=TREE_ROW_HEIGHT,
    )
    style.configure(
        "Treeview.Heading",
        background=TREE_HEADING_BG,
        foreground=TREE_FG,
        relief="flat",
    )
    style.map("Treeview.Heading", background=[("active", TREE_HEADING_ACTIVE)])
    style.map(
        "Treeview",
        background=[("selected", TREE_SELECTED_BG)],
        foreground=[("selected", TREE_SELECTED_FG)],
    )
