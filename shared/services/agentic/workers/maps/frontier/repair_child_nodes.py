"""Worker: ``map.repair_child_nodes.v1``.

Purpose:
- Retry parsing of a child-node proposal with relaxed deterministic heuristics.
- This is a pure repair step for format problems, not a semantic rewrite.

Expected input:
- ``state.map_candidate.raw_text``
- ``state.map_candidate.reason``
- ``state.map_evidence.segment_ids``
- ``policy.map_node_min_word_letters``
- ``policy.map_llm_child_limit``

Output value:
- child-candidate payload with repaired ``children`` and ``reason``

Meta:
- ``repaired_count``
- ``repaired``

Tool usage:
- none

Failure behavior:
- If no repair is possible, the original failure reason is preserved.

Invariants preserved:
- Repair only changes formatting / parsing interpretation.
- Candidate semantics are not expanded beyond the original raw response.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.lib.maps.parsing import parse_child_suggestions
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.repair_child_nodes.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    raw_text = str(projection_get(projected, "state.map_candidate.raw_text", "") or "")
    upstream_reason = str(projection_get(projected, "state.map_candidate.reason", "") or "").strip()
    current_children = list(projection_get(projected, "state.map_candidate.children", []) or [])
    segment_ids = {
        str(item or "")
        for item in list(projection_get(projected, "state.map_evidence.segment_ids", []) or [])
        if str(item or "")
    }
    min_letters = int(projection_get(projected, "policy.map_node_min_word_letters", 3) or 3)
    max_children = int(projection_get(projected, "policy.map_llm_child_limit", 4) or 4)

    if current_children:
        return StepOutcome(
            value={"raw_text": raw_text, "children": current_children, "reason": upstream_reason or "ok"},
            meta={"repaired_count": len(current_children), "repaired": False},
        )
    if upstream_reason != "invalid_response_format" or not raw_text.strip():
        return StepOutcome(
            value={"raw_text": raw_text, "children": [], "reason": upstream_reason or "invalid_response_format"},
            meta={"repaired_count": 0, "repaired": False},
        )

    parsed = parse_child_suggestions(
        raw_text,
        valid_segment_ids=segment_ids,
        min_word_letters=min_letters,
        max_children=max_children,
        relaxed=True,
    )
    children = list(parsed.get("children", []) or [])
    repaired = bool(children)
    reason = "repair_applied" if repaired else str(parsed.get("reason", upstream_reason) or upstream_reason or "invalid_response_format")
    return StepOutcome(
        value={"raw_text": raw_text, "children": children, "reason": reason},
        meta={"repaired_count": len(children), "repaired": repaired},
    )
