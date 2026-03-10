from __future__ import annotations

import os

import pytest
from PySide6.QtWidgets import QApplication

from shared.services.rag.config import RAGConfig
from shared.services.rag.orchestrator import RAGSystem


@pytest.fixture(scope="session", autouse=True)
def _qt_offscreen() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


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
