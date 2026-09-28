"""Scan orchestration: for each source, fetch the listing, diff it against
the DB, backfill details, match keywords, alert, and archive what vanished.

CLI flag handling lives in :mod:`jobscanner.cli`.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

from jobscanner import alerts, config, matching
from jobscanner import storage as db
from jobscanner.sources import SOURCES, Source
from jobscanner.sources.base import ListingRow


@dataclass
class SourceResult:
    """What one source contributed to a scan."""

    key: str
    label: str
    ok: bool = False
    listed: int = 0
    new: int = 0
    matching: int = 0
    error: str = ""
    archived: int = 0

    def summary(self) -> str:
        if not self.ok:
            return f"{self.label}: FAILED ({self.error})"
        bits = f"{self.listed} listed, {self.new} new, {self.matching} matching"
        if self.archived:
            bits += f", {self.archived} archived"
        return f"{self.label}: {bits}"


def _row_to_record(row: ListingRow, source: Source) -> dict:
    return {
        "job_id": row.job_id(source.key),
        "title": row.title,
        "company": row.company,
        "date_posted": row.date_posted,
        "detail_url": row.detail_url,
        "source": source.key,
    }


def _scan_source(
    source: Source,
    keywords: list[str],
    scan_started_at: str,
    dry_run: bool,
    verbose: bool,
    fetch_missing: bool,
) -> tuple[SourceResult, list[dict]]:
    result = SourceResult(key=source.key, label=source.label)
    match_jobs: list[dict] = []

    print(f"[scan] {source.label}: fetching listing…")
    try:
        rows = source.fetch_listing()
    except Exception as exc:  # noqa: BLE001
        # A source that fails must not take the scan down with it, and must
        # not have its jobs archived -- we have no evidence they are gone.
        result.error = f"{type(exc).__name__}: {exc}"
        print(f"  ! {source.label} failed: {result.error}", file=sys.stderr)
        return result, match_jobs

    result.ok = True
    result.listed = len(rows)
    print(f"[scan] {source.label}: parsed {len(rows)} listing row(s).")

    by_id = {r.job_id(source.key): r for r in rows}
    existing = db.get_existing_job_ids()
    new_rows = [r for r in rows if r.job_id(source.key) not in existing]
    result.new = len(new_rows)
    print(f"[scan] {source.label}: {len(new_rows)} new.")

    if dry_run:
        if verbose:
            for r in new_rows[:5]:
                print(f"   ~ (dry-run) would insert {r.job_id(source.key)} "
                      f"({r.title!r})")
        return result, match_jobs

    for r in rows:
        db.upsert_listing(_row_to_record(r, source))

    # Decide which rows still need their detail text.
    need_detail = [r.job_id(source.key) for r in new_rows]
    if fetch_missing:
        missing = set(db.get_jobs_missing_details()) & set(by_id)
        need_detail = list({*need_detail, *missing})

    for job_id in need_detail:
        row = by_id.get(job_id)
        if row is None:
            continue
        if source.supports_detail and source.fetch_detail is not None:
            try:
                detail = source.fetch_detail(row)
            except Exception as exc:  # noqa: BLE001
                print(f"  ! detail fetch failed for {job_id}: {exc}",
                      file=sys.stderr)
                continue
            # fetch_detail may enrich the row (company, posted date) but
            # must never change its id -- the listing is the only thing the
            # next scan sees, so a re-keyed row would be re-inserted.
            db.upsert_listing(_row_to_record(row, source))
            description = detail.job_description
            requirements, skills = detail.requirements, detail.skills
        else:
            # Listing-only source: the teaser is all the text there is.
            description, requirements, skills = row.teaser, "", ""

        full = db.get_job(job_id) or {}
        full.update({
            "job_description": description,
            "requirements": requirements,
            "skills": skills,
        })
        matches = matching.find_matches(full, keywords)
        if verbose:
            print(f"   {job_id}: matches={matches}")
        db.update_details(job_id, description, requirements, skills, matches)
        if matches:
            match_jobs.append({**full, "matched_keywords": ",".join(matches)})

    result.matching = len(match_jobs)

    # Only safe because we know this source's fetch succeeded.
    result.archived = db.auto_archive_removed_jobs(scan_started_at, source.key)
    if result.archived:
        print(f"[scan] {source.label}: auto-archived {result.archived} "
              f"job(s) no longer listed.")
    return result, match_jobs


def run(dry_run: bool = False, verbose: bool = False,
        fetch_missing: bool = True) -> int:
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

    results: list[SourceResult] = []
    all_matches: list[dict] = []
    for source in SOURCES:
        result, matches = _scan_source(
            source, keywords, scan_started_at, dry_run, verbose, fetch_missing)
        results.append(result)
        all_matches.extend(matches)

    alerts.alert(all_matches)

    print("[done] Per source:")
    for result in results:
        print(f"   - {result.summary()}")
    total = sum(r.listed for r in results if r.ok)
    new = sum(r.new for r in results if r.ok)
    failed = [r.label for r in results if not r.ok]
    print(f"[done] {total} listed | {new} new | {len(all_matches)} new matching.")
    if failed:
        print(f"[done] {len(failed)} source(s) failed: {', '.join(failed)}",
              file=sys.stderr)
    # A partial scan is still a successful run; the GUI and cron should not
    # treat one flaky board as a fatal error.
    return 0
