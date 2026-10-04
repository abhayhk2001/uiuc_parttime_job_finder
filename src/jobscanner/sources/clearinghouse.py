"""Graduate College Assistantship Clearinghouse.

Drupal. The listing is server-rendered (no JavaScript needed) into a view
container; each posting is an <ilw-panel> custom element carrying an
explicit numeric ID, which makes for a clean stable key.

Listing-only. Detail pages sit behind a campus login -- fetching a
delisted posting returns the "Log in | Graduate College" page rather than
the posting -- so the listing teaser is all the text we get. It is short
(25-271 characters across the postings observed), which is worth knowing
when a keyword fails to match something that looks like it should.
"""

from __future__ import annotations

import requests
from bs4 import BeautifulSoup

from jobscanner import config
from jobscanner.scraper import http
from jobscanner.sources.base import ListingParseError, ListingRow, Source, clean

KEY = "ach"
LABEL = "Assistantship Clearinghouse"

LISTING_URL = (
    "https://grad.illinois.edu/funding/assistantships/assistantship-clearinghouse"
)
BASE_URL = "https://grad.illinois.edu"


def _deadline(panel) -> str:
    """The application deadline as an ISO string, or "".

    Deliberately matches any nested <time> under .field-deadline rather than
    one exact wrapper class: the live markup nests it as
    .field-deadline > .field-deadline > time while archived pages used
    .field-deadline > .field-end-date-posting > time, and pinning the inner
    class silently lost the date on current postings. Also note the deadline
    is genuinely optional -- one of eleven observed postings had none.
    """
    el = panel.select_one(".field-deadline time[datetime]")
    if el is not None:
        return el.get("datetime") or ""
    el = panel.select_one(".field-end-date-posting time[datetime]")
    return (el.get("datetime") or "") if el is not None else ""


def _percent(panel) -> str:
    """The appointment percent, e.g. "50" or "33% or 41%".

    Some postings carry a machine-readable content attribute, others only
    text -- and the text is not always a single number, so this stays a
    string rather than being coerced to an int.
    """
    el = panel.select_one(".field-percent[content]")
    if el is not None and el.get("content"):
        return el.get("content")
    el = panel.select_one(".field-percent")
    return clean(el.get_text(" ", strip=True)) if el is not None else ""


def _format_percent(percent: str) -> str:
    """Append a % sign only when the value is a bare number."""
    return f"{percent}%" if percent.isdigit() else percent


def _with_metadata(teaser: str, deadline: str, percent: str) -> str:
    """Fold the deadline and appointment percent into the description text.

    This source is listing-only -- its detail pages sit behind a campus
    login -- and the teaser is often very short (one live posting's is just
    the heading "Description and Qualifications"). The deadline and percent
    are the most useful facts the listing carries, and there are no columns
    for them, so they go into the description where the detail pane shows
    them and search can reach them.
    """
    bits = []
    if deadline:
        bits.append(f"Application deadline: {deadline[:10]}")
    if percent:
        bits.append(f"Appointment: {_format_percent(percent)}")
    if not bits:
        return teaser
    suffix = "  \u00b7  ".join(bits)
    return f"{teaser}\n\n{suffix}" if teaser else suffix


def parse_listing(html: str) -> list[ListingRow]:
    """Parse the clearinghouse listing.

    An empty board renders as <div class="field-view"></div>; that is a
    legitimate "no openings", not a failure, so it returns []. A page with
    neither postings nor that container is not the listing at all, and
    raises ListingParseError.
    """
    soup = BeautifulSoup(html, "html.parser")
    rows: list[ListingRow] = []
    panels = soup.select("ilw-panel.node-assistantship, ilw-panel.node--teaser")
    if not panels and soup.select_one(".field-view") is None:
        raise ListingParseError(
            "Clearinghouse page has neither postings nor the listing "
            "container -- the markup has changed")

    for panel in panels:
        link = panel.select_one("h3 a")
        if not link:
            continue
        title = clean(link.get_text(" ", strip=True))

        id_el = panel.select_one(".field-id")
        native_id = clean(id_el.get_text(strip=True)) if id_el else ""
        if not native_id:
            # Without the board's own id there is no stable key; skip rather
            # than invent one that churns on every edit.
            continue

        href = link.get("href", "")
        if href.startswith("/"):
            href = BASE_URL + href

        desc = panel.select_one(".field-description")
        deadline = _deadline(panel)
        percent = _percent(panel)
        teaser = clean(desc.get_text(" ", strip=True)) if desc else ""

        rows.append(ListingRow(
            native_id=native_id,
            title=title,
            detail_url=href,
            company="Graduate College",
            teaser=_with_metadata(teaser, deadline, percent),
            extra={"deadline": deadline, "percent": percent},
        ))
    return rows


def fetch_listing() -> list[ListingRow]:
    session = requests.Session()
    session.headers.update(config.DEFAULT_HEADERS)
    resp = http.request(session, "GET", LISTING_URL)
    return parse_listing(resp.text)


SOURCE = Source(
    key=KEY,
    label=LABEL,
    fetch_listing=fetch_listing,
    supports_detail=False,
    empty_is_reliable=True,
)
