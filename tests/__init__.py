"""Isolated smoke tests for db.py.

These tests never touch the user's real ``data/jobs.db`` — they all run
against a temporary SQLite file created via ``tempfile.mkdtemp()``. The
pattern is the safe one: any future test in this repo should mirror it.

Run with::

    python tests/test_db_isolated.py

The module also works under pytest::

    pytest tests/test_db_isolated.py
"""
