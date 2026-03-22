"""Worker: ``map.choose_root_label.v1``.

Purpose:
- Choose a deterministic root label from request focus and document title.

Expected input:
- ``state.map_request``
- ``state.map_outline.title``

Output value:
- ``{"root_id": "root", "root_label": ...}``

Meta:
- ``root_label``

Tool usage:
- none

Failure behavior:
- Falls back to ``Mindmap``.

Invariants preserved:
- The root label is always a short word-like label.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.lib.maps.labels import choose_root_label
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.choose_root_label.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    query = str(projection_get(projected, "state.map_request.focus", "") or "")
    title = str(projection_get(projected, "state.map_outline.title", "") or "")
    root_label = choose_root_label(query=query, title=title)
    return StepOutcome(value={"root_id": "root", "root_label": root_label}, meta={"root_label": root_label})
