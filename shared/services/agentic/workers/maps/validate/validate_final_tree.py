"""Worker: ``map.validate_final_tree.v1``.

Purpose:
- Run the final structural validation for the current accepted mindmap.

Expected input:
- ``state.map_result.markdown``
- ``state.map_result.root_label``
- policy keys for map validation

Output value:
- final validation payload with stats and cleanup info

Meta:
- ``ok``
- ``nodes``
- ``edges``

Tool usage:
- none

Failure behavior:
- Invalid final maps produce ``ok = false`` and a structured reason.

Invariants preserved:
- The validated final markdown is normalized before emission.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.lib.maps.parsing import parse_map_markdown
from shared.services.agentic.lib.maps.tree_ops import sanitize_and_validate_spec
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.validate_final_tree.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    markdown = str(projection_get(projected, "state.map_result.markdown", "") or "")
    root_label = str(projection_get(projected, "state.map_result.root_label", "") or projection_get(projected, "state.map_request.topic", "") or "Mindmap")
    policy = dict(ctx.policy or {})
    spec = parse_map_markdown(markdown)
    if spec is None:
        value = {"ok": False, "reason": "final_parse_failed", "issues": [], "stats": {}}
        return StepOutcome(value=value, meta={"ok": False, "nodes": 0, "edges": 0})
    normalized_spec, payload = sanitize_and_validate_spec(spec, policy=policy, root_label=root_label, merge_similar_nodes=True)
    normalized_markdown = str(payload.get("normalized_markdown", markdown) or markdown)
    stats = dict(payload.get("stats", {}) or {})
    return StepOutcome(
        value=payload,
        updates={"state.map_result.markdown": normalized_markdown, "state.map_result.stats": stats},
        meta={"ok": bool(payload.get("ok", False)), "nodes": int(stats.get("nodes", 0) or 0), "edges": int(stats.get("edges", 0) or 0)},
    )
