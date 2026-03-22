"""Grounding and candidate-validation helpers for map expansion."""
from __future__ import annotations

import re
from typing import Any

from .labels import clean_label, contains_word_like_text, labels_equivalent, word_tokens

_META_PATTERNS = (
    "antworte", "format", "children", "nodes", "edges", "relation", "source", "target",
)


def label_grounded_in_text(label: str, text: str) -> bool:
    clean = clean_label(label, min_word_letters=2, max_chars=120)
    corpus = str(text or "")
    if not clean or not corpus.strip():
        return False
    norm_label = re.sub(r"\s+", " ", clean.casefold()).strip()
    norm_text = re.sub(r"\s+", " ", corpus.casefold())
    if len(norm_label) >= 8 and norm_label in norm_text:
        return True
    label_terms = set(word_tokens(clean, min_letters=3))
    text_terms = set(word_tokens(corpus, min_letters=3))
    return bool(label_terms and (label_terms & text_terms))


def is_meta_like_label(label: str) -> bool:
    raw = str(label or "").strip().casefold()
    if not raw:
        return True
    if not contains_word_like_text(raw, min_letters=3):
        return True
    return any(token in raw for token in _META_PATTERNS)


def validate_child_candidates(
    *,
    children: list[dict[str, Any]],
    parent_label: str,
    existing_labels: list[str],
    evidence_snippets: list[str],
    source_text: str,
    min_word_letters: int = 3,
    max_children: int = 4,
) -> dict[str, Any]:
    result = validate_node_candidates(
        nodes=children,
        parent_label=parent_label,
        existing_labels=existing_labels,
        evidence_snippets=evidence_snippets,
        source_text=source_text,
        min_word_letters=min_word_letters,
        max_nodes=max_children,
    )
    return {
        "ok": bool(result.get("ok", False)),
        "accepted_children": list(result.get("accepted_nodes", []) or []),
        "rejected_children": list(result.get("rejected_nodes", []) or []),
        "reason": str(result.get("reason", "no_grounded_children") or "no_grounded_children"),
    }


def validate_node_candidates(
    *,
    nodes: list[dict[str, Any]],
    parent_label: str = "",
    existing_labels: list[str] | None = None,
    evidence_snippets: list[str] | None = None,
    source_text: str = "",
    min_word_letters: int = 3,
    max_nodes: int = 4,
    require_grounding: bool = True,
) -> dict[str, Any]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    sibling_labels = [str(item or "") for item in list(existing_labels or [])]
    for node in list(nodes or [])[: max(1, int(max_nodes) * 2)]:
        label = clean_label(node.get("label"), min_word_letters=min_word_letters)
        reason = ""
        if not label:
            reason = "invalid_label"
        elif is_meta_like_label(label):
            reason = "meta_label"
        elif parent_label and labels_equivalent(label, parent_label):
            reason = "same_as_parent"
        elif any(labels_equivalent(label, existing) for existing in sibling_labels):
            reason = "duplicate_sibling"
        elif any(labels_equivalent(label, str(existing.get("label", "") or "")) for existing in accepted):
            reason = "duplicate_candidate"
        elif require_grounding:
            grounded = any(label_grounded_in_text(label, snippet) for snippet in list(evidence_snippets or []))
            if not grounded:
                grounded = label_grounded_in_text(label, source_text)
            if not grounded:
                reason = "not_grounded"
        row = {
            "label": label,
            "evidence_segment_ids": list(node.get("evidence_segment_ids", []) or []),
        }
        if reason:
            row["reason"] = reason
            rejected.append(row)
            continue
        accepted.append(row)
        sibling_labels.append(label)
        if len(accepted) >= max(1, int(max_nodes)):
            break
    return {
        "ok": bool(accepted),
        "accepted_nodes": accepted,
        "rejected_nodes": rejected,
        "reason": "ok" if accepted else "no_grounded_nodes",
    }
