"""Worker: ``canvas.preview_and_apply.v1``.

Purpose:
- Apply the generated patch through the canvas tool.

Expected input:
- ``state.canvas_patch.patched_text``

Output value:
- ``{"applied": bool, "text": str}``

Tool usage:
- ``canvas.apply``

Failure behavior:
- Tool failures are converted into ``applied = False``.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome

WORKER_ID = "canvas.preview_and_apply.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = step, projected
    patch = dict(ctx.state.get("canvas_patch", {}) or {})
    text = str(patch.get("patched_text", "") or "")
    applied = False
    try:
        ctx.tools.call("canvas.apply", text=text)
        applied = True
    except Exception:
        applied = False
    return StepOutcome(value={"applied": applied, "text": text})
