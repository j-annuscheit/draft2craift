"""Domain models for retrieval-augmented generation."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class RagChunk:
    """One retrievable chunk."""

    chunk_id: str
    document_id: str
    text: str
    score: float = 0.0


@dataclass(frozen=True, slots=True)
class RagQuery:
    """Search query input."""

    text: str
    top_k: int = 6


@dataclass(slots=True)
class RagResult:
    """Result set for one query."""

    query: RagQuery
    chunks: list[RagChunk] = field(default_factory=list)
