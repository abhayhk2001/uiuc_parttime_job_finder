"""Shared test helpers: assertions, temp databases, and GUI fixtures.

No pytest dependency — every test module here runs as a plain script and
also works under pytest. Import this via ``from support import ...``; the
path setup in :func:`bootstrap` makes that work either way.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional


def bootstrap() -> Path:
    """Put ``src/`` and this directory on sys.path. Returns the repo root.

    Call at the top of every test module, before importing ``jobscanner``.
    """
    tests_dir = Path(__file__).resolve().parent
    repo_root = tests_dir.parent
    for entry in (str(repo_root / "src"), str(tests_dir)):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    return repo_root


REPO_ROOT = bootstrap()


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------

class TestFailed(AssertionError):
    pass


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise TestFailed(msg)


def eq(a, b, msg: str = "") -> None:
    if a != b:
        raise TestFailed(f"{msg}: expected {b!r}, got {a!r}")


# ---------------------------------------------------------------------------
# Temp databases
# ---------------------------------------------------------------------------

class TempDB:
    """Yields a fresh DB path inside a temp dir, cleaning up afterwards.

    Tests must never touch the user's real ``data/jobs.db``; this is the
    pattern every test in this repo uses.
    """

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
    """Can we build a Tk window here? Returns (ok, reason-if-not).

    The GUI suite skips rather than fails on a headless box or an install
    without customtkinter, so the storage tests still mean something there.
    """
    try:
        import customtkinter  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return False, f"customtkinter unavailable ({exc})"
    try:
        import tkinter
        root = tkinter.Tk()
        root.destroy()
    except Exception as exc:  # noqa: BLE001
        return False, f"no display ({exc})"
    return True, ""


DEFAULT_KEYWORDS = ["python", "data"]


def seed_jobs(
    db,
    path: Path,
    count: int = 6,
    match_every: int = 2,
    with_details: bool = True,
) -> str:
    """Insert `count` jobs, every `match_every`-th one matching a keyword.

    Returns the scan cutoff, captured *before* the inserts so every row is
    unambiguously "New" — ``now_iso()`` is second-precision, so taking it
    afterwards races the inserts and makes tests flaky.
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
def gui_app(count: int = 6, match_every: int = 2,
            geometry: str = "1380x860", **seed_kwargs) -> Iterator[tuple]:
    """Yield ``(app, db_path, keywords_path)`` backed by a throwaway DB.

    The window is destroyed and the temp dir removed on exit, even if the
    test raises.
    """
    from jobscanner import storage as db
    from jobscanner.ui import app as gui

    with TempDB(prefix="jobscanner_gui_") as db_path:
        keywords_path = db_path.parent / "keywords.json"
        keywords_path.write_text(json.dumps(DEFAULT_KEYWORDS))
        seed_jobs(db, db_path, count=count, match_every=match_every,
                  **seed_kwargs)
        app = gui.JobScannerApp(db_path, keywords_path)
        app.geometry(geometry)
        app.update()
        try:
            yield app, db_path, keywords_path
        finally:
            _teardown(app)


def _teardown(app) -> None:
    """Destroy `app`, cancelling anything it still has scheduled.

    customtkinter keeps its own `after` callbacks alive (DPI polling, widget
    updates). A real run exits the process so they never fire, but a test
    process that builds and tears down many windows sees them fire against
    dead widgets and Tk writes the traceback straight to stderr.
    """
    try:
        for after_id in app.tk.eval("after info").split():
            try:
                app.after_cancel(after_id)
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass
    try:
        app.destroy()
    except Exception:  # noqa: BLE001
        pass
    try:
        app.update()
    except Exception:  # noqa: BLE001
        pass


def widget_box(widget) -> tuple[int, int, int, int]:
    """(x, y, width, height) of a widget in screen coordinates."""
    return (widget.winfo_rootx(), widget.winfo_rooty(),
            widget.winfo_width(), widget.winfo_height())


@contextmanager
def answer_dialogs(answer: bool) -> Iterator[list]:
    """Stub messagebox.askokcancel so confirmations can be driven headlessly.

    Yields a list that records the title of every prompt raised.
    """
    from tkinter import messagebox

    asked: list = []
    original = messagebox.askokcancel

    def _stub(title="", message="", **kwargs):
        asked.append(title)
        return answer

    messagebox.askokcancel = _stub
    try:
        yield asked
    finally:
        messagebox.askokcancel = original


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_module(namespace: dict, title: str = "",
               skip_reason: str = "") -> tuple[int, int, int]:
    """Run every ``test_*`` callable in `namespace`. Returns (pass, fail, skip).

    Discovery is automatic rather than a hand-maintained list, so a new test
    can't silently go unrun.
    """
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
