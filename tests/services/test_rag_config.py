from shared.services.rag.config import RAGConfig


def test_rag_config_defaults_are_stable():
    cfg = RAGConfig()
    assert cfg.selection.top_k == 5
    assert cfg.chunking.chunk_size == 800
    assert cfg.chunking.chunk_overlap == 150
    assert cfg.backend.use_tfidf is True


def test_rag_config_accepts_legacy_flat_keys():
    cfg = RAGConfig.from_dict(
        {
            "use_st": True,
            "chunking_strategy": "section",
            "top_k": 9,
            "literal_llm_max_terms": 12,
        }
    )
    assert cfg.backend.use_st is True
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
