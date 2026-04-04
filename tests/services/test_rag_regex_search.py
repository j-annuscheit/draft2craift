from __future__ import annotations

import pytest

from shared.services.rag.config import RAGConfig
from shared.services.rag.orchestrator import RAGSystem


def _rag_config() -> RAGConfig:
    cfg = RAGConfig()
    cfg.selection.top_k = 5
    return cfg


def test_rag_search_returns_structured_debug_for_v2_stack():
    rag = RAGSystem(config=_rag_config())
    rag.sync_index(
        [
            ("incidents.md", "Incident log: Error code E-1234 occurred at 12:30."),
            ("notes.md", "General project notes without incident IDs."),
        ]
    )

    results, debug = rag.search("Error code", with_debug=True)

    assert isinstance(results, list)
    assert isinstance(debug, dict)
    assert str(debug.get("backend", "")).startswith("llamaindex+lancedb")
    assert int(debug.get("doc_count", 0)) == 2


def test_rag_backend_unavailable_mode_does_not_crash():
    rag = RAGSystem(config=_rag_config())
    rag.sync_index(
        [
            ("symbols.md", "This line contains a literal token."),
        ]
    )

    rag._vector_backend_available = False
    rag._vector_backend_error = "forced_unavailable_for_test"

    with pytest.raises(RuntimeError, match="RAG backend unavailable"):
        rag.search("token", with_debug=True)


def test_rag_selection_threshold_filters_results():
    cfg = _rag_config()
    cfg.selection.mode = "threshold"
    cfg.selection.score_threshold = 10.0
    rag = RAGSystem(config=cfg)
    rag.sync_index(
        [
            ("alpha.md", "alpha token appears here"),
            ("beta.md", "beta token appears here"),
        ]
    )

    results = rag.search("alpha")

    assert results == []


def test_rag_literal_max_results_limits_regex_stage():
    cfg = _rag_config()
    cfg.backend.use_tfidf = False
    cfg.backend.use_regex_search = True
    cfg.literal.max_results = 1
    cfg.selection.mode = "threshold"
    cfg.selection.score_threshold = 1.1
    rag = RAGSystem(config=cfg)
    rag.sync_index(
        [
            ("doc1.md", "Error code E-1234 happened in module A."),
            ("doc2.md", "Error code E-9999 happened in module B."),
            ("doc3.md", "Error code E-1111 happened in module C."),
        ]
    )

    results, debug = rag.search("Error code E-", with_debug=True)

    assert isinstance(results, list)
    assert int(debug["counts"]["regex_hits"]) <= 1


def test_rag_context_window_changes_excerpt_size():
    cfg = _rag_config()
    cfg.chunking.chunk_size = 120
    cfg.chunking.chunk_overlap = 20
    cfg.context.enabled = False
    rag = RAGSystem(config=cfg)
    text = (
        "prefix " * 90
        + "KEYPHRASE_TARGET "
        + "suffix " * 90
    )
    rag.sync_index([("long.md", text)])

    base = rag.search("KEYPHRASE_TARGET", top_k=1)
    assert base
    base_excerpt = str(base[0].get("excerpt", ""))

    cfg.context.enabled = True
    cfg.context.before_chars = 300
    cfg.context.after_chars = 300
    expanded = rag.search("KEYPHRASE_TARGET", top_k=1)
    assert expanded
    expanded_excerpt = str(expanded[0].get("excerpt", ""))

    assert len(expanded_excerpt) > len(base_excerpt)


class _PluginManagerStub:
    def run_hook(self, hook_name: str, payload: dict):
        if hook_name == "rag.after_search":
            rows = list(payload.get("results", []) or [])
            rows.append(
                {
                    "name": "plugin-hit.md",
                    "score": 0.99,
                    "excerpt": "Injected by plugin",
                    "meta": {"methods": ["plugin"], "hit_count": 1, "chunk_indexes": [0]},
                }
            )
            out = dict(payload)
            out["results"] = rows
            return out
        return payload


def test_rag_after_search_plugin_hook_can_extend_results():
    rag = RAGSystem(config=_rag_config(), plugin_manager=_PluginManagerStub())
    rag.sync_index([("base.md", "A base document with plugin test token.")])

    results = rag.search("plugin test token")

    assert any(str(row.get("name", "")) == "plugin-hit.md" for row in results)


def test_rag_section_routing_strict_filter_prefers_relevant_heading():
    cfg = _rag_config()
    cfg.routing.enabled = True
    cfg.routing.mode = "heading"
    cfg.routing.strict_filter = True
    cfg.routing.top_k = 1
    cfg.routing.min_score = 0.05
    cfg.routing.expand_query = False
    cfg.routing.score_boost = 0.0
    rag = RAGSystem(config=cfg)
    rag.sync_index(
        [
            ("doc_attention.md", "# Attention\nSelf-attention explains token dependencies."),
            ("doc_conv.md", "# Convolution\nKernel and pooling operations."),
        ]
    )

    results, debug = rag.search("attention", with_debug=True)

    assert results
    assert str(results[0].get("name", "")) == "doc_attention.md"
    assert all(str(row.get("name", "")) != "doc_conv.md" for row in results)
    section_debug = dict(debug.get("section_routing", {}) or {})
    assert bool(section_debug.get("strict_filter")) is True
    assert int(section_debug.get("selected_count", 0)) >= 1


def test_rag_section_routing_strict_filter_without_section_match_returns_empty():
    cfg = _rag_config()
    cfg.routing.enabled = True
    cfg.routing.mode = "summary"
    cfg.routing.strict_filter = True
    cfg.routing.top_k = 1
    cfg.routing.min_score = 1.5
    cfg.routing.expand_query = False
    rag = RAGSystem(config=cfg)
    rag.sync_index(
        [
            ("alpha.md", "# Alpha\nAlpha domain text."),
            ("beta.md", "# Beta\nBeta domain text."),
        ]
    )

    results, debug = rag.search("unrelated-topic", with_debug=True)

    assert results == []
    assert int(debug["counts"]["routed_hits"]) == 0


def test_rag_section_routing_query_expansion_is_reported():
    cfg = _rag_config()
    cfg.routing.enabled = True
    cfg.routing.mode = "hybrid"
    cfg.routing.expand_query = True
    cfg.routing.expand_query_max_sections = 2
    cfg.routing.min_score = 0.01
    rag = RAGSystem(config=cfg)
    rag.sync_index(
        [
            (
                "transformer.md",
                "# Transformer Architecture\nAttention heads model context windows.",
            ),
        ]
    )

    _results, debug = rag.search("transformer architecture", with_debug=True)
    section_debug = dict(debug.get("section_routing", {}) or {})

    expansions = list(section_debug.get("query_expansions", []) or [])
    assert len(expansions) >= 1
