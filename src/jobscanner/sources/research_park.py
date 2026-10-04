"""Research Park job board.

The careers page ships no listings in its HTML -- it is WP Job Manager
loading them over AJAX. The plugin's own config exposes the endpoint:

    var job_manager_ajax_filters = {"ajax_url":"/jm-ajax/%%endpoint%%/", ...}

so we POST to the `get_listings` endpoint directly and parse the rendered
HTML it returns in a JSON envelope. The WordPress REST API is closed on
this site (/wp-json/wp/v2/job-listing returns 404), so this is the only
machine-readable route.

Detail pages carry schema.org JobPosting JSON-LD, which is far more
reliable than scraping the rendered page, and is where the numeric post id
comes from.
"""

from __future__ import annotations

import html as html_module
import json
import re
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

import hashlib

from jobscanner import config
from jobscanner.scraper import http
from jobscanner.sources.base import (
    Detail, ListingParseError, ListingRow, Source, clean, slugify,
)

KEY = "rp"
LABEL = "Research Park"

BASE_URL = "https://researchpark.illinois.edu"
LISTINGS_URL = f"{BASE_URL}/jm-ajax/get_listings/"

#: The board is small (15 postings when this was written); one page is
#: normally enough, but we still honour max_num_pages.
PER_PAGE = 50
MAX_PAGES = 20

_POST_ID_RE = re.compile(r"[?&]p=(\d+)")
#: Listing dates render as M.D.YY, e.g. "9.24.26".
_SHORT_DATE_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{2})$")


def _post(session: requests.Session, page: int) -> dict:
    resp = http.request(
        session, "POST", LISTINGS_URL,
        data={
            "per_page": PER_PAGE,
            "page": page,
            "orderby": "featured",
            "order": "DESC",
            "search_keywords": "",
        },
    )
    return resp.json()


def _parse_posted_date(text: str) -> str:
    """Turn '9.24.26' into '2026-09-24'. Returns '' if it doesn't match."""
    m = _SHORT_DATE_RE.match(clean(text))
    if not m:
        return ""
    month, day, year = (int(g) for g in m.groups())
    try:
        return datetime(2000 + year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _company_from_heading(h3) -> str:
    """The company is the bare text node after the <br> inside the <h3>.

    The title lives in an <a>, so anything stripped out after it is the
    organisation name.
    """
    parts = [clean(t) for t in h3.stripped_strings if clean(t)]
    return parts[-1] if len(parts) > 1 else ""


#: Longest native id; matches slugify's default so existing ids are unchanged.
_ID_MAX = 60


def _native_id(slug_source: str) -> str:
    """The URL slug, kept unique when it is too long to store whole.

    Plain truncation gave two postings whose slugs share their first 60
    characters the same id, and the second silently overwrote the first.
    A slug that fits is used as-is, so ids already in the database keep
    matching; a longer one keeps a prefix plus a hash of the whole slug.
    """
    full = slugify(slug_source, max_length=10_000)
    if len(full) <= _ID_MAX:
        return full
    digest = hashlib.sha1(full.encode()).hexdigest()[:8]
    return f"{full[:_ID_MAX - 9].rstrip('-')}-{digest}"


def _parse_rows(html: str) -> list[ListingRow]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[ListingRow] = []
    for li in soup.select("li.job-listing"):
        h3 = li.select_one(".title-sec h3")
        link = h3.find("a") if h3 else None
        if not link or not link.get("href"):
            continue
        title = clean(link.get_text(" ", strip=True))
        url = link["href"]
        posted = li.select_one(".posted-on span")
        desc = li.select_one(".description")
        rows.append(ListingRow(
            # The listing markup carries no id, so the URL slug is the key.
            # It is unique per posting and is the only identifier available
            # without fetching every detail page.
            native_id=_native_id(url.rstrip("/").split("/")[-1] or title),
            title=title,
            detail_url=url,
            company=_company_from_heading(h3),
            date_posted=_parse_posted_date(
                posted.get_text(strip=True) if posted else ""),
            teaser=clean(desc.get_text(" ", strip=True)) if desc else "",
        ))
    return rows


def fetch_listing() -> list[ListingRow]:
    session = requests.Session()
    session.headers.update(config.DEFAULT_HEADERS)

    rows: list[ListingRow] = []
    page = 1
    while page <= MAX_PAGES:
        payload = _post(session, page)
        if not isinstance(payload, dict) or "found_jobs" not in payload:
            # Not the shape this parser knows; an empty board still sends
            # the key, set to false.
            raise ListingParseError(
                "Research Park listing response has no found_jobs field")
        if not payload.get("found_jobs"):
            break
        rows.extend(_parse_rows(payload.get("html", "")))
        if page >= int(payload.get("max_num_pages") or 1):
            break
        page += 1
    return rows


def _json_ld_posting(soup: BeautifulSoup) -> Optional[dict]:
    """Return the schema.org JobPosting block, if the page has one."""
    for tag in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "{}")
        except (ValueError, TypeError):
            continue
        for item in (data if isinstance(data, list) else [data]):
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                return item
    return None


def _html_to_text(html: str) -> str:
    return clean(BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True))


def fetch_detail(row: ListingRow) -> Detail:
    session = requests.Session()
    session.headers.update(config.DEFAULT_HEADERS)
    resp = http.request(session, "GET", row.detail_url)
    soup = BeautifulSoup(resp.text, "html.parser")

    posting = _json_ld_posting(soup)
    if posting:
        # Promote the real numeric post id now that we can see it, and keep
        # the board's own metadata for logging.
        identifier = posting.get("identifier") or {}
        if isinstance(identifier, dict):
            # The numeric WordPress post id. Recorded as metadata only --
            # it must NOT become the row's native_id. The listing page only
            # ever exposes the URL slug, so re-keying a row here would make
            # the next scan see the slug as unknown and insert the job a
            # second time, every single scan.
            # WordPress leaves the ampersand HTML-escaped in the JSON-LD
            # ("...&#038;p=48827"), so unescape before matching on "&p=".
            value = html_module.unescape(str(identifier.get("value", "")))
            m = _POST_ID_RE.search(value)
            if m:
                row.extra["post_id"] = m.group(1)
        org = posting.get("hiringOrganization") or {}
        if isinstance(org, dict) and org.get("name"):
            row.company = clean(str(org["name"]))
        if posting.get("datePosted"):
            row.date_posted = str(posting["datePosted"])[:10]
        row.extra.update({
            "employment_type": posting.get("employmentType"),
            "valid_through": posting.get("validThrough"),
        })
        description = _html_to_text(posting.get("description", ""))
        if description:
            return Detail(job_description=description)

    # Fall back to the rendered block if the JSON-LD is missing or empty.
    body = soup.select_one(".job_description") or soup.select_one(".single_job_listing")
    return Detail(
        job_description=clean(body.get_text(" ", strip=True)) if body else row.teaser
    )


SOURCE = Source(
    key=KEY,
    label=LABEL,
    fetch_listing=fetch_listing,
    supports_detail=True,
    fetch_detail=fetch_detail,
    # An empty board is a JSON payload with found_jobs false, which cannot
    # be mistaken for a page we failed to read.
    empty_is_reliable=True,
)
