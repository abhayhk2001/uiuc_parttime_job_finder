#!/usr/bin/env python3
"""Root shim so `python gui.py` keeps working.

The real GUI lives in `jobscanner.ui_qt.app`.

With ``--scan-and-open`` the shim first runs a full scan and only then
opens the GUI. This is the entry point the launchd nightly agent uses:
the flag is handled *before* any Qt code is imported, and the scan
writes into the same AppData database the GUI reads, so the window opens
showing fresh results.

From the built .app the GUI is opened as a *separate* process via
``/usr/bin/open``, so this scheduled process exits as soon as the scan is
done. If the GUI ran inside it instead, launchd would consider the job
still running for as long as the window stayed open and would skip the
next day's 21:00 slot.
"""

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from jobscanner import nightly  # noqa: E402


def _launch_gui() -> None:
    """Open the GUI in this process (imported lazily so the nightly scan
    never loads Qt)."""
    from jobscanner.ui_qt.app import launch

    launch()


def _scan_with_retries() -> int:
    """Run the scan, retrying while the network is not up yet.

    Right after a wake, launchd can fire the agent before Wi-Fi/DNS is
    back, so every source fails to resolve. Each attempt first checks that
    DNS works (so a dead network does not run a scan or write an extra DB
    backup), then scans; up to ``nightly.SCAN_ATTEMPTS`` attempts,
    ``nightly.RETRY_DELAY_SECONDS`` apart. Returns the last scan's code.
    """
    from jobscanner import config, pipeline

    attempts = nightly.SCAN_ATTEMPTS
    rc = 1
    for attempt in range(1, attempts + 1):
        if nightly.network_up():
            rc = pipeline.run(dry_run=False, verbose=False, fetch_missing=True,
                              path=config.DB_PATH,
                              keywords_path=config.KEYWORDS_PATH)
            if rc == 0:
                return 0
            print(f"[nightly] Attempt {attempt}/{attempts}: no source "
                  "could be reached.", file=sys.stderr)
        else:
            print(f"[nightly] Attempt {attempt}/{attempts}: network is not "
                  "up yet.", file=sys.stderr)
        if attempt < attempts:
            time.sleep(nightly.RETRY_DELAY_SECONDS)
    return rc


def _open_gui() -> bool:
    """Open the GUI after a successful scan. Returns False if it could not.

    Frozen .app: hand the bundle to LaunchServices with ``/usr/bin/open``
    so the GUI is its own process and this one can exit. If the app is
    already open, ``open`` just brings it to the front. From source there
    is no bundle, so fall back to opening the GUI in-process.
    """
    bundle = (nightly.app_bundle(sys.executable)
              if getattr(sys, "frozen", False) else None)
    if bundle is None:
        _launch_gui()
        return True
    try:
        subprocess.run(["/usr/bin/open", str(bundle)], check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"[nightly] could not open {bundle}: {exc}", file=sys.stderr)
        return False
    return True


def _run_nightly_scan() -> int:
    """Scan every source once, then open the GUI.

    Returns the process exit code. On a scan that reached no board at
    all, returns non-zero *without* recording the marker, so the agent
    retries at the next wake/reboot instead of skipping a whole day.
    """
    if not nightly.is_due():
        print("[nightly] A scan already ran for this slot; skipping.")
        return 0

    print("[nightly] Running scheduled scan…")
    try:
        rc = _scan_with_retries()
    except Exception as exc:  # noqa: BLE001
        print(f"[nightly] scan failed: {exc}", file=sys.stderr)
        return 1

    if rc != 0:
        print("[nightly] Scan reached no source; it will retry on the "
              "next wake/reboot.", file=sys.stderr)
        return rc

    nightly.mark_run()
    print("[nightly] Scan complete; opening the GUI.")
    return 0 if _open_gui() else 1


if __name__ == "__main__":
    if "--scan-and-open" in sys.argv:
        sys.exit(_run_nightly_scan())
    _launch_gui()
