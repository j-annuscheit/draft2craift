"""Context assembly helpers for :mod:`studio.controllers.llm_tasks`."""
from __future__ import annotations


def _build_context_text_from_llm_context(
    self,
    ctx: dict,
    *,
    max_chars: int = 0,
) -> str:
    parts: list[str] = []
    try:
        char_limit = int(max_chars)
    except (TypeError, ValueError):
        char_limit = 0
    unlimited = char_limit <= 0
    total_len = 0
    truncated = False

    def add_chunk(label: str, content: str) -> bool:
        nonlocal total_len, truncated
        body = str(content or "").strip()
        if not body:
            return True
        header = f"## {label}\n"
        footer = "\n\n"
        if unlimited:
            chunk = f"{header}{body}{footer}"
            parts.append(chunk)
            total_len += len(chunk)
            return True
        room = char_limit - total_len - len(header) - len(footer)
        if room <= 0:
            truncated = True
            return False
        if len(body) > room:
            suffix = "\n\n[... gekürzt ...]"
            keep = max(0, room - len(suffix))
            body = body[:keep].rstrip()
            if keep > 0:
                body += suffix
            truncated = True
        chunk = f"{header}{body}{footer}"
        parts.append(chunk)
        total_len += len(chunk)
        return total_len < char_limit

    for name, content in list(ctx.get("file_contents", []) or []):
        if not add_chunk(f"Quelle: {name}", str(content or "")):
            break

    if unlimited or total_len < char_limit:
        for path, score, excerpt in list(ctx.get("rag_results", []) or []):
            label = str(path or "").strip() or "RAG Results"
            try:
                score_text = f"{float(score):.2f}"
            except (TypeError, ValueError):
                score_text = "?"
            if not add_chunk(
                f"RAG: {label} (score {score_text})",
                str(excerpt or ""),
            ):
                break

    if unlimited or total_len < char_limit:
        selected_text = str(ctx.get("selected_text", "") or "").strip()
        if selected_text:
            add_chunk("Ausgewählter Text (Draft)", selected_text)

    # Recovery path: selected docs checked but context payload arrived empty.
    if not parts:
        _use_canvas, _use_rag, doc_selection = self._chat_dock.get_context_selection()
        for name, _content in list(doc_selection or []):
            doc_name = str(name or "").strip()
            if not doc_name:
                continue
            resolved = self._resolve_imported_doc_content(doc_name)
            if not resolved:
                continue
            if not add_chunk(f"Quelle: {doc_name}", resolved):
                break

    text = "".join(parts).strip()
    if (not unlimited) and truncated and text:
        return f"{text}\n\n[Hinweis: Kontext wurde aus Platzgründen gekürzt.]"
    return text


def _fallback_context_text_from_ctx(
    self,
    ctx: dict,
    *,
    max_chars: int = 0,
) -> str:
    out: list[str] = []
    try:
        char_limit = int(max_chars)
    except (TypeError, ValueError):
        char_limit = 0
    unlimited = char_limit <= 0
    total_len = 0
    truncated = False

    def add_raw(label: str, content: str) -> bool:
        nonlocal total_len, truncated
        body = str(content or "").strip()
        if not body:
            return True
        header = f"[{label}]\n"
        footer = "\n\n"
        if unlimited:
            block = f"{header}{body}{footer}"
            out.append(block)
            total_len += len(block)
            return True
        room = char_limit - total_len - len(header) - len(footer)
        if room <= 0:
            truncated = True
            return False
        if len(body) > room:
            suffix = "\n\n[... gekürzt ...]"
            keep = max(0, room - len(suffix))
            body = body[:keep].rstrip()
            if keep > 0:
                body += suffix
            truncated = True
        block = f"{header}{body}{footer}"
        out.append(block)
        total_len += len(block)
        return total_len < char_limit

    for item in list(ctx.get("file_contents", []) or []):
        if not isinstance(item, (tuple, list)) or len(item) < 2:
            continue
        name = str(item[0] or "").strip() or "Quelle"
        body = str(item[1] or "")
        if not body.strip():
            body = self._resolve_imported_doc_content(name)
        if not add_raw(f"Quelle: {name}", body):
            break

    if unlimited or total_len < char_limit:
        for item in list(ctx.get("rag_results", []) or []):
            if not isinstance(item, (tuple, list)) or len(item) < 3:
                continue
            path = str(item[0] or "").strip() or "RAG Results"
            excerpt = str(item[2] or "")
            if not add_raw(f"RAG: {path}", excerpt):
                break

    if unlimited or total_len < char_limit:
        selected = str(ctx.get("selected_text", "") or "")
        if selected.strip():
            add_raw("Ausgewählter Text (Draft)", selected)

    text = "".join(out).strip()
    if (not unlimited) and truncated and text:
        return f"{text}\n\n[Hinweis: Kontext wurde aus Platzgründen gekürzt.]"
    return text


