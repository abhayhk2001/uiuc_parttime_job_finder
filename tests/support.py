"""Shared test helpers for the Qt-port test suite.

Public API mirrors the old Tk-support module so the test files can port
mechanically:

  TempDB, seed_jobs        -- unchanged
  qt_app() / gui_app()     -- equivalent context manager that builds a
                              QApplication + JobScannerApp against a
                              throwaway DB
  check / eq               -- unchanged
  run_module               -- unchanged
  widget_box               -- (x, y, width, height) in screen coords
  answer_dialogs           -- stub QMessageBox.question
  gui_available            -- check PySide6 + a working QApplication

Differences from the Tk version, called out where they matter:

  - app.update()             -> app.processEvents()
  - app.geometry("WxH")      -> app.resize(W, H)
  - app.winfo_*              -> Qt geometry accessors (see widget_box)
  - app.tk.eval("after info") -> app.findChildren(type) for timer cleanup
  - tk_popup on a Menu       -> contextMenuRequested signal + QMenu.popup
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

# Always add src/ + tests/ to sys.path so both `pytest` and `python tests/foo.py`
# work without a conftest dance.
REPO_ROOT = Path(__file__).resolve().parent.parent
for _entry in (str(REPO_ROOT / "src"), str(REPO_ROOT / "tests")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from PySide6.QtWidgets import QApplication  # noqa: E402


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------


class TestFailed(AssertionError):
    """Raised by `check` / `eq` when a test expectation fails."""


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise TestFailed(msg)


def eq(actual, expected, msg: str = "") -> None:
    if actual != expected:
        raise TestFailed(f"{msg}: expected {expected!r}, got {actual!r}")


# ---------------------------------------------------------------------------
# Temp databases
# ---------------------------------------------------------------------------


class TempDB:
    """Yields a fresh DB path inside a temp dir, cleaning up afterwards."""

    def __init__(self, prefix: str = "jobscanner_test_") -> None:
        self.prefix = prefix
        self.dir: Optional[Path] = None
        self.path: Optional[Path] = None

    def __enter__(self) -> Path:
        self.dir = Path(tempfile.mkdtemp(prefix=self.prefix))
        self.path = self.dir / "jobs.db"
        return self.path

    def __exit__(self, *exc) -> None:
        if self.dir and self.dir.exists():
            shutil.rmtree(self.dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# GUI fixtures
# ---------------------------------------------------------------------------


def gui_available() -> tuple[bool, str]:
    """Can we build a Qt window here? Returns (ok, reason-if-not).

    Skips the GUI suite on a headless box or an install without PySide6,
    so the storage tests still mean something there.
    """
    try:
        import PySide6  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return False, f"PySide6 unavailable ({exc})"
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        if app is None:
            return False, "no display"
    except Exception as exc:  # noqa: BLE001
        return False, f"no display ({exc})"
    return True, ""


DEFAULT_KEYWORDS = ["python", "data"]


def seed_jobs(db, path: Path, count: int = 6, match_every: int = 2,
              with_details: bool = True) -> str:
    """Insert `count` jobs, every `match_every`-th one matching a keyword.

    Returns the scan cutoff, captured *before* the inserts so every row
    is unambiguously "New".
    """
    db.init_db(path)
    cutoff = db.now_iso()
    for i in range(count):
        db.upsert_listing(
            {
                "job_id": f"T{i}",
                "title": f"Job {i}",
                "company": f"Dept {i}",
                "date_posted": "",
                "detail_url": f"https://example.org/{i}",
            },
            path=path,
        )
        if with_details:
            db.update_details(
                f"T{i}",
                f"needs python {i}" if i % match_every == 0 else f"body {i}",
                "requirements text",
                "skills text",
                ["python"] if i % match_every == 0 else [],
                path,
            )
    db.set_latest_scan_started_at(cutoff, path)
    return cutoff


@contextmanager
def qt_app(count: int = 6, match_every: int = 2,
           size: tuple[int, int] = (1380, 860),
           **seed_kwargs) -> Iterator[tuple]:
    """Yield ``(app, db_path, keywords_path)`` backed by a throwaway DB.

    Builds (or reuses) a QApplication, constructs a JobScannerApp, calls
    ``processEvents()`` so the window's widget tree is realised, then
    yields. On exit, cancels any pending QTimers, schedules the window
    for deletion, and processes events so the deletion fires cleanly.
    """
    from jobscanner import storage as db
    from jobscanner.ui_qt import app as gui

    # QApplication must be constructed exactly once per process. Pytest
    # runs tests in the same interpreter and threads, so we reuse the
    # existing instance if any. Use a sanitised argv: pytest's argv
    # has flags (e.g. "-s") that QApplication rejects.
    argv = sys.argv[:1] if QApplication.instance() is None else []

    with TempDB(prefix="jobscanner_gui_") as db_path:
        keywords_path = db_path.parent / "keywords.json"
        keywords_path.write_text(json.dumps(DEFAULT_KEYWORDS))
        seed_jobs(db, db_path, count=count, match_every=match_every,
                  **seed_kwargs)
        if QApplication.instance() is None:
            QApplication(argv)
        app = gui.JobScannerApp(db_path, keywords_path)
        app.resize(*size)
        # Make sure the widget tree is realised before the test inspects it.
        app.show()
        pump_events()
        try:
            yield app, db_path, keywords_path
        finally:
            _teardown(app)


# Back-compat alias: the old tests used `gui_app`. Keep that name as an
# alias so the test files port cleanly.
gui_app = qt_app


def _teardown(app) -> None:
    """Cancel any pending QTimers and schedule the window for deletion.

    The Qt event loop keeps firing after a window is destroyed unless we
    cancel the scheduled callbacks (palette refresh, log drain, etc.).
    A long test run would otherwise leak and eventually crash.
    """
    from PySide6.QtCore import QTimer

    try:
        for timer in app.findChildren(QTimer):
            timer.stop()
    except Exception:  # noqa: BLE001
        pass
    try:
        app.close()
    except Exception:  # noqa: BLE001
        pass
    try:
        app.deleteLater()
    except Exception:  # noqa: BLE001
        pass
    try:
        QApplication.processEvents()
    except Exception:  # noqa: BLE001
        pass


def pump_events() -> None:
    """Drain pending Qt events.

    Replacement for Tk's ``app.update()``. Tests call this after a state
    change (selecting a row, opening a dialog, setting a filter) to let
    the model/proxy/view settle before the test reads widget state.
    """
    QApplication.processEvents()


def widget_box(widget) -> tuple[int, int, int, int]:
    """(x, y, width, height) of a widget in screen coordinates.

    Qt widgets must be shown for `geometry()` to return real values;
    this helper ensures the widget is realised before reading it. The
    returned ``(x, y)`` is the widget's top-left in screen pixels.
    """
    if not widget.isVisible():
        widget.show()
        QApplication.processEvents()
    rect = widget.geometry()
    top_left = widget.mapToGlobal(rect.topLeft())
    return (top_left.x(), top_left.y(), rect.width(), rect.height())


@contextmanager
def answer_dialogs(answer: bool) -> Iterator[list]:
    """Stub QMessageBox.question so destructive confirmations can be driven.

    Yields a list that records every confirmation prompt raised. Each
    prompt is auto-answered with ``answer``.
    """
    from PySide6.QtWidgets import QMessageBox

    asked: list = []
    original = QMessageBox.question

    def _stub(parent=None, title="", text="", *args, **kwargs):
        asked.append(title)
        return QMessageBox.Yes if answer else QMessageBox.No

    QMessageBox.question = _stub
    try:
        yield asked
    finally:
        QMessageBox.question = original


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_module(namespace: dict, title: str = "",
               skip_reason: str = "") -> tuple[int, int, int]:
    """Run every ``test_*`` callable in ``namespace``."""
    tests = [
        (name, obj) for name, obj in sorted(namespace.items())
        if name.startswith("test_") and callable(obj)
    ]
    if title:
        print(f"\n{title}")
    if skip_reason:
        for name, _ in tests:
            print(f"  skip  {name}")
        print(f"\n0 passed, 0 failed, {len(tests)} skipped ({skip_reason}).")
        return 0, 0, len(tests)

    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
        except TestFailed as exc:
            failed += 1
            print(f"  FAIL  {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {name}: {exc!r}")
        else:
            passed += 1
            print(f"  ok    {name}")
    print()
    print(f"{passed} passed, {failed} failed.")
    return passed, failed, 0
