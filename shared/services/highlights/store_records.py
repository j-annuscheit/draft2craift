"""Record defaults and applicability rules for highlight storage."""
from __future__ import annotations

from .store_common import normalize_scope, normalize_tab


STORE_VERSION = 2
DEFAULT_HIGHLIGHT_COLOR = "#F9E2AF"
DEFAULT_GLOSSARY_COLOR = "#94E2D5"


def normalize_color(color: object) -> str:
    text = str(color or "").strip()
    if not text:
        return DEFAULT_HIGHLIGHT_COLOR
    if not text.startswith("#"):
        return DEFAULT_HIGHLIGHT_COLOR
    if len(text) == 4:
        # #RGB -> #RRGGBB
        r = text[1]
        g = text[2]
        b = text[3]
        return f"#{r}{r}{g}{g}{b}{b}".upper()
    if len(text) != 7:
        return DEFAULT_HIGHLIGHT_COLOR
    return text.upper()


def default_data() -> dict:
    return {
        "version": STORE_VERSION,
        "highlights": [],
        "settings": {"glossary_enabled": True},
    }


def normalize_settings(raw: object) -> dict:
    if not isinstance(raw, dict):
        return {"glossary_enabled": True}
    return {
        "glossary_enabled": bool(raw.get("glossary_enabled", True)),
    }


def record_kind(record: dict) -> str:
    clean = str(record.get("kind", "user") or "").strip().lower()
    if clean in {"user", "glossary"}:
        return clean
    return "user"


def is_glossary_record(record: dict) -> bool:
    return record_kind(record) == "glossary"


def match_mode(record: dict) -> str:
    mode = str(record.get("match_mode", "anchor") or "").strip().lower()
    if mode in {"anchor", "term_all"}:
        return mode
    return "anchor"


def record_applies(record: dict, panel_scope: str, tab_name: str) -> bool:
    rec_scope = normalize_scope(record.get("panel_scope", ""))
    if rec_scope not in {panel_scope, "*"}:
        return False

    tab_scope = str(record.get("tab_scope", "") or "tabs").strip().lower()
    if tab_scope == "all":
        return True

    tabs = [
        normalize_tab(item)
        for item in list(record.get("tabs", []) or [])
        if normalize_tab(item)
    ]
    if not tabs:
        return False
    return normalize_tab(tab_name) in tabs


__all__ = [
    "DEFAULT_GLOSSARY_COLOR",
    "DEFAULT_HIGHLIGHT_COLOR",
    "STORE_VERSION",
    "default_data",
    "is_glossary_record",
    "match_mode",
    "normalize_color",
    "normalize_settings",
    "record_applies",
    "record_kind",
]
