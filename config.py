import os
from pathlib import Path

BASE_URL = "https://secure.osfa.illinois.edu/vjb"
HOME_URL = f"{BASE_URL}/index.aspx"
DETAIL_URL_TEMPLATE = f"{BASE_URL}/detail.aspx?type=nonfws&postid={{postid}}"

SECTION = "nonfws"
BTN_NAME = "ctl00$ContentPlaceHolder1$btnnonfws"
BTN_VALUE = "Show University Positions"

ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "jobs.db"

KEYWORDS_PATH = ROOT_DIR / "keywords.json"

REQUEST_DELAY_SECONDS = 1.0
HTTP_TIMEOUT_SECONDS = 30
MAX_RETRIES = 3

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

SOUND_FILE = "/System/Library/Sounds/Glass.aiff"
