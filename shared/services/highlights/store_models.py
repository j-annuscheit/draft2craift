"""Highlight store view models."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class HighlightMatch:
    """Resolved highlight span in plain preview text."""

    highlight_id: str
    start: int
    end: int
    color: str
    hover_text: str
    jump_to: str
    kind: str = "user"


__all__ = ["HighlightMatch"]
