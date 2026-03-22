"""Worker: ``mindmap.ground_map_draft.v1``.

Purpose:
- Apply deterministic context-grounding checks to a normalized draft.
- Mindmap / chunkmap drafts are rejected early when the draft is not grounded
  enough in the source text. Graph drafts keep their markdown but still receive
  grounding metadata for later validation.

Expected input:
- ``state.map_draft``
- ``state.map_context.context_text``
- ``state.map_focus.query``
- grounding-related ``policy.*`` keys

Output value:
- updated ``map_draft`` payload including ``grounding`` metadata.
"""
from __future__ import annotations

from typing import Any

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.graph_grounding import evaluate_graph_grounding
from . import _support

WORKER_ID = "mindmap.ground_map_draft.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = step, projected
    draft = dict(ctx.state.get("map_draft", {}) or {})
    markdown = str(draft.get("markdown", "") or "")
    mode = str(draft.get("mode") or (ctx.state.get("map_focus", {}) or {}).get("mode") or "mindmap").strip().casefold()
    if not markdown.strip():
        return StepOutcome(value=draft)

    spec = _support._extract_spec_best_effort(markdown, mode=mode)
    grounding: dict[str, Any] = {}
    if spec is not None:
        grounding = evaluate_graph_grounding(
            spec=spec,
            mode=mode,
            context_text=str((ctx.state.get("map_context", {}) or {}).get("context_text", "") or ""),
            query=str((ctx.state.get("map_focus", {}) or {}).get("query", "") or ""),
            policy=dict(ctx.policy or {}),
        )
    value = dict(draft)
    if grounding:
        value["grounding"] = grounding
    if (
        grounding
        and str(mode or "").strip().casefold() in {"mindmap", "chunkmap"}
        and bool(grounding.get("enabled", False))
        and not bool(grounding.get("ok", True))
    ):
        value["markdown"] = ""
        value["reason"] = str(grounding.get("reason", "grounding_insufficient") or "grounding_insufficient")
    return StepOutcome(value=value)
