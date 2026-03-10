"""Feedback event formatting helpers for UI rendering."""
from __future__ import annotations

from typing import Any

from testcase_studio.draft_builder import event_payload
from testcase_studio.text_utils import safe_str, truncate


def format_feedback_fields(event: dict[str, Any]) -> str:
    payload = event_payload(event)
    lines: list[str] = []

    def add(label: str, value: Any) -> None:
        text = safe_str(value)
        if text:
            lines.append(f"{label}: {text}")

    add("event_id", event.get("event_id"))
    add("use_case", event.get("use_case"))
    add("sentiment", event.get("sentiment"))
    add("source", event.get("source"))
    add("user_id", event.get("user_id"))
    add("note", event.get("note"))

    tags = event.get("error_tags")
    if isinstance(tags, list) and tags:
        add("error_tags", ", ".join(str(item) for item in tags if str(item).strip()))

    add("model", payload.get("model"))
    llm_runtime = payload.get("llm_runtime")
    if isinstance(llm_runtime, dict):
        add("llm.model_path", llm_runtime.get("model_path"))
        add("llm.ctx_size", llm_runtime.get("ctx_size"))
        add("llm.gpu_layers", llm_runtime.get("gpu_layers"))

    rag = payload.get("rag_search")
    if isinstance(rag, dict):
        add("rag.query", rag.get("query"))
        add("rag.result_count", rag.get("result_count"))
        results = rag.get("results")
        if isinstance(results, list):
            names: list[str] = []
            for item in results[:5]:
                if isinstance(item, dict):
                    name = safe_str(item.get("name") or item.get("path"))
                    if name:
                        names.append(name)
            if names:
                add("rag.top_results", " | ".join(names))

    add("file_path", payload.get("file_path"))
    add("file_type", payload.get("file_type"))

    canvas = payload.get("canvas")
    if isinstance(canvas, dict):
        add("canvas.tab_title", canvas.get("tab_title"))
        selected = safe_str(canvas.get("selected_text"))
        if selected:
            add("canvas.selected_text", truncate(selected, 140))

    input_ctx = payload.get("input_context")
    if isinstance(input_ctx, dict):
        files = input_ctx.get("selected_file_names")
        if isinstance(files, list) and files:
            add("input.files", ", ".join(str(item) for item in files if str(item).strip()))
        rag_results = input_ctx.get("rag_results")
        if isinstance(rag_results, list):
            add("input.rag_results", len(rag_results))
        file_contents = input_ctx.get("file_contents")
        if isinstance(file_contents, list):
            add("input.file_contents", len(file_contents))

    add("last_user_message", truncate(safe_str(payload.get("last_user_message")), 180))
    add(
        "last_assistant_message",
        truncate(safe_str(payload.get("last_assistant_message")), 180),
    )

    return "\n".join(lines) if lines else "(keine strukturierten Felder erkannt)"
