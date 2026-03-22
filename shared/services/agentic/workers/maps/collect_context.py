"""Worker: ``mindmap.collect_context.v1``.

Purpose:
- Copy the already assembled context text into workflow state.

Expected input:
- ``request.context_text``

Output value:
- ``{"context_text": ...}``

Tool usage:
- None.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome

WORKER_ID = "mindmap.collect_context.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = step, projected
    return StepOutcome(value={"context_text": str(ctx.request.get("context_text", "") or "")})
