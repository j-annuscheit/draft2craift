"""Worker: ``rag.execute.v1``.

Purpose:
- Execute a factcheck retrieval plan with the requested retrieval mode.

Expected input:
- ``state.query_plan``
- ``request.q`` as optional source restriction
- ``policy.max_evidence_chunks``

Output value:
- bounded list of evidence hits.

Tool usage:
- ``rag.search``
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome

WORKER_ID = "rag.execute.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = step, projected
    plan = dict(ctx.state.get("query_plan", {}) or {})
    query = str(plan.get("query", "") or "")
    regex_patterns = list(plan.get("regex_patterns", []) or [])
    mode = str(plan.get("mode", "hybrid") or "hybrid")
    try:
        max_hits = max(1, int(ctx.policy.get("max_evidence_chunks", 8) or 8))
    except Exception:
        max_hits = 8
    try:
        hits = ctx.tools.call(
            "rag.search",
            query=query,
            mode=mode,
            regex_patterns=regex_patterns,
            possible_sources=ctx.request.get("q", []),
        )
    except Exception:
        hits = []
    return StepOutcome(value=list(hits or [])[:max_hits])
