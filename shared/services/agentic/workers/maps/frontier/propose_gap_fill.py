"""Worker: ``map.propose_gap_fill.v1``.

Purpose:
- Ask the LLM for a very small set of child nodes that close one uncovered content gap.

Expected input:
- ``state.map_gap``
- ``state.map_request.focus``
- ``state.map_result.markdown``
- ``state.map_source.normalized_text``
- ``policy.map_gap_fill_enabled``
- ``policy.map_gap_limit``

Output value:
- ``{"raw_text": ..., "reason": ..., "intent": "gap_fill"}``

Meta:
- ``prompt_chars``
- ``snippet_count``

Tool usage:
- ``llm.generate``

Failure behavior:
- Disabled runs, empty gaps or tool failures produce safe non-fatal reasons.

Invariants preserved:
- The worker only proposes direct children for the selected gap parent.
- It never rewrites the complete mindmap.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.propose_gap_fill.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = ctx, step
    enabled = bool(projection_get(projected, "policy.map_gap_fill_enabled", True))
    gap = dict(projection_get(projected, "state.map_gap", {}) or {})
    focus = str(projection_get(projected, "state.map_request.focus", "") or "")
    markdown = str(projection_get(projected, "state.map_result.markdown", "") or "")
    source_text = str(projection_get(projected, "state.map_source.normalized_text", "") or "")
    limit = max(1, min(6, int(projection_get(projected, "policy.map_gap_limit", 4) or 4)))
    parent_label = str(gap.get("parent_label", "") or "").strip()
    gap_label = str(gap.get("gap_label", "") or "").strip()
    snippets = [str(item or "") for item in list(gap.get("snippets", []) or []) if str(item or "").strip()][:4]
    if not enabled:
        return StepOutcome(value={"raw_text": "", "reason": "gap_fill_disabled", "intent": "gap_fill"}, meta={"prompt_chars": 0, "snippet_count": len(snippets)})
    if not parent_label or not snippets:
        return StepOutcome(value={"raw_text": "", "reason": "no_gap_target", "intent": "gap_fill"}, meta={"prompt_chars": 0, "snippet_count": len(snippets)})
    prompt = (
        "Du schliesst eine konkrete Inhaltsluecke in einer bestehenden Mindmap.\n"
        "WICHTIG:\n"
        "- Erzeuge nur DIREKTE Kinder fuer genau EINEN vorhandenen Parent.\n"
        "- Schlage nur wenige Knoten vor, die die konkrete Luecke abdecken.\n"
        "- Keine neue Gesamt-Mindmap.\n"
        "- Keine Erklaerungen ausserhalb des JSON.\n"
        f"- Maximal {limit} Kinder.\n\n"
        f"Fokus: {focus}\n"
        f"Luecke: {gap_label}\n"
        f"Parent: {parent_label}\n\n"
        "Aktuelle Mindmap:\n"
        f"{markdown}\n\n"
        "Belegsegmente fuer die Luecke:\n"
        + "\n\n".join(f"[{idx + 1}] {snippet}" for idx, snippet in enumerate(snippets))
        + "\n\nGesamtkontext:\n"
        + source_text
        + "\n\nAntworte NUR als JSON in diesem Format:\n"
        '{"children":[{"label":"...","evidence_segment_ids":[]}]}\n'
    )
    try:
        raw_text = str(ctx.tools.call("llm.generate", prompt=prompt) or "")
    except Exception as exc:
        return StepOutcome(
            value={"raw_text": "", "reason": "llm_error", "error": str(exc), "intent": "gap_fill"},
            meta={"prompt_chars": len(prompt), "snippet_count": len(snippets)},
        )
    reason = "ok" if raw_text.strip() else "empty_response"
    return StepOutcome(
        value={"raw_text": raw_text, "reason": reason, "intent": "gap_fill"},
        meta={"prompt_chars": len(prompt), "snippet_count": len(snippets)},
    )
