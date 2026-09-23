"""Timestamped snapshots of the SQLite file, taken before each scan writes."""

from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from jobscanner import config


def _backup_basename(ts: datetime) -> str:
    """Filename suffix used for backups: ``<UTC-ISO-with-dashes>.bak``.

    Example: ``2026-09-23T17-29-55.bak``. We replace ``:`` with ``-`` so the
    filename is safe on every filesystem.
    """
    return ts.strftime("%Y-%m-%dT%H-%M-%S.bak")


def backup_db(
    path: Path = config.DB_PATH,
    now: Optional[datetime] = None,
) -> Optional[Path]:
    """Copy `path` to a timestamped `.bak` file. Returns the new path on
    success, ``None`` if no source DB exists yet (a fresh run will create
    it). Best-effort: logs to stderr but never raises — a failed backup
    must not abort a real scan.
    """
    if not path.exists():
        return None
    ts = now or datetime.now(timezone.utc)
    backup_path = path.with_name(f"{path.name}.bak.{_backup_basename(ts)}")
    try:
        # Copy to a tmp name first, then atomically replace, so a partial
        # copy never leaves a half-written backup.
        tmp = backup_path.with_suffix(backup_path.suffix + ".partial")
        shutil.copy2(path, tmp)
        os.replace(tmp, backup_path)
        return backup_path
    except Exception as exc:
        print(f"[db] backup failed: {exc}", file=sys.stderr)
        return None


def prune_old_backups(
    path: Path = config.DB_PATH,
    keep: int = 3,
) -> int:
    """Delete older ``<path>.bak.*`` files beyond the most recent `keep`.

    Returns the number of files deleted. Newest-first ordering uses the
    lexicographic timestamp suffix (ISO-8601 sorts correctly).
    """
    if keep < 0:
        keep = 0
    pattern = f"{path.name}.bak.*"
    try:
        candidates = sorted(
            (p for p in path.parent.glob(pattern) if p.is_file()),
            reverse=True,
        )
    except Exception:
        return 0
    deleted = 0
    for old in candidates[keep:]:
        try:
            old.unlink()
            deleted += 1
        except Exception as exc:
            print(f"[db] prune failed for {old.name}: {exc}", file=sys.stderr)
    return deleted
