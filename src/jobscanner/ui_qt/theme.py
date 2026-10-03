"""Theme application: pick light vs dark, build QSS, follow OS changes.

Called once at startup from :func:`jobscanner.ui_qt.app.launch` after the
``QApplication`` exists. Also wires up
``QGuiApplication.styleHints().colorSchemeChanged`` so the window flips
when the user toggles macOS dark mode (or Windows "Apps use light theme")
without a restart.

The QSS is intentionally short for the skeleton: it sets window/background
colors and lets the Fusion style own most widget rendering. Subsequent
steps will extend it as the sidebar, table, and detail pane come online.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QObject
from PySide6.QtGui import QGuiApplication, QPalette

from jobscanner.ui_qt import palette as pal_mod
from jobscanner.ui_qt.palette import Palette
from jobscanner.ui_qt.settings import app_settings


_QSS_TEMPLATE = """
QMainWindow,
QDialog {{
    background-color: {bg};
    color: {text};
}}

QToolBar {{
    background: {bg_alt};
    border-bottom: 1px solid {border};
    spacing: 4px;
    padding: 4px;
}}

QStatusBar {{
    background: {bg_alt};
    color: {muted};
    border-top: 1px solid {border};
}}

QMenuBar {{
    background: {bg};
    color: {text};
    border-bottom: 1px solid {border};
}}

QMenuBar::item:selected {{
    background: {accent};
    color: white;
}}

QMenu {{
    background: {bg_alt};
    color: {text};
    border: 1px solid {border};
}}

QMenu::item:selected {{
    background: {accent};
    color: white;
}}

QSplitter::handle {{
    background: {border};
}}
QSplitter::handle:hover {{
    background: {accent};
}}

QDockWidget {{
    color: {text};
    titlebar-close-icon: none;
}}

QDockWidget::title {{
    background: {bg_alt};
    color: {muted};
    padding: 4px 8px;
    border-bottom: 1px solid {border};
}}

QLabel#placeholder {{
    color: {muted};
    font-size: 14px;
}}
"""


_CURRENT_PALETTE: Optional[Palette] = None
_SIGNAL_CONNECTED = False


def current_palette() -> Palette:
    """The palette currently applied. Useful for ad-hoc widget styling."""
    if _CURRENT_PALETTE is None:
        return pal_mod.LIGHT
    return _CURRENT_PALETTE


def _build_qss(p: Palette) -> str:
    return _QSS_TEMPLATE.format(**p)


def _build_qpalette(p: Palette) -> QPalette:
    """Map a small set of palette roles so widgets that ignore QSS still match."""
    qp = QPalette()
    qp.setColor(QPalette.Window, QColor_from_hex(p["bg"]))
    qp.setColor(QPalette.WindowText, QColor_from_hex(p["text"]))
    qp.setColor(QPalette.Base, QColor_from_hex(p["bg_alt"]))
    qp.setColor(QPalette.AlternateBase, QColor_from_hex(p["bg"]))
    qp.setColor(QPalette.Text, QColor_from_hex(p["text"]))
    qp.setColor(QPalette.Button, QColor_from_hex(p["bg_alt"]))
    qp.setColor(QPalette.ButtonText, QColor_from_hex(p["text"]))
    qp.setColor(QPalette.Highlight, QColor_from_hex(p["accent"]))
    qp.setColor(QPalette.HighlightedText, QColor_from_hex("#ffffff"))
    qp.setColor(QPalette.PlaceholderText, QColor_from_hex(p["faint"]))
    qp.setColor(QPalette.ToolTipBase, QColor_from_hex(p["bg_alt"]))
    qp.setColor(QPalette.ToolTipText, QColor_from_hex(p["text"]))
    return qp


def QColor_from_hex(hex_str: str):  # noqa: N802 -- Qt naming
    """Local helper: import QColor lazily so this module is cheap to load."""
    from PySide6.QtGui import QColor

    return QColor(hex_str)


def _detect_palette() -> Palette:
    """Return the palette matching the current OS appearance, honoring
    the user's manual override (Light / Dark / Auto) stored in QSettings.
    """
    # The override key is read here only on first apply; the live listener
    # added in `apply_app` keeps it in sync afterward.
    settings = app_settings()
    override = settings.value("appearance/override", "auto", type=str)
    if override == "light":
        return pal_mod.LIGHT
    if override == "dark":
        return pal_mod.DARK
    # Auto: follow the OS via QStyleHints.
    hints = QGuiApplication.styleHints()
    scheme = hints.colorScheme()
    if scheme == Qt.ColorScheme.Dark:
        return pal_mod.DARK
    return pal_mod.LIGHT


def apply_app(app: QObject) -> None:
    """Set the global style + palette + QSS, and follow OS scheme changes.

    Pass the ``QApplication`` instance. Idempotent: safe to call twice.
    """
    global _CURRENT_PALETTE

    # Use the Fusion style for a consistent cross-platform look. The macOS
    # default style would also work; Fusion wins because it respects QSS
    # the same way on every platform.
    app.setStyle("Fusion")

    p = _detect_palette()
    _set_palette_and_qss(app, p)

    # Live-update when the OS appearance flips while the app is running.
    # Track connection state to avoid PySide6's disconnect warning on first
    # call (when no prior connection exists).
    global _SIGNAL_CONNECTED
    hints = QGuiApplication.styleHints()
    if not _SIGNAL_CONNECTED:
        hints.colorSchemeChanged.connect(_on_color_scheme_changed)
        _SIGNAL_CONNECTED = True


def _on_color_scheme_changed(_scheme) -> None:
    app = QGuiApplication.instance()
    if app is None:
        return
    override = app_settings().value("appearance/override", "auto", type=str)
    if override != "auto":
        return  # user picked a fixed mode; OS changes are ignored
    p = pal_mod.DARK if _scheme == Qt.ColorScheme.Dark else pal_mod.LIGHT
    _set_palette_and_qss(app, p)


def _set_palette_and_qss(app: QObject, p: Palette) -> None:
    global _CURRENT_PALETTE
    _CURRENT_PALETTE = p
    app.setPalette(_build_qpalette(p))
    app.setStyleSheet(_build_qss(p))
