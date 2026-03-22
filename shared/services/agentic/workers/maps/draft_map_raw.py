"""Worker: ``mindmap.draft_map_raw.v1``.

Purpose:
- Build the initial LLM prompt for a map draft and capture the raw model output.
- This worker is intentionally narrow: it does not parse, repair or ground the
  response. Those responsibilities live in later workers.

Expected input:
- ``state.map_context.context_text``
- ``state.map_focus.mode``
- ``state.map_focus.query``
- optional retry information from ``state.structure_check`` or
  ``state.map_validation``

Output value:
- ``{"raw_markdown": ..., "mode": ..., "reason": ...}``

Meta:
- ``context_chars``
- ``prompt_chars``

Tool usage:
- ``llm.generate``

Failure behavior:
- LLM exceptions are converted into ``reason = llm_error``.
- Empty LLM output becomes ``reason = empty_response``.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from . import _support

WORKER_ID = "mindmap.draft_map_raw.v1"


def _previous_reason(ctx) -> tuple[bool, str]:  # noqa: ANN001
    structure_check = dict(ctx.state.get("structure_check", {}) or {})
    if structure_check:
        return bool(structure_check.get("parse_failed", False)), str(structure_check.get("reason", "") or "").strip()
    validation = dict(ctx.state.get("map_validation", {}) or {})
    reason = str(validation.get("reason", "") or "").strip()
    parse_failed = reason in {"empty", "grounding_insufficient", "meta_labels_detected"}
    return parse_failed, reason


def run(ctx, step, projected):  # noqa: ANN001
    _ = step, projected
    context_text = str((ctx.state.get("map_context", {}) or {}).get("context_text", "") or "")
    focus = dict(ctx.state.get("map_focus", {}) or {})
    mode = str(focus.get("mode", "mindmap") or "mindmap").strip().casefold()
    tag = _support._mode_tag(mode)
    prev_parse_failed, prev_reason = _previous_reason(ctx)

    retry_hint = (
        f"HINWEIS: Der vorherige Versuch hat KEINEN gültigen ```{tag}``` Block geliefert. "
        f"Antworte diesmal ZWINGEND mit genau einem ```{tag} ... ``` Block.\n\n"
        if prev_parse_failed else ""
    )
    if prev_reason in {"grounding_insufficient", "meta_labels_detected"}:
        retry_hint += (
            "HINWEIS: Der vorherige Versuch war INHALTLICH NICHT ausreichend im Kontext belegt.\n"
            "Nutze NUR Begriffe, Aussagen und Beziehungen, die im Dokument selbst vorkommen.\n"
            "Keine allgemein thematisch passenden, aber unbelegten Konzepte.\n\n"
        )
    prompt = (
        retry_hint
        + f"Erzeuge eine strukturierte {mode}-Ausgabe aus dem folgenden Kontext.\n\n"
        "STRENGE GROUNDING-REGELN — diese sind absolut verbindlich:\n"
        f"- Antworte NUR mit einem einzigen ```{tag} ... ``` Block, ohne jede weitere Erklärung.\n"
        "- VERBOTEN: Allgemeines Weltwissen, Wikipedia-Fakten, Schulbuchinhalte, "
        "Begriffe die NICHT im Kontext stehen.\n"
        "- ERLAUBT: Ausschließlich Begriffe, Konzepte, Ergebnisse und Beziehungen die "
        "WORTWÖRTLICH oder SINNGEMÄSS im Kontext belegt sind.\n"
        "- Wenn der Kontext nichts über ein Konzept sagt → gehört es NICHT in die Mindmap.\n"
        "- Die Mindmap muss das TATSÄCHLICHE Dokument widerspiegeln, nicht das Thema im Allgemeinen.\n\n"
        + _support._prompt_section("Fokus", focus.get("query", ""))
        + _support._prompt_section("Kontext", context_text)
    ).rstrip()
    try:
        raw_markdown = str(ctx.tools.call("llm.generate", prompt=prompt) or "")
    except Exception as exc:
        return StepOutcome(
            value={"raw_markdown": "", "mode": mode, "reason": "llm_error", "error": str(exc)},
            meta={"context_chars": len(context_text), "prompt_chars": len(prompt)},
        )

    reason = "ok" if str(raw_markdown or "").strip() else "empty_response"
    return StepOutcome(
        value={"raw_markdown": str(raw_markdown or ""), "mode": mode, "reason": reason},
        meta={"context_chars": len(context_text), "prompt_chars": len(prompt)},
    )
