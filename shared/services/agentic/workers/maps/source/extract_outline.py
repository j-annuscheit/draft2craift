"""Worker: ``map.extract_outline.v1``.

Purpose:
- Derive a deterministic document outline from normalized text and segments.

Expected input:
- ``state.map_source.normalized_text``
- ``state.map_segments.segments``

Output value:
- ``{"title": ..., "sections": [...]}``

Meta:
- ``section_count``

Tool usage:
- none

Failure behavior:
- Falls back to outline sections derived from the first segments.

Invariants preserved:
- The outline is always a plain serializable object.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.lib.maps.source import extract_outline
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.extract_outline.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    normalized_text = str(projection_get(projected, "state.map_source.normalized_text", "") or "")
    segments = list(projection_get(projected, "state.map_segments.segments", []) or [])
    value = extract_outline(normalized_text=normalized_text, segments=segments)
    return StepOutcome(value=value, meta={"section_count": len(list(value.get("sections", []) or []))})
