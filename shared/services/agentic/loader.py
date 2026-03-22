"""Load workflow definitions and profiles from TOML files."""
from __future__ import annotations

from pathlib import Path
import tomllib
from typing import Any

from .contracts import EdgeDef, StepDef, WorkflowDefinition, WorkflowProfile

_CURRENT_SCHEMA_VERSION = 1


def _read_toml_object(path: Path) -> dict[str, Any]:
    if path.suffix.casefold() != ".toml":
        raise ValueError(f"Workflow files must use .toml: {path}")
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Workflow file must contain a top-level object: {path}")
    return raw


def _require_schema_version(raw: dict[str, Any], *, kind: str, path: Path) -> None:
    schema_version = int(raw.get("schema_version", 0) or 0)
    if schema_version != _CURRENT_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported {kind} schema_version {schema_version} in {path}. "
            f"Expected {_CURRENT_SCHEMA_VERSION}."
        )


def _as_step(raw: dict[str, Any]) -> StepDef:
    try:
        max_visits = int(raw.get("max_visits", 0) or 0)
    except Exception:
        max_visits = 0
    return StepDef(
        id=str(raw.get("id", "") or ""),
        runner=str(raw.get("runner", "") or ""),
        input_projection=str(raw.get("input_projection", "") or ""),
        args=dict(raw.get("args", {}) or {}),
        write_to=str(raw.get("write_to", "") or ""),
        on_error=str(raw.get("on_error", "fail_hard") or "fail_hard"),
        max_visits=max(0, int(max_visits)),
        on_max_visits=str(raw.get("on_max_visits", "") or ""),
    )


def _as_edge(raw: dict[str, Any]) -> EdgeDef:
    return EdgeDef(
        from_step=str(raw.get("from", "") or ""),
        to_step=str(raw.get("to", "") or ""),
        when=str(raw.get("when", "") or ""),
        color=str(raw.get("color", "") or ""),
    )


def load_workflow_definition(path: Path) -> WorkflowDefinition:
    raw = _read_toml_object(path)
    _require_schema_version(raw, kind="workflow definition", path=path)
    steps = tuple(_as_step(row) for row in list(raw.get("steps", []) or []))
    edges = tuple(_as_edge(row) for row in list(raw.get("edges", []) or []))
    allow_raw = dict(raw.get("step_tool_allowlist", {}) or {})
    allow = {
        str(step_id): tuple(str(x) for x in list(items or []))
        for step_id, items in allow_raw.items()
    }
    return WorkflowDefinition(
        schema_version=int(raw.get("schema_version", 1) or 1),
        workflow_id=str(raw.get("workflow_id", "") or ""),
        workflow_version=str(raw.get("workflow_version", "1.0.0") or "1.0.0"),
        job_type=str(raw.get("job_type", "") or ""),
        entry_step=str(raw.get("entry_step", "") or ""),
        terminal_steps=tuple(str(x) for x in list(raw.get("terminal_steps", []) or [])),
        state_init=dict(raw.get("state_init", {}) or {}),
        projections=dict(raw.get("projections", {}) or {}),
        steps=steps,
        edges=edges,
        budgets=dict(raw.get("budgets", {}) or {}),
        step_tool_allowlist=allow,
    )


def load_workflow_profile(path: Path) -> WorkflowProfile:
    raw = _read_toml_object(path)
    _require_schema_version(raw, kind="workflow profile", path=path)
    return WorkflowProfile(
        schema_version=int(raw.get("schema_version", 1) or 1),
        profile_id=str(raw.get("profile_id", "") or ""),
        workflow_id=str(raw.get("workflow_id", "") or ""),
        profile_version=str(raw.get("profile_version", "1.0.0") or "1.0.0"),
        description=str(raw.get("description", "") or ""),
        policy=dict(raw.get("policy", {}) or {}),
        model_routing=dict(raw.get("model_routing", {}) or {}),
        cache_policy=dict(raw.get("cache_policy", {}) or {}),
        wiring=dict(raw.get("wiring", {}) or {}),
    )
