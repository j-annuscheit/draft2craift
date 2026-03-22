"""Worker: ``factcheck.append_fact_row.v1``.

Purpose:
- Append the verification result for the current claim to ``state.facts_out``.

Expected input:
- ``state.current_claim``
- ``state.verify_result``
- ``state.facts_out``
- ``state.claim_cursor``

Writes via ``StepOutcome.updates``:
- ``facts_out``
- ``claim_cursor``
- ``round`` reset to ``0``
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome

WORKER_ID = "factcheck.append_fact_row.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = step, projected
    claim = str(ctx.state.get("current_claim", "") or "").strip()
    verify = dict(ctx.state.get("verify_result", {}) or {})
    if claim:
        row = {
            "fact": claim,
            "status": str(verify.get("status", "nicht_belegt") or "nicht_belegt"),
            "reason": str(verify.get("reason", "") or ""),
            "evidence": str(verify.get("evidence", "") or ""),
            "confidence": float(verify.get("confidence", 0.0) or 0.0),
            "method": "agentic",
        }
        rows = list(ctx.state.get("facts_out", []) or [])
        rows.append(row)
        next_cursor = int(ctx.state.get("claim_cursor", 0) or 0) + 1
        return StepOutcome(updates={"facts_out": rows, "claim_cursor": next_cursor, "round": 0})
    return StepOutcome()
