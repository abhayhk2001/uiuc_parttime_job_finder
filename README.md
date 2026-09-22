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

## Run

```bash
python main.py            # full scan, then auto-open GUI
python main.py -v         # verbose logging
python main.py --dry-run  # parse but don't write to DB
python main.py --no-gui   # scan only, no GUI (use for cron)
python main.py --gui-only # open the GUI without scanning
python gui.py             # launch GUI directly (loads existing DB)
```

On first run the bot creates `data/jobs.db`. On subsequent runs it detects new postings (anything whose `Job ID` isn't already in the DB) and only fetches details for those — plus any older rows still missing detail text.

When run interactively, `python main.py` performs the scan and then opens the GUI. The GUI shows every job in the database, lets you search/filter, view detail, edit keywords, and trigger another scan with one click. When run from cron or another non-interactive context the GUI is auto-skipped; pass `--no-gui` to be explicit.

## Data flow

```
[ VJB web site ] ──(requests)──► fetcher ──(BeautifulSoup)──► parser
                                                                  │
              ▼                                                    ▼
       alerter (sound/console)                              db (SQLite)
              ▲                                                    │
              └────────────── matcher ◄──── keywords.json ◄────────┘
                                   │
                                   └─► gui (CustomTkinter)
```

## GUI features

The window is split into three columns:

| Sections sidebar    | Jobs table                | Detail pane                |
| ------------------- | ------------------------- | -------------------------- |
| New / Old / Reviewed | Sortable, filterable rows  | Job details, Reviewed/Revisit button, matched keywords |

- **Sections sidebar** — three blocks stacked, with live counts:
  - **SECTIONS** —
    - **New** — unreviewed jobs **first discovered in the most recent completed scan**. Anything that's already in the DB before the next scan runs is "Old".
    - **Old** — unreviewed jobs that pre-date the current scan (i.e. any non-New unreviewed row).
    - **Reviewed** — jobs you've already looked at.
  - **BULK ACTIONS** — "Mark all New reviewed", "Mark all Old reviewed", "Revisit all Reviewed".
  - **KEYWORDS** — count of loaded keywords, an "Edit Keywords…" button, and a scrollable list of every keyword currently in `keywords.json`. Empty state shows `(none — Edit Keywords to add)`.
- **Jobs table** columns: Job ID · Title · Company · Matches (#) · Reviewed (✓). The *Matched Keywords* and *Posted* columns were intentionally removed; keywords are shown as chips in the detail pane and `date_posted` was rarely populated by the source site.
- **Sorting**: click any column header to sort. **Matches defaults to descending** (highest match count first); all other columns default to ascending. Click the same header again to flip direction. Internally-tracked per column.
- **Highlight rules** in the table:
  - Bright green text = matched one or more keywords and is not yet reviewed.
  - Dim green text = matched keywords but already reviewed.
  - Gray text = reviewed but didn't match any keyword.
  - Default light text = unreviewed, no keyword match.
- **Detail pane** — per-job, in this order:
  1. **Title + job ID**.
  2. **VJB URL on its own line** — blue, single-clickable, opens in the default browser (cursor turns to a hand on hover).
  3. **Company**.
  4. **Single dynamic button** — labelled **"✓ Mark Reviewed"** when the row is unreviewed and **"↻ Revisit"** when it is. Clicking always flips the reviewed flag and re-buckets the row silently — no toast, no sound, no badge.
  5. **Matched keyword chips**.
  6. **Description / Requirements / Skills** sections.
  
  The First/Last seen timestamps are intentionally hidden — they're internal bookkeeping and not user-facing.
- **Free-text search** filters the currently selected section across title, company, description, requirements, skills, and matched keywords.
- **"Matches only" toggle** hides non-matching rows inside the current section.
- **"Run Scan"** runs the scanner in a background thread; live logs stream into a collapsible log console at the bottom of the window. The button is disabled while a scan is in flight. A successful scan advances the "New" cutoff — see the schema section.
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
main.py        orchestration / CLI entry; auto-opens GUI on success
gui.py         CustomTkinter GUI (sections, table, details, scan, log, keyword editor)
config.py      URLs, paths, headers, delays
fetcher.py     ASP.NET WebForms session (GET home, POST listing, GET detail)
parser.py      HTML → dict (listing rows + detail rows)
db.py          SQLite layer, schema with job_id PRIMARY KEY + `reviewed` flag + `meta` table
matcher.py     case-insensitive keyword matching + rematch_all
alerter.py     macOS sound + console summary (V2: WhatsApp bot)
keywords.json  your editable skill/keyword list
data/jobs.db   produced on first run
```

## Database schema

Created automatically; idempotent migrations add the `reviewed` column and the `meta` table to older DBs.

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

### `meta` table

| Column  | Type | Notes                                                            |
| ------- | ---- | ---------------------------------------------------------------- |
| `key`   | TEXT | Primary key. Currently only `latest_scan_started_at`.           |
| `value` | TEXT | The UTC ISO-8601 timestamp recorded at the *start* of the scan. The GUI uses this as the New/Old boundary. |

## Editing keywords

Either edit `keywords.json` by hand (it's a flat JSON list of strings) or use the **Edit Keywords…** dialog inside the GUI. Matching is case-insensitive substring match across `Job Description + Requirements + Skills`. Saving from the GUI also re-matches the existing DB so the table is up-to-date without re-fetching listings.

The keyword editor de-duplicates entries case-insensitively and writes atomically (`*.tmp` → `os.replace`), so a crash mid-save won't corrupt your keyword list.

## Reset

```bash
rm data/jobs.db
```

Note: `init_db()` runs an idempotent migration that adds the `reviewed` column to older DBs, so you generally don't need to delete the file — just delete it if you want a complete clean slate.

## Troubleshooting

- **"ModuleNotFoundError: No module named 'customtkinter'"** — you ran the GUI in an environment that didn't install all of `requirements.txt`. Re-run `pip install -r requirements.txt`.
- **`_tkinter.TclError: ... no display`** — invoked the GUI in a context without a display (cron, SSH without X-forwarding, etc.). Use `--no-gui` or `python main.py --gui-only` from your own terminal.
- **Scan hangs on the network** — `fetcher.py` retries up to 3× with a 1 s base delay (`config.MAX_RETRIES`, `config.REQUEST_DELAY_SECONDS`). Persistent failures raise `fetcher.VJBError`, which `main.py` surfaces as `[fatal] ...` and returns exit code 2.

## Notes

- Site is ASP.NET WebForms (server-rendered). No headless browser needed.
- `fetcher.py` uses a polite 1 s delay between requests — see `config.REQUEST_DELAY_SECONDS`.
- The bot is structured so a future WhatsApp alerter can replace `alerter.py`'s `alert()` body without touching the rest of the code.
- Matching is intentionally simple (case-insensitive whole-word-ish substring), so a keyword like `python` matches both `Python Developer` and `pythonic-style work`. Tighten keywords to reduce false positives if needed.
