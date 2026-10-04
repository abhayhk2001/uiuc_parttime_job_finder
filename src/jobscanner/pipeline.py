"""Scan orchestration: for each source, fetch the listing, diff it against
the DB, backfill details, match keywords, alert, and archive what vanished.

CLI flag handling lives in :mod:`jobscanner.cli`.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from jobscanner import alerts, config, matching
from jobscanner import storage as db
from jobscanner.sources import SOURCES, SOURCES_BY_KEY, Source
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
    path: Optional[Path] = None,
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
    existing = db.get_existing_job_ids(path)
    new_rows = [r for r in rows if r.job_id(source.key) not in existing]
    result.new = len(new_rows)
    print(f"[scan] {source.label}: {len(new_rows)} new.")

    if dry_run:
        if verbose:
            for r in new_rows[:5]:
                print(f"   ~ (dry-run) would insert {r.job_id(source.key)} "
                      f"({r.title!r})")
        return result, match_jobs

    # For a source with detail pages, the listing must not overwrite what
    # the detail page stored: VJB's listing title is the department, and
    # writing it back on every scan undid the real title from fetch_detail.
    for r in rows:
        db.upsert_listing(_row_to_record(r, source), path,
                          overwrite=not source.supports_detail)

    # Decide which rows still need their detail text.
    need_detail = [r.job_id(source.key) for r in new_rows]
    new_ids = set(need_detail)
    if fetch_missing:
        missing = set(db.get_jobs_missing_details(path)) & set(by_id)
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
            db.upsert_listing(_row_to_record(row, source), path)
            description = detail.job_description
            requirements, skills = detail.requirements, detail.skills
        else:
            # Listing-only source: the teaser is all the text there is.
            description, requirements, skills = row.teaser, "", ""

        full = db.get_job(job_id, path) or {}
        full.update({
            "job_description": description,
            "requirements": requirements,
            "skills": skills,
        })
        matches = matching.find_matches(full, keywords)
        if verbose:
            print(f"   {job_id}: matches={matches}")
        db.update_details(job_id, description, requirements, skills,
                          matches, path)
        # Only announce postings this scan discovered. Rows backfilled
        # through fetch_missing were already on the board; alerting on them
        # every time their text arrived said "NEW" about old jobs.
        if matches and job_id in new_ids:
            match_jobs.append({**full, "matched_keywords": ",".join(matches)})

    result.matching = len(match_jobs)

    # Archiving needs two things to be true: the fetch succeeded (we are
    # past the except above), and the listing is trustworthy. A non-empty
    # one is. An empty one is only for a source that raises on pages it
    # cannot read (`empty_is_reliable`); for the rest, [] may be a parser
    # that broke silently, and archiving on it would sweep the source.
    # Without this, a board that genuinely emptied kept its old rows forever.
    if rows or source.empty_is_reliable:
        result.archived = db.auto_archive_removed_jobs(
            scan_started_at, source.key, path)
        if result.archived:
            print(f"[scan] {source.label}: auto-archived {result.archived} "
                  f"job(s) no longer listed.")
    else:
        print(f"[scan] {source.label}: listing came back empty; skipping "
              f"auto-archive -- this source cannot tell an empty board from "
              f"a page it failed to read.")
    return result, match_jobs


def refetch_details(source_key: str, verbose: bool = False,
                    path: Optional[Path] = None,
                    keywords_path: Optional[Path] = None) -> int:
    """Re-fetch detail text for every stored row of one source.

    `get_jobs_missing_details()` only finds rows with *no* text, so a parser
    improvement that changes what we extract from a page that we already
    scraped would never reach the existing rows. This forces it.

    Returns the number of rows updated, or -1 when `source_key` is unknown
    or has no detail pages (the CLI turns that into a non-zero exit).
    """
    source = SOURCES_BY_KEY.get(source_key)
    if source is None:
        print(f"[refetch] unknown source {source_key!r}; known: "
              f"{', '.join(SOURCES_BY_KEY)}", file=sys.stderr)
        return -1
    if not source.supports_detail or source.fetch_detail is None:
        print(f"[refetch] {source.label} has no detail pages to re-fetch.",
              file=sys.stderr)
        return -1

    path = Path(path) if path else config.DB_PATH
    db.init_db(path)
    backup = db.backup_db(path)
    if backup is not None:
        print(f"[refetch] Backed up DB to {backup.name}")
        db.prune_old_backups(path)

    keywords = matching.load_keywords(keywords_path)
    rows = [r for r in db.get_all_jobs(path)
            if (r.get("source") or "") == source_key]
    print(f"[refetch] {source.label}: {len(rows)} stored row(s).")

    updated = 0
    for stored in rows:
        job_id = stored["job_id"]
        native_id = job_id.split(":", 1)[1] if ":" in job_id else job_id
        row = ListingRow(
            native_id=native_id,
            title=stored.get("title") or "",
            detail_url=stored.get("detail_url") or "",
            company=stored.get("company") or "",
            date_posted=stored.get("date_posted") or "",
        )
        try:
            detail = source.fetch_detail(row)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {job_id}: {exc}", file=sys.stderr)
            continue

        # fetch_detail may correct the title/company (VJB's listing only
        # carries the department), so write the row back too.
        db.upsert_listing(_row_to_record(row, source), path)
        full = {**stored,
                "job_description": detail.job_description,
                "requirements": detail.requirements,
                "skills": detail.skills}
        matches = matching.find_matches(full, keywords)
        db.update_details(job_id, detail.job_description, detail.requirements,
                          detail.skills, matches, path)
        updated += 1
        if verbose:
            print(f"   {job_id}: title={row.title!r} matches={matches}")

    print(f"[refetch] Updated {updated} row(s).")
    return updated


def run(dry_run: bool = False, verbose: bool = False,
        fetch_missing: bool = True, path: Optional[Path] = None,
        keywords_path: Optional[Path] = None) -> int:
    # `path` lets a caller (notably the GUI, which is constructed with its
    # own db_path) scan into a specific database instead of whichever one
    # config happens to point at.
    path = Path(path) if path else config.DB_PATH
    print(f"[init] DB at {path}")
    db.init_db(path)

    # Snapshot the DB before we write anything. No-op if the DB doesn't exist
    # yet (a fresh run will create it). Skip on dry-run / gui-only.
    if not dry_run:
        backup = db.backup_db(path)
        if backup is not None:
            print(f"[init] Backed up DB to {backup.name}")
            db.prune_old_backups(path)
        else:
            print("[init] No prior DB to back up (first run).")

    # Like `path`: the GUI scans with the keyword file its editor writes.
    keywords_path = Path(keywords_path) if keywords_path else config.KEYWORDS_PATH
    keywords = matching.load_keywords(keywords_path)
    print(f"[init] Loaded {len(keywords)} keywords from {keywords_path}")

    # The New/Old cutoff is this timestamp, but it is only recorded once
    # the scan has reached at least one source (below). Writing it up front
    # meant a scan with no network moved every New job into Old.
    scan_started_at = db.now_iso()
    print(f"[init] Scan started at {scan_started_at}")

    results: list[SourceResult] = []
    all_matches: list[dict] = []
    for source in SOURCES:
        result, matches = _scan_source(
            source, keywords, scan_started_at, dry_run, verbose,
            fetch_missing, path)
        results.append(result)
        all_matches.extend(matches)

    any_ok = any(r.ok for r in results)
    if dry_run:
        print("[init] Dry run — scan-started timestamp not advanced.")
    elif any_ok:
        db.set_latest_scan_started_at(scan_started_at, path)
    else:
        print("[done] No source could be reached; keeping the previous "
              "scan cutoff so New is left as it was.", file=sys.stderr)

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
    # treat one flaky board as a fatal error. A scan that reached no board
    # at all is a failure, and the GUI must not report it as complete.
    return 0 if any_ok else 1
