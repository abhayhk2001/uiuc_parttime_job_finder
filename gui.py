#!/usr/bin/env python3
"""Root shim so `python gui.py` keeps working.

The real GUI lives in `jobscanner.ui_qt.app`.

With ``--scan-and-open`` the shim first runs a full scan and only then
opens the GUI. This is the entry point the launchd nightly agent uses:
the flag is handled *before* the Qt event loop starts, and the scan
writes into the same AppData database the GUI reads, so the window opens
showing fresh results.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from jobscanner import nightly  # noqa: E402
from jobscanner.ui_qt.app import launch  # noqa: E402


def _run_nightly_scan() -> int:
    """Scan every source once, then let ``launch()`` open the GUI.

    Returns the process exit code. On a scan that reached no board at
    all, returns non-zero *without* recording the marker, so the agent
    retries at the next wake/reboot instead of skipping a whole day.
    """
    if not nightly.is_due():
        print("[nightly] A scan already ran for this slot; skipping.")
        return 0

    print("[nightly] Running scheduled scan…")
    try:
        from jobscanner import config, pipeline

        rc = pipeline.run(dry_run=False, verbose=False, fetch_missing=True,
                          path=config.DB_PATH,
                          keywords_path=config.KEYWORDS_PATH)
    except Exception as exc:  # noqa: BLE001
        print(f"[nightly] scan failed: {exc}", file=sys.stderr)
        return 1

    if rc != 0:
        print("[nightly] Scan reached no source; it will retry on the "
              "next wake/reboot.", file=sys.stderr)
        return rc

    nightly.mark_run()
    print("[nightly] Scan complete; opening the GUI.")
    return 0


if __name__ == "__main__":
    if "--scan-and-open" in sys.argv:
        sys.exit(_run_nightly_scan())
    launch()
