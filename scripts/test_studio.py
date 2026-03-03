#!/usr/bin/env python3
"""Test Studio dashboard for suite runs, pipeline execution, and run comparison."""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from PySide6.QtCharts import (
    QBarCategoryAxis,
    QBarSeries,
    QBarSet,
    QChart,
    QChartView,
    QStackedBarSeries,
    QValueAxis,
)
from PySide6.QtCore import QProcess, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QDoubleSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

_SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
_CASE_NO_RE = re.compile(r"^(?:tc_)?0*(\d+)$", flags=re.IGNORECASE)


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
    path: pathlib.Path
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


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalise_labels(raw: Any) -> list[str]:
    if isinstance(raw, str):
        tokens: list[str] = []
        for chunk in raw.split("|"):
            for part in chunk.split(","):
                text = part.strip()
                if text:
                    tokens.append(text)
        return tokens

    if not isinstance(raw, list):
        return []

    labels: list[str] = []
    for item in raw:
        text = str(item).strip()
        if text:
            labels.append(text)
    return labels


def _load_case_entry(raw: dict[str, Any]) -> CaseEntry:
    f1 = _safe_float(raw.get("f1"))
    failed_raw = raw.get("failed", None)
    failed = bool(failed_raw) if isinstance(failed_raw, bool) else (f1 <= 0.0)
    return CaseEntry(
        case_id=str(raw.get("case_id", "")),
        query=str(raw.get("query", "")),
        labels=_normalise_labels(raw.get("labels", [])),
        f1=f1,
        precision=_safe_float(raw.get("precision")),
        recall=_safe_float(raw.get("recall")),
        hit_at_k=_safe_float(raw.get("hit_at_k")),
        expected_docs=[str(x) for x in raw.get("expected_docs", []) if str(x)],
        predicted_docs=[str(x) for x in raw.get("predicted_docs", []) if str(x)],
        failed=failed,
    )


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    raw = str(value or "").strip().casefold()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off", ""}:
        return False
    return default


