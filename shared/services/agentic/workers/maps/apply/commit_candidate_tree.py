"""Worker: ``map.commit_candidate_tree.v1``.

Purpose:
- Commit or discard the staged map candidate after candidate-tree validation.

Expected input:
- ``state.map_validation``
- ``state._candidates.map_result_candidate``
- ``state.map_metrics``
- ``state.map_candidate.intent``

Output value:
- ``{"committed": bool, "reason": ..., "intent": ...}``

Meta:
- ``committed``

Tool usage:
- none

Failure behavior:
- Missing candidates are treated as discarded.

Invariants preserved:
- Only validated candidates can replace the accepted map.
- The candidate intent is preserved for later workflow decisions.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.commit_candidate_tree.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    validation = dict(projection_get(projected, "state.map_validation", {}) or {})
    candidate = dict(projection_get(projected, "state._candidates.map_result_candidate", {}) or {})
    metrics = dict(projection_get(projected, "state.map_metrics", {}) or {})
    intent = str(projection_get(projected, "state.map_candidate.intent", "") or "expansion")
    committed_count = int(metrics.get("candidate_commits", 0) or 0)
    discarded_count = int(metrics.get("candidate_discards", 0) or 0)
    if not candidate:
        return StepOutcome(
            value={"committed": False, "reason": "missing_candidate", "intent": intent},
            updates={"state.map_metrics.candidate_discards": discarded_count + 1},
            meta={"committed": False},
        )
    if bool(validation.get("ok", False)):
        return StepOutcome(
            value={"committed": True, "reason": "candidate_valid", "intent": intent},
            updates={"state.map_metrics.candidate_commits": committed_count + 1},
            commit_candidates=("map_result_candidate",),
            meta={"committed": True},
        )
    return StepOutcome(
        value={"committed": False, "reason": str(validation.get("reason", "candidate_invalid") or "candidate_invalid"), "intent": intent},
        updates={"state.map_metrics.candidate_discards": discarded_count + 1},
        discard_candidates=("map_result_candidate",),
        meta={"committed": False},
    )
