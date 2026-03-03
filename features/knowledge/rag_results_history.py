"""History helpers for RAG debug data."""
from __future__ import annotations

from datetime import datetime

MAX_DEBUG_HISTORY = 200
_MAX_INPUT_HISTORY = 500


def build_debug_entry(
    query: str,
    debug_payload: object,
    tab_index: int,
    tab_title: str,
    result_count: int,
) -> dict:
    """Create one persisted debug entry."""
    return {
        "query": query,
        "debug": debug_payload,
        "tab_index": tab_index,
        "tab_title": tab_title,
        "result_count": result_count,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def append_debug_entry(history: list[dict], entry: dict) -> list[dict]:
    """Append one entry and keep only the most recent history items."""
    return (list(history) + [entry])[-MAX_DEBUG_HISTORY:]


def sanitize_debug_history(items: object) -> list[dict]:
    """Validate and normalize loaded debug history state."""
    if not isinstance(items, list):
        return []

    clean: list[dict] = []
    for item in items[-_MAX_INPUT_HISTORY:]:
        if not isinstance(item, dict):
            continue

        query = str(item.get("query", ""))
        debug = item.get("debug", {})
        if not isinstance(debug, dict):
            continue

        tab_title = str(item.get("tab_title", "🔍 RAG"))
        try:
            tab_index = int(item.get("tab_index", -1))
        except (TypeError, ValueError):
            tab_index = -1

        try:
            result_count = int(item.get("result_count", 0))
        except (TypeError, ValueError):
            result_count = 0

        timestamp = str(item.get("timestamp", ""))
        clean.append(
            {
                "query": query,
                "debug": debug,
                "tab_title": tab_title,
                "tab_index": tab_index,
                "result_count": result_count,
                "timestamp": timestamp,
            }
        )

    return clean[-MAX_DEBUG_HISTORY:]
