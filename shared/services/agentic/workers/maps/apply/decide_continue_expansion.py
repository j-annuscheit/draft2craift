"""Worker: ``map.decide_continue_expansion.v1``.

Purpose:
- Decide whether another frontier-expansion round should run.

Expected input:
- ``state.map_result.markdown``
- ``state.map_request.target_depth``
- ``state.map_metrics.expansion_round``
- ``policy.map_max_expansion_rounds``

Output value:
- ``{"continue_flag": bool, "reason": ...}``

Meta:
- ``continue``
- ``current_depth``

Tool usage:
- none

Failure behavior:
- Stops safely when the current map cannot be parsed.

Invariants preserved:
- Expansion stops when the requested target depth is already reached.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.lib.maps.coverage import node_depths
from shared.services.agentic.lib.maps.parsing import parse_map_markdown
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.decide_continue_expansion.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    markdown = str(projection_get(projected, "state.map_result.markdown", "") or "")
    target_depth = int(projection_get(projected, "state.map_request.target_depth", 4) or 4)
    expansion_round = int(projection_get(projected, "state.map_metrics.expansion_round", 0) or 0)
    max_rounds = int(projection_get(projected, "policy.map_max_expansion_rounds", max(4, target_depth * 3)) or max(4, target_depth * 3))
    spec = parse_map_markdown(markdown)
    if spec is None:
        return StepOutcome(value={"continue_flag": False, "reason": "empty_map"}, meta={"continue": False, "current_depth": 0})
    depths = node_depths(spec)
    current_depth = max(depths.values()) if depths else 0
    if current_depth >= target_depth:
        return StepOutcome(value={"continue_flag": False, "reason": "target_depth_reached"}, meta={"continue": False, "current_depth": current_depth})
    if expansion_round >= max_rounds:
        return StepOutcome(value={"continue_flag": False, "reason": "max_expansion_rounds_reached"}, meta={"continue": False, "current_depth": current_depth})
    return StepOutcome(value={"continue_flag": True, "reason": "continue_expansion"}, meta={"continue": True, "current_depth": current_depth})
