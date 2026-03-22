"""Worker: ``map.extract_seed_concepts.v1``.

Purpose:
- Extract deterministic seed concepts from the most relevant focus segments.

Expected input:
- ``state.map_segments.segments``
- ``state.map_focus.top_segments``
- ``policy.map_seed_concept_limit``

Output value:
- ``{"concepts": [...], "reason": ...}``

Meta:
- ``concept_count``

Tool usage:
- none

Failure behavior:
- Returns an empty concept list when no relevant terms can be extracted.

Invariants preserved:
- Concepts are short, word-like labels.
- Concepts do not depend on LLM output.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.lib.maps.coverage import extract_seed_concepts
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.extract_seed_concepts.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    segments = list(projection_get(projected, "state.map_segments.segments", []) or [])
    top_segment_ids = list(projection_get(projected, "state.map_focus.top_segments", []) or [])
    limit = max(1, min(24, int(projection_get(projected, "policy.map_seed_concept_limit", 12) or 12)))
    value = extract_seed_concepts(segments=segments, top_segment_ids=top_segment_ids, limit=limit)
    return StepOutcome(value=value, meta={"concept_count": len(list(value.get("concepts", []) or []))})
