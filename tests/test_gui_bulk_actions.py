"""The sidebar's bulk actions, driven through the registry.

Confirmation dialogs are stubbed so the destructive actions can be
exercised headlessly, in both the accept and the cancel direction.

    python tests/test_gui_bulk_actions.py
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QToolButton

from support import (  # noqa: E402
    answer_dialogs, check, eq, gui_app, gui_available, pump_events, run_module,
)

from jobscanner import storage as db  # noqa: E402
from jobscanner.ui_qt.bulk_actions import (  # noqa: E402
    BULK_ACTIONS, BULK_ACTIONS_BY_ID,
)


def test_buttons_are_keyed_by_action_id_not_caption() -> None:
    """Regression: buttons were keyed by their English label, which also
    served as the dispatch discriminator, so renaming one broke both."""
    with gui_app() as (app, _path, _kw):
        buttons = app.sidebar._bulk._buttons
        # Every button is a QToolButton; keys are action ids.
        eq(set(buttons), {action.id for action in BULK_ACTIONS},
           "bulk buttons are keyed by action id")
        eq(all(isinstance(b, QToolButton) for b in buttons.values()),
           True, "every bulk button is a QToolButton")


def test_buttons_are_enabled_only_when_their_section_has_rows() -> None:
    with gui_app() as (app, path, _kw):
        apply_btn = app.sidebar._bulk._buttons["apply_all_to_apply"]
        check(not apply_btn.isEnabled(),
              "To Apply actions start disabled with an empty section")
        db.set_to_apply("T0", True, path)
        app.refresh()
        pump_events()
        check(apply_btn.isEnabled(),
              "and enable once the section has rows")


def test_destructive_actions_confirm_first() -> None:
    with gui_app() as (app, path, _kw):
        for i in range(3):
            db.set_to_apply(f"T{i}", True, path)
        app.refresh()
        pump_events()

        with answer_dialogs(True) as asked:
            app.bulk_mark_section("apply_all_to_apply")
            pump_events()
        eq(len(asked), 1, "the action asked for confirmation")
        eq(db.get_section_counts(path)["follow_up"], 3,
           "all 3 moved to Applied")
        check("moved to Applied" in app.status_bar.currentMessage(),
              f"the result was toasted "
              f"({app.status_bar.currentMessage()!r})")


def test_cancelling_a_confirmation_changes_nothing() -> None:
    with gui_app() as (app, path, _kw):
        for i in range(3):
            db.mark_applied(f"T{i}", path)
        app.refresh()
        pump_events()
        before = db.get_section_counts(path)["follow_up"]

        with answer_dialogs(False) as asked:
            app.bulk_mark_section("archive_follow_up")
            pump_events()
        eq(len(asked), 1, "it still prompted")
        eq(db.get_section_counts(path)["follow_up"], before,
           "cancelling leaves the data untouched")


def test_non_destructive_actions_act_immediately() -> None:
    with gui_app() as (app, _path, _kw):
        db.mark_applied("T0", app.db_path)
        app.refresh()
        pump_events()
        with answer_dialogs(False) as asked:
            app.bulk_mark_section("further_follow_up")
            pump_events()
        eq(len(asked), 0, "no confirmation for a non-destructive action")
        check("Reset follow-up date" in app.status_bar.currentMessage(),
              "it still reports its result")


def test_every_registered_action_runs() -> None:
    """Each action, against a section that actually has rows in it."""
    with gui_app(count=9) as (app, path, _kw):
        with answer_dialogs(True):
            for i in range(3):
                db.set_to_apply(f"T{i}", True, path)
            app.refresh()
            app.bulk_mark_section("apply_all_to_apply")
            pump_events()
            eq(db.get_section_counts(path)["follow_up"], 3, "applied in bulk")

            app.bulk_mark_section("further_follow_up")
            pump_events()
            app.bulk_mark_section("archive_follow_up")
            pump_events()
            eq(db.get_section_counts(path)["archived"], 3, "archived in bulk")

            app.bulk_mark_section("review_new")
            pump_events()
            eq(db.get_section_counts(path)["reviewed"], 6, "reviewed the rest")

            app.bulk_mark_section("revisit_reviewed")
            pump_events()
            eq(db.get_section_counts(path)["reviewed"], 0, "revisited them")

            for i in range(6, 9):
                db.set_to_apply(f"T{i}", True, path)
            app.refresh()
            app.bulk_mark_section("clear_to_apply")
            pump_events()
            eq(db.get_section_counts(path)["to_apply"], 0, "cleared To Apply")

            app.bulk_mark_section("review_old")
            pump_events()

        eq(len(BULK_ACTIONS_BY_ID), 7, "all seven actions are registered")


def test_unknown_action_id_is_a_noop() -> None:
    with gui_app() as (app, path, _kw):
        before = db.get_section_counts(path)
        app.bulk_mark_section("no_such_action")
        pump_events()
        eq(db.get_section_counts(path), before,
           "an unknown id changes nothing")


def test_all_section_is_available_and_counted() -> None:
    """SECTION_ALL is exposed in the sidebar and shows a live count."""
    from jobscanner.ui_qt.sidebar import _SectionsModel

    with gui_app() as (app, path, _kw):
        app.refresh()
        pump_events()
        sections_model = app.sidebar._sections._model
        all_label = None
        for r in range(sections_model.rowCount()):
            if (sections_model.data(sections_model.index(r, 0),
                                   _SectionsModel.KEY_ROLE)
                    == db.SECTION_ALL):
                all_label = sections_model.data(
                    sections_model.index(r, 0), 0x0)  # DisplayRole
                break
        check(all_label is not None, "the sidebar has an All entry")
        check("(6)" in all_label,
              f"All shows a live count ({all_label!r})")

        app.select_section(db.SECTION_ALL)
        pump_events()
        eq(app._table.visible_job_count(), 6, "All lists every job")


def test_status_message_after_bulk_action() -> None:
    """The status bar carries the toast from the most recent bulk action."""
    with gui_app() as (app, _path, _kw):
        db.mark_applied("T0", app.db_path)
        app.refresh()
        pump_events()
        app.bulk_mark_section("further_follow_up")
        pump_events()
        check("Reset follow-up date" in app.status_bar.currentMessage(),
              "non-destructive bulk action toasts via the status bar")


if __name__ == "__main__":
    ok, reason = gui_available()
    _, failed, _ = run_module(globals(), "GUI bulk actions",
                              skip_reason="" if ok else reason)
    sys.exit(1 if failed else 0)
