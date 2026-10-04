"""University Library employment pages.

These are hand-authored WordPress pages, not a job board: each renders a
heading followed by whatever the HR editor typed. Every page currently
reads

    <h2>Current Openings</h2><p>None</p>

and no populated example exists anywhere -- the Internet Archive has no
snapshot of any of these sub-pages, and the one archived parent page (July
2026, inside the Library's own stated hiring window) was also empty. So the
row markup below is a best guess across the shapes a WordPress editor
produces, and it is deliberately permissive.

The one thing that *is* stable is the "Current Openings" heading, which is
identical across all eight Library employment pages. We anchor on that and
read until the next heading of the same level.

When that block contains something other than the "None" sentinel but no
rows parse, we log loudly: that message is how we find out what the real
markup looks like, instead of silently importing nothing.
"""

from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

from jobscanner import config
from jobscanner.scraper import http
from jobscanner.sources.base import (
    ListingParseError, ListingRow, Source, clean, slugify,
)

KEY = "lib"
LABEL = "University Library"

BASE_URL = "https://www.library.illinois.edu/libinfo/about/library-employment"

#: The three pages requested. The hub links five more
#: (academic-professional, faculty, civil-service, undergraduate-hourly,
#: extra-help) if this should ever be widened.
PAGES: tuple[tuple[str, str], ...] = (
    ("academic-hourly-positions", "Academic Hourly"),
    ("graduate-assistantships", "Graduate Assistantship"),
    ("graduate-hourly-positions", "Graduate Hourly"),
)

_HEADING_RE = re.compile(r"^h[1-4]$")
#: What an empty board looks like today, on every one of these pages.
_EMPTY_SENTINELS = {"none", "none.", "n/a", ""}

#: Standing instructions that follow the openings on some pages, before the
#: next heading. Without this boundary the "Current Openings" block runs on
#: into the prose and every paragraph of it parses as a phantom posting --
#: graduate-hourly-positions yielded eight of them. Matched case-insensitively
#: against the start of an element's text.
_BOILERPLATE_PREFIXES = (
    "visit the site regularly",
    "we hire throughout the year",
    "typical library hiring cycles",
    "library hr does not accept",
    "how to apply",
    "once offered a position",
    "please review",
)


def _is_boilerplate(text: str) -> bool:
    low = clean(text).lower()
    return any(low.startswith(p) for p in _BOILERPLATE_PREFIXES)


def _openings_block(soup: BeautifulSoup) -> list:
    """Nodes between the 'Current Openings' heading and the end of its section.

    The section ends at the next heading of the *same or higher* level, or
    at the standing instructions. Deeper headings stay inside the block on
    purpose: if HR writes one <h3> per posting under an <h2> Current
    Openings, those <h3>s are the postings, not the boundary.
    """
    heading = None
    for h in soup.find_all(_HEADING_RE):
        if "current opening" in h.get_text(" ", strip=True).lower():
            heading = h
            break
    if heading is None:
        return []

    level = int(heading.name[1])
    block = []
    for sib in heading.find_next_siblings():
        if sib.name and _HEADING_RE.match(sib.name) and int(sib.name[1]) <= level:
            break
        if _is_boilerplate(sib.get_text(" ", strip=True)):
            break
        block.append(sib)
    return block


def _is_empty(block: list) -> bool:
    """True when the block says there is nothing on offer.

    Checked against the whole block, which by now excludes the standing
    instructions, so today this is exactly the "None" sentinel.
    """
    text = clean(" ".join(el.get_text(" ", strip=True) for el in block))
    return text.lower().strip(" .") in _EMPTY_SENTINELS


def _candidates(block: list) -> list[tuple]:
    """Pick the posting rows out of a block, committing to one shape.

    Editors write these three ways, and mixing the strategies double-counts:
    an <h3> posting's description paragraph would also be read as a posting
    of its own.

      1. sub-headings -- one <h3>/<h4> per posting, prose underneath
      2. a list       -- one <li> per posting
      3. paragraphs   -- one linked <p> per posting

    Returns (title, teaser, link) tuples.
    """
    in_block = set(id(el) for el in block)
    sub_headings = [el for el in block if el.name in ("h3", "h4")]
    if sub_headings:
        out = []
        for h in sub_headings:
            parts = []
            for sib in h.find_next_siblings():
                if sib.name in ("h3", "h4") or id(sib) not in in_block:
                    break
                parts.append(clean(sib.get_text(" ", strip=True)))
            link = h.find("a", href=True)
            title = clean((link or h).get_text(" ", strip=True))
            out.append((title, clean(" ".join(x for x in parts if x)), link))
        return out

    items = []
    for el in block:
        if el.name in ("ul", "ol"):
            items.extend(el.find_all("li", recursive=False))
    if not items:
        items = [el for el in block if el.name in ("p", "div")]

    out = []
    for el in items:
        text = clean(el.get_text(" ", strip=True))
        if not text or text.lower().strip(" .") in _EMPTY_SENTINELS:
            continue
        link = el.find("a", href=True)
        out.append((clean(link.get_text(" ", strip=True)) if link else text,
                    text, link))
    return out


def parse_page(html: str, page_key: str, page_label: str) -> list[ListingRow]:
    """Postings under the page's Current Openings heading.

    Returns [] only when that block positively says there is nothing on
    offer. A page with no such heading, or a block whose postings cannot
    be picked out, raises ListingParseError: returning [] for those made a
    markup change indistinguishable from an empty board.
    """
    soup = BeautifulSoup(html, "html.parser")
    block = _openings_block(soup)
    if not block:
        raise ListingParseError(
            f"Library '{page_key}' page has no Current Openings section")
    if _is_empty(block):
        return []

    rows: list[ListingRow] = []
    seen: set[str] = set()

    for title, text, link in _candidates(block):
        if not title:
            continue
        # Long prose with no link is almost certainly instructions.
        if not link and len(title) > 200:
            continue
        url = link["href"] if link else f"{BASE_URL}/{page_key}/"
        if url.startswith("/"):
            url = "https://www.library.illinois.edu" + url

        native_id = f"{page_key}-{slugify(title)}"
        if native_id in seen:
            continue
        seen.add(native_id)
        rows.append(ListingRow(
            native_id=native_id,
            title=title,
            detail_url=url,
            company=f"University Library — {page_label}",
            teaser=text,
        ))

    if not rows:
        raise ListingParseError(
            f"Library '{page_key}' has a non-empty Current Openings block but "
            f"no rows parsed -- the markup is not one of the shapes we handle. "
            f"Block starts: {clean(block[0].get_text(' ', strip=True))[:120]!r}")
    return rows


def fetch_listing() -> list[ListingRow]:
    session = requests.Session()
    session.headers.update(config.DEFAULT_HEADERS)

    rows: list[ListingRow] = []
    for page_key, page_label in PAGES:
        resp = http.request(session, "GET", f"{BASE_URL}/{page_key}/")
        rows.extend(parse_page(resp.text, page_key, page_label))
    return rows


SOURCE = Source(
    key=KEY,
    label=LABEL,
    fetch_listing=fetch_listing,
    supports_detail=False,
    empty_is_reliable=True,
)
