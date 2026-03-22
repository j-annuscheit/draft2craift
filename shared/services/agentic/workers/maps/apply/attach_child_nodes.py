"""Worker: ``map.attach_child_nodes.v1``.

Purpose:
- Attach validated child nodes to the selected parent and stage the result as a candidate.

Expected input:
- ``state.map_result.markdown``
- ``state.map_frontier.node_id``
- ``state.map_validation.accepted_children``
- ``state.map_result.root_label``

Output value:
- candidate summary with ``attached_count`` and ``reason``

Meta:
- ``attached_count``

Tool usage:
- none

Failure behavior:
- Missing parents or empty accepted children yield no staged candidate.

Invariants preserved:
- The accepted map is not overwritten directly.
- New nodes are only attached below the selected parent.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.lib.maps.parsing import parse_map_markdown
from shared.services.agentic.lib.maps.rendering import render_markdown
from shared.services.agentic.lib.maps.tree_ops import attach_children_to_parent
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.attach_child_nodes.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    markdown = str(projection_get(projected, "state.map_result.markdown", "") or "")
    parent_id = str(projection_get(projected, "state.map_frontier.node_id", "") or "")
    accepted_children = list(projection_get(projected, "state.map_validation.accepted_children", []) or [])
    root_label = str(projection_get(projected, "state.map_result.root_label", "") or "Mindmap")
    if not parent_id or not accepted_children:
        return StepOutcome(value={"attached_count": 0, "reason": "no_accepted_children", "intent": "expansion"}, meta={"attached_count": 0})
    spec = parse_map_markdown(markdown)
    if spec is None:
        return StepOutcome(value={"attached_count": 0, "reason": "empty_map", "intent": "expansion"}, meta={"attached_count": 0})
    candidate_spec = attach_children_to_parent(spec, parent_id=parent_id, children=accepted_children)
    candidate_markdown = render_markdown(candidate_spec)
    staged_value = {
        "markdown": candidate_markdown,
        "mode": "mindmap",
        "root_label": root_label,
        "reason": "attached_children",
    }
    return StepOutcome(
        value={"attached_count": len(accepted_children), "reason": "candidate_staged", "intent": "expansion"},
        candidate_writes={"map_result_candidate": {"write_to": "state.map_result", "value": staged_value}},
        meta={"attached_count": len(accepted_children)},
    )
