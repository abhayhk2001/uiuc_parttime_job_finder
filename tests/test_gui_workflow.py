"""End-to-end GUI behaviour: sections, selection, the job state machine,
sorting, filtering and the dialogs.

Runs headlessly against throwaway databases — the real data/jobs.db is
never opened. Skips cleanly where Tk or customtkinter isn't available.

    python tests/test_gui_workflow.py
"""

from __future__ import annotations

import sys

from support import check, eq, gui_app, gui_available, run_module  # noqa: E402

from jobscanner import storage as db  # noqa: E402


def test_each_section_queries_without_error() -> None:
    with gui_app() as (app, path, _kw):
        for section in db.VALID_SECTIONS:
            app.select_section(section)
            app.update()
            eq(app.section_var, section, "section should be selected")
        app.select_section(db.SECTION_ALL)
        app.update()
        eq(len(app.jobs_table.tree.get_children()), 6,
           "All should list every seeded job")


def test_selecting_a_row_populates_the_detail_pane() -> None:
    with gui_app() as (app, _path, _kw):
        app.select_section(db.SECTION_NEW)
        app.update()
        eq(len(app.jobs_table.tree.get_children()), 6,
           "all seeded rows should start in New")
        app.jobs_table.select("T0")
        app.update()
        eq(app.detail.job_id, "T0", "detail should follow the selection")
        check("Job 0" in app.detail.title_label.cget("text"),
              "detail shows the job title")
        check("Dept 0" in app.detail.meta_label.cget("text"),
              "detail shows the company")


def test_state_machine_walk() -> None:
    """New -> To Apply -> Follow Up -> Archived -> back."""
    with gui_app() as (app, path, _kw):
        app.select_section(db.SECTION_ALL)
        app.update()
        app.jobs_table.select("T0")
        app.update()

        check(app.detail.primary_btn.cget("text").endswith("Mark Reviewed"),
              "an untouched row offers Mark Reviewed")
        app._run_job_op(app.detail._secondary_op)   # Add to To Apply
        app.update()
        check(bool(db.get_job("T0", path)["to_apply"]), "row moved to To Apply")

        check(app.detail.primary_btn.cget("text").endswith("Mark Applied"),
              "a To Apply row offers Mark Applied")
        app._run_job_op(app.detail._primary_op)     # Mark Applied
        app.update()
        row = db.get_job("T0", path)
        check(bool(row["applied_at"]) and bool(row["follow_up_at"]),
              "Mark Applied records applied_at and follow_up_at")

        check(app.detail.primary_btn.cget("text").endswith("Further Follow Up"),
              "a Follow Up row offers Mark Further Follow Up")
        check(app.detail.follow_up_btn.winfo_manager() == "grid",
              "the follow-up date editor is offered for Follow Up rows")
        app._run_job_op(app.detail._secondary_op)   # Archive
        app.update()
        check(bool(db.get_job("T0", path)["archived"]), "row archived")

        check(app.detail.primary_btn.cget("text").endswith("Unarchive"),
              "an archived row offers Unarchive")
        eq(str(app.detail.secondary_btn.cget("state")), "disabled",
           "an archived row's secondary button is disabled")
        app._run_job_op(app.detail._primary_op)     # Unarchive
        app.update()
        check(not db.get_job("T0", path)["archived"], "row unarchived")


def test_archived_to_apply_row_label_matches_its_action() -> None:
    """Regression: the label and the click handler checked the four flags in
    different orders, so an auto-archived To Apply row showed "Unarchive"
    but ran mark_applied when clicked."""
    from jobscanner.ui import job_actions

    with gui_app() as (_app, path, _kw):
        db.set_to_apply("T1", True, path)
        db.archive_job("T1", path)
        state = job_actions.JobState.from_row(db.get_job("T1", path))
        eq(job_actions.primary_action(state).op, job_actions.OP_UNARCHIVE,
           "archived wins over to_apply for both label and action")
        check(not job_actions.secondary_action(state).enabled,
              "archived row has no secondary action")


def test_follow_up_date_editor_saves() -> None:
    from jobscanner.ui.dialogs.follow_up import FollowUpDateEditor

    with gui_app() as (app, path, _kw):
        db.mark_applied("T2", path)
        dialog = FollowUpDateEditor(app, "T2", "", on_save=lambda: None,
                                    db_path=path)
        app.update()
        dialog._apply_offset(30)
        app.update()
        follow_up = db.get_job("T2", path)["follow_up_at"]
        check(bool(follow_up), "preset wrote a follow-up date")
        check(follow_up > db.now_iso(), "the new date is in the future")


