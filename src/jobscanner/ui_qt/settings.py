"""One place that names the QSettings scope.

A bare ``QSettings()`` resolves against whatever
``QCoreApplication.setOrganizationName`` / ``setApplicationName`` were set
to. :func:`jobscanner.ui_qt.app.launch` sets them, so a normal run is fine
-- but anything that constructs widgets directly (the test suite, an
embedding caller, a debug script) gets the *shared* Python preferences file,
``org.python.python.Python.plist``, and writes this app's window geometry
and appearance override into it. That leaks state between unrelated runs and
is genuinely hard to notice: it showed up here as a layout test that passed
alone and failed under pytest.

So nothing in the UI should construct a bare QSettings. Use
:func:`app_settings`.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings

ORG = "UIUC"
APP = "PartTimeJobScanner"


def app_settings() -> QSettings:
    """Settings for this application, with the scope named explicitly."""
    return QSettings(ORG, APP)
