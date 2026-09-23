#!/usr/bin/env python3
"""Root shim so `python main.py` keeps working (cron lines, README, habit).

The real entry point is `jobscanner.cli:main`, also installed as the
`jobscanner` console script by `pip install -e .`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from jobscanner.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
