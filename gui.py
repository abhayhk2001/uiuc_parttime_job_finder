#!/usr/bin/env python3
"""Root shim so `python gui.py` keeps working.

The real GUI lives in `jobscanner.ui.app`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from jobscanner.ui.app import launch  # noqa: E402

if __name__ == "__main__":
    launch()
