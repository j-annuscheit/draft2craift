from shared.services.rag.config import RAGConfig


def test_rag_config_defaults_are_stable():
    cfg = RAGConfig()
    assert cfg.selection.top_k == 5
    assert cfg.selection.score_threshold == 0.05
    assert cfg.chunking.chunk_size == 800
    assert cfg.chunking.chunk_overlap == 150
    assert cfg.backend.use_tfidf is True
    assert cfg.backend.lexical_mode == "tfidf"
    assert cfg.backend.bm25_k1 == 1.2
    assert cfg.backend.bm25_b == 0.75


def test_rag_config_requires_structured_overrides():
    cfg = RAGConfig.from_dict(
        {
            "backend": {"use_st": True, "lexical_mode": "bm25", "bm25_k1": 1.5, "bm25_b": 0.6},
            "chunking": {"strategy": "section"},
            "selection": {"top_k": 9},
            "literal": {"max_llm_terms": 12},
        }
    )
    assert cfg.backend.use_st is True
    assert cfg.backend.lexical_mode == "bm25"
    assert cfg.backend.bm25_k1 == 1.5
    assert cfg.backend.bm25_b == 0.6
    assert cfg.chunking.strategy == "section"
    assert cfg.selection.top_k == 9
    assert cfg.literal.max_llm_terms == 12


def test_rag_config_allows_dotted_overrides():
    cfg = RAGConfig().with_overrides(
        {
            "backend.use_regex_search": False,
            "selection.mode": "threshold",
            "selection.score_threshold": 0.4,
        }
    )
    assert cfg.backend.use_regex_search is False
    assert cfg.selection.mode == "threshold"
    assert cfg.selection.score_threshold == 0.4
