"""Deterministic tool stubs for agentic benchmark runs."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


ToolFn = Callable[..., Any]


@dataclass(slots=True)
class ToolRecorder:
    calls: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def record(self, tool_name: str, kwargs: dict[str, Any]) -> None:
        key = str(tool_name or "").strip()
        self.calls.setdefault(key, []).append(dict(kwargs or {}))

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        return {name: list(rows) for name, rows in dict(self.calls or {}).items()}


def build_tools(specs: dict[str, dict[str, Any]]) -> tuple[dict[str, ToolFn], ToolRecorder]:
    recorder = ToolRecorder()
    tools: dict[str, ToolFn] = {}
    for tool_name, raw in dict(specs or {}).items():
        name = str(tool_name or "").strip()
        if not name:
            continue
        spec = dict(raw or {})
        tools[name] = _build_tool(name, spec, recorder)
    return tools, recorder


def _build_tool(tool_name: str, spec: dict[str, Any], recorder: ToolRecorder) -> ToolFn:
    kind = str(spec.get("kind", "constant") or "constant").strip().casefold()
    if kind == "constant":
        value = spec.get("value")

        def _fn(**kwargs):
            recorder.record(tool_name, kwargs)
            return value

        return _fn

    if kind == "sequence":
        values = list(spec.get("values", []) or [])
        cursor = {"idx": 0}

        def _fn(**kwargs):
            recorder.record(tool_name, kwargs)
            idx = int(cursor["idx"])
            cursor["idx"] = idx + 1
            if idx >= len(values):
                return values[-1] if values else None
            return values[idx]

        return _fn

    if kind == "nli_contains_hypothesis":
        threshold = float(spec.get("score", 0.91) or 0.91)

        def _fn(**kwargs):
            recorder.record(tool_name, kwargs)
            premise = str(kwargs.get("premise", "") or "")
            hypothesis = str(kwargs.get("hypothesis", "") or "")
            if hypothesis and hypothesis in premise:
                return {"label": "entailment", "score": threshold}
            return {"label": "neutral", "score": 0.15}

        return _fn

    if kind == "rag_from_possible_sources":
        default_hits = list(spec.get("fallback_hits", []) or [])

        def _fn(**kwargs):
            recorder.record(tool_name, kwargs)
            rows = list(kwargs.get("possible_sources", []) or [])
            hits: list[str] = []
            for item in rows:
                if not isinstance(item, (list, tuple)) or len(item) < 2:
                    continue
                text = str(item[1] or "").strip()
                if text:
                    hits.append(text)
            if hits:
                return hits
            return list(default_hits)

        return _fn

    if kind == "template":
        template = str(spec.get("template", "{prompt}") or "{prompt}")

        def _fn(**kwargs):
            recorder.record(tool_name, kwargs)
            try:
                return template.format(**dict(kwargs or {}))
            except Exception:
                return template

        return _fn

    if kind == "capture_text":
        value = spec.get("return", True)

        def _fn(**kwargs):
            recorder.record(tool_name, kwargs)
            return value

        return _fn

    if kind == "fail":
        message = str(spec.get("message", f"{tool_name} forced failure") or "")

        def _fn(**kwargs):
            recorder.record(tool_name, kwargs)
            raise RuntimeError(message)

        return _fn

    raise ValueError(f"Unsupported tool kind for '{tool_name}': {kind}")
