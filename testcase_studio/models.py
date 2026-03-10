"""Shared data models for Testcase Studio."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SuiteSpec:
    suite_id: str
    label: str
    description: str
    required_fields: tuple[str, ...]


@dataclass(frozen=True)
class FieldGuide:
    key: str
    label: str
    required: bool
    help_text: str
    example: str
    max_height: int = 62
