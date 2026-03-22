"""Worker: ``map.select_frontier_node.v1``.

Purpose:
- Choose exactly one existing node as the next expansion frontier.

Expected input:
- ``state.map_result.markdown``
- ``state.map_request.focus``
- ``state.map_request.target_depth``
- ``state.map_metrics.frontier_visits``
- ``policy.map_max_frontier_visits_per_node``
- ``policy.map_max_children_per_node``

Output value:
- frontier selection payload with ``selected``, ``node_id``, ``label`` and ``depth``

Meta:
- ``selected``
- ``reason``

Tool usage:
- none

Failure behavior:
- Returns ``selected = false`` when no suitable frontier node exists.

Invariants preserved:
- Only existing nodes can be selected.
- Visit counters are incremented only for an actually selected node.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.lib.maps.coverage import select_frontier_node
from shared.services.agentic.lib.maps.parsing import parse_map_markdown
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.select_frontier_node.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    markdown = str(projection_get(projected, "state.map_result.markdown", "") or "")
    query = str(projection_get(projected, "state.map_request.focus", "") or "")
    target_depth = int(projection_get(projected, "state.map_request.target_depth", 4) or 4)
    visits = dict(projection_get(projected, "state.map_metrics.frontier_visits", {}) or {})
    max_visits = int(projection_get(projected, "policy.map_max_frontier_visits_per_node", 2) or 2)
    max_children = int(projection_get(projected, "policy.map_max_children_per_node", 5) or 5)
    spec = parse_map_markdown(markdown)
    if spec is None:
        return StepOutcome(value={"selected": False, "reason": "empty_map"}, meta={"selected": False})
    value = select_frontier_node(
        spec=spec,
        query=query,
        target_depth=target_depth,
        frontier_visits=visits,
        max_frontier_visits_per_node=max_visits,
        max_children_per_node=max_children,
    )
    updates = {}
    node_id = str(value.get("node_id", "") or "")
    if bool(value.get("selected", False)) and node_id:
        current = int(visits.get(node_id, 0) or 0)
        updates[f"state.map_metrics.frontier_visits.{node_id}"] = current + 1
    return StepOutcome(value=value, updates=updates, meta={"selected": bool(value.get("selected", False)), "reason": str(value.get("reason", "") or "")})
