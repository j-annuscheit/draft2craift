"""Typed contracts for agentic workflow execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


ToolFn = Callable[..., Any]


@dataclass(slots=True)
class StepDef:
    id: str
    runner: str
    input_projection: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    write_to: str = ""
    on_error: str = "fail_hard"
    max_visits: int = 0
    on_max_visits: str = ""


@dataclass(slots=True)
class EdgeDef:
    from_step: str
    to_step: str
    when: str = ""
    color: str = ""   # optional hex color, e.g. "#27ae60"


@dataclass(slots=True)
class WorkflowDefinition:
    schema_version: int
    workflow_id: str
    workflow_version: str
    job_type: str
    entry_step: str
    terminal_steps: tuple[str, ...]
    state_init: dict[str, Any]
    projections: dict[str, dict[str, Any]]
    steps: tuple[StepDef, ...]
    edges: tuple[EdgeDef, ...]
    budgets: dict[str, Any]
    step_tool_allowlist: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def step_by_id(self) -> dict[str, StepDef]:
        return {step.id: step for step in self.steps}


@dataclass(slots=True)
class WorkflowProfile:
    schema_version: int
    profile_id: str
    workflow_id: str
    profile_version: str
    description: str
    policy: dict[str, Any]
    model_routing: dict[str, str]
    cache_policy: dict[str, Any]
    wiring: dict[str, str]


@dataclass(slots=True)
class StepOutcome:
    """Single-step result returned by step runners."""

    value: Any = None
    updates: dict[str, Any] = field(default_factory=dict)
    jump: str = ""
    stop: bool = False
    meta: dict[str, Any] = field(default_factory=dict)
    candidate_writes: dict[str, dict[str, Any]] = field(default_factory=dict)
    commit_candidates: tuple[str, ...] = ()
    discard_candidates: tuple[str, ...] = ()


@dataclass(slots=True)
class StepTrace:
    step_id: str
    runner: str
    status: str
    duration_ms: float
    reason: str = ""
    visit_index: int = 0
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    state_after: dict[str, Any] = field(default_factory=dict)
    transition: dict[str, Any] = field(default_factory=dict)
    # transition schema:
    # {
    #   "kind":            "edge" | "jump" | "error" | "stop" | "terminal"
    #                      | "budget_exceeded" | "no_edge_matched" | "max_visits",
    #   "next_step":       str,   # "" if workflow ends here
    #   "condition":       str,   # the `when` expression that fired (edge kind)
    #   "decisive_param":  str,   # first dotted-path identifier in condition
    #   "edges": [                # all edges from this step, in evaluation order
    #     {"to_step": str, "when": str, "matched": bool}, ...
    #   ],
    # }


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
