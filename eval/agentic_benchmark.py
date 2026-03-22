#!/usr/bin/env python3
"""A/B benchmark runner for agentic workflow profiles."""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
import sys
from typing import Any

_THIS_FILE = Path(__file__).resolve()
_PROJECT_ROOT = _THIS_FILE.parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from eval.agentic_bench.runner import load_suite, run_suite
from eval.shared.logger import build_logger


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agentic A/B benchmark suite runner")
    parser.add_argument(
        "--suite",
        required=True,
        help="Path to benchmark suite JSON",
    )
    parser.add_argument(
        "--output-dir",
        default="runs/agentic_benchmark",
        help="Output directory for artifacts",
    )
    parser.add_argument(
        "--run-name",
        default="",
        help="Optional run name (defaults to timestamp)",
    )
    parser.add_argument(
        "--repo-root",
        default=str(_PROJECT_ROOT),
        help="Repository root containing data/workflows",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Log level (DEBUG/INFO/WARNING/ERROR)",
    )
    args = parser.parse_args(argv)

    suite_path = Path(str(args.suite or "")).expanduser().resolve()
    output_dir = Path(str(args.output_dir or "runs/agentic_benchmark")).expanduser().resolve()
    repo_root = Path(str(args.repo_root or _PROJECT_ROOT)).expanduser().resolve()
    run_name = str(args.run_name or "").strip() or f"agentic_benchmark_{datetime.now():%Y%m%d_%H%M%S}"
    run_dir = output_dir / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    logger = build_logger(
        name=f"agentic_benchmark.{run_name}",
        log_path=run_dir / f"{run_name}.log",
        level=str(args.log_level or "INFO"),
    )

    logger.info("Loading suite: %s", suite_path)
    suite = load_suite(suite_path)
    logger.info(
        "Running suite '%s' | variants=%s cases=%s",
        suite.name,
        len(suite.variants),
        len(suite.cases),
    )

    payload = run_suite(suite, repo_root=repo_root)
    payload["run"] = {
        "run_name": run_name,
        "suite_path": str(suite_path),
        "repo_root": str(repo_root),
        "output_dir": str(run_dir),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }

    summary_path = run_dir / "summary.json"
    rows_path = run_dir / "rows.jsonl"
    csv_path = run_dir / "rows.csv"
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_jsonl(rows_path, list(payload.get("rows", []) or []))
    _write_csv(csv_path, list(payload.get("rows", []) or []))

    logger.info("Wrote summary: %s", summary_path)
    logger.info("Wrote rows jsonl: %s", rows_path)
    logger.info("Wrote rows csv: %s", csv_path)
    _log_variant_summary(logger, payload)
    return 0


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    lines: list[str] = []
    for row in list(rows or []):
        lines.append(json.dumps(row, ensure_ascii=False))
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = (
        "case_id",
        "workflow_id",
        "variant_id",
        "profile_id",
        "ok",
        "elapsed_ms",
        "assertions_passed",
        "assertions_total",
        "assertions_pass_rate",
        "score",
        "errors",
    )
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(columns)
        for row in list(rows or []):
            writer.writerow(
                [
                    str(row.get("case_id", "")),
                    str(row.get("workflow_id", "")),
                    str(row.get("variant_id", "")),
                    str(row.get("profile_id", "")),
                    bool(row.get("ok", False)),
                    float(row.get("elapsed_ms", 0.0) or 0.0),
                    int(row.get("assertions_passed", 0) or 0),
                    int(row.get("assertions_total", 0) or 0),
                    float(row.get("assertions_pass_rate", 0.0) or 0.0),
                    float(row.get("score", 0.0) or 0.0),
                    "; ".join(str(x) for x in list(row.get("errors", []) or [])),
                ]
            )


def _log_variant_summary(logger, payload: dict[str, Any]) -> None:  # noqa: ANN001
    summary = dict(payload.get("variant_summary", {}) or {})
    if not summary:
        logger.warning("No variant summary available.")
        return
    logger.info("Variant summary:")
    for variant_id, row in sorted(summary.items()):
        logger.info(
            "  %s | cases=%s ok_rate=%.3f mean_score=%.3f mean_elapsed_ms=%.2f",
            variant_id,
            int(row.get("cases", 0) or 0),
            float(row.get("ok_rate", 0.0) or 0.0),
            float(row.get("mean_score", 0.0) or 0.0),
            float(row.get("mean_elapsed_ms", 0.0) or 0.0),
        )


if __name__ == "__main__":
    raise SystemExit(main())
