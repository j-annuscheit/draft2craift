"""Validation helpers for :mod:`shared.domain.graph_spec`."""
from __future__ import annotations

from dataclasses import dataclass
import re

from shared.domain.graph_spec import GraphSpec

_WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")


@dataclass(slots=True, frozen=True)
class GraphValidationLimits:
    min_nodes: int = 1
    max_nodes: int = 128
    max_edges: int = 512
    max_depth: int = 16
    require_single_root: bool = False
    allow_cycles: bool = True
    max_isolated_nodes: int = 32
    require_connected: bool = False
    min_word_letters: int = 1


@dataclass(slots=True, frozen=True)
class GraphValidationIssue:
    code: str
    message: str
    severity: str = "error"

    def to_dict(self) -> dict[str, str]:
        return {
            "code": str(self.code or ""),
            "message": str(self.message or ""),
            "severity": str(self.severity or "error"),
        }


@dataclass(slots=True)
class GraphValidationReport:
    ok: bool
    issues: list[GraphValidationIssue]
    stats: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": bool(self.ok),
            "issues": [item.to_dict() for item in list(self.issues or [])],
            "stats": dict(self.stats or {}),
        }


def validate_graph_spec(
    spec: GraphSpec,
    *,
    limits: GraphValidationLimits | None = None,
) -> GraphValidationReport:
    cfg = limits or GraphValidationLimits()
    issues: list[GraphValidationIssue] = []

    node_ids = set(spec.nodes.keys())
    roots = [str(item or "") for item in list(spec.roots or []) if str(item or "")]
    edges = list(spec.edges or [])

    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    incoming_count: dict[str, int] = {node_id: 0 for node_id in node_ids}
    incoming_pairs: set[tuple[str, str]] = set()

    min_word_letters = max(1, int(getattr(cfg, "min_word_letters", 3) or 3))
    for node_id, node in dict(spec.nodes or {}).items():
        label = str(getattr(node, "label", "") or "").strip()
        if _contains_word_like_text(label, min_letters=min_word_letters):
            continue
        issues.append(
            GraphValidationIssue(
                code="node_label_invalid",
                message=(
                    f"Node '{node_id}' has no word-like label "
                    f"(required: >= {min_word_letters} letters)."
                ),
            )
        )

    for node_id, node in dict(spec.nodes or {}).items():
        for child_id in list(getattr(node, "children", []) or []):
            child = str(child_id or "").strip()
            if not child:
                continue
            if child not in node_ids:
                issues.append(
                    GraphValidationIssue(
                        code="unknown_child_ref",
                        message=f"Node '{node_id}' references unknown child '{child}'.",
                    )
                )
                continue
            adjacency[node_id].add(child)
            pair = (str(node_id), str(child))
            if pair not in incoming_pairs:
                incoming_pairs.add(pair)
                incoming_count[child] = int(incoming_count.get(child, 0)) + 1

    for edge in edges:
        src = str(getattr(edge, "source_id", "") or "").strip()
        dst = str(getattr(edge, "target_id", "") or "").strip()
        if not src or not dst:
            issues.append(
                GraphValidationIssue(
                    code="edge_missing_endpoint",
                    message="Edge without source/target endpoint found.",
                )
            )
            continue
        if src not in node_ids or dst not in node_ids:
            issues.append(
                GraphValidationIssue(
                    code="edge_unknown_endpoint",
                    message=f"Edge '{src}->{dst}' references unknown node id.",
                )
            )
            continue
        adjacency[src].add(dst)
        pair = (str(src), str(dst))
        if pair not in incoming_pairs:
            incoming_pairs.add(pair)
            incoming_count[dst] = int(incoming_count.get(dst, 0)) + 1
        if src == dst:
            issues.append(
                GraphValidationIssue(
                    code="self_edge",
                    message=f"Self-edge '{src}->{dst}' is not allowed.",
                )
            )

    if not node_ids:
        issues.append(GraphValidationIssue(code="empty_nodes", message="Graph has no nodes."))

    if len(node_ids) < max(0, int(cfg.min_nodes)):
        issues.append(
            GraphValidationIssue(
                code="nodes_under_minimum",
                message=(
                    f"Graph contains {len(node_ids)} nodes, "
                    f"minimum required is {int(cfg.min_nodes)}."
                ),
            )
        )
    if len(node_ids) > max(1, int(cfg.max_nodes)):
        issues.append(
            GraphValidationIssue(
                code="nodes_over_limit",
                message=(
                    f"Graph contains {len(node_ids)} nodes, "
                    f"maximum allowed is {int(cfg.max_nodes)}."
                ),
            )
        )
    if len(edges) > max(1, int(cfg.max_edges)):
        issues.append(
            GraphValidationIssue(
                code="edges_over_limit",
                message=(
                    f"Graph contains {len(edges)} edges, "
                    f"maximum allowed is {int(cfg.max_edges)}."
                ),
            )
        )

    for root_id in roots:
        if root_id not in node_ids:
            issues.append(
                GraphValidationIssue(
                    code="unknown_root",
                    message=f"Root id '{root_id}' does not exist in nodes.",
                )
            )
    if not roots:
        issues.append(GraphValidationIssue(code="no_roots", message="Graph has no roots."))
    if cfg.require_single_root and len(roots) != 1:
        issues.append(
            GraphValidationIssue(
                code="invalid_root_count",
                message=f"Expected exactly 1 root, got {len(roots)}.",
            )
        )

    if cfg.require_single_root:
        multi_parent = [
            node_id
            for node_id, count in incoming_count.items()
            if int(count) > 1
        ]
        if multi_parent:
            issues.append(
                GraphValidationIssue(
                    code="multiple_parents",
                    message=(
                        "Mindmap hierarchy requires single parent per node. "
                        f"Violations: {', '.join(sorted(multi_parent)[:10])}"
                    ),
                )
            )

    if not cfg.allow_cycles and _has_cycle(adjacency):
        issues.append(
            GraphValidationIssue(
                code="cycle_detected",
                message="Hierarchy contains at least one cycle.",
            )
        )

    isolated = [
        node_id
        for node_id in sorted(node_ids)
        if not adjacency.get(node_id) and int(incoming_count.get(node_id, 0)) == 0
    ]
    if len(isolated) > max(0, int(cfg.max_isolated_nodes)):
        issues.append(
            GraphValidationIssue(
                code="too_many_isolated_nodes",
                message=(
                    f"Graph has {len(isolated)} isolated nodes, "
                    f"maximum allowed is {int(cfg.max_isolated_nodes)}."
                ),
            )
        )

    components = _component_count(adjacency, node_ids=node_ids)
    if cfg.require_connected and components > 1:
        issues.append(
            GraphValidationIssue(
                code="disconnected_graph",
                message=(
                    f"Graph has {components} disconnected components; "
                    "expected a single connected component."
                ),
            )
        )

    max_depth = _max_depth(adjacency, roots=roots)
    if max_depth > max(1, int(cfg.max_depth)):
        issues.append(
            GraphValidationIssue(
                code="depth_over_limit",
                message=(
                    f"Graph depth is {max_depth}, "
                    f"maximum allowed is {int(cfg.max_depth)}."
                ),
            )
        )

    stats = {
        "nodes": len(node_ids),
        "edges": len(edges),
        "roots": len(roots),
        "isolated_nodes": len(isolated),
        "components": int(components),
        "max_depth": int(max_depth),
    }
    return GraphValidationReport(
        ok=not issues,
        issues=issues,
        stats=stats,
    )


