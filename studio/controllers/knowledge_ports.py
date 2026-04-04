"""Protocols for KnowledgeController dock dependencies."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class RAGWorkerPort(Protocol):
    """Subset of RAG worker API required by KnowledgeController."""

    def isRunning(self) -> bool: ...


@runtime_checkable
class KnowledgeDockPort(Protocol):
    """Public contract expected by KnowledgeController."""

    rag_worker: RAGWorkerPort

    def suspend_reindex(self) -> None: ...

    def resume_reindex(self, *, flush: bool = True) -> None: ...

    def reindex_rag(self) -> None: ...

    def add_imported_files(self, entries: list[tuple[str, str]]) -> None: ...

    def open_content(
        self,
        title: str,
        content: str,
        doc_key: str = "",
        *,
        activate: bool = True,
    ) -> None: ...

    def rename_viewer_document(self, old_doc_key: str, new_doc_key: str) -> bool: ...

    def rename_imported_file(self, old_name: str, new_name: str) -> str: ...

    def remove_imported_file(self, name: str) -> None: ...

    def remove_viewer_document(self, doc_key: str) -> None: ...


@runtime_checkable
class ChatDockPort(Protocol):
    """Public chat-dock contract expected by KnowledgeController."""

    def add_document(self, name: str, content: str) -> None: ...

    def rename_document(self, old_name: str, new_name: str) -> str: ...

    def remove_document(self, name: str) -> None: ...
