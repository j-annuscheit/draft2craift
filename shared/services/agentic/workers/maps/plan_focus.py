"""Worker: ``mindmap.plan_focus.v1``.

Purpose:
- Pass the user query and the normalized mode into one compact focus object.

Expected input:
- ``request.query``
- ``state.map_mode_scope.mode``

Output value:
- ``{"query": ..., "mode": ...}``

Tool usage:
- None.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome

WORKER_ID = "mindmap.plan_focus.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = step, projected
    query = str(ctx.request.get("query", "") or "").strip()
    mode_info = dict(ctx.state.get("map_mode_scope", {}) or {})
    return StepOutcome(value={"query": query, "mode": mode_info.get("mode", "mindmap")})
