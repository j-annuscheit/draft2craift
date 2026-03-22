"""Worker: ``map.parse_seed_enrichment.v1``.

Purpose:
- Parse the seed-enrichment proposal into a normalized node list.

Expected input:
- ``state.map_seed_enrichment.raw_text``
- ``state.map_seed_enrichment.reason``
- ``state.map_focus.top_segments``
- ``policy.map_node_min_word_letters``
- ``policy.map_seed_enrichment_limit``

Output value:
- ``{"nodes": [...], "reason": ...}``

Meta:
- ``node_count``

Tool usage:
- none

Failure behavior:
- Preserves upstream reasons for empty or failed LLM responses.

Invariants preserved:
- Node labels are normalized before validation.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.lib.maps.parsing import parse_node_suggestions
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.parse_seed_enrichment.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    raw_text = str(projection_get(projected, "state.map_seed_enrichment.raw_text", "") or "")
    upstream_reason = str(projection_get(projected, "state.map_seed_enrichment.reason", "") or "").strip()
    segment_ids = set(
        str(item or "")
        for item in list(projection_get(projected, "state.map_focus.top_segments", []) or [])
        if str(item or "")
    )
    min_letters = int(projection_get(projected, "policy.map_node_min_word_letters", 3) or 3)
    limit = int(projection_get(projected, "policy.map_seed_enrichment_limit", 3) or 3)
    parsed = parse_node_suggestions(
        raw_text,
        valid_segment_ids=segment_ids,
        min_word_letters=min_letters,
        max_nodes=limit,
        top_keys=("nodes", "children", "items"),
        relaxed=True,
    )
    reason = str(parsed.get("reason", upstream_reason or "invalid_response_format") or "invalid_response_format")
    if not raw_text.strip() and upstream_reason:
        reason = upstream_reason
    value = {"raw_text": raw_text, "nodes": list(parsed.get("nodes", []) or []), "reason": reason}
    return StepOutcome(value=value, meta={"node_count": len(list(value.get("nodes", []) or []))})
