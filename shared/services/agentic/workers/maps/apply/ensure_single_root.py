"""Worker: ``map.ensure_single_root.v1``.

Purpose:
- Ensure that the accepted map exposes exactly one root node.

Expected input:
- ``state.map_result.markdown``
- ``state.map_result.root_label``

Output value:
- corrected map payload

Meta:
- ``root_enforced``

Tool usage:
- none

Failure behavior:
- Leaves the current map unchanged when parsing fails.

Invariants preserved:
- The output root label remains stable.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.lib.maps.parsing import parse_map_markdown
from shared.services.agentic.lib.maps.rendering import render_markdown
from shared.services.agentic.lib.maps.tree_ops import ensure_single_root
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.ensure_single_root.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    markdown = str(projection_get(projected, "state.map_result.markdown", "") or "")
    root_label = str(projection_get(projected, "state.map_result.root_label", "") or "Mindmap")
    spec = parse_map_markdown(markdown)
    if spec is None:
        return StepOutcome(value={"markdown": markdown, "reason": "parse_failed"}, meta={"root_enforced": False})
    fixed = ensure_single_root(spec, root_label=root_label)
    return StepOutcome(value={"markdown": render_markdown(fixed), "mode": "mindmap", "root_label": root_label, "reason": "single_root"}, meta={"root_enforced": True})
