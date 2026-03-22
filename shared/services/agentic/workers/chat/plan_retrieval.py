"""Worker: ``chat.plan_retrieval.v1``.

Purpose:
- Translate the user question into a compact retrieval plan.

Expected input:
- ``request.question``
- ``policy.chat_top_k``

Output value:
- ``{"query": <question>, "top_k": <int>}``

Tool usage:
- None.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome

WORKER_ID = "chat.plan_retrieval.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = step, projected
    question = str(ctx.request.get("question", "") or "").strip()
    return StepOutcome(value={"query": question, "top_k": int(ctx.policy.get("chat_top_k", 5) or 5)})
