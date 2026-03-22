"""Worker: ``mindmap.resolve_mode_scope.v1``.

Purpose:
- Normalize ``request.mode`` and ``request.scope`` into a small state object.

Expected input:
- ``request.mode``
- ``request.scope``

Output value:
- ``{"mode": ..., "scope": ...}``

Tool usage:
- None.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome

WORKER_ID = "mindmap.resolve_mode_scope.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = step, projected
    mode = str(ctx.request.get("mode", "mindmap") or "mindmap").strip().casefold()
    if mode not in {"mindmap", "graph", "chunkmap"}:
        mode = "mindmap"
    scope = str(ctx.request.get("scope", "selection") or "selection").strip().casefold()
    return StepOutcome(value={"mode": mode, "scope": scope})
