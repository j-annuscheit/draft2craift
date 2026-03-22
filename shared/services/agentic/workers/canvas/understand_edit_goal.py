"""Worker: ``canvas.understand_edit_goal.v1``.

Purpose:
- Infer a coarse edit goal from the user instruction.

Expected input:
- ``request.instruction``

Output value:
- ``{"goal": "rewrite"|"condense"|"expand"}``
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome

WORKER_ID = "canvas.understand_edit_goal.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = step, projected
    instruction = str(ctx.request.get("instruction", "") or "").strip().casefold()
    goal = "rewrite"
    if "kürz" in instruction or "short" in instruction:
        goal = "condense"
    elif "erweit" in instruction or "expand" in instruction:
        goal = "expand"
    return StepOutcome(value={"goal": goal})
