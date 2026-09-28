"""Smoke test for the jobs table port: model + proxy + view + fake data.

Run with: .venv/bin/python tests/smoke_table.py
Does NOT enter the event loop.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtCore import QCoreApplication, QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from jobscanner.ui_qt import palette, theme  # noqa: E402
from jobscanner.ui_qt.jobs_table import JobsTableView  # noqa: E402
from jobscanner.ui_qt.models import COLUMNS, SORT_ROLE, JobRoles, JobsTableModel  # noqa: E402
from jobscanner.ui_qt.proxies import JobsFilterProxy  # noqa: E402


def fake_rows() -> list[dict]:
    return [
        {
            "job_id": "T0",
            "source": "vjb",
            "title": "Backend Engineer (Python)",
            "company": "Acme Corp",
            "job_description": "Build APIs in Flask and FastAPI.",
            "requirements": "3+ years Python, SQL, AWS.",
            "skills": "python, flask, aws",
            "matched_keywords": "python, aws",
            "reviewed": False,
            "to_apply": True,
            "applied_at": None,
            "archived": False,
            "follow_up_at": None,
        },
        {
            "job_id": "T1",
            "source": "vjb",
            "title": "Data Scientist Intern",
            "company": "Globex",
            "job_description": "Work on machine learning pipelines.",
            "requirements": "Statistics, Python, SQL.",
            "skills": "python, ml, sql",
            "matched_keywords": "python",
            "reviewed": True,
            "to_apply": False,
            "applied_at": None,
            "archived": False,
            "follow_up_at": None,
        },
        {
            "job_id": "T2",
            "source": "rp",
            "title": "SWE Intern",
            "company": "Initech",
            "job_description": "Internal tools in Go.",
            "requirements": "Go, REST.",
            "skills": "go",
            "matched_keywords": "",
            "reviewed": False,
            "to_apply": False,
            "applied_at": None,
            "archived": False,
            "follow_up_at": None,
        },
        {
            "job_id": "T3",
            "source": "rp",
            "title": "Research Assistant - HCI",
            "company": "Stark Industries",
            "job_description": "Conduct user studies; Python scripting.",
            "requirements": "HCI coursework, Python.",
            "skills": "python, hci",
            "matched_keywords": "python, hci, research",
            "reviewed": True,
            "to_apply": False,
            "applied_at": "2025-09-15T10:00:00",
            "archived": False,
            "follow_up_at": "2025-10-01T00:00:00",
        },
    ]


def _is_dark(p) -> bool:
    return p is palette.DARK


def main() -> int:
    QCoreApplication.setOrganizationName("UIUC")
    QCoreApplication.setApplicationName("PartTimeJobScanner-Test")
    app = QApplication.instance() or QApplication(sys.argv)
    theme.apply_app(app)
    print(f"theme: {'dark' if _is_dark(theme.current_palette()) else 'light'}")

    # --- model direct tests --------------------------------------------
    model = JobsTableModel()
    rows = fake_rows()
    model.set_rows(rows)
    assert model.rowCount() == 4
    assert model.columnCount() == len(COLUMNS)
    print(f"model rows={model.rowCount()}, cols={model.columnCount()}")

    # DisplayRole checks
    title_cell = model.data(model.index(0, COLUMNS[1].__class__ and 1))
    assert title_cell == "Backend Engineer (Python)", title_cell
    matches_cell = model.data(model.index(0, 3))
    assert matches_cell == "2", f"expected '2', got {matches_cell!r}"
    reviewed_cell = model.data(model.index(1, 4))
    assert reviewed_cell == "\u2713", f"expected checkmark, got {reviewed_cell!r}"

    # SortRole returns int for matches, int for reviewed, lowercased for text
    sort_matches = model.data(model.index(0, 3), SORT_ROLE)
    assert sort_matches == 2, sort_matches
    sort_reviewed = model.data(model.index(0, 4), SORT_ROLE)
    assert sort_reviewed == 0, sort_reviewed
    sort_reviewed_t1 = model.data(model.index(1, 4), SORT_ROLE)
    assert sort_reviewed_t1 == 1, sort_reviewed_t1
    sort_title_t0 = model.data(model.index(0, 1), SORT_ROLE)
    assert sort_title_t0 == "backend engineer (python)", sort_title_t0
    print("model DisplayRole + SortRole OK")

    # JobRoles.JobIdRole / JobDictRole
    t0_id = model.data(model.index(0, 0), JobRoles.JobIdRole)
    assert t0_id == "T0"
    t0_dict = model.data(model.index(0, 0), JobRoles.JobDictRole)
    assert t0_dict["company"] == "Acme Corp"
    print("model custom roles OK")

    # --- proxy tests ----------------------------------------------------
    proxy = JobsFilterProxy()
    proxy.setSourceModel(model)
    assert proxy.rowCount() == 4

    # Matches only
    proxy.set_matches_only(True)
    assert proxy.rowCount() == 3, f"matches_only should keep 3, got {proxy.rowCount()}"
    proxy.set_matches_only(False)
    assert proxy.rowCount() == 4
    print(f"proxy matches_only filter OK")

    # Search text
    proxy.set_search_text("intern")
    # T1 (Data Scientist Intern) and T2 (SWE Intern) should match.
    visible_ids = []
    for r in range(proxy.rowCount()):
        pidx = proxy.index(r, 0)
        sidx = proxy.mapToSource(pidx)
        visible_ids.append(model.data(sidx, JobRoles.JobIdRole))
    assert sorted(visible_ids) == ["T1", "T2"], visible_ids
    print(f"proxy search 'intern' -> {sorted(visible_ids)}")

    proxy.set_search_text("python")
    visible_ids = []
    for r in range(proxy.rowCount()):
        pidx = proxy.index(r, 0)
        sidx = proxy.mapToSource(pidx)
        visible_ids.append(model.data(sidx, JobRoles.JobIdRole))
    assert sorted(visible_ids) == ["T0", "T1", "T3"], visible_ids
    print(f"proxy search 'python' -> {sorted(visible_ids)}")

    # Combined: matches_only + search
    proxy.set_matches_only(True)
    proxy.set_search_text("hci")
    visible_ids = []
    for r in range(proxy.rowCount()):
        pidx = proxy.index(r, 0)
        sidx = proxy.mapToSource(pidx)
        visible_ids.append(model.data(sidx, JobRoles.JobIdRole))
    assert visible_ids == ["T3"], visible_ids
    print(f"proxy matches_only + 'hci' -> {visible_ids}")

    proxy.set_matches_only(False)
    proxy.set_search_text("")

    # --- view tests -----------------------------------------------------
    view = JobsTableView()
    view.resize(900, 400)
    view.show()
    app.processEvents()
    view.set_rows(fake_rows())
    app.processEvents()
    # The view groups by source, so proxy().rowCount() counts *sections*;
    # visible_job_count() is the number of jobs.
    assert view.proxy().rowCount() == 2, view.proxy().rowCount()
    assert view.visible_job_count() == 4, view.visible_job_count()
    assert view.visible_group_keys() == ["vjb", "rp"], view.visible_group_keys()
    sel = view.selected_id()
    assert sel is None
    print(f"view sections={view.visible_group_keys()} "
          f"jobs={view.visible_job_count()}, initial selection={sel}")

    # Select T2 and verify
    assert view.select_id("T2")
    app.processEvents()
    assert view.selected_id() == "T2"
    assert view.current_job_dict()["company"] == "Initech"
    print(f"view selected {view.selected_id()} ({view.current_job_dict()['company']})")

    # Sorting: click 'matches' header, verify T3 (3) > T0 (2) > T1 (1) > T2 (0)
    matches_col = [c.key for c in COLUMNS].index("matches")
    view.sortByColumn(matches_col, Qt.DescendingOrder)
    app.processEvents()
    ids = view.visible_job_ids()
    # Sorting happens inside each section: vjb holds T0/T1, rp holds T2/T3.
    assert ids[0] == "T0", ids       # 2 matches beats T1's 1
    assert ids[2] == "T3", ids       # 3 matches beats T2's 0
    assert view.visible_group_keys() == ["vjb", "rp"], "sections stay put"
    print(f"view sorted by matches desc -> {ids}")

    # Empty state
    view.set_rows([])
    view.set_empty_message("No matching jobs.")
    app.processEvents()
    assert view.proxy().rowCount() == 0
    assert view.visible_job_count() == 0
    print("view empty state OK")

    # Re-populate so we have rows to test foreground on.
    view.set_rows(fake_rows())
    app.processEvents()

    # Palette refresh: flip theme to dark, refresh model.
    QSettings().setValue("appearance/override", "dark")
    theme._set_palette_and_qss(app, palette.DARK)
    view.refresh_palette()
    app.processEvents()
    # The ForegroundRole for a matched-unreviewed row should still be a
    # valid QColor (palette.MATCH_FG in dark mode). index(0, 0) is now a
    # section heading, so reach into its first job.
    model = view.source_model()
    first_job = model.index(0, 0, model.index(0, 0))
    assert model.data(first_job, JobRoles.JobIdRole) == "T0", \
        model.data(first_job, JobRoles.JobIdRole)
    fg = model.data(first_job, Qt.ForegroundRole)
    if hasattr(fg, "name"):
        print(f"dark-mode foreground after refresh = {fg.name()}")
        assert fg.name().lower() == palette.DARK["match_fg"].lower()
    else:
        raise AssertionError(f"expected a QColor, got {fg!r}")

    # Restore auto.
    QSettings().setValue("appearance/override", "auto")
    theme._set_palette_and_qss(app, theme._detect_palette())
    view.refresh_palette()

    print("table smoke test OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
