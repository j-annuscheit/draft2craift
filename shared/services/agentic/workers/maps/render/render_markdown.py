"""Worker: ``map.render_markdown.v1``.

Purpose:
- Re-render the current accepted map into canonical markdown.

Expected input:
- ``state.map_result.markdown``

Output value:
- canonical map payload

Meta:
- ``rendered``

Tool usage:
- none

Failure behavior:
- Leaves the current markdown unchanged when parsing fails.

Invariants preserved:
- Output markdown is always canonical for the current map structure.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.lib.maps.parsing import parse_map_markdown
from shared.services.agentic.lib.maps.rendering import render_markdown
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.render_markdown.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    payload = dict(projection_get(projected, "state.map_result", {}) or {})
    markdown = str(payload.get("markdown", "") or "")
    spec = parse_map_markdown(markdown)
    if spec is None:
        return StepOutcome(value=payload, meta={"rendered": False})
    value = dict(payload)
    value["markdown"] = render_markdown(spec)
    value["reason"] = "rendered"
    return StepOutcome(value=value, meta={"rendered": True})
