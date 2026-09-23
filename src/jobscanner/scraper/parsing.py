import re
from typing import Optional

from bs4 import BeautifulSoup, Tag

from jobscanner import config


_WS_RE = re.compile(r"\s+")


def _clean(text: str) -> str:
    if not text:
        return ""
    return _WS_RE.sub(" ", text).strip()


def _norm_key(label: str) -> str:
    s = _clean(label).lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def find_main_listing_table(soup: BeautifulSoup) -> Optional[Tag]:
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        if any(r.find("input", {"value": "View Position Details"}) for r in rows[:5]):
            return table
    return None


def _parse_listing_row(row: Tag) -> Optional[dict]:
    strongs = row.find_all("strong")
    job_id = ""
    title = ""
    for st in strongs:
        txt = _clean(st.get_text(" ", strip=True))
        if not job_id:
            m = re.match(r"(\d+)\s*:?", txt)
            if m:
                job_id = m.group(1)
                continue
        if txt and not title:
            title = txt
    if not job_id:
        return None

    return {
        "job_id": job_id,
        "title": title,
        "company": title,
        "date_posted": "",
        "detail_url": config.DETAIL_URL_TEMPLATE.format(postid=job_id),
    }


def find_detail_table(soup: BeautifulSoup) -> Optional[Tag]:
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        labels = [_norm_key(r.find("th").get_text(" ", strip=True)) if r.find("th") else "" for r in rows]
        joined = " ".join(labels)
        if "job_description" in joined and "requirements" in joined and "skills" in joined:
            return table
    return None


def parse_listing(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = find_main_listing_table(soup)
    if not table:
        return []

    out: list[dict] = []
    for row in table.find_all("tr"):
        if not row.find("input", {"value": "View Position Details"}):
            continue
        parsed = _parse_listing_row(row)
        if parsed:
            out.append(parsed)
    return out


def parse_detail(html: str, job_id: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    table = find_detail_table(soup)
    fields: dict[str, str] = {}
    if table:
        for row in table.find_all("tr"):
            th = row.find("th")
            td = row.find("td")
            if not th or not td:
                continue
            key = _norm_key(th.get_text(" ", strip=True))
            val = _clean(td.get_text(" ", strip=True))
            if key:
                fields[key] = val
    return {
        "job_id": job_id,
        "company": fields.get("company", ""),
        "job_title": fields.get("job_title", ""),
        "pay_rate": fields.get("pay_rate", ""),
        "pay_type": fields.get("pay_type", ""),
        "work_schedule": fields.get("work_schedule", ""),
        "hours_per_week": fields.get("hours_per_week", ""),
        "job_duration": fields.get("job_duration", ""),
        "federal_work_study": fields.get("federal_work_study", ""),
        "seasonal": fields.get("seasonal", ""),
        "uiuc_job": fields.get("uiuc_job", ""),
        "location": fields.get("location", ""),
        "website": fields.get("website", ""),
        "contact_person": fields.get("contact_person", ""),
        "preference_of_contact": fields.get("preference_of_contact", ""),
        "job_description": fields.get("job_description", ""),
        "requirements": fields.get("requirements", ""),
        "skills": fields.get("skills", ""),
        "raw_fields": fields,
    }
