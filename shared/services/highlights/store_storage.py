"""Persistence helpers for highlight store payloads."""
from __future__ import annotations

import json
from pathlib import Path

from .store_common import utc_now
from .store_records import STORE_VERSION, default_data, normalize_settings


def load_store_data(path: Path) -> dict:
    try:
        if not path.exists():
            return default_data()
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return default_data()
        highlights = raw.get("highlights")
        if not isinstance(highlights, list):
            highlights = []
        settings = normalize_settings(raw.get("settings"))
        return {
            "version": int(raw.get("version", STORE_VERSION)),
            "highlights": [row for row in highlights if isinstance(row, dict)],
            "settings": settings,
        }
    except Exception:
        return default_data()


def save_store_data(path: Path, payload: dict):
    data = dict(payload)
    data["version"] = STORE_VERSION
    data["settings"] = normalize_settings(data.get("settings"))
    data["updated_at"] = utc_now()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp.replace(path)


__all__ = ["load_store_data", "save_store_data"]
