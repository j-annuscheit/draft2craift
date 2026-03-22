"""Worker: ``map.segment_context.v1``.

Purpose:
- Split normalized source text into stable segments with synthetic segment IDs.

Expected input:
- ``state.map_source.normalized_text``

Output value:
- ``{"segments": [...], "segment_count": int}``

Meta:
- ``segment_count``

Tool usage:
- none

Failure behavior:
- Returns an empty segment list when the normalized source is empty.

Invariants preserved:
- Segment IDs stay stable for a given source ordering.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.lib.maps.source import segment_context
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.segment_context.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    normalized_text = str(projection_get(projected, "state.map_source.normalized_text", "") or "")
    value = segment_context(normalized_text)
    return StepOutcome(
        value=value,
        updates={"state.map_coverage.total_segments": int(value.get("segment_count", 0) or 0)},
        meta={"segment_count": int(value.get("segment_count", 0) or 0)},
    )
