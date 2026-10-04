"""Smoke test for the skeleton: imports, QApplication, theme, window build.

Run with: .venv/bin/python tests/smoke_skeleton.py
Does NOT enter the event loop -- just builds everything and exits.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Keep this script's window state and data out of the real app's: its own
# QSettings scope, and a throwaway DB instead of config.DB_PATH.
os.environ["JOBSCANNER_SETTINGS_APP"] = "PartTimeJobScanner-Smoke"

from PySide6.QtCore import QCoreApplication, QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from support import TempDB  # noqa: E402

from jobscanner import storage as db  # noqa: E402
from jobscanner.ui_qt import palette, shortcuts, theme  # noqa: E402
from jobscanner.ui_qt.app import JobScannerApp  # noqa: E402


def _is_dark(p) -> bool:
    return p is palette.DARK


def main() -> int:
    with TempDB() as db_path:
        db.init_db(db_path)
        return _main(db_path)


def _main(db_path: Path) -> int:
    QCoreApplication.setOrganizationName("UIUC")
    QCoreApplication.setApplicationName("PartTimeJobScanner-Smoke")

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationDisplayName("UIUC Part-Time Job Scanner")

    # Wipe any prior override from previous runs.
    QSettings().remove("appearance/override")

    theme.apply_app(app)
    auto = theme.current_palette()
    print(f"theme applied; auto-detected = {'dark' if _is_dark(auto) else 'light'}")

    # Test override to dark.
    QSettings().setValue("appearance/override", "dark")
    forced = theme._detect_palette()
    assert forced is palette.DARK, f"override=dark should force DARK, got {forced}"
    theme._set_palette_and_qss(app, forced)
    print(f"override=dark -> {'dark' if _is_dark(theme.current_palette()) else 'light'}")

    # Test override to light.
    QSettings().setValue("appearance/override", "light")
    forced = theme._detect_palette()
    assert forced is palette.LIGHT
    theme._set_palette_and_qss(app, forced)
    print(f"override=light -> {'dark' if _is_dark(theme.current_palette()) else 'light'}")

    # Back to auto.
    QSettings().setValue("appearance/override", "auto")
    theme._set_palette_and_qss(app, theme._detect_palette())
    print(f"override=auto -> {'dark' if _is_dark(theme.current_palette()) else 'light'}")

    # Verify calling apply_app twice is idempotent (no warnings).
    theme.apply_app(app)
    theme.apply_app(app)
    print("apply_app is idempotent")

    # Build the window (no show, no exec).
    w = JobScannerApp(db_path, db_path.parent / "keywords.json")
    assert w.windowTitle() == "UIUC Part-Time Job Scanner"
    assert w.minimumWidth() == 1080 and w.minimumHeight() == 640
    assert w.centralWidget() is not None
    assert w.splitter is w.centralWidget()
    print(f"window title       = {w.windowTitle()}")
    print(f"window min size    = {w.minimumWidth()}x{w.minimumHeight()}")
    print(f"window actual size = {w.size().width()}x{w.size().height()}")
    print(f"central widget     = {type(w.centralWidget()).__name__}")
    print(f"splitter children  = {len(w.splitter.children())}")

    menus = w.menuBar().findChildren(QMenu)
    print(f"menus              = {[m.title().replace('&', '') for m in menus]}")
    print(f"actions            = {sorted(vars(w.actions).keys())}")
    print(f"toolbar            = {w.toolbar.objectName()}")
    print(f"status message     = {w.status_bar.currentMessage()}")


    # Save + restore geometry round-trip.
    w.resize(1200, 700)
    w.closeEvent  # no-op access to ensure attribute exists
    geo = w.saveGeometry()
    state = w.saveState()
    QSettings().setValue("window/geometry", geo)
    QSettings().setValue("window/state", state)

    w2 = JobScannerApp(db_path, db_path.parent / "keywords.json")
    print(f"restored size      = {w2.size().width()}x{w2.size().height()}")

    print("skeleton smoke test OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
