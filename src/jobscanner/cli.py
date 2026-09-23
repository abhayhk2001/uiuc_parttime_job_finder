"""Command-line entry point.

Parses flags, runs a scan via :mod:`jobscanner.pipeline`, and optionally
opens the GUI afterwards.
"""

import argparse
import os
import sys

from jobscanner import config, pipeline
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
    # Imported lazily on purpose: Tk / customtkinter are an optional runtime
    # dependency. A headless install (cron box, CI) can run the scanner
    # without them, and this is the only place that would break. Keep it here.
    try:
        from jobscanner.ui import app as gui
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
    args = p.parse_args()

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
