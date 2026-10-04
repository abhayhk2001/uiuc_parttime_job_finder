"""One retrying HTTP call, shared by every source.

Only VJB used to retry; the other boards made a single request, so one
dropped connection failed the whole board for that scan. VJB's own loop
went the other way and retried everything, including a 404, waiting
1 + 2 + 3 seconds for a page that was never coming back.
"""

from __future__ import annotations

import time
from typing import Optional

import requests

from jobscanner import config


def _retryable(status: int) -> bool:
    """Server trouble or rate limiting may clear up; a 4xx will not."""
    return status >= 500 or status == 429


def request(session: requests.Session, method: str, url: str,
            **kwargs) -> requests.Response:
    """`session.request` with retries on transient failures.

    Retries connection errors, timeouts, 5xx and 429 up to
    ``config.MAX_RETRIES`` attempts with a growing delay. Any other error
    status raises ``requests.HTTPError`` at once.
    """
    kwargs.setdefault("timeout", config.HTTP_TIMEOUT_SECONDS)
    last_exc: Optional[Exception] = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            resp = session.request(method, url, **kwargs)
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
        else:
            if not _retryable(resp.status_code):
                resp.raise_for_status()
                return resp
            last_exc = requests.HTTPError(
                f"{resp.status_code} from {url}", response=resp)
        if attempt < config.MAX_RETRIES:
            time.sleep(config.REQUEST_DELAY_SECONDS * attempt)
    assert last_exc is not None
    raise last_exc
