"""Worker: ``control.pick_next_claim.v1``.

Purpose:
- Select the next fact-check claim from ``state.claims``.
- Mark the workflow as done when the cursor is past the last claim.

Expected input:
- ``state.claims``: ordered list of candidate claims.
- ``state.claim_cursor``: zero-based index of the next claim.

Writes via ``StepOutcome.updates``:
- ``state.done``
- ``state.current_claim``

Tool usage:
- None.

Failure behavior:
- Missing state values fall back to an empty list / zero.
- The worker never raises intentionally; it always returns a deterministic
  outcome based on the current state snapshot.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.paths import get_path

WORKER_ID = "control.pick_next_claim.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = step, projected
    claims = get_path(ctx.state, "claims", []) or []
    cursor = int(get_path(ctx.state, "claim_cursor", 0) or 0)
    if cursor >= len(claims):
        return StepOutcome(
            updates={
                "state.done": True,
                "state.current_claim": "",
            }
        )
    claim = str(claims[cursor] or "").strip()
    return StepOutcome(
        updates={
            "state.done": False,
            "state.current_claim": claim,
        }
    )
