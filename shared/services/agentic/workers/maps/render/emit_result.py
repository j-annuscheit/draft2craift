"""Worker: ``map.emit_result.v1``.

Purpose:
- Emit the final mindmap markdown to canvas and finish the workflow.

Expected input:
- ``state.map_result.markdown``
- ``state.map_validation``

Output value:
- terminal result payload with final markdown

Meta:
- ``markdown_chars``

Tool usage:
- ``canvas.open_text``

Failure behavior:
- Emits an empty result when no markdown is available.

Invariants preserved:
- The workflow stops after this worker.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.emit_result.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = step
    payload = dict(projection_get(projected, "state.map_result", {}) or {})
    validation = dict(projection_get(projected, "state.map_validation", {}) or {})
    markdown = str(payload.get("markdown", "") or "")
    if markdown:
        ctx.tools.call("canvas.open_text", text=markdown, title="Mindmap")
    result_payload = {"markdown": markdown, "mode": "mindmap", "stats": dict(validation.get("stats", {}) or {})}
    return StepOutcome(
        value=result_payload,
        updates={"result.markdown": markdown, "result.meta": result_payload},
        stop=True,
        meta={"markdown_chars": len(markdown)},
    )
