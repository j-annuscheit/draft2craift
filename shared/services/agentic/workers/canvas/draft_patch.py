"""Worker: ``canvas.draft_patch.v1``.

Purpose:
- Ask the LLM for a replacement text snippet.

Expected input:
- ``state.canvas_context.selected_text``
- ``state.canvas_context.instruction``

Output value:
- ``{"patched_text": <llm text>}``

Tool usage:
- ``llm.generate``
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome

WORKER_ID = "canvas.draft_patch.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = step, projected
    c = dict(ctx.state.get("canvas_context", {}) or {})
    prompt = (
        "Bearbeite den Text gemaess Anweisung.\n"
        f"Anweisung: {c.get('instruction', '')}\n"
        f"Text:\n{c.get('selected_text', '')}\n"
    )
    try:
        patch = str(ctx.tools.call("llm.generate", prompt=prompt) or "")
    except Exception:
        patch = ""
    return StepOutcome(value={"patched_text": patch})
