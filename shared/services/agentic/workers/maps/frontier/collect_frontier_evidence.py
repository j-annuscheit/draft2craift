"""Worker: ``map.collect_frontier_evidence.v1``.

Purpose:
- Collect the best local evidence snippets for the currently selected frontier node.

Expected input:
- ``state.map_frontier``
- ``state.map_segments.segments``
- ``state.map_focus.top_segments``
- ``state.map_request.focus``
- ``policy.map_frontier_evidence_limit``

Output value:
- evidence payload containing selected segment IDs and snippets

Meta:
- ``snippet_count``

Tool usage:
- none

Failure behavior:
- Returns an empty evidence payload when no relevant segment can be found.

Invariants preserved:
- Evidence references only known segment IDs.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.lib.maps.coverage import collect_frontier_evidence
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.collect_frontier_evidence.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    frontier = dict(projection_get(projected, "state.map_frontier", {}) or {})
    segments = list(projection_get(projected, "state.map_segments.segments", []) or [])
    preferred = list(projection_get(projected, "state.map_focus.top_segments", []) or [])
    query = str(projection_get(projected, "state.map_request.focus", "") or "")
    limit = int(projection_get(projected, "policy.map_frontier_evidence_limit", 5) or 5)
    value = collect_frontier_evidence(
        frontier_label=str(frontier.get("label", "") or ""),
        query=query,
        segments=segments,
        preferred_segment_ids=preferred,
        limit=limit,
    )
    value["parent_label"] = str(frontier.get("label", "") or "")
    return StepOutcome(value=value, meta={"snippet_count": len(list(value.get("snippets", []) or []))})
