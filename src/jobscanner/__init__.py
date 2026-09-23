"""UIUC Virtual Job Board scanner.

Scrapes the VJB "Other University Positions" listing into a local SQLite
database, matches postings against a keyword list, and ships a
CustomTkinter GUI for triaging them.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
