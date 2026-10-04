import json
import re
from pathlib import Path
from typing import Iterable, Optional

from jobscanner import config
from jobscanner import storage as db


def load_keywords(path: Optional[Path] = None) -> list[str]:
    path = Path(path) if path else config.KEYWORDS_PATH
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"keywords.json must be a JSON list of strings; got {type(data).__name__}")
    return [str(k).strip() for k in data if str(k).strip()]


def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    """Whole-word pattern for one keyword.

    Bounded by "not a word character" lookarounds rather than ``\b``:
    ``\b`` needs a word character on its inner side, so keywords that
    start or end with a symbol -- ``C++``, ``C#``, ``.NET`` -- could never
    match at all.
    """
    return re.compile(r"(?<!\w)" + re.escape(keyword) + r"(?!\w)",
                      re.IGNORECASE)


def match(keywords: list[str], haystack: str) -> list[str]:
    """Every keyword that occurs in `haystack`, lowercased and sorted.

    Each keyword is searched on its own. One alternation over all of them
    consumed the text as it matched, so of two overlapping keywords ("data"
    and "data science") only whichever came first was ever reported.
    """
    if not keywords or not haystack:
        return []
    found = {k.lower() for k in keywords
             if k and _keyword_pattern(k).search(haystack)}
    return sorted(found)


def find_matches(job_record: dict, keywords: list[str]) -> list[str]:
    haystack = " ".join(
        str(job_record.get(k, "") or "")
        for k in ("job_description", "requirements", "skills")
    )
    return match(keywords, haystack)


def rematch_all(keywords: list[str], path: Optional[Path] = None) -> int:
    """Re-run matching for every job in the DB against the given keywords.

    Returns the number of job rows updated. Used by the GUI keyword editor
    so the table refreshes immediately when keywords change.
    """
    rows = db.get_all_jobs(path)
    updated = 0
    for row in rows:
        if not (row.get("job_description") or row.get("requirements") or row.get("skills")):
            continue
        matches = find_matches(row, keywords)
        new_val = ",".join(sorted({m for m in matches if m}))
        old_val = row.get("matched_keywords") or ""
        if new_val == old_val:
            continue
        db.update_details(
            row["job_id"],
            row.get("job_description", "") or "",
            row.get("requirements", "") or "",
            row.get("skills", "") or "",
            matches,
            path,
        )
        updated += 1
    return updated
