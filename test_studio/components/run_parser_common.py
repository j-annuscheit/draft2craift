"""Common parsing helpers for Test Studio run summary files."""
from __future__ import annotations

import csv
import pathlib
from datetime import datetime
from typing import Any

from test_studio.models import CaseEntry, RunEntry


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    text = str(value or "").strip().casefold()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off", ""}:
        return False
    return default


def normalise_labels(raw: Any) -> list[str]:
    if isinstance(raw, str):
        labels: list[str] = []
        for chunk in raw.split("|"):
            for part in chunk.split(","):
                text = part.strip()
                if text:
                    labels.append(text)
        return labels

    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def fallback_timestamp(path: pathlib.Path, payload: dict[str, Any]) -> str:
    timestamp = str(payload.get("timestamp", "")).strip()
    if timestamp:
        return timestamp
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    except Exception:
        return ""


def load_case_entry(raw: dict[str, Any]) -> CaseEntry:
    f1 = safe_float(raw.get("f1"))
    failed_raw = raw.get("failed", None)
    failed = bool(failed_raw) if isinstance(failed_raw, bool) else (f1 <= 0.0)
    return CaseEntry(
        case_id=str(raw.get("case_id", "")),
        query=str(raw.get("query", "")),
        labels=normalise_labels(raw.get("labels", [])),
        f1=f1,
        precision=safe_float(raw.get("precision")),
        recall=safe_float(raw.get("recall")),
        hit_at_k=safe_float(raw.get("hit_at_k")),
        expected_docs=[str(item) for item in raw.get("expected_docs", []) if str(item)],
        predicted_docs=[str(item) for item in raw.get("predicted_docs", []) if str(item)],
        failed=failed,
    )


def load_pdf_cases(path: pathlib.Path) -> list[CaseEntry]:
    if not path.exists():
        return []

    cases: list[CaseEntry] = []
    with open(path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            labels = normalise_labels(row.get("labels", ""))
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
            cases.append(
                CaseEntry(
                    case_id=str(row.get("case_id", "")),
                    query=query,
                    labels=labels,
                    f1=safe_float(row.get("token_f1")),
                    precision=safe_float(row.get("token_precision")),
                    recall=safe_float(row.get("token_recall")),
                    hit_at_k=safe_float(row.get("paragraph_mean")),
                    expected_docs=[pathlib.Path(expected_path).name] if expected_path else [],
                    predicted_docs=observed,
                    failed=(not passed),
                )
            )
    return cases


def build_run(
    *,
    run_type: str,
    path: pathlib.Path,
    payload: dict[str, Any],
    cases: list[CaseEntry],
    cases_count: int,
    micro_f1: float,
    macro_f1: float,
    hit_at_k: float,
    map_value: float,
    mrr: float,
    ndcg: float,
    failures: int,
) -> RunEntry:
    return RunEntry(
        run_type=run_type,
        run_name=str(payload.get("run_name") or path.stem.replace(".summary", "")),
        timestamp=fallback_timestamp(path, payload),
        suite=str(payload.get("suite", "")),
        path=path,
        cases_count=cases_count,
        micro_f1=micro_f1,
        macro_f1=macro_f1,
        hit_at_k=hit_at_k,
        map_value=map_value,
        mrr=mrr,
        ndcg=ndcg,
        failure_cases=failures,
        cases=cases,
    )
