"""Persistence helpers for feedback events and testcase registry."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

EVENTS_FILE = "feedback_events.jsonl"
TESTCASES_FILE = "test_cases.jsonl"
COUNTER_FILE = "testcase_counter.json"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def events_path(storage_dir: Path) -> Path:
    return storage_dir / EVENTS_FILE


def cases_path(storage_dir: Path) -> Path:
    return storage_dir / TESTCASES_FILE


def counter_path(storage_dir: Path) -> Path:
    return storage_dir / COUNTER_FILE


def read_events(storage_dir: Path) -> list[dict[str, Any]]:
    return _read_jsonl(events_path(storage_dir))


def write_events(storage_dir: Path, events: list[dict[str, Any]]) -> None:
    _write_jsonl(events_path(storage_dir), events)


def read_cases(storage_dir: Path) -> list[dict[str, Any]]:
    cases = _read_jsonl(cases_path(storage_dir))
    cases.sort(key=lambda row: int(row.get("case_no", 0) or 0))
    return cases


def write_cases(storage_dir: Path, cases: list[dict[str, Any]]) -> None:
    ordered = list(cases)
    ordered.sort(key=lambda row: int(row.get("case_no", 0) or 0))
    _write_jsonl(cases_path(storage_dir), ordered)


def _read_counter(storage_dir: Path) -> dict[str, Any]:
    raw = _read_json(counter_path(storage_dir))
    next_no = int(raw.get("next_case_no", 1) or 1)
    return {"next_case_no": max(1, next_no)}


def reserve_case_no(storage_dir: Path) -> int:
    data = _read_counter(storage_dir)
    case_no = int(data.get("next_case_no", 1))
    data["next_case_no"] = case_no + 1
    _write_json(counter_path(storage_dir), data)
    return case_no


def case_id_from_no(case_no: int) -> str:
    return f"tc_{int(case_no):06d}"
