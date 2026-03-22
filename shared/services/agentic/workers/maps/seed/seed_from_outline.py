"""Worker: ``map.seed_from_outline.v1``.

Purpose:
- Build the initial accepted mindmap from the deterministic outline.

Expected input:
- ``state.map_seed.root_label``
- ``state.map_outline``
- ``state.map_focus``

Output value:
- accepted map payload with canonical markdown and seed statistics

Meta:
- ``nodes``
- ``edges``

Tool usage:
- none

Failure behavior:
- Falls back to a root-only map when the outline is sparse.

Invariants preserved:
- The emitted seed is always parseable as a mindmap block.
- The seed never depends on LLM output.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.lib.maps.rendering import render_markdown
from shared.services.agentic.lib.maps.tree_ops import build_seed_spec, spec_stats
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.seed_from_outline.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    root_label = str(projection_get(projected, "state.map_seed.root_label", "") or "Mindmap")
    outline = dict(projection_get(projected, "state.map_outline", {}) or {})
    focus = dict(projection_get(projected, "state.map_focus", {}) or {})
    spec = build_seed_spec(root_label=root_label, outline=outline, focus=focus)
    markdown = render_markdown(spec)
    stats = spec_stats(spec)
    value = {
        "markdown": markdown,
        "mode": "mindmap",
        "root_label": root_label,
        "version": 1,
        "stats": stats,
        "reason": "seed_from_outline",
    }
    return StepOutcome(value=value, meta={"nodes": int(stats.get("nodes", 0) or 0), "edges": int(stats.get("edges", 0) or 0)})
