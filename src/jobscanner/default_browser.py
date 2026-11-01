"""Which browser the HES sign-in should happen in.

The HES login is a NetID sign-in with MFA, so it needs a real browser, and
the session cookies have to be read back out of that browser -- which means
Playwright either owns it or is attached to it over the DevTools protocol.

The OS default handler for web URLs is usually a browser (Chrome, Edge,
Brave, Arc), and Playwright drives those directly. It can also be a
*launcher*: Velja, for instance, shows a picker and hands the URL to a
browser of the user's choosing. A launcher has no engine of its own, so
for those the scanner starts the Chromium browsers it *can* drive with a
debugging port, lets the OS deliver the URL (so the picker appears), and
captures the session from whichever browser ends up showing the portal.

Only macOS is inspected. Elsewhere the scanner keeps its previous
behaviour: Google Chrome if it is installed, Playwright's own Chromium
otherwise.
"""

from __future__ import annotations

import plistlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

#: Where macOS keeps installed applications.
MACOS_APP_DIRS = (Path("/Applications"), Path.home() / "Applications")

#: The URL scheme the scanner asks the OS about.
_WEB_SCHEME = "https"

#: NSWorkspace answers for the URL itself, which is the question we are
#: asking. Reading the LaunchServices preferences cache is cheaper but
#: goes stale, and `defaults read` does not expose the handler table
#: in a stable shape. The script's value -- not console.log, which
#: osascript sends to stderr -- is what comes back on stdout.
_OSASCRIPT_DEFAULT_HANDLER = (
    'ObjC.import("AppKit"); '
    "var ws = $.NSWorkspace.sharedWorkspace; "
    f'var u = ws.URLForApplicationToOpenURL('
    f'$.NSURL.URLWithString("{_WEB_SCHEME}://example.com")); '
    'u ? ObjC.unwrap(u.path) : ""'
)


@dataclass(frozen=True)
class ChromiumBrowser:
    """An installed Chromium-based browser."""

    app: Path
    executable: Path

    @property
    def name(self) -> str:
        """The app's display name, e.g. "Brave Browser"."""
        return self.app.stem

    @property
    def slug(self) -> str:
        """A filesystem-safe name, used for this browser's profile dir."""
        return "".join(c if c.isalnum() else "_" for c in self.name).lower()


def default_url_handler() -> Optional[Path]:
    """The application the OS opens web URLs with, if we can tell."""
    if sys.platform == "darwin":
        return _macos_default_url_handler()
    return None


def chromium_browsers() -> list[ChromiumBrowser]:
    """The Chromium-based browsers installed on this Mac.

    Sorted by name so the order the scanner tries them in is stable.
    """
    found: list[ChromiumBrowser] = []
    for directory in MACOS_APP_DIRS:
        if not directory.is_dir():
            continue
        for app in sorted(directory.glob("*.app")):
            if not is_chromium_app(app):
                continue
            executable = _macos_executable(app)
            if executable is not None:
                found.append(ChromiumBrowser(app=app, executable=executable))
    return found


def is_chromium_app(app: Path) -> bool:
    """True when the bundle is a Chromium-based web browser.

    Chromium apps ship their engine as ``<Name> Framework.framework`` and
    claim the ``public.html`` document type. Electron apps (ChatGPT,
    Slack) have the framework but not the document type, and launchers
    (Velja) have the document type but no engine of their own.
    """
    frameworks = app / "Contents" / "Frameworks"
    if not frameworks.is_dir():
        return False
    if not any(p.name.endswith(" Framework.framework")
               for p in frameworks.iterdir()):
        return False
    return _declares_html_documents(app)


def _declares_html_documents(app: Path) -> bool:
    """True when the bundle claims it can open HTML documents."""
    info = _read_plist(app / "Contents" / "Info.plist")
    if not info:
        return False
    for entry in info.get("CFBundleDocumentTypes", []):
        if "public.html" in entry.get("LSItemContentTypes", []):
            return True
    return False


def _macos_executable(app: Path) -> Optional[Path]:
    """The browser binary inside an app bundle, if it is there."""
    info = _read_plist(app / "Contents" / "Info.plist")
    if not info:
        return None
    name = info.get("CFBundleExecutable")
    if not name:
        return None
    executable = app / "Contents" / "MacOS" / name
    if not executable.is_file():
        return None
    return executable


def _read_plist(path: Path) -> Optional[dict]:
    """Parse a plist, returning None when it is missing or unreadable."""
    try:
        with path.open("rb") as handle:
            data = plistlib.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _macos_default_url_handler() -> Optional[Path]:
    """Ask LaunchServices which app opens web URLs."""
    try:
        proc = subprocess.run(
            ["/usr/bin/osascript", "-l", "JavaScript",
             "-e", _OSASCRIPT_DEFAULT_HANDLER],
            capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    path = proc.stdout.strip()
    if not path.startswith("/"):
        return None
    return Path(path)
