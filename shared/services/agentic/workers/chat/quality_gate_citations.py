"""Worker: ``chat.quality_gate.citations.v1``.

Purpose:
- Reject empty answers and answers without citation payload.

Expected input:
- ``state.draft_answer.text``
- ``state.draft_answer.citations``

Output value:
- ``{"ok": bool, "reason": str}``

Tool usage:
- None.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome

WORKER_ID = "chat.quality_gate.citations.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = step, projected
    draft = dict(ctx.state.get("draft_answer", {}) or {})
    text = str(draft.get("text", "") or "")
    citations = list(draft.get("citations", []) or [])
    if text.strip() and citations:
        return StepOutcome(value={"ok": True, "reason": "has_citations"})
    return StepOutcome(value={"ok": False, "reason": "missing_citations"})
