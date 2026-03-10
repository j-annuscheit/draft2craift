"""Feedback-to-testcase draft conversion helpers."""
from __future__ import annotations

import json
from typing import Any

from testcase_studio.text_utils import safe_str, truncate


def event_payload(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload")
    return payload if isinstance(payload, dict) else {}


def extract_prompt_from_event(event: dict[str, Any]) -> str:
    use_case = safe_str(event.get("use_case")).lower()
    payload = event_payload(event)

    if use_case == "rag_search":
        rag = payload.get("rag_search")
        if isinstance(rag, dict):
            return safe_str(rag.get("query"))

    if use_case == "canvas_edit":
        canvas = payload.get("canvas")
        if isinstance(canvas, dict):
            selected = safe_str(canvas.get("selected_text"))
            if selected:
                return selected

    user_msg = safe_str(payload.get("last_user_message"))
    if user_msg:
        return user_msg
    return safe_str(payload.get("query"))


def extract_observed_output(event: dict[str, Any]) -> str:
    payload = event_payload(event)

    assistant = safe_str(payload.get("last_assistant_message"))
    if assistant:
        return assistant

    fact = payload.get("fact_check")
    if isinstance(fact, dict):
        markdown = safe_str(fact.get("markdown"))
        if markdown:
            return markdown

    rag = payload.get("rag_search")
    if isinstance(rag, dict):
        try:
            return json.dumps(rag.get("results", []), ensure_ascii=False, indent=2)
        except Exception:
            pass
    return ""


def _extract_inline_docs(event: dict[str, Any]) -> list[dict[str, str]]:
    payload = event_payload(event)
    input_ctx = payload.get("input_context")
    if not isinstance(input_ctx, dict):
        return []
    file_contents = input_ctx.get("file_contents")
    if not isinstance(file_contents, list):
        return []

    docs: list[dict[str, str]] = []
    for item in file_contents:
        name = ""
        content = ""
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            name = safe_str(item[0])
            content = safe_str(item[1])
        elif isinstance(item, dict):
            name = safe_str(item.get("name"))
            content = safe_str(item.get("content"))
        if name and content:
            docs.append({"name": name, "content": content})
    return docs


def event_labels(event: dict[str, Any], suite_id: str) -> list[str]:
    base = [
        "feedback",
        safe_str(event.get("use_case")) or "unknown",
        safe_str(event.get("sentiment")) or "neutral",
        suite_id,
    ]
    labels: list[str] = []
    seen: set[str] = set()
    for label in base:
        key = label.casefold()
        if not label or key in seen:
            continue
        seen.add(key)
        labels.append(label)
    return labels


def build_case_draft_from_event(event: dict[str, Any], suite_id: str) -> dict[str, Any]:
    prompt = extract_prompt_from_event(event)
    observed = extract_observed_output(event)
    labels = event_labels(event, suite_id)
    payload = event_payload(event)
    use_case = safe_str(event.get("use_case")).lower()

    if suite_id == "rag":
        documents: list[Any] = _extract_inline_docs(event)
        if not documents:
            input_ctx = payload.get("input_context")
            if isinstance(input_ctx, dict):
                selected = input_ctx.get("selected_file_names")
                if isinstance(selected, list):
                    documents.extend([safe_str(item) for item in selected if safe_str(item)])
        if not documents:
            documents = ["TODO: fixtures/rag_doc_1.md"]

        include_quotes: list[str] = []
        rag = payload.get("rag_search")
        if isinstance(rag, dict):
            results = rag.get("results")
            if isinstance(results, list):
                for item in results[:3]:
                    excerpt = safe_str(item.get("excerpt") if isinstance(item, dict) else "")
                    if excerpt:
                        include_quotes.append(truncate(excerpt, 140))

        return {
            "id": "",
            "labels": labels,
            "query": prompt or "TODO: Suchanfrage",
            "documents": documents,
            "include_quotes": [text for text in include_quotes if text],
            "exclude_quotes": [],
            "top_k": 3,
        }

    if suite_id == "pdf":
        file_path = safe_str(payload.get("file_path"))
        if not file_path.lower().endswith(".pdf"):
            file_path = "TODO: fixtures/pdf_eval/input.pdf"
        return {
            "id": "",
            "labels": labels,
            "pdf": file_path,
            "expected": "TODO: fixtures/pdf_eval/expected.md",
        }

    if suite_id == "glossary":
        glossary = payload.get("glossary")
        terms: list[str] = []
        if isinstance(glossary, dict):
            entries = glossary.get("entries")
            if isinstance(entries, list):
                for entry in entries:
                    value = safe_str(entry.get("term") if isinstance(entry, dict) else entry)
                    if value:
                        terms.append(value)
        if not terms:
            terms = ["TODO Begriff"]

        markdown = safe_str(payload.get("file_path"))
        draft = {"id": "", "labels": labels, "target_terms": terms, "excluded_terms": []}
        if markdown.lower().endswith(".md"):
            draft["markdown"] = markdown
        else:
            draft["markdown_text"] = "TODO: Markdown-Inhalt direkt einfuegen"
        return draft

    if suite_id == "factcheck":
        return {
            "id": "",
            "labels": labels,
            "mode": "full",
            "target_markdown": "TODO: fixtures/factcheck_eval/target.md",
            "sources": [{"name": "source_1.md", "path": "TODO: fixtures/factcheck_eval/source_1.md"}],
            "gt_facts_markdown": "TODO: fixtures/factcheck_eval/gt_facts.md",
            "gt_verdicts_markdown": "TODO: fixtures/factcheck_eval/gt_verdicts.md",
        }

    if suite_id == "judge":
        answer_loser = observed or "TODO: beobachtete (schwaechere) Antwort"
        if use_case == "chat_answer" and not observed:
            answer_loser = "TODO: beobachtete Antwort"
        return {
            "id": "",
            "labels": labels,
            "prompt": prompt or "TODO: Prompt",
            "answer_winner": "TODO: bessere Referenzantwort",
            "answer_loser": answer_loser,
        }

    if suite_id == "llmcompare":
        return {"id": "", "labels": labels, "prompt": prompt or "TODO: Prompt"}

    return {"id": "", "labels": labels}


def manual_case_template(_suite_id: str) -> dict[str, Any]:
    return {"id": "", "labels": []}
