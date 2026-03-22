"""Worker: ``map.validate_candidate_tree.v1``.

Purpose:
- Validate the staged candidate tree before it can replace the accepted map.

Expected input:
- ``state._candidates.map_result_candidate``
- ``state.map_request.topic``
- policy keys for map validation

Output value:
- validation payload with stats, cleanup info and candidate review data

Meta:
- ``ok``
- ``nodes``
- ``edges``

Tool usage:
- none

Failure behavior:
- Missing candidates become ``ok = false`` with ``reason = missing_candidate``.

Invariants preserved:
- The staged candidate is normalized again before commit.
- Validation never mutates the accepted map directly.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.lib.maps.parsing import parse_map_markdown
from shared.services.agentic.lib.maps.tree_ops import sanitize_and_validate_spec
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.validate_candidate_tree.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    candidate = dict(projection_get(projected, "state._candidates.map_result_candidate", {}) or {})
    policy = dict(ctx.policy or {})
    root_label = str(projection_get(projected, "state.map_result.root_label", "") or projection_get(projected, "state.map_request.topic", "") or "Mindmap")
    markdown = str(candidate.get("value", {}).get("markdown", "") or "")
    if not markdown.strip():
        value = {"ok": False, "reason": "missing_candidate", "candidate_review": {"accepted": False, "reason": "missing_candidate"}}
        return StepOutcome(value=value, meta={"ok": False, "nodes": 0, "edges": 0})
    spec = parse_map_markdown(markdown)
    if spec is None:
        value = {"ok": False, "reason": "candidate_parse_failed", "candidate_review": {"accepted": False, "reason": "candidate_parse_failed"}}
        return StepOutcome(value=value, meta={"ok": False, "nodes": 0, "edges": 0})
    normalized_spec, payload = sanitize_and_validate_spec(spec, policy=policy, root_label=root_label, merge_similar_nodes=True)
    normalized_markdown = str(payload.get("normalized_markdown", markdown) or markdown)
    review = {"accepted": bool(payload.get("ok", False)), "reason": str(payload.get("reason", "") or "validation_failed")}
    candidate_writes = {
        "map_result_candidate": {
            "write_to": "state.map_result",
            "value": {
                "markdown": normalized_markdown,
                "mode": "mindmap",
                "root_label": root_label,
                "stats": dict(payload.get("stats", {}) or {}),
                "reason": "candidate_tree",
            },
            "meta": {"validated": True},
        }
    }
    value = dict(payload)
    value["candidate_review"] = review
    stats = dict(payload.get("stats", {}) or {})
    return StepOutcome(
        value=value,
        candidate_writes=candidate_writes,
        meta={"ok": bool(payload.get("ok", False)), "nodes": int(stats.get("nodes", 0) or 0), "edges": int(stats.get("edges", 0) or 0)},
    )
