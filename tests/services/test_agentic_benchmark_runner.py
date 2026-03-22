from __future__ import annotations

from pathlib import Path

from eval.agentic_bench.runner import run_suite
from eval.agentic_bench.schema import parse_suite


def _repo_root() -> Path:
    return Path("/home/be/test_claude/canvas2")


def test_agentic_benchmark_runner_executes_variants():
    suite = parse_suite(
        {
            "schema_version": 1,
            "name": "t",
            "baseline_variant_id": "baseline",
            "variants": [
                {
                    "variant_id": "baseline",
                    "profile_by_workflow": {"factcheck_agentic": "factcheck_regex_only"},
                },
                {
                    "variant_id": "candidate",
                    "profile_by_workflow": {"factcheck_agentic": "factcheck_regex_only"},
                },
            ],
            "cases": [
                {
                    "case_id": "c1",
                    "workflow_id": "factcheck_agentic",
                    "request": {
                        "q": [["Doc-A", "Alice lebt in Berlin."]],
                        "c": "Alice lebt in Berlin.",
                        "o": {"rows": []},
                    },
                    "tools": {
                        "rag.search": {"kind": "rag_from_possible_sources"},
                        "nli.verify": {"kind": "nli_contains_hypothesis"},
                        "llm.generate": {"kind": "constant", "value": "ok"},
                    },
                    "assertions": [
                        {"path": "result.o", "op": "len_gte", "value": 1},
                    ],
                }
            ],
        }
    )
    payload = run_suite(suite, repo_root=_repo_root())
    rows = list(payload.get("rows", []) or [])
    assert len(rows) == 2
    assert all(bool(row.get("ok", False)) for row in rows)
    summary = dict(payload.get("variant_summary", {}) or {})
    assert "baseline" in summary
    assert "candidate" in summary


def test_agentic_benchmark_runner_collects_tool_call_assertions():
    suite = parse_suite(
        {
            "schema_version": 1,
            "name": "t2",
            "baseline_variant_id": "baseline",
            "variants": [
                {
                    "variant_id": "baseline",
                    "profile_by_workflow": {"canvas_agentic": "canvas_grounded_rewrite"},
                }
            ],
            "cases": [
                {
                    "case_id": "c2",
                    "workflow_id": "canvas_agentic",
                    "request": {
                        "instruction": "Kürze den Text.",
                        "selected_text": "Langer Text.",
                    },
                    "tools": {
                        "llm.generate": {"kind": "constant", "value": "Kurz."},
                        "canvas.apply": {"kind": "capture_text", "return": True},
                    },
                    "assertions": [
                        {"path": "tool_calls.canvas.apply[0].text", "op": "equals", "value": "Kurz."},
                    ],
                }
            ],
        }
    )
    payload = run_suite(suite, repo_root=_repo_root())
    rows = list(payload.get("rows", []) or [])
    assert len(rows) == 1
    row = dict(rows[0] or {})
    assert row.get("assertions_total") == 1
    assert row.get("assertions_passed") == 1
