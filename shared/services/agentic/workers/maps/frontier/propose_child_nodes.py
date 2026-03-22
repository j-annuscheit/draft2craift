"""Worker: ``map.propose_child_nodes.v1``.

Purpose:
- Ask the LLM for a very small set of direct child nodes for one existing parent.

Expected input:
- ``state.map_frontier``
- ``state.map_evidence``
- ``state.map_candidate_hints``
- ``state.map_request.focus``
- ``state.map_result.markdown``
- ``state.map_source.normalized_text``
- ``policy.map_llm_child_limit``

Output value:
- ``{"raw_text": ..., "reason": ..., "intent": "expansion"}``

Meta:
- ``prompt_chars``
- ``snippet_count``
- ``context_chars``

Tool usage:
- ``llm.generate``

Failure behavior:
- LLM failures become ``reason = llm_error``.
- Empty replies become ``reason = empty_response``.

Invariants preserved:
- The worker only asks for direct children of the currently selected parent.
- The worker never asks the LLM to rewrite the full map.
- The full normalized source context is always part of the prompt.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from shared.services.agentic.projection import projection_get

WORKER_ID = "map.propose_child_nodes.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = step
    frontier = dict(projection_get(projected, "state.map_frontier", {}) or {})
    evidence = dict(projection_get(projected, "state.map_evidence", {}) or {})
    hints = dict(projection_get(projected, "state.map_candidate_hints", {}) or {})
    query = str(projection_get(projected, "state.map_request.focus", "") or "")
    markdown = str(projection_get(projected, "state.map_result.markdown", "") or "")
    source_text = str(projection_get(projected, "state.map_source.normalized_text", "") or "")
    child_limit = max(1, min(6, int(projection_get(projected, "policy.map_llm_child_limit", 4) or 4)))
    parent_label = str(frontier.get("label", "") or "").strip()
    snippets = [str(item or "") for item in list(evidence.get("snippets", []) or []) if str(item or "").strip()][:5]
    candidate_terms = [
        str(item.get("label", "") or "").strip()
        for item in list(hints.get("candidate_terms", []) or [])
        if str(item.get("label", "") or "").strip()
    ]
    prompt = (
        "Du erweiterst eine bestehende Mindmap.\n"
        "WICHTIG:\n"
        "- Erzeuge nur DIREKTE Kinder fuer genau EINEN vorhandenen Parent.\n"
        "- Keine neue Gesamt-Mindmap.\n"
        "- Keine Erklaerungen ausserhalb des JSON.\n"
        "- Nutze nur Begriffe, die durch die Evidenz oder den Gesamtkontext belegt sind.\n"
        f"- Maximal {child_limit} Kinder.\n\n"
        f"Fokus: {query}\n"
        f"Parent: {parent_label}\n"
        f"Hinweise: {', '.join(candidate_terms[:8])}\n\n"
        "Aktuelle Mindmap:\n"
        f"{markdown}\n\n"
        "Lokale Evidenz:\n"
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
            value={"raw_text": "", "reason": "llm_error", "error": str(exc), "intent": "expansion"},
            meta={"prompt_chars": len(prompt), "snippet_count": len(snippets), "context_chars": len(source_text)},
        )
    reason = "ok" if str(raw_text or "").strip() else "empty_response"
    return StepOutcome(
        value={"raw_text": raw_text, "reason": reason, "intent": "expansion"},
        meta={"prompt_chars": len(prompt), "snippet_count": len(snippets), "context_chars": len(source_text)},
    )
