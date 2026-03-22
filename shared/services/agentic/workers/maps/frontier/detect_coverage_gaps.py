"""Worker: ``map.detect_coverage_gaps.v1``.

Purpose:
- Find relevant focus segments that are still not represented by the accepted mindmap.

Expected input:
- ``state.map_result.markdown``
- ``state.map_segments.segments``
- ``state.map_focus.top_segments``
- ``state.map_coverage.covered_segment_ids``
- ``policy.map_gap_fill_enabled``
- ``policy.map_gap_limit``

Output value:
- ``{"gaps": [...], "found": bool, "reason": ...}``

Meta:
- ``gap_count``

Tool usage:
- none

Failure behavior:
- Disabled or unparsable states return ``found = false``.

Invariants preserved:
- Reported gaps only reference known segments.
- Gap detection never mutates the accepted map.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.lib.maps.coverage import detect_coverage_gaps
from shared.services.agentic.lib.maps.parsing import parse_map_markdown
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.detect_coverage_gaps.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    enabled = bool(projection_get(projected, "policy.map_gap_fill_enabled", True))
    if not enabled:
        return StepOutcome(value={"gaps": [], "found": False, "reason": "gap_fill_disabled"}, meta={"gap_count": 0})
    markdown = str(projection_get(projected, "state.map_result.markdown", "") or "")
    segments = list(projection_get(projected, "state.map_segments.segments", []) or [])
    top_segments = list(projection_get(projected, "state.map_focus.top_segments", []) or [])
    covered_segment_ids = list(projection_get(projected, "state.map_coverage.covered_segment_ids", []) or [])
    max_gaps = int(projection_get(projected, "policy.map_gap_limit", 4) or 4)
    spec = parse_map_markdown(markdown)
    if spec is None:
        return StepOutcome(value={"gaps": [], "found": False, "reason": "empty_map"}, meta={"gap_count": 0})
    value = detect_coverage_gaps(
        spec=spec,
        segments=segments,
        top_segment_ids=top_segments,
        covered_segment_ids=covered_segment_ids,
        max_gaps=max_gaps,
    )
    return StepOutcome(value=value, meta={"gap_count": len(list(value.get("gaps", []) or []))})
