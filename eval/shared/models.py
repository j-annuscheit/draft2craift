"""Shared result models for eval commands."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalRunInfo:
    run_name: str
    suite_path: str
    output_dir: str


@dataclass(frozen=True)
class EvalSummary:
    total_cases: int
    passed_cases: int
    failed_cases: int
