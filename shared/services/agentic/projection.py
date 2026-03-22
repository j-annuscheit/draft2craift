"""Context projection helpers for least-context step execution."""
from __future__ import annotations

from typing import Any

from .paths import get_path


def _extract_wildcard_path(root: Any, parts: list[str]) -> Any:
    if not parts:
        return root
    head = parts[0]
    tail = parts[1:]
    if head.endswith("[*]"):
        key = head[:-3]
        base = root.get(key, []) if isinstance(root, dict) else []
        if not isinstance(base, list):
            return []
        return [_extract_wildcard_path(item, tail) for item in base]
    if "[" in head and head.endswith("]"):
        key, idx_raw = head[:-1].split("[", 1)
        base = root.get(key, []) if isinstance(root, dict) else []
        if not isinstance(base, list):
            return None
        try:
            idx = int(idx_raw)
        except Exception:
            return None
        if idx < 0 or idx >= len(base):
            return None
        return _extract_wildcard_path(base[idx], tail)
    nxt = root.get(head) if isinstance(root, dict) else None
    return _extract_wildcard_path(nxt, tail)


def _extract_path(context: dict[str, Any], path: str) -> Any:
    text = str(path or "").strip()
    if not text:
        return None
    parts = [part for part in text.split(".") if part]
    if any("[*]" in part for part in parts) or any("[" in part and part.endswith("]") for part in parts):
        return _extract_wildcard_path(context, parts)
    return get_path(context, text)


def project_context(
    *,
    projection_name: str,
    projection_map: dict[str, dict[str, Any]],
    context: dict[str, Any],
) -> dict[str, Any]:
    if not projection_name:
        return {"raw": {}, "name": ""}
    cfg = projection_map.get(projection_name, {})
    include = cfg.get("include", [])
    raw: dict[str, Any] = {}
    for item in list(include or []):
        path = str(item or "").strip()
        if not path:
            continue
        raw[path] = _extract_path(context, path)
    return {"name": projection_name, "raw": raw}


def projection_get(projected: dict[str, Any], path: str, default: Any = None) -> Any:
    raw = projected.get("raw", {}) if isinstance(projected, dict) else {}
    if path in raw:
        return raw.get(path, default)
    return default

