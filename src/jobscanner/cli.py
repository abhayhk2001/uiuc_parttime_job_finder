"""Command-line entry point.

Parses flags, runs a scan via :mod:`jobscanner.pipeline`, and optionally
opens the GUI afterwards.
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

from jobscanner import config, paths, pipeline
from jobscanner.scraper import VJBError


def _should_launch_gui(args) -> bool:
    """Decide whether to open the GUI after the scan completes.

    Honor explicit flags first, then fall back to a headless detection
    so a non-interactive invocation (e.g. cron) skips the GUI by default.
    """
    if getattr(args, "gui_only", False):
        return True
    if getattr(args, "no_gui", False):
        return False
    if getattr(args, "force_gui", False):
        return True
    # Auto-detect non-interactive environments.
    if not sys.stdout.isatty():
        return False
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        return False
    return True


def _open_gui() -> None:
    # Imported lazily on purpose: PySide6 is an optional runtime dependency.
    # A headless install (cron box, CI) can run the scanner without it, and
    # this is the only place that would break. Keep it here.
    try:
        from jobscanner.ui_qt import app as gui
    except Exception as exc:
        print(f"[gui] could not import GUI module: {exc}", file=sys.stderr)
        return
    try:
        gui.launch(config.DB_PATH, config.KEYWORDS_PATH)
    except Exception as exc:
        print(f"[gui] GUI exited with error: {exc}", file=sys.stderr)


def _frozen_style_appdata_dir() -> Path:
    """Same path ``paths.user_data_dir()`` returns when frozen.

    Used by ``import`` because the CLI subcommand is itself unfrozen
    (running from a terminal, not the .app), so ``paths.user_data_dir()``
    would resolve to the source directory and the import would be a
    no-op. Force the AppData path here so the subcommand is useful.
    """
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "UIUC Part-Time Job Scanner"
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "UIUC Part-Time Job Scanner"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "uiuc-parttime-job-scanner"


def _import_data(source: Path, *, force: bool, dry_run: bool) -> int:
    """Copy a source ``data/jobs.db`` (+ backups + keywords) into AppData."""
    from datetime import datetime, timezone

    dest_dir = _frozen_style_appdata_dir()
    print(f"Source:  {source / 'jobs.db'}")
    print(f"Dest:    {dest_dir / 'jobs.db'}")

    db_src = source / "jobs.db"
    kw_src = source.parent / "keywords.json"
    if not db_src.exists():
        print(f"error: {db_src} does not exist", file=sys.stderr)
        return 2

    # Refuse to clobber a newer destination unless --force.
    db_dst = dest_dir / "jobs.db"
    if not force and db_dst.exists() and db_dst.stat().st_mtime > db_src.stat().st_mtime:
        print(f"error: {db_dst} is newer than the source (use --force to overwrite)",
              file=sys.stderr)
        return 2

    plan: list[tuple[Path, Path]] = [(db_src, db_dst)]
    plan.extend((bak, dest_dir / bak.name)
                for bak in sorted(source.glob("jobs.db.bak.*")))
    if kw_src.exists():
        plan.append((kw_src, dest_dir / "keywords.json"))

    if dry_run:
        print("Dry run (pass --apply to execute):")
        for s, d in plan:
            print(f"  would copy {s.name} -> {d}")
        return 0

    print("Copying:")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    for s, d in plan:
        if not s.exists():
            continue
        if d.exists():
            backup = d.with_name(f"{d.name}.bak.{stamp}")
            shutil.copyfile(d, backup)
            print(f"  backed up {d.name} -> {backup.name}")
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(s, d)
        print(f"  copied {s.name} -> {d}")
    print(f"{len(plan)} file(s) migrated.")
    print("Launch the .app to see your data.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="UIUC Virtual Job Board scanner")
    p.add_argument("--dry-run", action="store_true", help="Parse but skip DB writes")
    p.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    p.add_argument("--no-backfill", action="store_true",
                   help="Do not fetch details for old jobs missing them")
    p.add_argument("--no-gui", action="store_true",
                   help="Skip GUI launch (used by cron jobs)")
    p.add_argument("--force-gui", action="store_true",
                   help="Force GUI launch even when stdout is not a TTY")
    p.add_argument("--gui-only", action="store_true",
                   help="Skip the scan and just open the GUI")
    p.add_argument("--refetch-details", metavar="SOURCE",
                   help="Re-fetch detail text for every stored row of SOURCE "
                        "(e.g. vjb) and exit. Use after a parser change.")
    sub = p.add_subparsers(dest="command")

    imp = sub.add_parser("import", help="Import a jobs.db into AppData")
    imp.add_argument("source", type=Path, nargs="?",
                     default=Path("data"),
                     help="Source directory containing jobs.db (default: ./data)")
    imp.add_argument("--apply", action="store_true",
                     help="Actually copy (default: dry-run)")
    imp.add_argument("--force", action="store_true",
                     help="Overwrite a newer destination DB")
    imp.set_defaults(func=_cmd_import)

    args = p.parse_args()
    if getattr(args, "func", None) is _cmd_import:
        return _cmd_import(args)
    return _main_scan(args)


def _cmd_import(args) -> int:
    return _import_data(args.source, force=args.force, dry_run=not args.apply)


def _main_scan(args) -> int:
    if getattr(args, "refetch_details", None):
        return 0 if pipeline.refetch_details(
            args.refetch_details, verbose=args.verbose) >= 0 else 1

    if args.gui_only:
        _open_gui()
        return 0

    try:
        rc = pipeline.run(dry_run=args.dry_run, verbose=args.verbose,
                          fetch_missing=not args.no_backfill)
    except VJBError as exc:
        print(f"[fatal] {exc}", file=sys.stderr)
        return 2

    if rc == 0 and _should_launch_gui(args):
        _open_gui()
    return rc


if __name__ == "__main__":
    sys.exit(main())
