"""The interface every job source implements.

A source knows how to list postings from one board and, where the board
allows it, how to fetch one posting's full text. Everything downstream --
storage, matching, the GUI -- works on the normalized shapes here and never
needs to know which board a row came from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

_WS_RE = re.compile(r"\s+")


def clean(text: str) -> str:
    """Collapse whitespace; the boards are full of stray newlines and nbsp."""
    if not text:
        return ""
    return _WS_RE.sub(" ", text.replace(" ", " ")).strip()


def slugify(text: str, max_length: int = 60) -> str:
    """Lowercase ASCII slug, used as a native id where a board has none."""
    s = re.sub(r"[^a-z0-9]+", "-", clean(text).lower()).strip("-")
    return s[:max_length] or "untitled"


@dataclass
class ListingRow:
    """One posting as it appears on a board's listing page."""

    native_id: str
    title: str
    detail_url: str
    company: str = ""
    date_posted: str = ""
    #: Whatever text the listing itself exposes. For listing-only sources
    #: this is all the text keyword matching will ever see.
    teaser: str = ""
    #: Board-specific extras (deadline, appointment percent, employment
    #: type). Not persisted as columns; kept for logging and future use.
    extra: dict = field(default_factory=dict)

    def job_id(self, source_key: str) -> str:
        return f"{source_key}:{self.native_id}"


@dataclass
class Detail:
    """The three text fields the matcher and detail pane consume."""

    job_description: str = ""
    requirements: str = ""
    skills: str = ""


class ListingParseError(Exception):
    """The page arrived but did not look like the board's listing.

    Raised instead of returning ``[]`` so that a markup change reads as a
    failed fetch -- which archives nothing -- rather than as an empty board.
    """


@dataclass(frozen=True)
class Source:
    """One job board.

    `fetch_listing` returns every posting currently on the board. It should
    return an empty list for a board with no openings, and raise only when
    the fetch genuinely failed -- the pipeline uses that difference to
    decide whether archiving this source's jobs is safe.
    """

    key: str
    label: str
    fetch_listing: Callable[[], list[ListingRow]]
    supports_detail: bool = False
    fetch_detail: Optional[Callable[[ListingRow], Detail]] = None
    #: True when ``fetch_listing`` returns ``[]`` only for a board that
    #: positively says it has no openings (and raises on anything it cannot
    #: read). Only then does an empty listing archive the source's old
    #: rows; otherwise it is treated as a possible silent parser failure.
    empty_is_reliable: bool = False
