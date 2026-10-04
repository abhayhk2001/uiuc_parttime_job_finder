"""Where the app keeps its user-writable files (DB, keywords, settings).

Resolution rules:

- Running from source (no ``sys.frozen``): the repo-relative ``data/``
  directory next to ``src/jobscanner/``. This is what every developer
  and CI run uses, and keeps the test fixtures honest.

- Running frozen (PyInstaller .app, etc.): the platform's per-user
  Application Support directory. Putting user data inside the bundle
  itself would break the moment the OS quarantines or replaces the
  app, and writing there is forbidden for signed/notarized apps.

- Installed as a regular (non-editable) package: also the per-user
  directory. There is no repo to sit next to -- ``parents[2]`` of this
  file is then ``<venv>/lib/python3.X``, where the database used to land.

- ``$JOBSCANNER_DATA_DIR``, when set, overrides all of the above. It is
  how a cron scan run from source shares one database with the .app
  instead of quietly keeping a second one.

The first-run case for the frozen app also seeds ``keywords.json`` from
the bundled default so the user has a working keyword list to edit
without having to find the bundled copy.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_DISPLAY_NAME = "UIUC Part-Time Job Scanner"
APP_SLUG = "uiuc-parttime-job-scanner"

# Repo root: src/jobscanner/paths.py -> src/jobscanner -> src -> <repo>
_REPO_ROOT = Path(__file__).resolve().parents[2]
_REPO_DATA_DIR = _REPO_ROOT / "data"
_REPO_KEYWORDS = _REPO_ROOT / "keywords.json"


#: Environment variable that pins the data directory.
DATA_DIR_ENV = "JOBSCANNER_DATA_DIR"


def user_data_dir() -> Path:
    """Return (and create) the per-user writable data directory."""
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        d = Path(override).expanduser()
    elif _uses_app_data_dir():
        d = app_data_dir()
    else:
        d = _REPO_DATA_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def user_db_path() -> Path:
    """The on-disk location of the SQLite database."""
    return user_data_dir() / "jobs.db"


def user_keywords_path() -> Path:
    """The editable keywords.json the GUI reads and writes.

    - Source run: <repo>/keywords.json (matches the historical layout;
      the user can edit it in their editor of choice).
    - Frozen run: <user_data_dir>/keywords.json. Created from the
      bundled default on first launch so the GUI has something to load.
    """
    target = _keywords_root() / "keywords.json"
    if target.exists():
        return target
    default = _bundled_keywords_path()
    if default != target and default.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(default, target)
    return target


# -- internals --------------------------------------------------------------


def _is_frozen() -> bool:
    """True when running inside a PyInstaller bundle or similar."""
    return getattr(sys, "frozen", False)


def _is_source_checkout() -> bool:
    """True when this file sits in the repo, not in site-packages."""
    return (_REPO_ROOT / "pyproject.toml").exists()


def _uses_app_data_dir() -> bool:
    return _is_frozen() or not _is_source_checkout()


def _keywords_root() -> Path:
    """Directory that holds the editable keywords.json.

    - Source run: the repo root (alongside pyproject.toml).
    - Frozen, installed, or ``$JOBSCANNER_DATA_DIR`` set: the data dir,
      so the keywords travel with the database they were matched into.
    """
    if os.environ.get(DATA_DIR_ENV) or _uses_app_data_dir():
        return user_data_dir()
    return _REPO_ROOT


def app_data_dir() -> Path:
    """The platform's per-user data dir -- where the .app keeps its files.

    Public because ``jobscanner import`` and scripts/migrate-to-appdata.py
    copy *into* it while running from source, where user_data_dir() would
    answer with the repo's own data/ directory.
    """
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DISPLAY_NAME
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / APP_DISPLAY_NAME
    # Linux / other Unix: XDG Base Directory spec
    base = os.environ.get("XDG_DATA_HOME") or str(
        Path.home() / ".local" / "share"
    )
    return Path(base) / APP_SLUG


def _bundled_keywords_path() -> Path:
    """The read-only keywords.json that ships with the binary."""
    if _is_frozen():
        # PyInstaller unpacks --add-data entries under sys._MEIPASS.
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / "keywords.json"
    return _REPO_KEYWORDS
