"""Small runtime helpers for agentic workflow runs."""
from __future__ import annotations

from typing import Any

from .contracts import WorkflowRunResult


def summarize_run(result: WorkflowRunResult) -> dict[str, Any]:
    """Return a compact, serializable run summary."""
    return {
        "ok": bool(result.ok),
        "workflow_id": str(result.workflow_id or ""),
        "profile_id": str(result.profile_id or ""),
        "errors": list(result.errors or []),
        "elapsed_ms": float(result.metrics.get("elapsed_ms", 0.0) or 0.0),
        "steps": int(result.metrics.get("steps", 0) or 0),
        "tool_calls": dict(result.metrics.get("tool_calls", {}) or {}),
    }
