"""Schema parsing for agentic A/B benchmark suites."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AssertionSpec:
    path: str
    op: str
    value: Any = None


@dataclass(slots=True)
class CaseSpec:
    case_id: str
    workflow_id: str
    request: dict[str, Any]
    tools: dict[str, dict[str, Any]]
    assertions: list[AssertionSpec]
    policy_overrides: dict[str, Any] = field(default_factory=dict)
    wiring_overrides: dict[str, str] = field(default_factory=dict)
    overlay_profile_ids: list[str] = field(default_factory=list)
    env_name: str = ""
    score_weights: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class VariantSpec:
    variant_id: str
    profile_by_workflow: dict[str, str]
    policy_overrides: dict[str, Any] = field(default_factory=dict)
    overlay_profile_ids: list[str] = field(default_factory=list)
    env_name: str = ""
    score_weights: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class SuiteSpec:
    schema_version: int
    name: str
    baseline_variant_id: str
    score_weights: dict[str, float]
    variants: list[VariantSpec]
    cases: list[CaseSpec]


def parse_suite(raw: dict[str, Any]) -> SuiteSpec:
    data = dict(raw or {})
    variants = [_parse_variant(item) for item in list(data.get("variants", []) or [])]
    if not variants:
        raise ValueError("Benchmark suite requires at least one variant.")
    cases = [_parse_case(item) for item in list(data.get("cases", []) or [])]
    if not cases:
        raise ValueError("Benchmark suite requires at least one case.")
    baseline = str(data.get("baseline_variant_id", "") or "").strip()
    if not baseline:
        baseline = variants[0].variant_id
    return SuiteSpec(
        schema_version=int(data.get("schema_version", 1) or 1),
        name=str(data.get("name", "agentic_ab") or "agentic_ab"),
        baseline_variant_id=baseline,
        score_weights=_coerce_float_map(
            data.get("score_weights", {}),
            defaults={"ok": 1.0, "assertions": 1.0, "speed": 0.0},
        ),
        variants=variants,
        cases=cases,
    )


def _parse_variant(raw: Any) -> VariantSpec:
    if not isinstance(raw, dict):
        raise ValueError("Variant entry must be an object.")
    variant_id = str(raw.get("variant_id", "") or "").strip()
    if not variant_id:
        raise ValueError("Variant requires non-empty 'variant_id'.")
    profile_by_workflow = {
        str(key): str(value or "").strip()
        for key, value in dict(raw.get("profile_by_workflow", {}) or {}).items()
        if str(key).strip() and str(value or "").strip()
    }
    return VariantSpec(
        variant_id=variant_id,
        profile_by_workflow=profile_by_workflow,
        policy_overrides=dict(raw.get("policy_overrides", {}) or {}),
        overlay_profile_ids=[
            str(item or "").strip()
            for item in list(raw.get("overlay_profile_ids", []) or [])
            if str(item or "").strip()
        ],
        env_name=str(raw.get("env_name", "") or "").strip(),
        score_weights=_coerce_float_map(raw.get("score_weights", {}), defaults={}),
    )


def _parse_case(raw: Any) -> CaseSpec:
    if not isinstance(raw, dict):
        raise ValueError("Case entry must be an object.")
    case_id = str(raw.get("case_id", "") or "").strip()
    if not case_id:
        raise ValueError("Case requires non-empty 'case_id'.")
    workflow_id = str(raw.get("workflow_id", "") or "").strip()
    if not workflow_id:
        raise ValueError(f"Case '{case_id}' requires 'workflow_id'.")
    assertions = [_parse_assertion(item) for item in list(raw.get("assertions", []) or [])]
    return CaseSpec(
        case_id=case_id,
        workflow_id=workflow_id,
        request=dict(raw.get("request", {}) or {}),
        tools={
            str(name): dict(spec or {})
            for name, spec in dict(raw.get("tools", {}) or {}).items()
            if str(name or "").strip()
        },
        assertions=assertions,
        policy_overrides=dict(raw.get("policy_overrides", {}) or {}),
        wiring_overrides={
            str(key): str(value or "").strip()
            for key, value in dict(raw.get("wiring_overrides", {}) or {}).items()
            if str(key or "").strip() and str(value or "").strip()
        },
        overlay_profile_ids=[
            str(item or "").strip()
            for item in list(raw.get("overlay_profile_ids", []) or [])
            if str(item or "").strip()
        ],
        env_name=str(raw.get("env_name", "") or "").strip(),
        score_weights=_coerce_float_map(raw.get("score_weights", {}), defaults={}),
    )


def _parse_assertion(raw: Any) -> AssertionSpec:
    if not isinstance(raw, dict):
        raise ValueError("Assertion entry must be an object.")
    path = str(raw.get("path", "") or "").strip()
    op = str(raw.get("op", "") or "").strip()
    if not path or not op:
        raise ValueError("Assertion requires non-empty 'path' and 'op'.")
    return AssertionSpec(
        path=path,
        op=op,
        value=raw.get("value"),
    )


def _coerce_float_map(raw: object, *, defaults: dict[str, float]) -> dict[str, float]:
    out = dict(defaults or {})
    if not isinstance(raw, dict):
        return out
    for key, value in raw.items():
        name = str(key or "").strip()
        if not name:
            continue
        try:
            out[name] = float(value)
        except Exception:
            continue
    return out
