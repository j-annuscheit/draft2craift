"""Worker: ``chat.retrieve_candidates.v1``.

Purpose:
- Execute the retrieval plan against the RAG backend.

Expected input:
- ``state.retrieval_plan.query``
- ``state.retrieval_plan.top_k``

Output value:
- list of retrieval hits.

Tool usage:
- ``rag.search``

Failure behavior:
- Tool failures degrade to an empty hit list.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome

WORKER_ID = "chat.retrieve_candidates.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = step, projected
    plan = dict(ctx.state.get("retrieval_plan", {}) or {})
    query = str(plan.get("query", "") or "")
    top_k = int(plan.get("top_k", 5) or 5)
    try:
        hits = ctx.tools.call("rag.search", query=query, mode="hybrid", top_k=top_k)
    except Exception:
        hits = []
    return StepOutcome(value=list(hits or []))
