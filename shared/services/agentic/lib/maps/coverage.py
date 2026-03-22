"""Coverage and frontier-selection helpers for incremental mindmaps."""
from __future__ import annotations

from collections import Counter
from typing import Any

from shared.domain.graph_spec import GraphSpec

from .grounding import label_grounded_in_text
from .labels import clean_label, labels_equivalent, slug, word_tokens


def node_depths(spec: GraphSpec) -> dict[str, int]:
    depths: dict[str, int] = {}
    stack = [(str(root or ""), 1) for root in list(spec.roots or [])]
    while stack:
        node_id, depth = stack.pop()
        if not node_id or node_id in depths:
            continue
        depths[node_id] = depth
        node = dict(spec.nodes or {}).get(node_id)
        if node is None:
            continue
        for child_id in reversed(list(getattr(node, "children", []) or [])):
            stack.append((str(child_id or ""), depth + 1))
    return depths


def select_frontier_node(
    *,
    spec: GraphSpec,
    query: str,
    target_depth: int,
    frontier_visits: dict[str, int] | None = None,
    max_frontier_visits_per_node: int = 2,
    max_children_per_node: int = 5,
) -> dict[str, Any]:
    depths = node_depths(spec)
    visits = {str(key): int(value or 0) for key, value in dict(frontier_visits or {}).items()}
    query_terms = set(word_tokens(query, min_letters=3))
    ranked: list[tuple[int, str]] = []
    for node_id, node in dict(spec.nodes or {}).items():
        label = clean_label(getattr(node, "label", ""), min_word_letters=2, max_chars=80)
        if not label:
            continue
        depth = int(depths.get(node_id, 1) or 1)
        child_count = len(list(getattr(node, "children", []) or []))
        visit_count = int(visits.get(node_id, 0) or 0)
        if depth >= max(1, int(target_depth or 1)):
            continue
        if visit_count >= max(1, int(max_frontier_visits_per_node)):
            continue
        if child_count >= max(1, int(max_children_per_node)):
            continue
        overlap = len(query_terms & set(word_tokens(label, min_letters=3)))
        score = (target_depth - depth) * 4 + max(0, 3 - child_count) * 2 + overlap * 3 - visit_count * 4
        ranked.append((score, str(node_id)))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    if not ranked:
        return {"selected": False, "reason": "no_frontier"}
    node_id = ranked[0][1]
    node = dict(spec.nodes or {}).get(node_id)
    return {
        "selected": True,
        "node_id": node_id,
        "label": str(getattr(node, "label", "") or ""),
        "depth": int(depths.get(node_id, 1) or 1),
        "reason": "frontier_selected",
    }


