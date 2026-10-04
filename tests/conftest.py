"""pytest bootstrap.

The test modules import shared helpers as ``from support import ...`` so
they also run as plain scripts (``python tests/test_gui_layout.py``).
Under pytest, ``tests/`` is imported as a package, so this directory isn't
on sys.path when the modules are collected — conftest.py is loaded first,
which makes it the right place to fix that.
"""

import os
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
for _entry in (str(_TESTS_DIR.parent / "src"), str(_TESTS_DIR)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

# Must be set before jobscanner.ui_qt.settings is imported: it picks the
# QSettings scope at import. Keeps the suite's window state out of the
# user's real preferences -- a test once failed only because the user's
# last real session had left the log dock open.
os.environ["JOBSCANNER_SETTINGS_APP"] = "PartTimeJobScanner-tests"


@pytest.fixture(autouse=True)
def _isolate_user_data(tmp_path, monkeypatch):
    """Point every defaulted DB/keywords path at a throwaway directory.

    Storage functions resolve ``config.DB_PATH`` at call time, so a test
    that forgets to pass a path lands here instead of in the real
    database. Before this, test fixtures (``last_seen_at='2020-01-01'``)
    leaked into data/jobs.db and from there into the app's copy.
    """
    from jobscanner import config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr(config, "KEYWORDS_PATH", tmp_path / "keywords.json")
    try:
        from jobscanner.ui_qt.settings import app_settings
    except ImportError:  # PySide6 missing; the GUI tests skip themselves
        yield
        return
    app_settings().clear()
    yield
