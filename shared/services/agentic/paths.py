"""Small dotted-path helpers used by agentic runtime."""
from __future__ import annotations

from typing import Any


def _split(path: str) -> list[str]:
    return [part for part in str(path or "").split(".") if part]


def get_path(data: Any, path: str, default: Any = None) -> Any:
    if not path:
        return data
    cur = data
    for part in _split(path):
        if isinstance(cur, dict):
            if part not in cur:
                return default
            cur = cur[part]
            continue
        if isinstance(cur, list):
            try:
                idx = int(part)
            except Exception:
                return default
            if idx < 0 or idx >= len(cur):
                return default
            cur = cur[idx]
            continue
        return default
    return cur


def set_path(data: dict[str, Any], path: str, value: Any) -> None:
    parts = _split(path)
    if not parts:
        return
    cur: Any = data
    for idx, part in enumerate(parts):
        is_last = idx == len(parts) - 1
        if is_last:
            if isinstance(cur, dict):
                cur[part] = value
            return
        nxt = cur.get(part) if isinstance(cur, dict) else None
        if not isinstance(nxt, dict):
            nxt = {}
            if isinstance(cur, dict):
                cur[part] = nxt
        cur = nxt


def pop_path(data: dict[str, Any], path: str) -> Any:
    parts = _split(path)
    if not parts:
        return None
    cur: Any = data
    for idx, part in enumerate(parts):
        is_last = idx == len(parts) - 1
        if not isinstance(cur, dict) or part not in cur:
            return None
        if is_last:
            return cur.pop(part, None)
        cur = cur[part]
    return None

