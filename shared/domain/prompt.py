"""Domain models for prompt templates."""
from __future__ import annotations

from dataclasses import dataclass


PROMPT_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    """A versioned system/user prompt pair."""

    key: str
    system: str
    user: str
    schema_version: int = PROMPT_SCHEMA_VERSION

    def is_valid(self) -> bool:
        return bool(self.key.strip() and self.system.strip() and self.user.strip())
