from __future__ import annotations

from shared.services.rag.config import RAGConfig
from shared.services.rag.indexer import RAGIndexer
from shared.services.rag.tfidf import BM25Index, TFIDFIndex


def test_indexer_uses_tfidf_by_default():
    cfg = RAGConfig()
    indexer = RAGIndexer(config=cfg)

    assert indexer.lexical_mode() == "tfidf"
    assert isinstance(indexer.index, TFIDFIndex)


def test_indexer_switches_to_bm25_and_rebuilds_documents():
    cfg = RAGConfig()
    indexer = RAGIndexer(config=cfg)
    assert indexer.index_content("alpha.md", "Solarenergie senkt Emissionen in Städten.")
    assert indexer.index_content("beta.md", "API Rollenprüfung verhindert Missbrauch.")

    next_cfg = cfg.copy()
    next_cfg.backend.lexical_mode = "bm25"
    next_cfg.backend.bm25_k1 = 1.5
    next_cfg.backend.bm25_b = 0.6
    indexer.set_config(next_cfg)

    assert isinstance(indexer.index, BM25Index)
    assert indexer.lexical_mode() == "bm25"

    hits = indexer.index.search("Emissionen Städte", top_k=5)
    assert hits
    assert any(key.startswith("alpha.md") for key, _score, _excerpt in hits)


def test_indexer_bm25_state_roundtrip_restores_mode_and_params():
    cfg = RAGConfig()
    cfg.backend.lexical_mode = "bm25"
    cfg.backend.bm25_k1 = 1.4
    cfg.backend.bm25_b = 0.55
    indexer = RAGIndexer(config=cfg)

    assert indexer.index_content("gamma.md", "Parallelbetrieb mit Rollback-Pfaden erhöht Stabilität.")
    state = indexer.dump_state()

    fresh_cfg = RAGConfig()
    restored = RAGIndexer(config=fresh_cfg)
    restored.load_state(state)

    assert restored.lexical_mode() == "bm25"
    assert isinstance(restored.index, BM25Index)
    assert restored.config.backend.bm25_k1 == 1.4
    assert restored.config.backend.bm25_b == 0.55

    hits = restored.index.search("Rollback", top_k=5)
    assert hits
    assert any(key.startswith("gamma.md") for key, _score, _excerpt in hits)
