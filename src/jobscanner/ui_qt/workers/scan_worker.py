"""The scan worker.

``ScanWorker`` is a ``QObject`` that runs :func:`jobscanner.pipeline.run`
on a background thread. It mirrors the app's stdout/stderr into a Qt
signal (``textWritten``) so the log dock can append without polling.

The class is intentionally framework-agnostic about threading: the caller
is expected to ``moveToThread`` it and bind ``started`` /
``finished`` signals as needed. The :mod:`jobscanner.ui_qt.app` module
wires the QThread in.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal

from jobscanner import pipeline


class _StreamRelay:
    """File-like shim that mirrors writes into a Qt signal.

    Replaces the old ``StreamToQueue`` -- the queue is gone, the work is
    now done by Qt's queued signal connections.
    """

    def __init__(self, owner: "ScanWorker", original) -> None:
        self._owner = owner
        self._original = original
        self._pending = ""

    def write(self, s: str) -> int:
        # Emit whole lines only. print() writes its text and the "\n" as
        # separate calls, and the log dock appends each emission as its own
        # line, so every line used to be followed by a blank one.
        if s:
            self._pending += s
            *lines, self._pending = self._pending.split("\n")
            for line in lines:
                self._owner.textWritten.emit(line)
        try:
            self._original.write(s)
            self._original.flush()
        except Exception:  # noqa: BLE001
            pass
        return len(s) if s is not None else 0

    def flush(self) -> None:
        try:
            self._original.flush()
        except Exception:  # noqa: BLE001
            pass

    def close(self) -> None:
        """Emit any trailing text that never got its newline."""
        if self._pending:
            self._owner.textWritten.emit(self._pending)
            self._pending = ""


class ScanWorker(QObject):
    """Runs a single scan and emits ``textWritten`` for each line of output.

    Use as::

        thread = QThread()
        worker = ScanWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()
    """

    #: Emitted for every chunk of stdout/stderr the pipeline produces.
    textWritten = Signal(str)

    #: Emitted once when the pipeline returns (or raises).
    #: ``success`` is True iff ``pipeline.run`` returned 0.
    finished = Signal(bool)

    def __init__(self, dry_run: bool = False, fetch_missing: bool = True,
                 db_path: Optional[Path] = None,
                 keywords_path: Optional[Path] = None,
                 parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._dry_run = dry_run
        self._fetch_missing = fetch_missing
        # The window is constructed with its own db_path; without passing it
        # through, a scan would write to whichever DB config points at.
        self._db_path = db_path
        # Same for keywords: match against the file the editor writes.
        self._keywords_path = keywords_path

    def run(self) -> None:
        """Run the scan. Always emits ``finished`` exactly once."""
        original_out, original_err = sys.stdout, sys.stderr
        relays = (_StreamRelay(self, original_out), _StreamRelay(self, original_err))
        sys.stdout, sys.stderr = relays  # type: ignore[assignment]
        success = False
        try:
            rc = pipeline.run(
                dry_run=self._dry_run,
                verbose=False,
                fetch_missing=self._fetch_missing,
                path=self._db_path,
                keywords_path=self._keywords_path,
            )
            success = (rc == 0)
        except Exception as exc:  # noqa: BLE001
            self.textWritten.emit(f"[gui] scan failed: {exc}\n")
        finally:
            sys.stdout, sys.stderr = original_out, original_err
            for relay in relays:
                relay.close()
            self.finished.emit(success)
