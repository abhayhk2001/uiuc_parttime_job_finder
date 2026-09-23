"""Test suite for the UIUC part-time job scanner.

Two layers:

* ``test_db_isolated``   -- the storage layer, against temporary SQLite files.
* ``test_gui_*``         -- the GUI, driven headlessly against throwaway
  databases. These skip themselves where Tk or customtkinter isn't
  available, so the suite stays useful on a headless box.

No test ever opens the user's real ``data/jobs.db``: every one runs inside
a ``tempfile.mkdtemp()`` directory that is removed afterwards. Any new test
in this repo should mirror that -- see ``support.TempDB`` and
``support.gui_app``.

Run the lot::

    python tests/run_all.py

Or a single module, as a plain script (no pytest needed)::

    python tests/test_gui_layout.py

pytest works too, and is the easiest way to run one test::

    pytest tests/
    pytest tests/test_gui_layout.py -k sidebar
"""
