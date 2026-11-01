"""Saved browser session for the HES Student Portal.

The portal sits behind Illinois NetID single sign-on (Microsoft Entra, with
passkey/Duo MFA), which can't be automated. So the user signs in once in a
visible browser (``jobscanner --hes-login``). Two things are kept:

- the browser profile, only so the next login starts from a warm account
  picker; and
- a ``storage_state`` file of every cookie *including session-only ones*.
  The portal's own login cookie is session-only, and Chromium throws those
  away when the browser closes, so the profile alone does not carry a
  login from one run to the next. Scans replay the cookie file in a fresh
  headless browser and ride the same server-side session until the
  university expires it.

No password is ever stored. Playwright is imported lazily so the other
sources (and the GUI) work on an install that doesn't have it.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional
from urllib.parse import urlparse

from jobscanner import default_browser, paths

PORTAL_URL = "https://web.housing.illinois.edu/HESStudentPortal/MyHES"
PORTAL_HOST = "web.housing.illinois.edu"
PORTAL_PATH_PREFIX = "/HESStudentPortal"

LOGIN_TIMEOUT_SECONDS = 600
NAV_TIMEOUT_MS = 45_000
#: How long a replayed session gets to land on the portal before it is
#: declared expired (the SAML hop-chain takes a few seconds even when valid).
REPLAY_TIMEOUT_MS = 12_000
#: How long to wait for the OS to deliver the portal URL to a browser we
#: can attach to. The user has to notice the launcher, pick a browser and
#: the URL has to arrive; a minute and a half is generous.
LAUNCHER_PICK_SECONDS = 90
#: How long a freshly started browser gets to open its debugging port.
BROWSER_START_TIMEOUT_SECONDS = 30


class HesSessionError(RuntimeError):
    """The browser couldn't start, or the saved login is unusable."""


class HesLoginRequired(HesSessionError):
    """The saved session is gone or expired; the user must sign in again."""


def relogin_command() -> str:
    """The command that re-signs in, exactly as the user has to type it.

    The scan usually starts from cron or the launchd agent, where the
    working directory is not the checkout and ``jobscanner`` may not be
    on PATH -- so the hint has to carry the ``cd`` that puts the user
    where the scanner can actually be started, not just the flag.
    """
    if getattr(sys, "frozen", False):
        # The bundle is its own entry point: LaunchServices hands the
        # flag on and gui.py picks it up before any Qt import.
        return (f'open -a "{paths.APP_DISPLAY_NAME}" '
                f"--args --hes-login")
    root = paths._REPO_ROOT
    if paths._is_source_checkout() and (root / "main.py").exists():
        # The interpreter running the scan is the one with Playwright
        # installed, so name it rather than whatever `python` is first
        # on the user's PATH.
        return f'cd "{root}" && "{sys.executable or "python"}" main.py --hes-login'
    # A regular (non-editable) install has no checkout to cd into; the
    # console script is the entry point there.
    return "jobscanner --hes-login"


def is_portal_url(url: str) -> bool:
    """True when ``url`` is a page of the portal itself, not the SSO login."""
    parts = urlparse(url)
    return (parts.hostname == PORTAL_HOST
            and parts.path.lower().startswith(PORTAL_PATH_PREFIX.lower()))


@dataclass(frozen=True)
class _BrowserSpec:
    """One way to start a browser.

    ``engine`` is a Playwright browser type ("chromium", "webkit");
    ``executable`` points at an installed browser to drive instead of
    Playwright's own build; ``channel`` names one of the browsers
    Playwright ships drivers for ("chrome", "msedge").
    """

    label: str
    engine: str = "chromium"
    executable: Optional[Path] = None
    channel: Optional[str] = None
    profile: Optional[Path] = None


