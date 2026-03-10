"""Shared data models for Test Studio."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class CaseEntry:
    case_id: str
    query: str
    labels: list[str]
    f1: float
    precision: float
    recall: float
    hit_at_k: float
    expected_docs: list[str]
    predicted_docs: list[str]
    failed: bool = False


@dataclass
class RunEntry:
    run_type: str
    run_name: str
    timestamp: str
    suite: str
    path: Path
    cases_count: int
    micro_f1: float
    macro_f1: float
    hit_at_k: float
    map_value: float
    mrr: float
    ndcg: float
    failure_cases: int
    cases: list[CaseEntry]


@dataclass
class LabelStat:
    label: str
    cases: int
    macro_f1: float
    macro_hit: float
    macro_precision: float
    macro_recall: float
    failures: int
    failure_rate: float
