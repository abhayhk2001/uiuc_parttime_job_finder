"""Test suite for the UIUC part-time job scanner.

Layers:

* ``test_db_isolated`` -- the storage layer, against temporary SQLite files.
* ``smoke_skeleton`` / ``smoke_table`` -- Qt port smoke tests against fake data.

No test ever opens the user's real ``data/jobs.db``: storage tests run
inside a ``tempfile.mkdtemp()`` directory that is removed afterwards.
GUI smoke tests use fake data only.

Run with::

    python tests/smoke_skeleton.py
    python tests/smoke_table.py
    pytest tests/test_db_isolated.py
"""
