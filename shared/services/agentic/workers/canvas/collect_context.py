"""Worker: ``canvas.collect_context.v1``.

Purpose:
- Normalize the selected canvas text and instruction into one state object.

Expected input:
- ``request.selected_text``
- ``request.instruction``

Output value:
- ``{"selected_text": ..., "instruction": ...}``
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome

WORKER_ID = "canvas.collect_context.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = step, projected
    return StepOutcome(
        value={
            "selected_text": str(ctx.request.get("selected_text", "") or ""),
            "instruction": str(ctx.request.get("instruction", "") or ""),
        }
    )
