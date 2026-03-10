"""Common normalization and path helpers for highlight storage."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_text(text: str) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\u2029", "\n")


def normalize_scope(value: str) -> str:
    clean = str(value or "").strip().lower()
    return clean or "generic"


def normalize_tab(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("🔒 "):
        text = text[2:].strip()
    return text


def default_store_path() -> Path:
    raw = str(os.getenv("DRAFT2CRAIFT_HIGHLIGHTS_JSON", "")).strip()
    if raw:
        return Path(raw).expanduser()
    return (Path.cwd() / "highlights.json").resolve()


__all__ = [
    "default_store_path",
    "normalize_scope",
    "normalize_tab",
    "normalize_text",
    "utc_now",
]
