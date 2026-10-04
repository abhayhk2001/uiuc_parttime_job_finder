"""Copy source-tree data (DB, its backups, keywords) into another data dir.

Shared by ``jobscanner import`` and scripts/migrate-to-appdata.py, which
used to carry two copies of this logic that had started to drift.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from jobscanner import paths


def job_count(db_path: Path) -> Optional[int]:
    """Rows in `db_path`'s jobs table; 0 if it has none, None if unreadable."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        return conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    except sqlite3.OperationalError:
        return 0  # no jobs table yet
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def _copy_db(src: Path, dst: Path) -> None:
    """Copy a SQLite file through the backup API, consistent mid-write."""
    s, d = sqlite3.connect(src), sqlite3.connect(dst)
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()


def import_data(source_dir: Path, keywords_src: Optional[Path], dest_dir: Path,
                *, force: bool, dry_run: bool) -> int:
    """Copy `source_dir`'s jobs.db and backups, plus `keywords_src`, into
    `dest_dir`. Returns a process exit code.

    Refuses to replace a destination database that already holds jobs
    unless `force`. An *empty* destination is replaced freely: launching
    the .app once creates one, and the old rule -- refuse if the
    destination is newer -- blocked every migration done after that.

    Anything replaced is first copied to ``<name>.pre-import-<stamp>``. The
    old ``<name>.bak.<stamp>`` matched the scan's backup-pruning pattern,
    so these copies crowded out (and were pruned with) the real backups.
    """
    db_src = source_dir / "jobs.db"
    db_dst = dest_dir / "jobs.db"
    print(f"Source:       {db_src}")
    print(f"Destination:  {db_dst}")
    if not db_src.exists():
        print(f"error: {db_src} does not exist")
        return 2

    if db_dst.exists() and not force:
        existing = job_count(db_dst)
        if existing is None or existing > 0:
            what = (f"already holds {existing} job(s)" if existing
                    else "exists and could not be read")
            print(f"error: {db_dst} {what}; pass --force to replace it "
                  f"(a .pre-import copy is kept)")
            return 2

    plan: list[tuple[Path, Path]] = [(db_src, db_dst)]
    plan.extend((bak, dest_dir / bak.name)
                for bak in sorted(source_dir.glob("jobs.db.bak.*"))
                if not bak.name.endswith(".partial"))
    if keywords_src is not None and keywords_src.exists():
        plan.append((keywords_src, dest_dir / "keywords.json"))

    if dry_run:
        print("Dry run (pass --apply to execute):")
        for s, d in plan:
            verb = "overwrite" if d.exists() else "copy to"
            print(f"  would {verb} {d}  <- {s.name}")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    dest_dir.mkdir(parents=True, exist_ok=True)
    for s, d in plan:
        if d.exists():
            keep = d.with_name(f"{d.name}.pre-import-{stamp}")
            shutil.copyfile(d, keep)
            print(f"  kept the previous {d.name} as {keep.name}")
        if s == db_src:
            _copy_db(s, d)
        else:
            shutil.copyfile(s, d)
        print(f"  copied {s.name} -> {d}")
    print(f"{len(plan)} file(s) imported.")
    print(f"Scans run from the source tree still write to {source_dir}. To "
          f"keep a single database, run them with "
          f"{paths.DATA_DIR_ENV}=\"{dest_dir}\".")
    return 0
