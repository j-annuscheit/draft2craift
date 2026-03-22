"""Worker: ``chat.emit_response.v1``.

Purpose:
- Project the prepared chat response into ``result.response`` and stop.

Expected input:
- ``state.draft_answer``
- ``state.quality_gate``

Writes via ``StepOutcome.updates``:
- ``result.response``

Tool usage:
- None.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome

WORKER_ID = "chat.emit_response.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = step, projected
    draft = dict(ctx.state.get("draft_answer", {}) or {})
    gate = dict(ctx.state.get("quality_gate", {}) or {})
    payload = {
        "text": str(draft.get("text", "") or ""),
        "citations": list(draft.get("citations", []) or []),
        "quality": gate,
    }
    return StepOutcome(updates={"result.response": payload}, stop=True)
