from pathlib import Path

from jobscanner import paths

BASE_URL = "https://secure.osfa.illinois.edu/vjb"
HOME_URL = f"{BASE_URL}/index.aspx"
DETAIL_URL_TEMPLATE = f"{BASE_URL}/detail.aspx?type=nonfws&postid={{postid}}"

SECTION = "nonfws"
BTN_NAME = "ctl00$ContentPlaceHolder1$btnnonfws"
BTN_VALUE = "Show University Positions"

# Repo root: src/jobscanner/config.py -> src/jobscanner -> src -> <repo>
ROOT_DIR = Path(__file__).resolve().parents[2]

# ``paths.user_*`` resolves to:
#   - <repo>/data/ and <repo>/keywords.json when running from source, or
#   - the platform's per-user AppData when running from a frozen bundle.
# Storage and matching functions take ``path=None`` and read these
# attributes at call time, so reassigning them (as tests/conftest.py does)
# redirects every defaulted call. Never bind them as a default argument.
DATA_DIR: Path = paths.user_data_dir()
DB_PATH: Path = paths.user_db_path()
KEYWORDS_PATH: Path = paths.user_keywords_path()

REQUEST_DELAY_SECONDS = 1.0
HTTP_TIMEOUT_SECONDS = 30
MAX_RETRIES = 3

# When a job is marked Applied (via mark_applied), record `applied_at` and
# default `follow_up_at = applied_at + FOLLOW_UP_WINDOW_DAYS`.
FOLLOW_UP_WINDOW_DAYS = 7

def _accept_encoding() -> str:
    """Advertise only the encodings this install can actually decode.

    This header used to hardcode "gzip, deflate, br". requests decodes
    brotli only when the brotli (or brotlicffi) package is present, and it
    is not a dependency here -- so any server that honoured the `br` offer
    handed back bytes we could not read. VJB never uses brotli so nothing
    broke; Research Park does, and its pages silently arrived as garbage.
    """
    encodings = ["gzip", "deflate"]
    for module in ("brotli", "brotlicffi"):
        try:
            __import__(module)
        except ImportError:
            continue
        encodings.append("br")
        break
    return ", ".join(encodings)


_ACCEPT_ENCODING = _accept_encoding()

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
    "Accept-Encoding": _ACCEPT_ENCODING,
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

SOUND_FILE = "/System/Library/Sounds/Glass.aiff"