def collect_frontier_evidence(
    *,
    frontier_label: str,
    query: str,
    segments: list[dict[str, Any]],
    preferred_segment_ids: list[str] | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    preferred = set(str(item or "") for item in list(preferred_segment_ids or []) if str(item or ""))
    terms = set(word_tokens(frontier_label, min_letters=3)) | set(word_tokens(query, min_letters=3))
    scored: list[tuple[int, str, str]] = []
    for segment in list(segments or []):
        seg_id = str(segment.get("segment_id", "") or "")
        text = str(segment.get("text", "") or "")
        overlap = len(terms & set(word_tokens(text, min_letters=3)))
        if seg_id in preferred:
            overlap += 3
        if overlap <= 0:
            continue
        scored.append((overlap, seg_id, text))
    scored.sort(key=lambda item: (-item[0], item[1]))
    rows = scored[: max(1, int(limit))]
    return {
        "segment_ids": [row[1] for row in rows],
        "snippets": [row[2] for row in rows],
        "reason": "ok" if rows else "no_evidence",
    }


def extract_local_candidates(
    *,
    snippets: list[str],
    parent_label: str,
    existing_labels: list[str],
    limit: int = 8,
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    for snippet in list(snippets or []):
        for token in word_tokens(snippet, min_letters=4):
            counts[token] += 1
    rows: list[dict[str, Any]] = []
    seen: list[str] = []
    for token, _freq in counts.most_common(max(1, int(limit) * 2)):
        label = clean_label(token, min_word_letters=4, max_chars=50)
        if not label:
            continue
        if labels_equivalent(label, parent_label):
            continue
        if any(labels_equivalent(label, existing) for existing in list(existing_labels or [])):
            continue
        if any(labels_equivalent(label, existing) for existing in seen):
            continue
        seen.append(label)
        rows.append({"label": label})
        if len(rows) >= max(1, int(limit)):
            break
    return {"candidate_terms": rows}


def extract_seed_concepts(
    *,
    segments: list[dict[str, Any]],
    top_segment_ids: list[str],
    limit: int = 12,
) -> dict[str, Any]:
    preferred = set(str(item or "") for item in list(top_segment_ids or []) if str(item or ""))
    counts: Counter[str] = Counter()
    for segment in list(segments or []):
        seg_id = str(segment.get("segment_id", "") or "")
        if preferred and seg_id not in preferred:
            continue
        text = str(segment.get("text", "") or "")
        for token in word_tokens(text, min_letters=4):
            counts[token] += 1
    concepts: list[dict[str, Any]] = []
    seen: list[str] = []
    for token, _freq in counts.most_common(max(1, int(limit) * 3)):
        label = clean_label(token, min_word_letters=4, max_chars=60)
        if not label:
            continue
        if any(labels_equivalent(label, existing) for existing in seen):
            continue
        seen.append(label)
        concepts.append({"label": label})
        if len(concepts) >= max(1, int(limit)):
            break
    return {"concepts": concepts, "reason": "ok" if concepts else "no_concepts"}


def detect_coverage_gaps(
    *,
    spec: GraphSpec,
    segments: list[dict[str, Any]],
    top_segment_ids: list[str],
    covered_segment_ids: list[str],
    max_gaps: int = 4,
) -> dict[str, Any]:
    segment_by_id = {
        str(row.get("segment_id", "") or ""): str(row.get("text", "") or "")
        for row in list(segments or [])
        if str(row.get("segment_id", "") or "")
    }
    covered = set(str(item or "") for item in list(covered_segment_ids or []) if str(item or ""))
    focus_ids = [str(item or "") for item in list(top_segment_ids or []) if str(item or "")]
    root_id = str(list(spec.roots or ["root"])[0] or "root")
    labels = [str(getattr(node, "label", "") or "") for node in dict(spec.nodes or {}).values()]
    gaps: list[dict[str, Any]] = []
    for seg_id in focus_ids:
        if seg_id in covered:
            continue
        text = segment_by_id.get(seg_id, "")
        if not text:
            continue
        if any(label_grounded_in_text(label, text) for label in labels if label):
            continue
        parent_id, parent_label = _choose_anchor_node(spec, text=text, fallback=root_id)
        label = _gap_label_from_text(text, fallback=f"Luecke {len(gaps) + 1}")
        gaps.append(
            {
                "gap_id": f"gap-{len(gaps) + 1:02d}-{slug(label)}",
                "gap_label": label,
                "segment_ids": [seg_id],
                "snippets": [text],
                "parent_id": parent_id,
                "parent_label": parent_label,
                "reason": "uncovered_focus_segment",
            }
        )
        if len(gaps) >= max(1, int(max_gaps)):
            break
    return {"gaps": gaps, "found": bool(gaps), "reason": "ok" if gaps else "no_gaps"}


def select_gap_target(
    *,
    gaps: list[dict[str, Any]],
    gap_round: int,
    max_gap_rounds: int,
) -> dict[str, Any]:
    if gap_round >= max(0, int(max_gap_rounds)):
        return {"selected": False, "reason": "max_gap_rounds_reached"}
    rows = list(gaps or [])
    if not rows:
        return {"selected": False, "reason": "no_gaps"}
    chosen = dict(rows[0] or {})
    chosen["selected"] = True
    chosen["reason"] = str(chosen.get("reason", "gap_selected") or "gap_selected")
    return chosen


def update_coverage(
    *,
    coverage: dict[str, Any],
    evidence_segment_ids: list[str],
    committed: bool,
    total_segments: int = 0,
) -> dict[str, Any]:
    covered = list(dict.fromkeys([str(item or "") for item in list(coverage.get("covered_segment_ids", []) or []) if str(item or "")]))
    if committed:
        for seg_id in list(evidence_segment_ids or []):
            clean = str(seg_id or "").strip()
            if clean and clean not in covered:
                covered.append(clean)
    base_total = int(coverage.get("total_segments", 0) or 0)
    resolved_total = max(base_total, int(total_segments or 0), len(covered), 1)
    return {
        "covered_segment_ids": covered,
        "coverage_ratio": round(len(covered) / resolved_total, 4),
        "total_segments": resolved_total,
    }


def _gap_label_from_text(text: str, *, fallback: str) -> str:
    first_line = str(text or "").strip().splitlines()[0] if str(text or "").strip() else ""
    first_sentence = first_line.split(".", 1)[0]
    label = clean_label(first_sentence, min_word_letters=2, max_chars=72)
    if label:
        return label
    tokens = word_tokens(text, min_letters=4)
    candidate = " ".join(tokens[:4]).strip()
    label = clean_label(candidate, min_word_letters=2, max_chars=72)
    return label or str(fallback or "Luecke")


def _choose_anchor_node(spec: GraphSpec, *, text: str, fallback: str) -> tuple[str, str]:
    text_terms = set(word_tokens(text, min_letters=3))
    best_id = str(fallback or "root")
    best_label = str(getattr(dict(spec.nodes or {}).get(best_id), "label", "") or "")
    best_score = -1
    for node_id, node in dict(spec.nodes or {}).items():
        label = clean_label(getattr(node, "label", ""), min_word_letters=2, max_chars=80)
        if not label:
            continue
        score = len(text_terms & set(word_tokens(label, min_letters=3)))
        if score > best_score:
            best_score = score
            best_id = str(node_id or fallback or "root")
            best_label = label
    return best_id, best_label
