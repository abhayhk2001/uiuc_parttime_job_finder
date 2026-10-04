"""Render the skeleton window + jobs table to a PNG for visual inspection.

Run with: .venv/bin/python tests/snapshot_skeleton.py /tmp/skeleton.png
Uses ``QWidget.grab()`` so no real display server interaction is needed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Keep this script's window state and data out of the real app's: its own
# QSettings scope, and a throwaway DB instead of config.DB_PATH.
os.environ["JOBSCANNER_SETTINGS_APP"] = "PartTimeJobScanner-Snapshot"

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from support import TempDB  # noqa: E402

from jobscanner import storage as db  # noqa: E402
from jobscanner.ui_qt import theme  # noqa: E402
from jobscanner.ui_qt.app import JobScannerApp  # noqa: E402


def fake_rows() -> list[dict]:
    return [
        {
            "job_id": "T0", "title": "Backend Engineer (Python)",
            "company": "Acme Corp",
            "matched_keywords": "python, aws", "reviewed": False, "to_apply": True,
            "applied_at": None, "archived": False, "follow_up_at": None,
            "job_description": (
                "Build distributed backend services in Python using FastAPI. "
                "Work with our platform team to design gRPC APIs, deploy on AWS, "
                "and contribute to our event-driven architecture built on Kafka."
            ),
            "requirements": (
                "3+ years professional Python experience. Strong SQL and "
                "familiarity with at least one cloud provider (AWS preferred). "
                "Experience with FastAPI, Flask, or Django."
            ),
            "skills": "python, fastapi, grpc, kafka, aws, sql",
            "detail_url": "https://example.com/jobs/T0",
        },
        {
            "job_id": "T1", "title": "Data Scientist Intern",
            "company": "Globex",
            "matched_keywords": "python", "reviewed": True, "to_apply": False,
            "applied_at": None, "archived": False, "follow_up_at": None,
            "job_description": "Work on machine learning pipelines.",
            "requirements": "Statistics, Python, SQL.",
            "skills": "python, ml, sql",
            "detail_url": "https://example.com/jobs/T1",
        },
        {
            "job_id": "T2", "title": "SWE Intern", "company": "Initech",
            "matched_keywords": "", "reviewed": False, "to_apply": False,
            "applied_at": None, "archived": False, "follow_up_at": None,
            "job_description": "Internal tools in Go.",
            "requirements": "Go, REST.",
            "skills": "go",
            "detail_url": "https://example.com/jobs/T2",
        },
        {
            "job_id": "T3", "title": "Research Assistant - HCI",
            "company": "Stark Industries",
            "matched_keywords": "python, hci, research", "reviewed": True,
            "to_apply": False, "applied_at": "2025-09-15",
            "archived": False, "follow_up_at": "2025-10-01",
            "job_description": "Conduct user studies.",
            "requirements": "HCI coursework, Python.",
            "skills": "python, hci",
            "detail_url": "https://example.com/jobs/T3",
        },
    ]


def main() -> int:
    with TempDB() as db_path:
        db.init_db(db_path)
        return _main(db_path)


def _main(db_path: Path) -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/skeleton.png")
    QCoreApplication.setOrganizationName("UIUC")
    QCoreApplication.setApplicationName("PartTimeJobScanner-Snapshot")
    app = QApplication.instance() or QApplication(sys.argv)
    theme.apply_app(app)

    w = JobScannerApp(db_path, db_path.parent / "keywords.json")
    w.resize(1380, 860)
    w._table.set_rows(fake_rows())
    w.show()
    app.processEvents()

    # Pick a row so the highlight is visible.
    w._table.select_id("T0")
    app.processEvents()

    pix = w.grab()
    pix.save(str(out_path), "PNG")
    print(f"wrote {out_path} ({pix.width()}x{pix.height()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
