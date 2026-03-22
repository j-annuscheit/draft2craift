"""Worker: ``map.normalize_context.v1``.

Purpose:
- Normalize the collected source text before any segmentation or outline parsing.

Expected input:
- ``state.map_source.context_text``

Output value:
- normalized source payload containing raw + normalized text and cleanup stats

Meta:
- cleanup counters

Tool usage:
- none

Failure behavior:
- Falls back to an empty normalized payload.

Invariants preserved:
- The raw original context text remains available in the output bucket.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.lib.maps.source import normalize_context
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.normalize_context.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    context_text = str(projection_get(projected, "state.map_source.context_text", "") or "")
    value = normalize_context(context_text)
    return StepOutcome(value=value, meta=dict(value.get("cleanup", {}) or {}))
