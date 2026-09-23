"""The sidebar's bulk actions, driven through the registry.

Confirmation dialogs are stubbed so the destructive actions can be
exercised headlessly, in both the accept and the cancel direction.

    python tests/test_gui_bulk_actions.py
"""

from __future__ import annotations

import sys

from support import (  # noqa: E402
    answer_dialogs, check, eq, gui_app, gui_available, run_module,
)

from jobscanner import storage as db  # noqa: E402
from jobscanner.ui.bulk_actions import (  # noqa: E402
    BULK_ACTIONS, BULK_ACTIONS_BY_ID,
)


def test_buttons_are_keyed_by_action_id_not_caption() -> None:
    """Regression: buttons were keyed by their English label, which also
    served as the dispatch discriminator, so renaming one broke both."""
    with gui_app() as (app, _path, _kw):
        eq(set(app.sections_panel._bulk_buttons),
           {action.id for action in BULK_ACTIONS},
           "bulk buttons are keyed by action id")


def test_buttons_are_enabled_only_when_their_section_has_rows() -> None:
    with gui_app() as (app, path, _kw):
        eq(str(app.sections_panel._bulk_buttons["apply_all_to_apply"].cget("state")),
           "disabled", "To Apply actions start disabled with an empty section")
        db.set_to_apply("T0", True, path)
        app.refresh()
        app.update()
        eq(str(app.sections_panel._bulk_buttons["apply_all_to_apply"].cget("state")),
           "normal", "and enable once the section has rows")


def test_destructive_actions_confirm_first() -> None:
    with gui_app() as (app, path, _kw):
        for i in range(3):
            db.set_to_apply(f"T{i}", True, path)
        app.refresh()
        app.update()

        with answer_dialogs(True) as asked:
            app.bulk_mark_section("apply_all_to_apply")
            app.update()
        eq(len(asked), 1, "the action asked for confirmation")
        eq(db.get_section_counts(path)["follow_up"], 3,
           "all 3 moved to Follow Up")
        check("moved to Follow Up" in app.toolbar.status_var.get(),
              f"the result was toasted ({app.toolbar.status_var.get()!r})")


def test_cancelling_a_confirmation_changes_nothing() -> None:
    with gui_app() as (app, path, _kw):
        for i in range(3):
            db.mark_applied(f"T{i}", path)
        app.refresh()
        app.update()
        before = db.get_section_counts(path)["follow_up"]

        with answer_dialogs(False) as asked:
            app.bulk_mark_section("archive_follow_up")
            app.update()
        eq(len(asked), 1, "it still prompted")
        eq(db.get_section_counts(path)["follow_up"], before,
           "cancelling leaves the data untouched")


def test_non_destructive_actions_act_immediately() -> None:
    with gui_app() as (app, path, _kw):
        db.mark_applied("T0", path)
        app.refresh()
        app.update()
        with answer_dialogs(False) as asked:
            app.bulk_mark_section("further_follow_up")
            app.update()
        eq(len(asked), 0, "no confirmation for a non-destructive action")
        check("Reset follow-up date" in app.toolbar.status_var.get(),
              "it still reports its result")


def test_every_registered_action_runs() -> None:
    """Each action, against a section that actually has rows in it."""
    with gui_app(count=9) as (app, path, _kw):
        with answer_dialogs(True):
            for i in range(3):
                db.set_to_apply(f"T{i}", True, path)
            app.refresh()
            app.bulk_mark_section("apply_all_to_apply")
            app.update()
            eq(db.get_section_counts(path)["follow_up"], 3, "applied in bulk")

            app.bulk_mark_section("further_follow_up")
            app.update()
            app.bulk_mark_section("archive_follow_up")
            app.update()
            eq(db.get_section_counts(path)["archived"], 3, "archived in bulk")

            app.bulk_mark_section("review_new")
            app.update()
            eq(db.get_section_counts(path)["reviewed"], 6, "reviewed the rest")

            app.bulk_mark_section("revisit_reviewed")
            app.update()
            eq(db.get_section_counts(path)["reviewed"], 0, "revisited them")

            for i in range(6, 9):
                db.set_to_apply(f"T{i}", True, path)
            app.refresh()
            app.bulk_mark_section("clear_to_apply")
            app.update()
            eq(db.get_section_counts(path)["to_apply"], 0, "cleared To Apply")

            app.bulk_mark_section("review_old")
            app.update()

        eq(len(BULK_ACTIONS_BY_ID), 7, "all seven actions are registered")


def test_unknown_action_id_is_a_noop() -> None:
    with gui_app() as (app, path, _kw):
        before = db.get_section_counts(path)
        app.bulk_mark_section("no_such_action")
        app.update()
        eq(db.get_section_counts(path), before, "an unknown id changes nothing")


def test_all_section_is_available_and_counted() -> None:
    """SECTION_ALL was fully implemented in storage but had no button, so
    search could only ever scan one section at a time."""
    with gui_app() as (app, _path, _kw):
        check(db.SECTION_ALL in app.sections_panel._section_buttons,
              "the sidebar has an All entry")
        app.select_section(db.SECTION_ALL)
        app.update()
        eq(len(app.jobs_table.tree.get_children()), 6, "All lists every job")
        check("(6)" in app.sections_panel._section_buttons[db.SECTION_ALL].cget("text"),
              "All shows a live count")


def test_toast_reverts_to_the_status_line() -> None:
    with gui_app() as (app, _path, _kw):
        app.toolbar.show_toast("temporary message", app._refresh_status, ms=60)
        check("temporary" in app.toolbar.status_var.get(), "the toast is shown")
        app.after(200, app.quit)
        app.mainloop()
        check("jobs" in app.toolbar.status_var.get(),
              f"it reverted ({app.toolbar.status_var.get()!r})")


if __name__ == "__main__":
    ok, reason = gui_available()
    _, failed, _ = run_module(globals(), "GUI bulk actions",
                              skip_reason="" if ok else reason)
    sys.exit(1 if failed else 0)
