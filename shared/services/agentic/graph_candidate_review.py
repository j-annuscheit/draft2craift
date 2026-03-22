"""Candidate acceptance/rejection for graph and mindmap updates."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shared.domain.graph_codec import graph_spec_signature
from shared.domain.graph_spec import GraphSpec

from .graph_closure import label_fingerprint


@dataclass(slots=True, frozen=True)
class CandidateReviewDecision:
    accept: bool
    reason: str
    compare: dict[str, Any]


def _bool(raw: Any, default: bool) -> bool:
    if isinstance(raw, bool):
        return raw
    text = str(raw or "").strip().casefold()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _int(raw: Any, default: int) -> int:
    try:
        return int(raw)
    except Exception:
        return int(default)


def _float(raw: Any, default: float) -> float:
    try:
        return float(raw)
    except Exception:
        return float(default)


def _stats(payload: dict[str, Any]) -> dict[str, int]:
    data = dict(payload.get("stats", {}) or {})
    return {
        "nodes": _int(data.get("nodes", 0), 0),
        "edges": _int(data.get("edges", 0), 0),
        "roots": _int(data.get("roots", 0), 0),
        "isolated_nodes": _int(data.get("isolated_nodes", 0), 0),
        "components": _int(data.get("components", 0), 0),
        "max_depth": _int(data.get("max_depth", 0), 0),
    }


def _grounding(payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload.get("grounding", {}) or {})
    enabled = bool(data.get("enabled", False))
    return {
        "enabled": enabled,
        "ok": bool(data.get("ok", not enabled)),
        "reason": str(data.get("reason", "grounded" if enabled else "grounding_disabled") or ""),
        "grounded_nodes": _int(data.get("grounded_nodes", 0), 0),
        "grounded_ratio": _float(data.get("grounded_ratio", 0.0), 0.0),
        "meta_like_nodes": _int(data.get("meta_like_nodes", 0), 0),
        "meta_like_ratio": _float(data.get("meta_like_ratio", 0.0), 0.0),
    }


def _root_penalty(*, roots: int, require_single_root: bool) -> int:
    if require_single_root:
        return abs(int(roots) - 1)
    return max(0, int(roots) - 1)


def _quality_vector(
    *,
    spec: GraphSpec | None,
    payload: dict[str, Any],
    require_single_root: bool,
) -> tuple[int, int, int, int, int, int, int, int]:
    stats = _stats(payload)
    return (
        1 if spec is not None else 0,
        1 if bool(payload.get("ok", False)) else 0,
        -int(stats.get("components", 0)),
        -int(stats.get("isolated_nodes", 0)),
        -_root_penalty(
            roots=int(stats.get("roots", 0)),
            require_single_root=require_single_root,
        ),
        int(stats.get("edges", 0)),
        int(stats.get("nodes", 0)),
        int(stats.get("max_depth", 0)),
    )


def _spec_label_keys(spec: GraphSpec | None) -> set[str]:
    if spec is None:
        return set()
    keys: set[str] = set()
    for node in dict(spec.nodes or {}).values():
        label = str(getattr(node, "label", "") or "").strip()
        fingerprint = " ".join(label_fingerprint(label))
        if fingerprint:
            keys.add(fingerprint)
    return keys


def _overlap_ratio(baseline_spec: GraphSpec | None, candidate_spec: GraphSpec | None) -> tuple[float, int, int]:
    base_keys = _spec_label_keys(baseline_spec)
    candidate_keys = _spec_label_keys(candidate_spec)
    if not base_keys:
        return 1.0, 0, len(candidate_keys)
    overlap = len(base_keys & candidate_keys)
    return overlap / max(1, len(base_keys)), overlap, len(base_keys)


def review_graph_candidate(
    *,
    baseline_spec: GraphSpec | None,
    baseline_payload: dict[str, Any],
    candidate_spec: GraphSpec | None,
    candidate_payload: dict[str, Any],
    candidate_meta: dict[str, Any] | None = None,
    require_single_root: bool,
) -> CandidateReviewDecision:
    meta = dict(candidate_meta or {})
    intent = str(meta.get("intent", "replace") or "replace").strip().casefold()
    min_overlap_ratio = _float(
        meta.get(
            "min_overlap_ratio",
            0.25 if intent == "closure" else (0.5 if intent == "refine" else (0.6 if intent == "expand" else 0.0)),
        ),
        0.0,
    )
    allow_invalid_improvement = _bool(
        meta.get("allow_invalid_improvement", intent == "closure"),
        intent == "closure",
    )
    skip_overlap_when_baseline_invalid = _bool(
        meta.get("skip_overlap_when_baseline_invalid", intent == "closure"),
        intent == "closure",
    )
    max_node_loss = _int(
        meta.get(
            "max_node_loss",
            9999 if intent == "closure" else (1 if intent == "refine" else 0),
        ),
        0,
    )

    base_stats = _stats(baseline_payload)
    candidate_stats = _stats(candidate_payload)
    baseline_grounding = _grounding(baseline_payload)
    candidate_grounding = _grounding(candidate_payload)
    overlap_ratio, overlap_count, overlap_base_count = _overlap_ratio(baseline_spec, candidate_spec)
    base_sig = graph_spec_signature(baseline_spec) if baseline_spec is not None else ""
    candidate_sig = graph_spec_signature(candidate_spec) if candidate_spec is not None else ""
    node_loss = int(base_stats.get("nodes", 0)) - int(candidate_stats.get("nodes", 0))
    base_vector = _quality_vector(
        spec=baseline_spec,
        payload=baseline_payload,
        require_single_root=require_single_root,
    )
    candidate_vector = _quality_vector(
        spec=candidate_spec,
        payload=candidate_payload,
        require_single_root=require_single_root,
    )
    compare = {
        "intent": intent,
        "baseline_ok": bool(baseline_payload.get("ok", False)),
        "candidate_ok": bool(candidate_payload.get("ok", False)),
        "baseline_stats": base_stats,
        "candidate_stats": candidate_stats,
        "baseline_grounding": baseline_grounding,
        "candidate_grounding": candidate_grounding,
        "overlap_ratio": round(float(overlap_ratio), 4),
        "overlap_count": int(overlap_count),
        "overlap_base_count": int(overlap_base_count),
        "node_loss": int(node_loss),
        "min_overlap_ratio": float(min_overlap_ratio),
        "max_node_loss": int(max_node_loss),
        "allow_invalid_improvement": bool(allow_invalid_improvement),
        "skip_overlap_when_baseline_invalid": bool(skip_overlap_when_baseline_invalid),
        "baseline_vector": list(base_vector),
        "candidate_vector": list(candidate_vector),
    }

    if candidate_spec is None:
        return CandidateReviewDecision(False, "candidate_parse_failed", compare)
    if bool(candidate_grounding.get("enabled", False)) and not bool(candidate_grounding.get("ok", True)):
        return CandidateReviewDecision(False, "candidate_not_grounded", compare)
    if baseline_spec is None:
        if bool(candidate_payload.get("ok", False)):
            return CandidateReviewDecision(True, "candidate_recovered_parse", compare)
        if allow_invalid_improvement and candidate_vector > base_vector:
            return CandidateReviewDecision(True, "candidate_invalid_but_better", compare)
        return CandidateReviewDecision(False, "baseline_missing_candidate_not_good_enough", compare)

    if base_sig and candidate_sig and base_sig == candidate_sig:
        return CandidateReviewDecision(False, "candidate_no_delta", compare)

    baseline_ok = bool(baseline_payload.get("ok", False))
    candidate_ok = bool(candidate_payload.get("ok", False))
    if candidate_ok and (not baseline_ok):
        return CandidateReviewDecision(True, "candidate_fixed_validation", compare)
    if baseline_ok and (not candidate_ok):
        return CandidateReviewDecision(False, "candidate_broke_validation", compare)
    if (
        (not baseline_ok)
        and (not candidate_ok)
        and allow_invalid_improvement
        and skip_overlap_when_baseline_invalid
        and candidate_vector > base_vector
    ):
        return CandidateReviewDecision(True, "candidate_invalid_but_better", compare)

    if float(overlap_ratio) < float(min_overlap_ratio):
        return CandidateReviewDecision(False, "candidate_structure_drift", compare)

    if int(node_loss) > int(max_node_loss):
        return CandidateReviewDecision(False, "candidate_too_much_content_loss", compare)

    if not baseline_ok and not candidate_ok:
        if allow_invalid_improvement and candidate_vector > base_vector:
            return CandidateReviewDecision(True, "candidate_invalid_but_better", compare)
        return CandidateReviewDecision(False, "candidate_not_better", compare)

    if intent == "expand":
        expanded = (
            int(candidate_stats.get("nodes", 0)) > int(base_stats.get("nodes", 0))
            or int(candidate_stats.get("edges", 0)) > int(base_stats.get("edges", 0))
            or int(candidate_stats.get("max_depth", 0)) > int(base_stats.get("max_depth", 0))
        )
        if expanded:
            return CandidateReviewDecision(True, "candidate_expanded", compare)
        return CandidateReviewDecision(False, "candidate_not_expanded", compare)

    if intent == "refine":
        if candidate_vector >= base_vector:
            return CandidateReviewDecision(True, "candidate_refined", compare)
        return CandidateReviewDecision(False, "candidate_refine_regression", compare)

    if intent == "closure":
        if candidate_vector > base_vector:
            return CandidateReviewDecision(True, "candidate_closure_improved", compare)
        return CandidateReviewDecision(False, "candidate_closure_not_improved", compare)

    if candidate_vector >= base_vector:
        return CandidateReviewDecision(True, "candidate_accepted", compare)
    return CandidateReviewDecision(False, "candidate_regression", compare)
