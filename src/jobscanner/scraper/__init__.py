"""Network + HTML layer: talking to the VJB site and turning it into dicts."""

from jobscanner.scraper.parsing import parse_detail, parse_listing
from jobscanner.scraper.session import VJBError, VJBSession

__all__ = ["VJBError", "VJBSession", "parse_detail", "parse_listing"]
