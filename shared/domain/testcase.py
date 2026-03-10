"""Domain models for testcase management."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class TestCase:
    """A saved testcase for evaluation."""

    case_id: str
    name: str
    prompt: str
    expected: str = ""
    labels: list[str] = field(default_factory=list)
