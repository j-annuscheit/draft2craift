"""Pronunciation overrides that can be extended via config files."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Iterable

from shared.config.paths import app_data_dir

_BASE_DIR = Path(__file__).resolve().parents[4]
_DEFAULT_OVERRIDES = (
    _BASE_DIR / "data" / "speech" / "pronunciations.json"
)
_ENV_OVERRIDES = os.getenv("DRAFT2CRAIFT_TTS_PRONUNCIATION_MAP", "").strip()
_CACHE: dict[str, str] | None = None


def _resolve_override_sources() -> Iterable[Path]:
    sources: list[Path] = []
    if _DEFAULT_OVERRIDES.exists():
        sources.append(_DEFAULT_OVERRIDES)
    if _ENV_OVERRIDES:
        env_path = Path(_ENV_OVERRIDES).expanduser()
        if env_path.is_absolute():
            sources.append(env_path)
        else:
            sources.append((app_data_dir() / env_path).resolve(strict=False))
    user_path = app_data_dir() / "speech" / "pronunciations.json"
    sources.append(user_path)
    return sources


def _load_pronunciation_overrides() -> dict[str, str]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    overrides: dict[str, str] = {}
    for source in _resolve_override_sources():
        if not source.exists():
            continue
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                continue
            for key, value in payload.items():
                if not key or not isinstance(key, str):
                    continue
                if not isinstance(value, str):
                    continue
                overrides[key.strip()] = value
        except Exception:
            continue
    _CACHE = overrides
    return overrides


def _apply_pronunciation_overrides(text: str) -> str:
    cleaned = str(text or "")
    if not cleaned.strip():
        return cleaned
    overrides = _load_pronunciation_overrides()
    if not overrides:
        return cleaned
    for phrase, substitute in overrides.items():
        if not phrase:
            continue
        try:
            pattern = re.compile(re.escape(phrase), re.IGNORECASE)
            cleaned = pattern.sub(substitute, cleaned)
        except re.error:
            continue
    return cleaned


__all__ = [
    "_apply_pronunciation_overrides",
]
