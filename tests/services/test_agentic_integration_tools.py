from __future__ import annotations

from types import SimpleNamespace

import pytest

from shared.services.agentic.integration_tools import build_tools


class _RagStub:
    def search(self, query: str, top_k: int = 8):
        _ = query, top_k
        return [
            {"source": "rag_doc", "excerpt": "RAG Treffer A"},
            ("rag_tuple", 0.8, "RAG Treffer B"),
        ]


class _LLMWorkerStub:
    def __init__(self, *, token_count: int, ctx_window: int, reply: str = "ok") -> None:
        self._token_count = int(token_count)
        self._ctx_window = int(ctx_window)
        self._reply = str(reply)

    def count_tokens(self, text: str) -> int:
        _ = text
        return int(self._token_count)

    def context_window(self, default_n_ctx: int = 4096) -> int:
        _ = default_n_ctx
        return int(self._ctx_window)

    def run_completion_sync(self, prompt: str, **kwargs) -> str:
        _ = prompt, kwargs
        return self._reply


class _LLMMindmapStub:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate_mindmap_sync(
        self,
        *,
        context_text: str,
        query: str,
        mode: str = "mindmap",
        max_nodes: int = 32,
        max_output_tokens: int = 1600,
        temperature: float = 0.3,
    ):
        self.calls.append(
            {
                "context_text": context_text,
                "query": query,
                "mode": mode,
                "max_nodes": max_nodes,
                "max_output_tokens": max_output_tokens,
                "temperature": temperature,
            }
        )
        return "```mindmap\nRoot\n  Child\n```", {"reason": "stub"}


def test_build_tools_source_search_hybrid_returns_hits():
    tools = build_tools(
        source_texts=[
            ("doc_a", "Alice lebt in Berlin."),
            ("doc_b", "Bob lebt in Paris."),
        ]
    )
    rag_search = tools["rag.search"]
    hits = rag_search(query="Wo lebt Alice?", mode="hybrid", top_k=3)
    assert hits
    assert any("doc_a:" in str(row) for row in hits)


def test_build_tools_source_search_regex_mode_uses_patterns():
    tools = build_tools(
        source_texts=[
            ("doc_a", "Produktionsjahr: 2024"),
            ("doc_b", "Version 3.2 ist veröffentlicht"),
        ]
    )
    rag_search = tools["rag.search"]
    hits = rag_search(
        query="irrelevant",
        mode="regex",
        regex_patterns=[r"Produktionsjahr:\s*2024"],
        top_k=5,
    )
    assert hits
    assert any("doc_a:" in str(row) for row in hits)
    assert all("doc_b:" not in str(row) for row in hits)


def test_build_tools_source_and_rag_system_merge_results():
    tools = build_tools(
        rag_system=_RagStub(),
        source_texts=[("doc_a", "Alice lebt in Berlin.")],
    )
    rag_search = tools["rag.search"]
    hits = rag_search(query="Alice", mode="hybrid", top_k=6)
    assert any("doc_a:" in str(row) for row in hits)
    assert any("rag_doc:" in str(row) for row in hits)


def test_build_tools_exposes_rag_search_alias():
    tools = build_tools(
        source_texts=[
            ("doc_a", "Alice lebt in Berlin."),
        ]
    )
    hits = tools["rag_search"](query="Alice", mode="hybrid", top_k=3)
    assert hits
    assert any("doc_a:" in str(row) for row in hits)


def test_build_tools_exposes_full_text_search_alias():
    tools = build_tools(
        source_texts=[
            ("doc_a", "Alice lebt in Berlin."),
        ]
    )
    text = str(tools["full_text_search"](doc_name="doc_a", max_chars=200) or "")
    assert "Alice lebt in Berlin" in text


def test_build_tools_llm_generate_raises_when_prompt_exceeds_context_window():
    tools = build_tools(
        llm_manager=SimpleNamespace(
            worker=_LLMWorkerStub(token_count=900, ctx_window=1024),
        )
    )
    with pytest.raises(RuntimeError, match="context window"):
        tools["llm.generate"](prompt="Sehr langer Prompt")


def test_build_tools_llm_generate_passes_when_prompt_fits_context_window():
    tools = build_tools(
        llm_manager=SimpleNamespace(
            worker=_LLMWorkerStub(token_count=120, ctx_window=2048, reply="Antwort"),
        )
    )
    assert tools["llm.generate"](prompt="Kurzer Prompt") == "Antwort"


def test_build_tools_forward_mindmap_generation_controls() -> None:
    llm_manager = _LLMMindmapStub()
    tools = build_tools(llm_manager=llm_manager)
    markdown, meta = tools["llm.generate_mindmap"](
        mode="mindmap",
        query="Transformer",
        context_text="Kontext",
        max_nodes=18,
        max_output_tokens=700,
        temperature=0.15,
    )
    assert "mindmap" in str(markdown).casefold()
    assert str(dict(meta).get("reason", "")) == "stub"
    assert llm_manager.calls
    call = dict(llm_manager.calls[0] or {})
    assert int(call.get("max_output_tokens", 0)) == 700
    assert float(call.get("temperature", 0.0)) == pytest.approx(0.15, rel=1e-4)
