import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

from jobscanner import config
from jobscanner.scraper import http


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
        try:
            resp = http.request(self.session, method, url, **kwargs)
        except requests.RequestException as exc:
            raise VJBError(f"{method} {url} failed: {exc}") from exc
        # Be polite to the board between consecutive requests.
        time.sleep(config.REQUEST_DELAY_SECONDS)
        return resp

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