def _browser_cache() -> Path:
    """Where ``playwright install`` puts browsers on this platform."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ms-playwright"
    return Path.home() / ".cache" / "ms-playwright"


def _replay_specs() -> list[_BrowserSpec]:
    """Browsers for the unattended replay.

    Chromium, because that is the engine the portal is most widely
    exercised against -- and because a session captured in another engine
    still replays here (see :func:`_normalize_same_site`).
    """
    return [
        _BrowserSpec(label="Google Chrome", channel="chrome"),
        _BrowserSpec(label="Chromium"),
    ]


@contextmanager
def _browser_context(headless: bool, *, persistent: bool,
                     state_path: Optional[Path] = None,
                     specs: Optional[list[_BrowserSpec]] = None) -> Iterator:
    """Yield a Playwright browser context.

    ``persistent`` uses the on-disk profile (for the interactive login);
    otherwise a throwaway context seeded from ``state_path``. ``specs``
    lists the browsers to try, best first.
    """
    if getattr(sys, "frozen", False):
        # PyInstaller's Playwright hook looks for browsers inside the
        # bundle; they are not shipped there. Use the shared cache that
        # ``playwright install chromium`` fills.
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(_browser_cache()))
        if os.environ["PLAYWRIGHT_BROWSERS_PATH"] == "0":
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_browser_cache())

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise HesSessionError(
            "Playwright is not installed. Run: pip install playwright"
        ) from exc

    with sync_playwright() as pw:
        ctx = None
        browser = None
        failures: list[str] = []
        for spec in (specs if specs is not None else _replay_specs()):
            browser_type = getattr(pw, spec.engine, None)
            if browser_type is None:
                continue
            kwargs: dict[str, Any] = {}
            if spec.executable is not None:
                kwargs["executable_path"] = str(spec.executable)
            if spec.channel is not None:
                kwargs["channel"] = spec.channel
            try:
                if persistent:
                    profile = spec.profile or paths.hes_profile_dir()
                    profile.mkdir(parents=True, exist_ok=True)
                    ctx = browser_type.launch_persistent_context(
                        str(profile), headless=headless, **kwargs)
                else:
                    browser = browser_type.launch(headless=headless, **kwargs)
                    ctx = browser.new_context(
                        storage_state=str(state_path) if state_path else None)
                break
            except PlaywrightError as exc:
                failures.append(f"{spec.label}: {str(exc).splitlines()[0]}")
        if ctx is None:
            raise HesSessionError(
                "No browser available (" + "; ".join(failures) + "). "
                "Install Google Chrome, or run: playwright install chromium")
        ctx.set_default_navigation_timeout(NAV_TIMEOUT_MS)
        try:
            yield ctx
        finally:
            ctx.close()
            if browser is not None:
                browser.close()


def _normalize_same_site(state_path: Path) -> None:
    """Make a captured session replayable by Chromium.

    WebKit records a cookie with no explicit SameSite attribute as
    ``"None"``; Chromium drops those unless the cookie is also Secure,
    which the portal's session cookie is not. Treating them as Lax is
    what Chromium itself records for the same cookie, and it lets a
    session captured in one engine replay in another.
    """
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    changed = False
    for cookie in state.get("cookies", []):
        if (cookie.get("sameSite") == "None"
                and not cookie.get("secure")):
            cookie["sameSite"] = "Lax"
            changed = True
    if not changed:
        return
    try:
        state_path.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass


@dataclass
class _StartedBrowser:
    """A browser we started ourselves, and how to talk to it."""

    browser: default_browser.ChromiumBrowser
    proc: subprocess.Popen
    port: int

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def _free_port() -> int:
    """A port nothing is listening on."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_browser(browser: default_browser.ChromiumBrowser) -> Optional[_StartedBrowser]:
    """Start an installed browser with a debugging port.

    The dedicated profile keeps the user's own browser data out of it,
    and keeps a second copy of the browser from refusing to start.
    """
    profile = paths.hes_profile_dir() / browser.slug
    profile.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    try:
        proc = subprocess.Popen(
            [str(browser.executable),
             f"--remote-debugging-port={port}",
             f"--user-data-dir={profile}",
             "--no-first-run",
             "--no-default-browser-check",
             "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return None
    started = _StartedBrowser(browser=browser, proc=proc, port=port)
    if not _wait_for_endpoint(started.endpoint):
        _stop_browser(started)
        return None
    return started


def _wait_for_endpoint(endpoint: str) -> bool:
    """Wait for a browser's DevTools endpoint to answer."""
    deadline = time.monotonic() + BROWSER_START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{endpoint}/json/version", timeout=2):
                return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.4)
    return False


def _stop_browser(started: _StartedBrowser) -> None:
    """Close a browser we started."""
    if started.proc.poll() is not None:
        return
    started.proc.terminate()
    try:
        started.proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        started.proc.kill()


def _page_urls(endpoint: str) -> list[str]:
    """The URLs of the tabs open in a browser on its debugging port."""
    try:
        with urllib.request.urlopen(f"{endpoint}/json/list", timeout=3) as response:
            tabs = json.load(response)
    except (urllib.error.URLError, OSError, ValueError):
        return []
    return [tab.get("url", "") for tab in tabs if tab.get("type") == "page"]


def _deliver_url(url: str) -> bool:
    """Hand a URL to the OS, so the user's default handler opens it.

    On a Mac whose default handler is a launcher -- Velja, say -- this is
    what brings the picker up, and the user's choice of browser is what
    decides where the URL lands.
    """
    try:
        if sys.platform == "darwin":
            subprocess.run(["/usr/bin/open", url], check=True, timeout=30)
        elif sys.platform == "win32":
            os.startfile(url)
        else:
            subprocess.run(["xdg-open", url], check=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def _wait_for_delivered_url(started: list[_StartedBrowser],
                            before: dict[str, list[str]]
                            ) -> Optional[tuple[_StartedBrowser, str]]:
    """Wait for the OS to deliver the portal URL to one of the browsers.

    Returns the browser it landed in and the URL it landed on. A tab
    that was already open before the hand-off does not count: only a new
    one is the browser acting on the URL we gave it.
    """
    deadline = time.monotonic() + LAUNCHER_PICK_SECONDS
    while time.monotonic() < deadline:
        for entry in started:
            fresh = [url for url in _page_urls(entry.endpoint)
                     if url not in before.get(entry.endpoint, [])]
            if fresh:
                return entry, fresh[0]
        time.sleep(0.5)
    return None


@contextmanager
def _launcher_login() -> Iterator[Optional[tuple[Any, Any]]]:
    """Sign in through whatever browser the user's launcher picks.

    Yields ``(page, context)`` for the browser that received the URL, or
    None when the URL went somewhere we cannot read -- Safari, say, which
    offers no way to capture its cookies.
    """
    browsers = default_browser.chromium_browsers()
    if not browsers:
        yield None
        return

    started: list[_StartedBrowser] = []
    try:
        for browser in browsers:
            entry = _start_browser(browser)
            if entry is not None:
                started.append(entry)
        if not started:
            yield None
            return

        before = {entry.endpoint: _page_urls(entry.endpoint) for entry in started}
        if not _deliver_url(PORTAL_URL):
            yield None
            return

        delivered = _wait_for_delivered_url(started, before)
        if delivered is None:
            yield None
            return
        chosen, delivered_url = delivered

        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(chosen.endpoint)
            try:
                # The tab the URL landed in is the one that was not there
                # before; the browser's own blank tab is not it. The tab
                # may already have redirected to the sign-in page, so the
                # exact URL is a preference, not a requirement.
                stale = set(before.get(chosen.endpoint, []))
                pages = [page for context in browser.contexts
                         for page in context.pages]
                page = next((p for p in pages
                             if p.url.startswith(delivered_url)), None)
                if page is None:
                    page = next((p for p in pages if p.url not in stale), None)
                if page is None:
                    yield None
                    return
                context = next((c for c in browser.contexts
                                if page in c.pages), browser.contexts[0])
                yield page, context
            finally:
                try:
                    browser.close()
                except Exception:  # noqa: BLE001
                    pass
    finally:
        for entry in started:
            _stop_browser(entry)


def _login_specs(default_browser_app: Optional[default_browser.ChromiumBrowser]
                 ) -> list[_BrowserSpec]:
    """Browsers for the interactive sign-in, best first.

    The user's own default browser comes first when it is one Playwright
    can drive. WebKit comes next because it is Safari's engine -- the
    closest stand-in when the default handler is a launcher that cannot
    be driven at all.
    """
    specs: list[_BrowserSpec] = []
    if default_browser_app is not None:
        specs.append(_BrowserSpec(
            label=default_browser_app.name,
            executable=default_browser_app.executable,
            profile=paths.hes_profile_dir() / default_browser_app.slug))
    specs.append(_BrowserSpec(label="WebKit", engine="webkit",
                               profile=paths.hes_profile_dir() / "webkit"))
    specs.append(_BrowserSpec(label="Google Chrome", channel="chrome",
                               profile=paths.hes_profile_dir() / "chrome"))
    specs.append(_BrowserSpec(label="Chromium",
                               profile=paths.hes_profile_dir() / "chromium"))
    return specs


def _open_portal(ctx, timeout_ms: int):
    """Open the portal; return the page, or raise HesLoginRequired."""
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(PORTAL_URL)
    try:
        page.wait_for_url(is_portal_url, timeout=timeout_ms)
    except Exception as exc:  # noqa: BLE001 -- Playwright TimeoutError
        raise HesLoginRequired(
            f"HES login expired or missing -- run: {relogin_command()}"
        ) from exc
    return page


def fetch_portal_html() -> str:
    """Return the rendered MyHES landing page using the saved cookies.

    Raises :class:`HesLoginRequired` when the portal bounces to the NetID
    login. Never blocks on a login prompt, so it is safe for the nightly
    unattended run.
    """
    state = paths.hes_state_path()
    if not state.exists():
        raise HesLoginRequired(
            f"No saved HES login -- run: {relogin_command()}")
    with _browser_context(True, persistent=False, state_path=state) as ctx:
        page = _open_portal(ctx, REPLAY_TIMEOUT_MS)
        # The positions are injected by script; the portal flips this
        # hidden input once they are in the DOM.
        page.wait_for_selector("#positionsloaded", state="attached",
                               timeout=NAV_TIMEOUT_MS)
        page.wait_for_load_state("networkidle")
        html = page.content()
        # Persist any refreshed cookies so a sliding session keeps sliding.
        ctx.storage_state(path=str(state))
        _normalize_same_site(state)
        return html


def _say(message: str, alert: Optional[str] = None) -> None:
    """Tell the user what is happening.

    The built .app is a windowed bundle with no console, so the same
    words go out as a macOS notification rather than going nowhere.
    """
    print(message)
    if not getattr(sys, "frozen", False) or sys.platform != "darwin":
        return
    try:
        subprocess.run(
            ["/usr/bin/osascript", "-e",
             f"display notification {json.dumps(alert or message)}"],
            check=False, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass


@contextmanager
def _login_browser() -> Iterator[tuple[Any, Any]]:
    """Yield the page and context the user signs in through.

    Where that is depends on what the OS opens web URLs with. A browser
    we can drive is used directly. A launcher -- Velja shows a picker
    and hands the URL to a browser of the user's choosing -- cannot be
    driven, so the browsers we *can* drive are started with a debugging
    port first and the session is captured from whichever one the picker
    lands on.
    """
    handler = default_browser.default_url_handler()
    if handler is not None and default_browser.is_chromium_app(handler):
        chosen = next((b for b in default_browser.chromium_browsers()
                       if b.app == handler), None)
        with _browser_context(False, persistent=True,
                              specs=_login_specs(chosen)) as ctx:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(PORTAL_URL)
            _say(f"A {chosen.name if chosen else 'browser'} window opened. "
                 f"Sign in with your NetID and approve the MFA prompt.",
                 alert="Sign in to HES in the browser window.")
            yield page, ctx
        return

    names = ", ".join(b.name for b in default_browser.chromium_browsers())
    _say(f"Opening {PORTAL_URL} in your default browser "
         f"({handler.name if handler else 'the system handler'}).",
         alert="Opening the HES sign-in in your default browser.")
    if names:
        _say(f"Attach-capable browsers started: {names}. Pick one of those "
             f"in the browser picker, or the session cannot be captured.",
             alert=f"Pick {names} in the browser picker.")
    with _launcher_login() as picked:
        if picked is not None:
            page, ctx = picked
            _say("Sign in with your NetID and approve the MFA prompt.",
                 alert="Sign in to HES in the browser window.")
            yield page, ctx
            return

    _say("[hes] The URL did not reach a browser the scanner can attach to "
         "(Safari cannot be captured). Falling back to a browser of our own.",
         alert="The browser you picked cannot be used; a new one is opening.")
    with _browser_context(False, persistent=True,
                          specs=_login_specs(None)) as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(PORTAL_URL)
        _say("A browser window opened. Sign in with your NetID and approve "
             "the MFA prompt.",
             alert="Sign in to HES in the browser window.")
        yield page, ctx


def login(out_dir: Path | None = None) -> int:
    """Interactive one-time login; also dumps page HTML for the parser.

    Opens a visible browser on the persistent profile and waits for the
    user to finish NetID + MFA. It saves the cookies, then verifies in a
    fresh headless browser that they really carry the login, so a session
    that can't be replayed is reported now rather than at 9 pm.
    """
    out_dir = out_dir or paths.user_data_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    state = paths.hes_state_path()

    try:
        with _login_browser() as (page, ctx):
            _await_portal(page)
            _save_session(ctx, state)
            _dump_sample(ctx, page, out_dir)
    except HesSessionError as exc:
        print(f"[hes] {exc}", file=sys.stderr)
        return 1

    print("Verifying the saved session in a fresh headless browser...")
    try:
        fetch_portal_html()
    except HesSessionError as exc:
        print(f"[hes] Saved session does NOT carry the login: {exc}",
              file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[hes] Verification failed: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 1
    print("OK: headless scans can reuse this login until the portal "
          "expires it.")
    return 0


def _await_portal(page) -> None:
    """Wait for the sign-in to land back on the portal."""
    deadline = time.monotonic() + LOGIN_TIMEOUT_SECONDS
    while not is_portal_url(page.url):
        if time.monotonic() > deadline:
            raise HesSessionError("Timed out waiting for login.")
        page.wait_for_timeout(500)
    page.wait_for_load_state("networkidle")


def _save_session(ctx, state: Path) -> None:
    """Write the signed-in cookies out, session-only ones included."""
    ctx.storage_state(path=str(state))
    _normalize_same_site(state)
    state.chmod(0o600)
    print(f"Logged in. Cookies saved -> {state}")


def _dump_sample(ctx, page, out_dir: Path) -> None:
    """Optionally save the postings page, for parser debugging."""
    if not sys.stdin.isatty():
        return
    input("Optional: open the page listing the job postings and press "
          "Enter to save it for parser debugging (or just press Enter)... ")
    page.wait_for_load_state("networkidle")
    (out_dir / "hes_sample.html").write_text(
        page.content(), encoding="utf-8")
    ctx.storage_state(path=str(state))
    _normalize_same_site(state)
