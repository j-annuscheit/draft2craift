"""Worker: ``map.update_coverage.v1``.

Purpose:
- Update covered segment IDs and loop counters after a candidate decision.

Expected input:
- ``state.map_coverage``
- ``state.map_evidence.segment_ids``
- ``state.map_gap.segment_ids``
- ``state.map_candidate.committed``
- ``state.map_candidate.intent``
- ``state.map_metrics.expansion_round``
- ``state.map_segments.segment_count``

Output value:
- updated coverage payload

Meta:
- ``coverage_ratio``
- ``intent``

Tool usage:
- none

Failure behavior:
- Keeps the previous coverage when nothing was committed.

Invariants preserved:
- Covered segment IDs stay unique.
- Expansion and gap loops stay separately observable.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.lib.maps.coverage import update_coverage
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.update_coverage.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    coverage = dict(projection_get(projected, "state.map_coverage", {}) or {})
    expansion_segment_ids = list(projection_get(projected, "state.map_evidence.segment_ids", []) or [])
    gap_segment_ids = list(projection_get(projected, "state.map_gap.segment_ids", []) or [])
    committed = bool(projection_get(projected, "state.map_candidate.committed", False))
    intent = str(projection_get(projected, "state.map_candidate.intent", "") or "expansion")
    expansion_round = int(projection_get(projected, "state.map_metrics.expansion_round", 0) or 0)
    total_segments = int(projection_get(projected, "state.map_segments.segment_count", 0) or 0)
    chosen_segment_ids = gap_segment_ids if intent == "gap_fill" else expansion_segment_ids
    value = update_coverage(
        coverage=coverage,
        evidence_segment_ids=chosen_segment_ids,
        committed=committed,
        total_segments=total_segments,
    )
    updates = {}
    if committed and intent == "expansion":
        updates["state.map_metrics.expansion_round"] = expansion_round + 1
    return StepOutcome(
        value=value,
        updates=updates,
        meta={"coverage_ratio": float(value.get("coverage_ratio", 0.0) or 0.0), "intent": intent},
    )
