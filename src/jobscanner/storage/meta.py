"""The `meta` key/value table: the scan cutoff and persisted UI layout."""

from __future__ import annotations

import json
from pathlib import Path

from jobscanner import config
from jobscanner.storage.schema import connect

META_KEY_LATEST_SCAN_STARTED_AT = "latest_scan_started_at"
# Historical key name — the payload is now a layout dict, but the key is
# kept so existing databases don't lose their saved sidebar width.
META_KEY_SASH_WIDTHS = "sash_widths_px"


def get_meta(key: str, path: Path = config.DB_PATH) -> str:
    with connect(path) as conn:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
    return row[0] if row else ""


def set_meta(key: str, value: str, path: Path = config.DB_PATH) -> None:
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()


def get_latest_scan_started_at(path: Path = config.DB_PATH) -> str:
    """ISO timestamp of the most recent completed scan, or ``''`` if none."""
    return get_meta(META_KEY_LATEST_SCAN_STARTED_AT, path)


def set_latest_scan_started_at(value: str, path: Path = config.DB_PATH) -> None:
    set_meta(META_KEY_LATEST_SCAN_STARTED_AT, value, path)


# ---------------------------------------------------------------------------
# UI layout preferences
# ---------------------------------------------------------------------------


def get_sash_widths(path: Path = config.DB_PATH) -> list[int] | None:
    """Return persisted [sidebar, table, detail] widths in px, or None."""
    raw = get_meta(META_KEY_SASH_WIDTHS, path)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if isinstance(data, list) and len(data) == 3 and all(
        isinstance(v, int) for v in data
    ):
        return data
    return None


def set_sash_widths(widths: list[int], path: Path = config.DB_PATH) -> None:
    """Persist [sidebar, table, detail] widths in px to the meta table."""
    set_meta(META_KEY_SASH_WIDTHS, json.dumps(list(widths)), path)
