import json
import re
from pathlib import Path
from typing import Iterable

from jobscanner import config
from jobscanner import storage as db


def load_keywords(path: Path = config.KEYWORDS_PATH) -> list[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"keywords.json must be a JSON list of strings; got {type(data).__name__}")
    return [str(k).strip() for k in data if str(k).strip()]


def _build_pattern(keywords: Iterable[str]) -> re.Pattern[str]:
    escaped = [re.escape(k.lower()) for k in keywords]
    if not escaped:
        return re.compile(r"(?!x)x")
    return re.compile(r"(?:\b(?:" + "|".join(escaped) + r")\b)", re.IGNORECASE)


def match(keywords: list[str], haystack: str) -> list[str]:
    if not keywords or not haystack:
        return []
    pattern = _build_pattern(keywords)
    found = {m.group(0).lower() for m in pattern.finditer(haystack)}
    return sorted(found)


def find_matches(job_record: dict, keywords: list[str]) -> list[str]:
    haystack = " ".join(
        str(job_record.get(k, "") or "")
        for k in ("job_description", "requirements", "skills")
    )
    return match(keywords, haystack)


def rematch_all(keywords: list[str]) -> int:
    """Re-run matching for every job in the DB against the given keywords.

    Returns the number of job rows updated. Used by the GUI keyword editor
    so the table refreshes immediately when keywords change.
    """
    rows = db.get_all_jobs()
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
        )
        updated += 1
    return updated
