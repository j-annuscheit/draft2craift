"""Worker: ``map.validate_seed_enrichment.v1``.

Purpose:
- Validate top-level seed-enrichment nodes against the current seed tree and source context.

Expected input:
- ``state.map_seed_enrichment.nodes``
- ``state.map_seed_enrichment.reason``
- ``state.map_result.markdown``
- ``state.map_seed.root_label``
- ``state.map_segments.segments``
- ``state.map_focus.top_segments``
- ``state.map_source.normalized_text``
- ``policy.map_node_min_word_letters``
- ``policy.map_seed_enrichment_limit``

Output value:
- validation payload with ``accepted_nodes`` and ``rejected_nodes``

Meta:
- ``accepted_count``
- ``rejected_count``

Tool usage:
- none

Failure behavior:
- Empty or invalid proposals become ``ok = false`` without breaking the workflow.

Invariants preserved:
- Accepted seed nodes must be grounded and must not duplicate existing root children.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.lib.maps.grounding import validate_node_candidates
from shared.services.agentic.lib.maps.parsing import parse_map_markdown
from shared.services.agentic.lib.maps.tree_ops import child_labels, root_node_id
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.validate_seed_enrichment.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    reason = str(projection_get(projected, "state.map_seed_enrichment.reason", "") or "").strip()
    nodes = list(projection_get(projected, "state.map_seed_enrichment.nodes", []) or [])
    markdown = str(projection_get(projected, "state.map_result.markdown", "") or "")
    root_label = str(projection_get(projected, "state.map_seed.root_label", "") or "Mindmap")
    segments = {
        str(row.get("segment_id", "") or ""): str(row.get("text", "") or "")
        for row in list(projection_get(projected, "state.map_segments.segments", []) or [])
        if str(row.get("segment_id", "") or "")
    }
    top_segment_ids = [
        str(item or "")
        for item in list(projection_get(projected, "state.map_focus.top_segments", []) or [])
        if str(item or "")
    ]
    source_text = str(projection_get(projected, "state.map_source.normalized_text", "") or "")
    min_letters = int(projection_get(projected, "policy.map_node_min_word_letters", 3) or 3)
    limit = int(projection_get(projected, "policy.map_seed_enrichment_limit", 3) or 3)
    if reason in {"llm_error", "empty_response", "invalid_response_format", "seed_enrichment_disabled", "no_seed_concepts"} and not nodes:
        value = {"ok": False, "accepted_nodes": [], "rejected_nodes": [], "reason": reason or "no_seed_enrichment"}
        return StepOutcome(value=value, meta={"accepted_count": 0, "rejected_count": 0})
    spec = parse_map_markdown(markdown)
    existing_labels = child_labels(spec, parent_id=root_node_id(spec)) if spec is not None else []
    evidence_snippets = [segments.get(seg_id, "") for seg_id in top_segment_ids if segments.get(seg_id, "")]
    result = validate_node_candidates(
        nodes=nodes,
        parent_label=root_label,
        existing_labels=existing_labels,
        evidence_snippets=evidence_snippets,
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