def _empty_context_error(self, ctx: dict) -> tuple[bool, str]:
    selected_text_len = len(str(ctx.get("selected_text", "") or "").strip())
    file_count = len(list(ctx.get("file_contents", []) or []))
    rag_count = len(list(ctx.get("rag_results", []) or []))
    file_lens = [
        (
            str(item[0] if isinstance(item, (tuple, list)) and item else ""),
            len(
                str(
                    item[1]
                    if isinstance(item, (tuple, list)) and len(item) > 1
                    else ""
                ).strip()
            ),
        )
        for item in list(ctx.get("file_contents", []) or [])[:6]
    ]
    _use_canvas, _use_rag, doc_selection = self._chat_dock.get_context_selection()
    selected_doc_names = [
        str(name or "").strip()
        for name, _ in list(doc_selection or [])
        if str(name or "").strip()
    ]
    return (
        False,
        "Kein verwertbarer Kontext ausgewählt.\n"
        f"(ctx: files={file_count}, rag={rag_count}, selected_text_len={selected_text_len}; "
        f"selected_docs={selected_doc_names[:6]}; file_lens={file_lens})",
    )


def _resolve_mindmap_mode_and_query(
    query_raw: str,
    *,
    mode_hint: str = "auto",
) -> tuple[str, str]:
    query = str(query_raw or "").strip()
    forced_mode = str(mode_hint or "").strip().casefold()
    mode = "mindmap"
    if forced_mode in {"mindmap", "graph", "chunkmap", "chunk"}:
        mode = "chunkmap" if forced_mode in {"chunkmap", "chunk"} else forced_mode
        low = query.casefold()
        if low.startswith("graph:") or low.startswith("wissensgraph:"):
            query = query.split(":", 1)[1].strip()
        elif low.startswith("mindmap:") or low.startswith("map:"):
            query = query.split(":", 1)[1].strip()
        elif low.startswith("chunkmap:") or low.startswith("chunk:"):
            query = query.split(":", 1)[1].strip()
    else:
        low = query.casefold()
        if low.startswith("graph:"):
            mode = "graph"
            query = query.split(":", 1)[1].strip()
        elif low.startswith("wissensgraph:"):
            mode = "graph"
            query = query.split(":", 1)[1].strip()
        elif low.startswith("mindmap:") or low.startswith("map:"):
            mode = "mindmap"
            query = query.split(":", 1)[1].strip()
        elif low.startswith("chunkmap:") or low.startswith("chunk:"):
            mode = "chunkmap"
            query = query.split(":", 1)[1].strip()
        elif "wissensgraph" in low:
            mode = "graph"
    if not query:
        if mode == "graph":
            query = (
                "Welche zentralen Entitäten und Beziehungen sind im Kontext belegt?"
            )
        elif mode == "chunkmap":
            query = (
                "Wie ist der Kontext nach Überschriften und Chunks strukturiert?"
            )
        else:
            query = (
                "Welche zentralen Konzepte beantworten die Fragestellung im Kontext?"
            )
    return mode, query
