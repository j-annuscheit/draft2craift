from __future__ import annotations

import os

import pytest
from PySide6.QtWidgets import QApplication

from shared.services.rag.config import RAGConfig
from shared.services.rag.orchestrator import RAGSystem


@pytest.fixture(scope="session", autouse=True)
def _qt_offscreen() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _rag_local_embedding_stub(monkeypatch):
    from llama_index.core.embeddings import MockEmbedding

    def _resolve_embedding_model(self):
        return MockEmbedding(embed_dim=384), "mock:test", ""

    monkeypatch.setattr(
        RAGSystem,
        "_resolve_embedding_model",
        _resolve_embedding_model,
        raising=True,
    )


@pytest.fixture(autouse=True)
def _rag_vector_backend_stub(monkeypatch):
    class _FakeRetriever:
        def retrieve(self, _query):
            return []

    class _FakeIndex:
        def as_retriever(self, similarity_top_k=5):
            _ = similarity_top_k
            return _FakeRetriever()

    def _rebuild_vector_backend(self):
        self._teardown_vector_backend()
        if not self._chunks:
            self._vector_backend_available = False
            self._vector_backend_error = "no_chunks"
            self._vector_embedding_provider = ""
            return
        self._vector_index = _FakeIndex()
        self._vector_backend_available = True
        self._vector_backend_error = ""
        self._vector_embedding_provider = "mock:index"

    monkeypatch.setattr(
        RAGSystem,
        "_rebuild_vector_backend",
        _rebuild_vector_backend,
        raising=True,
    )


@pytest.fixture(scope="session")
def qt_app(_qt_offscreen) -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def rag_config() -> RAGConfig:
    cfg = RAGConfig()
    cfg.backend.use_tfidf = True
    cfg.backend.use_st = False
    cfg.backend.use_regex_search = True
    cfg.hyde.use_hyde = False
    cfg.context.enabled = False
    cfg.selection.top_k = 5
    return cfg


@pytest.fixture
def rag_entries() -> list[tuple[str, str]]:
    return [
        (
            "doc_alpha.md",
            "Alpha topic. Architektur und Tests. Parallel indexing search safety.",
        ),
        (
            "doc_beta.md",
            "Beta topic. Deterministic retrieval with tfidf and literal search.",
        ),
        (
            "doc_gamma.md",
            "Gamma topic. Concurrency baseline for rag worker and orchestrator.",
        ),
    ]


@pytest.fixture
def rag_system(rag_config: RAGConfig) -> RAGSystem:
    return RAGSystem(config=rag_config)


@pytest.fixture
def indexed_rag_system(
    rag_system: RAGSystem,
    rag_entries: list[tuple[str, str]],
) -> RAGSystem:
    rag_system.sync_index(rag_entries)
    return rag_system
