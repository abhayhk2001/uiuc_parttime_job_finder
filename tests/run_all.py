#!/usr/bin/env python3
"""Run every test module in this directory.

    python tests/run_all.py

GUI modules skip themselves where Tk or customtkinter isn't available, so
this is safe to run headless — the storage tests still execute.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from support import bootstrap, gui_available, run_module

bootstrap()

#: Storage first: if it's broken, the GUI failures are just noise.
MODULES = (
    ("test_db_isolated", "Storage layer", False),
    ("test_gui_workflow", "GUI workflow", True),
    ("test_gui_layout", "GUI layout", True),
    ("test_gui_bulk_actions", "GUI bulk actions", True),
    ("test_gui_interactions", "GUI interactions", True),
)


def main() -> int:
    gui_ok, gui_reason = gui_available()
    if not gui_ok:
        print(f"note: GUI tests will skip — {gui_reason}")

    totals = [0, 0, 0]
    for module_name, title, needs_gui in MODULES:
        module = importlib.import_module(module_name)
        passed, failed, skipped = run_module(
            vars(module), title,
            skip_reason="" if (gui_ok or not needs_gui) else gui_reason,
        )
        totals[0] += passed
        totals[1] += failed
        totals[2] += skipped

    passed, failed, skipped = totals
    print("\n" + "=" * 52)
    summary = f"TOTAL: {passed} passed, {failed} failed"
    if skipped:
        summary += f", {skipped} skipped"
    print(summary)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
