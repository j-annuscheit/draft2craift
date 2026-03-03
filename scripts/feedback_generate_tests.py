#!/usr/bin/env python3
"""Export testcase registry into runnable suite files.

Source of truth:
  runs/feedback/test_cases.jsonl

Each row is a testcase entry with at least:
  - case_no (int, monotonic)
  - case_id (str, e.g. tc_000123)
  - suite_type (rag|pdf|glossary|factcheck|judge|llmcompare)
  - accepted (bool)
  - case (dict in evaluator-suite format)
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

_TESTCASES_FILE = "test_cases.jsonl"

SUITE_IDS: tuple[str, ...] = (
    "rag",
    "pdf",
    "glossary",
    "factcheck",
    "judge",
    "llmcompare",
)

SUITE_SUFFIX: dict[str, str] = {
    "rag": ".rag_suite.generated.json",
    "pdf": ".pdf_suite.generated.json",
    "glossary": ".glossary_suite.generated.json",
    "factcheck": ".factcheck_suite.generated.json",
    "judge": ".judge_suite.generated.json",
    "llmcompare": ".llm_compare_suite.generated.json",
}


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            raw = json.loads(text)
        except Exception:
            continue
        if isinstance(raw, dict):
            rows.append(raw)
    return rows


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _list_of_strings(raw: Any) -> list[str]:
    out: list[str] = []
    if isinstance(raw, str):
        for line in raw.splitlines():
            for item in line.split(","):
                token = item.strip()
                if token:
                    out.append(token)
    elif isinstance(raw, list):
        for item in raw:
            token = str(item or "").strip()
            if token:
                out.append(token)
    return out


def _suite_wrapper(suite_id: str, cases: list[dict[str, Any]]) -> dict[str, Any]:
    if suite_id == "rag":
        return {
            "documents": [],
            "config": {},
            "cases": cases,
        }
    if suite_id == "pdf":
        return {
            "defaults": {
                "settings": {},
                "thresholds": {},
            },
            "cases": cases,
        }
    if suite_id == "glossary":
        return {
            "defaults": {},
            "cases": cases,
        }
    if suite_id == "factcheck":
        return {
            "defaults": {
                "mode": "all",
            },
            "cases": cases,
        }
    if suite_id == "judge":
        return {
            "defaults": {},
            "cases": cases,
        }
    if suite_id == "llmcompare":
        return {
            "defaults": {},
            "cases": cases,
        }
    return {"cases": cases}


def _normalise_case_payload(entry: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    suite_id = str(entry.get("suite_type", "") or "").strip().lower()
    payload = entry.get("case")
    case_no = int(entry.get("case_no", 0) or 0)
    case_id = str(entry.get("case_id", "") or "").strip()

    out: dict[str, Any]
    if isinstance(payload, dict):
        out = json.loads(json.dumps(payload, ensure_ascii=False))
    else:
        out = {}

    if case_no > 0:
        if not case_id:
            case_id = f"tc_{case_no:06d}"
        out["id"] = case_id

        # Keep explicit case number for cross-run intersection logic.
        out.setdefault("case_no", case_no)

        labels = out.get("labels")
        if isinstance(labels, list):
            tag = f"case_no:{case_no}"
            if tag not in [str(x) for x in labels]:
                labels.append(tag)

    if suite_id == "rag":
        include_quotes = _list_of_strings(out.get("include_quotes"))
        exclude_quotes = _list_of_strings(out.get("exclude_quotes"))
        if include_quotes and not out.get("gt_contains") and not out.get("expected_contains"):
            out["expected_contains"] = include_quotes
        if exclude_quotes and not out.get("excluded_contains"):
            out["excluded_contains"] = exclude_quotes
    elif suite_id == "judge":
        winner_answer = str(out.get("answer_winner", "") or "").strip()
        loser_answer = str(out.get("answer_loser", "") or "").strip()
        if winner_answer and loser_answer:
            out["answer_a"] = winner_answer
            out["answer_b"] = loser_answer
            out["winner"] = "A"
            out.pop("answer_winner", None)
            out.pop("answer_loser", None)
        elif str(out.get("winner", "") or "").strip() == "":
            # Keep suite runnable if answer_a/answer_b exist but winner omitted.
            if str(out.get("answer_a", "") or "").strip() and str(out.get("answer_b", "") or "").strip():
                out["winner"] = "A"

    return suite_id, out


def export_from_storage(
    *,
    storage_dir: Path,
    output_dir: Path,
    run_name: str = "",
    include_unaccepted: bool = False,
    suites: list[str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    storage_dir = storage_dir.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    selected = set(SUITE_IDS if not suites else [s.strip().lower() for s in suites if s.strip()])
    selected = {s for s in selected if s in SUITE_SUFFIX}
    if not selected:
        raise ValueError("No valid suite selected")

    tc_path = storage_dir / _TESTCASES_FILE
    entries = _read_jsonl(tc_path)

    grouped: dict[str, list[dict[str, Any]]] = {sid: [] for sid in SUITE_IDS}
    total_seen = 0
    total_exported = 0

    for entry in entries:
        total_seen += 1
        accepted = bool(entry.get("accepted", False))
        if not accepted and not include_unaccepted:
            continue

        suite_id, payload = _normalise_case_payload(entry)
        if suite_id not in grouped:
            continue
        grouped[suite_id].append(payload)
        total_exported += 1

    if not run_name:
        run_name = f"testcase_{_now_stamp()}"

    written: list[str] = []
    for suite_id in SUITE_IDS:
        if suite_id not in selected:
            continue
        path = output_dir / f"{run_name}{SUITE_SUFFIX[suite_id]}"
        _write_json(path, _suite_wrapper(suite_id, grouped[suite_id]))
        written.append(str(path))

    by_suite = {sid: len(grouped[sid]) for sid in SUITE_IDS if sid in selected}
    summary = {
        "run_name": run_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "storage_dir": str(storage_dir),
        "testcases_file": str(tc_path),
        "output_dir": str(output_dir),
        "include_unaccepted": bool(include_unaccepted),
        "selected_suites": sorted(selected),
        "seen_cases": total_seen,
        "exported_cases": total_exported,
        "by_suite": by_suite,
    }
    summary_path = output_dir / f"{run_name}.summary.json"
    _write_json(summary_path, summary)
    written.insert(0, str(summary_path))
    return summary, written


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export testcase registry to suite JSON files")
    parser.add_argument(
        "--storage-dir",
        default="runs/feedback",
        help="Directory containing test_cases.jsonl (default: runs/feedback)",
    )
    parser.add_argument(
        "--output-dir",
        default="runs/feedback/generated",
        help="Directory where generated suite files are written",
    )
    parser.add_argument(
        "--run-name",
        default="",
        help="Output prefix (default: testcase_YYYYMMDD_HHMMSS)",
    )
    parser.add_argument(
        "--include-unaccepted",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Include draft/unaccepted cases as well (default: false)",
    )
    parser.add_argument(
        "--suites",
        default="",
        help="Comma-separated suite ids to export (default: all)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    suites = [part.strip() for part in str(args.suites or "").split(",") if part.strip()]
    summary, written = export_from_storage(
        storage_dir=Path(str(args.storage_dir)),
        output_dir=Path(str(args.output_dir)),
        run_name=str(args.run_name or "").strip(),
        include_unaccepted=bool(args.include_unaccepted),
        suites=suites,
    )

    print(
        "Export complete",
        f"| run_name={summary['run_name']}",
        f"| exported_cases={summary['exported_cases']}",
        f"| include_unaccepted={summary['include_unaccepted']}",
    )
    print("By suite:", ", ".join(f"{k}:{v}" for k, v in summary["by_suite"].items()))
    print("Written files:")
    for path in written:
        print(" -", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
