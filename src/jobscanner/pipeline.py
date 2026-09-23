"""Scan orchestration: fetch the listing, diff it against the DB, backfill
details for anything new or incomplete, match keywords, and alert.

CLI flag handling lives in :mod:`jobscanner.cli`.
"""

import sys

from jobscanner import alerts, config, matching
from jobscanner import storage as db
from jobscanner import scraper
from jobscanner.scraper import session as fetcher


def fetch_details_for(session: fetcher.VJBSession, job_ids: list[str]) -> dict:
    details: dict = {}
    for jid in job_ids:
        try:
            html = session.get_detail(jid)
        except fetcher.VJBError as exc:
            print(f"  ! could not fetch detail for {jid}: {exc}", file=sys.stderr)
            continue
        details[jid] = scraper.parse_detail(html, jid)
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

    keywords = matching.load_keywords()
    print(f"[init] Loaded {len(keywords)} keywords from {config.KEYWORDS_PATH}")

    scan_started_at = db.now_iso()
    if not dry_run:
        db.set_latest_scan_started_at(scan_started_at)
        print(f"[init] Scan started at {scan_started_at}")
    else:
        print("[init] Dry run — scan-started timestamp not advanced.")

    session = fetcher.VJBSession()

    print(f"[scan] Fetching listing ({config.SECTION})...")
    listing_html = session.get_listing()
    rows = scraper.parse_listing(listing_html)
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
            matches = matching.find_matches(full, keywords)
            if verbose:
                print(f"   {jid}: matches={matches}")
            if not dry_run:
                db.update_details(jid, det["job_description"], det["requirements"], det["skills"], matches)
            if matches:
                match_jobs.append({**full, "matched_keywords": ",".join(matches)})
    else:
        match_jobs = []

    alerts.alert(match_jobs)

    # Auto-archive any active job that wasn't re-seen in this scan.
    # Skipped on a dry run — it is a DB write like any other.
    if not dry_run:
        n_archived = db.auto_archive_removed_jobs(scan_started_at)
        if n_archived:
            print(f"[done] Auto-archived {n_archived} job(s) no longer on VJB.")

    total = len(rows)
    print(f"[done] {total} total | {len(new_rows)} new | {len(match_jobs)} new matching.")
    return 0
