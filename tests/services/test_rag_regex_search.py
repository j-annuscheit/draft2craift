from __future__ import annotations

from shared.services.rag.config import RAGConfig
from shared.services.rag.orchestrator import RAGSystem


def _regex_only_config() -> RAGConfig:
    cfg = RAGConfig()
    cfg.backend.use_tfidf = False
    cfg.backend.use_st = False
    cfg.backend.use_regex_search = True
    cfg.hyde.use_hyde = False
    cfg.literal.max_results = 10
    cfg.selection.top_k = 5
    return cfg


def test_regex_backend_matches_real_regex_patterns():
    rag = RAGSystem(config=_regex_only_config())
    rag.sync_index(
        [
            ("incidents.md", "Incident log: Error code E-1234 occurred at 12:30."),
            ("notes.md", "General project notes without incident IDs."),
        ]
    )

    results, debug = rag.search(r"E-\d{4}", with_debug=True)

    assert any(str(item.get("name", "")) == "incidents.md" for item in results)
    assert int(debug["counts"]["regex_hits"]) >= 1
    assert r"E-\d{4}" in list(debug["regex"]["compiled_patterns"])


def test_invalid_regex_pattern_falls_back_to_literal_match():
    rag = RAGSystem(config=_regex_only_config())
    rag.sync_index(
        [
            ("symbols.md", "This line contains the literal token ( which should still be found."),
        ]
    )

    results, debug = rag.search("(", with_debug=True)

    assert any(str(item.get("name", "")) == "symbols.md" for item in results)
    assert list(debug["regex"]["invalid_patterns"])
    assert "(" in list(debug["regex"]["literal_fallback_patterns"])
