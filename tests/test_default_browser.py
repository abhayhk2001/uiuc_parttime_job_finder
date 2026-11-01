"""Which browser the HES sign-in uses, and how the session is captured.

The HES login is a NetID sign-in with MFA. It needs a real browser, and
the session cookies have to be read back out of that browser -- which
means Playwright either owns it or is attached to it over the DevTools
protocol.

These tests cover the decisions: which browser the OS would open, which
of those Playwright can drive, and the cookie fix-up that lets a session
captured in one engine replay in another.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from support import check, eq, run_module  # noqa: E402

from jobscanner import default_browser, hes_session  # noqa: E402


# ---------------------------------------------------------------------------
# Telling browsers apart
# ---------------------------------------------------------------------------

def test_chromium_apps_are_recognised() -> None:
    # A Chromium app ships its engine as "<Name> Framework.framework" and
    # claims the public.html document type.
    check(default_browser.is_chromium_app(
        Path("/Applications/Google Chrome.app")),
        "Chrome is a Chromium app")
    check(not default_browser.is_chromium_app(
        Path("/Applications/Definitely Not Installed.app")),
        "a missing bundle is not a Chromium app")
    check(not default_browser.is_chromium_app(
        Path("/Applications/Velja.app")),
        "a launcher has no Chromium engine")


def test_a_missing_bundle_is_not_a_browser() -> None:
    check(not default_browser.is_chromium_app(Path("/nope/Nowhere.app")),
          "a path that is not there is not a Chromium app")


def test_every_detected_browser_can_be_launched() -> None:
    for browser in default_browser.chromium_browsers():
        check(browser.executable.is_file(),
              f"{browser.name} has no executable at {browser.executable}")
        check(browser.executable.stat().st_mode & 0o111,
              f"{browser.executable} is not executable")
        check(bool(browser.slug),
              f"{browser.name} needs a profile-dir slug")


def test_browser_slugs_are_filesystem_safe() -> None:
    browser = default_browser.ChromiumBrowser(
        app=Path("/Applications/Brave Browser.app"),
        executable=Path("/Applications/Brave Browser.app/Contents/MacOS/X"))
    eq(browser.slug, "brave_browser", "spaces become underscores")
    check("/" not in browser.slug, "a slug must not contain a path separator")


# ---------------------------------------------------------------------------
# The sign-in browser
# ---------------------------------------------------------------------------

def test_login_specs_prefer_the_default_browser() -> None:
    browser = default_browser.ChromiumBrowser(
        app=Path("/Applications/Brave Browser.app"),
        executable=Path("/Applications/Brave Browser.app/Contents/MacOS/Brave"))
    specs = hes_session._login_specs(browser)
    eq(specs[0].label, "Brave Browser", "the default browser comes first")
    eq(specs[0].executable, browser.executable,
       "the default browser is driven by its own binary")
    check(any(s.engine == "webkit" for s in specs),
          "WebKit is the fallback for browsers we cannot drive")


def test_login_specs_fall_back_to_webkit_then_chrome() -> None:
    specs = hes_session._login_specs(None)
    eq(specs[0].engine, "webkit",
       "without a driveable default, WebKit comes first")
    labels = [s.label for s in specs]
    check("Google Chrome" in labels, "Chrome is still a fallback")
    check("Chromium" in labels, "Playwright's Chromium is the last resort")


def test_replay_uses_chromium() -> None:
    specs = hes_session._replay_specs()
    check(all(s.engine == "chromium" for s in specs),
          "the unattended replay stays on Chromium")
    eq(specs[0].channel, "chrome", "the installed Chrome is tried first")


# ---------------------------------------------------------------------------
# Capturing the session
# ---------------------------------------------------------------------------

def test_same_site_none_becomes_lax(tmp_path: Path) -> None:
    """WebKit records an unspecified SameSite as "None"; Chromium drops
    those unless the cookie is Secure, so they are recorded as Lax."""
    state = tmp_path / "hes_state.json"
    state.write_text(json.dumps({
        "cookies": [
            {"name": "plain", "value": "v", "secure": False,
             "sameSite": "None"},
            {"name": "secure", "value": "v", "secure": True,
             "sameSite": "None"},
            {"name": "already", "value": "v", "secure": False,
             "sameSite": "Lax"},
        ],
        "origins": [],
    }), encoding="utf-8")

    hes_session._normalize_same_site(state)

    cookies = {c["name"]: c for c in json.loads(
        state.read_text(encoding="utf-8"))["cookies"]}
    eq(cookies["plain"]["sameSite"], "Lax",
       "an insecure SameSite=None cookie is recorded as Lax")
    eq(cookies["secure"]["sameSite"], "None",
       "a Secure cookie keeps SameSite=None")
    eq(cookies["already"]["sameSite"], "Lax", "Lax is left alone")


def test_same_site_normalisation_leaves_good_state_alone(tmp_path: Path) -> None:
    state = tmp_path / "hes_state.json"
    original = {"cookies": [{"name": "a", "sameSite": "Lax"}], "origins": []}
    state.write_text(json.dumps(original), encoding="utf-8")
    hes_session._normalize_same_site(state)
    eq(json.loads(state.read_text(encoding="utf-8")), original,
       "a state file with nothing to fix is not rewritten")


def test_same_site_normalisation_survives_a_broken_file(tmp_path: Path) -> None:
    state = tmp_path / "hes_state.json"
    state.write_text("not json at all", encoding="utf-8")
    hes_session._normalize_same_site(state)
    eq(state.read_text(encoding="utf-8"), "not json at all",
       "an unreadable state file is left alone rather than truncated")


# ---------------------------------------------------------------------------
# The launcher hand-off
# ---------------------------------------------------------------------------

def test_delivered_url_is_found_among_new_tabs() -> None:
    """Only a tab that appeared after the hand-off counts as the one the
    browser opened for us."""
    started = [hes_session._StartedBrowser(
        browser=default_browser.ChromiumBrowser(
            app=Path("/Applications/Brave Browser.app"),
            executable=Path("/x")),
        proc=None, port=1)]
    before = {"http://127.0.0.1:1": ["about:blank"]}

    with patch.object(hes_session, "LAUNCHER_PICK_SECONDS", 1), \
            patch.object(hes_session, "_page_urls",
                         return_value=["about:blank"]):
        eq(hes_session._wait_for_delivered_url(started, before), None,
           "no new tab means the URL went elsewhere")

    with patch.object(hes_session, "_page_urls",
                      return_value=["about:blank", "https://portal/"]):
        found = hes_session._wait_for_delivered_url(started, before)
        check(found is not None, "the new tab is found")
        entry, url = found
        eq(url, "https://portal/", "the new tab's URL is reported")
        eq(entry.port, 1, "the browser it landed in is reported")


class _FakePage:
    """A page stand-in that records where it was sent."""

    def __init__(self) -> None:
        self.visited: list[str] = []

    def goto(self, url: str) -> None:
        self.visited.append(url)


def test_login_browser_uses_the_default_browser_directly() -> None:
    """When the OS default is a browser Playwright can drive, the sign-in
    happens in it -- no launcher, no picker."""
    handler = Path("/Applications/Brave Browser.app")
    browser = default_browser.ChromiumBrowser(app=handler,
                                             executable=Path("/x"))
    fake_page = _FakePage()
    fake_ctx = type("Ctx", (), {"pages": [fake_page], "new_page": lambda: None})()
    factory = MagicMock()
    factory.return_value.__enter__.return_value = fake_ctx

    with patch.object(default_browser, "default_url_handler",
                      return_value=handler), \
            patch.object(default_browser, "is_chromium_app",
                         return_value=True), \
            patch.object(default_browser, "chromium_browsers",
                         return_value=[browser]), \
            patch.object(hes_session, "_browser_context", factory):
        with hes_session._login_browser() as (page, ctx):
            eq(page, fake_page, "the default browser's page is used")
            eq(ctx, fake_ctx, "the default browser's context is used")
    eq(fake_page.visited, [hes_session.PORTAL_URL],
       "the portal is opened in the default browser")
    specs = factory.call_args.kwargs["specs"]
    eq(specs[0].label, "Brave Browser", "the default browser is specified")


def test_login_browser_falls_back_when_the_launcher_wins() -> None:
    """A launcher that sends the URL to a browser we cannot read leaves
    us with no session, so a browser of our own takes over."""
    fake_page = _FakePage()
    fake_ctx = type("Ctx", (), {"pages": [fake_page], "new_page": lambda: None})()
    factory = MagicMock()
    factory.return_value.__enter__.return_value = fake_ctx

    with patch.object(default_browser, "default_url_handler",
                      return_value=Path("/Applications/Velja.app")), \
            patch.object(default_browser, "chromium_browsers",
                         return_value=[]), \
            patch.object(hes_session, "_launcher_login") as launcher:
        launcher.return_value.__enter__.return_value = None
        with patch.object(hes_session, "_browser_context", factory):
            with hes_session._login_browser() as (page, ctx):
                eq(page, fake_page, "our own browser is used instead")
    check(factory.called, "the fallback browser was started")
    eq(fake_page.visited, [hes_session.PORTAL_URL],
       "the portal is opened in the fallback browser")


if __name__ == "__main__":
    _, failed, _ = run_module(globals(), "Default browser")
    sys.exit(1 if failed else 0)
