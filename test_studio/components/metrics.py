"""Shared metrics and table helpers for Test Studio."""
from __future__ import annotations

import statistics
from typing import Iterable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem

from test_studio.models import CaseEntry, LabelStat, RunEntry


def score_color(value: float) -> QColor:
    bounded = max(0.0, min(1.0, float(value)))
    if bounded >= 0.70:
        return QColor("#1B4332")
    if bounded >= 0.45:
        return QColor("#5C4B1A")
    return QColor("#6A1B1A")


def short_name(text: str, max_len: int = 18) -> str:
    raw = str(text)
    if len(raw) <= max_len:
        return raw
    return f"{raw[: max_len - 1]}…"


def failure_count(run: RunEntry) -> int:
    if run.failure_cases > 0:
        return run.failure_cases
    return sum(1 for case in run.cases if case.failed)


def failure_rate(run: RunEntry) -> float:
    if run.cases_count <= 0:
        return 0.0
    return failure_count(run) / float(run.cases_count)


def aggregate_labels(cases: Iterable[CaseEntry]) -> list[LabelStat]:
    buckets: dict[str, list[CaseEntry]] = {}
    for case in cases:
        labels = case.labels or ["__unlabeled__"]
        for label in labels:
            buckets.setdefault(label, []).append(case)

    stats: list[LabelStat] = []
    for label, entries in buckets.items():
        cases_n = len(entries)
        failures = sum(1 for case in entries if case.failed)
        stats.append(
            LabelStat(
                label=label,
                cases=cases_n,
                macro_f1=statistics.fmean(case.f1 for case in entries) if entries else 0.0,
                macro_hit=statistics.fmean(case.hit_at_k for case in entries) if entries else 0.0,
                macro_precision=(
                    statistics.fmean(case.precision for case in entries) if entries else 0.0
                ),
                macro_recall=(
                    statistics.fmean(case.recall for case in entries) if entries else 0.0
                ),
                failures=failures,
                failure_rate=(failures / cases_n) if cases_n else 0.0,
            )
        )

    stats.sort(key=lambda item: item.label.casefold())
    return stats


def set_text_item(table: QTableWidget, row: int, col: int, text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    table.setItem(row, col, item)
    return item


def set_numeric_item(
    table: QTableWidget,
    row: int,
    col: int,
    value: float,
    *,
    digits: int = 3,
    heatmap: bool = False,
) -> QTableWidgetItem:
    item = QTableWidgetItem(f"{value:.{digits}f}")
    item.setData(Qt.ItemDataRole.UserRole, float(value))
    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    if heatmap:
        item.setBackground(score_color(value))
        item.setForeground(QColor("#F8F9FA"))
    table.setItem(row, col, item)
    return item
