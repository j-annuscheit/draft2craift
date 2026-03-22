"""Mindmap tree construction and validation helpers."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from shared.domain.graph_codec import spec_to_markdown
from shared.domain.graph_spec import GraphNode, GraphSpec
from shared.domain.graph_validation import GraphValidationLimits, validate_graph_spec
from shared.services.agentic.graph_closure import sanitize_graph_spec

from .labels import choose_root_label, clean_label, labels_equivalent, slug, word_tokens


def build_seed_spec(*, root_label: str, outline: dict[str, Any], focus: dict[str, Any], max_top_sections: int = 6) -> GraphSpec:
    title = clean_label(str(outline.get("title", "") or root_label), min_word_letters=2, max_chars=100) or root_label
    root_id = "root"
    nodes: dict[str, GraphNode] = {root_id: GraphNode(node_id=root_id, label=root_label)}
    roots = [root_id]
    sections = list(outline.get("sections", []) or [])
    preferred = set(str(item or "") for item in list(focus.get("top_sections", []) or []))
    ordered: list[dict[str, Any]] = []
    if preferred:
        ordered.extend([row for row in sections if str(row.get("section_id", "") or "") in preferred])
        ordered.extend([row for row in sections if str(row.get("section_id", "") or "") not in preferred])
    else:
        ordered = sections
    child_ids: list[str] = []
    for index, section in enumerate(ordered[: max(1, int(max_top_sections))], 1):
        label = clean_label(section.get("label"), min_word_letters=2, max_chars=80)
        if not label:
            continue
        node_id = f"sec-{index:02d}-{slug(label)}"
        if any(labels_equivalent(label, node.label) for node in nodes.values()):
            continue
        nodes[node_id] = GraphNode(node_id=node_id, label=label)
        child_ids.append(node_id)
    nodes[root_id].children = child_ids
    return GraphSpec(kind="mindmap", title=title, nodes=nodes, roots=roots, edges=[])


def spec_stats(spec: GraphSpec) -> dict[str, int]:
    report = validate_graph_spec(
        spec,
        limits=GraphValidationLimits(
            min_nodes=0,
            max_nodes=10_000,
            max_edges=10_000,
            max_depth=1_000,
            require_single_root=False,
            allow_cycles=True,
            max_isolated_nodes=10_000,
            require_connected=False,
            min_word_letters=1,
        ),
    )
    return dict(report.stats or {})


def root_node_id(spec: GraphSpec, *, fallback: str = "root") -> str:
    return str(list(spec.roots or [fallback])[0] or fallback)


def find_node_id_by_label(spec: GraphSpec, label: str) -> str:
    want = clean_label(label, min_word_letters=2, max_chars=120)
    if not want:
        return ""
    for node_id, node in dict(spec.nodes or {}).items():
        current = clean_label(getattr(node, "label", ""), min_word_letters=2, max_chars=120)
        if current and labels_equivalent(current, want):
            return str(node_id or "")
    return ""


def child_labels(spec: GraphSpec, *, parent_id: str) -> list[str]:
    node = dict(spec.nodes or {}).get(str(parent_id or ""))
    if node is None:
        return []
    out: list[str] = []
    for child_id in list(getattr(node, "children", []) or []):
        child = dict(spec.nodes or {}).get(str(child_id or ""))
        label = clean_label(getattr(child, "label", ""), min_word_letters=2, max_chars=80) if child is not None else ""
        if label:
            out.append(label)
    return out


def ensure_single_root(spec: GraphSpec, *, root_label: str) -> GraphSpec:
    if len(list(spec.roots or [])) == 1:
        return spec
    nodes = deepcopy(dict(spec.nodes or {}))
    root_id = "root"
    if root_id in nodes:
        root_id = f"root-{slug(root_label)}"
    nodes[root_id] = GraphNode(node_id=root_id, label=choose_root_label(query=root_label, title=spec.title or root_label))
    roots = [node_id for node_id in list(spec.roots or []) if node_id in nodes and node_id != root_id]
    nodes[root_id].children = list(dict.fromkeys(roots))
    return GraphSpec(kind=spec.kind, title=spec.title, nodes=nodes, roots=[root_id], edges=[])


def ensure_connected_tree(spec: GraphSpec, *, root_label: str) -> GraphSpec:
    fixed = ensure_single_root(spec, root_label=root_label)
    root_id = root_node_id(fixed)
    nodes = deepcopy(dict(fixed.nodes or {}))
    referenced: set[str] = set()
    for node in nodes.values():
        referenced.update(str(item or "") for item in list(node.children or []) if str(item or ""))
    disconnected = [node_id for node_id in list(nodes.keys()) if node_id != root_id and node_id not in referenced]
    if disconnected:
        root_children = list(nodes[root_id].children or [])
        for node_id in disconnected:
            if node_id not in root_children:
                root_children.append(node_id)
        nodes[root_id].children = root_children
    return GraphSpec(kind=fixed.kind, title=fixed.title, nodes=nodes, roots=[root_id], edges=[])


def attach_children_to_parent(spec: GraphSpec, *, parent_id: str, children: list[dict[str, Any]]) -> GraphSpec:
    nodes = deepcopy(dict(spec.nodes or {}))
    parent = nodes.get(str(parent_id or ""))
    if parent is None:
        return spec
    existing_children = list(parent.children or [])
    existing_labels = [str(nodes.get(child_id).label or "") for child_id in existing_children if child_id in nodes]
    for child in list(children or []):
        label = clean_label(child.get("label"), min_word_letters=2, max_chars=80)
        if not label:
            continue
        if any(labels_equivalent(label, item) for item in existing_labels):
            continue
        base_id = slug(label)
        node_id = base_id
        idx = 2
        while node_id in nodes:
            node_id = f"{base_id}-{idx}"
            idx += 1
        quote = ""
        evidence_ids = list(child.get("evidence_segment_ids", []) or [])
        if evidence_ids:
            quote = ", ".join(evidence_ids[:4])
        nodes[node_id] = GraphNode(node_id=node_id, label=label, quote=quote)
        existing_children.append(node_id)
        existing_labels.append(label)
    parent.children = existing_children
    return GraphSpec(kind=spec.kind, title=spec.title, nodes=nodes, roots=list(spec.roots or []), edges=list(spec.edges or []))


def attach_nodes_to_root(spec: GraphSpec, *, nodes: list[dict[str, Any]]) -> GraphSpec:
    return attach_children_to_parent(spec, parent_id=root_node_id(spec), children=nodes)


def best_matching_node_id(spec: GraphSpec, *, text: str, fallback: str = "root") -> str:
    wanted_terms = set(word_tokens(text, min_letters=3))
    best_id = str(fallback or root_node_id(spec))
    best_score = -1
    for node_id, node in dict(spec.nodes or {}).items():
        label = clean_label(getattr(node, "label", ""), min_word_letters=2, max_chars=80)
        if not label:
            continue
        score = len(wanted_terms & set(word_tokens(label, min_letters=3)))
        if score > best_score:
            best_score = score
            best_id = str(node_id or fallback or "root")
    return best_id


def sanitize_and_validate_spec(
    spec: GraphSpec,
    *,
    policy: dict[str, Any],
    root_label: str,
    merge_similar_nodes: bool = True,
) -> tuple[GraphSpec, dict[str, Any]]:
    cleaned, cleanup_info = sanitize_graph_spec(
        spec,
        min_word_letters=max(1, int(policy.get("map_node_min_word_letters", 3) or 3)),
        merge_similar_nodes=merge_similar_nodes,
    )
    connected = ensure_connected_tree(cleaned, root_label=root_label)
    limits = GraphValidationLimits(
        min_nodes=max(0, int(policy.get("map_min_nodes", 1) or 1)),
        max_nodes=max(1, int(policy.get("map_max_nodes", 128) or 128)),
        max_edges=max(1, int(policy.get("map_max_edges", 512) or 512)),
        max_depth=max(1, int(policy.get("map_max_depth", 16) or 16)),
        require_single_root=bool(policy.get("map_require_single_root", True)),
        allow_cycles=bool(policy.get("map_allow_cycles", False)),
        max_isolated_nodes=max(0, int(policy.get("map_max_isolated_nodes", 0) or 0)),
        require_connected=bool(policy.get("map_require_connected_graph", True)),
        min_word_letters=max(1, int(policy.get("map_node_min_word_letters", 3) or 3)),
    )
    report = validate_graph_spec(connected, limits=limits)
    return connected, {
        "ok": bool(report.ok),
        "issues": [issue.to_dict() for issue in list(report.issues or [])],
        "stats": dict(report.stats or {}),
        "cleanup": {
            "removed_nodes": int(getattr(cleanup_info, "removed_nodes", 0) or 0),
            "renamed_nodes": int(getattr(cleanup_info, "renamed_nodes", 0) or 0),
            "merged_nodes": int(getattr(cleanup_info, "merged_nodes", 0) or 0),
        },
        "normalized_markdown": spec_to_markdown(connected),
        "reason": "ok" if bool(report.ok) else "validation_failed",
    }
