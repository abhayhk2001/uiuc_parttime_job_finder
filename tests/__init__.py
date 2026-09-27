"""Test suite for the UIUC part-time job scanner.

Layers:

* ``test_db_isolated`` -- the storage layer, against temporary SQLite files.
* ``test_gui_workflow`` -- sections, selection, the job state machine
  walk, sorting, filtering, dialogs.
* ``test_gui_bulk_actions`` -- every registered bulk action, both
  confirmation paths.
* ``test_gui_interactions`` -- detail-pane rendering, context menu,
  shortcuts, clipboard, dock visibility.
* ``test_gui_layout`` -- window geometry, splitter proportions, dock
  placement, dialog geometry.
* ``smoke_skeleton`` / ``smoke_table`` -- model + theme + persistence
  smoke tests that don't need a display.

No test ever opens the user's real ``data/jobs.db``: storage tests run
inside a ``tempfile.mkdtemp()`` directory that is removed afterwards.

Run with::

    python tests/smoke_skeleton.py
    python tests/smoke_table.py
    pytest tests/
    # or one file at a time, as a plain script:
    python tests/test_gui_workflow.py
    python tests/test_gui_bulk_actions.py
    python tests/test_gui_interactions.py
    python tests/test_gui_layout.py
    python tests/test_db_isolated.py
"""
