"""Minimal helpers for the storage-layer tests.

The old ``support.py`` also bootstrapped the GUI test harness, which is
gone (the GUI now uses Qt). What's left is just the bits ``test_db_isolated``
needs: a temp DB context manager and a couple of assertion helpers.

Run with pytest::

    pytest tests/test_db_isolated.py

Or as a plain script (each test module is self-runnable)::

    python tests/test_db_isolated.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from typing import Iterator

REPO_ROOT = Path(__file__).resolve().parent.parent


def bootstrap() -> None:
    """Add ``src/`` and ``tests/`` to ``sys.path`` so plain-script runs work."""
    for entry in (str(REPO_ROOT / "src"), str(REPO_ROOT / "tests")):
        if entry not in sys.path:
            sys.path.insert(0, entry)


# Always bootstrap on import -- pytest's conftest.py also does this, but
# plain ``python tests/test_db_isolated.py`` doesn't go through conftest.
bootstrap()


class TempDB:
    """Context manager: creates a throwaway SQLite DB and yields its path.

    The DB lives in a ``tempfile.mkdtemp`` directory that is removed when
    the context exits (success or failure), so tests never touch the
    user's real ``data/jobs.db``.
    """

    def __init__(self, prefix: str = "jobscanner_test_") -> None:
        self._prefix = prefix
        self._dir: tempfile.TemporaryDirectory | None = None
        self.path: Path | None = None

    def __enter__(self) -> Path:
        self._dir = tempfile.TemporaryDirectory(prefix=self._prefix)
        self.path = Path(self._dir.name) / "jobs.db"
        return self.path

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._dir is not None:
            self._dir.cleanup()
            self._dir = None
        self.path = None


# -- tiny assertion helpers (inlined so we don't pull in pytest here) ---

_failures: list[str] = []


def _record(failure: str) -> None:
    _failures.append(failure)
    print(f"  FAIL: {failure}")


def check(condition: bool, message: str) -> None:
    if not condition:
        _record(message)


def eq(actual, expected, message: str = "") -> None:
    if actual != expected:
        _record(f"{message}: expected {expected!r}, got {actual!r}")


def run_module(tests: dict, title: str,
               skip_reason: str = "") -> tuple[int, int, int]:
    """Run every function in ``tests`` whose name starts with ``test_``.

    Mirrors the old GUI-test harness. Returns ``(passed, failed, skipped)``.
    """
    print(f"\n--- {title} ---")
    passed = failed = skipped = 0
    for name, fn in tests.items():
        if not name.startswith("test_"):
            continue
        if skip_reason:
            print(f"  SKIP: {name} ({skip_reason})")
            skipped += 1
            continue
        _failures.clear()
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            _record(f"{name}: raised {type(exc).__name__}: {exc}")
        if _failures:
            failed += 1
        else:
            print(f"  PASS: {name}")
            passed += 1
    return passed, failed, skipped


# -- GUI helpers (kept as a stub so anything else that imports them doesn't
# break; the GUI smoke tests use their own bootstrap). ---

def gui_available() -> tuple[bool, str]:
    """True if Qt is importable. Used by tests that skip on headless boxes."""
    try:
        import PySide6  # noqa: F401
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"PySide6 unavailable: {exc}"
