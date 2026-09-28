"""UIUC Virtual Job Board.

A thin adapter over the existing scraper package, which already knows how
to drive the site's ASP.NET WebForms postback.
"""

from __future__ import annotations

from jobscanner import scraper
from jobscanner.scraper import session as fetcher
from jobscanner.sources.base import Detail, ListingRow, Source

KEY = "vjb"
LABEL = "Virtual Job Board"

# One session per process: it carries the ASP.NET viewstate between the
# home GET and the listing POST.
_session: fetcher.VJBSession | None = None


def _get_session() -> fetcher.VJBSession:
    global _session
    if _session is None:
        _session = fetcher.VJBSession()
    return _session


def fetch_listing() -> list[ListingRow]:
    html = _get_session().get_listing()
    rows = []
    for r in scraper.parse_listing(html):
        rows.append(ListingRow(
            native_id=r["job_id"],
            title=r.get("title", ""),
            detail_url=r.get("detail_url", ""),
            company=r.get("company", ""),
            date_posted=r.get("date_posted", ""),
        ))
    return rows


def fetch_detail(row: ListingRow) -> Detail:
    html = _get_session().get_detail(row.native_id)
    parsed = scraper.parse_detail(html, row.native_id)
    return Detail(
        job_description=parsed.get("job_description", ""),
        requirements=parsed.get("requirements", ""),
        skills=parsed.get("skills", ""),
    )


SOURCE = Source(
    key=KEY,
    label=LABEL,
    fetch_listing=fetch_listing,
    supports_detail=True,
    fetch_detail=fetch_detail,
)
