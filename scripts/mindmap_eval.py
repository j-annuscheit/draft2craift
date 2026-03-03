#!/usr/bin/env python3
"""MindMap/Graph renderer evaluation with include/exclude string checks."""
from __future__ import annotations

import argparse
import csv
import dataclasses
import html
import json
from pathlib import Path
import re
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any


_THIS_FILE = Path(__file__).resolve()
_PROJECT_ROOT = _THIS_FILE.parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from features.canvas.structured_graph import extract_graph_spec, render_graph_html  # noqa: E402


@dataclass
class CaseSpec:
    case_id: str
    labels: list[str]
    markdown_path: Path | None
    markdown_text: str
    must_contain: list[str]
    must_not_contain: list[str]


@dataclass
class CaseResult:
    case_id: str
    labels: list[str]
    passed: bool
    duration_ms: float
    markdown_path: str
    found_required: list[str]
    missing_required: list[str]
    found_forbidden: list[str]
    fail_reasons: list[str]


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _load_json(path: Path) -> dict[str, Any]:
    raw = json.loads(_read_text(path))
    if not isinstance(raw, dict):
        raise ValueError(f"Expected JSON object in suite: {path}")
    return raw


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_labels(raw: Any) -> list[str]:
    values: list[str] = []
    if isinstance(raw, str):
        values = [part.strip() for part in raw.split(",")]
    elif isinstance(raw, list):
        values = [str(item).strip() for item in raw]
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _parse_terms(raw: Any) -> list[str]:
    out: list[str] = []
    if isinstance(raw, str):
        for part in raw.split(","):
            token = part.strip()
            if token:
                out.append(token)
    elif isinstance(raw, list):
        for item in raw:
            token = str(item or "").strip()
            if token:
                out.append(token)
    return out


def _resolve_path(raw: str, suite_dir: Path) -> Path:
    p = Path(str(raw or ""))
    if p.is_absolute():
        return p
    return (suite_dir / p).resolve()


def _parse_case(
    raw: dict[str, Any],
    *,
    suite_dir: Path,
    defaults: dict[str, Any],
) -> CaseSpec:
    case_id = str(raw.get("id") or raw.get("case_id") or "").strip()
    if not case_id:
        raise ValueError("Each case requires id")

    markdown_text = str(raw.get("markdown_text") or "").strip()
    markdown_path: Path | None = None
    md_field = raw.get("markdown") or raw.get("path")
    if md_field:
        markdown_path = _resolve_path(str(md_field), suite_dir)
        if not markdown_path.exists():
            raise FileNotFoundError(
                f"Case '{case_id}' missing markdown file: {markdown_path}"
            )
    if markdown_path is None and not markdown_text:
        raise ValueError(
            f"Case '{case_id}' needs 'markdown' or 'markdown_text'"
        )

    must_contain = _parse_terms(raw.get("must_contain", defaults.get("must_contain", [])))
    must_not_contain = _parse_terms(
        raw.get("must_not_contain", defaults.get("must_not_contain", []))
    )
    labels = _parse_labels(raw.get("labels"))
    return CaseSpec(
        case_id=case_id,
        labels=labels,
        markdown_path=markdown_path,
        markdown_text=markdown_text,
        must_contain=must_contain,
        must_not_contain=must_not_contain,
    )


def _normalize_search_text(html_text: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", str(html_text or ""))
    plain = html.unescape(no_tags)
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain.casefold()


def _evaluate_case(case: CaseSpec, *, artifacts_dir: Path | None) -> CaseResult:
    markdown = (
        case.markdown_text
        if case.markdown_text
        else _read_text(case.markdown_path)
    )
    t0 = time.perf_counter()
    spec = extract_graph_spec(markdown)
    duration_ms = (time.perf_counter() - t0) * 1000.0

    if spec is None:
        return CaseResult(
            case_id=case.case_id,
            labels=case.labels,
            passed=False,
            duration_ms=duration_ms,
            markdown_path=(
                str(case.markdown_path) if case.markdown_path else "<inline_markdown>"
            ),
            found_required=[],
            missing_required=list(case.must_contain),
            found_forbidden=[],
            fail_reasons=["no_structured_graph_block_found"],
        )

    html_view = render_graph_html(spec, collapsed_ids=set(), focus_node_id="")
    haystack = _normalize_search_text(html_view)
    found_required: list[str] = []
    missing_required: list[str] = []
    found_forbidden: list[str] = []

    for needle in case.must_contain:
        token = str(needle or "").strip()
        if not token:
            continue
        if token.casefold() in haystack:
            found_required.append(token)
        else:
            missing_required.append(token)

    for needle in case.must_not_contain:
        token = str(needle or "").strip()
        if not token:
            continue
        if token.casefold() in haystack:
            found_forbidden.append(token)

    fail_reasons: list[str] = []
    if missing_required:
        fail_reasons.append(
            "missing_required: " + ", ".join(missing_required[:24])
        )
    if found_forbidden:
        fail_reasons.append(
            "found_forbidden: " + ", ".join(found_forbidden[:24])
        )

    if artifacts_dir is not None:
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "case": {
                "case_id": case.case_id,
                "labels": case.labels,
                "markdown_path": (
                    str(case.markdown_path) if case.markdown_path else ""
                ),
                "markdown_text": case.markdown_text,
                "must_contain": case.must_contain,
                "must_not_contain": case.must_not_contain,
            },
            "spec": {
                "kind": spec.kind,
                "title": spec.title,
                "nodes": len(spec.nodes),
                "edges": len(spec.edges),
                "roots": list(spec.roots),
            },
            "found_required": found_required,
            "missing_required": missing_required,
            "found_forbidden": found_forbidden,
            "fail_reasons": fail_reasons,
        }
        _write_json(artifacts_dir / f"{case.case_id}.json", payload)
        (artifacts_dir / f"{case.case_id}.rendered.html").write_text(
            html_view,
            encoding="utf-8",
        )

    return CaseResult(
        case_id=case.case_id,
        labels=case.labels,
        passed=not fail_reasons,
        duration_ms=duration_ms,
        markdown_path=(
            str(case.markdown_path) if case.markdown_path else "<inline_markdown>"
        ),
        found_required=found_required,
        missing_required=missing_required,
        found_forbidden=found_forbidden,
        fail_reasons=fail_reasons,
    )


