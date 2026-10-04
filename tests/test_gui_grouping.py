"""The jobs table's per-source sections.

Rows are grouped into a collapsible section per board rather than carrying a
Source column. These cover the model's shape, that sorting never reshuffles
the sections, that filtering drops empty ones, and that collapse state
survives a relaunch.

    python tests/test_gui_grouping.py
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QModelIndex, Qt

from support import (  # noqa: E402
    check, eq, gui_available, pump_events, qt_only, run_module,
)

from jobscanner.sources import SOURCE_LABELS  # noqa: E402
from jobscanner.ui_qt.jobs_table import JobsTableView, _COLLAPSED_KEY  # noqa: E402
from jobscanner.ui_qt.models import COLUMNS, JobRoles, JobsTreeModel  # noqa: E402
from jobscanner.ui_qt.settings import app_settings  # noqa: E402

#: Deliberately out of registry order, so ordering can't pass by accident.
ROWS = [
    {"job_id": "ach:7", "source": "ach", "title": "Teaching Assistant",
     "company": "Grad College", "matched_keywords": "", "reviewed": 0},
    {"job_id": "rp:100", "source": "rp", "title": "Mango Engineer",
     "company": "Philowave", "matched_keywords": "ai,python", "reviewed": 0},
    {"job_id": "vjb:1", "source": "vjb", "title": "Zebra Assistant",
     "company": "Dept A", "matched_keywords": "python", "reviewed": 0},
    {"job_id": "rp:101", "source": "rp", "title": "Banana Intern",
     "company": "Brunswick", "matched_keywords": "", "reviewed": 0},
    {"job_id": "vjb:2", "source": "vjb", "title": "Alpha Tech",
     "company": "Dept B", "matched_keywords": "", "reviewed": 1},
]


def _clear_collapsed() -> None:
    app_settings().remove(_COLLAPSED_KEY)


def _view(rows=None) -> JobsTableView:
    _clear_collapsed()
    view = JobsTableView()
    view.set_rows(list(ROWS if rows is None else rows))
    view.show()
    pump_events()
    return view


def _col(key: str) -> int:
    for i, column in enumerate(COLUMNS):
        if column.key == key:
            return i
    raise AssertionError(f"no {key!r} column")


# ---------------------------------------------------------------------------
# Model shape
# ---------------------------------------------------------------------------

def test_source_is_not_a_column() -> None:
    eq([c.key for c in COLUMNS],
       ["job_id", "title", "company", "matches", "reviewed"],
       "the board's name belongs to the section heading, not a column")


def test_groups_follow_registry_order() -> None:
    with qt_only():
        view = _view()
        eq(view.visible_group_keys(), ["vjb", "rp", "ach"],
           "sections follow the SOURCES order, not alphabetical or input order")
        eq(view.proxy().rowCount(), 3, "one section per source present")
        eq(view.visible_job_count(), 5, "every job is still visible")


def test_group_headings_carry_a_count() -> None:
    with qt_only():
        view = _view()
        model = view.source_model()
        headings = [model.group_at(i).heading for i in range(3)]
        check(f"{SOURCE_LABELS['vjb']}  (2)" in headings,
              f"VJB heading shows its 2 rows ({headings})")
        check(f"{SOURCE_LABELS['rp']}  (2)" in headings,
              f"Research Park heading shows its 2 rows ({headings})")


def test_a_source_with_no_rows_gets_no_section() -> None:
    with qt_only():
        view = _view([r for r in ROWS if r["source"] == "rp"])
        eq(view.visible_group_keys(), ["rp"],
           "only boards with rows appear; Library contributes nothing")


def test_group_rows_are_not_jobs() -> None:
    with qt_only():
        view = _view()
        model = view.source_model()
        group_idx = model.index(0, 0)
        check(model.is_group(group_idx), "top-level rows are sections")
        check(model.data(group_idx, JobRoles.JobIdRole) is None,
              "a section has no job id")
        check(model.data(group_idx, JobRoles.JobDictRole) is None,
              "a section has no job dict")
        check(model.data(group_idx, Qt.FontRole) is not None,
              "a section heading is styled distinctly")


def test_group_rows_span_the_full_width() -> None:
    with qt_only():
        view = _view()
        for i in range(view.proxy().rowCount()):
            check(view.isFirstColumnSpanned(i, QModelIndex()),
                  f"section {i} heading spans the view")


def test_parent_child_navigation_round_trips() -> None:
    with qt_only():
        view = _view()
        model = view.source_model()
        group_idx = model.index(0, 0)
        child = model.index(0, 0, group_idx)
        check(child.isValid(), "sections have children")
        eq(model.parent(child).row(), group_idx.row(),
           "a child's parent is its own section")
        check(not model.parent(group_idx).isValid(),
              "a section's parent is the invisible root")
        eq(model.rowCount(child), 0, "job rows have no children")


# ---------------------------------------------------------------------------
# Sorting and filtering
# ---------------------------------------------------------------------------

def test_sorting_reorders_jobs_but_never_sections() -> None:
    with qt_only():
        view = _view()
        title = _col("title")

        view.sortByColumn(title, Qt.AscendingOrder)
        pump_events()
        eq(view.visible_group_keys(), ["vjb", "rp", "ach"],
           "ascending sort keeps section order")
        ascending = view.visible_job_ids()

        view.sortByColumn(title, Qt.DescendingOrder)
        pump_events()
        eq(view.visible_group_keys(), ["vjb", "rp", "ach"],
           "descending sort keeps section order too -- Qt negates lessThan, "
           "so the group branch has to compensate")
        descending = view.visible_job_ids()

        check(ascending != descending, "jobs did actually reorder")
        # Within the VJB section: Alpha before Zebra ascending, reversed after.
        eq(ascending[:2], ["vjb:2", "vjb:1"], "jobs sort inside their section")
        eq(descending[:2], ["vjb:1", "vjb:2"], "and flip with direction")


def test_filtering_drops_sections_with_no_matches() -> None:
    with qt_only():
        view = _view()
        view.set_search_text("Mango")
        pump_events()
        eq(view.visible_group_keys(), ["rp"],
           "only the section holding a match survives")
        eq(view.visible_job_ids(), ["rp:100"], "and only the matching job")

        view.set_search_text("zzz-nothing")
        pump_events()
        eq(view.proxy().rowCount(), 0, "no matches leaves no sections")
        eq(view.visible_job_count(), 0, "and no jobs")

        view.set_search_text("")
        pump_events()
        eq(view.visible_job_count(), 5, "clearing the search restores everything")


def test_matches_only_filters_within_sections() -> None:
    with qt_only():
        view = _view()
        view.set_matches_only(True)
        pump_events()
        eq(view.visible_group_keys(), ["vjb", "rp"],
           "the Clearinghouse section has no matches and disappears")
        eq(sorted(view.visible_job_ids()), ["rp:100", "vjb:1"],
           "only matching jobs remain")


# ---------------------------------------------------------------------------
# Selection and collapse
# ---------------------------------------------------------------------------

def test_selecting_a_heading_selects_no_job() -> None:
    with qt_only():
        view = _view()
        view.setCurrentIndex(view.proxy().index(0, 0))
        pump_events()
        check(view.selected_id() is None,
              "a section heading must not read as a selected job")
        check(view.current_job_dict() is None, "and carries no job dict")


def test_select_id_expands_a_collapsed_section() -> None:
    with qt_only():
        view = _view()
        rp_row = view.visible_group_keys().index("rp")
        view.collapse(view.proxy().index(rp_row, 0))
        pump_events()
        check(not view.isExpanded(view.proxy().index(rp_row, 0)),
              "section starts collapsed")

        check(view.select_id("rp:100"), "the job is still selectable")
        pump_events()
        eq(view.selected_id(), "rp:100", "and becomes the selection")
        check(view.isExpanded(view.proxy().index(rp_row, 0)),
              "selecting a hidden job reveals it")
        _clear_collapsed()


def test_collapse_state_survives_a_relaunch() -> None:
    with qt_only():
        view = _view()
        rp_row = view.visible_group_keys().index("rp")
        view.collapse(view.proxy().index(rp_row, 0))
        pump_events()
        eq(sorted(view.collapsed_sources()), ["rp"], "collapse was persisted")

        fresh = JobsTableView()
        fresh.set_rows(list(ROWS))
        fresh.show()
        pump_events()
        keys = fresh.visible_group_keys()
        states = {k: fresh.isExpanded(fresh.proxy().index(i, 0))
                  for i, k in enumerate(keys)}
        eq(states.get("rp"), False, "Research Park reopens collapsed")
        eq(states.get("vjb"), True, "the others reopen expanded")
        _clear_collapsed()


def test_empty_model_is_safe() -> None:
    with qt_only():
        view = _view([])
        eq(view.proxy().rowCount(), 0, "no sections")
        eq(view.visible_job_ids(), [], "no jobs")
        check(view.source_model().group_at(0) is None, "no group at 0")


if __name__ == "__main__":
    ok, reason = gui_available()
    _, failed, _ = run_module(globals(), "Table grouping",
                              skip_reason="" if ok else reason)
    sys.exit(1 if failed else 0)
