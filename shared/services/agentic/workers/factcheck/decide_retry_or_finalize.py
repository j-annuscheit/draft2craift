"""Worker: ``controller.retry_or_finalize.v1``.

Purpose:
- Decide whether a factcheck claim should trigger another search round.

Expected input:
- ``state.verify_result.status``
- ``state.round``
- ``policy.max_search_rounds_per_fact``

Output value:
- ``{"retry": bool, "reason": "status_gate"}``
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome

WORKER_ID = "controller.retry_or_finalize.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = step, projected
    verify = dict(ctx.state.get("verify_result", {}) or {})
    status = str(verify.get("status", "nicht_belegt") or "nicht_belegt").casefold()
    round_idx = int(ctx.state.get("round", 0) or 0)
    max_rounds = int(ctx.policy.get("max_search_rounds_per_fact", 2) or 2)
    retry = bool(status == "nicht_belegt" and round_idx + 1 < max_rounds)
    return StepOutcome(value={"retry": retry, "reason": "status_gate"})
