"""Tool adapters used by LangGraph workflow nodes."""
from __future__ import annotations

import re
from typing import Any


def _default_llm_generate(llm_manager: Any, prompt: str) -> str:
    worker = getattr(llm_manager, "worker", None)
    if worker is None:
        return ""
    count_tokens = getattr(worker, "count_tokens", None)
    context_window = getattr(worker, "context_window", None)
    if callable(count_tokens) and callable(context_window):
        try:
            tokens = int(count_tokens(str(prompt or "")) or 0)
            window = int(context_window(4096) or 4096)
            budget = max(64, window - 256)
            if tokens > budget:
                raise RuntimeError(
                    "Prompt exceeds context window budget."
                )
        except RuntimeError:
            raise
        except Exception:
            pass
    return str(
        worker.run_completion_sync(
            str(prompt or ""),
            max_tokens=768,
            temperature=0.25,
            top_p=0.9,
            repeat_penalty=1.05,
            stop=["<|"],
            forbidden_chars=(),
        )
        or ""
    )


def _normalize_rag_hit(hit: Any) -> str:
    if isinstance(hit, dict):
        source = str(hit.get("name", "") or hit.get("source", "") or "RAG").strip()
        excerpt = str(hit.get("excerpt", "") or hit.get("text", "") or "").strip()
        if source and excerpt:
            return f"{source}: {excerpt}"
        return excerpt or source
    if isinstance(hit, (tuple, list)) and len(hit) >= 2:
        return f"{hit[0]}: {hit[-1]}"
    return str(hit or "")


