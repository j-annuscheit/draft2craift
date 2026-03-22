"""Worker: ``map.normalize_labels.v1``.

Purpose:
- Apply deterministic label cleanup to the accepted map before final validation.

Expected input:
- ``state.map_result.markdown``
- ``state.map_result.root_label``
- policy keys for cleanup

Output value:
- normalized map payload

Meta:
- ``normalized``

Tool usage:
- none

Failure behavior:
- Leaves the current map unchanged when parsing fails.

Invariants preserved:
- The output remains a parseable mindmap block.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.lib.maps.parsing import parse_map_markdown
from shared.services.agentic.lib.maps.tree_ops import sanitize_and_validate_spec
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.normalize_labels.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    markdown = str(projection_get(projected, "state.map_result.markdown", "") or "")
    root_label = str(projection_get(projected, "state.map_result.root_label", "") or "Mindmap")
    spec = parse_map_markdown(markdown)
    if spec is None:
        return StepOutcome(value={"markdown": markdown, "reason": "parse_failed"}, meta={"normalized": False})
    normalized_spec, payload = sanitize_and_validate_spec(spec, policy=dict(ctx.policy or {}), root_label=root_label, merge_similar_nodes=False)
    return StepOutcome(
        value={"markdown": str(payload.get("normalized_markdown", markdown) or markdown), "mode": "mindmap", "root_label": root_label, "reason": "normalized_labels"},
        meta={"normalized": True},
    )