def test_follow_up_presets_each_get_their_own_cell() -> None:
    """Regression: all six presets gridded into column 0 across two rows, so
    three landed in each cell and only the last of each trio was visible."""
    from jobscanner.ui.dialogs.follow_up import FollowUpDateEditor

    with gui_app() as (app, path, _kw):
        dialog = FollowUpDateEditor(app, "T0", "", on_save=lambda: None,
                                    db_path=path)
        app.update()
        cells = [(b.grid_info().get("row"), b.grid_info().get("column"))
                 for b in dialog.preset_buttons]
        eq(len(set(cells)), len(cells),
           f"every preset needs its own grid cell (cells={cells})")
        eq(len({row for row, _ in cells}), 2, "presets form 2 rows of 3")
        dialog.destroy()


def test_sorting_toggles_and_survives_refresh() -> None:
    with gui_app() as (app, _path, _kw):
        app.select_section(db.SECTION_ALL)
        app.update()

        def order():
            return [app.jobs_table.tree.set(i, "job_id")
                    for i in app.jobs_table.tree.get_children()]

        app.jobs_table.sort_by("job_id")
        app.update()
        ascending = order()
        app.jobs_table.sort_by("job_id")
        app.update()
        descending = order()
        eq(ascending, list(reversed(descending)),
           "clicking the same header twice flips direction")

        heading = app.jobs_table.tree.heading("job_id")["text"]
        check("▲" in heading or "▼" in heading,
              f"the active column shows a direction arrow ({heading!r})")

        app.refresh()
        app.update()
        eq(order(), descending, "the chosen sort survives a refresh")


def test_default_sort_is_applied_on_open() -> None:
    """Regression: 'matches' was declared descending-first but no sort ran
    until the user clicked a header, so the table opened in DB order."""
    with gui_app() as (app, _path, _kw):
        eq(app.jobs_table._sort_col, "matches", "opens sorted by matches")
        check(app.jobs_table._sort_desc, "matches sorts descending first")
        app.select_section(db.SECTION_ALL)
        app.update()
        counts = [int(app.jobs_table.tree.set(i, "matches"))
                  for i in app.jobs_table.tree.get_children()]
        eq(counts, sorted(counts, reverse=True),
           f"rows are ordered by match count on open ({counts})")


def test_search_and_matches_only_filters() -> None:
    with gui_app() as (app, _path, _kw):
        app.select_section(db.SECTION_ALL)
        app.update()
        app.toolbar.search_var.set("Job 3")
        app.update()
        eq(len(app.jobs_table.tree.get_children()), 1, "search narrows the table")

        app.toolbar.clear_search()
        app.update()
        eq(len(app.jobs_table.tree.get_children()), 6, "clearing restores rows")

        app.toolbar.matches_only_var.set(True)
        app.refresh()
        app.update()
        eq(len(app.jobs_table.tree.get_children()), 3,
           "matches-only keeps the 3 matching rows")


def test_keyword_editor_round_trip() -> None:
    from jobscanner.ui.dialogs.keywords import KeywordEditor

    with gui_app() as (app, _path, kw_path):
        editor = KeywordEditor(app, kw_path, on_save=lambda _k: None)
        app.update()
        check("python" in editor.textbox.get("1.0", "end"),
              "the editor loads the existing keywords")
        editor.textbox.delete("1.0", "end")
        editor.textbox.insert("1.0", "alpha\nbeta\nALPHA\n")
        editor._handle_save()
        app.update()

        import json
        saved = json.loads(kw_path.read_text())
        eq(saved, ["alpha", "beta"],
           "save de-duplicates case-insensitively and drops blanks")


def test_sidebar_counts_and_keyword_list() -> None:
    with gui_app() as (app, path, _kw):
        app.refresh()
        app.update()
        counts = db.get_section_counts(path)
        label = app.sections_panel._section_buttons[db.SECTION_NEW].cget("text")
        check(f"({counts['new']})" in label,
              f"sidebar shows the live New count ({label!r})")
        check("2 loaded" in app.sections_panel._kw_count_label.cget("text"),
              "sidebar shows the keyword count")


def test_log_buffers_while_collapsed() -> None:
    """Regression: output logged while the console was hidden was dropped,
    so opening it mid-scan showed an empty box."""
    with gui_app() as (app, _path, _kw):
        check(not app._log_visible, "the log starts collapsed")
        app._append_log("written while collapsed\n")
        app._toggle_log()
        app.update()
        check("while collapsed" in app.log_console.textbox.get("1.0", "end"),
              "buffered output is replayed on open")
        check(app.log_console.master is app.footer,
              "the console lives inside the footer, under its own toggle")
        app._toggle_log()
        app.update()


def test_layout_is_persisted() -> None:
    with gui_app() as (app, path, _kw):
        app.sections_panel.set_expanded_width(321)
        app.sections_panel.set_collapsed(True)
        app._save_layout()
        saved = db.get_layout(path)
        eq(saved["sidebar_width"], 321, "sidebar width persisted")
        eq(saved["sidebar_collapsed"], True, "collapsed flag persisted")


if __name__ == "__main__":
    ok, reason = gui_available()
    _, failed, _ = run_module(globals(), "GUI workflow",
                              skip_reason="" if ok else reason)
    sys.exit(1 if failed else 0)
