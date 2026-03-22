"""Worker: ``map.validate_gap_fill.v1``.

Purpose:
- Validate gap-fill child candidates against the selected parent and source evidence.

Expected input:
- ``state.map_candidate.children``
- ``state.map_candidate.reason``
- ``state.map_gap``
- ``state.map_result.markdown``
- ``state.map_source.normalized_text``
- ``policy.map_node_min_word_letters``
- ``policy.map_gap_limit``

Output value:
- validation payload with ``accepted_nodes`` and ``rejected_nodes``

Meta:
- ``accepted_count``
- ``rejected_count``

Tool usage:
- none

Failure behavior:
- Empty or invalid proposals become ``ok = false``.

Invariants preserved:
- Accepted nodes must be grounded in the selected gap evidence or global source text.
- Accepted nodes must not duplicate existing siblings.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.lib.maps.grounding import validate_node_candidates
from shared.services.agentic.lib.maps.parsing import parse_map_markdown
from shared.services.agentic.lib.maps.tree_ops import child_labels
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.validate_gap_fill.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    reason = str(projection_get(projected, "state.map_candidate.reason", "") or "").strip()
    nodes = list(projection_get(projected, "state.map_candidate.children", []) or [])
    gap = dict(projection_get(projected, "state.map_gap", {}) or {})
    markdown = str(projection_get(projected, "state.map_result.markdown", "") or "")
    source_text = str(projection_get(projected, "state.map_source.normalized_text", "") or "")
    min_letters = int(projection_get(projected, "policy.map_node_min_word_letters", 3) or 3)
    limit = int(projection_get(projected, "policy.map_gap_limit", 4) or 4)
    if reason in {"llm_error", "empty_response", "invalid_response_format", "gap_fill_disabled", "no_gap_target"} and not nodes:
        value = {"ok": False, "accepted_nodes": [], "rejected_nodes": [], "reason": reason or "no_gap_fill"}
        return StepOutcome(value=value, meta={"accepted_count": 0, "rejected_count": 0})
    spec = parse_map_markdown(markdown)
    parent_id = str(gap.get("parent_id", "") or "")
    existing_labels = child_labels(spec, parent_id=parent_id) if spec is not None and parent_id else []
    result = validate_node_candidates(
        nodes=nodes,
        parent_label=str(gap.get("parent_label", "") or ""),
        existing_labels=existing_labels,
        evidence_snippets=[str(item or "") for item in list(gap.get("snippets", []) or []) if str(item or "").strip()],
        source_text=source_text,
        min_word_letters=min_letters,
        max_nodes=limit,
    )
    value = {
        "ok": bool(result.get("ok", False)),
        "accepted_nodes": list(result.get("accepted_nodes", []) or []),
        "rejected_nodes": list(result.get("rejected_nodes", []) or []),
        "reason": str(result.get("reason", "no_grounded_nodes") or "no_grounded_nodes"),
    }
    return StepOutcome(value=value, meta={"accepted_count": len(value["accepted_nodes"]), "rejected_count": len(value["rejected_nodes"])})