def _contains_word_like_text(text: str, *, min_letters: int) -> bool:
    required = max(1, int(min_letters))
    for token in _WORD_RE.findall(str(text or "")):
        if len(str(token or "")) >= required:
            return True
    return False


def _has_cycle(adjacency: dict[str, set[str]]) -> bool:
    state: dict[str, int] = {}

    def visit(node_id: str) -> bool:
        mark = int(state.get(node_id, 0))
        if mark == 1:
            return True
        if mark == 2:
            return False
        state[node_id] = 1
        for child in sorted(adjacency.get(node_id, set())):
            if visit(child):
                return True
        state[node_id] = 2
        return False

    for node_id in sorted(adjacency.keys()):
        if visit(node_id):
            return True
    return False


def _component_count(adjacency: dict[str, set[str]], *, node_ids: set[str]) -> int:
    if not node_ids:
        return 0
    undirected: dict[str, set[str]] = {
        node_id: set() for node_id in set(node_ids)
    }
    for src, targets in dict(adjacency or {}).items():
        if src not in undirected:
            undirected[src] = set()
        for dst in set(targets or set()):
            if dst not in undirected:
                undirected[dst] = set()
            undirected[src].add(dst)
            undirected[dst].add(src)

    seen: set[str] = set()
    components = 0
    for start in sorted(undirected.keys()):
        if start in seen:
            continue
        components += 1
        stack = [start]
        seen.add(start)
        while stack:
            node_id = stack.pop()
            for neighbor in sorted(undirected.get(node_id, set())):
                if neighbor in seen:
                    continue
                seen.add(neighbor)
                stack.append(neighbor)
    return int(components)


def _max_depth(adjacency: dict[str, set[str]], *, roots: list[str]) -> int:
    if not adjacency:
        return 0
    starts = [node_id for node_id in roots if node_id in adjacency]
    if not starts:
        starts = sorted(adjacency.keys())
    max_seen = 1
    stack: list[tuple[str, int, set[str]]] = [
        (node_id, 1, {node_id}) for node_id in starts
    ]
    while stack:
        node_id, depth, seen = stack.pop()
        if depth > max_seen:
            max_seen = depth
        for child in sorted(adjacency.get(node_id, set())):
            if child in seen:
                continue
            stack.append((child, depth + 1, set(seen) | {child}))
    return int(max_seen)
