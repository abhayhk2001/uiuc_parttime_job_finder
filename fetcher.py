import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

import config


class VJBError(Exception):
    pass


class VJBSession:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(config.DEFAULT_HEADERS)
        self._viewstate: Optional[str] = None
        self._viewstategenerator: Optional[str] = None
        self._eventvalidation: Optional[str] = None

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        last_exc: Optional[Exception] = None
        for attempt in range(1, config.MAX_RETRIES + 1):
            try:
                resp = self.session.request(
                    method, url, timeout=config.HTTP_TIMEOUT_SECONDS, **kwargs
                )
                if resp.status_code >= 500:
                    raise VJBError(f"Server error {resp.status_code}")
                resp.raise_for_status()
                time.sleep(config.REQUEST_DELAY_SECONDS)
                return resp
            except (requests.RequestException, VJBError) as exc:
                last_exc = exc
                time.sleep(config.REQUEST_DELAY_SECONDS * attempt)
        raise VJBError(f"Failed after {config.MAX_RETRIES} retries: {last_exc}")

    def _refresh_viewstate(self, html: str) -> None:
        soup = BeautifulSoup(html, "html.parser")
        self._viewstate = soup.find("input", {"name": "__VIEWSTATE"})
        self._viewstate = self._viewstate["value"] if self._viewstate else ""
        vg = soup.find("input", {"name": "__VIEWSTATEGENERATOR"})
        self._viewstategenerator = vg["value"] if vg else ""
        ev = soup.find("input", {"name": "__EVENTVALIDATION"})
        self._eventvalidation = ev["value"] if ev else ""

    def get_home(self) -> str:
        resp = self._request("GET", config.HOME_URL)
        self._refresh_viewstate(resp.text)
        return resp.text

    def get_listing(self, section: str = config.SECTION) -> str:
        self.get_home()
        data = {
            "__VIEWSTATE": self._viewstate or "",
            "__VIEWSTATEGENERATOR": self._viewstategenerator or "",
            "__EVENTVALIDATION": self._eventvalidation or "",
            config.BTN_NAME: config.BTN_VALUE,
        }
        resp = self._request("POST", config.HOME_URL, data=data)
        self._refresh_viewstate(resp.text)
        return resp.text

    def get_detail(self, postid: str) -> str:
        url = config.DETAIL_URL_TEMPLATE.format(postid=postid)
        resp = self._request("GET", url)
        return resp.text
