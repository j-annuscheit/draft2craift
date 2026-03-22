"""Execution runner for agentic A/B benchmark suites."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shared.services.agentic import AgenticWorkflowService

from .assertions import evaluate_assertions
from .mock_tools import build_tools
from .schema import CaseSpec, SuiteSpec, VariantSpec, parse_suite


def load_suite(path: Path) -> SuiteSpec:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Suite file must contain JSON object: {path}")
    return parse_suite(payload)


def run_suite(
    suite: SuiteSpec,
    *,
    repo_root: Path,
) -> dict[str, Any]:
    service = AgenticWorkflowService(repo_root=repo_root)
    rows: list[dict[str, Any]] = []

    for case in list(suite.cases or []):
        for variant in list(suite.variants or []):
            row = _run_case_variant(service=service, suite=suite, case=case, variant=variant)
            rows.append(row)

    by_variant = _summarize_variants(rows)
    comparisons = _compare_against_baseline(rows, baseline_variant_id=suite.baseline_variant_id)
    return {
        "suite": {
            "name": suite.name,
            "schema_version": suite.schema_version,
            "baseline_variant_id": suite.baseline_variant_id,
        },
        "rows": rows,
        "variant_summary": by_variant,
        "baseline_comparison": comparisons,
    }


def _run_case_variant(
    *,
    service: AgenticWorkflowService,
    suite: SuiteSpec,
    case: CaseSpec,
    variant: VariantSpec,
) -> dict[str, Any]:
    tools, recorder = build_tools(case.tools)
    profile_id = str(variant.profile_by_workflow.get(case.workflow_id, "") or "").strip()
    if not profile_id:
        raise ValueError(
            f"Variant '{variant.variant_id}' has no profile for workflow '{case.workflow_id}'."
        )

    merged_policy = _merge_dict(
        variant.policy_overrides,
        case.policy_overrides,
    )
    merged_overlays = _merge_str_list(variant.overlay_profile_ids, case.overlay_profile_ids)
    env_name = str(case.env_name or variant.env_name or "").strip()
    run_result = service.run(
        workflow_id=case.workflow_id,
        request=dict(case.request or {}),
        profile_id=profile_id,
        policy_overrides=merged_policy,
        wiring_overrides=dict(case.wiring_overrides or {}),
        overlay_profile_ids=merged_overlays,
        env_name=env_name,
        tools=tools,
    )
    tool_calls_flat = recorder.snapshot()
    tool_calls_nested = _nest_tool_calls(tool_calls_flat)
    payload_for_asserts = {
        "result": dict(run_result.result or {}),
        "state": dict(run_result.state or {}),
        "metrics": dict(run_result.metrics or {}),
        "errors": list(run_result.errors or []),
        "tool_calls": tool_calls_nested,
        "tool_calls_flat": tool_calls_flat,
    }
    checks = evaluate_assertions(payload_for_asserts, case.assertions)
    passed = sum(1 for item in checks if item.passed)
    total = len(checks)
    pass_rate = (float(passed) / float(total)) if total else 1.0
    elapsed_ms = float(run_result.metrics.get("elapsed_ms", 0.0) or 0.0)
    score = _score_row(
        ok=bool(run_result.ok),
        assertions_pass_rate=pass_rate,
        elapsed_ms=elapsed_ms,
        weights=_merge_score_weights(
            suite.score_weights,
            variant.score_weights,
            case.score_weights,
        ),
    )
    return {
        "case_id": case.case_id,
        "workflow_id": case.workflow_id,
        "variant_id": variant.variant_id,
        "profile_id": profile_id,
        "ok": bool(run_result.ok),
        "errors": list(run_result.errors or []),
        "elapsed_ms": elapsed_ms,
        "assertions_passed": int(passed),
        "assertions_total": int(total),
        "assertions_pass_rate": pass_rate,
        "score": score,
        "assertions": [item.to_dict() for item in checks],
        "metrics": dict(run_result.metrics or {}),
        "tool_calls": tool_calls_nested,
        "tool_calls_flat": tool_calls_flat,
    }


def _merge_dict(*maps: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for mapping in maps:
        out.update(dict(mapping or {}))
    return out


def _merge_str_list(*rows: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for items in rows:
        for item in list(items or []):
            text = str(item or "").strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(text)
    return out


def _merge_score_weights(*rows: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in rows:
        for key, value in dict(row or {}).items():
            try:
                out[str(key)] = float(value)
            except Exception:
                continue
    if "ok" not in out:
        out["ok"] = 1.0
    if "assertions" not in out:
        out["assertions"] = 1.0
    if "speed" not in out:
        out["speed"] = 0.0
    if "speed_ref_ms" not in out:
        out["speed_ref_ms"] = 1000.0
    return out


def _nest_tool_calls(flat_calls: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for tool_name, rows in dict(flat_calls or {}).items():
        parts = [part for part in str(tool_name or "").split(".") if part]
        if not parts:
            continue
        cur = out
        for part in parts[:-1]:
            nxt = cur.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                cur[part] = nxt
            cur = nxt
        cur[parts[-1]] = list(rows or [])
    return out


def _score_row(*, ok: bool, assertions_pass_rate: float, elapsed_ms: float, weights: dict[str, float]) -> float:
    ok_weight = float(weights.get("ok", 1.0))
    assertions_weight = float(weights.get("assertions", 1.0))
    speed_weight = float(weights.get("speed", 0.0))
    speed_ref_ms = max(1.0, float(weights.get("speed_ref_ms", 1000.0)))
    speed_score = 1.0 / (1.0 + (max(0.0, elapsed_ms) / speed_ref_ms))
    return (
        (1.0 if ok else 0.0) * ok_weight
        + float(assertions_pass_rate) * assertions_weight
        + speed_score * speed_weight
    )


def _summarize_variants(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in list(rows or []):
        grouped.setdefault(str(row.get("variant_id", "")), []).append(row)

    summary: dict[str, dict[str, Any]] = {}
    for variant_id, items in grouped.items():
        count = len(items)
        ok_count = sum(1 for row in items if bool(row.get("ok", False)))
        mean_elapsed = (
            sum(float(row.get("elapsed_ms", 0.0) or 0.0) for row in items) / float(count)
            if count
            else 0.0
        )
        mean_assert = (
            sum(float(row.get("assertions_pass_rate", 0.0) or 0.0) for row in items) / float(count)
            if count
            else 0.0
        )
        mean_score = (
            sum(float(row.get("score", 0.0) or 0.0) for row in items) / float(count)
            if count
            else 0.0
        )
        summary[variant_id] = {
            "cases": count,
            "ok_rate": (float(ok_count) / float(count)) if count else 0.0,
            "mean_elapsed_ms": mean_elapsed,
            "mean_assertions_pass_rate": mean_assert,
            "mean_score": mean_score,
            "total_score": sum(float(row.get("score", 0.0) or 0.0) for row in items),
        }
    return summary


def _compare_against_baseline(
    rows: list[dict[str, Any]],
    *,
    baseline_variant_id: str,
) -> dict[str, dict[str, int]]:
    baseline = str(baseline_variant_id or "").strip()
    by_case_variant: dict[tuple[str, str], dict[str, Any]] = {}
    variants: set[str] = set()
    cases: set[str] = set()
    for row in list(rows or []):
        case_id = str(row.get("case_id", ""))
        variant_id = str(row.get("variant_id", ""))
        by_case_variant[(case_id, variant_id)] = row
        variants.add(variant_id)
        cases.add(case_id)

    out: dict[str, dict[str, int]] = {}
    for variant_id in sorted(variants):
        if variant_id == baseline:
            continue
        wins = 0
        losses = 0
        ties = 0
        for case_id in sorted(cases):
            base_row = by_case_variant.get((case_id, baseline))
            cand_row = by_case_variant.get((case_id, variant_id))
            if base_row is None or cand_row is None:
                continue
            base_score = float(base_row.get("score", 0.0) or 0.0)
            cand_score = float(cand_row.get("score", 0.0) or 0.0)
            if cand_score > base_score:
                wins += 1
            elif cand_score < base_score:
                losses += 1
            else:
                ties += 1
        out[variant_id] = {"wins": wins, "losses": losses, "ties": ties}
    return out
