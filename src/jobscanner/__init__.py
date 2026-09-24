"""UIUC Virtual Job Board scanner.

Scrapes the VJB "Other University Positions" listing into a local SQLite
database, matches postings against a keyword list, and ships a PySide6
(Qt) GUI for triaging them.
"""

__all__ = ["__version__"]

__version__ = "0.2.0"
