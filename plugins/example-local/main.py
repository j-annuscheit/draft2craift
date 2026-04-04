"""Example plugin for the new local-first runtime."""
from __future__ import annotations

from typing import Any


def _tag_prompt(payload: dict[str, Any]) -> dict[str, Any]:
    prompt = str(payload.get("prompt", "") or "")
    if not prompt:
        return payload
    payload["prompt"] = prompt + "\n\n[Plugin: example-local active]"
    return payload


def _trim_result(payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload.get("text", "") or "")
    payload["text"] = text.strip()
    return payload


def register(manager) -> None:
    manager.register_hook(
        "llm.before_generate",
        _tag_prompt,
        plugin_id="example-local",
    )
    manager.register_hook(
        "llm.after_generate",
        _trim_result,
        plugin_id="example-local",
    )

