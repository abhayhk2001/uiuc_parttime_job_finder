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

- Backs up anything already at the destination (``jobs.db`` ->
  ``jobs.db.bak.<UTC-timestamp>``) before overwriting, so a second
  invocation is also safe.
- Refuses to clobber a destination DB that is newer than the source
  unless ``--force`` is passed.
- Defaults to dry-run; pass ``--apply`` to actually copy.

Note on destinations: the destination is the *frozen* AppData path
unconditionally. If you're running this script to set up local AppData
*while still running from source* (i.e. before the .app is even
launched), that's exactly the right behavior -- copy repo data into
the AppData location so the next .app launch sees it.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make `jobscanner` importable when invoked as a plain script.
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR.parent / "src"))


def _frozen_style_appdata_dir() -> Path:
    """Same path ``jobscanner.paths.user_data_dir()`` picks when frozen.

    Duplicated here because this script is itself unfrozen -- if we
    called ``paths.user_data_dir()`` it would resolve to the source
    directory, which is also the source we are copying *from*.
    """
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "UIUC Part-Time Job Scanner"
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "UIUC Part-Time Job Scanner"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "uiuc-parttime-job-scanner"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")


def _safe_copy(src: Path, dst: Path, dry_run: bool) -> str:
    """Return a human-readable description of what would happen / happened."""
    if not src.exists():
        return f"  skip {src.name} (source missing)"
    if dst.exists():
        return f"  would overwrite {dst} ({src.stat().st_size:,} bytes)"
    return f"  would copy {src.name} -> {dst} ({src.stat().st_size:,} bytes)"


def _do_copy(src: Path, dst: Path) -> str:
    if not src.exists():
        return f"  skip {src.name} (source missing)"
    if dst.exists():
        # Back up the destination first so the script is rerunnable.
        backup = dst.with_name(f"{dst.name}.bak.{_utc_stamp()}")
        shutil.copyfile(dst, backup)
        backed = f" (backed up to {backup.name})"
    else:
        backed = ""
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return f"  copied {src.name} -> {dst} ({src.stat().st_size:,} bytes){backed}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--apply", action="store_true",
                   help="Actually copy the files (default: dry-run).")
    p.add_argument("--force", action="store_true",
                   help="Overwrite a newer destination DB without prompting.")
    p.add_argument("--source", type=Path,
                   default=_SCRIPT_DIR.parent / "data",
                   help="Source directory (default: <repo>/data).")
    p.add_argument("--keywords-source", type=Path,
                   default=_SCRIPT_DIR.parent / "keywords.json",
                   help="Source keywords.json (default: <repo>/keywords.json).")
    args = p.parse_args(argv)

    source_dir = args.source
    keywords_src = args.keywords_source
    # Bypass ``paths.user_data_dir()`` -- this script is itself unfrozen,
    # so that helper would resolve to the source directory. Force the
    # frozen-mode AppData path so copying actually moves the data out of
    # the source tree and into the location the .app reads.
    dest_dir = _frozen_style_appdata_dir()

    print(f"Source data dir:  {source_dir}")
    print(f"Source keywords:  {keywords_src}")
    print(f"Destination:      {dest_dir}")
    print()

    # Plan the operations.
    operations: list[tuple[Path, Path]] = []
    if (source_dir / "jobs.db").exists():
        operations.append((source_dir / "jobs.db", dest_dir / "jobs.db"))
    for bak in sorted(source_dir.glob("jobs.db.bak.*")):
        operations.append((bak, dest_dir / bak.name))
    if keywords_src.exists():
        operations.append((keywords_src, dest_dir / "keywords.json"))

    if not operations:
        print("Nothing to migrate: no source data found.")
        return 0

    # Refuse to clobber a newer destination unless --force.
    for src, dst in operations:
        if not args.force and src.name == "jobs.db" and dst.exists():
            src_mtime = src.stat().st_mtime
            dst_mtime = dst.stat().st_mtime
            if dst_mtime > src_mtime:
                print(f"error: {dst} is newer than {src} (use --force to overwrite)")
                return 2

    # Dry-run by default.
    if not args.apply:
        print("Dry run (pass --apply to execute):")
        for src, dst in operations:
            print(_safe_copy(src, dst, dry_run=True))
        print()
        print(f"{len(operations)} file(s) would be migrated.")
        return 0

    # Apply.
    print("Migrating:")
    for src, dst in operations:
        print(_do_copy(src, dst))
    print()
    print(f"{len(operations)} file(s) migrated.")
    print(f"Launch the .app to see your data.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
