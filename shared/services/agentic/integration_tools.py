"""Helper adapters to connect existing services with agentic tools."""
from __future__ import annotations

import re
from typing import Any


_TOKEN_RE = re.compile(r"\w+", flags=re.UNICODE)
_SPLIT_RE = re.compile(r"\n{2,}|(?<=[.!?])\s+")


def _default_llm_generate(llm_manager: Any, prompt: str) -> str:
    worker = getattr(llm_manager, "worker", None)
    if worker is None:
        return ""
    prompt_text = str(prompt or "")
    count_tokens = getattr(worker, "count_tokens", None)
    context_window = getattr(worker, "context_window", None)
    if callable(count_tokens) and callable(context_window):
        try:
            prompt_tokens = max(0, int(count_tokens(prompt_text) or 0))
            context_limit = max(256, int(context_window(4096) or 4096))
            reserved_output_tokens = 544
            if (prompt_tokens + reserved_output_tokens) > context_limit:
                raise RuntimeError(
                    "Prompt exceeds model context window without truncation "
                    f"({prompt_tokens} prompt tokens + {reserved_output_tokens} reserve > {context_limit})."
                )
        except RuntimeError:
            raise
        except Exception:
            pass
    return str(
        worker.run_completion_sync(
            prompt_text,
            max_tokens=512,
            temperature=0.2,
            top_p=0.9,
            repeat_penalty=1.05,
            stop=["<|"],
            forbidden_chars=(),
        )
        or ""
    )


def _iter_sources(raw_sources: Any) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for item in list(raw_sources or []):
        name = ""
        text = ""
        if isinstance(item, dict):
            name = str(item.get("name", "") or item.get("source", "") or item.get("path", "")).strip()
            text = str(item.get("content", "") or item.get("text", "") or item.get("excerpt", "")).strip()
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            name = str(item[0] or "").strip()
            text = str(item[1] or "").strip()
        if name and text:
            out.append((name, text))
    return out


def _token_set(text: str) -> set[str]:
    return {
        tok
        for tok in _TOKEN_RE.findall(str(text or "").casefold())
        if len(tok) >= 3
    }


def _split_candidates(text: str) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    items = [part.strip() for part in _SPLIT_RE.split(raw) if part.strip()]
    if not items:
        return [raw]
    return items


def _source_search(
    *,
    query: str,
    mode: str,
    regex_patterns: list[str],
    sources: list[tuple[str, str]],
    top_k: int,
) -> list[str]:
    query_tokens = _token_set(query)
    compiled_patterns: list[re.Pattern[str]] = []
    for pattern in list(regex_patterns or []):
        text = str(pattern or "").strip()
        if not text:
            continue
        try:
            compiled_patterns.append(re.compile(text, flags=re.IGNORECASE))
        except re.error:
            continue

    scored: list[tuple[float, str]] = []
    regex_only = str(mode or "").strip().casefold() == "regex"
    for source_name, content in sources:
        for chunk in _split_candidates(content):
            best_score = 0.0
            if compiled_patterns:
                if any(p.search(chunk) for p in compiled_patterns):
                    best_score = max(best_score, 1.0)
            if not regex_only and query_tokens:
                overlap = len(query_tokens & _token_set(chunk))
                if overlap > 0:
                    lexical = overlap / max(1, len(query_tokens))
                    best_score = max(best_score, lexical)
            if best_score <= 0.0:
                continue
            scored.append((best_score, f"{source_name}: {chunk}"))

    scored.sort(key=lambda row: row[0], reverse=True)
    out: list[str] = []
    seen: set[str] = set()
    for _score, item in scored:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
        if len(out) >= max(1, int(top_k or 8)):
            break
    return out


def _normalize_rag_hit(hit: Any) -> str:
    if isinstance(hit, dict):
        source = str(
            hit.get("source", "")
            or hit.get("path", "")
            or hit.get("name", "")
            or hit.get("doc_name", "")
        ).strip()
        text = str(
            hit.get("excerpt", "")
            or hit.get("text", "")
            or hit.get("content", "")
            or hit.get("chunk_text", "")
        ).strip()
        if source and text:
            return f"{source}: {text}"
        if text:
            return text
        return str(hit)
    if isinstance(hit, (list, tuple)):
        if len(hit) >= 3:
            source = str(hit[0] or "").strip()
            text = str(hit[2] or "").strip()
            if source and text:
                return f"{source}: {text}"
            return text or source
        if len(hit) >= 2:
            source = str(hit[0] or "").strip()
            text = str(hit[1] or "").strip()
            if source and text:
                return f"{source}: {text}"
            return text or source
    return str(hit or "")


def build_tools(
    *,
    llm_manager: Any | None = None,
    rag_system: Any | None = None,
    source_texts: Any | None = None,
    canvas_apply=None,
    canvas_open_text=None,
) -> dict[str, Any]:
    tools: dict[str, Any] = {}

    if llm_manager is not None:
        tools["llm.generate"] = lambda prompt, **_kwargs: _default_llm_generate(
            llm_manager, str(prompt or "")
        )
        verify = getattr(llm_manager, "verify_nli_sync", None)
        if callable(verify):
            tools["nli.verify"] = lambda premise, hypothesis, **_kwargs: verify(
                str(premise or ""),
                str(hypothesis or ""),
            )

    if rag_system is not None or source_texts is not None:
        search = getattr(rag_system, "search", None) if rag_system is not None else None
        static_sources = _iter_sources(source_texts)

        def _rag_search(query: str, **kwargs):
            q = str(query or "")
            top_k = int(kwargs.get("top_k", 8) or 8)
            mode = str(kwargs.get("mode", "hybrid") or "hybrid").strip().casefold()
            regex_patterns = [str(x or "") for x in list(kwargs.get("regex_patterns", []) or [])]
            dynamic_sources = _iter_sources(kwargs.get("possible_sources", []))
            merged_sources = dynamic_sources or static_sources
            out: list[str] = []
            if merged_sources:
                out.extend(
                    _source_search(
                        query=q,
                        mode=mode,
                        regex_patterns=regex_patterns,
                        sources=merged_sources,
                        top_k=top_k,
                    )
                )
            if mode != "regex" and callable(search):
                try:
                    rag_hits = search(q, top_k=top_k)
                except TypeError:
                    rag_hits = search(q)
                except Exception:
                    rag_hits = []
                for hit in list(rag_hits or []):
                    item = _normalize_rag_hit(hit).strip()
                    if not item:
                        continue
                    out.append(item)
                    if len(out) >= top_k:
                        break
            dedup: list[str] = []
            seen: set[str] = set()
            for item in out:
                if item in seen:
                    continue
                seen.add(item)
                dedup.append(item)
                if len(dedup) >= top_k:
                    break
            return dedup

        tools["rag.search"] = _rag_search

    if callable(canvas_apply):
        tools["canvas.apply"] = lambda text, **_kwargs: canvas_apply(str(text or ""))

    if callable(canvas_open_text):
        tools["canvas.open_text"] = lambda text, title="Mindmap", **_kwargs: canvas_open_text(
            str(title or "Mindmap"),
            str(text or ""),
        )

    return tools
