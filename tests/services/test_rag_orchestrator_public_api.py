from __future__ import annotations

from shared.services.rag.config import RAGConfig
from shared.services.rag.orchestrator import RAGSystem


def test_st_model_loaded_reflects_backend_state() -> None:
    rag = RAGSystem(config=RAGConfig())

    assert rag.st_model_loaded is False

    rag._st_model = object()
    assert rag.st_model_loaded is True
