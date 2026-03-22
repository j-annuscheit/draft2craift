"""Tool runtime helpers: model routing and lightweight call cache."""
from __future__ import annotations

import hashlib
import json
from typing import Any


def _normalize_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key in sorted(value.keys(), key=lambda x: str(x)):
            out[str(key)] = _normalize_value(value[key])
        return out
    if isinstance(value, (list, tuple)):
        return [_normalize_value(item) for item in list(value)]
    return repr(value)


def make_cache_key(tool_name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    payload = {
        "tool_name": str(tool_name or ""),
        "args": _normalize_value(list(args or ())),
        "kwargs": _normalize_value(dict(kwargs or {})),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()


def resolve_model_route(
    *,
    model_routing: dict[str, Any] | None,
    step_id: str,
    logical_step_key: str,
) -> str:
    routes = dict(model_routing or {})
    for key in (str(logical_step_key or "").strip(), str(step_id or "").strip()):
        if not key:
            continue
        value = routes.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def cache_config(policy: dict[str, Any]) -> dict[str, Any]:
    cfg = dict(policy.get("cache_policy", {}) or {})
    return cfg


def cache_enabled(policy: dict[str, Any]) -> bool:
    cfg = cache_config(policy)
    return bool(cfg.get("enabled", False))


def cache_ttl_for_tool(policy: dict[str, Any], tool_name: str) -> float:
    cfg = cache_config(policy)
    per_tool = dict(cfg.get("per_tool_ttl_seconds", {}) or {})
    key = str(tool_name or "")
    value = per_tool.get(key, cfg.get("default_ttl_seconds", 0))
    try:
        return max(0.0, float(value or 0.0))
    except Exception:
        return 0.0

