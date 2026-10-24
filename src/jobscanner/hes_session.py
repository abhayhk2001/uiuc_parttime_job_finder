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

import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional
from urllib.parse import urlparse

from jobscanner import paths

PORTAL_URL = "https://web.housing.illinois.edu/HESStudentPortal/MyHES"
PORTAL_HOST = "web.housing.illinois.edu"
PORTAL_PATH_PREFIX = "/HESStudentPortal"

LOGIN_TIMEOUT_SECONDS = 600
NAV_TIMEOUT_MS = 45_000
#: How long a replayed session gets to land on the portal before it is
#: declared expired (the SAML hop-chain takes a few seconds even when valid).
REPLAY_TIMEOUT_MS = 12_000


class HesSessionError(RuntimeError):
    """The browser couldn't start, or the saved login is unusable."""


class HesLoginRequired(HesSessionError):
    """The saved session is gone or expired; the user must sign in again."""


def is_portal_url(url: str) -> bool:
    """True when ``url`` is a page of the portal itself, not the SSO login."""
    parts = urlparse(url)
    return (parts.hostname == PORTAL_HOST
            and parts.path.lower().startswith(PORTAL_PATH_PREFIX.lower()))


def _browser_cache() -> Path:
    """Where ``playwright install`` puts browsers on this platform."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ms-playwright"
    return Path.home() / ".cache" / "ms-playwright"


@contextmanager
def _browser_context(headless: bool, *, persistent: bool,
                     state_path: Optional[Path] = None) -> Iterator:
    """Yield a Playwright browser context.

    ``persistent`` uses the on-disk profile (for the interactive login);
    otherwise a throwaway context seeded from ``state_path``.
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
        # Prefer the user's own Chrome (no download); fall back to the
        # Chromium that ``playwright install chromium`` fetches.
        for channel in ("chrome", None):
            kwargs = {"channel": channel} if channel else {}
            try:
                if persistent:
                    profile = paths.hes_profile_dir()
                    profile.mkdir(parents=True, exist_ok=True)
                    ctx = pw.chromium.launch_persistent_context(
                        str(profile), headless=headless, **kwargs)
                else:
                    browser = pw.chromium.launch(headless=headless, **kwargs)
                    ctx = browser.new_context(
                        storage_state=str(state_path) if state_path else None)
                break
            except PlaywrightError as exc:
                failures.append(f"{channel or 'chromium'}: "
                                f"{str(exc).splitlines()[0]}")
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


def _open_portal(ctx, timeout_ms: int):
    """Open the portal; return the page, or raise HesLoginRequired."""
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(PORTAL_URL)
    try:
        page.wait_for_url(is_portal_url, timeout=timeout_ms)
    except Exception as exc:  # noqa: BLE001 -- Playwright TimeoutError
        raise HesLoginRequired(
            "HES login expired or missing -- run: jobscanner --hes-login"
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
            "No saved HES login -- run: jobscanner --hes-login")
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
        return html


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
        with _browser_context(False, persistent=True) as ctx:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(PORTAL_URL)
            print("A browser window opened. Sign in with your NetID and "
                  "approve the MFA prompt.")

            deadline = time.monotonic() + LOGIN_TIMEOUT_SECONDS
            while not is_portal_url(page.url):
                if time.monotonic() > deadline:
                    print("Timed out waiting for login.", file=sys.stderr)
                    return 1
                page.wait_for_timeout(500)
            page.wait_for_load_state("networkidle")

            # Includes session-only cookies, which the profile would drop.
            ctx.storage_state(path=str(state))
            state.chmod(0o600)
            print(f"Logged in. Cookies saved -> {state}")

            if sys.stdin.isatty():
                input("Optional: open the page listing the job postings and "
                      "press Enter to save it for parser debugging "
                      "(or just press Enter)... ")
                page.wait_for_load_state("networkidle")
                (out_dir / "hes_sample.html").write_text(
                    page.content(), encoding="utf-8")
                ctx.storage_state(path=str(state))
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
