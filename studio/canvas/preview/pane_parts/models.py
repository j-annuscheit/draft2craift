"""Data models for the preview pane."""
from __future__ import annotations

from dataclasses import dataclass

@dataclass(slots=True)
class _RenderedHighlight:
    """One applied highlight span in preview plain-text coordinates."""

    highlight_id: str
    start: int
    end: int
    color: str
    hover_text: str
    jump_to: str
    kind: str

