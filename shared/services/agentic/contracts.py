"""Minimal contracts for LangGraph-backed workflow execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class StepTrace:
    step_id: str
    status: str
    duration_ms: float
    reason: str = ""
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WorkflowRunResult:
    ok: bool
    workflow_id: str
    profile_id: str
    result: dict[str, Any]
    state: dict[str, Any]
    trace: list[StepTrace]
    errors: list[str]
    metrics: dict[str, Any]

