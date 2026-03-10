"""Project file schema models."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ProjectSchema:
    """Persisted project document."""

    schema_version: int = 1
    title: str = ""
    markdown: str = ""
    settings: dict[str, object] = field(default_factory=dict)
