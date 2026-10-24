"""Housing (HES) Student Portal -- student employment postings.

Unlike the other boards this one is behind Illinois NetID SSO + Duo, so it
is fetched through a saved browser session (see :mod:`jobscanner.hes_session`;
sign in once with ``jobscanner --hes-login``). When the session has
expired, ``fetch_listing`` raises rather than returning ``[]``, so the scan
reports "login required" and archives nothing.

The landing page renders every open position into ``#positionDisplay``:
a ``.positiontitle``, a ``.positiondate`` ("MM/DD/YYYY to MM/DD/YYYY"), an
``ApplyNow/<id>`` link, a short description, and a "More Details" modal
(``#pos_<id>``) holding the full text. That is all there is -- there are
no per-posting pages -- so this source is listing-only and the modal text
is used as the description.
"""

from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup

from jobscanner import hes_session
from jobscanner.sources.base import ListingParseError, ListingRow, Source, clean

KEY = "hes"
LABEL = "HES Student Employment"

BASE_URL = "https://web.housing.illinois.edu"
COMPANY = "University Housing"

_APPLY_ID_RE = re.compile(r"/ApplyNow/(\d+)", re.IGNORECASE)
_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def _iso(mdy: str) -> str:
    m = _DATE_RE.fullmatch(mdy.strip())
    if not m:
        return ""
    try:
        return datetime(int(m[3]), int(m[1]), int(m[2])).date().isoformat()
    except ValueError:
        return ""


def _dates(text: str) -> tuple[str, str]:
    """(start, end) as ISO strings from "MM/DD/YYYY to MM/DD/YYYY"."""
    found = [_iso("/".join(m)) for m in _DATE_RE.findall(text)]
    found += [""] * (2 - len(found))
    return found[0], found[1]


def parse_listing(html: str) -> list[ListingRow]:
    """Parse the MyHES landing page into postings.

    The positions container missing altogether means this is not the
    portal (the SSO login page, an error page, changed markup) and raises
    ListingParseError. The container present but empty is a genuine "no
    open positions" and returns [].
    """
    soup = BeautifulSoup(html, "html.parser")
    display = soup.select_one("#positionDisplay")
    if display is None:
        raise ListingParseError(
            "HES page has no #positionDisplay -- not logged in, or the "
            "markup has changed")

    rows: list[ListingRow] = []
    for title_el in display.select(".positiontitle"):
        block = title_el.find_parent("div", class_="col-sm-12")
        if block is None:
            continue
        link = block.select_one("a[href*='ApplyNow']")
        m = _APPLY_ID_RE.search(link.get("href", "")) if link else None
        if not m:
            # No board id means no stable key; skip rather than invent one.
            continue
        native_id = m.group(1)

        modal = soup.select_one(f"#pos_{native_id} .modal-body")
        short = block.select_one(".shortdescription")
        body = modal or short
        description = clean(body.get_text(" ", strip=True)) if body else ""

        date_el = block.select_one(".positiondate")
        start, end = _dates(date_el.get_text(" ", strip=True) if date_el else "")
        if end:
            description = (f"{description}\n\nPosting open through: {end}"
                           if description else f"Posting open through: {end}")

        rows.append(ListingRow(
            native_id=native_id,
            title=clean(title_el.get_text(" ", strip=True)),
            detail_url=f"{BASE_URL}/HESStudentPortal/Application/ApplyNow/{native_id}",
            company=COMPANY,
            date_posted=start,
            teaser=description,
            extra={"end_date": end},
        ))
    return rows


def fetch_listing() -> list[ListingRow]:
    return parse_listing(hes_session.fetch_portal_html())


SOURCE = Source(
    key=KEY,
    label=LABEL,
    fetch_listing=fetch_listing,
    supports_detail=False,
    # An empty #positionDisplay is trusted only loosely: the portal fills
    # it by script, so treat [] as a possible silent failure.
    empty_is_reliable=False,
)