def _load_pdf_cases_from_csv(path: pathlib.Path) -> list[CaseEntry]:
    if not path.exists():
        return []
    out: list[CaseEntry] = []
    with open(path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            labels = _normalise_labels(row.get("labels", ""))
            passed = str(row.get("passed", "")).strip().casefold() == "true"
            error_tags = str(row.get("error_tags", "")).strip()
            fail_reasons = str(row.get("fail_reasons", "")).strip()
            pdf_path = str(row.get("pdf_path", "")).strip()
            expected_path = str(row.get("expected_path", "")).strip()
            observed: list[str] = []
            if error_tags:
                observed.append(f"tags: {error_tags}")
            if fail_reasons:
                observed.append(f"fail: {fail_reasons}")
            if not observed:
                observed.append("ok")

            query = f"PDF: {pathlib.Path(pdf_path).name}" if pdf_path else "PDF case"
            out.append(
                CaseEntry(
                    case_id=str(row.get("case_id", "")),
                    query=query,
                    labels=labels,
                    f1=_safe_float(row.get("token_f1")),
                    precision=_safe_float(row.get("token_precision")),
                    recall=_safe_float(row.get("token_recall")),
                    hit_at_k=_safe_float(row.get("paragraph_mean")),
                    expected_docs=(
                        [pathlib.Path(expected_path).name] if expected_path else []
                    ),
                    predicted_docs=observed,
                    failed=(not passed),
                )
            )
    return out


def _load_rag_run_entry(path: pathlib.Path, payload: dict[str, Any]) -> RunEntry | None:
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        return None

    macro = summary.get("macro") if isinstance(summary.get("macro"), dict) else {}
    micro = summary.get("micro") if isinstance(summary.get("micro"), dict) else {}
    raw_cases = payload.get("cases") if isinstance(payload.get("cases"), list) else []
    cases = [_load_case_entry(case) for case in raw_cases if isinstance(case, dict)]
    cases_count = int(summary.get("cases", len(cases)) or 0)
    failures = sum(1 for case in cases if case.failed)

    return RunEntry(
        run_type="rag",
        run_name=str(payload.get("run_name") or path.stem.replace(".summary", "")),
        timestamp=str(payload.get("timestamp", "")),
        suite=str(payload.get("suite", "")),
        path=path,
        cases_count=cases_count,
        micro_f1=_safe_float(micro.get("f1")),
        macro_f1=_safe_float(macro.get("f1")),
        hit_at_k=_safe_float(macro.get("hit_at_k")),
        map_value=_safe_float(macro.get("map")),
        mrr=_safe_float(macro.get("mrr")),
        ndcg=_safe_float(macro.get("ndcg")),
        failure_cases=failures,
        cases=cases,
    )


def _load_pdf_run_entry(path: pathlib.Path, payload: dict[str, Any]) -> RunEntry:
    macro = payload.get("macro") if isinstance(payload.get("macro"), dict) else {}
    cases_csv = path.with_name(path.name.replace(".summary.json", ".cases.csv"))
    cases = _load_pdf_cases_from_csv(cases_csv)
    cases_count = _safe_int(payload.get("cases"), len(cases))
    if cases_count <= 0:
        cases_count = len(cases)
    failures = _safe_int(payload.get("failed"), sum(1 for case in cases if case.failed))
    timestamp = str(payload.get("timestamp", "")).strip()
    if not timestamp:
        try:
            timestamp = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
        except Exception:
            timestamp = ""

    return RunEntry(
        run_type="pdf",
        run_name=str(payload.get("run_name") or path.stem.replace(".summary", "")),
        timestamp=timestamp,
        suite=str(payload.get("suite", "")),
        path=path,
        cases_count=cases_count,
        micro_f1=_safe_float(macro.get("token_f1")),
        macro_f1=_safe_float(macro.get("token_f1")),
        hit_at_k=_safe_float(macro.get("paragraph_mean")),
        map_value=_safe_float(macro.get("line_ratio")),
        mrr=_safe_float(macro.get("char_ratio")),
        ndcg=_safe_float(payload.get("pass_rate")),
        failure_cases=failures,
        cases=cases,
    )


def _load_glossary_run_entry(path: pathlib.Path, payload: dict[str, Any]) -> RunEntry:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    macro = summary.get("macro") if isinstance(summary.get("macro"), dict) else {}
    micro = summary.get("micro") if isinstance(summary.get("micro"), dict) else {}
    raw_cases = payload.get("cases") if isinstance(payload.get("cases"), list) else []
    cases = [_load_case_entry(case) for case in raw_cases if isinstance(case, dict)]

    cases_count = _safe_int(summary.get("cases"), len(cases))
    if cases_count <= 0:
        cases_count = len(cases)
    failures = _safe_int(summary.get("failed"), sum(1 for case in cases if case.failed))
    timestamp = str(payload.get("timestamp", "")).strip()
    if not timestamp:
        try:
            timestamp = datetime.fromtimestamp(path.stat().st_mtime).isoformat(
                timespec="seconds"
            )
        except Exception:
            timestamp = ""

    return RunEntry(
        run_type="glossary",
        run_name=str(payload.get("run_name") or path.stem.replace(".summary", "")),
        timestamp=timestamp,
        suite=str(payload.get("suite", "")),
        path=path,
        cases_count=cases_count,
        micro_f1=_safe_float(micro.get("f1")),
        macro_f1=_safe_float(macro.get("f1")),
        hit_at_k=_safe_float(macro.get("recall")),
        map_value=_safe_float(macro.get("precision")),
        mrr=_safe_float(summary.get("pass_rate")),
        ndcg=_safe_float(macro.get("hit_at_k")),
        failure_cases=failures,
        cases=cases,
    )


def _load_factcheck_run_entry(path: pathlib.Path, payload: dict[str, Any]) -> RunEntry:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    macro = summary.get("macro") if isinstance(summary.get("macro"), dict) else {}
    micro = summary.get("micro") if isinstance(summary.get("micro"), dict) else {}
    steps = summary.get("steps") if isinstance(summary.get("steps"), dict) else {}
    extract = steps.get("extract") if isinstance(steps.get("extract"), dict) else {}
    extract_macro = (
        extract.get("macro") if isinstance(extract.get("macro"), dict) else {}
    )
    verify = steps.get("verify") if isinstance(steps.get("verify"), dict) else {}
    verify_macro = (
        verify.get("macro") if isinstance(verify.get("macro"), dict) else {}
    )
    raw_cases = payload.get("cases") if isinstance(payload.get("cases"), list) else []
    cases = [_load_case_entry(case) for case in raw_cases if isinstance(case, dict)]

    cases_count = _safe_int(summary.get("cases"), len(cases))
    if cases_count <= 0:
        cases_count = len(cases)
    failures = _safe_int(summary.get("failed"), sum(1 for case in cases if case.failed))
    timestamp = str(payload.get("timestamp", "")).strip()
    if not timestamp:
        try:
            timestamp = datetime.fromtimestamp(path.stat().st_mtime).isoformat(
                timespec="seconds"
            )
        except Exception:
            timestamp = ""

    return RunEntry(
        run_type="factcheck",
        run_name=str(payload.get("run_name") or path.stem.replace(".summary", "")),
        timestamp=timestamp,
        suite=str(payload.get("suite", "")),
        path=path,
        cases_count=cases_count,
        micro_f1=_safe_float(micro.get("f1")),
        macro_f1=_safe_float(macro.get("f1")),
        hit_at_k=_safe_float(extract_macro.get("f1")),
        map_value=_safe_float(verify_macro.get("status_accuracy")),
        mrr=_safe_float(summary.get("pass_rate")),
        ndcg=_safe_float(macro.get("recall")),
        failure_cases=failures,
        cases=cases,
    )


def _load_judge_run_entry(path: pathlib.Path, payload: dict[str, Any]) -> RunEntry:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    raw_cases = payload.get("cases") if isinstance(payload.get("cases"), list) else []
    cases: list[CaseEntry] = []
    for raw in raw_cases:
        if not isinstance(raw, dict):
            continue
        correct = _safe_bool(raw.get("correct"), False)
        parsed = _safe_bool(raw.get("parsed"), False)
        predicted = str(raw.get("predicted_winner", "")).strip()
        parse_mode = str(raw.get("parse_mode", "")).strip()
        fail_reasons = raw.get("fail_reasons") if isinstance(raw.get("fail_reasons"), list) else []
        observed = [predicted or "unparsed"]
        if parse_mode:
            observed.append(f"mode={parse_mode}")
        fail_parts = [str(x).strip() for x in fail_reasons if str(x).strip()]
        if fail_parts:
            observed.append(f"fail={', '.join(fail_parts)}")
        query = str(raw.get("reason") or raw.get("raw_preview") or "").strip()
        score = 1.0 if correct else 0.0
        expected = str(raw.get("expected_winner", "")).strip()
        cases.append(
            CaseEntry(
                case_id=str(raw.get("case_id", "")),
                query=query,
                labels=_normalise_labels(raw.get("labels", [])),
                f1=score,
                precision=score,
                recall=score,
                hit_at_k=(1.0 if parsed else 0.0),
                expected_docs=[expected] if expected else [],
                predicted_docs=observed,
                failed=(not correct),
            )
        )

    cases_count = _safe_int(summary.get("cases"), len(cases))
    if cases_count <= 0:
        cases_count = len(cases)
    failures = _safe_int(summary.get("incorrect"), sum(1 for case in cases if case.failed))
    timestamp = str(payload.get("timestamp", "")).strip()
    if not timestamp:
        try:
            timestamp = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
        except Exception:
            timestamp = ""

    accuracy = _safe_float(summary.get("accuracy"))
    return RunEntry(
        run_type="judge",
        run_name=str(payload.get("run_name") or path.stem.replace(".summary", "")),
        timestamp=timestamp,
        suite=str(payload.get("suite", "")),
        path=path,
        cases_count=cases_count,
        micro_f1=accuracy,
        macro_f1=accuracy,
        hit_at_k=_safe_float(summary.get("parsed_rate")),
        map_value=_safe_float(summary.get("avg_confidence")),
        mrr=_safe_float(summary.get("threshold_accuracy")),
        ndcg=(1.0 if _safe_bool(summary.get("passed"), False) else 0.0),
        failure_cases=failures,
        cases=cases,
    )


def _load_llmcompare_run_entry(path: pathlib.Path, payload: dict[str, Any]) -> RunEntry:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    cfg_a = (
        config.get("candidate_a") if isinstance(config.get("candidate_a"), dict) else {}
    )
    cfg_b = (
        config.get("candidate_b") if isinstance(config.get("candidate_b"), dict) else {}
    )
    label_a = str(cfg_a.get("label", "A")).strip() or "A"
    label_b = str(cfg_b.get("label", "B")).strip() or "B"

    raw_cases = payload.get("cases") if isinstance(payload.get("cases"), list) else []
    cases: list[CaseEntry] = []
    for raw in raw_cases:
        if not isinstance(raw, dict):
            continue
        preferred = str(raw.get("preferred_setting", "")).strip().casefold()
        parsed = _safe_bool(raw.get("parsed"), False)
        parse_mode = str(raw.get("parse_mode", "")).strip()
        judge_winner = str(raw.get("judge_winner", "")).strip()
        preferred_label = str(raw.get("preferred_label", "")).strip()
        if not preferred_label:
            if preferred == "a":
                preferred_label = label_a
            elif preferred == "b":
                preferred_label = label_b
            else:
                preferred_label = "undecided"

        if preferred == "a":
            f1 = 1.0
            precision = 0.0
        elif preferred == "b":
            f1 = 0.0
            precision = 1.0
        else:
            f1 = 0.0
            precision = 0.0

        observed = [f"preferred={preferred_label}"]
        if judge_winner:
            observed.append(f"judge={judge_winner}")
        if parse_mode:
            observed.append(f"mode={parse_mode}")

        reason = str(raw.get("reason") or "").strip()
        preview = str(raw.get("prompt_preview") or "").strip()
        query = f"{preview} | reason={reason}" if reason else preview
        cases.append(
            CaseEntry(
                case_id=str(raw.get("case_id", "")),
                query=query,
                labels=_normalise_labels(raw.get("labels", [])),
                f1=f1,
                precision=precision,
                recall=(1.0 if preferred in {"a", "b"} else 0.0),
                hit_at_k=(1.0 if parsed else 0.0),
                expected_docs=[f"A={label_a}", f"B={label_b}"],
                predicted_docs=observed,
                failed=(preferred not in {"a", "b"}),
            )
        )

    cases_count = _safe_int(summary.get("cases"), len(cases))
    if cases_count <= 0:
        cases_count = len(cases)
    failures = _safe_int(summary.get("undecided"), sum(1 for case in cases if case.failed))
    timestamp = str(payload.get("timestamp", "")).strip()
    if not timestamp:
        try:
            timestamp = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
        except Exception:
            timestamp = ""

    return RunEntry(
        run_type="llmcompare",
        run_name=str(payload.get("run_name") or path.stem.replace(".summary", "")),
        timestamp=timestamp,
        suite=str(payload.get("suite", "")),
        path=path,
        cases_count=cases_count,
        micro_f1=_safe_float(summary.get("preference_b_rate")),
        macro_f1=_safe_float(summary.get("preference_a_rate")),
        hit_at_k=_safe_float(summary.get("parsed_rate")),
        map_value=_safe_float(summary.get("avg_confidence")),
        mrr=_safe_float(summary.get("win_gap")),
        ndcg=_safe_float(summary.get("undecided_rate")),
        failure_cases=failures,
        cases=cases,
    )


def _load_run_entry(path: pathlib.Path) -> RunEntry | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None

    eval_type = str(payload.get("evaluation_type", "")).strip().casefold()
    if eval_type == "factcheck":
        return _load_factcheck_run_entry(path, payload)
    if eval_type == "glossary":
        return _load_glossary_run_entry(path, payload)
    if eval_type == "judge_pairwise":
        return _load_judge_run_entry(path, payload)
    if eval_type == "llm_compare_judge":
        return _load_llmcompare_run_entry(path, payload)
    if isinstance(payload.get("summary"), dict):
        return _load_rag_run_entry(path, payload)
    if isinstance(payload.get("macro"), dict) and "pass_rate" in payload:
        return _load_pdf_run_entry(path, payload)
    return None


def discover_runs(root_dir: pathlib.Path) -> list[RunEntry]:
    if not root_dir.exists():
        return []

    runs: list[RunEntry] = []
    for path in sorted(root_dir.rglob("*.summary.json")):
        run = _load_run_entry(path)
        if run is not None:
            runs.append(run)

    runs.sort(key=lambda r: (r.timestamp, r.run_name), reverse=True)
    return runs


def _score_color(value: float) -> QColor:
    v = max(0.0, min(1.0, float(value)))
    if v >= 0.70:
        return QColor("#1B4332")
    if v >= 0.45:
        return QColor("#5C4B1A")
    return QColor("#6A1B1A")


def _short_name(text: str, max_len: int = 18) -> str:
    t = str(text)
    if len(t) <= max_len:
        return t
    return f"{t[: max_len - 1]}…"


def _failure_count(run: RunEntry) -> int:
    if run.failure_cases > 0:
        return run.failure_cases
    return sum(1 for case in run.cases if case.failed)


def _failure_rate(run: RunEntry) -> float:
    if run.cases_count <= 0:
        return 0.0
    return _failure_count(run) / float(run.cases_count)


def _aggregate_labels(cases: list[CaseEntry]) -> list[LabelStat]:
    buckets: dict[str, list[CaseEntry]] = {}
    for case in cases:
        labels = case.labels or ["__unlabeled__"]
        for label in labels:
            buckets.setdefault(label, []).append(case)

    out: list[LabelStat] = []
    for label, items in buckets.items():
        cases_n = len(items)
        failures = sum(1 for case in items if case.failed)
        out.append(
            LabelStat(
                label=label,
                cases=cases_n,
                macro_f1=statistics.fmean(case.f1 for case in items) if items else 0.0,
                macro_hit=statistics.fmean(case.hit_at_k for case in items) if items else 0.0,
                macro_precision=(
                    statistics.fmean(case.precision for case in items) if items else 0.0
                ),
                macro_recall=(
                    statistics.fmean(case.recall for case in items) if items else 0.0
                ),
                failures=failures,
                failure_rate=(failures / cases_n) if cases_n else 0.0,
            )
        )

    out.sort(key=lambda s: s.label.casefold())
    return out


def _set_text_item(table: QTableWidget, row: int, col: int, text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    table.setItem(row, col, item)
    return item


def _set_numeric_item(
    table: QTableWidget,
    row: int,
    col: int,
    value: float,
    digits: int = 3,
    heatmap: bool = False,
) -> QTableWidgetItem:
    item = QTableWidgetItem(f"{value:.{digits}f}")
    item.setData(Qt.ItemDataRole.UserRole, float(value))
    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    if heatmap:
        item.setBackground(_score_color(value))
        item.setForeground(QColor("#F8F9FA"))
    table.setItem(row, col, item)
    return item


class MetricCard(QFrame):
    def __init__(self, title: str, accent: str):
        super().__init__()
        self.setObjectName("MetricCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)

        self._title = QLabel(title)
        self._title.setStyleSheet("font-size: 11px; color: #A6ADC8;")
        self._value = QLabel("—")
        self._value.setStyleSheet(
            f"font-size: 24px; font-weight: 700; color: {accent}; letter-spacing: 0.5px;"
        )
        self._sub = QLabel("")
        self._sub.setStyleSheet("font-size: 10px; color: #6C7086;")

        layout.addWidget(self._title)
        layout.addWidget(self._value)
        layout.addWidget(self._sub)

    def set_value(self, value_text: str, sub_text: str = "") -> None:
        self._value.setText(value_text)
        self._sub.setText(sub_text)


class TestStudioDashboard(QMainWindow):
    def __init__(self, root_dir: pathlib.Path):
        super().__init__()
        self.setWindowTitle(
            "Test Studio Dashboard (RAG + PDF + Glossary + Fact-Check + Judge + LLM-Compare)"
        )
        self.resize(1680, 980)

        self._all_runs: list[RunEntry] = []
        self._visible_runs: list[RunEntry] = []
        self._runs_by_path: dict[str, RunEntry] = {}

        self._root_edit = QLineEdit(str(root_dir))
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filter by run name or suite path…")
        self._type_selector = QComboBox()
        self._type_selector.addItem("All", "all")
        self._type_selector.addItem("RAG", "rag")
        self._type_selector.addItem("PDF", "pdf")
        self._type_selector.addItem("Glossary", "glossary")
        self._type_selector.addItem("Fact-Check", "factcheck")
        self._type_selector.addItem("Judge", "judge")
        self._type_selector.addItem("LLM Compare", "llmcompare")
        self._common_case_cb = QCheckBox("Nur gemeinsame Case-Nummern")
        self._common_case_cb.setChecked(False)
        self._status_lbl = QLabel("")

        self._run_table = QTableWidget(0, 10)

        self._comparison_table = QTableWidget(0, 11)
        self._case_run_selector = QComboBox()
        self._case_label_selector = QComboBox()
        self._case_query_filter = QLineEdit()
        self._case_table = QTableWidget(0, 9)
        self._label_scope_selector = QComboBox()
        self._label_mode_selector = QComboBox()
        self._label_filter_edit = QLineEdit()
        self._label_table = QTableWidget(0, 9)

        self._run_metric_chart = QChartView()
        self._failure_chart = QChartView()
        self._label_chart = QChartView()
        self._strength_table = QTableWidget(0, 4)
        self._weakness_table = QTableWidget(0, 4)

        self._card_loaded = MetricCard("Loaded Runs", "#89B4FA")
        self._card_visible = MetricCard("Visible Runs", "#B4BEFE")
        self._card_selected = MetricCard("Selected Runs", "#CBA6F7")
        self._card_macro = MetricCard("Mean Primary Score", "#A6E3A1")
        self._card_hit = MetricCard("Mean Structure Score", "#F9E2AF")
        self._card_fail = MetricCard("Mean Failure Rate", "#F38BA8")

        # Runner controls (Run All-Tests)
        self._runner_dialog: QDialog | None = None
        self._runner_tabs = QTabWidget()
        self._runner_log = QPlainTextEdit()
        self._runner_log.setReadOnly(True)
        self._runner_log.setPlaceholderText("Runner log output...")
        self._runner_proc: QProcess | None = None
        self._runner_queue: list[tuple[str, list[str]]] = []
        self._runner_active_name = ""
        self._runner_active_cmd: list[str] = []

        self._fb_storage_edit = QLineEdit("runs/feedback")
        self._fb_out_edit = QLineEdit("runs/feedback/generated")
        self._fb_run_name_edit = QLineEdit("")
        self._fb_include_unaccepted_cb = QCheckBox("Entwürfe mit exportieren")
        self._fb_include_unaccepted_cb.setChecked(False)

        self._rag_suite_edit = QLineEdit("scripts/examples/rag_suite.example.json")
        self._rag_out_edit = QLineEdit("runs/rag_eval")
        self._rag_name_edit = QLineEdit("gui_rag")
        self._rag_labels_edit = QLineEdit("")
        self._rag_topk_spin = QSpinBox()
        self._rag_topk_spin.setRange(0, 200)
        self._rag_topk_spin.setValue(0)
        self._rag_set_edit = QLineEdit("")
        self._rag_model_edit = QLineEdit("")
        self._rag_ctx_spin = QSpinBox()
        self._rag_ctx_spin.setRange(256, 65536)
        self._rag_ctx_spin.setValue(4096)
        self._rag_gpu_spin = QSpinBox()
        self._rag_gpu_spin.setRange(-1, 1024)
        self._rag_gpu_spin.setValue(0)
        self._rag_threads_spin = QSpinBox()
        self._rag_threads_spin.setRange(0, 256)
        self._rag_threads_spin.setValue(0)
        self._rag_log_combo = QComboBox()
        self._rag_log_combo.addItems(["INFO", "DEBUG", "WARNING", "ERROR"])

        self._pdf_suite_edit = QLineEdit("scripts/examples/pdf_suite.example.json")
        self._pdf_out_edit = QLineEdit("runs/pdf_eval")
        self._pdf_name_edit = QLineEdit("gui_pdf")
        self._pdf_labels_edit = QLineEdit("")
        self._pdf_max_cases_spin = QSpinBox()
        self._pdf_max_cases_spin.setRange(0, 10000)
        self._pdf_max_cases_spin.setValue(0)
        self._pdf_set_edit = QLineEdit("")
        self._pdf_log_combo = QComboBox()
        self._pdf_log_combo.addItems(["INFO", "DEBUG", "WARNING", "ERROR"])

        self._gloss_suite_edit = QLineEdit("scripts/examples/glossary_suite.example.json")
        self._gloss_out_edit = QLineEdit("runs/glossary_eval")
        self._gloss_name_edit = QLineEdit("gui_glossary")
        self._gloss_labels_edit = QLineEdit("")
        self._gloss_max_cases_spin = QSpinBox()
        self._gloss_max_cases_spin.setRange(0, 10000)
        self._gloss_max_cases_spin.setValue(0)
        self._gloss_model_edit = QLineEdit("")
        self._gloss_ctx_spin = QSpinBox()
        self._gloss_ctx_spin.setRange(256, 65536)
        self._gloss_ctx_spin.setValue(4096)
        self._gloss_gpu_spin = QSpinBox()
        self._gloss_gpu_spin.setRange(-1, 1024)
        self._gloss_gpu_spin.setValue(0)
        self._gloss_threads_spin = QSpinBox()
        self._gloss_threads_spin.setRange(0, 256)
        self._gloss_threads_spin.setValue(0)
        self._gloss_max_terms_spin = QSpinBox()
        self._gloss_max_terms_spin.setRange(0, 512)
        self._gloss_max_terms_spin.setValue(0)
        self._gloss_ctx_chars_spin = QSpinBox()
        self._gloss_ctx_chars_spin.setRange(0, 500000)
        self._gloss_ctx_chars_spin.setValue(0)
        self._gloss_recall_spin = QDoubleSpinBox()
        self._gloss_recall_spin.setRange(-1.0, 1.0)
        self._gloss_recall_spin.setSingleStep(0.05)
        self._gloss_recall_spin.setDecimals(2)
        self._gloss_recall_spin.setValue(-1.0)
        self._gloss_set_edit = QLineEdit("")
        self._gloss_prompts_edit = QLineEdit("")
        self._gloss_log_combo = QComboBox()
        self._gloss_log_combo.addItems(["INFO", "DEBUG", "WARNING", "ERROR"])

        self._fact_suite_edit = QLineEdit("scripts/examples/factcheck_suite.3stage.json")
        self._fact_out_edit = QLineEdit("runs/factcheck_eval")
        self._fact_name_edit = QLineEdit("gui_factcheck")
        self._fact_labels_edit = QLineEdit("")
        self._fact_max_cases_spin = QSpinBox()
        self._fact_max_cases_spin.setRange(0, 10000)
        self._fact_max_cases_spin.setValue(0)
        self._fact_mode_combo = QComboBox()
        self._fact_mode_combo.addItems(["all", "extract", "verify", "full"])
        self._fact_model_edit = QLineEdit("")
        self._fact_ctx_spin = QSpinBox()
        self._fact_ctx_spin.setRange(256, 65536)
        self._fact_ctx_spin.setValue(4096)
        self._fact_gpu_spin = QSpinBox()
        self._fact_gpu_spin.setRange(-1, 1024)
        self._fact_gpu_spin.setValue(0)
        self._fact_threads_spin = QSpinBox()
        self._fact_threads_spin.setRange(0, 256)
        self._fact_threads_spin.setValue(0)
        self._fact_prompts_edit = QLineEdit("")
        self._fact_extract_thr = QDoubleSpinBox()
        self._fact_extract_thr.setRange(-1.0, 1.0)
        self._fact_extract_thr.setSingleStep(0.05)
        self._fact_extract_thr.setDecimals(2)
        self._fact_extract_thr.setValue(-1.0)
        self._fact_verify_thr = QDoubleSpinBox()
        self._fact_verify_thr.setRange(-1.0, 1.0)
        self._fact_verify_thr.setSingleStep(0.05)
        self._fact_verify_thr.setDecimals(2)
        self._fact_verify_thr.setValue(-1.0)
        self._fact_full_thr = QDoubleSpinBox()
        self._fact_full_thr.setRange(-1.0, 1.0)
        self._fact_full_thr.setSingleStep(0.05)
        self._fact_full_thr.setDecimals(2)
        self._fact_full_thr.setValue(-1.0)
        self._fact_source_chars_spin = QSpinBox()
        self._fact_source_chars_spin.setRange(0, 500000)
        self._fact_source_chars_spin.setValue(0)
        self._fact_target_chars_spin = QSpinBox()
        self._fact_target_chars_spin.setRange(0, 500000)
        self._fact_target_chars_spin.setValue(0)
        self._fact_max_verify_spin = QSpinBox()
        self._fact_max_verify_spin.setRange(0, 10000)
        self._fact_max_verify_spin.setValue(0)
        self._fact_extract_tokens_spin = QSpinBox()
        self._fact_extract_tokens_spin.setRange(64, 8192)
        self._fact_extract_tokens_spin.setValue(1024)
        self._fact_verify_tokens_spin = QSpinBox()
        self._fact_verify_tokens_spin.setRange(64, 2048)
        self._fact_verify_tokens_spin.setValue(220)
        self._fact_temp_spin = QDoubleSpinBox()
        self._fact_temp_spin.setRange(0.0, 2.0)
        self._fact_temp_spin.setSingleStep(0.05)
        self._fact_temp_spin.setDecimals(2)
        self._fact_temp_spin.setValue(0.70)
        self._fact_set_edit = QLineEdit("")
        self._fact_log_combo = QComboBox()
        self._fact_log_combo.addItems(["INFO", "DEBUG", "WARNING", "ERROR"])

        self._judge_suite_edit = QLineEdit("scripts/examples/judge_suite.example.json")
        self._judge_out_edit = QLineEdit("runs/judge_eval")
        self._judge_name_edit = QLineEdit("gui_judge")
        self._judge_labels_edit = QLineEdit("")
        self._judge_max_cases_spin = QSpinBox()
        self._judge_max_cases_spin.setRange(0, 10000)
        self._judge_max_cases_spin.setValue(0)
        self._judge_model_edit = QLineEdit("")
        self._judge_ctx_spin = QSpinBox()
        self._judge_ctx_spin.setRange(256, 65536)
        self._judge_ctx_spin.setValue(4096)
        self._judge_gpu_spin = QSpinBox()
        self._judge_gpu_spin.setRange(-1, 1024)
        self._judge_gpu_spin.setValue(0)
        self._judge_threads_spin = QSpinBox()
        self._judge_threads_spin.setRange(0, 256)
        self._judge_threads_spin.setValue(0)
        judge_prompts_default = "prompts/defaults.json"
        self._judge_prompts_edit = QLineEdit(
            judge_prompts_default
            if (_SCRIPT_DIR.parent / judge_prompts_default).exists()
            else ""
        )
        self._judge_prompt_key_edit = QLineEdit("judge_pairwise_system")
        self._judge_prompt_file_edit = QLineEdit("")
        self._judge_max_tokens_spin = QSpinBox()
        self._judge_max_tokens_spin.setRange(32, 8192)
        self._judge_max_tokens_spin.setValue(192)
        self._judge_temp_spin = QDoubleSpinBox()
        self._judge_temp_spin.setRange(0.0, 2.0)
        self._judge_temp_spin.setSingleStep(0.05)
        self._judge_temp_spin.setDecimals(2)
        self._judge_temp_spin.setValue(0.00)
        self._judge_top_p_spin = QDoubleSpinBox()
        self._judge_top_p_spin.setRange(0.0, 1.0)
        self._judge_top_p_spin.setSingleStep(0.05)
        self._judge_top_p_spin.setDecimals(2)
        self._judge_top_p_spin.setValue(1.00)
        self._judge_repeat_penalty_spin = QDoubleSpinBox()
        self._judge_repeat_penalty_spin.setRange(0.5, 2.0)
        self._judge_repeat_penalty_spin.setSingleStep(0.01)
        self._judge_repeat_penalty_spin.setDecimals(2)
        self._judge_repeat_penalty_spin.setValue(1.05)
        self._judge_seed_spin = QSpinBox()
        self._judge_seed_spin.setRange(-1, 2147483647)
        self._judge_seed_spin.setValue(-1)
        self._judge_prompt_chars_spin = QSpinBox()
        self._judge_prompt_chars_spin.setRange(0, 500000)
        self._judge_prompt_chars_spin.setValue(0)
        self._judge_answer_chars_spin = QSpinBox()
        self._judge_answer_chars_spin.setRange(0, 500000)
        self._judge_answer_chars_spin.setValue(0)
        self._judge_threshold_spin = QDoubleSpinBox()
        self._judge_threshold_spin.setRange(-1.0, 1.0)
        self._judge_threshold_spin.setSingleStep(0.05)
        self._judge_threshold_spin.setDecimals(2)
        self._judge_threshold_spin.setValue(-1.0)
        self._judge_set_edit = QLineEdit("")
        self._judge_artifacts_combo = QComboBox()
        self._judge_artifacts_combo.addItem("Default", "default")
        self._judge_artifacts_combo.addItem("Write artifacts", "on")
        self._judge_artifacts_combo.addItem("No artifacts", "off")
        self._judge_log_combo = QComboBox()
        self._judge_log_combo.addItems(["INFO", "DEBUG", "WARNING", "ERROR"])

        self._cmp_suite_edit = QLineEdit("scripts/examples/llm_compare_suite.example.json")
        self._cmp_out_edit = QLineEdit("runs/llm_compare_eval")
        self._cmp_name_edit = QLineEdit("gui_llm_compare")
        self._cmp_labels_edit = QLineEdit("")
        self._cmp_max_cases_spin = QSpinBox()
        self._cmp_max_cases_spin.setRange(0, 10000)
        self._cmp_max_cases_spin.setValue(0)
        cmp_prompts_default = "prompts/defaults.json"
        self._cmp_prompts_edit = QLineEdit(
            cmp_prompts_default
            if (_SCRIPT_DIR.parent / cmp_prompts_default).exists()
            else ""
        )
        self._cmp_candidate_prompt_key_edit = QLineEdit("llm_compare_candidate_system")
        self._cmp_candidate_prompt_file_edit = QLineEdit("")
        self._cmp_judge_prompt_key_edit = QLineEdit("judge_pairwise_system")
        self._cmp_judge_prompt_file_edit = QLineEdit("")
        self._cmp_prompt_chars_spin = QSpinBox()
        self._cmp_prompt_chars_spin.setRange(0, 500000)
        self._cmp_prompt_chars_spin.setValue(0)
        self._cmp_threshold_gap_spin = QDoubleSpinBox()
        self._cmp_threshold_gap_spin.setRange(-1.0, 1.0)
        self._cmp_threshold_gap_spin.setSingleStep(0.01)
        self._cmp_threshold_gap_spin.setDecimals(2)
        self._cmp_threshold_gap_spin.setValue(-1.0)
        self._cmp_swap_combo = QComboBox()
        self._cmp_swap_combo.addItem("Swap order enabled", "on")
        self._cmp_swap_combo.addItem("Swap order disabled", "off")
        self._cmp_a_label_edit = QLineEdit("A")
        self._cmp_a_model_edit = QLineEdit("")
        self._cmp_a_ctx_spin = QSpinBox()
        self._cmp_a_ctx_spin.setRange(256, 65536)
        self._cmp_a_ctx_spin.setValue(4096)
        self._cmp_a_gpu_spin = QSpinBox()
        self._cmp_a_gpu_spin.setRange(-1, 1024)
        self._cmp_a_gpu_spin.setValue(0)
        self._cmp_a_threads_spin = QSpinBox()
        self._cmp_a_threads_spin.setRange(0, 256)
        self._cmp_a_threads_spin.setValue(0)
        self._cmp_a_tokens_spin = QSpinBox()
        self._cmp_a_tokens_spin.setRange(32, 8192)
        self._cmp_a_tokens_spin.setValue(512)
        self._cmp_a_temp_spin = QDoubleSpinBox()
        self._cmp_a_temp_spin.setRange(0.0, 2.0)
        self._cmp_a_temp_spin.setSingleStep(0.05)
        self._cmp_a_temp_spin.setDecimals(2)
        self._cmp_a_temp_spin.setValue(0.20)
        self._cmp_a_top_p_spin = QDoubleSpinBox()
        self._cmp_a_top_p_spin.setRange(0.0, 1.0)
        self._cmp_a_top_p_spin.setSingleStep(0.05)
        self._cmp_a_top_p_spin.setDecimals(2)
        self._cmp_a_top_p_spin.setValue(0.95)
        self._cmp_a_repeat_spin = QDoubleSpinBox()
        self._cmp_a_repeat_spin.setRange(0.5, 2.0)
        self._cmp_a_repeat_spin.setSingleStep(0.01)
        self._cmp_a_repeat_spin.setDecimals(2)
        self._cmp_a_repeat_spin.setValue(1.05)
        self._cmp_a_seed_spin = QSpinBox()
        self._cmp_a_seed_spin.setRange(-1, 2147483647)
        self._cmp_a_seed_spin.setValue(-1)
        self._cmp_b_label_edit = QLineEdit("B")
        self._cmp_b_model_edit = QLineEdit("")
        self._cmp_b_ctx_spin = QSpinBox()
        self._cmp_b_ctx_spin.setRange(256, 65536)
        self._cmp_b_ctx_spin.setValue(4096)
        self._cmp_b_gpu_spin = QSpinBox()
        self._cmp_b_gpu_spin.setRange(-1, 1024)
        self._cmp_b_gpu_spin.setValue(0)
        self._cmp_b_threads_spin = QSpinBox()
        self._cmp_b_threads_spin.setRange(0, 256)
        self._cmp_b_threads_spin.setValue(0)
        self._cmp_b_tokens_spin = QSpinBox()
        self._cmp_b_tokens_spin.setRange(32, 8192)
        self._cmp_b_tokens_spin.setValue(512)
        self._cmp_b_temp_spin = QDoubleSpinBox()
        self._cmp_b_temp_spin.setRange(0.0, 2.0)
        self._cmp_b_temp_spin.setSingleStep(0.05)
        self._cmp_b_temp_spin.setDecimals(2)
        self._cmp_b_temp_spin.setValue(0.20)
        self._cmp_b_top_p_spin = QDoubleSpinBox()
        self._cmp_b_top_p_spin.setRange(0.0, 1.0)
        self._cmp_b_top_p_spin.setSingleStep(0.05)
        self._cmp_b_top_p_spin.setDecimals(2)
        self._cmp_b_top_p_spin.setValue(0.95)
        self._cmp_b_repeat_spin = QDoubleSpinBox()
        self._cmp_b_repeat_spin.setRange(0.5, 2.0)
        self._cmp_b_repeat_spin.setSingleStep(0.01)
        self._cmp_b_repeat_spin.setDecimals(2)
        self._cmp_b_repeat_spin.setValue(1.05)
        self._cmp_b_seed_spin = QSpinBox()
        self._cmp_b_seed_spin.setRange(-1, 2147483647)
        self._cmp_b_seed_spin.setValue(-1)
        self._cmp_j_model_edit = QLineEdit("")
        self._cmp_j_ctx_spin = QSpinBox()
        self._cmp_j_ctx_spin.setRange(256, 65536)
        self._cmp_j_ctx_spin.setValue(4096)
        self._cmp_j_gpu_spin = QSpinBox()
        self._cmp_j_gpu_spin.setRange(-1, 1024)
        self._cmp_j_gpu_spin.setValue(0)
        self._cmp_j_threads_spin = QSpinBox()
        self._cmp_j_threads_spin.setRange(0, 256)
        self._cmp_j_threads_spin.setValue(0)
        self._cmp_j_tokens_spin = QSpinBox()
        self._cmp_j_tokens_spin.setRange(32, 8192)
        self._cmp_j_tokens_spin.setValue(192)
        self._cmp_j_temp_spin = QDoubleSpinBox()
        self._cmp_j_temp_spin.setRange(0.0, 2.0)
        self._cmp_j_temp_spin.setSingleStep(0.05)
        self._cmp_j_temp_spin.setDecimals(2)
        self._cmp_j_temp_spin.setValue(0.00)
        self._cmp_j_top_p_spin = QDoubleSpinBox()
        self._cmp_j_top_p_spin.setRange(0.0, 1.0)
        self._cmp_j_top_p_spin.setSingleStep(0.05)
        self._cmp_j_top_p_spin.setDecimals(2)
        self._cmp_j_top_p_spin.setValue(1.00)
        self._cmp_j_repeat_spin = QDoubleSpinBox()
        self._cmp_j_repeat_spin.setRange(0.5, 2.0)
        self._cmp_j_repeat_spin.setSingleStep(0.01)
        self._cmp_j_repeat_spin.setDecimals(2)
        self._cmp_j_repeat_spin.setValue(1.05)
        self._cmp_j_seed_spin = QSpinBox()
        self._cmp_j_seed_spin.setRange(-1, 2147483647)
        self._cmp_j_seed_spin.setValue(-1)
        self._cmp_set_edit = QLineEdit("")
        self._cmp_artifacts_combo = QComboBox()
        self._cmp_artifacts_combo.addItem("Default", "default")
        self._cmp_artifacts_combo.addItem("Write artifacts", "on")
        self._cmp_artifacts_combo.addItem("No artifacts", "off")
        self._cmp_log_combo = QComboBox()
        self._cmp_log_combo.addItems(["INFO", "DEBUG", "WARNING", "ERROR"])

        self._build_ui()
        self.reload_runs()

    def _build_ui(self) -> None:
        style = """
            QMainWindow, QDialog { background: #11131A; }
            QWidget { color: #CDD6F4; font-family: 'Noto Sans', 'Segoe UI', sans-serif; }
            QFrame#MetricCard {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                            stop:0 #1A1D2A, stop:1 #141723);
                border: 1px solid #313244;
                border-radius: 10px;
            }
            QLineEdit, QComboBox {
                background: #181B28;
                border: 1px solid #313244;
                border-radius: 6px;
                padding: 5px 8px;
            }
            QPushButton {
                background: #313244;
                border: none;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: 600;
            }
            QPushButton:hover { background: #45475A; }
            QTableWidget {
                background: #171A25;
                gridline-color: #2A2E3D;
                border: 1px solid #2A2E3D;
                border-radius: 8px;
            }
            QHeaderView::section {
                background: #222638;
                color: #BAC2DE;
                border: none;
                border-right: 1px solid #2A2E3D;
                border-bottom: 1px solid #2A2E3D;
                padding: 6px;
                font-size: 11px;
            }
            QTabWidget::pane { border: 1px solid #2A2E3D; border-radius: 8px; }
            QTabBar::tab {
                background: #1A1D2A;
                color: #7F849C;
                border: 1px solid #2A2E3D;
                padding: 6px 10px;
                margin-right: 2px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }
            QTabBar::tab:selected { color: #CDD6F4; background: #222638; }
            QPlainTextEdit {
                background: #171A25;
                border: 1px solid #2A2E3D;
                border-radius: 8px;
            }
            """
        self.setStyleSheet(style)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        browse_btn = QPushButton("Browse…")
        reload_btn = QPushButton("Reload")
        open_tests_btn = QPushButton("Tests…")
        run_all_toolbar_btn = QPushButton("Run All-Tests")
        toolbar.addWidget(QLabel("Runs root:"))
        toolbar.addWidget(self._root_edit, 1)
        toolbar.addWidget(browse_btn)
        toolbar.addWidget(reload_btn)
        toolbar.addWidget(open_tests_btn)
        toolbar.addWidget(run_all_toolbar_btn)
        layout.addLayout(toolbar)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Run filter:"))
        filter_row.addWidget(self._filter_edit, 1)
        filter_row.addWidget(QLabel("Type:"))
        filter_row.addWidget(self._type_selector)
        filter_row.addWidget(self._common_case_cb)
        layout.addLayout(filter_row)

        self._status_lbl.setStyleSheet("color: #7F849C; font-size: 11px;")
        layout.addWidget(self._status_lbl)

        card_row = QHBoxLayout()
        card_row.setSpacing(8)
        for card in (
            self._card_loaded,
            self._card_visible,
            self._card_selected,
            self._card_macro,
            self._card_hit,
            self._card_fail,
        ):
            card_row.addWidget(card, 1)
        layout.addLayout(card_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter, 1)

        self._setup_run_table()
        splitter.addWidget(self._run_table)

        tabs = QTabWidget()
        tabs.addTab(self._build_visual_tab(), "Visuals")
        tabs.addTab(self._build_comparison_tab(), "Vergleich")
        tabs.addTab(self._build_case_tab(), "Case View")
        tabs.addTab(self._build_label_tab(), "Label Analyse")
        splitter.addWidget(tabs)
        splitter.setSizes([620, 1050])

        browse_btn.clicked.connect(self._browse_root)
        reload_btn.clicked.connect(self.reload_runs)
        open_tests_btn.clicked.connect(self._open_runner_dialog)
        run_all_toolbar_btn.clicked.connect(self._open_and_run_all_tests)
        self._filter_edit.textChanged.connect(self._apply_filter)
        self._type_selector.currentIndexChanged.connect(self._apply_filter)
        self._common_case_cb.stateChanged.connect(self._refresh_all_views)
        self._run_table.itemSelectionChanged.connect(self._on_run_selection_changed)

        self._case_run_selector.currentIndexChanged.connect(self._on_case_run_changed)
        self._case_label_selector.currentIndexChanged.connect(self._refresh_case_table)
        self._case_query_filter.textChanged.connect(self._refresh_case_table)

        self._label_scope_selector.currentIndexChanged.connect(self._refresh_label_table)
        self._label_mode_selector.currentIndexChanged.connect(self._refresh_label_table)
        self._label_filter_edit.textChanged.connect(self._refresh_label_table)

    def _setup_run_table(self) -> None:
        self._configure_run_table_headers("mixed")
        self._run_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._run_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self._run_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._run_table.setSortingEnabled(True)

    def _build_visual_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        chart_split = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(chart_split, 1)

        top_row = QSplitter(Qt.Orientation.Horizontal)
        top_row.addWidget(self._prepare_chart_view(self._run_metric_chart))
        top_row.addWidget(self._prepare_chart_view(self._failure_chart))
        top_row.setSizes([500, 500])
        chart_split.addWidget(top_row)

        bottom_row = QSplitter(Qt.Orientation.Horizontal)
        bottom_row.addWidget(self._prepare_chart_view(self._label_chart))

        insight_wrap = QWidget()
        insight_layout = QVBoxLayout(insight_wrap)
        insight_layout.setContentsMargins(0, 0, 0, 0)
        insight_layout.setSpacing(6)
        insight_layout.addWidget(QLabel("Top labels (works)"))
        self._setup_insight_table(self._strength_table)
        insight_layout.addWidget(self._strength_table, 1)
        insight_layout.addWidget(QLabel("Weak labels (needs work)"))
        self._setup_insight_table(self._weakness_table)
        insight_layout.addWidget(self._weakness_table, 1)
        bottom_row.addWidget(insight_wrap)
        bottom_row.setSizes([540, 440])

        chart_split.addWidget(bottom_row)
        chart_split.setSizes([360, 420])
        return page

    def _prepare_chart_view(self, view: QChartView) -> QChartView:
        view.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        view.setMinimumHeight(220)
        self._set_empty_chart(view, "Waiting for data", "Select runs to populate chart")
        return view

    def _setup_insight_table(self, table: QTableWidget) -> None:
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["Label", "Cases", "Primary", "Fail%"])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setSortingEnabled(True)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

    def _build_comparison_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        hint = QLabel("Wähle links Runs aus. Ohne Auswahl zeigt die Tabelle die ersten sichtbaren Runs.")
        hint.setStyleSheet("color: #7F849C;")
        layout.addWidget(hint)

        self._configure_comparison_headers("mixed")
        self._comparison_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._comparison_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._comparison_table.setSortingEnabled(True)
        layout.addWidget(self._comparison_table, 1)
        return page

    def _build_case_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Run:"))
        controls.addWidget(self._case_run_selector)
        controls.addWidget(QLabel("Label:"))
        controls.addWidget(self._case_label_selector)
        self._case_query_filter.setPlaceholderText("Filter by case id or query…")
        controls.addWidget(self._case_query_filter, 1)
        layout.addLayout(controls)

        self._configure_case_headers("mixed")
        self._case_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._case_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._case_table.setSortingEnabled(True)
        layout.addWidget(self._case_table, 1)
        return page

    def _build_label_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        controls = QHBoxLayout()
        self._label_scope_selector.addItem("Selected runs", "selected")
        self._label_scope_selector.addItem("All visible runs", "all")
        self._label_mode_selector.addItem("Aggregated labels", "aggregate")
        self._label_mode_selector.addItem("Run x label", "per_run")
        self._label_filter_edit.setPlaceholderText("Filter labels…")
        controls.addWidget(QLabel("Scope:"))
        controls.addWidget(self._label_scope_selector)
        controls.addWidget(QLabel("Mode:"))
        controls.addWidget(self._label_mode_selector)
        controls.addWidget(self._label_filter_edit, 1)
        layout.addLayout(controls)

        self._configure_label_headers("mixed")
        self._label_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._label_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._label_table.setSortingEnabled(True)
        layout.addWidget(self._label_table, 1)
        return page

    def _build_runner_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        top_row = QHBoxLayout()
        run_all_btn = QPushButton(
            "Run All-Tests (Export + RAG + PDF + Glossary + Fact-Check + Judge + LLM-Compare)"
        )
        run_all_btn.clicked.connect(self._run_all_tests_clicked)
        stop_btn = QPushButton("Stop")
        stop_btn.clicked.connect(self._stop_runner)
        clear_log_btn = QPushButton("Clear Log")
        clear_log_btn.clicked.connect(self._runner_log.clear)
        top_row.addWidget(run_all_btn)
        top_row.addWidget(stop_btn)
        top_row.addWidget(clear_log_btn)
        top_row.addStretch()
        layout.addLayout(top_row)

        self._runner_tabs.addTab(self._build_runner_feedback_tab(), "Feedback->Suites")
        self._runner_tabs.addTab(self._build_runner_rag_tab(), "RAG")
        self._runner_tabs.addTab(self._build_runner_pdf_tab(), "PDF->Markdown")
        self._runner_tabs.addTab(self._build_runner_glossary_tab(), "Glossary")
        self._runner_tabs.addTab(self._build_runner_factcheck_tab(), "Fact-Check")
        self._runner_tabs.addTab(self._build_runner_judge_tab(), "Judge")
        self._runner_tabs.addTab(self._build_runner_llmcompare_tab(), "LLM-Compare")
        layout.addWidget(self._runner_tabs, 1)

        log_label = QLabel("Runner Output")
        log_label.setStyleSheet("color: #7F849C;")
        layout.addWidget(log_label)
        self._runner_log.setMinimumHeight(220)
        layout.addWidget(self._runner_log, 1)
        return page

    def _ensure_runner_dialog(self) -> None:
        if self._runner_dialog is not None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Run Test Pipelines")
        dialog.resize(980, 760)
        dialog.setStyleSheet(self.styleSheet())
        layout = QVBoxLayout(dialog)
        layout.addWidget(self._build_runner_tab(), 1)
        self._runner_dialog = dialog

    def _open_runner_dialog(self) -> None:
        self._ensure_runner_dialog()
        if self._runner_dialog is None:
            return
        self._runner_dialog.show()
        self._runner_dialog.raise_()
        self._runner_dialog.activateWindow()

    def _open_and_run_all_tests(self) -> None:
        self._open_runner_dialog()
        self._run_all_tests_clicked()

    def _feedback_run_name(self) -> str:
        raw = self._fb_run_name_edit.text().strip()
        if raw:
            return raw
        return "testcase_" + datetime.now().strftime("%Y%m%d_%H%M%S")

    @staticmethod
    def _feedback_suite_path(output_dir: str, run_name: str, suite_id: str) -> str:
        suffix = {
            "rag": ".rag_suite.generated.json",
            "pdf": ".pdf_suite.generated.json",
            "glossary": ".glossary_suite.generated.json",
            "factcheck": ".factcheck_suite.generated.json",
            "judge": ".judge_suite.generated.json",
            "llmcompare": ".llm_compare_suite.generated.json",
        }[suite_id]
        return str((pathlib.Path(output_dir) / f"{run_name}{suffix}").resolve())

    def _apply_feedback_suite_paths(self, run_name: str, output_dir: str) -> None:
        self._rag_suite_edit.setText(
            self._feedback_suite_path(output_dir, run_name, "rag")
        )
        self._pdf_suite_edit.setText(
            self._feedback_suite_path(output_dir, run_name, "pdf")
        )
        self._gloss_suite_edit.setText(
            self._feedback_suite_path(output_dir, run_name, "glossary")
        )
        self._fact_suite_edit.setText(
            self._feedback_suite_path(output_dir, run_name, "factcheck")
        )
        self._judge_suite_edit.setText(
            self._feedback_suite_path(output_dir, run_name, "judge")
        )
        self._cmp_suite_edit.setText(
            self._feedback_suite_path(output_dir, run_name, "llmcompare")
        )

    def _build_feedback_export_command(self, *, run_name: str) -> list[str]:
        cmd = [
            sys.executable,
            str((_SCRIPT_DIR / "feedback_generate_tests.py").resolve()),
            "--storage-dir",
            self._fb_storage_edit.text().strip(),
            "--output-dir",
            self._fb_out_edit.text().strip(),
            "--run-name",
            run_name,
            "--include-unaccepted"
            if self._fb_include_unaccepted_cb.isChecked()
            else "--no-include-unaccepted",
        ]
        return cmd

    def _feedback_case_counts(self) -> dict[str, int]:
        out = {
            "rag": 0,
            "pdf": 0,
            "glossary": 0,
            "factcheck": 0,
            "judge": 0,
            "llmcompare": 0,
        }
        path = pathlib.Path(self._fb_storage_edit.text().strip()).expanduser() / "test_cases.jsonl"
        if not path.exists():
            return out
        include_unaccepted = self._fb_include_unaccepted_cb.isChecked()
        for line in path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except Exception:
                continue
            if not isinstance(row, dict):
                continue
            if not include_unaccepted and not bool(row.get("accepted", False)):
                continue
            sid = str(row.get("suite_type", "")).strip().lower()
            if sid in out:
                out[sid] += 1
        return out

    def _build_runner_feedback_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        form.addRow(
            "Storage dir",
            self._with_browse_button(
                self._fb_storage_edit,
                mode="dir",
                caption="Select feedback storage directory",
            ),
        )
        form.addRow(
            "Output dir",
            self._with_browse_button(
                self._fb_out_edit,
                mode="dir",
                caption="Select generated-suite output directory",
            ),
        )
        form.addRow("Run name", self._fb_run_name_edit)
        form.addRow("Mode", self._fb_include_unaccepted_cb)
        hint = QLabel(
            "Exports accepted testcase registry to six suite files and updates suite paths for the next runs."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #7F849C;")
        form.addRow("", hint)
        layout.addLayout(form)

        row = QHBoxLayout()
        run_btn = QPushButton("Export Feedback->Suites")
        run_btn.clicked.connect(self._run_feedback_export_clicked)
        apply_btn = QPushButton("Apply Suite Paths Only")
        apply_btn.clicked.connect(
            lambda: self._apply_feedback_suite_paths(
                self._feedback_run_name(),
                self._fb_out_edit.text().strip(),
            )
        )
        row.addWidget(run_btn)
        row.addWidget(apply_btn)
        row.addStretch()
        layout.addLayout(row)
        return page

    def _build_runner_rag_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        form.addRow(
            "Suite",
            self._with_browse_button(
                self._rag_suite_edit,
                mode="file",
                caption="Select RAG suite JSON",
                file_filter="JSON (*.json);;All files (*)",
            ),
        )
        form.addRow(
            "Output dir",
            self._with_browse_button(
                self._rag_out_edit,
                mode="dir",
                caption="Select RAG output directory",
            ),
        )
        form.addRow("Run name", self._rag_name_edit)
        form.addRow("Labels", self._rag_labels_edit)
        form.addRow("Top-K (0=default)", self._rag_topk_spin)
        form.addRow("Config overrides (k=v,...)", self._rag_set_edit)
        form.addRow(
            "LLM model (optional)",
            self._with_browse_button(
                self._rag_model_edit,
                mode="file",
                caption="Select LLM model",
                file_filter="GGUF model (*.gguf);;All files (*)",
            ),
        )
        form.addRow("LLM n_ctx", self._rag_ctx_spin)
        form.addRow("LLM gpu layers", self._rag_gpu_spin)
        form.addRow("LLM threads (0=auto)", self._rag_threads_spin)
        form.addRow("Log level", self._rag_log_combo)
        layout.addLayout(form)

        row = QHBoxLayout()
        run_btn = QPushButton("Run RAG Tests")
        run_btn.clicked.connect(self._run_rag_tests_clicked)
        row.addWidget(run_btn)
        row.addStretch()
        layout.addLayout(row)
        return page

    def _build_runner_pdf_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        form.addRow(
            "Suite",
            self._with_browse_button(
                self._pdf_suite_edit,
                mode="file",
                caption="Select PDF suite JSON",
                file_filter="JSON (*.json);;All files (*)",
            ),
        )
        form.addRow(
            "Output dir",
            self._with_browse_button(
                self._pdf_out_edit,
                mode="dir",
                caption="Select PDF output directory",
            ),
        )
        form.addRow("Run name", self._pdf_name_edit)
        form.addRow("Labels", self._pdf_labels_edit)
        form.addRow("Max cases (0=all)", self._pdf_max_cases_spin)
        form.addRow("PDF setting overrides (k=v,...)", self._pdf_set_edit)
        form.addRow("Log level", self._pdf_log_combo)
        layout.addLayout(form)

        row = QHBoxLayout()
        run_btn = QPushButton("Run PDF Tests")
        run_btn.clicked.connect(self._run_pdf_tests_clicked)
        row.addWidget(run_btn)
        row.addStretch()
        layout.addLayout(row)
        return page

    def _build_runner_glossary_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        form.addRow(
            "Suite",
            self._with_browse_button(
                self._gloss_suite_edit,
                mode="file",
                caption="Select glossary suite JSON",
                file_filter="JSON (*.json);;All files (*)",
            ),
        )
        form.addRow(
            "Output dir",
            self._with_browse_button(
                self._gloss_out_edit,
                mode="dir",
                caption="Select glossary output directory",
            ),
        )
        form.addRow("Run name", self._gloss_name_edit)
        form.addRow("Labels", self._gloss_labels_edit)
        form.addRow("Max cases (0=all)", self._gloss_max_cases_spin)
        form.addRow(
            "LLM model (required)",
            self._with_browse_button(
                self._gloss_model_edit,
                mode="file",
                caption="Select glossary LLM model",
                file_filter="GGUF model (*.gguf);;All files (*)",
            ),
        )
        form.addRow("LLM n_ctx", self._gloss_ctx_spin)
        form.addRow("LLM gpu layers", self._gloss_gpu_spin)
        form.addRow("LLM threads (0=auto)", self._gloss_threads_spin)
        form.addRow(
            "Prompt overrides JSON (optional)",
            self._with_browse_button(
                self._gloss_prompts_edit,
                mode="file",
                caption="Select prompt override JSON",
                file_filter="JSON (*.json);;All files (*)",
            ),
        )
        form.addRow("Override max_terms (0=off)", self._gloss_max_terms_spin)
        form.addRow(
            "Override context chars (0=off)",
            self._gloss_ctx_chars_spin,
        )
        form.addRow(
            "Override threshold_recall (-1=off)",
            self._gloss_recall_spin,
        )
        form.addRow("Setting overrides (k=v,...)", self._gloss_set_edit)
        form.addRow("Log level", self._gloss_log_combo)
        layout.addLayout(form)

        row = QHBoxLayout()
        run_btn = QPushButton("Run Glossary Tests")
        run_btn.clicked.connect(self._run_glossary_tests_clicked)
        row.addWidget(run_btn)
        row.addStretch()
        layout.addLayout(row)
        return page

    def _build_runner_factcheck_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        form.addRow(
            "Suite",
            self._with_browse_button(
                self._fact_suite_edit,
                mode="file",
                caption="Select fact-check suite JSON",
                file_filter="JSON (*.json);;All files (*)",
            ),
        )
        form.addRow(
            "Output dir",
            self._with_browse_button(
                self._fact_out_edit,
                mode="dir",
                caption="Select fact-check output directory",
            ),
        )
        form.addRow("Run name", self._fact_name_edit)
        form.addRow("Labels", self._fact_labels_edit)
        form.addRow("Max cases (0=all)", self._fact_max_cases_spin)
        form.addRow("Mode", self._fact_mode_combo)
        form.addRow(
            "LLM model (required)",
            self._with_browse_button(
                self._fact_model_edit,
                mode="file",
                caption="Select fact-check LLM model",
                file_filter="GGUF model (*.gguf);;All files (*)",
            ),
        )
        form.addRow("LLM n_ctx", self._fact_ctx_spin)
        form.addRow("LLM gpu layers", self._fact_gpu_spin)
        form.addRow("LLM threads (0=auto)", self._fact_threads_spin)
        form.addRow(
            "Prompt overrides JSON (optional)",
            self._with_browse_button(
                self._fact_prompts_edit,
                mode="file",
                caption="Select prompt override JSON",
                file_filter="JSON (*.json);;All files (*)",
            ),
        )
        form.addRow("Extract threshold (-1=off)", self._fact_extract_thr)
        form.addRow("Verify threshold (-1=off)", self._fact_verify_thr)
        form.addRow("Full F1 threshold (-1=off)", self._fact_full_thr)
        form.addRow("Source chars override (0=off)", self._fact_source_chars_spin)
        form.addRow("Target chars override (0=off)", self._fact_target_chars_spin)
        form.addRow("Max verify facts override (0=off)", self._fact_max_verify_spin)
        form.addRow("Extract max tokens", self._fact_extract_tokens_spin)
        form.addRow("Verify max tokens", self._fact_verify_tokens_spin)
        form.addRow("Temperature", self._fact_temp_spin)
        form.addRow("Setting overrides (k=v,...)", self._fact_set_edit)
        form.addRow("Log level", self._fact_log_combo)
        layout.addLayout(form)

        row = QHBoxLayout()
        run_btn = QPushButton("Run Fact-Check Tests")
        run_btn.clicked.connect(self._run_factcheck_tests_clicked)
        row.addWidget(run_btn)
        row.addStretch()
        layout.addLayout(row)
        return page

    def _build_runner_judge_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        form.addRow(
            "Suite",
            self._with_browse_button(
                self._judge_suite_edit,
                mode="file",
                caption="Select judge suite JSON",
                file_filter="JSON (*.json);;All files (*)",
            ),
        )
        form.addRow(
            "Output dir",
            self._with_browse_button(
                self._judge_out_edit,
                mode="dir",
                caption="Select judge output directory",
            ),
        )
        form.addRow("Run name", self._judge_name_edit)
        form.addRow("Labels", self._judge_labels_edit)
        form.addRow("Max cases (0=all)", self._judge_max_cases_spin)
        form.addRow(
            "LLM model (required)",
            self._with_browse_button(
                self._judge_model_edit,
                mode="file",
                caption="Select judge LLM model",
                file_filter="GGUF model (*.gguf);;All files (*)",
            ),
        )
        form.addRow("LLM n_ctx", self._judge_ctx_spin)
        form.addRow("LLM gpu layers", self._judge_gpu_spin)
        form.addRow("LLM threads (0=auto)", self._judge_threads_spin)
        form.addRow(
            "Prompt overrides JSON (optional)",
            self._with_browse_button(
                self._judge_prompts_edit,
                mode="file",
                caption="Select judge prompt JSON",
                file_filter="JSON (*.json);;All files (*)",
            ),
        )
        form.addRow("Judge prompt key", self._judge_prompt_key_edit)
        form.addRow(
            "Judge prompt file (optional)",
            self._with_browse_button(
                self._judge_prompt_file_edit,
                mode="file",
                caption="Select judge prompt file",
                file_filter="Text files (*.txt *.md);;All files (*)",
            ),
        )
        form.addRow("Judge max tokens", self._judge_max_tokens_spin)
        form.addRow("Temperature", self._judge_temp_spin)
        form.addRow("Top-p", self._judge_top_p_spin)
        form.addRow("Repeat penalty", self._judge_repeat_penalty_spin)
        form.addRow("Seed (-1=off)", self._judge_seed_spin)
        form.addRow("Prompt max chars override (0=off)", self._judge_prompt_chars_spin)
        form.addRow("Answer max chars override (0=off)", self._judge_answer_chars_spin)
        form.addRow("Threshold accuracy override (-1=off)", self._judge_threshold_spin)
        form.addRow("Setting overrides (k=v,...)", self._judge_set_edit)
        form.addRow("Artifacts", self._judge_artifacts_combo)
        form.addRow("Log level", self._judge_log_combo)
        layout.addLayout(form)

        row = QHBoxLayout()
        run_btn = QPushButton("Run Judge Tests")
        run_btn.clicked.connect(self._run_judge_tests_clicked)
        row.addWidget(run_btn)
        row.addStretch()
        layout.addLayout(row)
        return page

    def _build_runner_llmcompare_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        form.addRow(
            "Suite",
            self._with_browse_button(
                self._cmp_suite_edit,
                mode="file",
                caption="Select LLM compare suite JSON",
                file_filter="JSON (*.json);;All files (*)",
            ),
        )
        form.addRow(
            "Output dir",
            self._with_browse_button(
                self._cmp_out_edit,
                mode="dir",
                caption="Select LLM compare output directory",
            ),
        )
        form.addRow("Run name", self._cmp_name_edit)
        form.addRow("Labels", self._cmp_labels_edit)
        form.addRow("Max cases (0=all)", self._cmp_max_cases_spin)
        form.addRow(
            "Prompts JSON (optional)",
            self._with_browse_button(
                self._cmp_prompts_edit,
                mode="file",
                caption="Select prompt override JSON",
                file_filter="JSON (*.json);;All files (*)",
            ),
        )
        form.addRow("Candidate prompt key", self._cmp_candidate_prompt_key_edit)
        form.addRow(
            "Candidate prompt file (optional)",
            self._with_browse_button(
                self._cmp_candidate_prompt_file_edit,
                mode="file",
                caption="Select candidate prompt file",
                file_filter="Text files (*.txt *.md);;All files (*)",
            ),
        )
        form.addRow("Judge prompt key", self._cmp_judge_prompt_key_edit)
        form.addRow(
            "Judge prompt file (optional)",
            self._with_browse_button(
                self._cmp_judge_prompt_file_edit,
                mode="file",
                caption="Select judge prompt file",
                file_filter="Text files (*.txt *.md);;All files (*)",
            ),
        )
        form.addRow("Prompt max chars override (0=off)", self._cmp_prompt_chars_spin)
        form.addRow("Threshold win gap (-1=off)", self._cmp_threshold_gap_spin)
        form.addRow("Swap order", self._cmp_swap_combo)
        form.addRow("A label", self._cmp_a_label_edit)
        form.addRow(
            "A model (required)",
            self._with_browse_button(
                self._cmp_a_model_edit,
                mode="file",
                caption="Select candidate A model",
                file_filter="GGUF model (*.gguf);;All files (*)",
            ),
        )
        form.addRow("A n_ctx", self._cmp_a_ctx_spin)
        form.addRow("A gpu layers", self._cmp_a_gpu_spin)
        form.addRow("A threads (0=auto)", self._cmp_a_threads_spin)
        form.addRow("A max tokens", self._cmp_a_tokens_spin)
        form.addRow("A temperature", self._cmp_a_temp_spin)
        form.addRow("A top-p", self._cmp_a_top_p_spin)
        form.addRow("A repeat penalty", self._cmp_a_repeat_spin)
        form.addRow("A seed (-1=off)", self._cmp_a_seed_spin)
        form.addRow("B label", self._cmp_b_label_edit)
        form.addRow(
            "B model (required)",
            self._with_browse_button(
                self._cmp_b_model_edit,
                mode="file",
                caption="Select candidate B model",
                file_filter="GGUF model (*.gguf);;All files (*)",
            ),
        )
        form.addRow("B n_ctx", self._cmp_b_ctx_spin)
        form.addRow("B gpu layers", self._cmp_b_gpu_spin)
        form.addRow("B threads (0=auto)", self._cmp_b_threads_spin)
        form.addRow("B max tokens", self._cmp_b_tokens_spin)
        form.addRow("B temperature", self._cmp_b_temp_spin)
        form.addRow("B top-p", self._cmp_b_top_p_spin)
        form.addRow("B repeat penalty", self._cmp_b_repeat_spin)
        form.addRow("B seed (-1=off)", self._cmp_b_seed_spin)
        form.addRow(
            "Judge model (required)",
            self._with_browse_button(
                self._cmp_j_model_edit,
                mode="file",
                caption="Select compare judge model",
                file_filter="GGUF model (*.gguf);;All files (*)",
            ),
        )
        form.addRow("Judge n_ctx", self._cmp_j_ctx_spin)
        form.addRow("Judge gpu layers", self._cmp_j_gpu_spin)
        form.addRow("Judge threads (0=auto)", self._cmp_j_threads_spin)
        form.addRow("Judge max tokens", self._cmp_j_tokens_spin)
        form.addRow("Judge temperature", self._cmp_j_temp_spin)
        form.addRow("Judge top-p", self._cmp_j_top_p_spin)
        form.addRow("Judge repeat penalty", self._cmp_j_repeat_spin)
        form.addRow("Judge seed (-1=off)", self._cmp_j_seed_spin)
        form.addRow("Setting overrides (k=v,...)", self._cmp_set_edit)
        form.addRow("Artifacts", self._cmp_artifacts_combo)
        form.addRow("Log level", self._cmp_log_combo)
        layout.addLayout(form)

        row = QHBoxLayout()
        run_btn = QPushButton("Run LLM-Compare Tests")
        run_btn.clicked.connect(self._run_llmcompare_tests_clicked)
        row.addWidget(run_btn)
        row.addStretch()
        layout.addLayout(row)
        return page

    def _with_browse_button(
        self,
        edit: QLineEdit,
        *,
        mode: str,
        caption: str,
        file_filter: str = "All files (*)",
    ) -> QWidget:
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        btn = QPushButton("...")
        btn.setToolTip(caption)
        btn.setMaximumWidth(34)
        if mode == "dir":
            btn.clicked.connect(
                lambda _=False, e=edit, c=caption: self._choose_dir_for(e, c)
            )
        else:
            btn.clicked.connect(
                lambda _=False, e=edit, c=caption, f=file_filter: self._choose_file_for(
                    e, c, f
                )
            )
        row.addWidget(edit, 1)
        row.addWidget(btn)
        return wrap

    @staticmethod
    def _browse_base_dir(current_text: str) -> str:
        raw = str(current_text or "").strip()
        if not raw:
            return str(pathlib.Path.cwd())
        p = pathlib.Path(raw).expanduser()
        if p.exists():
            if p.is_dir():
                return str(p)
            return str(p.parent)
        if p.suffix:
            return str(p.parent)
        return str(p)

    def _choose_file_for(self, edit: QLineEdit, caption: str, file_filter: str) -> None:
        base = self._browse_base_dir(edit.text())
        selected, _ = QFileDialog.getOpenFileName(
            self._runner_dialog or self,
            caption,
            base,
            file_filter,
        )
        if selected:
            edit.setText(selected)

    def _choose_dir_for(self, edit: QLineEdit, caption: str) -> None:
        base = self._browse_base_dir(edit.text())
        selected = QFileDialog.getExistingDirectory(
            self._runner_dialog or self,
            caption,
            base,
        )
        if selected:
            edit.setText(selected)

    @staticmethod
    def _parse_overrides_csv(text: str) -> list[str]:
        out: list[str] = []
        for part in str(text or "").replace("\n", ",").split(","):
            item = part.strip()
            if item:
                out.append(item)
        return out

    def _resolve_judge_model_path(self) -> str:
        direct = self._judge_model_edit.text().strip()
        if direct:
            return direct

        fallback_candidates = [
            self._fact_model_edit.text().strip(),
            self._gloss_model_edit.text().strip(),
            self._rag_model_edit.text().strip(),
        ]
        for candidate in fallback_candidates:
            if candidate:
                return candidate

        models_dir = (_SCRIPT_DIR.parent / "models").resolve()
        if models_dir.exists():
            for candidate in sorted(models_dir.rglob("*.gguf")):
                return str(candidate)
        return ""

    def _build_rag_command(self) -> list[str]:
        cmd = [
            sys.executable,
            str((_SCRIPT_DIR / "rag_eval.py").resolve()),
            "--suite",
            self._rag_suite_edit.text().strip(),
            "--output-dir",
            self._rag_out_edit.text().strip(),
            "--log-level",
            self._rag_log_combo.currentText().strip(),
        ]
        run_name = self._rag_name_edit.text().strip()
        if run_name:
            cmd.extend(["--run-name", run_name])
        labels = self._rag_labels_edit.text().strip()
        if labels:
            cmd.extend(["--labels", labels])
        top_k = int(self._rag_topk_spin.value())
        if top_k > 0:
            cmd.extend(["--top-k", str(top_k)])
        for item in self._parse_overrides_csv(self._rag_set_edit.text()):
            cmd.extend(["--set", item])
        llm_model = self._rag_model_edit.text().strip()
        if llm_model:
            cmd.extend(["--llm-model", llm_model])
            cmd.extend(["--llm-n-ctx", str(int(self._rag_ctx_spin.value()))])
            cmd.extend(["--llm-gpu-layers", str(int(self._rag_gpu_spin.value()))])
            cmd.extend(["--llm-threads", str(int(self._rag_threads_spin.value()))])
        return cmd

    def _build_pdf_command(self) -> list[str]:
        cmd = [
            sys.executable,
            str((_SCRIPT_DIR / "pdf_eval.py").resolve()),
            "--suite",
            self._pdf_suite_edit.text().strip(),
            "--output-dir",
            self._pdf_out_edit.text().strip(),
            "--log-level",
            self._pdf_log_combo.currentText().strip(),
        ]
        run_name = self._pdf_name_edit.text().strip()
        if run_name:
            cmd.extend(["--run-name", run_name])
        labels = self._pdf_labels_edit.text().strip()
        if labels:
            cmd.extend(["--labels", labels])
        max_cases = int(self._pdf_max_cases_spin.value())
        if max_cases > 0:
            cmd.extend(["--max-cases", str(max_cases)])
        for item in self._parse_overrides_csv(self._pdf_set_edit.text()):
            cmd.extend(["--set", item])
        return cmd

    def _build_glossary_command(self) -> list[str]:
        llm_model = self._gloss_model_edit.text().strip()
        cmd = [
            sys.executable,
            str((_SCRIPT_DIR / "glossary_eval.py").resolve()),
            "--suite",
            self._gloss_suite_edit.text().strip(),
            "--output-dir",
            self._gloss_out_edit.text().strip(),
            "--log-level",
            self._gloss_log_combo.currentText().strip(),
        ]
        run_name = self._gloss_name_edit.text().strip()
        if run_name:
            cmd.extend(["--run-name", run_name])
        labels = self._gloss_labels_edit.text().strip()
        if labels:
            cmd.extend(["--labels", labels])
        max_cases = int(self._gloss_max_cases_spin.value())
        if max_cases > 0:
            cmd.extend(["--max-cases", str(max_cases)])
        if llm_model:
            cmd.extend(["--llm-model", llm_model])
            cmd.extend(["--llm-n-ctx", str(int(self._gloss_ctx_spin.value()))])
            cmd.extend(["--llm-gpu-layers", str(int(self._gloss_gpu_spin.value()))])
            cmd.extend(["--llm-threads", str(int(self._gloss_threads_spin.value()))])
        prompts_json = self._gloss_prompts_edit.text().strip()
        if prompts_json:
            cmd.extend(["--prompts-json", prompts_json])
        if int(self._gloss_max_terms_spin.value()) > 0:
            cmd.extend(["--max-terms", str(int(self._gloss_max_terms_spin.value()))])
        if int(self._gloss_ctx_chars_spin.value()) > 0:
            cmd.extend(
                ["--context-max-chars", str(int(self._gloss_ctx_chars_spin.value()))]
            )
        if float(self._gloss_recall_spin.value()) >= 0.0:
            cmd.extend(["--threshold-recall", f"{float(self._gloss_recall_spin.value()):.2f}"])
        for item in self._parse_overrides_csv(self._gloss_set_edit.text()):
            cmd.extend(["--set", item])
        return cmd

    def _build_factcheck_command(self) -> list[str]:
        llm_model = self._fact_model_edit.text().strip()
        cmd = [
            sys.executable,
            str((_SCRIPT_DIR / "factcheck_eval.py").resolve()),
            "--suite",
            self._fact_suite_edit.text().strip(),
            "--output-dir",
            self._fact_out_edit.text().strip(),
            "--log-level",
            self._fact_log_combo.currentText().strip(),
            "--mode",
            self._fact_mode_combo.currentText().strip(),
            "--extract-max-tokens",
            str(int(self._fact_extract_tokens_spin.value())),
            "--verify-max-tokens",
            str(int(self._fact_verify_tokens_spin.value())),
            "--temperature",
            f"{float(self._fact_temp_spin.value()):.2f}",
        ]
        run_name = self._fact_name_edit.text().strip()
        if run_name:
            cmd.extend(["--run-name", run_name])
        labels = self._fact_labels_edit.text().strip()
        if labels:
            cmd.extend(["--labels", labels])
        max_cases = int(self._fact_max_cases_spin.value())
        if max_cases > 0:
            cmd.extend(["--max-cases", str(max_cases)])
        if llm_model:
            cmd.extend(["--llm-model", llm_model])
            cmd.extend(["--llm-n-ctx", str(int(self._fact_ctx_spin.value()))])
            cmd.extend(["--llm-gpu-layers", str(int(self._fact_gpu_spin.value()))])
            cmd.extend(["--llm-threads", str(int(self._fact_threads_spin.value()))])
        prompts_json = self._fact_prompts_edit.text().strip()
        if prompts_json:
            cmd.extend(["--prompts-json", prompts_json])
        if float(self._fact_extract_thr.value()) >= 0.0:
            cmd.extend(["--threshold-extract-recall", f"{float(self._fact_extract_thr.value()):.2f}"])
        if float(self._fact_verify_thr.value()) >= 0.0:
            cmd.extend(["--threshold-verify-status", f"{float(self._fact_verify_thr.value()):.2f}"])
        if float(self._fact_full_thr.value()) >= 0.0:
            cmd.extend(["--threshold-full-f1", f"{float(self._fact_full_thr.value()):.2f}"])
        if int(self._fact_source_chars_spin.value()) > 0:
            cmd.extend(["--source-max-chars", str(int(self._fact_source_chars_spin.value()))])
        if int(self._fact_target_chars_spin.value()) > 0:
            cmd.extend(["--target-max-chars", str(int(self._fact_target_chars_spin.value()))])
        if int(self._fact_max_verify_spin.value()) > 0:
            cmd.extend(["--max-verify-facts", str(int(self._fact_max_verify_spin.value()))])
        for item in self._parse_overrides_csv(self._fact_set_edit.text()):
            cmd.extend(["--set", item])
        return cmd

    def _build_judge_command(self) -> list[str]:
        llm_model = self._resolve_judge_model_path()
        cmd = [
            sys.executable,
            str((_SCRIPT_DIR / "judge_eval.py").resolve()),
            "--suite",
            self._judge_suite_edit.text().strip(),
            "--output-dir",
            self._judge_out_edit.text().strip(),
            "--log-level",
            self._judge_log_combo.currentText().strip(),
            "--judge-max-tokens",
            str(int(self._judge_max_tokens_spin.value())),
            "--temperature",
            f"{float(self._judge_temp_spin.value()):.2f}",
            "--top-p",
            f"{float(self._judge_top_p_spin.value()):.2f}",
            "--repeat-penalty",
            f"{float(self._judge_repeat_penalty_spin.value()):.2f}",
            "--seed",
            str(int(self._judge_seed_spin.value())),
        ]
        run_name = self._judge_name_edit.text().strip()
        if run_name:
            cmd.extend(["--run-name", run_name])
        labels = self._judge_labels_edit.text().strip()
        if labels:
            cmd.extend(["--labels", labels])
        max_cases = int(self._judge_max_cases_spin.value())
        if max_cases > 0:
            cmd.extend(["--max-cases", str(max_cases)])
        if llm_model:
            if not self._judge_model_edit.text().strip():
                self._judge_model_edit.setText(llm_model)
            cmd.extend(["--llm-model", llm_model])
            cmd.extend(["--llm-n-ctx", str(int(self._judge_ctx_spin.value()))])
            cmd.extend(["--llm-gpu-layers", str(int(self._judge_gpu_spin.value()))])
            cmd.extend(["--llm-threads", str(int(self._judge_threads_spin.value()))])
        prompts_json = self._judge_prompts_edit.text().strip()
        if prompts_json:
            cmd.extend(["--prompts-json", prompts_json])
        prompt_key = self._judge_prompt_key_edit.text().strip()
        if prompt_key:
            cmd.extend(["--judge-prompt-key", prompt_key])
        prompt_file = self._judge_prompt_file_edit.text().strip()
        if prompt_file:
            cmd.extend(["--judge-prompt-file", prompt_file])
        if int(self._judge_prompt_chars_spin.value()) > 0:
            cmd.extend(["--prompt-max-chars", str(int(self._judge_prompt_chars_spin.value()))])
        if int(self._judge_answer_chars_spin.value()) > 0:
            cmd.extend(["--answer-max-chars", str(int(self._judge_answer_chars_spin.value()))])
        if float(self._judge_threshold_spin.value()) >= 0.0:
            cmd.extend(["--threshold-accuracy", f"{float(self._judge_threshold_spin.value()):.2f}"])
        for item in self._parse_overrides_csv(self._judge_set_edit.text()):
            cmd.extend(["--set", item])
        artifacts_mode = str(self._judge_artifacts_combo.currentData() or "default")
        if artifacts_mode == "on":
            cmd.append("--write-artifacts")
        elif artifacts_mode == "off":
            cmd.append("--no-write-artifacts")
        return cmd

    def _build_llmcompare_command(self) -> list[str]:
        cmd = [
            sys.executable,
            str((_SCRIPT_DIR / "llm_compare_eval.py").resolve()),
            "--suite",
            self._cmp_suite_edit.text().strip(),
            "--output-dir",
            self._cmp_out_edit.text().strip(),
            "--log-level",
            self._cmp_log_combo.currentText().strip(),
            "--a-label",
            self._cmp_a_label_edit.text().strip() or "A",
            "--a-max-tokens",
            str(int(self._cmp_a_tokens_spin.value())),
            "--a-temperature",
            f"{float(self._cmp_a_temp_spin.value()):.2f}",
            "--a-top-p",
            f"{float(self._cmp_a_top_p_spin.value()):.2f}",
            "--a-repeat-penalty",
            f"{float(self._cmp_a_repeat_spin.value()):.2f}",
            "--a-seed",
            str(int(self._cmp_a_seed_spin.value())),
            "--b-label",
            self._cmp_b_label_edit.text().strip() or "B",
            "--b-max-tokens",
            str(int(self._cmp_b_tokens_spin.value())),
            "--b-temperature",
            f"{float(self._cmp_b_temp_spin.value()):.2f}",
            "--b-top-p",
            f"{float(self._cmp_b_top_p_spin.value()):.2f}",
            "--b-repeat-penalty",
            f"{float(self._cmp_b_repeat_spin.value()):.2f}",
            "--b-seed",
            str(int(self._cmp_b_seed_spin.value())),
            "--judge-max-tokens",
            str(int(self._cmp_j_tokens_spin.value())),
            "--judge-temperature",
            f"{float(self._cmp_j_temp_spin.value()):.2f}",
            "--judge-top-p",
            f"{float(self._cmp_j_top_p_spin.value()):.2f}",
            "--judge-repeat-penalty",
            f"{float(self._cmp_j_repeat_spin.value()):.2f}",
            "--judge-seed",
            str(int(self._cmp_j_seed_spin.value())),
        ]
        run_name = self._cmp_name_edit.text().strip()
        if run_name:
            cmd.extend(["--run-name", run_name])
        labels = self._cmp_labels_edit.text().strip()
        if labels:
            cmd.extend(["--labels", labels])
        max_cases = int(self._cmp_max_cases_spin.value())
        if max_cases > 0:
            cmd.extend(["--max-cases", str(max_cases)])
        model_a = self._cmp_a_model_edit.text().strip()
        if model_a:
            cmd.extend(["--a-llm-model", model_a])
            cmd.extend(["--a-llm-n-ctx", str(int(self._cmp_a_ctx_spin.value()))])
            cmd.extend(["--a-llm-gpu-layers", str(int(self._cmp_a_gpu_spin.value()))])
            cmd.extend(["--a-llm-threads", str(int(self._cmp_a_threads_spin.value()))])
        model_b = self._cmp_b_model_edit.text().strip()
        if model_b:
            cmd.extend(["--b-llm-model", model_b])
            cmd.extend(["--b-llm-n-ctx", str(int(self._cmp_b_ctx_spin.value()))])
            cmd.extend(["--b-llm-gpu-layers", str(int(self._cmp_b_gpu_spin.value()))])
            cmd.extend(["--b-llm-threads", str(int(self._cmp_b_threads_spin.value()))])
        judge_model = self._cmp_j_model_edit.text().strip()
        if judge_model:
            cmd.extend(["--judge-llm-model", judge_model])
            cmd.extend(["--judge-llm-n-ctx", str(int(self._cmp_j_ctx_spin.value()))])
            cmd.extend(["--judge-llm-gpu-layers", str(int(self._cmp_j_gpu_spin.value()))])
            cmd.extend(["--judge-llm-threads", str(int(self._cmp_j_threads_spin.value()))])
        prompts_json = self._cmp_prompts_edit.text().strip()
        if prompts_json:
            cmd.extend(["--prompts-json", prompts_json])
        candidate_key = self._cmp_candidate_prompt_key_edit.text().strip()
        if candidate_key:
            cmd.extend(["--candidate-prompt-key", candidate_key])
        candidate_prompt_file = self._cmp_candidate_prompt_file_edit.text().strip()
        if candidate_prompt_file:
            cmd.extend(["--candidate-prompt-file", candidate_prompt_file])
        judge_key = self._cmp_judge_prompt_key_edit.text().strip()
        if judge_key:
            cmd.extend(["--judge-prompt-key", judge_key])
        judge_prompt_file = self._cmp_judge_prompt_file_edit.text().strip()
        if judge_prompt_file:
            cmd.extend(["--judge-prompt-file", judge_prompt_file])
        if int(self._cmp_prompt_chars_spin.value()) > 0:
            cmd.extend(["--prompt-max-chars", str(int(self._cmp_prompt_chars_spin.value()))])
        if float(self._cmp_threshold_gap_spin.value()) >= 0.0:
            cmd.extend(["--threshold-win-gap", f"{float(self._cmp_threshold_gap_spin.value()):.2f}"])
        swap_mode = str(self._cmp_swap_combo.currentData() or "on")
        if swap_mode == "on":
            cmd.append("--swap-order")
        else:
            cmd.append("--no-swap-order")
        for item in self._parse_overrides_csv(self._cmp_set_edit.text()):
            cmd.extend(["--set", item])
        artifacts_mode = str(self._cmp_artifacts_combo.currentData() or "default")
        if artifacts_mode == "on":
            cmd.append("--write-artifacts")
        elif artifacts_mode == "off":
            cmd.append("--no-write-artifacts")
        return cmd

    def _run_rag_tests_clicked(self) -> None:
        self._start_runner_queue([("RAG", self._build_rag_command())], clear_log=False)

    def _run_feedback_export_clicked(self) -> None:
        run_name = self._feedback_run_name()
        out_dir = self._fb_out_edit.text().strip()
        self._apply_feedback_suite_paths(run_name, out_dir)
        self._start_runner_queue(
            [("Feedback->Suites", self._build_feedback_export_command(run_name=run_name))],
            clear_log=False,
        )

    def _run_pdf_tests_clicked(self) -> None:
        self._start_runner_queue([("PDF", self._build_pdf_command())], clear_log=False)

    def _run_glossary_tests_clicked(self) -> None:
        cmd = self._build_glossary_command()
        if "--llm-model" not in cmd:
            self._append_runner_log("ERROR: Glossary test requires --llm-model")
            return
        self._start_runner_queue([("Glossary", cmd)], clear_log=False)

    def _run_factcheck_tests_clicked(self) -> None:
        cmd = self._build_factcheck_command()
        if "--llm-model" not in cmd:
            self._append_runner_log("ERROR: Fact-Check test requires --llm-model")
            return
        self._start_runner_queue([("Fact-Check", cmd)], clear_log=False)

    def _run_judge_tests_clicked(self) -> None:
        cmd = self._build_judge_command()
        if "--llm-model" not in cmd:
            self._append_runner_log("ERROR: Judge test requires --llm-model")
            return
        self._start_runner_queue([("Judge", cmd)], clear_log=False)

    def _run_llmcompare_tests_clicked(self) -> None:
        cmd = self._build_llmcompare_command()
        required_flags = ("--a-llm-model", "--b-llm-model", "--judge-llm-model")
        missing = [flag for flag in required_flags if flag not in cmd]
        if missing:
            self._append_runner_log(
                f"ERROR: LLM-Compare test requires {', '.join(required_flags)}"
            )
            return
        self._start_runner_queue([("LLM-Compare", cmd)], clear_log=False)

    def _run_all_tests_clicked(self) -> None:
        export_run_name = self._feedback_run_name()
        export_out_dir = self._fb_out_edit.text().strip()
        self._apply_feedback_suite_paths(export_run_name, export_out_dir)
        counts = self._feedback_case_counts()

        queue: list[tuple[str, list[str]]] = [
            ("Feedback->Suites", self._build_feedback_export_command(run_name=export_run_name)),
        ]
        if counts.get("rag", 0) > 0:
            queue.append(("RAG", self._build_rag_command()))
        else:
            self._append_runner_log("INFO: RAG skipped in Run All-Tests (no testcase entries)")
        if counts.get("pdf", 0) > 0:
            queue.append(("PDF", self._build_pdf_command()))
        else:
            self._append_runner_log("INFO: PDF skipped in Run All-Tests (no testcase entries)")
        gloss_cmd = self._build_glossary_command()
        if counts.get("glossary", 0) <= 0:
            self._append_runner_log(
                "INFO: Glossary skipped in Run All-Tests (no testcase entries)"
            )
        elif "--llm-model" in gloss_cmd:
            queue.append(("Glossary", gloss_cmd))
        else:
            self._append_runner_log(
                "INFO: Glossary skipped in Run All-Tests (LLM model missing)"
            )
        fact_cmd = self._build_factcheck_command()
        if counts.get("factcheck", 0) <= 0:
            self._append_runner_log(
                "INFO: Fact-Check skipped in Run All-Tests (no testcase entries)"
            )
        elif "--llm-model" in fact_cmd:
            queue.append(("Fact-Check", fact_cmd))
        else:
            self._append_runner_log(
                "INFO: Fact-Check skipped in Run All-Tests (LLM model missing)"
            )
        judge_cmd = self._build_judge_command()
        if counts.get("judge", 0) <= 0:
            self._append_runner_log(
                "INFO: Judge skipped in Run All-Tests (no testcase entries)"
            )
        elif "--llm-model" in judge_cmd:
            queue.append(("Judge", judge_cmd))
        else:
            self._append_runner_log(
                "INFO: Judge skipped in Run All-Tests (LLM model missing)"
            )
        cmp_cmd = self._build_llmcompare_command()
        required_cmp = ("--a-llm-model", "--b-llm-model", "--judge-llm-model")
        if counts.get("llmcompare", 0) <= 0:
            self._append_runner_log(
                "INFO: LLM-Compare skipped in Run All-Tests (no testcase entries)"
            )
        elif all(flag in cmp_cmd for flag in required_cmp):
            queue.append(("LLM-Compare", cmp_cmd))
        else:
            self._append_runner_log(
                "INFO: LLM-Compare skipped in Run All-Tests (A/B/Judge model missing)"
            )
        self._start_runner_queue(queue, clear_log=True)

    def _start_runner_queue(
        self,
        queue: list[tuple[str, list[str]]],
        *,
        clear_log: bool,
    ) -> None:
        if self._runner_proc is not None and self._runner_proc.state() != QProcess.ProcessState.NotRunning:
            self._append_runner_log("Runner busy. Stop current process first.")
            return
        if clear_log:
            self._runner_log.clear()
        self._runner_queue = list(queue)
        self._start_next_runner_command()

    def _start_next_runner_command(self) -> None:
        if not self._runner_queue:
            self._append_runner_log("All queued tests finished.")
            self.reload_runs()
            return
        name, cmd = self._runner_queue.pop(0)
        self._runner_active_name = name
        self._runner_active_cmd = cmd
        self._append_runner_log(f"\n>>> START [{name}] {' '.join(cmd)}")

        proc = QProcess(self)
        proc.setProgram(cmd[0])
        proc.setArguments(cmd[1:])
        proc.setWorkingDirectory(str(_SCRIPT_DIR.parent))
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        proc.readyReadStandardOutput.connect(self._on_runner_stdout)
        proc.readyReadStandardError.connect(self._on_runner_stderr)
        proc.finished.connect(self._on_runner_finished)
        self._runner_proc = proc
        proc.start()
        if not proc.waitForStarted(3000):
            self._append_runner_log(f"ERROR: could not start process for [{name}]")
            self._runner_proc = None
            self._start_next_runner_command()

    def _stop_runner(self) -> None:
        proc = self._runner_proc
        if proc is None:
            return
        if proc.state() == QProcess.ProcessState.NotRunning:
            return
        self._append_runner_log("Stopping current runner process...")
        proc.kill()
        proc.waitForFinished(2000)

    def _on_runner_stdout(self) -> None:
        proc = self._runner_proc
        if proc is None:
            return
        data = bytes(proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        if data:
            self._append_runner_log(data.rstrip("\n"))

    def _on_runner_stderr(self) -> None:
        proc = self._runner_proc
        if proc is None:
            return
        data = bytes(proc.readAllStandardError()).decode("utf-8", errors="replace")
        if data:
            self._append_runner_log(data.rstrip("\n"))

    def _on_runner_finished(self, exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
        self._append_runner_log(
            f"<<< DONE [{self._runner_active_name}] exit={exit_code}"
        )
        self._runner_proc = None
        self._runner_active_name = ""
        self._runner_active_cmd = []
        self.reload_runs()
        self._start_next_runner_command()

    def _append_runner_log(self, text: str) -> None:
        self._runner_log.appendPlainText(str(text))

    @staticmethod
    def _runs_mode(runs: list[RunEntry]) -> str:
        kinds = {run.run_type for run in runs}
        if not kinds:
            return "mixed"
        if kinds == {"rag"}:
            return "rag"
        if kinds == {"pdf"}:
            return "pdf"
        if kinds == {"glossary"}:
            return "glossary"
        if kinds == {"factcheck"}:
            return "factcheck"
        if kinds == {"judge"}:
            return "judge"
        if kinds == {"llmcompare"}:
            return "llmcompare"
        return "mixed"

    def _requested_type_mode(self) -> str:
        value = str(self._type_selector.currentData() or "all").strip().lower()
        if value in {"rag", "pdf", "glossary", "factcheck", "judge", "llmcompare"}:
            return value
        return "mixed"

    def _configure_run_table_headers(self, mode: str) -> None:
        if mode == "rag":
            headers = [
                "Type",
                "Run",
                "Timestamp",
                "Cases",
                "Macro F1",
                "Hit@K",
                "MAP",
                "Zero-F1%",
                "Suite",
                "Summary File",
            ]
            stretch_cols = (8, 9)
        elif mode == "judge":
            headers = [
                "Type",
                "Run",
                "Timestamp",
                "Cases",
                "Accuracy",
                "Parsed Rate",
                "Avg Conf",
                "Fail%",
                "Suite",
                "Summary File",
            ]
            stretch_cols = (8, 9)
        elif mode == "llmcompare":
            headers = [
                "Type",
                "Run",
                "Timestamp",
                "Cases",
                "Pref A",
                "Pref B",
                "Parsed",
                "Fail%",
                "Suite",
                "Summary File",
            ]
            stretch_cols = (8, 9)
        elif mode == "factcheck":
            headers = [
                "Type",
                "Run",
                "Timestamp",
                "Cases",
                "Full F1",
                "Extract F1",
                "Verify Acc",
                "Fail%",
                "Suite",
                "Summary File",
            ]
            stretch_cols = (8, 9)
        elif mode == "pdf":
            headers = [
                "Type",
                "Run",
                "Timestamp",
                "Cases",
                "Token F1",
                "Paragraph",
                "Line Ratio",
                "Fail%",
                "Suite",
                "Summary File",
            ]
            stretch_cols = (8, 9)
        elif mode == "glossary":
            headers = [
                "Type",
                "Run",
                "Timestamp",
                "Cases",
                "Recall",
                "Precision",
                "F1",
                "Fail%",
                "Suite",
                "Summary File",
            ]
            stretch_cols = (8, 9)
        else:
            headers = [
                "Type",
                "Run",
                "Timestamp",
                "Cases",
                "Primary",
                "Structure",
                "Secondary",
                "Fail%",
                "Suite",
                "Summary File",
            ]
            stretch_cols = (8, 9)
        self._run_table.setColumnCount(len(headers))
        self._run_table.setHorizontalHeaderLabels(headers)
        header = self._run_table.horizontalHeader()
        for idx in range(len(headers)):
            if idx in stretch_cols:
                header.setSectionResizeMode(idx, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(idx, QHeaderView.ResizeMode.ResizeToContents)

    def _configure_comparison_headers(self, mode: str) -> None:
        if mode == "rag":
            headers = [
                "Type",
                "Run",
                "Cases",
                "Macro F1",
                "Micro F1",
                "Hit@K",
                "MAP",
                "MRR",
                "nDCG",
                "Zero-F1%",
                "Suite",
            ]
            stretch_col = 10
        elif mode == "judge":
            headers = [
                "Type",
                "Run",
                "Cases",
                "Accuracy",
                "Parsed Rate",
                "Avg Conf",
                "Threshold",
                "Pass",
                "Micro Acc",
                "Fail%",
                "Suite",
            ]
            stretch_col = 10
        elif mode == "llmcompare":
            headers = [
                "Type",
                "Run",
                "Cases",
                "Pref A",
                "Pref B",
                "Parsed",
                "Avg Conf",
                "Win Gap",
                "Undecided",
                "Fail%",
                "Suite",
            ]
            stretch_col = 10
        elif mode == "factcheck":
            headers = [
                "Type",
                "Run",
                "Cases",
                "Full F1",
                "Micro F1",
                "Extract F1",
                "Verify Acc",
                "Pass Rate",
                "Full Recall",
                "Fail%",
                "Suite",
            ]
            stretch_col = 10
        elif mode == "pdf":
            headers = [
                "Type",
                "Run",
                "Cases",
                "Token F1",
                "Paragraph",
                "Line Ratio",
                "Char Ratio",
                "Pass Rate",
                "Token F1 (Micro)",
                "Fail%",
                "Suite",
            ]
            stretch_col = 10
        elif mode == "glossary":
            headers = [
                "Type",
                "Run",
                "Cases",
                "Recall",
                "Precision",
                "F1",
                "Pass Rate",
                "Hit-All",
                "Micro F1",
                "Fail%",
                "Suite",
            ]
            stretch_col = 10
        else:
            headers = [
                "Type",
                "Run",
                "Cases",
                "Primary",
                "Structure",
                "Secondary",
                "Metric A",
                "Metric B",
                "Metric C",
                "Fail%",
                "Suite",
            ]
            stretch_col = 10
        self._comparison_table.setColumnCount(len(headers))
        self._comparison_table.setHorizontalHeaderLabels(headers)
        header = self._comparison_table.horizontalHeader()
        for idx in range(len(headers)):
            if idx == stretch_col:
                header.setSectionResizeMode(idx, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(idx, QHeaderView.ResizeMode.ResizeToContents)

    def _configure_case_headers(self, mode: str) -> None:
        if mode == "rag":
            headers = [
                "Case ID",
                "Labels",
                "F1",
                "Precision",
                "Recall",
                "Hit@K",
                "Expected Docs",
                "Predicted Docs",
                "Query",
            ]
        elif mode == "pdf":
            headers = [
                "Case ID",
                "Labels",
                "Token F1",
                "Precision",
                "Recall",
                "Paragraph",
                "Expected MD",
                "Observed",
                "PDF Input",
            ]
        elif mode == "glossary":
            headers = [
                "Case ID",
                "Labels",
                "Recall",
                "Precision",
                "F1",
                "Hit-All",
                "Target Terms",
                "Observed",
                "Markdown Input",
            ]
        elif mode == "factcheck":
            headers = [
                "Case ID",
                "Labels",
                "Full F1",
                "Full Precision",
                "Full Recall",
                "Verify Acc",
                "GT Facts",
                "Observed",
                "Target",
            ]
        elif mode == "judge":
            headers = [
                "Case ID",
                "Labels",
                "Correct",
                "Precision",
                "Recall",
                "Parsed",
                "Expected",
                "Predicted",
                "Judge Output",
            ]
        elif mode == "llmcompare":
            headers = [
                "Case ID",
                "Labels",
                "Pref A",
                "Pref B",
                "Decided",
                "Parsed",
                "Settings",
                "Decision",
                "Prompt",
            ]
        else:
            headers = [
                "Case ID",
                "Labels",
                "Primary",
                "Precision",
                "Recall",
                "Structure",
                "Expected",
                "Observed",
                "Input",
            ]
        self._case_table.setColumnCount(len(headers))
        self._case_table.setHorizontalHeaderLabels(headers)
        header = self._case_table.horizontalHeader()
        for idx in range(min(6, len(headers))):
            header.setSectionResizeMode(idx, QHeaderView.ResizeMode.ResizeToContents)
        for idx in range(6, len(headers)):
            header.setSectionResizeMode(idx, QHeaderView.ResizeMode.Stretch)

    def _configure_label_headers(self, mode: str) -> None:
        if mode == "rag":
            headers = [
                "Run",
                "Label",
                "Cases",
                "Macro F1",
                "Hit@K",
                "Precision",
                "Recall",
                "Failures",
                "Fail%",
            ]
        elif mode == "pdf":
            headers = [
                "Run",
                "Label",
                "Cases",
                "Token F1",
                "Paragraph",
                "Token Precision",
                "Token Recall",
                "Failures",
                "Fail%",
            ]
        elif mode == "factcheck":
            headers = [
                "Run",
                "Label",
                "Cases",
                "Full F1",
                "Extract F1",
                "Full Precision",
                "Full Recall",
                "Failures",
                "Fail%",
            ]
        elif mode == "judge":
            headers = [
                "Run",
                "Label",
                "Cases",
                "Accuracy",
                "Parsed Rate",
                "Precision",
                "Recall",
                "Failures",
                "Fail%",
            ]
        elif mode == "llmcompare":
            headers = [
                "Run",
                "Label",
                "Cases",
                "Pref A",
                "Pref B",
                "Decided",
                "Parsed",
                "Failures",
                "Fail%",
            ]
        elif mode == "glossary":
            headers = [
                "Run",
                "Label",
                "Cases",
                "Recall",
                "Precision",
                "F1",
                "Hit-All",
                "Failures",
                "Fail%",
            ]
        else:
            headers = [
                "Run",
                "Label",
                "Cases",
                "Primary",
                "Structure",
                "Precision",
                "Recall",
                "Failures",
                "Fail%",
            ]
        self._label_table.setColumnCount(len(headers))
        self._label_table.setHorizontalHeaderLabels(headers)
        header = self._label_table.horizontalHeader()
        for idx in range(len(headers)):
            header.setSectionResizeMode(idx, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

    def _browse_root(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Choose runs directory", self._root_edit.text())
        if not selected:
            return
        self._root_edit.setText(selected)
        self.reload_runs()

    def reload_runs(self) -> None:
        root = pathlib.Path(self._root_edit.text()).expanduser().resolve()
        self._all_runs = discover_runs(root)
        self._runs_by_path = {str(run.path): run for run in self._all_runs}
        self._apply_filter()

    def _apply_filter(self) -> None:
        query = self._filter_edit.text().strip().casefold()
        type_filter = str(self._type_selector.currentData() or "all").strip().lower()
        if not query:
            visible = list(self._all_runs)
        else:
            visible = [
                run
                for run in self._all_runs
                if (
                    query in run.run_name.casefold()
                    or query in run.suite.casefold()
                    or query in str(run.path).casefold()
                    or query in run.run_type.casefold()
                )
            ]
        if type_filter in {"rag", "pdf", "glossary", "factcheck", "judge", "llmcompare"}:
            visible = [run for run in visible if run.run_type == type_filter]
        self._visible_runs = visible
        self._render_run_table()
        self._refresh_all_views()

    def _render_run_table(self) -> None:
        self._run_table.setSortingEnabled(False)
        self._run_table.setRowCount(0)
        mode = self._runs_mode(self._visible_runs)
        if not self._visible_runs:
            mode = self._requested_type_mode()
        self._configure_run_table_headers(mode)

        for row_idx, run in enumerate(self._visible_runs):
            self._run_table.insertRow(row_idx)
            _set_text_item(self._run_table, row_idx, 0, run.run_type.upper())
            run_item = _set_text_item(self._run_table, row_idx, 1, run.run_name)
            run_item.setData(Qt.ItemDataRole.UserRole, str(run.path))

            _set_text_item(self._run_table, row_idx, 2, run.timestamp)
            _set_text_item(self._run_table, row_idx, 3, str(run.cases_count))
            if mode == "llmcompare":
                _set_numeric_item(self._run_table, row_idx, 4, run.macro_f1, heatmap=True)
                _set_numeric_item(self._run_table, row_idx, 5, run.micro_f1, heatmap=True)
                _set_numeric_item(self._run_table, row_idx, 6, run.hit_at_k, heatmap=True)
                _set_numeric_item(self._run_table, row_idx, 7, _failure_rate(run), heatmap=True)
                _set_text_item(self._run_table, row_idx, 8, run.suite)
                _set_text_item(self._run_table, row_idx, 9, str(run.path))
            elif mode == "judge":
                _set_numeric_item(self._run_table, row_idx, 4, run.macro_f1, heatmap=True)
                _set_numeric_item(self._run_table, row_idx, 5, run.hit_at_k, heatmap=True)
                _set_numeric_item(self._run_table, row_idx, 6, run.map_value, heatmap=True)
                _set_numeric_item(self._run_table, row_idx, 7, _failure_rate(run), heatmap=True)
                _set_text_item(self._run_table, row_idx, 8, run.suite)
                _set_text_item(self._run_table, row_idx, 9, str(run.path))
            elif mode == "factcheck":
                _set_numeric_item(self._run_table, row_idx, 4, run.macro_f1, heatmap=True)
                _set_numeric_item(self._run_table, row_idx, 5, run.hit_at_k, heatmap=True)
                _set_numeric_item(self._run_table, row_idx, 6, run.map_value, heatmap=True)
                _set_numeric_item(self._run_table, row_idx, 7, _failure_rate(run), heatmap=True)
                _set_text_item(self._run_table, row_idx, 8, run.suite)
                _set_text_item(self._run_table, row_idx, 9, str(run.path))
            elif mode in {"rag", "pdf"}:
                _set_numeric_item(self._run_table, row_idx, 4, run.macro_f1, heatmap=True)
                _set_numeric_item(self._run_table, row_idx, 5, run.hit_at_k, heatmap=True)
                _set_numeric_item(self._run_table, row_idx, 6, run.map_value, heatmap=True)
                _set_numeric_item(self._run_table, row_idx, 7, _failure_rate(run), heatmap=True)
                _set_text_item(self._run_table, row_idx, 8, run.suite)
                _set_text_item(self._run_table, row_idx, 9, str(run.path))
            elif mode == "glossary":
                _set_numeric_item(self._run_table, row_idx, 4, run.hit_at_k, heatmap=True)
                _set_numeric_item(self._run_table, row_idx, 5, run.map_value, heatmap=True)
                _set_numeric_item(self._run_table, row_idx, 6, run.macro_f1, heatmap=True)
                _set_numeric_item(self._run_table, row_idx, 7, _failure_rate(run), heatmap=True)
                _set_text_item(self._run_table, row_idx, 8, run.suite)
                _set_text_item(self._run_table, row_idx, 9, str(run.path))
            else:
                _set_numeric_item(self._run_table, row_idx, 4, run.macro_f1, heatmap=True)
                _set_numeric_item(self._run_table, row_idx, 5, run.hit_at_k, heatmap=True)
                _set_numeric_item(self._run_table, row_idx, 6, run.map_value, heatmap=True)
                _set_numeric_item(self._run_table, row_idx, 7, _failure_rate(run), heatmap=True)
                _set_text_item(self._run_table, row_idx, 8, run.suite)
                _set_text_item(self._run_table, row_idx, 9, str(run.path))

        self._run_table.setSortingEnabled(True)

    def _selected_runs(self) -> list[RunEntry]:
        model = self._run_table.selectionModel()
        if model is None:
            return []

        out: list[RunEntry] = []
        seen: set[str] = set()
        for idx in model.selectedRows(1):
            row = idx.row()
            item = self._run_table.item(row, 1)
            if item is None:
                continue
            path = str(item.data(Qt.ItemDataRole.UserRole) or "")
            if not path or path in seen:
                continue
            run = self._runs_by_path.get(path)
            if run is None:
                continue
            seen.add(path)
            out.append(run)

        out.sort(key=lambda r: (r.timestamp, r.run_name), reverse=True)
        return out

    @staticmethod
    def _case_no(case: CaseEntry) -> int | None:
        case_id = str(case.case_id or "").strip()
        if case_id:
            match = _CASE_NO_RE.match(case_id)
            if match:
                try:
                    return int(match.group(1))
                except Exception:
                    return None
        for label in case.labels:
            text = str(label or "").strip()
            if not text.casefold().startswith("case_no:"):
                continue
            raw = text.split(":", 1)[1].strip()
            try:
                return int(raw)
            except Exception:
                continue
        return None

    def _common_case_numbers(self, runs: list[RunEntry]) -> set[int]:
        if len(runs) < 2:
            return set()
        sets: list[set[int]] = []
        for run in runs:
            nums = {n for n in (self._case_no(c) for c in run.cases) if n is not None}
            if not nums:
                return set()
            sets.append(nums)
        if not sets:
            return set()
        return set.intersection(*sets)

    @staticmethod
    def _rebuild_run_for_cases(run: RunEntry, cases: list[CaseEntry]) -> RunEntry:
        if not cases:
            return RunEntry(
                run_type=run.run_type,
                run_name=run.run_name,
                timestamp=run.timestamp,
                suite=run.suite,
                path=run.path,
                cases_count=0,
                micro_f1=0.0,
                macro_f1=0.0,
                hit_at_k=0.0,
                map_value=0.0,
                mrr=0.0,
                ndcg=0.0,
                failure_cases=0,
                cases=[],
            )
        failures = sum(1 for case in cases if case.failed)
        macro_f1 = statistics.fmean(case.f1 for case in cases)
        hit_at_k = statistics.fmean(case.hit_at_k for case in cases)
        precision = statistics.fmean(case.precision for case in cases)
        recall = statistics.fmean(case.recall for case in cases)
        pass_rate = statistics.fmean(0.0 if case.failed else 1.0 for case in cases)
        return RunEntry(
            run_type=run.run_type,
            run_name=run.run_name,
            timestamp=run.timestamp,
            suite=run.suite,
            path=run.path,
            cases_count=len(cases),
            micro_f1=macro_f1,
            macro_f1=macro_f1,
            hit_at_k=hit_at_k,
            map_value=precision,
            mrr=recall,
            ndcg=pass_rate,
            failure_cases=failures,
            cases=cases,
        )

    def _filter_runs_common_cases(self, runs: list[RunEntry]) -> list[RunEntry]:
        if not self._common_case_cb.isChecked():
            return runs
        if len(runs) < 2:
            return runs
        common = self._common_case_numbers(runs)
        if not common:
            return []
        out: list[RunEntry] = []
        for run in runs:
            filtered = [case for case in run.cases if self._case_no(case) in common]
            out.append(self._rebuild_run_for_cases(run, filtered))
        return out

    def _runs_for_scope(self) -> list[RunEntry]:
        selected = self._selected_runs()
        base = selected if selected else self._visible_runs
        return self._filter_runs_common_cases(base)

    def _on_run_selection_changed(self) -> None:
        self._refresh_all_views()

    def _refresh_all_views(self) -> None:
        selected = self._selected_runs()
        runs_scope = self._runs_for_scope()
        rag_n = sum(1 for run in self._visible_runs if run.run_type == "rag")
        pdf_n = sum(1 for run in self._visible_runs if run.run_type == "pdf")
        glossary_n = sum(
            1 for run in self._visible_runs if run.run_type == "glossary"
        )
        factcheck_n = sum(
            1 for run in self._visible_runs if run.run_type == "factcheck"
        )
        judge_n = sum(1 for run in self._visible_runs if run.run_type == "judge")
        llmcompare_n = sum(
            1 for run in self._visible_runs if run.run_type == "llmcompare"
        )
        type_filter = str(self._type_selector.currentData() or "all").upper()
        common_info = ""
        if self._common_case_cb.isChecked():
            base_runs = selected if selected else self._visible_runs
            common_count = len(self._common_case_numbers(base_runs))
            common_info = f" | CommonCaseNo: {common_count}"

        self._status_lbl.setText(
            f"Loaded: {len(self._all_runs)} | Visible: {len(self._visible_runs)} | "
            f"Selected: {len(selected)} | Scope runs: {len(runs_scope)} | "
            f"RAG: {rag_n} | PDF: {pdf_n} | Glossary: {glossary_n} | "
            f"Fact-Check: {factcheck_n} | Judge: {judge_n} | LLM-Compare: {llmcompare_n} | "
            f"Type filter: {type_filter}{common_info}"
        )

        self._refresh_cards(runs_scope, selected)
        self._refresh_visuals(runs_scope)
        self._refresh_comparison_table(runs_scope)
        self._refresh_case_run_selector(runs_scope)
        self._refresh_case_table()
        self._refresh_label_table()

    def _refresh_cards(self, runs_scope: list[RunEntry], selected: list[RunEntry]) -> None:
        self._card_loaded.set_value(str(len(self._all_runs)), "all discovered")
        self._card_visible.set_value(str(len(self._visible_runs)), "after run filter")
        self._card_selected.set_value(str(len(selected)), "manual selection")

        if runs_scope:
            mean_macro = statistics.fmean(run.macro_f1 for run in runs_scope)
            mean_hit = statistics.fmean(run.hit_at_k for run in runs_scope)
            mean_zero = statistics.fmean(_failure_rate(run) for run in runs_scope)
            self._card_macro.set_value(f"{mean_macro:.3f}", "across scope")
            self._card_hit.set_value(f"{mean_hit:.3f}", "across scope")
            self._card_fail.set_value(f"{mean_zero:.1%}", "across scope")
        else:
            self._card_macro.set_value("—")
            self._card_hit.set_value("—")
            self._card_fail.set_value("—")

    def _set_empty_chart(self, view: QChartView, title: str, message: str) -> None:
        chart = QChart()
        chart.setTitle(f"{title}\n{message}")
        chart.legend().hide()
        chart.setBackgroundVisible(False)
        view.setChart(chart)

    def _refresh_visuals(self, runs_scope: list[RunEntry]) -> None:
        self._refresh_run_metric_chart(runs_scope)
        self._refresh_failure_chart(runs_scope)
        self._refresh_label_chart(runs_scope)
        self._refresh_strength_weakness_tables(runs_scope)

    def _refresh_run_metric_chart(self, runs_scope: list[RunEntry]) -> None:
        runs = runs_scope[:10]
        if not runs:
            self._set_empty_chart(self._run_metric_chart, "Run Scoreboard", "No runs in current scope")
            return

        categories = [_short_name(run.run_name, 16) for run in runs]

        macro_set = QBarSet("Primary")
        macro_set.setColor(QColor("#89B4FA"))
        macro_set.append([run.macro_f1 for run in runs])

        hit_set = QBarSet("Structure")
        hit_set.setColor(QColor("#F9E2AF"))
        hit_set.append([run.hit_at_k for run in runs])

        map_set = QBarSet("Secondary")
        map_set.setColor(QColor("#A6E3A1"))
        map_set.append([run.map_value for run in runs])

        series = QBarSeries()
        series.append(macro_set)
        series.append(hit_set)
        series.append(map_set)

        chart = QChart()
        chart.setTitle("Run Scoreboard: primary vs structure vs secondary")
        chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations)
        chart.setBackgroundVisible(False)
        chart.addSeries(series)

        axis_x = QBarCategoryAxis()
        axis_x.append(categories)
        axis_y = QValueAxis()
        axis_y.setRange(0.0, 1.0)
        axis_y.setLabelFormat("%.2f")

        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_x)
        series.attachAxis(axis_y)
        chart.legend().setVisible(True)

        self._run_metric_chart.setChart(chart)

    def _refresh_failure_chart(self, runs_scope: list[RunEntry]) -> None:
        runs = runs_scope[:12]
        if not runs:
            self._set_empty_chart(self._failure_chart, "Failure Pressure", "No runs in current scope")
            return

        categories = [_short_name(run.run_name, 16) for run in runs]
        fail_set = QBarSet("Failed cases")
        fail_set.setColor(QColor("#F38BA8"))
        fail_set.append([float(_failure_count(run)) for run in runs])

        success_set = QBarSet("Passing cases")
        success_set.setColor(QColor("#94E2D5"))
        success_set.append([float(max(0, run.cases_count - _failure_count(run))) for run in runs])

        series = QStackedBarSeries()
        series.append(success_set)
        series.append(fail_set)

        max_cases = max((run.cases_count for run in runs), default=1)

        chart = QChart()
        chart.setTitle("Failure Pressure: failing-case share per run")
        chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations)
        chart.setBackgroundVisible(False)
        chart.addSeries(series)

        axis_x = QBarCategoryAxis()
        axis_x.append(categories)
        axis_y = QValueAxis()
        axis_y.setRange(0.0, float(max_cases))
        axis_y.setLabelFormat("%.0f")

        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_x)
        series.attachAxis(axis_y)
        chart.legend().setVisible(True)

        self._failure_chart.setChart(chart)

    def _refresh_label_chart(self, runs_scope: list[RunEntry]) -> None:
        cases = [case for run in runs_scope for case in run.cases]
        stats = _aggregate_labels(cases)
        if not stats:
            self._set_empty_chart(self._label_chart, "Label Intelligence", "No labeled cases in current scope")
            return

        top = sorted(stats, key=lambda s: s.macro_f1, reverse=True)[:6]
        weak = sorted(stats, key=lambda s: (s.macro_f1, -s.failure_rate))[:6]

        categories: list[str] = []
        top_values: dict[str, float] = {}
        weak_values: dict[str, float] = {}

        for item in top:
            key = item.label
            if key not in categories:
                categories.append(key)
            top_values[key] = item.macro_f1

        for item in weak:
            key = item.label
            if key not in categories:
                categories.append(key)
            weak_values[key] = item.macro_f1

        top_set = QBarSet("Strong labels")
        top_set.setColor(QColor("#A6E3A1"))
        top_set.append([float(top_values.get(label, 0.0)) for label in categories])

        weak_set = QBarSet("Weak labels")
        weak_set.setColor(QColor("#F38BA8"))
        weak_set.append([float(weak_values.get(label, 0.0)) for label in categories])

        series = QBarSeries()
        series.append(top_set)
        series.append(weak_set)

        chart = QChart()
        chart.setTitle("Label Intelligence: what works vs what breaks")
        chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations)
        chart.setBackgroundVisible(False)
        chart.addSeries(series)

        axis_x = QBarCategoryAxis()
        axis_x.append([_short_name(label, 14) for label in categories])
        axis_y = QValueAxis()
        axis_y.setRange(0.0, 1.0)
        axis_y.setLabelFormat("%.2f")

        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_x)
        series.attachAxis(axis_y)
        chart.legend().setVisible(True)

        self._label_chart.setChart(chart)

    def _refresh_strength_weakness_tables(self, runs_scope: list[RunEntry]) -> None:
        cases = [case for run in runs_scope for case in run.cases]
        stats = _aggregate_labels(cases)

        strengths = sorted(
            stats,
            key=lambda s: (s.macro_f1, -s.failure_rate),
            reverse=True,
        )[:8]
        weaknesses = sorted(
            stats,
            key=lambda s: (s.macro_f1, -s.failure_rate),
        )[:8]

        self._fill_insight_table(self._strength_table, strengths)
        self._fill_insight_table(self._weakness_table, weaknesses)

    def _fill_insight_table(self, table: QTableWidget, rows: list[LabelStat]) -> None:
        table.setSortingEnabled(False)
        table.setRowCount(0)
        for row_idx, stat in enumerate(rows):
            table.insertRow(row_idx)
            _set_text_item(table, row_idx, 0, stat.label)
            _set_text_item(table, row_idx, 1, str(stat.cases))
            _set_numeric_item(table, row_idx, 2, stat.macro_f1, heatmap=True)
            _set_numeric_item(table, row_idx, 3, stat.failure_rate, heatmap=True)
        table.setSortingEnabled(True)

    def _refresh_comparison_table(self, runs_scope: list[RunEntry]) -> None:
        self._comparison_table.setSortingEnabled(False)
        self._comparison_table.setRowCount(0)
        mode = self._runs_mode(runs_scope)
        if not runs_scope:
            mode = self._requested_type_mode()
        self._configure_comparison_headers(mode)

        runs = runs_scope[:20]
        for row_idx, run in enumerate(runs):
            self._comparison_table.insertRow(row_idx)
            _set_text_item(self._comparison_table, row_idx, 0, run.run_type.upper())
            _set_text_item(self._comparison_table, row_idx, 1, run.run_name)
            _set_text_item(self._comparison_table, row_idx, 2, str(run.cases_count))
            if mode == "rag":
                _set_numeric_item(self._comparison_table, row_idx, 3, run.macro_f1, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 4, run.micro_f1, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 5, run.hit_at_k, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 6, run.map_value, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 7, run.mrr, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 8, run.ndcg, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 9, _failure_rate(run), heatmap=True)
                _set_text_item(self._comparison_table, row_idx, 10, run.suite)
            elif mode == "llmcompare":
                _set_numeric_item(self._comparison_table, row_idx, 3, run.macro_f1, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 4, run.micro_f1, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 5, run.hit_at_k, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 6, run.map_value, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 7, run.mrr, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 8, run.ndcg, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 9, _failure_rate(run), heatmap=True)
                _set_text_item(self._comparison_table, row_idx, 10, run.suite)
            elif mode == "judge":
                _set_numeric_item(self._comparison_table, row_idx, 3, run.macro_f1, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 4, run.hit_at_k, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 5, run.map_value, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 6, run.mrr, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 7, run.ndcg, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 8, run.micro_f1, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 9, _failure_rate(run), heatmap=True)
                _set_text_item(self._comparison_table, row_idx, 10, run.suite)
            elif mode == "factcheck":
                _set_numeric_item(self._comparison_table, row_idx, 3, run.macro_f1, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 4, run.micro_f1, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 5, run.hit_at_k, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 6, run.map_value, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 7, run.mrr, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 8, run.ndcg, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 9, _failure_rate(run), heatmap=True)
                _set_text_item(self._comparison_table, row_idx, 10, run.suite)
            elif mode == "pdf":
                _set_numeric_item(self._comparison_table, row_idx, 3, run.macro_f1, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 4, run.hit_at_k, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 5, run.map_value, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 6, run.mrr, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 7, run.ndcg, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 8, run.micro_f1, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 9, _failure_rate(run), heatmap=True)
                _set_text_item(self._comparison_table, row_idx, 10, run.suite)
            elif mode == "glossary":
                _set_numeric_item(self._comparison_table, row_idx, 3, run.hit_at_k, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 4, run.map_value, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 5, run.macro_f1, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 6, run.mrr, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 7, run.ndcg, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 8, run.micro_f1, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 9, _failure_rate(run), heatmap=True)
                _set_text_item(self._comparison_table, row_idx, 10, run.suite)
            else:
                _set_numeric_item(self._comparison_table, row_idx, 3, run.macro_f1, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 4, run.hit_at_k, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 5, run.map_value, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 6, run.micro_f1, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 7, run.mrr, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 8, run.ndcg, heatmap=True)
                _set_numeric_item(self._comparison_table, row_idx, 9, _failure_rate(run), heatmap=True)
                _set_text_item(self._comparison_table, row_idx, 10, run.suite)

        self._comparison_table.setSortingEnabled(True)

    def _refresh_case_run_selector(self, runs_scope: list[RunEntry]) -> None:
        current = self._case_run_selector.currentData()
        self._case_run_selector.blockSignals(True)
        self._case_run_selector.clear()

        for run in runs_scope:
            self._case_run_selector.addItem(
                f"[{run.run_type.upper()}] {run.run_name}",
                str(run.path),
            )

        if current:
            for idx in range(self._case_run_selector.count()):
                if self._case_run_selector.itemData(idx) == current:
                    self._case_run_selector.setCurrentIndex(idx)
                    break
        self._case_run_selector.blockSignals(False)
        self._refresh_case_label_selector()

    def _on_case_run_changed(self) -> None:
        self._refresh_case_label_selector()
        self._refresh_case_table()

    def _current_case_run(self) -> RunEntry | None:
        path = str(self._case_run_selector.currentData() or "")
        if not path:
            return None
        return self._runs_by_path.get(path)

    def _refresh_case_label_selector(self) -> None:
        run = self._current_case_run()
        labels = sorted({label for case in (run.cases if run else []) for label in case.labels}, key=str.casefold)

        current = self._case_label_selector.currentData()
        self._case_label_selector.blockSignals(True)
        self._case_label_selector.clear()
        self._case_label_selector.addItem("All labels", "")
        for label in labels:
            self._case_label_selector.addItem(label, label)

        if current:
            for idx in range(self._case_label_selector.count()):
                if self._case_label_selector.itemData(idx) == current:
                    self._case_label_selector.setCurrentIndex(idx)
                    break
        self._case_label_selector.blockSignals(False)

    def _refresh_case_table(self) -> None:
        run = self._current_case_run()
        self._case_table.setSortingEnabled(False)
        self._case_table.setRowCount(0)
        mode = run.run_type if run is not None else "mixed"
        self._configure_case_headers(mode)

        if run is None:
            self._case_table.setSortingEnabled(True)
            return

        label_filter = str(self._case_label_selector.currentData() or "")
        query_filter = self._case_query_filter.text().strip().casefold()

        filtered: list[CaseEntry] = []
        for case in run.cases:
            if label_filter and label_filter not in case.labels:
                continue
            if query_filter and query_filter not in case.case_id.casefold() and query_filter not in case.query.casefold():
                continue
            filtered.append(case)

        for row_idx, case in enumerate(filtered):
            self._case_table.insertRow(row_idx)
            _set_text_item(self._case_table, row_idx, 0, case.case_id)
            _set_text_item(self._case_table, row_idx, 1, ", ".join(case.labels) or "__unlabeled__")
            if mode == "glossary":
                _set_numeric_item(self._case_table, row_idx, 2, case.recall, heatmap=True)
                _set_numeric_item(self._case_table, row_idx, 3, case.precision, heatmap=True)
                _set_numeric_item(self._case_table, row_idx, 4, case.f1, heatmap=True)
                _set_numeric_item(self._case_table, row_idx, 5, case.hit_at_k, heatmap=True)
                _set_text_item(self._case_table, row_idx, 6, " | ".join(case.expected_docs))
                _set_text_item(self._case_table, row_idx, 7, " | ".join(case.predicted_docs))
                _set_text_item(self._case_table, row_idx, 8, case.query)
            elif mode == "factcheck":
                _set_numeric_item(self._case_table, row_idx, 2, case.f1, heatmap=True)
                _set_numeric_item(self._case_table, row_idx, 3, case.precision, heatmap=True)
                _set_numeric_item(self._case_table, row_idx, 4, case.recall, heatmap=True)
                _set_numeric_item(self._case_table, row_idx, 5, case.hit_at_k, heatmap=True)
                _set_text_item(self._case_table, row_idx, 6, " | ".join(case.expected_docs))
                _set_text_item(self._case_table, row_idx, 7, " | ".join(case.predicted_docs))
                _set_text_item(self._case_table, row_idx, 8, case.query)
            elif mode == "pdf":
                _set_numeric_item(self._case_table, row_idx, 2, case.f1, heatmap=True)
                _set_numeric_item(self._case_table, row_idx, 3, case.precision, heatmap=True)
                _set_numeric_item(self._case_table, row_idx, 4, case.recall, heatmap=True)
                _set_numeric_item(self._case_table, row_idx, 5, case.hit_at_k, heatmap=True)
                _set_text_item(self._case_table, row_idx, 6, " | ".join(case.expected_docs))
                _set_text_item(self._case_table, row_idx, 7, " | ".join(case.predicted_docs))
                _set_text_item(self._case_table, row_idx, 8, case.query)
            else:
                _set_numeric_item(self._case_table, row_idx, 2, case.f1, heatmap=True)
                _set_numeric_item(self._case_table, row_idx, 3, case.precision, heatmap=True)
                _set_numeric_item(self._case_table, row_idx, 4, case.recall, heatmap=True)
                _set_numeric_item(self._case_table, row_idx, 5, case.hit_at_k, heatmap=True)
                _set_text_item(self._case_table, row_idx, 6, " | ".join(case.expected_docs))
                _set_text_item(self._case_table, row_idx, 7, " | ".join(case.predicted_docs))
                _set_text_item(self._case_table, row_idx, 8, case.query)

        self._case_table.setSortingEnabled(True)

    def _refresh_label_table(self) -> None:
        scope = str(self._label_scope_selector.currentData() or "selected")
        mode = str(self._label_mode_selector.currentData() or "aggregate")
        label_filter = self._label_filter_edit.text().strip().casefold()

        if scope == "selected":
            runs = self._selected_runs()
            if not runs:
                runs = self._visible_runs
        else:
            runs = self._visible_runs
        run_mode = self._runs_mode(runs)
        if not runs:
            run_mode = self._requested_type_mode()
        self._configure_label_headers(run_mode)

        rows: list[tuple[str, LabelStat]] = []
        if mode == "aggregate":
            all_cases = [case for run in runs for case in run.cases]
            for stat in _aggregate_labels(all_cases):
                rows.append(("(aggregate)", stat))
        else:
            for run in runs:
                for stat in _aggregate_labels(run.cases):
                    rows.append((f"[{run.run_type.upper()}] {run.run_name}", stat))

        if label_filter:
            rows = [item for item in rows if label_filter in item[1].label.casefold()]

        self._label_table.setSortingEnabled(False)
        self._label_table.setRowCount(0)

        for row_idx, (run_name, stat) in enumerate(rows):
            self._label_table.insertRow(row_idx)
            _set_text_item(self._label_table, row_idx, 0, run_name)
            _set_text_item(self._label_table, row_idx, 1, stat.label)
            _set_text_item(self._label_table, row_idx, 2, str(stat.cases))
            if run_mode == "glossary":
                _set_numeric_item(self._label_table, row_idx, 3, stat.macro_recall, heatmap=True)
                _set_numeric_item(self._label_table, row_idx, 4, stat.macro_precision, heatmap=True)
                _set_numeric_item(self._label_table, row_idx, 5, stat.macro_f1, heatmap=True)
                _set_numeric_item(self._label_table, row_idx, 6, stat.macro_hit, heatmap=True)
            elif run_mode == "llmcompare":
                _set_numeric_item(self._label_table, row_idx, 3, stat.macro_f1, heatmap=True)
                _set_numeric_item(self._label_table, row_idx, 4, stat.macro_precision, heatmap=True)
                _set_numeric_item(self._label_table, row_idx, 5, stat.macro_recall, heatmap=True)
                _set_numeric_item(self._label_table, row_idx, 6, stat.macro_hit, heatmap=True)
            elif run_mode == "factcheck":
                _set_numeric_item(self._label_table, row_idx, 3, stat.macro_f1, heatmap=True)
                _set_numeric_item(self._label_table, row_idx, 4, stat.macro_hit, heatmap=True)
                _set_numeric_item(self._label_table, row_idx, 5, stat.macro_precision, heatmap=True)
                _set_numeric_item(self._label_table, row_idx, 6, stat.macro_recall, heatmap=True)
            else:
                _set_numeric_item(self._label_table, row_idx, 3, stat.macro_f1, heatmap=True)
                _set_numeric_item(self._label_table, row_idx, 4, stat.macro_hit, heatmap=True)
                _set_numeric_item(self._label_table, row_idx, 5, stat.macro_precision, heatmap=True)
                _set_numeric_item(self._label_table, row_idx, 6, stat.macro_recall, heatmap=True)
            _set_text_item(self._label_table, row_idx, 7, str(stat.failures))
            _set_numeric_item(self._label_table, row_idx, 8, stat.failure_rate, heatmap=True)

        self._label_table.setSortingEnabled(True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Open Test Studio dashboard for suite run artifacts"
    )
    parser.add_argument(
        "--root",
        default="runs",
        help="Directory scanned recursively for *.summary.json files",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    app = QApplication(sys.argv)
    window = TestStudioDashboard(pathlib.Path(args.root).expanduser().resolve())
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
