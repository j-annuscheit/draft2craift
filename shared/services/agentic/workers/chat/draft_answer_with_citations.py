"""Worker: ``chat.draft_answer_with_citations.v1``.

Purpose:
- Ask the LLM to draft a grounded answer from the retrieved evidence.

Expected input:
- ``request.question``
- ``state.retrieval_hits``

Output value:
- ``{"text": ..., "citations": ...}``

Tool usage:
- ``llm.generate``

Failure behavior:
- LLM errors degrade to an empty answer string.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome

WORKER_ID = "chat.draft_answer_with_citations.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = step, projected
    question = str(ctx.request.get("question", "") or "").strip()
    hits = list(ctx.state.get("retrieval_hits", []) or [])
    joined = "\n".join(str(h) for h in hits[:5])
    prompt = f"Beantworte die Frage anhand der Evidenz.\nFrage: {question}\nEvidenz:\n{joined}\n"
    try:
        answer = str(ctx.tools.call("llm.generate", prompt=prompt) or "")
    except Exception:
        answer = ""
    return StepOutcome(value={"text": answer, "citations": hits[:3]})
