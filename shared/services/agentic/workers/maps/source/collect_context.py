"""Worker: ``map.collect_context.v1``.

Purpose:
- Copy the full source context into workflow state without truncation.

Expected input:
- ``request.context_text``

Output value:
- ``{"context_text": ..., "context_chars": int}``

Meta:
- ``context_chars``

Tool usage:
- none

Failure behavior:
- Returns an empty context payload when the request is empty.

Invariants preserved:
- The worker never truncates the provided context.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.collect_context.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    context_text = str(projection_get(projected, "request.context_text", "") or "")
    return StepOutcome(
        value={"context_text": context_text, "context_chars": len(context_text)},
        meta={"context_chars": len(context_text)},
    )
