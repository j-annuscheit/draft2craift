"""Worker: ``map.resolve_request.v1``.

Purpose:
- Normalize the incoming user request for the mindmap workflow.
- Derive a stable topic/focus string and the requested target depth.

Expected input:
- ``request.query``
- ``request.mode``
- ``request.depth``

Output value:
- ``{"topic": ..., "focus": ..., "mode": "mindmap", "target_depth": int, "style_constraints": []}``

Meta:
- ``query_chars``

Tool usage:
- none

Failure behavior:
- Falls back to a safe default request object.

Invariants preserved:
- ``mode`` is always ``mindmap``.
- ``target_depth`` is clamped to a small positive range.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.resolve_request.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    query = str(projection_get(projected, "request.query", "") or "").strip()
    depth = projection_get(projected, "request.depth", 0)
    try:
        target_depth = int(depth or 0)
    except Exception:
        target_depth = 0
    target_depth = max(2, min(10, target_depth or 4))
    topic = query or "Mindmap aus Kontext"
    return StepOutcome(
        value={
            "topic": topic,
            "focus": query or topic,
            "mode": "mindmap",
            "target_depth": target_depth,
            "style_constraints": [],
        },
        meta={"query_chars": len(query)},
    )
