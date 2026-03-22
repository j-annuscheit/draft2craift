"""Worker: ``map.commit_initial_tree.v1``.

Purpose:
- Commit the deterministic seed tree plus validated seed-enrichment nodes as the first accepted map.

Expected input:
- ``state.map_result``
- ``state.map_validation.accepted_nodes``
- ``state.map_focus.top_segments``
- ``state.map_segments.segment_count``

Output value:
- accepted map payload for ``state.map_result``

Meta:
- ``nodes``
- ``edges``

Tool usage:
- none

Failure behavior:
- Falls back to the existing seed tree when no enrichment nodes are accepted.

Invariants preserved:
- The initial accepted tree remains parseable and connected.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.lib.maps.parsing import parse_map_markdown
from shared.services.agentic.lib.maps.rendering import render_markdown
from shared.services.agentic.lib.maps.tree_ops import attach_nodes_to_root, spec_stats
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.commit_initial_tree.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    current = dict(projection_get(projected, "state.map_result", {}) or {})
    markdown = str(current.get("markdown", "") or "")
    root_label = str(current.get("root_label", "") or projection_get(projected, "state.map_seed.root_label", "") or "Mindmap")
    accepted_nodes = list(projection_get(projected, "state.map_validation.accepted_nodes", []) or [])
    top_segments = [str(item or "") for item in list(projection_get(projected, "state.map_focus.top_segments", []) or []) if str(item or "")]
    segment_count = int(projection_get(projected, "state.map_segments.segment_count", 0) or 0)
    spec = parse_map_markdown(markdown)
    if spec is not None and accepted_nodes:
        spec = attach_nodes_to_root(spec, nodes=accepted_nodes)
        markdown = render_markdown(spec)
    stats = spec_stats(spec) if spec is not None else dict(current.get("stats", {}) or {})
    total_segments = max(segment_count, len(top_segments), 1)
    covered: list[str] = []
    coverage_ratio = 0.0
    value = {
        "markdown": markdown,
        "mode": "mindmap",
        "root_label": root_label,
        "version": int(current.get("version", 1) or 1) + (1 if accepted_nodes else 0),
        "stats": stats,
        "reason": "seed_committed" if accepted_nodes else str(current.get("reason", "seed_from_outline") or "seed_from_outline"),
    }
    return StepOutcome(
        value=value,
        updates={
            "state.map_coverage.covered_segment_ids": covered,
            "state.map_coverage.total_segments": total_segments,
            "state.map_coverage.coverage_ratio": coverage_ratio,
        },
        meta={"nodes": int(stats.get("nodes", 0) or 0), "edges": int(stats.get("edges", 0) or 0)},
    )
