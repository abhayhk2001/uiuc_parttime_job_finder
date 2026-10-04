#!/usr/bin/env python3
"""Migrate the source-tree database into the bundled app's AppData location.

When you switch from running the CLI / GUI from source to running the
PyInstaller .app, the app starts reading from the platform's per-user
AppData directory (e.g. ``~/Library/Application Support/UIUC Part-Time
Job Scanner/`` on macOS). The database you accumulated by running
``python main.py`` lives next to the source, in ``data/jobs.db``.

Run this script once after a clean install of the .app to copy your
existing source-tree data into the AppData directory the .app uses:

    python scripts/migrate-to-appdata.py

What it copies:

- ``data/jobs.db``              -> ``<AppData>/jobs.db``
- ``data/jobs.db.bak.*``        -> ``<AppData>/jobs.db.bak.*``
- ``keywords.json`` (at the repo root) -> ``<AppData>/keywords.json``

Safety:

- Defaults to dry-run; pass ``--apply`` to actually copy.
- Refuses to replace a destination database that already holds jobs
  unless ``--force`` is passed. An empty one -- what the first launch of
  the .app creates -- is replaced without asking.
- Keeps anything it replaces as ``<name>.pre-import-<UTC-timestamp>``.

The copying itself lives in :mod:`jobscanner.migrate`, shared with the
``jobscanner import`` command.

Afterwards, scans you run from source (``python main.py``, cron) still
write to ``data/jobs.db``. Set ``JOBSCANNER_DATA_DIR`` to the AppData
directory for those runs to keep a single database.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make `jobscanner` importable when invoked as a plain script.
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR.parent / "src"))

from jobscanner import migrate, paths  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--apply", action="store_true",
                   help="Actually copy the files (default: dry-run).")
    p.add_argument("--force", action="store_true",
                   help="Replace a destination DB that already holds jobs.")
    p.add_argument("--source", type=Path,
                   default=_SCRIPT_DIR.parent / "data",
                   help="Source directory (default: <repo>/data).")
    p.add_argument("--keywords-source", type=Path,
                   default=_SCRIPT_DIR.parent / "keywords.json",
                   help="Source keywords.json (default: <repo>/keywords.json).")
    args = p.parse_args(argv)

    # The .app's directory, not paths.user_data_dir(): this script runs
    # from source, where that would answer with the source dir itself.
    return migrate.import_data(args.source, args.keywords_source,
                               paths.app_data_dir(),
                               force=args.force, dry_run=not args.apply)


if __name__ == "__main__":
    sys.exit(main())
