# UIUC Virtual Job Board Scanner

A lightweight Python tool that crawls the **Other University Positions** section of the [UIUC Virtual Job Board](https://secure.osfa.illinois.edu/vjb/), mirrors every posting into a local SQLite database indexed by `Job ID`, scrapes each new posting's **Job Description / Requirements / Skills**, and matches them against your keyword list. Ships with both a terminal scanner and a CustomTkinter GUI.

## Requirements

- Python 3.9 or newer (uses `list[...]`, `tuple[...]`, etc.).
- Tk 8.6+ (bundled with the official python.org macOS / Windows installers). On Debian/Ubuntu install it explicitly:
  ```bash
  sudo apt install python3-tk
  ```

## Setup

```bash
cd uiuc_parttime_job_scanner
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Or install the package itself, which also puts a `jobscanner` command on your
PATH:

```bash
pip install -e .
jobscanner --no-gui
```

## Run

```bash
python main.py            # full scan, then auto-open GUI
python main.py -v         # verbose logging
python main.py --dry-run  # parse but don't write to DB
python main.py --no-gui   # scan only, no GUI (use for cron)
python main.py --gui-only # open the GUI without scanning
python gui.py             # launch GUI directly (loads existing DB)
jobscanner --no-gui       # same as `python main.py --no-gui`, if pip-installed
```

`main.py` and `gui.py` at the repo root are thin shims over
`jobscanner.cli:main` and `jobscanner.ui.app:launch`, so every command above
works whether or not the package is installed.

On first run the bot creates `data/jobs.db`. On subsequent runs it detects new postings (anything whose `Job ID` isn't already in the DB) and only fetches details for those — plus any older rows still missing detail text.

When run interactively, `python main.py` performs the scan and then opens the GUI. The GUI shows every job in the database, lets you search/filter, view detail, edit keywords, and trigger another scan with one click. When run from cron or another non-interactive context the GUI is auto-skipped; pass `--no-gui` to be explicit.

## Data flow

```
[ VJB web site ] ──(requests)──► scraper.session ──(BeautifulSoup)──► scraper.parsing
                                                                           │
              ▼                                                             ▼
       alerts (sound/console)                                        storage (SQLite)
              ▲                                                             │
              └──────────────── matching ◄──── keywords.json ◄─────────────┘
                                    │
                                    └─► ui (CustomTkinter)

              cli ──► pipeline ──► everything above
```

## GUI features

The window is split into three columns, separated by two draggable dividers:

| Sections sidebar    | Jobs table                | Detail pane                |
| ------------------- | ------------------------- | -------------------------- |
| All / New / Old / Reviewed | Sortable, filterable rows  | Job details, context-aware action buttons, matched keywords |

- **Sections sidebar** — five blocks stacked, with live counts:
  - **SECTIONS** —
    - **All** — every row in the database, so free-text search can span sections.
    - **New** — unreviewed jobs **first discovered in the most recent completed scan**. Anything that's already in the DB before the next scan runs is "Old".
    - **Old** — unreviewed jobs that pre-date the current scan (i.e. any non-New unreviewed row).
    - **Reviewed** — jobs you've looked at but haven't applied to.
  - **TO APPLY** — jobs you've flagged as "I want to apply to this one". Reviewed jobs cannot be added.
  - **FOLLOW UP** — jobs you've marked Applied (with `applied_at` and `follow_up_at` recorded). Sorted by follow-up date ascending so overdue items appear first.
  - **ARCHIVED** — jobs removed from the VJB listing since the last scan, or jobs you archived manually. Recoverable via Unarchive.
  - **BULK ACTIONS** — "Mark all New reviewed", "Mark all Old reviewed", "Revisit all Reviewed", "Mark all To Apply Applied", "Unmark all To Apply", "Mark all Follow Up Further", "Archive all Follow Up". Each button is enabled only when its section has rows. The four destructive ones (revisit all, apply all, unmark all, archive all) ask for confirmation first; every one reports its result as a status-bar toast that fades after a few seconds rather than a modal dialog.
  - **KEYWORDS** — count of loaded keywords, an "Edit Keywords…" button, and a scrollable list of every keyword currently in `keywords.json`. Empty state shows `(none — Edit Keywords to add)`.
- **Resizable, collapsible sidebar** — drag the sash between the sidebar and the table to resize it (180px – 700px). Collapse it to a 58px rail with the `«` button in its header, by double-clicking the sash, or with `Cmd/Ctrl-B`; the rail keeps every section's short label and live count. Expanding restores the width you last dragged to.
- **Resizable detail pane** — a second sash sits between the table and the detail pane. Detail text reflows to the pane's width as you drag.
- **Remembered layout** — sidebar width, collapsed state and detail width are saved on every drag release and on collapse (not just at exit), under the `ui_layout` key in the `meta` table.
- **Jobs table** columns: Job ID · Title · Company · Matches (#) · Reviewed (✓). The *Matched Keywords* and *Posted* columns were intentionally removed; keywords are shown as chips in the detail pane and `date_posted` was rarely populated by the source site.
- **Sorting**: click any column header to sort; the active column shows a ▲/▼ arrow. **Matches defaults to descending** (highest match count first) and is applied on open, so the most promising rows are already at the top; all other columns default to ascending. Click the same header again to flip direction. The chosen sort **persists across refreshes** — toggling Mark Reviewed, Mark Applied, Revisit, or adding/removing from To Apply preserves the user's chosen order.
- **Row actions**: double-click (or press Return on) a row to open the posting in your browser. Right-click a row for a context menu — open, copy Job ID, and the same two state-machine actions the detail pane offers for that row.
- **Empty sections** say why they're empty, distinguishing "no search matches", "no keyword matches" and a genuinely empty section.
- **Highlight rules** in the table:
  - Bright green text = matched one or more keywords and is not yet reviewed.
  - Dim green text = matched keywords but already reviewed.
  - Gray text = reviewed but didn't match any keyword.
  - Default light text = unreviewed, no keyword match.
- **Detail pane** — per-job, in this order:
  1. **Title + job ID**.
  2. **VJB URL on its own line** — blue and clickable, with an explicit **"Open ↗"** button beside it. Both open the default browser; the button is disabled when the row has no usable URL.
  3. **Company**, plus applied / follow-up / archived dates where they apply.
  4. **Primary action button** — context-aware, checked in this order:
     - Archived job → **"↩ Unarchive"**.
     - Applied job (Follow Up) → **"↻ Mark Further Follow Up"**.
     - To Apply job → **"✓ Mark Applied"** — atomic transition: clears `to_apply`, sets `reviewed=1`, and records `applied_at` / `follow_up_at`.
     - Reviewed job → **"↻ Revisit"** (clears reviewed, row returns to New/Old).
     - Otherwise → **"✓ Mark Reviewed"** (sets reviewed=1).
  5. **Secondary button**, in the same order:
     - Archived job → disabled (unarchive it first).
     - Applied job → **"★ Archive"**.
     - To Apply job → **"★ Remove from To Apply"**.
     - Reviewed job → disabled (can't re-add a reviewed job to To Apply).
     - Otherwise → **"☆ Add to To Apply"**.
  6. **Matched keyword chips**.
  7. **Description / Requirements / Skills** sections.

  Both buttons come from one state machine in `ui/job_actions.py`, so a button's label and what it does can't disagree.

  The First/Last seen timestamps are intentionally hidden — they're internal bookkeeping and not user-facing.

### Keyboard shortcuts

`Cmd` on macOS, `Ctrl` elsewhere.

| Shortcut | Action |
| -------- | ------ |
| `Cmd-R` | Refresh the table |
| `Cmd-F` | Focus the search box |
| `Esc` | Clear the search |
| `Cmd-L` | Toggle the log console |
| `Cmd-B` | Collapse / expand the sidebar |
| `Cmd-Return` | Run a scan |
| `Cmd-1` … `Cmd-7` | Jump to a section, in sidebar order |
| `Return` / double-click | Open the selected job in the browser |

### To Apply / Follow Up / Archive state machine

```
   New ───────────► To Apply ─────────► Follow Up ─────────► Archived
   Old ────────► (Add to To Apply)  (Mark Applied)       (Archive)
                  ↓                      ↓                  ↑
                  ↓  (Mark Applied)      ↓ (Mark Further     ↑ (Unarchive)
                  ↓                      ↓  Follow Up)        ↑
                  ↓                      ↓                  ↑ (auto-archive
                  ↓                      ↓                  ↑  if VJB listing
                  ↓                      ↓                  ↑  gone on next
                  ↓                      ↓                  ↑  scan)
   Reviewed ──── (Revisit) ────►  New / Old   (to_apply stays 0)
   Follow Up ── (Mark Further Follow Up) ──► Follow Up   (resets follow_up_at)
   Follow Up ── (Archive)        ──► Archived
   Archived ──── (Unarchive)     ──► Follow Up or Reviewed (whichever applied_at dictates)
   Any active section ── (next scan, last_seen_at < cutoff) ──► Archived (auto)
```

Single-row transitions are silent — the DB updates and the row re-buckets. Bulk actions report to the status bar, and the destructive ones confirm first.

### Follow Up workflow

When you click **Mark Applied** (in the To Apply section), the app records:
- `applied_at = now`
- `follow_up_at = applied_at + FOLLOW_UP_WINDOW_DAYS` (default 7 days, configurable in `config.py`)

The job moves from **To Apply** to **Follow Up**.

In the **Follow Up** section, the detail pane shows:
- "Applied: 2026-09-23"
- "Follow up: 2026-09-30 (in 7 days)"

Click **✎ Edit follow-up date** to open the date editor. Preset buttons (+1d / +3d / +1w / +2w / +1mo / +3mo) plus a custom `YYYY-MM-DD` entry are both available.

The **Mark Further Follow Up** primary button resets `follow_up_at = now + 7d` — for the common "I followed up today, remind me in a week" flow.

The bulk **"Mark all To Apply Applied"** action runs exactly the same transition as the single-row button, timestamps included, so bulk-applied jobs land in Follow Up rather than stopping at Reviewed.

The **Archive** secondary button moves the job to **Archived**.

### Auto-archive

After every successful `python main.py` scan, the app runs `db.auto_archive_removed_jobs(cutoff)` which archives any *active* job (reviewed OR to-apply OR in Follow Up) whose `last_seen_at` is older than the current scan cutoff — i.e. it disappeared from the VJB listing. Active jobs you can no longer apply to or follow up on get archived automatically. Use **Unarchive** to bring one back.
- **Free-text search** filters the currently selected section across title, company, description, requirements, skills, and matched keywords.
- **"Matches only" toggle** hides non-matching rows inside the current section.
- **"Run Scan"** runs the scanner in a background thread; live logs stream into a collapsible log console at the bottom of the window. Output produced while the console is collapsed is buffered and replayed when you open it. The button is disabled while a scan is in flight. A successful scan advances the "New" cutoff — see the schema section.
- **"Edit Keywords…"** opens an in-app editor for `keywords.json`. On Save it re-matches every existing row so the table refreshes immediately. The `Reviewed` flag is preserved across keyword edits — re-matching never silently re-classifies a job.
- **Status bar** shows total jobs, matching count, and reviewed count.

### How the New ↔ Old boundary moves

A successful scan sets `meta.latest_scan_started_at` at the moment it begins. Every row inserted by that scan has `first_seen_at >= that timestamp` and so lives in **New**. After the next scan, those rows pre-date the new cutoff and silently move to **Old**. Nothing else triggers a transition.

This means:
- `--dry-run` does not advance the cutoff (no DB writes).
- A job that disappears from the listing between scans simply falls to Old (search/All still finds it).
- Before the very first scan, every unreviewed row is treated as New; the first scan normalizes that.

## Cron example

```cron
*/30 * * * * cd /path/to/uiuc_parttime_job_scanner && /path/to/.venv/bin/python -u main.py --no-gui >> scanner.log 2>&1
```

Notes:
- `-u` makes stdout unbuffered so lines show up in `scanner.log` in real time instead of after the scan finishes.
- `--no-gui` is belt-and-suspenders: the CLI also auto-detects a non-TTY stdout and skips the GUI on its own.

## Files

```
pyproject.toml            packaging; defines the `jobscanner` console script
main.py                   shim -> jobscanner.cli:main
gui.py                    shim -> jobscanner.ui.app:launch
keywords.json             your editable skill/keyword list
data/jobs.db              produced on first run

src/jobscanner/
  config.py               URLs, paths, headers, delays
  timeutils.py            the one place UTC ISO-8601 is produced or parsed
  cli.py                  argparse entry point; decides whether to open the GUI
  pipeline.py             a scan: fetch, diff, backfill, match, alert, auto-archive
  matching.py             case-insensitive keyword matching + rematch_all
  alerts.py               macOS sound + console summary (V2: WhatsApp bot)
  scraper/
    session.py            ASP.NET WebForms session (GET home, POST listing, GET detail)
    parsing.py            HTML -> dict (listing rows + detail rows)
  storage/                SQLite layer; __init__ re-exports the whole API
    schema.py             tables, connection helper, idempotent migrations
    meta.py               the key/value meta table (scan cutoff, UI layout)
    sections.py           one registry defining what each section means in SQL
    jobs.py               row reads/writes and the state transitions
    backup.py             pre-scan snapshots of the DB file
  ui/
    app.py                the window shell, scan thread, shortcuts, context menu
    theme.py              every color, font and spacing token
    job_actions.py        the job state machine (no Tk imports)
    bulk_actions.py       the bulk-action registry
    toolbar.py            scan/refresh/search/filters/status + toasts
    sidebar.py            sections, counts, bulk actions, keywords, collapse
    jobs_table.py         the Treeview, row tagging, sorting, empty state
    detail_pane.py        the selected job and its context-aware buttons
    log_console.py        the stdout shim and the collapsible log
    sash.py               reusable draggable divider
    dialogs/              keyword editor, follow-up date editor

tests/test_db_isolated.py smoke tests for the storage layer (temp DBs only)
```

## Database schema

Created automatically; idempotent migrations add the `reviewed` and `to_apply` columns and the `meta` table to older DBs.

### `jobs` table

| Column            | Type | Notes                                            |
| ----------------- | ---- | ------------------------------------------------ |
| `job_id`          | TEXT | Primary key, from VJB.                           |
| `title`           | TEXT |                                                  |
| `company`         | TEXT |                                                  |
| `date_posted`     | TEXT |                                                  |
| `detail_url`      | TEXT |                                                  |
| `job_description` | TEXT | Filled after first detail fetch.                 |
| `requirements`    | TEXT |                                                  |
| `skills`          | TEXT |                                                  |
| `first_seen_at`   | TEXT | UTC ISO-8601; set at insert time.                |
| `last_seen_at`    | TEXT | UTC ISO-8601, refreshed each scan.               |
| `matched_keywords`| TEXT | Comma-separated lowercase keywords.              |
| `reviewed`        | INT  | 0 or 1; managed by the GUI.                      |
| `to_apply`        | INT  | 0 or 1; user-marked "I want to apply". Toggled from the detail pane. Migration adds this. |
| `applied_at`      | TEXT | ISO timestamp set by `mark_applied`. Migration adds this. |
| `follow_up_at`    | TEXT | ISO timestamp; default = `applied_at + FOLLOW_UP_WINDOW_DAYS`. User-editable from the detail pane. |
| `archived`        | INT  | 0 or 1; auto-archived when the VJB listing no longer contains the job, or manually via the Archive button. Migration adds this. |
| `archived_at`     | TEXT | ISO timestamp set when `archived` becomes 1. |

### `meta` table

| Column  | Type | Notes                                                            |
| ------- | ---- | ---------------------------------------------------------------- |
| `key`   | TEXT | Primary key. Used for `latest_scan_started_at` (ISO timestamp at the start of the latest successful scan — drives the New/Old boundary), `ui_layout` (JSON object: sidebar width, collapsed flag, detail width) and the older `sash_widths_px` (JSON list; still read once to seed `ui_layout` when upgrading a pre-existing DB). |
| `value` | TEXT | String payload — see above. |

## Editing keywords

Either edit `keywords.json` by hand (it's a flat JSON list of strings) or use the **Edit Keywords…** dialog inside the GUI. Matching is case-insensitive substring match across `Job Description + Requirements + Skills`. Saving from the GUI also re-matches the existing DB so the table is up-to-date without re-fetching listings.

The keyword editor de-duplicates entries case-insensitively and writes atomically (`*.tmp` → `os.replace`), so a crash mid-save won't corrupt your keyword list.

## Reset

```bash
rm data/jobs.db
```

Note: `init_db()` runs an idempotent migration that adds the `reviewed` column to older DBs, so you generally don't need to delete the file — just delete it if you want a complete clean slate.

## Backups

Every non-dry-run `python main.py` scan makes a timestamped copy of `data/jobs.db` to `data/jobs.db.bak.<UTC>` *before* writing anything. The three most recent backups are kept; older ones are pruned automatically.

```
data/                                       # created on first run
  jobs.db                                   # live database
  jobs.db.bak.2026-09-23T17-29-55.bak       # most recent backup
  jobs.db.bak.2026-09-23T17-21-03.bak       # ...
  jobs.db.bak.2026-09-23T16-58-12.bak       # oldest kept
```

### Restore from a backup

```bash
cp data/jobs.db.bak.2026-09-23T17-21-03.bak data/jobs.db
```

The backup files are excluded from git via `.gitignore`.

### Why this exists

A scan writes to the DB in several places (`init_db` migrations, `upsert_listing`, `update_details`, `set_latest_scan_started_at`). The backups exist so that if any of those writes ever corrupt or wipe state, you can roll back to the previous scan's snapshot with a single copy. The functions live in `jobscanner/storage/backup.py`.

## Tests

```bash
python tests/run_all.py                 # everything, no pytest needed
python tests/test_gui_layout.py         # one module, as a plain script
pytest tests/                           # also works: pip install -e ".[dev]"
pytest tests/test_gui_layout.py -k sidebar
```

58 tests in two layers:

| Module | Covers |
| ------ | ------ |
| `test_db_isolated.py` | Storage: schema + migrations, upserts, section queries and counts, every state transition, bulk actions, backup/prune |
| `test_gui_workflow.py` | Sections, selection, the full New → To Apply → Follow Up → Archived walk, sorting, filtering, both dialogs, log buffering, layout persistence |
| `test_gui_layout.py` | Real pixel geometry: panes not overlapping, toolbar/footer spanning, the log console inside the footer, preset buttons in distinct cells, collapse/expand, both sashes |
| `test_gui_bulk_actions.py` | Every registered bulk action, confirmation in both directions, toasts, the All section |
| `test_gui_interactions.py` | Detail-pane widget reuse, text reflow, empty states, keyboard navigation and shortcuts, the row context menu |

Notes:

- **No test ever opens `data/jobs.db`.** Each one runs against its own
  `tempfile.mkdtemp()` database, removed afterwards. New tests should use
  `support.TempDB` or the `support.gui_app` context manager.
- **The GUI tests run headlessly** — they build real windows, drive them, and
  assert on widget state and screen geometry, but need no interaction. Where
  Tk or customtkinter is unavailable they skip rather than fail, so
  `python tests/run_all.py` still exercises the storage layer on a headless
  box.
- Test discovery is automatic (`support.run_module` scans for `test_*`), so a
  new test can't silently go unrun.

## Troubleshooting

- **"ModuleNotFoundError: No module named 'customtkinter'"** — you ran the GUI in an environment that didn't install all of `requirements.txt`. Re-run `pip install -r requirements.txt`. The CLI itself does not need it: `jobscanner.cli` imports the GUI lazily, so a headless box can run scans without Tk.
- **"ModuleNotFoundError: No module named 'jobscanner'"** — you imported the package directly without installing it. Either `pip install -e .`, or go through the `main.py` / `gui.py` shims, which add `src/` to `sys.path` themselves.
- **`_tkinter.TclError: ... no display`** — invoked the GUI in a context without a display (cron, SSH without X-forwarding, etc.). Use `--no-gui` or `python main.py --gui-only` from your own terminal.
- **Scan hangs on the network** — `scraper/session.py` retries up to 3× with a 1 s base delay (`config.MAX_RETRIES`, `config.REQUEST_DELAY_SECONDS`). Persistent failures raise `VJBError`, which `cli.py` surfaces as `[fatal] ...` and returns exit code 2.

## Notes

- Site is ASP.NET WebForms (server-rendered). No headless browser needed.
- `scraper/session.py` uses a polite 1 s delay between requests — see `config.REQUEST_DELAY_SECONDS`.
- The bot is structured so a future WhatsApp alerter can replace `alerts.py`'s `alert()` body without touching the rest of the code.
- Matching is intentionally simple (case-insensitive whole-word-ish substring), so a keyword like `python` matches both `Python Developer` and `pythonic-style work`. Tighten keywords to reduce false positives if needed.
