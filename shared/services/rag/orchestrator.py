"""RAG orchestration over indexer/searcher/expanders."""
from __future__ import annotations

import threading
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

from shared.services.rag.chunking import build_chunks
from shared.services.rag.config import RAGConfig
from shared.services.rag.expanders import RAGExpanders
from shared.services.rag.indexer import RAGIndexer
from shared.services.rag.searcher import RAGSearcher


class RAGSystem(QObject):
    """Qt-core orchestration layer for indexing and retrieval."""

    results_ready = Signal(list)
    backend_changed = Signal(str)
    rag_settings_requested = Signal()

    def __init__(
        self,
        config: RAGConfig | None = None,
        query_expander: Callable[[str], str] | None = None,
        logger: Any = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._log = logger
        self._config = config or RAGConfig()
        self._lock = threading.RLock()

        self._expanders = RAGExpanders(self._config, logger, query_expander)
        self._indexer = RAGIndexer(self._config, logger)
        self._searcher = RAGSearcher(self._config, self._indexer, self._expanders, logger)

    @property
    def config(self) -> RAGConfig:
        with self._lock:
            return self._config

    @config.setter
    def config(self, value: RAGConfig) -> None:
        with self._lock:
            self._config = value
            self._indexer.set_config(value)
            self._expanders.set_config(value)
            self._searcher.set_config(value)

    @property
    def _st_model(self) -> Any:
        with self._lock:
            return self._indexer.st_model

    @_st_model.setter
    def _st_model(self, value: Any) -> None:
        with self._lock:
            self._indexer.st_model = value

    @property
    def _st_embeddings(self) -> dict[str, Any]:
        with self._lock:
            return self._indexer.st_embeddings

    @_st_embeddings.setter
    def _st_embeddings(self, value: dict[str, Any]) -> None:
        with self._lock:
            self._indexer.st_embeddings = dict(value or {})

    def try_load_sentence_transformers(self, model_name: str | None = None) -> bool:
        with self._lock:
            ok = self._indexer.try_load_sentence_transformers(model_name)
            backend = self._indexer.current_backend()
        self.backend_changed.emit(backend)
        return ok

    def set_query_expander(self, fn: Callable[[str], str] | None) -> None:
        with self._lock:
            self._expanders.set_query_expander(fn)

    def set_tfidf_query_expander(self, fn: Callable[[str], str] | None) -> None:
        with self._lock:
            self._expanders.set_tfidf_query_expander(fn)

    def set_st_query_expander(self, fn: Callable | None) -> None:
        with self._lock:
            self._expanders.set_st_query_expander(fn)

    def set_literal_query_expander(self, fn: Callable | None) -> None:
        with self._lock:
            self._expanders.set_literal_query_expander(fn)

    def set_rag_reranker(self, fn: Callable | None) -> None:
        with self._lock:
            self._expanders.set_rag_reranker(fn)

    def current_backend(self) -> str:
        with self._lock:
            return self._indexer.current_backend()

    @property
    def st_model_loaded(self) -> bool:
        with self._lock:
            return self._indexer.st_model is not None

    def index_content(self, name: str, content: str) -> bool:
        with self._lock:
            return self._indexer.index_content(name, content)

    def index_file(self, path: str) -> bool:
        with self._lock:
            return self._indexer.index_file(path)

    def sync_index(self, entries: list[tuple[str, str]]) -> tuple[int, int, int]:
        with self._lock:
            return self._indexer.sync_index(entries)

    def remove_file(self, name: str) -> None:
        with self._lock:
            self._indexer.remove_file(name)

    def clear(self) -> None:
        with self._lock:
            self._indexer.clear()

    def dump_state(self) -> dict[str, Any]:
        with self._lock:
            return self._indexer.dump_state()

    def load_state(self, state: dict[str, Any]) -> None:
        with self._lock:
            self._indexer.load_state(state)

    def search(
        self,
        query: str,
        top_k: int | None = None,
        with_debug: bool = False,
    ) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], dict[str, Any]]:
        with self._lock:
            return self._searcher.search(query, top_k, with_debug)

    def _build_chunks(self, content: str, doc_name: str = "") -> list[dict[str, Any]]:
        """Build chunks for chunk-based mindmap generation."""
        with self._lock:
            return build_chunks(content, self._config.chunking, doc_name, self._log)
