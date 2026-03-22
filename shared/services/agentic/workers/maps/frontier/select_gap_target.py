"""Worker: ``map.select_gap_target.v1``.

Purpose:
- Choose exactly one detected gap as the next gap-fill target.

Expected input:
- ``state.map_gaps.gaps``
- ``state.map_metrics.gap_round``
- ``policy.map_max_gap_rounds``

Output value:
- selected gap payload with ``selected`` and parent / segment metadata

Meta:
- ``selected``
- ``reason``

Tool usage:
- none

Failure behavior:
- Stops gap filling safely when no gap is available or the retry budget is exhausted.

Invariants preserved:
- Only one gap target is selected at a time.
- ``gap_round`` counts concrete gap-fill attempts.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.lib.maps.coverage import select_gap_target
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.select_gap_target.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    gaps = list(projection_get(projected, "state.map_gaps.gaps", []) or [])
    gap_round = int(projection_get(projected, "state.map_metrics.gap_round", 0) or 0)
    max_gap_rounds = int(projection_get(projected, "policy.map_max_gap_rounds", 6) or 6)
    value = select_gap_target(gaps=gaps, gap_round=gap_round, max_gap_rounds=max_gap_rounds)
    updates = {}
    if bool(value.get("selected", False)):
        updates["state.map_metrics.gap_round"] = gap_round + 1
    return StepOutcome(
        value=value,
        updates=updates,
        meta={"selected": bool(value.get("selected", False)), "reason": str(value.get("reason", "") or "")},
    )