def _search_static_sources(
    *,
    query: str,
    source_texts: list[tuple[str, str]],
    mode: str,
    regex_patterns: list[str],
    top_k: int,
) -> list[str]:
    q = str(query or "").strip()
    mode_clean = str(mode or "").strip().casefold()
    out: list[str] = []

    if mode_clean == "regex" and regex_patterns:
        compiled = []
        for pattern in list(regex_patterns or []):
            try:
                compiled.append(re.compile(str(pattern)))
            except Exception:
                continue
        if not compiled:
            return []
        for name, content in source_texts:
            text = str(content or "")
            if any(regex.search(text) for regex in compiled):
                out.append(f"{name}: {text}")
                if len(out) >= top_k:
                    break
        return out

    if not q:
        return []
    q_low = q.casefold()
    q_tokens = {
        token
        for token in re.findall(r"\w+", q_low, flags=re.UNICODE)
        if len(token) >= 3
    }
    for name, content in source_texts:
        text = str(content or "")
        text_low = text.casefold()
        if q_low in text_low:
            out.append(f"{name}: {text}")
            if len(out) >= top_k:
                break
            continue
        if q_tokens:
            text_tokens = {
                token
                for token in re.findall(r"\w+", text_low, flags=re.UNICODE)
                if len(token) >= 3
            }
            overlap = len(q_tokens & text_tokens)
            needed = max(1, min(2, len(q_tokens)))
            if overlap < needed:
                continue
            out.append(f"{name}: {text}")
            if len(out) >= top_k:
                break
    return out


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
        generate_mindmap = getattr(llm_manager, "generate_mindmap_sync", None)
        if callable(generate_mindmap):
            def _llm_generate_mindmap(
                mode: str = "mindmap",
                query: str = "",
                context_text: str = "",
                max_nodes: int = 32,
                **_kwargs: Any,
            ) -> tuple[str, dict]:
                try:
                    return generate_mindmap(
                        context_text=str(context_text or ""),
                        query=str(query or ""),
                        mode=str(mode or "mindmap"),
                        max_nodes=int(max_nodes or 32),
                        max_output_tokens=max(128, int(_kwargs.get("max_output_tokens", 1600) or 1600)),
                        temperature=float(_kwargs.get("temperature", 0.3) or 0.3),
                    )
                except TypeError:
                    # Backward-compatible path for older manager stubs without
                    # generation controls.
                    return generate_mindmap(
                        context_text=str(context_text or ""),
                        query=str(query or ""),
                        mode=str(mode or "mindmap"),
                        max_nodes=int(max_nodes or 32),
                    )
                except Exception:
                    return ("", {"reason": "llm_error"})
            tools["llm.generate_mindmap"] = _llm_generate_mindmap

    if rag_system is not None:
        search = getattr(rag_system, "search", None)
        if callable(search):
            def _rag_search(query: str, **kwargs):
                top_k = int(kwargs.get("top_k", 6) or 6)
                mode = str(kwargs.get("mode", "hybrid") or "hybrid")
                patterns = list(kwargs.get("regex_patterns", []) or [])
                merged: list[str] = _search_static_sources(
                    query=str(query or ""),
                    source_texts=static_sources,
                    mode=mode,
                    regex_patterns=[str(p) for p in patterns],
                    top_k=top_k,
                )
                try:
                    rows = search(str(query or ""), top_k=top_k)
                except TypeError:
                    rows = search(str(query or ""))
                merged.extend(
                    [
                    _normalize_rag_hit(row)
                    for row in list(rows or [])[:top_k]
                    if str(_normalize_rag_hit(row) or "").strip()
                    ]
                )
                out: list[str] = []
                seen: set[str] = set()
                for row in merged:
                    key = str(row or "").strip()
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    out.append(key)
                    if len(out) >= top_k:
                        break
                return out
            tools["rag.search"] = _rag_search
            tools["rag_search"] = _rag_search

    static_sources: list[tuple[str, str]] = []
    for row in list(source_texts or []):
        if isinstance(row, (tuple, list)) and len(row) >= 2:
            name = str(row[0] or "").strip()
            content = str(row[1] or "").strip()
            if name and content:
                static_sources.append((name, content))
    if static_sources and "rag.search" not in tools:
        def _rag_search_from_sources(query: str, **kwargs):
            top_k = int(kwargs.get("top_k", 6) or 6)
            mode = str(kwargs.get("mode", "hybrid") or "hybrid")
            patterns = [str(p) for p in list(kwargs.get("regex_patterns", []) or [])]
            return _search_static_sources(
                query=str(query or ""),
                source_texts=static_sources,
                mode=mode,
                regex_patterns=patterns,
                top_k=top_k,
            )
        tools["rag.search"] = _rag_search_from_sources
        tools["rag_search"] = _rag_search_from_sources
    if static_sources:
        tools["source.search"] = (
            lambda query, **_kwargs: [
                f"{name}: {content}"
                for name, content in static_sources
                if str(query or "").casefold() in content.casefold()
            ]
        )

    # ── Agent-accessible retrieval tools ─────────────────────────────────────
    if static_sources:

        def _regex_search(
            pattern: str = "",
            max_results: int = 10,
            flags: str = "IGNORECASE",
            context_lines: int = 2,
            **_kwargs: Any,
        ) -> list[str]:
            """Regex search across all source texts. Returns matching lines with context."""
            if not pattern:
                return []
            flag_bits = 0
            for flag_token in str(flags or "IGNORECASE").upper().split("|"):
                flag_token = flag_token.strip()
                bit = getattr(re, flag_token, None)
                if bit is not None:
                    flag_bits |= bit
            try:
                compiled = re.compile(str(pattern), flag_bits)
            except re.error as exc:
                return [f"[Ungültiges Regex-Muster '{pattern}': {exc}]"]

            results: list[str] = []
            ctx = max(0, int(context_lines or 2))
            for name, content in static_sources:
                lines = str(content or "").splitlines()
                for idx, line in enumerate(lines):
                    if compiled.search(line):
                        start = max(0, idx - ctx)
                        end = min(len(lines), idx + ctx + 1)
                        excerpt = "\n".join(lines[start:end]).strip()
                        results.append(f"{name} (Zeile {idx + 1}):\n{excerpt}")
                        if len(results) >= int(max_results or 10):
                            return results
            return results

        tools["regex_search"] = _regex_search

        def _heading_search(
            pattern: str = "",
            include_content: bool = True,
            max_chars_per_section: int = 600,
            max_sections: int = 10,
            **_kwargs: Any,
        ) -> list[str]:
            """
            Find sections by heading in source texts.
            Supports Markdown (# ...), numbered (1. ...), and CAPS headings.
            """
            heading_re = re.compile(
                r"^(?:"
                r"(#{1,6})\s+(.+)"            # Markdown: ## Title
                r"|(\d+(?:\.\d+)*)\s+(.+)"    # Numbered: 1.2 Title
                r"|([A-ZÄÖÜ][A-ZÄÖÜ\s]{3,})"  # ALLCAPS (min 4 chars)
                r")$"
            )
            pattern_re = None
            if pattern:
                try:
                    pattern_re = re.compile(str(pattern), re.IGNORECASE)
                except re.error:
                    pattern_re = None

            results: list[str] = []
            for name, content in static_sources:
                lines = str(content or "").splitlines()
                current_heading: str | None = None
                current_body: list[str] = []

                def _flush():
                    if current_heading is None:
                        return
                    if pattern_re is None or pattern_re.search(current_heading):
                        body_text = "\n".join(current_body).strip()
                        if include_content and body_text:
                            results.append(
                                f"{name} › {current_heading}\n"
                                f"{body_text[:int(max_chars_per_section or 600)]}"
                            )
                        else:
                            results.append(f"{name} › {current_heading}")

                for line in lines:
                    m = heading_re.match(line.rstrip())
                    if m:
                        _flush()
                        # Extract heading text
                        heading_text = (
                            m.group(2) or m.group(4) or m.group(5) or ""
                        ).strip()
                        current_heading = heading_text
                        current_body = []
                    elif current_heading is not None:
                        current_body.append(line)
                    if len(results) >= int(max_sections or 10):
                        break
                _flush()
                if len(results) >= int(max_sections or 10):
                    break
            return results

        tools["heading_search"] = _heading_search

        def _full_text(
            doc_name: str = "",
            max_chars: int = 3000,
            offset_chars: int = 0,
            **_kwargs: Any,
        ) -> str:
            """
            Return raw text of a source document (or all combined).
            Use doc_name="" for all sources. Use offset_chars for pagination.
            """
            limit = max(256, int(max_chars or 3000))
            offset = max(0, int(offset_chars or 0))
            if doc_name:
                needle = str(doc_name).strip().casefold()
                for src_name, content in static_sources:
                    if needle in src_name.casefold():
                        return content[offset : offset + limit]
            # Combine all sources proportionally
            per_doc = max(256, limit // max(1, len(static_sources)))
            parts = []
            for src_name, content in static_sources:
                snippet = content[offset : offset + per_doc]
                if snippet.strip():
                    parts.append(f"### {src_name}\n{snippet}")
            return "\n\n".join(parts)[:limit]

        tools["full_text"] = _full_text
        tools["full_text_search"] = _full_text

    if callable(canvas_apply):
        tools["canvas.apply"] = lambda text, **_kwargs: canvas_apply(str(text or ""))

    if callable(canvas_open_text):
        tools["canvas.open_text"] = lambda text, title="Mindmap", **_kwargs: canvas_open_text(
            str(title or "Mindmap"),
            str(text or ""),
        )

    return tools
