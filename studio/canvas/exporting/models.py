"""Export option models for canvas document export."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ExportOptions:
    """User-chosen options for document export."""

    output_format: str = "pdf"
    multi_column: bool = False
    include_highlights: bool = False
    include_comments: bool = False
    font_name: str = "Calibri"
    font_size_pt: int = 11
    line_spacing: float = 1.15
