"""Worker: ``chat.classify_user_intent.v1``.

Purpose:
- Heuristically classify the chat request so later steps can adapt retrieval
  and response behavior.

Expected input:
- ``request.question``

Output value:
- ``{"intent": <intent>}``

Tool usage:
- None.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome

WORKER_ID = "chat.classify_user_intent.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = step, projected
    question = str(ctx.request.get("question", "") or "").strip().casefold()
    intent = "answer"
    if "zusammen" in question or "summary" in question:
        intent = "summarize"
    elif "vergleich" in question or "compare" in question:
        intent = "compare"
    elif "beleg" in question or "quelle" in question:
        intent = "grounded_answer"
    return StepOutcome(value={"intent": intent})
