"""Worker: ``mindmap.parse_map_draft.v1``.

Purpose:
- Convert the raw LLM response from ``draft_map_raw`` into normalized map
  markdown.
- Apply one optional parse-repair attempt when the raw output is structured but
  not directly parseable.

Expected input:
- ``state.map_draft_raw.raw_markdown``
- ``state.map_draft_raw.mode``
- ``state.map_context.context_text``
- ``state.map_focus.query``
- ``policy.map_parse_repair_enabled``

Output value:
- canonical ``map_draft`` payload with ``markdown``, ``mode`` and ``reason``.

Tool usage:
- optionally ``llm.generate`` for repair.
"""
from __future__ import annotations

from shared.services.agentic.contracts import StepOutcome
from . import _support

WORKER_ID = "mindmap.parse_map_draft.v1"


def run(ctx, step, projected):  # noqa: ANN001
    _ = step, projected
    raw_payload = dict(ctx.state.get("map_draft_raw", {}) or {})
    context_text = str((ctx.state.get("map_context", {}) or {}).get("context_text", "") or "")
    focus = dict(ctx.state.get("map_focus", {}) or {})
    mode = str(raw_payload.get("mode") or focus.get("mode") or "mindmap").strip().casefold()
    raw_markdown = str(raw_payload.get("raw_markdown", "") or "")
    raw_reason = str(raw_payload.get("reason", "") or "").strip()
    raw_error = str(raw_payload.get("error", "") or "").strip()

    if not raw_markdown.strip():
        value = {"markdown": "", "mode": mode, "reason": raw_reason or "empty_response"}
        if raw_error:
            value["error"] = raw_error
        return StepOutcome(value=value)

    markdown = raw_markdown
    reason = "ok"
    repair_reason = ""
    spec = _support._extract_spec_best_effort(markdown, mode=mode)
    if spec is not None:
        markdown = _support.spec_to_markdown(spec)
        if f"```{_support._mode_tag(mode)}" not in raw_markdown:
            reason = "normalized_response_format"
    else:
        repaired_spec, repair_reason = _support._repair_parse_failure_with_llm(
            ctx,
            mode=mode,
            raw_markdown=markdown,
            context_text=context_text,
            query=str(focus.get("query", "") or ""),
        )
        if repaired_spec is not None:
            markdown = _support.spec_to_markdown(repaired_spec)
            reason = str(repair_reason or "repair_applied")
        else:
            markdown = ""
            reason = "invalid_response_format"

    value = {"markdown": markdown, "mode": mode, "reason": reason}
    if repair_reason:
        value["repair_reason"] = repair_reason
    return StepOutcome(value=value)
