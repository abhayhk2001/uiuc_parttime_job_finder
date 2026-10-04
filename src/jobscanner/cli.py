"""Command-line entry point.

Parses flags, runs a scan via :mod:`jobscanner.pipeline`, and optionally
opens the GUI afterwards.
"""

import argparse
import os
import sys
from pathlib import Path

from jobscanner import config, migrate, paths, pipeline


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
                     default=paths._REPO_DATA_DIR,
                     help="Source directory containing jobs.db "
                          "(default: the repo's data/)")
    imp.add_argument("--keywords", type=Path, default=None,
                     help="keywords.json to copy too (default: the one "
                          "next to SOURCE, else the repo's)")
    imp.add_argument("--apply", action="store_true",
                     help="Actually copy (default: dry-run)")
    imp.add_argument("--force", action="store_true",
                     help="Replace a destination DB that already has jobs")
    imp.set_defaults(func=_cmd_import)

    args = p.parse_args()
    if getattr(args, "func", None) is _cmd_import:
        return _cmd_import(args)
    return _main_scan(args)


def _cmd_import(args) -> int:
    keywords = args.keywords
    if keywords is None:
        beside = args.source.parent / "keywords.json"
        keywords = beside if beside.exists() else paths._REPO_KEYWORDS
    return migrate.import_data(args.source, keywords, paths.app_data_dir(),
                               force=args.force, dry_run=not args.apply)


def _main_scan(args) -> int:
    if getattr(args, "refetch_details", None):
        return 0 if pipeline.refetch_details(
            args.refetch_details, verbose=args.verbose) >= 0 else 1

    if args.gui_only:
        _open_gui()
        return 0

    # Every source's failure is caught and reported inside pipeline.run;
    # a scan that reached no board at all comes back as a non-zero rc.
    rc = pipeline.run(dry_run=args.dry_run, verbose=args.verbose,
                      fetch_missing=not args.no_backfill)

    if rc == 0 and _should_launch_gui(args):
        _open_gui()
    return rc


if __name__ == "__main__":
    sys.exit(main())
