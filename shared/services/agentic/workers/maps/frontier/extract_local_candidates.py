"""Worker: ``map.extract_local_candidates.v1``.

Purpose:
- Extract deterministic child-label hints from local evidence snippets.

Expected input:
- ``state.map_result.markdown``
- ``state.map_frontier.node_id``
- ``state.map_evidence``
- ``policy.map_local_candidate_limit``

Output value:
- ``{"candidate_terms": [...]}``

Meta:
- ``candidate_count``

Tool usage:
- none

Failure behavior:
- Returns an empty candidate list when no suitable terms are found.

Invariants preserved:
- Candidate labels exclude existing direct children of the current parent.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.lib.maps.coverage import extract_local_candidates
from shared.services.agentic.lib.maps.parsing import parse_map_markdown
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.extract_local_candidates.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    markdown = str(projection_get(projected, "state.map_result.markdown", "") or "")
    parent_id = str(projection_get(projected, "state.map_frontier.node_id", "") or "")
    evidence = dict(projection_get(projected, "state.map_evidence", {}) or {})
    limit = int(projection_get(projected, "policy.map_local_candidate_limit", 8) or 8)
    spec = parse_map_markdown(markdown)
    existing_labels: list[str] = []
    if spec is not None and parent_id in dict(spec.nodes or {}):
        parent = dict(spec.nodes or {}).get(parent_id)
        for child_id in list(getattr(parent, "children", []) or []):
            node = dict(spec.nodes or {}).get(str(child_id or ""))
            label = str(getattr(node, "label", "") or "").strip()
            if label:
                existing_labels.append(label)
    value = extract_local_candidates(
        snippets=list(evidence.get("snippets", []) or []),
        parent_label=str(evidence.get("parent_label", "") or ""),
        existing_labels=existing_labels,
        limit=limit,
    )
    return StepOutcome(value=value, meta={"candidate_count": len(list(value.get("candidate_terms", []) or []))})
