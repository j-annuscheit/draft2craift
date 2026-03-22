"""Worker: ``map.parse_child_nodes.v1``.

Purpose:
- Parse the raw LLM child proposal into a normalized internal child list.

Expected input:
- ``state.map_candidate.raw_text``
- ``state.map_candidate.reason``
- ``state.map_evidence.segment_ids``
- ``policy.map_node_min_word_letters``
- ``policy.map_llm_child_limit``

Output value:
- child-candidate payload with normalized ``children`` and ``reason``

Meta:
- ``child_count``

Tool usage:
- none

Failure behavior:
- Preserves upstream ``llm_error`` / ``empty_response`` reasons when no raw text exists.

Invariants preserved:
- Evidence segment IDs are filtered to the current evidence window.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.lib.maps.parsing import parse_child_suggestions
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.parse_child_nodes.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    raw_text = str(projection_get(projected, "state.map_candidate.raw_text", "") or "")
    upstream_reason = str(projection_get(projected, "state.map_candidate.reason", "") or "").strip()
    segment_ids = set(str(item or "") for item in list(projection_get(projected, "state.map_evidence.segment_ids", []) or []) if str(item or ""))
    min_letters = int(projection_get(projected, "policy.map_node_min_word_letters", 3) or 3)
    max_children = int(projection_get(projected, "policy.map_llm_child_limit", 4) or 4)
    parsed = parse_child_suggestions(
        raw_text,
        valid_segment_ids=segment_ids,
        min_word_letters=min_letters,
        max_children=max_children,
    )
    value = {
        "raw_text": raw_text,
        "children": list(parsed.get("children", []) or []),
        "reason": str(parsed.get("reason", upstream_reason or "invalid_response_format") or "invalid_response_format"),
    }
    if not raw_text.strip() and upstream_reason:
        value["reason"] = upstream_reason
    return StepOutcome(value=value, meta={"child_count": len(list(value.get("children", []) or []))})
