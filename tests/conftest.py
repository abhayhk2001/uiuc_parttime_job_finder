"""pytest bootstrap.

The test modules import shared helpers as ``from support import ...`` so
they also run as plain scripts (``python tests/test_gui_layout.py``).
Under pytest, ``tests/`` is imported as a package, so this directory isn't
on sys.path when the modules are collected — conftest.py is loaded first,
which makes it the right place to fix that.
"""

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
for _entry in (str(_TESTS_DIR.parent / "src"), str(_TESTS_DIR)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)
