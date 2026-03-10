"""Domain models for documents."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DocumentRef:
    """Reference metadata for one document."""

    document_id: str
    title: str
    path: Path | None = None


@dataclass(slots=True)
class DocumentContent:
    """Mutable text payload with optional metadata."""

    ref: DocumentRef
    text: str
    metadata: dict[str, str] = field(default_factory=dict)
