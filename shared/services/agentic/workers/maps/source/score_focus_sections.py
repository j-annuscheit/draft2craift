"""Worker: ``map.score_focus_sections.v1``.

Purpose:
- Score which outline sections and text segments are most relevant for the user query.

Expected input:
- ``state.map_request.focus``
- ``state.map_segments.segments``
- ``state.map_outline``

Output value:
- focus payload containing query terms and top section / segment IDs

Meta:
- ``top_section_count``
- ``top_segment_count``

Tool usage:
- none

Failure behavior:
- Returns an empty focus selection when no sections or segments are available.

Invariants preserved:
- Section and segment references stay within the known IDs.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.lib.maps.source import score_focus_sections
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.score_focus_sections.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    query = str(projection_get(projected, "state.map_request.focus", "") or "")
    segments = list(projection_get(projected, "state.map_segments.segments", []) or [])
    outline = dict(projection_get(projected, "state.map_outline", {}) or {})
    value = score_focus_sections(query=query, segments=segments, outline=outline)
    return StepOutcome(
        value=value,
        meta={
            "top_section_count": len(list(value.get("top_sections", []) or [])),
            "top_segment_count": len(list(value.get("top_segments", []) or [])),
        },
    )
