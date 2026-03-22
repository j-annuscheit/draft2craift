"""Worker: ``map.attach_gap_fill.v1``.

Purpose:
- Attach validated gap-fill nodes below the selected anchor parent and stage the result as a candidate.

Expected input:
- ``state.map_result.markdown``
- ``state.map_gap.parent_id``
- ``state.map_validation.accepted_nodes``
- ``state.map_result.root_label``

Output value:
- candidate summary with ``attached_count`` and ``reason``

Meta:
- ``attached_count``

Tool usage:
- none

Failure behavior:
- Missing parents or empty accepted nodes yield no staged candidate.

Invariants preserved:
- The accepted map is not overwritten directly.
- New nodes are only attached below the selected gap anchor.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.lib.maps.parsing import parse_map_markdown
from shared.services.agentic.lib.maps.rendering import render_markdown
from shared.services.agentic.lib.maps.tree_ops import attach_children_to_parent
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.attach_gap_fill.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    markdown = str(projection_get(projected, "state.map_result.markdown", "") or "")
    parent_id = str(projection_get(projected, "state.map_gap.parent_id", "") or "")
    accepted_nodes = list(projection_get(projected, "state.map_validation.accepted_nodes", []) or [])
    root_label = str(projection_get(projected, "state.map_result.root_label", "") or "Mindmap")
    if not parent_id or not accepted_nodes:
        return StepOutcome(value={"attached_count": 0, "reason": "no_accepted_gap_nodes", "intent": "gap_fill"}, meta={"attached_count": 0})
    spec = parse_map_markdown(markdown)
    if spec is None:
        return StepOutcome(value={"attached_count": 0, "reason": "empty_map", "intent": "gap_fill"}, meta={"attached_count": 0})
    candidate_spec = attach_children_to_parent(spec, parent_id=parent_id, children=accepted_nodes)
    candidate_markdown = render_markdown(candidate_spec)
    staged_value = {
        "markdown": candidate_markdown,
        "mode": "mindmap",
        "root_label": root_label,
        "reason": "attached_gap_fill",
    }
    return StepOutcome(
        value={"attached_count": len(accepted_nodes), "reason": "candidate_staged", "intent": "gap_fill"},
        candidate_writes={"map_result_candidate": {"write_to": "state.map_result", "value": staged_value}},
        meta={"attached_count": len(accepted_nodes)},
    )
