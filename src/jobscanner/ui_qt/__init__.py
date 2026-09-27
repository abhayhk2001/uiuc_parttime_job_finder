"""PySide6 (Qt) implementation of the UI.

The legacy :mod:`jobscanner.ui` package used CustomTkinter. This package is
its successor: a QMainWindow-based native desktop UI. Storage, scraping,
matching and the CLI entry point are all UI-framework agnostic and were not
changed during the port.
"""

from __future__ import annotations
