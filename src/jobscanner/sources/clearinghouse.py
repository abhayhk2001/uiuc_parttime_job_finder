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
from jobscanner.sources.base import ListingRow, Source, clean

KEY = "ach"
LABEL = "Assistantship Clearinghouse"

LISTING_URL = (
    "https://grad.illinois.edu/funding/assistantships/assistantship-clearinghouse"
)
BASE_URL = "https://grad.illinois.edu"


def parse_listing(html: str) -> list[ListingRow]:
    """Parse the clearinghouse listing.

    An empty board renders as <div class="field-view"></div>; that is a
    legitimate "no openings", not a failure, so it returns [].
    """
    soup = BeautifulSoup(html, "html.parser")
    rows: list[ListingRow] = []

    for panel in soup.select("ilw-panel.node-assistantship, ilw-panel.node--teaser"):
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
        deadline_el = panel.select_one(".field-end-date-posting time")
        percent_el = panel.select_one(".field-percent[content]")

        rows.append(ListingRow(
            native_id=native_id,
            title=title,
            detail_url=href,
            company="Graduate College",
            teaser=clean(desc.get_text(" ", strip=True)) if desc else "",
            extra={
                # Optional: one of the eleven observed postings had no
                # deadline, so never assume this is present.
                "deadline": (deadline_el.get("datetime") if deadline_el else ""),
                "percent": (percent_el.get("content") if percent_el else ""),
            },
        ))
    return rows


def fetch_listing() -> list[ListingRow]:
    session = requests.Session()
    session.headers.update(config.DEFAULT_HEADERS)
    resp = session.get(LISTING_URL, timeout=config.HTTP_TIMEOUT_SECONDS)
    resp.raise_for_status()
    return parse_listing(resp.text)


SOURCE = Source(
    key=KEY,
    label=LABEL,
    fetch_listing=fetch_listing,
    supports_detail=False,
)
