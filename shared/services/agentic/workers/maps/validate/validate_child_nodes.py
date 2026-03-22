"""Worker: ``map.validate_child_nodes.v1``.

Purpose:
- Validate proposed child nodes against evidence, parent fit and duplicate rules.

Expected input:
- ``state.map_candidate.children``
- ``state.map_candidate.reason``
- ``state.map_frontier``
- ``state.map_evidence``
- ``state.map_result.markdown``
- ``state.map_source.normalized_text``
- ``policy.map_node_min_word_letters``
- ``policy.map_llm_child_limit``

Output value:
- validation payload with accepted and rejected children

Meta:
- ``accepted_count``
- ``rejected_count``

Tool usage:
- none

Failure behavior:
- Non-parseable or empty child proposals become ``ok = false``.

Invariants preserved:
- No accepted child duplicates an existing direct sibling.
- No accepted child can equal the parent label.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.lib.maps.grounding import validate_child_candidates
from shared.services.agentic.lib.maps.parsing import parse_map_markdown
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.validate_child_nodes.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    reason = str(projection_get(projected, "state.map_candidate.reason", "") or "").strip()
    children = list(projection_get(projected, "state.map_candidate.children", []) or [])
    frontier = dict(projection_get(projected, "state.map_frontier", {}) or {})
    evidence = dict(projection_get(projected, "state.map_evidence", {}) or {})
    markdown = str(projection_get(projected, "state.map_result.markdown", "") or "")
    source_text = str(projection_get(projected, "state.map_source.normalized_text", "") or "")
    min_letters = int(projection_get(projected, "policy.map_node_min_word_letters", 3) or 3)
    max_children = int(projection_get(projected, "policy.map_llm_child_limit", 4) or 4)
    if reason in {"llm_error", "empty_response", "invalid_response_format"} and not children:
        value = {"ok": False, "accepted_children": [], "rejected_children": [], "reason": reason}
        return StepOutcome(value=value, meta={"accepted_count": 0, "rejected_count": 0})
    existing_labels: list[str] = []
    spec = parse_map_markdown(markdown)
    node_id = str(frontier.get("node_id", "") or "")
    if spec is not None and node_id in dict(spec.nodes or {}):
        parent = dict(spec.nodes or {}).get(node_id)
        for child_id in list(getattr(parent, "children", []) or []):
            node = dict(spec.nodes or {}).get(str(child_id or ""))
            label = str(getattr(node, "label", "") or "").strip()
            if label:
                existing_labels.append(label)
    value = validate_child_candidates(
        children=children,
        parent_label=str(frontier.get("label", "") or ""),
        existing_labels=existing_labels,
        evidence_snippets=list(evidence.get("snippets", []) or []),
        source_text=source_text,
        min_word_letters=min_letters,
        max_children=max_children,
    )
    return StepOutcome(
        value=value,
        meta={
            "accepted_count": len(list(value.get("accepted_children", []) or [])),
            "rejected_count": len(list(value.get("rejected_children", []) or [])),
        },
    )
