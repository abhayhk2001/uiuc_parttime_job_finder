"""Per-source listing and detail parsing, against captured fixtures.

The Clearinghouse and Library boards are usually empty, so parsing is
tested against saved markup rather than the network -- otherwise these
tests would pass by doing nothing. Provenance of each fixture is recorded
in its own header; `lib_*_synthetic` markup is constructed here and marked
as a guess, because no populated Library page exists to copy.

    python tests/test_sources.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from support import REPO_ROOT, check, eq, run_module  # noqa: E402

from jobscanner.sources import SOURCES, SOURCES_BY_KEY  # noqa: E402
from jobscanner.sources import clearinghouse, library, research_park  # noqa: E402
from jobscanner.sources.base import ListingRow, slugify  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_registry_keys_are_unique_and_stable() -> None:
    keys = [s.key for s in SOURCES]
    eq(len(keys), len(set(keys)), "source keys must be unique")
    eq(set(keys), {"vjb", "rp", "ach", "lib"}, "expected four sources")
    for source in SOURCES:
        check(bool(source.label), f"{source.key} needs a label")
        if source.supports_detail:
            check(source.fetch_detail is not None,
                  f"{source.key} claims detail support but has no fetcher")


def test_listing_only_sources_declare_no_detail() -> None:
    for key in ("ach", "lib"):
        check(not SOURCES_BY_KEY[key].supports_detail,
              f"{key} is listing-only: its detail pages are not public")


def test_job_ids_are_namespaced() -> None:
    row = ListingRow(native_id="48447", title="t", detail_url="u")
    eq(row.job_id("rp"), "rp:48447", "job_id should carry the source prefix")
    eq(row.job_id("vjb"), "vjb:48447", "same native id, different source")


# ---------------------------------------------------------------------------
# Research Park
# ---------------------------------------------------------------------------

def test_research_park_listing() -> None:
    payload = json.loads(_fixture("rp_listings.json"))
    rows = research_park._parse_rows(payload["html"])
    eq(len(rows), 15, "fixture holds 15 postings")

    first = rows[0]
    eq(first.title, "Hardware/FPGA Engineer", "title from the heading link")
    eq(first.company, "Philowave", "company is the text after the <br>")
    eq(first.date_posted, "2026-09-24", "M.D.YY listing date becomes ISO")
    eq(first.native_id, "hardware-fpga-engineer-full-time",
       "the URL slug is the key -- the listing exposes no numeric id")
    check(first.detail_url.startswith("https://researchpark.illinois.edu/job/"),
          "detail URL is absolute")
    check(first.teaser, "listing carries a teaser")
    check(all(r.title and r.detail_url for r in rows),
          "every row needs a title and a URL")


def test_research_park_short_date_parsing() -> None:
    eq(research_park._parse_posted_date("9.24.26"), "2026-09-24", "M.D.YY")
    eq(research_park._parse_posted_date("12.1.26"), "2026-12-01", "two-digit month")
    eq(research_park._parse_posted_date(""), "", "empty input")
    eq(research_park._parse_posted_date("not a date"), "", "unparseable input")
    eq(research_park._parse_posted_date("13.45.26"), "", "impossible date")


def test_research_park_detail_reads_json_ld() -> None:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(_fixture("rp_detail.html"), "html.parser")
    posting = research_park._json_ld_posting(soup)
    check(posting is not None, "fixture has a JobPosting block")
    eq(posting["title"], "Hardware/FPGA Engineer", "title from JSON-LD")
    eq(posting["hiringOrganization"]["name"], "Philowave", "company from JSON-LD")

    text = research_park._html_to_text(posting["description"])
    check(len(text) > 2000, f"full description, not the teaser (got {len(text)})")
    check("Philowave" in text, "description mentions the company")


def test_research_park_post_id_survives_html_escaping() -> None:
    """WordPress leaves the ampersand escaped in the JSON-LD, so a naive
    "&p=" match finds nothing."""
    import html as html_module
    value = ("https://researchpark.illinois.edu/?post_type=job_listing"
             "&#038;p=48827")
    m = research_park._POST_ID_RE.search(html_module.unescape(value))
    check(m is not None, "post id should be found after unescaping")
    eq(m.group(1), "48827", "numeric post id")


def test_research_park_detail_never_rekeys_the_row() -> None:
    """The listing only ever exposes the slug. If fetch_detail changed the
    native_id, the next scan would treat the slug as unseen and insert the
    job again -- on every scan, forever."""
    from bs4 import BeautifulSoup
    row = ListingRow(native_id="hardware-fpga-engineer-full-time",
                     title="Hardware/FPGA Engineer", detail_url="x")
    soup = BeautifulSoup(_fixture("rp_detail.html"), "html.parser")
    posting = research_park._json_ld_posting(soup)
    identifier = posting.get("identifier") or {}
    import html as html_module
    m = research_park._POST_ID_RE.search(
        html_module.unescape(str(identifier.get("value", ""))))
    row.extra["post_id"] = m.group(1)
    eq(row.native_id, "hardware-fpga-engineer-full-time",
       "native_id must stay the slug")
    eq(row.extra["post_id"], "48827", "numeric id is metadata only")


# ---------------------------------------------------------------------------
# Clearinghouse
# ---------------------------------------------------------------------------

def test_clearinghouse_populated_listing() -> None:
    rows = clearinghouse.parse_listing(_fixture("ch_populated.html"))
    eq(len(rows), 5, "fixture holds 5 postings")

    by_id = {r.native_id: r for r in rows}
    eq(sorted(by_id), ["65", "66", "68", "69", "70"],
       "native ids come from the board's own ID field")

    row = by_id["70"]
    # The source markup has a double space; clean() collapses whitespace.
    eq(row.title, "Graduate Teaching Assistantship for Computational Genomics Course",
       "title from the heading link, with whitespace normalized")
    eq(row.job_id("ach"), "ach:70", "namespaced id")
    eq(row.extra["deadline"][:10], "2026-03-13", "ISO deadline from <time>")
    eq(row.extra["percent"], "50", "appointment percent")
    check(row.detail_url.startswith("https://grad.illinois.edu/"),
          "relative hrefs are made absolute")
    check(all(r.teaser for r in rows), "every posting has teaser text")


def test_clearinghouse_handles_a_posting_with_no_deadline() -> None:
    """One of the eleven postings observed had no deadline, so the field
    must be optional rather than assumed."""
    html = _fixture("ch_populated.html").replace(
        '<div class="field-end-date-posting">', '<div class="absent">', 1)
    rows = clearinghouse.parse_listing(html)
    eq(len(rows), 5, "the row still parses without its deadline")
    check(any(r.extra["deadline"] == "" for r in rows),
          "a missing deadline yields an empty string, not a crash")


def test_clearinghouse_empty_board_is_not_an_error() -> None:
    rows = clearinghouse.parse_listing(_fixture("ch_empty.html"))
    eq(rows, [], "an empty view means no openings, not a failure")


def test_clearinghouse_skips_rows_without_an_id() -> None:
    html = _fixture("ch_populated.html").replace('class="field-id"', 'class="gone"')
    eq(clearinghouse.parse_listing(html), [],
       "without the board's id there is no stable key, so skip the row")


# ---------------------------------------------------------------------------
# Library
# ---------------------------------------------------------------------------

def test_library_none_sentinel_yields_no_rows() -> None:
    """Every Library page currently reads 'Current Openings / None'."""
    for key, label in library.PAGES:
        rows = library.parse_page(_fixture("lib_none.html"), key, label)
        eq(rows, [], f"{key}: 'None' must not produce postings")


def test_library_does_not_read_standing_instructions_as_jobs() -> None:
    """Regression: the boilerplate that follows 'None' on some pages was
    parsed as eight phantom postings."""
    html = _fixture("lib_none.html")
    check("Visit the site regularly" in html,
          "fixture must include the trailing boilerplate")
    rows = library.parse_page(html, "graduate-hourly-positions", "Graduate Hourly")
    eq(rows, [], "instructions are not job postings")


def test_library_parses_each_editor_shape() -> None:
    """SYNTHETIC markup: no populated Library page exists to copy, so these
    are the shapes a WordPress editor plausibly produces. Revisit against
    real markup when HR next posts something."""
    shapes = {
        "list": ("<h2>Current Openings</h2><ul>"
                 '<li><a href="/a">Circulation Desk Assistant</a> - 10 hrs/wk</li>'
                 '<li><a href="/b">Digitization Technician</a></li>'
                 "</ul><h2>How to Apply</h2>"),
        "sub-headings": ("<h2>Current Openings</h2>"
                         "<h3>Reference Assistant</h3><p>Desk work. 12 hrs/wk.</p>"
                         "<h3>Metadata Assistant</h3><p>Cataloguing.</p>"
                         "<h2>How to Apply</h2>"),
        "paragraphs": ("<h2>Current Openings</h2>"
                       '<p><a href="https://e.org/a">Stacks Attendant</a></p>'
                       '<p><a href="https://e.org/b">Evening Circulation Aide</a></p>'
                       "<h2>Once Offered a Position</h2>"),
    }
    for name, html in shapes.items():
        rows = library.parse_page(html, "graduate-hourly-positions", "Graduate Hourly")
        eq(len(rows), 2, f"{name}: expected exactly 2 postings, not descriptions")
        check(all(r.title for r in rows), f"{name}: every row needs a title")
        check(all(r.native_id.startswith("graduate-hourly-positions-")
                  for r in rows), f"{name}: id is scoped to its page")


def test_library_ids_are_stable_for_the_same_title() -> None:
    html = ("<h2>Current Openings</h2><ul>"
            '<li><a href="/a">Circulation Desk Assistant</a></li></ul>'
            "<h2>How to Apply</h2>")
    a = library.parse_page(html, "graduate-hourly-positions", "Graduate Hourly")
    b = library.parse_page(html, "graduate-hourly-positions", "Graduate Hourly")
    eq(a[0].native_id, b[0].native_id, "same title must yield the same id")
    eq(a[0].job_id("lib"),
       "lib:graduate-hourly-positions-circulation-desk-assistant",
       "id is derived from page and title")


def test_slugify_is_url_safe() -> None:
    eq(slugify("Hardware/FPGA Engineer"), "hardware-fpga-engineer", "slashes")
    eq(slugify("  Spaces  &  Symbols!  "), "spaces-symbols", "punctuation")
    eq(slugify(""), "untitled", "empty input has a fallback")


if __name__ == "__main__":
    _, failed, _ = run_module(globals(), "Sources")
    sys.exit(1 if failed else 0)
