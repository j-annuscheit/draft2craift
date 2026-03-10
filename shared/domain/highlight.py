"""Domain models for text highlights."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HighlightSpan:
    """Character range in a document."""

    start: int
    end: int

    def is_valid(self) -> bool:
        return self.start >= 0 and self.end >= self.start


@dataclass(slots=True)
class HighlightEntry:
    """Stored highlight metadata."""

    document_id: str
    span: HighlightSpan
    color: str
    note: str = ""