def _write_cases_csv(path: Path, rows: list[CaseResult]) -> None:
    cols = [
        "case_id",
        "labels",
        "passed",
        "duration_ms",
        "found_required",
        "missing_required",
        "found_forbidden",
        "fail_reasons",
        "markdown_path",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        for row in rows:
            rec = dataclasses.asdict(row)
            rec["labels"] = ",".join(row.labels)
            rec["found_required"] = " | ".join(row.found_required)
            rec["missing_required"] = " | ".join(row.missing_required)
            rec["found_forbidden"] = " | ".join(row.found_forbidden)
            rec["fail_reasons"] = " | ".join(row.fail_reasons)
            writer.writerow({k: rec.get(k, "") for k in cols})


def _summarize(rows: list[CaseResult]) -> dict[str, Any]:
    if not rows:
        return {
            "cases": 0,
            "passed": 0,
            "failed": 0,
            "pass_rate": 0.0,
            "avg_duration_ms": 0.0,
        }
    passed = sum(1 for row in rows if row.passed)
    return {
        "cases": len(rows),
        "passed": passed,
        "failed": len(rows) - passed,
        "pass_rate": passed / len(rows),
        "avg_duration_ms": statistics.fmean(row.duration_ms for row in rows),
    }


def run_suite(args: argparse.Namespace) -> dict[str, Any]:
    suite_path = Path(args.suite).expanduser().resolve()
    if not suite_path.exists():
        raise FileNotFoundError(f"Suite file not found: {suite_path}")
    suite_dir = suite_path.parent
    suite = _load_json(suite_path)

    defaults_block = suite.get("defaults")
    defaults = defaults_block if isinstance(defaults_block, dict) else {}

    raw_cases = suite.get("cases")
    if not isinstance(raw_cases, list):
        raise ValueError("suite.cases must be a list")

    cases = [
        _parse_case(raw, suite_dir=suite_dir, defaults=defaults)
        for raw in raw_cases
        if isinstance(raw, dict)
    ]
    if not cases:
        raise ValueError("No cases in suite")

    labels_filter = _parse_labels(args.labels) if args.labels else []
    if labels_filter:
        wanted = {label.casefold() for label in labels_filter}
        cases = [
            case for case in cases
            if wanted.intersection({label.casefold() for label in case.labels})
        ]
    if args.max_cases > 0:
        cases = cases[: int(args.max_cases)]
    if not cases:
        raise ValueError("No cases selected after filters")

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    run_name = str(args.run_name or "").strip() or datetime.now().strftime(
        "mindmap_%Y%m%d_%H%M%S"
    )
    artifacts_dir = output_dir / f"{run_name}.artifacts" if args.write_artifacts else None

    started = time.perf_counter()
    rows = [
        _evaluate_case(case, artifacts_dir=artifacts_dir)
        for case in cases
    ]
    elapsed = time.perf_counter() - started
    summary = _summarize(rows)

    payload = {
        "run_name": run_name,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "suite": str(suite_path),
        "evaluation_type": "mindmap",
        "summary": {
            **summary,
            "elapsed_sec": elapsed,
        },
        "cases": [dataclasses.asdict(row) for row in rows],
    }
    _write_json(output_dir / f"{run_name}.summary.json", payload)
    _write_cases_csv(output_dir / f"{run_name}.cases.csv", rows)
    with open(output_dir / f"{run_name}.debug.jsonl", "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(dataclasses.asdict(row), ensure_ascii=False) + "\n")

    print(
        "Done",
        f"| cases={summary['cases']}",
        f"| passed={summary['passed']}",
        f"| failed={summary['failed']}",
        f"| pass_rate={summary['pass_rate']:.3f}",
        f"| elapsed={elapsed:.2f}s",
    )
    return payload


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MindMap/Graph renderer eval (contains/excludes checks)"
    )
    parser.add_argument("--suite", required=True, help="Path to suite JSON")
    parser.add_argument(
        "--output-dir",
        default="runs/mindmap_eval",
        help="Directory for run artifacts",
    )
    parser.add_argument("--run-name", default="", help="Optional run name")
    parser.add_argument("--labels", default="", help="Optional comma-separated labels filter")
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument(
        "--write-artifacts",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        run_suite(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
