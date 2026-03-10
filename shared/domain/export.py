"""Domain models for export requests."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class ExportFormat(str, Enum):
    """Supported export targets."""

    MARKDOWN = "markdown"
    HTML = "html"
    PDF = "pdf"


@dataclass(frozen=True, slots=True)
class ExportRequest:
    """Export action payload."""

    output_path: Path
    export_format: ExportFormat
    include_highlights: bool = True
