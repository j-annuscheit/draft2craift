"""Worker: ``map.propose_seed_enrichment.v1``.

Purpose:
- Ask the LLM for a very small set of missing top-level nodes for the seed tree.

Expected input:
- ``state.map_seed.root_label``
- ``state.map_result.markdown``
- ``state.map_seed_concepts.concepts``
- ``state.map_segments.segments``
- ``state.map_focus.top_segments``
- ``state.map_request.focus``
- ``state.map_source.normalized_text``
- ``policy.map_seed_enrichment_enabled``
- ``policy.map_seed_enrichment_limit``

Output value:
- ``{"raw_text": ..., "reason": ...}``

Meta:
- ``prompt_chars``
- ``snippet_count``

Tool usage:
- ``llm.generate``

Failure behavior:
- Disabled runs, missing concepts or LLM failures produce a safe non-fatal reason.

Invariants preserved:
- The worker only proposes a few root-level additions.
- It never asks for a complete new mindmap.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.propose_seed_enrichment.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    enabled = bool(projection_get(projected, "policy.map_seed_enrichment_enabled", True))
    root_label = str(projection_get(projected, "state.map_seed.root_label", "") or "Mindmap")
    markdown = str(projection_get(projected, "state.map_result.markdown", "") or "")
    focus = str(projection_get(projected, "state.map_request.focus", "") or "")
    source_text = str(projection_get(projected, "state.map_source.normalized_text", "") or "")
    concepts = [
        str(item.get("label", "") or "").strip()
        for item in list(projection_get(projected, "state.map_seed_concepts.concepts", []) or [])
        if str(item.get("label", "") or "").strip()
    ]
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
    limit = max(1, min(6, int(projection_get(projected, "policy.map_seed_enrichment_limit", 3) or 3)))
    snippets = [segments.get(seg_id, "") for seg_id in top_segment_ids[:5] if segments.get(seg_id, "")]
    if not enabled:
        return StepOutcome(value={"raw_text": "", "reason": "seed_enrichment_disabled"}, meta={"prompt_chars": 0, "snippet_count": len(snippets)})
    if not concepts and not snippets:
        return StepOutcome(value={"raw_text": "", "reason": "no_seed_concepts"}, meta={"prompt_chars": 0, "snippet_count": 0})
    prompt = (
        "Du verbesserst den Startbaum einer Mindmap.\n"
        "WICHTIG:\n"
        "- Schlage nur wenige FEHLENDE Top-Level-Knoten direkt unter der Root vor.\n"
        "- Keine komplette Mindmap.\n"
        "- Keine Erklaerungen ausserhalb des JSON.\n"
        f"- Maximal {limit} neue Knoten.\n\n"
        f"Fokus: {focus}\n"
        f"Root: {root_label}\n\n"
        "Aktueller Seed:\n"
        f"{markdown}\n\n"
        f"Kandidatenbegriffe: {', '.join(concepts[:12])}\n\n"
        "Belegsegmente:\n"
        + "\n\n".join(f"[{idx + 1}] {snippet}" for idx, snippet in enumerate(snippets))
        + "\n\nGesamtkontext:\n"
        + source_text
        + "\n\nAntworte NUR als JSON in diesem Format:\n"
        '{"nodes":[{"label":"...","evidence_segment_ids":[]}]}\n'
    )
    try:
        raw_text = str(ctx.tools.call("llm.generate", prompt=prompt) or "")
    except Exception as exc:
        return StepOutcome(
            value={"raw_text": "", "reason": "llm_error", "error": str(exc)},
            meta={"prompt_chars": len(prompt), "snippet_count": len(snippets)},
        )
    reason = "ok" if str(raw_text or "").strip() else "empty_response"
    return StepOutcome(value={"raw_text": raw_text, "reason": reason}, meta={"prompt_chars": len(prompt), "snippet_count": len(snippets)})
