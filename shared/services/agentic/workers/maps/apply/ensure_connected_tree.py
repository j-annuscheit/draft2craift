"""Worker: ``map.ensure_connected_tree.v1``.

Purpose:
- Ensure that the accepted map contains one connected tree before emission.

Expected input:
- ``state.map_result.markdown``
- ``state.map_result.root_label``

Output value:
- connected map payload

Meta:
- ``connected``

Tool usage:
- none

Failure behavior:
- Leaves the current map unchanged when parsing fails.

Invariants preserved:
- Any detached nodes are reattached below the existing root.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.lib.maps.parsing import parse_map_markdown
from shared.services.agentic.lib.maps.rendering import render_markdown
from shared.services.agentic.lib.maps.tree_ops import ensure_connected_tree
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.ensure_connected_tree.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    markdown = str(projection_get(projected, "state.map_result.markdown", "") or "")
    root_label = str(projection_get(projected, "state.map_result.root_label", "") or "Mindmap")
    spec = parse_map_markdown(markdown)
    if spec is None:
        return StepOutcome(value={"markdown": markdown, "reason": "parse_failed"}, meta={"connected": False})
    fixed = ensure_connected_tree(spec, root_label=root_label)
    return StepOutcome(value={"markdown": render_markdown(fixed), "mode": "mindmap", "root_label": root_label, "reason": "connected_tree"}, meta={"connected": True})
