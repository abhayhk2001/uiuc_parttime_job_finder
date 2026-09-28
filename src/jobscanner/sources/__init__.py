"""The job sources the scanner reads, as a registry.

Adding a board means writing one module here and adding it to SOURCES;
nothing in storage, matching or the UI needs to know about it.
"""

from __future__ import annotations

from jobscanner.sources.base import Detail, ListingRow, Source
from jobscanner.sources import clearinghouse, library, research_park, vjb

SOURCES: tuple[Source, ...] = (
    vjb.SOURCE,
    research_park.SOURCE,
    clearinghouse.SOURCE,
    library.SOURCE,
)

SOURCES_BY_KEY: dict[str, Source] = {s.key: s for s in SOURCES}
SOURCE_LABELS: dict[str, str] = {s.key: s.label for s in SOURCES}


def get_source(key: str) -> Source | None:
    return SOURCES_BY_KEY.get(key)


__all__ = [
    "Detail", "ListingRow", "Source",
    "SOURCES", "SOURCES_BY_KEY", "SOURCE_LABELS", "get_source",
]
