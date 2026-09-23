import argparse
import os
import sys

import alerter
import config
import db
import fetcher
import matcher
import parser


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


def fetch_details_for(session: fetcher.VJBSession, job_ids: list[str]) -> dict:
    details: dict = {}
    for jid in job_ids:
        try:
            html = session.get_detail(jid)
        except fetcher.VJBError as exc:
            print(f"  ! could not fetch detail for {jid}: {exc}", file=sys.stderr)
            continue
        details[jid] = parser.parse_detail(html, jid)
    return details


def run(dry_run: bool = False, verbose: bool = False, fetch_missing: bool = True) -> int:
    print(f"[init] DB at {config.DB_PATH}")
    db.init_db()

    # Snapshot the DB before we write anything. No-op if the DB doesn't exist
    # yet (a fresh run will create it). Skip on dry-run / gui-only.
    if not dry_run:
        backup = db.backup_db()
        if backup is not None:
            print(f"[init] Backed up DB to {backup.name}")
            db.prune_old_backups()
        else:
            print("[init] No prior DB to back up (first run).")

    keywords = matcher.load_keywords()
    print(f"[init] Loaded {len(keywords)} keywords from {config.KEYWORDS_PATH}")

    if not dry_run:
        scan_started_at = db.now_iso()
        db.set_latest_scan_started_at(scan_started_at)
        print(f"[init] Scan started at {scan_started_at}")
    else:
        print("[init] Dry run — scan-started timestamp not advanced.")

    session = fetcher.VJBSession()

    print(f"[scan] Fetching listing ({config.SECTION})...")
    listing_html = session.get_listing()
    rows = parser.parse_listing(listing_html)
    print(f"[scan] Parsed {len(rows)} listing rows.")

    if verbose and rows:
        print("[scan] First 3 rows:")
        for r in rows[:3]:
            print(f"   - {r}")

    existing_ids = db.get_existing_job_ids()
    new_rows = [r for r in rows if r["job_id"] not in existing_ids]
    print(f"[scan] {len(new_rows)} new job(s) not yet in DB.")

    new_records: list[dict] = []
    for r in new_rows:
        if dry_run:
            if verbose:
                print(f"   ~ (dry-run) would insert {r['job_id']} ({r['title']!r})")
            continue
        is_new = db.upsert_listing(r)
        if verbose:
            print(f"   + inserted {r['job_id']} ({r['title']!r})" if is_new
                  else f"   = unchanged {r['job_id']}")

    if fetch_missing and not dry_run:
        missing_ids = db.get_jobs_missing_details()
        if missing_ids:
            print(f"[scan] Backfilling details for {len(missing_ids)} job(s)...")
            fetch_ids = list({*missing_ids, *[r["job_id"] for r in new_rows]})
        else:
            fetch_ids = [r["job_id"] for r in new_rows]
    else:
        fetch_ids = [r["job_id"] for r in new_rows]

    if fetch_ids:
        details = fetch_details_for(session, fetch_ids)
        match_jobs: list[dict] = []
        for jid, det in details.items():
            full = db.get_job(jid) or {}
            full.update(det)
            matches = matcher.find_matches(full, keywords)
            if verbose:
                print(f"   {jid}: matches={matches}")
            if not dry_run:
                db.update_details(jid, det["job_description"], det["requirements"], det["skills"], matches)
            if matches:
                match_jobs.append({**full, "matched_keywords": ",".join(matches)})
    else:
        match_jobs = []

    alerter.alert(match_jobs)

    total = len(rows)
    print(f"[done] {total} total | {len(new_rows)} new | {len(match_jobs)} new matching.")
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
    args = p.parse_args()

    if args.gui_only:
        _open_gui()
        return 0

    try:
        rc = run(dry_run=args.dry_run, verbose=args.verbose,
                 fetch_missing=not args.no_backfill)
    except fetcher.VJBError as exc:
        print(f"[fatal] {exc}", file=sys.stderr)
        return 2

    if rc == 0 and _should_launch_gui(args):
        _open_gui()
    return rc


def _open_gui() -> None:
    try:
        import gui
    except Exception as exc:
        print(f"[gui] could not import GUI module: {exc}", file=sys.stderr)
        return
    try:
        gui.launch(config.DB_PATH, config.KEYWORDS_PATH)
    except Exception as exc:
        print(f"[gui] GUI exited with error: {exc}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
